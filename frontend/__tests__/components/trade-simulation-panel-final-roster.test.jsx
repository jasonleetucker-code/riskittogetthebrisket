/**
 * `SimulationPanel` — final-roster rendering (V1-45).
 *
 * RED-FIRST, and the gap is the same shape as this file's sibling.
 * Since V1-42 (`VERIFIED`) `POST /api/trade/simulate` has published a
 * `finalRosterSimulation` block: the lineup RE-SOLVED after the trade
 * *and its forced cleanup*, with Team Strength before/after. Measured
 * on `main` (`b857d07c0`): 4 references in `src/api/trade_simulator.py`,
 * **0** anywhere in `frontend/`. The backend answered a question the UI
 * never asked.
 *
 * That block is not a second copy of `rosterCapacity`. Capacity says WHO
 * must go; this says what the roster IS once they have — releasing the
 * cheapest legal body can vacate a FLEX seat and promote a player the
 * trade never mentioned.
 *
 * Pure display: every field here is a backend stamp
 * (`src/roster_intel/simulation.py::RosterSimulation.to_dict` plus
 * `cleanupApplied` / `cleanupIsUpperBound` from
 * `src/trade/roster_capacity.py::simulate_final_legal_roster`). No trade
 * math is computed in the component or in this test — see
 * `reads the stamped strengthDelta rather than recomputing it`, which is
 * deliberately self-inconsistent so that only a READER can pass it.
 *
 * FOUR states, not three. The backend emits `populated`,
 * `capacity_uncertain`, `unavailable` — and ABSENT, which is the ordinary
 * state of an un-teamed what-if and must render nothing at all.
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

/** A populated block, in the exact shape the backend stamps. */
function populated(overrides = {}) {
  return {
    available: true,
    unavailableReason: null,
    strengthBefore: { total: 12000 },
    strengthAfter: { total: 12750 },
    strengthDelta: 750,
    coreBefore: {},
    coreAfter: {},
    weaknessBefore: null,
    weaknessAfter: null,
    needsFixed: [],
    needsCreated: [],
    movements: [],
    promotions: [],
    displacements: [],
    unpricedIncoming: [],
    outgoingNotFound: [],
    cleanupApplied: [],
    cleanupIsUpperBound: false,
    notes: [],
    ...overrides,
  };
}

function renderSim(finalRosterSimulation) {
  return render(
    <SimulationPanel
      simResult={
        finalRosterSimulation === undefined
          ? { ...BASE_SIM }
          : { ...BASE_SIM, finalRosterSimulation }
      }
    />,
  );
}

describe("SimulationPanel final roster — the four states", () => {
  it("renders nothing at all when the block is ABSENT", () => {
    renderSim(undefined);
    // Non-vacuity: the panel itself DID render, so "no final-roster copy"
    // cannot pass because nothing rendered.
    expect(screen.getByText(/Impact on My Team/i)).toBeTruthy();
    expect(screen.queryByText(/Final roster/i)).toBeNull();
    expect(screen.queryByText(/Not simulated/i)).toBeNull();
  });

  it("renders the re-solved strength when the block is POPULATED", () => {
    renderSim(populated());
    expect(screen.getByText(/Final roster/i)).toBeTruthy();
    expect(screen.getByText("12,000")).toBeTruthy();
    expect(screen.getByText("12,750")).toBeTruthy();
    expect(screen.getByText("+750")).toBeTruthy();
  });

  it("names the CAPACITY_UNCERTAIN refusal in its own words", () => {
    renderSim({
      available: false,
      unavailableReason: "capacity_uncertain",
      notes: ["taxi membership is unknown"],
    });
    expect(screen.getByText(/Not simulated/i)).toBeTruthy();
    expect(screen.getByText(/taxi occupancy is unknown/i)).toBeTruthy();
    // It must point at the sibling block, exactly as the backend note does.
    expect(screen.getByText(/Roster capacity/i)).toBeTruthy();
    // And it is NOT the generic unavailable copy.
    expect(screen.queryByText(/starting slots/i)).toBeNull();
  });

  it("names the STARTER_SLOTS_UNRESOLVED refusal distinctly", () => {
    renderSim({
      available: false,
      unavailableReason: "starter_slots_unresolved",
      notes: [],
    });
    expect(screen.getByText(/starting slots did not resolve/i)).toBeTruthy();
    expect(screen.queryByText(/taxi occupancy is unknown/i)).toBeNull();
  });

  it("FAILS CLOSED on the exception shape, which carries no `available` key", () => {
    // `trade_simulator.py` stamps {"unavailable": "<ExcType>"} on error —
    // no `available` key at all. A predicate written as `available !== false`
    // would read `undefined` and render this as a real simulation.
    renderSim({ unavailable: "ValueError", notes: ["could not be simulated"] });
    expect(screen.getByText(/Not simulated/i)).toBeTruthy();
    expect(screen.getByText(/ValueError/)).toBeTruthy();
    // Nothing that only a populated block can produce.
    expect(screen.queryByText(/Strength after/i)).toBeNull();
  });
});

