/**
 * Early/Mid/Late future-pick market references stay discoverable in the
 * Trade Calculator search (owner decision 2026-10-03, DECISION 2).
 *
 * Root cause of the disappearance: the canonical contract DOES carry
 * priced, unsuppressed tier rows for every active future year ("2027 Early
 * 1st" 6590 / "Mid 1st" 5546 / "Late 1st" 4723 on the 2026-10-03 board),
 * and the board search found them.  The /trade search then returned
 * ``[...owned, ...board]`` — up to five of the selected team's OWNED picks
 * BEFORE the board rows — so on a phone with the keyboard up only the
 * owned "2027 1st / 2nd" rows were visible.  The fix: market references
 * first, owned picks second, each group with its own limit
 * (``searchCalculatorAssets``), exact-query relevance first, and a
 * scrollable dropdown.
 *
 * These tests build the board through the real materializer (``buildRows``)
 * from a contract-shaped payload, so "the value shown is the board row's
 * canonical ``rankDerivedValue``" is checked end to end rather than assumed.
 * Years are derived from the fixture, never hardcoded in the assertions'
 * logic: the same checks run for 2027 and 2028.
 */
import { describe, expect, it } from "vitest";
import { buildRows } from "../lib/dynasty-data.js";
import {
  addAssetToSide,
  isTradeableBoardRow,
  searchCalculatorAssets,
  searchTradeAssets,
  sideTotal,
} from "../lib/trade-logic.js";
import { groupTradeSearchResults, ownedPickEntry, tradeEntryKey } from "../lib/trade-assets.js";

const TIERS = ["Early", "Mid", "Late"];
const ROUNDS = ["1st", "2nd", "3rd"];

/** Contract-shaped pick row. */
function pickRow(name, value, rank, extra = {}) {
  return {
    playerId: null,
    displayName: name,
    canonicalName: name,
    position: "PICK",
    assetClass: "pick",
    canonicalConsensusRank: rank,
    rankDerivedValue: value,
    values: { displayValue: value, finalAdjusted: value, rawComposite: value },
    ...extra,
  };
}

/** A board with tier rows for two future years and suppressed current-year aliases. */
function contract() {
  const playersArray = [
    {
      playerId: "6794",
      displayName: "Justin Jefferson",
      canonicalName: "Justin Jefferson",
      position: "WR",
      assetClass: "offense",
      canonicalConsensusRank: 5,
      rankDerivedValue: 8600,
      values: { displayValue: 8600, finalAdjusted: 8600, rawComposite: 8600 },
    },
  ];
  let rank = 20;
  for (const [y, base] of [
    [2027, 6590],
    [2028, 6100],
  ]) {
    ROUNDS.forEach((round, ri) => {
      TIERS.forEach((tier, ti) => {
        const value = Math.round(base / (ri + 1) - ti * 600);
        playersArray.push(pickRow(`${y} ${tier} ${round}`, value, rank));
        rank += 3;
      });
    });
  }
  // Current year: generic tiers are suppressed aliases of the slot rows.
  playersArray.push(
    pickRow("2026 Mid 1st", null, null, {
      pickGenericSuppressed: true,
      values: { displayValue: 0, finalAdjusted: 0, rawComposite: 0 },
    }),
  );
  playersArray.push(pickRow("2026 Pick 1.06", 4987, 52));
  return { playersArray };
}

const ROWS = buildRows(contract());
const rowByName = new Map(ROWS.map((r) => [r.name, r]));
const futureYears = [
  ...new Set(
    ROWS.filter((r) => r.assetClass === "pick" && /Early|Mid|Late/.test(r.name) && isTradeableBoardRow(r))
      .map((r) => Number(String(r.name).slice(0, 4))),
  ),
].sort();

/** Five+ owned picks for one team in ``year`` — the crowding case. */
function ownedPicks(year) {
  const labels = [
    `${year} 1st (own)`,
    `${year} 1st (from Team B)`,
    `${year} 2nd (own)`,
    `${year} 2nd (from Team C)`,
    `${year} 3rd (own)`,
    `${year} 3rd (from Team D)`,
  ];
  return labels.map((label, i) =>
    ownedPickEntry(rowByName.get(`${year} Mid ${["1st", "1st", "2nd", "2nd", "3rd", "3rd"][i]}`), {
      assetId: `pick:dynasty_main:${year}:r${Math.floor(i / 2) + 1}:o${i + 1}`,
      label,
    }),
  );
}

describe("fixture sanity", () => {
  it("derives two active future years from the data", () => {
    expect(futureYears).toEqual([2027, 2028]);
  });
});

