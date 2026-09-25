/**
 * T-NEW-02 / #1415 (scope row C3-CALC-01) — trade asset identity and quantity.
 *
 * Acceptance examples from the owner requirement:
 *   1. Side A can contain two "2027 Mid 1st" generic assets and their value
 *      contributes twice.
 *   2. Side A can contain two DIFFERENT real 2027 firsts even if both
 *      display "2027 Mid 1st".
 *   3. The exact same unique owned pick cannot be duplicated.
 *   4. Deleting one of two generic copies leaves the other.
 *   5. Share / persistence / export round-trips restore both copies.
 */

import { describe, expect, it } from "vitest";
import {
  availableTeamPickEntries,
  canAddEntry,
  countEntries,
  dedupeUniqueAcrossSides,
  deserializeEntry,
  groupSideEntries,
  isRepeatableEntry,
  ownedPickEntry,
  removeOneEntry,
  searchPickEntries,
  serializeEntry,
  teamPickEntries,
  tradeEntryKey,
  uniqueKeysInTrade,
} from "../lib/trade-assets.js";
import {
  addAssetToSide,
  computeSideFlowAssets,
  computeSideFlows,
  deserializeWorkspaceMulti,
  filterPickerRows,
  findBalancers,
  ktcAdjustPackage,
  removeAssetFromSide,
  serializeWorkspaceMulti,
  sideTotal,
  tradeGapAdjusted,
  tradeImbalance,
  tradeWorkspaceToCSV,
} from "../lib/trade-logic.js";
import { decodeTrade, encodeTrade } from "../lib/trade-share.js";

const MID_1ST = {
  name: "2027 Mid 1st",
  pos: "PICK",
  assetClass: "pick",
  values: { full: 5606 },
  rankDerivedValue: 5606,
};
const CHASE = {
  name: "Ja'Marr Chase",
  pos: "WR",
  assetClass: "offense",
  values: { full: 9000 },
  rankDerivedValue: 9000,
};
const ALLEN = {
  name: "Josh Allen",
  pos: "QB",
  assetClass: "offense",
  values: { full: 8000 },
  rankDerivedValue: 8000,
};
const OWN_ID = "pick:dynasty_main:2027:r1:o4";
const FROM_ID = "pick:dynasty_main:2027:r1:o9";
const OWN = ownedPickEntry(MID_1ST, { assetId: OWN_ID, label: "2027 Mid 1st (own)" });
const FROM = ownedPickEntry(MID_1ST, {
  assetId: FROM_ID,
  label: "2027 Mid 1st (from Team X)",
});
const rowByName = new Map([MID_1ST, CHASE, ALLEN].map((r) => [r.name, r]));
const side = (assets, extra = {}) => ({ label: "A", assets, destinations: {}, ...extra });

describe("identity classification", () => {
  it("a board pick row without an owned id is repeatable", () => {
    expect(isRepeatableEntry(MID_1ST)).toBe(true);
  });
  it("players and owned picks are unique — asset type alone does not decide", () => {
    expect(isRepeatableEntry(CHASE)).toBe(false);
    expect(isRepeatableEntry(OWN)).toBe(false);
  });
  it("two owned picks sharing a label have distinct identities", () => {
    expect(OWN.name).toBe(FROM.name);
    expect(tradeEntryKey(OWN)).not.toBe(tradeEntryKey(FROM));
    expect(tradeEntryKey(OWN)).toBe(OWN_ID);
  });
  it("a pickDetail without an assetId cannot claim uniqueness", () => {
    const e = ownedPickEntry(MID_1ST, { label: "2027 Mid 1st (own)" });
    expect(e.assetId).toBeUndefined();
    expect(isRepeatableEntry(e)).toBe(true);
  });
});

