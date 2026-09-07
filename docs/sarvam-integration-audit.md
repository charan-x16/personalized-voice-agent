# Sarvam Voice Agents integration audit

**Audit date:** 2026-09-03  
**Source policy:** Official Sarvam documentation and Sarvam-owned resources only.

## Executive conclusion

Yes: Sarvam can be the managed voice-agent layer while this application keeps its own database, authentication, customer identity, and business rules. Sarvam officially supports agent variables, on-start/on-end HTTP hooks, and mid-conversation HTTP API tools. Those are the correct integration points for customer-specific data.

The recommended tenancy model is **one reusable, versioned Sarvam agent per use case**, with dynamic context loaded for each authenticated customer. Create separate agents only when the prompt, tools, voice/language policy, compliance policy, or lifecycle differs materially. Do not create one Sarvam agent per end customer by default.

There is one important release blocker for this application's custom web voice UI: Sarvam advertises web, API, SDK, and WebSocket sessions, but its public [Deploy with Code](https://docs.sarvam.ai/conversations/deploy/deploy-with-code) page is explicitly a preview. It does not publish the live-session creation endpoint, WebSocket URL, authentication or ephemeral-token flow, audio framing, event schema, SDK package/methods, or initial-variable payload. The only fully described web path is copying a widget snippet from the authenticated Sarvam dashboard. We must obtain the provisioned contract from the dashboard or Sarvam support before enabling the real adapter.

## Support status

