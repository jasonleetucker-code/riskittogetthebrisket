// Manager Intelligence Batch D fixtures: one scouted roster in the two league
// states the trade tools distinguish.  Shapes follow GET
// /api/manager-intel/league (src/intel/manager_league.py): roster players carry
// `boardName` (the calculator's row name, null off the board) and held picks
// their canonical `pickId` + the generic `boardRowName` they were valued from.

export const RECEIPT = {
  id: "geom_q078_v1",
  family: "geom",
  version: "1",
  label: "Geometric Value Adjustment (q = 0.78)",
  classification: "ACTIVE",
};

export const SCOPED_TOOLS = {
  leagueScoped: true,
  leagueKey: "dynasty_main",
  reason: null,
  packageModel: RECEIPT,
};

export const EXTERNAL_TOOLS = {
  leagueScoped: false,
  leagueKey: null,
  reason: "external_league",
  packageModel: RECEIPT,
};

export const NOT_LOADED_TOOLS = {
  leagueScoped: false,
  leagueKey: null,
  reason: "league_rosters_not_loaded",
  packageModel: RECEIPT,
};

function pick(leagueKey, season, round, extra = {}) {
  return {
    kind: "pick",
    season,
    round,
    originRosterId: 4,
    pickId: `pick:${leagueKey}:${season}:r${round}:o4`,
    label: `${season} Round ${round}`,
    boardRowName: `${season} Round ${round}`,
    value: round === 1 ? 3500 : 1200,
    valueBasis: "board_row",
    valueReason: null,
    originOwnerName: "Dana",
    currentOwnerRosterId: 4,
    currentOwnerName: "Dana",
    own: true,
    ...extra,
  };
}

export function scoutedManager(leagueKey = "dynasty_main") {
  return {
    rosterId: 4,
    ownerUserId: "735693375101108224",
    displayName: "Dana",
    roster: {
      players: [
        {
          playerId: "4046",
          name: "Quinn Passer",
          position: "QB",
          slot: "starter",
          boardName: "Quinn Passer",
          value: 6000,
          rank: 10,
          valueReason: null,
        },
        {
          playerId: "6794",
          name: "Alpha Back",
          position: "RB",
          slot: "bench",
          boardName: "Alpha Back",
          value: 5000,
          rank: 20,
          valueReason: null,
        },
        {
          // On the board but unpriced: never seeded, never 0.
          playerId: "9001",
          name: "Deep Veteran",
          position: "WR",
          slot: "bench",
          boardName: "Deep Veteran",
          value: null,
          rank: null,
          valueReason: "unpriced_by_board",
        },
        {
          // Not on the board at all.
          playerId: "9002",
          name: "Zed Unranked",
          position: "WR",
          slot: "taxi",
          boardName: null,
          value: null,
          rank: null,
          valueReason: "not_on_board",
        },
      ],
    },
    draftCapital: {
      pickOwnershipState: "observed",
      picks: [
        pick(leagueKey, 2027, 1),
        pick(leagueKey, 2027, 2, { own: false, originOwnerName: "Bob" }),
        pick(leagueKey, 2026, 1, {
          boardRowName: null,
          value: null,
          valueBasis: null,
          valueReason: "pick_already_used",
        }),
      ],
    },
  };
}
