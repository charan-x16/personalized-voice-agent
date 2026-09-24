# Infrastructure

Svara currently has four production process types:

- `web`: the Next.js application in `apps/web`.
- `api`: the FastAPI application in `apps/api`.
- `invitation-worker`: `apps/api/scripts/process_invitation_outbox.py --watch`.
- `migration-job`: `alembic upgrade head`, run once before an API rollout.

PostgreSQL is the system of record. Clerk provides identity and session
issuance. Sarvam provides the live voice runtime. Secrets are injected into the
specific server process that needs them; none belong in browser-visible
variables.

The root `compose.yaml` is for local PostgreSQL only. A production platform
must additionally provide HTTPS/WSS termination, health checks, encrypted
secrets, database backups, worker monitoring, and a single API worker until the
process-local Sarvam session registry is replaced with shared coordination.
