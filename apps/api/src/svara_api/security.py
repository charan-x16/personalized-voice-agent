from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings
from .database import get_db
from .dependencies import get_app_settings
from .models import Customer, Tenant, User

_BEARER_SCHEME = HTTPBearer(auto_error=False)
_BASE64URL_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_TOKEN_CLAIMS = frozenset({"exp", "iat", "sub", "tenant_id"})
_MAX_TOKEN_LENGTH = 2_048
_MAX_CLAIM_LENGTH = 256
_MAX_TOKEN_LIFETIME_SECONDS = 60 * 60
_CLOCK_SKEW_SECONDS = 30
_AUTHENTICATION_ERROR = "Could not validate credentials"
_SUPPORTED_ROLES = frozenset({"admin", "customer"})
_MAX_ACTOR_DISPLAY_NAME_LENGTH = 160


@dataclass(frozen=True, slots=True)
class Actor:
    """The database-verified identity available to authenticated route handlers."""

    user_id: str
    tenant_id: str
    customer_id: str | None
    role: str
    display_name: str


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """The deliberately small set of claims accepted in an access token."""

    subject: str
    tenant_id: str
    issued_at: int
    expires_at: int


class InvalidAccessToken(ValueError):
    """Raised when an access token is malformed, invalid, or no longer usable."""


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _base64url_decode(value: str) -> bytes:
    if not value or not _BASE64URL_PATTERN.fullmatch(value):
        raise InvalidAccessToken

    padding = "=" * (-len(value) % 4)
    try:
        decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidAccessToken from exc

    # Reject non-canonical encodings so that each token has one representation.
    if not hmac.compare_digest(_base64url_encode(decoded), value):
        raise InvalidAccessToken
    return decoded


def _json_object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise InvalidAccessToken
        value[key] = item
    return value


def _timestamp(now: datetime | None = None) -> int:
    instant = now or datetime.now(UTC)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("A timezone-aware datetime is required")
    return int(instant.timestamp())


def create_access_token(
    *,
    user_id: str,
    tenant_id: str,
    secret: str,
    ttl_seconds: int,
    now: datetime | None = None,
) -> str:
    """Create a compact, URL-safe, HMAC-SHA256 signed access token."""

    if not secret:
        raise ValueError("An access-token secret is required")
    if not 1 <= ttl_seconds <= _MAX_TOKEN_LIFETIME_SECONDS:
        raise ValueError("Access-token lifetime is outside the supported range")
    if not _is_valid_claim_string(user_id) or not _is_valid_claim_string(tenant_id):
        raise ValueError("Token identity claims must be non-empty strings")

    issued_at = _timestamp(now)
    payload = {
        "exp": issued_at + ttl_seconds,
        "iat": issued_at,
        "sub": user_id,
        "tenant_id": tenant_id,
    }
    encoded_payload = _base64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = hmac.digest(secret.encode("utf-8"), encoded_payload.encode("ascii"), "sha256")
    return f"{encoded_payload}.{_base64url_encode(signature)}"


def decode_access_token(
    token: str,
    *,
    secret: str,
    now: datetime | None = None,
) -> AccessTokenClaims:
    """Verify and decode an access token, accepting only the documented claims."""

    if not secret or not token or len(token) > _MAX_TOKEN_LENGTH:
        raise InvalidAccessToken

    parts = token.split(".")
    if len(parts) != 2:
        raise InvalidAccessToken
    encoded_payload, encoded_signature = parts
    if not encoded_payload or not _BASE64URL_PATTERN.fullmatch(encoded_payload):
        raise InvalidAccessToken

    signature = _base64url_decode(encoded_signature)
    if len(signature) != hashlib.sha256().digest_size:
        raise InvalidAccessToken
    expected_signature = hmac.digest(
        secret.encode("utf-8"), encoded_payload.encode("ascii", errors="strict"), "sha256"
    )
    if not hmac.compare_digest(signature, expected_signature):
        raise InvalidAccessToken

    try:
        payload = json.loads(
            _base64url_decode(encoded_payload),
            object_pairs_hook=_json_object_without_duplicate_keys,
        )
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError, InvalidAccessToken) as exc:
        raise InvalidAccessToken from exc

    if not isinstance(payload, dict) or set(payload) != _TOKEN_CLAIMS:
        raise InvalidAccessToken

    subject = payload.get("sub")
    tenant_id = payload.get("tenant_id")
    issued_at = payload.get("iat")
    expires_at = payload.get("exp")
    if not _is_valid_claim_string(subject) or not _is_valid_claim_string(tenant_id):
        raise InvalidAccessToken
    if type(issued_at) is not int or type(expires_at) is not int:
        raise InvalidAccessToken
    if issued_at < 0 or expires_at <= issued_at:
        raise InvalidAccessToken
    if expires_at - issued_at > _MAX_TOKEN_LIFETIME_SECONDS:
        raise InvalidAccessToken

    current_time = _timestamp(now)
    if issued_at > current_time + _CLOCK_SKEW_SECONDS or expires_at <= current_time:
        raise InvalidAccessToken

    return AccessTokenClaims(
        subject=subject,
        tenant_id=tenant_id,
        issued_at=issued_at,
        expires_at=expires_at,
    )


