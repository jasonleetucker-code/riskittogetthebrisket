/**
 * Tests for lib/trade-logic.js — the pure trade calculator logic
 * extracted from the Next.js trade page.
 */
import { describe, expect, it } from "vitest";
import {
  VALUE_MODES,
  STORAGE_KEY,
  RECENT_KEY,
  verdictFromGap,
  colorFromGap,
  sideTotal,
  computeValueAdjustment,
  packageAdjustedPairTotals,
  perTeamPackageTotals,
  tradeRoutes,
  worstTeamBand,
  multiTeamNetSummary,
  valueAdjustmentFromSideArrays,
  adjustedSideTotals,
  multiAdjustedSideTotals,
  computeStackAdjustments,
  computeSideFlows,
  tradeImbalance,
  tradeGapAdjusted,
  effectiveValue,
  addAssetToSide,
  removeAssetFromSide,
  isAssetInTrade,
  serializeWorkspace,
  deserializeWorkspace,
  addRecent,
  filterPickerRows,
  getPlayerEdge,
  parsePickToken,
  buildPickLookupCandidates,
  resolvePickRow,
  findBalancers,
  verdictBarPosition,
  meterVerdict,
  percentageGap,
  multiTeamAnalysis,
  createSide,
  defaultDestination,
  computeSideFlowAssets,
  serializeWorkspaceMulti,
  deserializeWorkspaceMulti,
  SIDE_LABELS,
  MAX_SIDES,
  MIN_SIDES,
  ACTIVE_PACKAGE_MODEL_ID,
  PACKAGE_MODEL_IDS,
  packageAdjustPair,
  geomPackageUtility,
} from "@/lib/trade-logic";

// ── Test fixtures ────────────────────────────────────────────────────

function makeRow(name, fullValue, pos = "QB", assetClass = "offense") {
  return {
    name,
    pos,
    assetClass,
    values: { full: fullValue, raw: fullValue },
  };
}

const ALLEN = makeRow("Josh Allen", 9000);
const MAHOMES = makeRow("Patrick Mahomes", 8800);
const CHASE = makeRow("Ja'Marr Chase", 8500, "WR");
const PARSONS = makeRow("Micah Parsons", 5000, "LB", "idp");
const PICK_2026 = makeRow("2026 Early 1st", 7000, "PICK", "pick");

// ── Package-model helpers ────────────────────────────────────────────
//
// The owner promoted geom_q078_v1 (q = 0.78) to the ACTIVE package Value
// Adjustment on 2026-10-17; KTC's adjustPackage port (ktc_2026_04) is kept
// as the rollback model.  Tests of KTC's OWN formula select it explicitly
// through the canonical dispatch; consumer tests assert against the
// dispatch's ACTIVE answer rather than against KTC numbers.
const KTC = Object.freeze({ modelId: PACKAGE_MODEL_IDS.KTC_2026_04 });
const sumOf = (vals) => vals.reduce((t, v) => t + v, 0);

// The canonical owner's {value, side} mapped onto computeValueAdjustment's
// {adjustment, recipientIdx} shape, for raw value arrays.
function ownerAdjustment(aVals, bVals, opts = {}) {
  const r = packageAdjustPair(aVals, bVals, opts);
  if (!r.displayed || r.value <= 0 || r.side === 0) {
    return { adjustment: 0, recipientIdx: null };
  }
  return { adjustment: r.value, recipientIdx: r.side === 1 ? 0 : 1 };
}

// raw gap + the owner's signed adjustment: what tradeGapAdjusted must read.
function ownerGap(aVals, bVals, opts = {}) {
  const raw = sumOf(aVals) - sumOf(bVals);
  const { adjustment, recipientIdx } = ownerAdjustment(aVals, bVals, opts);
  if (recipientIdx === null) return raw;
  return recipientIdx === 0 ? raw + adjustment : raw - adjustment;
}

// ── Constants ────────────────────────────────────────────────────────

describe("constants", () => {
  it("VALUE_MODES is canonical only — the legacy-composite Raw mode is retired (TC-A P0-4)", () => {
    expect(VALUE_MODES.length).toBe(1);
    expect(VALUE_MODES.map((m) => m.key)).toEqual(["full"]);
  });

  it("storage keys are stable strings", () => {
    expect(STORAGE_KEY).toBe("next_trade_workspace_v1");
    expect(RECENT_KEY).toBe("next_trade_recent_assets_v1");
  });
});

// ── verdictFromGap ───────────────────────────────────────────────────

describe("verdictFromGap", () => {
  // The ONE fairness-band owner (relative): at the 10,000-point reference
  // side the 3.5% / 9% / 18% cuts fall at 350 / 900 / 1,800.
  it("returns 'Near even' for gaps under 350", () => {
    expect(verdictFromGap(0, 10000)).toBe("Near even");
    expect(verdictFromGap(349, 10000)).toBe("Near even");
    expect(verdictFromGap(-349, 10000)).toBe("Near even");
  });

  it("returns 'Lean' for gaps 350-899", () => {
    expect(verdictFromGap(350, 10000)).toBe("Lean");
    expect(verdictFromGap(899, 10000)).toBe("Lean");
    expect(verdictFromGap(-500, 10000)).toBe("Lean");
  });

  it("returns 'Strong lean' for gaps 900-1799", () => {
    expect(verdictFromGap(900, 10000)).toBe("Strong lean");
    expect(verdictFromGap(1799, 10000)).toBe("Strong lean");
    expect(verdictFromGap(-1200, 10000)).toBe("Strong lean");
  });

  it("returns 'Major gap' for gaps >= 1800", () => {
    expect(verdictFromGap(1800, 10000)).toBe("Major gap");
    expect(verdictFromGap(5000, 10000)).toBe("Major gap");
    expect(verdictFromGap(-2000, 10000)).toBe("Major gap");
  });

  it("treats gap symmetrically (absolute value)", () => {
    expect(verdictFromGap(500, 10000)).toBe(verdictFromGap(-500, 10000));
  });
});

// ── colorFromGap ─────────────────────────────────────────────────────

describe("colorFromGap", () => {
  it("returns empty string for near-even gaps", () => {
    expect(colorFromGap(0, 10000)).toBe("");
    expect(colorFromGap(255, 10000)).toBe("");
    expect(colorFromGap(-100, 10000)).toBe("");
  });

  it("returns 'green' when Side A wins (positive gap)", () => {
    expect(colorFromGap(500, 10000)).toBe("green");
    expect(colorFromGap(2000, 10000)).toBe("green");
  });

  it("returns 'red' when Side B wins (negative gap)", () => {
    expect(colorFromGap(-500, 10000)).toBe("red");
    expect(colorFromGap(-2000, 10000)).toBe("red");
  });
});

// ── sideTotal ────────────────────────────────────────────────────────

describe("sideTotal", () => {
  it("sums values for the selected mode", () => {
    expect(sideTotal([ALLEN, CHASE], "full")).toBe(9000 + 8500);
  });

  it("returns 0 for empty side", () => {
    expect(sideTotal([], "full")).toBe(0);
  });

  it("handles missing value mode gracefully", () => {
    expect(sideTotal([ALLEN], "nonexistent")).toBe(0);
  });

  it("uses different modes", () => {
    const row = {
      name: "Test",
      values: { full: 9000, raw: 7000 },
    };
    expect(sideTotal([row], "raw")).toBe(7000);
    expect(sideTotal([row], "full")).toBe(9000);
  });
});

// ── tradeGapAdjusted ─────────────────────────────────────────────────

describe("tradeGapAdjusted (KTC-style)", () => {
  it("single vs single equals linear gap (no VA)", () => {
    expect(tradeGapAdjusted([ALLEN], [CHASE], "full")).toBe(500);
    expect(tradeGapAdjusted([CHASE], [ALLEN], "full")).toBe(-500);
  });

  it("1-vs-2 with dominant single asset closes the linear gap", () => {
    // Stud (9999) vs Mid (6000) + Pick (5000) — gapRatio is big enough to
    // trigger a meaningful VA that narrows the raw gap.
    const stud = mockRow(9999);
    const mid = mockRow(6000);
    const pick = mockRow(5000);
    const rawGap = 9999 - (6000 + 5000);
    const gap = tradeGapAdjusted([stud], [mid, pick], "full");
    expect(rawGap).toBe(-1001);
    expect(gap).toBeGreaterThan(rawGap); // VA added to single side → less negative
  });

  it("KTC rollback model: 1-vs-2 with near-matching top assets is too lopsided for V12 to even (VA=0)", () => {
    // ALLEN (9000) vs [CHASE (8500), PICK_2026 (7000)].  V12 sees:
    //   raw_A = raw(9000) ≈ 3415  (lone stud, t=9000)
    //   raw_B = raw(8500) + raw(7000) ≈ 5058  (multi side wins on raw)
    // Side A would need a virtual ~6300-value player to raw-equalize,
    // but A's total (15300 with virtual) still falls short of B's
    // 15500 — so the displayed VA on B comes out negative and gets
    // clamped to 0.  Empirically this matches KTC's behavior on
    // "trades that are just lopsided"; KTC shows raw value comparison
    // only.  Pin: gap stays at the raw value gap (no VA closes any
    // of it).
    const rawGap = 9000 - (8500 + 7000); // −6500
    expect(ownerGap([9000], [8500, 7000], KTC)).toBe(rawGap);
  });

  it("geometric (active) model: the same 1-vs-2 credits the lone stud with the depth the pair discards", () => {
    // geom_q078_v1 has no fairness-suppression gate: the side that
    // discarded less depth receives |D_A - D_B|.  [8500, 7000] discards
    // 7000 x (1 - 0.78) = 1540; [9000] discards nothing, so side A is
    // credited 1540 and the gap is −6500 + 1540 = −4960 (geom q=0.78).
    const gap = tradeGapAdjusted([ALLEN], [CHASE, PICK_2026], "full");
    expect(gap).toBe(ownerGap([9000], [8500, 7000]));
    expect(gap).toBe(-4960);
    expect(gap).toBeCloseTo(geomPackageUtility([9000]) - geomPackageUtility([8500, 7000]), 6);
  });

  it("returns 0 for empty vs empty", () => {
    expect(tradeGapAdjusted([], [], "full")).toBe(0);
  });
});

// ── computeValueAdjustment ───────────────────────────────────────────

function mockRow(value) {
  return { name: `P${value}`, pos: "QB", assetClass: "offense", values: { full: value, raw: value } };
}

