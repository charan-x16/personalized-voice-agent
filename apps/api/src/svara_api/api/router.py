from fastapi import APIRouter

from ..domains.conversations import router as conversations
from ..domains.customers import router as customers
from ..domains.health import router as health
from ..domains.identity import auth, profile
from ..domains.reservations import router as reservation_tools
from ..domains.tools import router as tools
from ..domains.voice import router as voice
from ..domains.voice import stream as voice_stream
from ..integrations.clerk import router as webhooks
from ..integrations.sarvam import router as sarvam

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(auth.router, prefix="/auth", tags=["authentication"])
api_router.include_router(profile.router, tags=["customer profile"])
api_router.include_router(customers.router, prefix="/customers", tags=["customer management"])
api_router.include_router(tools.admin_router, prefix="/tools", tags=["voice tool management"])
api_router.include_router(
    conversations.router,
    prefix="/conversations",
    tags=["conversations"],
)
api_router.include_router(voice.router, prefix="/voice", tags=["voice sessions"])
api_router.include_router(voice_stream.router, prefix="/voice", tags=["voice sessions"])
api_router.include_router(sarvam.router, prefix="/sarvam", tags=["Sarvam tools and hooks"])
api_router.include_router(
    tools.runtime_router,
    prefix="/sarvam/tools",
    tags=["Sarvam custom tools"],
)
api_router.include_router(
    reservation_tools.router,
    prefix="/sarvam",
    tags=["Sarvam reservation tools"],
)
