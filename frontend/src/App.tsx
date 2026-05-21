import { FaultInjector } from "./components/FaultInjector";
import { FleetAggregate } from "./components/FleetAggregate";
import { VehicleList } from "./components/VehicleList";
import { ZoneCounts } from "./components/ZoneCounts";
import { useFleetState } from "./hooks/useFleetState";
import "./App.css";

export default function App() {
  const { vehicles, fleetState, zoneCounts } = useFleetState();
  return (
    <div className="min-h-screen p-4 md:p-6 space-y-4 max-w-7xl mx-auto">
      <header className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Fleet Telemetry</h1>
        <span className="text-xs text-zinc-400">live via SSE</span>
      </header>
      <FleetAggregate state={fleetState} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 space-y-4">
          <VehicleList vehicles={vehicles} />
        </div>
        <div className="space-y-4">
          <FaultInjector vehicles={vehicles} />
          <ZoneCounts counts={zoneCounts} />
        </div>
      </div>
    </div>
  );
}
