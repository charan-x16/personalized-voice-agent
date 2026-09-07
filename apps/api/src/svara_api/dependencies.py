from fastapi import Request

from .config import Settings


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_voice_provider(request: Request):  # type: ignore[no-untyped-def]
    return request.app.state.voice_provider
