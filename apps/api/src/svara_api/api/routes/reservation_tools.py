from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from secrets import token_hex
from time import perf_counter
from typing import Annotated, Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import get_db
from ...models import (
    CafeReservation,
    CafeTable,
    Customer,
    ReservationPolicy,
    ReservationToolOperation,
    VoiceSession,
    utc_now,
)
from ...schemas import (
    AvailabilitySlot,
    CancelReservationRequest,
    CheckAvailabilityRequest,
    CheckAvailabilityResponse,
    CreateReservationRequest,
    FindReservationRequest,
    FindReservationResponse,
    RescheduleReservationRequest,
    ReservationDetails,
    ReservationMutationResponse,
)
from ...security import require_voice_tool_key
from .sarvam import (
    _bind_interaction,
    _ensure_session_is_usable,
    _load_voice_session,
    _record_successful_tool_call,
    _utc_datetime,
)

router = APIRouter(dependencies=[Depends(require_voice_tool_key)])

_MAX_RETURNED_SLOTS = 5
_MAX_RETURNED_RESERVATIONS = 5


def _timezone(policy: ReservationPolicy) -> ZoneInfo:
    try:
        return ZoneInfo(policy.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reservation timezone is not configured correctly",
        ) from exc


async def _load_policy(db: AsyncSession, tenant_id: str) -> ReservationPolicy:
    policy = await db.get(ReservationPolicy, tenant_id)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Reservations are not configured for this workspace",
        )
    return policy


def _local_window(
    policy: ReservationPolicy,
    reservation_date: date,
) -> tuple[datetime, datetime]:
    timezone = _timezone(policy)
    opens_at = datetime.combine(reservation_date, policy.opening_time, timezone)
    closes_at = datetime.combine(reservation_date, policy.closing_time, timezone)
    return opens_at, closes_at


