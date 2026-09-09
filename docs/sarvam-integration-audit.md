# Sarvam Voice Agents integration audit

**Updated:** 9 September 2026
**Source policy:** Sarvam documentation, the Sarvam dashboard recipe supplied for this workspace,
and the Sarvam-maintained Python package only.

## Conclusion

Yes. Sarvam can provide the managed voice-agent runtime while Svara keeps customer identity,
tenant isolation, business data, and business rules in its own application and database.

The implemented default is one committed, version-pinned Sarvam agent per use case. Each live
session receives customer-specific variables from Svara after Clerk authentication and a
tenant-scoped database lookup. A separate Sarvam agent is warranted only when a customer needs a
materially different prompt, voice/language policy, tool set, compliance boundary, staff-access
boundary, or usage boundary.

## Official support versus Svara implementation

| Capability | Status | Boundary |
| --- | --- | --- |
| Managed ASR -> agent/LLM -> TTS, turn taking, interruptions, multilingual behavior | Officially supported | Sarvam owns the real-time conversational runtime. See the [Voice Agents overview](https://docs.sarvam.ai/conversations/overview). |
| Web, API, SDK, and telephony channels | Officially supported | Sarvam lists these as deployment channels. |
| Python Agents SDK and backend-proxy use case | Officially supported | Svara pins `sarvam-conv-ai-sdk==1.1.0`. Sarvam's package describes backend proxies as a supported use case. See the [official package](https://pypi.org/project/sarvam-conv-ai-sdk/1.1.0/). |
| Per-session agent variables and initial language/message overrides | Official SDK capability | Svara injects only bounded application context into each interaction. |
| Mid-conversation HTTP tools and code tools | Officially supported | HTTP tools are the normal database/business-API path. Code tools are available on request. See [Code Tools](https://docs.sarvam.ai/conversations/build/tools/code-tools). |
| Browser microphone/speaker implementation | Svara implementation | The browser sends raw signed 16-bit, mono, 16 kHz PCM to Svara and receives the same PCM format back. |
| Browser authentication to the relay | Svara implementation | The authenticated BFF returns an encrypted, expiring relay token. The browser moves it into the WebSocket subprotocol header so it is not written into normal URL access logs. Sarvam credentials never reach the browser. |
| Customer/tenant isolation | Svara implementation | Every session and tool lookup derives tenant/customer scope from authenticated server-side state. Sarvam variables are not an authorization boundary. |
| Durable multi-worker relay cancellation | Not implemented | Active SDK objects are process-local. Run one relay worker for the current release or add sticky routing/durable session coordination before scaling horizontally. |
| Domain-specific reservation tools for the current cafe prompt | Implemented in Svara; Sarvam dashboard mapping pending | Availability, create, lookup, reschedule, and cancel APIs plus tenant-scoped database storage are implemented and tested. They must still be configured as API tools on committed agent version 2. |

## Runtime flow

```text
Customer microphone
  -> Web Audio capture and 16 kHz PCM conversion
  -> authenticated Svara WebSocket relay
  -> official Sarvam Agents SDK
  -> Sarvam ASR -> agent/LLM
  -> optional Sarvam HTTP tool -> Svara API -> tenant-scoped database query
  -> minimal tool result -> Sarvam agent/LLM -> Sarvam TTS
  -> PCM audio through Svara relay -> browser speaker
```

The browser first creates a voice session through the same-origin Next.js BFF. FastAPI verifies
the Clerk session, resolves the application user, locks the matching customer, stores only a hash
of an opaque `conversation_ref`, and returns a short-lived WebSocket relay URL. The encrypted relay
token carries the opaque reference but does not expose it as plaintext.

When the browser connects, FastAPI validates the browser origin, decrypts the token, locks the
database session, verifies the provider/status/expiry/customer/tenant, and changes the session from
`ready` to `active`. It then starts `AsyncSamvaadAgent` with the configured organization, workspace,
agent, committed version, language, greeting, and dynamic variables. Audio, transcript, interrupt,
and completion events are relayed to the custom UI. The API stores a bounded outcome when the relay
ends unless a configured Sarvam on-end tool already wrote the first outcome.

## Values and versioning

Required backend values are:

```dotenv
VOICE_PROVIDER=sarvam
SARVAM_API_KEY=...
SARVAM_ORG_ID=...
SARVAM_WORKSPACE_ID=...
SARVAM_AGENT_ID=...
SARVAM_AGENT_VERSION=2
VOICE_WEBSOCKET_PUBLIC_URL=ws://127.0.0.1:8000/v1/voice/stream
```

Production must use `wss://` on the public API host. The agent version is deliberately pinned to a
committed integer; a draft is not a production target. Changing the draft does not change running
traffic until the new version is committed and the environment pin is deliberately updated.

The official SDK obtains the Sarvam-signed upstream WebSocket using the configured API key and
starts the interaction. Svara does not invent or call an undocumented browser endpoint and does
not expose the signed upstream URL or `X-API-Key` to client JavaScript.

## Dynamic customer context

Svara currently sends these session variables:

- `conversation_ref`: opaque capability used by Svara's tools to resolve the session.
- `preferred_language`: customer/session language.
- `user_name` and `customer_name`: resolved from the authenticated customer's record.
- `customer_plan`: the customer's plan.
- `service_provider_name`, `service_location`, and `business_hours`: resolved from the tenant's
  reservation policy, falling back to the workspace name/current-hours guidance when no policy is
  configured.
- `agent_display_name`, `agent_tone`, and `customer_instructions`: the saved per-customer agent
  configuration.
- `current_date`: the backend's current ISO calendar date for relative-date resolution.

Declare every variable the Sarvam prompt or tool mapping uses in the Sarvam **Variables** screen.
The prompt must treat these values as context, not proof of authorization. Keep large or frequently
changing records out of agent variables; retrieve them with a narrow HTTP tool when needed.

## Database tools

The repository exposes these provider-facing routes:

| Route | Purpose |
| --- | --- |
| `POST /v1/sarvam/hooks/on-start` | Returns bounded customer and per-customer agent context. The direct SDK relay already supplies its essential start context, so this hook is optional for the web path. |
| `POST /v1/sarvam/tools/get-order-status` | Reads one order belonging to the customer bound to the session. |
| `POST /v1/sarvam/tools/check-availability` | Returns up to five valid table slots near a requested local date/time. |
| `POST /v1/sarvam/tools/create-reservation` | Atomically creates a customer-scoped reservation and safely replays exact retries. |
| `POST /v1/sarvam/tools/find-reservation` | Finds a reference or the customer's upcoming confirmed reservations. |
| `POST /v1/sarvam/tools/reschedule-reservation` | Moves a reservation using a fresh slot and optimistic version check. |
| `POST /v1/sarvam/tools/cancel-reservation` | Cancels a reservation using an optimistic version check and safely handles retries. |
| `POST /v1/sarvam/hooks/on-end` | Stores the first bounded outcome and handles retries idempotently. |

These are Svara routes, not Sarvam-defined endpoints. Deploy them on public HTTPS, configure them
as tools/hooks in the Sarvam dashboard, store `SARVAM_TOOL_SECRET` in Sarvam's secret store, and
send it as `X-Voice-Tool-Key`. Map `conversation_ref` from the session variable; never ask the model
to supply tenant or customer IDs.

The reservation routes are implemented, but they are Svara's HTTPS contracts rather than automatic
Sarvam configuration. Follow the exact request-field and sequencing guide in
[Sarvam v2 reservation-tool setup](sarvam-v2-reservation-tools.md). Until all five tools are enabled
on committed agent version 2 and the database migration is applied, the agent must not promise live
booking actions.

## Security and isolation

- Clerk authenticates the human; FastAPI maps the immutable Clerk user ID to one active
  application user.
- The browser may select a language, but never a tenant, customer, agent ID, agent version, provider
  variable, or tool credential.
- `conversation_ref` is random, encrypted in transit to the relay, and stored only as a hash.
- The relay URL is accepted only from configured frontend origins. Remote deployments require TLS
  for both HTTP and WebSocket traffic.
- Sarvam API keys, Clerk secret keys, database credentials, and tool secrets remain backend-only.
- One active session per customer is enforced by the database.
- Reservation reads and writes derive tenant/customer scope only from the bound voice session.
  Mutation retries are idempotent, edits use optimistic versions, and PostgreSQL prevents
  overlapping confirmed bookings for one table. The new reservation tables enable RLS and remove
  Data API access for Supabase `anon` and `authenticated` roles; the server connects directly with
  its backend database role.
- Transcript and outcome storage is bounded, but retention/deletion, at-rest encryption, abuse rate
  limits, monitoring, and database-level tenant controls remain production work.

## What Sarvam handles and what Svara handles

Sarvam handles speech recognition, conversational reasoning, speech synthesis, turn behavior,
selected language/voice configuration, agent instructions, configured knowledge/tools, and its own
interaction analytics.

Svara handles the web product, Clerk authentication, customer onboarding, tenant/customer mapping,
database ownership, per-customer configuration, the browser audio relay, tool authorization,
business APIs, auditing, conversation persistence, and customer-facing history.

## Pricing and operational constraints

- Voice Agent usage and any phone-number/telephony charges are Sarvam account charges. Confirm the
  current dashboard price, rounding, included features, taxes, and concurrency allocation before
  production; do not estimate managed Voice Agent costs from separate model-API prices.
- The configured Svara session lifetime is 1-60 minutes and must not exceed the Sarvam agent's
  committed runtime limit.
- The current relay keeps active SDK sessions in one FastAPI process. Use one worker for the first
  deployment. Horizontal scale needs sticky routing plus shared coordination, or a dedicated relay
  service.
- Web Audio microphone capture requires a secure browser context (`https://`), except loopback local
  development where browsers permit `http://localhost`.
- The base SDK is enough for this headless relay. The `[all]` extra and PortAudio are needed for a
  server/desktop process that directly captures or plays audio hardware, not for browser audio.

## Release checklist

1. Keep agent version 2 committed and pinned for the current test.
2. Declare the variables listed above in the agent version and give safe defaults where appropriate.
3. Run migration `20260909_0003`, provision each tenant's policy/tables, and configure all five API
   tools using [the v2 mapping guide](sarvam-v2-reservation-tools.md).
4. Run FastAPI and Next.js, sign in with a Clerk account linked to an active customer, open `/voice`,
   allow the microphone, and complete a short test conversation.
5. Confirm the session appears in `/conversations` and that no API key or plaintext
   `conversation_ref` appears in browser responses.
6. Exercise book, lookup, reschedule, cancel, unavailable-slot, and duplicate-retry scenarios in
   Sarvam's **Tests** screen before committing a replacement agent version.
7. For staging/production, publish the API over HTTPS/WSS, set exact `FRONTEND_ORIGINS` and
   `VOICE_WEBSOCKET_HOSTS`, rotate development secrets, run migrations, and add monitoring/rate
   limits.
