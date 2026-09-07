"""Create the complete initial Svara schema.

Revision ID: 20260903_0001
Revises: None
Create Date: 2026-09-03
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "customers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("external_ref", sa.String(length=120), nullable=False),
        sa.Column("full_name", sa.String(length=160), nullable=False),
        sa.Column("preferred_language", sa.String(length=40), nullable=False),
        sa.Column("plan_name", sa.String(length=80), nullable=False),
        sa.Column("phone_hash", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "external_ref",
            name="uq_customer_tenant_external_ref",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customer_tenant_id"),
    )
    op.create_index("ix_customer_tenant", "customers", ["tenant_id"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("display_name", sa.String(length=160), nullable=False),
        sa.Column("role", sa.String(length=40), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_user_tenant_customer",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_user_tenant_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"], unique=False)

    op.create_table(
        "customer_orders",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("external_ref", sa.String(length=120), nullable=False),
        sa.Column("status", sa.String(length=80), nullable=False),
        sa.Column("estimated_arrival", sa.String(length=160), nullable=True),
        sa.Column("delivery_city", sa.String(length=120), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_order_tenant_customer",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "external_ref",
            name="uq_order_tenant_external_ref",
        ),
    )
    op.create_index(
        "ix_order_tenant_customer",
        "customer_orders",
        ["tenant_id", "customer_id"],
        unique=False,
    )

    op.create_table(
        "customer_profile_states",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_profile_state_tenant_customer",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "customer_id"),
    )
    op.create_index(
        "ix_customer_profile_state_tenant_customer",
        "customer_profile_states",
        ["tenant_id", "customer_id"],
        unique=False,
    )

    op.create_table(
        "customer_agent_configurations",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column(
            "display_name",
            sa.String(length=80),
            server_default=sa.text("'Asha'"),
            nullable=False,
        ),
        sa.Column(
            "opening_message",
            sa.String(length=500),
            server_default=sa.text("'Hello {first_name}, how can I help you today?'"),
            nullable=False,
        ),
        sa.Column(
            "tone",
            sa.String(length=20),
            server_default=sa.text("'professional'"),
            nullable=False,
        ),
        sa.Column(
            "instructions",
            sa.Text(),
            server_default=sa.text(
                "'Help the customer clearly, use only verified account information, "
                "and protect their privacy.'"
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "tone IN ('warm', 'professional', 'concise')",
            name="ck_customer_agent_configuration_tone",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_agent_configuration_tenant_customer",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "customer_id"),
    )
    op.create_index(
        "ix_customer_agent_configuration_tenant_customer",
        "customer_agent_configurations",
        ["tenant_id", "customer_id"],
        unique=False,
    )

    op.create_table(
        "voice_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("provider_session_id", sa.String(length=160), nullable=True),
        sa.Column("provider_interaction_id", sa.String(length=160), nullable=True),
        sa.Column("conversation_ref_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("active_slot", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(length=40), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_voice_session_tenant_customer",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "customer_id",
            "active_slot",
            name="uq_voice_session_active_customer",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_voice_session_tenant_id"),
    )
    op.create_index(
        "ix_voice_session_reference_hash",
        "voice_sessions",
        ["conversation_ref_hash"],
        unique=True,
    )
    op.create_index(
        "ix_voice_session_tenant_customer",
        "voice_sessions",
        ["tenant_id", "customer_id"],
        unique=False,
    )

    op.create_table(
        "conversation_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("interaction_id", sa.String(length=160), nullable=True),
        sa.Column("resolution", sa.String(length=80), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=False),
        sa.Column("final_variables", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["voice_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id"),
    )

    op.create_table(
        "tool_audit_logs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["voice_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.id"],
            name="fk_tool_audit_tenant_session",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_tool_audit_tenant_session",
        "tool_audit_logs",
        ["tenant_id", "session_id"],
        unique=False,
    )

    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_display_name", sa.String(length=160), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_admin_audit_event_tenant_customer",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_admin_audit_event_tenant_actor",
        "admin_audit_events",
        ["tenant_id", "actor_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_admin_audit_event_tenant_customer_created",
        "admin_audit_events",
        ["tenant_id", "customer_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_admin_audit_event_tenant_customer_created",
        table_name="admin_audit_events",
    )
    op.drop_index("ix_admin_audit_event_tenant_actor", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
    op.drop_index("ix_tool_audit_tenant_session", table_name="tool_audit_logs")
    op.drop_table("tool_audit_logs")
    op.drop_table("conversation_outcomes")
    op.drop_index("ix_voice_session_tenant_customer", table_name="voice_sessions")
    op.drop_index("ix_voice_session_reference_hash", table_name="voice_sessions")
    op.drop_table("voice_sessions")
    op.drop_index(
        "ix_customer_agent_configuration_tenant_customer",
        table_name="customer_agent_configurations",
    )
    op.drop_table("customer_agent_configurations")
    op.drop_index(
        "ix_customer_profile_state_tenant_customer",
        table_name="customer_profile_states",
    )
    op.drop_table("customer_profile_states")
    op.drop_index("ix_order_tenant_customer", table_name="customer_orders")
    op.drop_table("customer_orders")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_customer_tenant", table_name="customers")
    op.drop_table("customers")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
