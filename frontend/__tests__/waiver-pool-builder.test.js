// @vitest-environment node
import { describe, it, expect } from "vitest";

import * as waiverLogic from "@/lib/waiver-logic";
import { buildTopWaiverPool } from "@/lib/waiver-logic";

// ── Fixture helpers ────────────────────────────────────────────────────

function row(name, value, opts = {}) {
  return {
    name,
    pos: opts.pos || "WR",
    position: opts.pos || "WR",
    rookie: Boolean(opts.rookie),
    assetClass: opts.assetClass || "offense",
    rankDerivedValue: opts.rankDerivedValue !== undefined ? opts.rankDerivedValue : value,
    values: { full: value },
    confidenceBucket: opts.confidenceBucket || "medium",
    // Default to a corroborated multi-source player so existing
    // cases aren't swept by the two-source waiver gate.  Single-source
    // cases set sourceCount explicitly.
    sourceCount: opts.sourceCount !== undefined ? opts.sourceCount : 2,
  };
}

/** Build N rows at a position with descending values from start. */
function descending(prefix, n, start, step, opts = {}) {
  const out = [];
  for (let i = 0; i < n; i += 1) {
    out.push(row(`${prefix} ${i + 1}`, start - i * step, opts));
  }
  return out;
}

describe("buildTopWaiverPool — basic shape", () => {
  it("returns the top-N rows sorted by value desc when no coverage push needed", () => {
    const rows = [
      ...descending("QB", 5, 8000, 100, { pos: "QB" }),
      ...descending("RB", 5, 7000, 100, { pos: "RB" }),
      ...descending("WR", 5, 6000, 100, { pos: "WR" }),
      ...descending("TE", 5, 5000, 100, { pos: "TE" }),
    ];
    const out = buildTopWaiverPool(rows, new Set(), { limit: 10, minPerPosition: 1 });
    // Top 10 = 5 QBs (8000-7600) + 5 RBs (7000-6600); WR + TE
    // missing.  Coverage requires ≥1 of each — 2 injections push
    // the final count to 12.
    expect(out.cap).toBe(10);
    expect(out.players).toHaveLength(12);
    expect(out.injectedCount).toBe(2);
    expect(out.positionSummary.QB).toBe(5);
    expect(out.positionSummary.RB).toBe(5);
    expect(out.positionSummary.WR).toBe(1);
    expect(out.positionSummary.TE).toBe(1);
  });

  it("respects limit + minPerPosition + injects to satisfy floors", () => {
    const rows = [
      ...descending("QB", 8, 8000, 50, { pos: "QB" }),    // top 8 are all QB
      row("Rare WR", 1500, { pos: "WR" }),
      row("Rare WR2", 1400, { pos: "WR" }),
      row("Rare TE", 1300, { pos: "TE" }),
      row("Rare RB", 1200, { pos: "RB" }),
    ];
    // Top-3 by value: 3 QBs.  Need ≥3 of each of QB/RB/WR/TE per
    // the default floor (3).  Only 2 WRs in pool (insufficient),
    // 1 TE, 1 RB — so injection should pull all of them up.
    const out = buildTopWaiverPool(rows, new Set(), { limit: 3, minPerPosition: 3 });
    // Head = 3 QBs.  Injected = 2 WRs + 1 TE + 1 RB.  All available.
    expect(out.cap).toBe(3);
    expect(out.injectedCount).toBe(4);
    expect(out.players).toHaveLength(7);
    expect(out.positionSummary.QB).toBe(3);
    expect(out.positionSummary.WR).toBe(2);  // pool only had 2
    expect(out.positionSummary.TE).toBe(1);
    expect(out.positionSummary.RB).toBe(1);
  });

  it("breaks the cap only as much as needed for coverage", () => {
    const rows = [
      ...descending("QB", 50, 9000, 10, { pos: "QB" }),
      row("Lone WR", 100, { pos: "WR" }),
      row("Lone TE", 90, { pos: "TE" }),
      row("Lone RB", 80, { pos: "RB" }),
    ];
    const out = buildTopWaiverPool(rows, new Set(), { limit: 10, minPerPosition: 1 });
    // Top 10 are all QB.  Coverage needs 1 each of WR/TE/RB ⇒
    // 3 injections.
    expect(out.cap).toBe(10);
    expect(out.injectedCount).toBe(3);
    expect(out.players).toHaveLength(13);
  });
});

