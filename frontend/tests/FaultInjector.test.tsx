import "@testing-library/jest-dom";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { FaultInjector } from "../src/components/FaultInjector";
import type { VehicleSummary } from "../src/types";

const v = (id: string): VehicleSummary => ({
  vehicle_id: id,
  status: "moving",
  battery_pct: 80,
  speed_mps: 1,
  lat: 0,
  lon: 0,
  last_seen_at: new Date().toISOString(),
  latest_incident: null,
});

describe("FaultInjector", () => {
  beforeEach(() => {
    global.fetch = jest.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ status: "fault", applied: true }),
      } as Response),
    ) as unknown as typeof fetch;
  });

  it("calls PATCH /vehicles/{id}/status when injecting", async () => {
    render(<FaultInjector vehicles={[v("v-3"), v("v-4")]} />);
    const select = screen.getByLabelText("vehicle");
    await userEvent.selectOptions(select, "v-4");
    await userEvent.click(screen.getByRole("button", { name: /fault/i }));

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith(
        "/api/vehicles/v-4/status",
        expect.objectContaining({ method: "PATCH" }),
      );
    });
    expect(await screen.findByText(/Fault injected for v-4/)).toBeInTheDocument();
  });
});
