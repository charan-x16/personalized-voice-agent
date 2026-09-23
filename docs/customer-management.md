# Customer management slice

This slice adds a tenant-administrator workspace without turning administration into customer impersonation. A signed-in customer can still use only their own profile, conversations, and voice sessions. A signed-in administrator can list and maintain customer records for their tenant, but cannot start a voice session or open a customer transcript through the customer-facing routes.

## Request boundary

```text
Admin browser
    |
    | same-origin request + HttpOnly session cookie
    v
Next.js server/BFF
    |
    | server-only bearer token
    v
FastAPI customer route
    |
    | actor.tenant_id from the verified token
    v
Tenant-scoped customer, order, and conversation queries
```

The browser never supplies a `tenant_id`, role, or bearer token. Customer identifiers appear only as the resource being requested; every backend query combines that identifier with the administrator's verified tenant. An identifier from another tenant therefore returns the same `404` as an unknown identifier.

## API surface

All backend routes use the `/v1` prefix.

| Endpoint | Access | Purpose |
| --- | --- | --- |
| `GET /customers` | Tenant admin | Search and paginate active or inactive customers with bounded activity totals |
| `POST /customers` | Tenant admin | Create the customer, access user, default agent configuration, and Clerk invitation |
| `GET /customers/{customer_id}` | Tenant admin | Load the profile, agent configuration, recent audit events, order count, and five most recent saved conversations |
| `POST /customers/{customer_id}/access/invitation` | Tenant admin | Resend an invitation or restore a previously linked account |
| `POST /customers/{customer_id}/access/revoke` | Tenant admin | Revoke tenant access and invalidate a pending Clerk link when possible |
| `PATCH /customers/{customer_id}` | Tenant admin | Revision-safely update only name, preferred language, plan, or active state |
| `PATCH /customers/{customer_id}/agent-configuration` | Tenant admin | Revision-safely update agent name, greeting, tone, or instructions |

The matching browser routes live below `/api/customers`. Reads are rendered through authenticated server components; edits go through the same-origin BFF. Upstream responses are parsed into an explicit public shape before they cross the BFF.

There is intentionally no delete or impersonation endpoint. In this slice, `is_active` controls the customer profile: when the customer has a linked user, an inactive profile blocks that user's authentication and voice sessions. Deactivation is rejected while a voice session retains the customer's active slot, because disabling the profile must not bypass provider-session termination and reconciliation.

Customer onboarding commits the local profile, inactive access user, and invitation outbox job in one transaction before contacting Clerk. A confirmed invitation activates the access user; a provider failure leaves it inactive in `queued` state for bounded retry. The worker uses short claims and an access-generation check, so an older invitation result cannot reverse a newer revoke decision. Clerk public metadata is never used for authorization. A verified webhook can link the invited account first; first authenticated access remains a synchronous fallback that links the verified email to exactly one active local user. Revocation is local-authoritative, so a valid Clerk session or invitation link alone cannot cross the tenant boundary.

Profile and agent-configuration revisions are independent. Each mutation includes the revision from
the latest detail response; a stale revision returns `409` without writing. Successful changes
append an admin audit event containing the actor, timestamp, new revision, and changed field names.
Values are deliberately not copied into the audit record. See the
[production-hardening guide](production-hardening.md) for examples and deployment semantics.

## Production follow-ups

The demo role is sufficient to validate the authorization and UI flow, not to operate a production tenant. Before deployment:

- replace demo login with an identity provider and map immutable identity-provider groups or claims to tenant roles;
- define finer-grained roles if support agents should have less access than tenant owners;
- restrict direct database mutation of the application append-only audit table and decide whether an external tamper-evident archive is required;
- add database row-level security as a second tenant-isolation layer;
- add bulk import and archival workflows if tenants need them;
- deploy and monitor the Clerk invitation worker and signed webhook endpoint in every environment that sends real invitations;
- design explicit memberships before supporting one email across multiple tenant workspaces;
- replace the bounded offset pagination with cursor pagination for tenants above 10,020 matching customer records;
- introduce a separate voice-eligibility field if tenants need to pause calling without disabling the customer's workspace account;
- add an explicit, audited administrator terminate/reconcile flow for abandoned active sessions;
- snapshot or version the customer context and agent configuration bound to the first `on-start` call if retries/calls must remain deterministic while an administrator edits live data;
- add an application-level navigation guard for dirty forms; the current warning covers reloads and tab/window closure, not every client-side route transition; and
- apply an explicit retention and export policy to transcripts and account data.