def _validate_start(
    policy: ReservationPolicy,
    requested_start: datetime,
    *,
    now: datetime,
) -> tuple[datetime, datetime]:
    timezone = _timezone(policy)
    local_start = requested_start.astimezone(timezone)
    local_now = now.astimezone(timezone)
    latest_date = local_now.date() + timedelta(days=policy.advance_booking_days)

    if local_start <= local_now:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reservation time must be in the future",
        )
    if local_start.date() > latest_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reservation time is outside the advance-booking window",
        )
    if local_start.second or local_start.microsecond:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reservation time must align to a configured slot",
        )

    opens_at, closes_at = _local_window(policy, local_start.date())
    minutes_since_open = int((local_start - opens_at).total_seconds() // 60)
    local_end = local_start + timedelta(minutes=policy.reservation_duration_minutes)
    if (
        local_start < opens_at
        or local_end > closes_at
        or minutes_since_open % policy.slot_interval_minutes != 0
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Reservation time is outside configured business slots",
        )

    return local_start.astimezone(UTC), local_end.astimezone(UTC)


async def _available_table(
    db: AsyncSession,
    *,
    tenant_id: str,
    party_size: int,
    start_at: datetime,
    end_at: datetime,
    exclude_reservation_id: str | None = None,
    lock: bool = False,
) -> CafeTable | None:
    table_statement = (
        select(CafeTable)
        .where(
            CafeTable.tenant_id == tenant_id,
            CafeTable.is_active.is_(True),
            CafeTable.capacity >= party_size,
        )
        .order_by(CafeTable.capacity, CafeTable.id)
    )
    if lock:
        table_statement = table_statement.with_for_update()
    tables = list((await db.scalars(table_statement)).all())

    for cafe_table in tables:
        overlap_statement = select(CafeReservation.id).where(
            CafeReservation.tenant_id == tenant_id,
            CafeReservation.cafe_table_id == cafe_table.id,
            CafeReservation.status == "confirmed",
            CafeReservation.start_at < end_at,
            CafeReservation.end_at > start_at,
        )
        if exclude_reservation_id is not None:
            overlap_statement = overlap_statement.where(
                CafeReservation.id != exclude_reservation_id
            )
        overlap = await db.scalar(overlap_statement.limit(1))
        if overlap is None:
            return cafe_table
    return None


def _request_fingerprint(tool_name: str, values: dict[str, Any]) -> str:
    encoded = json.dumps(
        {"tool": tool_name, **values},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def _stored_operation(
    db: AsyncSession,
    *,
    voice_session: VoiceSession,
    tool_name: str,
    fingerprint: str,
) -> ReservationToolOperation | None:
    return await db.scalar(
        select(ReservationToolOperation).where(
            ReservationToolOperation.tenant_id == voice_session.tenant_id,
            ReservationToolOperation.voice_session_id == voice_session.id,
            ReservationToolOperation.tool_name == tool_name,
            ReservationToolOperation.request_fingerprint == fingerprint,
        )
    )


def _reservation_details(
    reservation: CafeReservation,
    policy: ReservationPolicy,
) -> ReservationDetails:
    return ReservationDetails(
        reservation_reference=reservation.reservation_reference,
        status=reservation.status,  # type: ignore[arg-type]
        guest_name=reservation.guest_name,
        party_size=reservation.party_size,
        start_at=_utc_datetime(reservation.start_at),
        end_at=_utc_datetime(reservation.end_at),
        service_location=policy.service_location,
        timezone=policy.timezone,
        special_requests=reservation.special_requests,
        version=reservation.version,
    )


def _replayed_response(operation: ReservationToolOperation) -> ReservationMutationResponse:
    return ReservationMutationResponse.model_validate(
        {"reservation": operation.response_payload, "idempotent": True}
    )


async def _new_reference(db: AsyncSession, tenant_id: str) -> str:
    for _ in range(5):
        reference = f"RSV-{token_hex(5).upper()}"
        existing = await db.scalar(
            select(CafeReservation.id).where(
                CafeReservation.tenant_id == tenant_id,
                CafeReservation.reservation_reference == reference,
            )
        )
        if existing is None:
            return reference
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not allocate a reservation reference",
    )


def _store_operation(
    db: AsyncSession,
    *,
    voice_session: VoiceSession,
    reservation: CafeReservation,
    tool_name: str,
    fingerprint: str,
    details: ReservationDetails,
) -> None:
    db.add(
        ReservationToolOperation(
            tenant_id=voice_session.tenant_id,
            voice_session_id=voice_session.id,
            reservation_id=reservation.id,
            tool_name=tool_name,
            request_fingerprint=fingerprint,
            response_payload=details.model_dump(mode="json"),
        )
    )


@router.post("/tools/check-availability", response_model=CheckAvailabilityResponse)
async def check_availability(
    payload: CheckAvailabilityRequest,
    http_response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CheckAvailabilityResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(db, payload.conversation_ref, lock=True)
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)
    policy = await _load_policy(db, voice_session.tenant_id)
    timezone = _timezone(policy)
    local_now = utc_now().astimezone(timezone)
    reason: str | None = None
    slots: list[AvailabilitySlot] = []

    if payload.party_size > policy.max_party_size:
        reason = f"The maximum supported party size is {policy.max_party_size}."
    elif payload.reservation_date < local_now.date():
        reason = "The requested date is in the past."
    elif payload.reservation_date > local_now.date() + timedelta(days=policy.advance_booking_days):
        reason = "The requested date is outside the advance-booking window."
    else:
        opens_at, closes_at = _local_window(policy, payload.reservation_date)
        latest_start = closes_at - timedelta(minutes=policy.reservation_duration_minutes)
        preferred = datetime.combine(payload.reservation_date, payload.preferred_time, timezone)
        candidates: list[datetime] = []
        candidate = opens_at
        while candidate <= latest_start:
            if candidate > local_now:
                candidates.append(candidate)
            candidate += timedelta(minutes=policy.slot_interval_minutes)

        candidates.sort(key=lambda value: (abs((value - preferred).total_seconds()), value))
        for local_start in candidates:
            start_at = local_start.astimezone(UTC)
            end_at = (
                local_start + timedelta(minutes=policy.reservation_duration_minutes)
            ).astimezone(UTC)
            if await _available_table(
                db,
                tenant_id=voice_session.tenant_id,
                party_size=payload.party_size,
                start_at=start_at,
                end_at=end_at,
            ):
                slots.append(
                    AvailabilitySlot(
                        start_at=local_start,
                        end_at=local_start + timedelta(minutes=policy.reservation_duration_minutes),
                        display_time=local_start.strftime("%I:%M %p").lstrip("0"),
                    )
                )
            if len(slots) == _MAX_RETURNED_SLOTS:
                break
        slots.sort(key=lambda slot: slot.start_at)
        if not slots:
            reason = "No tables are available near the requested time."

    response = CheckAvailabilityResponse(
        available=bool(slots),
        service_location=policy.service_location,
        timezone=policy.timezone,
        party_size=payload.party_size,
        slots=slots,
        reason=reason,
    )
    _record_successful_tool_call(
        db,
        voice_session=voice_session,
        tool_name="check_availability",
        request_payload={"party_size": payload.party_size},
        response_payload={"available": response.available, "slot_count": len(slots)},
        started_at=started_at,
    )
    await db.commit()
    http_response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/tools/create-reservation", response_model=ReservationMutationResponse)
async def create_reservation(
    payload: CreateReservationRequest,
    http_response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReservationMutationResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(db, payload.conversation_ref, lock=True)
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)
    policy = await _load_policy(db, voice_session.tenant_id)
    if payload.party_size > policy.max_party_size:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Party size exceeds the configured maximum of {policy.max_party_size}",
        )
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == voice_session.tenant_id,
            Customer.id == voice_session.customer_id,
            Customer.is_active.is_(True),
        )
    )
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer context not found")

    start_at, end_at = _validate_start(policy, payload.start_at, now=utc_now())
    guest_name = payload.guest_name or customer.full_name
    fingerprint = _request_fingerprint(
        "create_reservation",
        {
            "start_at": start_at.isoformat(),
            "party_size": payload.party_size,
            "guest_name": guest_name,
            "special_requests": payload.special_requests,
        },
    )
    operation = await _stored_operation(
        db,
        voice_session=voice_session,
        tool_name="create_reservation",
        fingerprint=fingerprint,
    )
    if operation is not None:
        await db.commit()
        http_response.headers["Cache-Control"] = "no-store"
        return _replayed_response(operation)

    cafe_table = await _available_table(
        db,
        tenant_id=voice_session.tenant_id,
        party_size=payload.party_size,
        start_at=start_at,
        end_at=end_at,
        lock=True,
    )
    if cafe_table is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected reservation time is no longer available",
        )

    reservation = CafeReservation(
        tenant_id=voice_session.tenant_id,
        customer_id=voice_session.customer_id,
        cafe_table_id=cafe_table.id,
        voice_session_id=voice_session.id,
        reservation_reference=await _new_reference(db, voice_session.tenant_id),
        interaction_id=payload.interaction_id,
        guest_name=guest_name,
        party_size=payload.party_size,
        start_at=start_at,
        end_at=end_at,
        special_requests=payload.special_requests,
        status="confirmed",
        version=1,
    )
    db.add(reservation)
    await db.flush()
    details = _reservation_details(reservation, policy)
    _store_operation(
        db,
        voice_session=voice_session,
        reservation=reservation,
        tool_name="create_reservation",
        fingerprint=fingerprint,
        details=details,
    )
    _record_successful_tool_call(
        db,
        voice_session=voice_session,
        tool_name="create_reservation",
        request_payload={"party_size": payload.party_size},
        response_payload={"status": reservation.status},
        started_at=started_at,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The selected reservation time is no longer available",
        ) from exc
    http_response.headers["Cache-Control"] = "no-store"
    return ReservationMutationResponse(reservation=details, idempotent=False)


