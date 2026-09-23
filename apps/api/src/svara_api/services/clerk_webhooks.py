from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from svix.webhooks import Webhook, WebhookVerificationError

from ..config import Settings
from ..models import ClerkWebhookEvent, Tenant, User, utc_now
from ..security import application_email_candidates

_SUPPORTED_EVENTS = frozenset({"user.created", "user.updated", "user.deleted"})


class WebhookConfigurationError(RuntimeError):
    pass


class WebhookPayloadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WebhookProcessResult:
    duplicate: bool
    status: str


def verify_clerk_webhook(
    body: bytes,
    headers: Mapping[str, str],
    *,
    settings: Settings,
) -> dict[str, Any]:
    """Verify Clerk's signature against the untouched request body."""

    secret = settings.clerk_webhook_signing_secret
    if not secret:
        raise WebhookConfigurationError("Clerk webhook verification is not configured")
    Webhook(secret).verify(body, dict(headers))
    try:
        event: object = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookPayloadError("The verified webhook body is not valid JSON") from exc
    if not isinstance(event, dict):
        raise WebhookPayloadError("The verified webhook body must be an object")
    return event


def _event_timestamp(value: object) -> datetime:
    if type(value) is not int or value < 0:
        raise WebhookPayloadError("The webhook timestamp is invalid")
    try:
        return datetime.fromtimestamp(value / 1_000, tz=UTC)
    except (OverflowError, OSError, ValueError) as exc:
        raise WebhookPayloadError("The webhook timestamp is invalid") from exc


def _safe_string(value: object, *, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        return None
    return normalized


def _verified_primary_email(data: Mapping[str, Any]) -> str | None:
    primary_id = _safe_string(data.get("primary_email_address_id"), maximum=160)
    addresses = data.get("email_addresses")
    if primary_id is None or not isinstance(addresses, list):
        return None
    for address in addresses:
        if not isinstance(address, dict) or address.get("id") != primary_id:
            continue
        verification = address.get("verification")
        if not isinstance(verification, dict) or verification.get("status") != "verified":
            return None
        email = _safe_string(address.get("email_address"), maximum=254)
        if email is None or "@" not in email:
            return None
        return email.casefold()
    return None


def _event_is_blocked(data: Mapping[str, Any]) -> bool:
    return any(data.get(key) is True for key in ("banned", "locked", "deprovisioned"))


async def _matching_user(
    db: AsyncSession,
    *,
    clerk_user_id: str,
    verified_email: str | None,
    settings: Settings,
) -> User | None:
    user = await db.scalar(
        select(User).where(User.clerk_user_id == clerk_user_id).limit(1).with_for_update()
    )
    if user is not None or verified_email is None:
        return user

    candidates = application_email_candidates(verified_email, settings=settings)
    rows = (
        await db.scalars(
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                func.lower(User.email).in_(candidates),
                User.role == "customer",
                User.customer_id.is_not(None),
                User.clerk_user_id.is_(None),
                User.invitation_status.in_(("queued", "pending")),
                Tenant.is_active.is_(True),
            )
            .limit(2)
            .with_for_update()
        )
    ).all()
    return rows[0] if len(rows) == 1 else None


async def process_clerk_webhook(
    db: AsyncSession,
    *,
    message_id: str,
    event: Mapping[str, Any],
    settings: Settings,
) -> WebhookProcessResult:
    """Reconcile a verified Clerk user event exactly once."""

    normalized_message_id = _safe_string(message_id, maximum=160)
    event_type = _safe_string(event.get("type"), maximum=100)
    data = event.get("data")
    event_at = _event_timestamp(event.get("timestamp"))
    if normalized_message_id is None or event_type is None or not isinstance(data, dict):
        raise WebhookPayloadError("The webhook envelope is invalid")
    object_id = _safe_string(data.get("id"), maximum=160)
    now = utc_now()

    existing = await db.scalar(
        select(ClerkWebhookEvent.message_id).where(
            ClerkWebhookEvent.message_id == normalized_message_id
        )
    )
    if existing is not None:
        await db.rollback()
        return WebhookProcessResult(duplicate=True, status="duplicate")

    receipt = ClerkWebhookEvent(
        message_id=normalized_message_id,
        event_type=event_type,
        object_id=object_id,
        event_at=event_at,
        status="ignored",
        received_at=now,
        processed_at=now,
    )
    db.add(receipt)

    if event_type not in _SUPPORTED_EVENTS or object_id is None:
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            return WebhookProcessResult(duplicate=True, status="duplicate")
        return WebhookProcessResult(duplicate=False, status="ignored")

    verified_email = _verified_primary_email(data) if event_type != "user.deleted" else None
    user = await _matching_user(
        db,
        clerk_user_id=object_id,
        verified_email=verified_email,
        settings=settings,
    )
    if user is not None:
        last_event_at = user.clerk_last_event_at
        if last_event_at is not None and last_event_at.tzinfo is None:
            last_event_at = last_event_at.replace(tzinfo=UTC)
        if last_event_at is None or event_at >= last_event_at:
            if event_type == "user.deleted":
                user.access_generation = max(user.access_generation, 0) + 1
                user.clerk_user_id = None
                user.is_active = False
                user.invitation_status = "revoked"
                user.invitation_expires_at = event_at
            elif _event_is_blocked(data):
                user.access_generation = max(user.access_generation, 0) + 1
                user.is_active = False
                user.invitation_status = "revoked"
            elif user.invitation_status in {"queued", "pending"}:
                user.clerk_user_id = object_id
                user.is_active = True
                user.invitation_status = "accepted"
                user.invitation_accepted_at = event_at
            user.clerk_last_event_at = event_at
            receipt.status = "processed"

    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        return WebhookProcessResult(duplicate=True, status="duplicate")
    return WebhookProcessResult(duplicate=False, status=receipt.status)


__all__ = [
    "WebhookConfigurationError",
    "WebhookPayloadError",
    "WebhookProcessResult",
    "WebhookVerificationError",
    "process_clerk_webhook",
    "verify_clerk_webhook",
]
