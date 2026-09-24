from datetime import time
from hashlib import sha256

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_configuration import (
    DEFAULT_AGENT_DISPLAY_NAME,
    DEFAULT_AGENT_INSTRUCTIONS,
    DEFAULT_AGENT_OPENING_MESSAGE,
    DEFAULT_AGENT_TONE,
)
from .domains.tools.catalog import provision_default_tool_catalog
from .models import (
    CafeTable,
    Customer,
    CustomerAgentConfiguration,
    CustomerOrder,
    CustomerProfileState,
    ReservationPolicy,
    Tenant,
    User,
)

DEMO_TENANT_ID = "00000000-0000-4000-8000-000000000001"
DEMO_CUSTOMER_ID = "00000000-0000-4000-8000-000000000002"
DEMO_USER_ID = "00000000-0000-4000-8000-000000000003"
DEMO_ORDER_ID = "00000000-0000-4000-8000-000000000004"
DEMO_EMAIL = "rahul@example.com"
DEMO_ADMIN_USER_ID = "00000000-0000-4000-8000-000000000005"
DEMO_ADMIN_EMAIL = "ananya@example.com"
OWNER_CUSTOMER_ID = "00000000-0000-4000-8000-000000000030"
OWNER_USER_ID = "00000000-0000-4000-8000-000000000031"
OWNER_CUSTOMER_REF = "CUS-1500"

_DEMO_CUSTOMERS = (
    {
        "id": DEMO_CUSTOMER_ID,
        "external_ref": "CUS-1042",
        "full_name": "Rahul Mehta",
        "preferred_language": "English",
        "plan_name": "Essential",
        "phone": b"+910000000000",
        "is_active": True,
    },
    {
        "id": "00000000-0000-4000-8000-000000000006",
        "external_ref": "CUS-1187",
        "full_name": "Priya Shah",
        "preferred_language": "Hindi",
        "plan_name": "Growth",
        "phone": b"+910000000001",
        "is_active": True,
    },
    {
        "id": "00000000-0000-4000-8000-000000000007",
        "external_ref": "CUS-1274",
        "full_name": "Arjun Nair",
        "preferred_language": "Tamil",
        "plan_name": "Premium",
        "phone": b"+910000000002",
        "is_active": True,
    },
    {
        "id": "00000000-0000-4000-8000-000000000008",
        "external_ref": "CUS-1318",
        "full_name": "Meera Iyer",
        "preferred_language": "English",
        "plan_name": "Essential",
        "phone": b"+910000000003",
        "is_active": False,
    },
    {
        "id": "00000000-0000-4000-8000-000000000009",
        "external_ref": "CUS-1395",
        "full_name": "Kabir Singh",
        "preferred_language": "Marathi",
        "plan_name": "Growth",
        "phone": b"+910000000004",
        "is_active": True,
    },
)

_DEMO_ORDERS = (
    {
        "id": DEMO_ORDER_ID,
        "customer_ref": "CUS-1042",
        "external_ref": "ORD-8294",
        "status": "In transit",
        "estimated_arrival": "Tomorrow between 10:00 AM and 12:00 PM",
        "delivery_city": "Bengaluru",
    },
    {
        "id": "00000000-0000-4000-8000-000000000010",
        "customer_ref": "CUS-1187",
        "external_ref": "ORD-8461",
        "status": "Processing",
        "estimated_arrival": "Friday by 6:00 PM",
        "delivery_city": "Mumbai",
    },
    {
        "id": "00000000-0000-4000-8000-000000000011",
        "customer_ref": "CUS-1274",
        "external_ref": "ORD-8513",
        "status": "Delivered",
        "estimated_arrival": None,
        "delivery_city": "Chennai",
    },
)

_DEMO_CAFE_TABLES = (
    ("00000000-0000-4000-8000-000000000020", "T1", 2),
    ("00000000-0000-4000-8000-000000000021", "T2", 2),
    ("00000000-0000-4000-8000-000000000022", "T3", 4),
    ("00000000-0000-4000-8000-000000000023", "T4", 4),
    ("00000000-0000-4000-8000-000000000024", "T5", 6),
    ("00000000-0000-4000-8000-000000000025", "T6", 8),
)


