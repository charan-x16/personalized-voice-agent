from __future__ import annotations

import argparse
import asyncio
import json
import ssl
from datetime import UTC, datetime, timedelta
from hashlib import sha256

from sqlalchemy import func, inspect, or_, select, text
from sqlalchemy.engine import make_url

from svara_api.config import Settings
from svara_api.database import Database
from svara_api.models import ConversationOutcome, Customer, Tenant, User, VoiceSession
from svara_api.seed import (
    DEMO_ADMIN_EMAIL,
    DEMO_EMAIL,
    DEMO_TENANT_ID,
    seed_demo_data,
)

REQUIRED_TABLES = {
    "alembic_version",
    "cafe_reservations",
    "cafe_tables",
    "conversation_outcomes",
    "customer_agent_configurations",
    "customer_orders",
    "customer_profile_states",
    "customers",
    "reservation_policies",
    "reservation_tool_operations",
    "tenants",
    "users",
    "voice_sessions",
}

CONVERSATIONS = (
    {
        "session_id": "10000000-0000-4000-8000-000000000001",
        "outcome_id": "20000000-0000-4000-8000-000000000001",
        "customer_ref": "CUS-1042",
        "language": "English",
        "started_at": datetime(2026, 9, 5, 9, 30, tzinfo=UTC),
        "duration_seconds": 164,
        "resolution": "resolved",
        "summary": "Confirmed the Bengaluru delivery window for order ORD-8294.",
        "transcript": [
            {"speaker": "agent", "text": "Hello Rahul, how can I help you today?"},
            {"speaker": "customer", "text": "When will my order arrive?"},
            {
                "speaker": "agent",
                "text": "Order ORD-8294 is in transit and is expected tomorrow morning.",
            },
        ],
        "final_variables": {"order_reference": "ORD-8294", "resolution_code": "resolved"},
    },
    {
        "session_id": "10000000-0000-4000-8000-000000000002",
        "outcome_id": "20000000-0000-4000-8000-000000000002",
        "customer_ref": "CUS-1042",
        "language": "Hindi",
        "started_at": datetime(2026, 9, 6, 14, 15, tzinfo=UTC),
        "duration_seconds": 92,
        "resolution": "follow_up",
        "summary": "Recorded a request for a Hindi-language delivery update.",
        "transcript": [
            {"speaker": "agent", "text": "Namaste Rahul, main aapki kaise madad kar sakti hoon?"},
            {"speaker": "customer", "text": "Mujhe delivery update Hindi mein chahiye."},
            {"speaker": "agent", "text": "Bilkul, maine aapki preference note kar li hai."},
        ],
        "final_variables": {"follow_up": "Hindi delivery update"},
    },
    {
        "session_id": "10000000-0000-4000-8000-000000000003",
        "outcome_id": "20000000-0000-4000-8000-000000000003",
        "customer_ref": "CUS-1187",
        "language": "Hindi",
        "started_at": datetime(2026, 9, 7, 11, 0, tzinfo=UTC),
        "duration_seconds": 138,
        "resolution": "resolved",
        "summary": "Explained that order ORD-8461 is processing and shared its delivery estimate.",
        "transcript": [
            {"speaker": "agent", "text": "Namaste Priya, main aapki kaise madad kar sakti hoon?"},
            {"speaker": "customer", "text": "Mera order abhi kis stage par hai?"},
            {
                "speaker": "agent",
                "text": "Order ORD-8461 processing mein hai aur Friday shaam tak expected hai.",
            },
        ],
        "final_variables": {"order_reference": "ORD-8461", "resolution_code": "resolved"},
    },
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect or idempotently seed non-production Svara test data."
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Insert the test records after all safety checks pass.",
    )
    parser.add_argument(
        "--pooler-host",
        help=(
            "Temporarily route a direct Supabase URL through this official "
            "Supavisor session-pooler hostname."
        ),
    )
    return parser.parse_args()


def settings_with_pooler(settings: Settings, pooler_host: str | None) -> Settings:
    if pooler_host is None:
        return settings
    updated = settings.model_copy(update={"database_pooler_host": pooler_host})
    _ = updated.resolved_database_url
    return updated


async def table_names(database: Database) -> set[str]:
    async with database.engine.connect() as connection:
        return await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))


async def validate_seed_namespace(database: Database) -> None:
    async with database.session_factory() as session:
        tenants = (
            await session.scalars(
                select(Tenant).where(or_(Tenant.id == DEMO_TENANT_ID, Tenant.slug == "acme"))
            )
        ).all()
        if tenants and (
            len(tenants) != 1 or tenants[0].id != DEMO_TENANT_ID or tenants[0].slug != "acme"
        ):
            raise RuntimeError("The reserved test tenant ID or slug is already in use.")

        conflicting_users = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(
                func.lower(User.email).in_((DEMO_EMAIL, DEMO_ADMIN_EMAIL)),
                User.tenant_id != DEMO_TENANT_ID,
            )
        )
        if conflicting_users:
            raise RuntimeError("A reserved test email already belongs to another tenant.")


