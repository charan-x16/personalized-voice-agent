import type {
  AgentConfiguration,
  AgentConfigurationAuditField,
  AgentConfigurationUpdateRequest,
  AgentTone,
  CancelVoiceSessionResponse,
  ConversationDetailResponse,
  ConversationListResponse,
  ConversationSummary,
  CustomerAuditAction,
  CustomerAuditEvent,
  CustomerAccess,
  CustomerAccessAuditField,
  CustomerAccessStatus,
  CustomerCreateRequest,
  CustomerDetail,
  CustomerListQuery,
  CustomerListResponse,
  CustomerProfileAuditField,
  CustomerStatusFilter,
  CustomerSummary,
  CustomerUpdateRequest,
  MeResponse,
  TranscriptTurn,
  VoiceSessionResponse,
  VoiceSessionCancelStatus,
  CustomerVoiceTool,
  CustomerVoiceToolListResponse,
  CustomerVoiceToolUpdateRequest,
  VoiceToolAdminAction,
  VoiceToolAdminEvent,
  VoiceToolCapability,
  VoiceToolCreateRequest,
  VoiceToolDefinition,
  VoiceToolListResponse,
  VoiceToolUpdateRequest,
} from "@/lib/api-types";

type UnknownRecord = Record<string, unknown>;

function asRecord(value: unknown): UnknownRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}

function nullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function nullableNumber(value: unknown): value is number | null {
  return value === null || (typeof value === "number" && Number.isFinite(value));
}

function trimmedString(value: unknown, minLength: number, maxLength: number): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length >= minLength && trimmed.length <= maxLength ? trimmed : null;
}

function trimmedStringAllowEmpty(value: unknown, maxLength: number): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  return trimmed.length <= maxLength ? trimmed : null;
}

function validTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length > 0 &&
    value.length <= 80 &&
    Number.isFinite(Date.parse(value))
  );
}

function nonNegativeInteger(value: unknown, maximum = Number.MAX_SAFE_INTEGER): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0 &&
    value <= maximum
  );
}

function positiveInteger(value: unknown): value is number {
  return nonNegativeInteger(value) && value >= 1;
}

const SAFE_CUSTOMER_ID = /^[a-zA-Z0-9_-]{1,64}$/;
const SAFE_AUDIT_EVENT_ID = /^[a-zA-Z0-9_-]{1,64}$/;
const AGENT_TONES: ReadonlySet<AgentTone> = new Set([
  "warm",
  "professional",
  "concise",
]);
const PROFILE_AUDIT_FIELDS: ReadonlySet<CustomerProfileAuditField> = new Set([
  "full_name",
  "preferred_language",
  "plan_name",
  "is_active",
]);
const AGENT_CONFIGURATION_AUDIT_FIELDS: ReadonlySet<AgentConfigurationAuditField> =
  new Set(["display_name", "opening_message", "tone", "instructions"]);
const ACCESS_AUDIT_FIELDS: ReadonlySet<CustomerAccessAuditField> = new Set([
  "access_status",
]);
const CUSTOMER_AUDIT_ACTIONS: ReadonlySet<CustomerAuditAction> = new Set([
  "customer.profile_updated",
  "customer.agent_configuration_updated",
  "customer.created",
  "customer.access_invitation_sent",
  "customer.access_invitation_failed",
  "customer.access_revoked",
  "customer.access_restored",
]);
const CUSTOMER_ACCESS_STATUSES: ReadonlySet<CustomerAccessStatus> = new Set([
  "not_invited",
  "queued",
  "pending",
  "accepted",
  "revoked",
  "expired",
  "failed",
]);
const VOICE_TOOL_CAPABILITIES: ReadonlySet<VoiceToolCapability> = new Set([
  "customer_profile",
  "order_status",
  "reservation_availability",
  "reservation_lookup",
  "reservation_create",
  "reservation_reschedule",
  "reservation_cancel",
]);
const SAFE_TOOL_KEY = /^[a-z][a-z0-9_]{2,79}$/;

const FIRST_NAME_TEMPLATE_FIELD = "{first_name}";
export const MAX_RUNTIME_OPENING_MESSAGE_LENGTH = 500;
export const FALLBACK_AGENT_OPENING_MESSAGE = "Hello, how can I help you today?";

export type AgentOpeningTemplateResult =
  | { valid: false; rendered: ""; usedFallback: false }
  | { valid: true; rendered: string; usedFallback: boolean };