describe("buildTopWaiverPool — IDP gating", () => {
  const rows = [
    row("QB1", 8000, { pos: "QB" }),
    row("QB2", 7900, { pos: "QB" }),
    row("QB3", 7800, { pos: "QB" }),
    row("DL1", 6500, { pos: "DL", assetClass: "idp" }),
    row("LB1", 6400, { pos: "LB", assetClass: "idp" }),
    row("DB1", 6300, { pos: "DB", assetClass: "idp" }),
  ];

  it("includes IDP positions in coverage when idpEnabled=true", () => {
    const out = buildTopWaiverPool(rows, new Set(), {
      limit: 3,
      minPerPosition: 1,
      idpEnabled: true,
    });
    // Top 3 = 3 QBs.  IDP coverage requires DL/LB/DB ≥ 1 each ⇒
    // 3 injections.
    expect(out.cap).toBe(3);
    expect(out.injectedCount).toBe(3);
    expect(out.positionSummary.DL).toBe(1);
    expect(out.positionSummary.LB).toBe(1);
    expect(out.positionSummary.DB).toBe(1);
    expect(out.players.find((p) => p.name === "DL1")).toBeDefined();
  });

  it("drops IDP rows entirely when idpEnabled=false", () => {
    const out = buildTopWaiverPool(rows, new Set(), {
      limit: 3,
      minPerPosition: 1,
      idpEnabled: false,
    });
    // IDP rows excluded; pool = 3 QBs.
    expect(out.players).toHaveLength(3);
    expect(out.players.every((p) => p.assetClass !== "idp")).toBe(true);
    expect(out.positionSummary.DL).toBeUndefined();
    expect(out.positionSummary.LB).toBeUndefined();
    expect(out.positionSummary.DB).toBeUndefined();
  });
});

describe("buildTopWaiverPool — rookie gating", () => {
  const rows = [
    row("Vet WR1", 6000, { pos: "WR" }),
    row("Rookie WR1", 5500, { pos: "WR", rookie: true }),
    row("Rookie RB1", 5400, { pos: "RB", rookie: true }),
    row("Vet RB1", 4500, { pos: "RB" }),
  ];

  it("excludes rookies by default", () => {
    const out = buildTopWaiverPool(rows, new Set(), { limit: 10, minPerPosition: 1 });
    expect(out.players.map((p) => p.name)).toEqual(["Vet WR1", "Vet RB1"]);
  });

  it("includes rookies when includeRookies=true", () => {
    const out = buildTopWaiverPool(rows, new Set(), {
      limit: 10,
      minPerPosition: 1,
      includeRookies: true,
    });
    expect(out.players.map((p) => p.name)).toEqual([
      "Vet WR1",
      "Rookie WR1",
      "Rookie RB1",
      "Vet RB1",
    ]);
  });
});

describe("buildTopWaiverPool — ownership filtering", () => {
  const rows = [
    row("Owned WR", 6000, { pos: "WR" }),
    row("Free WR", 5500, { pos: "WR" }),
    row("My RB", 5400, { pos: "RB" }),
    row("Free RB", 4500, { pos: "RB" }),
  ];

  it("skips league-rostered names", () => {
    const owned = new Set(["owned wr"]);
    const out = buildTopWaiverPool(rows, owned, {
      limit: 10,
      minPerPosition: 1,
    });
    expect(out.players.find((p) => p.name === "Owned WR")).toBeUndefined();
    expect(out.players.find((p) => p.name === "Free WR")).toBeDefined();
  });

  it("skips my-roster names too when myRosterNameSet provided", () => {
    const owned = new Set(["owned wr"]);
    const mine = new Set(["my rb"]);
    const out = buildTopWaiverPool(rows, owned, {
      limit: 10,
      minPerPosition: 1,
      myRosterNameSet: mine,
    });
    expect(out.players.find((p) => p.name === "My RB")).toBeUndefined();
    expect(out.players.find((p) => p.name === "Owned WR")).toBeUndefined();
  });
});

