"""Run a read-only connectivity and core-schema check against the configured database."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from svara_api.config import Settings
from svara_api.database import Database
from svara_api.models import (
    CafeReservation,
    CafeTable,
    ClerkInvitationOutbox,
    ClerkWebhookEvent,
    Customer,
    CustomerVoiceTool,
    ReservationPolicy,
    Tenant,
    VoiceSession,
    VoiceToolAdminEvent,
    VoiceToolDefinition,
)


async def main() -> None:
    database = Database(Settings())
    try:
        async with database.session_factory() as session:
            counts = {
                "tenants": await session.scalar(select(func.count()).select_from(Tenant)),
                "customers": await session.scalar(select(func.count()).select_from(Customer)),
                "voice_sessions": await session.scalar(
                    select(func.count()).select_from(VoiceSession)
                ),
                "reservation_policies": await session.scalar(
                    select(func.count()).select_from(ReservationPolicy)
                ),
                "cafe_tables": await session.scalar(select(func.count()).select_from(CafeTable)),
                "cafe_reservations": await session.scalar(
                    select(func.count()).select_from(CafeReservation)
                ),
                "clerk_invitation_outbox": await session.scalar(
                    select(func.count()).select_from(ClerkInvitationOutbox)
                ),
                "clerk_webhook_events": await session.scalar(
                    select(func.count()).select_from(ClerkWebhookEvent)
                ),
                "voice_tool_definitions": await session.scalar(
                    select(func.count()).select_from(VoiceToolDefinition)
                ),
                "customer_voice_tools": await session.scalar(
                    select(func.count()).select_from(CustomerVoiceTool)
                ),
                "voice_tool_admin_events": await session.scalar(
                    select(func.count()).select_from(VoiceToolAdminEvent)
                ),
            }
        print(counts)
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
