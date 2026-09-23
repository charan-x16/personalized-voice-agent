from __future__ import annotations

from datetime import UTC, datetime
from time import perf_counter
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from pydantic import ValidationError
from sqlalchemy import and_, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import (
    Customer,
    CustomerVoiceTool,
    VoiceToolAdminEvent,
    VoiceToolDefinition,
    utc_now,
)
from ...schemas import (
    CancelReservationRequest,
    CheckAvailabilityRequest,
    CreateReservationRequest,
    CustomerProfileToolResponse,
    CustomerVoiceToolListResponse,
    CustomerVoiceToolResponse,
    CustomerVoiceToolUpdateRequest,
    FindReservationRequest,
    OrderStatusRequest,
    RescheduleReservationRequest,
    VoiceToolAdminEventResponse,
    VoiceToolCreateRequest,
    VoiceToolDefinitionResponse,
    VoiceToolExecuteRequest,
    VoiceToolListResponse,
    VoiceToolUpdateRequest,
)
from ...security import Actor, require_tenant_admin, require_voice_tool_key
from . import reservation_tools, sarvam

admin_router = APIRouter()
runtime_router = APIRouter(dependencies=[Depends(require_voice_tool_key)])

_TOOL_CONFLICT = "Tool settings were updated by another administrator. Refresh and try again."
_ASSIGNMENT_CONFLICT = (
    "Customer tool access was updated by another administrator. Refresh and try again."
)


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _definition_response(
    definition: VoiceToolDefinition,
    *,
    assigned_customer_count: int,
) -> VoiceToolDefinitionResponse:
    return VoiceToolDefinitionResponse(
        id=definition.id,
        tool_key=definition.tool_key,
        display_name=definition.display_name,
        description=definition.description,
        capability=definition.capability,  # type: ignore[arg-type]
        is_enabled=definition.is_enabled,
        revision=definition.revision,
        assigned_customer_count=assigned_customer_count,
        created_at=_utc_datetime(definition.created_at),
        updated_at=_utc_datetime(definition.updated_at),
    )


def _admin_event_response(
    event: VoiceToolAdminEvent,
    definition: VoiceToolDefinition,
    customer_reference: str | None,
) -> VoiceToolAdminEventResponse:
    changed_fields = event.changed_fields if isinstance(event.changed_fields, list) else []
    return VoiceToolAdminEventResponse(
        id=event.id,
        action=event.action,  # type: ignore[arg-type]
        tool_id=event.tool_id,
        tool_key=definition.tool_key,
        tool_display_name=definition.display_name,
        customer_id=event.customer_id,
        customer_reference=customer_reference,
        changed_fields=[field for field in changed_fields if isinstance(field, str)],
        revision=event.revision,
        actor_display_name=event.actor_display_name,
        created_at=_utc_datetime(event.created_at),
    )


async def _assignment_counts(
    db: AsyncSession,
    *,
    tenant_id: str,
) -> dict[str, int]:
    rows = (
        await db.execute(
            select(CustomerVoiceTool.tool_id, func.count(CustomerVoiceTool.customer_id))
            .where(
                CustomerVoiceTool.tenant_id == tenant_id,
                CustomerVoiceTool.is_enabled.is_(True),
            )
            .group_by(CustomerVoiceTool.tool_id)
        )
    ).all()
    return {tool_id: int(count) for tool_id, count in rows}


async def _load_definition(
    db: AsyncSession,
    *,
    actor: Actor,
    tool_id: str,
) -> VoiceToolDefinition:
    definition = await db.scalar(
        select(VoiceToolDefinition).where(
            VoiceToolDefinition.id == tool_id,
            VoiceToolDefinition.tenant_id == actor.tenant_id,
        )
    )
    if definition is None:
        raise HTTPException(status_code=404, detail="Voice tool not found.")
    return definition


