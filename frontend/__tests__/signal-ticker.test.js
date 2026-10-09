// C6-SIG-02 — the homepage ticker's presentation rules over the C6-SIG-01
// reconciler payload.  Payload shapes mirror src/signals/reconciler.py's
// `reconcile()` output plus collect.py's `roster` / per-player `board`.
import { describe, it, expect } from "vitest";
import {
  SELL_SCOPE,
  lineageText,
  selectTickerVerdicts,
  sellScopeText,
  unobservedEmitters,
} from "@/lib/signal-ticker";

function sig(emitter, domain, direction, lineageGroup = `${emitter}_lineage`) {
  return { emitter, domain, direction, lineageGroup, ancestors: [], nativeLabel: direction };
}

function player(key, name, state, { signals = [], agreement, conflict = null, rank = 10, assetClass = "offense", pos = "WR" } = {}) {
  return {
    playerKey: key,
    displayName: name,
    state,
    withheldBy: state === "withheld" ? [{ source: "canonical_quarantine", reason: "x" }] : [],
    signals,
    collapsed: [],
    conflict,
    agreement: agreement || { buy: null, sell: null },
    board: { canonicalConsensusRank: rank, position: pos, assetClass },
  };
}

const TEAM = { ownerId: "owner-1", name: "Alpha Team" };

function payload(players, { team = TEAM, rosterKeys = ["player:1", "player:2", "player:5", "player:9"] } = {}) {
  return {
    players,
    team,
    teamResolution: { requested: team ? { ownerId: team.ownerId } : null, resolved: !!team, source: "explicit", reason: null },
    roster: team ? { playerKeys: rosterKeys, placement: "player_id", unresolvedCount: 0 } : null,
    emitters: [],
  };
}

const BUY_ON_ROSTER = player("player:1", "Rostered Buy", "directional_buy_only", {
  signals: [sig("bdvm_market_signal", "fundamental", "buy")],
  rank: 30,
});
const SELL_ON_ROSTER = player("player:2", "Rostered Sell", "directional_sell_only", {
  signals: [sig("consensus_edge", "consensus", "sell")],
  rank: 12,
});
const BUY_ELSEWHERE = player("player:3", "Elsewhere Buy", "directional_buy_only", {
  signals: [sig("consensus_edge", "consensus", "buy")],
  rank: 5,
});
const SELL_ELSEWHERE = player("player:4", "Elsewhere Sell", "directional_sell_only", {
  signals: [sig("bdvm_market_signal", "fundamental", "sell")],
  rank: 3,
});
const CONFLICT_ON_ROSTER = player("player:5", "Rostered Conflict", "conflict", {
  signals: [sig("consensus_edge", "consensus", "buy"), sig("bdvm_market_signal", "fundamental", "sell")],
  conflict: {
    buy: [{ emitter: "consensus_edge", domain: "consensus" }],
    sell: [{ emitter: "bdvm_market_signal", domain: "fundamental" }],
    sharedAncestry: ["value_market_sources"],
    resolution: "not_resolved_by_reconciler",
  },
  rank: 40,
});
const CONFLICT_ELSEWHERE = player("player:6", "Elsewhere Conflict", "conflict", {
  conflict: { buy: [{}], sell: [{}], sharedAncestry: [] },
});
const WITHHELD_BUY = player("player:7", "Withheld Buy", "withheld", {
  signals: [sig("bdvm_market_signal", "fundamental", "buy")],
});
const WITHHELD_ON_ROSTER = player("player:9", "Withheld Rostered", "withheld", {
  signals: [sig("bdvm_market_signal", "fundamental", "sell")],
});

const ALL = [
  BUY_ON_ROSTER,
  SELL_ON_ROSTER,
  BUY_ELSEWHERE,
  SELL_ELSEWHERE,
  CONFLICT_ON_ROSTER,
  CONFLICT_ELSEWHERE,
  WITHHELD_BUY,
  WITHHELD_ON_ROSTER,
];

