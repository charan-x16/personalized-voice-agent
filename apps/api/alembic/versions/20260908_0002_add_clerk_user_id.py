"""Link application users to immutable Clerk user IDs.

Revision ID: 20260908_0002
Revises: 20260903_0001
Create Date: 2026-09-08
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260908_0002"
down_revision: str | None = "20260903_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("clerk_user_id", sa.Text(), nullable=True))
    op.create_index(
        "ux_users_clerk_user_id",
        "users",
        ["clerk_user_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ux_users_clerk_user_id", table_name="users")
    op.drop_column("users", "clerk_user_id")