async def _seed_owner_account(
    session: AsyncSession,
    *,
    tenant: Tenant,
    email: str,
    display_name: str,
) -> Customer | None:
    """Seed a local sign-in account so a real identity provider user resolves to a profile."""

    normalized_email = email.strip().casefold()
    normalized_name = display_name.strip() or "Workspace Owner"
    if not normalized_email:
        return None

    customer = await session.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant.id,
            Customer.external_ref == OWNER_CUSTOMER_REF,
        )
    )
    if customer is None:
        if await session.get(Customer, OWNER_CUSTOMER_ID) is not None:
            return None
        customer = Customer(
            id=OWNER_CUSTOMER_ID,
            tenant_id=tenant.id,
            external_ref=OWNER_CUSTOMER_REF,
            full_name=normalized_name,
            preferred_language="English",
            plan_name="Premium",
            phone_hash=sha256(normalized_email.encode("utf-8")).hexdigest(),
            is_active=True,
        )
        session.add(customer)
        await session.flush()

    existing_user = await session.scalar(
        select(User).where(
            User.tenant_id == tenant.id,
            User.email == normalized_email,
        )
    )
    if existing_user is None and await session.get(User, OWNER_USER_ID) is None:
        session.add(
            User(
                id=OWNER_USER_ID,
                tenant_id=tenant.id,
                customer_id=customer.id,
                email=normalized_email,
                display_name=normalized_name,
                role="customer",
            )
        )
        await session.flush()
    return customer


