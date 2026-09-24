import assert from "node:assert/strict";
import { createRequire, registerHooks } from "node:module";
import { dirname, resolve } from "node:path";
import test, { beforeEach } from "node:test";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
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
    pathToFileURL(resolve(webRoot, "src/lib/api-validation.ts")).href,
  ],
  ["@/lib/bff", pathToFileURL(resolve(webRoot, "src/lib/bff.ts")).href],
  [
    "@/lib/retry-after",
    pathToFileURL(resolve(webRoot, "src/lib/retry-after.ts")).href,
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
  pathToFileURL(resolve(webRoot, "src/app/api/customers/[id]/route.ts")).href
);
const customersRoute = await import(
  pathToFileURL(resolve(webRoot, "src/app/api/customers/route.ts")).href
);
const agentRoute = await import(
  pathToFileURL(
    resolve(webRoot, "src/app/api/customers/[id]/agent-configuration/route.ts"),
  ).href
);
const previewRoute = await import(
  pathToFileURL(
    resolve(webRoot, "src/app/api/customers/[id]/voice-preview-sessions/route.ts"),
  ).href
);
const accessRoute = await import(
  pathToFileURL(
    resolve(webRoot, "src/app/api/customers/[id]/access/[action]/route.ts"),
  ).href
);
const toolsRoute = await import(
  pathToFileURL(resolve(webRoot, "src/app/api/tools/route.ts")).href
);
const toolRoute = await import(
  pathToFileURL(resolve(webRoot, "src/app/api/tools/[id]/route.ts")).href
);
const customerToolRoute = await import(
  pathToFileURL(
    resolve(
      webRoot,
      "src/app/api/tools/customer-assignments/[customerId]/[toolId]/route.ts",
    ),
  ).href
);

const customerId = "b4d8596e-1780-4fd8-8ac8-e62e1c1a11b3";
const differentCustomerId = "c4d8596e-1780-4fd8-8ac8-e62e1c1a11b4";
const toolId = "00000000-0000-4000-8000-000000000041";
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
    access: {
      email: "rahul@example.com",
      status: "accepted",
      is_active: true,
      invited_at: "2026-08-01T09:30:00.000Z",
      expires_at: "2026-08-31T09:30:00.000Z",
      accepted_at: "2026-08-01T10:00:00.000Z",
    },
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

function routeRequest(
  path,
  { body = "{}", contentType = "application/json", origin, method = "PATCH" } = {},
) {
  return new Request(`${applicationOrigin}${path}`, {
    method,
    headers: {
      "Content-Type": contentType,
      Origin: origin ?? applicationOrigin,
    },
    body,
  });
}

function voiceSessionResponse() {
  const expiresAt = new Date(Date.now() + 5 * 60_000).toISOString();
  return {
    session_id: "preview-session-1",
    provider: "mock",
    status: "ready",
    language: "Marathi",
    expires_at: expiresAt,
    connection: {
      transport: "mock",
      websocket_url: null,
      expires_at: expiresAt,
    },
  };
}

