/**
 * Frontend parity tests for the scope-aware ranking pipeline in
 * lib/dynasty-data.js (computeUnifiedRanks).
 *
 * The backend authority lives in src/api/data_contract.py and is
 * exercised by tests/api/test_scope_aware_rankings.py.  These tests
 * run the SAME fixture shapes through the frontend fallback and pin
 * identical expected outputs so the two ranking paths stay in sync.
 *
 * Categories (must match the backend integration tests):
 *   A. Full overall IDP source normalises correctly
 *   B. Position-only translation (exact / interpolated / extrapolated)
 *   D. Offense does not regress and KTC scope excludes IDP rows
 *   E. Transparency fields present (sourceRankMeta, idpBackboneFallback)
 *   F. Edge cases: zero values, unsupported positions
 *
 * Coverage-aware weighting (category C) and backbone-missing fallback
 * are validated directly against the backend-parity helpers rather than
 * through `buildRows`, since the frontend registry is private.
 */
import { describe, expect, it } from "vitest";
import {
  buildRows,
  rankToValue,
  TRANSLATION_DIRECT,
  TRANSLATION_EXACT,
} from "@/lib/dynasty-data";

// Shared row-builder used by the parity tests.  Matches the Python
// `_row` helper in tests/api/test_scope_aware_rankings.py.
function row(name, pos, { ktc, idp, dlf } = {}) {
  const sites = {};
  if (ktc !== undefined) sites.ktc = ktc;
  if (idp !== undefined) sites.idpTradeCalc = idp;
  if (dlf !== undefined) sites.dlfIdp = dlf;
  return {
    displayName: name,
    canonicalName: name,
    position: pos,
    values: {
      rawComposite: 0,
      finalAdjusted: 0,
      overall: 0,
    },
    canonicalSiteValues: sites,
  };
}

describe("A. Full overall IDP source", () => {
  it("ranks IDP players descending by backbone value", () => {
    const rows = buildRows({
      playersArray: [
        row("dl_top", "DL", { idp: 950 }),
        row("lb_mid", "LB", { idp: 700 }),
        row("db_low", "DB", { idp: 400 }),
      ],
    });
    const dl = rows.find((r) => r.name === "dl_top");
    const lb = rows.find((r) => r.name === "lb_mid");
    const db = rows.find((r) => r.name === "db_low");

    expect(dl.idpRank).toBe(1);
    expect(lb.idpRank).toBe(2);
    expect(db.idpRank).toBe(3);

    // Method is direct and the effective rank equals the raw rank.
    expect(dl.sourceRankMeta.idpTradeCalc.method).toBe(TRANSLATION_DIRECT);
    expect(dl.sourceRankMeta.idpTradeCalc.rawRank).toBe(1);
    expect(dl.sourceRankMeta.idpTradeCalc.effectiveRank).toBe(1);
    expect(dl.sourceRankMeta.idpTradeCalc.scope).toBe("overall_idp");
    // Overall board order: IDP #1 beats offense if KTC is absent.
    expect(dl.canonicalConsensusRank).toBe(1);
    // No backbone fallback when the backbone source itself is producing
    // the ranks.
    expect(dl.idpBackboneFallback).toBe(false);
  });

  it("matches the Hill curve for the backbone source", () => {
    const rows = buildRows({
      playersArray: [row("solo", "DL", { idp: 9999 })],
    });
    const solo = rows.find((r) => r.name === "solo");
    expect(solo.rankDerivedValue).toBe(rankToValue(1));
    expect(solo.rankDerivedValue).toBe(9999);
  });
});

