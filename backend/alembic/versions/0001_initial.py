"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enum types owned here (not by per-table CREATE TYPE).
    op.execute(
        "CREATE TYPE vehicle_status AS ENUM ('idle', 'moving', 'charging', 'fault')"
    )
    op.execute("CREATE TYPE mission_status AS ENUM ('current', 'finished', 'canceled')")
    op.execute(
        "CREATE TYPE maintenance_status AS ENUM ('queued', 'ongoing', 'complete')"
    )
    op.execute(
        "CREATE TYPE incident_type AS ENUM ("
        "'movement_under_fault','over_speed_limit','low_battery',"
        "'error_code_present','rapid_battery_drain')"
    )

    op.create_table(
        "telemetry_events",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("vehicle_id", sa.Text, nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lat", sa.Float, nullable=False),
        sa.Column("lon", sa.Float, nullable=False),
        sa.Column("battery_pct", sa.SmallInteger, nullable=False),
        sa.Column("speed_mps", sa.Float, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="vehicle_status", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "error_codes",
            postgresql.ARRAY(sa.Text),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("zone_entered", sa.Text, nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("battery_pct BETWEEN 0 AND 100", name="battery_pct_range"),
        sa.CheckConstraint("speed_mps >= 0", name="speed_mps_nonneg"),
    )
    op.execute(
        "CREATE INDEX telemetry_vehicle_time_idx ON telemetry_events (vehicle_id, timestamp DESC)"
    )
    op.execute(
        "CREATE INDEX telemetry_zone_idx "
        "ON telemetry_events (zone_entered) WHERE zone_entered IS NOT NULL"
    )

    op.create_table(
        "missions",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("vehicle_id", sa.Text, nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM(name="mission_status", create_type=False),
            nullable=False,
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        "CREATE UNIQUE INDEX missions_one_active_per_vehicle_idx "
        "ON missions (vehicle_id) WHERE status = 'current'"
    )

    op.create_table(
        "incidents",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("vehicle_id", sa.Text, nullable=False),
        sa.Column(
            "incident_type",
            postgresql.ENUM(name="incident_type", create_type=False),
            nullable=False,
        ),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "telemetry_event_id",
            sa.BigInteger,
            sa.ForeignKey("telemetry_events.id"),
            nullable=False,
        ),
        sa.Column(
            "details",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.execute(
        "CREATE INDEX incidents_vehicle_time_idx ON incidents (vehicle_id, timestamp DESC)"
    )

    op.create_table(
        "maintenance_reports",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("vehicle_id", sa.Text, nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "status",
            postgresql.ENUM(name="maintenance_status", create_type=False),
            nullable=False,
        ),
        sa.Column("diagnostics", sa.Text, nullable=True),
        sa.Column(
            "cancelled_mission_id",
            sa.BigInteger,
            sa.ForeignKey("missions.id"),
            nullable=True,
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX maintenance_one_open_per_vehicle_idx "
        "ON maintenance_reports (vehicle_id) WHERE status IN ('queued', 'ongoing')"
    )


def downgrade() -> None:
    op.drop_table("maintenance_reports")
    op.drop_table("incidents")
    op.drop_table("missions")
    op.drop_table("telemetry_events")
    op.execute("DROP TYPE IF EXISTS incident_type")
    op.execute("DROP TYPE IF EXISTS maintenance_status")
    op.execute("DROP TYPE IF EXISTS mission_status")
    op.execute("DROP TYPE IF EXISTS vehicle_status")
