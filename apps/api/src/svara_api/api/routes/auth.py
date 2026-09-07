from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings
from ...database import get_db
from ...dependencies import get_app_settings
from ...models import Tenant, User
from ...schemas import DemoLoginRequest, TokenResponse
from ...security import create_access_token, is_actor_account_eligible

router = APIRouter()


def _invalid_demo_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


@router.post("/demo-login", response_model=TokenResponse, summary="Create a demo session")
async def demo_login(
    payload: DemoLoginRequest,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> TokenResponse:
    """Issue a short-lived token for an active seeded user in demo environments."""

    if not settings.enable_demo_auth:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    normalized_email = payload.email.strip().casefold()
    if not normalized_email:
        raise _invalid_demo_login()

    rows = (
        await db.execute(
            select(User, Tenant)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(
                func.lower(User.email) == normalized_email,
                User.is_active.is_(True),
                Tenant.is_active.is_(True),
            )
            .limit(2)
        )
    ).all()
    # An email can exist in more than one tenant; never guess which identity was intended.
    if len(rows) != 1:
        raise _invalid_demo_login()

    user, tenant = rows[0]
    if not await is_actor_account_eligible(db, user=user, tenant=tenant):
        raise _invalid_demo_login()

    ttl_seconds = settings.session_ttl_minutes * 60
    token = create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        secret=settings.session_secret,
        ttl_seconds=ttl_seconds,
    )
    response.headers["Cache-Control"] = "no-store"
    return TokenResponse(access_token=token, expires_in=ttl_seconds)
