/**
 * Second Opinions under BOTH package models (owner directive 2026-10-19,
 * part 3).  Each vendor row is evaluated twice over the SAME per-asset
 * resolutions — Chase Upside's active geometric adjustment (the row's opinion,
 * the only thing that votes) and the KTC adjustment method (a read-only
 * comparison attached as `row.comparison`).
 *
 * Covered: several correlation families (one family with two vendors),
 * canonical-fallback assets (IDP under an offense-only vendor, a pick nobody
 * but IDPTC prices), an evidence-excluded observation (UNAVAILABLE), an
 * unpriced piece (INCOMPLETE), a 3-team trade, tally invariance, and the
 * "Compare adjustments" control (one line per source row at every width).
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";

import TradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import { OPINION_STATE, tallyOpinions } from "@/lib/second-opinions";
import { buildOpinionRows } from "@/lib/second-opinions-rows";
import { PACKAGE_MODEL_IDS, valueAdjustmentFromSideArrays } from "@/lib/trade-logic";

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
      { key: "dlfSf", columnLabel: "DLF", scope: "overall_offense", isRankSignal: true },
      {
        key: "idpTradeCalc",
        columnLabel: "IDPTC",
        scope: "overall_idp",
        extraScopes: ["overall_offense"],
        isRankSignal: false,
      },
      { key: "staleSf", columnLabel: "Stale", scope: "overall_offense", isRankSignal: true },
    ],
    SOURCE_VENDOR_LABELS: {},
    vendorForSource: (key) => key,
  };
});

const KTC = PACKAGE_MODEL_IDS.KTC_2026_04;
const COMPARE = { compareModelId: KTC };

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

const STALE = {
  valueContribution: 7000,
  contributedToBlend: false,
  excludedReason: "freshness_or_health_zero_weight",
};
// Side A: one stud.  Side B: two mids + an IDP + a pick — a consolidation the
// two models price differently.
const STUD = row("QB Stud", 9000, {
  ktcCrowdSfTep: 9050,
  fantasyNavigatorSf: 8950,
  dlfSf: 8900,
  idpTradeCalc: 9100,
  staleSf: STALE,
});
const WR = row("WR Mid", 5200, {
  ktcCrowdSfTep: 5250,
  fantasyNavigatorSf: 5150,
  dlfSf: 5300,
  idpTradeCalc: 5100,
});
const RB = row("RB Mid", 3100, {
  ktcCrowdSfTep: 3000,
  fantasyNavigatorSf: 3150,
  dlfSf: 3050,
  idpTradeCalc: 3200,
});
const LB = row("LB Starter", 1500, { idpTradeCalc: 1600 }, { assetClass: "idp" });
const PICK = row("2027 Early 1st", 2400, { idpTradeCalc: 2450 }, { assetClass: "pick" });
const UNPRICED = {
  name: "Mystery",
  assetClass: "offense",
  values: { full: 0 },
  rankDerivedValue: null,
  sourceRankMeta: {},
};

const SIDES = [
  { label: "A", assets: [STUD] },
  { label: "B", assets: [WR, RB, LB, PICK] },
];

const byKey = (rows) => Object.fromEntries(rows.map((r) => [r.key, r]));

describe("cross-model rows: same per-asset inputs, two whole-package evaluations", () => {
  const plain = byKey(buildOpinionRows(SIDES));
  const compared = byKey(buildOpinionRows(SIDES, COMPARE));

  it("preserves every coverage state", () => {
    expect(plain.idpTradeCalc.opinion.state).toBe(OPINION_STATE.FULL_SOURCE);
    // Offense-only vendors fill the LB (out of scope) and the pick (not
    // published) with Chase Upside's exact value: hybrid estimates.
    expect(plain.ktcCrowdSfTep.opinion.state).toBe(OPINION_STATE.HYBRID_ESTIMATE);
    expect(plain.dlfSf.opinion.state).toBe(OPINION_STATE.HYBRID_ESTIMATE);
    // The stale source's only observation was excluded for an evidence reason.
    expect(plain.staleSf.opinion.state).toBe(OPINION_STATE.UNAVAILABLE);
  });

  it("row.opinion is byte-identical with or without the comparison", () => {
    for (const key of Object.keys(plain)) {
      expect(compared[key].opinion).toEqual(plain[key].opinion);
      expect(plain[key].comparison).toBeUndefined();
    }
  });

  it("the comparison re-prices the SAME resolved values with the KTC method only", () => {
    for (const key of ["idpTradeCalc", "ktcCrowdSfTep", "dlfSf"]) {
      const { opinion, comparison } = compared[key];
      expect(comparison.available).toBe(true);
      expect(comparison.modelId).toBe(KTC);
      const values = opinion.resolutionsBySide.map((rs) => rs.map((r) => r.value));
      // Fallback pieces enter the comparison at the SAME canonical value.
      const ktcAdj = valueAdjustmentFromSideArrays(values, { modelId: KTC });
      const activeAdj = valueAdjustmentFromSideArrays(values);
      expect(comparison.adjustments).toEqual(ktcAdj);
      expect(opinion.adjustments).toEqual(activeAdj);
      expect(comparison.adjustedTotals).toEqual(opinion.rawTotals.map((t, i) => t + ktcAdj[i]));
      // Never blended or chained.
      expect(comparison.adjustedTotals).not.toEqual(
        opinion.rawTotals.map((t, i) => t + ktcAdj[i] + activeAdj[i]),
      );
    }
  });

  it("never carries a state, so it can never vote", () => {
    for (const r of Object.values(compared)) {
      if (r.comparison) expect(r.comparison).not.toHaveProperty("state");
    }
  });

  it("no numeric verdict → no comparison (never a zero): UNAVAILABLE and INCOMPLETE", () => {
    expect(compared.staleSf.comparison).toMatchObject({
      available: false,
      reason: "no_numeric_verdict",
    });
    const incomplete = byKey(
      buildOpinionRows(
        [
          { label: "A", assets: [STUD] },
          { label: "B", assets: [WR, UNPRICED] },
        ],
        COMPARE,
      ),
    );
    for (const r of Object.values(incomplete)) {
      if (r.opinion.state === OPINION_STATE.INCOMPLETE) {
        expect(r.comparison).toMatchObject({ available: false, reason: "no_numeric_verdict" });
      }
    }
    expect(
      Object.values(incomplete).some((r) => r.opinion.state === OPINION_STATE.INCOMPLETE),
    ).toBe(true);
  });

  it("a 3-team trade gets no comparison, and its opinions are unchanged", () => {
    const three = [...SIDES, { label: "C", assets: [RB] }];
    const a = buildOpinionRows(three);
    const b = buildOpinionRows(three, COMPARE);
    b.forEach((r, i) => {
      expect(r.opinion).toEqual(a[i].opinion);
      expect(r.comparison).toMatchObject({ available: false, reason: "multi_team" });
    });
  });

  it("leaderDiffers marks only a real change of adjusted leader", () => {
    // One stud vs two mids: the geometric model and KTC's method lean
    // opposite ways ([9000] vs [8200, 2000] — the pure-lib disagreement).
    const s = [
      { label: "A", assets: [row("S", 9000, { idpTradeCalc: 9000 })] },
      {
        label: "B",
        assets: [row("M1", 8200, { idpTradeCalc: 8200 }), row("M2", 2000, { idpTradeCalc: 2000 })],
      },
    ];
    const r = byKey(buildOpinionRows(s, COMPARE)).idpTradeCalc;
    expect(r.opinion.leaderIdx).toBe(1);
    expect(r.comparison.leaderIdx).toBe(0);
    expect(r.comparison.leaderDiffers).toBe(true);
    // Same leader → no marker.
    const same = byKey(buildOpinionRows(SIDES, COMPARE)).idpTradeCalc;
    expect(same.comparison.leaderDiffers).toBe(
      same.comparison.leaderIdx !== same.opinion.leaderIdx,
    );
  });
});

describe("the active tally is identical whether or not the comparison is enabled", () => {
  it("tallyOpinions over rows with and without comparison deep-equal", () => {
    for (const sides of [
      SIDES,
      [
        { label: "A", assets: [STUD] },
        { label: "B", assets: [WR, UNPRICED] },
      ],
      [
        { label: "A", assets: [STUD, PICK] },
        { label: "B", assets: [WR, RB, LB] },
      ],
      [...SIDES, { label: "C", assets: [RB] }],
    ]) {
      const n = sides.length;
      expect(tallyOpinions(buildOpinionRows(sides, COMPARE), n)).toEqual(
        tallyOpinions(buildOpinionRows(sides), n),
      );
    }
  });
});

describe("TradeSourceBreakdown — one 'Compare adjustments' control", () => {
  it("is compact by default and reveals the KTC-method answer for every row on demand", () => {
    render(<TradeSourceBreakdown sides={SIDES} settings={{}} />);
    const tallyBefore = screen.getByTestId("second-opinions-tally").textContent;
    const btn = screen.getByRole("button", { name: "Compare adjustments" });
    expect(btn).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryAllByTestId("second-opinions-compare-line")).toHaveLength(0);

    fireEvent.click(btn);
    expect(btn).toHaveAttribute("aria-pressed", "true");
    const shownRows = screen.getAllByRole("row").filter((r) => r.getAttribute("data-state"));
    // One KTC-method line under each shown source name, the same at every
    // width (no extra column to pan to), and no new table column.
    expect(screen.getAllByTestId("second-opinions-compare-line")).toHaveLength(shownRows.length);
    for (const r of shownRows) {
      expect(within(r).getByTestId("second-opinions-compare-line").textContent).toMatch(
        /^KTC method: /,
      );
    }
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "Source",
      "Side A",
      "Side B",
      "Leader",
      "Margin",
    ]);
    // A row with a verdict reads its KTC-method leader tersely ("A by 58%");
    // the totals are only in the expanded detail, so the line stays short.
    const idptc = shownRows.find((r) => r.textContent.includes("IDPTC"));
    const ktcRow = byKey(buildOpinionRows(SIDES, COMPARE)).idpTradeCalc.comparison;
    const side = ["A", "B"][ktcRow.leaderIdx];
    const line = within(idptc).getByTestId("second-opinions-compare-line");
    expect(line.textContent).toBe(
      `KTC method: ${side} by ${Math.round(ktcRow.marginPct)}%` +
        (ktcRow.leaderDiffers ? " · leader differs" : ""),
    );
    for (const r of shownRows) {
      const text = within(r).getByTestId("second-opinions-compare-line").textContent;
      expect(text).toMatch(/^KTC method: (even|not computed|[AB] by \d+%)( · leader differs)?$/);
      expect(text.length).toBeLessThanOrEqual(40);
    }
    // Never presented as the vendor's own policy or as KTC's values.
    const note = screen.getByTestId("second-opinions-compare-note");
    expect(note).toHaveTextContent("not that source's own calculator");
    expect(note).toHaveTextContent("not KTC's own player values");
    expect(note).toHaveTextContent("the votes above use Chase Upside's adjustment");
    // The unavailable source shows no number for the comparison either.
    const staleRow = shownRows.find(
      (r) => r.getAttribute("data-state") === OPINION_STATE.UNAVAILABLE,
    );
    expect(within(staleRow).getByTestId("second-opinions-compare-line")).toHaveTextContent(
      "KTC method: not computed",
    );
    // The tally did not move.
    expect(screen.getByTestId("second-opinions-tally").textContent).toBe(tallyBefore);

    fireEvent.click(btn);
    expect(screen.queryAllByTestId("second-opinions-compare-line")).toHaveLength(0);
    expect(screen.getByTestId("second-opinions-tally").textContent).toBe(tallyBefore);
  });

  it("flags a disagreement in words only on rows whose leader changes", () => {
    const s = [
      { label: "A", assets: [row("S", 9000, { idpTradeCalc: 9000, dlfSf: 9000 })] },
      {
        label: "B",
        assets: [
          row("M1", 8200, { idpTradeCalc: 8200, dlfSf: 8200 }),
          // DLF prices M2 far lower, so both models agree Side A leads there.
          row("M2", 2000, { idpTradeCalc: 2000, dlfSf: 200 }),
        ],
      },
    ];
    render(<TradeSourceBreakdown sides={s} settings={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Compare adjustments" }));
    const lines = screen.getAllByTestId("second-opinions-compare-line");
    const differs = lines.filter((c) => c.getAttribute("data-differs") === "true");
    expect(differs).toHaveLength(1);
    expect(differs[0]).toHaveTextContent("leader differs");
    expect(lines.filter((c) => /leader differs/.test(c.textContent))).toHaveLength(1);
    expect(screen.getByTestId("second-opinions-compare-count")).toHaveTextContent(
      /^Leader differs on 1 of \d+ compared sources?\.$/,
    );
  });

  it("per-row detail shows both methods side by side from the same raw totals", () => {
    render(<TradeSourceBreakdown sides={SIDES} settings={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Compare adjustments" }));
    fireEvent.click(screen.getByRole("button", { name: "Show asset values for IDPTC" }));
    const t = screen.getByRole("table", { name: "Both adjustment methods for IDPTC" });
    expect(
      within(t)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Side", "Raw", "Chase Upside adj.", "Total", "KTC method adj.", "Total"]);
    expect(within(t).getAllByRole("row")).toHaveLength(3);
    // The full KTC-method totals live here, not in the compact row line.
    const cmp = byKey(buildOpinionRows(SIDES, COMPARE)).idpTradeCalc.comparison;
    const cells = within(t)
      .getAllByRole("row")
      .slice(1)
      .map((r) => within(r).getAllByRole("cell").at(-1).textContent);
    expect(cells).toEqual(cmp.adjustedTotals.map((v) => Math.round(v).toLocaleString()));
  });

  it("layout only: side cells carry the adjusted total; raw + adjustment live in the expanded row", () => {
    render(<TradeSourceBreakdown sides={SIDES} settings={{}} />);
    const shownRows = screen.getAllByRole("row").filter((r) => r.getAttribute("data-state"));
    const idptc = shownRows.find((r) => r.textContent.includes("IDPTC"));
    const o = byKey(buildOpinionRows(SIDES)).idpTradeCalc.opinion;
    const cells = within(idptc).getAllByRole("cell");
    // Source | Side A | Side B | Leader | Margin — numbers unchanged.
    expect(cells.slice(1, 3).map((c) => c.textContent)).toEqual(
      o.adjustedTotals.map((v) => Math.round(v).toLocaleString()),
    );
    expect(idptc.querySelector('[data-opinion="leader"]')).not.toBeNull();
    expect(idptc.querySelector('[data-opinion="margin"]').textContent).toBe(
      `${o.marginPct.toFixed(1)}%`,
    );
    expect(within(idptc).getByTestId("second-opinions-coverage")).toHaveTextContent(
      `vendor value · ${o.counts.source}/${o.counts.total} source`,
    );
    expect(idptc.textContent).not.toMatch(/raw /);
    fireEvent.click(screen.getByRole("button", { name: "Show asset values for IDPTC" }));
    const t = screen.getByRole("table", { name: "Package totals for IDPTC" });
    const body = within(t)
      .getAllByRole("row")
      .slice(1)
      .map((r) =>
        within(r)
          .getAllByRole("cell")
          .map((c) => c.textContent),
      );
    expect(body).toEqual(
      ["A", "B"].map((lbl, i) => [
        `Side ${lbl}`,
        Math.round(o.rawTotals[i]).toLocaleString(),
        o.adjustments[i] > 0 ? `+${Math.round(o.adjustments[i]).toLocaleString()}` : "none",
        Math.round(o.adjustedTotals[i]).toLocaleString(),
      ]),
    );
  });

  it("3-team trades say the comparison is not computed instead of showing numbers", () => {
    render(<TradeSourceBreakdown sides={[...SIDES, { label: "C", assets: [RB] }]} settings={{}} />);
    fireEvent.click(screen.getByRole("button", { name: "Compare adjustments" }));
    expect(screen.getByTestId("second-opinions-compare-note")).toHaveTextContent(
      "not computed for a 3-team trade",
    );
    expect(screen.queryAllByTestId("second-opinions-compare-line")).toHaveLength(0);
  });
});
