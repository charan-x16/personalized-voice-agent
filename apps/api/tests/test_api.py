from __future__ import annotations

import asyncio
import base64
import json
import sqlite3
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sarvam_conv_ai_sdk import AudioEncoding, MsgStatus, Role, ServerAudioChunkMsg
from sarvam_conv_ai_sdk.messages.events import ServerInteractionConnectedEvent
from sarvam_conv_ai_sdk.messages.text import ServerTranscriptMsg
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from starlette.websockets import WebSocketDisconnect
from svix.webhooks import Webhook

from alembic import command
from svara_api.agent_configuration import (
    FALLBACK_AGENT_OPENING_MESSAGE,
    MAX_RUNTIME_OPENING_MESSAGE_LENGTH,
    is_supported_opening_message_template,
    render_opening_message,
)
from svara_api.config import Settings
from svara_api.database import Database, get_db
from svara_api.domains.voice import router as voice_routes
from svara_api.integrations.clerk.invitations import (
    AccessInvitation,
    InvitationProviderError,
)
from svara_api.integrations.clerk.outbox import process_ready_invitation_jobs
from svara_api.integrations.sarvam.provider import (
    SarvamVoiceProvider,
    VoiceProviderSession,
    VoiceProviderTerminationError,
)
from svara_api.main import create_app
from svara_api.models import Base, VoiceSession, new_id
from svara_api.schemas import RuntimeAgentConfiguration
from svara_api.security import (
    application_email_candidates,
    hash_conversation_ref,
    verify_clerk_session,
)
from svara_api.seed import (
    DEMO_ADMIN_EMAIL,
    DEMO_ADMIN_USER_ID,
    DEMO_CUSTOMER_ID,
    DEMO_USER_ID,
)

from .conftest import (
    TEST_CONVERSATION_REF,
    TEST_TOOL_SECRET,
    ApiHarness,
    settings_for_database,
)


def _login(client: TestClient, email: str = "rahul@example.com") -> str:
    response = client.post("/v1/auth/demo-login", json={"email": email})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["token_type"] == "bearer"
    return str(payload["access_token"])


class StubInvitationProvider:
    def __init__(self, *, fail_create: bool = False, fail_revoke: bool = False) -> None:
        self.fail_create = fail_create
        self.fail_revoke = fail_revoke
        self.calls: list[tuple[str, str]] = []
        self.invitation_number = 0

    async def create_invitation(self, *, email: str) -> AccessInvitation:
        self.calls.append(("create", email))
        if self.fail_create:
            raise InvitationProviderError(retry_after_seconds=17)
        self.invitation_number += 1
        now = datetime.now(UTC)
        return AccessInvitation(
            invitation_id=f"inv_test_{self.invitation_number}",
            sent_at=now,
            expires_at=now + timedelta(days=30),
        )

    async def find_pending_invitation(self, *, email: str) -> AccessInvitation | None:
        return None

    async def revoke_invitation(self, *, invitation_id: str) -> None:
        self.calls.append(("revoke", invitation_id))
        if self.fail_revoke:
            raise InvitationProviderError(retry_after_seconds=23)


def _create_session(client: TestClient, token: str, **body: Any) -> dict[str, Any]:
    response = client.post(
        "/v1/voice/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def _create_preview_session(
    client: TestClient,
    token: str,
    customer_id: str = DEMO_CUSTOMER_ID,
    **body: Any,
) -> dict[str, Any]:
    response = client.post(
        f"/v1/voice/customers/{customer_id}/preview-sessions",
        headers={"Authorization": f"Bearer {token}"},
        json=body,
    )
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def _tool_headers(key: str = TEST_TOOL_SECRET) -> dict[str, str]:
    return {"X-Voice-Tool-Key": key}


def _mock_clerk_identity(
    monkeypatch: pytest.MonkeyPatch,
    *,
    subject: str = "user_clerk_test_123",
    email: str,
) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []

    def verify_clerk_session(
        _request: object,
        *,
        settings: Settings,
    ) -> str:
        calls.append(
            {
                "operation": "verify",
                "authorized_parties": settings.cors_origins,
            }
        )
        return subject

    async def fetch_clerk_primary_email(
        received_subject: str,
        *,
        settings: Settings,
    ) -> str:
        calls.append(
            {
                "operation": "fetch-email",
                "subject": received_subject,
                "has_secret": bool(settings.clerk_secret_key),
            }
        )
        return email.strip().casefold()

    monkeypatch.setattr("svara_api.security.verify_clerk_session", verify_clerk_session)
    monkeypatch.setattr(
        "svara_api.security.fetch_clerk_primary_email",
        fetch_clerk_primary_email,
    )
    return calls


def _signed_webhook_headers(*, secret: str, message_id: str, body: str) -> dict[str, str]:
    timestamp = datetime.now(UTC)
    return {
        "Content-Type": "application/json",
        "svix-id": message_id,
        "svix-timestamp": str(int(timestamp.timestamp())),
        "svix-signature": Webhook(secret).sign(message_id, timestamp, body),
    }


def _query_one(
    database_path: Path,
    statement: str,
    parameters: tuple[object, ...] = (),
) -> tuple[Any, ...]:
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(statement, parameters).fetchone()
    assert row is not None
    return row


def _count(database_path: Path, table: str) -> int:
    statements = {
        "admin_audit_events": "SELECT COUNT(*) FROM admin_audit_events",
        "conversation_outcomes": "SELECT COUNT(*) FROM conversation_outcomes",
        "customer_agent_configurations": "SELECT COUNT(*) FROM customer_agent_configurations",
        "customer_profile_states": "SELECT COUNT(*) FROM customer_profile_states",
        "voice_sessions": "SELECT COUNT(*) FROM voice_sessions",
    }
    assert table in statements
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(statements[table]).fetchone()
    assert row is not None
    return int(row[0])


