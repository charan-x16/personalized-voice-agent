from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlalchemy import case, select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings
from ...database import get_db
from ...dependencies import get_app_settings, get_voice_provider
from ...models import ConversationOutcome, Customer, VoiceSession, new_id, utc_now
from ...schemas import (
    ConversationDetailResponse,
    MockConversationCompleteRequest,
    ProviderConnection,
    VoiceSessionCancelResponse,
    VoiceSessionCreateRequest,
    VoiceSessionResponse,
)
from ...security import (
    Actor,
    generate_conversation_ref,
    get_current_actor,
    hash_conversation_ref,
    require_tenant_admin,
)
from ...services.voice_provider import (
    VoiceProvider,
    VoiceProviderBootstrapAmbiguousError,
    VoiceProviderSession,
    VoiceProviderTerminationError,
    VoiceProviderUnavailableError,
)
from .conversations import conversation_detail_response, load_scoped_conversation

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_MOCK_TRANSCRIPT_TURNS = 250
_MAX_MOCK_TRANSCRIPT_CHARACTERS = 128_000
_CANCELLATION_TERMINAL_STATUSES = frozenset(
    {"cancelled", "completed", "ended", "expired", "failed"}
)
_CANCELLABLE_STATUSES = frozenset({"creating", "ready", "active", "cancelling"})
_DEFAULT_TERMINATION_RETRY_SECONDS = 3
_DEFAULT_BOOTSTRAP_RETRY_SECONDS = 3


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _bounded_mock_transcript(
    payload: MockConversationCompleteRequest,
) -> list[dict[str, Any]]:
    transcript: list[dict[str, Any]] = []
    remaining_characters = _MAX_MOCK_TRANSCRIPT_CHARACTERS
    for turn in payload.transcript[:_MAX_MOCK_TRANSCRIPT_TURNS]:
        if remaining_characters <= 0:
            break
        text = turn.text[:remaining_characters]
        remaining_characters -= len(text)
        transcript.append(
            {
                "speaker": turn.speaker,
                "text": text,
                "timestamp": turn.timestamp,
            }
        )
    return transcript


def _is_active_session_conflict(exc: IntegrityError) -> bool:
    expected_constraint = "uq_voice_session_active_customer"
    candidates = (exc.orig, getattr(exc.orig, "__cause__", None))
    if any(
        getattr(candidate, "constraint_name", None) == expected_constraint
        for candidate in candidates
        if candidate is not None
    ):
        return True

    # SQLite reports the constrained columns instead of the declared name.
    message = str(exc.orig).casefold()
    return all(
        column in message
        for column in (
            "voice_sessions.tenant_id",
            "voice_sessions.customer_id",
            "voice_sessions.active_slot",
        )
    )