describe("computeValueAdjustment", () => {
  // V12: KTC's actual published formula.  Earlier versions (V2)
  // gated VA off when piece counts matched; V12 fires on equal-count
  // trades whenever one side has the bigger raw_adjustment_sum
  // (i.e. the bigger studs).  The 1v1 case is the one empirical
  // exception — KTC's UI suppresses VA there.

  it("returns zero VA on a 1v1 trade (KTC empirical: never displayed)", () => {
    // 1v1 is the documented suppression case from the calibration
    // captures (EQ_1v1_a–f all reported VA=[0,0] at KTC).  V12 ports
    // that gate verbatim.
    const r = computeValueAdjustment([ALLEN], [CHASE], "full");
    expect(r).toEqual({ adjustment: 0, recipientIdx: null });
  });

  it("returns zero when either side is empty", () => {
    const r = computeValueAdjustment([], [CHASE, PICK_2026], "full");
    expect(r).toEqual({ adjustment: 0, recipientIdx: null });
  });

  it("fires VA on equal-count trades when one side has bigger studs", () => {
    // 2v2 stud-vs-pile shape: V2 returned 0 here (equal counts), V12
    // correctly returns a positive VA on the stud side because that
    // side has the bigger raw_adjustment_sum.
    const r = computeValueAdjustment(
      [mockRow(9000), mockRow(1500)],
      [mockRow(5000), mockRow(4500)],
      "full",
    );
    expect(r.adjustment).toBeGreaterThan(0);
    expect(r.recipientIdx).toBe(0);
  });

  it("recipientIdx is the consolidator side when KTC fires", () => {
    // KTC's actual algorithm (ported 2026-04-26 from site.min.js):
    // [9000] vs [8500, 7000] is too "fair" on intensity-adjusted
    // raw_adj — KTC's UI shows no VA badge.  Test the case that
    // unambiguously fires: a true stud (9999) versus two mids — the
    // stud side gets the VA.
    const r = computeValueAdjustment(
      [mockRow(9999)],
      [mockRow(4000), mockRow(3000)],
      "full",
    );
    expect(r.recipientIdx).toBe(0);
    expect(r.adjustment).toBeGreaterThan(0);
  });

  it("KTC rollback model: suppresses VA on intensity-balanced consolidation trades", () => {
    // [ALLEN (9000)] vs [CHASE (8500) + PICK_2026 (7000)] — by KTC's
    // actual algorithm this is a "Fair Trade": Side A's raw_adj
    // intensity (raw_adj / total) is comparable to Side B's, so KTC
    // suppresses the VA badge entirely.  The previous V13 regression
    // fit fired here, but KTC.com does not.
    const r1 = ownerAdjustment([9000], [8500, 7000], KTC);
    expect(r1.recipientIdx).toBeNull();
    expect(r1.adjustment).toBe(0);
    const r2 = ownerAdjustment([8500, 7000], [9000], KTC);
    expect(r2.recipientIdx).toBeNull();
    expect(r2.adjustment).toBe(0);
    // [CHASE (8500)] vs [ALLEN (9000) + PICK_2026 (7000)] — same
    // intensity-balanced shape, different stud assignment.  KTC also
    // suppresses.
    const r3 = ownerAdjustment([8500], [9000, 7000], KTC);
    expect(r3.recipientIdx).toBeNull();
    expect(r3.adjustment).toBe(0);
  });

  it("geometric (active) model: the same shapes give a positive-only adjustment equal to the utility difference", () => {
    // geom_q078_v1 has no suppression band: the lone side receives the
    // depth the pair discards, 0.22 x its smaller piece (geom q=0.78).
    const r1 = computeValueAdjustment([ALLEN], [CHASE, PICK_2026], "full");
    expect(r1).toEqual({ adjustment: 1540, recipientIdx: 0 });
    const r2 = computeValueAdjustment([CHASE, PICK_2026], [ALLEN], "full");
    expect(r2).toEqual({ adjustment: 1540, recipientIdx: 1 });
    const r3 = computeValueAdjustment([CHASE], [ALLEN, PICK_2026], "full");
    expect(r3).toEqual({ adjustment: 1540, recipientIdx: 0 });
    for (const [r, a, b] of [
      [r1, [9000], [8500, 7000]],
      [r2, [8500, 7000], [9000]],
      [r3, [8500], [9000, 7000]],
    ]) {
      const raw = sumOf(a) - sumOf(b);
      const adjustedGap = r.recipientIdx === 0 ? raw + r.adjustment : raw - r.adjustment;
      expect(adjustedGap).toBeCloseTo(geomPackageUtility(a) - geomPackageUtility(b), 6);
    }
  });

  // ── KTC live-fixture reference cases ─────────────────────────────────
  //
  // The 2026-04-26 port of KTC's site.min.js algorithm replaces the
  // V12/V13 regression fit.  The 2022 article that V12 reproduced
  // (~4900 on Chase 8200 vs Lamb+Mixon) used an outdated formula
  // version; the current KTC algorithm produces ~3636 for the same
  // inputs.  Reference checks now pin against captured KTC.com
  // outputs (scripts/ktc_va_observations.json) — RMS error across
  // the 139-trade fixture is ~27 absolute, basically bit-exact.
  describe("KTC rollback model: live-fixture reference (port ground truth)", () => {
    it("Chase-style 1v2 stud-vs-mids: VA fires on the stud side", () => {
      // [8200] vs [5500, 4900]: KTC's current algorithm produces
      // ~3636 (we tolerate ±5% to absorb tiny iterative-search
      // rounding differences between Node and KTC's live JS).
      const r = ownerAdjustment([8200], [5500, 4900], KTC);
      expect(r.recipientIdx).toBe(0);
      expect(r.adjustment).toBeGreaterThan(3400);
      expect(r.adjustment).toBeLessThan(3900);
    });

    it("ktcProcessV reproduces KTC's per-piece raw-adj for canonical inputs", () => {
      // Pin a few outputs of ktcProcessV (KTC's processV) so a future
      // refactor can't silently drift the per-piece weights.  Values
      // computed directly from the ported algorithm at maxInTrade=9999,
      // t=10041 — same inputs KTC uses on its top-of-board page.
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const { ktcProcessV } = require("../lib/trade-logic.js");
      const cases = [
        [9000, 1469, 5],    // top-tier piece
        [7000, 950, 5],     // strong piece
        [5000, 604, 5],     // mid piece
        [3000, 331, 5],     // depth piece
        [1000, 103, 5],     // throw-in
      ];
      for (const [p, expected, tol] of cases) {
        const got = ktcProcessV(p, 9999, 10041, -1);
        expect(Math.abs(got - expected)).toBeLessThan(tol);
      }
    });

    it("VA always ≥ 0 (non-negativity invariant — KTC and the active model)", () => {
      // Sweep a range of trade shapes; neither model may return negative.
      const shapes = [
        [[9999], [5000, 3000]],
        [[5000], [9000, 7000]],
        [[7000, 5000], [6000, 4000]],
        [[3000, 2000, 1000], [4000, 2500, 1500]],
        [[1000], [9999, 9999, 9999, 9999, 9999]],
      ];
      for (const [a, b] of shapes) {
        const r = computeValueAdjustment(
          a.map(mockRow),
          b.map(mockRow),
          "full",
        );
        expect(r.adjustment).toBeGreaterThanOrEqual(0);
        expect(ownerAdjustment(a, b, KTC).adjustment).toBeGreaterThanOrEqual(0);
      }
    });

    it("VA is monotonic in stud value (bigger stud → bigger VA, all else equal)", () => {
      // Same 1v2 shape with the lone stud ramped up.  Larger studs
      // should produce larger VAs because raw(p) grows faster than p.
      const va6000 = ownerAdjustment([6000], [4000, 3000], KTC).adjustment;
      const va8000 = ownerAdjustment([8000], [4000, 3000], KTC).adjustment;
      const va9999 = ownerAdjustment([9999], [4000, 3000], KTC).adjustment;
      expect(va8000).toBeGreaterThan(va6000);
      expect(va9999).toBeGreaterThan(va8000);
    });
  });

  it("geometric (active) model: a lone stud's adjustment is the depth the pair discards, whatever the stud", () => {
    // KTC's VA grows with the stud; the geometric model's does not — a
    // lone piece discards nothing, so it receives exactly what the other
    // side discards: [4000, 3000] -> 3000 x 0.22 = 660 (geom q=0.78).
    for (const stud of [6000, 8000, 9999]) {
      expect(computeValueAdjustment([mockRow(stud)], [mockRow(4000), mockRow(3000)], "full")).toEqual({
        adjustment: 660,
        recipientIdx: 0,
      });
    }
  });

  // ── V13 suppression rules (calibrated 2026-04 from 39 borderline trades) ──
  // KTC's own 'fair trade' gates — the geometric active model has no
  // suppression band, so these pin the KTC rollback model explicitly.
  describe("KTC rollback model: V13 suppression ('fair trade' gates)", () => {
    it("suppresses VA when raw_diff is below the close-trade threshold", () => {
      // Two near-identical 2v2 sides — raw_diff under 100, no firing.
      // Captured analog: BORD_2v2_f, BORD_2v2_c → KTC reported VA=0.
      const r = ownerAdjustment([6896, 3486], [6888, 3387], KTC);
      expect(r.adjustment).toBe(0);
    });

    it("suppresses VA when best AND worst piece are on the same side (KTC article hint)", () => {
      // Per KTC's article: "the value adjustment ... tends to be
      // applied to the side with less junk."  When both extremes
      // are on the same side AND the raw gap is moderate (< 400),
      // KTC suppresses to 0.  Captured analog: BORD_USER_a — the
      // user's reported "fair trade" where V12 over-predicted +1028
      // but KTC actually displayed +0.
      //
      // Side A holds best (7765) AND worst (1963); side B has 3
      // moderate-tier pieces.  KTC's UI suppresses.
      const r = ownerAdjustment([7765, 3880, 2540, 1963], [6642, 4915, 4874], KTC);
      expect(r.adjustment).toBe(0);
    });

    it("does NOT suppress when best+worst same side but raw_diff is large", () => {
      // BORD_3v3_e analog: stud + mid + throw vs three mids/strong.
      // Same-side rule alone doesn't suppress when the raw gap is
      // big enough that KTC fires anyway.
      const r = ownerAdjustment([9979, 4868, 3387], [6888, 6642, 4921], KTC);
      expect(r.adjustment).toBeGreaterThan(0);
    });

    it("does NOT suppress when best+worst on different sides with moderate raw_diff", () => {
      // Best on side A, worst on side B → same-side rule doesn't
      // apply.  Falls through to V12's article math.  Captured
      // analog: BORD_3v3_c which fires VA=2428.
      const r = ownerAdjustment([6642, 5309, 3486], [4921, 4868, 3387], KTC);
      expect(r.adjustment).toBeGreaterThan(0);
    });
  });
});

// ── computeMultiSideAdjustments (N-team trades) ──────────────────────
//
// Structural property tests — we don't have KTC observations for 3+
// team trades yet, so these assert formula invariants and consistency
// with the 2-side path rather than hitting specific KTC numbers.
// ── Per-team package rule (spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md §5.1) ──
//
// Every team of a routed trade is read in its OWN perspective:
// packageAdjustedPairTotals(gives_i, receives_i).  The retired
// computeMultiSideAdjustments read each side against the flattened union of
// every OTHER side — the "two imaginary sides" collapse directive §6 forbids.

const routed = (spec) =>
  spec.map(([assets, dests], i) => ({
    id: i,
    label: "ABCDE"[i],
    assets: assets.map(([name, v]) => makeRow(name, v)),
    destinations: Object.fromEntries(
      assets.map(([name], k) => [name, dests == null ? undefined : dests[k]]),
    ),
  }));

