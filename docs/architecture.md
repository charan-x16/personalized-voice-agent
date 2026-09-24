# Svara architecture

Svara is a modular monolith: two deployable applications in one repository,
with provider integrations kept behind application-owned boundaries. This is
deliberate. The current workload does not need independently deployed
microservices, and keeping transactions inside the API preserves tenant and
customer consistency.

## Repository boundaries

```text
apps/
  web/                         Next.js UI and same-origin BFF routes
  api/                         FastAPI application and Alembic migrations
    src/svara_api/
      api/                     Public router composition only
      domains/                 Business capabilities
        identity/
        customers/
        conversations/
        voice/
        tools/
        reservations/
        health/
      integrations/            External provider adapters
        clerk/
        sarvam/
      models.py                Shared persistence model (split later by domain)
      schemas.py               Shared transport schemas (split later by domain)
packages/
  api-contract/                Generated OpenAPI contract for consumers
infrastructure/                Deployment topology and operational guidance
docs/                          Product, security, and integration decisions
```

## Request flow

```text
Browser -> Next.js BFF -> FastAPI domain -> PostgreSQL
                         |          |
                         |          +-> Clerk integration
                         +------------> Sarvam integration -> live voice agent
```

The browser never receives backend credentials, Sarvam API keys, tenant IDs to
trust, or raw customer-scoping tokens. Next.js obtains the Clerk session token
server-side. FastAPI verifies it, derives tenant/customer scope from the
database, and calls external providers through the integration modules.

## Dependency rules

1. `api/router.py` composes domain and integration routers; it contains no
   business logic.
2. Domain modules may use shared database models, schemas, and security helpers.
3. Provider-specific logic belongs under `integrations/` and must not leak API
   keys or provider session material to the browser.
4. Cross-domain calls should use a small exported function, not reach into an
   unrelated router handler.
5. Database migrations stay under `apps/api/alembic`; production schema changes
   are migration-managed.
6. The committed OpenAPI document is generated from FastAPI and checked in CI.

`models.py`, `schemas.py`, and the larger route modules are retained as shared
compatibility seams for now. Split them only as features change; a mechanical
rewrite would add risk without improving the runtime boundary.
