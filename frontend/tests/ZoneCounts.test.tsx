import "@testing-library/jest-dom";
import { render, screen } from "@testing-library/react";
import { ZoneCounts } from "../src/components/ZoneCounts";
import { ZONES } from "../src/types";

describe("ZoneCounts", () => {
  it("renders all 20 zones from the constant", () => {
    const counts = ZONES.map((z) => ({ zone: z, entry_count: 0 }));
    render(<ZoneCounts counts={counts} />);
    for (const z of ZONES) {
      expect(screen.getByTestId(`zone-${z}`)).toBeInTheDocument();
    }
  });

  it("shows entry counts", () => {
    const counts = ZONES.map((z) => ({
      zone: z,
      entry_count: z === "charging_bay_1" ? 42 : 0,
    }));
    render(<ZoneCounts counts={counts} />);
    expect(screen.getByTestId("zone-charging_bay_1")).toHaveTextContent("42");
  });
});
