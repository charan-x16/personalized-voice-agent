# Svara API

FastAPI service for authenticated, tenant-safe voice sessions and customer-data tools. The Next.js application uses it through a server-side BFF. Both the local mock flow and live browser voice through the official Sarvam Agents SDK are implemented. See the [Sarvam integration audit](../../docs/sarvam-integration-audit.md) for the verified support boundary.

## Local development

For existing Sarvam, Clerk, and Supabase database credentials, read the [environment setup guide](../../docs/local-environment-setup.md) first. The demo instructions below are for local SQLite only; PostgreSQL startup never creates or seeds tables, and demo authentication is disabled for remote databases.

Requires Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
cd apps/api
cp .env.example .env
uv sync --dev
uv run uvicorn svara_api.main:app --reload
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. The default configuration creates `svara.db`, seeds the customer login `rahul@example.com`, the tenant-admin login `ananya@acme.example`, and a small customer directory, then serves interactive documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

## Run the wired web flow

Keep the API running, then create `.env.local` at the repository root with the server-only backend address:

```text
API_BASE_URL=http://127.0.0.1:8000
```

From the repository root:

```bash
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000) and sign in with a Clerk account whose verified primary email matches one active application user. With `VOICE_PROVIDER=mock`, the voice room uses the local simulated transport. With `VOICE_PROVIDER=sarvam` and the required values configured, the browser microphone is converted to 16 kHz PCM and relayed through FastAPI to the official Sarvam SDK; returned audio and transcripts drive the same custom UI.

`API_BASE_URL` is consumed by the Next.js server and defaults to `http://127.0.0.1:8000`. Do not expose it as a `NEXT_PUBLIC_` variable. Production requires HTTPS unless the backend address is loopback.

### Browser/BFF authentication

Clerk components own sign-in, sign-up, recovery, and sign-out. Server components and BFF routes use `await auth()` and forward the short-lived Clerk session token only in server-to-server FastAPI requests. FastAPI independently verifies the token, including its authorized party, and resolves the immutable Clerk user ID to one active tenant-bound application user. On first access only, a verified primary Clerk email can link to exactly one pre-provisioned active user; that immutable link is then stored in `users.clerk_user_id`.

`POST /v1/auth/demo-login` remains available only when explicitly enabled with local SQLite. It is intended for direct API development and automated tests, not browser sign-in.

The BFF also proxies session creation at `POST /api/voice/sessions`, cancellation at `POST /api/voice/sessions/{id}/cancel`, and, only outside production with the mock provider, completion at `POST /api/voice/sessions/{id}/mock-complete`. Mutation routes require same-origin JSON requests. The browser never receives the bearer token, `conversation_ref`, provider variables, or Sarvam credentials.

## Try the backend API directly

1. Create a demo bearer token:

   ```http
   POST /v1/auth/demo-login
   Content-Type: application/json

   {"email":"rahul@example.com"}
   ```

2. Create a session with `Authorization: Bearer <access_token>`:

   ```http
   POST /v1/voice/sessions
   Content-Type: application/json

   {"language":"English"}
   ```

   The response contains public session metadata and `connection`. In mock mode, `connection.transport` is `mock`. In Sarvam mode it is an expiring WebSocket URL for Svara's backend relay, not Sarvam's signed upstream URL.

   A customer can hold one active session. Starting another returns `409`. On a later start attempt, an expired session is marked expired and its database-enforced active slot is released; completed and failed sessions also release the slot.

   To stop the session instead of completing it, call:

   ```http
   POST /v1/voice/sessions/<session_id>/cancel
   Authorization: Bearer <access_token>
   Content-Type: application/json

   {}
   ```

   Cancellation is customer-scoped and idempotent. It retains the active slot while provider termination is uncertain; an ambiguous failure returns `503` with `Retry-After` so the same request can be retried safely. The equivalent browser route is same-origin `POST /api/voice/sessions/{id}/cancel`.