@router.post("/tools/find-reservation", response_model=FindReservationResponse)
async def find_reservation(
    payload: FindReservationRequest,
    http_response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FindReservationResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(db, payload.conversation_ref, lock=True)
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)
    policy = await _load_policy(db, voice_session.tenant_id)

    statement = select(CafeReservation).where(
        CafeReservation.tenant_id == voice_session.tenant_id,
        CafeReservation.customer_id == voice_session.customer_id,
    )
    if payload.reservation_reference is not None:
        statement = statement.where(
            CafeReservation.reservation_reference == payload.reservation_reference
        )
    else:
        statement = statement.where(
            CafeReservation.status == "confirmed",
            CafeReservation.end_at > utc_now(),
        )
    reservations = list(
        (
            await db.scalars(
                statement.order_by(CafeReservation.start_at).limit(_MAX_RETURNED_RESERVATIONS)
            )
        ).all()
    )
    response = FindReservationResponse(
        found=bool(reservations),
        reservations=[_reservation_details(item, policy) for item in reservations],
    )
    _record_successful_tool_call(
        db,
        voice_session=voice_session,
        tool_name="find_reservation",
        request_payload={"has_reference": payload.reservation_reference is not None},
        response_payload={"found": response.found, "count": len(reservations)},
        started_at=started_at,
    )
    await db.commit()
    http_response.headers["Cache-Control"] = "no-store"
    return response