async def _mark_session_failed(
    db: AsyncSession,
    *,
    session_id: str,
    provider_session_id: str | None = None,
) -> None:
    """Best-effort fail-closed cleanup after provider bootstrap has started."""

    try:
        await db.rollback()
        voice_session = await db.scalar(
            select(VoiceSession)
            .where(VoiceSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if voice_session is None:
            return

        if provider_session_id is not None:
            voice_session.provider_session_id = provider_session_id
        if voice_session.status in {"creating", "ready", "active"}:
            voice_session.status = "failed"
            voice_session.active_slot = None
        elif voice_session.status == "cancelling":
            # The bootstrap definitively created no resource, or its returned
            # resource has already been terminated by compensation.
            voice_session.status = "cancelled"
            voice_session.active_slot = None
            voice_session.ended_at = voice_session.ended_at or utc_now()
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Unable to mark a failed voice session")


async def _retain_session_for_termination_retry(
    db: AsyncSession,
    *,
    session_id: str,
    provider_session_id: str,
    allow_terminal_transition: bool = False,
) -> None:
    """Persist a retryable provider termination state and its opaque handle."""

    try:
        await db.rollback()
        voice_session = await db.scalar(
            select(VoiceSession)
            .where(VoiceSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if voice_session is None:
            return
        current_status = voice_session.status.casefold()
        if current_status in {"completed", "ended"}:
            return
        if current_status in _CANCELLATION_TERMINAL_STATUSES and not allow_terminal_transition:
            return
        voice_session.provider_session_id = provider_session_id
        voice_session.status = "cancelling"
        # Preserve the existing slot instead of reacquiring one. It remains 1
        # for an ordinary cancellation, but may already be NULL if an expired
        # session was reclaimed by a replacement while termination was in flight.
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Unable to retain a voice session for termination retry")


async def _retain_ambiguous_bootstrap(
    db: AsyncSession,
    *,
    session_id: str,
) -> None:
    """Keep a possibly accepted bootstrap from allowing a duplicate live call."""

    try:
        await db.rollback()
        voice_session = await db.scalar(
            select(VoiceSession)
            .where(VoiceSession.id == session_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if voice_session is None or voice_session.status.casefold() not in {
            "creating",
            "cancelling",
        }:
            return
        # The reservation was committed before the provider call. Preserve its
        # current value so an expiry/reclamation race cannot collide with a new slot.
        # Quarantine a timeout-orphan from all runtime hooks and customer-data tools.
        voice_session.status = "cancelling"
        await db.commit()
    except SQLAlchemyError:
        await db.rollback()
        logger.exception("Unable to retain an ambiguously bootstrapped voice session")


async def _terminate_provider_session(
    provider: VoiceProvider,
    *,
    provider_session_id: str,
    idempotency_key: str,
) -> None:
    """Normalize unexpected provider errors into a retry-safe typed failure."""

    try:
        await provider.terminate_session(
            provider_session_id=provider_session_id,
            idempotency_key=idempotency_key,
        )
    except VoiceProviderTerminationError:
        raise
    except Exception as exc:
        logger.exception("Unexpected voice-provider termination failure")
        raise VoiceProviderTerminationError(
            ambiguous=True,
            retry_after_seconds=_DEFAULT_TERMINATION_RETRY_SECONDS,
        ) from exc


def _termination_failure_http_exception(
    exc: VoiceProviderTerminationError,
) -> HTTPException:
    headers = {"Cache-Control": "no-store"}
    if exc.ambiguous:
        headers["Retry-After"] = str(exc.retry_after_seconds or _DEFAULT_TERMINATION_RETRY_SECONDS)
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
        headers=headers,
    )


def _bootstrap_failure_http_exception(
    exc: VoiceProviderBootstrapAmbiguousError,
) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=str(exc),
        headers={
            "Cache-Control": "no-store",
            "Retry-After": str(exc.retry_after_seconds or _DEFAULT_BOOTSTRAP_RETRY_SECONDS),
        },
    )


async def _finalize_cancellation(
    db: AsyncSession,
    *,
    actor: Actor,
    session_id: str,
) -> VoiceSession:
    """Commit cancellation unless another terminal callback won the race."""

    voice_session, _ = await load_scoped_conversation(
        db,
        actor=actor,
        session_id=session_id,
        lock=True,
    )
    if voice_session.status == "cancelling":
        voice_session.status = "cancelled"
        voice_session.active_slot = None
        voice_session.ended_at = voice_session.ended_at or utc_now()
        await db.commit()
    return voice_session


async def _create_voice_session_for_customer(
    payload: VoiceSessionCreateRequest,
    response: Response,
    actor: Actor,
    db: AsyncSession,
    settings: Settings,
    provider: VoiceProvider,
    *,
    customer_id: str,
    session_mode: Literal["customer", "admin_preview"],
) -> VoiceSessionResponse:
    """Reserve and bootstrap a customer-scoped provider session."""

    # Customer deactivation takes the same row lock. Whichever transaction wins is
    # observed before a slot is reserved, so an administrator cannot orphan a call.
    customer = await db.scalar(
        select(Customer)
        .where(
            Customer.id == customer_id,
            Customer.tenant_id == actor.tenant_id,
            Customer.is_active.is_(True),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active customer profile not found.",
        )

    language = (payload.language or customer.preferred_language).strip()
    if not language:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Language must not be blank.",
        )

    now = utc_now()
    requested_expiry = now + timedelta(minutes=settings.session_ttl_minutes)
    conversation_ref = generate_conversation_ref()
    agent_variables = {
        "conversation_ref": conversation_ref,
        "preferred_language": language,
    }
    voice_session = VoiceSession(
        id=new_id(),
        tenant_id=actor.tenant_id,
        customer_id=customer.id,
        session_mode=session_mode,
        initiated_by_user_id=actor.user_id,
        provider=provider.name,
        conversation_ref_hash=hash_conversation_ref(conversation_ref),
        status="creating",
        active_slot=1,
        language=language,
        started_at=now,
        expires_at=requested_expiry,
    )

    # Release an abandoned slot before reserving a new one. A database unique
    # constraint closes the concurrent double-start race across API workers.
    try:
        await db.execute(
            update(VoiceSession)
            .where(
                VoiceSession.tenant_id == actor.tenant_id,
                VoiceSession.customer_id == customer.id,
                VoiceSession.active_slot == 1,
                VoiceSession.expires_at <= now,
            )
            .values(status="expired", active_slot=None)
        )
        db.add(voice_session)

        # Commit the opaque reference before contacting the provider. Sarvam can invoke
        # on-start immediately, and that callback must be able to resolve the session.
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if not _is_active_session_conflict(exc):
            logger.exception("Database integrity failure while reserving a voice session")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to create voice session.",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An active voice session already exists for this customer.",
        ) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database failure while reserving a voice session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create voice session.",
        ) from exc

    provider_session: VoiceProviderSession | None = None
    bootstrap_terminal_status: str | None = None
    try:
        provider_session = await provider.create_session(
            session_id=voice_session.id,
            language=language,
            expires_at=requested_expiry,
            agent_variables=agent_variables,
        )
        effective_expiry = min(requested_expiry, provider_session.expires_at)
        bootstrap_expired = effective_expiry <= utc_now()
        # Store provider metadata and transition to ready in one atomic update.
        # A cancellation or completion committed before this statement keeps its
        # status; there is no stale ORM read that can overwrite terminal intent.
        finalized = await db.execute(
            update(VoiceSession)
            .where(VoiceSession.id == voice_session.id)
            .values(
                provider_session_id=provider_session.provider_session_id,
                expires_at=effective_expiry,
                status=case(
                    (
                        VoiceSession.status == "creating",
                        "expired" if bootstrap_expired else "ready",
                    ),
                    else_=VoiceSession.status,
                ),
                active_slot=case(
                    (
                        VoiceSession.status == "creating",
                        None if bootstrap_expired else VoiceSession.active_slot,
                    ),
                    else_=VoiceSession.active_slot,
                ),
            )
            .execution_options(synchronize_session=False)
        )
        if finalized.rowcount != 1:
            raise SQLAlchemyError("Voice session disappeared during provider finalization")
        await db.commit()
        await db.refresh(voice_session)

        finalized_status = voice_session.status.casefold()
        if finalized_status == "cancelling":
            # Persist the provider handle before the network call. If termination
            # is ambiguous, an authenticated retry can safely resume from it.
            await _terminate_provider_session(
                provider,
                provider_session_id=provider_session.provider_session_id,
                idempotency_key=voice_session.id,
            )
            voice_session = await _finalize_cancellation(
                db,
                actor=actor,
                session_id=voice_session.id,
            )
            bootstrap_terminal_status = voice_session.status.casefold()
        elif finalized_status in {"cancelled", "expired", "failed"}:
            # A provider resource returned after the local session became unusable.
            # Confirm its termination before reporting the local terminal result.
            await _terminate_provider_session(
                provider,
                provider_session_id=provider_session.provider_session_id,
                idempotency_key=voice_session.id,
            )
            bootstrap_terminal_status = finalized_status
        elif finalized_status in {"completed", "ended"}:
            # An end callback won the race. The remote conversation is already
            # terminal, but connection credentials must never be returned now.
            bootstrap_terminal_status = finalized_status
        elif finalized_status != "ready":
            # Unknown local states fail closed. Terminate the newly returned
            # resource and withhold its connection credentials.
            await _terminate_provider_session(
                provider,
                provider_session_id=provider_session.provider_session_id,
                idempotency_key=voice_session.id,
            )
            bootstrap_terminal_status = finalized_status
    except VoiceProviderUnavailableError as exc:
        await _mark_session_failed(db, session_id=voice_session.id)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except VoiceProviderBootstrapAmbiguousError as exc:
        await _retain_ambiguous_bootstrap(db, session_id=voice_session.id)
        raise _bootstrap_failure_http_exception(exc) from exc
    except VoiceProviderTerminationError as exc:
        # Expiry reclamation can race the network call. Restore a retryable
        # state without reacquiring a slot that may now belong to a replacement.
        if provider_session is not None:
            await _retain_session_for_termination_retry(
                db,
                session_id=voice_session.id,
                provider_session_id=provider_session.provider_session_id,
                allow_terminal_transition=True,
            )
        raise _termination_failure_http_exception(exc) from exc
    except SQLAlchemyError as exc:
        logger.exception("Database failure while finalizing a voice session")
        if provider_session is None:
            await _retain_ambiguous_bootstrap(db, session_id=voice_session.id)
            ambiguous_error = VoiceProviderBootstrapAmbiguousError(
                retry_after_seconds=_DEFAULT_BOOTSTRAP_RETRY_SECONDS
            )
            raise _bootstrap_failure_http_exception(ambiguous_error) from exc
        if provider_session is not None:
            try:
                await _terminate_provider_session(
                    provider,
                    provider_session_id=provider_session.provider_session_id,
                    idempotency_key=voice_session.id,
                )
            except VoiceProviderTerminationError as termination_exc:
                await _retain_session_for_termination_retry(
                    db,
                    session_id=voice_session.id,
                    provider_session_id=provider_session.provider_session_id,
                    allow_terminal_transition=True,
                )
                raise _termination_failure_http_exception(termination_exc) from exc
        await _mark_session_failed(
            db,
            session_id=voice_session.id,
            provider_session_id=(
                provider_session.provider_session_id if provider_session is not None else None
            ),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to create voice session.",
            headers={"Cache-Control": "no-store"},
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected voice-provider failure")
        if provider_session is not None:
            try:
                await _terminate_provider_session(
                    provider,
                    provider_session_id=provider_session.provider_session_id,
                    idempotency_key=voice_session.id,
                )
            except VoiceProviderTerminationError as termination_exc:
                await _retain_session_for_termination_retry(
                    db,
                    session_id=voice_session.id,
                    provider_session_id=provider_session.provider_session_id,
                    allow_terminal_transition=True,
                )
                raise _termination_failure_http_exception(termination_exc) from exc
            await _mark_session_failed(
                db,
                session_id=voice_session.id,
                provider_session_id=provider_session.provider_session_id,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Voice service is temporarily unavailable.",
                headers={"Cache-Control": "no-store"},
            ) from exc

        # The provider call may have been accepted before it failed without a
        # handle. Keep the active slot until expiry/reconciliation rather than
        # allowing a second potentially live call.
        await _retain_ambiguous_bootstrap(db, session_id=voice_session.id)
        ambiguous_error = VoiceProviderBootstrapAmbiguousError(
            retry_after_seconds=_DEFAULT_BOOTSTRAP_RETRY_SECONDS
        )
        raise _bootstrap_failure_http_exception(ambiguous_error) from exc

    if bootstrap_terminal_status == "expired":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Voice session expired while it was being created.",
            headers={"Cache-Control": "no-store"},
        )
    if bootstrap_terminal_status in {"completed", "ended"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice session ended while it was being created.",
            headers={"Cache-Control": "no-store"},
        )
    if bootstrap_terminal_status == "failed":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Voice session failed while it was being created.",
            headers={"Cache-Control": "no-store"},
        )
    if bootstrap_terminal_status in {"cancelled", "cancelling"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice session was cancelled while it was being created.",
            headers={"Cache-Control": "no-store"},
        )
    if bootstrap_terminal_status is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice session became unavailable while it was being created.",
            headers={"Cache-Control": "no-store"},
        )

    response.headers["Cache-Control"] = "no-store"
    public_expiry = _as_utc(voice_session.expires_at)
    return VoiceSessionResponse(
        session_id=voice_session.id,
        provider=voice_session.provider,
        status=voice_session.status,
        language=voice_session.language,
        expires_at=public_expiry,
        connection=ProviderConnection(
            transport=provider_session.transport,
            websocket_url=provider_session.websocket_url,
            expires_at=public_expiry,
        ),
    )


