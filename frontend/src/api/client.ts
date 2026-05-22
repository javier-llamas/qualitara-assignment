import type {
  FleetState,
  IncidentOut,
  VehicleDetail,
  VehicleSummary,
  ZoneCount,
} from "../types";

const API_BASE = "/api";

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
}

export const api = {
  getVehicles: () => jsonFetch<VehicleSummary[]>("/vehicles"),
  getZoneCounts: () => jsonFetch<ZoneCount[]>("/zones/counts"),
  getFleetState: () => jsonFetch<FleetState>("/fleet/state"),
  getAnomalies: (
    params: {
      vehicle_id?: string;
      since?: string;
      until?: string;
      limit?: number;
    } = {}
  ) => {
    const qs = new URLSearchParams();
    if (params.vehicle_id) qs.set("vehicle_id", params.vehicle_id);
    if (params.since) qs.set("since", params.since);
    if (params.until) qs.set("until", params.until);
    if (params.limit != null) qs.set("limit", String(params.limit));
    return jsonFetch<IncidentOut[]>(`/anomalies?${qs.toString()}`);
  },
  getVehicleDetail: (vehicleId: string) =>
    jsonFetch<VehicleDetail>(
      `/vehicles/${encodeURIComponent(vehicleId)}/detail`
    ),
  setStatus: (vehicleId: string, status: "fault") =>
    jsonFetch<{ status: string; applied: boolean }>(
      `/vehicles/${encodeURIComponent(vehicleId)}/status`,
      { method: "PATCH", body: JSON.stringify({ status }) }
    ),
};

export const STREAM_URL = `${API_BASE}/stream`;
