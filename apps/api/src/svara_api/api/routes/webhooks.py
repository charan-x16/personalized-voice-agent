from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import Settings
from ...database import get_db
from ...dependencies import get_app_settings
from ...services.clerk_webhooks import (
    WebhookConfigurationError,
    WebhookPayloadError,
    WebhookVerificationError,
    process_clerk_webhook,
    verify_clerk_webhook,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/clerk")
async def clerk_webhook(
    request: Request,
    response: Response,
    settings: Annotated[Settings, Depends(get_app_settings)],
    db_session: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    """Verify and idempotently reconcile supported Clerk user events."""

    body = await request.body()
    try:
        event = await asyncio.to_thread(
            verify_clerk_webhook,
            body,
            request.headers,
            settings=settings,
        )
    except WebhookConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook verification is unavailable.",
        ) from exc
    except (WebhookVerificationError, WebhookPayloadError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook request.",
        ) from exc

    message_id = request.headers.get("svix-id") or request.headers.get("webhook-id") or ""
    try:
        result = await process_clerk_webhook(
            db_session,
            message_id=message_id,
            event=event,
            settings=settings,
        )
    except WebhookPayloadError as exc:
        await db_session.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook request.",
        ) from exc
    except SQLAlchemyError as exc:
        await db_session.rollback()
        logger.exception("Database failure while processing a Clerk webhook")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook processing is temporarily unavailable.",
        ) from exc

    response.headers["Cache-Control"] = "no-store"
    return {"received": True, "duplicate": result.duplicate, "status": result.status}
