from __future__ import annotations

import json
import math
from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_configuration import render_opening_message, resolve_agent_configuration
from ...config import Settings
from ...database import get_db
from ...dependencies import get_app_settings
from ...models import (
    ConversationOutcome,
    Customer,
    CustomerAgentConfiguration,
    CustomerOrder,
    Tenant,
    ToolAuditLog,
    VoiceSession,
)
from ...schemas import (
    CustomerContext,
    OnEndRequest,
    OnEndResponse,
    OnStartRequest,
    OnStartResponse,
    OrderStatusRequest,
    OrderStatusResponse,
    RuntimeAgentConfiguration,
)
from ...security import hash_conversation_ref, require_voice_tool_key

router = APIRouter(dependencies=[Depends(require_voice_tool_key)])

_TERMINAL_SESSION_STATUSES = frozenset({"cancelling", "cancelled", "completed", "ended", "failed"})
_RUNTIME_BLOCKED_SESSION_STATUSES = _TERMINAL_SESSION_STATUSES
_MAX_STORED_TRANSCRIPT_TURNS = 250
_MAX_STORED_TRANSCRIPT_CHARACTERS = 128_000
_MAX_STORED_TURN_CHARACTERS = 8_000
_MAX_FINAL_VARIABLE_BYTES = 64 * 1024
_MAX_FINAL_VARIABLE_ITEMS = 1_000
_MAX_FINAL_VARIABLE_DEPTH = 6
_MAX_FINAL_VARIABLE_STRING_CHARACTERS = 4_000
_MAX_FINAL_VARIABLE_KEY_CHARACTERS = 128


