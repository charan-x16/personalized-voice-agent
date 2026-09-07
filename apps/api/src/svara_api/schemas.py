from datetime import datetime
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
    ]
    changed_fields: list[str]
    revision: int = Field(ge=1)
    actor_display_name: str = Field(min_length=1, max_length=160)
    created_at: datetime


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
