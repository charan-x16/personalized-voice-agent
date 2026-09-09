"""Run a read-only connectivity and core-schema check against the configured database."""

from __future__ import annotations

import asyncio

from sqlalchemy import func, select

from svara_api.config import Settings
from svara_api.database import Database
from svara_api.models import (
    CafeReservation,
    CafeTable,
    Customer,
    ReservationPolicy,
    Tenant,
    VoiceSession,
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
            }
        print(counts)
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