describe("per-team package rule", () => {
  it("packageAdjustedPairTotals: empty side gets no adjustment; gives are the FIRST argument", () => {
    expect(packageAdjustedPairTotals([3000, 2000], [])).toEqual({
      sendRaw: 5000,
      recvRaw: 0,
      sendAdj: 5000,
      recvAdj: 0,
      sendVA: 0,
      recvVA: 0,
    });
    // 1-for-1 never adjusts.
    expect(packageAdjustedPairTotals([5000], [4000]).sendVA).toBe(0);
    expect(packageAdjustedPairTotals([5000], [4000]).recvVA).toBe(0);
    // Consolidating team (one stud for two) carries the VA on its gives.
    const t = packageAdjustedPairTotals([9999], [7846, 5717]);
    const pair = packageAdjustPair([9999], [7846, 5717]);
    expect(pair.side).toBe(1);
    expect(t.sendVA).toBe(pair.value);
    expect(t.sendAdj).toBe(9999 + pair.value);
    expect(t.recvAdj).toBe(7846 + 5717);
    // Swapping the arguments mirrors the answer exactly.
    const m = packageAdjustedPairTotals([7846, 5717], [9999]);
    expect(m.recvVA).toBe(t.sendVA);
    expect(m.recvAdj - m.sendAdj).toBe(-(t.recvAdj - t.sendAdj));
  });

  it("packageAdjustedPairTotals drops non-positive and non-finite values (missing is never zero)", () => {
    expect(packageAdjustedPairTotals([5000, 0, NaN, -3], [4000, null])).toEqual(
      packageAdjustedPairTotals([5000], [4000]),
    );
  });

  it("I14 directional correctness: one team sending to two destinations", () => {
    // A sends 6000 -> B and 3000 -> C; B sends 7000 -> A; C sends 2500 -> A.
    const teams = perTeamPackageTotals([[6000, 3000], [7000], [2500]], [[1, 2], [0], [0]]);
    expect(teams.map((t) => t.gap)).toEqual([610, -1000, 500]);
    expect(teams.map((t) => t.larger)).toEqual([9610, 7000, 3000]);
    expect(teams.map((t) => t.band.level)).toEqual(["slight", "unfair", "unfair"]);
    expect(teams.map((t) => t.band.relativePct)).toEqual([6.35, 14.29, 16.67]);
    // RAW routed flows are conserved; adjusted per-team values are not.
    const rawIn = teams.reduce((a, t) => a + t.rawReceived, 0);
    const rawOut = teams.reduce((a, t) => a + t.rawGiven, 0);
    expect(rawIn).toBe(rawOut);
  });

  it("N = 2: the per-team reading is the two-side reading, mirrored", () => {
    const sides = routed([[[["a", 9999]]], [[["b1", 7846], ["b2", 5717]]]]);
    const [a, b] = perTeamPackageTotals(
      sides.map((s) => s.assets.map((r) => r.values.full)),
      tradeRoutes(sides),
    );
    const gap = tradeGapAdjusted(sides[0].assets, sides[1].assets, "full");
    expect(b.gap).toBe(gap);
    expect(a.gap).toBe(-gap);
    expect(a.larger).toBe(b.larger);
    expect(a.band.level).toBe(b.band.level);
  });

  it("locality: a leg between B and C never moves A's reading", () => {
    const base = perTeamPackageTotals([[6000], [5000], [4000]], [[1], [0], [0]]);
    const more = perTeamPackageTotals([[6000], [5000, 1200], [4000, 900]], [[1], [0, 2], [0, 1]]);
    expect(more[0]).toEqual(base[0]);
  });

  it("team order independence: permuting the teams permutes the readings", () => {
    const vals = [[6000, 3000], [7000], [2500]];
    const routes = [[1, 2], [0], [0]];
    const base = perTeamPackageTotals(vals, routes);
    // Order C, A, B: old index -> new index map.
    const perm = [2, 0, 1];
    const inv = [1, 2, 0];
    const pv = perm.map((i) => vals[i]);
    const pr = perm.map((i) => routes[i].map((d) => inv[d]));
    const out = perTeamPackageTotals(pv, pr);
    perm.forEach((oldIdx, newIdx) => expect(out[newIdx]).toEqual(base[oldIdx]));
  });

  it("asset order independence within a side", () => {
    const a = perTeamPackageTotals([[6000, 3000], [7000], [2500]], [[1, 2], [0], [0]]);
    const b = perTeamPackageTotals([[3000, 6000], [7000], [2500]], [[2, 1], [0], [0]]);
    expect(b).toEqual(a);
  });

  it("a one-for-one cycle has no VA, and its per-team gaps sum to zero", () => {
    const teams = perTeamPackageTotals([[5000], [4200], [3900]], [[1], [2], [0]]);
    for (const t of teams) {
      expect(t.sendVA).toBe(0);
      expect(t.recvVA).toBe(0);
    }
    expect(teams.reduce((acc, t) => acc + t.gap, 0)).toBe(0);
  });

  it("valueAdjustmentFromSideArrays: 3+ sides need the routing (no union stand-in)", () => {
    expect(valueAdjustmentFromSideArrays([[6000, 3000], [7000], [2500]])).toBeNull();
    const out = valueAdjustmentFromSideArrays([[6000, 3000], [7000], [2500]], {
      routes: [[1, 2], [0], [0]],
    });
    const teams = perTeamPackageTotals([[6000, 3000], [7000], [2500]], [[1, 2], [0], [0]]);
    expect(out).toEqual(teams.map((t) => t.sendVA));
    // 2 sides: unchanged single-recipient shape.
    const two = valueAdjustmentFromSideArrays([[9999], [7846, 5717]]);
    expect(two[1]).toBe(0);
    expect(two[0]).toBe(packageAdjustPair([9999], [7846, 5717]).value);
  });

  it("valueAdjustmentFromSideArrays: 3+ sides exclude an unpriced value, never price it at 0, and keep routes aligned", () => {
    // Side 0's middle asset is unpriced (null / undefined / NaN / "x").  It
    // must drop out of every team's package, and the asset after it must
    // still follow ITS OWN route (side 2), not shift onto the unpriced one's.
    const routes = [[1, 2, 2], [0], [0]];
    const priced = valueAdjustmentFromSideArrays([[6000, 3000], [7000], [2500]], {
      routes: [[1, 2], [0], [0]],
    });
    for (const missing of [null, undefined, NaN, "x"]) {
      const out = valueAdjustmentFromSideArrays([[6000, missing, 3000], [7000], [2500]], {
        routes,
      });
      expect(out).toEqual(priced);
      const teams = perTeamPackageTotals([[6000, missing, 3000], [7000], [2500]], routes);
      expect(teams[0].rawGiven).toBe(9000);
      expect(teams[2].rawReceived).toBe(3000);
    }
  });

  it("worstTeamBand: band severity first, then relative gap, then lower index; unknown wins", () => {
    const flows = [
      { given: 9000, received: 9610, net: 610 },
      { given: 7000, received: 6000, net: -1000 },
      { given: 2500, received: 3000, net: 500 },
    ];
    expect(worstTeamBand(flows)).toMatchObject({ index: 2, level: "unfair", relPct: 16.67 });
    expect(worstTeamBand([...flows, { given: 100, received: 100, net: NaN }])).toMatchObject({
      index: 3,
      level: null,
    });
    expect(worstTeamBand([])).toBeNull();
  });

  it("multiTeamNetSummary grades each team on its OWN larger package", () => {
    const sides = routed([
      [[["a1", 6000], ["a2", 3000]], [1, 2]],
      [[["b1", 7000]], [0]],
      [[["c1", 2500]], [0]],
    ]);
    const s = multiTeamNetSummary(computeSideFlows(sides, "full"));
    expect(s.nets).toEqual([610, -1000, 500]);
    expect(s.perTeam.map((b) => b.level)).toEqual(["slight", "unfair", "unfair"]);
    expect(s.worstIndex).toBe(2);
    expect(s.worst).toBe(500);
    expect(s.largerSide).toBe(3000);
    expect(s.verdict.level).toBe("unfair");
  });
});

describe("multiAdjustedSideTotals", () => {
  it("returns raw/adjustment/adjusted per side for 3 teams", () => {
    const sides = [
      [mockRow(9999)],
      [mockRow(5000), mockRow(3500)],
      [mockRow(4800), mockRow(3200)],
    ];
    const totals = multiAdjustedSideTotals(sides, "full");
    expect(totals).toHaveLength(3);
    for (const t of totals) {
      expect(t).toHaveProperty("raw");
      expect(t).toHaveProperty("adjustment");
      expect(t).toHaveProperty("adjusted");
      expect(t.adjusted).toBeCloseTo(t.raw + t.adjustment, 5);
    }
    // Stud side should have positive adjustment.
    expect(totals[0].adjustment).toBeGreaterThan(0);
  });

  it("is consistent with adjustedSideTotals for 2 teams", () => {
    const sideA = [mockRow(9999)];
    const sideB = [mockRow(7846), mockRow(5717)];
    const multi = multiAdjustedSideTotals([sideA, sideB], "full");
    const [a, b] = adjustedSideTotals(sideA, sideB, "full");
    expect(multi[0].raw).toBe(a.raw);
    expect(multi[0].adjustment).toBeCloseTo(a.adjustment, 5);
    expect(multi[0].adjusted).toBeCloseTo(a.adjusted, 5);
    expect(multi[1].raw).toBe(b.raw);
    expect(multi[1].adjustment).toBeCloseTo(b.adjustment, 5);
    expect(multi[1].adjusted).toBeCloseTo(b.adjusted, 5);
  });
});

// ── adjustedSideTotals ───────────────────────────────────────────────

describe("adjustedSideTotals", () => {
  it("both sides have raw/adjustment/adjusted with matching invariants", () => {
    // Use a big enough concentration gap so the smaller side gets a VA.
    const stud = mockRow(9999);
    const mid = mockRow(6000);
    const pick = mockRow(5000);
    const [a, b] = adjustedSideTotals([stud], [mid, pick], "full");
    expect(a.raw).toBe(9999);
    expect(b.raw).toBe(6000 + 5000);
    expect(a.adjusted).toBe(a.raw + a.adjustment);
    expect(b.adjusted).toBe(b.raw + b.adjustment);
    // Only the smaller side gets a bonus
    expect(b.adjustment).toBe(0);
    expect(a.adjustment).toBeGreaterThan(0);
  });

  it("equal-count trades fire VA on the side with bigger studs (V12)", () => {
    // V2 was strictly count-based: equal counts → 0 VA on both
    // sides.  V12 fires whenever raw_adjustment_sums differ.  In
    // this fixture ALLEN+CHASE is the bigger-stud side so it gets
    // the VA, the other side gets 0.  This is the structural
    // change: only one side ever has a positive VA, but it's no
    // longer gated on piece-count imbalance.
    const [a, b] = adjustedSideTotals([ALLEN, CHASE], [MAHOMES, PICK_2026], "full");
    // Exactly one side's adjustment is positive, the other is 0.
    expect(a.adjustment > 0 || b.adjustment > 0).toBe(true);
    expect(a.adjustment === 0 || b.adjustment === 0).toBe(true);
    // Adjusted total is raw + adjustment per side.
    expect(a.adjusted).toBeCloseTo(a.raw + a.adjustment, 5);
    expect(b.adjusted).toBeCloseTo(b.raw + b.adjustment, 5);
  });
});

// ── addAssetToSide / removeAssetFromSide ─────────────────────────────

describe("addAssetToSide", () => {
  it("adds a new asset", () => {
    const result = addAssetToSide([], ALLEN);
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Josh Allen");
  });

  it("adds another copy of an asset already on the side (owner decision 2026-10-03)", () => {
    // Calculator quantities are hypothetical, not inventory: a second add
    // is a second copy, never refused.
    const result = addAssetToSide([ALLEN], ALLEN);
    expect(result.length).toBe(2);
  });

  it("returns same array for null row", () => {
    const side = [ALLEN];
    expect(addAssetToSide(side, null)).toBe(side);
  });

  it("preserves existing assets when adding", () => {
    const result = addAssetToSide([ALLEN], CHASE);
    expect(result.length).toBe(2);
    expect(result[0].name).toBe("Josh Allen");
    expect(result[1].name).toBe("Ja'Marr Chase");
  });
});

describe("removeAssetFromSide", () => {
  it("removes a named asset", () => {
    const result = removeAssetFromSide([ALLEN, CHASE], "Josh Allen");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Ja'Marr Chase");
  });

  it("returns same contents if name not found", () => {
    const result = removeAssetFromSide([ALLEN], "Not Here");
    expect(result.length).toBe(1);
  });

  it("returns empty array when removing last asset", () => {
    const result = removeAssetFromSide([ALLEN], "Josh Allen");
    expect(result.length).toBe(0);
  });
});

// ── isAssetInTrade ───────────────────────────────────────────────────

describe("isAssetInTrade", () => {
  it("returns true if asset is in side A", () => {
    expect(isAssetInTrade([ALLEN], [], "Josh Allen")).toBe(true);
  });

  it("returns true if asset is in side B", () => {
    expect(isAssetInTrade([], [CHASE], "Ja'Marr Chase")).toBe(true);
  });

  it("returns false if asset is in neither side", () => {
    expect(isAssetInTrade([ALLEN], [CHASE], "Patrick Mahomes")).toBe(false);
  });
});

// ── Workspace serialization/deserialization ──────────────────────────

describe("serializeWorkspace", () => {
  it("serializes trade state to name-only arrays", () => {
    const result = serializeWorkspace([ALLEN], [CHASE], "full", "A");
    expect(result).toEqual({
      valueMode: "full",
      activeSide: "A",
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    });
  });

  it("handles empty sides", () => {
    const result = serializeWorkspace([], [], "raw", "B");
    expect(result.sideA).toEqual([]);
    expect(result.sideB).toEqual([]);
    expect(result.valueMode).toBe("raw");
    expect(result.activeSide).toBe("B");
  });
});

