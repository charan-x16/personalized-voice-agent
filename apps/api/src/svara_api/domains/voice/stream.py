from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sarvam_conv_ai_sdk import (
    MsgStatus,
    Role,
    ServerAudioChunkMsg,
    ServerInteractionEndEvent,
    ServerTranscriptMsg,
    ServerUserInterruptEvent,
)
from sarvam_conv_ai_sdk.messages.events import ServerInteractionConnectedEvent
from sqlalchemy import and_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ...agent_configuration import render_opening_message, resolve_agent_configuration
from ...integrations.sarvam.provider import SarvamRelayClaims, SarvamVoiceProvider
from ...models import (
    ConversationOutcome,
    Customer,
    CustomerAgentConfiguration,
    ReservationPolicy,
    Tenant,
    VoiceSession,
    utc_now,
)
from ...security import hash_conversation_ref

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_AUDIO_FRAME_BYTES = 64 * 1024
_MAX_AUDIO_BYTES_PER_SECOND = 128 * 1024
_MAX_CONTROL_MESSAGE_BYTES = 2 * 1024
_MAX_TRANSCRIPT_TURNS = 250
_MAX_TRANSCRIPT_CHARACTERS = 128_000
_MAX_TRANSCRIPT_TURN_CHARACTERS = 8_000
_RELAY_PROTOCOL = "svara-relay"
_RELAY_CREDENTIAL_PROTOCOL_PREFIX = "svara-token."


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _close_before_accept(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except RuntimeError:
        pass


def _relay_token_from_subprotocol(websocket: WebSocket) -> str:
    offered_header = websocket.headers.get("sec-websocket-protocol", "")
    offered_protocols = [item.strip() for item in offered_header.split(",") if item.strip()]
    token_protocols = [
        item for item in offered_protocols if item.startswith(_RELAY_CREDENTIAL_PROTOCOL_PREFIX)
    ]
    if _RELAY_PROTOCOL not in offered_protocols or len(token_protocols) != 1:
        raise ValueError("Missing voice relay credential")
    token = token_protocols[0][len(_RELAY_CREDENTIAL_PROTOCOL_PREFIX) :]
    if not token or len(token) > 8_192 or "=" in token:
        raise ValueError("Invalid voice relay credential")
    return token + "=" * (-len(token) % 4)


async def _reserve_relay_session(
    websocket: WebSocket,
    provider: SarvamVoiceProvider,
    token: str,
) -> tuple[SarvamRelayClaims, dict[str, str], str]:
    claims = provider.decode_relay_token(token)
    database = websocket.app.state.database

    async with database.session_factory() as db:
        row = (
            await db.execute(
                select(VoiceSession, Customer, Tenant, CustomerAgentConfiguration)
                .join(
                    Customer,
                    and_(
                        Customer.id == VoiceSession.customer_id,
                        Customer.tenant_id == VoiceSession.tenant_id,
                    ),
                )
                .join(Tenant, Tenant.id == VoiceSession.tenant_id)
                .outerjoin(
                    CustomerAgentConfiguration,
                    and_(
                        CustomerAgentConfiguration.customer_id == VoiceSession.customer_id,
                        CustomerAgentConfiguration.tenant_id == VoiceSession.tenant_id,
                    ),
                )
                .where(VoiceSession.id == claims.session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Voice session is unavailable")

        voice_session, customer, tenant, stored_agent_configuration = row
        now = utc_now()
        if (
            voice_session.provider != provider.name
            or voice_session.provider_session_id != claims.session_id
            or voice_session.conversation_ref_hash != hash_conversation_ref(claims.conversation_ref)
            or voice_session.status.casefold() != "ready"
            or voice_session.active_slot != 1
            or _as_utc(voice_session.expires_at) <= now
            or claims.expires_at > _as_utc(voice_session.expires_at)
            or not customer.is_active
            or not tenant.is_active
        ):
            raise ValueError("Voice session is unavailable")

        configuration = resolve_agent_configuration(stored_agent_configuration)
        reservation_policy = await db.get(ReservationPolicy, voice_session.tenant_id)
        name_parts = customer.full_name.split()
        first_name = name_parts[0] if name_parts else "Customer"
        service_provider_name = (
            reservation_policy.service_provider_name if reservation_policy else tenant.name
        )
        service_location = (
            reservation_policy.service_location if reservation_policy else tenant.name
        )
        business_hours = (
            (
                f"Daily {reservation_policy.opening_time.strftime('%I:%M %p').lstrip('0')}–"
                f"{reservation_policy.closing_time.strftime('%I:%M %p').lstrip('0')} "
                f"({reservation_policy.timezone})"
            )
            if reservation_policy
            else "Contact the service provider for current hours"
        )
        agent_variables = {
            **claims.agent_variables,
            "user_name": first_name,
            "customer_name": customer.full_name,
            "customer_plan": customer.plan_name,
            "service_provider_name": service_provider_name,
            "service_location": service_location,
            "business_hours": business_hours,
            "agent_display_name": configuration.display_name,
            "agent_tone": configuration.tone,
            "customer_instructions": configuration.instructions,
            "current_date": now.date().isoformat(),
        }
        opening_message = render_opening_message(
            configuration.opening_message,
            first_name=first_name,
        )
        voice_session.status = "active"
        await db.commit()

    return claims, agent_variables, opening_message


async def _finalize_relay_session(
    websocket: WebSocket,
    *,
    session_id: str,
    interaction_id: str | None,
    transcript: list[dict[str, Any]],
    started_at: datetime,
    failed_before_connect: bool,
) -> None:
    database = websocket.app.state.database
    async with database.session_factory() as db:
        try:
            voice_session = await db.scalar(
                select(VoiceSession)
                .where(VoiceSession.id == session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if voice_session is None:
                return

            current_status = voice_session.status.casefold()
            if failed_before_connect and current_status in {"ready", "active"}:
                voice_session.status = "failed"
                voice_session.active_slot = None
                voice_session.ended_at = voice_session.ended_at or utc_now()
                await db.commit()
                return

            if current_status not in {"ready", "active"}:
                return

            existing_outcome = await db.scalar(
                select(ConversationOutcome).where(
                    ConversationOutcome.session_id == voice_session.id
                )
            )
            if existing_outcome is None:
                last_agent_turn = next(
                    (
                        turn["text"]
                        for turn in reversed(transcript)
                        if turn.get("speaker") == "agent"
                    ),
                    None,
                )
                db.add(
                    ConversationOutcome(
                        session_id=voice_session.id,
                        interaction_id=interaction_id,
                        resolution="unknown",
                        summary=last_agent_turn or "Voice conversation completed.",
                        transcript=transcript,
                        final_variables={},
                        duration_seconds=max(
                            0,
                            int((utc_now() - started_at).total_seconds()),
                        ),
                    )
                )

            if voice_session.provider_interaction_id is None and interaction_id is not None:
                voice_session.provider_interaction_id = interaction_id
            voice_session.status = "completed"
            voice_session.active_slot = None
            voice_session.ended_at = voice_session.ended_at or utc_now()
            await db.commit()
        except IntegrityError:
            # A configured Sarvam on-end tool may win the first-write outcome race.
            await db.rollback()
        except SQLAlchemyError:
            await db.rollback()
            logger.exception("Unable to finalize Sarvam relay session %s", session_id)


@router.websocket("/stream")
async def stream_voice(websocket: WebSocket) -> None:
    """Relay browser PCM audio to the official server-side Sarvam Agents SDK."""

    settings = websocket.app.state.settings
    origin = websocket.headers.get("origin")
    if origin is None or origin not in settings.cors_origins:
        await _close_before_accept(websocket, 4403)
        return

    provider = websocket.app.state.voice_provider
    if not isinstance(provider, SarvamVoiceProvider):
        await _close_before_accept(websocket, 4404)
        return

    try:
        token = _relay_token_from_subprotocol(websocket)
        claims, agent_variables, opening_message = await _reserve_relay_session(
            websocket,
            provider,
            token,
        )
    except (ValueError, UnicodeError, SQLAlchemyError):
        await _close_before_accept(websocket, 4401)
        return

    await websocket.accept(subprotocol=_RELAY_PROTOCOL)
    started_at = utc_now()
    connected = False
    client_closed = False
    interaction_ended = asyncio.Event()
    interaction_connected = asyncio.Event()
    send_lock = asyncio.Lock()
    interaction_id: str | None = None
    transcript: list[dict[str, Any]] = []
    transcript_characters = 0
    agent = None

    async def send_json(payload: dict[str, Any]) -> None:
        nonlocal client_closed
        if client_closed:
            return
        try:
            async with send_lock:
                await websocket.send_json(payload)
        except (RuntimeError, WebSocketDisconnect):
            client_closed = True

    async def send_audio(message: ServerAudioChunkMsg) -> None:
        nonlocal client_closed
        if client_closed:
            return
        if message.audio_base64:
            try:
                audio = base64.b64decode(message.audio_base64, validate=True)
            except (binascii.Error, ValueError, TypeError):
                return
            if not audio or len(audio) > _MAX_AUDIO_FRAME_BYTES:
                return
            try:
                async with send_lock:
                    await websocket.send_bytes(audio)
            except (RuntimeError, WebSocketDisconnect):
                client_closed = True
                return
        if message.status == MsgStatus.COMPLETED:
            await send_json({"type": "state", "state": "listening"})

    async def record_transcript(message: ServerTranscriptMsg) -> None:
        nonlocal transcript_characters
        text = message.content.strip()[:_MAX_TRANSCRIPT_TURN_CHARACTERS]
        if not text:
            return
        speaker = "customer" if message.role == Role.USER else "agent"
        if (
            len(transcript) < _MAX_TRANSCRIPT_TURNS
            and transcript_characters < _MAX_TRANSCRIPT_CHARACTERS
        ):
            text = text[: _MAX_TRANSCRIPT_CHARACTERS - transcript_characters]
            transcript_characters += len(text)
            transcript.append({"speaker": speaker, "text": text, "timestamp": None})
        await send_json(
            {
                "type": "transcript",
                "turn_id": f"{speaker}-{len(transcript)}",
                "speaker": speaker,
                "text": text,
                "final": True,
            }
        )
        await send_json(
            {
                "type": "state",
                "state": "thinking" if speaker == "customer" else "speaking",
            }
        )

    async def handle_event(event: Any) -> None:
        nonlocal interaction_id
        if isinstance(event, ServerInteractionConnectedEvent):
            interaction_id = event.interaction_id
            interaction_connected.set()
            await send_json({"type": "connected"})
            await send_json({"type": "state", "state": "listening"})
        elif isinstance(event, ServerUserInterruptEvent):
            await send_json({"type": "interrupt"})
            await send_json({"type": "state", "state": "listening"})
        elif isinstance(event, ServerInteractionEndEvent):
            interaction_ended.set()

    failed_before_connect = False
    disconnect_task: asyncio.Task[None] | None = None
    receive_task: asyncio.Task[dict[str, Any]] | None = None
    end_task: asyncio.Task[bool] | None = None
    try:
        agent = await provider.activate_agent(
            claims,
            agent_variables=agent_variables,
            initial_bot_message=opening_message,
            audio_callback=send_audio,
            transcript_callback=record_transcript,
            event_callback=handle_event,
        )
        try:
            await asyncio.wait_for(interaction_connected.wait(), timeout=15.0)
        except TimeoutError as exc:
            raise RuntimeError("Sarvam did not acknowledge the interaction") from exc
        connected = True

        disconnect_task = asyncio.create_task(agent.wait_for_disconnect())
        receive_task = asyncio.create_task(websocket.receive())
        end_task = asyncio.create_task(interaction_ended.wait())
        window_started = asyncio.get_running_loop().time()
        window_audio_bytes = 0

        while not client_closed:
            done, _ = await asyncio.wait(
                {receive_task, disconnect_task, end_task},
                timeout=1.0,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if end_task in done:
                await send_json({"type": "completed"})
                break
            if disconnect_task in done:
                await send_json({"type": "completed"})
                break
            if _as_utc(claims.expires_at) <= utc_now():
                await send_json(
                    {
                        "type": "error",
                        "code": "session_expired",
                        "message": "The secure voice session expired.",
                    }
                )
                break
            if receive_task not in done:
                continue

            message = receive_task.result()
            if message["type"] == "websocket.disconnect":
                client_closed = True
                break
            receive_task = asyncio.create_task(websocket.receive())

            audio = message.get("bytes")
            if audio is not None:
                if (
                    not isinstance(audio, bytes)
                    or not audio
                    or len(audio) % 2 != 0
                    or len(audio) > _MAX_AUDIO_FRAME_BYTES
                ):
                    await websocket.close(code=1009)
                    client_closed = True
                    break
                now_monotonic = asyncio.get_running_loop().time()
                if now_monotonic - window_started >= 1.0:
                    window_started = now_monotonic
                    window_audio_bytes = 0
                window_audio_bytes += len(audio)
                if window_audio_bytes > _MAX_AUDIO_BYTES_PER_SECOND:
                    await websocket.close(code=1008)
                    client_closed = True
                    break
                await agent.send_audio(audio)
                continue

            text = message.get("text")
            if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_CONTROL_MESSAGE_BYTES:
                await websocket.close(code=1008)
                client_closed = True
                break
            try:
                control = json.loads(text)
            except json.JSONDecodeError:
                await websocket.close(code=1008)
                client_closed = True
                break
            if control != {"type": "end"}:
                await websocket.close(code=1008)
                client_closed = True
                break
            break
    except Exception:
        failed_before_connect = not connected
        logger.exception("Sarvam browser relay failed for session %s", claims.session_id)
        await send_json(
            {
                "type": "error",
                "code": "provider_unavailable",
                "message": "The live voice service is temporarily unavailable.",
            }
        )
    finally:
        for task in (receive_task, disconnect_task, end_task):
            if task is not None and not task.done():
                task.cancel()
        pending_tasks = [
            task for task in (receive_task, disconnect_task, end_task) if task is not None
        ]
        if pending_tasks:
            await asyncio.gather(*pending_tasks, return_exceptions=True)
        if agent is not None:
            await provider.release_agent(claims.session_id, agent)
        await _finalize_relay_session(
            websocket,
            session_id=claims.session_id,
            interaction_id=interaction_id,
            transcript=transcript,
            started_at=started_at,
            failed_before_connect=failed_before_connect,
        )
        if not client_closed:
            try:
                await websocket.close(code=1000 if connected else 1011)
            except RuntimeError:
                pass