export function renderAgentOpeningTemplate(
  template: string,
  firstName: string,
): AgentOpeningTemplateResult {
  let rendered = "";
  let firstNameFieldCount = 0;

  for (let index = 0; index < template.length; ) {
    const character = template[index];
    if (character === "{") {
      if (template[index + 1] === "{") {
        rendered += "{";
        index += 2;
        continue;
      }
      if (!template.startsWith(FIRST_NAME_TEMPLATE_FIELD, index)) {
        return { valid: false, rendered: "", usedFallback: false };
      }
      firstNameFieldCount += 1;
      if (firstNameFieldCount > 1) {
        return { valid: false, rendered: "", usedFallback: false };
      }
      rendered += firstName;
      index += FIRST_NAME_TEMPLATE_FIELD.length;
      continue;
    }
    if (character === "}") {
      if (template[index + 1] !== "}") {
        return { valid: false, rendered: "", usedFallback: false };
      }
      rendered += "}";
      index += 2;
      continue;
    }
    rendered += character;
    index += 1;
  }

  if (rendered.length > MAX_RUNTIME_OPENING_MESSAGE_LENGTH) {
    return {
      valid: true,
      rendered: FALLBACK_AGENT_OPENING_MESSAGE,
      usedFallback: true,
    };
  }
  return { valid: true, rendered, usedFallback: false };
}

function isSupportedAgentOpeningTemplate(template: string): boolean {
  return renderAgentOpeningTemplate(template, "").valid;
}
export function parseMeResponse(value: unknown): MeResponse | null {
  const item = asRecord(value);
  if (!item) return null;

  const userId = trimmedString(item.user_id, 1, 64);
  const customerId =
    item.customer_id === null ? null : trimmedString(item.customer_id, 1, 64);
  const fullName = trimmedString(item.full_name, 1, 160);
  const firstName = trimmedString(item.first_name, 1, 160);
  const initials = trimmedString(item.initials, 1, 8);
  const email = trimmedString(item.email, 3, 254);
  const workspaceName = trimmedString(item.workspace_name, 1, 160);
  const preferredLanguage =
    item.preferred_language === null
      ? null
      : trimmedString(item.preferred_language, 2, 40);
  const planName =
    item.plan_name === null ? null : trimmedString(item.plan_name, 1, 80);
  const agentName = item.agent_name == null ? null : trimmedString(item.agent_name, 1, 80);
  const openingMessage = item.agent_opening_message == null ? null : trimmedString(item.agent_opening_message, 1, 500);
  if ((item.agent_name != null && !agentName) ||
      (item.agent_opening_message != null && !openingMessage) ||
      (item.voice_mode !== undefined && item.voice_mode !== "mock" && item.voice_mode !== "sarvam")) return null;

  if (
    (item.role !== "customer" && item.role !== "admin") ||
    !userId ||
    (item.customer_id !== null && !customerId) ||
    !fullName ||
    !firstName ||
    !initials ||
    !email ||
    !workspaceName ||
    (item.preferred_language !== null && !preferredLanguage) ||
    (item.plan_name !== null && !planName) ||
    (item.role === "customer" && (!customerId || !preferredLanguage || !planName)) ||
    (item.role === "admin" &&
      (customerId !== null || preferredLanguage !== null || planName !== null))
  ) {
    return null;
  }

  return {
    user_id: userId,
    role: item.role,
    customer_id: customerId,
    full_name: fullName,
    first_name: firstName,
    initials,
    email,
    workspace_name: workspaceName,
    preferred_language: preferredLanguage,
    plan_name: planName,
    ...(item.agent_name !== undefined ? { agent_name: agentName } : {}),
    ...(item.agent_opening_message !== undefined ? { agent_opening_message: openingMessage } : {}),
    ...(item.voice_mode !== undefined ? { voice_mode: item.voice_mode as "mock" | "sarvam" } : {}),
  };
}

function parseConversationSummary(value: unknown): ConversationSummary | null {
  const item = asRecord(value);
  const id = trimmedString(item?.id, 1, 64);
  const provider = trimmedString(item?.provider, 1, 40);
  const language = trimmedString(item?.language, 1, 40);
  if (
    !item ||
    !id ||
    !provider ||
    !validTimestamp(item.started_at) ||
    (item.ended_at !== null && !validTimestamp(item.ended_at)) ||
    !nullableNumber(item.duration_seconds) ||
    (item.duration_seconds !== null &&
      (!nonNegativeInteger(item.duration_seconds, 86_400))) ||
    !language ||
    !nullableString(item.resolution) ||
    (typeof item.resolution === "string" && item.resolution.length > 80) ||
    !nullableString(item.summary) ||
    (typeof item.summary === "string" && item.summary.length > 4_000)
  ) {
    return null;
  }

  return {
    id,
    provider,
    started_at: item.started_at,
    ended_at: item.ended_at,
    duration_seconds: item.duration_seconds,
    language,
    resolution: item.resolution,
    summary: item.summary,
  };
}

