from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .models import IncidentType, MaintenanceStatus, MissionStatus, VehicleStatus


class TelemetryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vehicle_id: str
    timestamp: datetime
    lat: float
    lon: float
    battery_pct: int = Field(ge=0, le=100)
    speed_mps: float = Field(ge=0)
    status: VehicleStatus
    error_codes: list[str] = Field(default_factory=list)
    zone_entered: str | None = None


class TelemetryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: str
    timestamp: datetime
    lat: float
    lon: float
    battery_pct: int
    speed_mps: float
    status: VehicleStatus
    error_codes: list[str]
    zone_entered: str | None
    received_at: datetime


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: str
    incident_type: IncidentType
    timestamp: datetime
    telemetry_event_id: int
    details: dict


class VehicleSummary(BaseModel):
    vehicle_id: str
    status: VehicleStatus
    battery_pct: int
    speed_mps: float
    lat: float
    lon: float
    last_seen_at: datetime
    latest_incident: IncidentOut | None = None


class FleetState(BaseModel):
    idle: int = 0
    moving: int = 0
    charging: int = 0
    fault: int = 0
    total: int = 0


class ZoneCount(BaseModel):
    zone: str
    entry_count: int


class StatusUpdate(BaseModel):
    status: VehicleStatus


class IngestResult(BaseModel):
    telemetry_id: int
    incidents: list[IncidentOut]


class MaintenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: str
    timestamp: datetime
    status: MaintenanceStatus
    diagnostics: str | None
    cancelled_mission_id: int | None


class MissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    vehicle_id: str
    status: MissionStatus
    description: str | None
    started_at: datetime
    ended_at: datetime | None


# SSE event payload
StreamEventType = Literal["telemetry", "incident", "fault", "zone_entered"]


class StreamEvent(BaseModel):
    v: int = 1
    type: StreamEventType
    vehicle_id: str
    data: dict
    ts: datetime
