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

export type CustomerAuditAction =
  | "customer.profile_updated"
  | "customer.agent_configuration_updated";

export type CustomerAuditEvent = {
  id: string;
  action: CustomerAuditAction;
  changed_fields: Array<CustomerProfileAuditField | AgentConfigurationAuditField>;
  revision: number;
  actor_display_name: string;
  created_at: string;
};

export type CustomerDetail = CustomerSummary & {
  email: string | null;
  open_order_count: number;
  profile_revision: number;
  agent_configuration: AgentConfiguration;
  recent_audit_events: CustomerAuditEvent[];
  recent_conversations: ConversationSummary[];
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
