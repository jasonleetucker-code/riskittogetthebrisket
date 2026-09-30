import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import * as TL from "@/lib/trade-logic";

// OWNER DIRECTIVE 2026-09-29: the draft-capital stack effect is
// INFORMATIONAL ONLY.  It must not affect side totals, the verdict,
// fairness classification, multi-team comparisons, side flows, balancer
// suggestions, or anything driven by the package totals.  The adjusted
// package total is RAW + VALUE ADJUSTMENT -- nothing else.
//
// Re-admitting the stack term requires an explicit, owner-approved
// methodology meeting the prerequisites in issue #1529 (Calculator Ideas).
// Changing this file to let it back in is that decision, not a test fix.

const A = { name: "Player A", pos: "WR", assetClass: "offense", values: { full: 3000 } };
const C = { name: "Player C", pos: "RB", assetClass: "offense", values: { full: 2000 } };
const PICK = { name: "2027 Mid 1st", pos: "PICK", assetClass: "pick", values: { full: 5487 } };
const LATE = { name: "2029 Mid 5th", pos: "PICK", assetClass: "pick", values: { full: 1399 } };

// A context the informational model DOES respond to strongly, so every
// "no effect" assertion below is meaningful.
const LIVE_STACK = {
  sideTeams: ["T0", "T1", "T2"],
  leagueStacks: { T0: 541, T1: 0, T2: 327, T3: 115, T4: 101, T5: 89, T6: 8, T7: 2 },
  moves: [
    { from: 1, to: 0, dollars: 72 },
    { from: 2, to: 0, dollars: 3 },
  ],
  boardPerDollar: 165,
};

describe("decision helpers take no stack input", () => {
  it("the fixture context is live for the informational model", () => {
    const stack = TL.computeStackAdjustments(3, LIVE_STACK);
    expect(stack.some((v) => Math.abs(v) > 100)).toBe(true);
  });

  const sides2 = [
    { assets: [A, C] },
    { assets: [PICK, LATE] },
  ];
  const sides3 = [
    { assets: [A], destinations: { "Player A": 1 } },
    { assets: [PICK], destinations: { "2027 Mid 1st": 2 } },
    { assets: [LATE, C], destinations: { "2029 Mid 5th": 0, "Player C": 0 } },
  ];

  // Every current decision owner, called with and without a stack context
  // in every trailing position (positional AND options-object forms).
  const cases = {
    adjustedSideTotals: (extra) => TL.adjustedSideTotals([A, C], [PICK, LATE], "full", null, ...extra),
    multiAdjustedSideTotals: (extra) =>
      TL.multiAdjustedSideTotals(sides3.map((s) => s.assets), "full", null, ...extra),
    tradeGapAdjusted: (extra) => TL.tradeGapAdjusted([A, C], [PICK, LATE], "full", null, ...extra),
    computeSideFlows: (extra) => TL.computeSideFlows(sides3, "full", null, ...extra),
    tradeImbalance2: (extra) => TL.tradeImbalance(sides2, "full", null, ...extra),
    tradeImbalance3: (extra) => TL.tradeImbalance(sides3, "full", null, ...extra),
    findBalancers: (extra) =>
      TL.findBalancers(sides2, 0, [C, LATE, { ...A, name: "Player D" }], "full", {
        settings: null,
        ...(extra.length ? { stackContext: extra[0] } : {}),
      }),
  };
  for (const [name, call] of Object.entries(cases)) {
    it(`${name}: identical with or without a stack context`, () => {
      const base = call([]);
      expect(call([LIVE_STACK])).toEqual(base);
      expect(call([LIVE_STACK, LIVE_STACK])).toEqual(base);
    });
  }

  it("the adjusted total is exactly raw + Value Adjustment, with no third term", () => {
    for (const t of [
      ...TL.adjustedSideTotals([A, C], [PICK, LATE], "full"),
      ...TL.multiAdjustedSideTotals(sides3.map((s) => s.assets), "full"),
    ]) {
      expect(Object.keys(t).sort()).toEqual(["adjusted", "adjustment", "raw"]);
      expect(t.adjusted).toBe(t.raw + t.adjustment);
    }
  });

  it("no decision helper's code reaches the stack model", () => {
    for (const fn of [
      TL.adjustedSideTotals,
      TL.multiAdjustedSideTotals,
      TL.tradeGapAdjusted,
      TL.computeSideFlows,
      TL.tradeImbalance,
      TL.findBalancers,
      TL.computeValueAdjustment,
      TL.computeMultiSideAdjustments,
    ]) {
      expect(fn.toString()).not.toMatch(/computeStackAdjustments|stackContext|stackAdjustment/);
    }
  });
});

