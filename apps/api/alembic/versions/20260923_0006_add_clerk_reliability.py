"""Add durable Clerk invitation jobs and idempotent webhook receipts.

Revision ID: 20260923_0006
Revises: 20260922_0005
Create Date: 2026-09-23 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260923_0006"
down_revision: str | None = "20260922_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_invitation_status", type_="check")
        batch_op.add_column(
            sa.Column(
                "access_generation",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column("clerk_last_event_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_users_invitation_status",
            "invitation_status IS NULL OR invitation_status IN "
            "('queued', 'pending', 'accepted', 'revoked', 'expired', 'failed')",
        )
        batch_op.create_check_constraint(
            "ck_users_access_generation",
            "access_generation >= 0",
        )

    op.create_table(
        "clerk_invitation_outbox",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=False),
        sa.Column("actor_display_name", sa.String(length=160), nullable=False),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("access_generation", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("invitation_id", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_by", sa.String(length=160), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation IN ('create', 'revoke')",
            name="ck_clerk_invitation_outbox_operation",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'succeeded', 'dead_letter')",
            name="ck_clerk_invitation_outbox_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_clerk_invitation_outbox_attempts",
        ),
        sa.CheckConstraint(
            "access_generation >= 1",
            name="ck_clerk_invitation_outbox_generation",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_clerk_invitation_outbox_tenant_customer",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clerk_invitation_outbox_ready",
        "clerk_invitation_outbox",
        ["status", "available_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_clerk_invitation_outbox_user",
        "clerk_invitation_outbox",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ux_clerk_invitation_outbox_active_operation",
        "clerk_invitation_outbox",
        ["user_id", "operation", "access_generation"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'processing')"),
        sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )

    op.create_table(
        "clerk_webhook_events",
        sa.Column("message_id", sa.String(length=160), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("object_id", sa.String(length=160), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('processed', 'ignored')",
            name="ck_clerk_webhook_events_status",
        ),
        sa.PrimaryKeyConstraint("message_id"),
    )
    op.create_index(
        "ix_clerk_webhook_events_received",
        "clerk_webhook_events",
        ["received_at"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table_name in ("clerk_invitation_outbox", "clerk_webhook_events"):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"REVOKE ALL ON TABLE {table_name} FROM anon, authenticated")


def downgrade() -> None:
    op.drop_index(
        "ix_clerk_webhook_events_received",
        table_name="clerk_webhook_events",
    )
    op.drop_table("clerk_webhook_events")
    op.drop_index(
        "ux_clerk_invitation_outbox_active_operation",
        table_name="clerk_invitation_outbox",
    )
    op.drop_index(
        "ix_clerk_invitation_outbox_user",
        table_name="clerk_invitation_outbox",
    )
    op.drop_index(
        "ix_clerk_invitation_outbox_ready",
        table_name="clerk_invitation_outbox",
    )
    op.drop_table("clerk_invitation_outbox")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_access_generation", type_="check")
        batch_op.drop_constraint("ck_users_invitation_status", type_="check")
        batch_op.create_check_constraint(
            "ck_users_invitation_status",
            "invitation_status IS NULL OR invitation_status IN "
            "('pending', 'accepted', 'revoked', 'expired', 'failed')",
        )
        batch_op.drop_column("clerk_last_event_at")
        batch_op.drop_column("access_generation")
