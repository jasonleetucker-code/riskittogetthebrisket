/**
 * Trade Calculator asset quantity and identity.
 *
 * OWNER DECISION 2026-10-03 (supersedes T-NEW-02 / #1415's uniqueness rule
 * for the calculator): every selectable asset — player, generic
 * Early/Mid/Late pick, exact slot pick, owned league pick — may be added any
 * number of times, to either or both sides, with no quantity cap.  Trade
 * Calculator assets are hypothetical quantities, not inventory-enforced
 * unique objects; real uniqueness remains in ownership records, transaction
 * history, pick identity and roster-aware recommendations.
 *
 * What this file pins:
 *   * manual construction never refuses a copy (players, generic picks,
 *     owned picks, the same asset on both sides);
 *   * removal takes exactly one copy;
 *   * every consumer counts copies — raw total, Value Adjustment, flows,
 *     CSV/JSON export, localStorage, share links — and every round trip
 *     preserves exact counts (Jefferson x4 + 2027 Mid 1st x6 + owned x8);
 *   * owned-pick IDENTITY still distinguishes two same-label picks for
 *     display and routing;
 *   * the roster-aware equalizer still reads real inventory through its
 *     own, separately named functions — it never claims a team holds four
 *     Jeffersons.
 */

import { describe, expect, it } from "vitest";
import {
  canAddEntry,
  countEntries,
  deserializeEntry,
  groupSideEntries,
  heldAssetKeysInTrade,
  isRepeatableEntry,
  ownedPickEntry,
  removeOneEntry,
  searchPickEntries,
  serializeEntry,
  teamPickEntries,
  tradeEntryKey,
  unusedTeamPickEntries,
} from "../lib/trade-assets.js";
import {
  addAssetToSide,
  computeSideFlowAssets,
  computeSideFlows,
  deserializeWorkspaceMulti,
  filterPickerRows,
  findBalancers,
  ktcAdjustPackage,
  MAX_SIDES,
  removeAssetFromSide,
  serializeWorkspaceMulti,
  sideTotal,
  tradeGapAdjusted,
  tradeImbalance,
  tradeWorkspaceToCSV,
  tradeWorkspaceToJSON,
} from "../lib/trade-logic.js";
import {
  SHARE_MAX_LINES_PER_SIDE,
  SHARE_MAX_SIDES,
  SHARE_MAX_TOTAL_COPIES,
  SHARE_TRUNCATION,
  decodeTrade,
  encodeTrade,
  shareLinkLimits,
} from "../lib/trade-share.js";
import { tradeRequestForTeam } from "../lib/trade-war-room.js";

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
const JEFFERSON = {
  name: "Justin Jefferson",
  pos: "WR",
  assetClass: "offense",
  values: { full: 7000 },
  rankDerivedValue: 7000,
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
const rowByName = new Map([MID_1ST, CHASE, ALLEN, JEFFERSON].map((r) => [r.name, r]));
const side = (assets, extra = {}) => ({ label: "A", assets, destinations: {}, ...extra });
const copies = (row, n) => Array.from({ length: n }, () => row);
/** base64url of a hand-written (possibly hostile) share payload. */
const rawLink = (json) =>
  btoa(unescape(encodeURIComponent(json))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

/** Add ``row`` ``n`` times through the real calculator add path. */
function addTimes(assets, row, n) {
  let out = assets;
  for (let i = 0; i < n; i += 1) out = addAssetToSide(out, row);
  return out;
}

/** The headline mixed trade from the owner decision. */
const BIG = [
  side([...copies(JEFFERSON, 4), ...copies(MID_1ST, 6), ...copies(OWN, 8)]),
  side([...copies(JEFFERSON, 1), CHASE], { label: "B" }),
];
const keyCounts = (assets) => {
  const m = {};
  for (const a of assets) m[tradeEntryKey(a)] = (m[tradeEntryKey(a)] || 0) + 1;
  return m;
};
const BIG_A_COUNTS = { "Justin Jefferson": 4, "2027 Mid 1st": 6, [OWN_ID]: 8 };
const BIG_B_COUNTS = { "Justin Jefferson": 1, "Ja'Marr Chase": 1 };

describe("identity classification", () => {
  it("every valid entry is repeatable — players, generic picks and owned picks", () => {
    expect(isRepeatableEntry(MID_1ST)).toBe(true);
    expect(isRepeatableEntry(CHASE)).toBe(true);
    expect(isRepeatableEntry(OWN)).toBe(true);
    expect(isRepeatableEntry(null)).toBe(false);
  });
  it("two owned picks sharing a label keep distinct identities (display + routing)", () => {
    expect(OWN.name).toBe(FROM.name);
    expect(tradeEntryKey(OWN)).not.toBe(tradeEntryKey(FROM));
    expect(tradeEntryKey(OWN)).toBe(OWN_ID);
  });
  it("a pickDetail without an assetId keeps the board row identity", () => {
    const e = ownedPickEntry(MID_1ST, { label: "2027 Mid 1st (own)" });
    expect(e.assetId).toBeUndefined();
    expect(tradeEntryKey(e)).toBe("2027 Mid 1st");
  });
});

describe("manual construction is unlimited", () => {
  it.each([1, 2, 3, 4, 10])("[1] a player can be added %i times", (n) => {
    const a = addTimes([], JEFFERSON, n);
    expect(a).toHaveLength(n);
    expect(countEntries(a, "Justin Jefferson")).toBe(n);
  });
  it("[2] a generic pick can be added x10", () => {
    expect(addTimes([], MID_1ST, 10)).toHaveLength(10);
  });
  it("[3] an owned pick can be added x10", () => {
    const a = addTimes([], OWN, 10);
    expect(a).toHaveLength(10);
    expect(a.every((e) => e.assetId === OWN_ID)).toBe(true);
  });
  it("[4] the same asset can sit on both sides", () => {
    const sides = [side([JEFFERSON, OWN]), side([], { label: "B" })];
    expect(canAddEntry(sides, JEFFERSON)).toBe(true);
    expect(canAddEntry(sides, OWN)).toBe(true);
    expect(addAssetToSide(sides[1].assets, JEFFERSON)).toHaveLength(1);
  });
  it("canAddEntry refuses only an invalid row", () => {
    expect(canAddEntry([side(copies(CHASE, 50))], CHASE)).toBe(true);
    expect(canAddEntry([], null)).toBe(false);
    expect(canAddEntry([], { name: "" })).toBe(false);
  });
  it("distinct owned picks with the same label coexist", () => {
    expect(addAssetToSide([OWN], FROM)).toHaveLength(2);
  });
  it("[5] the picker keeps an asset pickable after its first add", () => {
    const rows = [MID_1ST, CHASE, ALLEN];
    const names = filterPickerRows(rows, [MID_1ST, CHASE], [CHASE], "", "all").map((r) => r.name);
    expect(names).toEqual(["2027 Mid 1st", "Ja'Marr Chase", "Josh Allen"]);
  });
});

describe("remove one copy", () => {
  it("[7] removing takes exactly one copy, for any asset kind", () => {
    const after = removeOneEntry([MID_1ST, CHASE, MID_1ST, CHASE], "Ja'Marr Chase");
    expect(countEntries(after, "Ja'Marr Chase")).toBe(1);
    expect(countEntries(after, "2027 Mid 1st")).toBe(2);
    expect(removeAssetFromSide(copies(OWN, 3), OWN_ID)).toHaveLength(2);
  });
  it("[8] at quantity 1, removing one removes the line", () => {
    const after = removeOneEntry([CHASE, MID_1ST], "Ja'Marr Chase");
    expect(groupSideEntries(after).map((g) => g.key)).toEqual(["2027 Mid 1st"]);
  });
  it("removing one owned pick never removes its same-label sibling", () => {
    expect(removeOneEntry([OWN, FROM], FROM_ID)).toEqual([OWN]);
  });
});

describe("grouping for display (the − N + control on every line)", () => {
  it("[6] every asset kind groups into one line whose count grows without limit", () => {
    let a = [];
    for (let i = 1; i <= 25; i += 1) {
      a = addAssetToSide(a, CHASE);
      expect(groupSideEntries(a)).toEqual([{ key: "Ja'Marr Chase", entry: CHASE, count: i }]);
    }
  });
  it("copies group by identity; owned siblings stay separate lines", () => {
    const groups = groupSideEntries([MID_1ST, OWN, MID_1ST, FROM, CHASE, CHASE, OWN]);
    expect(groups.map((g) => [g.key, g.count])).toEqual([
      ["2027 Mid 1st", 2],
      [OWN_ID, 2],
      [FROM_ID, 1],
      ["Ja'Marr Chase", 2],
    ]);
  });
});

describe("math counts every copy", () => {
  it("[9] the raw side total multiplies exactly", () => {
    expect(sideTotal(copies(JEFFERSON, 4), "full")).toBe(4 * 7000);
    expect(sideTotal(BIG[0].assets, "full")).toBe(4 * 7000 + 6 * 5606 + 8 * 5606);
  });
  it("[10] Value Adjustment sees every copy as a piece", () => {
    // Pinned against Python in tests/trade/test_repeated_trade_assets.py.
    expect(ktcAdjustPackage([5606, 5606], [9000])).toEqual({
      value: 4240,
      side: 2,
      displayed: true,
    });
    // A player repeated is a repeated piece too: 2 x Jefferson vs 1 x Chase
    // must equal the VA over the explicit [7000, 7000] package.
    const expected = ktcAdjustPackage([9000], [7000, 7000]);
    const gap = tradeGapAdjusted([CHASE], copies(JEFFERSON, 2), "full");
    const raw = 9000 - 14000;
    const va = expected.side === 1 ? expected.value : -expected.value;
    expect(gap).toBe(raw + va);
  });
  it("two copies reach the adjusted gap as two pieces", () => {
    expect(tradeGapAdjusted([MID_1ST], [CHASE], "full")).toBe(5606 - 9000);
    expect(tradeGapAdjusted([MID_1ST, MID_1ST], [CHASE], "full")).toBe(-2028);
    expect(tradeGapAdjusted([OWN, OWN], [CHASE], "full")).toBe(-2028);
    expect(tradeGapAdjusted([OWN, FROM], [CHASE], "full")).toBe(-2028);
  });
  it("3-team flows route every copy of a line to that line's destination", () => {
    const sides = [
      side([MID_1ST, MID_1ST, OWN, JEFFERSON, JEFFERSON, JEFFERSON], {
        destinations: { "2027 Mid 1st": 2, [OWN_ID]: 1, "Justin Jefferson": 2 },
      }),
      side([CHASE], { label: "B" }),
      side([ALLEN], { label: "C" }),
    ];
    const flows = computeSideFlowAssets(sides);
    expect(flows[2].incoming.filter((x) => x.fromSideIdx === 0)).toHaveLength(5);
    expect(flows[1].incoming.filter((x) => x.fromSideIdx === 0)).toHaveLength(1);
    const raw = computeSideFlows(sides, "full");
    expect(raw[0].given).toBeGreaterThanOrEqual(3 * 5606 + 3 * 7000);
  });
  it("tradeImbalance counts the same asset on both sides on each side", () => {
    const sides = [side(copies(JEFFERSON, 3)), side(copies(JEFFERSON, 3), { label: "B" })];
    expect(tradeImbalance(sides, "full").imbalance).toBe(0);
  });
});

describe("downstream payloads carry every copy", () => {
  it("the War Room / simulator request lists each copy", () => {
    const req = tradeRequestForTeam(
      [side([...copies(JEFFERSON, 3), ...copies(OWN, 2)]), side(copies(MID_1ST, 4), { label: "B" })],
      new Set(["Justin Jefferson"]),
      "Team A",
    );
    expect(req.playersOut).toEqual(copies("Justin Jefferson", 3));
    expect(req.picksOut).toEqual(copies("2027 Mid 1st (own)", 2));
    expect(req.picksIn).toEqual(copies("2027 Mid 1st", 4));
  });
});

describe("roster-aware equalizer still reads real inventory", () => {
  it("heldAssetKeysInTrade names players and owned picks, never market picks", () => {
    const keys = heldAssetKeysInTrade([side([MID_1ST, OWN]), side([CHASE])]);
    expect([...keys].sort()).toEqual([OWN_ID, "Ja'Marr Chase"].sort());
  });
  it("offers a team's second same-label owned pick after the first is in the trade", () => {
    const sides = [side([ALLEN]), side([CHASE, OWN], { label: "B" })];
    expect(unusedTeamPickEntries([OWN, FROM], sides, 1).map(tradeEntryKey)).toEqual([FROM_ID]);
  });
  it("a generic copy on the side consumes one of the team's picks of that row", () => {
    const sides = [side([ALLEN]), side([MID_1ST], { label: "B" })];
    expect(unusedTeamPickEntries([OWN, FROM], sides, 1)).toHaveLength(1);
  });
  it("never suggests a pick the team does not hold, however many copies are in", () => {
    const sides = [side([ALLEN]), side(copies(OWN, 4), { label: "B" })];
    expect(unusedTeamPickEntries([OWN], sides, 1)).toEqual([]);
  });
  it("findBalancers keeps both same-label owned picks as separate candidates", () => {
    const sides = [side([CHASE, ALLEN]), side([MID_1ST], { label: "B" })];
    const out = findBalancers(sides, 1, [OWN, FROM], "full");
    expect(out.map((b) => b.key).sort()).toEqual([FROM_ID, OWN_ID].sort());
    expect(out.map((b) => b.label)).toContain("2027 Mid 1st (from Team X)");
  });
  it("findBalancers scores a repeated pool row once", () => {
    const sides = [side([CHASE, ALLEN]), side([MID_1ST], { label: "B" })];
    expect(findBalancers(sides, 1, [MID_1ST, MID_1ST], "full")).toHaveLength(1);
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
  it("falls back to board-keyed entries when only labels exist", () => {
    const entries = teamPickEntries({ picks: ["2027 Mid 1st (own)", "2027 Mid 1st (from X)"] }, resolve);
    expect(entries).toHaveLength(2);
    expect(entries.every((e) => !e.assetId && tradeEntryKey(e) === "2027 Mid 1st")).toBe(true);
  });
});

describe("serialization round trips preserve exact counts", () => {
  it("[12] localStorage: Jefferson x4 + 2027 Mid 1st x6 + owned x8 come back exactly", () => {
    const payload = JSON.parse(JSON.stringify(serializeWorkspaceMulti(BIG, "full", 0)));
    expect(payload.sides[0].assets).toHaveLength(18);
    const restored = deserializeWorkspaceMulti(payload, rowByName);
    expect(keyCounts(restored.sides[0].assets)).toEqual(BIG_A_COUNTS);
    expect(keyCounts(restored.sides[1].assets)).toEqual(BIG_B_COUNTS);
    expect(restored.sides[0].assets.filter((e) => e.assetId === OWN_ID)).toHaveLength(8);
    expect(sideTotal(restored.sides[0].assets, "full")).toBe(sideTotal(BIG[0].assets, "full"));
  });

  it("a saved workspace keeps quantity and distinct identity, in order", () => {
    const trade = [side([MID_1ST, MID_1ST, OWN, FROM]), side([CHASE], { label: "B" })];
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
  });

  it("an old workspace (bare names only) loads with every duplicate, on both sides", () => {
    const restored = deserializeWorkspaceMulti(
      {
        version: 2,
        valueMode: "full",
        activeSide: 0,
        sides: [
          { label: "A", assets: ["2027 Mid 1st", "2027 Mid 1st", "Josh Allen", "Josh Allen"] },
          { label: "B", assets: ["Josh Allen"] },
        ],
      },
      rowByName,
    );
    expect(restored.sides[0].assets.map((r) => r.name)).toEqual([
      "2027 Mid 1st",
      "2027 Mid 1st",
      "Josh Allen",
      "Josh Allen",
    ]);
    expect(restored.sides[1].assets.map((r) => r.name)).toEqual(["Josh Allen"]);
  });

  it("a payload repeating one owned pick keeps every copy, on both sides", () => {
    const item = serializeEntry(OWN);
    const restored = deserializeWorkspaceMulti(
      { version: 2, sides: [{ assets: [item, item] }, { assets: [item] }] },
      rowByName,
    );
    expect(restored.sides[0].assets).toHaveLength(2);
    expect(restored.sides[1].assets).toHaveLength(1);
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

  const shareOf = (sides) => ({
    sides: sides.map((s) => ({
      name: `Side ${s.label}`,
      players: s.assets.map((a) => a.name),
      assetIds: s.assets.map((a) => a.assetId || null),
    })),
  });

  it("[11] share link: Jefferson x4 + 2027 Mid 1st x6 + owned x8 come back exactly", () => {
    const decoded = decodeTrade(encodeTrade(shareOf(BIG)));
    const back = (s) =>
      s.players.map((name, i) => deserializeEntry(
        s.assetIds[i] ? { name, assetId: s.assetIds[i] } : name,
        rowByName,
      ));
    expect(keyCounts(back(decoded.sides[0]))).toEqual(BIG_A_COUNTS);
    expect(keyCounts(back(decoded.sides[1]))).toEqual(BIG_B_COUNTS);
  });

  it("share link copies collapse into lines, so quantity is not bounded by the 32-line URL cap", () => {
    const decoded = decodeTrade(encodeTrade(shareOf([side(copies(CHASE, 40))])));
    expect(decoded.sides[0].players).toHaveLength(40);
  });

  it("share link keeps copies and owned ids", () => {
    const trade = [side([MID_1ST, MID_1ST, OWN, FROM]), side([CHASE], { label: "B" })];
    const decoded = decodeTrade(encodeTrade(shareOf(trade)));
    expect(decoded.sides[0].players).toEqual(copies("2027 Mid 1st", 4));
    expect(decoded.sides[0].assetIds).toEqual([null, null, OWN_ID, FROM_ID]);
    expect(decoded.sides[1].assetIds).toEqual([null]);
  });

  it("a legacy share link (one item per copy, no ids, no counts) still decodes every copy", () => {
    const legacyJson = JSON.stringify({ v: 1, s: [{ n: "A", p: ["2027 Mid 1st", "2027 Mid 1st"] }] });
    const legacy = btoa(legacyJson).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
    const decoded = decodeTrade(legacy);
    expect(decoded.sides[0].players).toEqual(["2027 Mid 1st", "2027 Mid 1st"]);
    expect(decoded.sides[0].assetIds).toEqual([null, null]);
    expect(decoded.truncated).toBe(false);
    expect(decoded.truncationReasons).toEqual([]);
  });

  it("a full-size legacy link (32 items per side, the old encoder's cap) decodes identically", () => {
    const names = Array.from({ length: 32 }, (_, i) => (i % 2 ? "Josh Allen" : "2027 Mid 1st"));
    const legacyJson = JSON.stringify({ v: 1, s: [{ n: "A", p: names }, { n: "B", p: names }] });
    const decoded = decodeTrade(rawLink(legacyJson));
    expect(decoded.sides.map((x) => x.players)).toEqual([names, names]);
    expect(decoded.truncated).toBe(false);
  });

  describe("untrusted-link bounds (decode side; manual entry stays uncapped)", () => {
    it("pins the bounds to the encoder cap and the calculator's MAX_SIDES", () => {
      expect(SHARE_MAX_SIDES).toBe(MAX_SIDES);
      const many = Array.from({ length: 40 }, (_, i) => `Player ${i}`);
      const enc = decodeTrade(encodeTrade({ sides: [{ name: "A", players: many }] }));
      expect(enc.sides[0].players).toHaveLength(SHARE_MAX_LINES_PER_SIDE);
      expect(SHARE_MAX_TOTAL_COPIES).toBe(10000);
    });

    it("many lines: 5,000 lines x q 999 is cut to 32 lines and the 10,000-copy budget, and says so", () => {
      const p = Array.from({ length: 5000 }, (_, i) => `Player ${i}`);
      const q = p.map(() => 999);
      const decoded = decodeTrade(rawLink(JSON.stringify({ v: 1, s: [{ n: "A", p, q }] })));
      expect(decoded.sides[0].players).toHaveLength(SHARE_MAX_TOTAL_COPIES);
      expect(new Set(decoded.sides[0].players).size).toBeLessThanOrEqual(SHARE_MAX_LINES_PER_SIDE);
      expect(decoded.truncated).toBe(true);
      expect(decoded.truncationReasons).toEqual(
        expect.arrayContaining([SHARE_TRUNCATION.TOO_MANY_LINES, SHARE_TRUNCATION.COPY_BUDGET]),
      );
    });

    it("many lines alone (no counts): 33+ lines keep the first 32 and report too_many_lines", () => {
      const p = Array.from({ length: 100 }, (_, i) => `Player ${i}`);
      const decoded = decodeTrade(rawLink(JSON.stringify({ v: 1, s: [{ n: "A", p }] })));
      expect(decoded.sides[0].players).toEqual(p.slice(0, 32));
      expect(decoded.truncationReasons).toEqual([SHARE_TRUNCATION.TOO_MANY_LINES]);
    });

    it("the total-copies budget spans ALL sides", () => {
      const sideOf = (n) => ({ n, p: ["Josh Allen", "Ja'Marr Chase"], q: [3000, 3000] });
      const decoded = decodeTrade(
        rawLink(JSON.stringify({ v: 1, s: [sideOf("A"), sideOf("B")] })),
      );
      const total = decoded.sides.reduce((n, x) => n + x.players.length, 0);
      expect(total).toBe(SHARE_MAX_TOTAL_COPIES);
      expect(decoded.sides[0].players).toHaveLength(6000);
      expect(decoded.sides[1].players).toHaveLength(4000);
      expect(decoded.truncationReasons).toEqual([SHARE_TRUNCATION.COPY_BUDGET]);
    });

    it("exactly the budget is not truncated", () => {
      const decoded = decodeTrade(
        rawLink(JSON.stringify({ v: 1, s: [{ n: "A", p: ["Josh Allen"], q: [SHARE_MAX_TOTAL_COPIES] }] })),
      );
      expect(decoded.sides[0].players).toHaveLength(SHARE_MAX_TOTAL_COPIES);
      expect(decoded.truncated).toBe(false);
    });

    it("sides past MAX_SIDES are dropped and reported", () => {
      const s = Array.from({ length: 9 }, (_, i) => ({ n: `S${i}`, p: ["Josh Allen"] }));
      const decoded = decodeTrade(rawLink(JSON.stringify({ v: 1, s })));
      expect(decoded.sides).toHaveLength(SHARE_MAX_SIDES);
      expect(decoded.truncationReasons).toEqual([SHARE_TRUNCATION.TOO_MANY_SIDES]);
    });

    it("shareLinkLimits warns the SENDER before a link drops anything", () => {
      expect(shareLinkLimits(shareOf(BIG))).toEqual({ complete: true, reasons: [] });
      const distinct = Array.from({ length: 33 }, (_, i) => `Player ${i}`);
      expect(shareLinkLimits({ sides: [{ players: distinct }] }).reasons).toEqual([
        SHARE_TRUNCATION.TOO_MANY_LINES,
      ]);
      const heavy = { sides: [{ players: Array(SHARE_MAX_TOTAL_COPIES + 1).fill("Josh Allen") }] };
      expect(shareLinkLimits(heavy).reasons).toEqual([SHARE_TRUNCATION.COPY_BUDGET]);
      const wide = { sides: Array.from({ length: 6 }, () => ({ players: ["Josh Allen"] })) };
      expect(shareLinkLimits(wide).reasons).toEqual([SHARE_TRUNCATION.TOO_MANY_SIDES]);
    });

    it("manual construction and localStorage stay uncapped (the bounds are link-only)", () => {
      const huge = addTimes([], CHASE, SHARE_MAX_TOTAL_COPIES + 5);
      expect(huge).toHaveLength(SHARE_MAX_TOTAL_COPIES + 5);
      const payload = JSON.parse(JSON.stringify(serializeWorkspaceMulti([side(huge), side([], { label: "B" })], "full", 0)));
      const restored = deserializeWorkspaceMulti(payload, rowByName);
      expect(restored.sides[0].assets).toHaveLength(SHARE_MAX_TOTAL_COPIES + 5);
    });
  });

  it("a side without owned picks or repeats encodes without either additive field", () => {
    const encoded = encodeTrade({ sides: [{ name: "A", players: ["Josh Allen"], assetIds: [null] }] });
    const json = JSON.parse(
      decodeURIComponent(
        escape(atob(encoded.replace(/-/g, "+").replace(/_/g, "/") + "==".slice(0, (4 - (encoded.length % 4)) % 4))),
      ),
    );
    expect(json.s[0].a).toBeUndefined();
    expect(json.s[0].q).toBeUndefined();
  });

  it("[13] CSV export writes one line per copy and each owned pick's id", () => {
    const lines = tradeWorkspaceToCSV(BIG, "full", "Market consensus").trim().split("\n");
    expect(lines).toHaveLength(1 + 18 + 2);
    expect(lines.filter((l) => l.startsWith("A,Justin Jefferson,"))).toHaveLength(4);
    expect(lines.filter((l) => l.startsWith("A,2027 Mid 1st,") && l.endsWith(",")).length).toBe(6);
    expect(lines.filter((l) => l.endsWith(`,${OWN_ID}`))).toHaveLength(8);
    expect(lines.filter((l) => l.startsWith("B,Justin Jefferson,"))).toHaveLength(1);
  });

  it("[13] JSON export keeps every copy and restores exactly", () => {
    const parsed = JSON.parse(tradeWorkspaceToJSON(BIG, "full", 0));
    expect(parsed.sides[0].assets).toHaveLength(18);
    const restored = deserializeWorkspaceMulti(parsed, rowByName);
    expect(keyCounts(restored.sides[0].assets)).toEqual(BIG_A_COUNTS);
  });

  it("deserializeEntry refuses rows the board no longer has", () => {
    expect(deserializeEntry("Nobody", rowByName)).toBeNull();
    expect(deserializeEntry({ name: "Nobody", assetId: OWN_ID }, rowByName)).toBeNull();
  });
});
