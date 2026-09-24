from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import secrets
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol
from urllib.parse import urlencode, urlsplit, urlunsplit

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr
from sarvam_conv_ai_sdk import (
    AsyncSamvaadAgent,
    InteractionConfig,
    InteractionType,
    SarvamToolLanguageName,
)
from sarvam_conv_ai_sdk.messages.types import UserIdentifierType

from ...config import Settings

logger = logging.getLogger(__name__)

VoiceTransport = Literal["mock", "websocket"]


@dataclass(frozen=True, slots=True)
class SarvamRelayClaims:
    session_id: str
    conversation_ref: str
    language: str
    expires_at: datetime
    agent_variables: dict[str, str]


@dataclass(frozen=True, slots=True)
class VoiceProviderSession:
    """Connection details returned after a provider accepts a new session."""

    provider_session_id: str
    transport: VoiceTransport
    expires_at: datetime
    websocket_url: str | None = None

    def __post_init__(self) -> None:
        if not self.provider_session_id:
            raise ValueError("provider_session_id must not be empty")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        if self.expires_at <= datetime.now(UTC):
            raise ValueError("expires_at must be in the future")
        if self.transport == "websocket" and not self.websocket_url:
            raise ValueError("websocket transport requires websocket_url")
        if self.websocket_url:
            parsed_url = urlsplit(self.websocket_url)
            loopback = parsed_url.hostname in {"localhost", "127.0.0.1", "::1"}
            if (
                (parsed_url.scheme != "wss" and not (parsed_url.scheme == "ws" and loopback))
                or parsed_url.hostname is None
                or parsed_url.username is not None
                or parsed_url.password is not None
            ):
                raise ValueError("websocket_url must be an authenticated wss URL")


class VoiceProviderUnavailableError(RuntimeError):
    """A definitive provider rejection that did not create a remote session."""


