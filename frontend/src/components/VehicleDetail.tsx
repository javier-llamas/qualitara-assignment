import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type {
  IncidentOut,
  MaintenanceStatus,
  MissionStatus,
  VehicleDetail as VehicleDetailData,
} from "../types";

const missionStyles: Record<MissionStatus, string> = {
  current: "bg-emerald-900 text-emerald-200",
  finished: "bg-zinc-700 text-zinc-100",
  canceled: "bg-rose-900 text-rose-200",
};

const maintenanceStyles: Record<MaintenanceStatus, string> = {
  queued: "bg-amber-900 text-amber-200",
  ongoing: "bg-blue-900 text-blue-200",
  complete: "bg-zinc-700 text-zinc-100",
};

type Preset = { label: string; minutes: number | null };

const PRESETS: Preset[] = [
  { label: "15m", minutes: 15 },
  { label: "1h", minutes: 60 },
  { label: "24h", minutes: 60 * 24 },
  { label: "All", minutes: null },
];

// datetime-local value (no tz) -> ISO 8601 in UTC for the API.
function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const d = new Date(local);
  return Number.isNaN(d.getTime()) ? undefined : d.toISOString();
}

function Badge({ className, children }: { className: string; children: React.ReactNode }) {
  return (
    <span className={`px-2 py-0.5 rounded text-xs ${className}`}>{children}</span>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-sm font-semibold uppercase text-zinc-400 mb-2">{title}</h3>
      {children}
    </section>
  );
}

export function VehicleDetail({
  vehicleId,
  onClose,
}: {
  vehicleId: string;
  onClose: () => void;
}) {
  const [detail, setDetail] = useState<VehicleDetailData | null>(null);
  const [incidents, setIncidents] = useState<IncidentOut[]>([]);
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Mission + maintenance load once per vehicle.
  useEffect(() => {
    let cancelled = false;
    api
      .getVehicleDetail(vehicleId)
      .then((d) => !cancelled && setDetail(d))
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [vehicleId]);

  // Incidents re-fetch whenever the time range changes.
  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setLoading(true);
    api
      .getAnomalies({
        vehicle_id: vehicleId,
        since: toIso(since),
        until: toIso(until),
      })
      .then((rows) => {
        if (cancelled) return;
        setIncidents(rows);
        setError(null);
      })
      .catch((e) => !cancelled && setError((e as Error).message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [vehicleId, since, until]);

  const applyPreset = useCallback((p: Preset) => {
    setUntil("");
    if (p.minutes === null) {
      setSince("");
      return;
    }
    const d = new Date(Date.now() - p.minutes * 60_000);
    // Build a datetime-local string in the user's local time.
    const pad = (n: number) => String(n).padStart(2, "0");
    setSince(
      `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(
        d.getHours()
      )}:${pad(d.getMinutes())}`
    );
  }, []);

  const mission = detail?.current_mission ?? null;
  const reports = detail?.maintenance_reports ?? [];
  const rangeLabel = useMemo(() => {
    if (!since && !until) return "all time";
    if (since && !until) return `since ${new Date(since).toLocaleString()}`;
    if (!since && until) return `until ${new Date(until).toLocaleString()}`;
    return `${new Date(since).toLocaleString()} → ${new Date(until).toLocaleString()}`;
  }, [since, until]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-zinc-900 rounded-lg w-full max-w-2xl my-8 shadow-xl border border-zinc-800"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h2 className="text-lg font-semibold">
            Vehicle <span className="font-mono">{vehicleId}</span>
          </h2>
          <button
            onClick={onClose}
            aria-label="close"
            className="text-zinc-400 hover:text-zinc-100 px-2 py-1 rounded"
          >
            ✕
          </button>
        </header>

        <div className="p-4 space-y-6">
          {error && (
            <div className="bg-rose-950 text-rose-200 text-sm rounded p-2">{error}</div>
          )}

          <Section title="Current mission">
            {mission ? (
              <div className="rounded border border-zinc-800 p-3 text-sm space-y-1">
                <div className="flex items-center gap-2">
                  <span className="font-mono text-zinc-300">#{mission.id}</span>
                  <Badge className={missionStyles[mission.status]}>{mission.status}</Badge>
                </div>
                <div className="text-zinc-300">
                  {mission.description ?? <span className="text-zinc-600">no description</span>}
                </div>
                <div className="text-xs text-zinc-500">
                  started {new Date(mission.started_at).toLocaleString()}
                </div>
              </div>
            ) : (
              <div className="text-sm text-zinc-600">No active mission.</div>
            )}
          </Section>

          <Section title={`Maintenance reports (${reports.length})`}>
            {reports.length ? (
              <ul className="space-y-2">
                {reports.map((r) => (
                  <li
                    key={r.id}
                    className="rounded border border-zinc-800 p-3 text-sm space-y-1"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-zinc-300">#{r.id}</span>
                      <Badge className={maintenanceStyles[r.status]}>{r.status}</Badge>
                      <span className="text-xs text-zinc-500 ml-auto">
                        {new Date(r.timestamp).toLocaleString()}
                      </span>
                    </div>
                    {r.diagnostics && (
                      <div className="text-zinc-300">{r.diagnostics}</div>
                    )}
                    {r.cancelled_mission_id != null && (
                      <div className="text-xs text-zinc-500">
                        cancelled mission #{r.cancelled_mission_id}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-zinc-600">No maintenance reports.</div>
            )}
          </Section>

          <Section title="Recent incidents">
            <div className="flex flex-wrap items-end gap-3 mb-3">
              <div className="flex gap-1">
                {PRESETS.map((p) => (
                  <button
                    key={p.label}
                    onClick={() => applyPreset(p)}
                    className="bg-zinc-800 hover:bg-zinc-700 text-xs px-2 py-1 rounded border border-zinc-700"
                  >
                    {p.label}
                  </button>
                ))}
              </div>
              <label className="text-xs text-zinc-400 flex flex-col gap-1">
                Since
                <input
                  type="datetime-local"
                  value={since}
                  onChange={(e) => setSince(e.target.value)}
                  className="bg-zinc-800 px-2 py-1 rounded border border-zinc-700 text-zinc-100"
                />
              </label>
              <label className="text-xs text-zinc-400 flex flex-col gap-1">
                Until
                <input
                  type="datetime-local"
                  value={until}
                  onChange={(e) => setUntil(e.target.value)}
                  className="bg-zinc-800 px-2 py-1 rounded border border-zinc-700 text-zinc-100"
                />
              </label>
            </div>

            <div className="text-xs text-zinc-500 mb-2">
              Showing {incidents.length} incident{incidents.length === 1 ? "" : "s"} ·{" "}
              {rangeLabel}
            </div>

            {loading ? (
              <div className="text-sm text-zinc-500">Loading…</div>
            ) : incidents.length ? (
              <ul className="space-y-2 max-h-72 overflow-y-auto">
                {incidents.map((inc) => (
                  <li
                    key={inc.id}
                    className="rounded border border-zinc-800 p-2 text-sm flex items-start gap-2"
                  >
                    <Badge className="bg-rose-900 text-rose-200">
                      {inc.incident_type}
                    </Badge>
                    <span className="text-xs text-zinc-500 ml-auto whitespace-nowrap">
                      {new Date(inc.timestamp).toLocaleString()}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="text-sm text-zinc-600">No incidents in this range.</div>
            )}
          </Section>
        </div>
      </div>
    </div>
  );
}
