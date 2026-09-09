import ssl
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from svara_api.config import Settings
from svara_api.database import database_connect_args, get_db
from svara_api.main import create_app


@pytest.mark.parametrize("flag", ["enable_demo_auth", "seed_demo_data"])
def test_remote_development_database_rejects_demo_flags(flag: str) -> None:
    with pytest.raises(ValidationError, match="only allowed with a local SQLite database"):
        Settings(
            _env_file=None,
            app_env="development",
            database_url="postgresql+asyncpg://user:password@localhost/test",
            **{flag: True},
        )


def test_remote_startup_does_not_initialize_or_seed_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="postgresql+asyncpg://user:password@localhost/test",
        enable_demo_auth=False,
        seed_demo_data=False,
        voice_provider="mock",
    )
    app = create_app(settings)
    create_schema = AsyncMock()
    seed = AsyncMock()
    connect = AsyncMock(side_effect=AssertionError("Startup must not connect to the remote DB"))
    monkeypatch.setattr(app.state.database, "create_schema", create_schema)
    monkeypatch.setattr("svara_api.main.seed_demo_data", seed)
    monkeypatch.setattr(app.state.database.engine.sync_engine, "connect", connect)

    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        response = client.post("/v1/auth/demo-login", json={"email": "test@example.com"})
        assert response.status_code == 404

    create_schema.assert_not_called()
    seed.assert_not_called()
    connect.assert_not_called()


def test_postgres_verify_full_checks_certificate_and_hostname() -> None:
    args = database_connect_args("postgresql+asyncpg://localhost/test", "verify-full")
    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.cert_store_stats()["x509_ca"] > 0


def test_sqlite_does_not_receive_postgres_ssl_arguments() -> None:
    assert database_connect_args("sqlite+aiosqlite:///:memory:", "verify-full") == {
        "check_same_thread": False,
    }


def test_local_postgres_can_explicitly_disable_tls() -> None:
    assert database_connect_args("postgresql+asyncpg://localhost/test", "disable") == {"ssl": False}


def test_supabase_direct_url_can_route_through_an_official_session_pooler() -> None:
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql+asyncpg://postgres:password@db.abcdefghijklmnopqrst.supabase.co/postgres"
        ),
        database_pooler_host="aws-0-ap-southeast-2.pooler.supabase.com",
    )

    url = make_url(settings.resolved_database_url)

    assert url.host == "aws-0-ap-southeast-2.pooler.supabase.com"
    assert url.port == 5432
    assert url.username == "postgres.abcdefghijklmnopqrst"
    assert url.password == "password"


def test_pooler_override_rejects_non_supabase_hosts() -> None:
    settings = Settings(
        _env_file=None,
        database_url=(
            "postgresql+asyncpg://postgres:password@db.abcdefghijklmnopqrst.supabase.co/postgres"
        ),
        database_pooler_host="attacker.example.com",
    )

    with pytest.raises(ValueError, match="official Supabase AWS pooler host"):
        _ = settings.resolved_database_url


def test_production_requires_clerk_auth_configuration() -> None:
    with pytest.raises(
        ValidationError,
        match="Production Clerk authentication configuration is incomplete",
    ):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+asyncpg://user:password@db.example.com/postgres",
            database_ssl_mode="verify-full",
            frontend_origins="https://voice.example.com",
            session_secret="production-session-secret-is-long-and-random",
            sarvam_tool_secret="production-tool-secret-is-long-and-different",
            voice_provider="sarvam",
            enable_demo_auth=False,
            seed_demo_data=False,
            sarvam_api_key="sarvam-api-key",
            sarvam_org_id="sarvam-org",
            sarvam_workspace_id="sarvam-workspace",
            sarvam_agent_id="sarvam-agent",
            sarvam_agent_version=2,
        )


def test_health_reports_unavailable_when_database_resolution_fails() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        enable_demo_auth=False,
        seed_demo_data=False,
        voice_provider="mock",
    )
    app = create_app(settings)

    failing_session = AsyncMock()
    failing_session.execute.side_effect = OSError("Name resolution failed")

    async def failing_db():  # type: ignore[no-untyped-def]
        yield failing_session

    app.dependency_overrides[get_db] = failing_db

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}


def test_production_requires_a_secure_public_voice_relay() -> None:
    with pytest.raises(ValidationError, match="Production voice relay URL must use WSS"):
        Settings(
            _env_file=None,
            app_env="production",
            database_url="postgresql+asyncpg://user:password@db.example.com/postgres",
            database_ssl_mode="verify-full",
            frontend_origins="https://voice.example.com",
            session_secret="production-session-secret-is-long-and-random",
            sarvam_tool_secret="production-tool-secret-is-long-and-different",
            voice_provider="sarvam",
            enable_demo_auth=False,
            seed_demo_data=False,
            sarvam_api_key="sarvam-api-key",
            sarvam_org_id="sarvam-org",
            sarvam_workspace_id="sarvam-workspace",
            sarvam_agent_id="sarvam-agent",
            sarvam_agent_version=2,
            clerk_secret_key="sk_test_valid-looking-test-key",
        )
