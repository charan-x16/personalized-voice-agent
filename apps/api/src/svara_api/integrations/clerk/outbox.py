from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ...config import Settings
from ...models import (
    AdminAuditEvent,
    ClerkInvitationOutbox,
    Customer,
    User,
    utc_now,
)
from .invitations import AccessInvitation, InvitationProvider, InvitationProviderError

logger = logging.getLogger(__name__)

_ACTIVE_JOB_STATUSES = ("pending", "processing")
_INVITATION_SENT_AUDIT_ACTION = "customer.access_invitation_sent"
_INVITATION_FAILED_AUDIT_ACTION = "customer.access_invitation_failed"


@dataclass(frozen=True, slots=True)
class OutboxProcessResult:
    job_id: str
    state: Literal["succeeded", "retry_scheduled", "dead_letter", "not_claimed"]
    retry_after_seconds: int | None = None


def _audit_event(job: ClerkInvitationOutbox, *, action: str) -> AdminAuditEvent:
    return AdminAuditEvent(
        tenant_id=job.tenant_id,
        customer_id=job.customer_id,
        actor_user_id=job.actor_user_id,
        actor_display_name=job.actor_display_name,
        action=action,
        changed_fields=["access_status"],
        revision=1,
        created_at=utc_now(),
    )


async def enqueue_create_invitation(
    db: AsyncSession,
    *,
    customer: Customer,
    user: User,
    actor_user_id: str,
    actor_display_name: str,
) -> ClerkInvitationOutbox:
    """Persist a create-invitation intent in the caller's current transaction."""

    active_job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.user_id == user.id,
            ClerkInvitationOutbox.operation == "create",
            ClerkInvitationOutbox.access_generation == user.access_generation,
            ClerkInvitationOutbox.status.in_(_ACTIVE_JOB_STATUSES),
        )
        .order_by(ClerkInvitationOutbox.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if active_job is not None:
        return active_job

    now = utc_now()
    user.access_generation = max(user.access_generation, 0) + 1
    user.is_active = False
    user.invitation_status = "queued"
    user.invitation_sent_at = None
    user.invitation_expires_at = None
    user.invitation_accepted_at = None
    user.invited_by_user_id = actor_user_id
    job = ClerkInvitationOutbox(
        tenant_id=user.tenant_id,
        customer_id=customer.id,
        user_id=user.id,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        operation="create",
        access_generation=user.access_generation,
        email=user.email,
        invitation_id=user.clerk_invitation_id,
        status="pending",
        attempt_count=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    return job


async def enqueue_revoke_invitation(
    db: AsyncSession,
    *,
    customer: Customer,
    user: User,
    actor_user_id: str,
    actor_display_name: str,
) -> ClerkInvitationOutbox | None:
    """Revoke local access and persist any required provider cleanup."""

    now = utc_now()
    user.access_generation = max(user.access_generation, 0) + 1
    user.is_active = False
    user.invitation_status = "revoked"
    user.invitation_expires_at = now
    user.invited_by_user_id = actor_user_id
    invitation_id = user.clerk_invitation_id
    if not invitation_id:
        return None

    active_job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.user_id == user.id,
            ClerkInvitationOutbox.operation == "revoke",
            ClerkInvitationOutbox.status.in_(_ACTIVE_JOB_STATUSES),
            ClerkInvitationOutbox.invitation_id == invitation_id,
        )
        .order_by(ClerkInvitationOutbox.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if active_job is not None:
        return active_job

    job = ClerkInvitationOutbox(
        tenant_id=user.tenant_id,
        customer_id=customer.id,
        user_id=user.id,
        actor_user_id=actor_user_id,
        actor_display_name=actor_display_name,
        operation="revoke",
        access_generation=user.access_generation,
        invitation_id=invitation_id,
        status="pending",
        attempt_count=0,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    return job


def _retry_delay(
    settings: Settings,
    *,
    attempt_count: int,
    provider_retry_after: int | None,
) -> int:
    if provider_retry_after is not None:
        return min(provider_retry_after, settings.clerk_outbox_retry_max_seconds)
    exponent = max(attempt_count - 1, 0)
    calculated = settings.clerk_outbox_retry_base_seconds * (2**exponent)
    return min(calculated, settings.clerk_outbox_retry_max_seconds)


async def _claim_job(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    settings: Settings,
) -> ClerkInvitationOutbox | None:
    now = utc_now()
    stale_before = now - timedelta(seconds=settings.clerk_outbox_claim_timeout_seconds)
    job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.id == job_id,
            or_(
                (
                    (ClerkInvitationOutbox.status == "pending")
                    & (ClerkInvitationOutbox.available_at <= now)
                ),
                (
                    (ClerkInvitationOutbox.status == "processing")
                    & (ClerkInvitationOutbox.locked_at < stale_before)
                ),
            ),
        )
        .with_for_update(skip_locked=True)
        .execution_options(populate_existing=True)
    )
    if job is None:
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="not_claimed")
    job.status = "processing"
    job.locked_at = now
    job.locked_by = worker_id[:160]
    job.attempt_count += 1
    job.updated_at = now
    await db.commit()
    return job