| Capability | Audit status | Implementation implication |
| --- | --- | --- |
| Managed ASR -> LLM -> TTS voice runtime, VAD, interruptions, language switching | **Confirmed** | Sarvam can own speech processing, orchestration, turn-taking, and synthesis. See [runtime](https://docs.sarvam.ai/conversations/build/run-time). |
| Telephony, web widget, API, and SDK voice channels | **Confirmed as product availability** | Sarvam says voice is generally available on these channels. See [overview](https://docs.sarvam.ai/conversations/overview). |
| On-start customer-context lookup and on-end result push | **Confirmed** | Point lifecycle hooks at narrowly scoped backend endpoints. See [hooks](https://docs.sarvam.ai/conversations/build/on-start-on-end-hooks). |
| Mid-call database/business API calls | **Confirmed** | Use an HTTP API tool; supported methods are GET, POST, PUT, PATCH, DELETE. See [API tool](https://docs.sarvam.ai/conversations/build/tools/https-tool). |
| Input/output variables, tool-readable variables, LLM-context toggle, PII masking/hashing | **Confirmed** | Pass an opaque conversation reference and minimal allowlisted context; keep identifiers/PII out of LLM context where possible. See [variables](https://docs.sarvam.ai/conversations/build/variables-personalization). |
| Static knowledge-base retrieval | **Confirmed** | Use for policies, product information, and FAQs. Sarvam explicitly says not to use it for personal account data. See [knowledge bases](https://docs.sarvam.ai/conversations/build/knowledge-base). |
| Dashboard-generated web widget | **Confirmed** | The authenticated dashboard supplies the snippet and controls theme/launcher/agent. No phone number is required. |
| Custom web session bootstrap and Voice Agents WebSocket | **Preview; contract not public** | Do not guess an endpoint or wire the browser directly. Keep the production provider fail-closed until Sarvam supplies the contract. |
| Programmatic create/update-agent API and managed Voice Agents SDK | **Preview; no public endpoint/package contract found** | Author and version the first agent in the dashboard. The public REST reference currently covers deployments, campaigns/cohorts, instant outbound, analytics, and BYOK—not agent authoring or live sessions. |
| Agent versioning and rollback | **Confirmed** | Deploy only committed/tested versions and pin `app_id` plus `app_version`. See [versioning](https://docs.sarvam.ai/conversations/build/agent/versioning). |
| Code Tools (`sarvam_conv_ai_sdk`) | **Enterprise only** | Not needed for the current database lookup; prefer HTTP API tools. See [Code Tools](https://docs.sarvam.ai/conversations/build/tools/code-tools). |
| Human handover | **Enterprise today** | Treat as account-gated. DTMF is described as planned, not generally available. |
| Voice on WhatsApp, text agents, additional IN22 languages | **Enterprise/on request** | Do not include in the base product promise without a contract. |
| Webhook signing, retry schedule, delivery ordering, and idempotency headers | **Not publicly documented** | Keep handlers idempotent and ask Sarvam for the verification/retry contract before production. |
| Live-session idempotency, lookup, and reconciliation | **Not publicly documented** | A production adapter needs a durable worker that can resolve timed-out or abandoned bootstrap/termination requests without creating duplicate sessions. |
| Managed Voice Agents numeric concurrency/CPS limits by plan | **Not publicly documented** | Read the account dashboard/contract; do not reuse Model API limits as Voice Agents limits. |
| Transcript/recording retention and zero-data-retention terms | **Not sufficiently documented for this deployment** | Obtain written retention/deletion terms before sending production customer data. |

## What Sarvam handles and what we handle

Sarvam handles the managed real-time loop: speech recognition, LLM reasoning, speech synthesis, VAD/turn-taking, barge-in, selected voice and language behavior, agent prompt/tools/knowledge, telephony or web transport, and Sarvam-side monitoring/analytics. Sarvam documents a 25-minute maximum configurable call length in [Conversation Settings](https://docs.sarvam.ai/conversations/build/conversation-settings), while its [runtime documentation](https://docs.sarvam.ai/conversations/build/run-time) labels human handover as enterprise-only today.

This platform must continue to handle:

- application login and authorization;
- tenant and customer resolution;
- the customer database and all business rules;
- narrow, authenticated tool/hook endpoints;
- tenant scoping on every lookup and mutation;
- consent, data minimization, audit logs, and retention policy;
- session correlation and replay/idempotency protection;
- UI, BFF, error states, product analytics, and fallback behavior;
- Sarvam credential storage, rotation, and provider-contract adaptation.

Sarvam states that the models in its managed Voice Agents stack are self-hosted and that data, including PII, remains in India. That is a useful [documented platform claim](https://docs.sarvam.ai/conversations/overview), but it is not a substitute for reviewing the applicable DPA, retention terms, subcontractors, and account contract. Data deliberately sent from Sarvam to our API tools is again governed by our own infrastructure controls.

## Recommended request and data flow

```text
Authenticated customer in web app
  -> Next.js BFF creates an internal voice session
  -> FastAPI verifies the actor and resolves tenant/customer from our database
  -> FastAPI creates an opaque, one-session conversation_ref
  -> provider adapter starts the Sarvam session and supplies only approved variables
  -> browser audio is carried through the provisioned Sarvam web transport
  -> Sarvam STT -> agent LLM
  -> on-start/API tool calls our FastAPI endpoints
  -> FastAPI resolves conversation_ref -> fixed tenant/customer and queries our DB
  -> minimal tool result -> Sarvam LLM -> Sarvam TTS -> customer
  -> on-end hook/outcome callback -> idempotent persistence in our DB
```

The LLM must never provide a tenant ID, customer ID, arbitrary SQL, or arbitrary database filter. It may supply only business inputs such as an order reference. The backend derives tenant/customer scope from the opaque session reference created after application authentication.

Do not use a Sarvam workspace as a replacement for application-level row isolation. Keep our database's tenant/customer checks authoritative. Use one Sarvam workspace per environment by default; use a dedicated workspace for a customer only when provider-side keys, staff access, configuration, or usage attribution must be separated. Sarvam says workspaces still share the organization's credit balance, while a separate organization is required for hard billing separation.

## Mapping to the implementation in this repository

The repository already implements the correct security boundary:

| Repository component | Current behavior | Sarvam mapping |
| --- | --- | --- |
| [`src/app/api/voice/sessions/route.ts`](../src/app/api/voice/sessions/route.ts) | Authenticated same-origin BFF; accepts only `language`; never returns provider credentials. | Calls our backend session bootstrap. Keep this boundary. |
| [`apps/api/src/svara_api/api/routes/voice.py`](../apps/api/src/svara_api/api/routes/voice.py) | Resolves the logged-in actor's active customer, creates and stores an opaque `conversation_ref`, enforces one active session, and calls the provider abstraction. | The eventual Sarvam bootstrap must send `conversation_ref` and `preferred_language` as initial agent variables. |
| [`apps/api/src/svara_api/services/voice_provider.py`](../apps/api/src/svara_api/services/voice_provider.py) | Has `mock` and guarded `sarvam` providers. The Sarvam provider validates server-only config and deliberately returns 503 because the public session contract is missing. | Correct current behavior. Implement only after obtaining the real endpoint/auth/frame/event contract. |
| [`apps/api/src/svara_api/api/routes/sarvam.py`](../apps/api/src/svara_api/api/routes/sarvam.py) | Implements on-start, `get_order_status`, and on-end endpoints. It derives tenant/customer from `conversation_ref`, binds an optional provider interaction ID, enforces expiry, audits calls, and makes completion first-write-wins. | Configure these as Sarvam lifecycle/API tools after public HTTPS deployment. |
| [`apps/api/src/svara_api/security.py`](../apps/api/src/svara_api/security.py) | Protects Sarvam-facing endpoints with constant-time validation of `X-Voice-Tool-Key`. | Store the corresponding secret in Sarvam Settings -> Secrets and add it as the API-tool authentication header. |
| [`src/hooks/use-voice-session.ts`](../src/hooks/use-voice-session.ts) and [`src/lib/voice/unsupported-live-transport.ts`](../src/lib/voice/unsupported-live-transport.ts) | Own provider-neutral microphone/session lifecycle and deliberately reject live transport without constructing a WebSocket. | Replace only the unsupported adapter after the managed web contract is known. |

Current internal endpoint contracts:

```text
POST /v1/sarvam/hooks/on-start
X-Voice-Tool-Key: <dedicated secret>
{ conversation_ref, interaction_id?, metadata? }

POST /v1/sarvam/tools/get-order-status
X-Voice-Tool-Key: <dedicated secret>
{ conversation_ref, interaction_id?, order_reference }

POST /v1/sarvam/hooks/on-end
X-Voice-Tool-Key: <dedicated secret>
{ conversation_ref, interaction_id?, resolution, summary?, transcript?, final_variables?, duration_seconds? }
```

The published instant-outbound webhook payload is **not shape-compatible** with our on-end request. It uses fields such as `status`, `final_agent_variables`, and transcript turns shaped as `{role, en_text}`. Do not point that webhook directly at `/v1/sarvam/hooks/on-end`; add a verified normalization route if instant outbound is adopted. See the official [instant-outbound webhook schema](https://docs.sarvam.ai/conversations/api/instant-outbound/webhook-payload).

## Exact Sarvam dashboard checklist

1. Create/select the correct organization and a dedicated **production workspace**. Use a separate staging workspace and separate API keys. Sarvam describes an organization as the billing/identity boundary and a workspace as the project/environment/access boundary in its [Platform FAQ](https://docs.sarvam.ai/api/platform/faq).
2. In Voice Agents, create one agent for this customer-support use case. Record its Agent ID, commit a version, and test that committed version. The first agent should be authored in the dashboard because the public create/update-agent contract is only previewed.
3. Configure the voice, starting language, allowed language switching, interruption behavior, quiet-caller nudges, privacy protection, and maximum call length. Keep the maximum at or below both Sarvam's 25-minute cap and our session TTL.
4. Create these input variables:
   - `conversation_ref`: opaque per-session correlation value; keep it out of LLM context if the tool builder permits tool-only use.
   - `preferred_language`: minimal language preference.
   - `first_name`, `plan_name`, and `open_request_count`: populated by the on-start response; expose to the LLM only when needed.
5. Create only allowlisted output variables that the application will persist, currently `order_reference`, `follow_up`, and `resolution_code`. Mark PII variables and configure masking/hashing.
6. Under Settings -> Secrets, store a unique production tool secret corresponding to backend `SARVAM_TOOL_SECRET`. Never reuse the Sarvam Voice Agents API key or the application's session-signing secret.
7. Add an API tool with lifecycle `on_start`:
   - method: `POST`;
   - URL: `https://<api-host>/v1/sarvam/hooks/on-start`;
   - header: `X-Voice-Tool-Key` from the Sarvam secret store;
   - JSON body mapped to `conversation_ref`, and to Sarvam's interaction ID/metadata if those fields are exposed by the provisioned builder;
   - response mappings: `customer.first_name`, `customer.preferred_language`, `customer.plan_name`, `customer.open_request_count`, and `safe_to_continue`.
8. Add a during-conversation API tool named `get_order_status`:
   - clear description stating it may run only when the caller asks about an order;
   - method: `POST`;
   - URL: `https://<api-host>/v1/sarvam/tools/get-order-status`;
   - the same secret header;
   - body fields `conversation_ref`, optional bound `interaction_id`, and model-supplied `order_reference`;
   - a short pre-run phrase and a tight timeout. Sarvam allows API-tool timeouts up to 30 seconds, but our target should be much lower.
9. Add an `on_end` lifecycle hook to `https://<api-host>/v1/sarvam/hooks/on-end` with the same secret header. Map the final fields into our normalized schema. Confirm in the actual builder which runtime fields are available for interaction ID, transcript, summary, and duration; the public hook page does not publish an exact template schema.
10. Allow Sarvam egress to the API. The API-tool page currently lists `4.213.167.70`; confirm the current complete list with Sarvam before production because the BYOK documentation separately says to contact support for current egress IPs.
11. In Deploy with Code, either copy the dashboard widget snippet for the supported widget path, or obtain the account-specific custom session API/SDK recipe. Never put `X-API-Key` in browser JavaScript. Sarvam explicitly recommends a backend proxy for client-facing WebSockets.
12. In backend production secrets, set `VOICE_PROVIDER=sarvam`, `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `SARVAM_AGENT_ID`, and a distinct `SARVAM_TOOL_SECRET`—but switch the provider only after the adapter and end-to-end contract tests are complete.

The unresolved critical step is how a web/API session accepts the initial `conversation_ref`. Campaign CSVs and on-start/telephony metadata are documented variable sources, but the public web-session initial-variable payload is not. Require Sarvam to demonstrate this before adopting the widget or custom WebSocket for authenticated personalization.

## Public Voice Agents API surface

Voice Agents REST calls use `X-API-Key`; the official [API introduction](https://docs.sarvam.ai/conversations/api/introduction) lists these service bases:

- deployments: `https://apps.sarvam.ai/api/app-authoring`;
- campaigns/cohorts: `https://apps.sarvam.ai/api/scheduling`;
- instant outbound: `https://apps.sarvam.ai/api/outbounds`;
- analytics: `https://apps.sarvam.ai/api`.

Documented examples relevant to this platform:

- Create an inbound telephony deployment: `POST https://apps.sarvam.ai/api/app-authoring/v1/orgs/{org_id}/workspaces/{workspace_id}/deployments`, with `name`, `app_id`, `app_version`, and `connection_configs`; see [Create deployment](https://docs.sarvam.ai/conversations/api/deployments/create).
- Place an instant outbound call: `POST https://apps.sarvam.ai/api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds`, with `app_config`, `user_config`, and optional `webhook_config`; see [Create outbound call](https://docs.sarvam.ai/conversations/api/instant-outbound/create).
- Analytics includes attempts, interactions, recordings, and transcripts beneath `https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/...`; see [attempts](https://docs.sarvam.ai/conversations/api/analytics/attempts), [interactions](https://docs.sarvam.ai/conversations/api/analytics/interactions), [recordings](https://docs.sarvam.ai/conversations/api/analytics/recordings), and [transcripts](https://docs.sarvam.ai/conversations/api/analytics/transcripts).

These are management/telephony/analytics endpoints. None is a documented inbound browser-session bootstrap.

Authentication has three separate contracts that must not be conflated:

- Voice Agents management REST: `X-API-Key`, backend only.
- Our Sarvam-facing hook/tool endpoints: application-defined `X-Voice-Tool-Key` stored as a Sarvam workspace secret.
- Sarvam Model APIs: `api-subscription-key` (or documented Bearer alternative), not the managed Voice Agents header. See [Model API authentication](https://docs.sarvam.ai/api-reference/authentication).

Sarvam's API tool supports no auth, bearer, API key, and basic auth, and stores credential values as masked workspace secrets. Organization policy controls are plan-dependent and can restrict agent creation, production deployment, transcript/recording access, and secret management; see [Policy](https://docs.sarvam.ai/conversations/settings/policy). BYOK is also documented for customer-controlled encryption keys, but public availability/tier and its fit for this account must be confirmed; see [BYOK](https://docs.sarvam.ai/conversations/api/byok/overview).

## Pricing and limits

- Sarvam's official Epoch announcement says managed Voice Agents are generally available without a waitlist at **₹3.50 per minute**, with authoring, simulation, phone numbers, evaluation, and analytics included. See [Epoch summary](https://www.sarvam.ai/epoch/summary). Confirm taxes, billing rounding, minimums, and what “phone numbers included” means in the account contract.
- The current public product/API documentation does not provide a detailed managed Voice Agents pricing table or billing-unit definition; ₹3.50/minute is the official announcement figure, not a complete commercial schedule.
- The telephony docs separately say rented-number prices vary by number, are visible in the dashboard catalog, are deducted from the Sarvam wallet, and renew every 30 calendar days. See [Rent from Sarvam](https://docs.sarvam.ai/conversations/deploy/telephony/rent-from-sarvam). BYOT carrier charges remain with the chosen provider.
- Billing is organization-level: all workspaces/products consume one credit balance, and there are no per-workspace budgets. Enterprise offers custom pricing, concurrency, throughput, support, and SLAs. See [Billing](https://docs.sarvam.ai/api/platform/billing).
- Campaign APS/CPS defaults to `2`. Sarvam documents `concurrency ~= APS x connect rate x average talk time`; plan CPS/concurrency is shared across campaigns, instant outbound, and inbound calls. See [Dialing rate and concurrency](https://docs.sarvam.ai/conversations/deploy/campaigns/dialing-rate).
- Sarvam does **not** publish numeric managed Voice Agents CPS/concurrency ceilings by plan in the public docs. The runtime page's “20,000+ concurrent calls” statement is a platform-scale claim, not an allocation for this account.
- Sarvam Model API pricing and limits are separate from the managed ₹3.50/minute offering and must not be used to estimate the current managed design.

## Required answers from Sarvam before live web enablement

Ask Sarvam support (`developer@sarvam.ai`) or the account team for:

1. the exact create-session endpoint, method, request/response schemas, agent/version selection rules, idempotency-key support, and lookup/reconciliation API;
2. the exact WSS URL, handshake auth, audio encoding/sample rate/frame boundaries, client and server event schemas, keepalive, reconnect, and session termination rules;
3. whether a browser-safe short-lived token exists, its TTL, origin controls, and revocation behavior; otherwise the supported backend proxy pattern;
4. the official managed Voice Agents SDK package, supported versions, session methods, and compatibility policy;
5. the supported way to pass signed initial variables/opaque metadata (`conversation_ref`) into widget, API, and SDK sessions;
6. lifecycle-hook runtime field names and exact body-template syntax for interaction ID, transcript, summary, final variables, and duration;
7. webhook/tool request signing, retry schedule, timeout behavior, ordering, replay protection, and complete egress IP ranges;
8. account-specific managed concurrency/CPS, rate-limit responses, maximum web sessions, SLAs, and quota-increase process;
9. billing rounding, failed/short-call billing, widget/web session billing, number rental/carrier charges, and taxes;
10. transcript/audio/log retention, deletion APIs, training opt-out, DPA, data residency, ZDR options, and incident commitments.

## Explicit alternative: build the runtime with Model APIs

If Sarvam cannot provide a usable managed web-session contract, a separately scoped fallback is to build the voice runtime ourselves using Sarvam Model APIs plus LiveKit or Pipecat. Sarvam publishes runnable official guides for [LiveKit](https://docs.sarvam.ai/api/integration/build-voice-agent-with-live-kit) and [Pipecat](https://docs.sarvam.ai/api/integration/build-voice-agent-with-pipecat). In that design Sarvam supplies STT, the conversational LLM, and TTS, while we own realtime transport, orchestration, tool calling, turn state, retries, recording, and monitoring.

This is **an alternative, not the current implementation**. It has a different authentication contract, separate per-model pricing/rate limits, and materially more operational responsibility. Do not silently substitute it for managed Voice Agents; make it a deliberate architecture decision if the managed contract remains unavailable.

## Decision

Proceed with the existing dynamic-context architecture and the current fail-closed provider boundary. Configure and validate the Sarvam agent, variables, hooks, and HTTP tool in a staging workspace now. Enable live web voice only after the dashboard/account contract proves that a server-created session can carry the opaque `conversation_ref`, gives us a browser-safe or backend-proxied WebSocket protocol, and supports durable reconciliation of uncertain or abandoned session operations.
