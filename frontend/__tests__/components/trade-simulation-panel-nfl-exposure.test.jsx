/**
 * `SimulationPanel` — NFL team exposure rendering (C2-EXP-01, #786).
 *
 * `POST /api/trade/simulate` stamps an `nflExposure` block (PR #1439):
 * value-weighted NFL-franchise share of the team's full roster before →
 * after the trade, computed by `src/roster_intel/exposure.py` and attached
 * AFTER the simulation so it feeds no value, equity or verdict.
 *
 * What these tests pin:
 *
 * - PURE RENDERER. Every share, delta and concentration figure is read from
 *   the backend stamp. The populated fixture carries a deliberately
 *   self-inconsistent row (after − before ≠ delta) so only a reader passes.
 * - CONTEXT, NOT VERDICT. The section is labelled as context, folded by
 *   default, and renders after the equity line — outside the Roster fit
 *   block that carries the verdict badge.
 * - MISSING IS NEVER ZERO. `unavailable`, unpriced / unknown-team players,
 *   an unmeasured (null) concentration and `outgoingNotOnRoster` each have
 *   an explicit state; none renders as 0%.
 * - Accessible structure: an h3 heading labelling a region, a native
 *   <details>/<summary> disclosure (keyboard-operable), and captioned
 *   tables with numeric columns.
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SimulationPanel } from "@/app/trade/trade-sections";

const BASE_SIM = {
  team: { name: "My Team" },
  before: { totalValue: 1000 },
  after: { totalValue: 1200 },
  delta: { totalValue: 200, byPosition: {} },
  teamImpact: {
    verdict: "lean accept",
    compositeScore: 1.5,
    fitScore: 1,
    equityScore: 2,
    windowFit: 0.1,
    posture: "Contender",
    starterValueDelta: {},
    rationale: [],
    redundancy: [],
  },
  equity: 200,
  unresolvedIn: [],
  unresolvedOut: [],
};

/** One side, in the exact shape `NflExposure.to_dict` emits. */
function side(overrides = {}) {
  return {
    scope: "full_roster",
    buckets: [],
    pricedValue: 10000,
    topFranchiseShare: 18.2,
    franchiseHHI: 812.4,
    unpricedIds: [],
    unknownTeamIds: [],
    handcuffPairs: [],
    ...overrides,
  };
}

/** A populated block, in the exact shape `trade_nfl_exposure` emits. */
function exposure(overrides = {}) {
  const moved = [
    { team: "MIN", isFranchise: true, shareBefore: 18.2, shareAfter: 22.4, delta: 4.2 },
    // Self-inconsistent on purpose: 12.0 − 20.0 = −8.0, but the backend
    // stamped −3.1. A renderer shows −3.1; a recomputer shows 8.0.
    { team: "CIN", isFranchise: true, shareBefore: 20.0, shareAfter: 12.0, delta: -3.1 },
  ];
  return {
    before: side(),
    after: side({ topFranchiseShare: 22.4, franchiseHHI: 901.6 }),
    changes: [...moved, { team: "KC", isFranchise: true, shareBefore: 5, shareAfter: 5, delta: 0 }],
    moved,
    scope: "full_roster",
    valueScale: "rankDerivedValue",
    descriptiveOnly: true,
    outgoingNotOnRoster: [],
    notes: ["descriptive context only"],
    ...overrides,
  };
}

function renderSim(nflExposure) {
  return render(
    <SimulationPanel
      simResult={nflExposure === undefined ? { ...BASE_SIM } : { ...BASE_SIM, nflExposure }}
    />,
  );
}

function exposureRegion() {
  return screen.getByRole("region", { name: "NFL team exposure" });
}

async function openDetail() {
  const region = exposureRegion();
  const summary = region.querySelector("summary");
  await userEvent.click(summary);
  return region;
}

