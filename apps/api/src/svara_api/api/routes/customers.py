from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_configuration import (
    DEFAULT_AGENT_DISPLAY_NAME,
    DEFAULT_AGENT_INSTRUCTIONS,
    DEFAULT_AGENT_OPENING_MESSAGE,
    DEFAULT_AGENT_TONE,
    resolve_agent_configuration,
)
from ...database import get_db
from ...models import (
    AdminAuditEvent,
    ConversationOutcome,
    Customer,
    CustomerAgentConfiguration,
    CustomerOrder,
    CustomerProfileState,
    User,
    VoiceSession,
    utc_now,
)
from ...schemas import (
    AdminAuditEventResponse,
    AgentConfigurationResponse,
    AgentConfigurationUpdateRequest,
    CustomerDetailResponse,
    CustomerListResponse,
    CustomerSummaryResponse,
    CustomerUpdateRequest,
)
from ...security import Actor, require_tenant_admin
from .conversations import conversation_summary_response

router = APIRouter()
logger = logging.getLogger(__name__)

_RESOLVED_OUTCOMES = ("answered", "completed", "resolved", "success")
_TERMINAL_ORDER_STATUSES = (
    "canceled",
    "cancelled",
    "completed",
    "delivered",
    "refunded",
    "returned",
)
_PROFILE_FIELDS = ("full_name", "preferred_language", "plan_name", "is_active")
_AGENT_CONFIGURATION_FIELDS = ("display_name", "opening_message", "tone", "instructions")
_PROFILE_CONFLICT_DETAIL = (
    "Customer profile was updated by another administrator. Refresh and try again."
)
_AGENT_CONFIGURATION_CONFLICT_DETAIL = (
    "Agent configuration was updated by another administrator. Refresh and try again."
)
_PROFILE_AUDIT_ACTION = "customer.profile_updated"
_AGENT_CONFIGURATION_AUDIT_ACTION = "customer.agent_configuration_updated"


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _initials(full_name: str) -> str:
    parts = full_name.strip().split()
    if not parts:
        return "CU"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[-1][0]}".upper()


def _summary_response(
    customer: Customer,
    *,
    conversation_count: int,
    resolved_conversation_count: int,
    last_conversation_at: datetime | None,
) -> CustomerSummaryResponse:
    return CustomerSummaryResponse(
        id=customer.id,
        external_ref=customer.external_ref,
        full_name=customer.full_name,
        initials=_initials(customer.full_name),
        preferred_language=customer.preferred_language,
        plan_name=customer.plan_name,
        is_active=customer.is_active,
        created_at=_utc_datetime(customer.created_at),
        conversation_count=conversation_count,
        resolved_conversation_count=resolved_conversation_count,
        last_conversation_at=(
            _utc_datetime(last_conversation_at) if last_conversation_at is not None else None
        ),
    )


def _agent_configuration_response(
    configuration: CustomerAgentConfiguration | None,
) -> AgentConfigurationResponse:
    values = resolve_agent_configuration(configuration)
    return AgentConfigurationResponse(
        display_name=values.display_name,
        opening_message=values.opening_message,
        tone=values.tone,
        instructions=values.instructions,
        revision=values.revision,
        updated_at=(_utc_datetime(configuration.updated_at) if configuration is not None else None),
    )


def _audit_event_response(event: AdminAuditEvent) -> AdminAuditEventResponse:
    changed_fields = event.changed_fields if isinstance(event.changed_fields, list) else []
    safe_changed_fields = [field for field in changed_fields if isinstance(field, str)]
    return AdminAuditEventResponse(
        id=event.id,
        action=event.action,
        changed_fields=safe_changed_fields,
        revision=max(event.revision, 1),
        actor_display_name=event.actor_display_name,
        created_at=_utc_datetime(event.created_at),
    )


