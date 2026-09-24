# Local environment setup

The two processes read different files:

- Next.js reads `apps/web/.env.local`. Keep `API_BASE_URL`,
  `APP_ORIGIN`, `VOICE_WEBSOCKET_HOSTS`, the Clerk publishable/secret keys, and
  Clerk route settings there. Never prefix `CLERK_SECRET_KEY` with
  `NEXT_PUBLIC_`. Keep `APP_ENV` aligned with the backend if changing modes.
- FastAPI reads `.env` in its working directory. Start it from `apps/api` and
  keep database credentials, Sarvam credentials, internal secrets, and
  `CLERK_SECRET_KEY` in `apps/api/.env`.

No additional runtime `.env` files are required. The repository-root
`apps/web/.env.example` documents only Next.js variables, while
`apps/api/.env.example` documents only FastAPI variables.

Restart both processes after environment changes. Both files must remain ignored
by Git. Do not paste passwords or API keys into diagnostics or screenshots.

## Supabase development connection

Copy the actual connection string from your project's **Connect** panel. Use the
SQLAlchemy async driver (`postgresql+asyncpg://`) and percent-encode special
characters in the password portion, not the whole URL. Do not guess the host or
pooler region. Direct Supabase connections generally require IPv6; the session
pooler on port 5432 is an alternative for IPv4 networks.

Set these backend values alongside the actual URL and credentials:

```dotenv
APP_ENV=development
DATABASE_SSL_MODE=verify-full
DATABASE_CA_CERT_FILE=./certs/supabase-prod-ca-2021.crt
DATABASE_POOLER_HOST=aws-0-your-project-region.pooler.supabase.com
ENABLE_DEMO_AUTH=false
SEED_DEMO_DATA=false
VOICE_PROVIDER=sarvam
CLERK_SECRET_KEY=your-clerk-secret-key
# Optional: networkless Clerk JWT signature verification.
CLERK_JWT_KEY=
# Clerk Dashboard -> Webhooks -> endpoint signing secret.
CLERK_WEBHOOK_SIGNING_SECRET=whsec_your-signing-secret
```

`verify-full` enables certificate-chain and hostname verification for both the
API and the Alembic connection. Do not add a separate `sslmode` query parameter
to this asyncpg URL; this application configures TLS through
`DATABASE_SSL_MODE`. Supabase's database certificate uses its private CA. The
public CA included at `apps/api/certs/supabase-prod-ca-2021.crt` was obtained
from Supabase's official download host; compare it with the certificate offered
in your project's **Database Settings → SSL Configuration** when rotating it.

Starting the API does **not** create PostgreSQL tables or seed PostgreSQL data.
Remote migrations require a separate, explicit review and execution. Demo
authentication and seeding are rejected for non-SQLite databases, even in
development mode.

After migrations or credential changes, verify the connection and required tables without writing
data:

```bash
cd apps/api
uv run python scripts/check_database.py
```

Use the Clerk CLI to merge the linked development keys into both runtime files
without printing them:

```bash
clerk env pull --file apps/web/.env.local
clerk env pull --file apps/api/.env
```

Create a Clerk account whose verified primary email matches exactly one active
row in the application's `users` table. On first access, FastAPI persists the
immutable Clerk user ID on that row; later requests no longer rely on email.
A customer user must reference an active customer in the same tenant, while an
administrator must not reference a customer. Missing, ambiguous, inactive, or
already-linked matches fail closed. In non-production only, Clerk test aliases
such as `rahul+clerk_test@example.com` may link to the seeded
`rahul@example.com` row; use verification code `424242` in Clerk test mode.

For local webhook testing, expose port 8000 with a trusted tunnel, configure the exact public URL ending in `/v1/webhooks/clerk` in Clerk Dashboard, and subscribe to `user.created`, `user.updated`, and `user.deleted`. Never disable signature verification for local testing. In production, use the final HTTPS API hostname with no redirect in front of the webhook path.

Use different, randomly generated values of at least 32 characters for
`SESSION_SECRET` and `SARVAM_TOOL_SECRET`. Rotating the session secret invalidates
previously issued application sessions; rotating the tool secret requires
updating any configured callback caller.

Add the Sarvam runtime values from the committed agent:

```dotenv
SARVAM_API_KEY=your-server-only-key
SARVAM_ORG_ID=your-organization-id
SARVAM_WORKSPACE_ID=your-workspace-id
SARVAM_AGENT_ID=your-agent-id
SARVAM_AGENT_VERSION=2
VOICE_WEBSOCKET_PUBLIC_URL=ws://127.0.0.1:8000/v1/voice/stream
CLERK_INVITATION_REDIRECT_URL=http://localhost:3000/sign-up
CLERK_INVITATION_EXPIRY_DAYS=30
CLERK_OUTBOX_MAX_ATTEMPTS=8
CLERK_OUTBOX_RETRY_BASE_SECONDS=30
CLERK_OUTBOX_RETRY_MAX_SECONDS=3600
CLERK_OUTBOX_CLAIM_TIMEOUT_SECONDS=300
```

The version must be committed in Sarvam. Use the latest deliberate committed version, not a draft.
The local relay uses `ws:` only on loopback; staging and production require a public `wss:` URL.
The base `sarvam-conv-ai-sdk` dependency is sufficient because browser audio is proxied as PCM and
the API server does not open local audio hardware.

When testing retries or running a shared environment, start the invitation worker in a third terminal:

```bash
cd apps/api
uv run python scripts/process_invitation_outbox.py --watch
```

## What these settings do not enable

Supabase connectivity does not prove the application schema exists. The health
endpoint runs `SELECT 1`, so it checks database connectivity but not schema
readiness. A read-only connection test should precede any migration review.

Sarvam credentials and the relay enable live speech. Cafe availability, create, lookup,
reschedule, and cancel actions are implemented in the backend, but they also require migration
`20260909_0003`, a tenant reservation policy/table inventory, and manual Sarvam API-tool
configuration. Follow the exact [Sarvam v2 tool mapping guide](sarvam-v2-reservation-tools.md)
before testing live booking actions.

For isolated UI/mock testing, use the local SQLite configuration from
`apps/api/.env.example` with demo flags enabled. Do not overwrite a configured
remote `.env` with that example; choose a separate local environment or explicit
process overrides. Backend tests use private temporary SQLite databases.

References: [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres),
[Clerk Next.js quickstart](https://clerk.com/docs/nextjs/getting-started/quickstart),
and [SQLAlchemy password escaping](https://docs.sqlalchemy.org/en/20/core/engines.html#escaping-special-characters-such-as-signs-in-passwords).
