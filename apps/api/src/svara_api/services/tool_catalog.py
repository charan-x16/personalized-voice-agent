from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Customer, CustomerVoiceTool, VoiceToolAdminEvent, VoiceToolDefinition


@dataclass(frozen=True, slots=True)
class VoiceToolTemplate:
    tool_key: str
    display_name: str
    description: str
    capability: str


DEFAULT_VOICE_TOOL_TEMPLATES = (
    VoiceToolTemplate(
        tool_key="get_customer_profile",
        display_name="Customer profile",
        description="Retrieve the customer's verified name, preferred language, and plan.",
        capability="customer_profile",
    ),
    VoiceToolTemplate(
        tool_key="get_order_status",
        display_name="Order status",
        description="Look up an order that belongs to the current customer.",
        capability="order_status",
    ),
    VoiceToolTemplate(
        tool_key="check_availability",
        display_name="Check table availability",
        description="Find available reservation times for the requested date and party size.",
        capability="reservation_availability",
    ),
    VoiceToolTemplate(
        tool_key="find_reservation",
        display_name="Find reservation",
        description="Retrieve an upcoming reservation for the current customer.",
        capability="reservation_lookup",
    ),
    VoiceToolTemplate(
        tool_key="create_reservation",
        display_name="Create reservation",
        description="Create a table reservation after the customer confirms an available time.",
        capability="reservation_create",
    ),
    VoiceToolTemplate(
        tool_key="reschedule_reservation",
        display_name="Reschedule reservation",
        description="Move a confirmed reservation to a newly available time.",
        capability="reservation_reschedule",
    ),
    VoiceToolTemplate(
        tool_key="cancel_reservation",
        display_name="Cancel reservation",
        description="Cancel a reservation after the customer confirms the action.",
        capability="reservation_cancel",
    ),
)


@dataclass(frozen=True, slots=True)
class ProvisionedToolCatalog:
    created_tools: int
    existing_tools: int
    created_assignments: int
    existing_assignments: int


async def provision_default_tool_catalog(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_user_id: str,
    actor_display_name: str,
    customer_ids: tuple[str, ...],
) -> ProvisionedToolCatalog:
    """Idempotently create built-ins and assign them to explicit in-tenant customers."""

    scoped_customer_ids = set(
        (
            await session.scalars(
                select(Customer.id).where(
                    Customer.tenant_id == tenant_id,
                    Customer.id.in_(customer_ids),
                    Customer.is_active.is_(True),
                )
            )
        ).all()
    )
    if scoped_customer_ids != set(customer_ids):
        raise ValueError("Every requested customer must be active and belong to the tenant")

    existing_definitions = {
        definition.tool_key: definition
        for definition in (
            await session.scalars(
                select(VoiceToolDefinition).where(
                    VoiceToolDefinition.tenant_id == tenant_id,
                    VoiceToolDefinition.tool_key.in_(
                        template.tool_key for template in DEFAULT_VOICE_TOOL_TEMPLATES
                    ),
                )
            )
        ).all()
    }
    definitions: list[VoiceToolDefinition] = []
    created_definitions: list[VoiceToolDefinition] = []
    created_tools = 0
    for template in DEFAULT_VOICE_TOOL_TEMPLATES:
        definition = existing_definitions.get(template.tool_key)
        if definition is None:
            definition = VoiceToolDefinition(
                tenant_id=tenant_id,
                tool_key=template.tool_key,
                display_name=template.display_name,
                description=template.description,
                capability=template.capability,
                is_enabled=True,
                revision=1,
                created_by_user_id=actor_user_id,
                updated_by_user_id=actor_user_id,
            )
            session.add(definition)
            created_definitions.append(definition)
            created_tools += 1
        elif definition.capability != template.capability:
            raise ValueError(f"Existing tool {template.tool_key!r} uses an incompatible capability")
        definitions.append(definition)
    await session.flush()
    for definition in created_definitions:
        session.add(
            VoiceToolAdminEvent(
                tenant_id=tenant_id,
                tool_id=definition.id,
                customer_id=None,
                actor_user_id=actor_user_id,
                actor_display_name=actor_display_name,
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

    existing_assignment_keys = set(
        (
            await session.execute(
                select(CustomerVoiceTool.customer_id, CustomerVoiceTool.tool_id).where(
                    CustomerVoiceTool.tenant_id == tenant_id,
                    CustomerVoiceTool.customer_id.in_(customer_ids),
                    CustomerVoiceTool.tool_id.in_(definition.id for definition in definitions),
                )
            )
        ).all()
    )
    created_assignments = 0
    for customer_id in customer_ids:
        for definition in definitions:
            if (customer_id, definition.id) in existing_assignment_keys:
                continue
            session.add(
                CustomerVoiceTool(
                    tenant_id=tenant_id,
                    customer_id=customer_id,
                    tool_id=definition.id,
                    is_enabled=True,
                    revision=1,
                    updated_by_user_id=actor_user_id,
                )
            )
            session.add(
                VoiceToolAdminEvent(
                    tenant_id=tenant_id,
                    tool_id=definition.id,
                    customer_id=customer_id,
                    actor_user_id=actor_user_id,
                    actor_display_name=actor_display_name,
                    action="customer_voice_tool.updated",
                    changed_fields=["is_enabled"],
                    revision=1,
                )
            )
            created_assignments += 1
    await session.flush()
    return ProvisionedToolCatalog(
        created_tools=created_tools,
        existing_tools=len(definitions) - created_tools,
        created_assignments=created_assignments,
        existing_assignments=len(customer_ids) * len(definitions) - created_assignments,
    )