def _patch_with_forced_audit_insert_failure(
    api: ApiHarness,
    *,
    endpoint: str,
    token: str,
    payload: dict[str, object],
) -> Any:
    audit_insert_attempted = False

    def fail_audit_insert(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal audit_insert_attempted
        if "insert into admin_audit_events" not in statement.casefold():
            return
        audit_insert_attempted = True
        raise SQLAlchemyError("simulated audit insert failure")

    sync_engine = api.client.app.state.database.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", fail_audit_insert)
    try:
        response = api.client.patch(
            endpoint,
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
    finally:
        event.remove(sync_engine, "before_cursor_execute", fail_audit_insert)

    assert audit_insert_attempted is True
    return response


class _CompletingDuringBootstrapProvider:
    name = "race-test"

    def __init__(self, database: Database) -> None:
        self.database = database
        self.agent_variables: dict[str, str] | None = None

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        self.agent_variables = dict(agent_variables)
        async with self.database.session_factory() as database_session:
            voice_session = await database_session.get(VoiceSession, session_id)
            assert voice_session is not None
            voice_session.status = "completed"
            voice_session.active_slot = None
            voice_session.ended_at = datetime.now(UTC)
            await database_session.commit()

        return VoiceProviderSession(
            provider_session_id="provider-race-session",
            transport="mock",
            expires_at=expires_at,
        )

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        del provider_session_id, idempotency_key


class _ControllableTerminationProvider:
    name = "mock"

    def __init__(self) -> None:
        self.fail_termination = False
        self.termination_calls: list[tuple[str, str]] = []

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        del session_id, language, agent_variables
        return VoiceProviderSession(
            provider_session_id="provider-cancellable-session",
            transport="mock",
            expires_at=expires_at,
        )

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        self.termination_calls.append((provider_session_id, idempotency_key))
        if self.fail_termination:
            raise VoiceProviderTerminationError(
                "The provider has not confirmed that the voice session stopped.",
                ambiguous=True,
                retry_after_seconds=7,
            )


class _CancellingDuringBootstrapProvider(_ControllableTerminationProvider):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        del language, agent_variables
        async with self.database.session_factory() as database_session:
            voice_session = await database_session.get(VoiceSession, session_id)
            assert voice_session is not None
            voice_session.status = "cancelling"
            await database_session.commit()

        return VoiceProviderSession(
            provider_session_id="provider-create-cancel-race",
            transport="mock",
            expires_at=expires_at,
        )


class _UnexpectedBootstrapFailureProvider:
    name = "mock"

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        del session_id, language, expires_at, agent_variables
        raise TimeoutError("simulated timeout after the bootstrap request was sent")

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        del provider_session_id, idempotency_key
        raise AssertionError("an unavailable provider handle cannot be terminated")


class _SlowBootstrapProvider(_ControllableTerminationProvider):
    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        del session_id, language, expires_at, agent_variables
        return VoiceProviderSession(
            provider_session_id="provider-slow-bootstrap-session",
            transport="mock",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )


class _ExpiredAndReclaimedDuringBootstrapProvider(_ControllableTerminationProvider):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.original_session_id: str | None = None
        self.replacement_session_id: str | None = None

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        del agent_variables
        self.original_session_id = session_id
        async with self.database.session_factory() as database_session:
            original = await database_session.get(VoiceSession, session_id)
            assert original is not None
            original.status = "expired"
            original.active_slot = None
            await database_session.commit()

            self.replacement_session_id = new_id()
            database_session.add(
                VoiceSession(
                    id=self.replacement_session_id,
                    tenant_id=original.tenant_id,
                    customer_id=original.customer_id,
                    provider=self.name,
                    provider_session_id="provider-replacement-session",
                    conversation_ref_hash=hash_conversation_ref(
                        "cvr_replacement-reference-0123456789"
                    ),
                    status="ready",
                    active_slot=1,
                    language=language,
                    started_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(minutes=15),
                )
            )
            await database_session.commit()

        return VoiceProviderSession(
            provider_session_id="provider-expired-bootstrap-session",
            transport="mock",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )


class _ExpiringDuringTerminationProvider(_ControllableTerminationProvider):
    def __init__(self, database: Database) -> None:
        super().__init__()
        self.database = database
        self.expired_once = False

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        self.termination_calls.append((provider_session_id, idempotency_key))
        if self.expired_once:
            return
        self.expired_once = True

        async with self.database.session_factory() as database_session:
            original = await database_session.get(VoiceSession, idempotency_key)
            assert original is not None
            original.status = "expired"
            original.active_slot = None
            await database_session.commit()

            database_session.add(
                VoiceSession(
                    id=new_id(),
                    tenant_id=original.tenant_id,
                    customer_id=original.customer_id,
                    provider=self.name,
                    provider_session_id="provider-termination-race-replacement",
                    conversation_ref_hash=hash_conversation_ref(
                        "cvr_termination-race-replacement-0123456789"
                    ),
                    status="ready",
                    active_slot=1,
                    language=original.language,
                    started_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(minutes=15),
                )
            )
            await database_session.commit()

        raise VoiceProviderTerminationError(
            "The provider has not confirmed that the voice session stopped.",
            ambiguous=True,
            retry_after_seconds=7,
        )


def test_health_reports_ok(api: ApiHarness) -> None:
    response = api.client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert api.client.app.state.database.engine.sync_engine.hide_parameters is True


def test_declared_oversized_request_body_is_rejected(api: ApiHarness) -> None:
    response = api.client.post(
        "/v1/auth/demo-login",
        content=b"{}",
        headers={
            "Content-Length": str(api.settings.max_request_body_bytes + 1),
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Request body too large"}


def test_streamed_oversized_request_body_is_rejected(api: ApiHarness) -> None:
    def oversized_chunks() -> Iterator[bytes]:
        yield b'{"email":"'
        yield b"x" * api.settings.max_request_body_bytes
        yield b'"}'

    response = api.client.post(
        "/v1/auth/demo-login",
        content=oversized_chunks(),
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Request body too large"}


def test_demo_login_is_normalized_and_returns_short_lived_bearer(api: ApiHarness) -> None:
    response = api.client.post(
        "/v1/auth/demo-login",
        json={"email": "  RAHUL@EXAMPLE.COM  "},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["expires_in"] == api.settings.session_ttl_minutes * 60
    assert isinstance(payload["access_token"], str)
    assert len(payload["access_token"]) > 40
    assert response.headers["cache-control"] == "no-store"


def test_demo_login_rejects_unknown_user(api: ApiHarness) -> None:
    response = api.client.post(
        "/v1/auth/demo-login",
        json={"email": "unknown@example.com"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_clerk_bearer_links_and_resolves_active_application_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "clerk-auth.db"
    settings = settings_for_database(
        database_path,
        enable_demo_auth=False,
        clerk_secret_key="sk_test_not-a-real-secret",
    )
    calls = _mock_clerk_identity(
        monkeypatch,
        email="RAHUL+CLERK_TEST_001@EXAMPLE.COM",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        first_response = client.get(
            "/v1/me",
            headers={"Authorization": "Bearer clerk-session-token"},
        )
        second_response = client.get(
            "/v1/me",
            headers={"Authorization": "Bearer clerk-session-token"},
        )

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    assert first_response.json()["email"] == "rahul@example.com"
    assert first_response.json()["role"] == "customer"
    assert _query_one(
        database_path,
        "SELECT clerk_user_id, invitation_status, invitation_accepted_at IS NOT NULL "
        "FROM users WHERE lower(email) = ?",
        ("rahul@example.com",),
    ) == ("user_clerk_test_123", "accepted", 1)
    assert calls == [
        {
            "operation": "verify",
            "authorized_parties": ["http://testserver"],
        },
        {
            "operation": "fetch-email",
            "subject": "user_clerk_test_123",
            "has_secret": True,
        },
        {
            "operation": "verify",
            "authorized_parties": ["http://testserver"],
        },
    ]


def test_clerk_verifier_accepts_only_session_tokens_from_configured_parties(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = settings_for_database(
        tmp_path / "clerk-verifier.db",
        enable_demo_auth=False,
        clerk_secret_key="sk_test_not-a-real-secret",
        clerk_jwt_key="test-public-key",
        frontend_origins="https://voice.example,https://admin.example",
    )
    captured: dict[str, object] = {}

    def authenticate(request: Request, options: object) -> object:
        captured.update({"request": request, "options": options})
        return SimpleNamespace(
            is_signed_in=True,
            payload={"sub": "user_clerk_test_123"},
        )

    monkeypatch.setattr("svara_api.security.authenticate_request", authenticate)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/me",
            "headers": [(b"authorization", b"Bearer token")],
        }
    )

    assert verify_clerk_session(request, settings=settings) == "user_clerk_test_123"
    options = captured["options"]
    assert options.authorized_parties == ["https://voice.example", "https://admin.example"]
    assert options.accepts_token == ["session_token"]
    assert options.secret_key == "sk_test_not-a-real-secret"
    assert options.jwt_key == "test-public-key"


def test_clerk_test_email_aliases_are_disabled_in_production(tmp_path: Path) -> None:
    development = settings_for_database(tmp_path / "development.db")
    production = development.model_copy(update={"app_env": "production"})
    email = "rahul+clerk_test_001@example.com"

    assert application_email_candidates(email, settings=development) == (
        email,
        "rahul@example.com",
    )
    assert application_email_candidates(email, settings=production) == (email,)


def test_clerk_bearer_rejects_unlinked_email(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "clerk-unlinked-auth.db"
    settings = settings_for_database(
        database_path,
        enable_demo_auth=False,
        clerk_secret_key="sk_test_not-a-real-secret",
    )
    _mock_clerk_identity(monkeypatch, email="unknown+clerk_test@example.com")
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.get(
            "/v1/me",
            headers={"Authorization": "Bearer clerk-session-token"},
        )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_clerk_webhook_is_verified_idempotent_and_reconciles_user_lifecycle(
    tmp_path: Path,
) -> None:
    secret = "whsec_" + base64.b64encode(b"svara-test-webhook-signing-key-32").decode()
    database_path = tmp_path / "clerk-webhook.sqlite3"
    settings = settings_for_database(
        database_path,
        clerk_webhook_signing_secret=secret,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        provider = StubInvitationProvider()
        client.app.state.invitation_provider = provider
        admin_token = _login(client, DEMO_ADMIN_EMAIL)
        created = client.post(
            "/v1/customers",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"full_name": "Webhook User", "email": "webhook@example.com"},
        )
        assert created.status_code == 201, created.text

        event = {
            "data": {
                "id": "user_webhook_123",
                "primary_email_address_id": "idn_primary",
                "email_addresses": [
                    {
                        "id": "idn_primary",
                        "email_address": "webhook@example.com",
                        "verification": {"status": "verified"},
                    }
                ],
                "banned": False,
                "locked": False,
                "deprovisioned": False,
            },
            "object": "event",
            "timestamp": int(datetime.now(UTC).timestamp() * 1_000),
            "type": "user.created",
        }
        body = json.dumps(event, separators=(",", ":"))
        headers = _signed_webhook_headers(
            secret=secret,
            message_id="msg_user_created_123",
            body=body,
        )

        invalid = client.post(
            "/v1/webhooks/clerk",
            content=body,
            headers={**headers, "svix-signature": "v1,invalid"},
        )
        assert invalid.status_code == 400

        first = client.post("/v1/webhooks/clerk", content=body, headers=headers)
        duplicate = client.post("/v1/webhooks/clerk", content=body, headers=headers)
        assert first.status_code == 200, first.text
        assert first.json() == {"received": True, "duplicate": False, "status": "processed"}
        assert duplicate.status_code == 200
        assert duplicate.json()["duplicate"] is True
        assert _query_one(
            database_path,
            "SELECT clerk_user_id, invitation_status, is_active FROM users WHERE email = ?",
            ("webhook@example.com",),
        ) == ("user_webhook_123", "accepted", 1)

        deleted_event = {
            "data": {"id": "user_webhook_123", "deleted": True},
            "object": "event",
            "timestamp": event["timestamp"] + 1_000,
            "type": "user.deleted",
        }
        deleted_body = json.dumps(deleted_event, separators=(",", ":"))
        deleted = client.post(
            "/v1/webhooks/clerk",
            content=deleted_body,
            headers=_signed_webhook_headers(
                secret=secret,
                message_id="msg_user_deleted_123",
                body=deleted_body,
            ),
        )
        assert deleted.status_code == 200, deleted.text
        assert _query_one(
            database_path,
            "SELECT clerk_user_id, invitation_status, is_active FROM users WHERE email = ?",
            ("webhook@example.com",),
        ) == (None, "revoked", 0)
        assert _query_one(
            database_path,
            "SELECT COUNT(*) FROM clerk_webhook_events",
        ) == (2,)


def test_webhook_linked_access_supersedes_a_queued_invitation_retry(tmp_path: Path) -> None:
    secret = "whsec_" + base64.b64encode(b"svara-test-webhook-linked-key-32-bytes").decode()
    database_path = tmp_path / "clerk-webhook-supersedes-outbox.sqlite3"
    settings = settings_for_database(
        database_path,
        clerk_webhook_signing_secret=secret,
        clerk_outbox_retry_base_seconds=1,
        clerk_outbox_retry_max_seconds=1,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        provider = StubInvitationProvider(fail_create=True)
        client.app.state.invitation_provider = provider
        admin_token = _login(client, DEMO_ADMIN_EMAIL)
        created = client.post(
            "/v1/customers",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"full_name": "Linked User", "email": "linked@example.com"},
        )
        assert created.status_code == 201
        assert created.json()["access"]["status"] == "queued"

        event = {
            "data": {
                "id": "user_linked_123",
                "primary_email_address_id": "idn_linked_primary",
                "email_addresses": [
                    {
                        "id": "idn_linked_primary",
                        "email_address": "linked@example.com",
                        "verification": {"status": "verified"},
                    }
                ],
                "banned": False,
                "locked": False,
                "deprovisioned": False,
            },
            "object": "event",
            "timestamp": int(datetime.now(UTC).timestamp() * 1_000),
            "type": "user.created",
        }
        body = json.dumps(event, separators=(",", ":"))
        linked = client.post(
            "/v1/webhooks/clerk",
            content=body,
            headers=_signed_webhook_headers(
                secret=secret,
                message_id="msg_linked_before_retry",
                body=body,
            ),
        )
        assert linked.status_code == 200

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE clerk_invitation_outbox SET available_at = ? WHERE status = 'pending'",
                ("2000-01-01 00:00:00+00:00",),
            )
            connection.commit()
        provider.fail_create = False
        results = asyncio.run(
            process_ready_invitation_jobs(
                app.state.database.session_factory,
                provider=provider,
                settings=settings,
                worker_id="test-worker",
            )
        )
        assert [result.state for result in results] == ["succeeded"]

    assert provider.calls == [("create", "linked@example.com")]
    assert _query_one(
        database_path,
        "SELECT clerk_user_id, invitation_status, is_active FROM users WHERE email = ?",
        ("linked@example.com",),
    ) == ("user_linked_123", "accepted", 1)


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic not-a-bearer-token", "Bearer not-a-valid-token"],
)
def test_voice_session_rejects_missing_or_invalid_bearer(
    api: ApiHarness,
    authorization: str | None,
) -> None:
    headers = {} if authorization is None else {"Authorization": authorization}

    response = api.client.post("/v1/voice/sessions", headers=headers, json={})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_voice_session_rejects_tampered_bearer(api: ApiHarness) -> None:
    token = _login(api.client)
    replacement = "A" if token[-1] != "A" else "B"
    tampered_token = f"{token[:-1]}{replacement}"

    response = api.client.post(
        "/v1/voice/sessions",
        headers={"Authorization": f"Bearer {tampered_token}"},
        json={},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}


def test_authenticated_customer_can_create_a_voice_session(api: ApiHarness) -> None:
    token = _login(api.client)

    session = _create_session(api.client, token, language=" Hindi ")

    assert session["provider"] == "mock"
    assert session["status"] == "ready"
    assert session["language"] == "Hindi"
    assert "conversation_ref" not in session
    assert "agent_variables" not in session
    assert session["connection"]["transport"] == "mock"
    assert session["connection"]["websocket_url"] is None
    assert session["connection"]["expires_at"] == session["expires_at"]

    stored_hash, stored_provider, stored_status, session_mode, initiated_by = _query_one(
        api.database_path,
        (
            "SELECT conversation_ref_hash, provider, status, session_mode, "
            "initiated_by_user_id FROM voice_sessions WHERE id = ?"
        ),
        (session["session_id"],),
    )
    assert stored_hash == hash_conversation_ref(TEST_CONVERSATION_REF)
    assert stored_hash != TEST_CONVERSATION_REF
    assert stored_provider == "mock"
    assert stored_status == "ready"
    assert session_mode == "customer"
    assert initiated_by == DEMO_USER_ID


def test_admin_can_create_and_cancel_an_auditable_read_only_preview(
    api: ApiHarness,
) -> None:
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    session = _create_preview_session(api.client, admin_token, language=" Marathi ")

    stored = _query_one(
        api.database_path,
        (
            "SELECT customer_id, session_mode, initiated_by_user_id, language "
            "FROM voice_sessions WHERE id = ?"
        ),
        (session["session_id"],),
    )
    assert stored == (DEMO_CUSTOMER_ID, "admin_preview", DEMO_ADMIN_USER_ID, "Marathi")

    started = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": "interaction-admin-preview",
        },
    )
    assert started.status_code == 200, started.text
    instructions = started.json()["agent"]["instructions"]
    assert "Administrator preview mode is active" in instructions
    assert "must not create, reschedule, cancel" in instructions

    customer_token = _login(api.client)
    hidden_from_customer = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/cancel",
        headers={"Authorization": f"Bearer {customer_token}"},
    )
    assert hidden_from_customer.status_code == 404

    cancelled = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/cancel",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


def test_customer_cannot_start_an_admin_preview(api: ApiHarness) -> None:
    token = _login(api.client)

    response = api.client.post(
        f"/v1/voice/customers/{DEMO_CUSTOMER_ID}/preview-sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 403
    assert _count(api.database_path, "voice_sessions") == 0


def test_admin_preview_requires_an_active_customer_in_the_same_tenant(
    api: ApiHarness,
) -> None:
    _insert_out_of_scope_orders(api.database_path)
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}

    inactive = api.client.post(
        "/v1/voice/customers/00000000-0000-4000-8000-000000000008/preview-sessions",
        headers=headers,
        json={},
    )
    cross_tenant = api.client.post(
        "/v1/voice/customers/20000000-0000-4000-8000-000000000002/preview-sessions",
        headers=headers,
        json={},
    )

    assert inactive.status_code == 404
    assert cross_tenant.status_code == 404
    assert _count(api.database_path, "voice_sessions") == 0


def test_provider_receives_opaque_ref_without_exposing_it_and_terminal_race_wins(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-race.sqlite3"
    settings = settings_for_database(database_path)
    app = create_app(settings)
    provider = _CompletingDuringBootstrapProvider(app.state.database)
    app.state.voice_provider = provider

    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={"language": "English"},
        )

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Voice session ended while it was being created."}
    assert "connection" not in response.json()
    assert provider.agent_variables == {
        "conversation_ref": TEST_CONVERSATION_REF,
        "preferred_language": "English",
    }
    stored_status, provider_session_id, session_id = _query_one(
        database_path,
        "SELECT status, provider_session_id, id FROM voice_sessions",
    )
    assert stored_status == "completed"
    assert provider_session_id == "provider-race-session"
    assert session_id is not None


def test_ambiguous_termination_retains_slot_and_retry_finishes_cancellation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-termination-retry.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _ControllableTerminationProvider()
    app.state.voice_provider = provider

    with TestClient(app) as client:
        token = _login(client)
        session = _create_session(client, token)
        path = f"/v1/voice/sessions/{session['session_id']}/cancel"
        headers = {"Authorization": f"Bearer {token}"}

        provider.fail_termination = True
        failed = client.post(path, headers=headers)
        status_after_failure, slot_after_failure = _query_one(
            database_path,
            "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
            (session["session_id"],),
        )

        on_start_while_cancelling = client.post(
            "/v1/sarvam/hooks/on-start",
            headers=_tool_headers(),
            json={"conversation_ref": TEST_CONVERSATION_REF},
        )
        on_end_while_cancelling = client.post(
            "/v1/sarvam/hooks/on-end",
            headers=_tool_headers(),
            json={
                "conversation_ref": TEST_CONVERSATION_REF,
                "resolution": "must-not-win-after-cancellation",
            },
        )
        mock_complete_while_cancelling = client.post(
            f"/v1/voice/sessions/{session['session_id']}/mock-complete",
            headers=headers,
            json={"resolution": "must-not-win-after-cancellation"},
        )

        provider.fail_termination = False
        retry = client.post(path, headers=headers)
        idempotent_retry = client.post(path, headers=headers)

    assert failed.status_code == 503
    assert failed.headers["cache-control"] == "no-store"
    assert failed.headers["retry-after"] == "7"
    assert failed.json() == {
        "detail": "The provider has not confirmed that the voice session stopped."
    }
    assert (status_after_failure, slot_after_failure) == ("cancelling", 1)
    assert on_start_while_cancelling.status_code == 409
    assert on_start_while_cancelling.json() == {"detail": "Voice session is being cancelled"}
    assert on_end_while_cancelling.status_code == 409
    assert mock_complete_while_cancelling.status_code == 409
    assert retry.status_code == 200
    assert retry.json() == {
        "session_id": session["session_id"],
        "status": "cancelled",
        "idempotent": True,
    }
    assert idempotent_retry.status_code == 200
    assert idempotent_retry.json()["idempotent"] is True
    assert provider.termination_calls == [
        ("provider-cancellable-session", session["session_id"]),
        ("provider-cancellable-session", session["session_id"]),
    ]


def test_cancellation_that_races_provider_bootstrap_terminates_before_response(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-create-cancel-race.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _CancellingDuringBootstrapProvider(app.state.database)
    app.state.voice_provider = provider

    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Voice session was cancelled while it was being created."}
    session_id, provider_session_id, stored_status, active_slot = _query_one(
        database_path,
        "SELECT id, provider_session_id, status, active_slot FROM voice_sessions",
    )
    assert provider_session_id == "provider-create-cancel-race"
    assert (stored_status, active_slot) == ("cancelled", None)
    assert provider.termination_calls == [(provider_session_id, session_id)]


def test_atomic_finalize_preserves_cancellation_committed_immediately_before_update(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-atomic-finalize-race.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _ControllableTerminationProvider()
    app.state.voice_provider = provider
    cancellation_injected = False

    def inject_cancellation_before_finalize(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal cancellation_injected
        normalized_statement = statement.casefold()
        if (
            cancellation_injected
            or "update voice_sessions set" not in normalized_statement
            or "provider_session_id" not in normalized_statement
        ):
            return
        cancellation_injected = True
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE voice_sessions SET status = 'cancelling' "
                "WHERE id = (SELECT id FROM voice_sessions LIMIT 1)"
            )
            connection.commit()

    sync_engine = app.state.database.engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", inject_cancellation_before_finalize)
    try:
        with TestClient(app) as client:
            token = _login(client)
            response = client.post(
                "/v1/voice/sessions",
                headers={"Authorization": f"Bearer {token}"},
                json={},
            )
    finally:
        event.remove(sync_engine, "before_cursor_execute", inject_cancellation_before_finalize)

    assert cancellation_injected is True
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "connection" not in response.json()
    session_id, provider_session_id, stored_status, active_slot = _query_one(
        database_path,
        "SELECT id, provider_session_id, status, active_slot FROM voice_sessions",
    )
    assert (stored_status, active_slot) == ("cancelled", None)
    assert provider.termination_calls == [(provider_session_id, session_id)]


def test_slow_bootstrap_that_expires_before_finalize_is_terminated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "provider-slow-bootstrap-expiry.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _SlowBootstrapProvider()
    app.state.voice_provider = provider
    stale_now = datetime.now(UTC) - timedelta(minutes=30)
    route_times = iter((stale_now, datetime.now(UTC)))
    monkeypatch.setattr(voice_routes, "utc_now", lambda: next(route_times))

    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    assert response.status_code == 410
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Voice session expired while it was being created."}
    assert "connection" not in response.json()
    session_id, provider_session_id, stored_status, active_slot = _query_one(
        database_path,
        "SELECT id, provider_session_id, status, active_slot FROM voice_sessions",
    )
    assert provider_session_id == "provider-slow-bootstrap-session"
    assert (stored_status, active_slot) == ("expired", None)
    assert provider.termination_calls == [(provider_session_id, session_id)]


def test_reclaimed_session_is_not_revived_when_slow_provider_bootstrap_returns(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-bootstrap-reclaimed.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _ExpiredAndReclaimedDuringBootstrapProvider(app.state.database)
    app.state.voice_provider = provider

    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    assert response.status_code == 410
    assert response.headers["cache-control"] == "no-store"
    assert "connection" not in response.json()
    original_status, original_slot, original_provider_session_id = _query_one(
        database_path,
        "SELECT status, active_slot, provider_session_id FROM voice_sessions WHERE id = ?",
        (provider.original_session_id,),
    )
    replacement_status, replacement_slot = _query_one(
        database_path,
        "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
        (provider.replacement_session_id,),
    )
    assert (original_status, original_slot) == ("expired", None)
    assert original_provider_session_id == "provider-expired-bootstrap-session"
    assert (replacement_status, replacement_slot) == ("ready", 1)
    assert provider.termination_calls == [
        ("provider-expired-bootstrap-session", provider.original_session_id)
    ]


def test_database_finalize_failure_compensates_the_provider_session(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-finalize-compensation.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _ControllableTerminationProvider()
    app.state.voice_provider = provider

    async def fail_second_commit():  # type: ignore[no-untyped-def]
        async with app.state.database.session_factory() as database_session:
            original_commit = database_session.commit
            commit_count = 0

            async def flaky_commit() -> None:
                nonlocal commit_count
                commit_count += 1
                if commit_count == 2:
                    raise SQLAlchemyError("simulated finalization failure")
                await original_commit()

            database_session.commit = flaky_commit  # type: ignore[method-assign]
            yield database_session

    app.dependency_overrides[get_db] = fail_second_commit
    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

    assert response.status_code == 500
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Unable to create voice session."}
    session_id, provider_session_id, stored_status, active_slot = _query_one(
        database_path,
        "SELECT id, provider_session_id, status, active_slot FROM voice_sessions",
    )
    assert provider_session_id == "provider-cancellable-session"
    assert (stored_status, active_slot) == ("failed", None)
    assert provider.termination_calls == [(provider_session_id, session_id)]


def test_unexpected_finalize_failure_with_ambiguous_termination_is_retryable(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-unexpected-finalize-compensation.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _ControllableTerminationProvider()
    provider.fail_termination = True
    app.state.voice_provider = provider

    async def fail_provider_finalize():  # type: ignore[no-untyped-def]
        async with app.state.database.session_factory() as database_session:
            original_execute = database_session.execute
            failed_once = False

            async def flaky_execute(statement: object, *args: Any, **kwargs: Any) -> Any:
                nonlocal failed_once
                normalized_statement = str(statement).casefold()
                if (
                    not failed_once
                    and "update voice_sessions set" in normalized_statement
                    and "provider_session_id" in normalized_statement
                ):
                    failed_once = True
                    raise RuntimeError("simulated unexpected finalization failure")
                return await original_execute(statement, *args, **kwargs)  # type: ignore[arg-type]

            database_session.execute = flaky_execute  # type: ignore[method-assign]
            yield database_session

    app.dependency_overrides[get_db] = fail_provider_finalize
    with TestClient(app) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        failed = client.post("/v1/voice/sessions", headers=headers, json={})
        session_id, provider_session_id, stored_status, active_slot = _query_one(
            database_path,
            "SELECT id, provider_session_id, status, active_slot FROM voice_sessions",
        )

        provider.fail_termination = False
        retry = client.post(
            f"/v1/voice/sessions/{session_id}/cancel",
            headers=headers,
        )

    assert failed.status_code == 503
    assert failed.headers["cache-control"] == "no-store"
    assert failed.headers["retry-after"] == "7"
    assert (stored_status, active_slot) == ("cancelling", 1)
    assert provider_session_id == "provider-cancellable-session"
    assert retry.status_code == 200
    assert retry.json() == {
        "session_id": session_id,
        "status": "cancelled",
        "idempotent": True,
    }
    assert provider.termination_calls == [
        (provider_session_id, session_id),
        (provider_session_id, session_id),
    ]


def test_unexpected_bootstrap_failure_retains_slot_until_expiry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "provider-ambiguous-bootstrap.sqlite3"
    app = create_app(settings_for_database(database_path))
    app.state.voice_provider = _UnexpectedBootstrapFailureProvider()
    ambiguous_ref = f"{TEST_CONVERSATION_REF}-ambiguous"
    conversation_refs = iter(
        (
            ambiguous_ref,
            f"{TEST_CONVERSATION_REF}-blocked-retry",
        )
    )
    monkeypatch.setattr(voice_routes, "generate_conversation_ref", lambda: next(conversation_refs))

    with TestClient(app) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        failed = client.post("/v1/voice/sessions", headers=headers, json={})
        on_start = client.post(
            "/v1/sarvam/hooks/on-start",
            headers=_tool_headers(),
            json={"conversation_ref": ambiguous_ref},
        )
        order_tool = client.post(
            "/v1/sarvam/tools/get-order-status",
            headers=_tool_headers(),
            json={
                "conversation_ref": ambiguous_ref,
                "interaction_id": "ambiguous-bootstrap-interaction",
                "order_reference": "ORD-8294",
            },
        )
        on_end = client.post(
            "/v1/sarvam/hooks/on-end",
            headers=_tool_headers(),
            json={
                "conversation_ref": ambiguous_ref,
                "interaction_id": "ambiguous-bootstrap-interaction",
                "resolution": "must-not-record",
            },
        )
        blocked_retry = client.post("/v1/voice/sessions", headers=headers, json={})

    assert failed.status_code == 503
    assert failed.headers["cache-control"] == "no-store"
    assert failed.headers["retry-after"] == "3"
    assert failed.json() == {
        "detail": "The voice provider has not confirmed whether the session started."
    }
    assert on_start.status_code == 409
    assert on_start.json() == {"detail": "Voice session is being cancelled"}
    assert order_tool.status_code == 409
    assert order_tool.json() == {"detail": "Voice session is being cancelled"}
    assert on_end.status_code == 409
    assert _count(database_path, "conversation_outcomes") == 0
    assert blocked_retry.status_code == 409
    assert blocked_retry.json() == {
        "detail": "An active voice session already exists for this customer."
    }
    provider_session_id, stored_status, active_slot = _query_one(
        database_path,
        "SELECT provider_session_id, status, active_slot FROM voice_sessions",
    )
    assert provider_session_id is None
    assert (stored_status, active_slot) == ("cancelling", 1)


def test_termination_failure_after_expiry_race_stays_retryable_without_slot_collision(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "provider-termination-expiry-race.sqlite3"
    app = create_app(settings_for_database(database_path))
    provider = _ExpiringDuringTerminationProvider(app.state.database)
    app.state.voice_provider = provider

    with TestClient(app) as client:
        token = _login(client)
        headers = {"Authorization": f"Bearer {token}"}
        session = _create_session(client, token)
        path = f"/v1/voice/sessions/{session['session_id']}/cancel"

        failed = client.post(path, headers=headers)
        original_status, original_slot = _query_one(
            database_path,
            "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
            (session["session_id"],),
        )
        replacement_status, replacement_slot = _query_one(
            database_path,
            "SELECT status, active_slot FROM voice_sessions WHERE id != ?",
            (session["session_id"],),
        )
        retry = client.post(path, headers=headers)

    assert failed.status_code == 503
    assert failed.headers["retry-after"] == "7"
    assert (original_status, original_slot) == ("cancelling", None)
    assert (replacement_status, replacement_slot) == ("ready", 1)
    assert retry.status_code == 200
    assert retry.json()["status"] == "cancelled"
    assert provider.termination_calls == [
        ("provider-cancellable-session", session["session_id"]),
        ("provider-cancellable-session", session["session_id"]),
    ]


def test_only_one_active_session_is_allowed_and_completion_releases_slot(
    api: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_refs = iter(
        (
            f"{TEST_CONVERSATION_REF}-first",
            f"{TEST_CONVERSATION_REF}-blocked",
            f"{TEST_CONVERSATION_REF}-after-completion",
        )
    )
    monkeypatch.setattr(
        voice_routes,
        "generate_conversation_ref",
        lambda: next(conversation_refs),
    )
    token = _login(api.client)

    first = _create_session(api.client, token)
    blocked = api.client.post(
        "/v1/voice/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert blocked.status_code == 409
    assert blocked.json() == {"detail": "An active voice session already exists for this customer."}
    assert _count(api.database_path, "voice_sessions") == 1

    completed = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json={
            "conversation_ref": f"{TEST_CONVERSATION_REF}-first",
            "resolution": "completed",
        },
    )
    assert completed.status_code == 200

    replacement = _create_session(api.client, token)
    assert replacement["session_id"] != first["session_id"]
    assert _count(api.database_path, "voice_sessions") == 2
    first_status, first_slot = _query_one(
        api.database_path,
        "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
        (first["session_id"],),
    )
    replacement_status, replacement_slot = _query_one(
        api.database_path,
        "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
        (replacement["session_id"],),
    )
    assert (first_status, first_slot) == ("completed", None)
    assert (replacement_status, replacement_slot) == ("ready", 1)


def test_expired_active_session_is_released_before_creating_replacement(
    api: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_refs = iter(
        (
            f"{TEST_CONVERSATION_REF}-expired",
            f"{TEST_CONVERSATION_REF}-replacement",
        )
    )
    monkeypatch.setattr(
        voice_routes,
        "generate_conversation_ref",
        lambda: next(conversation_refs),
    )
    token = _login(api.client)
    expired_session = _create_session(api.client, token)
    expired_at = datetime.now(UTC) - timedelta(minutes=1)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE voice_sessions SET expires_at = ? WHERE id = ?",
            (expired_at.isoformat(sep=" "), expired_session["session_id"]),
        )
        connection.commit()

    replacement = _create_session(api.client, token)

    old_status, old_slot = _query_one(
        api.database_path,
        "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
        (expired_session["session_id"],),
    )
    assert (old_status, old_slot) == ("expired", None)
    assert replacement["status"] == "ready"


def test_voice_session_cancel_is_authenticated_idempotent_and_releases_slot(
    api: ApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_refs = iter(
        (
            f"{TEST_CONVERSATION_REF}-cancelled",
            f"{TEST_CONVERSATION_REF}-replacement-after-cancel",
        )
    )
    monkeypatch.setattr(
        voice_routes,
        "generate_conversation_ref",
        lambda: next(conversation_refs),
    )
    token = _login(api.client)
    session = _create_session(api.client, token)
    path = f"/v1/voice/sessions/{session['session_id']}/cancel"

    unauthenticated = api.client.post(path)
    first = api.client.post(path, headers={"Authorization": f"Bearer {token}"})
    retry = api.client.post(path, headers={"Authorization": f"Bearer {token}"})

    assert unauthenticated.status_code == 401
    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json() == {
        "session_id": session["session_id"],
        "status": "cancelled",
        "idempotent": False,
    }
    assert "provider" not in first.text
    assert "conversation_ref" not in first.text
    assert retry.status_code == 200
    assert retry.json() == {
        "session_id": session["session_id"],
        "status": "cancelled",
        "idempotent": True,
    }

    stored_status, active_slot, ended_at = _query_one(
        api.database_path,
        "SELECT status, active_slot, ended_at FROM voice_sessions WHERE id = ?",
        (session["session_id"],),
    )
    assert (stored_status, active_slot) == ("cancelled", None)
    assert ended_at is not None

    replacement = _create_session(api.client, token)
    assert replacement["session_id"] != session["session_id"]


def test_cancel_during_bootstrap_stays_pending_without_releasing_slot(api: ApiHarness) -> None:
    token = _login(api.client)
    session = _create_session(api.client, token)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE voice_sessions SET status = 'creating', provider_session_id = NULL "
            "WHERE id = ?",
            (session["session_id"],),
        )
        connection.commit()

    path = f"/v1/voice/sessions/{session['session_id']}/cancel"
    headers = {"Authorization": f"Bearer {token}"}
    first = api.client.post(path, headers=headers)
    retry = api.client.post(path, headers=headers)

    assert first.status_code == 200
    assert first.json() == {
        "session_id": session["session_id"],
        "status": "cancelling",
        "idempotent": False,
    }
    assert retry.status_code == 200
    assert retry.json() == {
        "session_id": session["session_id"],
        "status": "cancelling",
        "idempotent": True,
    }
    stored_status, active_slot = _query_one(
        api.database_path,
        "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
        (session["session_id"],),
    )
    assert (stored_status, active_slot) == ("cancelling", 1)


def test_cancel_completed_voice_session_is_a_safe_noop(api: ApiHarness) -> None:
    token = _login(api.client)
    session = _create_session(api.client, token)
    completion = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/mock-complete",
        headers={"Authorization": f"Bearer {token}"},
        json={"resolution": "resolved", "summary": "Already complete."},
    )
    assert completion.status_code == 200

    response = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session["session_id"],
        "status": "completed",
        "idempotent": True,
    }
    assert _count(api.database_path, "conversation_outcomes") == 1


def test_session_creation_rejects_browser_supplied_identity(api: ApiHarness) -> None:
    token = _login(api.client)

    response = api.client.post(
        "/v1/voice/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "language": "English",
            "tenant_id": "attacker-controlled-tenant",
            "customer_id": "attacker-controlled-customer",
        },
    )

    assert response.status_code == 422
    error_locations = {tuple(error["loc"]) for error in response.json()["detail"]}
    assert ("body", "tenant_id") in error_locations
    assert ("body", "customer_id") in error_locations
    assert _count(api.database_path, "voice_sessions") == 0


def test_sarvam_tools_require_the_configured_key(api: ApiHarness) -> None:
    token = _login(api.client)
    _create_session(api.client, token)
    payload = {"conversation_ref": TEST_CONVERSATION_REF}

    missing_key = api.client.post("/v1/sarvam/hooks/on-start", json=payload)
    wrong_key = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers("wrong-tool-key"),
        json=payload,
    )
    correct_key = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json=payload,
    )

    assert missing_key.status_code == 401
    assert missing_key.json() == {"detail": "Unauthorized"}
    assert wrong_key.status_code == 401
    assert wrong_key.json() == {"detail": "Unauthorized"}
    assert correct_key.status_code == 200
    assert correct_key.headers["cache-control"] == "no-store"


def test_on_start_returns_only_personalized_safe_context(api: ApiHarness) -> None:
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "DELETE FROM customer_agent_configurations WHERE customer_id = ?",
            ("00000000-0000-4000-8000-000000000002",),
        )
        connection.commit()
    token = _login(api.client)
    session = _create_session(api.client, token)

    response = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": "interaction-test-1",
            "metadata": {"channel": "web"},
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "session_id": session["session_id"],
        "customer": {
            "first_name": "Rahul",
            "preferred_language": "English",
            "plan_name": "Essential",
            "open_request_count": 0,
        },
        "agent": {
            "display_name": "Asha",
            "opening_message": "Hello Rahul, how can I help you today?",
            "tone": "professional",
            "instructions": (
                "Help the customer clearly, use only verified account information, "
                "and protect their privacy."
            ),
            "revision": 1,
        },
        "safe_to_continue": True,
    }


def _insert_out_of_scope_orders(database_path: Path) -> None:
    created_at = "2026-01-01 00:00:00.000000"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO customers (
                id, tenant_id, external_ref, full_name, preferred_language,
                plan_name, phone_hash, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "10000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000001",
                "CUS-OTHER",
                "Other Customer",
                "English",
                "Essential",
                None,
                1,
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO customer_orders (
                id, tenant_id, customer_id, external_ref, status,
                estimated_arrival, delivery_city, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "10000000-0000-4000-8000-000000000002",
                "00000000-0000-4000-8000-000000000001",
                "10000000-0000-4000-8000-000000000001",
                "ORD-OTHER-CUSTOMER",
                "Private",
                None,
                "Mumbai",
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO tenants (id, slug, name, is_active, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "20000000-0000-4000-8000-000000000001",
                "other-tenant",
                "Other Tenant",
                1,
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO customers (
                id, tenant_id, external_ref, full_name, preferred_language,
                plan_name, phone_hash, is_active, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "20000000-0000-4000-8000-000000000002",
                "20000000-0000-4000-8000-000000000001",
                "CUS-OTHER-TENANT",
                "Other Tenant Customer",
                "English",
                "Essential",
                None,
                1,
                created_at,
            ),
        )
        connection.execute(
            """
            INSERT INTO customer_orders (
                id, tenant_id, customer_id, external_ref, status,
                estimated_arrival, delivery_city, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "20000000-0000-4000-8000-000000000003",
                "20000000-0000-4000-8000-000000000001",
                "20000000-0000-4000-8000-000000000002",
                "ORD-OTHER-TENANT",
                "Private",
                None,
                "Chennai",
                created_at,
            ),
        )
        connection.commit()


def _insert_out_of_scope_voice_session(database_path: Path) -> str:
    _insert_out_of_scope_orders(database_path)
    session_id = "10000000-0000-4000-8000-000000000003"
    started_at = datetime.now(UTC)
    expires_at = started_at + timedelta(minutes=15)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO voice_sessions (
                id, tenant_id, customer_id, provider, provider_session_id,
                provider_interaction_id, conversation_ref_hash, status, active_slot,
                language, started_at, expires_at, ended_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                "00000000-0000-4000-8000-000000000001",
                "10000000-0000-4000-8000-000000000001",
                "mock",
                "private-provider-session",
                None,
                hash_conversation_ref(f"{TEST_CONVERSATION_REF}-other-customer"),
                "ready",
                1,
                "English",
                started_at.isoformat(sep=" "),
                expires_at.isoformat(sep=" "),
                None,
            ),
        )
        connection.commit()
    return session_id


def test_cancel_does_not_disclose_another_customers_voice_session(api: ApiHarness) -> None:
    out_of_scope_session_id = _insert_out_of_scope_voice_session(api.database_path)
    token = _login(api.client)

    response = api.client.post(
        f"/v1/voice/sessions/{out_of_scope_session_id}/cancel",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found."}
    stored_status, active_slot = _query_one(
        api.database_path,
        "SELECT status, active_slot FROM voice_sessions WHERE id = ?",
        (out_of_scope_session_id,),
    )
    assert (stored_status, active_slot) == ("ready", 1)


def test_order_lookup_is_scoped_to_session_customer_and_tenant(api: ApiHarness) -> None:
    _insert_out_of_scope_orders(api.database_path)
    token = _login(api.client)
    _create_session(api.client, token)
    interaction_id = "interaction-order-scope"

    own_order = api.client.post(
        "/v1/sarvam/tools/get-order-status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "order_reference": "ORD-8294",
        },
    )
    other_customer_order = api.client.post(
        "/v1/sarvam/tools/get-order-status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "order_reference": "ORD-OTHER-CUSTOMER",
        },
    )
    other_tenant_order = api.client.post(
        "/v1/sarvam/tools/get-order-status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "order_reference": "ORD-OTHER-TENANT",
        },
    )

    assert own_order.status_code == 200
    assert own_order.headers["cache-control"] == "no-store"
    assert own_order.json() == {
        "order_reference": "ORD-8294",
        "status": "In transit",
        "estimated_arrival": "Tomorrow between 10:00 AM and 12:00 PM",
        "delivery_city": "Bengaluru",
    }
    assert other_customer_order.status_code == 404
    assert other_customer_order.json() == {"detail": "Order not found"}
    assert other_tenant_order.status_code == 404
    assert other_tenant_order.json() == {"detail": "Order not found"}


def test_reservation_tools_complete_an_idempotent_customer_scoped_lifecycle(
    api: ApiHarness,
) -> None:
    token = _login(api.client)
    _create_session(api.client, token)
    interaction_id = "interaction-reservation-lifecycle"
    reservation_date = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)).date()

    availability = api.client.post(
        "/v1/sarvam/tools/check-availability",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "reservation_date": reservation_date.isoformat(),
            "preferred_time": "19:00:00",
            "party_size": 8,
        },
    )
    assert availability.status_code == 200, availability.text
    assert availability.headers["cache-control"] == "no-store"
    availability_body = availability.json()
    assert availability_body["available"] is True
    assert availability_body["service_location"] == "By the Brew"
    assert availability_body["timezone"] == "Asia/Kolkata"
    assert 1 <= len(availability_body["slots"]) <= 5
    selected_start = availability_body["slots"][0]["start_at"]

    create_payload = {
        "conversation_ref": TEST_CONVERSATION_REF,
        "interaction_id": interaction_id,
        "start_at": selected_start,
        "party_size": 8,
        "special_requests": "Window seat if possible",
    }
    created = api.client.post(
        "/v1/sarvam/tools/create-reservation",
        headers=_tool_headers(),
        json=create_payload,
    )
    replayed_create = api.client.post(
        "/v1/sarvam/tools/create-reservation",
        headers=_tool_headers(),
        json=create_payload,
    )
    conflicting_create = api.client.post(
        "/v1/sarvam/tools/create-reservation",
        headers=_tool_headers(),
        json={**create_payload, "guest_name": "Another Guest"},
    )

    assert created.status_code == 200, created.text
    assert created.json()["idempotent"] is False
    created_reservation = created.json()["reservation"]
    reference = created_reservation["reservation_reference"]
    assert reference.startswith("RSV-")
    assert created_reservation["guest_name"] == "Rahul Mehta"
    assert created_reservation["status"] == "confirmed"
    assert created_reservation["version"] == 1
    assert replayed_create.status_code == 200
    assert replayed_create.json()["idempotent"] is True
    assert replayed_create.json()["reservation"] == created_reservation
    assert conflicting_create.status_code == 409
    assert conflicting_create.json() == {
        "detail": "The selected reservation time is no longer available"
    }

    found = api.client.post(
        "/v1/sarvam/tools/find-reservation",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "reservation_reference": reference.lower(),
        },
    )
    assert found.status_code == 200
    assert found.json()["found"] is True
    assert found.json()["reservations"] == [created_reservation]

    later_availability = api.client.post(
        "/v1/sarvam/tools/check-availability",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "reservation_date": reservation_date.isoformat(),
            "preferred_time": "20:00:00",
            "party_size": 8,
        },
    )
    assert later_availability.status_code == 200
    alternative_start = next(
        slot["start_at"]
        for slot in later_availability.json()["slots"]
        if slot["start_at"] != selected_start
    )
    reschedule_payload = {
        "conversation_ref": TEST_CONVERSATION_REF,
        "interaction_id": interaction_id,
        "reservation_reference": reference,
        "new_start_at": alternative_start,
        "expected_version": 1,
    }
    rescheduled = api.client.post(
        "/v1/sarvam/tools/reschedule-reservation",
        headers=_tool_headers(),
        json=reschedule_payload,
    )
    replayed_reschedule = api.client.post(
        "/v1/sarvam/tools/reschedule-reservation",
        headers=_tool_headers(),
        json=reschedule_payload,
    )
    assert rescheduled.status_code == 200, rescheduled.text
    assert rescheduled.json()["reservation"]["version"] == 2
    assert rescheduled.json()["reservation"]["start_at"] != created_reservation["start_at"]
    assert replayed_reschedule.status_code == 200
    assert replayed_reschedule.json()["idempotent"] is True

    cancel_payload = {
        "conversation_ref": TEST_CONVERSATION_REF,
        "interaction_id": interaction_id,
        "reservation_reference": reference,
        "expected_version": 2,
    }
    cancelled = api.client.post(
        "/v1/sarvam/tools/cancel-reservation",
        headers=_tool_headers(),
        json=cancel_payload,
    )
    replayed_cancel = api.client.post(
        "/v1/sarvam/tools/cancel-reservation",
        headers=_tool_headers(),
        json=cancel_payload,
    )
    current_version_cancel = api.client.post(
        "/v1/sarvam/tools/cancel-reservation",
        headers=_tool_headers(),
        json={**cancel_payload, "expected_version": 3},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["reservation"]["status"] == "cancelled"
    assert cancelled.json()["reservation"]["version"] == 3
    assert replayed_cancel.status_code == 200
    assert replayed_cancel.json()["idempotent"] is True
    assert current_version_cancel.status_code == 200
    assert current_version_cancel.json()["idempotent"] is True
    assert current_version_cancel.json()["reservation"]["version"] == 3

    with sqlite3.connect(api.database_path) as connection:
        reservation_count = connection.execute("SELECT COUNT(*) FROM cafe_reservations").fetchone()
        operation_count = connection.execute(
            "SELECT COUNT(*) FROM reservation_tool_operations"
        ).fetchone()
    assert reservation_count == (1,)
    assert operation_count == (4,)


def test_admin_preview_allows_lookups_but_blocks_reservation_mutations(
    api: ApiHarness,
) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    _create_preview_session(api.client, token)
    interaction_id = "interaction-read-only-admin-preview"
    reservation_date = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)).date()

    availability = api.client.post(
        "/v1/sarvam/tools/check-availability",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "reservation_date": reservation_date.isoformat(),
            "preferred_time": "19:00:00",
            "party_size": 2,
        },
    )
    assert availability.status_code == 200, availability.text
    assert availability.json()["available"] is True
    selected_start = availability.json()["slots"][0]["start_at"]

    blocked = api.client.post(
        "/v1/sarvam/tools/create-reservation",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": interaction_id,
            "start_at": selected_start,
            "party_size": 2,
        },
    )

    assert blocked.status_code == 403
    assert blocked.json() == {
        "detail": "State-changing tools are disabled in administrator preview sessions"
    }
    with sqlite3.connect(api.database_path) as connection:
        reservation_count = connection.execute("SELECT COUNT(*) FROM cafe_reservations").fetchone()
        mutation_operation_count = connection.execute(
            """
            SELECT COUNT(*)
            FROM reservation_tool_operations
            WHERE tool_name IN (
                'create_reservation',
                'reschedule_reservation',
                'cancel_reservation'
            )
            """
        ).fetchone()
    assert reservation_count == (0,)
    assert mutation_operation_count == (0,)


def test_completed_admin_preview_is_excluded_from_customer_history(
    api: ApiHarness,
) -> None:
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {admin_token}"}
    customer_path = f"/v1/customers/{DEMO_CUSTOMER_ID}"
    before = api.client.get(customer_path, headers=headers)
    assert before.status_code == 200

    session = _create_preview_session(api.client, admin_token)
    completion = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/mock-complete",
        headers=headers,
        json={
            "resolution": "resolved",
            "summary": "Administrator-only preview outcome.",
            "transcript": [
                {"speaker": "agent", "text": "Preview complete."},
            ],
            "duration_seconds": 5,
        },
    )
    assert completion.status_code == 200, completion.text

    after = api.client.get(customer_path, headers=headers)
    assert after.status_code == 200
    assert after.json()["conversation_count"] == before.json()["conversation_count"]
    assert (
        after.json()["resolved_conversation_count"]
        == (before.json()["resolved_conversation_count"])
    )
    assert after.json()["last_conversation_at"] == before.json()["last_conversation_at"]
    assert after.json()["recent_conversations"] == before.json()["recent_conversations"]
    assert _count(api.database_path, "conversation_outcomes") == 1


def test_reservation_tools_reject_bad_auth_and_ambiguous_times(api: ApiHarness) -> None:
    token = _login(api.client)
    _create_session(api.client, token)
    reservation_date = (datetime.now(ZoneInfo("Asia/Kolkata")) + timedelta(days=2)).date()
    payload = {
        "conversation_ref": TEST_CONVERSATION_REF,
        "reservation_date": reservation_date.isoformat(),
        "preferred_time": "19:00:00",
        "party_size": 2,
    }

    unauthenticated = api.client.post(
        "/v1/sarvam/tools/check-availability",
        json=payload,
    )
    oversized_party = api.client.post(
        "/v1/sarvam/tools/check-availability",
        headers=_tool_headers(),
        json={**payload, "party_size": 9},
    )
    naive_start = api.client.post(
        "/v1/sarvam/tools/create-reservation",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "start_at": f"{reservation_date.isoformat()}T19:00:00",
            "party_size": 2,
        },
    )

    assert unauthenticated.status_code == 401
    assert oversized_party.status_code == 200
    assert oversized_party.json()["available"] is False
    assert oversized_party.json()["slots"] == []
    assert "maximum supported party size is 8" in oversized_party.json()["reason"]
    assert naive_start.status_code == 422


def test_sqlite_composite_key_rejects_cross_tenant_order_relationship(
    api: ApiHarness,
) -> None:
    _insert_out_of_scope_orders(api.database_path)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            connection.execute(
                """
                INSERT INTO customer_orders (
                    id, tenant_id, customer_id, external_ref, status,
                    estimated_arrival, delivery_city, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "30000000-0000-4000-8000-000000000001",
                    "00000000-0000-4000-8000-000000000001",
                    "20000000-0000-4000-8000-000000000002",
                    "ORD-CROSS-TENANT",
                    "Must be rejected",
                    None,
                    None,
                    "2026-01-01 00:00:00.000000",
                ),
            )


@pytest.mark.parametrize(
    ("table", "record_id"),
    [
        ("tenants", "00000000-0000-4000-8000-000000000001"),
        ("customers", "00000000-0000-4000-8000-000000000002"),
    ],
)
def test_runtime_tools_reject_inactive_tenant_or_customer(
    api: ApiHarness,
    table: str,
    record_id: str,
) -> None:
    token = _login(api.client)
    _create_session(api.client, token)
    update_statements = {
        "tenants": "UPDATE tenants SET is_active = 0 WHERE id = ?",
        "customers": "UPDATE customers SET is_active = 0 WHERE id = ?",
    }
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(update_statements[table], (record_id,))
        connection.commit()

    runtime_response = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json={"conversation_ref": TEST_CONVERSATION_REF},
    )
    completion_response = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json={"conversation_ref": TEST_CONVERSATION_REF, "resolution": "disabled-context"},
    )

    assert runtime_response.status_code == 404
    assert runtime_response.json() == {"detail": "Voice session not found"}
    assert completion_response.status_code == 200


def test_bound_session_requires_matching_interaction_for_order_tool(api: ApiHarness) -> None:
    token = _login(api.client)
    _create_session(api.client, token)
    bound_interaction = "interaction-bound-to-session"
    on_start = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": bound_interaction,
        },
    )
    assert on_start.status_code == 200

    without_interaction = api.client.post(
        "/v1/sarvam/tools/get-order-status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "order_reference": "ORD-8294",
        },
    )
    mismatched_interaction = api.client.post(
        "/v1/sarvam/tools/get-order-status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": "interaction-from-another-call",
            "order_reference": "ORD-8294",
        },
    )
    matching_interaction = api.client.post(
        "/v1/sarvam/tools/get-order-status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": bound_interaction,
            "order_reference": "ORD-8294",
        },
    )

    assert without_interaction.status_code == 409
    assert without_interaction.json() == {"detail": "Interaction does not match this voice session"}
    assert mismatched_interaction.status_code == 409
    assert mismatched_interaction.json() == {
        "detail": "Interaction does not match this voice session"
    }
    assert matching_interaction.status_code == 200
    assert matching_interaction.json()["order_reference"] == "ORD-8294"


