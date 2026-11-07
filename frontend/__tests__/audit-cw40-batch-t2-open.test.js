/**
 * CW-40 Batch T2 -- frontend findings still OPEN / PARTIAL / awaiting an owner decision (2026-11-07).
 *
 *  W07-F003  rankings `#` column: a non-pick row the backend left rank-less because the board could
 *            NOT price it still gets a client display ordinal (same mechanism as the recorded
 *            W25-F003 display half; `audit-w25-f003-regression.test.js`).  OPEN.
 *  W07-F004  the same unpriced rows get a fabricated TIER from that ordinal (`tierLabel`
 *            falls through to `rankBasedTierLabel(row.rank)`).  PARTIAL: the BUY/SELL verdict and
 *            the confidence badge for such rows are now honest (asserted below as passing tests);
 *            tier and position rank are not.
 *  W12-F007  the BUY/SELL verdict reads no confidence field.  REQUIRES_OWNER_DECISION: characterised
 *            only, no xfail, because what to do with a low-confidence verdict is a product choice.
 */
import { describe, expect, it } from "vitest";

import { buildRows } from "@/lib/dynasty-data";
import { tierLabel } from "@/lib/rankings-helpers";
import { marketAction } from "@/lib/display-helpers";
import { confidenceDisplay } from "@/lib/value-explainers";

function player(name, extra) {
  return {
    displayName: name,
    canonicalName: name,
    position: "RB",
    team: "XXX",
    assetClass: "offense",
    ...extra,
  };
}

const CONTRACT = {
  playersArray: [
    player("Ranked One", {
      canonicalConsensusRank: 1,
      rankDerivedValue: 9000,
      canonicalTierId: 1,
      confidenceBucket: "high",
    }),
    player("Ranked Two", {
      canonicalConsensusRank: 2,
      rankDerivedValue: 8000,
      canonicalTierId: 1,
      confidenceBucket: "high",
    }),
    // What the backend stamps for a row it declines to price (audit W07-F003/F004 evidence).
    player("Unpriced Back", {
      canonicalConsensusRank: null,
      rankDerivedValue: null,
      canonicalTierId: null,
      positionRank: null,
      confidenceBucket: "none",
      confidenceLabel: "None - unranked",
      marketGapDirection: "none",
      marketGapValueRatio: null,
      edgeSignal: null,
    }),
  ],
};

const byName = () => Object.fromEntries(buildRows(CONTRACT).map((r) => [r.name, r]));

describe("W07-F003: unpriced rows are not numbered by the client", () => {
  it("backend stamps win; the unpriced row is minted no local ordinal", () => {
    const rows = byName();
    expect(rows["Ranked One"].rank).toBe(1);
    expect(rows["Unpriced Back"].computedConsensusRank).toBeNull();
  });

  it("W07-F003: an unpriced row carries no `#` ordinal", () => {
    expect(byName()["Unpriced Back"].rank).toBeNull();
  });
});

describe("W07-F004: fabricated tier / verdict / confidence for unpriced rows", () => {
  it("(closed half) the verdict for an unpriced row is honest: no BUY/SELL, 'unranked'", () => {
    const action = marketAction(byName()["Unpriced Back"]);
    expect(action.kind).toBe("unranked");
    expect(["BUY", "SELL"]).not.toContain(action.label);
  });

  it("(closed half) the confidence badge for an unpriced row reads 'none', never 'low'", () => {
    const c = confidenceDisplay(byName()["Unpriced Back"]);
    expect(c.level).toBe("none");
  });

  it("W07-F004: an unpriced row shows no invented tier", () => {
    expect(tierLabel(byName()["Unpriced Back"])).toBe("Unranked");
  });
});

describe("W12-F007 (characterization, owner decision): the verdict ignores confidence", () => {
  const lowConfidence = {
    name: "Thin Evidence",
    pos: "WR",
    assetClass: "offense",
    rankDerivedValue: 5000,
    values: { full: 5000 },
    ktcMarket: { available: true, normalizedValue: 6500 },
    marketGapDirection: "retail_premium",
    marketGapValueRatio: 0.26,
    confidenceBucket: "low",
    sourceCount: 1,
    isSingleSource: true,
    anomalyFlags: ["some_flag"],
  };

  it("a low-confidence, single-source row still receives an actionable SELL", () => {
    expect(marketAction(lowConfidence).kind).toBe("sell");
  });

  it("raising confidence changes nothing about the verdict", () => {
    expect(marketAction({ ...lowConfidence, confidenceBucket: "high", sourceCount: 9 }).kind).toBe(
      marketAction(lowConfidence).kind,
    );
  });
});
