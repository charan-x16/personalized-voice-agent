from __future__ import annotations

import logging
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, Protocol
from urllib.parse import urlsplit

from ..config import Settings

logger = logging.getLogger(__name__)

VoiceTransport = Literal["mock", "websocket"]


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
            if (
                parsed_url.scheme != "wss"
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
    """Guarded adapter for Sarvam's authenticated Voice Agent session contract.

    Sarvam's public material describes a signed WebSocket/SDK flow, but does not
    currently publish a stable session-bootstrap HTTP contract. Keeping this
    adapter closed prevents us from fabricating an endpoint or accidentally
    exposing a long-lived API key to the browser.
    """

    name = "sarvam"

    def __init__(self, settings: Settings) -> None:
        required_configuration = {
            "SARVAM_API_KEY": settings.sarvam_api_key,
            "SARVAM_ORG_ID": settings.sarvam_org_id,
            "SARVAM_WORKSPACE_ID": settings.sarvam_workspace_id,
            "SARVAM_AGENT_ID": settings.sarvam_agent_id,
        }
        self._missing_configuration = tuple(
            name for name, value in required_configuration.items() if not value
        )

    async def create_session(
        self,
        *,
        session_id: str,
        language: str,
        expires_at: datetime,
        agent_variables: Mapping[str, str],
    ) -> VoiceProviderSession:
        del session_id, language, expires_at, agent_variables

        if self._missing_configuration:
            logger.error(
                "Sarvam voice provider configuration is incomplete: %s",
                ", ".join(self._missing_configuration),
            )
            raise VoiceProviderUnavailableError(
                "Voice sessions are unavailable because the provider is not fully configured."
            )

        logger.warning(
            "Sarvam credentials are configured, but the authenticated session contract "
            "has not been enabled."
        )
        raise VoiceProviderUnavailableError(
            "Voice sessions are temporarily unavailable pending the authenticated "
            "provider session contract."
        )

    async def terminate_session(
        self,
        *,
        provider_session_id: str,
        idempotency_key: str,
    ) -> None:
        del provider_session_id, idempotency_key

        if self._missing_configuration:
            logger.error(
                "Sarvam voice provider configuration is incomplete: %s",
                ", ".join(self._missing_configuration),
            )
            raise VoiceProviderTerminationError(
                "The voice session cannot be stopped because the provider is not fully configured.",
                ambiguous=False,
            )

        logger.warning(
            "Sarvam credentials are configured, but the authenticated termination "
            "contract has not been enabled."
        )
        raise VoiceProviderTerminationError(
            "The voice session could not be stopped because the provider termination "
            "contract is unavailable.",
            ambiguous=False,
        )


def build_voice_provider(settings: Settings) -> VoiceProvider:
    if settings.voice_provider == "mock":
        return MockVoiceProvider()
    return SarvamVoiceProvider(settings)