def test_on_end_persists_once_and_accepts_idempotent_retry(api: ApiHarness) -> None:
    token = _login(api.client)
    session = _create_session(api.client, token)
    payload = {
        "conversation_ref": TEST_CONVERSATION_REF,
        "interaction_id": "interaction-test-end",
        "resolution": "answered",
        "summary": "Rahul checked the delivery time for his order.",
        "transcript": [
            {"speaker": "customer", "text": "When will my order arrive?"},
            {"speaker": "agent", "text": "It is expected tomorrow morning."},
        ],
        "final_variables": {
            "order_reference": "ORD-8294",
            "follow_up": False,
            "resolution_code": "DELIVERY_CONFIRMED",
            "internal_debug": {"token": "must-not-be-persisted"},
        },
        "duration_seconds": 42,
    }

    first = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json=payload,
    )
    changed_retry_payload = {
        **payload,
        "resolution": "should-not-overwrite",
        "summary": "A retry must not replace the recorded outcome.",
        "transcript": [{"speaker": "agent", "text": "Replacement transcript"}],
        "final_variables": {"replacement": True},
        "duration_seconds": 999,
    }
    retry = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json=changed_retry_payload,
    )

    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert first.json()["status"] == "recorded"
    assert first.json()["idempotent"] is False
    assert retry.status_code == 200
    assert retry.headers["cache-control"] == "no-store"
    assert retry.json()["idempotent"] is True
    assert retry.json()["outcome_id"] == first.json()["outcome_id"]
    assert _count(api.database_path, "conversation_outcomes") == 1

    outcome = _query_one(
        api.database_path,
        """
        SELECT interaction_id, resolution, summary, transcript,
               final_variables, duration_seconds
        FROM conversation_outcomes
        WHERE id = ?
        """,
        (first.json()["outcome_id"],),
    )
    assert outcome[0:3] == (
        "interaction-test-end",
        "answered",
        "Rahul checked the delivery time for his order.",
    )
    assert json.loads(outcome[3]) == [{**turn, "timestamp": None} for turn in payload["transcript"]]
    assert json.loads(outcome[4]) == {
        "order_reference": "ORD-8294",
        "follow_up": False,
        "resolution_code": "DELIVERY_CONFIRMED",
    }
    assert outcome[5] == 42

    status_value, ended_at = _query_one(
        api.database_path,
        "SELECT status, ended_at FROM voice_sessions WHERE id = ?",
        (session["session_id"],),
    )
    assert status_value == "completed"
    assert ended_at is not None

    mismatched_retry = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json={**payload, "interaction_id": "a-different-interaction"},
    )
    assert mismatched_retry.status_code == 409
    assert "Interaction does not match" in mismatched_retry.json()["detail"]
    assert _count(api.database_path, "conversation_outcomes") == 1


