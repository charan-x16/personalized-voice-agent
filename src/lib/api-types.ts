export type MeResponse = {
  user_id: string;
  role: "customer" | "admin";
  customer_id: string | null;
  full_name: string;
  first_name: string;
  initials: string;
  email: string;
  workspace_name: string;
  preferred_language: string | null;
  plan_name: string | null;
  agent_name?: string | null;
  agent_opening_message?: string | null;
  voice_mode?: "mock" | "sarvam";
};

export type ConversationSummary = {
  id: string;
  provider: string;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  language: string;
  resolution: string | null;
  summary: string | null;
};

export type ConversationListResponse = {
  items: ConversationSummary[];
  total: number;
};

export type CustomerStatusFilter = "all" | "active" | "inactive";

export type CustomerListQuery = {
  query?: string;
  status?: CustomerStatusFilter;
  limit?: number;
  offset?: number;
};

export type CustomerSummary = {
  id: string;
  external_ref: string;
  full_name: string;
  initials: string;
  preferred_language: string;
  plan_name: string;
  is_active: boolean;
  created_at: string;
  conversation_count: number;
  resolved_conversation_count: number;
  last_conversation_at: string | null;
};

export type CustomerListResponse = {
  items: CustomerSummary[];
  total: number;
};

export type VoiceToolCapability =
  | "customer_profile"
  | "order_status"
  | "reservation_availability"
  | "reservation_lookup"
  | "reservation_create"
  | "reservation_reschedule"
  | "reservation_cancel";

export type VoiceToolDefinition = {
  id: string;
  tool_key: string;
  display_name: string;
  description: string;
  capability: VoiceToolCapability;
  is_enabled: boolean;
  revision: number;
  assigned_customer_count: number;
  created_at: string;
  updated_at: string;
};

export type VoiceToolAdminAction =
  | "voice_tool.created"
  | "voice_tool.updated"
  | "customer_voice_tool.updated";

export type VoiceToolAdminEvent = {
  id: string;
  action: VoiceToolAdminAction;
  tool_id: string;
  tool_key: string;
  tool_display_name: string;
  customer_id: string | null;
  customer_reference: string | null;
  changed_fields: string[];
  revision: number;
  actor_display_name: string;
  created_at: string;
};

export type VoiceToolListResponse = {
  items: VoiceToolDefinition[];
  total: number;
  recent_events: VoiceToolAdminEvent[];
};

export type VoiceToolCreateRequest = {
  tool_key: string;
  display_name: string;
  description: string;
  capability: VoiceToolCapability;
  is_enabled: boolean;
};

export type VoiceToolUpdateRequest = {
  expected_revision: number;
  display_name?: string;
  description?: string;
  is_enabled?: boolean;
};

export type CustomerVoiceTool = {
  tool: VoiceToolDefinition;
  assigned: boolean;
  is_enabled: boolean;
  revision: number | null;
  updated_at: string | null;
};

export type CustomerVoiceToolListResponse = {
  customer_id: string;
  items: CustomerVoiceTool[];
};

export type CustomerVoiceToolUpdateRequest = {
  is_enabled: boolean;
  expected_revision: number | null;
};

export type AgentTone = "warm" | "professional" | "concise";

export type AgentConfiguration = {
  display_name: string;
  opening_message: string;
  tone: AgentTone;
  instructions: string;
  revision: number;
  updated_at: string | null;
};

export type CustomerProfileAuditField =
  | "full_name"
  | "preferred_language"
  | "plan_name"
  | "is_active";

export type AgentConfigurationAuditField =
  | "display_name"
  | "opening_message"
  | "tone"
  | "instructions";

export type CustomerAccessAuditField = "access_status";

export type CustomerAuditAction =
  | "customer.profile_updated"
  | "customer.agent_configuration_updated"
  | "customer.created"
  | "customer.access_invitation_sent"
  | "customer.access_invitation_failed"
  | "customer.access_revoked"
  | "customer.access_restored";

export type CustomerAuditEvent = {
  id: string;
  action: CustomerAuditAction;
  changed_fields: Array<
    CustomerProfileAuditField | AgentConfigurationAuditField | CustomerAccessAuditField
  >;
  revision: number;
  actor_display_name: string;
  created_at: string;
};

export type CustomerDetail = CustomerSummary & {
  email: string | null;
  access: CustomerAccess | null;
  open_order_count: number;
  profile_revision: number;
  agent_configuration: AgentConfiguration;
  recent_audit_events: CustomerAuditEvent[];
  recent_conversations: ConversationSummary[];
};

export type CustomerAccessStatus =
  | "not_invited"
  | "queued"
  | "pending"
  | "accepted"
  | "revoked"
  | "expired"
  | "failed";

export type CustomerAccess = {
  email: string;
  status: CustomerAccessStatus;
  is_active: boolean;
  invited_at: string | null;
  expires_at: string | null;
  accepted_at: string | null;
};

export type CustomerCreateRequest = {
  full_name: string;
  email: string;
  external_ref?: string;
  preferred_language: string;
  plan_name: string;
};

export type CustomerUpdateRequest = {
  expected_revision: number;
  full_name?: string;
  preferred_language?: string;
  plan_name?: string;
  is_active?: boolean;
};

export type AgentConfigurationUpdateRequest = {
  expected_revision: number;
  display_name?: string;
  opening_message?: string;
  tone?: AgentTone;
  instructions?: string;
};

export type TranscriptTurn = {
  speaker: "agent" | "customer" | "tool";
  text: string;
  timestamp?: string | null;
};

export type ConversationDetailResponse = ConversationSummary & {
  transcript: TranscriptTurn[];
  final_variables: Record<string, unknown>;
};

export type MockVoiceConnection = {
  transport: "mock";
  websocket_url: null;
  expires_at: string;
};

export type WebSocketVoiceConnection = {
  transport: "websocket";
  websocket_url: string;
  expires_at: string;
};

export type VoiceConnection = MockVoiceConnection | WebSocketVoiceConnection;

export type VoiceSessionResponse = {
  session_id: string;
  provider: string;
  status: "ready";
  language: string;
  expires_at: string;
  connection: VoiceConnection;
};

export type VoiceSessionCancelStatus =
  | "cancelling"
  | "cancelled"
  | "completed"
  | "ended"
  | "expired"
  | "failed";

export type CancelVoiceSessionResponse = {
  session_id: string;
  status: VoiceSessionCancelStatus;
  idempotent: boolean;
};