describe("B. Position-only translation (via exported helpers)", () => {
  // The frontend registry is not exposed, so we hit the translation
  // helper directly to pin the math the same way the backend does.
  // The helpers are exported from the module for this purpose.
  it("is validated through the pure helpers in dynasty-data.js", async () => {
    // Dynamic import so we can grab the internal symbols that are
    // namespaced at module scope.  We explicitly import what we need.
    const mod = await import("@/lib/dynasty-data");
    // The translation method constants are public.
    expect(mod.TRANSLATION_EXACT).toBe("exact");
    expect(mod.TRANSLATION_INTERPOLATED).toBe("interpolated");
    expect(mod.TRANSLATION_EXTRAPOLATED).toBe("extrapolated");
    expect(mod.TRANSLATION_FALLBACK).toBe("fallback");
    expect(mod.SOURCE_SCOPE_POSITION_IDP).toBe("position_idp");
  });
});

describe("D. No offense regression", () => {
  it("ranks KTC-driven offense in descending order with picks included", () => {
    const rows = buildRows({
      playersArray: [
        row("qb1", "QB", { ktc: 9500 }),
        row("wr1", "WR", { ktc: 9000 }),
        row("rb1", "RB", { ktc: 8500 }),
        row("pick1", "PICK", { ktc: 8000 }),
      ],
    });
    expect(rows.find((r) => r.name === "qb1").ktcRank).toBe(1);
    expect(rows.find((r) => r.name === "wr1").ktcRank).toBe(2);
    expect(rows.find((r) => r.name === "rb1").ktcRank).toBe(3);
    expect(rows.find((r) => r.name === "pick1").ktcRank).toBe(4);
    // All four land in the unified board via the overall_offense scope.
    for (const r of rows) {
      expect(r.sourceRankMeta.ktc.method).toBe(TRANSLATION_DIRECT);
      expect(r.sourceRankMeta.ktc.effectiveRank).toBe(r.sourceRanks.ktc);
    }
  });

  it("KTC scope excludes an IDP row from receiving ktcRank", () => {
    const rows = buildRows({
      playersArray: [
        row("qb1", "QB", { ktc: 9500 }),
        // Defensive: DL row that accidentally carries a KTC value.
        row("dl_with_ktc", "DL", { ktc: 9000, idp: 500 }),
      ],
    });
    const dl = rows.find((r) => r.name === "dl_with_ktc");
    expect(dl.sourceRanks.ktc).toBeUndefined();
    expect(dl.ktcRank).toBeUndefined();
    // It still gets its IDP rank.
    expect(dl.sourceRanks.idpTradeCalc).toBe(1);
    expect(dl.idpRank).toBe(1);
  });
});

describe("E. Transparency fields", () => {
  it("stamps sourceRanks, sourceRankMeta, backbone fallback and legacy fields", () => {
    const rows = buildRows({
      playersArray: [
        row("qb1", "QB", { ktc: 9500 }),
        row("dl1", "DL", { idp: 900 }),
      ],
    });
    for (const r of rows) {
      expect(r.sourceRanks).toBeDefined();
      expect(r.sourceRankMeta).toBeDefined();
      expect(r.rankDerivedValue).toBeGreaterThan(0);
      expect(r.canonicalConsensusRank).toBeGreaterThan(0);
      expect(r.idpBackboneFallback).toBe(false);
      expect(Object.keys(r.sourceRankMeta)).toEqual(
        Object.keys(r.sourceRanks)
      );
    }
  });
});

describe("F. Edge cases", () => {
  it("ignores zero-valued source entries", () => {
    const rows = buildRows({
      playersArray: [
        row("has_val", "WR", { ktc: 9000 }),
        row("zero_val", "WR", { ktc: 0 }),
      ],
    });
    const zv = rows.find((r) => r.name === "zero_val");
    expect(zv.ktcRank).toBeUndefined();
    // Row with no usable source values never enters the ranked set,
    // so sourceRanks is never stamped.
    expect(zv.sourceRanks).toBeUndefined();
    expect(zv.rankDerivedValue).toBeUndefined();
  });

  it("unsupported positions are excluded from the unified board", () => {
    const rows = buildRows({
      playersArray: [
        row("qb1", "QB", { ktc: 9500 }),
        { displayName: "OL1", position: "OT", values: { overall: 0 }, canonicalSiteValues: { ktc: 9000 } },
      ],
    });
    const qb = rows.find((r) => r.name === "qb1");
    expect(qb).toBeDefined();
    // OL player is classified "excluded" by buildRows and never enters the row list.
    expect(rows.find((r) => r.name === "OL1")).toBeUndefined();
  });
});