def test_delayed_on_end_is_accepted_after_expiry_but_runtime_tool_is_not(
    api: ApiHarness,
) -> None:
    token = _login(api.client)
    session = _create_session(api.client, token)
    recently_expired = datetime.now(UTC) - timedelta(minutes=1)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE voice_sessions SET expires_at = ? WHERE id = ?",
            (recently_expired.isoformat(sep=" "), session["session_id"]),
        )
        connection.commit()

    runtime_response = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json={"conversation_ref": TEST_CONVERSATION_REF},
    )
    completion_response = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": "delayed-interaction",
            "resolution": "completed",
        },
    )

    assert runtime_response.status_code == 410
    assert runtime_response.json() == {"detail": "Voice session has expired"}
    assert completion_response.status_code == 200
    assert completion_response.json()["idempotent"] is False
    assert _count(api.database_path, "conversation_outcomes") == 1


def test_on_end_rejects_callback_beyond_completion_grace(api: ApiHarness) -> None:
    token = _login(api.client)
    session = _create_session(api.client, token)
    expiry_outside_grace = datetime.now(UTC) - timedelta(
        minutes=api.settings.completion_grace_minutes + 5
    )
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE voice_sessions SET expires_at = ? WHERE id = ?",
            (expiry_outside_grace.isoformat(sep=" "), session["session_id"]),
        )
        connection.commit()

    response = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": "too-late-interaction",
            "resolution": "completed",
        },
    )

    assert response.status_code == 410
    assert response.json() == {"detail": "Voice session completion window has expired"}
    assert _count(api.database_path, "conversation_outcomes") == 0


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v1/sarvam/hooks/on-start", {}),
        (
            "/v1/sarvam/tools/get-order-status",
            {"order_reference": "ORD-8294"},
        ),
    ],
)
def test_runtime_tools_are_blocked_after_session_end(
    api: ApiHarness,
    path: str,
    body: dict[str, str],
) -> None:
    token = _login(api.client)
    _create_session(api.client, token)
    ended = api.client.post(
        "/v1/sarvam/hooks/on-end",
        headers=_tool_headers(),
        json={"conversation_ref": TEST_CONVERSATION_REF, "resolution": "completed"},
    )
    assert ended.status_code == 200

    response = api.client.post(
        path,
        headers=_tool_headers(),
        json={"conversation_ref": TEST_CONVERSATION_REF, **body},
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Voice session has already ended"}


def test_production_rejects_default_secrets() -> None:
    with pytest.raises(ValidationError, match="Production secrets must be explicitly configured"):
        Settings(
            app_env="production",
            session_secret="development-session-secret-change-before-production",
            sarvam_tool_secret="development-tool-secret-change-before-production",
            enable_demo_auth=False,
            seed_demo_data=False,
        )


def test_production_rejects_demo_defaults_even_with_safe_secrets() -> None:
    with pytest.raises(
        ValidationError,
        match="Demo authentication and seed data must be disabled in production",
    ):
        Settings(
            app_env="production",
            session_secret="a-production-session-secret-that-is-long-enough",
            sarvam_tool_secret="a-production-tool-secret-that-is-also-long-enough",
            enable_demo_auth=True,
            seed_demo_data=True,
        )


def test_sarvam_provider_fails_closed_with_incomplete_configuration(tmp_path: Path) -> None:
    database_path = tmp_path / "sarvam-provider.sqlite3"
    settings = settings_for_database(
        database_path,
        voice_provider="sarvam",
    )

    with TestClient(create_app(settings)) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={},
        )

        assert response.status_code == 503
        assert response.json() == {
            "detail": "Voice sessions are unavailable because the provider is not fully configured."
        }
        assert _count(database_path, "voice_sessions") == 1
        (stored_status,) = _query_one(
            database_path,
            "SELECT status FROM voice_sessions",
        )
        assert stored_status == "failed"