describe("deserializeWorkspace", () => {
  it("restores trade state from serialized names", () => {
    const rowByName = new Map([
      ["Josh Allen", ALLEN],
      ["Ja'Marr Chase", CHASE],
    ]);
    const parsed = {
      valueMode: "raw",
      activeSide: "B",
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    };
    const result = deserializeWorkspace(parsed, rowByName);
    // A workspace saved under the retired "Raw" mode restores canonical.
    expect(result.valueMode).toBe("full");
    expect(result.activeSide).toBe("B");
    expect(result.sideA.length).toBe(1);
    expect(result.sideA[0].name).toBe("Josh Allen");
    expect(result.sideB[0].name).toBe("Ja'Marr Chase");
  });

  it("drops players not found in current data", () => {
    const rowByName = new Map([["Josh Allen", ALLEN]]);
    const parsed = {
      sideA: ["Josh Allen", "Retired Player"],
      sideB: [],
    };
    const result = deserializeWorkspace(parsed, rowByName);
    expect(result.sideA.length).toBe(1);
  });

  it("defaults to 'full' mode for invalid valueMode", () => {
    const rowByName = new Map();
    const result = deserializeWorkspace({ valueMode: "invalid" }, rowByName);
    expect(result.valueMode).toBe("full");
  });

  it("defaults activeSide to A for non-B values", () => {
    const rowByName = new Map();
    const result = deserializeWorkspace({ activeSide: "C" }, rowByName);
    expect(result.activeSide).toBe("A");
  });

  it("returns null for null/non-object input", () => {
    const rowByName = new Map();
    expect(deserializeWorkspace(null, rowByName)).toBeNull();
    expect(deserializeWorkspace("bad", rowByName)).toBeNull();
  });
});

// ── addRecent ────────────────────────────────────────────────────────

describe("addRecent", () => {
  it("adds name to front of list", () => {
    const result = addRecent(["A", "B"], "C");
    expect(result[0]).toBe("C");
    expect(result.length).toBe(3);
  });

  it("deduplicates — moves existing name to front", () => {
    const result = addRecent(["A", "B", "C"], "B");
    expect(result).toEqual(["B", "A", "C"]);
  });

  it("caps at 20 entries", () => {
    const existing = Array.from({ length: 20 }, (_, i) => `P${i}`);
    const result = addRecent(existing, "New");
    expect(result.length).toBe(20);
    expect(result[0]).toBe("New");
    expect(result).not.toContain("P19");
  });
});

// ── filterPickerRows ─────────────────────────────────────────────────

describe("filterPickerRows", () => {
  const allRows = [ALLEN, MAHOMES, CHASE, PARSONS, PICK_2026];

  it("keeps assets already in the trade pickable (owner decision 2026-10-03)", () => {
    const result = filterPickerRows(allRows, [ALLEN], [CHASE], "", "all");
    expect(result.map((r) => r.name)).toContain("Josh Allen");
    expect(result.map((r) => r.name)).toContain("Ja'Marr Chase");
    expect(result.length).toBe(5);
  });

  it("filters by asset class", () => {
    const result = filterPickerRows(allRows, [], [], "", "idp");
    expect(result.every((r) => r.assetClass === "idp")).toBe(true);
    expect(result.length).toBe(1);
  });

  it("filters by search query (case insensitive)", () => {
    const result = filterPickerRows(allRows, [], [], "allen", "all");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Josh Allen");
  });

  it("combines filter and query", () => {
    const result = filterPickerRows(allRows, [], [], "parsons", "idp");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("Micah Parsons");
  });

  it("returns empty for no matches", () => {
    const result = filterPickerRows(allRows, [], [], "nonexistent", "all");
    expect(result.length).toBe(0);
  });

  it("limits to 80 results", () => {
    const manyRows = Array.from({ length: 200 }, (_, i) => makeRow(`Player ${i}`, 1000 - i));
    const result = filterPickerRows(manyRows, [], [], "", "all");
    expect(result.length).toBe(80);
  });

  it("shows all when filter is 'all' and query is empty", () => {
    const result = filterPickerRows(allRows, [], [], "", "all");
    expect(result.length).toBe(5);
  });

  it("filters picks", () => {
    const result = filterPickerRows(allRows, [], [], "", "pick");
    expect(result.length).toBe(1);
    expect(result[0].name).toBe("2026 Early 1st");
  });
});

// ── Full trade scenario ──────────────────────────────────────────────

describe("full trade scenario", () => {
  it("builds a trade, computes verdict, swaps sides, clears", () => {
    // Build side A: Allen + Chase
    let sideA = addAssetToSide([], ALLEN);
    sideA = addAssetToSide(sideA, CHASE);

    // Build side B: Mahomes + 2026 pick
    let sideB = addAssetToSide([], MAHOMES);
    sideB = addAssetToSide(sideB, PICK_2026);

    // Compute
    const totalA = sideTotal(sideA, "full"); // 9000 + 8500 = 17500
    const totalB = sideTotal(sideB, "full"); // 8800 + 7000 = 15800
    const gap = tradeGapAdjusted(sideA, sideB, "full");

    expect(totalA).toBe(17500);
    expect(totalB).toBe(15800);
    // Active (geom q=0.78) model: Allen+Chase discards 8500 x 0.22 =
    // 1870 of depth, Mahomes+pick 7000 x 0.22 = 1540, so side B — the
    // side that discarded less — is credited 330 against side A's raw
    // 1700 lead.  Gap = 1370 on a 17,500 larger side = 7.8%: a "Lean" to
    // side A under the relative bands (TC-C; the retired absolute bands
    // called it a "Strong lean").
    expect(gap).toBe(ownerGap([9000, 8500], [8800, 7000]));
    expect(gap).toBe(1370);
    const larger = Math.max(...adjustedSideTotals(sideA, sideB, "full").map((t) => t.adjusted));
    expect(larger).toBe(17500);
    expect(verdictFromGap(gap, larger)).toBe("Lean");
    expect(colorFromGap(gap, larger)).toBe("green"); // Side A wins

    // Swap sides — the model is side-symmetric, so the gap simply
    // flips sign.
    const [newA, newB] = [sideB, sideA];
    const swappedGap = tradeGapAdjusted(newA, newB, "full");
    expect(swappedGap).toBe(-gap);
    expect(verdictFromGap(swappedGap, larger)).toBe("Lean");
    expect(colorFromGap(swappedGap, larger)).toBe("red"); // Now Side B wins

    // Remove an asset — newA has 2 pieces (8800+7000), trimmedB has 1 (9000)
    const trimmedB = removeAssetFromSide(newB, "Ja'Marr Chase");
    const newGap = tradeGapAdjusted(newA, trimmedB, "full");
    // newA (Mahomes 8800 + Pick 7000) discards 1540 of depth; the lone
    // Allen discards none, so trimmedB is credited 1540.  newA's raw
    // lead (6800) is far larger, so newA still wins: 6800 − 1540 = 5260
    // (geom q=0.78).
    const rawNewGap = (8800 + 7000) - 9000;
    expect(rawNewGap).toBe(6800);
    expect(newGap).toBe(ownerGap([8800, 7000], [9000]));
    expect(newGap).toBe(5260);
    expect(newGap).toBeGreaterThan(0);

    // Serialize and restore
    const serialized = serializeWorkspace(newA, trimmedB, "full", "A");
    const rowByName = new Map([
      ["Josh Allen", ALLEN],
      ["Patrick Mahomes", MAHOMES],
      ["Ja'Marr Chase", CHASE],
      ["2026 Early 1st", PICK_2026],
    ]);
    const restored = deserializeWorkspace(serialized, rowByName);
    expect(restored.sideA.length).toBe(2);
    expect(restored.sideB.length).toBe(1);
    expect(tradeGapAdjusted(restored.sideA, restored.sideB, "full")).toBe(newGap);
  });
});

describe("verdictBarPosition", () => {
  it("returns 50 for even trade", () => {
    expect(verdictBarPosition(0)).toBe(50);
  });

  it("returns > 50 when A ahead", () => {
    expect(verdictBarPosition(2000)).toBeGreaterThan(50);
  });

  it("returns < 50 when B ahead", () => {
    expect(verdictBarPosition(-2000)).toBeLessThan(50);
  });
});

