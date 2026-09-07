# Svara

Svara is a personalized, multilingual voice-agent platform prototype. The repository contains polished Next.js customer and tenant-admin interfaces plus a FastAPI backend vertical slice for tenant-scoped customer management, per-customer agent configuration, voice sessions, customer data tools, and conversation persistence.

The web app and backend are wired end to end for the local mock flow. Sarvam advertises API/SDK deployment for Voice Agents, but its public Deploy with Code guide remains a preview and does not publish a concrete session-bootstrap or WebSocket handshake contract. The Sarvam adapter therefore returns `503` until that authenticated, account-provisioned contract is available. See the [Sarvam integration audit](docs/sarvam-integration-audit.md) for the verified support boundary and deployment checklist.

## Current status

### Web application

- Editorial product landing page
- HttpOnly-cookie demo sign-in through a same-origin Next.js backend-for-frontend (BFF)
- Role-aware customer and tenant-administrator workspaces
- Searchable, filterable customer directory with revision-safe profile and voice-agent editors
- Per-customer agent name, greeting preview, tone, and bounded custom instructions
- Recent admin-change timeline that records changed field names without duplicating values
- Live profile and dashboard data from `GET /v1/me` and `GET /v1/conversations`
- Searchable conversation archive and transcript detail view backed by the API
- Voice-room session creation, provider-neutral transport lifecycle, authenticated cancellation, and development-only mock completion
- Responsive layouts, keyboard navigation, reduced-motion support, and accessible status announcements
- Simulated call experience; captured microphone audio is not sent to a provider yet

### API

- Short-lived demo bearer authentication for the Next.js BFF
- Tenant-administrator customer list, detail, and allowlisted update endpoints
- Optimistic concurrency for profile and agent-configuration changes
- Application append-only admin audit events with actor, revision, time, and changed field names
- Tenant-scoped profile and conversation read endpoints
- Authenticated, tenant-safe voice-session bootstrap and idempotent cancellation
- One active voice session per customer, enforced by the database
- Mock provider implementation for local development
- Backend-only conversation references stored only as hashes
- Authenticated `on_start`, read-only order-status, and `on_end` endpoints for the voice provider
- Provider-interaction binding, first-write-wins completion, and a bounded delayed-callback grace window
- Tenant/customer-scoped database queries, bounded outcome persistence, and minimized tool audit records
- Database-backed health checks, global request-body limits, and allowlisted final variables
- Alembic-managed production schema with a fresh-database baseline migration
- SQLite for local development and PostgreSQL support through SQLAlchemy

## Architecture

```text
Customer browser
        |
        | same-origin requests + HttpOnly svara_session cookie
        v
Next.js BFF / server components
        |
        | Authorization: Bearer ... (server-side only)
        v
Svara API (FastAPI) -----> voice-provider adapter -----> Sarvam Voice Agent*
        ^                                                   |
        | X-Voice-Tool-Key + opaque conversation reference |
        +---------------- hooks and tools ------------------+
        |
        +---- tenant/customer-scoped queries ----> PostgreSQL

* Mock provider today. Provider-neutral create/terminate and browser transport boundaries are implemented; real Sarvam provisioning and audio framing remain fail-closed.
```

The browser never receives the bearer token or selects a `tenant_id` or `customer_id`. The Next.js BFF stores the demo token in an HttpOnly cookie and forwards it to FastAPI only from the server. The API derives tenant and customer scope from that token and passes an opaque, short-lived conversation reference directly to the provider adapter. Neither that reference nor provider agent variables are included in browser responses.

## Repository layout

```text
src/                 Next.js frontend
apps/api/            FastAPI backend
compose.yaml         Local PostgreSQL service
```

## Run locally

Prerequisites: Node.js 22.15 or newer, pnpm 11, Python 3.11 or newer, and `uv`.
Docker is optional for running the local PostgreSQL service.

### 1. Start the API

From the repository root:

