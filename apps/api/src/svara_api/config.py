import re
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # ".env" is the template-copied file; ".env.local" is an optional, never-
        # templated overlay that wins, so re-running `cp .env.example .env` cannot
        # destroy configured secrets.
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Svara API"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/v1"
    database_url: str = Field(default="sqlite+aiosqlite:///./svara.db", repr=False)
    database_ssl_mode: Literal["disable", "verify-full"] = "disable"
    database_ca_cert_file: Path | None = None
    database_pooler_host: str | None = None
    frontend_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    max_request_body_bytes: int = Field(default=1_000_000, ge=16_384, le=10_000_000)
    final_variable_allowlist: str = "order_reference,follow_up,resolution_code"

    session_secret: str = Field(  # noqa: S106 - guarded development-only default
        default="development-session-secret-change-before-production",
        min_length=32,
        repr=False,
    )
    session_ttl_minutes: int = Field(default=15, ge=1, le=60)
    completion_grace_minutes: int = Field(default=60, ge=1, le=1_440)
    sarvam_tool_secret: str = Field(  # noqa: S106 - guarded development-only default
        default="development-tool-secret-change-before-production",
        min_length=32,
        repr=False,
    )
    voice_provider: Literal["mock", "sarvam"] = "mock"
    enable_demo_auth: bool = False
    seed_demo_data: bool = False
    seed_owner_email: str | None = None
    seed_owner_name: str = "Workspace Owner"

    sarvam_api_key: str | None = Field(default=None, repr=False)
    sarvam_org_id: str | None = None
    sarvam_workspace_id: str | None = None
    sarvam_agent_id: str | None = None
    sarvam_agent_version: int | None = Field(default=None, ge=1)
    voice_websocket_public_url: str = "ws://127.0.0.1:8000/v1/voice/stream"

    clerk_secret_key: str | None = Field(default=None, repr=False)
    clerk_jwt_key: str | None = Field(default=None, repr=False)

    @field_validator(
        "database_ca_cert_file",
        "database_pooler_host",
        "seed_owner_email",
        "sarvam_api_key",
        "sarvam_org_id",
        "sarvam_workspace_id",
        "sarvam_agent_id",
        "sarvam_agent_version",
        "clerk_secret_key",
        "clerk_jwt_key",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """Treat blank env vars (``KEY=``) as unset instead of invalid values."""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def allowed_final_variable_keys(self) -> frozenset[str]:
        return frozenset(
            key.strip() for key in self.final_variable_allowlist.split(",") if key.strip()
        )

    @property
    def resolved_database_url(self) -> str:
        if self.database_pooler_host is None:
            return self.database_url
        if not re.fullmatch(
            r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com",
            self.database_pooler_host,
        ):
            raise ValueError("DATABASE_POOLER_HOST must be an official Supabase AWS pooler host")

        url = make_url(self.database_url)
        direct_host = url.host or ""
        direct_match = re.fullmatch(r"db\.([a-z0-9]+)\.supabase\.co", direct_host)
        if direct_match is None or not url.username:
            raise ValueError(
                "DATABASE_POOLER_HOST requires a direct Supabase DATABASE_URL as its source"
            )

        project_ref = direct_match.group(1)
        username = url.username
        if not username.endswith(f".{project_ref}"):
            username = f"{username}.{project_ref}"
        return url.set(
            username=username,
            host=self.database_pooler_host,
            port=5432,
        ).render_as_string(hide_password=False)

    @model_validator(mode="after")
    def protect_production_defaults(self) -> "Settings":
        websocket_url = urlsplit(self.voice_websocket_public_url)
        websocket_is_loopback = websocket_url.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }
        if (
            websocket_url.scheme not in {"ws", "wss"}
            or websocket_url.hostname is None
            or websocket_url.username is not None
            or websocket_url.password is not None
            or websocket_url.query
            or websocket_url.fragment
            or (websocket_url.scheme == "ws" and not websocket_is_loopback)
        ):
            raise ValueError("VOICE_WEBSOCKET_PUBLIC_URL must be WSS, or WS on a loopback host")

        if self.app_env != "production":
            if not self.database_url.startswith("sqlite+aiosqlite://") and (
                self.enable_demo_auth or self.seed_demo_data
            ):
                raise ValueError(
                    "Demo authentication and seeding are only allowed with a local SQLite database"
                )
            return self

        unsafe_values = {
            "development-session-secret-change-before-production",
            "development-tool-secret-change-before-production",
        }
        if self.session_secret in unsafe_values or self.sarvam_tool_secret in unsafe_values:
            raise ValueError("Production secrets must be explicitly configured")
        if self.session_secret == self.sarvam_tool_secret:
            raise ValueError("Session and tool secrets must be different")
        if self.enable_demo_auth or self.seed_demo_data:
            raise ValueError("Demo authentication and seed data must be disabled in production")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("Production requires a PostgreSQL async database URL")
        if self.voice_provider != "sarvam":
            raise ValueError("Production requires an explicitly configured Sarvam provider")
        if not all(
            (
                self.sarvam_api_key,
                self.sarvam_org_id,
                self.sarvam_workspace_id,
                self.sarvam_agent_id,
                self.sarvam_agent_version,
            )
        ):
            raise ValueError("Production Sarvam configuration is incomplete")
        if not self.clerk_secret_key:
            raise ValueError("Production Clerk authentication configuration is incomplete")
        if websocket_url.scheme != "wss":
            raise ValueError("Production voice relay URL must use WSS")
        if any(
            origin == "*"
            or origin.startswith("http://")
            or "localhost" in origin
            or "127.0.0.1" in origin
            for origin in self.cors_origins
        ):
            raise ValueError("Production frontend origins must be explicit HTTPS origins")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