async def seed_conversations(database: Database) -> None:
    async with database.session_factory() as session:
        customers = {
            customer.external_ref: customer
            for customer in (
                await session.scalars(
                    select(Customer).where(
                        Customer.tenant_id == DEMO_TENANT_ID,
                        Customer.external_ref.in_(
                            conversation["customer_ref"] for conversation in CONVERSATIONS
                        ),
                    )
                )
            ).all()
        }

        for values in CONVERSATIONS:
            customer = customers.get(values["customer_ref"])
            if customer is None:
                continue
            existing_session = await session.scalar(
                select(VoiceSession).where(VoiceSession.id == values["session_id"])
            )
            if existing_session is None:
                started_at = values["started_at"]
                duration_seconds = values["duration_seconds"]
                ended_at = started_at + timedelta(seconds=duration_seconds)
                existing_session = VoiceSession(
                    id=values["session_id"],
                    tenant_id=customer.tenant_id,
                    customer_id=customer.id,
                    provider="mock",
                    provider_session_id=f"seed-{values['session_id']}",
                    conversation_ref_hash=sha256(
                        f"seed-{values['session_id']}".encode()
                    ).hexdigest(),
                    status="completed",
                    language=values["language"],
                    started_at=started_at,
                    expires_at=started_at + timedelta(minutes=15),
                    ended_at=ended_at,
                )
                session.add(existing_session)
                await session.flush()
                existing_session.active_slot = None
                await session.flush()
            elif (
                existing_session.tenant_id != customer.tenant_id
                or existing_session.customer_id != customer.id
                or existing_session.provider_session_id != f"seed-{values['session_id']}"
            ):
                raise RuntimeError("A reserved test conversation ID is already in use.")

            existing_outcome = await session.scalar(
                select(ConversationOutcome.id).where(
                    ConversationOutcome.session_id == values["session_id"]
                )
            )
            if existing_outcome is None:
                outcome_id_is_available = (
                    await session.get(ConversationOutcome, values["outcome_id"])
                ) is None
                if not outcome_id_is_available:
                    raise RuntimeError("A reserved test outcome ID is already in use.")
                session.add(
                    ConversationOutcome(
                        id=values["outcome_id"],
                        session_id=values["session_id"],
                        resolution=values["resolution"],
                        summary=values["summary"],
                        transcript=values["transcript"],
                        final_variables=values["final_variables"],
                        duration_seconds=values["duration_seconds"],
                    )
                )

        await session.commit()


async def database_summary(database: Database, settings: Settings) -> dict[str, object]:
    url = make_url(settings.resolved_database_url)
    async with database.engine.connect() as connection:
        counts = {
            "tenants": int(
                await connection.scalar(select(func.count()).select_from(text("tenants")))
            ),
            "customers": int(
                await connection.scalar(select(func.count()).select_from(text("customers")))
            ),
            "users": int(await connection.scalar(select(func.count()).select_from(text("users")))),
            "orders": int(
                await connection.scalar(select(func.count()).select_from(text("customer_orders")))
            ),
            "agent_configurations": int(
                await connection.scalar(
                    select(func.count()).select_from(text("customer_agent_configurations"))
                )
            ),
            "reservation_policies": int(
                await connection.scalar(
                    select(func.count()).select_from(text("reservation_policies"))
                )
            ),
            "cafe_tables": int(
                await connection.scalar(select(func.count()).select_from(text("cafe_tables")))
            ),
            "cafe_reservations": int(
                await connection.scalar(select(func.count()).select_from(text("cafe_reservations")))
            ),
            "profile_states": int(
                await connection.scalar(
                    select(func.count()).select_from(text("customer_profile_states"))
                )
            ),
            "voice_sessions": int(
                await connection.scalar(select(func.count()).select_from(text("voice_sessions")))
            ),
            "conversations": int(
                await connection.scalar(
                    select(func.count()).select_from(text("conversation_outcomes"))
                )
            ),
        }
        linked_clerk_users = int(
            await connection.scalar(
                select(func.count()).select_from(User).where(User.clerk_user_id.is_not(None))
            )
        )

    return {
        "driver": url.drivername,
        "host": url.host,
        "database": url.database,
        "app_env": settings.app_env,
        "counts": counts,
        "linked_clerk_users": linked_clerk_users,
    }


def safe_error_details(error: Exception) -> dict[str, object]:
    details: dict[str, object] = {"error_type": type(error).__name__}
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        for attribute in ("sqlstate", "constraint_name", "table_name", "column_name"):
            value = getattr(current, attribute, None)
            if value is not None:
                details[attribute] = value
        if isinstance(current, ssl.SSLCertVerificationError):
            details.update(
                {
                    "tls_verify_code": current.verify_code,
                    "tls_verify_message": current.verify_message,
                }
            )
            break
        current = current.__cause__ or current.__context__
    return details


async def run(args: argparse.Namespace) -> int:
    settings = settings_with_pooler(Settings(), args.pooler_host)
    url = make_url(settings.resolved_database_url)
    if settings.app_env == "production":
        print("Refusing to seed test data while APP_ENV=production.")
        return 2
    if url.get_backend_name() != "postgresql":
        print("Refusing to seed: DATABASE_URL is not PostgreSQL.")
        return 2

    print(
        json.dumps(
            {
                "target": {
                    "driver": url.drivername,
                    "host": url.host,
                    "port": url.port,
                    "database": url.database,
                    "app_env": settings.app_env,
                }
            },
            indent=2,
        )
    )
    database = Database(settings)
    try:
        try:
            existing_tables = await table_names(database)
            missing_tables = sorted(REQUIRED_TABLES - existing_tables)
            if missing_tables:
                print(json.dumps({"schema_ready": False, "missing_tables": missing_tables}))
                return 2

            await validate_seed_namespace(database)
            before = await database_summary(database, settings)
            print(json.dumps({"schema_ready": True, "before": before}, indent=2))
            if not args.apply:
                print("Preflight only. Re-run with --apply to insert idempotent test data.")
                return 0

            async with database.session_factory() as session:
                await seed_demo_data(session)
            await seed_conversations(database)
            after = await database_summary(database, settings)
            print(json.dumps({"seeded": True, "after": after}, indent=2))
            return 0
        except Exception as error:
            print(
                json.dumps(
                    {
                        "connection_ready": False,
                        **safe_error_details(error),
                    }
                )
            )
            return 3
    finally:
        await database.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