function names(sel, kind) {
  return sel.items.filter((i) => i.kind === kind).map((i) => i.name);
}

describe("selectTickerVerdicts — BUY is global", () => {
  it("shows BUY verdicts whether or not the player is on the selected roster", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: TEAM });
    expect(names(sel, "buy").sort()).toEqual(["Elsewhere Buy", "Rostered Buy"]);
  });

  it("still shows global BUYs when no team is selected", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: null });
    expect(names(sel, "buy").sort()).toEqual(["Elsewhere Buy", "Rostered Buy"]);
  });
});

describe("selectTickerVerdicts — SELL only for the selected roster", () => {
  it("never surfaces another team's player as SELL", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: TEAM });
    expect(names(sel, "sell")).toEqual(["Rostered Sell"]);
    expect(sel.sellScope).toBe(SELL_SCOPE.ROSTER);
    expect(sel.counts.sellOffRoster).toBe(1);
  });

  it("no team selected → no SELL items, and says so", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: null });
    expect(names(sel, "sell")).toEqual([]);
    expect(names(sel, "conflict")).toEqual([]);
    expect(sel.sellScope).toBe(SELL_SCOPE.NO_TEAM);
    expect(sellScopeText(sel.sellScope)).toMatch(/no team selected/i);
  });

  it("a payload resolved for a DIFFERENT team shows no SELL (never a previous team's roster)", () => {
    const other = { ownerId: "owner-2", name: "Bravo Team" };
    const sel = selectTickerVerdicts(payload(ALL, { team: other }), { selectedTeam: TEAM });
    expect(names(sel, "sell")).toEqual([]);
    expect(sel.sellScope).toBe(SELL_SCOPE.TEAM_MISMATCH);
  });

  it("an explicit team the server could not resolve shows no SELL", () => {
    const p = payload(ALL, { team: null });
    p.teamResolution = { requested: { ownerId: "owner-1" }, resolved: false, source: null, reason: "team_not_found" };
    const sel = selectTickerVerdicts(p, { selectedTeam: TEAM });
    expect(names(sel, "sell")).toEqual([]);
    expect(sel.sellScope).toBe(SELL_SCOPE.TEAM_NOT_FOUND);
  });

  it("no published roster membership shows no SELL (unknown is not empty)", () => {
    const p = payload(ALL);
    p.roster = null;
    const sel = selectTickerVerdicts(p, { selectedTeam: TEAM });
    expect(names(sel, "sell")).toEqual([]);
    expect(sel.sellScope).toBe(SELL_SCOPE.ROSTER_UNAVAILABLE);
  });

  it("a pick is never a SELL item, even on the roster", () => {
    const pick = player("mpick:2027:r1", "2027 Round 1", "directional_sell_only", {
      signals: [sig("consensus_edge", "consensus", "sell")],
      assetClass: "pick",
    });
    const sel = selectTickerVerdicts(payload([pick], { rosterKeys: ["mpick:2027:r1"] }), {
      selectedTeam: TEAM,
    });
    expect(sel.items).toEqual([]);
  });

  it("a name-only selection (no owner id) shows no SELL and says identity is unresolved", () => {
    const nameOnly = { ownerId: "", name: "Alpha Team" };
    // Even when the payload's team carries that exact name.
    const p = payload(ALL, { team: { ownerId: "", name: "Alpha Team" } });
    const sel = selectTickerVerdicts(p, { selectedTeam: nameOnly });
    expect(names(sel, "sell")).toEqual([]);
    expect(names(sel, "conflict")).toEqual([]);
    expect(sel.sellScope).toBe(SELL_SCOPE.TEAM_IDENTITY_UNRESOLVED);
    expect(sellScopeText(sel.sellScope)).toBe("Sells hidden: team identity unresolved");
    // BUYs are unaffected.
    expect(names(sel, "buy").sort()).toEqual(["Elsewhere Buy", "Rostered Buy"]);
  });

  it("the mismatch reason is not described as loading", () => {
    expect(sellScopeText(SELL_SCOPE.TEAM_MISMATCH)).not.toMatch(/loading/i);
  });

  it("changing the selected team changes SELL eligibility", () => {
    const bravo = { ownerId: "owner-2", name: "Bravo Team" };
    const forBravo = payload(ALL, { team: bravo, rosterKeys: ["player:4"] });
    expect(names(selectTickerVerdicts(forBravo, { selectedTeam: bravo }), "sell")).toEqual([
      "Elsewhere Sell",
    ]);
    // Alpha's payload with Bravo selected: nothing sells.
    expect(names(selectTickerVerdicts(payload(ALL), { selectedTeam: bravo }), "sell")).toEqual([]);
  });
});

