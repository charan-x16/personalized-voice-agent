"""Add append-only administrator audit events for voice tool changes.

Revision ID: 20260923_0008
Revises: 20260923_0007
Create Date: 2026-09-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_0008"
down_revision: str | None = "20260923_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_tool_admin_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=True),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_display_name", sa.String(length=160), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('voice_tool.created', 'voice_tool.updated', "
            "'customer_voice_tool.updated')",
            name="ck_voice_tool_admin_event_action",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_voice_tool_admin_event_revision"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["voice_tool_definitions.tenant_id", "voice_tool_definitions.id"],
            name="fk_voice_tool_admin_event_tenant_tool",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_voice_tool_admin_event_tenant_customer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_voice_tool_admin_event_tenant_created",
        "voice_tool_admin_events",
        ["tenant_id", "created_at"],
    )
    op.create_index(
        "ix_voice_tool_admin_event_tenant_customer_created",
        "voice_tool_admin_events",
        ["tenant_id", "customer_id", "created_at"],
    )
    op.create_index(
        "ix_voice_tool_admin_event_actor",
        "voice_tool_admin_events",
        ["actor_user_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE voice_tool_admin_events ENABLE ROW LEVEL SECURITY")
        op.execute(
            "REVOKE ALL ON TABLE voice_tool_admin_events FROM anon, authenticated"
        )


def downgrade() -> None:
    op.drop_index(
        "ix_voice_tool_admin_event_actor", table_name="voice_tool_admin_events"
    )
    op.drop_index(
        "ix_voice_tool_admin_event_tenant_customer_created",
        table_name="voice_tool_admin_events",
    )
    op.drop_index(
        "ix_voice_tool_admin_event_tenant_created",
        table_name="voice_tool_admin_events",
    )
    op.drop_table("voice_tool_admin_events")
