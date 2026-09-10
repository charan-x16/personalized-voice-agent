# Svara

Svara is a personalized, multilingual voice-agent platform prototype. The repository contains polished Next.js customer and tenant-admin interfaces plus a FastAPI backend vertical slice for tenant-scoped customer management, per-customer agent configuration, voice sessions, customer data tools, and conversation persistence.

The web app and backend support both an isolated local mock flow and live browser voice through Sarvam's official Python Agents SDK. Live audio is proxied by FastAPI so the Sarvam API key never reaches the browser. See the [Sarvam integration audit](docs/sarvam-integration-audit.md) for the support boundary, setup, and remaining production constraints.

## Current status

### Web application

- Editorial product landing page with public, no-microphone conversation and language simulations
- Clerk sign-in/sign-up with managed sessions and polished account controls
- Role-aware customer and tenant-administrator workspaces
- Searchable, filterable customer directory with revision-safe profile and voice-agent editors
- Per-customer agent name, greeting preview, tone, and bounded custom instructions
- Recent admin-change timeline that records changed field names without duplicating values
- Live profile and dashboard data from `GET /v1/me` and `GET /v1/conversations`
- Searchable conversation archive and transcript detail view backed by the API
- Voice-room session creation, browser PCM capture/playback, live Sarvam relay, authenticated cancellation, and development-only mock completion
- Responsive layouts, keyboard navigation, reduced-motion support, and accessible status announcements

### API

- Independent Clerk session-token verification and tenant-safe application-user mapping
- Short-lived demo bearer authentication retained only for local SQLite API tests
- Tenant-administrator customer list, detail, and allowlisted update endpoints
- Optimistic concurrency for profile and agent-configuration changes
- Application append-only admin audit events with actor, revision, time, and changed field names
- Tenant-scoped profile and conversation read endpoints
- Authenticated, tenant-safe voice-session bootstrap and idempotent cancellation
- One active voice session per customer, enforced by the database
- Mock provider implementation for local development
- Official Sarvam SDK provider with a committed-version pin and secure browser WebSocket relay
- Backend-only conversation references stored only as hashes
- Authenticated `on_start`, read-only order-status, and `on_end` endpoints for the voice provider
- Tenant-safe cafe availability, reservation creation, lookup, rescheduling, and cancellation tools
- Retry-safe reservation mutations, optimistic edit versions, and PostgreSQL overlap protection
- Provider-interaction binding, first-write-wins completion, and a bounded delayed-callback grace window
- Tenant/customer-scoped database queries, bounded outcome persistence, and minimized tool audit records
- Database-backed health checks, global request-body limits, and allowlisted final variables
- Alembic-managed production schema with a fresh-database baseline migration
- SQLite for local development and PostgreSQL support through SQLAlchemy

## Architecture

```text
Customer browser
        |
        | Clerk-managed session + same-origin application requests
        v
Next.js BFF / server components
        |
        | Authorization: Bearer ... (server-side only)
        v
Svara API (FastAPI) -----> official SDK adapter ------> Sarvam Voice Agent
        ^                                                   |
        | X-Voice-Tool-Key + opaque conversation reference |
        +---------------- hooks and tools ------------------+
        |
        +---- tenant/customer-scoped queries ----> PostgreSQL

```

Browser application code never receives the FastAPI bearer token or selects a `tenant_id` or `customer_id`. Clerk owns sign-in, sign-up, recovery, and the browser session. Next.js obtains the current Clerk session token on the server and forwards it only in server-to-server FastAPI requests. FastAPI verifies the Clerk token, resolves its immutable user ID, and derives tenant/customer scope from the application database. On first access only, a verified primary Clerk email can link to exactly one pre-provisioned active application user; the immutable Clerk user ID is persisted for later requests. The API passes an opaque, short-lived conversation reference directly to the provider adapter; neither that reference nor provider agent variables are included in browser responses.

## Repository layout

```text
src/                 Next.js frontend
apps/api/            FastAPI backend
compose.yaml         Local PostgreSQL service
```

## Run locally

Prerequisites: Node.js 22.15 or newer, pnpm 11, Python 3.11 or newer, and `uv`.
Docker is optional for running the local PostgreSQL service.

The project uses exactly two untracked runtime environment files:
`.env.local` for Next.js and `apps/api/.env` for FastAPI. Their tracked,
credential-free templates are `.env.example` and `apps/api/.env.example`.
Do not copy database or Sarvam secrets into the root Next.js environment file,
and never expose `CLERK_SECRET_KEY` through a `NEXT_PUBLIC_` name.

