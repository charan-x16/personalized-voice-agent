import assert from "node:assert/strict";
import test from "node:test";

import {
  FALLBACK_AGENT_OPENING_MESSAGE,
  parseAgentConfigurationUpdatePayload,
  parseCustomerCreatePayload,
  parseCustomerDetail,
  parseCustomerListResponse,
  parseCustomerListSearchParams,
  parseCustomerUpdatePayload,
  parseMeResponse,
  parseCustomerVoiceToolListResponse,
  parseCustomerVoiceToolUpdatePayload,
  parseVoiceToolCreatePayload,
  parseVoiceToolListResponse,
  parseVoiceToolUpdatePayload,
  renderAgentOpeningTemplate,
} from "../src/lib/api-validation.ts";

const createdAt = "2026-08-01T09:30:00.000Z";
const lastConversationAt = "2026-08-28T12:15:00+00:00";

function customerSummary(overrides = {}) {
  return {
    id: "b4d8596e-1780-4fd8-8ac8-e62e1c1a11b3",
    external_ref: "customer-1042",
    full_name: "Rahul Sharma",
    initials: "RS",
    preferred_language: "Hindi",
    plan_name: "Essential",
    is_active: true,
    created_at: createdAt,
    conversation_count: 7,
    resolved_conversation_count: 5,
    last_conversation_at: lastConversationAt,
    ...overrides,
  };
}

function conversationSummary(overrides = {}) {
  return {
    id: "conversation-1",
    provider: "mock",
    started_at: lastConversationAt,
    ended_at: "2026-08-28T12:18:00.000Z",
    duration_seconds: 180,
    language: "Hindi",
    resolution: "resolved",
    summary: "The customer checked an order status.",
    ...overrides,
  };
}

function agentConfiguration(overrides = {}) {
  return {
    display_name: "Svara Concierge",
    opening_message: "Hello {first_name}, how can I help today?",
    tone: "warm",
    instructions: "Use verified customer context and keep answers concise.",
    revision: 2,
    updated_at: lastConversationAt,
    ...overrides,
  };
}

function customerAccess(overrides = {}) {
  return {
    email: "rahul@example.com",
    status: "accepted",
    is_active: true,
    invited_at: "2026-08-01T09:30:00.000Z",
    expires_at: "2026-08-31T09:30:00.000Z",
    accepted_at: "2026-08-01T10:00:00.000Z",
    ...overrides,
  };
}

function auditEvent(overrides = {}) {
  return {
    id: "audit-event-1",
    action: "customer.profile_updated",
    changed_fields: ["preferred_language"],
    revision: 2,
    actor_display_name: "Ananya Rao",
    created_at: lastConversationAt,
    ...overrides,
  };
}

function customerDetail(overrides = {}) {
  return {
    ...customerSummary(),
    email: "rahul@example.com",
    access: customerAccess(),
    open_order_count: 2,
    profile_revision: 2,
    agent_configuration: agentConfiguration(),
    recent_audit_events: [auditEvent()],
    recent_conversations: [conversationSummary()],
    ...overrides,
  };
}

test("me parser supports tenant admins without customer context", () => {
  const admin = parseMeResponse({
    user_id: "admin-user",
    role: "admin",
    customer_id: null,
    full_name: "Ananya Admin",
    first_name: "Ananya",
    initials: "AA",
    email: "admin@example.com",
    workspace_name: "Acme Support",
    preferred_language: null,
    plan_name: null,
    internal_claim: "must-not-cross-the-bff",
  });

  assert.deepEqual(admin, {
    user_id: "admin-user",
    role: "admin",
    customer_id: null,
    full_name: "Ananya Admin",
    first_name: "Ananya",
    initials: "AA",
    email: "admin@example.com",
    workspace_name: "Acme Support",
    preferred_language: null,
    plan_name: null,
  });
});

test("me parser requires customer context for customer users", () => {
  assert.equal(
    parseMeResponse({
      user_id: "customer-user",
      role: "customer",
      customer_id: null,
      full_name: "Rahul Sharma",
      first_name: "Rahul",
      initials: "RS",
      email: "rahul@example.com",
      workspace_name: "Acme Support",
      preferred_language: null,
      plan_name: null,
    }),
    null,
  );

  assert.equal(
    parseMeResponse({
      user_id: "admin-user",
      role: "admin",
      customer_id: "customer-1",
      full_name: "Ananya Admin",
      first_name: "Ananya",
      initials: "AA",
      email: "admin@example.com",
      workspace_name: "Acme Support",
      preferred_language: "Hindi",
      plan_name: "Essential",
    }),
    null,
  );
});

