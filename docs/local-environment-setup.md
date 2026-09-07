# Local environment setup

The two processes read different files:

- Next.js reads `.env.local` at the repository root. Keep `API_BASE_URL`,
  `APP_ORIGIN`, and `VOICE_WEBSOCKET_HOSTS` there. Keep its `APP_ENV` aligned with
  the backend if changing environment modes.
- FastAPI reads `.env` in its working directory. Start it from `apps/api` and
  keep database credentials, Sarvam credentials, and internal secrets in
  `apps/api/.env` only. Never use a `NEXT_PUBLIC_` prefix for credentials.

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
ENABLE_DEMO_AUTH=false
SEED_DEMO_DATA=false
VOICE_PROVIDER=mock
```

`verify-full` enables certificate-chain and hostname verification for both the
API and the Alembic connection. Do not add a separate `sslmode` query parameter
to this asyncpg URL; this application configures TLS through
`DATABASE_SSL_MODE`. If certificate verification fails, configure a trusted CA
bundle rather than disabling verification.

Starting the API does **not** create PostgreSQL tables or seed PostgreSQL data.
Remote migrations require a separate, explicit review and execution. Demo
authentication and seeding are rejected for non-SQLite databases, even in
development mode. Until real authentication and tenant/user provisioning are
implemented, demo email sign-in is intentionally unavailable in this setup.

Use different, randomly generated values of at least 32 characters for
`SESSION_SECRET` and `SARVAM_TOOL_SECRET`. Rotating the session secret invalidates
previously issued application sessions; rotating the tool secret requires
updating any configured callback caller.

## What these settings do not enable

Supabase connectivity does not prove the application schema exists. The health
endpoint runs `SELECT 1`, so it checks database connectivity but not schema
readiness. A read-only connection test should precede any migration review.

Sarvam credentials do not yet enable live calls: the provider adapter deliberately
rejects real session creation until the provisioned session contract and audio
transport are implemented. `VOICE_PROVIDER=mock` is retained for now; no real
customer calls should be made during configuration checks.

For isolated UI/mock testing, use the local SQLite configuration from
`apps/api/.env.example` with demo flags enabled. Do not overwrite a configured
remote `.env` with that example; choose a separate local environment or explicit
process overrides. Backend tests use private temporary SQLite databases.

References: [Supabase connection options](https://supabase.com/docs/guides/database/connecting-to-postgres)
and [SQLAlchemy password escaping](https://docs.sqlalchemy.org/en/20/core/engines.html#escaping-special-characters-such-as-signs-in-passwords).
