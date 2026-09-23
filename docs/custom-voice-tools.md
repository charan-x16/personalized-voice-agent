# Custom voice tools

Svara now owns a tenant-scoped tool registry and per-customer assignments. This lets one committed
Sarvam agent expose a reviewed set of business capabilities while Svara decides, at runtime, which
tools each customer may use.

## What is implemented

- Tenant administrators can register aliases for approved capabilities from **Agent tools**.
- Each customer profile has a **Customer tools** section with independent availability switches.
- Sarvam calls one Svara endpoint per registered alias:
  `POST /v1/sarvam/tools/execute/{tool_key}`.
- The gateway resolves tenant and customer scope only from the opaque `conversation_ref` created by
  Svara. It does not accept a tenant ID, customer ID, Clerk identity, database credential, or URL.
- Both the workspace tool and the customer assignment must be enabled.
- Tool creation, definition updates, and customer-assignment changes append a tenant-scoped audit
  event with the administrator snapshot, revision, time, and field names (never changed values).
- The **Agent tools** page shows the latest 20 audit events and refreshes them after a successful
  mutation.
- Existing order and reservation validation, preview-mode write restrictions, interaction binding,
  locking, version checks, idempotency, and audit behavior remain in force.

The approved capabilities are `customer_profile`, `order_status`, `reservation_availability`,
`reservation_lookup`, `reservation_create`, `reservation_reschedule`, and `reservation_cancel`.
Arbitrary customer-supplied HTTP destinations or executable code are intentionally not supported.
That avoids turning the voice runtime into an SSRF or secret-exfiltration surface.

## Sarvam HTTP tool configuration

The endpoint below is a Svara endpoint configured as a Sarvam HTTP tool; it is not a Sarvam REST
endpoint. FastAPI must be deployed on public HTTPS before Sarvam can call it.

For each enabled registry entry, create the matching HTTP tool in the committed Sarvam agent:

- Method: `POST`
- URL: `https://<public-api-host>/v1/sarvam/tools/execute/<tool_key>`
- Authentication: API key header `X-Voice-Tool-Key`
- Secret value: the same high-entropy value as backend `SARVAM_TOOL_SECRET`
- Header: `Content-Type: application/json`
- Timeout: no more than Sarvam's documented 30-second maximum

Use this envelope:

```json
{
  "conversation_ref": "{{conversation_ref}}",
  "interaction_id": "<call-context-interaction-id>",
  "arguments": {}
}
```

Map `conversation_ref` from the declared agent variable injected by Svara. Map `interaction_id`
from Sarvam's call context when available; it is optional until an interaction is bound. Put only
the capability-specific fields inside `arguments`. Do not let the model compose either identity
field.

Examples:

```json
{
  "conversation_ref": "{{conversation_ref}}",
  "interaction_id": "<call-context-interaction-id>",
  "arguments": { "order_reference": "ORD-8294" }
}
```

```json
{
  "conversation_ref": "{{conversation_ref}}",
  "interaction_id": "<call-context-interaction-id>",
  "arguments": {
    "reservation_date": "2026-09-25",
    "preferred_time": "19:00:00",
    "party_size": 4
  }
}
```

The exact reservation fields and safe sequencing rules are documented in
[Sarvam v2 reservation-tool setup](sarvam-v2-reservation-tools.md); place those fields inside the
new `arguments` object when using the registry endpoint.

Sarvam's official HTTP-tool documentation confirms webhook-style mid-conversation calls, API-key
authentication, tool lifecycle placement, call metadata inputs, and a configurable timeout up to
30 seconds: [HTTP Tools](https://docs.sarvam.ai/conversations/build/tools/https-tool).

## Runtime authorization flow

```text
Sarvam HTTP tool
  -> X-Voice-Tool-Key check
  -> hash conversation_ref and load active voice session
  -> derive tenant_id + customer_id from that session
  -> require enabled tenant tool definition
  -> require enabled assignment for that customer
  -> validate capability-specific arguments
  -> run allow-listed Svara business logic
  -> return minimized result to Sarvam
```

The database migration `20260923_0007` adds `voice_tool_definitions` and
`customer_voice_tools`; `20260923_0008` adds `voice_tool_admin_events`. On PostgreSQL all three
tables have RLS enabled and direct Supabase Data API privileges revoked from `anon` and
`authenticated`; the FastAPI backend remains the only data path. Audit writes commit in the same
transaction as their corresponding configuration change, so a conflict or rollback cannot leave a
false audit record.

For an existing workspace, provision the built-in catalog only for explicit active customers. The
command is idempotent and requires an active tenant administrator as the recorded actor:

```powershell
cd apps/api
uv run python scripts/provision_voice_tools.py `
  --tenant-slug acme `
  --customer-ref CUS-1042 `
  --actor-email ananya@example.com
```

Repeat `--customer-ref` to assign the catalog to additional customers. Existing definitions and
assignments are preserved; an existing key with a different capability fails closed.

## Current operational boundary

Creating or changing a Svara registry entry does not create or update the corresponding tool in
Sarvam. Sarvam configuration remains a deliberate deployment step in its dashboard (or its
documented MCP tooling). Keep the committed agent's declared tools synchronized with the registry.
If a Sarvam tool remains declared but its Svara assignment is disabled, calls fail closed with
`404` and no business action runs.

Sarvam configuration should follow its versioned lifecycle: update the draft, test it, commit that
version, and deploy the committed version. A real provider test still requires the API to be
reachable on public HTTPS and may incur Sarvam usage charges.
