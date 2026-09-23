# Production hardening: customer revisions, agent configuration, and audit events

This guide covers the application controls needed to manage personalized agents safely across
multiple customers. The live browser transport now uses Sarvam's official Python Agents SDK behind
an authenticated Svara WebSocket relay. The remaining release controls are described in the
[Sarvam integration audit](sarvam-integration-audit.md).

## What this phase adds

- Versioned database migrations for production deployments.
- Optimistic concurrency for customer-profile and agent-configuration edits.
- A provider-neutral configuration record per customer.
- An application append-only admin audit trail containing field names, not old/new values.
- A rendered agent configuration in the authenticated voice `on-start` response.

These controls keep three concerns separate:

1. **Identity and scope** come from the authenticated application session. The browser never
   chooses a tenant or customer identifier.
2. **Business data** remains in the application database and is returned only through narrowly
   scoped backend tools such as `get-order-status`.
3. **Agent behavior** is configured through a small allowlist: display name, greeting, tone, and
   custom instructions. Administrators must not place credentials, database filters, provider
   connection details, or customer records in these text fields.

## Customer profile revisions

`GET /v1/customers/{customer_id}` returns `profile_revision`. Every profile update must echo that
value as `expected_revision`:

```json
{
  "expected_revision": 3,
  "preferred_language": "Hindi",
  "plan_name": "Growth"
}
```

The API locks the tenant-scoped customer record, compares the revision, applies only allowlisted
fields, increments the revision, and appends an audit event in one transaction. A stale update
returns `409 Conflict` without changing the profile. Clients should reload the latest record,
show the administrator what changed, and let them reapply their edit deliberately.

This is optimistic concurrency rather than field merging. Two administrators may edit different
fields, but the second save still has to reload after the first save; this prevents silent
last-write-wins behavior.

## Per-customer agent configuration

The customer detail response contains:

```json
{
  "agent_configuration": {
    "display_name": "Asha",
    "opening_message": "Hello {first_name}, how can I help you today?",
    "tone": "professional",
    "instructions": "Help with plan and order questions. Confirm before promising a change.",
    "revision": 1,
    "updated_at": null
  }
}
```

Administrators update it through:

```http
PATCH /v1/customers/{customer_id}/agent-configuration
Authorization: Bearer <admin-token>
Content-Type: application/json
```

```json
{
  "expected_revision": 1,
  "tone": "warm",
  "opening_message": "Namaste {first_name}. How may I help today?"
}
```

The same revision and audit rules apply. Supported tones are `warm`, `professional`, and
`concise`. The greeting accepts at most one `{first_name}` placeholder. Custom instructions
are administrator-authored, bounded text; they must describe behavior, never carry customer
records or secrets. The application does not perform reliable secret/DLP classification, so treat
both text fields as untrusted outbound provider data and govern who may edit them.

Using one provider agent with this dynamic configuration is the recommended default. It avoids
creating and synchronizing a Sarvam agent for every customer while our application remains the
source of truth. Separate Sarvam agents or workspaces should be reserved for customers that need
genuinely different provider-side policies, staff access, compliance boundaries, or billing
attribution.

## Runtime voice context

The authenticated provider callback remains:

```http
POST /v1/sarvam/hooks/on-start
X-Voice-Tool-Key: <dedicated-tool-secret>
```

After resolving the opaque `conversation_ref` to a fixed tenant and customer, the API returns
minimal customer context plus a runtime agent object. The greeting is rendered on the server, so
the provider receives `Hello Rahul, ...`, not a template it must evaluate. The provider can then
use the configured tone and instructions for that session. The minimized `on-start` tool audit
records the configuration revision used, but not its text values.

The response is not a general database snapshot. When the conversation needs current business
data, the agent calls an allowlisted tool. The backend ignores any model-supplied tenant/customer
scope, derives scope from the conversation reference, queries the database, and returns only the
required result.

```text
Customer voice
  -> provider speech recognition / agent runtime
  -> authenticated on-start receives bounded behavior + customer context
  -> allowlisted tool call with a business input such as order_reference
  -> API resolves conversation_ref to tenant/customer
  -> tenant-scoped database query
  -> minimal result to agent
  -> provider response generation / text to speech
  -> customer
```

## Audit events

Successful changes append one of these events:

- `customer.profile_updated`
- `customer.agent_configuration_updated`

An event records the tenant-scoped customer, immutable actor identifier, actor display-name
snapshot, revision, timestamp, and the names of fields that changed. It deliberately does not
duplicate customer profile values or custom instructions. No update or delete endpoint is exposed
for audit events.

"Append-only" here describes the application contract. A production database role should also be
denied direct `UPDATE` and `DELETE` access to the audit table, and audit exports should be retained
according to the organization's compliance policy. The current implementation is not a
cryptographically tamper-evident ledger.

## Migrations and deployment

Development/test startup may call SQLAlchemy `create_all` so a fresh local SQLite database remains
easy to use. Production startup never creates or alters tables. Run migrations as a separate,
single deployment step before starting the new application version:

```bash
cd apps/api
uv sync --dev
uv run alembic upgrade head
uv run uvicorn svara_api.main:app
```

Back up the database first and test both upgrade and application rollback procedures against a
staging copy. The initial Alembic revision is a baseline for a fresh production database. A
database created before migrations were introduced must be reconciled explicitly (recreate a
disposable development database, or validate its exact schema before stamping the baseline); do
not blindly stamp an unknown shared database.

## Clerk lifecycle reliability

Configure a Clerk webhook endpoint at `https://<api-host>/v1/webhooks/clerk`, subscribe only to `user.created`, `user.updated`, and `user.deleted`, and store its `whsec_...` value in `CLERK_WEBHOOK_SIGNING_SECRET`. The handler verifies the untouched request body with Svix, records the message ID in the same transaction as the reconciliation, returns `2xx` for duplicates, and does not retain the full identity payload.

Run the durable invitation processor independently from the API:

```bash
uv run python scripts/process_invitation_outbox.py --watch
```

The outbox is the retry source of truth. Alert on old `pending` rows, recovered stale `processing` rows, and any `dead_letter` row. Do not run a custom retry process that bypasses the claim and access-generation checks.

## Controls still required before production

- Design an explicit multi-workspace membership selector before allowing one email in multiple
  tenants; onboarding currently rejects global application-email duplicates so first-access
  linking stays unambiguous. Define the production recovery, MFA, and deprovisioning lifecycle.
- Apply least-privilege database roles, database-level tenant controls where appropriate,
  encrypted backups, retention/deletion policy, and secret rotation.
- Add rate limits, abuse controls, structured monitoring, and alerting for authentication, tool,
  provider, and database failures.
- Add shared active-session coordination and sticky routing (or a dedicated relay service) before
  running more than one FastAPI worker.
- Load-test the 16 kHz PCM relay, connection lifecycle, provider errors, and browser interruption
  behavior against a non-production committed Sarvam agent.
- Implement the domain-specific availability and reservation APIs expected by the current cafe
  prompt before exposing those actions to customers.
- Decide whether audit records require an external immutable archive or tamper-evident signing for
  the applicable compliance regime.
- If exact conversation replay or regulated evidence is required, persist immutable, retained
  agent-configuration and customer-context snapshots on the first `on-start` call and reuse them
  for retries. A revision number alone proves which edit generation was returned but cannot
  reconstruct overwritten text or make repeated `on-start` responses deterministic after an
  administrator edits live data.
