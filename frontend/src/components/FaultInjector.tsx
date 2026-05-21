import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { VehicleSummary } from "../types";

export function FaultInjector({ vehicles }: { vehicles: VehicleSummary[] }) {
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);

  // Memoize the id list so the <option> children only re-render when the actual
  // set of vehicles changes. Without this, every SSE tick mutates each option's
  // label and the native <select> closes its dropdown mid-click.
  const idsKey = vehicles.map((v) => v.vehicle_id).join("|");
  const vehicleIds = useMemo(() => (idsKey ? idsKey.split("|") : []), [idsKey]);

  const inject = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      await api.setStatus(selected, "fault");
      setToast(`Fault injected for ${selected}`);
    } catch (e) {
      setToast(`Error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
      setTimeout(() => setToast(null), 2500);
    }
  };

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h2 className="text-lg font-semibold mb-3">Inject fault</h2>
      <div className="flex items-center gap-2">
        <select
          aria-label="vehicle"
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="bg-zinc-800 px-2 py-1 rounded border border-zinc-700"
        >
          <option value="">Select vehicle…</option>
          {vehicleIds.map((id) => (
            <option key={id} value={id}>
              {id}
            </option>
          ))}
        </select>
        <button
          onClick={inject}
          disabled={!selected || busy}
          className="bg-rose-700 hover:bg-rose-600 disabled:opacity-40 px-3 py-1 rounded text-sm"
        >
          {busy ? "Injecting…" : "Fault"}
        </button>
        {toast && <span className="text-xs text-zinc-300 ml-2">{toast}</span>}
      </div>
    </div>
  );
}
