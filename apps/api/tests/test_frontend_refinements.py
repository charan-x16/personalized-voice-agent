from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine

from svara_api.models import ConversationOutcome, VoiceSession, new_id
from svara_api.seed import DEMO_CUSTOMER_ID, DEMO_TENANT_ID

from .conftest import ApiHarness
from .test_api import _login


def test_archive_search_finds_older_records_and_paginates_filtered_results(api: ApiHarness) -> None:
    engine = create_engine(f"sqlite:///{api.database_path.as_posix()}")
    now = datetime.now(UTC)
    sessions = []
    outcomes = []
    for index in range(55):
        session_id = new_id()
        sessions.append(
            {
                "id": session_id,
                "tenant_id": DEMO_TENANT_ID,
                "customer_id": DEMO_CUSTOMER_ID,
                "provider": "mock",
                "conversation_ref_hash": new_id().replace("-", "").ljust(64, "0"),
                "status": "completed",
                "active_slot": None,
                "language": "English",
                "started_at": now + timedelta(seconds=index),
                "ended_at": now + timedelta(seconds=index + 1),
                "expires_at": now + timedelta(hours=1),
            }
        )
        outcomes.append(
            {
                "id": new_id(),
                "session_id": session_id,
                "summary": "Old invoice 100%_confirmed" if index == 0 else f"Plan question {index}",
                "resolution": "resolved" if index % 2 == 0 else "needs_follow_up",
                "transcript": [],
                "final_variables": {},
                "duration_seconds": 1,
            }
        )
    try:
        with engine.begin() as connection:
            connection.execute(VoiceSession.__table__.insert(), sessions)
            connection.execute(ConversationOutcome.__table__.insert(), outcomes)
    finally:
        engine.dispose()

    headers = {"Authorization": f"Bearer {_login(api.client)}"}
    first = api.client.get("/v1/conversations", headers=headers).json()
    assert first["total"] == 55
    assert len(first["items"]) == 50
    assert sessions[0]["id"] not in [item["id"] for item in first["items"]]
    search = api.client.get("/v1/conversations", params={"query": "INVOICE"}, headers=headers)
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["id"] == sessions[0]["id"]
    literal = api.client.get("/v1/conversations", params={"query": "%_"}, headers=headers)
    assert literal.json()["total"] == 1
    filtered = api.client.get(
        "/v1/conversations",
        params={"outcome": "resolved", "limit": 20, "offset": 20},
        headers=headers,
    ).json()
    assert filtered["total"] == 28
    assert len(filtered["items"]) == 8
    assert all(item["resolution"] == "resolved" for item in filtered["items"])
    assert api.client.get("/v1/conversations?outcome=invalid", headers=headers).status_code == 422
    assert (
        api.client.get(
            "/v1/conversations", params={"query": "x" * 201}, headers=headers
        ).status_code
        == 422
    )


def test_profile_exposes_configured_agent_identity_but_not_private_instructions(
    api: ApiHarness,
) -> None:
    admin = {"Authorization": f"Bearer {_login(api.client, 'ananya@acme.example')}"}
    update = api.client.patch(
        f"/v1/customers/{DEMO_CUSTOMER_ID}/agent-configuration",
        headers=admin,
        json={
            "expected_revision": 1,
            "display_name": "Mira",
            "opening_message": "Welcome {first_name}.",
            "instructions": "Private business instructions",
        },
    )
    assert update.status_code == 200
    customer = {"Authorization": f"Bearer {_login(api.client)}"}
    profile = api.client.get("/v1/me", headers=customer).json()
    assert profile["agent_name"] == "Mira"
    assert profile["agent_opening_message"] == "Welcome Rahul."
    assert profile["voice_mode"] == "mock"
    assert "instructions" not in str(profile)
