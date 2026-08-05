/**
 * The Edge column and the popup opened from it must never disagree —
 * W12-F001.
 *
 * ``marketAction`` (display-helpers.js, /rankings Edge column) and
 * ``getPlayerEdge`` (trade-logic.js, PlayerPopup + /trade + /trades +
 * /rosters) read the SAME quantity: |consensusMean − retailMean| over the
 * per-source ranks, which the backend also stamps as
 * ``marketGapMagnitude``.  They applied 10 and 3 to it in two files with
 * no shared import, so every row whose gap fell in [3, 10) rendered HOLD
 * in the table and a full "Sell High" card in the popup opened from that
 * very row — 83 of 1,072 live rows, including Brock Bowers (#2), Bijan
 * Robinson (#3), Drake Maye (#5), Jahmyr Gibbs (#6), Trey McBride (#8),
 * Lamar Jackson (#11) and Joe Burrow (#13).
 *
 * This sweeps the whole band and asserts the two verbs agree at every
 * gap, so re-introducing a private floor in either file fails here.
 */
import { describe, it, expect } from "vitest";

import { marketAction } from "@/lib/display-helpers";
import { getPlayerEdge } from "@/lib/trade-logic";
import { MARKET_GAP_MIN_DIFF } from "@/lib/thresholds";

// ``ktcSfTep`` is the registry's only isRetail source; anything else is
// the consensus side.  Retail ranked BETTER (lower) than consensus =
// retail premium = SELL.
function rowWithGap(gap, { retailHigher = true } = {}) {
  const consensusRank = 50;
  const retailRank = retailHigher ? consensusRank - gap : consensusRank + gap;
  return {
    name: `Gap ${gap}`,
    canonicalConsensusRank: consensusRank,
    rankDerivedValue: 6000,
    values: { full: 6000 },
    confidenceBucket: "high",
    sourceCount: 4,
    effectiveSourceRanks: { ktcSfTep: retailRank, dlf: consensusRank },
    // What the backend stamps for exactly this row.
    marketGapConsensusSources: 3,
    marketGapRetailSources: 1,
    marketGapMagnitude: gap,
    marketGapDirection: retailHigher ? "retail_premium" : "consensus_premium",
  };
}

// The Edge column's verb, reduced to the popup's vocabulary.
function tableSignal(row) {
  const label = marketAction(row).label;
  if (label === "BUY") return "BUY";
  if (label === "SELL") return "SELL";
  return null; // HOLD / "—" — no directional verb on the row
}

describe("Edge column vs PlayerPopup verdict", () => {
  it("agree on direction and on whether there is a verb at all, gap 0-25", () => {
    const disagreements = [];
    for (let gap = 0; gap <= 25; gap += 1) {
      for (const retailHigher of [true, false]) {
        const row = rowWithGap(gap, { retailHigher });
        const table = tableSignal(row);
        const popup = getPlayerEdge(row).signal;
        if (table !== popup) disagreements.push({ gap, retailHigher, table, popup });
      }
    }
    expect(disagreements).toEqual([]);
  });

  it("both abstain below the shared floor and both fire at it", () => {
    const under = rowWithGap(MARKET_GAP_MIN_DIFF - 1);
    const at = rowWithGap(MARKET_GAP_MIN_DIFF);
    expect(tableSignal(under)).toBeNull();
    expect(getPlayerEdge(under).signal).toBeNull();
    expect(tableSignal(at)).toBe("SELL");
    expect(getPlayerEdge(at).signal).toBe("SELL");
  });

  it("both abstain together when the consensus side is one source", () => {
    const thin = { ...rowWithGap(40), marketGapConsensusSources: 1 };
    expect(tableSignal(thin)).toBeNull();
    expect(getPlayerEdge(thin).signal).toBeNull();
    expect(getPlayerEdge(thin).thinConsensus).toBe(true);
  });

  it("covers the band the two thresholds used to straddle", () => {
    // Nothing in [3, 10) may carry a verb on either surface.
    for (let gap = 3; gap < 10; gap += 1) {
      const row = rowWithGap(gap);
      expect(tableSignal(row)).toBeNull();
      expect(getPlayerEdge(row).signal).toBeNull();
    }
  });
});
