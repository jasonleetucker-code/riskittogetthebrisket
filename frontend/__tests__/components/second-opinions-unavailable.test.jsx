/**
 * Owner closeout 2026-10-18, decision 9 (TCM-K06) — an excluded external
 * opinion is "Unavailable — <actual reason>".
 *
 * Pinned, through the Second Opinions owners (lib/second-opinions.js,
 * lib/second-opinions-rows.js, TradeSourceBreakdown, TradeOpinionTally):
 *   - never shown as EVEN;
 *   - our canonical value never stands in for its vote;
 *   - a canonical fallback is never counted as a second opinion;
 *   - never turned into 0;
 *   - never hidden;
 *   - the independent tally equals the independent opinions displayed.
 */
import { describe, expect, it, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";

import TradeOpinionTally from "@/components/trade/TradeOpinionTally";
import TradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import {
  OPINION_ORIGIN,
  OPINION_STATE,
  resolveOpinionAsset,
  tallyOpinions,
  unavailableReasonText,
} from "@/lib/second-opinions";
import { buildOpinionRows } from "@/lib/second-opinions-rows";

vi.mock("@/lib/dynasty-data", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    RANKING_SOURCES: [
      { key: "ktcCrowdSfTep", columnLabel: "KTC Crowd", scope: "overall_offense", correlationGroup: "ktcCrowd", isRankSignal: false },
      { key: "dlfSf", columnLabel: "DLF", scope: "overall_offense", isRankSignal: true },
      { key: "idpTradeCalc", columnLabel: "IDPTC", scope: "overall_idp", extraScopes: ["overall_offense"], isRankSignal: false },
    ],
    SOURCE_VENDOR_LABELS: {},
    vendorForSource: (key) => key,
  };
});

const KTC = [{ key: "ktcCrowdSfTep", scope: "overall_offense", isRankSignal: false }];
const voting = (v) => ({ valueContribution: v, contributedToBlend: true, appliedWeight: 1 });

function row(name, canonical, meta = {}, extra = {}) {
  return {
    name,
    assetClass: "offense",
    values: { full: canonical },
    rankDerivedValue: canonical,
    sourceRankMeta: meta,
    ...extra,
  };
}

// DLF's value for the WR is stale (excluded from our blend); KTC and IDPTC vote.
const WR = row("WR One", 7900, {
  ktcCrowdSfTep: voting(8000),
  dlfSf: {
    valueContribution: 7800,
    contributedToBlend: false,
    appliedWeight: 0,
    excludedReason: "freshness_or_health_zero_weight",
  },
  idpTradeCalc: voting(8100),
});
const RB = row("RB Two", 6600, {
  ktcCrowdSfTep: voting(6500),
  dlfSf: voting(6400),
  idpTradeCalc: voting(6550),
});
const sides = [
  { label: "A", assets: [WR] },
  { label: "B", assets: [RB] },
];

describe("resolveOpinionAsset — the actual reason, no stand-in value", () => {
  it("compact view: a row-level freshness exclusion with no meta flags is unavailable", () => {
    const r = resolveOpinionAsset({
      row: row("X", 5000, { ktcCrowdSfTep: { valueContribution: 5100, appliedWeight: 0.4 } }, {
        freshnessExcludedSources: ["ktcCrowdSfTep"],
      }),
      mainSubs: KTC,
    });
    expect(r.origin).toBe(OPINION_ORIGIN.UNAVAILABLE);
    expect(r.reason).toBe("freshness_or_health_zero_weight");
    expect(r.value).toBeNull();
    expect(r.fallbackValue).toBeNull();
  });

  it("a superseded member and an unknown backend reason keep their own words", () => {
    const sup = resolveOpinionAsset({
      row: row("X", 5000, {
        ktcCrowdSfTep: { valueContribution: 5100, contributedToBlend: false, supersededBy: "ktcTradesSfTep" },
      }),
      mainSubs: KTC,
    });
    expect(sup.reason).toBe("superseded_by_family");
    const odd = resolveOpinionAsset({
      row: row("X", 5000, {
        ktcCrowdSfTep: { valueContribution: 5100, contributedToBlend: false, excludedReason: "identity_quarantine" },
      }),
      mainSubs: KTC,
    });
    expect(odd.reason).toBe("identity_quarantine");
    expect(unavailableReasonText("identity_quarantine")).toBe("identity quarantine");
    expect(unavailableReasonText(null)).toMatch(/reason not published/);
  });

  it("an eligible sibling sub-board still prices the asset (the vendor did publish one)", () => {
    const subs = [
      { key: "ktcCrowdSfTep", scope: "overall_offense" },
      { key: "ktcTradesSfTep", scope: "overall_offense" },
    ];
    const r = resolveOpinionAsset({
      row: row("X", 5000, {
        ktcCrowdSfTep: { valueContribution: 5100, contributedToBlend: false, appliedWeight: 0 },
        ktcTradesSfTep: voting(5300),
      }),
      mainSubs: subs,
    });
    expect(r.origin).toBe(OPINION_ORIGIN.SOURCE);
    expect(r.value).toBe(5300);
  });
});

describe("rows and tally — never EVEN, never a vote, never hidden", () => {
  it("the stale source is UNAVAILABLE with no totals and no leader", () => {
    const rows = buildOpinionRows(sides);
    const dlf = rows.find((r) => r.key === "dlfSf");
    expect(dlf.opinion.state).toBe(OPINION_STATE.UNAVAILABLE);
    expect(dlf.opinion.leaderIdx).toBeNull();
    expect(dlf.opinion.adjustedTotals).toBeNull();
    expect(dlf.opinion.rawTotals).toBeNull();
    expect(dlf.opinion.unavailableReasons).toEqual(["freshness_or_health_zero_weight"]);
  });

  it("the independent tally equals the independent opinions displayed", () => {
    const rows = buildOpinionRows(sides);
    const t = tallyOpinions(rows, 2);
    const fullFamilies = new Set(
      rows.filter((r) => r.opinion.state === OPINION_STATE.FULL_SOURCE).map((r) => r.family),
    );
    expect(t.independent.families).toBe(fullFamilies.size);
    expect(t.independent.wins.reduce((a, b) => a + b, 0) + t.independent.even + t.independent.split).toBe(
      t.independent.families,
    );
    // The unavailable source is counted as unavailable, not as even.
    expect(t.counts.unavailable).toBe(1);
    expect(t.independent.even).toBe(0);
    expect(t.modeled.families).toBe(0);
    expect(t.unavailableFamilies).toBe(1);
  });

  it("the per-source table says Unavailable with the reason, never Even and never 0", () => {
    render(<TradeSourceBreakdown sides={sides} settings={{}} />);
    const cell = screen.getByTestId("second-opinions-unavailable");
    expect(cell.textContent).toBe(
      "Unavailable — stale or unhealthy source, excluded from our blend",
    );
    const tr = cell.closest("tr");
    expect(tr.getAttribute("data-state")).toBe(OPINION_STATE.UNAVAILABLE);
    expect(tr.textContent).not.toMatch(/\bEven\b/);
    // Side totals read "—", never a 0.
    const totals = within(tr).getAllByRole("cell").slice(1, 3).map((c) => c.textContent);
    expect(totals).toEqual(["—", "—"]);
    expect(screen.getByTestId("second-opinions-unavailable-tally").textContent).toMatch(
      /1 source/,
    );
  });

  it("the immediate tally names the unavailable source in its coverage", () => {
    render(<TradeOpinionTally sides={sides} />);
    expect(screen.getByTestId("trade-opinion-tally-coverage").textContent).toMatch(
      /1 source unavailable/,
    );
  });
});