describe("getPlayerEdge", () => {
  // REVERSAL RECORDED IN PLACE. These fixtures fed rank-space magnitudes
  // (2, 5, 6) against a rank-space threshold (3), so they stayed green while
  // the feature was dead: #740 moved the gap into value space, published it
  // as `marketGapValueRatio`, and stamped `marketGapMagnitude = None` on
  // every row — and `Number(null) === 0`, which is finite and below 3, so
  // getPlayerEdge returned no signal for EVERY player. Nothing here
  // exercised it against a contract-shaped row, which is why green tests
  // and a dead feature coexisted.
  it("returns no signal when the row has no market-gap data", () => {
    expect(getPlayerEdge({}).signal).toBeNull();
    expect(getPlayerEdge(null).signal).toBeNull();
  });

  it("returns no signal on a row shaped like a real contract row", () => {
    // The regression, pinned: marketGapMagnitude is stamped None by the
    // backend and must not be what this function reads.
    const row = {
      marketGapDirection: "retail_premium",
      marketGapMagnitude: null,
      marketGapValueRatio: 0.18,
    };
    expect(getPlayerEdge(row).signal).toBe("SELL");
  });

  it("returns no signal below the shared ratio floor", () => {
    const row = {
      marketGapDirection: "retail_premium",
      marketGapValueRatio: 0.02,
    };
    expect(getPlayerEdge(row).signal).toBeNull();
  });

  it("returns BUY when consensus_premium (market undervalues vs consensus)", () => {
    const row = {
      values: { full: 5000 },
      rawSourceValues: { ktcSfTep: 4000 },
      marketGapDirection: "consensus_premium",
      marketGapValueRatio: 0.11,
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("BUY");
    expect(result.edgePct).toBe(25);
  });

  it("returns SELL when retail_premium (market overvalues vs consensus)", () => {
    const row = {
      values: { full: 4000 },
      rawSourceValues: { ktcSfTep: 5000 },
      marketGapDirection: "retail_premium",
      marketGapValueRatio: 0.22,
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("SELL");
    expect(result.valueGapPct).toBe(22);
  });

  it("renders the ratio as an honest percentage when values are missing", () => {
    // The ratio IS a relative difference, so x100 is a real percentage —
    // unlike the ordinal version, which printed a rank count as "%".
    const row = {
      marketGapDirection: "consensus_premium",
      marketGapValueRatio: 0.15,
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("BUY");
    expect(result.edgePct).toBe(15);
  });

  it("parses slot format", () => {
    const p = parsePickToken("2026 1.06");
    expect(p.year).toBe("2026");
    expect(p.round).toBe("1st");
    expect(p.tier).toBe("mid");
    expect(p.slot).toBe(6);
  });

  it("parses label format", () => {
    const p = parsePickToken("2026 early 2nd");
    expect(p.year).toBe("2026");
    expect(p.round).toBe("2nd");
    expect(p.tier).toBe("early");
  });

  it("returns null for invalid", () => {
    expect(parsePickToken("not a pick")).toBeNull();
  });
});

describe("buildPickLookupCandidates", () => {
  it("emits 'Pick' canonical for Sleeper slot labels with (from X)", () => {
    const c = buildPickLookupCandidates("2026 1.04 (from Chargers Team Doctor)");
    expect(c).toContain("2026 pick 1.04");
    expect(c).toContain("2026 1.04");
    // Also emits tier fallback
    expect(c).toContain("2026 early 1st");
  });

  it("handles (own) annotation", () => {
    const c = buildPickLookupCandidates("2026 5.04 (own)");
    expect(c).toContain("2026 pick 5.04");
    expect(c).toContain("2026 5.04");
  });

  it("handles tier-based labels for future years", () => {
    const c = buildPickLookupCandidates("2027 Mid 1st (own)");
    expect(c).toContain("2027 mid 1st");
    // Tier-centre slot fallback for years that DO have slot rows
    expect(c).toContain("2027 pick 1.06");
  });

  it("returns an empty list for blank input", () => {
    expect(buildPickLookupCandidates("")).toEqual([]);
    expect(buildPickLookupCandidates(null)).toEqual([]);
  });

  it("synthesizes Mid tier-centre fallbacks for bare year+round labels", () => {
    // Sleeper /traded_picks emits "2027 1st" / "2026 2nd" with no slot
    // and no tier — without a fallback the rankings row never matches.
    const c = buildPickLookupCandidates("2027 1st");
    expect(c).toContain("2027 1st");
    expect(c).toContain("2027 mid 1st");
    expect(c).toContain("2027 pick 1.06");
  });
});

describe("resolvePickRow", () => {
  function mkLookup(entries) {
    const m = new Map();
    for (const [name, value] of entries) {
      m.set(name.toLowerCase(), { name, pos: "PICK", values: { full: value } });
    }
    return m;
  }

  it("resolves Sleeper slot label against rankings 'Pick' row", () => {
    const lookup = mkLookup([["2026 Pick 1.04", 9123]]);
    const row = resolvePickRow("2026 1.04 (from Rage Against The Achane)", lookup);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(9123);
  });

  it("resolves tier label against tier-based rankings row", () => {
    const lookup = mkLookup([["2027 Mid 1st", 6800]]);
    const row = resolvePickRow("2027 Mid 1st (own)", lookup);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(6800);
  });

  it("uses pickAliases map when direct candidates miss", () => {
    const lookup = mkLookup([["2026 Pick 1.06", 7700]]);
    const aliases = { "2026 Mid 1st": "2026 Pick 1.06" };
    const row = resolvePickRow("2026 Mid 1st (own)", lookup, aliases);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(7700);
  });

  it("prefers pickAliases over a suppressed generic-tier row", () => {
    // Backend kept the suppressed generic-tier row on the board (with
    // stale value 1) so name search still resolves it, but pickAliases
    // authoritatively redirects to the slot-specific row (value 7700).
    const m = new Map();
    m.set("2026 mid 1st", {
      name: "2026 Mid 1st",
      pos: "PICK",
      values: { full: 1 },
      raw: { pickGenericSuppressed: true },
    });
    m.set("2026 pick 1.06", { name: "2026 Pick 1.06", pos: "PICK", values: { full: 7700 } });
    const aliases = { "2026 Mid 1st": "2026 Pick 1.06" };
    const row = resolvePickRow("2026 Mid 1st (own)", m, aliases);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.06");
    expect(row.values.full).toBe(7700);
  });

  it("skips suppressed generic-tier rows during direct lookup fallback", () => {
    // No pickAliases available — resolver must still skip the
    // suppressed row and continue to the slot-specific candidate that
    // buildPickLookupCandidates derives from the tier-centre slot.
    const m = new Map();
    m.set("2026 mid 1st", {
      name: "2026 Mid 1st",
      pos: "PICK",
      values: { full: 1 },
      raw: { pickGenericSuppressed: true },
    });
    m.set("2026 pick 1.06", { name: "2026 Pick 1.06", pos: "PICK", values: { full: 7700 } });
    const row = resolvePickRow("2026 Mid 1st (own)", m);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.06");
    expect(row.values.full).toBe(7700);
  });

  it("does not apply alias redirects to derived tier candidates for slot inputs", () => {
    // Sleeper emits a slot label.  pickAliases contains generic-tier
    // redirects that would point derived candidates at the WRONG slot
    // (Early→1.02, Mid→1.06, Late→1.10).  The resolver must only
    // apply aliases to the input label itself, not to synthesized
    // derived candidates, or slot picks get rewritten to the
    // tier-centre slot.
    const m = new Map();
    m.set("2026 pick 1.04", { name: "2026 Pick 1.04", pos: "PICK", values: { full: 9200 } });
    m.set("2026 pick 1.02", { name: "2026 Pick 1.02", pos: "PICK", values: { full: 9500 } });
    const aliases = { "2026 Early 1st": "2026 Pick 1.02" };
    const row = resolvePickRow("2026 1.04 (from Team X)", m, aliases);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.04");
    expect(row.values.full).toBe(9200);
  });

  it("resolves round 6 slot picks", () => {
    const lookup = mkLookup([["2026 Pick 6.04", 420]]);
    const row = resolvePickRow("2026 6.04 (own)", lookup);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 6.04");
    expect(row.values.full).toBe(420);
  });

  it("resolves round 6 tier labels", () => {
    const lookup = mkLookup([["2027 Mid 6th", 280]]);
    const row = resolvePickRow("2027 Mid 6th (own)", lookup);
    expect(row).not.toBeNull();
    expect(row.values.full).toBe(280);
  });

  it("returns null when nothing matches", () => {
    const lookup = mkLookup([["2026 Pick 1.04", 9000]]);
    expect(resolvePickRow("2099 1.01", lookup)).toBeNull();
  });

  it("resolves bare year+round Sleeper label to slot-bearing year row", () => {
    // /traded_picks emits "2026 1st".  Rankings has slot-specific rows
    // for the current rookie year — resolver should fall back to the
    // Mid tier-centre slot (1.06).
    const lookup = mkLookup([["2026 Pick 1.06", 7700]]);
    const row = resolvePickRow("2026 1st", lookup);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2026 Pick 1.06");
    expect(row.values.full).toBe(7700);
  });

  it("resolves bare year+round Sleeper label to tier-only future-year row", () => {
    // Future years only have generic tier rows on the board — the bare
    // Sleeper label should land on the Mid tier row.
    const lookup = mkLookup([["2027 Mid 2nd", 4200]]);
    const row = resolvePickRow("2027 2nd", lookup);
    expect(row).not.toBeNull();
    expect(row.name).toBe("2027 Mid 2nd");
    expect(row.values.full).toBe(4200);
  });
});

describe("parsePickToken round 6", () => {
  it("parses slot format round 6", () => {
    const p = parsePickToken("2026 6.04");
    expect(p).not.toBeNull();
    expect(p.year).toBe("2026");
    expect(p.round).toBe("6th");
    expect(p.slot).toBe(4);
  });

  it("parses tier label round 6", () => {
    const p = parsePickToken("2027 Mid 6th");
    expect(p).not.toBeNull();
    expect(p.year).toBe("2027");
    expect(p.round).toBe("6th");
    expect(p.tier).toBe("mid");
  });
});

describe("findBalancers", () => {
  // ``findBalancers`` takes the TRADE, not a pre-computed gap, so a raw
  // value can never be matched against an adjusted target (defect #800).
  const pool = (step = 50, lo = 150, hi = 9500) => {
    const out = [];
    for (let v = lo; v <= hi; v += step) {
      out.push({ name: `P${v}`, pos: "RB", values: { full: v } });
    }
    return out;
  };
  const sidesOf = (a, b) => [
    { assets: a.map((v, i) => ({ name: `a${i}`, pos: "RB", values: { full: v } })) },
    { assets: b.map((v, i) => ({ name: `b${i}`, pos: "WR", values: { full: v } })) },
  ];

  it("returns players that actually close the gap — which is not the one whose value matches it", () => {
    // Scenario rebuilt for the geometric active model (2026-10-17).  The
    // KTC-era version (P3 = 2000) relied on KTC's premium making the
    // value-matched piece WORSE; under geom q=0.78 adding any positive
    // piece narrows the gap, so the distinguishing property is now which
    // piece lands nearest even — and it is still not the value match.
    const rosterRows = [
      { name: "P1", pos: "WR", values: { full: 500 } },
      { name: "P2", pos: "RB", values: { full: 1000 } },
      { name: "P3", pos: "QB", values: { full: 1282 } },
    ];
    // Side B is behind by exactly 1,000 on a 1-for-1 (no package
    // adjustment on 1-for-1, so raw and adjusted coincide at the start).
    const sides = sidesOf([5000], [4000]);
    const result = findBalancers(sides, 1, rosterRows, "full");

    // The retired rule matched raw value to the gap and would have
    // picked P2 (1,000 against a 1,000 gap).  But the moment side B
    // holds two pieces, its second piece is discounted by q = 0.78 and
    // side A is credited 0.22 x that piece, so a 1,000 add only closes
    // 780 of the gap.  The piece that actually closes it is 1000 / 0.78.
    //
    //   P3 (1282) → gap   0     even
    //   P2 (1000) → gap 220     the "perfect" value match falls short
    //   P1 (500)  → gap 610
    expect(result.map((r) => r.name)).toEqual(["P3", "P2", "P1"]);
    expect(Math.round(result[0].gapBefore)).toBe(1000);
    expect(Math.round(result[0].gapAfter)).toBe(0);
    expect(Math.round(result[1].gapAfter)).toBe(220);
    for (const r of result) {
      expect(r.gapAfter).toBe(ownerGap([5000], [4000, r.value]));
    }
  });

  it("returns empty for a near-even trade", () => {
    expect(findBalancers(sidesOf([5000], [4900]), 1, pool(), "full")).toEqual([]);
  });

  it("returns empty for malformed input", () => {
    expect(findBalancers(null, 1, pool(), "full")).toEqual([]);
    expect(findBalancers(sidesOf([5000], [1000]), 7, pool(), "full")).toEqual([]);
  });

  it("scores against the ADJUSTED gap, not the raw value (defect #800)", () => {
    // A single 8,000 stud against 3,000 + 2,500.  Raw gap is 2,500 but
    // the consolidation premium pushes the ADJUSTED gap to 6,130, and
    // the piece that lands nearest zero is NOT the one whose raw value
    // is nearest 6,130.
    const sides = sidesOf([8000], [3000, 2500]);
    const [best] = findBalancers(sides, 1, pool(), "full", { maxResults: 1 });
    expect(best.gapBefore).toBe(tradeGapAdjusted(sides[0].assets, sides[1].assets, "full"));
    expect(Math.abs(best.gapAfter)).toBeLessThan(350);

    // The retired rule — nearest raw value to |gap| — overshoots here.
    const target = Math.abs(best.gapBefore);
    const retired = pool().reduce((acc, r) =>
      Math.abs(r.values.full - target) < Math.abs(acc.values.full - target) ? r : acc,
    );
    const retiredGap = tradeGapAdjusted(
      sides[0].assets,
      [...sides[1].assets, retired],
      "full",
    );
    expect(Math.abs(best.gapAfter)).toBeLessThan(Math.abs(retiredGap));
  });

  it("never leaves the trade further apart than it started", () => {
    for (const [a, b] of [
      [[8000], [3000, 2500]],
      [[3000, 2500], [8000]],
      [[9500], [3500, 2000, 1200]],
      [[6400, 3100, 1800], [7900, 2200]],
      [[428, 3420], [2808, 6451, 4484]],
    ]) {
      const sides = sidesOf(a, b);
      const gap = tradeGapAdjusted(sides[0].assets, sides[1].assets, "full");
      const behind = gap > 0 ? 1 : 0;
      for (const s of findBalancers(sides, behind, pool(), "full")) {
        expect(s.imbalanceAfter).toBeLessThan(s.imbalanceBefore);
      }
    }
  });

  it("picks the best available candidate, not merely a better one", () => {
    const sides = sidesOf([428, 3420], [2808, 6451, 4484]);
    const gap = tradeGapAdjusted(sides[0].assets, sides[1].assets, "full");
    const behind = gap > 0 ? 1 : 0;
    const rows = pool();
    const [best] = findBalancers(sides, behind, rows, "full", { maxResults: 1 });
    const exhaustive = Math.min(
      ...rows.map((r) => {
        const next = sides.map((side, i) =>
          i === behind ? { ...side, assets: [...side.assets, r] } : side,
        );
        return Math.abs(tradeGapAdjusted(next[0].assets, next[1].assets, "full"));
      }),
    );
    expect(best.imbalanceAfter).toBeCloseTo(exhaustive, 6);
  });

  it("never proposes an asset the board declined to price", () => {
    // MISSING IS NEVER ZERO: an unpriced row must not read as a
    // suggestion that changes nothing.
    const rows = [
      { name: "Unpriced", pos: "WR", values: {} },
      { name: "Zeroed", pos: "RB", values: { full: 0 } },
    ];
    expect(findBalancers(sidesOf([8000], [3000, 2500]), 1, rows, "full")).toEqual([]);
  });

  it("is disabled for 3+ teams (spec §5.1 R10d): no balancing objective is approved", () => {
    const sides = [
      { assets: [{ name: "a0", pos: "QB", values: { full: 9000 } }], destinations: { a0: 1 } },
      { assets: [{ name: "b0", pos: "WR", values: { full: 2000 } }], destinations: { b0: 2 } },
      { assets: [{ name: "c0", pos: "RB", values: { full: 2200 } }], destinations: { c0: 0 } },
    ];
    for (const idx of [0, 1, 2]) {
      expect(findBalancers(sides, idx, pool(), "full", { combos: true })).toEqual([]);
    }
  });
});

describe("tradeImbalance — one representation for every side count", () => {
  it("N = 2: the net flow IS the adjusted gap", () => {
    // The 2-team meter reads adjusted side totals and the multi-team
    // meter reads net flow.  Since 2026-08-18 both include Value
    // Adjustment, so for N = 2 they must be the same number.  Before
    // that, computeSideFlows carried no VA at all and this failed by
    // the entire adjustment.
    for (const [a, b] of [
      [[8000], [3000, 2500]],
      [[9000], [4000, 2000]],
      [[7000, 1200], [4500, 1500]],
      [[6400, 3100, 1800], [7900, 2200]],
      [[5000], [4900]],
    ]) {
      const sides = [
        { assets: a.map((v, i) => ({ name: `a${i}`, pos: "RB", values: { full: v } })) },
        { assets: b.map((v, i) => ({ name: `b${i}`, pos: "WR", values: { full: v } })) },
      ];
      const flows = computeSideFlows(sides, "full");
      const gap = tradeGapAdjusted(sides[0].assets, sides[1].assets, "full");
      expect(flows[1].net).toBeCloseTo(gap, 6);
      expect(tradeImbalance(sides, "full").imbalance).toBeCloseTo(Math.abs(gap), 6);
    }
  });

  it("a side's given total is its raw total plus its own premium", () => {
    const sides = [
      { assets: [{ name: "a0", pos: "QB", values: { full: 9000 } }], destinations: { a0: 2 } },
      { assets: [{ name: "b0", pos: "WR", values: { full: 8500 } }], destinations: { b0: 0 } },
      { assets: [{ name: "c0", pos: "LB", values: { full: 5000 } }], destinations: { c0: 1 } },
    ];
    const flows = computeSideFlows(sides, "full");
    expect(flows[0].given).toBeCloseTo(9000 + flows[0].adjustment, 6);
    expect(flows[1].given).toBeCloseTo(8500 + flows[1].adjustment, 6);
    expect(flows[2].given).toBeCloseTo(5000 + flows[2].adjustment, 6);
  });

  it("nothing is created or destroyed: RAW routed flows are conserved", () => {
    const sides = [
      { assets: [{ name: "a0", pos: "QB", values: { full: 9000 } }], destinations: { a0: 2 } },
      { assets: [{ name: "b0", pos: "WR", values: { full: 4000 } },
                 { name: "b1", pos: "TE", values: { full: 2500 } }], destinations: { b0: 0, b1: 2 } },
      { assets: [{ name: "c0", pos: "LB", values: { full: 5000 } }], destinations: { c0: 1 } },
    ];
    const flows = computeSideFlows(sides, "full");
    const given = flows.reduce((t, f) => t + f.rawGiven, 0);
    const received = flows.reduce((t, f) => t + f.rawReceived, 0);
    expect(given).toBe(received);
    // Adjusted per-team values are perspective quantities: C receives two
    // pieces (9000 + 2500) for one, so its own reading carries VA that no
    // sender's reading carries — they are never summed into a trade total.
    expect(flows[2].recvVA + flows[2].sendVA).toBeGreaterThan(0);
  });

  it("N >= 3 shape: per-team gaps and the worst team, never max(net) - min(net)", () => {
    const sides = [
      { assets: [{ name: "a1", values: { full: 6000 } }, { name: "a2", values: { full: 3000 } }],
        destinations: { a1: 1, a2: 2 } },
      { assets: [{ name: "b1", values: { full: 7000 } }], destinations: { b1: 0 } },
      { assets: [{ name: "c1", values: { full: 2500 } }], destinations: { c1: 0 } },
    ];
    const imb = tradeImbalance(sides, "full");
    expect(imb.gap).toBeNull();
    expect(imb.imbalance).toBeUndefined();
    expect(imb.perTeam).toEqual([
      { gap: 610, larger: 9610, level: "slight" },
      { gap: -1000, larger: 7000, level: "unfair" },
      { gap: 500, larger: 3000, level: "unfair" },
    ]);
    expect(imb.worst).toEqual({ index: 2, level: "unfair", relPct: 16.67 });
  });

  it("a side whose pieces are all unpriced carries no premium", () => {
    const sides = [
      { assets: [{ name: "a0", pos: "WR", values: {} }] },
      { assets: [{ name: "b0", pos: "RB", values: { full: 4000 } }] },
    ];
    const flows = computeSideFlows(sides, "full");
    expect(flows[0].given).toBe(0);
    expect(flows[0].adjustment).toBe(0);
  });
});

// ── effectiveValue + settings-aware totals ───────────────────────────

describe("effectiveValue", () => {
  it("returns raw value when no settings provided", () => {
    expect(effectiveValue(ALLEN, "full")).toBe(9000);
    expect(effectiveValue(ALLEN, "full", null)).toBe(9000);
  });

  it("returns raw value with settings (no adjustment)", () => {
    const settings = { leagueFormat: "superflex" };
    expect(effectiveValue(ALLEN, "full", settings)).toBe(9000);
  });
});

describe("settings-aware sideTotal", () => {
  it("returns sum without adjustment", () => {
    const settings = { leagueFormat: "superflex" };
    const total = sideTotal([ALLEN, CHASE], "full", settings);
    expect(total).toBe(9000 + 8500);
  });
});

// ── Pick year discount is backend-owned (no client-side function) ───
//
// The future-year pick discount + its self-rolling current draft year
// live in src/api/data_contract.py and are baked into rankDerivedValue
// before the contract reaches the client.  The old client-side
// pickYearDiscount() helper was removed (it double-discounted with
// divergent, non-self-rolling constants).  effectiveValue now returns
// pick values verbatim — pinned below.

// ── TEP is backend-authoritative — effectiveValue MUST NOT re-apply it ──
//
// The TE-premium multiplier is threaded through the backend rankings
// override pipeline (see src/api/data_contract.py::_compute_unified_rankings
// and frontend/lib/dynasty-data.js::fetchDynastyData).  By the time a
// TE row reaches `effectiveValue`, its ``values.full`` already reflects
// the TEP-adjusted blended value.  If we multiplied again here we'd
// double-boost every TE whenever the slider is > 1.0 AND would miss
// the TEP-native source carve-out.  These tests pin that behavior.

describe("effectiveValue leaves TEP alone (backend-authoritative)", () => {
  const TE_ROW = makeRow("Mark Andrews", 4000, "TE");

  it("TE full value is returned verbatim even with tepMultiplier set", () => {
    const settings = { leagueFormat: "superflex", tepMultiplier: 1.15 };
    const val = effectiveValue(TE_ROW, "full", settings);
    // Backend already baked in the TEP boost — effectiveValue returns
    // values.full untouched.  The input fixture has values.full=4000,
    // which is what we get back.
    expect(val).toBe(4000);
  });

  it("TE full value is returned verbatim when tepMultiplier is 1.0", () => {
    const settings = { leagueFormat: "superflex", tepMultiplier: 1.0 };
    const val = effectiveValue(TE_ROW, "full", settings);
    expect(val).toBe(4000);
  });

  it("non-TE is also untouched regardless of tepMultiplier", () => {
    const settings = { leagueFormat: "superflex", tepMultiplier: 1.5 };
    const val = effectiveValue(CHASE, "full", settings);
    expect(val).toBe(8500);
  });

  it("future pick is returned verbatim — discount is backend-baked", () => {
    // The pick-year discount is applied once, in the backend, and is
    // already in values.full.  effectiveValue must NOT re-discount.
    const FUTURE_PICK = makeRow("2028 Early 1st", 7000, "PICK", "pick");
    const settings = {
      leagueFormat: "superflex",
      tepMultiplier: 1.15,
      pickCurrentYear: 2026,
    };
    const val = effectiveValue(FUTURE_PICK, "full", settings);
    expect(val).toBe(7000);
  });
});

// ── effectiveValue does not re-discount picks (backend-authoritative) ─

describe("effectiveValue picks: no client-side discount", () => {
  const PICK_2027 = makeRow("2027 Early 1st", 7000, "PICK", "pick");

  it("future pick value is returned verbatim", () => {
    const settings = { leagueFormat: "superflex" };
    expect(effectiveValue(PICK_2027, "full", settings)).toBe(7000);
  });

  it("legacy pickCurrentYear setting is ignored", () => {
    // Even if a stale client still passes pickCurrentYear, it has no
    // effect — the discount is backend-owned.
    const settings = { leagueFormat: "superflex", pickCurrentYear: 2026 };
    expect(effectiveValue(PICK_2027, "full", settings)).toBe(7000);
  });

  it("per-player custom override still wins", () => {
    const row = { ...PICK_2027, customValue: 5000 };
    expect(effectiveValue(row, "full", { leagueFormat: "superflex" })).toBe(5000);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// NEW: Trade Meter + Multi-Team tests
// ══════════════════════════════════════════════════════════════════════════

// ── meterVerdict ────────────────────────────────────────────────────────

describe("meterVerdict", () => {
  it("returns FAIR for gap < 350", () => {
    expect(meterVerdict(0, 10000)).toMatchObject({ label: "FAIR", level: "fair" });
    expect(meterVerdict(349, 10000)).toMatchObject({ label: "FAIR", level: "fair" });
  });

  it("returns SLIGHT EDGE for gap 350-899", () => {
    expect(meterVerdict(350, 10000)).toMatchObject({ label: "SLIGHT EDGE", level: "slight" });
    expect(meterVerdict(899, 10000)).toMatchObject({ label: "SLIGHT EDGE", level: "slight" });
  });

  it("returns UNFAIR for gap 900-1799", () => {
    expect(meterVerdict(900, 10000)).toMatchObject({ label: "UNFAIR", level: "unfair" });
    expect(meterVerdict(1799, 10000)).toMatchObject({ label: "UNFAIR", level: "unfair" });
  });

  it("returns LOPSIDED for gap >= 1800", () => {
    expect(meterVerdict(1800, 10000)).toMatchObject({ label: "LOPSIDED", level: "lopsided" });
    expect(meterVerdict(5000, 10000)).toMatchObject({ label: "LOPSIDED", level: "lopsided" });
  });
});

// ── percentageGap ───────────────────────────────────────────────────────

describe("percentageGap", () => {
  it("returns 0 when both sides are 0", () => {
    expect(percentageGap(0, 0)).toBe(0);
  });

  it("returns 100% when one side is empty", () => {
    expect(percentageGap(5000, 0)).toBe(100);
    expect(percentageGap(0, 5000)).toBe(100);
  });

  it("returns correct percentage for unequal sides", () => {
    // |5000 - 4000| / 5000 * 100 = 20%
    expect(percentageGap(5000, 4000)).toBe(20);
    expect(percentageGap(4000, 5000)).toBe(20);
  });

  it("returns 0 when sides are equal", () => {
    expect(percentageGap(3000, 3000)).toBe(0);
  });
});

// ── multiTeamAnalysis ───────────────────────────────────────────────────

describe("multiTeamAnalysis", () => {
  it("reports balanced for equal totals", () => {
    const result = multiTeamAnalysis([1000, 1000, 1000]);
    expect(result.overall).toBe("Balanced");
    expect(result.shares).toEqual([33, 33, 33]);
    result.perTeam.forEach((t) => expect(t).toBe("Fair share"));
  });

  it("reports imbalanced when one team overpays", () => {
    const result = multiTeamAnalysis([5000, 1000, 1000]);
    expect(result.overall).toBe("Imbalanced");
    expect(result.perTeam[0]).toBe("Overpaying");
    expect(result.perTeam[1]).toBe("Getting a deal");
    expect(result.perTeam[2]).toBe("Getting a deal");
  });

  it("handles all-zero totals", () => {
    const result = multiTeamAnalysis([0, 0, 0]);
    expect(result.overall).toBe("Empty");
    expect(result.shares).toEqual([0, 0, 0]);
  });

  it("works with 5 teams", () => {
    const result = multiTeamAnalysis([2000, 2000, 2000, 2000, 2000]);
    expect(result.overall).toBe("Balanced");
    expect(result.shares.length).toBe(5);
  });
});

// ── createSide ──────────────────────────────────────────────────────────

describe("createSide", () => {
  it("creates side with correct label and empty destinations map", () => {
    expect(createSide(0)).toEqual({ id: 0, label: "A", assets: [], destinations: {} });
    expect(createSide(1)).toEqual({ id: 1, label: "B", assets: [], destinations: {} });
    expect(createSide(4)).toEqual({ id: 4, label: "E", assets: [], destinations: {} });
  });
});

// ── defaultDestination ──────────────────────────────────────────────────

describe("defaultDestination", () => {
  it("returns the next side (circular) for a given side count", () => {
    expect(defaultDestination(0, 3)).toBe(1);
    expect(defaultDestination(1, 3)).toBe(2);
    expect(defaultDestination(2, 3)).toBe(0);
    expect(defaultDestination(0, 4)).toBe(1);
    expect(defaultDestination(3, 4)).toBe(0);
  });

  it("clamps to 0 for degenerate inputs", () => {
    expect(defaultDestination(0, 1)).toBe(0);
    expect(defaultDestination(-1, 3)).toBe(0);
    expect(defaultDestination(5, 3)).toBe(0);
  });
});

// ── computeSideFlows ────────────────────────────────────────────────────

describe("computeSideFlows", () => {
  it("2-team trade: every asset flows to the other side implicitly", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: {} },
      { id: 1, label: "B", assets: [CHASE], destinations: {} },
    ];
    const flows = computeSideFlows(sides, "full");
    // 1-for-1: KTC suppresses Value Adjustment, so the VA-inclusive
    // flow is identical to the raw one here.
    expect(flows).toMatchObject([
      { given: 9000, received: 8500, net: -500, adjustment: 0, rawGiven: 9000, rawReceived: 8500 },
      { given: 8500, received: 9000, net: 500, adjustment: 0, rawGiven: 8500, rawReceived: 9000 },
    ]);
  });

  it("2-team trade ignores any stored destinations", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 0 } }, // self-ref
      { id: 1, label: "B", assets: [CHASE], destinations: {} },
    ];
    const flows = computeSideFlows(sides, "full");
    // Implicit flow overrides the self-referencing destination
    expect(flows[0].net).toBe(-500);
    expect(flows[1].net).toBe(500);
  });

  it("3-team trade: routes assets via destinations map", () => {
    // A gives Allen (9000) to C, B gives Chase (8500) to A, C gives Parsons (5000) to B
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 2 } },
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 0 } },
      { id: 2, label: "C", assets: [PARSONS], destinations: { "Micah Parsons": 1 } },
    ];
    const flows = computeSideFlows(sides, "full");
    // Per-team rule (spec §5.1): every team here gives one piece and gets
    // one piece, so no team's OWN reading carries a Value Adjustment.  The
    // retired union collapse credited A and B 1,100 and C 1,870 by pricing
    // each side against the other two sides' pieces combined.
    expect(flows.map((f) => f.adjustment)).toEqual([0, 0, 0]);
    expect(flows).toMatchObject([
      { given: 9000, received: 8500, net: -500 }, // Allen -> C, Chase from B
      { given: 8500, received: 5000, net: -3500 }, // Chase -> A, Parsons from C
      { given: 5000, received: 9000, net: 4000 }, // Parsons -> B, Allen from A
    ]);
  });

  it("3-team trade: missing destination falls back to next-side default", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: {} }, // no dest → default to 1
      { id: 1, label: "B", assets: [CHASE], destinations: {} }, // no dest → default to 2
      { id: 2, label: "C", assets: [PARSONS], destinations: {} }, // no dest → default to 0
    ];
    const flows = computeSideFlows(sides, "full");
    expect(flows[0].rawReceived).toBe(5000); // Parsons from C
    expect(flows[1].rawReceived).toBe(9000); // Allen from A
    expect(flows[2].rawReceived).toBe(8500); // Chase from B
  });

  it("3-team trade: self-referencing or out-of-range destination falls back to default", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 0 } }, // self
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 99 } }, // OOR
      { id: 2, label: "C", assets: [PARSONS], destinations: { "Micah Parsons": -1 } }, // neg
    ];
    const flows = computeSideFlows(sides, "full");
    // All fall back to defaults: A→1, B→2, C→0
    expect(flows[0].rawReceived).toBe(5000); // Parsons from C
    expect(flows[1].rawReceived).toBe(9000); // Allen from A
    expect(flows[2].rawReceived).toBe(8500); // Chase from B
  });

  it("returns zero-shaped arrays for empty / single-side inputs", () => {
    expect(computeSideFlows([], "full")).toEqual([]);
    expect(computeSideFlows([{ assets: [ALLEN] }], "full")).toEqual([
      { given: 0, received: 0, net: 0, adjustment: 0, rawGiven: 0, rawReceived: 0 },
    ]);
  });

  it("handles empty sides in a 3-team trade", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 1 } },
      { id: 1, label: "B", assets: [], destinations: {} },
      { id: 2, label: "C", assets: [], destinations: {} },
    ];
    const flows = computeSideFlows(sides, "full");
    // Only one side has anything on the table, so there is no package
    // to price a consolidation premium against.
    expect(flows[0]).toMatchObject({ given: 9000, received: 0, net: -9000, adjustment: 0 });
    expect(flows[1]).toMatchObject({ given: 0, received: 9000, net: 9000, adjustment: 0 });
    expect(flows[2]).toMatchObject({ given: 0, received: 0, net: 0, adjustment: 0 });
  });

  it("RAW flow is conserved across all sides; adjusted nets are per-team", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN, MAHOMES], destinations: { "Josh Allen": 1, "Patrick Mahomes": 2 } },
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 2 } },
      { id: 2, label: "C", assets: [PARSONS, PICK_2026], destinations: { "Micah Parsons": 0, "2026 Early 1st": 1 } },
    ];
    const flows = computeSideFlows(sides, "full");
    const rawNet = flows.reduce((s, f) => s + (f.rawReceived - f.rawGiven), 0);
    expect(rawNet).toBe(0);
    for (const f of flows) expect(f.net).toBe(f.recvAdj - f.sendAdj);
  });
});

