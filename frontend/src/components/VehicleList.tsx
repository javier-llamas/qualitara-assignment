import type { VehicleSummary } from "../types";

const statusStyles: Record<string, string> = {
  idle: "bg-zinc-700 text-zinc-100",
  moving: "bg-emerald-700 text-emerald-50",
  charging: "bg-blue-700 text-blue-50",
  fault: "bg-rose-700 text-rose-50",
};

function BatteryBar({ pct }: { pct: number }) {
  const color = pct < 15 ? "bg-rose-500" : pct < 40 ? "bg-amber-500" : "bg-emerald-500";
  return (
    <div className="w-24 h-2 bg-zinc-800 rounded">
      <div
        data-testid="battery-fill"
        className={`h-full rounded ${color}`}
        style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
      />
    </div>
  );
}

export function VehicleList({
  vehicles,
  onSelect,
}: {
  vehicles: VehicleSummary[];
  onSelect?: (vehicleId: string) => void;
}) {
  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h2 className="text-lg font-semibold mb-3">Vehicles ({vehicles.length})</h2>
      <div className="max-h-[60vh] overflow-y-auto">
        <table className="w-full text-sm">
          <thead className="text-xs uppercase text-zinc-400 sticky top-0 bg-zinc-900">
            <tr>
              <th className="text-left py-2">ID</th>
              <th className="text-left">Status</th>
              <th className="text-left">Battery</th>
              <th className="text-left">Speed</th>
              <th className="text-left">Latest anomaly</th>
            </tr>
          </thead>
          <tbody>
            {vehicles.map((v) => (
              <tr
                key={v.vehicle_id}
                onClick={() => onSelect?.(v.vehicle_id)}
                className="border-t border-zinc-800 cursor-pointer hover:bg-zinc-800/60"
              >
                <td className="py-2 font-mono">{v.vehicle_id}</td>
                <td>
                  <span
                    className={`px-2 py-0.5 rounded text-xs ${
                      statusStyles[v.status] ?? "bg-zinc-700"
                    }`}
                  >
                    {v.status}
                  </span>
                </td>
                <td>
                  <div className="flex items-center gap-2">
                    <BatteryBar pct={v.battery_pct} />
                    <span className="tabular-nums text-zinc-400 text-xs">
                      {v.battery_pct}%
                    </span>
                  </div>
                </td>
                <td className="tabular-nums">{v.speed_mps.toFixed(2)} m/s</td>
                <td className="text-xs text-zinc-400">
                  {v.latest_incident ? (
                    <span>
                      {v.latest_incident.incident_type}{" "}
                      <span className="text-zinc-500">
                        {new Date(v.latest_incident.timestamp).toLocaleTimeString()}
                      </span>
                    </span>
                  ) : (
                    <span className="text-zinc-600">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