```bash
cd apps/api
cp .env.example .env
uv sync --dev
uv run uvicorn svara_api.main:app --reload
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. The API is available at [http://localhost:8000](http://localhost:8000), with OpenAPI documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

The default configuration creates `apps/api/svara.db` and idempotently seeds:

- Customer account: `rahul@example.com`
- Workspace administrator: `ananya@acme.example`
- Five example customers and three example orders, including `ORD-8294`

### 2. Start the frontend

From the repository root, set the server-only backend address in `.env.local`:

```text
API_BASE_URL=http://127.0.0.1:8000
```

Then run:

```bash
pnpm install
pnpm dev
```

Open [http://localhost:3000](http://localhost:3000). Choose Rahul to test the customer voice workspace or Ananya to test tenant customer management. `API_BASE_URL` is read only by the Next.js server; do not rename it to a `NEXT_PUBLIC_` variable.

To use PostgreSQL instead, run `docker compose up -d postgres` from the repository root and set:

```text
DATABASE_URL=postgresql+asyncpg://svara:local-development-only@localhost:5432/svara
DATABASE_SSL_MODE=disable
ENABLE_DEMO_AUTH=false
SEED_DEMO_DATA=false
```

The Compose port is bound to `127.0.0.1` only, and its included password is strictly for local development.

PostgreSQL requires explicitly reviewed migrations and real authentication/user provisioning; it does not support the SQLite demo login. For Supabase credentials, TLS, and the two environment files, see the [local environment setup guide](docs/local-environment-setup.md).

## Implemented API endpoints

All routes use the `/v1` prefix.

| Endpoint | Caller | Purpose |
| --- | --- | --- |
| `GET /health` | Infrastructure | Verifies the API can execute a database query |
| `POST /auth/demo-login` | Next.js BFF | Issues a short-lived token for the seeded demo user |
| `GET /me` | Authenticated Next.js server | Returns the current user's minimal profile |
| `GET /customers` | Tenant administrator | Searches and paginates customers in the authenticated tenant |
| `GET /customers/{customer_id}` | Tenant administrator | Returns a scoped profile, agent configuration, recent audit events, and activity summary |
| `PATCH /customers/{customer_id}` | Tenant administrator | Revision-safely updates only name, preferred language, plan, or active state |
| `PATCH /customers/{customer_id}/agent-configuration` | Tenant administrator | Revision-safely updates the customer's provider-neutral agent behavior |
| `GET /conversations` | Authenticated Next.js server | Lists completed conversations in the current customer scope |
| `GET /conversations/{session_id}` | Authenticated Next.js server | Returns one scoped transcript and outcome |
| `POST /voice/sessions` | Authenticated Next.js BFF | Creates a customer-scoped mock/provider session |
| `POST /voice/sessions/{session_id}/cancel` | Authenticated Next.js BFF | Idempotently stops a scoped provider session and releases its active slot after confirmed termination |
| `POST /voice/sessions/{session_id}/mock-complete` | Authenticated Next.js BFF | Completes a mock call in development/test only |
| `POST /sarvam/hooks/on-start` | Voice provider | Returns minimal customer context and rendered runtime agent configuration |
| `POST /sarvam/tools/get-order-status` | Voice provider | Reads one order within the bound customer scope |
| `POST /sarvam/hooks/on-end` | Voice provider | Stores the first bounded outcome and safely handles retries |

The browser calls same-origin BFF routes for login/logout, customer reads and updates, voice-session creation/cancellation, and development-only mock completion. Authenticated server-rendered pages read the same HttpOnly cookie before loading profile, customer, or conversation data. Direct FastAPI client calls still require `Authorization: Bearer <token>`.

Administrators cannot choose a tenant, impersonate a customer, use customer voice routes, or delete history. A cross-tenant customer identifier is returned as not found. Profile and agent edits require the revision returned by the detail endpoint; a stale update receives `409` instead of silently overwriting newer work. See the [customer-management security boundary](docs/customer-management.md) and [production-hardening guide](docs/production-hardening.md) for the request flow, migration procedure, and remaining release gates.

Sarvam-facing hooks and tools require `X-Voice-Tool-Key` and the backend-only `conversation_ref` injected into the provider session. When `on-start` supplies a provider `interaction_id`, later tool and completion calls must supply that same value.

Only one active voice session can be reserved for a customer. A second start returns `409`; a later start can reclaim a slot whose session has expired. Successful authentication and session-bootstrap responses include `Cache-Control: no-store`.

## Deployment defaults

- The API container runs as the unprivileged `svara` user.
- Browser credentials are held in an HttpOnly, `SameSite=Lax` cookie; mutation BFF routes reject cross-origin requests.
- `VOICE_WEBSOCKET_HOSTS` is a server-only, comma-separated exact-host allowlist applied by the BFF before any provider WSS URL can reach the browser. Set it for live deployments.
- Request bodies are capped by `MAX_REQUEST_BODY_BYTES` before route handling.
- Only top-level outcome keys listed in `FINAL_VARIABLE_ALLOWLIST` are retained from provider final variables.
- Only non-production SQLite startup may create a development schema. PostgreSQL startup never creates or seeds tables; its schema must be explicitly migrated before use.
- Application-level tenant scoping is implemented. Rate limiting and database row-level security are not implemented yet.
- Administrative updates are allowlisted, revision-checked, and recorded in an application append-only audit trail. Production database roles must separately deny direct mutation of that table where required.
- Transcripts are bounded, but production still requires an explicit retention/deletion policy, encryption, and access controls.

See [apps/api/README.md](apps/api/README.md) for request examples and lifecycle semantics, and the [Sarvam integration audit](docs/sarvam-integration-audit.md) for confirmed capabilities, preview gaps, pricing, and dashboard configuration.

## Quality checks

Frontend:

```bash
pnpm typecheck
pnpm lint
pnpm build
```

Backend:

```bash
cd apps/api
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest
```

## Production gaps

- Replace demo login and the custom development token issuer with the application's production identity provider.
- Map production tenant roles from immutable identity-provider claims.
- Implement `SarvamVoiceProvider.create_session` and `terminate_session` only against Sarvam's authenticated contract provisioned for the account. Do not expose the Sarvam API key to the browser.
- Replace the intentionally unsupported live browser transport with Sarvam's documented handshake, audio framing, event parsing, and close behavior once the provisioned contract is available.
- Add a durable reconciliation worker for provider bootstrap/termination uncertainty. It must use Sarvam's provisioned idempotency or session-lookup contract so an abandoned browser request cannot leave an untracked remote session running.
- Configure the Sarvam agent to send the shared tool credential and opaque conversation reference to the backend hooks/tools.
- Preserve the backend-to-provider reference boundary: neither the conversation reference nor provider agent variables should be returned by browser-facing endpoints.
- Run the versioned database migration as a single deployment step before starting each production release; production startup intentionally does not create tables.
- Add secret management and rotation, rate limiting, database-level row security where appropriate, and operational monitoring.
- Define and enforce the production transcript encryption, access, retention, and deletion policy.