@router.post("/tools/reschedule-reservation", response_model=ReservationMutationResponse)
async def reschedule_reservation(
    payload: RescheduleReservationRequest,
    http_response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReservationMutationResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(db, payload.conversation_ref, lock=True)
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)
    policy = await _load_policy(db, voice_session.tenant_id)
    new_start_at, new_end_at = _validate_start(policy, payload.new_start_at, now=utc_now())
    fingerprint = _request_fingerprint(
        "reschedule_reservation",
        {
            "reservation_reference": payload.reservation_reference,
            "new_start_at": new_start_at.isoformat(),
            "expected_version": payload.expected_version,
        },
    )
    operation = await _stored_operation(
        db,
        voice_session=voice_session,
        tool_name="reschedule_reservation",
        fingerprint=fingerprint,
    )
    if operation is not None:
        await db.commit()
        http_response.headers["Cache-Control"] = "no-store"
        return _replayed_response(operation)

    reservation = await db.scalar(
        select(CafeReservation)
        .where(
            CafeReservation.tenant_id == voice_session.tenant_id,
            CafeReservation.customer_id == voice_session.customer_id,
            CafeReservation.reservation_reference == payload.reservation_reference,
        )
        .with_for_update()
    )
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.status != "confirmed":
        raise HTTPException(status_code=409, detail="Only confirmed reservations can be moved")
    if reservation.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Reservation was changed; retrieve it again")

    cafe_table = await _available_table(
        db,
        tenant_id=voice_session.tenant_id,
        party_size=reservation.party_size,
        start_at=new_start_at,
        end_at=new_end_at,
        exclude_reservation_id=reservation.id,
        lock=True,
    )
    if cafe_table is None:
        raise HTTPException(status_code=409, detail="The new reservation time is unavailable")

    reservation.cafe_table_id = cafe_table.id
    reservation.start_at = new_start_at
    reservation.end_at = new_end_at
    reservation.interaction_id = payload.interaction_id
    reservation.version += 1
    reservation.updated_at = utc_now()
    details = _reservation_details(reservation, policy)
    _store_operation(
        db,
        voice_session=voice_session,
        reservation=reservation,
        tool_name="reschedule_reservation",
        fingerprint=fingerprint,
        details=details,
    )
    _record_successful_tool_call(
        db,
        voice_session=voice_session,
        tool_name="reschedule_reservation",
        request_payload={"expected_version": payload.expected_version},
        response_payload={"status": reservation.status, "version": reservation.version},
        started_at=started_at,
    )
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="The new reservation time is unavailable"
        ) from exc
    http_response.headers["Cache-Control"] = "no-store"
    return ReservationMutationResponse(reservation=details, idempotent=False)


@router.post("/tools/cancel-reservation", response_model=ReservationMutationResponse)
async def cancel_reservation(
    payload: CancelReservationRequest,
    http_response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ReservationMutationResponse:
    started_at = perf_counter()
    voice_session = await _load_voice_session(db, payload.conversation_ref, lock=True)
    _ensure_session_is_usable(voice_session)
    _bind_interaction(voice_session, payload.interaction_id)
    policy = await _load_policy(db, voice_session.tenant_id)
    fingerprint = _request_fingerprint(
        "cancel_reservation",
        {
            "reservation_reference": payload.reservation_reference,
            "expected_version": payload.expected_version,
        },
    )
    operation = await _stored_operation(
        db,
        voice_session=voice_session,
        tool_name="cancel_reservation",
        fingerprint=fingerprint,
    )
    if operation is not None:
        await db.commit()
        http_response.headers["Cache-Control"] = "no-store"
        return _replayed_response(operation)

    reservation = await db.scalar(
        select(CafeReservation)
        .where(
            CafeReservation.tenant_id == voice_session.tenant_id,
            CafeReservation.customer_id == voice_session.customer_id,
            CafeReservation.reservation_reference == payload.reservation_reference,
        )
        .with_for_update()
    )
    if reservation is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if reservation.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Reservation was changed; retrieve it again")
    if reservation.status == "cancelled":
        details = _reservation_details(reservation, policy)
        _store_operation(
            db,
            voice_session=voice_session,
            reservation=reservation,
            tool_name="cancel_reservation",
            fingerprint=fingerprint,
            details=details,
        )
        _record_successful_tool_call(
            db,
            voice_session=voice_session,
            tool_name="cancel_reservation",
            request_payload={"expected_version": payload.expected_version},
            response_payload={
                "status": reservation.status,
                "version": reservation.version,
                "already_cancelled": True,
            },
            started_at=started_at,
        )
        await db.commit()
        http_response.headers["Cache-Control"] = "no-store"
        return ReservationMutationResponse(
            reservation=details,
            idempotent=True,
        )

    reservation.status = "cancelled"
    reservation.cancelled_at = utc_now()
    reservation.interaction_id = payload.interaction_id
    reservation.version += 1
    reservation.updated_at = utc_now()
    details = _reservation_details(reservation, policy)
    _store_operation(
        db,
        voice_session=voice_session,
        reservation=reservation,
        tool_name="cancel_reservation",
        fingerprint=fingerprint,
        details=details,
    )
    _record_successful_tool_call(
        db,
        voice_session=voice_session,
        tool_name="cancel_reservation",
        request_payload={"expected_version": payload.expected_version},
        response_payload={"status": reservation.status, "version": reservation.version},
        started_at=started_at,
    )
    await db.commit()
    http_response.headers["Cache-Control"] = "no-store"
    return ReservationMutationResponse(reservation=details, idempotent=False)
