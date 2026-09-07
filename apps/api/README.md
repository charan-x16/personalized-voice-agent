# Svara API

FastAPI service for authenticated, tenant-safe voice sessions and customer-data tools. The Next.js application uses it through a server-side BFF. The provider-neutral create/terminate lifecycle and local mock flow work end to end; real Sarvam session provisioning and audio transport do not. See the [Sarvam integration audit](../../docs/sarvam-integration-audit.md) for the verified public-support boundary.

## Local development

For existing Sarvam/Supabase credentials, read the [environment setup guide](../../docs/local-environment-setup.md) first. The demo instructions below are for local SQLite only; PostgreSQL startup never creates or seeds tables, and demo authentication is disabled for remote databases.

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

Open [http://localhost:3000](http://localhost:3000) and sign in with `rahul@example.com`. The dashboard, `GET /v1/me`, conversation list, and conversation detail are backed by FastAPI. The voice room creates a mock session and uses a development-only mock completion route so the resulting transcript appears in the archive. Its call visualization is simulated; no microphone stream is sent to Sarvam.

`API_BASE_URL` is consumed by the Next.js server and defaults to `http://127.0.0.1:8000`. Do not expose it as a `NEXT_PUBLIC_` variable. Production requires HTTPS unless the backend address is loopback.

### Browser/BFF authentication

The browser posts the seeded email to `POST /api/auth/demo-login`. The BFF exchanges it with `POST /v1/auth/demo-login`, stores the returned token in the HttpOnly `svara_session` cookie, and returns only `{ "ok": true }`. Server components and BFF routes read that cookie and add the bearer token only to server-to-server FastAPI requests. `POST /api/auth/logout` clears it.

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

   The response contains the public session metadata and `connection`. In mock mode, `connection.transport` is `mock`; no microphone/audio connection is opened.

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

Run `uv run pytest` to exercise the complete mock lifecycle. The test provider captures that backend-only reference and uses it for the provider callbacks below.

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
- Every customer/order query is scoped using the tenant and customer bound to the voice session. The API does not trust IDs supplied by the caller.
- Successful hooks/tools record minimized audit metadata rather than the opaque reference or order/customer PII. The on-start event records the non-PII agent-configuration revision used by the runtime, but not configuration text; an immutable full configuration snapshot remains a future compliance feature if exact historical reconstruction is required.
- Request bodies are rejected with `413` after `MAX_REQUEST_BODY_BYTES`, whether or not a trustworthy `Content-Length` was supplied.
- Transcripts and outcomes are deliberately bounded before persistence. Only top-level final-variable keys in `FINAL_VARIABLE_ALLOWLIST` are retained. Transcripts can still contain sensitive data, so production needs encryption, access policy, and retention/deletion controls.
- CORS is restricted to `FRONTEND_ORIGINS`.
- Successful authentication, session, profile, and conversation responses set `Cache-Control: no-store` so credentials, connection details, and customer data are not cached.

Demo authentication is for local development, not a password-based production login. With `APP_ENV=production`, startup rejects the included development secrets, non-PostgreSQL databases, non-Sarvam providers, incomplete Sarvam configuration, insecure frontend origins, and enabled demo authentication/seeding. Production should use the application's identity provider and mature token/session handling.

Application-level scoping is implemented. Rate limiting, PostgreSQL row-level security, and per-tenant encryption keys are not yet implemented.

## Provider-neutral lifecycle and Sarvam boundary

The backend provider interface owns `create_session` and idempotent `terminate_session`; its public connection result is discriminated as `mock` or `websocket`. The browser uses the same transport lifecycle for microphone ownership, events, mute, stop, reset, and page teardown. `VOICE_PROVIDER=mock` is the only operational provider today, and the WebSocket transport intentionally refuses to connect until Sarvam's real protocol is known.

Provider adapters must distinguish a definitive pre-acceptance rejection from a timeout or other post-send ambiguity. The latter quarantines the local session as `cancelling` and preserves its existing active-slot reservation until expiry/reconciliation, preventing both runtime data access and an immediate duplicate call. The local session ID is the stable idempotency key when a provider supports one. A browser-aborted request still cannot be conclusively reconciled without provider-side idempotency or lookup/cancellation by that key; production enablement therefore requires that Sarvam capability or a provider-backed reconciliation worker.

Sarvam advertises Voice Agent deployment through web, API, and SDK channels. However, its public Deploy with Code guide is still marked preview and omits the concrete session-bootstrap endpoint, WSS authentication/handshake, audio/event schemas, SDK calls, and initial-variable payload. Those details require the current account-provisioned contract; the [audit](../../docs/sarvam-integration-audit.md) separates confirmed features from that gap.

`VOICE_PROVIDER=sarvam` is intentionally fail-closed:

- Missing `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, or `SARVAM_AGENT_ID` produces a safe `503`.
- Even with those variables present, session creation and termination return safe typed failures because no undocumented Sarvam endpoint is guessed.
- No live WebSocket/session credential or browser-to-provider microphone/audio path exists yet.
- No Sarvam credential is returned to the browser.

To enable live sessions, implement `SarvamVoiceProvider.create_session` and `terminate_session` against the authenticated session/SDK contract provisioned by Sarvam, map its short-lived browser connection details into `VoiceProviderSession`, and replace the unsupported browser transport with the documented handshake/framing. Configure the Sarvam agent's hooks/tools to call this API with `X-Voice-Tool-Key`, the injected `conversation_ref`, and its stable `interaction_id`. Keep the reference inside the backend-to-provider channel.

The Next.js BFF accepts only future-dated `wss:` connection URLs without embedded user info or fragments. Set its server-only `VOICE_WEBSOCKET_HOSTS` variable to a comma-separated list of exact provider hostnames so unexpected WSS hosts are rejected before connection metadata reaches the browser.

The three Sarvam-facing route shapes in this service are Svara's integration contract. Their exact mapping into Sarvam's dashboard/tool configuration must be verified against the account's current official contract before deployment.

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

Only non-production SQLite startup may create missing tables for convenience. PostgreSQL startup always skips `create_all`; demo login and automatic seeding are also rejected for non-SQLite databases. PostgreSQL schemas require reviewed Alembic migrations, and real authentication/user provisioning is still required for login. After confirming the target is an appropriate fresh database:

```bash
cd apps/api
uv run alembic upgrade head
uv run alembic current
```

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
| `FRONTEND_ORIGINS` | Comma-separated CORS allowlist |
| `MAX_REQUEST_BODY_BYTES` | Global HTTP request-body cap, from 16,384 to 10,000,000 bytes |
| `FINAL_VARIABLE_ALLOWLIST` | Comma-separated top-level provider outcome keys permitted in storage |
| `SESSION_SECRET` | Signs development bearer tokens |
| `SESSION_TTL_MINUTES` | Token and voice-session TTL, from 1 to 60 minutes |
| `COMPLETION_GRACE_MINUTES` | Additional 1 to 1,440 minute window for a delayed first `on-end` callback |
| `SARVAM_TOOL_SECRET` | Authenticates provider hook/tool requests |
| `VOICE_PROVIDER` | `mock` or guarded `sarvam` adapter |
| `ENABLE_DEMO_AUTH` | Enables `/auth/demo-login` |
| `SEED_DEMO_DATA` | Seeds the local tenant/customer/order |
| `SARVAM_*` | Server-side placeholders needed by the future live adapter |

## Quality checks

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
uv run alembic heads
```
