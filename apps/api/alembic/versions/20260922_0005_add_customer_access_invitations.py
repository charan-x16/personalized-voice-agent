"""Add tenant-controlled customer access invitation state.

Revision ID: 20260922_0005
Revises: 20260922_0004
Create Date: 2026-09-22 00:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260922_0005"
down_revision: str | None = "20260922_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("clerk_invitation_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("invitation_status", sa.String(length=32), nullable=True))
        batch_op.add_column(
            sa.Column("invitation_sent_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("invitation_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("invitation_accepted_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("invited_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_users_invitation_status",
            "invitation_status IS NULL OR invitation_status IN "
            "('pending', 'accepted', 'revoked', 'expired', 'failed')",
        )
        batch_op.create_foreign_key(
            "fk_users_invited_by_user",
            "users",
            ["invited_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ux_users_clerk_invitation_id",
            ["clerk_invitation_id"],
            unique=True,
        )
        batch_op.create_index(
            "ix_users_invited_by_user_id",
            ["invited_by_user_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_users_tenant_customer_active",
            ["tenant_id", "customer_id", "is_active"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_index("ix_users_tenant_customer_active")
        batch_op.drop_index("ix_users_invited_by_user_id")
        batch_op.drop_index("ux_users_clerk_invitation_id")
        batch_op.drop_constraint("fk_users_invited_by_user", type_="foreignkey")
        batch_op.drop_constraint("ck_users_invitation_status", type_="check")
        batch_op.drop_column("invited_by_user_id")
        batch_op.drop_column("invitation_accepted_at")
        batch_op.drop_column("invitation_expires_at")
        batch_op.drop_column("invitation_sent_at")
        batch_op.drop_column("invitation_status")
        batch_op.drop_column("clerk_invitation_id")