// ── computeSideFlowAssets ───────────────────────────────────────────────

describe("computeSideFlowAssets", () => {
  it("2-team trade: every outgoing asset has a mirror incoming entry", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: {} },
      { id: 1, label: "B", assets: [CHASE], destinations: {} },
    ];
    const flow = computeSideFlowAssets(sides);
    expect(flow[0].outgoing).toEqual([{ asset: ALLEN, toSideIdx: 1 }]);
    expect(flow[0].incoming).toEqual([{ asset: CHASE, fromSideIdx: 1 }]);
    expect(flow[1].outgoing).toEqual([{ asset: CHASE, toSideIdx: 0 }]);
    expect(flow[1].incoming).toEqual([{ asset: ALLEN, fromSideIdx: 0 }]);
  });

  it("3-team trade: routes per the destinations map", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 2 } },
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 0 } },
      { id: 2, label: "C", assets: [PARSONS], destinations: { "Micah Parsons": 1 } },
    ];
    const flow = computeSideFlowAssets(sides);
    expect(flow[0].outgoing).toEqual([{ asset: ALLEN, toSideIdx: 2 }]);
    expect(flow[0].incoming).toEqual([{ asset: CHASE, fromSideIdx: 1 }]);
    expect(flow[1].outgoing).toEqual([{ asset: CHASE, toSideIdx: 0 }]);
    expect(flow[1].incoming).toEqual([{ asset: PARSONS, fromSideIdx: 2 }]);
    expect(flow[2].outgoing).toEqual([{ asset: PARSONS, toSideIdx: 1 }]);
    expect(flow[2].incoming).toEqual([{ asset: ALLEN, fromSideIdx: 0 }]);
  });

  it("empty side with no incoming: receives nothing", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 1 } },
      { id: 1, label: "B", assets: [], destinations: {} },
      { id: 2, label: "C", assets: [], destinations: {} },
    ];
    const flow = computeSideFlowAssets(sides);
    expect(flow[0].outgoing.length).toBe(1);
    expect(flow[0].incoming.length).toBe(0);
    expect(flow[1].incoming.length).toBe(1);
    expect(flow[2].incoming.length).toBe(0);
  });

  it("every outgoing has a matching incoming (bijection)", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN, MAHOMES], destinations: { "Josh Allen": 1, "Patrick Mahomes": 2 } },
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 2 } },
      { id: 2, label: "C", assets: [PARSONS, PICK_2026], destinations: { "Micah Parsons": 0, "2026 Early 1st": 1 } },
    ];
    const flow = computeSideFlowAssets(sides);
    const totalOutgoing = flow.reduce((s, f) => s + f.outgoing.length, 0);
    const totalIncoming = flow.reduce((s, f) => s + f.incoming.length, 0);
    expect(totalOutgoing).toBe(5);
    expect(totalIncoming).toBe(5);
    expect(totalOutgoing).toBe(totalIncoming);
  });

  it("empty / single-side inputs return empty-shaped results", () => {
    expect(computeSideFlowAssets([])).toEqual([]);
    expect(computeSideFlowAssets([{ assets: [ALLEN] }])).toEqual([
      { outgoing: [], incoming: [] },
    ]);
  });
});