def _conversation_stat_subqueries() -> tuple[object, object, object]:
    conversation_count = (
        select(func.count(ConversationOutcome.id))
        .select_from(ConversationOutcome)
        .join(VoiceSession, VoiceSession.id == ConversationOutcome.session_id)
        .where(
            VoiceSession.tenant_id == Customer.tenant_id,
            VoiceSession.customer_id == Customer.id,
        )
        .correlate(Customer)
        .scalar_subquery()
    )
    resolved_count = (
        select(func.count(ConversationOutcome.id))
        .select_from(ConversationOutcome)
        .join(VoiceSession, VoiceSession.id == ConversationOutcome.session_id)
        .where(
            VoiceSession.tenant_id == Customer.tenant_id,
            VoiceSession.customer_id == Customer.id,
            func.lower(func.trim(ConversationOutcome.resolution)).in_(_RESOLVED_OUTCOMES),
        )
        .correlate(Customer)
        .scalar_subquery()
    )
    last_conversation_at = (
        select(func.max(VoiceSession.started_at))
        .select_from(VoiceSession)
        .join(ConversationOutcome, ConversationOutcome.session_id == VoiceSession.id)
        .where(
            VoiceSession.tenant_id == Customer.tenant_id,
            VoiceSession.customer_id == Customer.id,
        )
        .correlate(Customer)
        .scalar_subquery()
    )
    return conversation_count, resolved_count, last_conversation_at


async def _load_scoped_customer(
    db_session: AsyncSession,
    *,
    actor: Actor,
    customer_id: str,
    lock: bool = False,
) -> Customer:
    statement = select(Customer).where(
        Customer.id == customer_id,
        Customer.tenant_id == actor.tenant_id,
    )
    if lock:
        statement = statement.with_for_update()
    customer = await db_session.scalar(statement)
    if customer is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Customer not found.",
        )
    return customer


async def _customer_detail_response(
    db_session: AsyncSession,
    *,
    customer: Customer,
) -> CustomerDetailResponse:
    conversation_count, resolved_count, last_conversation_at = _conversation_stat_subqueries()
    stats = (
        await db_session.execute(
            select(conversation_count, resolved_count, last_conversation_at).where(
                Customer.id == customer.id,
                Customer.tenant_id == customer.tenant_id,
            )
        )
    ).one()

    email = await db_session.scalar(
        select(User.email)
        .where(
            User.tenant_id == customer.tenant_id,
            User.customer_id == customer.id,
            User.is_active.is_(True),
        )
        .order_by(User.created_at.asc(), User.id.asc())
        .limit(1)
    )
    open_order_count = await db_session.scalar(
        select(func.count(CustomerOrder.id)).where(
            CustomerOrder.tenant_id == customer.tenant_id,
            CustomerOrder.customer_id == customer.id,
            func.lower(func.trim(CustomerOrder.status)).not_in(_TERMINAL_ORDER_STATUSES),
        )
    )
    recent_rows = (
        await db_session.execute(
            select(VoiceSession, ConversationOutcome)
            .join(ConversationOutcome, ConversationOutcome.session_id == VoiceSession.id)
            .where(
                VoiceSession.tenant_id == customer.tenant_id,
                VoiceSession.customer_id == customer.id,
            )
            .order_by(VoiceSession.started_at.desc(), VoiceSession.id.desc())
            .limit(5)
        )
    ).all()
    profile_state = await db_session.scalar(
        select(CustomerProfileState).where(
            CustomerProfileState.tenant_id == customer.tenant_id,
            CustomerProfileState.customer_id == customer.id,
        )
    )
    agent_configuration = await db_session.scalar(
        select(CustomerAgentConfiguration).where(
            CustomerAgentConfiguration.tenant_id == customer.tenant_id,
            CustomerAgentConfiguration.customer_id == customer.id,
        )
    )
    audit_events = (
        await db_session.scalars(
            select(AdminAuditEvent)
            .where(
                AdminAuditEvent.tenant_id == customer.tenant_id,
                AdminAuditEvent.customer_id == customer.id,
            )
            .order_by(AdminAuditEvent.created_at.desc(), AdminAuditEvent.id.desc())
            .limit(10)
        )
    ).all()

    summary = _summary_response(
        customer,
        conversation_count=stats[0] or 0,
        resolved_conversation_count=stats[1] or 0,
        last_conversation_at=stats[2],
    )
    return CustomerDetailResponse(
        **summary.model_dump(),
        email=email,
        open_order_count=open_order_count or 0,
        profile_revision=max(profile_state.revision, 1) if profile_state is not None else 1,
        agent_configuration=_agent_configuration_response(agent_configuration),
        recent_conversations=[
            conversation_summary_response(voice_session, outcome)
            for voice_session, outcome in recent_rows
        ],
        recent_audit_events=[_audit_event_response(event) for event in audit_events],
    )


