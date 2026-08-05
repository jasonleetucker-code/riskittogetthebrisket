/**
 * /edge Buy & Sell panels — gate, sort and label on the MARKET GAP.
 *
 * WHY THIS FILE EXISTS
 *
 * The page had no test that rendered it, and two defects lived in that gap.
 *
 * 1. AUDIT S-3 — the panels display the sign of `marketGapDirection` while
 *    gating, sorting and labelling on `sourceRankSpread`, which measures how
 *    much the SOURCES disagree with EACH OTHER.  Two different quantities.  A
 *    clean, large retail-vs-consensus gap on a player every source agrees
 *    about was excluded outright; a negligible gap on a player they were
 *    arguing over sorted first.  The panel structurally surfaced its least
 *    reliable rows and hid its most reliable.
 *
 * 2. Fixing only the filter left the display half live.  `DataTable` is not
 *    `presorted`, so it re-sorts by `defaultSort` — which was still
 *    `{key: "spread"}` — and the caller's ordering never reached the screen.
 *    The rendered column was `colSpread()` too, so the number printed beside
 *    a market-gap signal was the disagreement width.
 *
 * Rendering the page is also the only thing that catches a missing import:
 * `premiumBy` calls `marketGapAtLeast`/`marketGapRatioOf`, and there is no
 * ESLint in this repo and `build:nocheck` skips Next's own lint, so an
 * unimported helper is a runtime ReferenceError that no gate could see.
 *
 * The fixture is built so the two axes DISAGREE.  If a future change reverts
 * to the spread axis, the expected order flips and these tests fail.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";

// ── Fixture ─────────────────────────────────────────────────────────
// Ordering by gap and ordering by spread are deliberately OPPOSITE, and
// one row is admissible on exactly one of the two axes.
//
//  name             gap   spread   by gap   by spread
//  WideGapTight    0.40      2       1st      last     ← agreement, huge gap
//  MidGapMid       0.25     40       2nd      2nd
//  NarrowGapLoose  0.16     90       3rd      1st      ← disagreement, tiny gap
//  UnderFloor      0.04    120     excluded   1st      ← spread gate yes, gap no
//
// No name is a substring of another: the row matcher below works on the
// rendered row text, so an overlapping pair would silently mis-attribute.
function row(name, marketGapValueRatio, sourceRankSpread, rank, direction) {
  return {
    name,
    displayName: name,
    pos: "WR",
    position: "WR",
    assetClass: "offense",
    rank,
    canonicalConsensusRank: rank,
    rankDerivedValue: 5000 - rank,
    values: { full: 5000 - rank },
    sourceCount: 5,
    quarantined: false,
    confidenceBucket: "high",
    marketGapDirection: direction,
    marketGapValueRatio,
    // Retired rank-space field: the backend stamps None on every row.
    marketGapMagnitude: null,
    sourceRankSpread,
  };
}

const SELL_ROWS = [
  row("WideGapTight", 0.4, 2, 10, "retail_premium"),
  row("MidGapMid", 0.25, 40, 20, "retail_premium"),
  row("NarrowGapLoose", 0.16, 90, 30, "retail_premium"),
  row("UnderFloor", 0.04, 120, 40, "retail_premium"),
];

const BUY_ROWS = [
  row("BuyStrong", 0.35, 3, 50, "consensus_premium"),
  row("BuyWeak", 0.17, 80, 60, "consensus_premium"),
];

const ROWS = [...SELL_ROWS, ...BUY_ROWS];

vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => ({
    loading: false,
    error: "",
    rows: ROWS,
    rawData: { sleeper: { teams: [] } },
  }),
}));
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ openPlayerPopup: vi.fn(), rows: ROWS, rawData: {} }),
}));
// The scatter measures layout; irrelevant here and noisy under jsdom.
vi.mock("@/components/graphs/ConfidenceValueScatter", () => ({ default: () => null }));

import EdgePage from "@/app/edge/page";

/** The <table> belonging to the panel whose heading is `title`. */
function panelTable(title) {
  // The panel is a <section class="ds-panel">; the heading is an <h2> a few
  // levels inside its <header>.  Anchor on the section explicitly — a bare
  // `closest("div")` matches `div.ds-panel__heading`, which holds no table.
  const panel = screen.getByText(title).closest("section");
  const table = panel?.querySelector("table");
  if (!table) throw new Error(`no table under panel "${title}" (panel may be empty)`);
  return table;
}

/** The rows of the panel whose heading is `title`, in render order. */
function panelRowNames(title) {
  return Array.from(panelTable(title).querySelectorAll("tbody tr"))
    .map((tr) => tr.textContent || "")
    .map((text) => ROWS.find((r) => text.includes(r.name))?.name)
    .filter(Boolean);
}

describe("/edge market-gap panels", () => {
  beforeEach(() => {
    render(<EdgePage />);
  });

  it("renders at all — a helper used but never imported is a ReferenceError", () => {
    // `premiumBy` calls marketGapAtLeast/marketGapRatioOf. If either is not
    // imported the page throws during render and every assertion below is
    // unreachable. Stated as its own test so the failure names the cause.
    expect(screen.getByText("Sell signals")).toBeTruthy();
    expect(screen.getByText("Buy signals")).toBeTruthy();
  });

  it("orders sell signals by market gap, not by source disagreement", () => {
    // By spread this would be NarrowGapLoose, MidGapMid, WideGapTight —
    // the exact reverse.
    expect(panelRowNames("Sell signals")).toEqual([
      "WideGapTight",
      "MidGapMid",
      "NarrowGapLoose",
    ]);
  });

  it("orders buy signals by market gap, not by source disagreement", () => {
    // By spread: BuyWeak (80) first. By gap: BuyStrong (0.35) first.
    expect(panelRowNames("Buy signals")).toEqual(["BuyStrong", "BuyWeak"]);
  });

  it("excludes a row below the gap floor even though its spread is the widest", () => {
    // UnderFloor has the largest sourceRankSpread on the board (120) and would
    // have sorted FIRST under the old gate. Its gap is 4%, under
    // PREMIUM_SUMMARY_VALUE_RATIO, so it must not appear at all.
    expect(panelRowNames("Sell signals")).not.toContain("UnderFloor");
  });

  it("admits a row the old spread gate would have excluded", () => {
    // WideGapTight's sources agree almost perfectly (spread 2), far under the
    // old PREMIUM_SUMMARY_SPREAD of 20, so the old gate dropped it — the single
    // clearest signal on the board. It must now lead the panel.
    expect(panelRowNames("Sell signals")[0]).toBe("WideGapTight");
  });

  it("labels the gap, not the disagreement width", () => {
    // The old column rendered "±90" (an ordinal spread) beside a signal about
    // a value gap. It must now render the gap as a percentage.
    const table = panelTable("Sell signals");
    const headers = Array.from(table.querySelectorAll("thead th")).map((th) =>
      th.textContent.trim(),
    );
    expect(headers).toContain("Gap");
    expect(headers).not.toContain("Spread");

    const wideGapRow = Array.from(table.querySelectorAll("tbody tr")).find((tr) =>
      (tr.textContent || "").includes("WideGapTight"),
    );
    expect(within(wideGapRow).getByText("40%")).toBeTruthy();
    // "±90" was the old rendering: an ordinal spread beside a value signal.
    expect(wideGapRow.textContent).not.toContain("±");
  });
});