3. In development/test with `VOICE_PROVIDER=mock`, complete it using the returned `session_id`:

   ```http
   POST /v1/voice/sessions/<session_id>/mock-complete
   Authorization: Bearer <access_token>
   Content-Type: application/json

   {
     "resolution":"resolved",
     "summary":"Customer received an order update.",
     "transcript":[
       {"speaker":"customer","text":"Where is my order?"},
       {"speaker":"agent","text":"Your order is in transit."}
     ],
     "duration_seconds":42
   }
   ```

   The route is tenant-scoped and first-write-wins. It returns `404` outside development/test or when the configured provider is not `mock`.

The browser response deliberately excludes both `conversation_ref` and `agent_variables`. The API passes the opaque reference directly to the provider adapter when it creates the session. This keeps customer-data capabilities out of browser-controlled state.

Run `uv run pytest` to exercise the mock lifecycle plus the Sarvam provider token and browser-relay contract without making a paid external call.

For a read-only check of the configured database connection and core tables, run:

```bash
uv run python scripts/check_database.py
```

## Provider callback contract

These endpoints are server-to-server. `<conversation_ref>` represents the value injected by the backend into the provider session; it cannot be obtained from the browser-facing session response.

1. Start the provider interaction and bind its identifier:

   ```http
   POST /v1/sarvam/hooks/on-start
   X-Voice-Tool-Key: <SARVAM_TOOL_SECRET>
   Content-Type: application/json

   {"conversation_ref":"<conversation_ref>","interaction_id":"<interaction_id>"}
   ```

2. Call the read-only business tool with the same interaction identifier:

   ```http
   POST /v1/sarvam/tools/get-order-status
   X-Voice-Tool-Key: <SARVAM_TOOL_SECRET>
   Content-Type: application/json

   {
     "conversation_ref":"<conversation_ref>",
     "interaction_id":"<interaction_id>",
     "order_reference":"ORD-8294"
   }
   ```

   The cafe agent also has five database-backed routes for checking availability and creating,
   finding, rescheduling, or cancelling reservations. Their exact Sarvam v2 field mappings and
   required call sequence are documented in the
   [reservation-tool setup guide](../../docs/sarvam-v2-reservation-tools.md).

3. End and persist the same provider interaction:

   ```http
   POST /v1/sarvam/hooks/on-end
   X-Voice-Tool-Key: <SARVAM_TOOL_SECRET>
   Content-Type: application/json

   {
     "conversation_ref":"<conversation_ref>",
     "interaction_id":"<interaction_id>",
     "resolution":"resolved",
     "summary":"Customer received an order update.",
     "transcript":[],
     "final_variables":{},
     "duration_seconds":42
   }
   ```

All request bodies reject unknown fields. If `on-start` binds a non-null `interaction_id`, subsequent tool and completion requests must include exactly that identifier or receive `409`. If no identifier has been bound yet, the first later callback that supplies one binds it.

A completed or expired session cannot be used by `on-start` or the order tool. The first accepted `on-end` payload wins and cannot be silently rewritten by retries. Matching retries return the original outcome as idempotent. A first completion callback may arrive after runtime expiry but only within `COMPLETION_GRACE_MINUTES`; this grace does not extend access to runtime tools.

## Endpoints

All routes use the `/v1` prefix.