function parseTranscriptTurn(value: unknown): TranscriptTurn | null {
  const item = asRecord(value);
  if (
    !item ||
    (item.speaker !== "agent" && item.speaker !== "customer" && item.speaker !== "tool") ||
    typeof item.text !== "string" ||
    (item.timestamp !== undefined && !nullableString(item.timestamp))
  ) {
    return null;
  }

  return {
    speaker: item.speaker,
    text: item.text,
    ...(item.timestamp !== undefined ? { timestamp: item.timestamp as string | null } : {}),
  };
}

export function parseConversationListResponse(
  value: unknown,
): ConversationListResponse | null {
  const payload = asRecord(value);
  if (
    !payload ||
    !Array.isArray(payload.items) ||
    typeof payload.total !== "number" ||
    !Number.isInteger(payload.total) ||
    payload.total < 0
  ) {
    return null;
  }

  const items = payload.items.map(parseConversationSummary);
  if (items.some((item) => item === null)) return null;

  return {
    items: items as ConversationSummary[],
    total: payload.total,
  };
}

function parseCustomerSummary(value: unknown): CustomerSummary | null {
  const item = asRecord(value);
  if (!item) return null;

  const id = trimmedString(item.id, 1, 64);
  const externalRef = trimmedString(item.external_ref, 1, 120);
  const fullName = trimmedString(item.full_name, 1, 160);
  const initials = trimmedString(item.initials, 1, 8);
  const preferredLanguage = trimmedString(item.preferred_language, 2, 40);
  const planName = trimmedString(item.plan_name, 1, 80);
  if (
    !id ||
    !SAFE_CUSTOMER_ID.test(id) ||
    !externalRef ||
    !fullName ||
    !initials ||
    !preferredLanguage ||
    !planName ||
    typeof item.is_active !== "boolean" ||
    !validTimestamp(item.created_at) ||
    !nonNegativeInteger(item.conversation_count) ||
    !nonNegativeInteger(item.resolved_conversation_count) ||
    item.resolved_conversation_count > item.conversation_count ||
    (item.last_conversation_at !== null && !validTimestamp(item.last_conversation_at))
  ) {
    return null;
  }

  return {
    id,
    external_ref: externalRef,
    full_name: fullName,
    initials,
    preferred_language: preferredLanguage,
    plan_name: planName,
    is_active: item.is_active,
    created_at: item.created_at,
    conversation_count: item.conversation_count,
    resolved_conversation_count: item.resolved_conversation_count,
    last_conversation_at: item.last_conversation_at,
  };
}

export function parseCustomerListResponse(value: unknown): CustomerListResponse | null {
  const payload = asRecord(value);
  if (
    !payload ||
    !Array.isArray(payload.items) ||
    payload.items.length > 100 ||
    !nonNegativeInteger(payload.total) ||
    payload.total < payload.items.length
  ) {
    return null;
  }

  const items = payload.items.map(parseCustomerSummary);
  if (items.some((item) => item === null)) return null;

  return {
    items: items as CustomerSummary[],
    total: payload.total,
  };
}

function parseVoiceToolDefinition(value: unknown): VoiceToolDefinition | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).length !== 10) return null;
  const id = trimmedString(payload.id, 1, 64);
  const toolKey = trimmedString(payload.tool_key, 3, 80);
  const displayName = trimmedString(payload.display_name, 1, 80);
  const description = trimmedString(payload.description, 1, 500);
  if (
    !id ||
    !SAFE_CUSTOMER_ID.test(id) ||
    !toolKey ||
    !SAFE_TOOL_KEY.test(toolKey) ||
    !displayName ||
    !description ||
    typeof payload.capability !== "string" ||
    !VOICE_TOOL_CAPABILITIES.has(payload.capability as VoiceToolCapability) ||
    typeof payload.is_enabled !== "boolean" ||
    !positiveInteger(payload.revision) ||
    !nonNegativeInteger(payload.assigned_customer_count) ||
    !validTimestamp(payload.created_at) ||
    !validTimestamp(payload.updated_at)
  ) {
    return null;
  }
  return {
    id,
    tool_key: toolKey,
    display_name: displayName,
    description,
    capability: payload.capability as VoiceToolCapability,
    is_enabled: payload.is_enabled,
    revision: payload.revision,
    assigned_customer_count: payload.assigned_customer_count,
    created_at: payload.created_at,
    updated_at: payload.updated_at,
  };
}

export function parseVoiceToolListResponse(value: unknown): VoiceToolListResponse | null {
  const payload = asRecord(value);
  if (
    !payload ||
    Object.keys(payload).length !== 3 ||
    !Array.isArray(payload.items) ||
    !Array.isArray(payload.recent_events) ||
    payload.recent_events.length > 20
  ) {
    return null;
  }
  if (!nonNegativeInteger(payload.total) || payload.items.length !== payload.total) return null;
  const items = payload.items.map(parseVoiceToolDefinition);
  const recentEvents = payload.recent_events.map(parseVoiceToolAdminEvent);
  if (items.some((item) => item === null) || recentEvents.some((event) => event === null)) {
    return null;
  }
  return {
    items: items as VoiceToolDefinition[],
    total: payload.total,
    recent_events: recentEvents as VoiceToolAdminEvent[],
  };
}

