import type { FleetState } from "../types";

const styles: Record<keyof Omit<FleetState, "total">, string> = {
  idle: "bg-zinc-800 text-zinc-200",
  moving: "bg-emerald-900 text-emerald-200",
  charging: "bg-blue-900 text-blue-200",
  fault: "bg-rose-900 text-rose-200",
};

export function FleetAggregate({ state }: { state: FleetState }) {
  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h2 className="text-lg font-semibold mb-3">
        Fleet state <span className="text-zinc-400 text-sm">({state.total} vehicles)</span>
      </h2>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {(Object.keys(styles) as Array<keyof typeof styles>).map((k) => (
          <div
            key={k}
            data-testid={`fleet-${k}`}
            className={`p-3 rounded ${styles[k]} flex flex-col items-start`}
          >
            <span className="text-xs uppercase opacity-70">{k}</span>
            <span className="text-3xl font-bold tabular-nums">{state[k]}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
