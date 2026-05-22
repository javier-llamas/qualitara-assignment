from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    SmallInteger,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import ENUM as PgEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class VehicleStatus(StrEnum):
    IDLE = "idle"
    MOVING = "moving"
    CHARGING = "charging"
    FAULT = "fault"


class MissionStatus(StrEnum):
    CURRENT = "current"
    FINISHED = "finished"
    CANCELED = "canceled"


class MaintenanceStatus(StrEnum):
    QUEUED = "queued"
    ONGOING = "ongoing"
    COMPLETE = "complete"


class IncidentType(StrEnum):
    MOVEMENT_UNDER_FAULT = "movement_under_fault"
    OVER_SPEED_LIMIT = "over_speed_limit"
    LOW_BATTERY = "low_battery"
    ERROR_CODE_PRESENT = "error_code_present"
    RAPID_BATTERY_DRAIN = "rapid_battery_drain"
    # Fires when telemetry reports a non-fault status for a vehicle that has an
    # open maintenance report (QUEUED/ONGOING). i.e. dispatch flagged the vehicle
    # for service but the vehicle keeps reporting itself as healthy.
    TELEMETRY_CONTRADICTS_MAINTENANCE = "telemetry_contradicts_maintenance"


# values_callable forces SQLAlchemy to serialize the Enum's .value (e.g. "moving")
# rather than its .name ("MOVING") — Postgres enum labels are the lowercase values.
def _values(enum_cls: type[StrEnum]) -> list[str]:
    return [m.value for m in enum_cls]


vehicle_status_pg = PgEnum(
    VehicleStatus,
    name="vehicle_status",
    create_type=False,
    values_callable=_values,
)
mission_status_pg = PgEnum(
    MissionStatus,
    name="mission_status",
    create_type=False,
    values_callable=_values,
)
maintenance_status_pg = PgEnum(
    MaintenanceStatus,
    name="maintenance_status",
    create_type=False,
    values_callable=_values,
)
incident_type_pg = PgEnum(
    IncidentType,
    name="incident_type",
    create_type=False,
    values_callable=_values,
)


class TelemetryEvent(Base):
    __tablename__ = "telemetry_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    battery_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    speed_mps: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[VehicleStatus] = mapped_column(vehicle_status_pg, nullable=False)
    error_codes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    zone_entered: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("battery_pct BETWEEN 0 AND 100", name="battery_pct_range"),
        CheckConstraint("speed_mps >= 0", name="speed_mps_nonneg"),
        Index("telemetry_vehicle_time_idx", "vehicle_id", text("timestamp DESC")),
        Index(
            "telemetry_zone_idx",
            "zone_entered",
            postgresql_where=text("zone_entered IS NOT NULL"),
        ),
    )


class Mission(Base):
    __tablename__ = "missions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[MissionStatus] = mapped_column(mission_status_pg, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "missions_one_active_per_vehicle_idx",
            "vehicle_id",
            unique=True,
            postgresql_where=text("status = 'current'"),
        ),
    )


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(Text, nullable=False)
    incident_type: Mapped[IncidentType] = mapped_column(
        incident_type_pg, nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    telemetry_event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("telemetry_events.id"), nullable=False
    )
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        Index("incidents_vehicle_time_idx", "vehicle_id", text("timestamp DESC")),
    )


class MaintenanceReport(Base):
    __tablename__ = "maintenance_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    vehicle_id: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    status: Mapped[MaintenanceStatus] = mapped_column(
        maintenance_status_pg, nullable=False
    )
    diagnostics: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancelled_mission_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("missions.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "maintenance_one_open_per_vehicle_idx",
            "vehicle_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'ongoing')"),
        ),
    )