@router.post(
    "/sessions",
    response_model=VoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_voice_session(
    payload: VoiceSessionCreateRequest,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    provider: Annotated[VoiceProvider, Depends(get_voice_provider)],
) -> VoiceSessionResponse:
    """Start a voice session for the authenticated actor's own customer profile."""

    if actor.customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A customer profile is required to start a voice session.",
        )
    return await _create_voice_session_for_customer(
        payload,
        response,
        actor,
        db,
        settings,
        provider,
        customer_id=actor.customer_id,
        session_mode="customer",
    )


@router.post(
    "/customers/{customer_id}/preview-sessions",
    response_model=VoiceSessionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_admin_preview_session(
    customer_id: Annotated[str, Path(min_length=1, max_length=64)],
    payload: VoiceSessionCreateRequest,
    response: Response,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
    provider: Annotated[VoiceProvider, Depends(get_voice_provider)],
) -> VoiceSessionResponse:
    """Preview one tenant-scoped customer agent without impersonating the customer."""

    return await _create_voice_session_for_customer(
        payload,
        response,
        actor,
        db,
        settings,
        provider,
        customer_id=customer_id,
        session_mode="admin_preview",
    )


@router.post(
    "/sessions/{session_id}/cancel",
    response_model=VoiceSessionCancelResponse,
)
async def cancel_voice_session(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: Annotated[VoiceProvider, Depends(get_voice_provider)],
) -> VoiceSessionCancelResponse:
    """Stop the actor's own provider session without trusting provider identifiers."""

    voice_session, _ = await load_scoped_conversation(
        db,
        actor=actor,
        session_id=session_id,
        lock=True,
    )
    current_status = voice_session.status.casefold()
    if current_status in _CANCELLATION_TERMINAL_STATUSES:
        response.headers["Cache-Control"] = "no-store"
        return VoiceSessionCancelResponse(
            session_id=voice_session.id,
            status=current_status,
            idempotent=True,
        )

    if current_status not in _CANCELLABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice session cannot be cancelled from its current state.",
            headers={"Cache-Control": "no-store"},
        )

    cancellation_was_pending = current_status == "cancelling"
    provider_session_id = voice_session.provider_session_id
    if not cancellation_was_pending:
        voice_session.status = "cancelling"

    # Commit and release the row lock before making a network call. The active
    # slot intentionally remains reserved until provider termination is known.
    try:
        await db.commit()
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database failure while requesting voice-session cancellation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to cancel voice session.",
            headers={"Cache-Control": "no-store"},
        ) from exc

    if provider_session_id is None:
        if current_status == "ready":
            logger.error("Ready voice session has no provider handle: %s", voice_session.id)
            raise _termination_failure_http_exception(
                VoiceProviderTerminationError(
                    ambiguous=True,
                    retry_after_seconds=_DEFAULT_TERMINATION_RETRY_SECONDS,
                )
            )

        # Session creation is still in flight. Its bootstrap path will persist
        # the provider handle, observe `cancelling`, and perform compensation.
        response.headers["Cache-Control"] = "no-store"
        return VoiceSessionCancelResponse(
            session_id=voice_session.id,
            status="cancelling",
            idempotent=cancellation_was_pending,
        )

    if voice_session.provider != provider.name:
        logger.error(
            "Configured provider cannot terminate stored voice session %s",
            voice_session.id,
        )
        raise _termination_failure_http_exception(
            VoiceProviderTerminationError(
                "The voice session could not be stopped with the active provider configuration.",
                ambiguous=False,
            )
        )

    try:
        await _terminate_provider_session(
            provider,
            provider_session_id=provider_session_id,
            idempotency_key=voice_session.id,
        )
        voice_session = await _finalize_cancellation(
            db,
            actor=actor,
            session_id=voice_session.id,
        )
    except VoiceProviderTerminationError as exc:
        await _retain_session_for_termination_retry(
            db,
            session_id=voice_session.id,
            provider_session_id=provider_session_id,
            allow_terminal_transition=True,
        )
        raise _termination_failure_http_exception(exc) from exc
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database failure while finalizing voice-session cancellation")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to cancel voice session.",
            headers={"Cache-Control": "no-store"},
        ) from exc

    final_status = voice_session.status.casefold()
    if final_status not in _CANCELLATION_TERMINAL_STATUSES:
        logger.error("Voice-session cancellation did not reach a terminal state")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The voice session could not be stopped yet.",
            headers={
                "Cache-Control": "no-store",
                "Retry-After": str(_DEFAULT_TERMINATION_RETRY_SECONDS),
            },
        )

    response.headers["Cache-Control"] = "no-store"
    return VoiceSessionCancelResponse(
        session_id=voice_session.id,
        status=final_status,
        idempotent=cancellation_was_pending or final_status != "cancelled",
    )