async def _reschedule_failure(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    error: InvitationProviderError,
    settings: Settings,
) -> OutboxProcessResult:
    job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.id == job_id,
            ClerkInvitationOutbox.status == "processing",
            ClerkInvitationOutbox.locked_by == worker_id[:160],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        await db.rollback()
        return OutboxProcessResult(job_id=job_id, state="not_claimed")

    user = await db.scalar(
        select(User)
        .where(User.id == job.user_id, User.tenant_id == job.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        job.status = "dead_letter"
        job.last_error_code = "access_user_missing"
        job.completed_at = utc_now()
        job.locked_at = None
        job.locked_by = None
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="dead_letter")

    # A verified Clerk account may have linked through a webhook while this
    # invitation attempt was in flight. In that case the desired access state
    # is already satisfied and an invitation error must not downgrade it.
    if (
        job.operation == "create"
        and user.access_generation == job.access_generation
        and user.clerk_user_id is not None
        and user.invitation_status == "accepted"
    ):
        now = utc_now()
        job.status = "succeeded"
        job.completed_at = now
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = "access_already_linked"
        job.updated_at = now
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="succeeded")

    # A newer access command supersedes creation. The only remaining work is
    # cleanup of a previously known invitation, if one exists.
    if job.operation == "create" and user.access_generation != job.access_generation:
        if not job.invitation_id:
            job.status = "succeeded"
            job.completed_at = utc_now()
            job.locked_at = None
            job.locked_by = None
            job.last_error_code = "superseded"
            await db.commit()
            return OutboxProcessResult(job_id=job_id, state="succeeded")
        job.operation = "revoke"
        job.email = None
        job.attempt_count = 0

    is_dead = job.attempt_count >= settings.clerk_outbox_max_attempts
    now = utc_now()
    retry_after = _retry_delay(
        settings,
        attempt_count=job.attempt_count,
        provider_retry_after=error.retry_after_seconds,
    )
    job.status = "dead_letter" if is_dead else "pending"
    job.available_at = now + timedelta(seconds=retry_after)
    job.locked_at = None
    job.locked_by = None
    job.last_error_code = error.error_code
    job.updated_at = now
    job.completed_at = now if is_dead else None

    if job.operation == "create" and user.access_generation == job.access_generation:
        user.is_active = False
        user.invitation_status = "failed" if is_dead else "queued"
        if is_dead:
            db.add(_audit_event(job, action=_INVITATION_FAILED_AUDIT_ACTION))

    await db.commit()
    return OutboxProcessResult(
        job_id=job_id,
        state="dead_letter" if is_dead else "retry_scheduled",
        retry_after_seconds=None if is_dead else retry_after,
    )