const VOICE_TOOL_ADMIN_ACTIONS: ReadonlySet<VoiceToolAdminAction> = new Set([
  "voice_tool.created",
  "voice_tool.updated",
  "customer_voice_tool.updated",
]);

function parseVoiceToolAdminEvent(value: unknown): VoiceToolAdminEvent | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).length !== 11) return null;
  const id = trimmedString(payload.id, 1, 64);
  const toolId = trimmedString(payload.tool_id, 1, 64);
  const toolKey = trimmedString(payload.tool_key, 3, 80);
  const toolDisplayName = trimmedString(payload.tool_display_name, 1, 80);
  const actorDisplayName = trimmedString(payload.actor_display_name, 1, 160);
  const customerId =
    payload.customer_id === null ? null : trimmedString(payload.customer_id, 1, 64);
  const customerReference =
    payload.customer_reference === null
      ? null
      : trimmedString(payload.customer_reference, 1, 120);
  const action = payload.action as VoiceToolAdminAction;
  if (
    !id ||
    !SAFE_CUSTOMER_ID.test(id) ||
    !toolId ||
    !SAFE_CUSTOMER_ID.test(toolId) ||
    !toolKey ||
    !SAFE_TOOL_KEY.test(toolKey) ||
    !toolDisplayName ||
    !actorDisplayName ||
    !VOICE_TOOL_ADMIN_ACTIONS.has(action) ||
    !Array.isArray(payload.changed_fields) ||
    payload.changed_fields.length > 10 ||
    payload.changed_fields.some(
      (field) => typeof field !== "string" || field.length < 1 || field.length > 80,
    ) ||
    !positiveInteger(payload.revision) ||
    !validTimestamp(payload.created_at) ||
    (customerId !== null && !SAFE_CUSTOMER_ID.test(customerId)) ||
    ((customerId === null) !== (customerReference === null)) ||
    (action === "customer_voice_tool.updated" && customerId === null) ||
    (action !== "customer_voice_tool.updated" && customerId !== null)
  ) {
    return null;
  }
  return {
    id,
    action,
    tool_id: toolId,
    tool_key: toolKey,
    tool_display_name: toolDisplayName,
    customer_id: customerId,
    customer_reference: customerReference,
    changed_fields: payload.changed_fields as string[],
    revision: payload.revision,
    actor_display_name: actorDisplayName,
    created_at: payload.created_at,
  };
}

export function parseVoiceToolDefinitionResponse(value: unknown): VoiceToolDefinition | null {
  return parseVoiceToolDefinition(value);
}

function parseCustomerVoiceTool(value: unknown): CustomerVoiceTool | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).length !== 5) return null;
  const tool = parseVoiceToolDefinition(payload.tool);
  if (
    !tool ||
    typeof payload.assigned !== "boolean" ||
    typeof payload.is_enabled !== "boolean" ||
    !(payload.revision === null || positiveInteger(payload.revision)) ||
    !(payload.updated_at === null || validTimestamp(payload.updated_at)) ||
    (payload.assigned !== (payload.revision !== null)) ||
    (!payload.assigned && payload.is_enabled)
  ) {
    return null;
  }
  return {
    tool,
    assigned: payload.assigned,
    is_enabled: payload.is_enabled,
    revision: payload.revision,
    updated_at: payload.updated_at,
  };
}

export function parseCustomerVoiceToolResponse(value: unknown): CustomerVoiceTool | null {
  return parseCustomerVoiceTool(value);
}

export function parseCustomerVoiceToolListResponse(
  value: unknown,
): CustomerVoiceToolListResponse | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).length !== 2 || !Array.isArray(payload.items)) return null;
  const customerId = trimmedString(payload.customer_id, 1, 64);
  if (!customerId || !SAFE_CUSTOMER_ID.test(customerId)) return null;
  const items = payload.items.map(parseCustomerVoiceTool);
  if (items.some((item) => item === null)) return null;
  return { customer_id: customerId, items: items as CustomerVoiceTool[] };
}