| Method and path | Authentication | Current behavior |
| --- | --- | --- |
| `GET /health` | None | Executes `SELECT 1`; returns `503` when the database is unavailable |
| `POST /auth/demo-login` | None | Issues a short-lived HMAC-SHA256 bearer token for one active seeded user |
| `GET /me` | Bearer token | Returns the current user's role-aware minimal workspace profile |
| `GET /customers` | Tenant-admin bearer token | Lists/searches tenant-scoped customers with conversation statistics |
| `GET /customers/{customer_id}` | Tenant-admin bearer token | Returns a scoped customer, order count, and five recent conversations |
| `PATCH /customers/{customer_id}` | Tenant-admin bearer token | Revision-checks and audits allowlisted profile/status changes; active calls block deactivation |
| `PATCH /customers/{customer_id}/agent-configuration` | Tenant-admin bearer token | Revision-checks and audits the customer's voice-agent configuration |
| `GET /conversations` | Bearer token | Lists completed outcomes in the current tenant/customer scope |
| `GET /conversations/{session_id}` | Bearer token | Returns one scoped transcript and outcome |
| `POST /voice/sessions` | Bearer token | Derives tenant/customer and creates a provider session without exposing provider variables |
| `POST /voice/sessions/{session_id}/cancel` | Bearer token | Idempotently terminates the actor's scoped provider session; retryable uncertainty keeps its active slot reserved |
| `POST /voice/sessions/{session_id}/mock-complete` | Bearer token | Completes a mock session in development/test only |
| `POST /sarvam/hooks/on-start` | `X-Voice-Tool-Key` | Binds the interaction and returns minimal customer context plus rendered runtime agent configuration |
| `POST /sarvam/tools/get-order-status` | `X-Voice-Tool-Key` | Verifies the bound interaction and reads one scoped order |
| `POST /sarvam/tools/check-availability` | `X-Voice-Tool-Key` | Returns up to five valid table slots near a requested date/time |
| `POST /sarvam/tools/create-reservation` | `X-Voice-Tool-Key` | Creates a scoped reservation with retry-safe idempotency |
| `POST /sarvam/tools/find-reservation` | `X-Voice-Tool-Key` | Finds a scoped reference or upcoming confirmed reservations |
| `POST /sarvam/tools/reschedule-reservation` | `X-Voice-Tool-Key` | Moves a reservation using a current version and available slot |
| `POST /sarvam/tools/cancel-reservation` | `X-Voice-Tool-Key` | Cancels a reservation using a current version and retry-safe idempotency |
| `POST /sarvam/hooks/on-end` | `X-Voice-Tool-Key` | Persists the first bounded outcome and handles matching retries idempotently |

Agent opening-message templates are limited to 500 characters and may contain at most one exact `{first_name}` replacement field. The rendered runtime greeting is also limited to 500 characters; malformed legacy data or unexpectedly large customer data falls back to a generic bounded greeting.

## Security model

- Session creation accepts an optional `language` only. Tenant and customer identifiers are resolved from the signed bearer token and revalidated against active database records.
- Authenticated roles fail closed to two valid shapes: a `customer` must have one active customer profile, while an `admin` must not be linked to a customer. Identity display names are trimmed and must contain 1–160 characters before an Actor can be created. Administrators cannot implicitly impersonate customers or start calls.
- Customer-management routes require the explicit `admin` role and scope every lookup, aggregate, and update by the authenticated tenant. Foreign-tenant identifiers return the same `404` as missing records.
- Customer and agent-configuration writes require the revision returned by the detail API. Stale writes return `409`; successful writes increment the corresponding revision and append an audit event containing field names only, never changed values. The administrator display name is snapshotted into each event so later account renames cannot rewrite historical attribution.
- Audit rows have database-enforced customer/tenant integrity. Actor and tenant are both derived from the same authenticated `Actor`; their relationship is application-enforced because legacy development databases do not have a composite tenant/user parent key. `actor_user_id` and `tenant_id` retain individual foreign keys.
- SQLAlchemy hides bound parameters in engine errors and logs, preventing failed profile or agent-configuration writes from echoing customer text into operational logs.
- A database unique constraint allows one active session per tenant/customer. Concurrent double-starts fail with `409`, and a new start reclaims an expired slot.
- The API creates a high-entropy conversation reference, passes it directly into provider variables, and stores only its SHA-256 hash. It is not returned in the browser response.
- Provider hooks/tools require a constant-time checked `X-Voice-Tool-Key`. Treat this key as a server-to-server secret, rotate it, and never expose it in frontend code.
- A provider `interaction_id`, once bound to a session, must match on later tool and completion calls. Callbacks from a different interaction are rejected after binding.
- Every customer, order, and reservation query is scoped using the tenant and customer bound to the voice session. Reservation tools do not accept caller-selected tenant/customer IDs.
- Reservation writes use deterministic table locking, database overlap protection on PostgreSQL, optimistic versions for edits, and stored request fingerprints for retry-safe mutations.
- Successful hooks/tools record minimized audit metadata rather than the opaque reference or order/customer PII. The on-start event records the non-PII agent-configuration revision used by the runtime, but not configuration text; an immutable full configuration snapshot remains a future compliance feature if exact historical reconstruction is required.
- Request bodies are rejected with `413` after `MAX_REQUEST_BODY_BYTES`, whether or not a trustworthy `Content-Length` was supplied.
- Transcripts and outcomes are deliberately bounded before persistence. Only top-level final-variable keys in `FINAL_VARIABLE_ALLOWLIST` are retained. Transcripts can still contain sensitive data, so production needs encryption, access policy, and retention/deletion controls.
- CORS is restricted to `FRONTEND_ORIGINS`.
- Successful authentication, session, profile, and conversation responses set `Cache-Control: no-store` so credentials, connection details, and customer data are not cached.