describe("no frontend caller feeds the stack into a decision", () => {
  const root = resolve(__dirname, "..");
  const files = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      if (name === "node_modules" || name.startsWith(".") || name === "__tests__") continue;
      const full = join(dir, name);
      if (statSync(full).isDirectory()) walk(full);
      else if (/\.(js|jsx)$/.test(name)) files.push(full);
    }
  };
  for (const d of ["app", "components", "lib"]) walk(join(root, d));

  const DECISION = [
    "adjustedSideTotals",
    "multiAdjustedSideTotals",
    "tradeGapAdjusted",
    "computeSideFlows",
    "tradeImbalance",
    "findBalancers",
    "meterVerdict",
    "verdictFromGap",
  ];
  const callArgs = (src, fn) => {
    const out = [];
    const re = new RegExp(`\\b${fn}\\(`, "g");
    let m;
    while ((m = re.exec(src))) {
      let depth = 0;
      let j = m.index + fn.length;
      for (; j < src.length; j++) {
        if (src[j] === "(") depth++;
        else if (src[j] === ")" && --depth === 0) break;
      }
      out.push(src.slice(m.index, j + 1));
    }
    return out;
  };

  it("scans real sources", () => {
    expect(files.some((f) => f.endsWith(join("app", "trade", "page.jsx")))).toBe(true);
  });

  it("no call to a decision helper mentions the stack", () => {
    const offenders = [];
    for (const f of files) {
      const src = readFileSync(f, "utf8");
      for (const fn of DECISION) {
        for (const call of callArgs(src, fn)) {
          if (/stack/i.test(call)) offenders.push(`${f}: ${call.slice(0, 120)}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  // Whole-file identifier rule: the stack model may be touched on /trade
  // ONLY inside the STACK-NOTE-ONLY fences (the model's memo, the note memo
  // and the note JSX).  Anything else -- subtracting the note from a total,
  // passing it to a component as a prop, a new inline "adjusted - stack" --
  // mentions one of these names outside a fence and fails here.
  const STACK_NAMES =
    /\b(stackContext|stackNote|stackAdjustments?|computeStackAdjustments|leagueStacks|boardPerDollar|poolBoardPerDollar|buildLeagueStacks|pickAuctionDollars|effectiveAuctionPower\w*)\b/;
  const stripImports = (src) => src.replace(/^import[\s\S]*?from\s+["'][^"']+["'];?$/gm, "");
  const stripFences = (src) =>
    src.replace(/STACK-NOTE-ONLY:BEGIN[\s\S]*?STACK-NOTE-ONLY:END/g, "");

  it("/trade touches the stack model only inside STACK-NOTE-ONLY fences", () => {
    const page = readFileSync(join(root, "app", "trade", "page.jsx"), "utf8");
    expect((page.match(/STACK-NOTE-ONLY:BEGIN/g) || []).length).toBe(2);
    const outside = stripFences(stripImports(page));
    const hits = outside.split(/\r?\n/).filter((l) => STACK_NAMES.test(l));
    expect(hits).toEqual([]);
  });

  it("no other frontend file consumes the stack model", () => {
    const owners = new Set(
      [["lib", "trade-logic.js"], ["lib", "pick-stack.js"], ["lib", "auction-power.js"], ["app", "trade", "page.jsx"]].map(
        (parts) => join(root, ...parts),
      ),
    );
    // The league Draft Capital page and its simulator show effective auction
    // POWER in dollars -- a display lens with no trade verdict; they may
    // use the power function, never the trade stack adjustment.
    const powerLens = new Set(
      [["app", "league", "sections", "draft-capital.jsx"], ["app", "league", "sections", "_trade-simulator.jsx"]].map(
        (parts) => join(root, ...parts),
      ),
    );
    const TRADE_STACK = /\b(stackContext|stackNote|stackAdjustments?|computeStackAdjustments|leagueStacks|boardPerDollar|poolBoardPerDollar)\b/;
    const offenders = [];
    for (const f of files) {
      if (owners.has(f)) continue;
      const src = stripImports(readFileSync(f, "utf8"));
      const re = powerLens.has(f) ? TRADE_STACK : STACK_NAMES;
      src.split(/\r?\n/).forEach((l, i) => {
        if (re.test(l)) offenders.push(`${f}:${i + 1}: ${l.trim().slice(0, 100)}`);
      });
    }
    expect(offenders).toEqual([]);
  });

  it("/trade still computes the stack effect -- for the labelled note only", () => {
    const page = readFileSync(join(root, "app", "trade", "page.jsx"), "utf8");
    expect(page).toMatch(/computeStackAdjustments\(sidesWithOverrides\.length, stackContext\)/);
    expect(page).toMatch(/experimental, not calibrated/);
    expect(page).toMatch(/Not included in the totals or verdict/);
  });
});
