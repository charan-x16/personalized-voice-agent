from fastapi import APIRouter

from .routes import (
    auth,
    conversations,
    customers,
    health,
    profile,
    reservation_tools,
    sarvam,
    voice,
    voice_stream,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(profile.router, tags=["customer profile"])
api_router.include_router(customers.router, prefix="/customers", tags=["customer management"])
api_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["conversations"],
)
api_router.include_router(voice.router, prefix="/voice", tags=["voice sessions"])
api_router.include_router(voice_stream.router, prefix="/voice", tags=["voice sessions"])
api_router.include_router(sarvam.router, prefix="/sarvam", tags=["Sarvam tools and hooks"])
api_router.include_router(
    reservation_tools.router,
    prefix="/sarvam",
    tags=["Sarvam reservation tools"],
)