async def _complete_create(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    invitation: AccessInvitation,
) -> OutboxProcessResult:
    job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.id == job_id,
            ClerkInvitationOutbox.status == "processing",
            ClerkInvitationOutbox.locked_by == worker_id[:160],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        await db.rollback()
        return OutboxProcessResult(job_id=job_id, state="not_claimed")
    user = await db.scalar(
        select(User)
        .where(User.id == job.user_id, User.tenant_id == job.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        job.operation = "revoke"
        job.email = None
        job.invitation_id = invitation.invitation_id
        job.status = "pending"
        job.attempt_count = 0
        job.available_at = utc_now()
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = "access_user_missing"
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="retry_scheduled", retry_after_seconds=0)

    if (
        user.access_generation == job.access_generation
        and user.clerk_user_id is not None
        and user.invitation_status == "accepted"
    ):
        job.operation = "revoke"
        job.email = None
        job.invitation_id = invitation.invitation_id
        job.status = "pending"
        job.attempt_count = 0
        job.available_at = utc_now()
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = "access_already_linked"
        job.updated_at = utc_now()
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="retry_scheduled", retry_after_seconds=0)

    if user.access_generation != job.access_generation or user.invitation_status == "revoked":
        job.operation = "revoke"
        job.email = None
        job.invitation_id = invitation.invitation_id
        job.status = "pending"
        job.attempt_count = 0
        job.available_at = utc_now()
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = "superseded"
        job.updated_at = utc_now()
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="retry_scheduled", retry_after_seconds=0)

    now = utc_now()
    user.is_active = True
    user.clerk_invitation_id = invitation.invitation_id
    user.invitation_status = "accepted" if user.clerk_user_id else "pending"
    user.invitation_sent_at = invitation.sent_at
    user.invitation_expires_at = invitation.expires_at
    if user.clerk_user_id is None:
        user.invitation_accepted_at = None
    job.invitation_id = invitation.invitation_id
    job.status = "succeeded"
    job.completed_at = now
    job.locked_at = None
    job.locked_by = None
    job.last_error_code = None
    job.updated_at = now
    db.add(_audit_event(job, action=_INVITATION_SENT_AUDIT_ACTION))
    await db.commit()
    return OutboxProcessResult(job_id=job_id, state="succeeded")


