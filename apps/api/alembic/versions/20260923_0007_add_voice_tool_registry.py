"""Add tenant tool definitions and per-customer assignments.

Revision ID: 20260923_0007
Revises: 20260923_0006
Create Date: 2026-09-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_0007"
down_revision: str | None = "20260923_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voice_tool_definitions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("tool_key", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=80), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "capability IN ('customer_profile', 'order_status', "
            "'reservation_availability', 'reservation_lookup', 'reservation_create', "
            "'reservation_reschedule', 'reservation_cancel')",
            name="ck_voice_tool_capability",
        ),
        sa.CheckConstraint("revision >= 1", name="ck_voice_tool_revision"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_voice_tool_tenant_id"),
        sa.UniqueConstraint("tenant_id", "tool_key", name="uq_voice_tool_tenant_key"),
    )
    op.create_index(
        "ix_voice_tool_tenant_enabled_key",
        "voice_tool_definitions",
        ["tenant_id", "is_enabled", "tool_key"],
    )
    op.create_index(
        "ix_voice_tool_created_by", "voice_tool_definitions", ["created_by_user_id"]
    )
    op.create_index(
        "ix_voice_tool_updated_by", "voice_tool_definitions", ["updated_by_user_id"]
    )

    op.create_table(
        "customer_voice_tools",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("tool_id", sa.String(length=36), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("updated_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_customer_voice_tool_revision"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_customer_voice_tool_tenant_customer",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "tool_id"],
            ["voice_tool_definitions.tenant_id", "voice_tool_definitions.id"],
            name="fk_customer_voice_tool_tenant_tool",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"], ["users.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("tenant_id", "customer_id", "tool_id"),
    )
    op.create_index(
        "ix_customer_voice_tool_tenant_customer_enabled",
        "customer_voice_tools",
        ["tenant_id", "customer_id", "is_enabled"],
    )
    op.create_index(
        "ix_customer_voice_tool_tenant_tool",
        "customer_voice_tools",
        ["tenant_id", "tool_id"],
    )
    op.create_index(
        "ix_customer_voice_tool_updated_by",
        "customer_voice_tools",
        ["updated_by_user_id"],
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("voice_tool_definitions", "customer_voice_tools"):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"REVOKE ALL ON TABLE {table_name} FROM anon, authenticated")


def downgrade() -> None:
    op.drop_index("ix_customer_voice_tool_updated_by", table_name="customer_voice_tools")
    op.drop_index("ix_customer_voice_tool_tenant_tool", table_name="customer_voice_tools")
    op.drop_index(
        "ix_customer_voice_tool_tenant_customer_enabled",
        table_name="customer_voice_tools",
    )
    op.drop_table("customer_voice_tools")
    op.drop_index("ix_voice_tool_updated_by", table_name="voice_tool_definitions")
    op.drop_index("ix_voice_tool_created_by", table_name="voice_tool_definitions")
    op.drop_index("ix_voice_tool_tenant_enabled_key", table_name="voice_tool_definitions")
    op.drop_table("voice_tool_definitions")
