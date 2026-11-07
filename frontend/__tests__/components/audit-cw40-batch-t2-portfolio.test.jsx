/**
 * CW-40 Batch T2, W20-F004 -- OPEN.
 *
 * PortfolioSummary merges the SERVER portfolio (`totalValue`, `byPosition`: players only, picks
 * excluded -- src/api/terminal.py) onto the LOCAL one (`starterValue`, `benchValue`, `pickValue`,
 * which include/measure picks).  The panel therefore prints a "Total Value" that excludes picks beside
 * a Starters / Bench / Picks legend that sums to MORE than it.
 *
 * Whether picks belong in the total is an owner decision (see CW40_P1_BATCH_t2.md); the defect is
 * that the panel mixes the two definitions, which is wrong under either answer.  `it.fails` states
 * the invariant "the legend adds up to the stated total".
 */
import React from "react";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const state = vi.hoisted(() => ({ server: null }));

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: state.rows, rawData: {}, openPlayerPopup: () => {} }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({
    selectedTeam: state.team,
    idpEnabled: false,
    rosterSettings: null,
    loading: false,
  }),
}));
vi.mock("@/components/useRankHistory", () => ({
  useRankHistory: () => ({ history: {}, loading: false }),
}));
vi.mock("@/components/useTerminal", () => ({
  useTerminal: () => ({ portfolio: state.server }),
}));

import PortfolioSummary from "@/components/terminal/PortfolioSummary";

afterEach(cleanup);

function setup() {
  state.rows = [
    { name: "Alice", pos: "QB", age: 27, rankDerivedValue: 9000 },
    { name: "Bob", pos: "WR", age: 25, rankDerivedValue: 7000 },
    { name: "2026 Pick 1.01", pos: "PICK", rankDerivedValue: 5000 },
  ];
  state.team = {
    players: ["Alice", "Bob"],
    picks: ["2026 1.01"],
    // the server's solved lineup: both players start
    optimalLineup: { slots: [] },
  };
  // exactly what src/api/terminal.py publishes: players only, PICK bucket empty
  state.server = {
    totalValue: 16000,
    byPosition: {
      QB: { count: 1, value: 9000, pct: 56.3 },
      WR: { count: 1, value: 7000, pct: 43.8 },
      RB: { count: 0, value: 0, pct: 0 },
      TE: { count: 0, value: 0, pct: 0 },
      K: { count: 0, value: 0, pct: 0 },
      DEF: { count: 0, value: 0, pct: 0 },
      IDP: { count: 0, value: 0, pct: 0 },
      PICK: { count: 0, value: 0, pct: 0 },
    },
  };
}

function numbers(text) {
  return [...text.matchAll(/\d[\d,]*/g)].map((m) => Number(m[0].replace(/,/g, "")));
}

function readPanel(container) {
  const total = container.querySelector(".portfolio-agg-value")?.textContent || "";
  const legend = container.querySelector(".portfolio-split-legend")?.textContent || "";
  const picks = /Picks\s*([\d,]+)/.exec(legend);
  return { totalText: total, legendText: legend, total: numbers(total)[0], pickLegend: picks };
}

describe("W20-F004: PortfolioSummary total vs legend", () => {
  it("(characterization) the Total Value is the server's player-only sum while the Picks legend carries pick value", () => {
    setup();
    const { container } = render(<PortfolioSummary />);
    const p = readPanel(container);
    expect(p.total).toBe(16000);
    expect(p.pickLegend).not.toBeNull();
    expect(Number(p.pickLegend[1].replace(/,/g, ""))).toBe(5000);
  });

  it.fails("W20-F004 open: Starters + Bench + Picks in the legend equal the stated Total Value", () => {
    setup();
    const { container } = render(<PortfolioSummary />);
    const p = readPanel(container);
    const legendValues = [...p.legendText.matchAll(/(Starters|Bench|Picks)\s*([\d,]+)/g)].map((m) =>
      Number(m[2].replace(/,/g, "")),
    );
    expect(legendValues.length).toBeGreaterThan(0);
    expect(legendValues.reduce((a, b) => a + b, 0)).toBe(p.total);
  });
});