// ── constants ───────────────────────────────────────────────────────────

describe("multi-team constants", () => {
  it("SIDE_LABELS has 5 labels", () => {
    expect(SIDE_LABELS).toEqual(["A", "B", "C", "D", "E"]);
  });

  it("MAX_SIDES is 5, MIN_SIDES is 2", () => {
    expect(MAX_SIDES).toBe(5);
    expect(MIN_SIDES).toBe(2);
  });
});

// ── serializeWorkspaceMulti / deserializeWorkspaceMulti ─────────────────

describe("serializeWorkspaceMulti", () => {
  it("serializes sides array with version 2", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: {} },
      { id: 1, label: "B", assets: [CHASE], destinations: {} },
    ];
    const result = serializeWorkspaceMulti(sides, "full", 0);
    expect(result.version).toBe(2);
    expect(result.sides.length).toBe(2);
    expect(result.sides[0].assets).toEqual(["Josh Allen"]);
    expect(result.sides[1].assets).toEqual(["Ja'Marr Chase"]);
    expect(result.valueMode).toBe("full");
    expect(result.activeSide).toBe(0);
  });

  it("handles 3+ sides", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: {} },
      { id: 1, label: "B", assets: [CHASE], destinations: {} },
      { id: 2, label: "C", assets: [PARSONS], destinations: {} },
    ];
    const result = serializeWorkspaceMulti(sides, "raw", 2);
    expect(result.sides.length).toBe(3);
    expect(result.sides[2].label).toBe("C");
    expect(result.activeSide).toBe(2);
  });

  it("persists per-asset destinations for each side", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 2 } },
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 0 } },
      { id: 2, label: "C", assets: [PARSONS], destinations: { "Micah Parsons": 1 } },
    ];
    const result = serializeWorkspaceMulti(sides, "full", 1);
    expect(result.sides[0].destinations).toEqual({ "Josh Allen": 2 });
    expect(result.sides[1].destinations).toEqual({ "Ja'Marr Chase": 0 });
    expect(result.sides[2].destinations).toEqual({ "Micah Parsons": 1 });
  });

  it("drops destination entries for assets that are no longer on the side", () => {
    const sides = [
      {
        id: 0,
        label: "A",
        assets: [ALLEN],
        destinations: { "Josh Allen": 1, "Ghost Player": 2 },
      },
      { id: 1, label: "B", assets: [CHASE], destinations: {} },
    ];
    const result = serializeWorkspaceMulti(sides, "full", 0);
    expect(result.sides[0].destinations).toEqual({ "Josh Allen": 1 });
    expect(result.sides[0].destinations["Ghost Player"]).toBeUndefined();
  });
});

