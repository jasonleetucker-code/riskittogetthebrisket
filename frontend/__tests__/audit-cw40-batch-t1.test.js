/**
 * CW-40 P1 re-audit, batch t1 — permanent regression tests for the /trade
 * calculator findings that re-verified CLOSED on current main.
 *
 *   W08-F002  VA copy no longer claims a "fewer pieces" roster-spot bonus
 *   W08-F003  adding a positive asset never lowers a side's standing
 *   W08-F004  current-year slot picks are searchable / year-agnostic filter
 *   W08-F005  owned picks sharing a label stay distinct, addable assets
 *   W08-F007  no value mode puts a legacy composite on the trade meter
 *
 * Record: docs/audits/remediation_2026-11-06/CW40_P1_BATCH_t1.md
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  TRADE_VALUE_MODE,
  VALUE_MODES,
  adjustedSideTotals,
  computeValueAdjustment,
  isTradeableBoardRow,
  packageAdjustPair,
  searchTradeAssets,
} from "../lib/trade-logic.js";
import {
  canAddEntry,
  groupSideEntries,
  teamPickEntries,
  tradeEntryKey,
} from "../lib/trade-assets.js";

const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), "utf8");
const asset = (name, v, extra = {}) => ({
  name,
  values: { full: v, raw: v * 1.3 },
  rankDerivedValue: v,
  ...extra,
});

// Deterministic LCG so a failure reproduces.
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 2 ** 32;
  };
}

describe("W08-F002 — the VA is not described as a fewer-pieces bonus", () => {
  it("the side card carries no roster-spot / fewer-pieces claim", () => {
    const src = read("../app/trade/trade-sections.jsx");
    expect(src).not.toMatch(/title=\{?["'`]Consolidation \/ roster-spot premium/);
    expect(src).not.toMatch(/frees a roster spot/i);
  });

  it("the behaviour the old copy denied is real: equal counts fire, and MORE pieces can earn it", () => {
    // 2 v 2: the side concentrated in one stud is credited.
    const eq = packageAdjustPair([9000, 1000], [5000, 5000]);
    expect(eq.displayed).toBe(true);
    expect(eq.side).toBe(1);
    // 4 v 3: the four-piece side holds the 9000 stud and is the recipient.
    const A = [asset("a1", 9000), asset("a2", 3000), asset("a3", 2000), asset("a4", 1700)];
    const B = [asset("b1", 5500), asset("b2", 4300), asset("b3", 4000)];
    const va = computeValueAdjustment(A, B, TRADE_VALUE_MODE, {});
    expect(va.recipientIdx).toBe(0);
    expect(va.adjustment).toBeGreaterThan(0);
    // 1 v 1 never adjusts.
    expect(packageAdjustPair([8000], [4000]).displayed).toBe(false);
  });
});

describe("W08-F003 — adding a positive-value asset never worsens that side", () => {
  it("over seeded 1-3 v 1-3 trades the gap (adjA - adjB) never falls by more than rounding", () => {
    const r = rng(20261107);
    const pick = () => 500 + Math.floor(r() * 9000);
    let violations = 0;
    let trials = 0;
    for (let i = 0; i < 4000; i++) {
      const na = 1 + Math.floor(r() * 3);
      const nb = 1 + Math.floor(r() * 3);
      const A = Array.from({ length: na }, (_, k) => asset(`a${k}`, pick()));
      const B = Array.from({ length: nb }, (_, k) => asset(`b${k}`, pick()));
      const extra = asset("extra", 300 + Math.floor(r() * 4700));
      const gap = (a, b) => {
        const [ta, tb] = adjustedSideTotals(a, b, TRADE_VALUE_MODE, {});
        return ta.adjusted - tb.adjusted;
      };
      const before = gap(A, B);
      const after = gap([...A, extra], B);
      trials += 1;
      // 1 point of slack: VA is rounded to an integer.
      if (after < before - 1) violations += 1;
    }
    expect(trials).toBe(4000);
    expect(violations).toBe(0);
  });

  it("the audit's 1v1 -> 2v1 shape is monotone too (1v1 suppression is not a cliff)", () => {
    const [b0, a0] = [asset("b", 6000), asset("a", 6100)];
    const g = (A, B) => {
      const [x, y] = adjustedSideTotals(A, B, TRADE_VALUE_MODE, {});
      return x.adjusted - y.adjusted;
    };
    expect(g([a0, asset("z", 400)], [b0])).toBeGreaterThanOrEqual(g([a0], [b0]) - 1);
  });
});

describe("W08-F004 — pick search excludes aliases, never a hardcoded year", () => {
  const slot = (year, n, v) => ({
    name: `${year} Pick ${n}`,
    assetClass: "pick",
    rankDerivedValue: v,
    values: { full: v },
    blendedSourceRank: 10,
  });
  const alias = (year) => ({
    name: `${year} Mid 1st`,
    assetClass: "pick",
    pickGenericSuppressed: true,
    rankDerivedValue: null,
    values: { full: 0 },
  });

  it("offers slot rows of ANY current year and hides only the suppressed alias", () => {
    for (const year of [2026, 2027, 2031]) {
      const rows = [alias(year), slot(year, "1.01", 7799)];
      expect(searchTradeAssets(rows, String(year)).map((x) => x.name)).toEqual([
        `${year} Pick 1.01`,
      ]);
      expect(isTradeableBoardRow(rows[0])).toBe(false);
      expect(isTradeableBoardRow(rows[1])).toBe(true);
    }
  });

  it("no year literal gates pick eligibility anywhere on /trade", () => {
    const page = read("../app/trade/page.jsx");
    const logic = read("../lib/trade-logic.js");
    expect(page).not.toMatch(/\/\^20\d\d\\b\/\.test\(/);
    expect(logic).not.toMatch(/\/\^20\d\d\\b\/\.test\(/);
    // both balancer pools and the search box route through the one predicate
    expect(page).toMatch(/isTradeableBoardRow/);
  });
});

describe("W08-F005 — owned picks sharing a label stay distinct and addable", () => {
  const picks = Array.from({ length: 8 }, (_, i) => ({
    label: "2027 1st",
    season: 2027,
    round: 1,
    original_roster_id: i + 1,
    assetId: `pick:dynasty_main:2027:r1:o${i + 1}`,
  }));
  const team = {
    name: "Jason",
    players: [],
    picks: picks.map((p) => p.label),
    pickDetails: picks,
    pickOwnershipState: "observed",
  };
  const tierCentre = (label) => ({ name: "2027 Mid 1st", assetClass: "pick", label });

  it("eight same-label firsts become eight entries with eight identities", () => {
    const entries = teamPickEntries(team, tierCentre);
    expect(entries).toHaveLength(8);
    expect(new Set(entries.map(tradeEntryKey)).size).toBe(8);
    // they share the priced board row but never the identity
    expect(new Set(entries.map((e) => e.name)).size).toBe(1);
  });

  it("the calculator accepts all of them on one side (no duplicate-name guard)", () => {
    const entries = teamPickEntries(team, tierCentre);
    let side = [];
    for (const e of entries) {
      expect(canAddEntry([{ assets: side }, { assets: [] }], e)).toBe(true);
      side = [...side, e];
    }
    expect(groupSideEntries(side)).toHaveLength(8);
  });
});

describe("W08-F007 — no value mode makes a legacy composite the trade meter's scale", () => {
  it("offers exactly one mode, canonical", () => {
    expect(VALUE_MODES.map((m) => m.key)).toEqual(["full"]);
    expect(TRADE_VALUE_MODE).toBe("full");
  });

  it("the audit's LaPorta (TE) vs Styles (LB) pair stays FAIR/even whatever .raw says", () => {
    const laporta = { name: "LaPorta", values: { full: 5222, raw: 5564 } };
    const styles = { name: "Styles", values: { full: 5222, raw: 4180 } };
    const [a, b] = adjustedSideTotals([laporta], [styles], TRADE_VALUE_MODE, {});
    expect(a.adjusted).toBe(5222);
    expect(b.adjusted).toBe(5222);
  });

  it("the page has no value-mode control", () => {
    const src = read("../app/trade/page.jsx");
    expect(src).not.toMatch(/aria-label="Value mode"/);
    expect(src).toMatch(/const valueMode = TRADE_VALUE_MODE;/);
  });
});