describe("add / remove", () => {
  it("[1] a generic pick may be added twice and both copies count", () => {
    let a = addAssetToSide([], MID_1ST);
    a = addAssetToSide(a, MID_1ST);
    expect(a).toHaveLength(2);
    expect(sideTotal(a, "full")).toBe(2 * 5606);
  });
  it("[2] distinct owned picks with the same label coexist", () => {
    const sides = [side([OWN]), side([])];
    expect(canAddEntry(sides, FROM)).toBe(true);
    expect(addAssetToSide([OWN], FROM)).toHaveLength(2);
  });
  it("[3] the same owned pick cannot be added twice, on either side", () => {
    expect(canAddEntry([side([OWN]), side([])], OWN)).toBe(false);
    expect(canAddEntry([side([]), side([OWN])], { ...OWN })).toBe(false);
    expect(addAssetToSide([OWN], OWN)).toHaveLength(1);
  });
  it("a player cannot be added twice", () => {
    expect(canAddEntry([side([CHASE]), side([])], CHASE)).toBe(false);
  });
  it("[4] removing one generic copy leaves the other", () => {
    const after = removeOneEntry([MID_1ST, CHASE, MID_1ST], "2027 Mid 1st");
    expect(countEntries(after, "2027 Mid 1st")).toBe(1);
    expect(after.map((r) => r.name)).toEqual(["2027 Mid 1st", "Ja'Marr Chase"]);
    expect(removeAssetFromSide([MID_1ST, MID_1ST], "2027 Mid 1st")).toHaveLength(1);
  });
  it("removing one owned pick never removes its same-label sibling", () => {
    const after = removeOneEntry([OWN, FROM], FROM_ID);
    expect(after).toEqual([OWN]);
  });
  it("uniqueness keys cover players and owned picks only", () => {
    const keys = uniqueKeysInTrade([side([MID_1ST, OWN]), side([CHASE])]);
    expect([...keys].sort()).toEqual([OWN_ID, "Ja'Marr Chase"].sort());
  });
});

describe("grouping for display (the − N + control)", () => {
  it("copies group into one line with a count; owned siblings stay separate lines", () => {
    const groups = groupSideEntries([MID_1ST, OWN, MID_1ST, FROM, CHASE]);
    expect(groups.map((g) => [g.key, g.count, g.repeatable])).toEqual([
      ["2027 Mid 1st", 2, true],
      [OWN_ID, 1, false],
      [FROM_ID, 1, false],
      ["Ja'Marr Chase", 1, false],
    ]);
  });
});

describe("math counts every copy", () => {
  it("VA parity with repeated values (pinned against Python in tests/trade/test_repeated_trade_assets.py)", () => {
    expect(ktcAdjustPackage([5606, 5606], [9000])).toEqual({
      value: 4240,
      side: 2,
      displayed: true,
    });
    expect(ktcAdjustPackage([5606, 5606, 5606], [9000, 3000])).toEqual({
      value: 3339,
      side: 2,
      displayed: true,
    });
    expect(ktcAdjustPackage([4000, 4000, 2500], [7000, 3500]).value).toBe(3759);
  });
  it("two generic copies reach the adjusted gap as two pieces", () => {
    const one = tradeGapAdjusted([MID_1ST], [CHASE], "full");
    const two = tradeGapAdjusted([MID_1ST, MID_1ST], [CHASE], "full");
    expect(one).toBe(5606 - 9000);
    expect(two).toBe(-2028);
  });
  it("two owned picks with the same label are two pieces too", () => {
    expect(tradeGapAdjusted([OWN, FROM], [CHASE], "full")).toBe(-2028);
  });
  it("3-team flows route each line by identity and count every copy", () => {
    const sides = [
      side([MID_1ST, MID_1ST, OWN], { destinations: { "2027 Mid 1st": 2, [OWN_ID]: 1 } }),
      side([CHASE], { label: "B" }),
      side([ALLEN], { label: "C" }),
    ];
    const flows = computeSideFlowAssets(sides);
    expect(flows[2].incoming.filter((x) => x.fromSideIdx === 0)).toHaveLength(2);
    expect(flows[1].incoming.filter((x) => x.fromSideIdx === 0)).toHaveLength(1);
    const raw = computeSideFlows(sides, "full");
    expect(raw[0].given).toBeGreaterThanOrEqual(3 * 5606);
  });
});

