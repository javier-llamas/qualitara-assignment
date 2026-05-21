// Mirrors backend/app/zones.py
export const ZONES = [
  "inbound_dock_a",
  "inbound_dock_b",
  "receiving_staging",
  "aisle_a",
  "aisle_b",
  "aisle_c",
  "high_bay_1",
  "high_bay_2",
  "bulk_storage",
  "pick_zone_1",
  "pick_zone_2",
  "pack_station",
  "sort_belt",
  "outbound_dock_a",
  "outbound_dock_b",
  "shipping_staging",
  "charging_bay_1",
  "charging_bay_2",
  "charging_bay_3",
  "maintenance_bay",
] as const;

export type Zone = (typeof ZONES)[number];

export type VehicleStatus = "idle" | "moving" | "charging" | "fault";

export type IncidentType =
  | "movement_under_fault"
  | "over_speed_limit"
  | "low_battery"
  | "error_code_present"
  | "rapid_battery_drain"
  | "telemetry_contradicts_maintenance";

export interface IncidentOut {
  id: number;
  vehicle_id: string;
  incident_type: IncidentType;
  timestamp: string;
  telemetry_event_id: number;
  details: Record<string, unknown>;
}

export interface VehicleSummary {
  vehicle_id: string;
  status: VehicleStatus;
  battery_pct: number;
  speed_mps: number;
  lat: number;
  lon: number;
  last_seen_at: string;
  latest_incident: IncidentOut | null;
}

export interface FleetState {
  idle: number;
  moving: number;
  charging: number;
  fault: number;
  total: number;
}

export interface ZoneCount {
  zone: string;
  entry_count: number;
}

export type StreamEventType = "telemetry" | "incident" | "fault" | "zone_entered";

export interface StreamEvent {
  v: number;
  type: StreamEventType;
  vehicle_id: string;
  data: Record<string, any>;
  ts: string;
}