export function parseVoiceToolCreatePayload(value: unknown): VoiceToolCreateRequest | null {
  const payload = asRecord(value);
  if (!payload || ![4, 5].includes(Object.keys(payload).length)) return null;
  const allowed = new Set(["tool_key", "display_name", "description", "capability", "is_enabled"]);
  if (Object.keys(payload).some((key) => !allowed.has(key))) return null;
  const toolKey = trimmedString(payload.tool_key, 3, 80);
  const displayName = trimmedString(payload.display_name, 1, 80);
  const description = trimmedString(payload.description, 1, 500);
  if (
    !toolKey ||
    !SAFE_TOOL_KEY.test(toolKey) ||
    !displayName ||
    !description ||
    typeof payload.capability !== "string" ||
    !VOICE_TOOL_CAPABILITIES.has(payload.capability as VoiceToolCapability) ||
    !(payload.is_enabled === undefined || typeof payload.is_enabled === "boolean")
  ) return null;
  return {
    tool_key: toolKey,
    display_name: displayName,
    description,
    capability: payload.capability as VoiceToolCapability,
    is_enabled: payload.is_enabled ?? true,
  };
}

export function parseVoiceToolUpdatePayload(value: unknown): VoiceToolUpdateRequest | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).length < 2 || Object.keys(payload).length > 4) return null;
  const allowed = new Set(["expected_revision", "display_name", "description", "is_enabled"]);
  if (Object.keys(payload).some((key) => !allowed.has(key)) || !positiveInteger(payload.expected_revision)) return null;
  const result: VoiceToolUpdateRequest = { expected_revision: payload.expected_revision };
  if ("display_name" in payload) {
    const value = trimmedString(payload.display_name, 1, 80);
    if (!value) return null;
    result.display_name = value;
  }
  if ("description" in payload) {
    const value = trimmedString(payload.description, 1, 500);
    if (!value) return null;
    result.description = value;
  }
  if ("is_enabled" in payload) {
    if (typeof payload.is_enabled !== "boolean") return null;
    result.is_enabled = payload.is_enabled;
  }
  return result;
}

export function parseCustomerVoiceToolUpdatePayload(
  value: unknown,
): CustomerVoiceToolUpdateRequest | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).length !== 2) return null;
  if (typeof payload.is_enabled !== "boolean") return null;
  if (!(payload.expected_revision === null || positiveInteger(payload.expected_revision))) return null;
  return {
    is_enabled: payload.is_enabled,
    expected_revision: payload.expected_revision,
  };
}

function parseAgentConfiguration(value: unknown): AgentConfiguration | null {
  const item = asRecord(value);
  if (!item) return null;

  const displayName = trimmedString(item.display_name, 1, 80);
  const openingMessage = trimmedString(item.opening_message, 1, 500);
  const instructions = trimmedStringAllowEmpty(item.instructions, 2_000);
  const updatedAt = item.updated_at;
  if (
    !displayName ||
    !openingMessage ||
    !isSupportedAgentOpeningTemplate(openingMessage) ||
    !AGENT_TONES.has(item.tone as AgentTone) ||
    instructions === null ||
    !positiveInteger(item.revision) ||
    (updatedAt !== null && !validTimestamp(updatedAt))
  ) {
    return null;
  }

  return {
    display_name: displayName,
    opening_message: openingMessage,
    tone: item.tone as AgentTone,
    instructions,
    revision: item.revision,
    updated_at: updatedAt,
  };
}

function parseCustomerAccess(value: unknown): CustomerAccess | null {
  const item = asRecord(value);
  if (!item) return null;
  const email = trimmedString(item.email, 3, 254);
  if (
    !email ||
    !CUSTOMER_ACCESS_STATUSES.has(item.status as CustomerAccessStatus) ||
    typeof item.is_active !== "boolean" ||
    (item.invited_at !== null && !validTimestamp(item.invited_at)) ||
    (item.expires_at !== null && !validTimestamp(item.expires_at)) ||
    (item.accepted_at !== null && !validTimestamp(item.accepted_at))
  ) {
    return null;
  }
  return {
    email,
    status: item.status as CustomerAccessStatus,
    is_active: item.is_active,
    invited_at: item.invited_at,
    expires_at: item.expires_at,
    accepted_at: item.accepted_at,
  };
}