test("customer list parser validates timestamps and count invariants", () => {
  assert.deepEqual(
    parseCustomerListResponse({
      items: [customerSummary({ private_phone_hash: "secret" })],
      total: 1,
      internal_tenant_id: "must-not-cross-the-bff",
    }),
    {
      items: [customerSummary()],
      total: 1,
    },
  );

  assert.equal(
    parseCustomerListResponse({
      items: [customerSummary({ created_at: "not-a-date" })],
      total: 1,
    }),
    null,
  );
  assert.equal(
    parseCustomerListResponse({
      items: [
        customerSummary({
          conversation_count: 2,
          resolved_conversation_count: 3,
        }),
      ],
      total: 1,
    }),
    null,
  );
});

test("customer detail parser strips upstream extras and validates nested conversations", () => {
  const detail = parseCustomerDetail(customerDetail({
    agent_configuration: agentConfiguration({ provider_agent_id: "private" }),
    recent_audit_events: [auditEvent({ tenant_id: "private" })],
    recent_conversations: [conversationSummary({ provider_session_id: "private" })],
    tenant_id: "private",
  }));

  assert.deepEqual(detail, {
    ...customerSummary(),
    email: "rahul@example.com",
    access: customerAccess(),
    open_order_count: 2,
    profile_revision: 2,
    agent_configuration: agentConfiguration(),
    recent_audit_events: [auditEvent()],
    recent_conversations: [conversationSummary()],
  });

  assert.equal(
    parseCustomerDetail(customerDetail({
      open_order_count: -1,
      recent_conversations: [],
    })),
    null,
  );
  assert.equal(
    parseCustomerDetail(customerDetail({
      recent_conversations: [conversationSummary({ started_at: "yesterday" })],
    })),
    null,
  );
  assert.equal(
    parseCustomerDetail(customerDetail({
      recent_conversations: Array.from({ length: 6 }, () => conversationSummary()),
    })),
    null,
  );
});

test("customer detail parser validates revisions, agent configuration, and audit events", () => {
  for (const detail of [
    customerDetail({ profile_revision: 0 }),
    customerDetail({ profile_revision: Number.MAX_SAFE_INTEGER + 1 }),
    customerDetail({ agent_configuration: agentConfiguration({ revision: 0 }) }),
    customerDetail({ agent_configuration: agentConfiguration({ tone: "casual" }) }),
    customerDetail({ agent_configuration: agentConfiguration({ opening_message: "Hi {customer}" }) }),
    customerDetail({ agent_configuration: agentConfiguration({ opening_message: "Hi {first_name!r}" }) }),
    customerDetail({ agent_configuration: agentConfiguration({ instructions: "x".repeat(2_001) }) }),
    customerDetail({ access: customerAccess({ status: "unknown" }) }),
    customerDetail({ access: customerAccess({ invited_at: "yesterday" }) }),
    customerDetail({ recent_audit_events: [auditEvent({ action: "customer.deleted" })] }),
    customerDetail({ recent_audit_events: [auditEvent({ changed_fields: ["tenant_id"] })] }),
    customerDetail({ recent_audit_events: [auditEvent({ changed_fields: [] })] }),
    customerDetail({ recent_audit_events: [auditEvent({ revision: 0 })] }),
    customerDetail({
      recent_audit_events: [
        auditEvent({
          action: "customer.agent_configuration_updated",
          changed_fields: ["plan_name"],
        }),
      ],
    }),
    customerDetail({
      recent_audit_events: [auditEvent({ changed_fields: ["full_name", "full_name"] })],
    }),
    customerDetail({ recent_audit_events: [auditEvent({ created_at: "today" })] }),
    customerDetail({
      recent_audit_events: Array.from({ length: 11 }, (_, index) =>
        auditEvent({ id: `audit-${index}` }),
      ),
    }),
  ]) {
    assert.equal(parseCustomerDetail(detail), null);
  }

  assert.deepEqual(
    parseCustomerDetail(customerDetail({
      agent_configuration: agentConfiguration({ instructions: "   ", updated_at: null }),
      recent_audit_events: [
        auditEvent({
          id: "audit-config-1",
          action: "customer.agent_configuration_updated",
          changed_fields: ["display_name", "tone"],
        }),
      ],
    }))?.agent_configuration,
    agentConfiguration({ instructions: "", updated_at: null }),
  );
});

test("customer creation parser normalizes its allowlist and safe defaults", () => {
  assert.deepEqual(
    parseCustomerCreatePayload({
      full_name: "  Devika Rao ",
      email: " DEVIKA@EXAMPLE.COM ",
      external_ref: " CUS-DEVIKA ",
      preferred_language: " Hindi ",
      plan_name: " Growth ",
    }),
    {
      full_name: "Devika Rao",
      email: "devika@example.com",
      external_ref: "CUS-DEVIKA",
      preferred_language: "Hindi",
      plan_name: "Growth",
    },
  );
  assert.deepEqual(
    parseCustomerCreatePayload({ full_name: "Devika Rao", email: "devika@example.com" }),
    {
      full_name: "Devika Rao",
      email: "devika@example.com",
      preferred_language: "English",
      plan_name: "Essential",
    },
  );

  for (const payload of [
    {},
    { full_name: "Devika", email: "not-an-email" },
    { full_name: " ", email: "devika@example.com" },
    { full_name: "Devika", email: "devika@example.com", tenant_id: "other" },
    { full_name: "Devika", email: "devika@example.com", external_ref: null },
  ]) {
    assert.equal(parseCustomerCreatePayload(payload), null);
  }
});

