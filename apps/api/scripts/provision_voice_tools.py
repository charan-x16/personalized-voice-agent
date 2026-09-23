"""Provision Svara's approved voice tools for explicit tenant customers."""

from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from svara_api.config import Settings
from svara_api.database import Database
from svara_api.models import Customer, Tenant, User
from svara_api.services.tool_catalog import provision_default_tool_catalog


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotently create the default tool catalog and explicit assignments."
    )
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument(
        "--customer-ref",
        action="append",
        dest="customer_refs",
        required=True,
        help="Active external customer reference; repeat for more than one customer.",
    )
    parser.add_argument(
        "--actor-email",
        required=True,
        help="Existing active tenant administrator recorded as the provisioning actor.",
    )
    return parser.parse_args()


async def main() -> None:
    options = arguments()
    database = Database(Settings())
    try:
        async with database.session_factory() as session:
            tenant = await session.scalar(
                select(Tenant).where(
                    Tenant.slug == options.tenant_slug.strip(),
                    Tenant.is_active.is_(True),
                )
            )
            if tenant is None:
                raise SystemExit("Active tenant not found")
            actor = await session.scalar(
                select(User).where(
                    User.tenant_id == tenant.id,
                    User.email == options.actor_email.strip().casefold(),
                    User.role == "admin",
                    User.is_active.is_(True),
                )
            )
            if actor is None:
                raise SystemExit("Active tenant administrator not found")

            normalized_refs = tuple(dict.fromkeys(ref.strip() for ref in options.customer_refs))
            customers = list(
                (
                    await session.scalars(
                        select(Customer).where(
                            Customer.tenant_id == tenant.id,
                            Customer.external_ref.in_(normalized_refs),
                            Customer.is_active.is_(True),
                        )
                    )
                ).all()
            )
            if {customer.external_ref for customer in customers} != set(normalized_refs):
                raise SystemExit("Every requested customer must be active in the tenant")

            result = await provision_default_tool_catalog(
                session,
                tenant_id=tenant.id,
                actor_user_id=actor.id,
                actor_display_name=actor.display_name,
                customer_ids=tuple(customer.id for customer in customers),
            )
            await session.commit()
            print(
                {
                    "tenant": tenant.slug,
                    "customer_refs": sorted(normalized_refs),
                    "created_tools": result.created_tools,
                    "existing_tools": result.existing_tools,
                    "created_assignments": result.created_assignments,
                    "existing_assignments": result.existing_assignments,
                }
            )
    finally:
        await database.dispose()


if __name__ == "__main__":
    asyncio.run(main())
