from __future__ import annotations

from datetime import UTC, datetime
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
    UniqueConstraint,
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
    display_name: Mapped[str] = mapped_column(String(160))
    role: Mapped[str] = mapped_column(String(40), default="customer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


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
        Index("ix_voice_session_reference_hash", "conversation_ref_hash", unique=True),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
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