async def seed_demo_data(
    session: AsyncSession,
    *,
    owner_email: str | None = None,
    owner_name: str = "Workspace Owner",
) -> None:
    tenant = await session.scalar(
        select(Tenant).where(
            or_(Tenant.id == DEMO_TENANT_ID, Tenant.slug == "acme"),
        )
    )
    if tenant is None:
        tenant = Tenant(
            id=DEMO_TENANT_ID,
            slug="acme",
            name="Acme Workspace",
        )
        session.add(tenant)
        await session.flush()

    customers_by_ref: dict[str, Customer] = {}
    for values in _DEMO_CUSTOMERS:
        external_ref = str(values["external_ref"])
        customer = await session.scalar(
            select(Customer).where(
                Customer.tenant_id == tenant.id,
                Customer.external_ref == external_ref,
            )
        )
        if customer is None:
            id_is_available = await session.get(Customer, str(values["id"])) is None
            if not id_is_available:
                continue
            customer = Customer(
                id=str(values["id"]),
                tenant_id=tenant.id,
                external_ref=external_ref,
                full_name=str(values["full_name"]),
                preferred_language=str(values["preferred_language"]),
                plan_name=str(values["plan_name"]),
                phone_hash=sha256(bytes(values["phone"])).hexdigest(),
                is_active=bool(values["is_active"]),
            )
            session.add(customer)
            await session.flush()
        customers_by_ref[external_ref] = customer

    rahul = customers_by_ref.get("CUS-1042")
    existing_rahul_user = await session.scalar(
        select(User).where(
            User.tenant_id == tenant.id,
            User.email == DEMO_EMAIL,
        )
    )
    if (
        rahul is not None
        and existing_rahul_user is None
        and await session.get(User, DEMO_USER_ID) is None
    ):
        session.add(
            User(
                id=DEMO_USER_ID,
                tenant_id=tenant.id,
                customer_id=rahul.id,
                email=DEMO_EMAIL,
                display_name="Rahul Mehta",
                role="customer",
            )
        )

    existing_admin = await session.scalar(
        select(User).where(
            User.tenant_id == tenant.id,
            User.email == DEMO_ADMIN_EMAIL,
        )
    )
    if existing_admin is None and await session.get(User, DEMO_ADMIN_USER_ID) is None:
        session.add(
            User(
                id=DEMO_ADMIN_USER_ID,
                tenant_id=tenant.id,
                customer_id=None,
                email=DEMO_ADMIN_EMAIL,
                display_name="Ananya Rao",
                role="admin",
            )
        )
    if owner_email:
        owner_customer = await _seed_owner_account(
            session,
            tenant=tenant,
            email=owner_email,
            display_name=owner_name,
        )
        if owner_customer is not None:
            customers_by_ref[OWNER_CUSTOMER_REF] = owner_customer
    await session.flush()

    for customer in customers_by_ref.values():
        profile_state = await session.scalar(
            select(CustomerProfileState).where(
                CustomerProfileState.tenant_id == tenant.id,
                CustomerProfileState.customer_id == customer.id,
            )
        )
        if profile_state is None:
            session.add(
                CustomerProfileState(
                    tenant_id=tenant.id,
                    customer_id=customer.id,
                    revision=1,
                )
            )

        agent_configuration = await session.scalar(
            select(CustomerAgentConfiguration).where(
                CustomerAgentConfiguration.tenant_id == tenant.id,
                CustomerAgentConfiguration.customer_id == customer.id,
            )
        )
        if agent_configuration is None:
            session.add(
                CustomerAgentConfiguration(
                    tenant_id=tenant.id,
                    customer_id=customer.id,
                    display_name=DEFAULT_AGENT_DISPLAY_NAME,
                    opening_message=DEFAULT_AGENT_OPENING_MESSAGE,
                    tone=DEFAULT_AGENT_TONE,
                    instructions=DEFAULT_AGENT_INSTRUCTIONS,
                    revision=1,
                )
            )
    await session.flush()

    await provision_default_tool_catalog(
        session,
        tenant_id=tenant.id,
        actor_user_id=DEMO_ADMIN_USER_ID,
        actor_display_name="Ananya Rao",
        customer_ids=tuple(
            customer.id for customer in customers_by_ref.values() if customer.is_active
        ),
    )

    reservation_policy = await session.get(ReservationPolicy, tenant.id)
    if reservation_policy is None:
        session.add(
            ReservationPolicy(
                tenant_id=tenant.id,
                service_provider_name="By the Brew",
                service_location="By the Brew",
                timezone="Asia/Kolkata",
                opening_time=time(9, 0),
                closing_time=time(22, 0),
                slot_interval_minutes=30,
                reservation_duration_minutes=90,
                max_party_size=8,
                advance_booking_days=90,
            )
        )

    for table_id, table_name, capacity in _DEMO_CAFE_TABLES:
        existing_table = await session.scalar(
            select(CafeTable).where(
                CafeTable.tenant_id == tenant.id,
                CafeTable.name == table_name,
            )
        )
        if existing_table is None and await session.get(CafeTable, table_id) is None:
            session.add(
                CafeTable(
                    id=table_id,
                    tenant_id=tenant.id,
                    name=table_name,
                    capacity=capacity,
                )
            )
    await session.flush()

    for values in _DEMO_ORDERS:
        customer = customers_by_ref.get(str(values["customer_ref"]))
        if customer is None:
            continue
        existing_order = await session.scalar(
            select(CustomerOrder).where(
                CustomerOrder.tenant_id == tenant.id,
                CustomerOrder.external_ref == str(values["external_ref"]),
            )
        )
        if existing_order is not None or await session.get(CustomerOrder, str(values["id"])):
            continue
        session.add(
            CustomerOrder(
                id=str(values["id"]),
                tenant_id=tenant.id,
                customer_id=customer.id,
                external_ref=str(values["external_ref"]),
                status=str(values["status"]),
                estimated_arrival=(
                    str(values["estimated_arrival"])
                    if values["estimated_arrival"] is not None
                    else None
                ),
                delivery_city=(
                    str(values["delivery_city"]) if values["delivery_city"] is not None else None
                ),
            )
        )
    await session.commit()
