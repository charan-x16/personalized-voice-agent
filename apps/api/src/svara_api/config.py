from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "Svara API"
    app_env: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/v1"
    database_url: str = Field(default="sqlite+aiosqlite:///./svara.db", repr=False)
    database_ssl_mode: Literal["disable", "verify-full"] = "disable"
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

    sarvam_api_key: str | None = Field(default=None, repr=False)
    sarvam_org_id: str | None = None
    sarvam_workspace_id: str | None = None
    sarvam_agent_id: str | None = None

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins.split(",") if origin.strip()]

    @property
    def allowed_final_variable_keys(self) -> frozenset[str]:
        return frozenset(
            key.strip() for key in self.final_variable_allowlist.split(",") if key.strip()
        )

    @model_validator(mode="after")
    def protect_production_defaults(self) -> "Settings":
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
            )
        ):
            raise ValueError("Production Sarvam configuration is incomplete")
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
