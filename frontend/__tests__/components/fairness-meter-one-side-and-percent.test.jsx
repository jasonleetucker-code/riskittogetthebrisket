// fairness_bands_v2 review findings, pinned at the render level.
//
// 1. /waivers regression: with only the Drop (or only the Add) side picked,
//    ManualAddDrop built a flat-sum total with no package `utility`, and the
//    meter's base (`sideTotalsFairnessBase`) threw FairnessInputError during
//    render -- the ResilientSection replaced the fairness bar with an
//    "unavailable" banner that stuck after the second pick.  No test rendered
//    the meter with one side filled.
// 2. A side total / flow WITHOUT a utility (any future caller) renders an
//    explicit "no verdict" state, never a thrown render and never a band.
// 3. The percentage printed beside the badge is the band's own (relative to
//    the larger package utility), so it is never below the badge's cut --
//    v2 had shown percentageGap's adjusted-side basis next to it.
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import ManualAddDrop from "@/components/waivers/ManualAddDrop";
import TradeMeter, { TradeMeterTwoTeam } from "@/components/trade/TradeMeter";
import TradeFairnessExplanation from "@/components/trade/TradeFairnessExplanation";
import { adjustedSideTotals, meterVerdict, sideTotalsFairnessBase } from "@/lib/trade-logic";
import { LOPSIDED_PCT, SLIGHT_PCT, UNFAIR_PCT } from "@/lib/fairness-bands";

const row = (name, value, pos = "WR") => ({
  name,
  pos,
  rankDerivedValue: value,
  assetClass: "offense",
  sourceCount: 6,
  confidenceBucket: "high",
  values: { full: value },
});

const ROSTERED = row("Josh Allen", 5200, "QB");
const FREE = row("Emeka Egbuka", 3100, "WR");
const TEAM = { name: "Mine", players: ["Josh Allen"], faabRemaining: 63 };

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: false, status: 503, json: async () => ({}) })),
  );
});
afterEach(() => vi.unstubAllGlobals());

function renderManual() {
  return render(
    <ManualAddDrop rows={[ROSTERED, FREE]} selectedTeam={TEAM} sleeperTeams={[]} settings={{}} />,
  );
}

function pick(label, name) {
  const input = screen.getByLabelText(`Search ${label} candidates`);
  fireEvent.focus(input);
  fireEvent.mouseDown(screen.getByText(name).closest("button"));
}

describe("/waivers Manual add/drop: the fairness bar with ONE side picked", () => {
  it("Add only: renders a band, not the 'unavailable' banner", () => {
    renderManual();
    pick("add", "Emeka Egbuka");
    expect(screen.queryByText(/fairness bar unavailable/i)).toBeNull();
    expect(screen.getByText("LOPSIDED")).toBeInTheDocument();
    expect(screen.getByText("Side Add wins by 100%")).toBeInTheDocument();
  });

  it("Drop only, then Add: the bar survives the whole normal flow", () => {
    renderManual();
    pick("drop", "Josh Allen");
    expect(screen.queryByText(/fairness bar unavailable/i)).toBeNull();
    expect(screen.getByText("Side Drop wins by 100%")).toBeInTheDocument();
    pick("add", "Emeka Egbuka");
    expect(screen.queryByText(/fairness bar unavailable/i)).toBeNull();
    // 5200 vs 3100 on a 1-for-1: (5200 - 3100) / 5200 = 40.38...%
    expect(screen.getByText("Side Drop wins by 40.3%")).toBeInTheDocument();
  });

  it("one-sided totals carry a package utility", () => {
    const totals = adjustedSideTotals([ROSTERED], [], "full");
    expect(totals.map((t) => t.utility)).toEqual([5200, 0]);
    expect(sideTotalsFairnessBase(totals)).toBe(5200);
  });
});