describe("equalizer candidates", () => {
  it("offers a team's second same-label owned pick after the first is in the trade", () => {
    const sides = [side([ALLEN]), side([CHASE, OWN], { label: "B" })];
    const pool = availableTeamPickEntries([OWN, FROM], sides, 1);
    expect(pool.map(tradeEntryKey)).toEqual([FROM_ID]);
  });
  it("a generic copy on the side consumes one of the team's picks of that row", () => {
    const sides = [side([ALLEN]), side([MID_1ST], { label: "B" })];
    expect(availableTeamPickEntries([OWN, FROM], sides, 1)).toHaveLength(1);
  });
  it("findBalancers keeps both same-label owned picks as separate candidates", () => {
    const sides = [side([CHASE, ALLEN]), side([MID_1ST], { label: "B" })];
    const out = findBalancers(sides, 1, [OWN, FROM], "full");
    expect(out.map((b) => b.key).sort()).toEqual([FROM_ID, OWN_ID].sort());
    expect(out[0].entry.assetId).toBeTruthy();
    expect(out.map((b) => b.label)).toContain("2027 Mid 1st (from Team X)");
  });
  it("findBalancers scores a repeated generic row once, even when already in the trade", () => {
    const sides = [side([CHASE, ALLEN]), side([MID_1ST], { label: "B" })];
    const out = findBalancers(sides, 1, [MID_1ST, MID_1ST], "full");
    expect(out).toHaveLength(1);
    expect(out[0].imbalanceAfter).toBe(
      tradeImbalance(
        [sides[0], side([MID_1ST, MID_1ST], { label: "B" })],
        "full",
      ).imbalance,
    );
  });
  it("the picker only hides unique identities already in the trade", () => {
    const rows = [MID_1ST, CHASE, ALLEN];
    const names = filterPickerRows(rows, [MID_1ST, CHASE], [], "", "all").map((r) => r.name);
    expect(names).toEqual(["2027 Mid 1st", "Josh Allen"]);
  });
});

describe("team pick entries", () => {
  const resolve = (label) => (String(label).startsWith("2027 Mid 1st") ? MID_1ST : null);
  it("builds owned entries from pickDetails, keeping each canonical id", () => {
    const team = {
      pickDetails: [
        { label: "2027 Mid 1st (own)", assetId: OWN_ID },
        { label: "2027 Mid 1st (from Team X)", assetId: FROM_ID },
      ],
    };
    const entries = teamPickEntries(team, resolve);
    expect(entries.map(tradeEntryKey)).toEqual([OWN_ID, FROM_ID]);
    expect(searchPickEntries(entries, "from team x").map(tradeEntryKey)).toEqual([FROM_ID]);
  });
  it("falls back to repeatable entries when only labels exist", () => {
    const entries = teamPickEntries({ picks: ["2027 Mid 1st (own)", "2027 Mid 1st (from X)"] }, resolve);
    expect(entries).toHaveLength(2);
    expect(entries.every(isRepeatableEntry)).toBe(true);
  });
});