describe("selectTickerVerdicts — conflict and withheld", () => {
  it("a conflict renders as CONFLICT, never as its BUY or SELL half", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: TEAM });
    expect(names(sel, "conflict")).toEqual(["Rostered Conflict"]);
    expect(names(sel, "buy")).not.toContain("Rostered Conflict");
    expect(names(sel, "sell")).not.toContain("Rostered Conflict");
  });

  it("an off-roster conflict is not shown (its SELL half would be a sell call on another team)", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: TEAM });
    expect(sel.items.map((i) => i.name)).not.toContain("Elsewhere Conflict");
    expect(sel.counts.conflictOffRoster).toBe(1);
  });

  it("withheld players never appear as BUY or SELL", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: TEAM });
    const shown = sel.items.map((i) => i.name);
    expect(shown).not.toContain("Withheld Buy");
    expect(shown).not.toContain("Withheld Rostered");
    expect(sel.counts.withheld).toBe(2);
  });
});

describe("selectTickerVerdicts — order and limit", () => {
  it("roster items first, each group in backend-stamped board-rank order, rank-less last", () => {
    const unranked = player("player:8", "Unranked Buy", "directional_buy_only", {
      signals: [sig("consensus_edge", "consensus", "buy")],
      rank: null,
    });
    const sel = selectTickerVerdicts(payload([...ALL, unranked]), { selectedTeam: TEAM });
    expect(sel.items.map((i) => i.name)).toEqual([
      "Rostered Sell", // rank 12
      "Rostered Conflict", // rank 40
      "Elsewhere Buy", // rank 5
      "Rostered Buy", // rank 30
      "Unranked Buy",
    ]);
  });

  it("the cap applies to the WHOLE strip: roster items first, BUYs fill the rest", () => {
    const sel = selectTickerVerdicts(payload(ALL), { selectedTeam: TEAM, limit: 3 });
    expect(sel.items.map((i) => i.name)).toEqual([
      "Rostered Sell",
      "Rostered Conflict",
      "Elsewhere Buy",
    ]);
    expect(sel.counts.buy).toBe(2);
    expect(sel.counts.buyShown).toBe(1);
    expect(sel.counts.rosterShown).toBe(2);
  });

  it("a 58-man roster of SELLs cannot overflow the strip", () => {
    const keys = [];
    const sells = [];
    for (let i = 1; i <= 58; i++) {
      keys.push(`player:r${i}`);
      sells.push(
        player(`player:r${i}`, `Roster ${i}`, "directional_sell_only", {
          signals: [sig("bdvm_market_signal", "fundamental", "sell")],
          rank: i,
        }),
      );
    }
    const sel = selectTickerVerdicts(payload([...sells, BUY_ELSEWHERE], { rosterKeys: keys }), {
      selectedTeam: TEAM,
      limit: 20,
    });
    expect(sel.items).toHaveLength(20);
    expect(sel.items.every((i) => i.kind === "sell")).toBe(true);
    expect(sel.items[0].name).toBe("Roster 1"); // board-rank order
    expect(sel.counts.sell).toBe(58);
    expect(sel.counts.rosterShown).toBe(20);
    expect(sel.counts.buyShown).toBe(0);
  });

  it("the default cap is 20 for the whole strip", () => {
    const many = [];
    for (let i = 1; i <= 30; i++) {
      many.push(
        player(`player:b${i}`, `Buy ${i}`, "directional_buy_only", {
          signals: [sig("consensus_edge", "consensus", "buy")],
          rank: i,
        }),
      );
    }
    const sel = selectTickerVerdicts(payload([SELL_ON_ROSTER, ...many]), { selectedTeam: TEAM });
    expect(sel.items).toHaveLength(20);
    expect(sel.items[0].name).toBe("Rostered Sell");
  });
});