describe.each(futureYears.map((y) => [y]))("market tier references for %i", (year) => {
  it.each(TIERS.map((t) => [t]))("[15-18] '%s 1st' is selectable by exact query", (tier) => {
    const name = `${year} ${tier} 1st`;
    const hits = searchCalculatorAssets(ROWS, name, ownedPicks(year));
    expect(hits[0].name).toBe(name);
    expect(hits[0].assetId).toBeUndefined();
  });

  it("searching the year lists Early/Mid/Late 1st first, with no owned picks at all", () => {
    // [20] the selected team owns nothing
    const names = searchCalculatorAssets(ROWS, String(year), []).map((r) => r.name);
    expect(names.slice(0, 3)).toEqual(TIERS.map((t) => `${year} ${t} 1st`));
    expect(names).toContain(`${year} Early 2nd`);
  });

  it("[19] each tier's value is the board row's canonical rankDerivedValue", () => {
    for (const tier of TIERS) {
      const hit = searchCalculatorAssets(ROWS, `${year} ${tier} 1st`, [])[0];
      const contractRow = contract().playersArray.find((r) => r.displayName === hit.name);
      expect(hit.rankDerivedValue).toBe(contractRow.rankDerivedValue);
      expect(hit.values.full).toBe(contractRow.rankDerivedValue);
      // Added to a side, the copy carries the same value — no frontend arithmetic.
      expect(sideTotal(addAssetToSide([], hit), "full")).toBe(contractRow.rankDerivedValue);
    }
  });

  it("[21] owned and market picks coexist, and both are addable", () => {
    const hits = searchCalculatorAssets(ROWS, String(year), ownedPicks(year));
    expect(hits.some((r) => r.assetId)).toBe(true);
    expect(hits.some((r) => !r.assetId && r.name === `${year} Mid 1st`)).toBe(true);
    const owned = hits.find((r) => r.assetId);
    const market = hits.find((r) => r.name === `${year} Mid 1st` && !r.assetId);
    const side = addAssetToSide(addAssetToSide([], owned), market);
    expect(side.map(tradeEntryKey)).toEqual([owned.assetId, `${year} Mid 1st`]);
  });

  it("[22] six owned picks cannot crowd the market tiers out of the first results", () => {
    const hits = searchCalculatorAssets(ROWS, String(year), ownedPicks(year));
    expect(hits.slice(0, 3).map((r) => r.name)).toEqual(TIERS.map((t) => `${year} ${t} 1st`));
    const groups = groupTradeSearchResults(hits);
    expect(groups.map((g) => [g.key, g.label])).toEqual([
      ["market", "Market picks"],
      ["owned", "Owned picks"],
    ]);
    expect(groups[0].entries.slice(0, 3).map((r) => r.name)).toEqual(
      TIERS.map((t) => `${year} ${t} 1st`),
    );
    expect(groups[1].entries.every((r) => r.assetId)).toBe(true);
    // Owned picks keep their own label (no Mid mapping in the display).
    expect(groups[1].entries[0].assetLabel).toBe(`${year} 1st (own)`);
  });

  it("an owned pick already in the trade is still offered (ownership displayed, not enforced)", () => {
    const owned = ownedPicks(year);
    const hits = searchCalculatorAssets(ROWS, `${year} 1st (own)`, owned);
    expect(hits.some((r) => r.assetId === owned[0].assetId)).toBe(true);
  });
});

describe("relevance and eligibility", () => {
  it("exact query beats looser matches", () => {
    const hits = searchTradeAssets(ROWS, "2027 Late 1st", null, 8);
    expect(hits.map((r) => r.name)).toEqual(["2027 Late 1st"]);
  });

  it("word matching finds every tier for '2027 1st' without outranking contiguous matches", () => {
    const names = searchTradeAssets(ROWS, "2027 1st", null, 8).map((r) => r.name);
    expect(names).toEqual(TIERS.map((t) => `${2027} ${t} 1st`));
  });

  it("a suppressed generic tier stays excluded while unsuppressed tiers appear", () => {
    const names = searchTradeAssets(ROWS, "Mid 1st", null, 8).map((r) => r.name);
    expect(names).toContain("2027 Mid 1st");
    expect(names).toContain("2028 Mid 1st");
    expect(names).not.toContain("2026 Mid 1st");
    expect(searchTradeAssets(ROWS, "2026", null, 8).map((r) => r.name)).toEqual(["2026 Pick 1.06"]);
  });

  it("[5] a search result is still offered after its first add", () => {
    const first = searchCalculatorAssets(ROWS, "Jefferson", [])[0];
    const side = addAssetToSide([], first);
    expect(searchCalculatorAssets(ROWS, "Jefferson", [])[0].name).toBe("Justin Jefferson");
    expect(addAssetToSide(side, first)).toHaveLength(2);
  });

  it("market and owned groups have separate limits", () => {
    const hits = searchCalculatorAssets(ROWS, "2027", ownedPicks(2027), {
      boardLimit: 3,
      ownedLimit: 2,
    });
    expect(hits.filter((r) => !r.assetId)).toHaveLength(3);
    expect(hits.filter((r) => r.assetId)).toHaveLength(2);
  });

  it("a plain player search renders one unlabelled group", () => {
    const groups = groupTradeSearchResults(searchCalculatorAssets(ROWS, "Jefferson", ownedPicks(2027)));
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBeNull();
  });
});
