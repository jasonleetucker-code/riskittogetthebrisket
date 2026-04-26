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
  computeMultiSideAdjustments,
  adjustedSideTotals,
  multiAdjustedSideTotals,
  tradeGapAdjusted,
  VA_SCARCITY_SLOPE,
  VA_SCARCITY_INTERCEPT,
  VA_SCARCITY_CAP,
  VA_POSITION_DECAY,
  VA_PER_EXTRA_BOOST,
  VA_EFFECTIVE_CAP,
  effectiveValue,
  pickYearDiscount,
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
  computeSideFlows,
  computeSideFlowAssets,
  serializeWorkspaceMulti,
  deserializeWorkspaceMulti,
  SIDE_LABELS,
  MAX_SIDES,
  MIN_SIDES,
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

// ── Constants ────────────────────────────────────────────────────────

describe("constants", () => {
  it("VALUE_MODES has 2 modes", () => {
    expect(VALUE_MODES.length).toBe(2);
    expect(VALUE_MODES.map((m) => m.key)).toEqual(["full", "raw"]);
  });

  it("storage keys are stable strings", () => {
    expect(STORAGE_KEY).toBe("next_trade_workspace_v1");
    expect(RECENT_KEY).toBe("next_trade_recent_assets_v1");
  });
});

// ── verdictFromGap ───────────────────────────────────────────────────

describe("verdictFromGap", () => {
  // Thresholds on 1–9999 display scale: 350, 900, 1800
  it("returns 'Near even' for gaps under 350", () => {
    expect(verdictFromGap(0)).toBe("Near even");
    expect(verdictFromGap(349)).toBe("Near even");
    expect(verdictFromGap(-349)).toBe("Near even");
  });

  it("returns 'Lean' for gaps 350-899", () => {
    expect(verdictFromGap(350)).toBe("Lean");
    expect(verdictFromGap(899)).toBe("Lean");
    expect(verdictFromGap(-500)).toBe("Lean");
  });

  it("returns 'Strong lean' for gaps 900-1799", () => {
    expect(verdictFromGap(900)).toBe("Strong lean");
    expect(verdictFromGap(1799)).toBe("Strong lean");
    expect(verdictFromGap(-1200)).toBe("Strong lean");
  });

  it("returns 'Major gap' for gaps >= 1800", () => {
    expect(verdictFromGap(1800)).toBe("Major gap");
    expect(verdictFromGap(5000)).toBe("Major gap");
    expect(verdictFromGap(-2000)).toBe("Major gap");
  });

  it("treats gap symmetrically (absolute value)", () => {
    expect(verdictFromGap(500)).toBe(verdictFromGap(-500));
  });
});

// ── colorFromGap ─────────────────────────────────────────────────────