Demo authentication is for local development only. With `APP_ENV=production`, startup rejects the included development secrets, non-PostgreSQL databases, non-Sarvam providers, incomplete Sarvam or Clerk configuration, insecure frontend origins, and enabled demo authentication/seeding.

Application-level scoping is implemented. The reservation tables enable PostgreSQL row-level security and revoke Supabase Data API access from `anon` and `authenticated`; the remaining application tables still rely on the direct backend role and application scoping. Rate limiting and per-tenant encryption keys are not yet implemented.

## Provider-neutral lifecycle and Sarvam boundary

The backend provider interface owns `create_session` and idempotent `terminate_session`; its public connection result is discriminated as `mock` or `websocket`. The browser uses the same transport lifecycle for microphone ownership, events, mute, stop, reset, and page teardown. `VOICE_PROVIDER=mock` remains available for isolated development, while `VOICE_PROVIDER=sarvam` uses `sarvam-conv-ai-sdk==1.1.0` behind the API relay.

Provider adapters distinguish a definitive pre-acceptance rejection from a timeout or other post-send ambiguity. The latter quarantines the local session as `cancelling` and preserves its existing active-slot reservation until expiry/reconciliation, preventing both runtime data access and an immediate duplicate call. The local session ID is also the relay identifier.

`VOICE_PROVIDER=sarvam` fails closed when any of `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_AGENT_ID`, or `SARVAM_AGENT_VERSION` is absent. The provider issues an encrypted, expiring relay token; the browser never receives the Sarvam credential, the signed upstream WebSocket, or a plaintext `conversation_ref`.

The relay accepts raw signed 16-bit mono PCM at 16 kHz, uses the official SDK callbacks for audio/transcripts/events, and persists a bounded outcome when the connection finishes. Local loopback may use `ws:`. Remote URLs must use `wss:`, and the Next.js BFF applies `VOICE_WEBSOCKET_HOSTS` before returning the connection to the browser.

The active SDK registry is process-local. Run one FastAPI worker for the current deployment or add sticky routing plus shared coordination before horizontal scaling; otherwise a cancellation request handled by a different worker cannot directly stop the original in-memory SDK object.

The Sarvam-facing route shapes in this service are Svara's integration contract. Configure the five cafe routes as Sarvam API tools using the reviewed field mappings in the [reservation-tool setup guide](../../docs/sarvam-v2-reservation-tools.md); the dashboard configuration itself is not stored in this repository.

## Database

SQLite is the development default:

```text
DATABASE_URL=sqlite+aiosqlite:///./svara.db
```

For local PostgreSQL, start the service from the repository root:

```bash
docker compose up -d postgres
```

Then configure:

```text
DATABASE_URL=postgresql+asyncpg://svara:local-development-only@localhost:5432/svara
DATABASE_SSL_MODE=disable
ENABLE_DEMO_AUTH=false
SEED_DEMO_DATA=false
```

Compose publishes PostgreSQL on `127.0.0.1` only. The included password is a local-development credential and must not be reused elsewhere.

