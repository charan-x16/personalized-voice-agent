# Sarvam v2 reservation-tool setup

This guide maps the committed Sarvam agent version 2 to Svara's implemented cafe-reservation
API. The URLs below are Svara endpoints configured as Sarvam **API tools**; they are not Sarvam
REST endpoints.

## Before configuring Sarvam

1. Deploy FastAPI on a public HTTPS origin. Sarvam cannot call `localhost`.
2. Run `alembic upgrade head` against the target PostgreSQL database.
3. Provision one `reservation_policies` row and at least one active `cafe_tables` row for each
   tenant that can take reservations. The test seed creates a `By the Brew` policy and six tables.
4. Store the same high-entropy value in FastAPI's `SARVAM_TOOL_SECRET` and in Sarvam's workspace
   secret store. Never put it in the prompt, frontend, or a normal agent variable.
5. Keep `SARVAM_AGENT_VERSION=2`. Version 2 must remain committed in Sarvam.

For every API tool, use:

- Method: `POST`
- Header: `Content-Type: application/json`
- Authentication: API key in header `X-Voice-Tool-Key`
- Base URL: `https://<public-api-host>/v1/sarvam`
- Timeout: keep the endpoint within Sarvam's configured API-tool timeout (the official tool
  documentation currently allows up to 30 seconds).

If the API is behind an IP firewall, review Sarvam's current documented egress address before
allowlisting it. The official documentation currently lists `4.213.167.70`.

## Trusted common inputs

Every request needs `conversation_ref`. Map it from the declared Sarvam agent variable with that
name. Do not let the model compose it and do not expose it to the browser.

Map `interaction_id` from Sarvam's call context **Interaction ID** when the dashboard exposes that
field. The API accepts it as optional for transport compatibility, but after a non-null value binds
the voice session, a different value receives `409`.

Never send `tenant_id`, `customer_id`, database IDs, or a Clerk identity. FastAPI derives the tenant
and customer from the server-created voice session represented by `conversation_ref`.

## Tool definitions

### 1. `check_availability`

URL: `/tools/check-availability`

Request fields:

| Field | Type | Source |
| --- | --- | --- |
| `conversation_ref` | string | Agent variable `conversation_ref` |
| `interaction_id` | string or null | Call-context Interaction ID |
| `reservation_date` | `YYYY-MM-DD` string | Date resolved by the agent using `current_date` |
| `preferred_time` | local `HH:MM:SS` string | Customer's requested local wall-clock time |
| `party_size` | integer | Customer's requested party size |

Example body:

```json
{
  "conversation_ref": "{{conversation_ref}}",
  "interaction_id": "<call-context-interaction-id>",
  "reservation_date": "2026-09-12",
  "preferred_time": "19:00:00",
  "party_size": 4
}
```

The response has `available`, `service_location`, `timezone`, `party_size`, up to five `slots`,
and an optional `reason`. Each slot contains authoritative `start_at`, `end_at`, and
`display_time` values. `start_at` includes a timezone offset.

### 2. `create_reservation`

URL: `/tools/create-reservation`

Request fields:

| Field | Type | Source |
| --- | --- | --- |
| `conversation_ref` | string | Agent variable `conversation_ref` |
| `interaction_id` | string or null | Call-context Interaction ID |
| `start_at` | ISO 8601 date-time with offset | Exact `start_at` returned by `check_availability` |
| `party_size` | integer | Confirmed party size |
| `guest_name` | string or null | Optional confirmed name; defaults to the linked customer |
| `special_requests` | string or null | Optional customer request, maximum 500 characters |

Example body:

```json
{
  "conversation_ref": "{{conversation_ref}}",
  "interaction_id": "<call-context-interaction-id>",
  "start_at": "2026-09-12T19:00:00+05:30",
  "party_size": 4,
  "guest_name": "Rahul Mehta",
  "special_requests": "Window seat if possible"
}
```

The response contains `reservation` and `idempotent`. The reservation includes the public
`reservation_reference`, status, date-times, location, timezone, and `version`. Repeat calls with
the same meaningful inputs safely return the original reservation. A slot lost to another request
returns `409`.

### 3. `find_reservation`

URL: `/tools/find-reservation`

Request fields:

| Field | Type | Source |
| --- | --- | --- |
| `conversation_ref` | string | Agent variable `conversation_ref` |
| `interaction_id` | string or null | Call-context Interaction ID |
| `reservation_reference` | string or null | Customer-provided reference; omit to list upcoming confirmed reservations |

The result contains `found` and up to five customer-scoped `reservations`. Always use the returned
`version` for a later reschedule or cancellation.

### 4. `reschedule_reservation`

URL: `/tools/reschedule-reservation`

Request fields:

| Field | Type | Source |
| --- | --- | --- |
| `conversation_ref` | string | Agent variable `conversation_ref` |
| `interaction_id` | string or null | Call-context Interaction ID |
| `reservation_reference` | string | Exact reference returned by `find_reservation` |
| `new_start_at` | ISO 8601 date-time with offset | Exact slot returned by a fresh `check_availability` call |
| `expected_version` | integer | Version returned by `find_reservation` |

The request is retry-safe. A stale version or a reservation changed by another caller returns
`409`, so the agent must retrieve it again rather than retrying with invented state.

### 5. `cancel_reservation`

URL: `/tools/cancel-reservation`

Request fields:

| Field | Type | Source |
| --- | --- | --- |
| `conversation_ref` | string | Agent variable `conversation_ref` |
| `interaction_id` | string or null | Call-context Interaction ID |
| `reservation_reference` | string | Exact reference returned by `find_reservation` |
| `expected_version` | integer | Version returned by `find_reservation` |

Cancellation is retry-safe. It returns the updated reservation with status `cancelled`; the agent
must only tell the customer that cancellation succeeded after a successful tool response.

## Required agent behavior

- Booking: collect date, time, and party size; call `check_availability`; read only returned slots;
  confirm one exact slot; then call `create_reservation`.
- Rescheduling: call `find_reservation`; call `check_availability` for the requested new time;
  confirm the exact slot; then call `reschedule_reservation` with the current version.
- Cancellation: call `find_reservation`; confirm the target with the customer; then call
  `cancel_reservation` with the current version.
- Never claim booked, moved, or cancelled unless the corresponding mutation tool succeeded.
- Never invent a slot when availability returns an empty list or a tool errors.
- Keep internal IDs, credentials, tool names, and raw error details out of customer-facing speech.

## Current MVP boundaries

The database implementation supports one location and one daily business-hours window per tenant,
one reservation duration, fixed slot intervals, tables up to the configured maximum party size,
and free cancellation. It prevents overlapping confirmed reservations on PostgreSQL and uses
version checks plus idempotency records for writes.

Holiday closures, per-day schedules, combined tables, deposits/payments, walk-in queues, staff
assignment, an operations UI for policies/tables, and multi-location selection are not implemented.
The Sarvam dashboard tool definitions still require manual configuration because they belong to
the Sarvam workspace, not this repository.

Official references: [API tools](https://docs.sarvam.ai/conversations/build/tools/https-tool),
[tools overview](https://docs.sarvam.ai/conversations/build/tools), and
[agent versioning](https://docs.sarvam.ai/conversations/build/agent/versioning).
