from __future__ import annotations

from fastapi.testclient import TestClient

from svara_api.seed import DEMO_ADMIN_EMAIL, DEMO_CUSTOMER_ID

from .conftest import TEST_CONVERSATION_REF, TEST_TOOL_SECRET, ApiHarness


def _login(client: TestClient, email: str) -> str:
    response = client.post("/v1/auth/demo-login", json={"email": email})
    assert response.status_code == 200
    return str(response.json()["access_token"])


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _tool_headers() -> dict[str, str]:
    return {"X-Voice-Tool-Key": TEST_TOOL_SECRET}


def test_admin_manages_safe_tool_catalog_and_customer_assignments(api: ApiHarness) -> None:
    admin_token = _login(api.client, DEMO_ADMIN_EMAIL)
    customer_token = _login(api.client, "rahul@example.com")

    forbidden = api.client.get("/v1/tools", headers=_auth(customer_token))
    assert forbidden.status_code == 403

    catalog = api.client.get("/v1/tools", headers=_auth(admin_token))
    assert catalog.status_code == 200
    assert catalog.json()["total"] == 7
    assert {item["capability"] for item in catalog.json()["items"]} == {
        "customer_profile",
        "order_status",
        "reservation_availability",
        "reservation_lookup",
        "reservation_create",
        "reservation_reschedule",
        "reservation_cancel",
    }

    created = api.client.post(
        "/v1/tools",
        headers=_auth(admin_token),
        json={
            "tool_key": "lookup_delivery",
            "display_name": "Delivery lookup",
            "description": "Retrieve an order that belongs to the current customer.",
            "capability": "order_status",
            "is_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    tool = created.json()
    assert tool["revision"] == 1
    assert tool["assigned_customer_count"] == 0

    updated_tool = api.client.patch(
        f"/v1/tools/{tool['id']}",
        headers=_auth(admin_token),
        json={"expected_revision": 1, "description": "A revised customer-scoped lookup."},
    )
    assert updated_tool.status_code == 200, updated_tool.text
    assert updated_tool.json()["revision"] == 2

    stale_tool = api.client.patch(
        f"/v1/tools/{tool['id']}",
        headers=_auth(admin_token),
        json={"expected_revision": 1, "is_enabled": False},
    )
    assert stale_tool.status_code == 409

    duplicate = api.client.post(
        "/v1/tools",
        headers=_auth(admin_token),
        json={
            "tool_key": "lookup_delivery",
            "display_name": "Duplicate",
            "description": "This key is already in use.",
            "capability": "order_status",
        },
    )
    assert duplicate.status_code == 409

    assigned = api.client.patch(
        f"/v1/tools/customer-assignments/{DEMO_CUSTOMER_ID}/{tool['id']}",
        headers=_auth(admin_token),
        json={"is_enabled": True, "expected_revision": None},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["revision"] == 1
    assert assigned.json()["is_enabled"] is True

    stale = api.client.patch(
        f"/v1/tools/customer-assignments/{DEMO_CUSTOMER_ID}/{tool['id']}",
        headers=_auth(admin_token),
        json={"is_enabled": False, "expected_revision": None},
    )
    assert stale.status_code == 409

    disabled = api.client.patch(
        f"/v1/tools/customer-assignments/{DEMO_CUSTOMER_ID}/{tool['id']}",
        headers=_auth(admin_token),
        json={"is_enabled": False, "expected_revision": 1},
    )
    assert disabled.status_code == 200
    assert disabled.json()["revision"] == 2
    assert disabled.json()["is_enabled"] is False

    audited_catalog = api.client.get("/v1/tools", headers=_auth(admin_token))
    assert audited_catalog.status_code == 200
    tool_events = [
        event for event in audited_catalog.json()["recent_events"] if event["tool_id"] == tool["id"]
    ]
    assert [event["action"] for event in tool_events] == [
        "customer_voice_tool.updated",
        "customer_voice_tool.updated",
        "voice_tool.updated",
        "voice_tool.created",
    ]
    assert [event["revision"] for event in tool_events] == [2, 1, 2, 1]
    assert all(event["actor_display_name"] == "Ananya Rao" for event in tool_events)
    assert tool_events[0]["customer_reference"] == "CUS-1042"
    assert tool_events[2]["customer_reference"] is None


def test_runtime_gateway_enforces_assignment_and_customer_scope(api: ApiHarness) -> None:
    customer_token = _login(api.client, "rahul@example.com")
    session = api.client.post("/v1/voice/sessions", headers=_auth(customer_token), json={})
    assert session.status_code == 201, session.text

    result = api.client.post(
        "/v1/sarvam/tools/execute/get_order_status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "arguments": {"order_reference": "ORD-8294"},
        },
    )
    assert result.status_code == 200, result.text
    assert result.json() == {
        "order_reference": "ORD-8294",
        "status": "In transit",
        "estimated_arrival": "Tomorrow between 10:00 AM and 12:00 PM",
        "delivery_city": "Bengaluru",
    }

    cross_customer = api.client.post(
        "/v1/sarvam/tools/execute/get_order_status",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "arguments": {"order_reference": "ORD-8461"},
        },
    )
    assert cross_customer.status_code == 404
    assert cross_customer.json()["detail"] == "Order not found"

    unavailable = api.client.post(
        "/v1/sarvam/tools/execute/not_assigned",
        headers=_tool_headers(),
        json={"conversation_ref": TEST_CONVERSATION_REF, "arguments": {}},
    )
    assert unavailable.status_code == 404

    unauthorized = api.client.post(
        "/v1/sarvam/tools/execute/get_customer_profile",
        json={"conversation_ref": TEST_CONVERSATION_REF, "arguments": {}},
    )
    assert unauthorized.status_code == 401


def test_runtime_gateway_rejects_unexpected_tool_arguments(api: ApiHarness) -> None:
    customer_token = _login(api.client, "rahul@example.com")
    session = api.client.post("/v1/voice/sessions", headers=_auth(customer_token), json={})
    assert session.status_code == 201

    response = api.client.post(
        "/v1/sarvam/tools/execute/get_customer_profile",
        headers=_tool_headers(),
        json={
            "conversation_ref": TEST_CONVERSATION_REF,
            "arguments": {"customer_id": "00000000-0000-4000-8000-000000000006"},
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "This tool does not accept arguments"
