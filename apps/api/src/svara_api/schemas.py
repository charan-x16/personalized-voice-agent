import re
from datetime import date, datetime, time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from .agent_configuration import (
    MAX_RUNTIME_OPENING_MESSAGE_LENGTH,
    is_supported_opening_message_template,
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DemoLoginRequest(StrictModel):
    email: str = Field(default="rahul@example.com", min_length=3, max_length=254)


class TokenResponse(StrictModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 - OAuth token type, not a secret
    expires_in: int


class MeResponse(StrictModel):
    user_id: str
    customer_id: str | None
    role: str
    full_name: str
    first_name: str
    initials: str
    email: str
    workspace_name: str
    preferred_language: str | None
    plan_name: str | None
    agent_name: str | None = None
    agent_opening_message: str | None = None
    voice_mode: Literal["mock", "sarvam"] = "mock"


class VoiceSessionCreateRequest(StrictModel):
    language: str | None = Field(default=None, min_length=2, max_length=40)


class ProviderConnection(StrictModel):
    transport: Literal["mock", "websocket"]
    websocket_url: str | None = None
    expires_at: datetime


class VoiceSessionResponse(StrictModel):
    session_id: str
    provider: str
    status: str
    language: str
    expires_at: datetime
    connection: ProviderConnection


class VoiceSessionCancelResponse(StrictModel):
    session_id: str
    status: Literal["cancelling", "cancelled", "completed", "ended", "expired", "failed"]
    idempotent: bool


class OnStartRequest(StrictModel):
    conversation_ref: str = Field(min_length=24, max_length=256)
    interaction_id: str | None = Field(default=None, max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CustomerContext(StrictModel):
    first_name: str
    preferred_language: str
    plan_name: str
    open_request_count: int = Field(ge=0)


class RuntimeAgentConfiguration(StrictModel):
    display_name: str
    opening_message: str = Field(max_length=MAX_RUNTIME_OPENING_MESSAGE_LENGTH)
    tone: Literal["warm", "professional", "concise"]
    instructions: str
    revision: int = Field(ge=1)


class OnStartResponse(StrictModel):
    session_id: str
    customer: CustomerContext
    agent: RuntimeAgentConfiguration
    safe_to_continue: bool


class OrderStatusRequest(StrictModel):
    conversation_ref: str = Field(min_length=24, max_length=256)
    interaction_id: str | None = Field(default=None, max_length=160)
    order_reference: str = Field(min_length=3, max_length=120)


class OrderStatusResponse(StrictModel):
    order_reference: str
    status: str
    estimated_arrival: str | None
    delivery_city: str | None


VoiceToolCapability = Literal[
    "customer_profile",
    "order_status",
    "reservation_availability",
    "reservation_lookup",
    "reservation_create",
    "reservation_reschedule",
    "reservation_cancel",
]


class VoiceToolDefinitionResponse(StrictModel):
    id: str
    tool_key: str
    display_name: str
    description: str
    capability: VoiceToolCapability
    is_enabled: bool
    revision: int = Field(ge=1)
    assigned_customer_count: int = Field(ge=0)
    created_at: datetime
    updated_at: datetime


class VoiceToolAdminEventResponse(StrictModel):
    id: str
    action: Literal[
        "voice_tool.created",
        "voice_tool.updated",
        "customer_voice_tool.updated",
    ]
    tool_id: str
    tool_key: str
    tool_display_name: str
    customer_id: str | None
    customer_reference: str | None
    changed_fields: list[str]
    revision: int = Field(ge=1)
    actor_display_name: str = Field(min_length=1, max_length=160)
    created_at: datetime


class VoiceToolListResponse(StrictModel):
    items: list[VoiceToolDefinitionResponse]
    total: int = Field(ge=0)
    recent_events: list[VoiceToolAdminEventResponse]


class VoiceToolCreateRequest(StrictModel):
    tool_key: str = Field(min_length=3, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    display_name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=500)
    capability: VoiceToolCapability
    is_enabled: bool = True

    @field_validator("tool_key", "display_name", "description", mode="before")
    @classmethod
    def trim_tool_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class VoiceToolUpdateRequest(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, min_length=1, max_length=500)
    is_enabled: bool | None = None

    @field_validator("display_name", "description", mode="before")
    @classmethod
    def trim_optional_tool_fields(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def require_tool_change(self) -> "VoiceToolUpdateRequest":
        if self.display_name is None and self.description is None and self.is_enabled is None:
            raise ValueError("At least one tool field must be provided")
        return self


class CustomerVoiceToolResponse(StrictModel):
    tool: VoiceToolDefinitionResponse
    assigned: bool
    is_enabled: bool
    revision: int | None = Field(default=None, ge=1)
    updated_at: datetime | None


class CustomerVoiceToolListResponse(StrictModel):
    customer_id: str
    items: list[CustomerVoiceToolResponse]


class CustomerVoiceToolUpdateRequest(StrictModel):
    is_enabled: bool
    expected_revision: int | None = Field(default=None, ge=1, strict=True)


class VoiceToolExecuteRequest(StrictModel):
    conversation_ref: str = Field(min_length=24, max_length=256)
    interaction_id: str | None = Field(default=None, max_length=160)
    arguments: dict[str, Any] = Field(default_factory=dict)


class CustomerProfileToolResponse(StrictModel):
    full_name: str
    preferred_language: str
    plan_name: str


class ReservationToolRequest(StrictModel):
    conversation_ref: str = Field(min_length=24, max_length=256)
    interaction_id: str | None = Field(default=None, max_length=160)


class CheckAvailabilityRequest(ReservationToolRequest):
    reservation_date: date
    preferred_time: time
    party_size: int = Field(ge=1, le=100, strict=True)

    @field_validator("preferred_time")
    @classmethod
    def require_local_wall_clock(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("preferred_time must be a local time without an offset")
        return value


class AvailabilitySlot(StrictModel):
    start_at: datetime
    end_at: datetime
    display_time: str


class CheckAvailabilityResponse(StrictModel):
    available: bool
    service_location: str
    timezone: str
    party_size: int
    slots: list[AvailabilitySlot] = Field(max_length=5)
    reason: str | None = None


class CreateReservationRequest(ReservationToolRequest):
    start_at: datetime
    party_size: int = Field(ge=1, le=100, strict=True)
    guest_name: str | None = Field(default=None, min_length=1, max_length=160)
    special_requests: str | None = Field(default=None, max_length=500)

    @field_validator("start_at")
    @classmethod
    def require_start_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("start_at must include a timezone offset")
        return value

    @field_validator("guest_name", "special_requests", mode="before")
    @classmethod
    def trim_optional_text(cls, value: object) -> object:
        if isinstance(value, str):
            trimmed = value.strip()
            return trimmed or None
        return value


class FindReservationRequest(ReservationToolRequest):
    reservation_reference: str | None = Field(default=None, min_length=5, max_length=24)

    @field_validator("reservation_reference", mode="before")
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip().upper()
        return value


class RescheduleReservationRequest(ReservationToolRequest):
    reservation_reference: str = Field(min_length=5, max_length=24)
    new_start_at: datetime
    expected_version: int = Field(ge=1, strict=True)

    @field_validator("reservation_reference", mode="before")
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    @field_validator("new_start_at")
    @classmethod
    def require_start_offset(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("new_start_at must include a timezone offset")
        return value


class CancelReservationRequest(ReservationToolRequest):
    reservation_reference: str = Field(min_length=5, max_length=24)
    expected_version: int = Field(ge=1, strict=True)

    @field_validator("reservation_reference", mode="before")
    @classmethod
    def normalize_reference(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class ReservationDetails(StrictModel):
    reservation_reference: str
    status: Literal["confirmed", "cancelled"]
    guest_name: str
    party_size: int
    start_at: datetime
    end_at: datetime
    service_location: str
    timezone: str
    special_requests: str | None
    version: int = Field(ge=1)


class ReservationMutationResponse(StrictModel):
    reservation: ReservationDetails
    idempotent: bool


class FindReservationResponse(StrictModel):
    found: bool
    reservations: list[ReservationDetails] = Field(max_length=5)


class TranscriptTurn(StrictModel):
    speaker: Literal["agent", "customer", "tool"]
    text: str = Field(min_length=1, max_length=8_000)
    timestamp: str | None = Field(default=None, max_length=80)


class ConversationSummaryResponse(StrictModel):
    id: str
    provider: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    language: str
    resolution: str | None
    summary: str | None


class ConversationListResponse(StrictModel):
    items: list[ConversationSummaryResponse]
    total: int = Field(ge=0)


class ConversationDetailResponse(ConversationSummaryResponse):
    transcript: list[TranscriptTurn]
    final_variables: dict[str, Any]


class CustomerSummaryResponse(StrictModel):
    id: str
    external_ref: str
    full_name: str
    initials: str
    preferred_language: str
    plan_name: str
    is_active: bool
    created_at: datetime
    conversation_count: int = Field(ge=0)
    resolved_conversation_count: int = Field(ge=0)
    last_conversation_at: datetime | None


class CustomerListResponse(StrictModel):
    items: list[CustomerSummaryResponse]
    total: int = Field(ge=0)


class CustomerDetailResponse(CustomerSummaryResponse):
    email: str | None
    access: "CustomerAccessResponse | None"
    open_order_count: int = Field(ge=0)
    profile_revision: int = Field(ge=1)
    agent_configuration: "AgentConfigurationResponse"
    recent_conversations: list[ConversationSummaryResponse]
    recent_audit_events: list["AdminAuditEventResponse"]


class AgentConfigurationResponse(StrictModel):
    display_name: str
    opening_message: str
    tone: Literal["warm", "professional", "concise"]
    instructions: str
    revision: int = Field(ge=1)
    updated_at: datetime | None


class AdminAuditEventResponse(StrictModel):
    id: str
    action: Literal[
        "customer.profile_updated",
        "customer.agent_configuration_updated",
        "customer.created",
        "customer.access_invitation_sent",
        "customer.access_invitation_failed",
        "customer.access_revoked",
        "customer.access_restored",
    ]
    changed_fields: list[str]
    revision: int = Field(ge=1)
    actor_display_name: str = Field(min_length=1, max_length=160)
    created_at: datetime


class CustomerAccessResponse(StrictModel):
    email: str
    status: Literal[
        "not_invited",
        "queued",
        "pending",
        "accepted",
        "revoked",
        "expired",
        "failed",
    ]
    is_active: bool
    invited_at: datetime | None
    expires_at: datetime | None
    accepted_at: datetime | None


class CustomerCreateRequest(StrictModel):
    full_name: str = Field(min_length=1, max_length=160)
    email: str = Field(min_length=3, max_length=254)
    external_ref: str | None = Field(default=None, min_length=1, max_length=120)
    preferred_language: str = Field(default="English", min_length=2, max_length=40)
    plan_name: str = Field(default="Essential", min_length=1, max_length=80)

    @field_validator(
        "full_name",
        "email",
        "external_ref",
        "preferred_language",
        "plan_name",
        mode="before",
    )
    @classmethod
    def trim_fields(cls, value: object) -> object:
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        normalized = value.casefold()
        if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,189}", normalized):
            raise ValueError("Enter a valid email address")
        return normalized


class CustomerUpdateRequest(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    full_name: str | None = Field(default=None, min_length=1, max_length=160)
    preferred_language: str | None = Field(default=None, min_length=2, max_length=40)
    plan_name: str | None = Field(default=None, min_length=1, max_length=80)
    is_active: StrictBool | None = None

    @field_validator("full_name", "preferred_language", "plan_name", mode="before")
    @classmethod
    def trim_and_reject_null_strings(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field must not be null")
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("is_active", mode="before")
    @classmethod
    def reject_null_status(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field must not be null")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "CustomerUpdateRequest":
        editable_fields = {"full_name", "preferred_language", "plan_name", "is_active"}
        if not self.model_fields_set.intersection(editable_fields):
            raise ValueError("At least one customer field is required")
        return self


class AgentConfigurationUpdateRequest(StrictModel):
    expected_revision: int = Field(ge=1, strict=True)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    opening_message: str | None = Field(default=None, min_length=1, max_length=500)
    tone: Literal["warm", "professional", "concise"] | None = None
    instructions: str | None = Field(default=None, max_length=2_000)

    @field_validator(
        "display_name",
        "opening_message",
        "tone",
        "instructions",
        mode="before",
    )
    @classmethod
    def trim_and_reject_null_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("Field must not be null")
        if isinstance(value, str):
            return value.strip()
        return value

    @field_validator("opening_message")
    @classmethod
    def validate_opening_message_template(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_opening_message_template(value):
            raise ValueError("At most one exact {first_name} placeholder is supported")
        return value

    @model_validator(mode="after")
    def require_at_least_one_field(self) -> "AgentConfigurationUpdateRequest":
        editable_fields = {"display_name", "opening_message", "tone", "instructions"}
        if not self.model_fields_set.intersection(editable_fields):
            raise ValueError("At least one agent configuration field is required")
        return self


class MockConversationCompleteRequest(StrictModel):
    resolution: str = Field(default="completed", min_length=2, max_length=80)
    summary: str | None = Field(default=None, max_length=4_000)
    transcript: list[TranscriptTurn] = Field(default_factory=list, max_length=500)
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)


class OnEndRequest(StrictModel):
    conversation_ref: str = Field(min_length=24, max_length=256)
    interaction_id: str | None = Field(default=None, max_length=160)
    resolution: str = Field(default="unknown", min_length=2, max_length=80)
    summary: str | None = Field(default=None, max_length=4_000)
    transcript: list[TranscriptTurn] = Field(default_factory=list, max_length=500)
    final_variables: dict[str, Any] = Field(default_factory=dict)
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)


class OnEndResponse(StrictModel):
    session_id: str
    outcome_id: str
    status: Literal["recorded"] = "recorded"
    idempotent: bool