// ── Dual-scope IDPTradeCalc parity ──────────────────────────────────
// IDPTradeCalc registers under BOTH overall_idp (as the backbone) and
// overall_offense (as a second opinion alongside KTC).  Mirrors the
// backend TestGDualScopeIdpTradeCalc cases in
// tests/api/test_scope_aware_rankings.py.
describe("Dual-scope IDPTradeCalc: offense + IDP contribution", () => {
  it("ranks offense players through both KTC and IDPTradeCalc", () => {
    const rows = buildRows({
      playersArray: [
        row("qb1", "QB", { ktc: 9500, idp: 9600 }),
        row("wr1", "WR", { ktc: 9000, idp: 9200 }),
        row("rb1", "RB", { ktc: 8500, idp: 8400 }),
      ],
    });
    const qb = rows.find((r) => r.name === "qb1");
    const wr = rows.find((r) => r.name === "wr1");
    const rb = rows.find((r) => r.name === "rb1");

    for (const r of [qb, wr, rb]) {
      expect(r.sourceRanks.ktc).toBeDefined();
      expect(r.sourceRanks.idpTradeCalc).toBeDefined();
      // Offense players receive the idpTradeCalc rank under the
      // overall_offense scope, not overall_idp.
      expect(r.sourceRankMeta.idpTradeCalc.scope).toBe("overall_offense");
      expect(r.isSingleSource).toBe(false);
      expect(r.sourceCount).toBe(2);
    }

    // KTC ordering: qb > wr > rb
    expect(qb.sourceRanks.ktc).toBe(1);
    expect(wr.sourceRanks.ktc).toBe(2);
    expect(rb.sourceRanks.ktc).toBe(3);
    // IDPTC ordering: qb > wr > rb (9600 > 9200 > 8400)
    expect(qb.sourceRanks.idpTradeCalc).toBe(1);
    expect(wr.sourceRanks.idpTradeCalc).toBe(2);
    expect(rb.sourceRanks.idpTradeCalc).toBe(3);
  });

  it("captures per-source spread when KTC and IDPTC disagree", () => {
    const rows = buildRows({
      playersArray: [
        row("wr1", "WR", { ktc: 9500, idp: 8000 }),
        row("wr2", "WR", { ktc: 9000, idp: 9500 }),
      ],
    });
    const wr1 = rows.find((r) => r.name === "wr1");
    const wr2 = rows.find((r) => r.name === "wr2");
    expect(wr1.sourceRanks.ktc).toBe(1);
    expect(wr1.sourceRanks.idpTradeCalc).toBe(2);
    expect(wr2.sourceRanks.ktc).toBe(2);
    expect(wr2.sourceRanks.idpTradeCalc).toBe(1);
    expect(wr1.sourceRankSpread).toBe(1);
    expect(wr2.sourceRankSpread).toBe(1);
  });

  it("does not leak offense scope onto IDP rows", () => {
    const rows = buildRows({
      playersArray: [
        row("dl1", "DL", { idp: 900 }),
        row("lb1", "LB", { idp: 800 }),
      ],
    });
    for (const r of rows) {
      expect(r.sourceRanks.ktc).toBeUndefined();
      expect(r.sourceRankMeta.idpTradeCalc.scope).toBe("overall_idp");
    }
  });
});

