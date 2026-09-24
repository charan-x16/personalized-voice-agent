from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from svara_api.config import Settings
from svara_api.domains.voice import router as voice_routes
from svara_api.main import create_app

TEST_SESSION_SECRET = "test-session-secret-that-is-not-used-outside-tests"
TEST_TOOL_SECRET = "test-sarvam-tool-secret-that-is-not-used-outside-tests"
TEST_CONVERSATION_REF = "cvr_test-reference-0123456789-abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True, slots=True)
class ApiHarness:
    client: TestClient
    database_path: Path
    settings: Settings


def settings_for_database(database_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_name": "Svara API Tests",
        "app_env": "test",
        "api_prefix": "/v1",
        "database_url": f"sqlite+aiosqlite:///{database_path.as_posix()}",
        "frontend_origins": "http://testserver",
        "max_request_body_bytes": 16_384,
        "final_variable_allowlist": "order_reference,follow_up,resolution_code",
        "session_secret": TEST_SESSION_SECRET,
        "session_ttl_minutes": 15,
        "completion_grace_minutes": 60,
        "sarvam_tool_secret": TEST_TOOL_SECRET,
        "voice_provider": "mock",
        "enable_demo_auth": True,
        "seed_demo_data": True,
        "sarvam_api_key": None,
        "sarvam_org_id": None,
        "sarvam_workspace_id": None,
        "sarvam_agent_id": None,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def deterministic_conversation_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        voice_routes,
        "generate_conversation_ref",
        lambda: TEST_CONVERSATION_REF,
    )


@pytest.fixture
def api(tmp_path: Path) -> Iterator[ApiHarness]:
    database_path = tmp_path / "svara-test.sqlite3"
    settings = settings_for_database(database_path)
    app = create_app(settings)

    # The context manager is intentional: TestClient runs the application's
    # lifespan, which creates and seeds this test's private database.
    with TestClient(app) as client:
        yield ApiHarness(client=client, database_path=database_path, settings=settings)