// The client-side bid formula is GONE, and this is the guard against it
// coming back.  ``computeFaabHint`` was a JS port of the old Python
// ``_compute_faab_bid``; every dollar figure now comes from
// ``src/trade/faab_engine.py`` via the backend.  A second formula on the
// client is the exact drift the "no frontend ranking/valuation engine,
// period" rule exists to prevent — and this one had already gone
// numerically wrong against the engine before it was removed.
describe("waiver-logic exports no client-side bid calculator", () => {
  it("no longer exports computeFaabHint", () => {
    expect(waiverLogic.computeFaabHint).toBeUndefined();
    expect(Object.keys(waiverLogic)).not.toContain("computeFaabHint");
  });

  it("exports nothing that computes a FAAB/bid dollar figure", () => {
    // Name-shaped guard: a re-port under a new name (computeBid,
    // faabEstimate, bidHint, …) trips this without the test needing to
    // know the new name.  ``buildOwnedNameSet`` and friends are
    // unaffected — the pattern only matches faab/bid vocabulary.
    const offenders = Object.keys(waiverLogic).filter((k) => /faab|bid/i.test(k));
    expect(offenders).toEqual([]);
  });
});

describe("buildTopWaiverPool — must-have rookie fallback filter", () => {
  it("excludes rows with confidenceBucket=none even if values.full is high", () => {
    // The scraper's ``must_have_rookie_guarantee`` path seeds
    // synthetic values around 1888 for unranked prospects.  These
    // entries have rankDerivedValue=null + confidenceBucket='none'
    // and should never appear in the add pool — comparing them
    // against rostered players produces nonsense bids (the per-source
    // breakdown shows 0 vs N because no real source has them, but
    // the blended value lies).
    const rows = [
      // Real player — should appear.
      row("Real WR", 6000, { pos: "WR", confidenceBucket: "medium" }),
      // Must-have rookie fallback — should be filtered out.
      {
        name: "Synthetic Rookie",
        pos: "WR",
        position: "WR",
        assetClass: "offense",
        rookie: false, // some are flagged rookie=false but still synthetic
        rankDerivedValue: null,
        values: { full: 1888 },
        confidenceBucket: "none",
      },
    ];
    const out = buildTopWaiverPool(rows, new Set(), { limit: 10, minPerPosition: 1 });
    const names = out.players.map((p) => p.name);
    expect(names).toContain("Real WR");
    expect(names).not.toContain("Synthetic Rookie");
  });

  it("also filters legacy rows that lack confidenceBucket but flag fallbackValue", () => {
    const rows = [
      row("Real RB", 5000, { pos: "RB" }),
      {
        name: "Legacy Fallback",
        pos: "RB",
        position: "RB",
        assetClass: "offense",
        rankDerivedValue: null,
        values: { full: 2000 },
        // No confidenceBucket field — but explicit fallbackValue.
        fallbackValue: true,
      },
    ];
    const out = buildTopWaiverPool(rows, new Set(), { limit: 10, minPerPosition: 1 });
    expect(out.players.map((p) => p.name)).toContain("Real RB");
    expect(out.players.map((p) => p.name)).not.toContain("Legacy Fallback");
  });
});

describe("buildTopWaiverPool — two-source minimum", () => {
  it("excludes single-source and zero-source free agents", () => {
    const rows = [
      row("Multi WR", 6000, { pos: "WR", sourceCount: 3 }),
      row("Two-Source RB", 5500, { pos: "RB", sourceCount: 2 }),
      row("Solo WR", 6500, { pos: "WR", sourceCount: 1 }),
      row("No-Source TE", 6200, { pos: "TE", sourceCount: 0 }),
      // Raw literal with no sourceCount field at all — must be treated
      // as zero sources and excluded.
      {
        name: "Unset QB",
        pos: "QB",
        position: "QB",
        assetClass: "offense",
        rookie: false,
        rankDerivedValue: 5800,
        values: { full: 5800 },
        confidenceBucket: "medium",
      },
    ];
    const out = buildTopWaiverPool(rows, new Set(), { limit: 10, minPerPosition: 0 });
    const names = out.players.map((p) => p.name);
    expect(names).toContain("Multi WR");
    expect(names).toContain("Two-Source RB");
    expect(names).not.toContain("Solo WR");
    expect(names).not.toContain("No-Source TE");
    expect(names).not.toContain("Unset QB");
  });
});

describe("buildTopWaiverPool — defensive defaults", () => {
  it("returns empty pool for non-arrays", () => {
    expect(buildTopWaiverPool(null, new Set()).players).toEqual([]);
    expect(buildTopWaiverPool(undefined, new Set()).players).toEqual([]);
  });

  it("treats non-Set ownedNameSet as empty", () => {
    const rows = [row("WR1", 5000)];
    expect(
      buildTopWaiverPool(rows, null, { limit: 5, minPerPosition: 0 }).players,
    ).toEqual(rows);
  });
});