test("customer list query accepts only canonical bounded filters", () => {
  assert.deepEqual(
    parseCustomerListSearchParams(
      new URLSearchParams({
        query: "  Rahul  ",
        status: "active",
        limit: "25",
        offset: "50",
      }),
    ),
    { query: "Rahul", status: "active", limit: 25, offset: 50 },
  );
  assert.deepEqual(
    parseCustomerListSearchParams(new URLSearchParams({ query: "   " })),
    {},
  );

  for (const params of [
    new URLSearchParams({ sort: "email" }),
    new URLSearchParams("status=active&status=inactive"),
    new URLSearchParams({ status: "disabled" }),
    new URLSearchParams({ limit: "0" }),
    new URLSearchParams({ limit: "01" }),
    new URLSearchParams({ offset: "10001" }),
    new URLSearchParams({ query: "x".repeat(161) }),
  ]) {
    assert.equal(parseCustomerListSearchParams(params), null);
  }
});

test("customer patch parser trims its allowlist and rejects ambiguous input", () => {
  assert.deepEqual(
    parseCustomerUpdatePayload({
      expected_revision: 3,
      full_name: "  Rahul Sharma  ",
      preferred_language: " Hindi ",
      plan_name: " Premium ",
      is_active: false,
    }),
    {
      expected_revision: 3,
      full_name: "Rahul Sharma",
      preferred_language: "Hindi",
      plan_name: "Premium",
      is_active: false,
    },
  );

  for (const payload of [
    {},
    { expected_revision: 3 },
    { full_name: "Rahul" },
    { expected_revision: 0, full_name: "Rahul" },
    { expected_revision: Number.MAX_SAFE_INTEGER + 1, full_name: "Rahul" },
    { expected_revision: "3", full_name: "Rahul" },
    { expected_revision: null, full_name: "Rahul" },
    { expected_revision: 3, customer_id: "another-customer" },
    { expected_revision: 3, full_name: "Rahul", tenant_id: "another-tenant" },
    { expected_revision: 3, full_name: "   " },
    { expected_revision: 3, preferred_language: "E" },
    { expected_revision: 3, plan_name: null },
    { expected_revision: 3, is_active: "false" },
    { expected_revision: 3, full_name: "x".repeat(161) },
  ]) {
    assert.equal(parseCustomerUpdatePayload(payload), null);
  }
});

test("agent configuration patch parser enforces revision, template, and field allowlists", () => {
  assert.deepEqual(
    parseAgentConfigurationUpdatePayload({
      expected_revision: 4,
      display_name: "  Svara Guide  ",
      opening_message: "  Namaste {first_name}, how may I help?  ",
      tone: "  professional  ",
      instructions: "   ",
    }),
    {
      expected_revision: 4,
      display_name: "Svara Guide",
      opening_message: "Namaste {first_name}, how may I help?",
      tone: "professional",
      instructions: "",
    },
  );

  for (const payload of [
    {},
    { expected_revision: 1 },
    { display_name: "Svara" },
    { expected_revision: 0, display_name: "Svara" },
    { expected_revision: Number.MAX_SAFE_INTEGER + 1, display_name: "Svara" },
    { expected_revision: 1, display_name: null },
    { expected_revision: 1, display_name: "   " },
    { expected_revision: 1, display_name: "x".repeat(81) },
    { expected_revision: 1, opening_message: null },
    { expected_revision: 1, opening_message: "Hello {customer}" },
    { expected_revision: 1, opening_message: "Hello {first_name!r}" },
    { expected_revision: 1, opening_message: "Hello {first_name:}" },
    { expected_revision: 1, opening_message: "Hello {first_name:>10}" },
    { expected_revision: 1, opening_message: "Hello {first_name}, again {first_name}" },
    { expected_revision: 1, opening_message: "Hello {first_name" },
    { expected_revision: 1, opening_message: "Hello first_name}" },
    { expected_revision: 1, tone: "playful" },
    { expected_revision: 1, instructions: null },
    { expected_revision: 1, instructions: "x".repeat(2_001) },
    { expected_revision: 1, agent_id: "provider-secret" },
  ]) {
    assert.equal(parseAgentConfigurationUpdatePayload(payload), null);
  }

  assert.deepEqual(
    parseAgentConfigurationUpdatePayload({
      expected_revision: 7,
      opening_message: "Welcome. How can I help?",
    }),
    { expected_revision: 7, opening_message: "Welcome. How can I help?" },
  );
  assert.deepEqual(
    parseAgentConfigurationUpdatePayload({
      expected_revision: 7,
      opening_message: "Use {{ and }} for literal braces; hello {first_name}.",
    }),
    {
      expected_revision: 7,
      opening_message: "Use {{ and }} for literal braces; hello {first_name}.",
    },
  );
});

