/**
 * `SimulationPanel` — roster-capacity rendering (V1-45).
 *
 * RED-FIRST: `src/api/trade_simulator.py` has computed and published a
 * real `rosterCapacity` block (forced drops, cost, upper-bound flag) on
 * every `/api/trade/simulate` response since C3-CAP-01 landed, and this
 * component read none of it — the panel showed "Impact on <team>" with
 * no mention that the trade forces a release. `rosterCapacity` never
 * appeared in `frontend/` outside test files before this fix.
 *
 * Pure display: every field here is a backend stamp
 * (`src/trade/roster_capacity.py::RosterCapacity.to_dict`). No trade
 * math is computed in this component or this test.
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";
import { SimulationPanel } from "@/app/trade/trade-sections";

const BASE_SIM = {
  team: { name: "My Team" },
  before: { totalValue: 1000 },
  after: { totalValue: 1200 },
  delta: { totalValue: 200, byPosition: {} },
  equity: 200,
  unresolvedIn: [],
  unresolvedOut: [],
};

describe("SimulationPanel roster capacity", () => {
  it("renders nothing extra when the trade fits cleanly (requiresDrops: false)", () => {
    render(
      <SimulationPanel
        simResult={{
          ...BASE_SIM,
          rosterCapacity: { requiresDrops: false, rosterLimit: 58 },
        }}
      />,
    );
    expect(screen.queryByText(/Roster capacity/i)).toBeNull();
  });

  it("names the forced release and its cost when requiresDrops is true", () => {
    render(
      <SimulationPanel
        simResult={{
          ...BASE_SIM,
          rosterCapacity: {
            requiresDrops: true,
            rosterLimit: 58,
            forcedDropValue: 1234.5,
            forcedDropsAreUpperBound: false,
            ladderExhausted: false,
            forcedDrops: [
              {
                playerId: "p1",
                name: "Bench Guy",
                position: "WR",
                value: 456.7,
              },
            ],
          },
        }}
      />,
    );
    expect(screen.getByText(/Roster capacity/i)).toBeTruthy();
    expect(screen.getByText(/Forces 1 release/i)).toBeTruthy();
    expect(screen.getByText(/58-man limit/i)).toBeTruthy();
    expect(screen.getByText(/1,235 value released|1,234.5 value released|1,234 value released/i)).toBeTruthy();
    expect(screen.getByText(/Bench Guy/)).toBeTruthy();
  });

  it("marks an upper-bound forced-drop set as worst-case, not certain", () => {
    render(
      <SimulationPanel
        simResult={{
          ...BASE_SIM,
          rosterCapacity: {
            requiresDrops: true,
            rosterLimit: 58,
            forcedDropValue: 100,
            forcedDropsAreUpperBound: true,
            ladderExhausted: false,
            forcedDrops: [{ playerId: "p2", name: "Taxi Maybe", position: "RB", value: 100 }],
          },
        }}
      />,
    );
    expect(screen.getByText(/worst case; taxi occupancy uncertain/i)).toBeTruthy();
  });

  it("shows an unpriced forced drop honestly rather than as zero", () => {
    render(
      <SimulationPanel
        simResult={{
          ...BASE_SIM,
          rosterCapacity: {
            requiresDrops: true,
            rosterLimit: 58,
            forcedDropValue: null,
            forcedDropsAreUpperBound: false,
            ladderExhausted: false,
            forcedDrops: [{ playerId: "p3", name: "Unpriced Guy", position: "TE", value: null }],
          },
        }}
      />,
    );
    expect(screen.getByText(/unpriced/i)).toBeTruthy();
  });

  it("distinguishes unknown certainty from a clean fit (requiresDrops: null)", () => {
    render(
      <SimulationPanel
        simResult={{
          ...BASE_SIM,
          rosterCapacity: { requiresDrops: null, rosterLimit: 58 },
        }}
      />,
    );
    expect(screen.getByText(/taxi occupancy unknown/i)).toBeTruthy();
  });

  it("says the cap itself is unknown when rosterLimit is null", () => {
    render(
      <SimulationPanel
        simResult={{
          ...BASE_SIM,
          rosterCapacity: { requiresDrops: null, rosterLimit: null },
        }}
      />,
    );
    expect(screen.getByText(/Roster capacity unknown for this league/i)).toBeTruthy();
  });

  it("renders nothing when rosterCapacity is absent (older/degraded response)", () => {
    render(<SimulationPanel simResult={{ ...BASE_SIM }} />);
    expect(screen.queryByText(/Roster capacity/i)).toBeNull();
  });
});
