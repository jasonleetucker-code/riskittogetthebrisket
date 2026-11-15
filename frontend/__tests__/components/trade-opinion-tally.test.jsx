/**
 * TC-B / TCM-K03 — the IMMEDIATE one-glance Second Opinions tally.
 *
 * It reads the same rows as the per-source table (one assembly,
 * lib/second-opinions-rows.js) and the same tally owner: full-source rows
 * are the only independent votes, one per correlation family; hybrid rows
 * are estimates, shown apart and never counted.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, screen, within } from "@testing-library/react";

import TradeOpinionTally from "@/components/trade/TradeOpinionTally";
import TradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import { buildOpinionRows, opinionTally, opinionTallyText } from "@/lib/second-opinions-rows";

vi.mock("@/lib/dynasty-data", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    RANKING_SOURCES: [
      { key: "ktcCrowdSfTep", columnLabel: "KTC Crowd", scope: "overall_offense", correlationGroup: "ktcCrowd", isRankSignal: false },
      { key: "fantasyNavigatorSf", columnLabel: "FN", scope: "overall_offense", correlationGroup: "ktcCrowd", isRankSignal: true },
      { key: "dlfSf", columnLabel: "DLF", scope: "overall_offense", isRankSignal: true },
      { key: "idpTradeCalc", columnLabel: "IDPTC", scope: "overall_idp", extraScopes: ["overall_offense"], isRankSignal: false },
    ],
    SOURCE_VENDOR_LABELS: {},
    vendorForSource: (key) => key,
  };
});

function row(name, canonical, meta = {}, extra = {}) {
  return {
    name,
    assetClass: extra.assetClass || "offense",
    values: { full: canonical },
    rankDerivedValue: canonical,
    sourceRankMeta: Object.fromEntries(
      Object.entries(meta).map(([k, v]) => [k, { valueContribution: v, contributedToBlend: true, appliedWeight: 1 }]),
    ),
    ...extra,
  };
}

const WR = row("WR One", 7900, { ktcCrowdSfTep: 8000, fantasyNavigatorSf: 7950, dlfSf: 7800, idpTradeCalc: 8100 });
const RB = row("RB Two", 6600, { ktcCrowdSfTep: 6500, fantasyNavigatorSf: 6550, dlfSf: 6400, idpTradeCalc: 6550 });
const LB = row("LB Three", 3200, { idpTradeCalc: 3300 }, { assetClass: "idp" });

const sides = (a, b) => [
  { label: "A", assets: a },
  { label: "B", assets: b },
];

describe("TradeOpinionTally", () => {
  it("shows independent family votes and estimates apart, with coverage", () => {
    // KTC family (2 members) + DLF are offense-only: with an LB on side B
    // they are hybrid estimates.  IDPTC prices every piece: the only vote.
    const s = sides([WR], [RB, LB]);
    render(<TradeOpinionTally sides={s} />);
    const line = screen.getByTestId("trade-opinion-tally");
    const t = opinionTally(buildOpinionRows(s), 2);
    expect(t.independent.families).toBe(1);
    expect(t.modeled.families).toBe(2);
    expect(line.textContent).toContain(`Independent: ${opinionTallyText(t.independent, ["A", "B"])}`);
    expect(within(line).getByTestId("trade-opinion-tally-coverage").textContent).toBe(
      "1 of 3 source families priced every piece",
    );
    expect(line.textContent).toContain("Estimates (share our values, not votes)");
  });

  it("agrees with the per-source table beside it (one row assembly)", () => {
    const s = sides([WR], [RB]);
    render(
      <>
        <TradeOpinionTally sides={s} />
        <TradeSourceBreakdown sides={s} settings={{}} />
      </>,
    );
    const tally = opinionTally(buildOpinionRows(s), 2);
    const text = opinionTallyText(tally.independent, ["A", "B"]);
    expect(screen.getByTestId("trade-opinion-tally").textContent).toContain(text);
    expect(screen.getByTestId("second-opinions-tally").textContent).toContain(text);
    // A KTC family of two agreeing members is ONE vote.
    expect(tally.independent.families).toBe(3);
  });

  it("says there is no independent vote rather than inventing one", () => {
    const ghost = { name: "Ghost", assetClass: "offense", values: {}, sourceRankMeta: {} };
    render(<TradeOpinionTally sides={sides([LB], [ghost])} />);
    expect(screen.getByTestId("trade-opinion-tally").textContent).toMatch(
      /No source priced every piece, so there is no independent vote/,
    );
  });

  it("renders nothing until two sides hold assets", () => {
    const { container } = render(<TradeOpinionTally sides={sides([WR], [])} />);
    expect(container.textContent).toBe("");
  });
});