### 1. Start the API

From the repository root:

```bash
cd apps/api
cp .env.example .env
uv sync --dev
uv run uvicorn svara_api.main:app --reload
```

On PowerShell, use `Copy-Item .env.example .env` instead of `cp`. The API is available at [http://localhost:8000](http://localhost:8000), with OpenAPI documentation at [http://localhost:8000/docs](http://localhost:8000/docs).

The default backend configuration creates `apps/api/svara.db` and idempotently seeds these application profiles:

- Customer account: `rahul@example.com`
- Workspace administrator: `ananya@acme.example`
- Five example customers and three example orders, including `ORD-8294`

### 2. Start the frontend

From the repository root, set the server-only backend address in `.env.local`:

```text
API_BASE_URL=http://127.0.0.1:8000
NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=your-clerk-publishable-key
CLERK_SECRET_KEY=your-clerk-secret-key
NEXT_PUBLIC_CLERK_SIGN_IN_URL=/sign-in
NEXT_PUBLIC_CLERK_SIGN_UP_URL=/sign-up
# Optional: canonical URL for production metadata
NEXT_PUBLIC_SITE_URL=http://localhost:3000
# Optional: an HTTPS support page or mailto address for access help
NEXT_PUBLIC_SUPPORT_URL=
```

Then run:

```bash
pnpm install
pnpm dev
```

The preferred setup is `clerk init --app app_3J2EY1ljMXFFTN6tlNCp7eU1wJu`, followed by `clerk env pull --file .env.local` and `clerk env pull --file apps/api/.env`. The backend needs `CLERK_SECRET_KEY`; it is never sent to the browser. Open [http://localhost:3000](http://localhost:3000) and create the first test account from the navigation. In a Clerk development instance, `rahul+clerk_test@example.com` links to the seeded `rahul@example.com` customer and can be verified with code `424242`. Use `ananya+clerk_test@acme.example` for the seeded administrator.

To use PostgreSQL instead, run `docker compose up -d postgres` from the repository root and set:

```text
DATABASE_URL=postgresql+asyncpg://svara:local-development-only@localhost:5432/svara
DATABASE_SSL_MODE=disable
ENABLE_DEMO_AUTH=false
SEED_DEMO_DATA=false
```

The Compose port is bound to `127.0.0.1` only, and its included password is strictly for local development.

PostgreSQL requires explicitly reviewed migrations and application-user provisioning; it does not support the SQLite demo login. Clerk authentication is implemented. First access links one verified Clerk email to one active application user and persists the immutable Clerk user ID; ambiguous or inactive matches fail closed. For credentials, TLS, and the two environment files, see the [local environment setup guide](docs/local-environment-setup.md).

## Implemented API endpoints

All routes use the `/v1` prefix.

| Endpoint | Caller | Purpose |
| --- | --- | --- |
| `GET /health` | Infrastructure | Verifies the API can execute a database query |
| `POST /auth/demo-login` | Local SQLite API tests only | Issues a short-lived token for a seeded demo user |
| `GET /me` | Authenticated Next.js server | Returns the current user's minimal profile |
| `GET /customers` | Tenant administrator | Searches and paginates customers in the authenticated tenant |
| `GET /customers/{customer_id}` | Tenant administrator | Returns a scoped profile, agent configuration, recent audit events, and activity summary |
| `PATCH /customers/{customer_id}` | Tenant administrator | Revision-safely updates only name, preferred language, plan, or active state |
| `PATCH /customers/{customer_id}/agent-configuration` | Tenant administrator | Revision-safely updates the customer's provider-neutral agent behavior |
| `GET /conversations` | Authenticated Next.js server | Lists completed conversations in the current customer scope |
| `GET /conversations/{session_id}` | Authenticated Next.js server | Returns one scoped transcript and outcome |
| `POST /voice/sessions` | Authenticated Next.js BFF | Creates a customer-scoped mock/provider session |
| `WS /voice/stream` | Browser with encrypted relay token | Relays 16 kHz PCM and bounded live events through the server-side Sarvam SDK |
| `POST /voice/sessions/{session_id}/cancel` | Authenticated Next.js BFF | Idempotently stops a scoped provider session and releases its active slot after confirmed termination |
| `POST /voice/sessions/{session_id}/mock-complete` | Authenticated Next.js BFF | Completes a mock call in development/test only |
| `POST /sarvam/hooks/on-start` | Voice provider | Returns minimal customer context and rendered runtime agent configuration |
| `POST /sarvam/tools/get-order-status` | Voice provider | Reads one order within the bound customer scope |
| `POST /sarvam/tools/check-availability` | Voice provider | Returns valid cafe slots near a requested local date/time |
| `POST /sarvam/tools/create-reservation` | Voice provider | Atomically books one customer-scoped slot |
| `POST /sarvam/tools/find-reservation` | Voice provider | Finds a reference or upcoming customer reservations |
| `POST /sarvam/tools/reschedule-reservation` | Voice provider | Moves a reservation with an optimistic version check |
| `POST /sarvam/tools/cancel-reservation` | Voice provider | Cancels a reservation with retry-safe idempotency |
| `POST /sarvam/hooks/on-end` | Voice provider | Stores the first bounded outcome and safely handles retries |

Clerk components handle browser sign-in, sign-up, account recovery, and sign-out. The browser calls same-origin BFF routes for customer reads and updates, voice-session creation/cancellation, and development-only mock completion. Authenticated server-rendered pages use `await auth()` and forward a short-lived Clerk session token to FastAPI. Direct FastAPI client calls require `Authorization: Bearer <Clerk session token>`; the local demo token remains limited to isolated SQLite API tests.

Administrators cannot choose a tenant, impersonate a customer, use customer voice routes, or delete history. A cross-tenant customer identifier is returned as not found. Profile and agent edits require the revision returned by the detail endpoint; a stale update receives `409` instead of silently overwriting newer work. See the [customer-management security boundary](docs/customer-management.md) and [production-hardening guide](docs/production-hardening.md) for the request flow, migration procedure, and remaining release gates.

Sarvam-facing hooks and tools require `X-Voice-Tool-Key` and the backend-only `conversation_ref` injected into the provider session. When `on-start` supplies a provider `interaction_id`, later tool and completion calls must supply that same value.

Only one active voice session can be reserved for a customer. A second start returns `409`; a later start can reclaim a slot whose session has expired. Successful authentication and session-bootstrap responses include `Cache-Control: no-store`.

## Deployment defaults

- The API container runs as the unprivileged `svara` user.
- Clerk manages browser session cookies; mutation BFF routes still reject cross-origin requests.
- `VOICE_WEBSOCKET_HOSTS` is a server-only, comma-separated exact-host allowlist applied by the BFF before a relay URL can reach the browser. Production uses the public API hostname over WSS.
- Request bodies are capped by `MAX_REQUEST_BODY_BYTES` before route handling.
- Only top-level outcome keys listed in `FINAL_VARIABLE_ALLOWLIST` are retained from provider final variables.
- Only non-production SQLite startup may create a development schema. PostgreSQL startup never creates or seeds tables; its schema must be explicitly migrated before use.
- Application-level tenant scoping is implemented. New reservation tables also enable PostgreSQL row-level security and deny Supabase Data API access to `anon` and `authenticated`; broader database RLS and rate limiting remain production work.
- Administrative updates are allowlisted, revision-checked, and recorded in an application append-only audit trail. Production database roles must separately deny direct mutation of that table where required.
- Transcripts are bounded, but production still requires an explicit retention/deletion policy, encryption, and access controls.

See [apps/api/README.md](apps/api/README.md) for request examples and lifecycle semantics, and the [Sarvam integration audit](docs/sarvam-integration-audit.md) for confirmed capabilities, implementation boundaries, pricing considerations, and dashboard configuration.

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

- Replace automatic first-access email linking with an explicit Clerk invitation/webhook provisioning workflow where the same email must belong to multiple tenants.
- Configure the production Clerk account lifecycle, recovery/MFA policy, invitation flow, authorized parties, and application-level auth abuse controls.
- Add durable coordination for active SDK connections before running multiple API workers; the current in-memory relay registry requires one worker or sticky routing.
- Configure the committed Sarvam agent variables and map its HTTP tools to the public backend using the shared tool credential and opaque conversation reference.
- Apply migration `20260909_0003`, provision the production policy/table inventory, and configure the five reservation tools using [the v2 mapping guide](docs/sarvam-v2-reservation-tools.md).
- Preserve the backend-to-provider reference boundary: neither the conversation reference nor provider agent variables should be returned by browser-facing endpoints.
- Run the versioned database migration as a single deployment step before starting each production release; production startup intentionally does not create tables.
- Add secret management and rotation, rate limiting, database-level row security where appropriate, and operational monitoring.
- Define and enforce the production transcript encryption, access, retention, and deletion policy.
