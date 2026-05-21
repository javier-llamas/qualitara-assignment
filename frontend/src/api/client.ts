import type { FleetState, IncidentOut, VehicleSummary, ZoneCount } from "../types";

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
  getAnomalies: (params: { vehicle_id?: string } = {}) => {
    const qs = new URLSearchParams(params as Record<string, string>);
    return jsonFetch<IncidentOut[]>(`/anomalies?${qs.toString()}`);
  },
  setStatus: (vehicleId: string, status: "fault") =>
    jsonFetch<{ status: string; applied: boolean }>(
      `/vehicles/${encodeURIComponent(vehicleId)}/status`,
      { method: "PATCH", body: JSON.stringify({ status }) }
    ),
};

export const STREAM_URL = `${API_BASE}/stream`;
