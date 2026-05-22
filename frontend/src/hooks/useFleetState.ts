import { useCallback, useEffect, useState } from "react";
import { api, STREAM_URL } from "../api/client";
import type {
  FleetState,
  IncidentOut,
  IncidentType,
  StreamEvent,
  VehicleStatus,
  VehicleSummary,
  ZoneCount,
} from "../types";
import { ZONES } from "../types";
import { useEventStream } from "./useEventStream";

interface State {
  vehicles: Map<string, VehicleSummary>;
  fleetState: FleetState;
  zoneCounts: Map<string, number>;
  connected: boolean;
}

const empty: State = {
  vehicles: new Map(),
  fleetState: { idle: 0, moving: 0, charging: 0, fault: 0, total: 0 },
  zoneCounts: new Map(ZONES.map((z) => [z, 0])),
  connected: false,
};

function recomputeFleet(vehicles: Map<string, VehicleSummary>): FleetState {
  const out: FleetState = { idle: 0, moving: 0, charging: 0, fault: 0, total: 0 };
  for (const v of vehicles.values()) {
    out[v.status] += 1;
    out.total += 1;
  }
  return out;
}

export function useFleetState() {
  const [state, setState] = useState<State>(empty);

  const resync = useCallback(async () => {
    try {
      const [vehicles, zoneCounts, fleetState] = await Promise.all([
        api.getVehicles(),
        api.getZoneCounts(),
        api.getFleetState(),
      ]);
      setState({
        vehicles: new Map(vehicles.map((v) => [v.vehicle_id, v])),
        fleetState,
        zoneCounts: new Map(zoneCounts.map((z) => [z.zone, z.entry_count])),
        connected: true,
      });
    } catch (e) {
      console.error("resync failed", e);
      setState((s) => ({ ...s, connected: false }));
    }
  }, []);

  useEffect(() => {
    // Fetch the REST baseline once on mount (and on reconnect via onError).
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void resync();
  }, [resync]);

  const onMessage = useCallback((raw: string) => {
    let ev: StreamEvent;
    try {
      ev = JSON.parse(raw);
    } catch {
      return;
    }
    setState((s) => {
      const vehicles = new Map(s.vehicles);
      const zoneCounts = new Map(s.zoneCounts);

      if (ev.type === "telemetry") {
        const d = ev.data as {
          status?: VehicleStatus;
          battery_pct?: number;
          speed_mps?: number;
          lat?: number;
          lon?: number;
          timestamp?: string;
        };
        const existing = vehicles.get(ev.vehicle_id);
        const next: VehicleSummary = {
          vehicle_id: ev.vehicle_id,
          status: d.status ?? existing?.status ?? "idle",
          battery_pct: d.battery_pct ?? existing?.battery_pct ?? 0,
          speed_mps: d.speed_mps ?? existing?.speed_mps ?? 0,
          lat: d.lat ?? existing?.lat ?? 0,
          lon: d.lon ?? existing?.lon ?? 0,
          last_seen_at: d.timestamp ?? ev.ts,
          latest_incident: existing?.latest_incident ?? null,
        };
        vehicles.set(ev.vehicle_id, next);
      } else if (ev.type === "incident") {
        const d = ev.data as {
          incident_id: number;
          incident_type: IncidentType;
          telemetry_id: number;
        };
        const existing = vehicles.get(ev.vehicle_id);
        if (existing) {
          const incident: IncidentOut = {
            id: d.incident_id,
            vehicle_id: ev.vehicle_id,
            incident_type: d.incident_type,
            timestamp: ev.ts,
            telemetry_event_id: d.telemetry_id,
            details: {},
          };
          vehicles.set(ev.vehicle_id, { ...existing, latest_incident: incident });
        }
      } else if (ev.type === "fault") {
        const existing = vehicles.get(ev.vehicle_id);
        if (existing) vehicles.set(ev.vehicle_id, { ...existing, status: "fault" });
      } else if (ev.type === "zone_entered") {
        const zone = ev.data.zone as string;
        zoneCounts.set(zone, (zoneCounts.get(zone) ?? 0) + 1);
      }

      const fleetState = recomputeFleet(vehicles);
      return { ...s, vehicles, fleetState, zoneCounts };
    });
  }, []);

  const onError = useCallback(() => {
    // Resync from REST baseline on reconnect (ADR-001 §7.5 / D6).
    void resync();
  }, [resync]);

  useEventStream(STREAM_URL, onMessage, onError);

  const orderedZoneCounts: ZoneCount[] = ZONES.map((z) => ({
    zone: z,
    entry_count: state.zoneCounts.get(z) ?? 0,
  }));

  return {
    vehicles: Array.from(state.vehicles.values()).sort((a, b) =>
      a.vehicle_id.localeCompare(b.vehicle_id, undefined, { numeric: true }),
    ),
    fleetState: state.fleetState,
    zoneCounts: orderedZoneCounts,
    resync,
  };
}