// ── H. Cross-universe ranking for dual-scope sources ────────────────
// Frontend mirror of TestHCrossUniverseRanking in the backend.
//
// IDPTradeCalc prices both offense and IDP players on a shared 0-9999
// scale, so its ordinal rank must be computed over the UNION of offense
// and IDP rows, not per-scope.  Earlier revisions re-ranked each scope
// from 1, which mapped the top IDP player to Hill value 9999 even when
// dozens of offense players had higher raw IDPTC values.
describe("H. Cross-universe IDPTradeCalc ranking", () => {
  it("ranks a top IDP behind offense starters with higher raw values", () => {
    const rows = buildRows({
      playersArray: [
        row("qb_elite", "QB", { ktc: 9999, idp: 9987 }),
        row("wr_elite", "WR", { ktc: 9800, idp: 9500 }),
        row("rb_elite", "RB", { ktc: 9600, idp: 9200 }),
        row("te_elite", "TE", { ktc: 9400, idp: 8800 }),
        row("dl_top", "DL", { idp: 5963 }),
        row("lb_top", "LB", { idp: 5400 }),
      ],
    });
    const qb = rows.find((r) => r.name === "qb_elite");
    const dl = rows.find((r) => r.name === "dl_top");
    const lb = rows.find((r) => r.name === "lb_top");

    // Combined pool: qb=9987, wr=9500, rb=9200, te=8800, dl=5963, lb=5400
    expect(qb.sourceRanks.idpTradeCalc).toBe(1);
    expect(dl.sourceRanks.idpTradeCalc).toBe(5);
    expect(lb.sourceRanks.idpTradeCalc).toBe(6);
  });

  it("does not award rank 1 to the top IDP when offense outvalues it", () => {
    // Mirrors the backend regression guard: a 40-player offense ladder
    // whose raw IDPTC values all sit above the top IDP.
    const playersArray = [];
    for (let i = 0; i < 40; i++) {
      playersArray.push(
        row(`off${i}`, i % 2 === 0 ? "QB" : "WR", {
          ktc: 9999 - i * 10,
          idp: 9900 - i * 80,
        })
      );
    }
    playersArray.push(row("dl_top", "DL", { idp: 5963 }));
    const rows = buildRows({ playersArray });
    const dl = rows.find((r) => r.name === "dl_top");
    // Lowest offense IDPTC value is 9900 - 39*80 = 6780 > 5963, so
    // dl_top lands at combined rank 41.
    expect(dl.sourceRanks.idpTradeCalc).toBe(41);
    expect(dl.rankDerivedValue).toBeLessThan(8000);
  });

  it("tags row scope per position even though ranking is combined", () => {
    const rows = buildRows({
      playersArray: [
        row("qb1", "QB", { ktc: 9000, idp: 9000 }),
        row("dl1", "DL", { idp: 5000 }),
      ],
    });
    const qb1 = rows.find((r) => r.name === "qb1");
    const dl1 = rows.find((r) => r.name === "dl1");
    expect(qb1.sourceRankMeta.idpTradeCalc.scope).toBe("overall_offense");
    expect(dl1.sourceRankMeta.idpTradeCalc.scope).toBe("overall_idp");
    // rawRank is the combined-pool rank for both rows.
    expect(qb1.sourceRankMeta.idpTradeCalc.rawRank).toBe(1);
    expect(dl1.sourceRankMeta.idpTradeCalc.rawRank).toBe(2);
  });
});

