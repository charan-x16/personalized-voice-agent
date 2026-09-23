from __future__ import annotations

from datetime import UTC, datetime, time
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from .agent_configuration import (
    DEFAULT_AGENT_DISPLAY_NAME,
    DEFAULT_AGENT_INSTRUCTIONS,
    DEFAULT_AGENT_OPENING_MESSAGE,
    DEFAULT_AGENT_TONE,
)


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_ref", name="uq_customer_tenant_external_ref"),
        UniqueConstraint("tenant_id", "id", name="uq_customer_tenant_id"),
        Index("ix_customer_tenant", "tenant_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    external_ref: Mapped[str] = mapped_column(String(120))
    full_name: Mapped[str] = mapped_column(String(160))
    preferred_language: Mapped[str] = mapped_column(String(40), default="English")
    plan_name: Mapped[str] = mapped_column(String(80), default="Essential")
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
        Index("ux_users_clerk_user_id", "clerk_user_id", unique=True),
        Index("ux_users_clerk_invitation_id", "clerk_invitation_id", unique=True),
        Index("ix_users_invited_by_user_id", "invited_by_user_id"),
        Index("ix_users_tenant_customer_active", "tenant_id", "customer_id", "is_active"),
        CheckConstraint(
            "invitation_status IS NULL OR invitation_status IN "
            "('queued', 'pending', 'accepted', 'revoked', 'expired', 'failed')",
            name="ck_users_invitation_status",
        ),
        CheckConstraint("access_generation >= 0", name="ck_users_access_generation"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_user_tenant_customer",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[str | None] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True
    )
    email: Mapped[str] = mapped_column(String(254), index=True)
    clerk_user_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    clerk_invitation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    invitation_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    invitation_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invitation_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invitation_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    access_generation: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    clerk_last_event_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    invited_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40), default="customer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClerkInvitationOutbox(Base):
    __tablename__ = "clerk_invitation_outbox"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('create', 'revoke')",
            name="ck_clerk_invitation_outbox_operation",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'dead_letter')",
            name="ck_clerk_invitation_outbox_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_clerk_invitation_outbox_attempts"),
        CheckConstraint("access_generation >= 1", name="ck_clerk_invitation_outbox_generation"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_clerk_invitation_outbox_tenant_customer",
            ondelete="CASCADE",
        ),
        Index(
            "ix_clerk_invitation_outbox_ready",
            "status",
            "available_at",
            "created_at",
        ),
        Index("ix_clerk_invitation_outbox_user", "user_id", "created_at"),
        Index(
            "ux_clerk_invitation_outbox_active_operation",
            "user_id",
            "operation",
            "access_generation",
            unique=True,
            postgresql_where=text("status IN ('pending', 'processing')"),
            sqlite_where=text("status IN ('pending', 'processing')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    actor_display_name: Mapped[str] = mapped_column(String(160))
    operation: Mapped[str] = mapped_column(String(16))
    access_generation: Mapped[int] = mapped_column(Integer)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    invitation_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending", server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    locked_by: Mapped[str | None] = mapped_column(String(160), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ClerkWebhookEvent(Base):
    __tablename__ = "clerk_webhook_events"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processed', 'ignored')",
            name="ck_clerk_webhook_events_status",
        ),
        Index("ix_clerk_webhook_events_received", "received_at"),
    )

    message_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(100))
    object_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class CustomerOrder(Base):
    __tablename__ = "customer_orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_ref", name="uq_order_tenant_external_ref"),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_order_tenant_customer",
        ),
        Index("ix_order_tenant_customer", "tenant_id", "customer_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    external_ref: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(80))
    estimated_arrival: Mapped[str | None] = mapped_column(String(160), nullable=True)
    delivery_city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ReservationPolicy(Base):
    __tablename__ = "reservation_policies"
    __table_args__ = (
        CheckConstraint(
            "opening_time < closing_time",
            name="ck_reservation_policy_business_hours",
        ),
        CheckConstraint(
            "slot_interval_minutes BETWEEN 5 AND 240",
            name="ck_reservation_policy_slot_interval",
        ),
        CheckConstraint(
            "reservation_duration_minutes BETWEEN 15 AND 480",
            name="ck_reservation_policy_duration",
        ),
        CheckConstraint(
            "max_party_size BETWEEN 1 AND 100",
            name="ck_reservation_policy_max_party_size",
        ),
        CheckConstraint(
            "advance_booking_days BETWEEN 1 AND 365",
            name="ck_reservation_policy_advance_days",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    service_provider_name: Mapped[str] = mapped_column(String(160))
    service_location: Mapped[str] = mapped_column(String(160))
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    opening_time: Mapped[time] = mapped_column(Time(), default=time(9, 0))
    closing_time: Mapped[time] = mapped_column(Time(), default=time(22, 0))
    slot_interval_minutes: Mapped[int] = mapped_column(Integer, default=30)
    reservation_duration_minutes: Mapped[int] = mapped_column(Integer, default=90)
    max_party_size: Mapped[int] = mapped_column(Integer, default=8)
    advance_booking_days: Mapped[int] = mapped_column(Integer, default=90)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CafeTable(Base):
    __tablename__ = "cafe_tables"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cafe_table_tenant_id"),
        UniqueConstraint("tenant_id", "name", name="uq_cafe_table_tenant_name"),
        CheckConstraint("capacity BETWEEN 1 AND 100", name="ck_cafe_table_capacity"),
        Index(
            "ix_cafe_table_tenant_active_capacity",
            "tenant_id",
            "is_active",
            "capacity",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(80))
    capacity: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CustomerProfileState(Base):
    __tablename__ = "customer_profile_states"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_profile_state_tenant_customer",
            ondelete="CASCADE",
        ),
        Index(
            "ix_customer_profile_state_tenant_customer",
            "tenant_id",
            "customer_id",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CustomerAgentConfiguration(Base):
    __tablename__ = "customer_agent_configurations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_agent_configuration_tenant_customer",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "tone IN ('warm', 'professional', 'concise')",
            name="ck_customer_agent_configuration_tone",
        ),
        Index(
            "ix_customer_agent_configuration_tenant_customer",
            "tenant_id",
            "customer_id",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), primary_key=True
    )
    display_name: Mapped[str] = mapped_column(String(80), default=DEFAULT_AGENT_DISPLAY_NAME)
    opening_message: Mapped[str] = mapped_column(String(500), default=DEFAULT_AGENT_OPENING_MESSAGE)
    tone: Mapped[str] = mapped_column(String(20), default=DEFAULT_AGENT_TONE)
    instructions: Mapped[str] = mapped_column(Text, default=DEFAULT_AGENT_INSTRUCTIONS)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class VoiceToolDefinition(Base):
    __tablename__ = "voice_tool_definitions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "tool_key", name="uq_voice_tool_tenant_key"),
        UniqueConstraint("tenant_id", "id", name="uq_voice_tool_tenant_id"),
        CheckConstraint(
            "capability IN ('customer_profile', 'order_status', "
            "'reservation_availability', 'reservation_lookup', 'reservation_create', "
            "'reservation_reschedule', 'reservation_cancel')",
            name="ck_voice_tool_capability",
        ),
        CheckConstraint("revision >= 1", name="ck_voice_tool_revision"),
        Index(
            "ix_voice_tool_tenant_enabled_key",
            "tenant_id",
            "is_enabled",
            "tool_key",
        ),
        Index("ix_voice_tool_created_by", "created_by_user_id"),
        Index("ix_voice_tool_updated_by", "updated_by_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    tool_key: Mapped[str] = mapped_column(String(80))
    display_name: Mapped[str] = mapped_column(String(80))
    description: Mapped[str] = mapped_column(Text)
    capability: Mapped[str] = mapped_column(String(40))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class CustomerVoiceTool(Base):
    __tablename__ = "customer_voice_tools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_voice_tool_tenant_customer",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["voice_tool_definitions.tenant_id", "voice_tool_definitions.id"],
            name="fk_customer_voice_tool_tenant_tool",
            ondelete="CASCADE",
        ),
        CheckConstraint("revision >= 1", name="ck_customer_voice_tool_revision"),
        Index(
            "ix_customer_voice_tool_tenant_customer_enabled",
            "tenant_id",
            "customer_id",
            "is_enabled",
        ),
        Index("ix_customer_voice_tool_tenant_tool", "tenant_id", "tool_id"),
        Index("ix_customer_voice_tool_updated_by", "updated_by_user_id"),
    )

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    customer_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tool_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    updated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class VoiceToolAdminEvent(Base):
    __tablename__ = "voice_tool_admin_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["voice_tool_definitions.tenant_id", "voice_tool_definitions.id"],
            name="fk_voice_tool_admin_event_tenant_tool",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_voice_tool_admin_event_tenant_customer",
            ondelete="CASCADE",
        ),
        CheckConstraint(
            "action IN ('voice_tool.created', 'voice_tool.updated', 'customer_voice_tool.updated')",
            name="ck_voice_tool_admin_event_action",
        ),
        CheckConstraint("revision >= 1", name="ck_voice_tool_admin_event_revision"),
        Index(
            "ix_voice_tool_admin_event_tenant_created",
            "tenant_id",
            "created_at",
        ),
        Index(
            "ix_voice_tool_admin_event_tenant_customer_created",
            "tenant_id",
            "customer_id",
            "created_at",
        ),
        Index("ix_voice_tool_admin_event_actor", "actor_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    tool_id: Mapped[str] = mapped_column(String(36))
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    actor_display_name: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(100))
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdminAuditEvent(Base):
    __tablename__ = "admin_audit_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_admin_audit_event_tenant_customer",
            ondelete="CASCADE",
        ),
        Index(
            "ix_admin_audit_event_tenant_customer_created",
            "tenant_id",
            "customer_id",
            "created_at",
        ),
        Index("ix_admin_audit_event_tenant_actor", "tenant_id", "actor_user_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    actor_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    actor_display_name: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(100))
    changed_fields: Mapped[list[str]] = mapped_column(JSON, default=list)
    revision: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class VoiceSession(Base):
    __tablename__ = "voice_sessions"
    __table_args__ = (
        CheckConstraint(
            "session_mode IN ('customer', 'admin_preview')",
            name="ck_voice_session_mode",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_voice_session_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "customer_id",
            "active_slot",
            name="uq_voice_session_active_customer",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_voice_session_tenant_customer",
        ),
        Index("ix_voice_session_tenant_customer", "tenant_id", "customer_id"),
        Index(
            "ix_voice_session_tenant_initiator_started",
            "tenant_id",
            "initiated_by_user_id",
            "started_at",
        ),
        Index("ix_voice_session_reference_hash", "conversation_ref_hash", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    session_mode: Mapped[str] = mapped_column(
        String(32),
        default="customer",
        server_default="customer",
    )
    initiated_by_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(40), default="mock")
    provider_session_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    provider_interaction_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    conversation_ref_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(40), default="created")
    active_slot: Mapped[int | None] = mapped_column(Integer, default=1, nullable=True)
    language: Mapped[str] = mapped_column(String(40), default="English")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class CafeReservation(Base):
    __tablename__ = "cafe_reservations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "id", name="uq_cafe_reservation_tenant_id"),
        UniqueConstraint(
            "tenant_id",
            "reservation_reference",
            name="uq_cafe_reservation_tenant_reference",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_cafe_reservation_tenant_customer",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "cafe_table_id"],
            ["cafe_tables.tenant_id", "cafe_tables.id"],
            name="fk_cafe_reservation_tenant_table",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "voice_session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.id"],
            name="fk_cafe_reservation_tenant_voice_session",
        ),
        CheckConstraint("end_at > start_at", name="ck_cafe_reservation_time_range"),
        CheckConstraint("party_size BETWEEN 1 AND 100", name="ck_cafe_reservation_party_size"),
        CheckConstraint(
            "status IN ('confirmed', 'cancelled')",
            name="ck_cafe_reservation_status",
        ),
        CheckConstraint("version >= 1", name="ck_cafe_reservation_version"),
        Index(
            "ix_cafe_reservation_tenant_table_window",
            "tenant_id",
            "cafe_table_id",
            "status",
            "start_at",
            "end_at",
        ),
        Index(
            "ix_cafe_reservation_customer_upcoming",
            "tenant_id",
            "customer_id",
            "status",
            "start_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    cafe_table_id: Mapped[str] = mapped_column(ForeignKey("cafe_tables.id"))
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id"))
    reservation_reference: Mapped[str] = mapped_column(String(24))
    interaction_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    guest_name: Mapped[str] = mapped_column(String(160))
    party_size: Mapped[int] = mapped_column(Integer)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    special_requests: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="confirmed")
    version: Mapped[int] = mapped_column(Integer, default=1)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ReservationToolOperation(Base):
    __tablename__ = "reservation_tool_operations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "voice_session_id",
            "tool_name",
            "request_fingerprint",
            name="uq_reservation_tool_operation_request",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "voice_session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.id"],
            name="fk_reservation_tool_operation_session",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["cafe_reservations.tenant_id", "cafe_reservations.id"],
            name="fk_reservation_tool_operation_reservation",
            ondelete="CASCADE",
        ),
        Index(
            "ix_reservation_tool_operation_session",
            "tenant_id",
            "voice_session_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    voice_session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id"))
    reservation_id: Mapped[str] = mapped_column(ForeignKey("cafe_reservations.id"))
    tool_name: Mapped[str] = mapped_column(String(80))
    request_fingerprint: Mapped[str] = mapped_column(String(64))
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ConversationOutcome(Base):
    __tablename__ = "conversation_outcomes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("voice_sessions.id", ondelete="CASCADE"), unique=True
    )
    interaction_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    resolution: Mapped[str] = mapped_column(String(80), default="unknown")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    final_variables: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class ToolAuditLog(Base):
    __tablename__ = "tool_audit_logs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.id"],
            name="fk_tool_audit_tenant_session",
        ),
        Index("ix_tool_audit_tenant_session", "tenant_id", "session_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    session_id: Mapped[str] = mapped_column(ForeignKey("voice_sessions.id", ondelete="CASCADE"))
    tool_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(40))
    request_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    response_payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