describe("SimulationPanel — NFL team exposure", () => {
  it("renders nothing when the backend sent no nflExposure block", () => {
    renderSim(undefined);
    expect(screen.queryByText("NFL team exposure")).toBeNull();
  });

  it("is an h3-labelled region, marked as context, folded by default", () => {
    renderSim(exposure());
    const heading = screen.getByRole("heading", { level: 3, name: "NFL team exposure" });
    expect(heading).toBeTruthy();
    const region = exposureRegion();
    expect(within(region).getByText("Context only — not part of the verdict")).toBeTruthy();
    const details = region.querySelector("details");
    expect(details).not.toBeNull();
    expect(details.open).toBe(false);
    expect(within(region).getByText("Show 2 teams that moved")).toBeTruthy();
  });

  it("renders after the equity line, outside the verdict-bearing Roster fit block", () => {
    renderSim(exposure());
    const region = exposureRegion();
    const equity = screen.getByText(/Equity \(receiving − sending\)/);
    // eslint-disable-next-line no-bitwise
    expect(equity.compareDocumentPosition(region) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const verdictBadge = screen.getByText("lean accept");
    expect(region.contains(verdictBadge)).toBe(false);
    expect(within(region).queryByText("lean accept")).toBeNull();
  });

  it("is reachable by Tab and opens via the native summary control", async () => {
    renderSim(exposure());
    const region = exposureRegion();
    const summary = region.querySelector("summary");
    const user = userEvent.setup();
    await user.tab();
    // The summary is the section's only tab stop inside the panel body.
    while (document.activeElement !== summary && document.activeElement !== document.body) {
      await user.tab();
    }
    expect(document.activeElement).toBe(summary);
    // Browsers map Enter/Space on a focused <summary> to its activation
    // natively; jsdom does not synthesize that, so activate it directly.
    await user.click(summary);
    expect(region.querySelector("details").open).toBe(true);
  });

  it("shows each moved team as before → after with the BACKEND delta in pp", async () => {
    renderSim(exposure());
    const region = await openDetail();
    const table = within(region).getByRole("table", {
      name: "NFL team share of roster value, before and after the trade",
    });
    const rows = within(table).getAllByRole("row");
    // header + the two MOVED teams; the unchanged KC row from `changes` is not listed.
    expect(rows).toHaveLength(3);
    const min = within(table).getByText("MIN").closest("tr");
    expect(within(min).getByText("18.2%")).toBeTruthy();
    expect(within(min).getByText("22.4%")).toBeTruthy();
    expect(within(min).getByRole("img", { name: "up 4.2 percentage points" })).toBeTruthy();

    const cin = within(table).getByText("CIN").closest("tr");
    expect(within(cin).getByRole("img", { name: "down 3.1 percentage points" })).toBeTruthy();
    // Reader, not recomputer: 12.0 − 20.0 would be 8.0.
    expect(within(cin).queryByText(/8\.0/)).toBeNull();
    expect(within(table).queryByText("KC")).toBeNull();
  });

  it("shows concentration before/after from the stamps, without deriving a delta", async () => {
    renderSim(exposure());
    const region = await openDetail();
    const table = within(region).getByRole("table", {
      name: "Roster concentration across NFL teams, before and after the trade",
    });
    const top = within(table).getByText("Largest single team").closest("tr");
    expect(within(top).getByText("18.2%")).toBeTruthy();
    expect(within(top).getByText("22.4%")).toBeTruthy();
    const hhi = within(table).getByText("Concentration index (HHI, 0–10,000)").closest("tr");
    expect(within(hhi).getByText("812")).toBeTruthy();
    expect(within(hhi).getByText("902")).toBeTruthy();
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Measure",
      "Before",
      "After",
    ]);
  });

  it("marks a non-franchise bucket (FA) as not an NFL franchise", async () => {
    renderSim(
      exposure({
        moved: [{ team: "FA", isFranchise: false, shareBefore: 0, shareAfter: 3.5, delta: 3.5 }],
      }),
    );
    const region = await openDetail();
    expect(within(region).getByText("FA (not an NFL franchise)")).toBeTruthy();
  });

  it("renders the unavailable state with its reason and no tables", () => {
    renderSim({
      unavailable: "KeyError",
      notes: ["NFL-team exposure could not be computed for this trade"],
    });
    const region = exposureRegion();
    expect(
      within(region).getByText(
        "Unavailable — NFL-team exposure could not be computed for this trade. (KeyError)",
      ),
    ).toBeTruthy();
    expect(region.querySelector("table")).toBeNull();
    expect(region.querySelector("details")).toBeNull();
    // The rest of the simulation still renders.
    expect(screen.getByText("lean accept")).toBeTruthy();
  });

  it("names unpriced and unknown-team players and never shows an unmeasured share as 0%", async () => {
    renderSim(
      exposure({
        before: side({
          topFranchiseShare: null,
          franchiseHHI: null,
          unpricedIds: ["Mystery Rookie"],
          unknownTeamIds: [],
        }),
        after: side({
          unpricedIds: ["Mystery Rookie", "Unjoined Name"],
          unknownTeamIds: ["Teamless Vet"],
        }),
      }),
    );
    const region = exposureRegion();
    expect(within(region).getByText(/Coverage incomplete/)).toBeTruthy();
    await openDetail();
    expect(
      within(region).getByText(
        "Not priced by the board — excluded, never counted as zero (before): Mystery Rookie",
      ),
    ).toBeTruthy();
    expect(
      within(region).getByText(
        "Not priced by the board — excluded, never counted as zero (after): Mystery Rookie, Unjoined Name",
      ),
    ).toBeTruthy();
    expect(
      within(region).getByText("Priced, but NFL team unknown — excluded (after): Teamless Vet"),
    ).toBeTruthy();
    const conc = within(region).getByRole("table", {
      name: "Roster concentration across NFL teams, before and after the trade",
    });
    const top = within(conc).getByText("Largest single team").closest("tr");
    const cells = within(top).getAllByRole("cell").map((c) => c.textContent);
    expect(cells[1]).toBe("—");
    expect(cells[1]).not.toBe("0.0%");
  });

  it("says plainly when no team's share changed", async () => {
    renderSim(exposure({ moved: [], changes: [] }));
    const region = exposureRegion();
    expect(within(region).getByText("Show detail — no team's share changed")).toBeTruthy();
    await openDetail();
    expect(within(region).getByText("No NFL team's share of roster value changed.")).toBeTruthy();
    // Concentration still renders from the stamps.
    expect(
      within(region).getByRole("table", {
        name: "Roster concentration across NFL teams, before and after the trade",
      }),
    ).toBeTruthy();
  });

  it("lists outgoing players the roster does not hold", async () => {
    renderSim(exposure({ outgoingNotOnRoster: ["Not My Player"] }));
    const region = exposureRegion();
    expect(within(region).getByText(/Coverage incomplete/)).toBeTruthy();
    await openDetail();
    expect(
      within(region).getByText("Sent but not on this roster — frees nothing: Not My Player"),
    ).toBeTruthy();
  });

  it("shows no coverage caveat when nothing was excluded", () => {
    renderSim(exposure());
    expect(within(exposureRegion()).queryByText(/Coverage incomplete/)).toBeNull();
  });
});