def _utc_datetime(value: datetime) -> datetime:
    """Normalize database datetimes, including SQLite's timezone-naive values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _session_has_ended(voice_session: VoiceSession) -> bool:
    return voice_session.ended_at is not None or (
        voice_session.status.casefold() in _TERMINAL_SESSION_STATUSES
    )


def _ensure_session_is_usable(voice_session: VoiceSession) -> None:
    if voice_session.status.casefold() in _RUNTIME_BLOCKED_SESSION_STATUSES or (
        voice_session.ended_at is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Voice session is being cancelled"
                if voice_session.status.casefold() == "cancelling"
                else "Voice session has already ended"
            ),
        )

    if _utc_datetime(voice_session.expires_at) <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Voice session has expired",
        )


def _ensure_session_can_end(
    voice_session: VoiceSession,
    *,
    completion_grace_minutes: int,
) -> None:
    """Allow a delayed completion callback while rejecting failed/cancelled sessions."""

    if _session_has_ended(voice_session):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Voice session has already ended",
        )

    completion_deadline = _utc_datetime(voice_session.expires_at) + timedelta(
        minutes=completion_grace_minutes
    )
    if completion_deadline <= datetime.now(UTC):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Voice session completion window has expired",
        )


def _bind_interaction(
    voice_session: VoiceSession,
    interaction_id: str | None,
) -> None:
    if voice_session.provider_interaction_id is not None:
        if voice_session.provider_interaction_id == interaction_id:
            return
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Interaction does not match this voice session",
        )
    if interaction_id is not None:
        voice_session.provider_interaction_id = interaction_id


async def _load_voice_session(
    db_session: AsyncSession,
    conversation_ref: str,
    *,
    lock: bool = False,
    require_active_context: bool = True,
) -> VoiceSession:
    statement = select(VoiceSession).where(
        VoiceSession.conversation_ref_hash == hash_conversation_ref(conversation_ref)
    )
    if require_active_context:
        statement = (
            statement.join(Tenant, Tenant.id == VoiceSession.tenant_id)
            .join(
                Customer,
                and_(
                    Customer.id == VoiceSession.customer_id,
                    Customer.tenant_id == VoiceSession.tenant_id,
                ),
            )
            .where(
                Tenant.is_active.is_(True),
                Customer.is_active.is_(True),
            )
        )
    if lock:
        statement = statement.with_for_update()

    voice_session = await db_session.scalar(statement)
    if voice_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Voice session not found",
        )
    return voice_session


def _elapsed_ms(started_at: float) -> int:
    return max(0, int((perf_counter() - started_at) * 1_000))


def _record_successful_tool_call(
    db_session: AsyncSession,
    *,
    voice_session: VoiceSession,
    tool_name: str,
    request_payload: dict[str, Any],
    response_payload: dict[str, Any],
    started_at: float,
) -> None:
    db_session.add(
        ToolAuditLog(
            tenant_id=voice_session.tenant_id,
            session_id=voice_session.id,
            tool_name=tool_name,
            status="success",
            request_payload=request_payload,
            response_payload=response_payload,
            duration_ms=_elapsed_ms(started_at),
        )
    )


def _bounded_transcript(payload: OnEndRequest) -> list[dict[str, Any]]:
    stored_turns: list[dict[str, Any]] = []
    remaining_characters = _MAX_STORED_TRANSCRIPT_CHARACTERS

    for turn in payload.transcript[:_MAX_STORED_TRANSCRIPT_TURNS]:
        if remaining_characters <= 0:
            break

        text = turn.text[: min(_MAX_STORED_TURN_CHARACTERS, remaining_characters)]
        remaining_characters -= len(text)
        stored_turns.append(
            {
                "speaker": turn.speaker,
                "text": text,
                "timestamp": turn.timestamp,
            }
        )

    return stored_turns


def _bounded_final_variables(
    values: dict[str, Any],
    *,
    allowed_keys: frozenset[str],
) -> dict[str, Any]:
    remaining_items = _MAX_FINAL_VARIABLE_ITEMS

    def sanitize(value: Any, depth: int) -> Any:
        nonlocal remaining_items
        if remaining_items <= 0 or depth > _MAX_FINAL_VARIABLE_DEPTH:
            return "[truncated]"

        remaining_items -= 1
        if value is None or isinstance(value, bool | int):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else None
        if isinstance(value, str):
            return value[:_MAX_FINAL_VARIABLE_STRING_CHARACTERS]
        if isinstance(value, list):
            return [sanitize(item, depth + 1) for item in value if remaining_items > 0]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for raw_key, item in value.items():
                if remaining_items <= 0:
                    break
                key = str(raw_key)[:_MAX_FINAL_VARIABLE_KEY_CHARACTERS]
                result[key] = sanitize(item, depth + 1)
            return result
        return str(value)[:_MAX_FINAL_VARIABLE_STRING_CHARACTERS]

    bounded: dict[str, Any] = {}
    for raw_key, value in values.items():
        if remaining_items <= 0:
            break

        key = str(raw_key)[:_MAX_FINAL_VARIABLE_KEY_CHARACTERS]
        if key not in allowed_keys:
            continue
        candidate = sanitize(value, 1)
        proposed = {**bounded, key: candidate}
        encoded = json.dumps(
            proposed,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > _MAX_FINAL_VARIABLE_BYTES:
            break
        bounded = proposed

    return bounded


@router.post("/hooks/on-start", response_model=OnStartResponse)
async def on_start(
    payload: OnStartRequest,
    http_response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> OnStartResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(
        db_session,
        payload.conversation_ref,
        lock=True,
    )
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)

    customer_statement = (
        select(Customer)
        .join(
            VoiceSession,
            and_(
                VoiceSession.customer_id == Customer.id,
                VoiceSession.tenant_id == Customer.tenant_id,
            ),
        )
        .where(
            VoiceSession.id == voice_session.id,
            Customer.id == voice_session.customer_id,
            Customer.tenant_id == voice_session.tenant_id,
            Customer.is_active.is_(True),
        )
    )
    customer = await db_session.scalar(customer_statement)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer context not found",
        )

    name_parts = customer.full_name.split()
    first_name = name_parts[0] if name_parts else "Customer"
    stored_agent_configuration = await db_session.scalar(
        select(CustomerAgentConfiguration).where(
            CustomerAgentConfiguration.tenant_id == voice_session.tenant_id,
            CustomerAgentConfiguration.customer_id == voice_session.customer_id,
        )
    )
    agent_configuration = resolve_agent_configuration(stored_agent_configuration)
    response = OnStartResponse(
        session_id=voice_session.id,
        customer=CustomerContext(
            first_name=first_name,
            preferred_language=customer.preferred_language,
            plan_name=customer.plan_name,
            open_request_count=0,
        ),
        agent=RuntimeAgentConfiguration(
            display_name=agent_configuration.display_name,
            opening_message=render_opening_message(
                agent_configuration.opening_message,
                first_name=first_name,
            ),
            tone=agent_configuration.tone,
            instructions=agent_configuration.instructions,
            revision=agent_configuration.revision,
        ),
        safe_to_continue=True,
    )
    _record_successful_tool_call(
        db_session,
        voice_session=voice_session,
        tool_name="on_start",
        request_payload={
            "has_interaction_id": payload.interaction_id is not None,
            "metadata_field_count": len(payload.metadata),
        },
        response_payload={
            "safe_to_continue": True,
            "agent_configuration_revision": agent_configuration.revision,
        },
        started_at=started_at,
    )
    await db_session.commit()
    http_response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/tools/get-order-status", response_model=OrderStatusResponse)
async def get_order_status(
    payload: OrderStatusRequest,
    http_response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> OrderStatusResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(db_session, payload.conversation_ref)
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)

    order = await db_session.scalar(
        select(CustomerOrder).where(
            CustomerOrder.tenant_id == voice_session.tenant_id,
            CustomerOrder.customer_id == voice_session.customer_id,
            CustomerOrder.external_ref == payload.order_reference,
        )
    )
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Order not found",
        )

    response = OrderStatusResponse(
        order_reference=order.external_ref,
        status=order.status,
        estimated_arrival=order.estimated_arrival,
        delivery_city=order.delivery_city,
    )
    _record_successful_tool_call(
        db_session,
        voice_session=voice_session,
        tool_name="get_order_status",
        request_payload={"has_order_reference": True},
        response_payload={"found": True},
        started_at=started_at,
    )
    await db_session.commit()
    http_response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/hooks/on-end", response_model=OnEndResponse)
async def on_end(
    payload: OnEndRequest,
    http_response: Response,
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> OnEndResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(
        db_session,
        payload.conversation_ref,
        lock=True,
        require_active_context=False,
    )
    outcome = await db_session.scalar(
        select(ConversationOutcome).where(ConversationOutcome.session_id == voice_session.id)
    )

    # Completion is first-write-wins. Provider retries return the original outcome
    # and cannot silently rewrite an already recorded conversation.
    if outcome is not None:
        _bind_interaction(voice_session, payload.interaction_id)
        if (
            outcome.interaction_id is not None
            and payload.interaction_id is not None
            and outcome.interaction_id != payload.interaction_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Interaction does not match the recorded outcome",
            )
        _record_successful_tool_call(
            db_session,
            voice_session=voice_session,
            tool_name="on_end",
            request_payload={"retry": True},
            response_payload={"idempotent": True, "recorded": True},
            started_at=started_at,
        )
        await db_session.commit()
        http_response.headers["Cache-Control"] = "no-store"
        return OnEndResponse(
            session_id=voice_session.id,
            outcome_id=outcome.id,
            idempotent=True,
        )

    _ensure_session_can_end(
        voice_session,
        completion_grace_minutes=settings.completion_grace_minutes,
    )
    _bind_interaction(voice_session, payload.interaction_id)
    outcome = ConversationOutcome(
        session_id=voice_session.id,
        interaction_id=payload.interaction_id,
        resolution=payload.resolution,
        summary=payload.summary,
        transcript=_bounded_transcript(payload),
        final_variables=_bounded_final_variables(
            payload.final_variables,
            allowed_keys=settings.allowed_final_variable_keys,
        ),
        duration_seconds=payload.duration_seconds,
    )
    db_session.add(outcome)

    voice_session.status = "completed"
    voice_session.active_slot = None
    if voice_session.ended_at is None:
        voice_session.ended_at = datetime.now(UTC)

    _record_successful_tool_call(
        db_session,
        voice_session=voice_session,
        tool_name="on_end",
        request_payload={
            "transcript_turn_count": len(payload.transcript),
            "final_variable_count": len(payload.final_variables),
            "has_interaction_id": payload.interaction_id is not None,
        },
        response_payload={"idempotent": False, "recorded": True},
        started_at=started_at,
    )
    await db_session.commit()
    http_response.headers["Cache-Control"] = "no-store"

    return OnEndResponse(
        session_id=voice_session.id,
        outcome_id=outcome.id,
        idempotent=False,
    )