def test_sarvam_provider_returns_an_encrypted_backend_relay_url(tmp_path: Path) -> None:
    database_path = tmp_path / "sarvam-relay-session.sqlite3"
    settings = settings_for_database(
        database_path,
        voice_provider="sarvam",
        sarvam_api_key="test-api-key",
        sarvam_org_id="test-organisation",
        sarvam_workspace_id="test-workspace",
        sarvam_agent_id="test-agent",
        sarvam_agent_version=2,
        voice_websocket_public_url="ws://127.0.0.1:8000/v1/voice/stream",
    )
    app = create_app(settings)

    with TestClient(app) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions",
            headers={"Authorization": f"Bearer {token}"},
            json={"language": "Hindi"},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["provider"] == "sarvam"
    assert payload["connection"]["transport"] == "websocket"
    websocket_url = payload["connection"]["websocket_url"]
    assert websocket_url.startswith("ws://127.0.0.1:8000/v1/voice/stream?token=")
    assert TEST_CONVERSATION_REF not in websocket_url

    relay_token = parse_qs(urlsplit(websocket_url).query)["token"][0]
    claims = app.state.voice_provider.decode_relay_token(relay_token)
    assert claims.session_id == payload["session_id"]
    assert claims.conversation_ref == TEST_CONVERSATION_REF
    assert claims.language == "Hindi"
    assert claims.agent_variables == {
        "conversation_ref": TEST_CONVERSATION_REF,
        "preferred_language": "Hindi",
    }


def test_sarvam_browser_relay_streams_audio_and_saves_the_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "sarvam-browser-relay.sqlite3"
    settings = settings_for_database(
        database_path,
        voice_provider="sarvam",
        sarvam_api_key="test-api-key",
        sarvam_org_id="test-organisation",
        sarvam_workspace_id="test-workspace",
        sarvam_agent_id="test-agent",
        sarvam_agent_version=2,
        voice_websocket_public_url="ws://127.0.0.1:8000/v1/voice/stream",
    )
    app = create_app(settings)
    provider = app.state.voice_provider
    captured_audio: list[bytes] = []
    captured_variables: dict[str, str] = {}

    class FakeAgent:
        def __init__(self) -> None:
            self.disconnected = asyncio.Event()

        async def send_audio(self, audio: bytes) -> None:
            captured_audio.append(audio)

        async def wait_for_disconnect(self) -> None:
            await self.disconnected.wait()

        async def stop(self) -> None:
            self.disconnected.set()

    async def activate_agent(
        claims: object,
        *,
        agent_variables: Mapping[str, str],
        initial_bot_message: str | None,
        audio_callback: Any,
        transcript_callback: Any,
        event_callback: Any,
    ) -> FakeAgent:
        del claims
        captured_variables.update(agent_variables)
        assert initial_bot_message == "Hello Rahul, how can I help you today?"
        await event_callback(
            ServerInteractionConnectedEvent(
                timestamp=1.0,
                reference_id="reference-test",
                interaction_id="interaction-test",
            )
        )
        await transcript_callback(
            ServerTranscriptMsg(
                timestamp=2.0,
                role=Role.BOT,
                content="Your account is ready.",
            )
        )
        await audio_callback(
            ServerAudioChunkMsg(
                timestamp=3.0,
                audio_base64="AQI=",
                format=AudioEncoding.LINEAR16,
                sample_rate=16_000,
                status=MsgStatus.COMPLETED,
            )
        )
        return FakeAgent()

    monkeypatch.setattr(provider, "activate_agent", activate_agent)

    with TestClient(app) as client:
        bearer = _login(client)
        session = _create_session(client, bearer, language="English")
        websocket_url = urlsplit(session["connection"]["websocket_url"])
        relay_token = parse_qs(websocket_url.query)["token"][0].rstrip("=")

        with client.websocket_connect(
            websocket_url.path,
            headers={"origin": "http://testserver"},
            subprotocols=["svara-relay", f"svara-token.{relay_token}"],
        ) as socket:
            assert socket.accepted_subprotocol == "svara-relay"
            assert socket.receive_json() == {"type": "connected"}
            assert socket.receive_json() == {"type": "state", "state": "listening"}
            transcript = socket.receive_json()
            assert transcript["type"] == "transcript"
            assert transcript["speaker"] == "agent"
            assert transcript["text"] == "Your account is ready."
            assert socket.receive_json() == {"type": "state", "state": "speaking"}
            assert socket.receive_bytes() == b"\x01\x02"
            assert socket.receive_json() == {"type": "state", "state": "listening"}
            socket.send_bytes(b"\x03\x04")
            socket.send_json({"type": "end"})
            with pytest.raises(WebSocketDisconnect):
                socket.receive_json()

        archive = client.get(
            "/v1/conversations",
            headers={"Authorization": f"Bearer {bearer}"},
        )

    assert captured_audio == [b"\x03\x04"]
    assert captured_variables["conversation_ref"] == TEST_CONVERSATION_REF
    assert captured_variables["user_name"] == "Rahul"
    assert captured_variables["service_provider_name"] == "By the Brew"
    assert captured_variables["service_location"] == "By the Brew"
    assert captured_variables["business_hours"] == "Daily 9:00 AM–10:00 PM (Asia/Kolkata)"
    assert archive.status_code == 200
    assert archive.json()["total"] == 1
    assert archive.json()["items"][0]["provider"] == "sarvam"