def _is_valid_claim_string(value: object) -> bool:
    return isinstance(value, str) and value == value.strip() and 0 < len(value) <= _MAX_CLAIM_LENGTH


def _normalize_actor_display_name(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not 1 <= len(normalized) <= _MAX_ACTOR_DISPLAY_NAME_LENGTH:
        return None
    return normalized


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=_AUTHENTICATION_ERROR,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_actor(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(_BEARER_SCHEME),
    ],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> Actor:
    """Resolve a signed bearer token to an active, tenant-bound database user."""

    if credentials is None or credentials.scheme.casefold() != "bearer":
        raise _unauthorized()

    try:
        claims = decode_access_token(credentials.credentials, secret=settings.session_secret)
    except (InvalidAccessToken, UnicodeError, ValueError):
        raise _unauthorized() from None

    row = (
        await db.execute(
            select(User, Tenant)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.id == claims.subject,
                User.tenant_id == claims.tenant_id,
                User.is_active.is_(True),
                Tenant.id == claims.tenant_id,
                Tenant.is_active.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise _unauthorized()

    user, tenant = row
    actor_display_name = _normalize_actor_display_name(user.display_name)
    if actor_display_name is None or not await is_actor_account_eligible(
        db, user=user, tenant=tenant
    ):
        raise _unauthorized()

    return Actor(
        user_id=user.id,
        tenant_id=tenant.id,
        customer_id=user.customer_id,
        role=user.role,
        display_name=actor_display_name,
    )


async def is_actor_account_eligible(
    db: AsyncSession,
    *,
    user: User,
    tenant: Tenant,
) -> bool:
    """Return whether a database user can safely become an authenticated actor."""

    if (
        user.tenant_id != tenant.id
        or not user.is_active
        or not tenant.is_active
        or not _is_valid_claim_string(user.role)
        or user.role not in _SUPPORTED_ROLES
        or _normalize_actor_display_name(user.display_name) is None
        or (user.role == "customer" and user.customer_id is None)
        or (user.role == "admin" and user.customer_id is not None)
    ):
        return False

    if user.customer_id is not None:
        customer_id = await db.scalar(
            select(Customer.id).where(
                Customer.id == user.customer_id,
                Customer.tenant_id == tenant.id,
                Customer.is_active.is_(True),
            )
        )
        if customer_id is None:
            return False
    return True


def require_tenant_admin(
    actor: Annotated[Actor, Depends(get_current_actor)],
) -> Actor:
    """Allow only explicitly assigned tenant administrators."""

    if actor.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access is required.",
        )
    return actor


async def require_voice_tool_key(
    settings: Annotated[Settings, Depends(get_app_settings)],
    provided_key: Annotated[str | None, Header(alias="X-Voice-Tool-Key")] = None,
) -> None:
    """Require Sarvam tool requests to present the configured shared secret."""

    expected = settings.sarvam_tool_secret.encode("utf-8")
    provided = (provided_key or "").encode("utf-8")
    if not expected or not hmac.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
        )


def generate_conversation_ref() -> str:
    """Return an opaque reference carrying 256 bits of cryptographic entropy."""

    return f"cvr_{secrets.token_urlsafe(32)}"


def hash_conversation_ref(reference: str) -> str:
    """Hash an opaque conversation reference before database storage or lookup."""

    return hashlib.sha256(reference.encode("utf-8")).hexdigest()