@admin_router.get("", response_model=VoiceToolListResponse)
async def list_voice_tools(
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    http_response: Response,
) -> VoiceToolListResponse:
    definitions = list(
        (
            await db.scalars(
                select(VoiceToolDefinition)
                .where(VoiceToolDefinition.tenant_id == actor.tenant_id)
                .order_by(VoiceToolDefinition.created_at, VoiceToolDefinition.id)
            )
        ).all()
    )
    counts = await _assignment_counts(db, tenant_id=actor.tenant_id)
    event_rows = (
        await db.execute(
            select(VoiceToolAdminEvent, VoiceToolDefinition, Customer.external_ref)
            .join(
                VoiceToolDefinition,
                and_(
                    VoiceToolDefinition.tenant_id == VoiceToolAdminEvent.tenant_id,
                    VoiceToolDefinition.id == VoiceToolAdminEvent.tool_id,
                ),
            )
            .outerjoin(
                Customer,
                and_(
                    Customer.tenant_id == VoiceToolAdminEvent.tenant_id,
                    Customer.id == VoiceToolAdminEvent.customer_id,
                ),
            )
            .where(VoiceToolAdminEvent.tenant_id == actor.tenant_id)
            .order_by(VoiceToolAdminEvent.created_at.desc(), VoiceToolAdminEvent.id.desc())
            .limit(20)
        )
    ).all()
    http_response.headers["Cache-Control"] = "no-store"
    return VoiceToolListResponse(
        items=[
            _definition_response(item, assigned_customer_count=counts.get(item.id, 0))
            for item in definitions
        ],
        total=len(definitions),
        recent_events=[
            _admin_event_response(event, definition, customer_reference)
            for event, definition, customer_reference in event_rows
        ],
    )


@admin_router.post("", response_model=VoiceToolDefinitionResponse, status_code=201)
async def create_voice_tool(
    payload: VoiceToolCreateRequest,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    http_response: Response,
) -> VoiceToolDefinitionResponse:
    definition = VoiceToolDefinition(
        tenant_id=actor.tenant_id,
        tool_key=payload.tool_key,
        display_name=payload.display_name,
        description=payload.description,
        capability=payload.capability,
        is_enabled=payload.is_enabled,
        revision=1,
        created_by_user_id=actor.user_id,
        updated_by_user_id=actor.user_id,
    )
    db.add(definition)
    try:
        await db.flush()
        db.add(
            VoiceToolAdminEvent(
                tenant_id=actor.tenant_id,
                tool_id=definition.id,
                customer_id=None,
                actor_user_id=actor.user_id,
                actor_display_name=actor.display_name,
                action="voice_tool.created",
                changed_fields=[
                    "tool_key",
                    "display_name",
                    "description",
                    "capability",
                    "is_enabled",
                ],
                revision=1,
            )
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A tool with this key already exists in the workspace.",
        ) from exc
    await db.refresh(definition)
    http_response.headers["Cache-Control"] = "no-store"
    return _definition_response(definition, assigned_customer_count=0)


@admin_router.patch("/{tool_id}", response_model=VoiceToolDefinitionResponse)
async def update_voice_tool(
    payload: VoiceToolUpdateRequest,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    http_response: Response,
    tool_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> VoiceToolDefinitionResponse:
    await _load_definition(db, actor=actor, tool_id=tool_id)
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_none=True)
    result = await db.execute(
        update(VoiceToolDefinition)
        .where(
            VoiceToolDefinition.id == tool_id,
            VoiceToolDefinition.tenant_id == actor.tenant_id,
            VoiceToolDefinition.revision == payload.expected_revision,
        )
        .values(
            **changes,
            revision=VoiceToolDefinition.revision + 1,
            updated_by_user_id=actor.user_id,
            updated_at=utc_now(),
        )
    )
    if result.rowcount != 1:
        await db.rollback()
        raise HTTPException(status_code=409, detail=_TOOL_CONFLICT)
    db.add(
        VoiceToolAdminEvent(
            tenant_id=actor.tenant_id,
            tool_id=tool_id,
            customer_id=None,
            actor_user_id=actor.user_id,
            actor_display_name=actor.display_name,
            action="voice_tool.updated",
            changed_fields=sorted(changes),
            revision=payload.expected_revision + 1,
        )
    )
    await db.commit()
    definition = await _load_definition(db, actor=actor, tool_id=tool_id)
    counts = await _assignment_counts(db, tenant_id=actor.tenant_id)
    http_response.headers["Cache-Control"] = "no-store"
    return _definition_response(definition, assigned_customer_count=counts.get(definition.id, 0))


