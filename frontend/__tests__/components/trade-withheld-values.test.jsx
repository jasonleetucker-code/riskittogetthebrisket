/**
 * Withheld asset values on the multi-team preliminary meter (finding F2).
 *
 * The engine gives a traded asset the evidence gates withhold an explicit
 * valueState (quarantined / stale) with value null — never priced
 * (src/trade/analyze_service.py::_value_entry, from
 * trade_decision.asset_evidence_codes).  The browser's preliminary reading
 * reads the SAME row stamps (`quarantined`, `confidenceAxes.freshness`), so a
 * team whose part of the trade carries one shows WITHHELD with the reason —
 * never its gap, never a band, never 0 — and the headline is not
 * determinable.  Teams the asset does not touch keep their reading.
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TradeMeterMultiTeam } from "@/components/trade/TradeMeter";
import { MultiTeamSummaryBar } from "@/app/trade/trade-layout";
import {
  computeSideFlows,
  multiTeamNetSummary,
  withheldAssetsBySide,
  withheldReasonText,
  withheldValueState,
} from "@/lib/trade-logic";

const row = (name, v, extra = {}) => ({
  name,
  pos: "WR",
  position: "WR",
  assetClass: "offense",
  rankDerivedValue: v,
  values: { full: v },
  ...extra,
});

// A -> B -> C -> A, one asset each.  "B Seven" (B -> C) is the withheld one,
// so B (sends it) and C (receives it) are withheld and A is not.
function cycle(bSeven) {
  return [
    { id: 0, label: "A", assets: [row("A Six", 6000)], destinations: { "A Six": 1 } },
    { id: 1, label: "B", assets: [bSeven], destinations: { "B Seven": 2 } },
    { id: 2, label: "C", assets: [row("C TwoFive", 2500)], destinations: { "C TwoFive": 0 } },
  ];
}
const QUARANTINED = row("B Seven", 7000, { quarantined: true });
const STALE = row("B Seven", 7000, { raw: { confidenceAxes: { freshness: "low" } } });

describe("withheldValueState reads the pipeline's own stamps", () => {
  it("quarantined, then stale, in the engine's gate order", () => {
    expect(withheldValueState(row("x", 10, { quarantined: true }))).toBe("quarantined");
    expect(withheldValueState(row("x", 10, { raw: { quarantined: true } }))).toBe("quarantined");
    expect(withheldValueState(row("x", 10, { confidenceAxes: { freshness: "low" } }))).toBe(
      "stale",
    );
    expect(
      withheldValueState(
        row("x", 10, { quarantined: true, raw: { confidenceAxes: { freshness: "low" } } }),
      ),
    ).toBe("quarantined");
  });

  it("an absent or non-low stamp is not withheld; a user-typed value is not the board's", () => {
    expect(withheldValueState(row("x", 10))).toBeNull();
    expect(withheldValueState(row("x", 10, { quarantined: false }))).toBeNull();
    expect(withheldValueState(row("x", 10, { raw: { confidenceAxes: { freshness: "medium" } } })))
      .toBeNull();
    expect(withheldValueState(row("x", 10, { quarantined: true, customValue: 500 }))).toBeNull();
    expect(withheldValueState(null)).toBeNull();
  });
});

describe("withheldAssetsBySide follows the routes", () => {
  it("the sender and the receiver both carry it; an untouched team carries nothing", () => {
    const w = withheldAssetsBySide(cycle(QUARANTINED));
    expect(w[0]).toEqual([]);
    expect(w[1]).toEqual([
      { name: "B Seven", state: "quarantined", direction: "out", fromSide: 1, toSide: 2 },
    ]);
    expect(w[2]).toEqual([
      { name: "B Seven", state: "quarantined", direction: "in", fromSide: 1, toSide: 2 },
    ]);
    expect(withheldReasonText(w[1])).toBe("B Seven (sent, quarantined)");
    expect(withheldReasonText(w[2])).toBe("B Seven (received, quarantined)");
    expect(withheldReasonText(w[0])).toBeNull();
  });

  it("a trade with nothing withheld has no entries", () => {
    expect(withheldAssetsBySide(cycle(row("B Seven", 7000)))).toEqual([[], [], []]);
  });
});

describe("multiTeamNetSummary withholds, never prices", () => {
  it("a withheld team has no gap and no band, and the headline is Withheld", () => {
    const sides = cycle(QUARANTINED);
    const flows = computeSideFlows(sides, "full");
    // The browser's arithmetic does sum the quarantined 7000 ...
    expect(flows[1].given).toBe(7000);
    const s = multiTeamNetSummary(flows, withheldAssetsBySide(sides));
    // ... but no team result is read from it.
    expect(s.withheld).toEqual([false, true, true]);
    expect(s.nets[1]).toBeNull();
    expect(s.nets[2]).toBeNull();
    expect(s.perTeam[1]).toBeNull();
    expect(s.perTeam[2]).toBeNull();
    expect(s.worst).toBeNull();
    expect(s.verdict).toEqual({ label: "Withheld", level: null, relativePct: null });
    // The untouched team keeps its own reading.
    expect(s.nets[0]).toBe(flows[0].net);
    expect(s.perTeam[0]).not.toBeNull();
  });

  it("without a withheld asset the reading is unchanged", () => {
    const sides = cycle(row("B Seven", 7000));
    const flows = computeSideFlows(sides, "full");
    const plain = multiTeamNetSummary(flows);
    const withEmpty = multiTeamNetSummary(flows, withheldAssetsBySide(sides));
    expect(withEmpty.nets).toEqual(plain.nets);
    expect(withEmpty.verdict).toEqual(plain.verdict);
    expect(withEmpty.withheld).toEqual([false, false, false]);
  });
});

describe("TradeMeterMultiTeam renders a withheld team as WITHHELD with the reason", () => {
  for (const [label, asset, state] of [
    ["quarantined", QUARANTINED, "quarantined"],
    ["stale", STALE, "stale"],
  ]) {
    it(`a ${label} value: B and C withheld, A priced, no band, never 0`, () => {
      const sides = cycle(asset);
      const flows = computeSideFlows(sides, "full");
      const { container } = render(
        <TradeMeterMultiTeam sides={sides} sideTotals={[]} flows={flows} />,
      );
      const cells = [...container.querySelectorAll(".trade-meter-multi-val")];
      expect(cells.map((c) => c.getAttribute("data-team-state"))).toEqual([
        "priced",
        "withheld",
        "withheld",
      ]);
      const reasons = screen.getAllByTestId("trade-meter-withheld").map((n) => n.textContent);
      expect(reasons).toEqual([
        `Not determinable — value withheld: B Seven (sent, ${state})`,
        `Not determinable — value withheld: B Seven (received, ${state})`,
      ]);
      for (const c of cells.slice(1)) {
        expect(c.querySelector(".trade-meter-side-val").textContent).toBe("Withheld");
        // Neither the withheld 7,000 nor a 0 is shown for these teams.
        expect(c.textContent).not.toMatch(/7,000/);
        expect(c.textContent).not.toMatch(/Give|Get/);
        expect(c.textContent).not.toMatch(/(^|\D)0(\D|$)/);
      }
      expect(cells[0].textContent).toMatch(/Give 6,000/);
      expect(container.querySelector(".trade-meter-verdict").textContent).toBe("Withheld");
      expect(container.textContent).toMatch(
        /No overall reading: Side B, Side C withheld \(a quarantined or stale value is not priced\)/,
      );
      expect(container.textContent).not.toMatch(/Widest gap/);
    });
  }

  it("a value the user typed prices the line again (the user's number, not the board's)", () => {
    const sides = cycle({ ...QUARANTINED, customValue: 6500 });
    const flows = computeSideFlows(sides, "full");
    const { container } = render(
      <TradeMeterMultiTeam sides={sides} sideTotals={[]} flows={flows} />,
    );
    expect(screen.queryAllByTestId("trade-meter-withheld")).toHaveLength(0);
    expect(container.textContent).toMatch(/Widest gap/);
  });
});

describe("MultiTeamSummaryBar says withheld, never a band or a 0", () => {
  it("names the withheld sides and keeps the untouched team's gap", () => {
    const sides = cycle(QUARANTINED);
    const flows = computeSideFlows(sides, "full");
    const summary = multiTeamNetSummary(flows, withheldAssetsBySide(sides));
    render(
      <MultiTeamSummaryBar sides={sides} summary={summary} evalState={{ state: "complete" }} />,
    );
    const bar = screen.getByTestId("trade-multi-summary").textContent;
    expect(bar).toMatch(/B withheld/);
    expect(bar).toMatch(/C withheld/);
    expect(bar).toContain(
      "Preliminary — not determinable: Side B, Side C withheld (a quarantined or stale value) · final result in the War Room",
    );
    expect(bar).not.toMatch(/widest gap/);
  });
});
