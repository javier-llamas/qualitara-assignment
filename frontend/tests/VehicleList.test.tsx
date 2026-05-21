import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { VehicleList } from "../src/components/VehicleList";
import type { VehicleSummary } from "../src/types";

const v: VehicleSummary = {
  vehicle_id: "v-7",
  status: "moving",
  battery_pct: 60,
  speed_mps: 1.23,
  lat: 0,
  lon: 0,
  last_seen_at: new Date().toISOString(),
  latest_incident: null,
};

describe("VehicleList", () => {
  it("renders vehicle row with status and battery", () => {
    render(<VehicleList vehicles={[v]} />);
    expect(screen.getByText("v-7")).toBeInTheDocument();
    expect(screen.getByText("moving")).toBeInTheDocument();
    expect(screen.getByText("60%")).toBeInTheDocument();
  });

  it("renders an em-dash when no incident", () => {
    render(<VehicleList vehicles={[v]} />);
    expect(screen.getByText("—")).toBeInTheDocument();
  });

  it("shows latest anomaly when present", () => {
    const withIncident: VehicleSummary = {
      ...v,
      latest_incident: {
        id: 1,
        vehicle_id: "v-7",
        incident_type: "low_battery",
        timestamp: new Date().toISOString(),
        telemetry_event_id: 1,
        details: {},
      },
    };
    render(<VehicleList vehicles={[withIncident]} />);
    expect(screen.getByText(/low_battery/)).toBeInTheDocument();
  });
});
