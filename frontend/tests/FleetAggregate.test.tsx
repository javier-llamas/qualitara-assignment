import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { FleetAggregate } from "../src/components/FleetAggregate";

describe("FleetAggregate", () => {
  it("renders four counters", () => {
    render(
      <FleetAggregate
        state={{ idle: 5, moving: 30, charging: 10, fault: 2, total: 47 }}
      />,
    );
    expect(screen.getByTestId("fleet-idle")).toHaveTextContent("5");
    expect(screen.getByTestId("fleet-moving")).toHaveTextContent("30");
    expect(screen.getByTestId("fleet-charging")).toHaveTextContent("10");
    expect(screen.getByTestId("fleet-fault")).toHaveTextContent("2");
    expect(screen.getByText(/47 vehicles/)).toBeInTheDocument();
  });
});
