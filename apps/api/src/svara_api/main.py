from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api.router import api_router
from .config import Settings, get_settings
from .database import Database
from .middleware import RequestBodyLimitMiddleware
from .seed import seed_demo_data
from .services.voice_provider import build_voice_provider


def create_app(settings: Settings | None = None) -> FastAPI:
    application_settings = settings or get_settings()
    database = Database(application_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            # Only local SQLite may be initialized automatically. Remote schemas
            # are migration-managed, including when APP_ENV is development.
            if application_settings.app_env != "production" and (
                application_settings.database_url.startswith("sqlite+aiosqlite://")
            ):
                await database.create_schema()
            if application_settings.seed_demo_data:
                async with database.session_factory() as session:
                    await seed_demo_data(session)
            yield
        finally:
            await database.dispose()

    app = FastAPI(
        title=application_settings.app_name,
        version="0.1.0",
        description="Tenant-safe session and tool gateway for personalized voice agents.",
        lifespan=lifespan,
    )
    app.state.settings = application_settings
    app.state.database = database
    app.state.voice_provider = build_voice_provider(application_settings)

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_bytes=application_settings.max_request_body_bytes,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=application_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(api_router, prefix=application_settings.api_prefix)
    return app


app = create_app()