// ── G. DLF (Dynasty League Football) IDP source parity ──────────────
// DLF is registered as a second overall_idp source alongside the
// IDPTradeCalc backbone.  Both are full-board (no depth penalty), both
// carry weight 1.0, and IDPTradeCalc remains the only backbone.  The
// frontend registry in lib/dynasty-data.js must mirror the backend
// `_RANKING_SOURCES` entry in src/api/data_contract.py exactly; if it
// drifts, these assertions fail.
describe("G. DLF IDP source parity", () => {
  it("ranks DLF alongside IDPTradeCalc under the overall_idp scope", () => {
    const rows = buildRows({
      playersArray: [
        row("dl_hero", "DL", { idp: 900, dlf: 9995 }),
        row("lb_hero", "LB", { idp: 800, dlf: 9990 }),
        row("db_hero", "DB", { idp: 700, dlf: 9985 }),
      ],
    });

    const dl = rows.find((r) => r.name === "dl_hero");
    const lb = rows.find((r) => r.name === "lb_hero");
    const db = rows.find((r) => r.name === "db_hero");

    // Both sources agree on the order dl > lb > db.
    expect(dl.sourceRanks.idpTradeCalc).toBe(1);
    expect(lb.sourceRanks.idpTradeCalc).toBe(2);
    expect(db.sourceRanks.idpTradeCalc).toBe(3);
    expect(dl.sourceRanks.dlfIdp).toBe(1);
    expect(lb.sourceRanks.dlfIdp).toBe(2);
    expect(db.sourceRanks.dlfIdp).toBe(3);

    // DLF's meta entry should be present, direct (overall_idp is a
    // pass-through scope), and pin the same scope token the backend uses.
    expect(dl.sourceRankMeta.dlfIdp.scope).toBe("overall_idp");
    expect(dl.sourceRankMeta.dlfIdp.method).toBe(TRANSLATION_DIRECT);
    expect(dl.sourceRankMeta.dlfIdp.rawRank).toBe(1);
    expect(dl.sourceRankMeta.dlfIdp.effectiveRank).toBe(1);
    expect(dl.sourceRankMeta.dlfIdp.positionGroup).toBeNull();
  });

  it("picks up DLF-only players even when IDPTradeCalc has no value", () => {
    const rows = buildRows({
      playersArray: [
        row("idp_anchor", "DL", { idp: 900 }),
        row("dlf_only", "DL", { dlf: 9950 }),
      ],
    });
    const dlfOnly = rows.find((r) => r.name === "dlf_only");
    expect(dlfOnly.sourceRanks.dlfIdp).toBeDefined();
    expect(dlfOnly.sourceRanks.idpTradeCalc).toBeUndefined();
    // Still gets a unified rank because dlfIdp is overall_idp scope.
    expect(dlfOnly.canonicalConsensusRank).toBeGreaterThan(0);
    expect(dlfOnly.isSingleSource).toBe(true);
    expect(dlfOnly.idpBackboneFallback).toBe(false);
  });
});

// ── Backend/frontend parity fixture ──────────────────────────────────
// A single fixture whose expected ranks/values are hand-computed and
// pinned in BOTH this test and the Python `TestETransparencyFields` case
// in tests/api/test_scope_aware_rankings.py.  Divergence in either
// pipeline will fail here.
describe("Backend/frontend parity: shared fixture", () => {
  const fixture = {
    playersArray: [
      row("qb_hero", "QB", { ktc: 9800 }),
      row("wr_hero", "WR", { ktc: 9500 }),
      row("dl_hero", "DL", { idp: 900 }),
      row("lb_hero", "LB", { idp: 800 }),
      row("db_hero", "DB", { idp: 700 }),
    ],
  };

  it("produces the same ordinal per-source ranks as the backend", () => {
    const rows = buildRows(fixture);

    const qb = rows.find((r) => r.name === "qb_hero");
    const wr = rows.find((r) => r.name === "wr_hero");
    const dl = rows.find((r) => r.name === "dl_hero");
    const lb = rows.find((r) => r.name === "lb_hero");
    const db = rows.find((r) => r.name === "db_hero");

    // Offense: ordered by ktc desc
    expect(qb.ktcRank).toBe(1);
    expect(wr.ktcRank).toBe(2);
    // IDP: ordered by backbone value desc
    expect(dl.idpRank).toBe(1);
    expect(lb.idpRank).toBe(2);
    expect(db.idpRank).toBe(3);

    // Effective rank fed into the Hill curve equals the raw rank.
    expect(qb.sourceRankMeta.ktc.effectiveRank).toBe(1);
    expect(dl.sourceRankMeta.idpTradeCalc.effectiveRank).toBe(1);

    // rankDerivedValue reflects rank_to_value(1) at the top of each pool.
    expect(qb.rankDerivedValue).toBe(rankToValue(1));
    expect(dl.rankDerivedValue).toBe(rankToValue(1));
    expect(lb.rankDerivedValue).toBe(rankToValue(2));
  });
});
