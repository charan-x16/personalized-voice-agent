from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from clerk_backend_api import Clerk, models

from ...config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class AccessInvitation:
    invitation_id: str
    sent_at: datetime
    expires_at: datetime | None


class InvitationProviderError(RuntimeError):
    """A sanitized Clerk invitation failure safe to handle at the API boundary."""

    def __init__(
        self,
        *,
        retry_after_seconds: int | None = None,
        error_code: str = "provider_unavailable",
    ) -> None:
        super().__init__("The identity provider could not complete the invitation request.")
        self.retry_after_seconds = retry_after_seconds
        self.error_code = error_code


class InvitationProvider(Protocol):
    async def create_invitation(self, *, email: str) -> AccessInvitation: ...

    async def find_pending_invitation(self, *, email: str) -> AccessInvitation | None: ...

    async def revoke_invitation(self, *, invitation_id: str) -> None: ...


def _timestamp(milliseconds: int | None) -> datetime | None:
    if milliseconds is None:
        return None
    return datetime.fromtimestamp(milliseconds / 1_000, tz=UTC)


def _retry_after(error: Exception) -> int | None:
    headers = getattr(error, "headers", None)
    if headers is None:
        return None
    raw_value = headers.get("retry-after")
    if raw_value is None:
        return None
    try:
        seconds = int(raw_value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


def _status_code(error: Exception) -> int | None:
    for source in (
        error,
        getattr(error, "raw_response", None),
        getattr(error, "response", None),
    ):
        status_code = getattr(source, "status_code", None)
        if isinstance(status_code, int):
            return status_code
    return None


def _provider_error_code(error: Exception) -> str:
    status_code = _status_code(error)
    if status_code == 429:
        return "provider_rate_limited"
    if status_code is not None and 400 <= status_code < 500:
        return "provider_rejected"
    return "provider_unavailable"


def _invitation(value: models.Invitation) -> AccessInvitation | None:
    sent_at = _timestamp(value.created_at)
    if not value.id or sent_at is None:
        return None
    return AccessInvitation(
        invitation_id=value.id,
        sent_at=sent_at,
        expires_at=_timestamp(value.expires_at if isinstance(value.expires_at, int) else None),
    )


class ClerkInvitationProvider:
    def __init__(self, settings: Settings) -> None:
        self._secret_key = settings.clerk_secret_key
        self._redirect_url = settings.resolved_clerk_invitation_redirect_url
        self._expiry_days = settings.clerk_invitation_expiry_days

    async def create_invitation(self, *, email: str) -> AccessInvitation:
        if not self._secret_key:
            raise InvitationProviderError()

        try:
            async with Clerk(bearer_auth=self._secret_key, timeout_ms=5_000) as clerk:
                invitation = await clerk.invitations.create_async(
                    request=models.CreateInvitationRequestBody(
                        email_address=email,
                        redirect_url=self._redirect_url,
                        notify=True,
                        # Existing Clerk users still need an application invitation
                        # so they receive the workspace entry link. Clerk documents
                        # this flag as the supported way to invite an address that is
                        # already registered in the same application instance.
                        ignore_existing=True,
                        expires_in_days=self._expiry_days,
                    )
                )
        except Exception as exc:
            logger.warning(
                "Clerk invitation creation failed",
                extra={"provider_status": getattr(exc, "status_code", None)},
            )
            raise InvitationProviderError(
                retry_after_seconds=_retry_after(exc),
                error_code=_provider_error_code(exc),
            ) from exc

        result = _invitation(invitation)
        if result is None:
            raise InvitationProviderError()
        return result

    async def find_pending_invitation(self, *, email: str) -> AccessInvitation | None:
        if not self._secret_key:
            raise InvitationProviderError()
        try:
            async with Clerk(bearer_auth=self._secret_key, timeout_ms=5_000) as clerk:
                invitations = await clerk.invitations.list_async(
                    status=models.ListInvitationsQueryParamStatus.PENDING,
                    query=email,
                    limit=10,
                    offset=0,
                )
        except Exception as exc:
            logger.warning(
                "Clerk invitation lookup failed",
                extra={"provider_status": _status_code(exc)},
            )
            raise InvitationProviderError(
                retry_after_seconds=_retry_after(exc),
                error_code=_provider_error_code(exc),
            ) from exc

        normalized_email = email.strip().casefold()
        for invitation in invitations:
            if invitation.email_address.strip().casefold() != normalized_email:
                continue
            return _invitation(invitation)
        return None

    async def revoke_invitation(self, *, invitation_id: str) -> None:
        if not self._secret_key:
            raise InvitationProviderError()
        try:
            async with Clerk(bearer_auth=self._secret_key, timeout_ms=5_000) as clerk:
                await clerk.invitations.revoke_async(invitation_id=invitation_id)
        except Exception as exc:
            if _status_code(exc) == 404:
                return
            logger.warning(
                "Clerk invitation revocation failed",
                extra={"provider_status": _status_code(exc)},
            )
            raise InvitationProviderError(
                retry_after_seconds=_retry_after(exc),
                error_code=_provider_error_code(exc),
            ) from exc


def build_invitation_provider(settings: Settings) -> InvitationProvider:
    return ClerkInvitationProvider(settings)