describe("selectTickerVerdicts — league guard", () => {
  it("drops a payload built for a different league than the one selected — no BUY, no SELL", () => {
    const p = { ...payload(ALL), leagueKey: "dynasty_new" };
    const sel = selectTickerVerdicts(p, { selectedTeam: TEAM, selectedLeagueKey: "dynasty_main" });
    expect(sel.items).toEqual([]);
    expect(sel.leagueMismatch).toBe(true);
  });

  it("keeps a payload for the selected league", () => {
    const p = { ...payload(ALL), leagueKey: "dynasty_main" };
    const sel = selectTickerVerdicts(p, { selectedTeam: TEAM, selectedLeagueKey: "dynasty_main" });
    expect(sel.leagueMismatch).toBe(false);
    expect(names(sel, "sell")).toEqual(["Rostered Sell"]);
  });
});

describe("lineage is read from the payload, never re-derived", () => {
  it("agreement with shared ancestry reads as shared lineage, not independent", () => {
    const p = player("player:3", "Two Buys", "directional_buy_only", {
      signals: [sig("terminal_signal", "market_momentum", "buy"), sig("consensus_edge", "consensus", "buy")],
      agreement: {
        buy: {
          emitters: ["terminal_signal", "consensus_edge"],
          domains: ["consensus", "market_momentum"],
          sharedAncestry: ["value_market_sources"],
          independent: false,
        },
        sell: null,
      },
    });
    const [item] = selectTickerVerdicts(payload([p]), { selectedTeam: TEAM }).items;
    expect(lineageText(item.lineage)).toBe("2 signals · shared lineage");
  });

  it("independent agreement says independent — because the payload says so", () => {
    const p = player("player:3", "Two Buys", "directional_buy_only", {
      signals: [sig("bdvm_market_signal", "fundamental", "buy"), sig("x", "sharp", "buy")],
      agreement: { buy: { emitters: ["a", "b"], sharedAncestry: [], independent: true }, sell: null },
    });
    const [item] = selectTickerVerdicts(payload([p]), { selectedTeam: TEAM }).items;
    expect(lineageText(item.lineage)).toBe("2 independent signals");
  });

  it("a single verdict names its domain", () => {
    const [item] = selectTickerVerdicts(payload([BUY_ELSEWHERE]), { selectedTeam: TEAM }).items;
    expect(lineageText(item.lineage)).toBe("1 signal · Consensus Edge");
  });

  it("a conflict states both sides and its shared lineage", () => {
    const sel = selectTickerVerdicts(payload([CONFLICT_ON_ROSTER]), { selectedTeam: TEAM });
    expect(lineageText(sel.items[0].lineage)).toBe("1 buy vs 1 sell · shared lineage");
  });
});

describe("unobservedEmitters", () => {
  it("lists only collected emitters that did not run", () => {
    const p = {
      emitters: [
        { emitterId: "a", disposition: "collected", state: "unobserved" },
        { emitterId: "b", disposition: "collected", state: "observed" },
        { emitterId: "c", disposition: "restatement", state: "restatement" },
      ],
    };
    expect(unobservedEmitters(p).map((e) => e.emitterId)).toEqual(["a"]);
  });
});
