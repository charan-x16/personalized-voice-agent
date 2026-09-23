from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from pydantic import ValidationError
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import ConversationOutcome, VoiceSession
from ...schemas import (
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationSummaryResponse,
    TranscriptTurn,
)
from ...security import Actor, get_current_actor

router = APIRouter()

_MAX_RETURNED_TRANSCRIPT_TURNS = 250


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def conversation_summary_response(
    voice_session: VoiceSession,
    outcome: ConversationOutcome | None,
) -> ConversationSummaryResponse:
    return ConversationSummaryResponse(
        id=voice_session.id,
        provider=voice_session.provider,
        started_at=_utc_datetime(voice_session.started_at),
        ended_at=(
            _utc_datetime(voice_session.ended_at) if voice_session.ended_at is not None else None
        ),
        duration_seconds=outcome.duration_seconds if outcome is not None else None,
        language=voice_session.language,
        resolution=outcome.resolution if outcome is not None else None,
        summary=outcome.summary if outcome is not None else None,
    )


def _safe_transcript(value: object) -> list[TranscriptTurn]:
    if not isinstance(value, list):
        return []

    transcript: list[TranscriptTurn] = []
    for candidate in value[:_MAX_RETURNED_TRANSCRIPT_TURNS]:
        try:
            transcript.append(TranscriptTurn.model_validate(candidate))
        except ValidationError:
            # Historical/provider data should never make the browser API unavailable.
            continue
    return transcript


def conversation_detail_response(
    voice_session: VoiceSession,
    outcome: ConversationOutcome | None,
) -> ConversationDetailResponse:
    summary = conversation_summary_response(voice_session, outcome)
    raw_variables: Any = outcome.final_variables if outcome is not None else {}
    final_variables = dict(raw_variables) if isinstance(raw_variables, dict) else {}
    return ConversationDetailResponse(
        **summary.model_dump(),
        transcript=_safe_transcript(outcome.transcript if outcome is not None else []),
        final_variables=final_variables,
    )


def require_customer_id(actor: Actor) -> str:
    if actor.customer_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="A customer profile is required.",
        )
    return actor.customer_id


async def load_scoped_conversation(
    db_session: AsyncSession,
    *,
    actor: Actor,
    session_id: str,
    lock: bool = False,
) -> tuple[VoiceSession, ConversationOutcome | None]:
    if actor.customer_id is None:
        actor_scope = (
            VoiceSession.session_mode == "admin_preview",
            VoiceSession.initiated_by_user_id == actor.user_id,
        )
    else:
        actor_scope = (
            VoiceSession.session_mode == "customer",
            VoiceSession.customer_id == actor.customer_id,
        )
    statement = (
        select(VoiceSession, ConversationOutcome)
        .outerjoin(ConversationOutcome, ConversationOutcome.session_id == VoiceSession.id)
        .where(
            VoiceSession.id == session_id,
            VoiceSession.tenant_id == actor.tenant_id,
            *actor_scope,
        )
    )
    if lock:
        statement = statement.with_for_update(of=VoiceSession).execution_options(
            populate_existing=True
        )

    row = (await db_session.execute(statement)).one_or_none()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found.",
        )
    return row[0], row[1]


@router.get("", response_model=ConversationListResponse)
async def list_conversations(
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
    query: Annotated[str, Query(max_length=200)] = "",
    outcome: Literal["all", "resolved", "follow-up", "escalated"] = "all",
) -> ConversationListResponse:
    """List only voice sessions belonging to the authenticated customer."""

    customer_id = require_customer_id(actor)
    scope = (
        VoiceSession.tenant_id == actor.tenant_id,
        VoiceSession.customer_id == customer_id,
        VoiceSession.session_mode == "customer",
    )
    normalized_resolution = func.lower(func.trim(func.coalesce(ConversationOutcome.resolution, "")))
    outcome_group = case(
        (normalized_resolution.in_(["answered", "completed", "resolved", "success"]), "resolved"),
        (normalized_resolution.contains("escalat"), "escalated"),
        else_="follow-up",
    )
    if outcome != "all":
        scope += (outcome_group == outcome,)
    search = query.strip().lower()
    if search:
        title = case(
            (outcome_group == "resolved", "Customer question resolved"),
            (outcome_group == "escalated", "Conversation escalated"),
            else_="Follow-up requested",
        )
        scope += (
            or_(
                func.lower(func.coalesce(ConversationOutcome.summary, "")).contains(
                    search, autoescape=True
                ),
                normalized_resolution.contains(search, autoescape=True),
                func.lower(VoiceSession.language).contains(search, autoescape=True),
                func.lower(VoiceSession.provider).contains(search, autoescape=True),
                func.lower(title).contains(search, autoescape=True),
            ),
        )
    total = await db_session.scalar(
        select(func.count(VoiceSession.id))
        .join(ConversationOutcome, ConversationOutcome.session_id == VoiceSession.id)
        .where(*scope)
    )
    rows = (
        await db_session.execute(
            select(VoiceSession, ConversationOutcome)
            .join(ConversationOutcome, ConversationOutcome.session_id == VoiceSession.id)
            .where(*scope)
            .order_by(VoiceSession.started_at.desc(), VoiceSession.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    response.headers["Cache-Control"] = "no-store"
    return ConversationListResponse(
        items=[conversation_summary_response(session, outcome) for session, outcome in rows],
        total=total or 0,
    )


@router.get("/{session_id}", response_model=ConversationDetailResponse)
async def get_conversation(
    session_id: Annotated[str, Path(min_length=1, max_length=64)],
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> ConversationDetailResponse:
    """Return one tenant- and customer-bound conversation without provider secrets."""

    voice_session, outcome = await load_scoped_conversation(
        db_session,
        actor=actor,
        session_id=session_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return conversation_detail_response(voice_session, outcome)