function parseCustomerAuditEvent(value: unknown): CustomerAuditEvent | null {
  const item = asRecord(value);
  if (!item) return null;

  const id = trimmedString(item.id, 1, 64);
  const actorDisplayName = trimmedString(item.actor_display_name, 1, 160);
  if (
    !id ||
    !SAFE_AUDIT_EVENT_ID.test(id) ||
    !CUSTOMER_AUDIT_ACTIONS.has(item.action as CustomerAuditAction) ||
    !Array.isArray(item.changed_fields) ||
    item.changed_fields.length < 1 ||
    item.changed_fields.length > 4 ||
    !positiveInteger(item.revision) ||
    !actorDisplayName ||
    !validTimestamp(item.created_at)
  ) {
    return null;
  }

  const changedFields = item.changed_fields.filter(
    (field): field is
      | CustomerProfileAuditField
      | AgentConfigurationAuditField
      | CustomerAccessAuditField =>
      typeof field === "string" &&
      (PROFILE_AUDIT_FIELDS.has(field as CustomerProfileAuditField) ||
        AGENT_CONFIGURATION_AUDIT_FIELDS.has(field as AgentConfigurationAuditField) ||
        ACCESS_AUDIT_FIELDS.has(field as CustomerAccessAuditField)),
  );
  const allowedFields: ReadonlySet<string> =
    item.action === "customer.profile_updated" || item.action === "customer.created"
      ? PROFILE_AUDIT_FIELDS
      : item.action === "customer.agent_configuration_updated"
        ? AGENT_CONFIGURATION_AUDIT_FIELDS
        : ACCESS_AUDIT_FIELDS;
  if (
    changedFields.length !== item.changed_fields.length ||
    new Set(changedFields).size !== changedFields.length ||
    changedFields.some((field) => !allowedFields.has(field))
  ) {
    return null;
  }

  return {
    id,
    action: item.action as CustomerAuditAction,
    changed_fields: changedFields,
    revision: item.revision,
    actor_display_name: actorDisplayName,
    created_at: item.created_at,
  };
}

export function parseCustomerDetail(value: unknown): CustomerDetail | null {
  const payload = asRecord(value);
  const summary = parseCustomerSummary(value);
  const agentConfiguration = parseAgentConfiguration(payload?.agent_configuration);
  if (
    !payload ||
    !summary ||
    !nonNegativeInteger(payload.open_order_count) ||
    !positiveInteger(payload.profile_revision) ||
    !agentConfiguration ||
    !Array.isArray(payload.recent_audit_events) ||
    payload.recent_audit_events.length > 10 ||
    !Array.isArray(payload.recent_conversations) ||
    payload.recent_conversations.length > 5
  ) {
    return null;
  }

  const email = payload.email === null ? null : trimmedString(payload.email, 3, 254);
  if (payload.email !== null && !email) return null;
  const access = payload.access === null ? null : parseCustomerAccess(payload.access);
  if (payload.access !== null && !access) return null;

  const recentConversations = payload.recent_conversations.map(parseConversationSummary);
  const recentAuditEvents = payload.recent_audit_events.map(parseCustomerAuditEvent);
  if (
    recentConversations.some((conversation) => conversation === null) ||
    recentAuditEvents.some((event) => event === null)
  ) {
    return null;
  }

  return {
    ...summary,
    email,
    access,
    open_order_count: payload.open_order_count,
    profile_revision: payload.profile_revision,
    agent_configuration: agentConfiguration,
    recent_audit_events: recentAuditEvents as CustomerAuditEvent[],
    recent_conversations: recentConversations as ConversationSummary[],
  };
}

const CUSTOMER_CREATE_KEYS = new Set([
  "full_name",
  "email",
  "external_ref",
  "preferred_language",
  "plan_name",
]);
const CUSTOMER_EMAIL = /^[^@\s]{1,64}@[^@\s]{1,189}$/;

export function parseCustomerCreatePayload(value: unknown): CustomerCreateRequest | null {
  const payload = asRecord(value);
  if (!payload || Object.keys(payload).some((key) => !CUSTOMER_CREATE_KEYS.has(key))) {
    return null;
  }

  const fullName = trimmedString(payload.full_name, 1, 160);
  const email = trimmedString(payload.email, 3, 254)?.toLowerCase() ?? null;
  const externalRef = Object.hasOwn(payload, "external_ref")
    ? trimmedString(payload.external_ref, 1, 120)
    : undefined;
  const preferredLanguage = Object.hasOwn(payload, "preferred_language")
    ? trimmedString(payload.preferred_language, 2, 40)
    : "English";
  const planName = Object.hasOwn(payload, "plan_name")
    ? trimmedString(payload.plan_name, 1, 80)
    : "Essential";
  if (
    !fullName ||
    !email ||
    !CUSTOMER_EMAIL.test(email) ||
    (Object.hasOwn(payload, "external_ref") && !externalRef) ||
    !preferredLanguage ||
    !planName
  ) {
    return null;
  }

  return {
    full_name: fullName,
    email,
    ...(externalRef ? { external_ref: externalRef } : {}),
    preferred_language: preferredLanguage,
    plan_name: planName,
  };
}

const CUSTOMER_LIST_QUERY_KEYS = new Set(["query", "status", "limit", "offset"]);
const CUSTOMER_STATUS_FILTERS: ReadonlySet<CustomerStatusFilter> = new Set([
  "all",
  "active",
  "inactive",
]);

function parseDecimalInteger(
  value: string | null,
  minimum: number,
  maximum: number,
): number | undefined | null {
  if (value === null) return undefined;
  if (!/^(0|[1-9]\d*)$/.test(value)) return null;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed >= minimum && parsed <= maximum
    ? parsed
    : null;
}

