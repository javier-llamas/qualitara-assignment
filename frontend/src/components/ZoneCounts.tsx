import { useEffect, useRef } from "react";
import type { ZoneCount } from "../types";

function Cell({ z }: { z: ZoneCount }) {
  const prev = useRef(z.entry_count);
  const cellRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (z.entry_count > prev.current && cellRef.current) {
      cellRef.current.animate(
        [
          { background: "rgba(16,185,129,0.5)" },
          { background: "transparent" },
        ],
        { duration: 600 },
      );
    }
    prev.current = z.entry_count;
  }, [z.entry_count]);

  return (
    <div
      ref={cellRef}
      data-testid={`zone-${z.zone}`}
      className="p-2 rounded border border-zinc-800 text-xs"
    >
      <div className="text-zinc-400 break-words">{z.zone.replace(/_/g, " ")}</div>
      <div className="tabular-nums text-lg font-semibold">{z.entry_count}</div>
    </div>
  );
}

export function ZoneCounts({ counts }: { counts: ZoneCount[] }) {
  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <h2 className="text-lg font-semibold mb-3">Zone entry counts</h2>
      <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-4 gap-2">
        {counts.map((c) => (
          <Cell key={c.zone} z={c} />
        ))}
      </div>
    </div>
  );
}
