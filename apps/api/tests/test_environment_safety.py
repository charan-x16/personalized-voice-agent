import ssl
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from svara_api.config import Settings
from svara_api.database import get_db
from svara_api.database import database_connect_args
from svara_api.main import create_app


@pytest.mark.parametrize("flag", ["enable_demo_auth", "seed_demo_data"])
def test_remote_development_database_rejects_demo_flags(flag: str) -> None:
    with pytest.raises(ValidationError, match="only allowed with a local SQLite database"):
        Settings(
            _env_file=None,
            app_env="development",
            database_url="postgresql+asyncpg://user:password@localhost/test",
            **{flag: True},
        )


def test_remote_startup_does_not_initialize_or_seed_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="postgresql+asyncpg://user:password@localhost/test",
        enable_demo_auth=False,
        seed_demo_data=False,
        voice_provider="mock",
    )
    app = create_app(settings)
    create_schema = AsyncMock()
    seed = AsyncMock()
    connect = AsyncMock(side_effect=AssertionError("Startup must not connect to the remote DB"))
    monkeypatch.setattr(app.state.database, "create_schema", create_schema)
    monkeypatch.setattr("svara_api.main.seed_demo_data", seed)
    monkeypatch.setattr(app.state.database.engine.sync_engine, "connect", connect)

    with TestClient(app) as client:
        assert client.get("/openapi.json").status_code == 200
        response = client.post("/v1/auth/demo-login", json={"email": "test@example.com"})
        assert response.status_code == 404

    create_schema.assert_not_called()
    seed.assert_not_called()
    connect.assert_not_called()


def test_postgres_verify_full_checks_certificate_and_hostname() -> None:
    args = database_connect_args("postgresql+asyncpg://localhost/test", "verify-full")
    context = args["ssl"]
    assert isinstance(context, ssl.SSLContext)
    assert context.check_hostname is True
    assert context.verify_mode == ssl.CERT_REQUIRED


def test_sqlite_does_not_receive_postgres_ssl_arguments() -> None:
    assert database_connect_args("sqlite+aiosqlite:///:memory:", "verify-full") == {
        "check_same_thread": False,
    }


def test_local_postgres_can_explicitly_disable_tls() -> None:
    assert database_connect_args("postgresql+asyncpg://localhost/test", "disable") == {"ssl": False}


def test_health_reports_unavailable_when_database_resolution_fails() -> None:
    settings = Settings(
        _env_file=None,
        app_env="development",
        database_url="postgresql+asyncpg://user:pass@localhost/test",
        enable_demo_auth=False,
        seed_demo_data=False,
        voice_provider="mock",
    )
    app = create_app(settings)

    async def failing_db() -> None:
        raise OSError("Name resolution failed")

    app.dependency_overrides[get_db] = failing_db

    with TestClient(app) as client:
        response = client.get("/v1/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable"}