@router.get("", response_model=CustomerListResponse)
async def list_customers(
    response: Response,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    query: Annotated[str | None, Query(max_length=160)] = None,
    customer_status: Annotated[Literal["all", "active", "inactive"], Query(alias="status")] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0, le=10_000)] = 0,
) -> CustomerListResponse:
    """List customer profiles within the authenticated administrator's tenant."""

    filters = [Customer.tenant_id == actor.tenant_id]
    normalized_query = query.strip().casefold() if query is not None else ""
    if normalized_query:
        filters.append(
            or_(
                func.lower(Customer.full_name).contains(normalized_query, autoescape=True),
                func.lower(Customer.external_ref).contains(normalized_query, autoescape=True),
            )
        )
    if customer_status != "all":
        filters.append(Customer.is_active.is_(customer_status == "active"))

    total = await db_session.scalar(select(func.count(Customer.id)).where(*filters))
    conversation_count, resolved_count, last_conversation_at = _conversation_stat_subqueries()
    rows = (
        await db_session.execute(
            select(Customer, conversation_count, resolved_count, last_conversation_at)
            .where(*filters)
            .order_by(Customer.created_at.desc(), Customer.full_name.asc(), Customer.id.asc())
            .offset(offset)
            .limit(limit)
        )
    ).all()

    response.headers["Cache-Control"] = "no-store"
    return CustomerListResponse(
        items=[
            _summary_response(
                customer,
                conversation_count=row_conversation_count or 0,
                resolved_conversation_count=row_resolved_count or 0,
                last_conversation_at=row_last_conversation_at,
            )
            for (
                customer,
                row_conversation_count,
                row_resolved_count,
                row_last_conversation_at,
            ) in rows
        ],
        total=total or 0,
    )


@router.get("/{customer_id}", response_model=CustomerDetailResponse)
async def get_customer(
    customer_id: Annotated[str, Path(min_length=1, max_length=64)],
    response: Response,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerDetailResponse:
    """Return one customer profile, scoped to the administrator's tenant."""

    customer = await _load_scoped_customer(
        db_session,
        actor=actor,
        customer_id=customer_id,
    )
    detail = await _customer_detail_response(db_session, customer=customer)
    response.headers["Cache-Control"] = "no-store"
    return detail


@router.patch("/{customer_id}", response_model=CustomerDetailResponse)
async def update_customer(
    payload: CustomerUpdateRequest,
    customer_id: Annotated[str, Path(min_length=1, max_length=64)],
    response: Response,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerDetailResponse:
    """Update the small, explicitly allowlisted set of editable customer fields."""

    customer = await _load_scoped_customer(
        db_session,
        actor=actor,
        customer_id=customer_id,
        lock=True,
    )
    profile_state = await db_session.scalar(
        select(CustomerProfileState)
        .where(
            CustomerProfileState.tenant_id == actor.tenant_id,
            CustomerProfileState.customer_id == customer.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current_revision = max(profile_state.revision, 1) if profile_state is not None else 1
    if payload.expected_revision != current_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_PROFILE_CONFLICT_DETAIL,
        )

    changed_fields = [
        field_name
        for field_name in _PROFILE_FIELDS
        if field_name in payload.model_fields_set
        and getattr(customer, field_name) != getattr(payload, field_name)
    ]
    if not changed_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No customer changes were detected.",
        )

    if "is_active" in changed_fields and payload.is_active is False:
        active_session_id = await db_session.scalar(
            select(VoiceSession.id)
            .where(
                VoiceSession.tenant_id == actor.tenant_id,
                VoiceSession.customer_id == customer.id,
                VoiceSession.active_slot.is_not(None),
            )
            .limit(1)
        )
        if active_session_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The customer's active voice session must end before deactivation.",
            )

    for field_name in changed_fields:
        setattr(customer, field_name, getattr(payload, field_name))

    next_revision = current_revision + 1
    now = utc_now()
    if profile_state is None:
        profile_state = CustomerProfileState(
            tenant_id=actor.tenant_id,
            customer_id=customer.id,
            revision=next_revision,
            updated_at=now,
        )
        db_session.add(profile_state)
    else:
        profile_state.revision = next_revision
        profile_state.updated_at = now
    db_session.add(
        AdminAuditEvent(
            tenant_id=actor.tenant_id,
            customer_id=customer.id,
            actor_user_id=actor.user_id,
            actor_display_name=actor.display_name,
            action=_PROFILE_AUDIT_ACTION,
            changed_fields=changed_fields,
            revision=next_revision,
            created_at=now,
        )
    )

    try:
        await db_session.commit()
    except SQLAlchemyError as exc:
        await db_session.rollback()
        logger.exception("Database failure while updating a customer")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update customer.",
        ) from exc

    detail = await _customer_detail_response(db_session, customer=customer)
    response.headers["Cache-Control"] = "no-store"
    return detail


