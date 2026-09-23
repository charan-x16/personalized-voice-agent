"""Add auditable administrator voice-preview session metadata.

Revision ID: 20260922_0004
Revises: 20260909_0003
Create Date: 2026-09-22 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_0004"
down_revision: str | None = "20260909_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("voice_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "session_mode",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'customer'"),
            )
        )
        batch_op.add_column(
            sa.Column("initiated_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_voice_session_mode",
            "session_mode IN ('customer', 'admin_preview')",
        )
        batch_op.create_foreign_key(
            "fk_voice_session_initiated_by_user",
            "users",
            ["initiated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_voice_session_tenant_initiator_started",
            ["tenant_id", "initiated_by_user_id", "started_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("voice_sessions") as batch_op:
        batch_op.drop_index("ix_voice_session_tenant_initiator_started")
        batch_op.drop_constraint(
            "fk_voice_session_initiated_by_user",
            type_="foreignkey",
        )
        batch_op.drop_constraint("ck_voice_session_mode", type_="check")
        batch_op.drop_column("initiated_by_user_id")
        batch_op.drop_column("session_mode")