@pytest.mark.asyncio
async def test_sarvam_termination_is_idempotent_before_the_relay_connects(
    tmp_path: Path,
) -> None:
    settings = settings_for_database(
        tmp_path / "sarvam-termination.sqlite3",
        voice_provider="sarvam",
        sarvam_api_key="test-api-key",
        sarvam_org_id="test-organisation",
        sarvam_workspace_id="test-workspace",
        sarvam_agent_id="test-agent",
        sarvam_agent_version=2,
    )
    provider = SarvamVoiceProvider(settings)

    await provider.terminate_session(
        provider_session_id="provider-session",
        idempotency_key="local-session",
    )
    await provider.terminate_session(
        provider_session_id="provider-session",
        idempotency_key="local-session",
    )


def test_authenticated_profile_is_minimal_and_customer_scoped(api: ApiHarness) -> None:
    unauthenticated = api.client.get("/v1/me")
    assert unauthenticated.status_code == 401

    token = _login(api.client)
    response = api.client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "user_id": "00000000-0000-4000-8000-000000000003",
        "customer_id": "00000000-0000-4000-8000-000000000002",
        "role": "customer",
        "full_name": "Rahul Mehta",
        "first_name": "Rahul",
        "initials": "RM",
        "email": "rahul@example.com",
        "workspace_name": "Acme Workspace",
        "preferred_language": "English",
        "plan_name": "Essential",
        "agent_name": "Asha",
        "agent_opening_message": "Hello Rahul, how can I help you today?",
        "voice_mode": "mock",
    }


def test_mock_completion_populates_browser_conversation_archive(api: ApiHarness) -> None:
    token = _login(api.client)
    auth_headers = {"Authorization": f"Bearer {token}"}
    session = _create_session(api.client, token)

    before_completion = api.client.get("/v1/conversations", headers=auth_headers)
    assert before_completion.status_code == 200
    assert before_completion.json() == {"items": [], "total": 0}

    completion_payload = {
        "resolution": "resolved",
        "summary": "Rahul confirmed his plan details.",
        "transcript": [
            {"speaker": "customer", "text": "Which plan am I on?"},
            {"speaker": "agent", "text": "You are on the Essential plan."},
        ],
        "duration_seconds": 18,
    }
    completion = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/mock-complete",
        headers=auth_headers,
        json=completion_payload,
    )

    assert completion.status_code == 200
    detail = completion.json()
    assert detail["id"] == session["session_id"]
    assert detail["provider"] == "mock"
    assert detail["resolution"] == "resolved"
    assert detail["summary"] == completion_payload["summary"]
    assert detail["transcript"] == [
        {**turn, "timestamp": None} for turn in completion_payload["transcript"]
    ]
    serialized = json.dumps(detail)
    assert "conversation_ref" not in serialized
    assert "provider_session_id" not in serialized
    assert TEST_CONVERSATION_REF not in serialized

    retry = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/mock-complete",
        headers=auth_headers,
        json={**completion_payload, "summary": "A retry must not replace the first result."},
    )
    assert retry.status_code == 200
    assert retry.json()["summary"] == completion_payload["summary"]

    archive = api.client.get("/v1/conversations", headers=auth_headers)
    assert archive.status_code == 200
    assert archive.json()["total"] == 1
    assert archive.json()["items"][0]["id"] == session["session_id"]

    stored_detail = api.client.get(
        f"/v1/conversations/{session['session_id']}",
        headers=auth_headers,
    )
    assert stored_detail.status_code == 200
    assert stored_detail.json() == detail


def test_conversation_detail_is_not_discoverable_outside_scope(api: ApiHarness) -> None:
    token = _login(api.client)
    response = api.client.get(
        "/v1/conversations/20000000-0000-4000-8000-000000000003",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Conversation not found."}


def test_mock_completion_is_hidden_when_sarvam_provider_is_selected(tmp_path: Path) -> None:
    settings = settings_for_database(
        tmp_path / "no-mock-completion.sqlite3",
        voice_provider="sarvam",
        sarvam_api_key="test-api-key",
        sarvam_org_id="test-organisation",
        sarvam_workspace_id="test-workspace",
        sarvam_agent_id="test-agent",
    )

    with TestClient(create_app(settings)) as client:
        token = _login(client)
        response = client.post(
            "/v1/voice/sessions/00000000-0000-4000-8000-000000000099/mock-complete",
            headers={"Authorization": f"Bearer {token}"},
            json={"resolution": "resolved"},
        )

    assert response.status_code == 404
    assert response.json() == {"detail": "Not found"}


def test_admin_login_and_profile_do_not_require_a_customer_record(api: ApiHarness) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    response = api.client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "user_id": DEMO_ADMIN_USER_ID,
        "customer_id": None,
        "role": "admin",
        "full_name": "Ananya Rao",
        "first_name": "Ananya",
        "initials": "AR",
        "email": DEMO_ADMIN_EMAIL,
        "workspace_name": "Acme Workspace",
        "preferred_language": None,
        "plan_name": None,
        "agent_name": None,
        "agent_opening_message": None,
        "voice_mode": "mock",
    }

    voice = api.client.post(
        "/v1/voice/sessions",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    conversations = api.client.get(
        "/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert voice.status_code == 403
    assert conversations.status_code == 403


def test_customer_management_requires_an_explicit_admin_role(api: ApiHarness) -> None:
    token = _login(api.client)
    headers = {"Authorization": f"Bearer {token}"}
    customer_id = "00000000-0000-4000-8000-000000000002"

    responses = (
        api.client.get("/v1/customers", headers=headers),
        api.client.post(
            "/v1/customers",
            headers=headers,
            json={"full_name": "No Access", "email": "no-access@example.com"},
        ),
        api.client.get(f"/v1/customers/{customer_id}", headers=headers),
        api.client.post(
            f"/v1/customers/{customer_id}/access/invitation",
            headers=headers,
        ),
        api.client.post(
            f"/v1/customers/{customer_id}/access/revoke",
            headers=headers,
        ),
        api.client.patch(
            f"/v1/customers/{customer_id}",
            headers=headers,
            json={"expected_revision": 1, "full_name": "Unauthorized change"},
        ),
        api.client.patch(
            f"/v1/customers/{customer_id}/agent-configuration",
            headers=headers,
            json={"expected_revision": 1, "tone": "warm"},
        ),
    )

    for response in responses:
        assert response.status_code == 403
        assert response.json() == {"detail": "Administrator access is required."}


@pytest.mark.parametrize(
    ("email", "invalid_shape"),
    [
        (DEMO_ADMIN_EMAIL, "linked-admin"),
        ("rahul@example.com", "unlinked-customer"),
        ("rahul@example.com", "unsupported-role"),
    ],
)
def test_authentication_fails_closed_for_invalid_role_profile_combinations(
    api: ApiHarness,
    email: str,
    invalid_shape: str,
) -> None:
    token = _login(api.client, email)
    with sqlite3.connect(api.database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        if invalid_shape == "linked-admin":
            connection.execute(
                "UPDATE users SET customer_id = ? WHERE id = ?",
                ("00000000-0000-4000-8000-000000000002", DEMO_ADMIN_USER_ID),
            )
        elif invalid_shape == "unlinked-customer":
            connection.execute(
                "UPDATE users SET customer_id = NULL WHERE id = ?",
                ("00000000-0000-4000-8000-000000000003",),
            )
        else:
            connection.execute(
                "UPDATE users SET role = 'owner' WHERE id = ?",
                ("00000000-0000-4000-8000-000000000003",),
            )
        connection.commit()

    response = api.client.get(
        "/v1/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    relogin = api.client.post("/v1/auth/demo-login", json={"email": email})

    assert response.status_code == 401
    assert response.json() == {"detail": "Could not validate credentials"}
    assert relogin.status_code == 401
    assert relogin.json() == {"detail": "Invalid credentials"}


@pytest.mark.parametrize(
    "invalid_display_name",
    ["   ", "A" * 161],
    ids=["blank", "overlong"],
)
def test_malformed_admin_display_name_is_rejected_before_customer_write(
    api: ApiHarness,
    invalid_display_name: str,
) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    endpoint = "/v1/customers/00000000-0000-4000-8000-000000000006"
    original_plan = _query_one(
        api.database_path,
        "SELECT plan_name FROM customers WHERE id = ?",
        ("00000000-0000-4000-8000-000000000006",),
    )
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            (invalid_display_name, DEMO_ADMIN_USER_ID),
        )
        connection.commit()

    update = api.client.patch(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
        json={"expected_revision": 1, "plan_name": "Unauthorized change"},
    )
    relogin = api.client.post("/v1/auth/demo-login", json={"email": DEMO_ADMIN_EMAIL})

    assert update.status_code == 401
    assert update.json() == {"detail": "Could not validate credentials"}
    assert relogin.status_code == 401
    assert relogin.json() == {"detail": "Invalid credentials"}
    assert _count(api.database_path, "admin_audit_events") == 0
    assert (
        _query_one(
            api.database_path,
            "SELECT plan_name FROM customers WHERE id = ?",
            ("00000000-0000-4000-8000-000000000006",),
        )
        == original_plan
    )


def test_actor_display_name_is_trimmed_before_audit_snapshot(api: ApiHarness) -> None:
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            ("  Ananya Rao  ", DEMO_ADMIN_USER_ID),
        )
        connection.commit()
    token = _login(api.client, DEMO_ADMIN_EMAIL)

    updated = api.client.patch(
        "/v1/customers/00000000-0000-4000-8000-000000000006",
        headers={"Authorization": f"Bearer {token}"},
        json={"expected_revision": 1, "plan_name": "Enterprise"},
    )

    assert updated.status_code == 200
    assert updated.json()["recent_audit_events"][0]["actor_display_name"] == "Ananya Rao"


def test_demo_login_rejects_a_customer_deactivated_by_an_admin(api: ApiHarness) -> None:
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    deactivated = api.client.patch(
        "/v1/customers/00000000-0000-4000-8000-000000000002",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"expected_revision": 1, "is_active": False},
    )
    assert deactivated.status_code == 200

    login = api.client.post(
        "/v1/auth/demo-login",
        json={"email": "rahul@example.com"},
    )

    assert login.status_code == 401
    assert login.json() == {"detail": "Invalid credentials"}
    assert login.headers["www-authenticate"] == "Bearer"


def test_admin_can_filter_search_and_paginate_tenant_customers(api: ApiHarness) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}

    all_customers = api.client.get("/v1/customers", headers=headers)
    assert all_customers.status_code == 200
    assert all_customers.headers["cache-control"] == "no-store"
    assert all_customers.json()["total"] == 5
    assert len(all_customers.json()["items"]) == 5
    assert set(all_customers.json()["items"][0]) == {
        "id",
        "external_ref",
        "full_name",
        "initials",
        "preferred_language",
        "plan_name",
        "is_active",
        "created_at",
        "conversation_count",
        "resolved_conversation_count",
        "last_conversation_at",
    }

    inactive = api.client.get("/v1/customers?status=inactive", headers=headers)
    assert inactive.status_code == 200
    assert inactive.json()["total"] == 1
    assert inactive.json()["items"][0]["full_name"] == "Meera Iyer"

    by_name = api.client.get("/v1/customers?query=%20PRIYA%20", headers=headers)
    assert by_name.status_code == 200
    assert by_name.json()["total"] == 1
    assert by_name.json()["items"][0]["external_ref"] == "CUS-1187"

    by_reference = api.client.get("/v1/customers?query=cus-1274", headers=headers)
    assert by_reference.status_code == 200
    assert by_reference.json()["total"] == 1
    assert by_reference.json()["items"][0]["full_name"] == "Arjun Nair"

    page = api.client.get("/v1/customers?limit=2&offset=2", headers=headers)
    assert page.status_code == 200
    assert page.json()["total"] == 5
    assert len(page.json()["items"]) == 2


def test_admin_onboards_invites_revokes_and_reinvites_a_customer(api: ApiHarness) -> None:
    provider = StubInvitationProvider()
    api.client.app.state.invitation_provider = provider
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}

    created = api.client.post(
        "/v1/customers",
        headers=headers,
        json={
            "full_name": "  Devika Rao  ",
            "email": "  DEVIKA@EXAMPLE.COM  ",
            "preferred_language": "Hindi",
            "plan_name": "Growth",
        },
    )

    assert created.status_code == 201, created.text
    assert created.headers["cache-control"] == "no-store"
    customer = created.json()
    customer_id = customer["id"]
    assert customer["external_ref"].startswith("CUS-")
    assert customer["email"] == "devika@example.com"
    assert customer["access"]["email"] == "devika@example.com"
    assert customer["access"]["status"] == "pending"
    assert customer["access"]["is_active"] is True
    assert customer["access"]["invited_at"] is not None
    assert customer["access"]["expires_at"] is not None
    assert customer["access"]["accepted_at"] is None
    assert {event["action"] for event in customer["recent_audit_events"]} == {
        "customer.created",
        "customer.access_invitation_sent",
    }
    assert provider.calls == [("create", "devika@example.com")]

    duplicate = api.client.post(
        "/v1/customers",
        headers=headers,
        json={"full_name": "Duplicate", "email": "DEVIKA@example.com"},
    )
    assert duplicate.status_code == 409
    assert provider.calls == [("create", "devika@example.com")]

    revoked = api.client.post(
        f"/v1/customers/{customer_id}/access/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["access"]["status"] == "revoked"
    assert revoked.json()["access"]["is_active"] is False
    assert provider.calls[-1] == ("revoke", "inv_test_1")

    reinvited = api.client.post(
        f"/v1/customers/{customer_id}/access/invitation",
        headers=headers,
    )
    assert reinvited.status_code == 200, reinvited.text
    assert reinvited.json()["access"]["status"] == "pending"
    assert reinvited.json()["access"]["is_active"] is True
    assert provider.calls[-1] == ("create", "devika@example.com")
    assert _query_one(
        api.database_path,
        "SELECT invitation_status, clerk_invitation_id, is_active FROM users WHERE customer_id = ?",
        (customer_id,),
    ) == ("pending", "inv_test_2", 1)


def test_customer_creation_is_retained_and_invitation_is_queued_when_clerk_fails(
    api: ApiHarness,
) -> None:
    provider = StubInvitationProvider(fail_create=True)
    api.client.app.state.invitation_provider = provider
    token = _login(api.client, DEMO_ADMIN_EMAIL)

    created = api.client.post(
        "/v1/customers",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "full_name": "Maya Sen",
            "email": "maya@example.com",
            "external_ref": "CUS-MAYA",
        },
    )

    assert created.status_code == 201, created.text
    assert created.headers["retry-after"] == "17"
    assert created.json()["access"]["status"] == "queued"
    assert created.json()["access"]["is_active"] is False
    assert created.json()["recent_audit_events"][0]["action"] == "customer.created"
    assert _query_one(
        api.database_path,
        "SELECT is_active, invitation_status, clerk_invitation_id FROM users WHERE email = ?",
        ("maya@example.com",),
    ) == (0, "queued", None)