describe("[5] serialization round trips", () => {
  const trade = [
    side([MID_1ST, MID_1ST, OWN, FROM]),
    side([CHASE], { label: "B" }),
  ];

  it("localStorage workspace keeps quantity and distinct identity", () => {
    const payload = JSON.parse(JSON.stringify(serializeWorkspaceMulti(trade, "full", 0)));
    expect(payload.sides[0].assets).toEqual([
      "2027 Mid 1st",
      "2027 Mid 1st",
      { name: "2027 Mid 1st", assetId: OWN_ID, label: "2027 Mid 1st (own)" },
      { name: "2027 Mid 1st", assetId: FROM_ID, label: "2027 Mid 1st (from Team X)" },
    ]);
    const restored = deserializeWorkspaceMulti(payload, rowByName);
    expect(restored.sides[0].assets.map(tradeEntryKey)).toEqual([
      "2027 Mid 1st",
      "2027 Mid 1st",
      OWN_ID,
      FROM_ID,
    ]);
    expect(sideTotal(restored.sides[0].assets, "full")).toBe(4 * 5606);
  });

  it("an old workspace (bare names only) still loads, and its pick duplicates survive", () => {
    const restored = deserializeWorkspaceMulti(
      {
        version: 2,
        valueMode: "full",
        activeSide: 0,
        sides: [
          { label: "A", assets: ["2027 Mid 1st", "2027 Mid 1st", "Josh Allen"], destinations: {} },
          { label: "B", assets: ["Josh Allen"], destinations: {} },
        ],
      },
      rowByName,
    );
    expect(restored.sides[0].assets.map((r) => r.name)).toEqual([
      "2027 Mid 1st",
      "2027 Mid 1st",
      "Josh Allen",
    ]);
    // A player saved on both sides (corrupt payload) keeps its first copy only.
    expect(restored.sides[1].assets).toEqual([]);
  });

  it("a payload repeating one owned pick keeps it once", () => {
    const item = serializeEntry(OWN);
    const restored = deserializeWorkspaceMulti(
      { version: 2, sides: [{ assets: [item, item] }, { assets: [item] }] },
      rowByName,
    );
    expect(restored.sides[0].assets).toHaveLength(1);
    expect(restored.sides[1].assets).toHaveLength(0);
  });

  it("3-team destinations persist per line identity", () => {
    const three = [
      side([MID_1ST, MID_1ST, OWN], { destinations: { "2027 Mid 1st": 2, [OWN_ID]: 1 } }),
      side([CHASE], { label: "B" }),
      side([ALLEN], { label: "C" }),
    ];
    const payload = JSON.parse(JSON.stringify(serializeWorkspaceMulti(three, "full", 0)));
    expect(payload.sides[0].destinations).toEqual({ "2027 Mid 1st": 2, [OWN_ID]: 1 });
    const restored = deserializeWorkspaceMulti(payload, rowByName);
    expect(restored.sides[0].destinations).toEqual({ "2027 Mid 1st": 2, [OWN_ID]: 1 });
  });

  it("share link keeps copies and owned ids", () => {
    const decoded = decodeTrade(
      encodeTrade({
        sides: trade.map((s) => ({
          name: `Side ${s.label}`,
          players: s.assets.map((a) => a.name),
          assetIds: s.assets.map((a) => a.assetId || null),
        })),
      }),
    );
    expect(decoded.sides[0].players).toEqual([
      "2027 Mid 1st",
      "2027 Mid 1st",
      "2027 Mid 1st",
      "2027 Mid 1st",
    ]);
    expect(decoded.sides[0].assetIds).toEqual([null, null, OWN_ID, FROM_ID]);
    expect(decoded.sides[1].assetIds).toEqual([null]);
  });

  it("a legacy share link (no ids) decodes with null ids for every name", () => {
    const legacy = encodeTrade({ sides: [{ name: "A", players: ["2027 Mid 1st", "2027 Mid 1st"] }] });
    const decoded = decodeTrade(legacy);
    expect(decoded.sides[0].players).toEqual(["2027 Mid 1st", "2027 Mid 1st"]);
    expect(decoded.sides[0].assetIds).toEqual([null, null]);
  });

  it("a side without owned picks encodes without the additive field", () => {
    const encoded = encodeTrade({ sides: [{ name: "A", players: ["Josh Allen"], assetIds: [null] }] });
    const json = JSON.parse(
      decodeURIComponent(
        escape(atob(encoded.replace(/-/g, "+").replace(/_/g, "/") + "==".slice(0, (4 - (encoded.length % 4)) % 4))),
      ),
    );
    expect(json.s[0].a).toBeUndefined();
  });

  it("CSV export writes one line per copy and each owned pick's id", () => {
    const lines = tradeWorkspaceToCSV(trade, "full", "Market consensus").trim().split("\n");
    expect(lines).toHaveLength(1 + 5);
    expect(lines.filter((l) => l.startsWith("A,2027 Mid 1st"))).toHaveLength(4);
    expect(lines.some((l) => l.endsWith(`,${OWN_ID}`))).toBe(true);
    expect(lines.some((l) => l.endsWith(`,${FROM_ID}`))).toBe(true);
  });

  it("deserializeEntry refuses rows the board no longer has", () => {
    expect(deserializeEntry("Nobody", rowByName)).toBeNull();
    expect(deserializeEntry({ name: "Nobody", assetId: OWN_ID }, rowByName)).toBeNull();
  });

  it("dedupeUniqueAcrossSides keeps every generic copy", () => {
    const [a, b] = dedupeUniqueAcrossSides([[MID_1ST, CHASE], [MID_1ST, CHASE]]);
    expect(a.map((r) => r.name)).toEqual(["2027 Mid 1st", "Ja'Marr Chase"]);
    expect(b.map((r) => r.name)).toEqual(["2027 Mid 1st"]);
  });
});