function voiceTool(overrides = {}) {
  return {
    id: toolId,
    tool_key: "get_order_status",
    display_name: "Order status",
    description: "Look up an order for the active customer.",
    capability: "order_status",
    is_enabled: true,
    revision: 1,
    assigned_customer_count: 4,
    created_at: "2026-08-01T09:30:00.000Z",
    updated_at: "2026-08-01T09:30:00.000Z",
    ...overrides,
  };
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

test("tool BFF mutations reject cross-origin requests before forwarding", async () => {
  const response = await toolsRoute.POST(
    routeRequest("/api/tools", {
      method: "POST",
      origin: "https://attacker.example",
      body: JSON.stringify({
        tool_key: "get_order_status",
        display_name: "Order status",
        description: "Scoped order lookup",
        capability: "order_status",
      }),
    }),
  );
  assert.equal(response.status, 403);
  assert.equal(state().calls.length, 0);
});

test("tool BFF forwards only validated catalog and assignment updates", async () => {
  state().upstream = (path, init) => {
    if (path === `/v1/tools/${toolId}`) {
      assert.equal(init.method, "PATCH");
      assert.deepEqual(JSON.parse(init.body), { expected_revision: 1, is_enabled: false });
      return jsonResponse(voiceTool({ is_enabled: false, revision: 2 }));
    }
    assert.equal(path, `/v1/tools/customer-assignments/${customerId}/${toolId}`);
    assert.equal(init.method, "PATCH");
    assert.deepEqual(JSON.parse(init.body), { is_enabled: true, expected_revision: null });
    return jsonResponse({
      tool: voiceTool({ assigned_customer_count: 5 }),
      assigned: true,
      is_enabled: true,
      revision: 1,
      updated_at: "2026-08-01T09:30:00.000Z",
    });
  };

  const updated = await toolRoute.PATCH(
    routeRequest(`/api/tools/${toolId}`, {
      body: JSON.stringify({ expected_revision: 1, is_enabled: false }),
    }),
    { params: Promise.resolve({ id: toolId }) },
  );
  assert.equal(updated.status, 200);

  const assigned = await customerToolRoute.PATCH(
    routeRequest(`/api/tools/customer-assignments/${customerId}/${toolId}`, {
      body: JSON.stringify({ is_enabled: true, expected_revision: null }),
    }),
    { params: Promise.resolve({ customerId, toolId }) },
  );
  assert.equal(assigned.status, 200);
  assert.equal(state().calls.length, 2);
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

test("admin preview POST forwards only language to the customer-scoped backend route", async () => {
  const upstreamSession = voiceSessionResponse();
  state().upstream = () => jsonResponse(upstreamSession, 201);
  const path = `/api/customers/${customerId}/voice-preview-sessions`;

  const response = await previewRoute.POST(
    routeRequest(path, {
      method: "POST",
      body: JSON.stringify({ language: "Marathi" }),
    }),
    context(),
  );

  assert.equal(response.status, 201);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.deepEqual(await response.json(), upstreamSession);
  assert.equal(state().calls.length, 1);
  assert.equal(
    state().calls[0].path,
    `/v1/voice/customers/${customerId}/preview-sessions`,
  );
  assert.equal(state().calls[0].init.method, "POST");
  assert.equal(state().calls[0].init.token, "server-only-test-token");
  assert.deepEqual(JSON.parse(state().calls[0].init.body), { language: "Marathi" });
});

test("admin preview POST rejects cross-origin and identity-bearing requests", async () => {
  const path = `/api/customers/${customerId}/voice-preview-sessions`;
  const crossOrigin = await previewRoute.POST(
    routeRequest(path, {
      method: "POST",
      origin: "https://attacker.example",
    }),
    context(),
  );
  const identityBearing = await previewRoute.POST(
    routeRequest(path, {
      method: "POST",
      body: JSON.stringify({ customer_id: differentCustomerId }),
    }),
    context(),
  );

  assert.equal(crossOrigin.status, 403);
  assert.equal(identityBearing.status, 400);
  assert.deepEqual(await identityBearing.json(), {
    detail: "Only language may be supplied.",
  });
  assert.deepEqual(state().calls, []);
});

test("admin preview POST validates the route ID and authentication before forwarding", async () => {
  const path = "/api/customers/bad%20id/voice-preview-sessions";
  const invalidId = await previewRoute.POST(
    routeRequest(path, { method: "POST" }),
    context("bad id"),
  );
  state().token = null;
  const unauthenticated = await previewRoute.POST(
    routeRequest(`/api/customers/${customerId}/voice-preview-sessions`, { method: "POST" }),
    context(),
  );

  assert.equal(invalidId.status, 400);
  assert.equal(unauthenticated.status, 401);
  assert.deepEqual(state().calls, []);
});

test("customer onboarding POST validates, normalizes, and forwards the allowlist", async () => {
  state().upstream = () => jsonResponse(customerDetail(), 201);
  const response = await customersRoute.POST(
    routeRequest("/api/customers", {
      method: "POST",
      body: JSON.stringify({
        full_name: "  Rahul Mehta ",
        email: " RAHUL@EXAMPLE.COM ",
        preferred_language: " English ",
        plan_name: " Growth ",
      }),
    }),
  );

  assert.equal(response.status, 201);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.equal(state().calls.length, 1);
  assert.equal(state().calls[0].path, "/v1/customers");
  assert.deepEqual(JSON.parse(state().calls[0].init.body), {
    full_name: "Rahul Mehta",
    email: "rahul@example.com",
    preferred_language: "English",
    plan_name: "Growth",
  });
});

test("customer onboarding POST rejects cross-origin and identity-bearing input", async () => {
  const crossOrigin = await customersRoute.POST(
    routeRequest("/api/customers", {
      method: "POST",
      origin: "https://attacker.example",
      body: JSON.stringify({ full_name: "Rahul", email: "rahul@example.com" }),
    }),
  );
  const unknownField = await customersRoute.POST(
    routeRequest("/api/customers", {
      method: "POST",
      body: JSON.stringify({
        full_name: "Rahul",
        email: "rahul@example.com",
        tenant_id: "another-tenant",
      }),
    }),
  );

  assert.equal(crossOrigin.status, 403);
  assert.equal(unknownField.status, 400);
  assert.deepEqual(state().calls, []);
});

test("customer access POST forwards only an allowlisted route action", async () => {
  state().upstream = () => jsonResponse(customerDetail());
  const request = routeRequest(
    `/api/customers/${customerId}/access/invitation`,
    { method: "POST" },
  );
  const response = await accessRoute.POST(request, {
    params: Promise.resolve({ id: customerId, action: "invitation" }),
  });

  assert.equal(response.status, 200);
  assert.equal(state().calls.length, 1);
  assert.equal(
    state().calls[0].path,
    `/v1/customers/${customerId}/access/invitation`,
  );
  assert.equal(state().calls[0].init.method, "POST");

  state().calls = [];
  const rejected = await accessRoute.POST(request, {
    params: Promise.resolve({ id: customerId, action: "delete" }),
  });
  assert.equal(rejected.status, 400);
  assert.deepEqual(state().calls, []);
});