Only non-production SQLite startup may create missing tables for convenience. PostgreSQL startup always skips `create_all`; demo login and automatic seeding are also rejected for non-SQLite databases. PostgreSQL schemas require reviewed Alembic migrations, and an application user row must be provisioned before its matching Clerk account can access a workspace. After confirming the target is an appropriate fresh database:

```bash
cd apps/api
uv run alembic upgrade head
uv run alembic current
```

For an explicitly configured, non-production PostgreSQL database, inspect and
then apply the idempotent test dataset:

```bash
uv run python scripts/seed_test_data.py
uv run python scripts/seed_test_data.py --apply
```

The seed contains one Acme tenant, five customers, two application users, three
orders, per-customer agent configuration, a `By the Brew` reservation policy,
six cafe tables, and three completed conversations.
It never creates Clerk identities. In a Clerk development instance, sign up as
`ananya+clerk_test@acme.example` or `rahul+clerk_test@example.com` and use the
test verification code `424242`; non-production alias handling links those
identities to the corresponding seeded application users on first access.

Create a reviewed revision after changing SQLAlchemy metadata with `uv run alembic revision --autogenerate -m "description"`.

The included `20260903_0001` revision is a fresh-database baseline that creates the complete schema. Do not run it directly against an existing production schema created before Alembic: first reconcile that schema with the baseline, back it up, and then stamp the verified revision with `uv run alembic stamp 20260903_0001`. Stamping records history without applying DDL, so it is safe only after an operator has confirmed the schemas match.

The supplied API image contains `alembic.ini` and the migration scripts while still running as the unprivileged `svara` user. Run migrations as a separate deployment job from that same immutable image before rolling out API instances, for example:

```bash
docker run --rm --env-file .env svara-api alembic upgrade head
```

The supplied API Dockerfile runs Uvicorn as the unprivileged `svara` user.

## Configuration

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | `development`, `test`, or `production` guardrails |
| `DATABASE_URL` | SQLAlchemy async database URL |
| `DATABASE_SSL_MODE` | `verify-full` verifies PostgreSQL TLS certificates and hostnames; `disable` is for local non-TLS PostgreSQL and ignored by SQLite |
| `DATABASE_CA_CERT_FILE` | Optional PEM CA file added to the verified PostgreSQL trust store (required for Supabase's private database CA) |
| `DATABASE_POOLER_HOST` | Optional official Supabase session-pooler host used to route a direct project URL over IPv4 |
| `FRONTEND_ORIGINS` | Comma-separated CORS allowlist |
| `MAX_REQUEST_BODY_BYTES` | Global HTTP request-body cap, from 16,384 to 10,000,000 bytes |
| `FINAL_VARIABLE_ALLOWLIST` | Comma-separated top-level provider outcome keys permitted in storage |
| `SESSION_SECRET` | Signs development bearer tokens |
| `SESSION_TTL_MINUTES` | Token and voice-session TTL, from 1 to 60 minutes |
| `COMPLETION_GRACE_MINUTES` | Additional 1 to 1,440 minute window for a delayed first `on-end` callback |
| `SARVAM_TOOL_SECRET` | Authenticates provider hook/tool requests |
| `VOICE_PROVIDER` | `mock` or live `sarvam` SDK adapter |
| `ENABLE_DEMO_AUTH` | Enables `/auth/demo-login` |
| `SEED_DEMO_DATA` | Seeds the local tenant/customer/order |
| `CLERK_SECRET_KEY` | Server-only Clerk key used for token verification and first-access identity linking |
| `CLERK_JWT_KEY` | Optional public key for networkless Clerk JWT signature verification |
| `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_AGENT_ID` | Server-only Sarvam SDK credentials and identifiers |
| `SARVAM_AGENT_VERSION` | Committed Sarvam agent version pinned for runtime sessions |
| `VOICE_WEBSOCKET_PUBLIC_URL` | Public Svara relay URL; loopback `ws:` locally and `wss:` remotely |

## Quality checks

```bash
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run pytest
uv run alembic heads
```
