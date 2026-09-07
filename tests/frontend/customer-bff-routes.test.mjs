import assert from "node:assert/strict";
import { createRequire, registerHooks } from "node:module";
import { dirname, resolve } from "node:path";
import test, { beforeEach } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const require = createRequire(import.meta.url);
const testStateKey = "__svaraCustomerBffRouteTestState";
const mockServerApiSource = `
  export async function getSessionToken() {
    return globalThis.${testStateKey}.token;
  }
  export async function requestBackend(path, init = {}) {
    const state = globalThis.${testStateKey};
    state.calls.push({ path, init });
    return state.upstream(path, init);
  }
`;

const moduleUrls = new Map([
  [
    "@/lib/api-validation",
    pathToFileURL(resolve(repositoryRoot, "src/lib/api-validation.ts")).href,
  ],
  ["@/lib/bff", pathToFileURL(resolve(repositoryRoot, "src/lib/bff.ts")).href],
  [
    "@/lib/retry-after",
    pathToFileURL(resolve(repositoryRoot, "src/lib/retry-after.ts")).href,
  ],
  ["@/lib/server-api", `data:text/javascript,${encodeURIComponent(mockServerApiSource)}`],
  ["next/server", pathToFileURL(require.resolve("next/server.js")).href],
  ["server-only", "data:text/javascript,export{}"],
]);

registerHooks({
  resolve(specifier, context, nextResolve) {
    const url = moduleUrls.get(specifier);
    return url ? { shortCircuit: true, url } : nextResolve(specifier, context);
  },
});

const profileRoute = await import(
  pathToFileURL(resolve(repositoryRoot, "src/app/api/customers/[id]/route.ts")).href
);
const agentRoute = await import(
  pathToFileURL(
    resolve(repositoryRoot, "src/app/api/customers/[id]/agent-configuration/route.ts"),
  ).href
);

const customerId = "b4d8596e-1780-4fd8-8ac8-e62e1c1a11b3";
const differentCustomerId = "c4d8596e-1780-4fd8-8ac8-e62e1c1a11b4";
const applicationOrigin = "https://voice.example";

function customerDetail(id = customerId) {
  return {
    id,
    external_ref: "CUS-1042",
    full_name: "Rahul Mehta",
    initials: "RM",
    preferred_language: "English",
    plan_name: "Growth",
    is_active: true,
    created_at: "2026-08-01T09:30:00.000Z",
    conversation_count: 0,
    resolved_conversation_count: 0,
    last_conversation_at: null,
    email: "rahul@example.com",
    open_order_count: 0,
    profile_revision: 3,
    agent_configuration: {
      display_name: "Asha",
      opening_message: "Hello {first_name}, how can I help today?",
      tone: "professional",
      instructions: "Use only verified account information.",
      revision: 2,
      updated_at: "2026-09-03T10:00:00.000Z",
    },
    recent_audit_events: [],
    recent_conversations: [],
  };
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function routeRequest(path, { body = "{}", contentType = "application/json", origin } = {}) {
  return new Request(`${applicationOrigin}${path}`, {
    method: "PATCH",
    headers: {
      "Content-Type": contentType,
      Origin: origin ?? applicationOrigin,
    },
    body,
  });
}

function context(id = customerId) {
  return { params: Promise.resolve({ id }) };
}

function state() {
  return globalThis[testStateKey];
}

beforeEach(() => {
  process.env.APP_ORIGIN = applicationOrigin;
  globalThis[testStateKey] = {
    token: "server-only-test-token",
    calls: [],
    upstream: () => jsonResponse(customerDetail()),
  };
});

const mutationRoutes = [
  {
    label: "customer profile",
    handler: profileRoute.PATCH,
    path: `/api/customers/${customerId}`,
    upstreamPath: `/v1/customers/${customerId}`,
    validBody: { expected_revision: 2, plan_name: "Scale" },
    conflictDetail:
      "Customer profile was updated by another administrator. Refresh and try again.",
    oversizedBody: JSON.stringify({
      expected_revision: 2,
      full_name: "x".repeat(4 * 1024),
    }),
  },
  {
    label: "agent configuration",
    handler: agentRoute.PATCH,
    path: `/api/customers/${customerId}/agent-configuration`,
    upstreamPath: `/v1/customers/${customerId}/agent-configuration`,
    validBody: { expected_revision: 2, tone: "warm" },
    conflictDetail:
      "Agent configuration was updated by another administrator. Refresh and try again.",
    oversizedBody: JSON.stringify({
      expected_revision: 2,
      instructions: "x".repeat(16 * 1024),
    }),
  },
];

for (const route of mutationRoutes) {
  test(`${route.label} PATCH rejects cross-origin requests before forwarding`, async () => {
    const response = await route.handler(
      routeRequest(route.path, {
        body: JSON.stringify(route.validBody),
        origin: "https://attacker.example",
      }),
      context(),
    );

    assert.equal(response.status, 403);
    assert.deepEqual(await response.json(), {
      detail: "The request origin could not be verified.",
    });
    assert.deepEqual(state().calls, []);
  });

  test(`${route.label} PATCH rejects non-JSON media types before forwarding`, async () => {
    const response = await route.handler(
      routeRequest(route.path, {
        body: JSON.stringify(route.validBody),
        contentType: "text/plain",
      }),
      context(),
    );

    assert.equal(response.status, 415);
    assert.deepEqual(await response.json(), {
      detail: "Content-Type must be application/json.",
    });
    assert.deepEqual(state().calls, []);
  });

  test(`${route.label} PATCH rejects an oversized streamed body before forwarding`, async () => {
    const response = await route.handler(
      routeRequest(route.path, { body: route.oversizedBody }),
      context(),
    );

    assert.equal(response.status, 413);
    assert.deepEqual(await response.json(), { detail: "Request body is too large." });
    assert.deepEqual(state().calls, []);
  });

  test(`${route.label} PATCH rejects an upstream customer-ID mismatch`, async () => {
    state().upstream = () => jsonResponse(customerDetail(differentCustomerId));

    const response = await route.handler(
      routeRequest(route.path, { body: JSON.stringify(route.validBody) }),
      context(),
    );

    assert.equal(response.status, 502);
    assert.deepEqual(await response.json(), {
      detail: "Invalid customer-service response.",
    });
    assert.equal(state().calls.length, 1);
    assert.equal(state().calls[0].path, route.upstreamPath);
  });

  test(`${route.label} PATCH preserves the backend's exact revision conflict`, async () => {
    state().upstream = () => jsonResponse({ detail: route.conflictDetail }, 409);

    const response = await route.handler(
      routeRequest(route.path, { body: JSON.stringify(route.validBody) }),
      context(),
    );

    assert.equal(response.status, 409);
    assert.deepEqual(await response.json(), { detail: route.conflictDetail });
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(state().calls.length, 1);
    assert.equal(state().calls[0].path, route.upstreamPath);
    assert.deepEqual(JSON.parse(state().calls[0].init.body), route.validBody);
  });
}