async def _complete_revoke(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
) -> OutboxProcessResult:
    job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.id == job_id,
            ClerkInvitationOutbox.status == "processing",
            ClerkInvitationOutbox.locked_by == worker_id[:160],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        await db.rollback()
        return OutboxProcessResult(job_id=job_id, state="not_claimed")
    user = await db.scalar(
        select(User)
        .where(User.id == job.user_id, User.tenant_id == job.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        user is not None
        and user.access_generation == job.access_generation
        and user.clerk_invitation_id == job.invitation_id
    ):
        user.clerk_invitation_id = None
    now = utc_now()
    job.status = "succeeded"
    job.completed_at = now
    job.locked_at = None
    job.locked_by = None
    job.last_error_code = None
    job.updated_at = now
    await db.commit()
    return OutboxProcessResult(job_id=job_id, state="succeeded")


async def _prepare_create_job(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
) -> OutboxProcessResult | None:
    """Resolve stale create work before making an external provider call."""

    job = await db.scalar(
        select(ClerkInvitationOutbox)
        .where(
            ClerkInvitationOutbox.id == job_id,
            ClerkInvitationOutbox.operation == "create",
            ClerkInvitationOutbox.status == "processing",
            ClerkInvitationOutbox.locked_by == worker_id[:160],
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if job is None:
        await db.rollback()
        return None
    user = await db.scalar(
        select(User)
        .where(User.id == job.user_id, User.tenant_id == job.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        job.status = "dead_letter"
        job.completed_at = utc_now()
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = "access_user_missing"
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="dead_letter")

    if user.access_generation != job.access_generation or user.invitation_status == "revoked":
        if job.invitation_id:
            job.operation = "revoke"
            job.email = None
            job.status = "pending"
            job.attempt_count = 0
            job.available_at = utc_now()
            job.locked_at = None
            job.locked_by = None
            job.last_error_code = "superseded"
            job.updated_at = utc_now()
            await db.commit()
            return OutboxProcessResult(
                job_id=job_id,
                state="retry_scheduled",
                retry_after_seconds=0,
            )
        job.status = "succeeded"
        job.completed_at = utc_now()
        job.locked_at = None
        job.locked_by = None
        job.last_error_code = "superseded"
        job.updated_at = utc_now()
        await db.commit()
        return OutboxProcessResult(job_id=job_id, state="succeeded")

    if user.clerk_user_id is None or user.invitation_status != "accepted":
        # End the short read transaction without expiring unrelated ORM
        # instances held by an inline API caller.
        await db.commit()
        return None

    now = utc_now()
    job.status = "succeeded"
    job.completed_at = now
    job.locked_at = None
    job.locked_by = None
    job.last_error_code = "access_already_linked"
    job.updated_at = now
    await db.commit()
    return OutboxProcessResult(job_id=job_id, state="succeeded")


async def process_invitation_job(
    db: AsyncSession,
    *,
    job_id: str,
    worker_id: str,
    provider: InvitationProvider,
    settings: Settings,
) -> OutboxProcessResult:
    """Claim one durable job, call Clerk outside a transaction, then record the result."""

    try:
        job = await _claim_job(
            db,
            job_id=job_id,
            worker_id=worker_id,
            settings=settings,
        )
    except (IntegrityError, SQLAlchemyError):
        await db.rollback()
        logger.exception("Unable to claim Clerk invitation job", extra={"job_id": job_id})
        return OutboxProcessResult(job_id=job_id, state="not_claimed")
    if job is None:
        return OutboxProcessResult(job_id=job_id, state="not_claimed")

    claimed_job_id = job.id
    operation = job.operation
    invitation_id = job.invitation_id
    email = job.email
    if operation == "create":
        linked_result = await _prepare_create_job(
            db,
            job_id=claimed_job_id,
            worker_id=worker_id,
        )
        if linked_result is not None:
            return linked_result

    try:
        if operation == "revoke":
            if invitation_id:
                await provider.revoke_invitation(invitation_id=invitation_id)
            return await _complete_revoke(db, job_id=claimed_job_id, worker_id=worker_id)

        if invitation_id:
            await provider.revoke_invitation(invitation_id=invitation_id)
        if not email:
            raise InvitationProviderError(error_code="invalid_outbox_payload")
        invitation = await provider.find_pending_invitation(email=email)
        if invitation is None:
            invitation = await provider.create_invitation(email=email)
        return await _complete_create(
            db,
            job_id=claimed_job_id,
            worker_id=worker_id,
            invitation=invitation,
        )
    except InvitationProviderError as exc:
        return await _reschedule_failure(
            db,
            job_id=claimed_job_id,
            worker_id=worker_id,
            error=exc,
            settings=settings,
        )
    except SQLAlchemyError:
        await db.rollback()
        logger.exception(
            "Unable to record Clerk invitation job result", extra={"job_id": claimed_job_id}
        )
        return OutboxProcessResult(job_id=claimed_job_id, state="not_claimed")


async def ready_job_ids(db: AsyncSession, *, settings: Settings, limit: int) -> list[str]:
    now = utc_now()
    stale_before = now - timedelta(seconds=settings.clerk_outbox_claim_timeout_seconds)
    rows = await db.scalars(
        select(ClerkInvitationOutbox.id)
        .where(
            or_(
                (
                    (ClerkInvitationOutbox.status == "pending")
                    & (ClerkInvitationOutbox.available_at <= now)
                ),
                (
                    (ClerkInvitationOutbox.status == "processing")
                    & (ClerkInvitationOutbox.locked_at < stale_before)
                ),
            )
        )
        .order_by(ClerkInvitationOutbox.available_at.asc(), ClerkInvitationOutbox.created_at.asc())
        .limit(limit)
    )
    job_ids = list(rows)
    await db.rollback()
    return job_ids


async def process_ready_invitation_jobs(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider: InvitationProvider,
    settings: Settings,
    worker_id: str,
    limit: int = 20,
) -> list[OutboxProcessResult]:
    async with session_factory() as db:
        job_ids = await ready_job_ids(db, settings=settings, limit=limit)
    results: list[OutboxProcessResult] = []
    for job_id in job_ids:
        async with session_factory() as db:
            results.append(
                await process_invitation_job(
                    db,
                    job_id=job_id,
                    worker_id=worker_id,
                    provider=provider,
                    settings=settings,
                )
            )
    return results