describe("SimulationPanel final roster — what it reports", () => {
  it("reads the stamped strengthDelta rather than recomputing it", () => {
    // DELIBERATELY SELF-INCONSISTENT. 500 - 100 = 400, but the backend
    // stamped 7. The component must publish the backend's number: it is
    // a materializer, not a calculator, and this file's own header says
    // "NO trade math lives in this file". A client-side subtraction
    // passes every other test here and fails this one.
    renderSim(
      populated({
        strengthBefore: { total: 100 },
        strengthAfter: { total: 500 },
        strengthDelta: 7,
      }),
    );
    expect(screen.getByText("+7")).toBeTruthy();
    expect(screen.queryByText("+400")).toBeNull();
  });

  it("shows who was promoted into a seat the trade never mentioned", () => {
    renderSim(
      populated({
        promotions: [
          {
            playerId: "p9",
            name: "Quiet Bench WR",
            position: "WR",
            slotBefore: null,
            slotAfter: "FLEX",
            kind: "promoted",
          },
        ],
      }),
    );
    expect(screen.getByText(/Quiet Bench WR/)).toBeTruthy();
    expect(screen.getByText(/FLEX/)).toBeTruthy();
  });

  it("shows who was displaced OUT of the lineup", () => {
    renderSim(
      populated({
        displacements: [
          {
            playerId: "p10",
            name: "Former Starter",
            position: "RB",
            slotBefore: "RB",
            slotAfter: null,
            kind: "displaced",
          },
        ],
      }),
    );
    expect(screen.getByText(/Former Starter/)).toBeTruthy();
  });

  it("reports needs OPENED with the same weight as needs closed", () => {
    // RosterSimulation's own docstring: "A simulation that only showed
    // what improved would be an advocacy tool."
    renderSim(populated({ needsFixed: ["TE"], needsCreated: ["RB"] }));
    expect(screen.getByText(/closed/i)).toBeTruthy();
    expect(screen.getByText(/opened/i)).toBeTruthy();
    expect(screen.getByText(/TE/)).toBeTruthy();
    expect(screen.getByText(/RB/)).toBeTruthy();
  });

  it("reports a needs-opened-only trade rather than staying silent", () => {
    renderSim(populated({ needsFixed: [], needsCreated: ["QB"] }));
    expect(screen.getByText(/opened/i)).toBeTruthy();
    expect(screen.getByText(/QB/)).toBeTruthy();
  });

  it("says the final roster is one of a RANGE when the cleanup is an upper bound", () => {
    renderSim(
      populated({
        cleanupIsUpperBound: true,
        cleanupApplied: [{ playerId: "d1", name: "Cut One", position: "WR", value: 10 }],
      }),
    );
    expect(screen.getByText(/one of a range/i)).toBeTruthy();
  });

  it("counts the applied cleanup without re-listing names the capacity block owns", () => {
    renderSim(
      populated({
        cleanupApplied: [
          { playerId: "d1", name: "Cut One", position: "WR", value: 10 },
          { playerId: "d2", name: "Cut Two", position: "RB", value: 20 },
        ],
      }),
    );
    expect(screen.getByText(/2 required release/i)).toBeTruthy();
    // The names live in the Roster capacity block; a second full list
    // would be a duplicate surface for the same fact.
    expect(screen.queryByText(/Cut One/)).toBeNull();
  });

  it("discloses incoming players the board could not price", () => {
    renderSim(populated({ unpricedIncoming: ["Mystery Rookie"] }));
    expect(screen.getByText(/Mystery Rookie/)).toBeTruthy();
    expect(screen.getByText(/not priced/i)).toBeTruthy();
  });

  it("discloses outgoing names that were not on the roster", () => {
    renderSim(populated({ outgoingNotFound: ["Never Here"] }));
    expect(screen.getByText(/Never Here/)).toBeTruthy();
  });

  it("stays quiet about promotions, needs and cleanup when there are none", () => {
    renderSim(populated());
    // Still non-vacuous: the populated block itself rendered.
    expect(screen.getByText(/Final roster/i)).toBeTruthy();
    expect(screen.queryByText(/Promoted/i)).toBeNull();
    expect(screen.queryByText(/opened/i)).toBeNull();
    expect(screen.queryByText(/required release/i)).toBeNull();
    expect(screen.queryByText(/one of a range/i)).toBeNull();
  });
});
