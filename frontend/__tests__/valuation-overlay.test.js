/**
 * LI-9 league-adjusted overlay application.
 *
 * The dangerous cases, in order:
 *  1. The DEFAULT path is the legacy `players` dict, not `playersArray`
 *     (server.py pops it). That path reads `_canonicalConsensusRank`
 *     with an underscore but `rankDerivedValue` without one — so an
 *     applier that writes one key set moves the value and leaves the
 *     rank stale, on the only path that ships.
 *  2. Sparse `factors` mean "absent = unchanged". Reusing the override
 *     delta's merge would delete every unmentioned player instead.
 *  3. A version mismatch must refuse outright, not half-apply.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { applyValuationOverlay, buildRows } from "@/lib/dynasty-data";

const STAMP = "2026-07-27T05:14:44";

function baseArrayContract() {
  return {
    ok: true,
    source: "backend",
    data: {
      scrapeTimestamp: STAMP,
      playersArray: [
        {
          displayName: "Rise",
          canonicalName: "rise",
          position: "RB",
          assetClass: "player",
          rankDerivedValue: 5000,
          canonicalConsensusRank: 2,
          canonicalTierId: 1,
          rankChange: 4,
          values: { overall: 5000, finalAdjusted: 5000, displayValue: 5000, raw: 4200 },
        },
        {
          displayName: "Fall",
          canonicalName: "fall",
          position: "TE",
          assetClass: "player",
          rankDerivedValue: 5200,
          canonicalConsensusRank: 1,
          canonicalTierId: 1,
          rankChange: -2,
          values: { overall: 5200, finalAdjusted: 5200, displayValue: 5200, raw: 4400 },
        },
        {
          displayName: "Still",
          canonicalName: "still",
          position: "WR",
          assetClass: "player",
          rankDerivedValue: 3000,
          canonicalConsensusRank: 3,
          canonicalTierId: 2,
          values: { overall: 3000, finalAdjusted: 3000, displayValue: 3000, raw: 2500 },
        },
      ],
    },
  };
}

function baseLegacyContract() {
  return {
    ok: true,
    source: "backend",
    data: {
      scrapeTimestamp: STAMP,
      players: {
        Rise: {
          rankDerivedValue: 5000,
          _canonicalConsensusRank: 2,
          _canonicalTierId: 1,
          _finalAdjusted: 5000,
          _rankChange: 4,
        },
        Fall: {
          rankDerivedValue: 5200,
          _canonicalConsensusRank: 1,
          _canonicalTierId: 1,
          _finalAdjusted: 5200,
        },
      },
      sleeper: { positions: { Rise: "RB", Fall: "TE" } },
    },
  };
}

const OVERLAY = {
  isNoop: false,
  scrapeTimestamp: STAMP,
  factors: { Rise: 1.06, Fall: 0.94 },
  ranks: { Rise: 1, Fall: 2, Still: 3 },
  tiers: { Rise: 1, Fall: 1, Still: 2 },
};

describe("applyValuationOverlay — playersArray path", () => {
  it("scales value and every alias that mirrors it", () => {
    const out = applyValuationOverlay(baseArrayContract(), OVERLAY);
    const rise = out.data.playersArray.find((r) => r.displayName === "Rise");
    expect(rise.rankDerivedValue).toBe(5300);
    expect(rise.values.overall).toBe(5300);
    expect(rise.values.finalAdjusted).toBe(5300);
    expect(rise.values.displayValue).toBe(5300);
  });

  it("leaves values.raw alone — the toggle changes Our Value, never Raw", () => {
    const out = applyValuationOverlay(baseArrayContract(), OVERLAY);
    const rise = out.data.playersArray.find((r) => r.displayName === "Rise");
    expect(rise.values.raw).toBe(4200);
  });

  it("applies the served ranks, not a locally derived order", () => {
    const out = applyValuationOverlay(baseArrayContract(), OVERLAY);
    const byName = Object.fromEntries(
      out.data.playersArray.map((r) => [r.displayName, r.canonicalConsensusRank]),
    );
    expect(byName).toEqual({ Rise: 1, Fall: 2, Still: 3 });
  });

  it("a row with no factor still takes its served rank", () => {
    const out = applyValuationOverlay(baseArrayContract(), OVERLAY);
    const still = out.data.playersArray.find((r) => r.displayName === "Still");
    expect(still.rankDerivedValue).toBe(3000);
    expect(still.canonicalConsensusRank).toBe(3);
  });

  it("nulls rankChange — 'moved up N since the previous scrape' is about the market board", () => {
    const out = applyValuationOverlay(baseArrayContract(), OVERLAY);
    expect(out.data.playersArray.every((r) => r.rankChange === null)).toBe(true);
  });

  it("does not mutate the input contract", () => {
    const base = baseArrayContract();
    const snapshot = JSON.stringify(base);
    applyValuationOverlay(base, OVERLAY);
    expect(JSON.stringify(base)).toBe(snapshot);
  });
});

describe("applyValuationOverlay — legacy dict path (THE DEFAULT)", () => {
  it("writes the underscored rank key AND the un-underscored value key", () => {
    const out = applyValuationOverlay(baseLegacyContract(), OVERLAY);
    const rise = out.data.players.Rise;
    // The asymmetry that makes this the highest-risk bug in the feature.
    expect(rise.rankDerivedValue).toBe(5300);
    expect(rise._canonicalConsensusRank).toBe(1);
    expect(rise._canonicalTierId).toBe(1);
  });

  it("moves value and rank together", () => {
    const out = applyValuationOverlay(baseLegacyContract(), OVERLAY);
    const fall = out.data.players.Fall;
    expect(fall.rankDerivedValue).toBe(4888);
    expect(fall._canonicalConsensusRank).toBe(2);
  });

  it("does not drop players absent from the overlay", () => {
    const base = baseLegacyContract();
    base.data.players.Unmentioned = { rankDerivedValue: 100, _canonicalConsensusRank: 9 };
    const out = applyValuationOverlay(base, { ...OVERLAY, ranks: { Rise: 1 } });
    expect(out.data.players.Unmentioned).toBeDefined();
    expect(out.data.players.Unmentioned.rankDerivedValue).toBe(100);
  });
});

describe("applyValuationOverlay — refuses rather than half-applies", () => {
  let warn;
  beforeEach(() => {
    warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  });
  afterEach(() => warn.mockRestore());

  it("returns the base contract on a scrape-timestamp mismatch", () => {
    const base = baseArrayContract();
    const out = applyValuationOverlay(base, { ...OVERLAY, scrapeTimestamp: "2026-07-27T09:00:00" });
    expect(out).toBe(base);
    expect(warn).toHaveBeenCalled();
  });

  it("returns the base contract when the overlay has no factors", () => {
    const base = baseArrayContract();
    expect(applyValuationOverlay(base, { ...OVERLAY, factors: {} })).toBe(base);
  });

  it("returns the base contract for a null overlay", () => {
    const base = baseArrayContract();
    expect(applyValuationOverlay(base, null)).toBe(base);
  });
});

describe("buildRows with an overlay applied", () => {
  it("orders by served rank and never invents one", () => {
    const out = applyValuationOverlay(baseArrayContract(), OVERLAY);
    const rows = buildRows(out.data);
    expect(rows.map((r) => r.name)).toEqual(["Rise", "Fall", "Still"]);
    expect(rows.map((r) => r.rank)).toEqual([1, 2, 3]);
  });

  it("an unranked row shows no rank rather than a client-derived ordinal", () => {
    const base = baseArrayContract();
    base.data.playersArray.push({
      displayName: "Deep",
      canonicalName: "deep",
      position: "WR",
      assetClass: "player",
      rankDerivedValue: 50,
      canonicalConsensusRank: null,
      values: { overall: 50 },
    });
    const rows = buildRows(applyValuationOverlay(base, OVERLAY).data);
    const deep = rows.find((r) => r.name === "Deep");
    expect(deep.rank).toBeNull();
  });
});

// ── The lens must reach EVERY board-scale field, and only those ────────
//
// R28 / W29-F002. The client applier scaled ``rankDerivedValue`` and the
// three ``values`` aliases, and additionally scaled ``_finalAdjusted``.
// Two things were wrong with that list:
//
//   * ``offenseOnlyRankDerivedValue`` — a SECOND board on the same
//     0-9999 scale, read by the trade simulator, the arbitrage finder
//     and the suggestion engine — was left at its market value, so the
//     lens was a silent no-op on every all-offense trade while the
//     response still stamped ``valuationMode: leagueAdjusted``.
//   * ``_finalAdjusted`` is the PRE-CANONICAL scraper composite, which
//     runs at a median 1.0855x the board. Multiplying it by a
//     board-derived factor produces a number on neither scale. The
//     server-side applier never did this.
//
// The two appliers now scale the same set — see BOARD_SCALE_ROW_FIELDS
// in src/league_intel/overlay.py.

describe("applyValuationOverlay — which fields the lens is allowed to move", () => {
  function contractWithBothBoards() {
    return {
      ok: true,
      source: "backend",
      data: {
        scrapeTimestamp: STAMP,
        playersArray: [
          {
            displayName: "Rise",
            canonicalName: "rise",
            position: "RB",
            rankDerivedValue: 5000,
            offenseOnlyRankDerivedValue: 4800,
            canonicalConsensusRank: 2,
            values: {
              overall: 5000,
              finalAdjusted: 5000,
              displayValue: 5000,
              rawComposite: 5400,
            },
          },
        ],
        players: {
          Rise: {
            rankDerivedValue: 5000,
            _offenseOnlyFinalAdjusted: 4800,
            _finalAdjusted: 5400,
            _canonicalConsensusRank: 2,
          },
        },
      },
    };
  }

  it("scales the offense-only board too — it is the same 0-9999 scale", () => {
    const out = applyValuationOverlay(contractWithBothBoards(), OVERLAY);
    const rise = out.data.playersArray.find((r) => r.displayName === "Rise");
    expect(rise.rankDerivedValue).toBe(5300);
    expect(rise.offenseOnlyRankDerivedValue).toBe(5088);
  });

  it("scales the legacy offense-only mirror too", () => {
    const out = applyValuationOverlay(contractWithBothBoards(), OVERLAY);
    expect(out.data.players.Rise._offenseOnlyFinalAdjusted).toBe(5088);
  });

  it("never scales the scraper composite — it is a different scale", () => {
    const out = applyValuationOverlay(contractWithBothBoards(), OVERLAY);
    const rise = out.data.playersArray.find((r) => r.displayName === "Rise");
    expect(rise.values.rawComposite).toBe(5400);
    expect(out.data.players.Rise._finalAdjusted).toBe(5400);
  });
});