export function parseCustomerListSearchParams(
  searchParams: URLSearchParams,
): CustomerListQuery | null {
  if (
    [...searchParams.keys()].some((key) => !CUSTOMER_LIST_QUERY_KEYS.has(key)) ||
    [...CUSTOMER_LIST_QUERY_KEYS].some((key) => searchParams.getAll(key).length > 1)
  ) {
    return null;
  }

  const queryValue = searchParams.get("query");
  const query = queryValue === null ? undefined : queryValue.trim();
  if (query !== undefined && query.length > 160) return null;

  const statusValue = searchParams.get("status");
  if (
    statusValue !== null &&
    !CUSTOMER_STATUS_FILTERS.has(statusValue as CustomerStatusFilter)
  ) {
    return null;
  }

  const limit = parseDecimalInteger(searchParams.get("limit"), 1, 100);
  const offset = parseDecimalInteger(searchParams.get("offset"), 0, 10_000);
  if (limit === null || offset === null) return null;

  return {
    ...(query ? { query } : {}),
    ...(statusValue !== null ? { status: statusValue as CustomerStatusFilter } : {}),
    ...(limit !== undefined ? { limit } : {}),
    ...(offset !== undefined ? { offset } : {}),
  };
}

const CUSTOMER_UPDATE_KEYS = new Set([
  "expected_revision",
  "full_name",
  "preferred_language",
  "plan_name",
  "is_active",
]);

export function parseCustomerUpdatePayload(value: unknown): CustomerUpdateRequest | null {
  const payload = asRecord(value);
  if (!payload) return null;

  const keys = Object.keys(payload);
  if (
    keys.length < 2 ||
    keys.some((key) => !CUSTOMER_UPDATE_KEYS.has(key)) ||
    !Object.hasOwn(payload, "expected_revision") ||
    !positiveInteger(payload.expected_revision)
  ) {
    return null;
  }

  const update: CustomerUpdateRequest = {
    expected_revision: payload.expected_revision,
  };
  if (Object.hasOwn(payload, "full_name")) {
    const fullName = trimmedString(payload.full_name, 1, 160);
    if (!fullName) return null;
    update.full_name = fullName;
  }
  if (Object.hasOwn(payload, "preferred_language")) {
    const preferredLanguage = trimmedString(payload.preferred_language, 2, 40);
    if (!preferredLanguage) return null;
    update.preferred_language = preferredLanguage;
  }
  if (Object.hasOwn(payload, "plan_name")) {
    const planName = trimmedString(payload.plan_name, 1, 80);
    if (!planName) return null;
    update.plan_name = planName;
  }
  if (Object.hasOwn(payload, "is_active")) {
    if (typeof payload.is_active !== "boolean") return null;
    update.is_active = payload.is_active;
  }

  return update;
}

const AGENT_CONFIGURATION_UPDATE_KEYS = new Set([
  "expected_revision",
  "display_name",
  "opening_message",
  "tone",
  "instructions",
]);

export function parseAgentConfigurationUpdatePayload(
  value: unknown,
): AgentConfigurationUpdateRequest | null {
  const payload = asRecord(value);
  if (!payload) return null;

  const keys = Object.keys(payload);
  if (
    keys.length < 2 ||
    keys.some((key) => !AGENT_CONFIGURATION_UPDATE_KEYS.has(key)) ||
    !Object.hasOwn(payload, "expected_revision") ||
    !positiveInteger(payload.expected_revision)
  ) {
    return null;
  }

  const update: AgentConfigurationUpdateRequest = {
    expected_revision: payload.expected_revision,
  };
  if (Object.hasOwn(payload, "display_name")) {
    const displayName = trimmedString(payload.display_name, 1, 80);
    if (!displayName) return null;
    update.display_name = displayName;
  }
  if (Object.hasOwn(payload, "opening_message")) {
    const openingMessage = trimmedString(payload.opening_message, 1, 500);
    if (!openingMessage || !isSupportedAgentOpeningTemplate(openingMessage)) return null;
    update.opening_message = openingMessage;
  }
  if (Object.hasOwn(payload, "tone")) {
    const tone = trimmedString(payload.tone, 1, 20);
    if (!tone || !AGENT_TONES.has(tone as AgentTone)) return null;
    update.tone = tone as AgentTone;
  }
  if (Object.hasOwn(payload, "instructions")) {
    const instructions = trimmedStringAllowEmpty(payload.instructions, 2_000);
    if (instructions === null) return null;
    update.instructions = instructions;
  }

  return update;
}

export function parseConversationDetailResponse(
  value: unknown,
): ConversationDetailResponse | null {
  const payload = asRecord(value);
  const summary = parseConversationSummary(value);
  if (!payload || !summary || !Array.isArray(payload.transcript)) return null;

  const transcript = payload.transcript.map(parseTranscriptTurn);
  const finalVariables = asRecord(payload.final_variables);
  if (transcript.some((turn) => turn === null) || !finalVariables) return null;

  return {
    ...summary,
    transcript: transcript as TranscriptTurn[],
    final_variables: { ...finalVariables },
  };
}