class VoiceProviderBootstrapAmbiguousError(RuntimeError):
    """A bootstrap failure that may have created an unreachable remote session.

    Provider adapters should raise this after a request may have left the process
    (for example, a timeout while waiting for a response). The API retains the
    customer's active slot until the local session expires or reconciliation can
    prove that no remote session exists. Unexpected adapter exceptions receive
    the same conservative treatment.
    """

    def __init__(
        self,
        message: str = "The voice provider has not confirmed whether the session started.",
        *,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        if retry_after_seconds is not None and retry_after_seconds < 1:
            raise ValueError("retry_after_seconds must be positive")
        self.retry_after_seconds = retry_after_seconds


class VoiceProviderTerminationError(RuntimeError):
    """A safe provider-termination failure with explicit retry semantics.

    ``ambiguous`` means the request may have reached the provider, so callers
    must retain the local active slot until an idempotent retry confirms that
    the remote session is no longer running.
    """

    def __init__(
        self,
        message: str = "The voice session could not be stopped yet.",
        *,
        ambiguous: bool,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        if retry_after_seconds is not None and retry_after_seconds < 1:
            raise ValueError("retry_after_seconds must be positive")
        self.ambiguous = ambiguous
        self.retry_after_seconds = retry_after_seconds


class VoiceProvider(Protocol):
    """Provider boundary used by the API without exposing provider credentials.

    Implementations should use ``session_id`` as a stable provider idempotency key
    when the provider contract supports one. A definitive pre-acceptance rejection
    raises :class:`VoiceProviderUnavailableError`; post-send uncertainty raises
    :class:`VoiceProviderBootstrapAmbiguousError`. Without provider-side idempotency
    or lookup by this key, an interrupted request cannot be conclusively reconciled.
    """

    name: str

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession: ...

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None: ...


class MockVoiceProvider:
    name = "mock"

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        # Touch the inputs so the mock exercises the same boundary as a real provider.
        del session_id, language, agent_variables
        return VoiceProviderSession(
            provider_session_id=f"mock_{secrets.token_urlsafe(18)}",
            transport="mock",
            expires_at=expires_at,
        )

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        # There is no remote resource in mock mode. Repeating this operation is
        # deliberately safe so the API exercises production retry semantics.
        del provider_session_id, idempotency_key


class SarvamVoiceProvider:
    """Server-side Sarvam SDK adapter with an ephemeral browser relay token."""

    name = "sarvam"

    def __init__(self, settings: Settings) -> None:
        required_configuration = {
            "SARVAM_API_KEY": settings.sarvam_api_key,
            "SARVAM_ORG_ID": settings.sarvam_org_id,
            "SARVAM_WORKSPACE_ID": settings.sarvam_workspace_id,
            "SARVAM_AGENT_ID": settings.sarvam_agent_id,
            "SARVAM_AGENT_VERSION": settings.sarvam_agent_version,
        }
        self._missing_configuration = tuple(
            name for name, value in required_configuration.items() if not value
        )
        self._api_key = SecretStr(settings.sarvam_api_key or "")
        self._org_id = settings.sarvam_org_id or ""
        self._workspace_id = settings.sarvam_workspace_id or ""
        self._agent_id = settings.sarvam_agent_id or ""
        self._agent_version = settings.sarvam_agent_version
        self._relay_url = settings.voice_websocket_public_url
        relay_key = base64.urlsafe_b64encode(
            hashlib.sha256(settings.session_secret.encode("utf-8")).digest()
        )
        self._relay_cipher = Fernet(relay_key)
        self._active_agents: dict[str, AsyncSamvaadAgent] = {}
        self._active_agents_lock = asyncio.Lock()

    @staticmethod
    def _language_name(language: str) -> SarvamToolLanguageName | None:
        normalized = language.strip().casefold().split("-", maxsplit=1)[0]
        languages = {
            "as": SarvamToolLanguageName.ASSAMESE,
            "assamese": SarvamToolLanguageName.ASSAMESE,
            "bn": SarvamToolLanguageName.BENGALI,
            "bengali": SarvamToolLanguageName.BENGALI,
            "en": SarvamToolLanguageName.ENGLISH,
            "english": SarvamToolLanguageName.ENGLISH,
            "gu": SarvamToolLanguageName.GUJARATI,
            "gujarati": SarvamToolLanguageName.GUJARATI,
            "hi": SarvamToolLanguageName.HINDI,
            "hindi": SarvamToolLanguageName.HINDI,
            "kn": SarvamToolLanguageName.KANNADA,
            "kannada": SarvamToolLanguageName.KANNADA,
            "kok": SarvamToolLanguageName.KONKANI,
            "konkani": SarvamToolLanguageName.KONKANI,
            "ml": SarvamToolLanguageName.MALAYALAM,
            "malayalam": SarvamToolLanguageName.MALAYALAM,
            "mr": SarvamToolLanguageName.MARATHI,
            "marathi": SarvamToolLanguageName.MARATHI,
            "or": SarvamToolLanguageName.ODIA,
            "odia": SarvamToolLanguageName.ODIA,
            "pa": SarvamToolLanguageName.PUNJABI,
            "punjabi": SarvamToolLanguageName.PUNJABI,
            "ta": SarvamToolLanguageName.TAMIL,
            "tamil": SarvamToolLanguageName.TAMIL,
            "te": SarvamToolLanguageName.TELUGU,
            "telugu": SarvamToolLanguageName.TELUGU,
        }
        return languages.get(normalized)

    def decode_relay_token(self, token: str) -> SarvamRelayClaims:
        if not token or len(token) > 8_192:
            raise ValueError("Invalid voice relay token")
        try:
            payload = json.loads(self._relay_cipher.decrypt(token.encode("ascii")))
        except (InvalidToken, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid voice relay token") from exc

        if not isinstance(payload, dict) or payload.get("v") != 1:
            raise ValueError("Invalid voice relay token")
        session_id = payload.get("session_id")
        conversation_ref = payload.get("conversation_ref")
        language = payload.get("language")
        expires_at_value = payload.get("expires_at")
        agent_variables = payload.get("agent_variables")
        if (
            not isinstance(session_id, str)
            or not isinstance(conversation_ref, str)
            or not isinstance(language, str)
            or not isinstance(expires_at_value, int)
            or not isinstance(agent_variables, dict)
            or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in agent_variables.items()
            )
        ):
            raise ValueError("Invalid voice relay token")
        expires_at = datetime.fromtimestamp(expires_at_value, tz=UTC)
        if expires_at <= datetime.now(UTC):
            raise ValueError("Voice relay token has expired")
        return SarvamRelayClaims(
            session_id=session_id,
            conversation_ref=conversation_ref,
            language=language,
            expires_at=expires_at,
            agent_variables=dict(agent_variables),
        )

    async def activate_agent(
        self,
        claims: SarvamRelayClaims,
        *,
        agent_variables: Mapping[str, str],
        initial_bot_message: str | None,
        audio_callback: Callable[[Any], Awaitable[None]],
        transcript_callback: Callable[[Any], Awaitable[None]],
        event_callback: Callable[[Any], Awaitable[None]],
    ) -> AsyncSamvaadAgent:
        config = InteractionConfig(
            user_identifier_type=UserIdentifierType.CUSTOM,
            user_identifier=claims.session_id,
            org_id=self._org_id,
            workspace_id=self._workspace_id,
            app_id=self._agent_id,
            version=self._agent_version,
            interaction_type=InteractionType.CALL,
            sample_rate=16_000,
            agent_variables=dict(agent_variables),
            initial_language_name=self._language_name(claims.language),
            initial_bot_message=initial_bot_message,
        )
        agent = AsyncSamvaadAgent(
            api_key=self._api_key,
            config=config,
            audio_callback=audio_callback,
            transcript_callback=transcript_callback,
            event_callback=event_callback,
        )
        async with self._active_agents_lock:
            if claims.session_id in self._active_agents:
                raise VoiceProviderUnavailableError("This voice session is already connected.")
            self._active_agents[claims.session_id] = agent
        try:
            await agent.start()
            if not await agent.wait_for_connect(timeout=15.0):
                raise VoiceProviderUnavailableError("Sarvam did not establish the voice session.")
            return agent
        except Exception:
            await self.release_agent(claims.session_id, agent)
            raise

    async def release_agent(
        self,
        session_id: str,
        agent: AsyncSamvaadAgent,
    ) -> None:
        async with self._active_agents_lock:
            if self._active_agents.get(session_id) is agent:
                self._active_agents.pop(session_id, None)
        try:
            await asyncio.wait_for(agent.stop(), timeout=10.0)
        except Exception:
            logger.exception("Unable to cleanly release Sarvam session %s", session_id)

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        if self._missing_configuration:
            logger.error(
                "Sarvam voice provider configuration is incomplete: %s",
                ", ".join(self._missing_configuration),
            )
            raise VoiceProviderUnavailableError(
                "Voice sessions are unavailable because the provider is not fully configured."
            )

        conversation_ref = agent_variables.get("conversation_ref")
        if not conversation_ref:
            raise VoiceProviderUnavailableError("Voice session context is incomplete.")
        relay_payload = json.dumps(
            {
                "v": 1,
                "session_id": session_id,
                "conversation_ref": conversation_ref,
                "language": language,
                "expires_at": int(expires_at.timestamp()),
                "agent_variables": dict(agent_variables),
            },
            separators=(",", ":"),
        ).encode("utf-8")
        relay_token = self._relay_cipher.encrypt(relay_payload).decode("ascii")
        parsed_url = urlsplit(self._relay_url)
        websocket_url = urlunsplit(
            (
                parsed_url.scheme,
                parsed_url.netloc,
                parsed_url.path,
                urlencode({"token": relay_token}),
                "",
            )
        )
        return VoiceProviderSession(
            provider_session_id=session_id,
            transport="websocket",
            expires_at=expires_at,
            websocket_url=websocket_url,
        )

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        del idempotency_key

        if self._missing_configuration:
            logger.error(
                "Sarvam voice provider configuration is incomplete: %s",
                ", ".join(self._missing_configuration),
            )
            raise VoiceProviderTerminationError(
                "The voice session cannot be stopped because the provider is not fully configured.",
                ambiguous=False,
            )

        async with self._active_agents_lock:
            agent = self._active_agents.pop(provider_session_id, None)
        if agent is not None:
            try:
                await agent.stop()
            except Exception as exc:
                raise VoiceProviderTerminationError(
                    "The Sarvam voice session could not be stopped yet.",
                    ambiguous=True,
                    retry_after_seconds=2,
                ) from exc

    async def shutdown(self) -> None:
        async with self._active_agents_lock:
            agents = list(self._active_agents.values())
            self._active_agents.clear()
        if agents:
            await asyncio.gather(
                *(asyncio.wait_for(agent.stop(), timeout=10.0) for agent in agents),
                return_exceptions=True,
            )


def build_voice_provider(settings: Settings) -> VoiceProvider:
    if settings.voice_provider == "mock":
        return MockVoiceProvider()
    return SarvamVoiceProvider(settings)
