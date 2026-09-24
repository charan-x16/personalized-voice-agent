from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...agent_configuration import render_opening_message, resolve_agent_configuration
from ...config import Settings
from ...database import get_db
from ...dependencies import get_app_settings
from ...models import Customer, CustomerAgentConfiguration, Tenant, User
from ...schemas import MeResponse
from ...security import Actor, get_current_actor

router = APIRouter()


@router.get("/me", response_model=MeResponse)
async def get_me(
    response: Response,
    actor: Annotated[Actor, Depends(get_current_actor)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> MeResponse:
    """Return the authenticated user's minimum UI bootstrap profile."""

    user_tenant = (
        await db_session.execute(
            select(User, Tenant)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                User.id == actor.user_id,
                User.tenant_id == actor.tenant_id,
                User.customer_id == actor.customer_id,
                User.role == actor.role,
                User.is_active.is_(True),
                Tenant.id == actor.tenant_id,
                Tenant.is_active.is_(True),
            )
        )
    ).one_or_none()
    if user_tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found.",
        )

    user, tenant = user_tenant
    customer: Customer | None = None
    if actor.customer_id is not None:
        customer = await db_session.scalar(
            select(Customer).where(
                Customer.id == actor.customer_id,
                Customer.tenant_id == actor.tenant_id,
                Customer.is_active.is_(True),
            )
        )
        if customer is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Customer profile not found.",
            )

    full_name = (
        customer.full_name.strip() if customer is not None else user.display_name.strip()
    ) or "User"
    name_parts = full_name.split()
    first_name = name_parts[0]
    initials = (
        f"{name_parts[0][0]}{name_parts[-1][0]}" if len(name_parts) > 1 else first_name[:2]
    ).upper()

    agent = None
    if customer is not None:
        configuration = await db_session.scalar(
            select(CustomerAgentConfiguration).where(
                CustomerAgentConfiguration.tenant_id == actor.tenant_id,
                CustomerAgentConfiguration.customer_id == customer.id,
            )
        )
        agent = resolve_agent_configuration(configuration)

    response.headers["Cache-Control"] = "no-store"
    return MeResponse(
        user_id=user.id,
        customer_id=customer.id if customer is not None else None,
        role=actor.role,
        full_name=full_name,
        first_name=first_name,
        initials=initials,
        email=user.email,
        workspace_name=tenant.name,
        preferred_language=(customer.preferred_language if customer is not None else None),
        plan_name=customer.plan_name if customer is not None else None,
        agent_name=agent.display_name if agent is not None else None,
        agent_opening_message=(
            render_opening_message(agent.opening_message, first_name=first_name)
            if agent is not None
            else None
        ),
        voice_mode=settings.voice_provider,
    )