type VoiceSessionValidationOptions = {
  allowedWebsocketHosts?: readonly string[];
  requireWebsocketHostAllowlist?: boolean;
  now?: number;
};

const MAX_VOICE_SESSION_LIFETIME_MS = 65 * 60 * 1_000;
const SAFE_VOICE_SESSION_ID = /^[a-zA-Z0-9_-]{1,100}$/;
const VOICE_SESSION_CANCEL_STATUSES: ReadonlySet<VoiceSessionCancelStatus> = new Set([
  "cancelling",
  "cancelled",
  "completed",
  "ended",
  "expired",
  "failed",
]);

function validFutureTimestamp(value: unknown, now: number): value is string {
  if (typeof value !== "string") return false;
  const timestamp = Date.parse(value);
  return Number.isFinite(timestamp) && timestamp > now;
}

function validWebsocketUrl(
  value: unknown,
  allowedHosts: readonly string[] | undefined,
  requireAllowlist: boolean,
): value is string {
  if (typeof value !== "string" || value.length > 8_192) return false;

  try {
    const url = new URL(value);
    const loopbackHost =
      url.hostname === "localhost" || url.hostname === "127.0.0.1" || url.hostname === "[::1]";
    if (
      (url.protocol !== "wss:" && !(url.protocol === "ws:" && loopbackHost)) ||
      !url.hostname ||
      url.username ||
      url.password ||
      url.hash
    ) {
      return false;
    }

    if (!allowedHosts?.length) return !requireAllowlist;
    const normalizedAllowedHosts = allowedHosts.map((host) => host.trim().toLowerCase());
    return normalizedAllowedHosts.includes(url.hostname.toLowerCase());
  } catch {
    return false;
  }
}

export function parseVoiceSessionResponse(
  value: unknown,
  options: VoiceSessionValidationOptions = {},
): VoiceSessionResponse | null {
  const payload = asRecord(value);
  const connection = asRecord(payload?.connection);
  const now = options.now ?? Date.now();
  if (
    !payload ||
    !connection ||
    typeof payload.session_id !== "string" ||
    !SAFE_VOICE_SESSION_ID.test(payload.session_id) ||
    typeof payload.provider !== "string" ||
    payload.provider.length < 1 ||
    payload.provider.length > 80 ||
    payload.status !== "ready" ||
    typeof payload.language !== "string" ||
    payload.language.length < 1 ||
    payload.language.length > 80 ||
    !validFutureTimestamp(payload.expires_at, now) ||
    (connection.transport !== "mock" && connection.transport !== "websocket") ||
    !validFutureTimestamp(connection.expires_at, now)
  ) {
    return null;
  }

  const sessionExpiry = Date.parse(payload.expires_at as string);
  const connectionExpiry = Date.parse(connection.expires_at as string);
  if (
    sessionExpiry - now > MAX_VOICE_SESSION_LIFETIME_MS ||
    connectionExpiry - now > MAX_VOICE_SESSION_LIFETIME_MS ||
    connectionExpiry > sessionExpiry
  ) {
    return null;
  }

  if (connection.transport === "mock" && connection.websocket_url !== null) return null;
  if (
    connection.transport === "websocket" &&
    !validWebsocketUrl(
      connection.websocket_url,
      options.allowedWebsocketHosts,
      options.requireWebsocketHostAllowlist ?? false,
    )
  ) {
    return null;
  }

  return {
    session_id: payload.session_id,
    provider: payload.provider,
    status: payload.status,
    language: payload.language,
    expires_at: payload.expires_at,
    connection:
      connection.transport === "mock"
        ? {
            transport: "mock",
            websocket_url: null,
            expires_at: connection.expires_at,
          }
        : {
            transport: "websocket",
            websocket_url: connection.websocket_url as string,
            expires_at: connection.expires_at,
          },
  };
}

export function parseCancelVoiceSessionResponse(
  value: unknown,
): CancelVoiceSessionResponse | null {
  const payload = asRecord(value);
  if (
    !payload ||
    typeof payload.session_id !== "string" ||
    payload.session_id.length < 1 ||
    payload.session_id.length > 100 ||
    typeof payload.status !== "string" ||
    !VOICE_SESSION_CANCEL_STATUSES.has(payload.status as VoiceSessionCancelStatus) ||
    typeof payload.idempotent !== "boolean"
  ) {
    return null;
  }

  return {
    session_id: payload.session_id,
    status: payload.status as VoiceSessionCancelStatus,
    idempotent: payload.idempotent,
  };
}