test("opening-message preview mirrors the bounded runtime fallback", () => {
  const longFirstName = "R".repeat(160);
  const maximumTemplate = `{first_name}${"x".repeat(488)}`;

  assert.deepEqual(renderAgentOpeningTemplate(maximumTemplate, longFirstName), {
    valid: true,
    rendered: FALLBACK_AGENT_OPENING_MESSAGE,
    usedFallback: true,
  });
  assert.deepEqual(renderAgentOpeningTemplate("Hi {{friend}} and {first_name}.", "Rahul"), {
    valid: true,
    rendered: "Hi {friend} and Rahul.",
    usedFallback: false,
  });
  assert.equal(
    renderAgentOpeningTemplate("Hello {first_name}, again {first_name}.", "Rahul").valid,
    false,
  );
});

test("voice tool parsers enforce the approved capability and revision contracts", () => {
  const tool = {
    id: "00000000-0000-4000-8000-000000000041",
    tool_key: "get_order_status",
    display_name: "Order status",
    description: "Look up an order for the active customer.",
    capability: "order_status",
    is_enabled: true,
    revision: 2,
    assigned_customer_count: 4,
    created_at: createdAt,
    updated_at: lastConversationAt,
  };
  const event = {
    id: "00000000-0000-4000-8000-000000000051",
    action: "customer_voice_tool.updated",
    tool_id: tool.id,
    tool_key: tool.tool_key,
    tool_display_name: tool.display_name,
    customer_id: "00000000-0000-4000-8000-000000000002",
    customer_reference: "CUS-1042",
    changed_fields: ["is_enabled"],
    revision: 3,
    actor_display_name: "Ananya Rao",
    created_at: lastConversationAt,
  };
  assert.deepEqual(parseVoiceToolListResponse({ items: [tool], total: 1, recent_events: [event] }), {
    items: [tool],
    total: 1,
    recent_events: [event],
  });
  assert.equal(
    parseVoiceToolListResponse({
      items: [{ ...tool, capability: "fetch_any_url" }],
      total: 1,
      recent_events: [],
    }),
    null,
  );
  assert.equal(
    parseVoiceToolListResponse({
      items: [tool],
      total: 1,
      recent_events: [{ ...event, customer_id: null }],
    }),
    null,
  );
  assert.deepEqual(
    parseCustomerVoiceToolListResponse({
      customer_id: "00000000-0000-4000-8000-000000000002",
      items: [
        {
          tool,
          assigned: true,
          is_enabled: true,
          revision: 3,
          updated_at: lastConversationAt,
        },
      ],
    }),
    {
      customer_id: "00000000-0000-4000-8000-000000000002",
      items: [
        {
          tool,
          assigned: true,
          is_enabled: true,
          revision: 3,
          updated_at: lastConversationAt,
        },
      ],
    },
  );
  assert.equal(
    parseCustomerVoiceToolListResponse({
      customer_id: "00000000-0000-4000-8000-000000000002",
      items: [{ tool, assigned: false, is_enabled: true, revision: null, updated_at: null }],
    }),
    null,
  );
  assert.deepEqual(
    parseVoiceToolCreatePayload({
      tool_key: "  find_booking  ",
      display_name: "  Find booking  ",
      description: "  Retrieve an upcoming reservation.  ",
      capability: "reservation_lookup",
    }),
    {
      tool_key: "find_booking",
      display_name: "Find booking",
      description: "Retrieve an upcoming reservation.",
      capability: "reservation_lookup",
      is_enabled: true,
    },
  );
  assert.equal(
    parseVoiceToolCreatePayload({
      tool_key: "external_url",
      display_name: "External URL",
      description: "Unsafe arbitrary request",
      capability: "http_request",
    }),
    null,
  );
  assert.deepEqual(parseVoiceToolUpdatePayload({ expected_revision: 2, is_enabled: false }), {
    expected_revision: 2,
    is_enabled: false,
  });
  assert.equal(parseVoiceToolUpdatePayload({ expected_revision: 2 }), null);
  assert.deepEqual(
    parseCustomerVoiceToolUpdatePayload({ is_enabled: true, expected_revision: null }),
    { is_enabled: true, expected_revision: null },
  );
});