@router.post(
    "/sessions/{session_id}/mock-complete",
    response_model=ConversationDetailResponse,
)
async def mock_complete_voice_session(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    payload: MockConversationCompleteRequest,
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> ConversationDetailResponse:
    """Finish a mock call so the browser can exercise the complete local flow."""

    if settings.app_env not in {"development", "test"} or settings.voice_provider != "mock":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    voice_session, existing_outcome = await load_scoped_conversation(
        db,
        actor=actor,
        session_id=session_id,
        lock=True,
    )
    if voice_session.provider != "mock":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    # The first accepted completion is authoritative. Browser retries receive the
    # stored outcome and cannot silently rewrite conversation history.
    if existing_outcome is not None:
        response.headers["Cache-Control"] = "no-store"
        return conversation_detail_response(voice_session, existing_outcome)

    if voice_session.status.casefold() in {"cancelling", "cancelled", "expired", "failed"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice session cannot be completed.",
        )

    outcome = ConversationOutcome(
        session_id=voice_session.id,
        resolution=payload.resolution,
        summary=payload.summary,
        transcript=_bounded_mock_transcript(payload),
        final_variables={},
        duration_seconds=payload.duration_seconds,
    )
    db.add(outcome)
    voice_session.status = "completed"
    voice_session.active_slot = None
    if voice_session.ended_at is None:
        voice_session.ended_at = utc_now()

    try:
        await db.commit()
    except IntegrityError as exc:
        # PostgreSQL row locking serializes this path. The unique outcome key is
        # the final guard for databases where FOR UPDATE is unavailable (SQLite).
        await db.rollback()
        voice_session, concurrent_outcome = await load_scoped_conversation(
            db,
            actor=actor,
            session_id=session_id,
        )
        if concurrent_outcome is None:
            logger.exception("Integrity failure while completing a mock voice session")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Unable to complete voice session.",
            ) from exc
        outcome = concurrent_outcome
    except SQLAlchemyError as exc:
        await db.rollback()
        logger.exception("Database failure while completing a mock voice session")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete voice session.",
        ) from exc

    response.headers["Cache-Control"] = "no-store"
    return conversation_detail_response(voice_session, outcome)