def test_revoked_queued_access_can_be_reinvited_with_a_new_generation(api: ApiHarness) -> None:
    provider = StubInvitationProvider(fail_create=True)
    api.client.app.state.invitation_provider = provider
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}

    created = api.client.post(
        "/v1/customers",
        headers=headers,
        json={"full_name": "Retry User", "email": "retry-generation@example.com"},
    )
    assert created.status_code == 201
    customer_id = created.json()["id"]
    assert created.json()["access"]["status"] == "queued"

    revoked = api.client.post(
        f"/v1/customers/{customer_id}/access/revoke",
        headers=headers,
    )
    assert revoked.status_code == 200
    assert revoked.json()["access"]["status"] == "revoked"

    provider.fail_create = False
    reinvited = api.client.post(
        f"/v1/customers/{customer_id}/access/invitation",
        headers=headers,
    )
    assert reinvited.status_code == 200
    assert reinvited.json()["access"]["status"] == "pending"
    assert reinvited.json()["access"]["is_active"] is True
    assert provider.calls == [
        ("create", "retry-generation@example.com"),
        ("create", "retry-generation@example.com"),
    ]
    assert _query_one(
        api.database_path,
        "SELECT access_generation, invitation_status, clerk_invitation_id "
        "FROM users WHERE customer_id = ?",
        (customer_id,),
    ) == (3, "pending", "inv_test_1")


def test_failed_invitation_replacement_is_durable_and_retries_safely(
    api: ApiHarness,
) -> None:
    provider = StubInvitationProvider()
    api.client.app.state.invitation_provider = provider
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    created = api.client.post(
        "/v1/customers",
        headers=headers,
        json={"full_name": "Ravi Das", "email": "ravi@example.com"},
    )
    assert created.status_code == 201
    customer_id = created.json()["id"]

    provider.fail_revoke = True
    failed = api.client.post(
        f"/v1/customers/{customer_id}/access/invitation",
        headers=headers,
    )
    assert failed.status_code == 200
    assert failed.headers["retry-after"] == "23"
    assert failed.json()["access"]["status"] == "queued"
    assert failed.json()["access"]["is_active"] is False
    assert _query_one(
        api.database_path,
        "SELECT clerk_invitation_id FROM users WHERE customer_id = ?",
        (customer_id,),
    ) == ("inv_test_1",)

    provider.fail_revoke = False
    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE clerk_invitation_outbox SET available_at = ? WHERE status = 'pending'",
            ("2000-01-01 00:00:00+00:00",),
        )
        connection.commit()
    retried = api.client.post(
        f"/v1/customers/{customer_id}/access/invitation",
        headers=headers,
    )
    assert retried.status_code == 200
    assert retried.json()["access"]["status"] == "pending"
    assert provider.calls[-2:] == [
        ("revoke", "inv_test_1"),
        ("create", "ravi@example.com"),
    ]


def test_revocation_supersedes_an_older_queued_invitation(tmp_path: Path) -> None:
    database_path = tmp_path / "superseded-invitation.sqlite3"
    settings = settings_for_database(
        database_path,
        clerk_outbox_retry_base_seconds=1,
        clerk_outbox_retry_max_seconds=1,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        provider = StubInvitationProvider(fail_create=True)
        client.app.state.invitation_provider = provider
        token = _login(client, DEMO_ADMIN_EMAIL)
        headers = {"Authorization": f"Bearer {token}"}
        created = client.post(
            "/v1/customers",
            headers=headers,
            json={"full_name": "Superseded User", "email": "superseded@example.com"},
        )
        assert created.status_code == 201
        customer_id = created.json()["id"]
        revoked = client.post(
            f"/v1/customers/{customer_id}/access/revoke",
            headers=headers,
        )
        assert revoked.status_code == 200
        assert revoked.json()["access"]["status"] == "revoked"

        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "UPDATE clerk_invitation_outbox SET available_at = ? WHERE status = 'pending'",
                ("2000-01-01 00:00:00+00:00",),
            )
            connection.commit()
        provider.fail_create = False
        first_results = asyncio.run(
            process_ready_invitation_jobs(
                app.state.database.session_factory,
                provider=provider,
                settings=settings,
                worker_id="test-worker",
            )
        )
        assert [result.state for result in first_results] == ["succeeded"]
        second_results = asyncio.run(
            process_ready_invitation_jobs(
                app.state.database.session_factory,
                provider=provider,
                settings=settings,
                worker_id="test-worker",
            )
        )
        assert second_results == []

    assert _query_one(
        database_path,
        "SELECT clerk_user_id, invitation_status, is_active FROM users WHERE email = ?",
        ("superseded@example.com",),
    ) == (None, "revoked", 0)
    assert provider.calls == [("create", "superseded@example.com")]


