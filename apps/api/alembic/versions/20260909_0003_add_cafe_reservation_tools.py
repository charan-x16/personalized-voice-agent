"""Add tenant-safe cafe reservation policies, tables, and bookings.

Revision ID: 20260909_0003
Revises: 20260908_0002
Create Date: 2026-09-09 15:39:14.648133
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260909_0003"
down_revision: str | None = "20260908_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reservation_policies",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("service_provider_name", sa.String(length=160), nullable=False),
        sa.Column("service_location", sa.String(length=160), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("opening_time", sa.Time(), nullable=False),
        sa.Column("closing_time", sa.Time(), nullable=False),
        sa.Column("slot_interval_minutes", sa.Integer(), nullable=False),
        sa.Column("reservation_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("max_party_size", sa.Integer(), nullable=False),
        sa.Column("advance_booking_days", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "opening_time < closing_time",
            name="ck_reservation_policy_business_hours",
        ),
        sa.CheckConstraint(
            "slot_interval_minutes BETWEEN 5 AND 240",
            name="ck_reservation_policy_slot_interval",
        ),
        sa.CheckConstraint(
            "reservation_duration_minutes BETWEEN 15 AND 480",
            name="ck_reservation_policy_duration",
        ),
        sa.CheckConstraint(
            "max_party_size BETWEEN 1 AND 100",
            name="ck_reservation_policy_max_party_size",
        ),
        sa.CheckConstraint(
            "advance_booking_days BETWEEN 1 AND 365",
            name="ck_reservation_policy_advance_days",
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("tenant_id"),
    )

    op.create_table(
        "cafe_tables",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("capacity BETWEEN 1 AND 100", name="ck_cafe_table_capacity"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cafe_table_tenant_id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_cafe_table_tenant_name"),
    )
    op.create_index(
        "ix_cafe_table_tenant_active_capacity",
        "cafe_tables",
        ["tenant_id", "is_active", "capacity"],
        unique=False,
    )

    op.create_table(
        "cafe_reservations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("customer_id", sa.String(length=36), nullable=False),
        sa.Column("cafe_table_id", sa.String(length=36), nullable=False),
        sa.Column("voice_session_id", sa.String(length=36), nullable=False),
        sa.Column("reservation_reference", sa.String(length=24), nullable=False),
        sa.Column("interaction_id", sa.String(length=160), nullable=True),
        sa.Column("guest_name", sa.String(length=160), nullable=False),
        sa.Column("party_size", sa.Integer(), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("special_requests", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("end_at > start_at", name="ck_cafe_reservation_time_range"),
        sa.CheckConstraint(
            "party_size BETWEEN 1 AND 100",
            name="ck_cafe_reservation_party_size",
        ),
        sa.CheckConstraint(
            "status IN ('confirmed', 'cancelled')",
            name="ck_cafe_reservation_status",
        ),
        sa.CheckConstraint("version >= 1", name="ck_cafe_reservation_version"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["cafe_table_id"], ["cafe_tables.id"]),
        sa.ForeignKeyConstraint(["voice_session_id"], ["voice_sessions.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"],
            ["customers.tenant_id", "customers.id"],
            name="fk_cafe_reservation_tenant_customer",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "cafe_table_id"],
            ["cafe_tables.tenant_id", "cafe_tables.id"],
            name="fk_cafe_reservation_tenant_table",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "voice_session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.id"],
            name="fk_cafe_reservation_tenant_voice_session",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_cafe_reservation_tenant_id"),
        sa.UniqueConstraint(
            "tenant_id",
            "reservation_reference",
            name="uq_cafe_reservation_tenant_reference",
        ),
    )
    op.create_index(
        "ix_cafe_reservation_tenant_table_window",
        "cafe_reservations",
        ["tenant_id", "cafe_table_id", "status", "start_at", "end_at"],
        unique=False,
    )
    op.create_index(
        "ix_cafe_reservation_customer_upcoming",
        "cafe_reservations",
        ["tenant_id", "customer_id", "status", "start_at"],
        unique=False,
    )

    op.create_table(
        "reservation_tool_operations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("voice_session_id", sa.String(length=36), nullable=False),
        sa.Column("reservation_id", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["voice_session_id"], ["voice_sessions.id"]),
        sa.ForeignKeyConstraint(["reservation_id"], ["cafe_reservations.id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "voice_session_id"],
            ["voice_sessions.tenant_id", "voice_sessions.id"],
            name="fk_reservation_tool_operation_session",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "reservation_id"],
            ["cafe_reservations.tenant_id", "cafe_reservations.id"],
            name="fk_reservation_tool_operation_reservation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "voice_session_id",
            "tool_name",
            "request_fingerprint",
            name="uq_reservation_tool_operation_request",
        ),
    )
    op.create_index(
        "ix_reservation_tool_operation_session",
        "reservation_tool_operations",
        ["tenant_id", "voice_session_id"],
        unique=False,
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist WITH SCHEMA extensions")
        op.execute(
            """
            ALTER TABLE cafe_reservations
            ADD CONSTRAINT ex_cafe_reservation_no_confirmed_overlap
            EXCLUDE USING gist (
                tenant_id WITH =,
                cafe_table_id WITH =,
                tstzrange(start_at, end_at, '[)') WITH &&
            ) WHERE (status = 'confirmed')
            """
        )
        for table_name in (
            "reservation_policies",
            "cafe_tables",
            "cafe_reservations",
            "reservation_tool_operations",
        ):
            op.execute(f"ALTER TABLE {table_name} ENABLE ROW LEVEL SECURITY")
            op.execute(f"REVOKE ALL ON TABLE {table_name} FROM anon, authenticated")


def downgrade() -> None:
    op.drop_index(
        "ix_reservation_tool_operation_session",
        table_name="reservation_tool_operations",
    )
    op.drop_table("reservation_tool_operations")
    op.drop_index(
        "ix_cafe_reservation_customer_upcoming",
        table_name="cafe_reservations",
    )
    op.drop_index(
        "ix_cafe_reservation_tenant_table_window",
        table_name="cafe_reservations",
    )
    op.drop_table("cafe_reservations")
    op.drop_index(
        "ix_cafe_table_tenant_active_capacity",
        table_name="cafe_tables",
    )
    op.drop_table("cafe_tables")
    op.drop_table("reservation_policies")