describe("a side total without a utility is refused explicitly, never thrown", () => {
  const sides = [{ assets: [FREE] }, { assets: [] }];
  it("two-team meter renders NO VERDICT for the old flat-sum shape", () => {
    const flat = [
      { raw: 3100, adjustment: 0, adjusted: 3100 },
      { raw: 0, adjustment: 0, adjusted: 0 },
    ];
    render(<TradeMeterTwoTeam sides={sides} sideTotals={flat} />);
    expect(screen.getByText("NO VERDICT")).toBeInTheDocument();
    expect(screen.getByText("Gap: not computed")).toBeInTheDocument();
    for (const label of ["FAIR", "SLIGHT EDGE", "UNFAIR", "LOPSIDED"]) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it("multi-team meter renders NO VERDICT for a flow without a utility", () => {
    const three = [{ assets: [FREE] }, { assets: [ROSTERED] }, { assets: [row("X", 900)] }];
    const flows = [
      { given: 3100, received: 900, net: -2200 },
      { given: 5200, received: 3100, net: -2100 },
      { given: 900, received: 5200, net: 4300 },
    ];
    render(<TradeMeter sides={three} sideTotals={[]} flows={flows} />);
    expect(screen.getByText("NO VERDICT")).toBeInTheDocument();
  });

  it("the fairness explanation stays silent rather than throwing", () => {
    const flat = [
      { raw: 3100, adjustment: 0, adjusted: 3100 },
      { raw: 2000, adjustment: 0, adjusted: 2000 },
    ];
    const { container } = render(
      <TradeFairnessExplanation sides={[{ assets: [FREE] }, { assets: [row("Y", 2000)] }]} sideTotals={flat} />,
    );
    expect(container.textContent).not.toMatch(/worth .*% more/);
  });
});

describe("the percentage beside the badge is the band's own (never below its cut)", () => {
  const cutOf = { slight: SLIGHT_PCT, unfair: UNFAIR_PCT, lopsided: LOPSIDED_PCT };
  const nextCutOf = { fair: SLIGHT_PCT, slight: UNFAIR_PCT, unfair: LOPSIDED_PCT, lopsided: Infinity };

  it("reviewer examples: 7990 vs [5795, 2441] and 5225 vs [1918, 1280, 1907]", () => {
    for (const [a, b] of [
      [[7990], [5795, 2441]],
      [[5225], [1918, 1280, 1907]],
    ]) {
      const totals = adjustedSideTotals(
        a.map((v, i) => row(`a${i}`, v)),
        b.map((v, i) => row(`b${i}`, v)),
        "full",
      );
      const v = meterVerdict(totals[0].adjusted - totals[1].adjusted, sideTotalsFairnessBase(totals));
      expect(v.level).not.toBe("fair");
      expect(Number(v.percentText)).toBeGreaterThanOrEqual(cutOf[v.level]);
    }
  });

  it("seeded 1-vs-k sweep: every badge's percentage sits inside its own band", () => {
    let seed = 20261020;
    const rnd = () => {
      seed = (seed * 1103515245 + 12345) % 2147483648;
      return seed / 2147483648;
    };
    let checked = 0;
    for (let n = 0; n < 4000; n++) {
      const k = 1 + Math.floor(rnd() * 5);
      const a = [Math.round(500 + rnd() * 9499)];
      const b = Array.from({ length: k }, () => Math.round(100 + rnd() * 6000));
      const totals = adjustedSideTotals(
        a.map((v, i) => row(`a${i}`, v)),
        b.map((v, i) => row(`b${i}`, v)),
        "full",
      );
      const gap = totals[0].adjusted - totals[1].adjusted;
      const v = meterVerdict(gap, sideTotalsFairnessBase(totals));
      const shown = Number(v.percentText);
      if (v.level !== "fair") expect(shown).toBeGreaterThanOrEqual(cutOf[v.level]);
      // Relative-band FAIR (gap above the floor) shows under the slight cut.
      if (v.level !== "fair" || Math.abs(gap) >= 250) expect(shown).toBeLessThan(nextCutOf[v.level]);
      checked++;
    }
    expect(checked).toBe(4000);
  });

  it("the meter text prints that percentage", () => {
    const sides = [{ assets: [row("a", 7990)] }, { assets: [row("b", 5795), row("c", 2441)] }];
    const totals = adjustedSideTotals(sides[0].assets, sides[1].assets, "full");
    const v = meterVerdict(totals[0].adjusted - totals[1].adjusted, sideTotalsFairnessBase(totals));
    render(<TradeMeterTwoTeam sides={sides} sideTotals={totals} />);
    expect(screen.getByText(v.label)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(`by ${v.percentText.replace(".", "\\.")}%`))).toBeInTheDocument();
  });
});

describe("a NaN board value on /trade never reaches a band", () => {
  // effectiveValue keeps a 0 arithmetic neutral for an unpriced row (so the
  // piece count stays right), and the verdict gate refuses the trade -- the
  // meter shows INCOMPLETE, never FAIR (review of #1886, JS row path).
  it("renders INCOMPLETE, not a band", () => {
    const nanRow = { name: "Mystery", pos: "WR", rankDerivedValue: null, values: { full: NaN } };
    const sides = [{ assets: [row("a", 5000), nanRow] }, { assets: [row("b", 5000)] }];
    const totals = adjustedSideTotals(sides[0].assets, sides[1].assets, "full");
    render(<TradeMeter sides={sides} sideTotals={totals} />);
    expect(screen.getByText("INCOMPLETE")).toBeInTheDocument();
    expect(screen.queryByText("FAIR")).toBeNull();
  });
});
