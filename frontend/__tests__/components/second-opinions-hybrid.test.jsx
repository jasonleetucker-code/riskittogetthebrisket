/**
 * Second Opinions — source values + EXACT Chase Upside fallback, under OUR
 * active package model (owner package 2026-10-17,
 * SECOND_OPINIONS_CANONICAL_FALLBACK_SPEC). Replaces the vendor-literal
 * tests (second-opinions-coverage / -scale), whose zero-adjustment,
 * native-KTC/DLF and "Not applicable" behaviors the owner overrode.
 *
 * The spec's twelve required cases, by number.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";

import TradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import {
  FALLBACK_REASON,
  OPINION_ORIGIN,
  OPINION_STATE,
  evaluateOpinion,
  publishedCanonicalValueOf,
  resolveOpinionAsset,
  tallyOpinions,
} from "@/lib/second-opinions";
import {
  PACKAGE_MODEL_IDS,
  packageAdjustPair,
  valueAdjustmentFromSideArrays,
} from "@/lib/trade-logic";

vi.mock("@/lib/dynasty-data", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    RANKING_SOURCES: [
      {
        key: "ktcCrowdSfTep",
        columnLabel: "KTC Crowd",
        scope: "overall_offense",
        correlationGroup: "ktcCrowd",
        isRankSignal: false,
      },
      {
        key: "fantasyNavigatorSf",
        columnLabel: "FN",
        scope: "overall_offense",
        correlationGroup: "ktcCrowd",
        isRankSignal: true,
      },
      {
        key: "dlfSf",
        columnLabel: "DLF",
        scope: "overall_offense",
        isRankSignal: true,
      },
      {
        key: "idpTradeCalc",
        columnLabel: "IDPTC",
        scope: "overall_idp",
        extraScopes: ["overall_offense"],
        isRankSignal: false,
      },
    ],
    SOURCE_VENDOR_LABELS: {},
    vendorForSource: (key) => key,
  };
});

const KTC = [
  { key: "ktcCrowdSfTep", scope: "overall_offense", isRankSignal: false },
];
const DLF = [{ key: "dlfSf", scope: "overall_offense", isRankSignal: true }];
const IDPTC = [
  {
    key: "idpTradeCalc",
    scope: "overall_idp",
    extraScopes: ["overall_offense"],
    isRankSignal: false,
  },
];

function row(name, canonical, meta = {}, extra = {}) {
  return {
    name,
    assetClass: extra.assetClass || "offense",
    values: { full: canonical },
    rankDerivedValue: canonical,
    sourceRankMeta: Object.fromEntries(
      Object.entries(meta).map(([k, v]) => [
        k,
        typeof v === "number"
          ? { valueContribution: v, contributedToBlend: true, appliedWeight: 1 }
          : v,
      ]),
    ),
    ...extra,
  };
}

const evaluate = (sides, subs) =>
  evaluateOpinion(
    sides.map((assets) =>
      assets.map((r) => resolveOpinionAsset({ row: r, mainSubs: subs })),
    ),
    valueAdjustmentFromSideArrays,
  );

const WR = row("WR One", 7900, {
  ktcCrowdSfTep: 8000,
  dlfSf: 7800,
  idpTradeCalc: 8100,
});
const RB = row("RB Two", 6600, {
  ktcCrowdSfTep: 6500,
  dlfSf: 6400,
  idpTradeCalc: 6550,
});
const LB = row("LB Three", 3200, { idpTradeCalc: 3300 }, { assetClass: "idp" });
const PICK = row(
  "2027 Early 1st",
  5400,
  { idpTradeCalc: 5300 },
  { assetClass: "pick" },
);

describe("1. offense-only vendor + IDP uses the exact canonical IDP value", () => {
  it("assembles the spec's worked example and applies the active model once", () => {
    const o = evaluate([[WR], [RB, LB]], KTC);
    expect(o.state).toBe(OPINION_STATE.HYBRID_ESTIMATE);
    const lb = o.resolutionsBySide[1][1];
    expect(lb).toMatchObject({
      origin: OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK,
      value: 3200,
      reason: FALLBACK_REASON.OUT_OF_SCOPE,
    });
    expect(lb.value).toBe(publishedCanonicalValueOf(LB));
    expect(o.rawTotals).toEqual([8000, 9700]);
    const va = packageAdjustPair([8000], [6500, 3200]);
    const expectA = va.displayed && va.side === 1 ? va.value : 0;
    const expectB = va.displayed && va.side === 2 ? va.value : 0;
    expect(o.adjustedTotals).toEqual([8000 + expectA, 9700 + expectB]);
  });
});

describe("2/3. every missing category — IDP, pick, offense — gets its exact canonical value", () => {
  it("mixed offense + IDP + pick keeps names and per-asset provenance", () => {
    const missingWr = row("WR Missing", 4100, {});
    const o = evaluate(
      [
        [WR, missingWr],
        [RB, LB, PICK],
      ],
      KTC,
    );
    const byName = Object.fromEntries(
      o.resolutionsBySide.flat().map((r, i) => [i, r]),
    );
    expect(Object.values(byName).map((r) => [r.origin, r.value])).toEqual([
      [OPINION_ORIGIN.SOURCE, 8000],
      [OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK, 4100],
      [OPINION_ORIGIN.SOURCE, 6500],
      [OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK, 3200],
      [OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK, 5400],
    ]);
    expect(o.resolutionsBySide[0][1].reason).toBe(
      FALLBACK_REASON.NOT_PUBLISHED,
    );
  });
});

describe("4. a fully covered source has no fallback and may vote", () => {
  it("is FULL_SOURCE", () => {
    const o = evaluate([[WR], [RB, LB]], IDPTC);
    expect(o.state).toBe(OPINION_STATE.FULL_SOURCE);
    expect(o.counts).toEqual({ total: 3, source: 3, fallback: 0, unpriced: 0 });
  });
});

describe("5. a source covering zero assets is only a baseline, never a vote", () => {
  it("is CHASE_ONLY_BASELINE and never in either tally", () => {
    const o = evaluate([[LB], [PICK]], KTC);
    expect(o.state).toBe(OPINION_STATE.CHASE_ONLY_BASELINE);
    const t = tallyOpinions(
      [{ key: "ktc", family: "ktcCrowd", opinion: o }],
      2,
    );
    expect(t.independent.families).toBe(0);
    expect(t.modeled.families).toBe(0);
    expect(t.counts.baseline).toBe(1);
  });
});

describe("6. nobody prices an asset: incomplete, no numeric winner, never zero", () => {
  it("is INCOMPLETE with no totals", () => {
    const orphan = {
      name: "Ghost",
      assetClass: "offense",
      values: {},
      sourceRankMeta: {},
    };
    const o = evaluate([[WR], [orphan]], KTC);
    expect(o.state).toBe(OPINION_STATE.INCOMPLETE);
    expect(o.rawTotals).toBeNull();
    expect(o.leaderIdx).toBeNull();
    expect(o.resolutionsBySide[1][0]).toMatchObject({
      origin: OPINION_ORIGIN.UNPRICED,
      value: null,
      reason: FALLBACK_REASON.CANONICAL_VALUE_UNAVAILABLE,
    });
  });
});

describe("7. DLF's native scale is never mixed with canonical thousands", () => {
  it("uses the normalized observation; native survives only as a diagnostic", () => {
    const dlfNative = row(
      "WR Native",
      7900,
      { dlfSf: 7700 },
      { sourceNativeValues: { dlfSf: 245 } },
    );
    const r = resolveOpinionAsset({ row: dlfNative, mainSubs: DLF });
    expect(r).toMatchObject({
      value: 7700,
      origin: OPINION_ORIGIN.SOURCE,
      nativeValue: 245,
    });
    const o = evaluate([[dlfNative], [RB]], DLF);
    expect(o.rawTotals).toEqual([7700, 6400]);
    expect(o.rawTotals).not.toContain(245);
  });
});

describe("8. no numeric translation available: fall back, labelled — no invented vendor price", () => {
  it("a rank-only board without a valueContribution falls back to canonical", () => {
    const noContribution = row("RB Rank", 5000, {
      dlfSf: { rank: 40, contributedToBlend: true },
    });
    const r = resolveOpinionAsset({ row: noContribution, mainSubs: DLF });
    expect(r).toMatchObject({
      origin: OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK,
      value: 5000,
      sourceValue: null,
    });
  });
});

describe("9. stale / zero-weight / held sources are not source evidence", () => {
  it("a held observation falls back with STALE_OR_HELD and cannot make a row FULL_SOURCE", () => {
    const held = row("WR Held", 7000, {
      ktcCrowdSfTep: {
        valueContribution: 7100,
        contributedToBlend: false,
        appliedWeight: 0,
      },
    });
    const r = resolveOpinionAsset({ row: held, mainSubs: KTC });
    expect(r).toMatchObject({
      origin: OPINION_ORIGIN.CHASE_UPSIDE_FALLBACK,
      value: 7000,
      reason: FALLBACK_REASON.STALE_OR_HELD,
    });
    expect(evaluate([[held], [RB]], KTC).state).toBe(
      OPINION_STATE.HYBRID_ESTIMATE,
    );
  });
});

describe("10. overrides, swapped sides, 1v1, N sides, model switch", () => {
  it("the fallback ignores a manual override", () => {
    const overridden = { ...LB, customValue: 9999 };
    expect(resolveOpinionAsset({ row: overridden, mainSubs: KTC }).value).toBe(
      3200,
    );
  });
  it("swapping sides mirrors the verdict", () => {
    const ab = evaluate([[WR], [RB, LB]], KTC);
    const ba = evaluate([[RB, LB], [WR]], KTC);
    expect(ba.adjustedTotals).toEqual([...ab.adjustedTotals].reverse());
    expect(ba.leaderIdx).toBe(1 - ab.leaderIdx);
  });
  it("1v1 carries no adjustment under the incumbent", () => {
    const o = evaluate([[WR], [RB]], KTC);
    expect(o.adjustments).toEqual([0, 0]);
  });
  it("three sides evaluate under the same adjustment function", () => {
    const o = evaluate([[WR], [RB], [LB]], IDPTC);
    expect(o.adjustments).toEqual(
      valueAdjustmentFromSideArrays([[8100], [6550], [3300]]),
    );
  });
  it("the adjustment is whatever the injected active model returns", () => {
    const geom = (sidesValues) => {
      const r = packageAdjustPair(sidesValues[0], sidesValues[1], {
        modelId: PACKAGE_MODEL_IDS.GEOM_Q078_V1,
      });
      return r.displayed
        ? r.side === 1
          ? [r.value, 0]
          : [0, r.value]
        : [0, 0];
    };
    const o = evaluateOpinion(
      [[WR], [RB, LB]].map((as) =>
        as.map((r) => resolveOpinionAsset({ row: r, mainSubs: KTC })),
      ),
      geom,
    );
    expect(o.adjustedTotals[0] - o.adjustedTotals[1]).toBeCloseTo(
      8000 - (6500 + 0.78 * 3200),
      0,
    );
  });
});

describe("12. independent and modeled tallies never contaminate each other", () => {
  it("two sources filling the same IDP with our value are estimates, not agreement", () => {
    const hybridA = evaluate([[WR], [RB, LB]], KTC);
    const hybridB = evaluate([[WR], [RB, LB]], DLF);
    const full = evaluate([[WR], [RB, LB]], IDPTC);
    const t = tallyOpinions(
      [
        { key: "ktcCrowdSfTep", family: "ktcCrowd", opinion: hybridA },
        { key: "dlfSf", family: "dlfSf", opinion: hybridB },
        { key: "idpTradeCalc", family: "idpTradeCalc", opinion: full },
      ],
      2,
    );
    expect(t.independent.families).toBe(1);
    expect(t.independent.eligible).toBe(3);
    expect(t.modeled.families).toBe(2);
    expect(t.counts).toEqual({
      full: 1,
      hybrid: 2,
      baseline: 0,
      incomplete: 0,
    });
  });
});

describe("panel", () => {
  it("shows hybrid rows with coverage, the notice, separate tallies and a provenance drilldown", () => {
    render(
      <TradeSourceBreakdown
        sides={[
          { label: "A", assets: [WR] },
          { label: "B", assets: [RB, LB] },
        ]}
        settings={{}}
        hasOverrides
      />,
    );
    expect(screen.getByTestId("second-opinions-notice").textContent).toMatch(
      /may not match that website's own calculator/,
    );
    expect(screen.getByTestId("second-opinions-override-note")).toBeTruthy();
    expect(screen.getByTestId("second-opinions-tally").textContent).toMatch(
      /IDPTC|independent votes/,
    );
    expect(
      screen.getByTestId("second-opinions-modeled-tally").textContent,
    ).toMatch(/Estimates \(not independent/);
    expect(
      screen.getAllByText(/2\/3 source · 1 Chase fallback/).length,
    ).toBeGreaterThan(0);
    fireEvent.click(
      screen.getByRole("button", { name: "Show asset values for KTC Crowd" }),
    );
    const drill = screen.getByRole("table", {
      name: "Asset values for KTC Crowd",
    });
    expect(
      within(drill).getByText(
        /Chase Upside fallback — outside this source's coverage/,
      ),
    ).toBeTruthy();
  });

  it("says there are no complete independent votes when no source covers everything", () => {
    render(
      <TradeSourceBreakdown
        sides={[
          { label: "A", assets: [WR] },
          {
            label: "B",
            assets: [LB, row("Unknown Pick", 900, {}, { assetClass: "pick" })],
          },
        ]}
        settings={{}}
      />,
    );
    expect(screen.getByTestId("second-opinions-tally").textContent).toMatch(
      /No complete independent votes available/,
    );
  });
});

describe("an adjustment the model cannot produce is not a zero adjustment", () => {
  it("non-finite or missing adjustments leave the row without a numeric verdict", () => {
    const sides = [[WR], [RB]].map((as) =>
      as.map((r) => resolveOpinionAsset({ row: r, mainSubs: IDPTC })),
    );
    for (const bad of [() => [NaN, 0], () => [0], () => null]) {
      const o = evaluateOpinion(sides, bad);
      expect(o.state).toBe(OPINION_STATE.INCOMPLETE);
      expect(o.leaderIdx).toBeNull();
      expect(o.adjustedTotals).toBeNull();
    }
  });
});