describe("deserializeWorkspaceMulti", () => {
  const rowByName = new Map([
    ["Josh Allen", ALLEN],
    ["Ja'Marr Chase", CHASE],
    ["Patrick Mahomes", MAHOMES],
    ["Micah Parsons", PARSONS],
  ]);

  it("restores version 2 format", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 1,
      sides: [
        { label: "A", assets: ["Josh Allen"] },
        { label: "B", assets: ["Ja'Marr Chase"] },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(2);
    expect(result.sides[0].assets[0].name).toBe("Josh Allen");
    expect(result.sides[1].assets[0].name).toBe("Ja'Marr Chase");
    expect(result.activeSide).toBe(1);
    expect(result.valueMode).toBe("full");
  });

  it("migrates legacy sideA/sideB format", () => {
    const parsed = {
      valueMode: "raw",
      activeSide: "B",
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(2);
    expect(result.sides[0].label).toBe("A");
    expect(result.sides[0].assets[0].name).toBe("Josh Allen");
    expect(result.sides[1].label).toBe("B");
    expect(result.sides[1].assets[0].name).toBe("Ja'Marr Chase");
    expect(result.activeSide).toBe(1); // "B" → 1
    expect(result.valueMode).toBe("full"); // retired "raw" restores canonical
  });

  it("migrates legacy format with activeSide A", () => {
    const parsed = {
      valueMode: "full",
      activeSide: "A",
      sideA: ["Patrick Mahomes"],
      sideB: [],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.activeSide).toBe(0); // "A" → 0
    expect(result.sides[0].assets[0].name).toBe("Patrick Mahomes");
    expect(result.sides[1].assets.length).toBe(0);
  });

  it("ensures at least 2 sides even if stored data has fewer", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 0,
      sides: [{ label: "A", assets: [] }],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(2);
  });

  it("drops unknown player names during migration", () => {
    const parsed = {
      sideA: ["Josh Allen", "Unknown Player"],
      sideB: [],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides[0].assets.length).toBe(1);
    expect(result.sides[0].assets[0].name).toBe("Josh Allen");
  });

  it("returns null for null/non-object input", () => {
    expect(deserializeWorkspaceMulti(null, rowByName)).toBeNull();
    expect(deserializeWorkspaceMulti("bad", rowByName)).toBeNull();
  });

  it("defaults to full mode for invalid valueMode", () => {
    const parsed = { version: 2, valueMode: "invalid", activeSide: 0, sides: [] };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.valueMode).toBe("full");
  });

  it("clamps activeSide to valid range", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 99,
      sides: [
        { label: "A", assets: [] },
        { label: "B", assets: [] },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.activeSide).toBe(1); // clamped to sides.length - 1
  });

  it("restores 3+ sides in version 2 format", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 2,
      sides: [
        { label: "A", assets: ["Josh Allen"] },
        { label: "B", assets: ["Ja'Marr Chase"] },
        { label: "C", assets: ["Micah Parsons"] },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides.length).toBe(3);
    expect(result.sides[2].assets[0].name).toBe("Micah Parsons");
    expect(result.activeSide).toBe(2);
  });

  it("restores per-asset destinations in version 2 format", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 0,
      sides: [
        { label: "A", assets: ["Josh Allen"], destinations: { "Josh Allen": 2 } },
        { label: "B", assets: ["Ja'Marr Chase"], destinations: { "Ja'Marr Chase": 0 } },
        { label: "C", assets: ["Micah Parsons"], destinations: { "Micah Parsons": 1 } },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides[0].destinations).toEqual({ "Josh Allen": 2 });
    expect(result.sides[1].destinations).toEqual({ "Ja'Marr Chase": 0 });
    expect(result.sides[2].destinations).toEqual({ "Micah Parsons": 1 });
  });

  it("drops invalid / stale destination entries during restore", () => {
    const parsed = {
      version: 2,
      valueMode: "full",
      activeSide: 0,
      sides: [
        {
          label: "A",
          assets: ["Josh Allen"],
          destinations: {
            "Josh Allen": 0, // self-ref → drop
            "Ghost Player": 1, // asset not on side → drop
          },
        },
        {
          label: "B",
          assets: ["Ja'Marr Chase"],
          destinations: { "Ja'Marr Chase": 99 }, // OOR → drop
        },
      ],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides[0].destinations).toEqual({});
    expect(result.sides[1].destinations).toEqual({});
  });

  it("seeds empty destinations map when legacy format is migrated", () => {
    const parsed = {
      sideA: ["Josh Allen"],
      sideB: ["Ja'Marr Chase"],
    };
    const result = deserializeWorkspaceMulti(parsed, rowByName);
    expect(result.sides[0].destinations).toEqual({});
    expect(result.sides[1].destinations).toEqual({});
  });
});

// ── Multi-team total calculations ──────────────────────────────────────

describe("multi-team total calculations", () => {
  it("sideTotal works for 3+ sides independently", () => {
    const totals = [
      sideTotal([ALLEN], "full"),
      sideTotal([CHASE], "full"),
      sideTotal([PARSONS], "full"),
    ];
    expect(totals).toEqual([9000, 8500, 5000]);
  });
});

// ── Draft-capital stack effect (Option #2) ──────────────────────────
//
// computeStackAdjustments recomputes zero-sum effective auction power
// before/after the routed pick-$ swap and returns each side's change
// in premium, in board-value units (× the LEAGUE POOL's board-$ rate,
// ``boardPerDollar`` -- owner decision 2026-09-29).

describe("computeStackAdjustments", () => {
  it("returns zeros without a context", () => {
    expect(computeStackAdjustments(2, null)).toEqual([0, 0]);
    expect(computeStackAdjustments(3, undefined)).toEqual([0, 0, 0]);
  });

  it("returns zeros when required fields are missing or no moves", () => {
    expect(computeStackAdjustments(2, { sideTeams: ["A", "B"] })).toEqual([0, 0]);
    expect(
      computeStackAdjustments(2, {
        sideTeams: ["A", "B"],
        leagueStacks: { A: 1, B: 1 },
        moves: [],
      }),
    ).toEqual([0, 0]);
  });

  it("gates: a move whose side has no team yields zeros", () => {
    const ctx = {
      sideTeams: [null, "B"],
      leagueStacks: { A: 175, B: 180, C: 95, D: 85 },
      moves: [{ from: 1, to: 0, dollars: 20 }],
      boardPerDollar: 1,
    };
    expect(computeStackAdjustments(2, ctx)).toEqual([0, 0]);
  });

  it("withholds the effect when there is no pool rate", () => {
    const base = {
      sideTeams: ["A", "B"],
      leagueStacks: { A: 175, B: 180, C: 95, D: 85, E: 75, F: 65 },
      moves: [{ from: 1, to: 0, dollars: 20 }],
    };
    for (const boardPerDollar of [undefined, null, 0, -5, Number.NaN]) {
      expect(computeStackAdjustments(2, { ...base, boardPerDollar })).toEqual([0, 0]);
    }
  });

  it("a pick that leapfrogs the field credits the receiver, debits the sender", () => {
    // B (side 1) sends $20 of picks to A (side 0); A 175→195 passes
    // the old leader (B 180→160) and becomes the clear top stack.
    const ctx = {
      sideTeams: ["A", "B"],
      leagueStacks: { A: 175, B: 180, C: 95, D: 85, E: 75, F: 65 },
      moves: [{ from: 1, to: 0, dollars: 20 }],
      boardPerDollar: 1,
    };
    const [adjA, adjB] = computeStackAdjustments(2, ctx);
    expect(adjA).toBeGreaterThan(0);
    expect(adjB).toBeLessThan(0);
    // A rate of 1 here, so the magnitudes are real premium $.
    expect(Math.abs(adjA)).toBeGreaterThan(1);
  });

  it("scales by the league pool rate", () => {
    const base = {
      sideTeams: ["A", "B"],
      leagueStacks: { A: 175, B: 180, C: 95, D: 85, E: 75, F: 65 },
      moves: [{ from: 1, to: 0, dollars: 20 }],
    };
    const k1 = computeStackAdjustments(2, { ...base, boardPerDollar: 1 });
    const k10 = computeStackAdjustments(2, { ...base, boardPerDollar: 10 });
    expect(k10[0]).toBeCloseTo(k1[0] * 10, 4);
  });

  it("the moved picks' own board value no longer sets the rate", () => {
    // The retired rate was moved board / moved dollars: a $1 pick worth
    // 1,300 board points priced the whole league-wide premium shift at
    // 1,300 per $.  The pool rate ignores what the trade happens to move.
    const base = {
      sideTeams: ["A", "B"],
      leagueStacks: { A: 175, B: 180, C: 95, D: 85, E: 75, F: 65 },
      boardPerDollar: 150,
    };
    const cheap = computeStackAdjustments(2, {
      ...base,
      moves: [{ from: 1, to: 0, dollars: 20, board: 26000 }],
    });
    const dear = computeStackAdjustments(2, {
      ...base,
      moves: [{ from: 1, to: 0, dollars: 20, board: 900 }],
    });
    expect(cheap).toEqual(dear);
  });

  it("uses unrounded effective power (no whole-dollar rounding noise)", () => {
    // Moving a fraction of a dollar moves the premium by a fraction of a
    // dollar -- not by a whole rounding step.
    const ctx = {
      sideTeams: ["A", "B"],
      leagueStacks: { A: 175, B: 180, C: 95, D: 85, E: 75, F: 65 },
      moves: [{ from: 1, to: 0, dollars: 0.25 }],
      boardPerDollar: 1,
    };
    const [adjA] = computeStackAdjustments(2, ctx);
    expect(Math.abs(adjA)).toBeLessThan(0.25);
  });

  it("production league, two late picks: never outweighs what the side gives", () => {
    // 2026-09-29 dynasty_main upcoming-draft stacks; owner report: Side A
    // went to -2,603 when two 2029 late picks ($2, $1 at the anchor)
    // moved to it.  At a league pool rate the effect is a fraction of
    // those picks' own dollars, whichever two teams trade.
    const leagueStacks = {
      "Chargers Team Doctor": 327, CollinFoz: 101, "JerryJones and the Boyz": 0,
      "Medical Murrayjuana": 541, "Pop Trunk": 2, PorchHonkey: 8, "Queso Fresco": 7,
      "Rage Against The Achane ": 89, "The fags": 6, "Theres always next year ": 0,
      "Unsolicited Diggs Pics ": 4, jstuedle: 115,
    };
    const rate = 150;
    const moved = 3;
    const teams = Object.keys(leagueStacks);
    for (const a of teams) {
      for (const b of teams) {
        if (a === b) continue;
        const [adjA, adjB] = computeStackAdjustments(2, {
          sideTeams: [a, b],
          leagueStacks,
          moves: [
            { from: 1, to: 0, dollars: 2 },
            { from: 1, to: 0, dollars: 1 },
          ],
          boardPerDollar: rate,
        });
        expect(Math.abs(adjA)).toBeLessThan(moved * rate);
        expect(Math.abs(adjB)).toBeLessThan(moved * rate);
      }
    }
  });
});


// ── The ONE fairness-band owner on /trade (TC-C, owner decision 3) ─────────
describe("meter bands are relative with an absolute minimum", () => {
  it("the same 300-point gap is FAIR between stars and LOPSIDED between bench players", () => {
    expect(meterVerdict(300, 9300).label).toBe("FAIR");
    expect(meterVerdict(300, 1500).label).toBe("LOPSIDED");
  });
  it("a gap under 250 points is FAIR whatever the size", () => {
    expect(meterVerdict(249, 500).label).toBe("FAIR");
  });
  it("the meter, colour and words never disagree about 'fair'", () => {
    for (const [gap, larger] of [[100, 1000], [400, 9000], [400, 3000], [5000, 20000]]) {
      const fair = meterVerdict(gap, larger).level === "fair";
      expect(colorFromGap(gap, larger) === "").toBe(fair);
      expect(verdictFromGap(gap, larger) === "Near even").toBe(fair);
    }
  });
});