def test_customer_detail_contains_scoped_stats_orders_and_recent_conversations(
    api: ApiHarness,
) -> None:
    customer_token = _login(api.client)
    session = _create_session(api.client, customer_token)
    completion = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/mock-complete",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={
            "resolution": " Success ",
            "summary": "Rahul's request was resolved.",
            "duration_seconds": 21,
        },
    )
    assert completion.status_code == 200

    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    response = api.client.get(
        "/v1/customers/00000000-0000-4000-8000-000000000002",
        headers={"Authorization": f"Bearer {admin_token}"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    detail = response.json()
    assert detail["email"] == "rahul@example.com"
    assert detail["open_order_count"] == 1
    assert detail["conversation_count"] == 1
    assert detail["resolved_conversation_count"] == 1
    assert detail["profile_revision"] == 1
    assert detail["agent_configuration"]["display_name"] == "Asha"
    assert detail["agent_configuration"]["revision"] == 1
    assert detail["agent_configuration"]["updated_at"] is not None
    assert detail["recent_audit_events"] == []
    assert detail["last_conversation_at"] is not None
    assert len(detail["recent_conversations"]) == 1
    assert detail["recent_conversations"][0]["id"] == session["session_id"]
    serialized = json.dumps(detail)
    assert "conversation_ref" not in serialized
    assert "provider_session_id" not in serialized


def test_uncompleted_voice_session_is_not_reported_as_a_saved_conversation(
    api: ApiHarness,
) -> None:
    customer_token = _login(api.client)
    _create_session(api.client, customer_token)
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    detail = api.client.get(
        "/v1/customers/00000000-0000-4000-8000-000000000002",
        headers=admin_headers,
    )
    customer_list = api.client.get(
        "/v1/customers?query=CUS-1042",
        headers=admin_headers,
    )

    assert detail.status_code == 200
    assert detail.json()["conversation_count"] == 0
    assert detail.json()["resolved_conversation_count"] == 0
    assert detail.json()["last_conversation_at"] is None
    assert detail.json()["recent_conversations"] == []
    assert customer_list.status_code == 200
    assert customer_list.json()["items"][0]["conversation_count"] == 0
    assert customer_list.json()["items"][0]["last_conversation_at"] is None


def test_admin_patch_trims_allowlisted_fields_and_rejects_invalid_payloads(
    api: ApiHarness,
) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    customer_id = "00000000-0000-4000-8000-000000000006"
    endpoint = f"/v1/customers/{customer_id}"

    updated = api.client.patch(
        endpoint,
        headers=headers,
        json={
            "expected_revision": 1,
            "full_name": "  Priya S. Shah  ",
            "preferred_language": "  Gujarati  ",
            "plan_name": "  Enterprise  ",
        },
    )
    assert updated.status_code == 200
    assert updated.headers["cache-control"] == "no-store"
    assert updated.json()["full_name"] == "Priya S. Shah"
    assert updated.json()["initials"] == "PS"
    assert updated.json()["preferred_language"] == "Gujarati"
    assert updated.json()["plan_name"] == "Enterprise"
    assert updated.json()["profile_revision"] == 2
    assert updated.json()["recent_audit_events"][0]["action"] == "customer.profile_updated"
    assert updated.json()["recent_audit_events"][0]["changed_fields"] == [
        "full_name",
        "preferred_language",
        "plan_name",
    ]
    assert updated.json()["recent_audit_events"][0]["revision"] == 2
    assert updated.json()["recent_audit_events"][0]["actor_display_name"] == "Ananya Rao"
    assert "Priya S. Shah" not in json.dumps(updated.json()["recent_audit_events"][0])

    stale = api.client.patch(
        endpoint,
        headers=headers,
        json={"expected_revision": 1, "plan_name": "Stale plan"},
    )
    assert stale.status_code == 409
    assert stale.json() == {
        "detail": "Customer profile was updated by another administrator. Refresh and try again."
    }
    no_op = api.client.patch(
        endpoint,
        headers=headers,
        json={"expected_revision": 2, "full_name": "Priya S. Shah"},
    )
    assert no_op.status_code == 400
    assert no_op.json() == {"detail": "No customer changes were detected."}
    assert _count(api.database_path, "admin_audit_events") == 1

    invalid_payloads = (
        {},
        {"expected_revision": 1},
        {"expected_revision": "2", "full_name": "Strict revision"},
        {"expected_revision": 1, "full_name": "   "},
        {"expected_revision": 1, "preferred_language": None},
        {"expected_revision": 1, "is_active": "false"},
        {"expected_revision": 1, "tenant_id": "attacker-tenant"},
        {"expected_revision": 1, "external_ref": "CUS-REASSIGNED"},
    )
    for payload in invalid_payloads:
        rejected = api.client.patch(endpoint, headers=headers, json=payload)
        assert rejected.status_code == 422

    deactivated = api.client.patch(
        endpoint,
        headers=headers,
        json={"expected_revision": 2, "is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False
    assert deactivated.json()["profile_revision"] == 3
    assert deactivated.json()["recent_audit_events"][0]["changed_fields"] == ["is_active"]
    assert _count(api.database_path, "admin_audit_events") == 2


def test_profile_update_rolls_back_when_audit_insert_fails(api: ApiHarness) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    customer_id = "00000000-0000-4000-8000-000000000006"
    endpoint = f"/v1/customers/{customer_id}"
    state_before = _query_one(
        api.database_path,
        """
        SELECT customers.full_name, customer_profile_states.revision,
               customer_profile_states.updated_at
        FROM customers
        JOIN customer_profile_states
          ON customer_profile_states.tenant_id = customers.tenant_id
         AND customer_profile_states.customer_id = customers.id
        WHERE customers.id = ?
        """,
        (customer_id,),
    )

    response = _patch_with_forced_audit_insert_failure(
        api,
        endpoint=endpoint,
        token=token,
        payload={"expected_revision": 1, "full_name": "Uncommitted profile name"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to update customer."}
    assert (
        _query_one(
            api.database_path,
            """
        SELECT customers.full_name, customer_profile_states.revision,
               customer_profile_states.updated_at
        FROM customers
        JOIN customer_profile_states
          ON customer_profile_states.tenant_id = customers.tenant_id
         AND customer_profile_states.customer_id = customers.id
        WHERE customers.id = ?
        """,
            (customer_id,),
        )
        == state_before
    )
    assert _count(api.database_path, "admin_audit_events") == 0

    detail = api.client.get(
        endpoint,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["full_name"] == state_before[0]
    assert detail.json()["profile_revision"] == state_before[1]
    assert detail.json()["recent_audit_events"] == []


def test_agent_configuration_update_rolls_back_when_audit_insert_fails(
    api: ApiHarness,
) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    customer_id = "00000000-0000-4000-8000-000000000006"
    endpoint = f"/v1/customers/{customer_id}/agent-configuration"
    state_before = _query_one(
        api.database_path,
        """
        SELECT tone, revision, updated_at
        FROM customer_agent_configurations
        WHERE customer_id = ?
        """,
        (customer_id,),
    )

    response = _patch_with_forced_audit_insert_failure(
        api,
        endpoint=endpoint,
        token=token,
        payload={"expected_revision": 1, "tone": "warm"},
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "Unable to update agent configuration."}
    assert (
        _query_one(
            api.database_path,
            """
        SELECT tone, revision, updated_at
        FROM customer_agent_configurations
        WHERE customer_id = ?
        """,
            (customer_id,),
        )
        == state_before
    )
    assert _count(api.database_path, "admin_audit_events") == 0

    detail = api.client.get(
        f"/v1/customers/{customer_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail.status_code == 200
    assert detail.json()["agent_configuration"]["tone"] == state_before[0]
    assert detail.json()["agent_configuration"]["revision"] == state_before[1]
    assert detail.json()["recent_audit_events"] == []


def test_audit_event_preserves_actor_display_name_after_user_rename(
    api: ApiHarness,
) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "/v1/customers/00000000-0000-4000-8000-000000000006"

    updated = api.client.patch(
        endpoint,
        headers=headers,
        json={"expected_revision": 1, "plan_name": "Enterprise"},
    )
    assert updated.status_code == 200
    historical_event_id = updated.json()["recent_audit_events"][0]["id"]

    with sqlite3.connect(api.database_path) as connection:
        connection.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            ("Renamed Administrator", DEMO_ADMIN_USER_ID),
        )
        connection.commit()

    detail = api.client.get(endpoint, headers=headers)

    assert detail.status_code == 200
    historical_event = detail.json()["recent_audit_events"][0]
    assert historical_event["id"] == historical_event_id
    assert historical_event["actor_display_name"] == "Ananya Rao"
    assert _query_one(
        api.database_path,
        "SELECT actor_display_name FROM admin_audit_events WHERE id = ?",
        (historical_event_id,),
    ) == ("Ananya Rao",)


def test_runtime_opening_message_rejects_repeated_fields_and_bounds_expansion() -> None:
    repeated_template = " ".join(["{first_name}"] * 41)
    unexpectedly_large_first_name = "A" * 10_000

    assert not is_supported_opening_message_template(repeated_template)
    assert (
        render_opening_message(repeated_template, first_name=unexpectedly_large_first_name)
        == FALLBACK_AGENT_OPENING_MESSAGE
    )
    assert (
        render_opening_message("Welcome {first_name}", first_name=unexpectedly_large_first_name)
        == FALLBACK_AGENT_OPENING_MESSAGE
    )
    assert len(FALLBACK_AGENT_OPENING_MESSAGE) <= MAX_RUNTIME_OPENING_MESSAGE_LENGTH
    with pytest.raises(ValidationError):
        RuntimeAgentConfiguration(
            display_name="Asha",
            opening_message="x" * (MAX_RUNTIME_OPENING_MESSAGE_LENGTH + 1),
            tone="professional",
            instructions="Safe instructions",
            revision=1,
        )


def test_agent_configuration_revision_validation_no_op_and_audit(api: ApiHarness) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    customer_id = "00000000-0000-4000-8000-000000000006"
    endpoint = f"/v1/customers/{customer_id}/agent-configuration"

    invalid_payloads = (
        {},
        {"expected_revision": 1},
        {"expected_revision": "1", "tone": "warm"},
        {"expected_revision": 1, "display_name": "   "},
        {"expected_revision": 1, "opening_message": "Hello {customer_name}"},
        {"expected_revision": 1, "opening_message": "Hello {first_name:}"},
        {
            "expected_revision": 1,
            "opening_message": "Hello {first_name}, again {first_name}",
        },
        {"expected_revision": 1, "opening_message": "Hello {first_name"},
        {"expected_revision": 1, "tone": "friendly"},
        {"expected_revision": 1, "instructions": "x" * 2_001},
        {"expected_revision": 1, "instructions": None},
        {"expected_revision": 1, "tenant_id": "attacker-tenant"},
    )
    for payload in invalid_payloads:
        rejected = api.client.patch(endpoint, headers=headers, json=payload)
        assert rejected.status_code == 422, (payload, rejected.text)

    updated = api.client.patch(
        endpoint,
        headers=headers,
        json={
            "expected_revision": 1,
            "display_name": "  Mira  ",
            "opening_message": "  Namaste {first_name}, welcome back.  ",
            "tone": " warm ",
            "instructions": "   ",
        },
    )

    assert updated.status_code == 200
    assert updated.headers["cache-control"] == "no-store"
    configuration = updated.json()["agent_configuration"]
    assert configuration["display_name"] == "Mira"
    assert configuration["opening_message"] == "Namaste {first_name}, welcome back."
    assert configuration["tone"] == "warm"
    assert configuration["instructions"] == ""
    assert configuration["revision"] == 2
    assert configuration["updated_at"] is not None
    audit_event = updated.json()["recent_audit_events"][0]
    assert audit_event["action"] == "customer.agent_configuration_updated"
    assert audit_event["changed_fields"] == [
        "display_name",
        "opening_message",
        "tone",
        "instructions",
    ]
    assert audit_event["revision"] == 2
    assert audit_event["actor_display_name"] == "Ananya Rao"
    assert "Mira" not in json.dumps(audit_event)

    stale = api.client.patch(
        endpoint,
        headers=headers,
        json={"expected_revision": 1, "tone": "concise"},
    )
    assert stale.status_code == 409
    assert stale.json() == {
        "detail": (
            "Agent configuration was updated by another administrator. Refresh and try again."
        )
    }
    no_op = api.client.patch(
        endpoint,
        headers=headers,
        json={"expected_revision": 2, "display_name": "Mira"},
    )
    assert no_op.status_code == 400
    assert no_op.json() == {"detail": "No agent configuration changes were detected."}
    assert _count(api.database_path, "admin_audit_events") == 1


def test_customer_detail_limits_audit_history_to_ten_newest_events(api: ApiHarness) -> None:
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "/v1/customers/00000000-0000-4000-8000-000000000006"
    current_name = "Priya Shah"

    for expected_revision in range(1, 13):
        current_name = "Priya Shah A" if current_name != "Priya Shah A" else "Priya Shah B"
        updated = api.client.patch(
            endpoint,
            headers=headers,
            json={
                "expected_revision": expected_revision,
                "full_name": current_name,
            },
        )
        assert updated.status_code == 200

    detail = api.client.get(endpoint, headers=headers)

    assert detail.status_code == 200
    assert detail.json()["profile_revision"] == 13
    audit_events = detail.json()["recent_audit_events"]
    assert len(audit_events) == 10
    assert [event["revision"] for event in audit_events] == list(range(13, 3, -1))
    assert _count(api.database_path, "admin_audit_events") == 12


def test_missing_agent_configuration_uses_defaults_and_can_be_created(
    api: ApiHarness,
) -> None:
    _insert_out_of_scope_orders(api.database_path)
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    customer_id = "10000000-0000-4000-8000-000000000001"

    detail = api.client.get(f"/v1/customers/{customer_id}", headers=headers)

    assert detail.status_code == 200
    assert detail.json()["profile_revision"] == 1
    assert detail.json()["agent_configuration"] == {
        "display_name": "Asha",
        "opening_message": "Hello {first_name}, how can I help you today?",
        "tone": "professional",
        "instructions": (
            "Help the customer clearly, use only verified account information, "
            "and protect their privacy."
        ),
        "revision": 1,
        "updated_at": None,
    }
    assert detail.json()["recent_audit_events"] == []

    created = api.client.patch(
        f"/v1/customers/{customer_id}/agent-configuration",
        headers=headers,
        json={"expected_revision": 1, "tone": "warm"},
    )
    assert created.status_code == 200
    assert created.json()["agent_configuration"]["revision"] == 2
    assert created.json()["agent_configuration"]["tone"] == "warm"
    assert created.json()["recent_audit_events"][0]["changed_fields"] == ["tone"]

    profile_created = api.client.patch(
        f"/v1/customers/{customer_id}",
        headers=headers,
        json={"expected_revision": 1, "plan_name": "Growth"},
    )
    assert profile_created.status_code == 200
    assert profile_created.json()["profile_revision"] == 2
    assert profile_created.json()["recent_audit_events"][0]["action"] == (
        "customer.profile_updated"
    )


def test_on_start_renders_scoped_agent_configuration_without_auditing_its_values(
    api: ApiHarness,
) -> None:
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    configured = api.client.patch(
        "/v1/customers/00000000-0000-4000-8000-000000000002/agent-configuration",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={
            "expected_revision": 1,
            "display_name": "Sana",
            "opening_message": "Namaste {first_name}. How may I help?",
            "tone": "concise",
            "instructions": "Answer only from verified order data.",
        },
    )
    assert configured.status_code == 200

    customer_token = _login(api.client)
    session = _create_session(api.client, customer_token)
    response = api.client.post(
        "/v1/sarvam/hooks/on-start",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "interaction_id": "interaction-configured-agent",
        },
    )

    assert response.status_code == 200
    assert response.json()["agent"] == {
        "display_name": "Sana",
        "opening_message": "Namaste Rahul. How may I help?",
        "tone": "concise",
        "instructions": "Answer only from verified order data.",
        "revision": 2,
    }
    request_payload, response_payload = _query_one(
        api.database_path,
        "SELECT request_payload, response_payload FROM tool_audit_logs WHERE session_id = ?",
        (session["session_id"],),
    )
    assert json.loads(response_payload) == {
        "agent_configuration_revision": 2,
        "safe_to_continue": True,
    }
    serialized_audit = f"{request_payload} {response_payload}"
    assert "Sana" not in serialized_audit
    assert "verified order data" not in serialized_audit


def test_admin_cannot_discover_or_patch_a_cross_tenant_customer(api: ApiHarness) -> None:
    _insert_out_of_scope_orders(api.database_path)
    token = _login(api.client, DEMO_ADMIN_EMAIL)
    headers = {"Authorization": f"Bearer {token}"}
    foreign_id = "20000000-0000-4000-8000-000000000002"

    detail = api.client.get(f"/v1/customers/{foreign_id}", headers=headers)
    update = api.client.patch(
        f"/v1/customers/{foreign_id}",
        headers=headers,
        json={"expected_revision": 1, "full_name": "Tenant leak"},
    )
    configuration_update = api.client.patch(
        f"/v1/customers/{foreign_id}/agent-configuration",
        headers=headers,
        json={"expected_revision": 1, "tone": "warm"},
    )
    search = api.client.get(
        "/v1/customers?query=Other%20Tenant%20Customer",
        headers=headers,
    )

    assert detail.status_code == 404
    assert detail.json() == {"detail": "Customer not found."}
    assert update.status_code == 404
    assert update.json() == {"detail": "Customer not found."}
    assert configuration_update.status_code == 404
    assert configuration_update.json() == {"detail": "Customer not found."}
    assert search.status_code == 200
    assert search.json() == {"items": [], "total": 0}


def test_customer_deactivation_is_blocked_while_a_voice_slot_is_active(
    api: ApiHarness,
) -> None:
    customer_token = _login(api.client)
    session = _create_session(api.client, customer_token)
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    admin_headers = {"Authorization": f"Bearer {admin_token}"}
    endpoint = "/v1/customers/00000000-0000-4000-8000-000000000002"

    blocked = api.client.patch(
        endpoint,
        headers=admin_headers,
        json={"expected_revision": 1, "is_active": False},
    )

    assert blocked.status_code == 409
    assert blocked.json() == {
        "detail": "The customer's active voice session must end before deactivation."
    }
    assert (
        _query_one(
            api.database_path,
            "SELECT is_active FROM customers WHERE id = ?",
            ("00000000-0000-4000-8000-000000000002",),
        )[0]
        == 1
    )

    completion = api.client.post(
        f"/v1/voice/sessions/{session['session_id']}/mock-complete",
        headers={"Authorization": f"Bearer {customer_token}"},
        json={"resolution": "resolved"},
    )
    assert completion.status_code == 200
    deactivated = api.client.patch(
        endpoint,
        headers=admin_headers,
        json={"expected_revision": 1, "is_active": False},
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


def test_existing_demo_tenant_receives_missing_seed_rows(tmp_path: Path) -> None:
    database_path = tmp_path / "existing-demo-tenant.sqlite3"
    unseeded_settings = settings_for_database(database_path, seed_demo_data=False)
    with TestClient(create_app(unseeded_settings)):
        pass

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            INSERT INTO tenants (id, slug, name, is_active, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "00000000-0000-4000-8000-000000000001",
                "acme",
                "Existing Acme Workspace",
                1,
                "2026-01-01 00:00:00.000000",
            ),
        )
        connection.commit()

    seeded_settings = settings_for_database(database_path, seed_demo_data=True)
    with TestClient(create_app(seeded_settings)) as client:
        admin_token = _login(client, DEMO_ADMIN_EMAIL)
        customers = client.get(
            "/v1/customers",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert customers.status_code == 200
        assert customers.json()["total"] == 5

    assert _count(database_path, "customer_profile_states") == 5
    assert _count(database_path, "customer_agent_configurations") == 5
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            UPDATE customer_agent_configurations
            SET display_name = ?, revision = ?
            WHERE tenant_id = ? AND customer_id = ?
            """,
            (
                "Edited agent",
                7,
                "00000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000002",
            ),
        )
        connection.execute(
            """
            UPDATE customer_profile_states SET revision = ?
            WHERE tenant_id = ? AND customer_id = ?
            """,
            (
                4,
                "00000000-0000-4000-8000-000000000001",
                "00000000-0000-4000-8000-000000000002",
            ),
        )
        connection.execute(
            "DELETE FROM customer_agent_configurations WHERE customer_id = ?",
            ("00000000-0000-4000-8000-000000000006",),
        )
        connection.execute(
            "DELETE FROM customer_profile_states WHERE customer_id = ?",
            ("00000000-0000-4000-8000-000000000006",),
        )
        connection.commit()

    with TestClient(create_app(seeded_settings)) as client:
        admin_token = _login(client, DEMO_ADMIN_EMAIL)
        rahul = client.get(
            "/v1/customers/00000000-0000-4000-8000-000000000002",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        priya = client.get(
            "/v1/customers/00000000-0000-4000-8000-000000000006",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert rahul.status_code == 200
        assert rahul.json()["profile_revision"] == 4
        assert rahul.json()["agent_configuration"]["display_name"] == "Edited agent"
        assert rahul.json()["agent_configuration"]["revision"] == 7
        assert priya.status_code == 200
        assert priya.json()["profile_revision"] == 1
        assert priya.json()["agent_configuration"]["revision"] == 1


def test_phase_two_development_database_gains_new_tables_and_accepts_audit(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "phase-two-compatible.sqlite3"
    phase_two_tables = {
        "conversation_outcomes",
        "customer_orders",
        "customers",
        "tenants",
        "tool_audit_logs",
        "users",
        "voice_sessions",
    }
    legacy_metadata = MetaData()
    for table_name in phase_two_tables:
        Base.metadata.tables[table_name].to_metadata(legacy_metadata)
    sync_engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    legacy_metadata.create_all(sync_engine)
    sync_engine.dispose()

    settings = settings_for_database(database_path, seed_demo_data=True)
    with TestClient(create_app(settings)) as client:
        admin_token = _login(client, DEMO_ADMIN_EMAIL)
        updated = client.patch(
            "/v1/customers/00000000-0000-4000-8000-000000000006",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"expected_revision": 1, "plan_name": "Scale"},
        )

    assert updated.status_code == 200
    assert updated.json()["profile_revision"] == 2
    assert _count(database_path, "customer_profile_states") == 5
    assert _count(database_path, "customer_agent_configurations") == 5
    assert _count(database_path, "admin_audit_events") == 1


def test_initial_alembic_migration_creates_the_complete_fresh_schema(tmp_path: Path) -> None:
    database_path = tmp_path / "alembic-fresh.sqlite3"
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    alembic_config.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{database_path.as_posix()}",
    )

    command.upgrade(alembic_config, "head")

    with sqlite3.connect(database_path) as connection:
        table_names = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        revision = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        audit_foreign_keys = connection.execute(
            "PRAGMA foreign_key_list(admin_audit_events)"
        ).fetchall()
        audit_columns = {
            row[1]: (row[2], row[3])
            for row in connection.execute("PRAGMA table_info(admin_audit_events)").fetchall()
        }
        user_columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    assert table_names == {*Base.metadata.tables, "alembic_version"}
    assert revision == ("20260923_0008",)
    assert {foreign_key[2] for foreign_key in audit_foreign_keys} == {
        "customers",
        "tenants",
        "users",
    }
    assert audit_columns["actor_display_name"] == ("VARCHAR(160)", 1)
    assert {
        "clerk_invitation_id",
        "invitation_status",
        "invitation_sent_at",
        "invitation_expires_at",
        "invitation_accepted_at",
        "invited_by_user_id",
        "access_generation",
        "clerk_last_event_at",
    }.issubset(user_columns)
    command.check(alembic_config)

    settings = settings_for_database(database_path, seed_demo_data=True)
    with TestClient(create_app(settings)) as client:
        token = _login(client, DEMO_ADMIN_EMAIL)
        detail = client.get(
            "/v1/customers/00000000-0000-4000-8000-000000000002",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert detail.status_code == 200
        assert detail.json()["profile_revision"] == 1


def test_cors_preflight_allows_customer_patch(api: ApiHarness) -> None:
    response = api.client.options(
        "/v1/customers/00000000-0000-4000-8000-000000000002",
        headers={
            "Origin": "http://testserver",
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )

    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]