@admin_router.get(
    "/customer-assignments/{customer_id}",
    response_model=CustomerVoiceToolListResponse,
)
async def list_customer_voice_tools(
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    http_response: Response,
    customer_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> CustomerVoiceToolListResponse:
    customer_exists = await db.scalar(
        select(Customer.id).where(
            Customer.id == customer_id,
            Customer.tenant_id == actor.tenant_id,
        )
    )
    if customer_exists is None:
        raise HTTPException(status_code=404, detail="Customer not found.")

    rows = (
        await db.execute(
            select(VoiceToolDefinition, CustomerVoiceTool)
            .outerjoin(
                CustomerVoiceTool,
                and_(
                    CustomerVoiceTool.tenant_id == VoiceToolDefinition.tenant_id,
                    CustomerVoiceTool.tool_id == VoiceToolDefinition.id,
                    CustomerVoiceTool.customer_id == customer_id,
                ),
            )
            .where(VoiceToolDefinition.tenant_id == actor.tenant_id)
            .order_by(VoiceToolDefinition.created_at, VoiceToolDefinition.id)
        )
    ).all()
    counts = await _assignment_counts(db, tenant_id=actor.tenant_id)
    http_response.headers["Cache-Control"] = "no-store"
    return CustomerVoiceToolListResponse(
        customer_id=customer_id,
        items=[
            CustomerVoiceToolResponse(
                tool=_definition_response(
                    definition,
                    assigned_customer_count=counts.get(definition.id, 0),
                ),
                assigned=assignment is not None,
                is_enabled=assignment.is_enabled if assignment is not None else False,
                revision=assignment.revision if assignment is not None else None,
                updated_at=(
                    _utc_datetime(assignment.updated_at) if assignment is not None else None
                ),
            )
            for definition, assignment in rows
        ],
    )


@admin_router.patch(
    "/customer-assignments/{customer_id}/{tool_id}",
    response_model=CustomerVoiceToolResponse,
)
async def update_customer_voice_tool(
    payload: CustomerVoiceToolUpdateRequest,
    actor: Annotated[Actor, Depends(require_tenant_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    http_response: Response,
    customer_id: Annotated[str, Path(min_length=1, max_length=64)],
    tool_id: Annotated[str, Path(min_length=1, max_length=64)],
) -> CustomerVoiceToolResponse:
    customer_exists = await db.scalar(
        select(Customer.id).where(
            Customer.id == customer_id,
            Customer.tenant_id == actor.tenant_id,
        )
    )
    if customer_exists is None:
        raise HTTPException(status_code=404, detail="Customer not found.")
    definition = await _load_definition(db, actor=actor, tool_id=tool_id)
    assignment = await db.scalar(
        select(CustomerVoiceTool).where(
            CustomerVoiceTool.tenant_id == actor.tenant_id,
            CustomerVoiceTool.customer_id == customer_id,
            CustomerVoiceTool.tool_id == tool_id,
        )
    )

    if assignment is None:
        if payload.expected_revision is not None:
            raise HTTPException(status_code=409, detail=_ASSIGNMENT_CONFLICT)
        assignment = CustomerVoiceTool(
            tenant_id=actor.tenant_id,
            customer_id=customer_id,
            tool_id=tool_id,
            is_enabled=payload.is_enabled,
            revision=1,
            updated_by_user_id=actor.user_id,
        )
        db.add(assignment)
        try:
            db.add(
                VoiceToolAdminEvent(
                    tenant_id=actor.tenant_id,
                    tool_id=tool_id,
                    customer_id=customer_id,
                    actor_user_id=actor.user_id,
                    actor_display_name=actor.display_name,
                    action="customer_voice_tool.updated",
                    changed_fields=["is_enabled"],
                    revision=1,
                )
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise HTTPException(status_code=409, detail=_ASSIGNMENT_CONFLICT) from exc
    else:
        if payload.expected_revision != assignment.revision:
            raise HTTPException(status_code=409, detail=_ASSIGNMENT_CONFLICT)
        result = await db.execute(
            update(CustomerVoiceTool)
            .where(
                CustomerVoiceTool.tenant_id == actor.tenant_id,
                CustomerVoiceTool.customer_id == customer_id,
                CustomerVoiceTool.tool_id == tool_id,
                CustomerVoiceTool.revision == payload.expected_revision,
            )
            .values(
                is_enabled=payload.is_enabled,
                revision=CustomerVoiceTool.revision + 1,
                updated_by_user_id=actor.user_id,
                updated_at=utc_now(),
            )
        )
        if result.rowcount != 1:
            await db.rollback()
            raise HTTPException(status_code=409, detail=_ASSIGNMENT_CONFLICT)
        db.add(
            VoiceToolAdminEvent(
                tenant_id=actor.tenant_id,
                tool_id=tool_id,
                customer_id=customer_id,
                actor_user_id=actor.user_id,
                actor_display_name=actor.display_name,
                action="customer_voice_tool.updated",
                changed_fields=["is_enabled"],
                revision=payload.expected_revision + 1,
            )
        )
        await db.commit()
        assignment = await db.scalar(
            select(CustomerVoiceTool).where(
                CustomerVoiceTool.tenant_id == actor.tenant_id,
                CustomerVoiceTool.customer_id == customer_id,
                CustomerVoiceTool.tool_id == tool_id,
            )
        )
        assert assignment is not None

    counts = await _assignment_counts(db, tenant_id=actor.tenant_id)
    http_response.headers["Cache-Control"] = "no-store"
    return CustomerVoiceToolResponse(
        tool=_definition_response(
            definition,
            assigned_customer_count=counts.get(definition.id, 0),
        ),
        assigned=True,
        is_enabled=assignment.is_enabled,
        revision=assignment.revision,
        updated_at=_utc_datetime(assignment.updated_at),
    )


def _validation_detail(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]}
        for error in exc.errors(include_url=False)
    ]


@runtime_router.post("/execute/{tool_key}")
async def execute_voice_tool(
    payload: VoiceToolExecuteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    http_response: Response,
    tool_key: Annotated[str, Path(min_length=3, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")],
) -> dict[str, Any]:
    started_at = perf_counter()
    voice_session = await sarvam._load_voice_session(db, payload.conversation_ref)
    sarvam._ensure_session_is_usable(voice_session)
    row = (
        await db.execute(
            select(VoiceToolDefinition, CustomerVoiceTool)
            .join(
                CustomerVoiceTool,
                and_(
                    CustomerVoiceTool.tenant_id == VoiceToolDefinition.tenant_id,
                    CustomerVoiceTool.tool_id == VoiceToolDefinition.id,
                ),
            )
            .where(
                VoiceToolDefinition.tenant_id == voice_session.tenant_id,
                VoiceToolDefinition.tool_key == tool_key,
                VoiceToolDefinition.is_enabled.is_(True),
                CustomerVoiceTool.customer_id == voice_session.customer_id,
                CustomerVoiceTool.is_enabled.is_(True),
            )
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Voice tool is not available for this session")
    definition, _assignment = row

    if definition.capability == "customer_profile":
        if payload.arguments:
            raise HTTPException(status_code=422, detail="This tool does not accept arguments")
        sarvam._bind_interaction(voice_session, payload.interaction_id)
        customer = await db.scalar(
            select(Customer).where(
                Customer.tenant_id == voice_session.tenant_id,
                Customer.id == voice_session.customer_id,
                Customer.is_active.is_(True),
            )
        )
        if customer is None:
            raise HTTPException(status_code=404, detail="Customer context not found")
        response = CustomerProfileToolResponse(
            full_name=customer.full_name,
            preferred_language=customer.preferred_language,
            plan_name=customer.plan_name,
        )
        sarvam._record_successful_tool_call(
            db,
            voice_session=voice_session,
            tool_name=definition.tool_key,
            request_payload={},
            response_payload={"found": True},
            started_at=started_at,
        )
        await db.commit()
        http_response.headers["Cache-Control"] = "no-store"
        return response.model_dump(mode="json")

    dispatch = {
        "order_status": (OrderStatusRequest, sarvam.get_order_status),
        "reservation_availability": (
            CheckAvailabilityRequest,
            reservation_tools.check_availability,
        ),
        "reservation_lookup": (FindReservationRequest, reservation_tools.find_reservation),
        "reservation_create": (CreateReservationRequest, reservation_tools.create_reservation),
        "reservation_reschedule": (
            RescheduleReservationRequest,
            reservation_tools.reschedule_reservation,
        ),
        "reservation_cancel": (
            CancelReservationRequest,
            reservation_tools.cancel_reservation,
        ),
    }
    request_model, handler = dispatch[definition.capability]
    try:
        request_payload = request_model.model_validate(
            {
                **payload.arguments,
                "conversation_ref": payload.conversation_ref,
                "interaction_id": payload.interaction_id,
            }
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=_validation_detail(exc)) from exc

    result = await handler(request_payload, http_response, db)
    return result.model_dump(mode="json")