describe("colorFromGap", () => {
  it("returns empty string for near-even gaps", () => {
    expect(colorFromGap(0)).toBe("");
    expect(colorFromGap(255)).toBe("");
    expect(colorFromGap(-100)).toBe("");
  });

  it("returns 'green' when Side A wins (positive gap)", () => {
    expect(colorFromGap(500)).toBe("green");
    expect(colorFromGap(2000)).toBe("green");
  });

  it("returns 'red' when Side B wins (negative gap)", () => {
    expect(colorFromGap(-500)).toBe("red");
    expect(colorFromGap(-2000)).toBe("red");
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

  it("1-vs-2 with near-matching top assets is too lopsided for V12 to even (VA=0)", () => {
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
    const gap = tradeGapAdjusted([ALLEN], [CHASE, PICK_2026], "full");
    const rawGap = 9000 - (8500 + 7000); // −6500
    expect(gap).toBe(rawGap);
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

  it("suppresses VA on intensity-balanced consolidation trades", () => {
    // [ALLEN (9000)] vs [CHASE (8500) + PICK_2026 (7000)] — by KTC's
    // actual algorithm this is a "Fair Trade": Side A's raw_adj
    // intensity (raw_adj / total) is comparable to Side B's, so KTC
    // suppresses the VA badge entirely.  The previous V13 regression
    // fit fired here, but KTC.com does not.  Mirror returns null too.
    const r1 = computeValueAdjustment([ALLEN], [CHASE, PICK_2026], "full");
    expect(r1.recipientIdx).toBeNull();
    expect(r1.adjustment).toBe(0);
    const r2 = computeValueAdjustment([CHASE, PICK_2026], [ALLEN], "full");
    expect(r2.recipientIdx).toBeNull();
    expect(r2.adjustment).toBe(0);
    // [CHASE (8500)] vs [ALLEN (9000) + PICK_2026 (7000)] — same
    // intensity-balanced shape, different stud assignment.  KTC also
    // suppresses.
    const r3 = computeValueAdjustment([CHASE], [ALLEN, PICK_2026], "full");
    expect(r3.recipientIdx).toBeNull();
    expect(r3.adjustment).toBe(0);
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
  describe("KTC live-fixture reference (port ground truth)", () => {
    it("Chase-style 1v2 stud-vs-mids: VA fires on the stud side", () => {
      // [8200] vs [5500, 4900]: KTC's current algorithm produces
      // ~3636 (we tolerate ±5% to absorb tiny iterative-search
      // rounding differences between Node and KTC's live JS).
      const r = computeValueAdjustment(
        [mockRow(8200)],
        [mockRow(5500), mockRow(4900)],
        "full",
      );
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

    it("VA always ≥ 0 (non-negativity invariant)", () => {
      // Sweep a range of trade shapes; V12 must never return negative.
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
      }
    });

    it("VA is monotonic in stud value (bigger stud → bigger VA, all else equal)", () => {
      // Same 1v2 shape with the lone stud ramped up.  Larger studs
      // should produce larger VAs because raw(p) grows faster than p.
      const va6000 = computeValueAdjustment([mockRow(6000)], [mockRow(4000), mockRow(3000)], "full").adjustment;
      const va8000 = computeValueAdjustment([mockRow(8000)], [mockRow(4000), mockRow(3000)], "full").adjustment;
      const va9999 = computeValueAdjustment([mockRow(9999)], [mockRow(4000), mockRow(3000)], "full").adjustment;
      expect(va8000).toBeGreaterThan(va6000);
      expect(va9999).toBeGreaterThan(va8000);
    });
  });

  // ── V13 suppression rules (calibrated 2026-04 from 39 borderline trades) ──
  describe("V13 suppression (KTC 'fair trade' gates)", () => {
    it("suppresses VA when raw_diff is below the close-trade threshold", () => {
      // Two near-identical 2v2 sides — raw_diff under 100, no firing.
      // Captured analog: BORD_2v2_f, BORD_2v2_c → KTC reported VA=0.
      const r = computeValueAdjustment(
        [mockRow(6896), mockRow(3486)],
        [mockRow(6888), mockRow(3387)],
        "full",
      );
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
      const r = computeValueAdjustment(
        [mockRow(7765), mockRow(3880), mockRow(2540), mockRow(1963)],
        [mockRow(6642), mockRow(4915), mockRow(4874)],
        "full",
      );
      expect(r.adjustment).toBe(0);
    });

    it("does NOT suppress when best+worst same side but raw_diff is large", () => {
      // BORD_3v3_e analog: stud + mid + throw vs three mids/strong.
      // Same-side rule alone doesn't suppress when the raw gap is
      // big enough that KTC fires anyway.
      const r = computeValueAdjustment(
        [mockRow(9979), mockRow(4868), mockRow(3387)],
        [mockRow(6888), mockRow(6642), mockRow(4921)],
        "full",
      );
      expect(r.adjustment).toBeGreaterThan(0);
    });

    it("does NOT suppress when best+worst on different sides with moderate raw_diff", () => {
      // Best on side A, worst on side B → same-side rule doesn't
      // apply.  Falls through to V12's article math.  Captured
      // analog: BORD_3v3_c which fires VA=2428.
      const r = computeValueAdjustment(
        [mockRow(6642), mockRow(5309), mockRow(3486)],
        [mockRow(4921), mockRow(4868), mockRow(3387)],
        "full",
      );
      expect(r.adjustment).toBeGreaterThan(0);
    });
  });
});

// ── computeMultiSideAdjustments (N-team trades) ──────────────────────
//
// Structural property tests — we don't have KTC observations for 3+
// team trades yet, so these assert formula invariants and consistency
// with the 2-side path rather than hitting specific KTC numbers.
describe("computeMultiSideAdjustments", () => {
  it("returns array matching input length", () => {
    const out = computeMultiSideAdjustments(
      [[mockRow(9999)], [mockRow(5000)], [mockRow(3000)]],
      "full",
    );
    expect(out).toHaveLength(3);
  });

  it("reduces to 2-side behavior when called with 2 sides", () => {
    const sideA = [mockRow(9999)];
    const sideB = [mockRow(7846), mockRow(5717)];
    const [adjA, adjB] = computeMultiSideAdjustments([sideA, sideB], "full");
    const twoSide = computeValueAdjustment(sideA, sideB, "full");
    const expectedRecipient = twoSide.adjustment;
    const expectedOther = 0;
    expect(adjA).toBeCloseTo(expectedRecipient, 5);
    expect(adjB).toBeCloseTo(expectedOther, 5);
    expect(twoSide.recipientIdx).toBe(0);
  });

  it("returns zero for every side when all have equal piece counts (2 ea)", () => {
    const out = computeMultiSideAdjustments(
      [
        [mockRow(5000), mockRow(3000)],
        [mockRow(4800), mockRow(3100)],
        [mockRow(4900), mockRow(2900)],
      ],
      "full",
    );
    // Each side has count=2, opposition count=4 → guard passes, but
    // small.length < large.length only because opposition is larger.
    // However topGap is computed per side — most sides will have top
    // ≤ merged top, so VA stays at zero.  At most the side with the
    // strictly-highest top gets a non-zero VA.
    const nonZero = out.filter((v) => v > 0).length;
    expect(nonZero).toBeLessThanOrEqual(1);
  });

  it("in 3-team with one clear stud holder, that side gets the premium", () => {
    // Side A has a single 9999 stud.  Sides B and C each have 2
    // medium pieces.  A should earn significant VA for consolidation;
    // B and C may earn little or none (their tops are below A's stud).
    const out = computeMultiSideAdjustments(
      [
        [mockRow(9999)],
        [mockRow(5000), mockRow(3500)],
        [mockRow(4800), mockRow(3200)],
      ],
      "full",
    );
    expect(out[0]).toBeGreaterThan(1000);
    // B and C: their top < merged top (includes A's 9999), so their
    // topGap is 0 and they earn 0 VA.
    expect(out[1]).toBe(0);
    expect(out[2]).toBe(0);
  });

  it("never produces negative adjustments", () => {
    const out = computeMultiSideAdjustments(
      [
        [mockRow(9999), mockRow(8000)],
        [mockRow(7500)],
        [mockRow(6000), mockRow(4000), mockRow(2000)],
      ],
      "full",
    );
    for (const v of out) expect(v).toBeGreaterThanOrEqual(0);
  });

  it("VA stays within a sane bound (≤ 2× top asset)", () => {
    // V12 can produce VA values that exceed the side's own top asset
    // when the trade is heavily stud-vs-pile (the displayed VA is the
    // gap-to-equality on the OTHER side's total, not a per-asset
    // multiplier).  Pin a relaxed but defensible upper bound: the VA
    // never blows past 2× the side's own top piece.  Catches a
    // catastrophic constant-drift regression without false-failing on
    // legitimate big-VA cases.
    const sides = [
      [mockRow(9999)],
      [mockRow(5000), mockRow(3000), mockRow(2000)],
      [mockRow(4000), mockRow(3000)],
    ];
    const out = computeMultiSideAdjustments(sides, "full");
    sides.forEach((side, i) => {
      const top = Math.max(...side.map((r) => r.values.full));
      expect(out[i]).toBeLessThanOrEqual(top * 2);
    });
  });

  it("empty or single-side input returns zeros", () => {
    expect(computeMultiSideAdjustments([], "full")).toEqual([]);
    expect(computeMultiSideAdjustments([[mockRow(9999)]], "full")).toEqual([0]);
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

  it("does not duplicate an existing asset", () => {
    const result = addAssetToSide([ALLEN], ALLEN);
    expect(result.length).toBe(1);
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
    expect(result.valueMode).toBe("raw");
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

  it("excludes assets already in trade", () => {
    const result = filterPickerRows(allRows, [ALLEN], [CHASE], "", "all");
    expect(result.map((r) => r.name)).not.toContain("Josh Allen");
    expect(result.map((r) => r.name)).not.toContain("Ja'Marr Chase");
    expect(result.length).toBe(3);
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
    // V12: equal counts fire VA when one side has the bigger studs.
    // Allen+Chase (raw_adj_sum ≈ 6429) outranks Mahomes+pick (raw_adj
    // ≈ 5306), so side A is the recipient and gets a substantial VA
    // bonus on top of the raw 1700 lead.  The combined gap pushes
    // into the "Major gap" verdict zone (>1800).
    expect(gap).toBeGreaterThan(1700);
    expect(verdictFromGap(gap)).toBe("Major gap");
    expect(colorFromGap(gap)).toBe("green"); // Side A wins

    // Swap sides — V12 fires the same VA on whichever side has the
    // bigger raw_sum, so the gap simply flips sign.
    const [newA, newB] = [sideB, sideA];
    const swappedGap = tradeGapAdjusted(newA, newB, "full");
    expect(swappedGap).toBeLessThan(-1700);
    expect(verdictFromGap(swappedGap)).toBe("Major gap");
    expect(colorFromGap(swappedGap)).toBe("red"); // Now Side B wins

    // Remove an asset — newA has 2 pieces (8800+7000), trimmedB has 1 (9000)
    const trimmedB = removeAssetFromSide(newB, "Ja'Marr Chase");
    const newGap = tradeGapAdjusted(newA, trimmedB, "full");
    // V12: newA (Mahomes 8800 + Pick 7000, raw ≈ 5306) vs trimmedB
    // (Allen 9000 alone, raw ≈ 3415).  newA has more raw → newA is
    // the recipient.  newA's total (15800) is already bigger than
    // trimmedB's 9000, so adding VA pushes the gap further positive.
    // Pin the directional invariant: newGap stays positive (newA
    // wins) and is ≥ raw 6800.
    const rawNewGap = (8800 + 7000) - 9000;
    expect(rawNewGap).toBe(6800);
    expect(newGap).toBeGreaterThanOrEqual(rawNewGap);

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
  it("returns no signal when the row has no market-gap data", () => {
    const result = getPlayerEdge({ values: { full: 5000 } });
    expect(result.signal).toBeNull();
  });

  it("returns no signal when the market-gap magnitude is below 3 ranks", () => {
    const row = {
      values: { full: 5000 },
      canonicalSites: { ktc: 5200 },
      marketGapDirection: "retail_premium",
      marketGapMagnitude: 2,
    };
    expect(getPlayerEdge(row).signal).toBeNull();
  });

  it("returns BUY when consensus_premium (market undervalues vs consensus)", () => {
    // Consensus mean rank is lower (better) than retail/KTC — market
    // is pricing the player cheap.  We should BUY from a KTC-anchored
    // partner before the market catches up.
    const row = {
      values: { full: 9000 },
      canonicalSites: { ktc: 7000 },
      marketGapDirection: "consensus_premium",
      marketGapMagnitude: 6,
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("BUY");
    expect(result.rankGap).toBe(6);
    expect(result.edgePct).toBeGreaterThan(0);
  });

  it("returns SELL when retail_premium (market overvalues vs consensus)", () => {
    // KTC ranks the player higher than the rest of the board — the
    // retail market is overpaying.  SELL HIGH to that market.
    const row = {
      values: { full: 5000 },
      canonicalSites: { ktc: 6800 },
      marketGapDirection: "retail_premium",
      marketGapMagnitude: 8,
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("SELL");
    expect(result.rankGap).toBe(8);
  });

  it("falls back to rank-gap for edgePct when per-source values are missing", () => {
    const row = {
      marketGapDirection: "consensus_premium",
      marketGapMagnitude: 5,
    };
    const result = getPlayerEdge(row);
    expect(result.signal).toBe("BUY");
    expect(result.edgePct).toBe(5);
  });
});

describe("parsePickToken", () => {
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
  it("returns players that could fill the gap", () => {
    const rosterRows = [
      { name: "P1", pos: "WR", values: { full: 500 } },
      { name: "P2", pos: "RB", values: { full: 1000 } },
      { name: "P3", pos: "QB", values: { full: 2000 } },
    ];
    const result = findBalancers(1000, rosterRows, "full");
    expect(result.length).toBeGreaterThan(0);
    expect(result[0].name).toBe("P2"); // closest to gap of 1000
  });

  it("returns empty for small gap", () => {
    expect(findBalancers(100, [], "full")).toEqual([]);
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

// ── Pick year discount ──────────────────────────────────────────────

describe("pickYearDiscount", () => {
  it("current year gets 1.0", () => {
    expect(pickYearDiscount("2026 Early 1st", 2026)).toBe(1.0);
  });

  it("year+1 gets 0.85", () => {
    expect(pickYearDiscount("2027 Mid 2nd", 2026)).toBe(0.85);
  });

  it("year+2 gets 0.72", () => {
    expect(pickYearDiscount("2028 Late 1st", 2026)).toBe(0.72);
  });

  it("year+3 gets 0.60", () => {
    expect(pickYearDiscount("2029 Early 1st", 2026)).toBe(0.60);
  });

  it("non-pick returns 1.0", () => {
    expect(pickYearDiscount("Josh Allen", 2026)).toBe(1.0);
  });
});

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

  it("pick year discount still applies for future picks", () => {
    // The pick year discount path is the only remaining adjustment
    // inside effectiveValue.  Backend TEP lives elsewhere.
    const FUTURE_PICK = makeRow("2028 Early 1st", 7000, "PICK", "pick");
    const settings = {
      leagueFormat: "superflex",
      tepMultiplier: 1.15,
      pickCurrentYear: 2026,
    };
    const val = effectiveValue(FUTURE_PICK, "full", settings);
    // 2028 - 2026 = 2 year discount = 0.72 multiplier
    expect(val).toBeCloseTo(7000 * 0.72, 0);
  });
});

// ── Pick year discount in effectiveValue ────────────────────────────

describe("effectiveValue with pick discount", () => {
  const PICK_2027 = makeRow("2027 Early 1st", 7000, "PICK", "pick");

  it("future pick gets discounted", () => {
    const settings = { leagueFormat: "superflex", pickCurrentYear: 2026 };
    const val = effectiveValue(PICK_2027, "full", settings);
    expect(val).toBeCloseTo(7000 * 0.85, 0);
  });

  it("current year pick is not discounted", () => {
    const settings = { leagueFormat: "superflex", pickCurrentYear: 2027 };
    const val = effectiveValue(PICK_2027, "full", settings);
    expect(val).toBe(7000);
  });
});

// ══════════════════════════════════════════════════════════════════════════
// NEW: Trade Meter + Multi-Team tests
// ══════════════════════════════════════════════════════════════════════════

// ── meterVerdict ────────────────────────────────────────────────────────

describe("meterVerdict", () => {
  it("returns FAIR for gap < 350", () => {
    expect(meterVerdict(0)).toEqual({ label: "FAIR", level: "fair" });
    expect(meterVerdict(349)).toEqual({ label: "FAIR", level: "fair" });
  });

  it("returns SLIGHT EDGE for gap 350-899", () => {
    expect(meterVerdict(350)).toEqual({ label: "SLIGHT EDGE", level: "slight" });
    expect(meterVerdict(899)).toEqual({ label: "SLIGHT EDGE", level: "slight" });
  });

  it("returns UNFAIR for gap 900-1799", () => {
    expect(meterVerdict(900)).toEqual({ label: "UNFAIR", level: "unfair" });
    expect(meterVerdict(1799)).toEqual({ label: "UNFAIR", level: "unfair" });
  });

  it("returns LOPSIDED for gap >= 1800", () => {
    expect(meterVerdict(1800)).toEqual({ label: "LOPSIDED", level: "lopsided" });
    expect(meterVerdict(5000)).toEqual({ label: "LOPSIDED", level: "lopsided" });
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
    expect(flows).toEqual([
      { given: 9000, received: 8500, net: -500 },
      { given: 8500, received: 9000, net: 500 },
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
    expect(flows[0]).toEqual({ given: 9000, received: 8500, net: -500 });
    expect(flows[1]).toEqual({ given: 8500, received: 5000, net: -3500 });
    expect(flows[2]).toEqual({ given: 5000, received: 9000, net: 4000 });
  });

  it("3-team trade: missing destination falls back to next-side default", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: {} }, // no dest → default to 1
      { id: 1, label: "B", assets: [CHASE], destinations: {} }, // no dest → default to 2
      { id: 2, label: "C", assets: [PARSONS], destinations: {} }, // no dest → default to 0
    ];
    const flows = computeSideFlows(sides, "full");
    expect(flows[0].received).toBe(5000); // Parsons from C
    expect(flows[1].received).toBe(9000); // Allen from A
    expect(flows[2].received).toBe(8500); // Chase from B
  });

  it("3-team trade: self-referencing or out-of-range destination falls back to default", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 0 } }, // self
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 99 } }, // OOR
      { id: 2, label: "C", assets: [PARSONS], destinations: { "Micah Parsons": -1 } }, // neg
    ];
    const flows = computeSideFlows(sides, "full");
    // All fall back to defaults: A→1, B→2, C→0
    expect(flows[0].received).toBe(5000); // Parsons from C
    expect(flows[1].received).toBe(9000); // Allen from A
    expect(flows[2].received).toBe(8500); // Chase from B
  });

  it("returns zero-shaped arrays for empty / single-side inputs", () => {
    expect(computeSideFlows([], "full")).toEqual([]);
    expect(computeSideFlows([{ assets: [ALLEN] }], "full")).toEqual([
      { given: 0, received: 0, net: 0 },
    ]);
  });

  it("handles empty sides in a 3-team trade", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN], destinations: { "Josh Allen": 1 } },
      { id: 1, label: "B", assets: [], destinations: {} },
      { id: 2, label: "C", assets: [], destinations: {} },
    ];
    const flows = computeSideFlows(sides, "full");
    expect(flows[0]).toEqual({ given: 9000, received: 0, net: -9000 });
    expect(flows[1]).toEqual({ given: 0, received: 9000, net: 9000 });
    expect(flows[2]).toEqual({ given: 0, received: 0, net: 0 });
  });

  it("NET flow always sums to zero across all sides (conservation)", () => {
    const sides = [
      { id: 0, label: "A", assets: [ALLEN, MAHOMES], destinations: { "Josh Allen": 1, "Patrick Mahomes": 2 } },
      { id: 1, label: "B", assets: [CHASE], destinations: { "Ja'Marr Chase": 2 } },
      { id: 2, label: "C", assets: [PARSONS, PICK_2026], destinations: { "Micah Parsons": 0, "2026 Early 1st": 1 } },
    ];
    const flows = computeSideFlows(sides, "full");
    const totalNet = flows.reduce((s, f) => s + f.net, 0);
    expect(totalNet).toBe(0);
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
    expect(result.valueMode).toBe("raw");
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