@router.patch(
    "/{customer_id}/agent-configuration",
    response_model=CustomerDetailResponse,
)
async def update_customer_agent_configuration(
    payload: AgentConfigurationUpdateRequest,
    customer_id: Annotated[str, Path(min_length=1, max_length=64)],
    response: Response,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> CustomerDetailResponse:
    """Update one tenant-scoped agent configuration with optimistic concurrency."""

    customer = await _load_scoped_customer(
        db_session,
        actor=actor,
        customer_id=customer_id,
        lock=True,
    )
    configuration = await db_session.scalar(
        select(CustomerAgentConfiguration)
        .where(
            CustomerAgentConfiguration.tenant_id == actor.tenant_id,
            CustomerAgentConfiguration.customer_id == customer.id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current_revision = max(configuration.revision, 1) if configuration is not None else 1
    if payload.expected_revision != current_revision:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_AGENT_CONFIGURATION_CONFLICT_DETAIL,
        )

    current_values = {
        "display_name": (
            configuration.display_name if configuration is not None else DEFAULT_AGENT_DISPLAY_NAME
        ),
        "opening_message": (
            configuration.opening_message
            if configuration is not None
            else DEFAULT_AGENT_OPENING_MESSAGE
        ),
        "tone": configuration.tone if configuration is not None else DEFAULT_AGENT_TONE,
        "instructions": (
            configuration.instructions if configuration is not None else DEFAULT_AGENT_INSTRUCTIONS
        ),
    }
    changed_fields = [
        field_name
        for field_name in _AGENT_CONFIGURATION_FIELDS
        if field_name in payload.model_fields_set
        and current_values[field_name] != getattr(payload, field_name)
    ]
    if not changed_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No agent configuration changes were detected.",
        )

    next_revision = current_revision + 1
    now = utc_now()
    if configuration is None:
        updated_values = {
            field_name: (
                getattr(payload, field_name)
                if field_name in changed_fields
                else current_values[field_name]
            )
            for field_name in _AGENT_CONFIGURATION_FIELDS
        }
        configuration = CustomerAgentConfiguration(
            tenant_id=actor.tenant_id,
            customer_id=customer.id,
            display_name=updated_values["display_name"],
            opening_message=updated_values["opening_message"],
            tone=updated_values["tone"],
            instructions=updated_values["instructions"],
            revision=next_revision,
            updated_at=now,
        )
        db_session.add(configuration)
    else:
        for field_name in changed_fields:
            setattr(configuration, field_name, getattr(payload, field_name))
        configuration.revision = next_revision
        configuration.updated_at = now
    db_session.add(
        AdminAuditEvent(
            tenant_id=actor.tenant_id,
            customer_id=customer.id,
            actor_user_id=actor.user_id,
            actor_display_name=actor.display_name,
            action=_AGENT_CONFIGURATION_AUDIT_ACTION,
            changed_fields=changed_fields,
            revision=next_revision,
            created_at=now,
        )
    )

    try:
        await db_session.commit()
    except SQLAlchemyError as exc:
        await db_session.rollback()
        logger.exception("Database failure while updating an agent configuration")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to update agent configuration.",
        ) from exc

    detail = await _customer_detail_response(db_session, customer=customer)
    response.headers["Cache-Control"] = "no-store"
    return detail
