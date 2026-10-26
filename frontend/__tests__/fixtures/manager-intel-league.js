// Shape of GET /api/manager-intel/league (src/intel/manager_league.py),
// generated from the backend's own deterministic test fake
// (tests/intel/test_manager_league.py) and then edited: roster 3's picks
// are set to the unknown (rate-limited) state.
export const LEAGUE = {
  "status": "ok",
  "query": {
    "leagueId": "555000111"
  },
  "league": {
    "leagueId": "555000111",
    "name": "Championship Alleys",
    "season": "2026",
    "format": {
      "teams": 3,
      "season": "2026",
      "status": "in_season",
      "leagueType": "dynasty",
      "superflex": true,
      "startingQb": 1,
      "tePremium": true,
      "teBonus": 0.5,
      "idp": true,
      "kicker": false,
      "teamDefense": false,
      "taxiSlots": 3,
      "bestBall": false
    },
    "scope": "dynasty",
    "status": "in_season",
    "totalRosters": 3,
    "registryLeague": false,
    "registryKey": null
  },
  "season": "2026",
  "currentSeason": "2026",
  "window": "season",
  "windowApplied": "season",
  "windowStart": null,
  "hasBoard": true,
  "managers": [
    {
      "rosterId": 1,
      "ownerUserId": "u1",
      "displayName": "Ann",
      "teamName": "Ann's Team",
      "orphan": false,
      "coOwnerCount": 0,
      "record": {
        "wins": 4,
        "losses": 2,
        "ties": null,
        "pointsFor": null
      },
      "roster": {
        "playerCount": 3,
        "rosterSpots": 9,
        "starters": 2,
        "bench": 0,
        "taxi": 1,
        "reserve": 0,
        "pricedCount": 2,
        "unpricedCount": 1,
        "unpricedReasons": {
          "not_on_board": 1
        },
        "pricedValue": 11000,
        "byPosition": {
          "QB": {
            "count": 1,
            "pricedCount": 1,
            "unpricedCount": 0,
            "pricedValue": 6000,
            "rank": 1
          },
          "RB": {
            "count": 1,
            "pricedCount": 1,
            "unpricedCount": 0,
            "pricedValue": 5000,
            "rank": 1
          },
          "WR": {
            "count": 1,
            "pricedCount": 0,
            "unpricedCount": 1,
            "pricedValue": null,
            "rank": null
          }
        },
        "topPlayers": [
          {
            "playerId": "Q",
            "name": "Quinn Passer",
            "position": "QB",
            "value": 6000,
            "rank": 10
          },
          {
            "playerId": "A",
            "name": "Alpha Back",
            "position": "RB",
            "value": 5000,
            "rank": 20
          }
        ],
        "players": [
          {
            "playerId": "Q",
            "name": "Quinn Passer",
            "position": "QB",
            "team": "CIN",
            "age": null,
            "isRookie": false,
            "slot": "starter",
            "value": 6000,
            "rank": 10,
            "valueReason": null
          },
          {
            "playerId": "A",
            "name": "Alpha Back",
            "position": "RB",
            "team": "KC",
            "age": null,
            "isRookie": false,
            "slot": "starter",
            "value": 5000,
            "rank": 20,
            "valueReason": null
          },
          {
            "playerId": "Z",
            "name": "Zed Unranked",
            "position": "WR",
            "team": "MIA",
            "age": null,
            "isRookie": false,
            "slot": "taxi",
            "value": null,
            "rank": null,
            "valueReason": "not_on_board"
          }
        ],
        "valueNote": null
      },
      "draftCapital": {
        "leagueId": "555000111",
        "name": "Championship Test",
        "season": "2026",
        "format": {
          "teams": 3,
          "season": "2026",
          "status": "in_season",
          "leagueType": "dynasty",
          "superflex": true,
          "startingQb": 1,
          "tePremium": true,
          "teBonus": 0.5,
          "idp": true,
          "kicker": false,
          "teamDefense": false,
          "taxiSlots": 3,
          "bestBall": false
        },
        "coverage": "complete",
        "managerRosterIds": [
          1
        ],
        "rounds": 2,
        "roundsSource": "league_settings",
        "draftYears": {
          "scope": "league",
          "rule": "src/identity/pick_lifecycle.py::league_draft_years",
          "anchorYear": 2026,
          "upcomingDraftYear": 2026,
          "ownedPickSeasons": [
            2026,
            2027,
            2028,
            2029
          ],
          "retiredSeasons": [],
          "reasons": [
            "2026:unknown",
            "2027:unknown",
            "2028:unknown",
            "2029:unknown"
          ],
          "evidence": "league_drafts_read",
          "heldSeasons": [
            2026,
            2027,
            2028,
            2029
          ],
          "draftCompleteSeasons": []
        },
        "picks": [
          {
            "kind": "pick",
            "season": 2026,
            "round": 1,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2026:r1:o1",
            "label": "2026 Round 1",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2026,
            "round": 2,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2026:r2:o1",
            "label": "2026 Round 2",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2027,
            "round": 1,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2027:r1:o1",
            "label": "2027 Round 1",
            "boardRowName": "2027 Round 1",
            "value": 3500,
            "valueBasis": "board_row",
            "valueReason": null,
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2027,
            "round": 1,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2027:r1:o2",
            "label": "2027 Round 1",
            "boardRowName": "2027 Round 1",
            "value": 3500,
            "valueBasis": "board_row",
            "valueReason": null,
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": false
          },
          {
            "kind": "pick",
            "season": 2027,
            "round": 2,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2027:r2:o1",
            "label": "2027 Round 2",
            "boardRowName": "2027 Round 2",
            "value": 1200,
            "valueBasis": "board_row",
            "valueReason": null,
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2028,
            "round": 1,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2028:r1:o1",
            "label": "2028 Round 1",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2028,
            "round": 2,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2028:r2:o1",
            "label": "2028 Round 2",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2029,
            "round": 1,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2029:r1:o1",
            "label": "2029 Round 1",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2029,
            "round": 2,
            "originRosterId": 1,
            "pickId": "pick:sleeper-555000111:2029:r2:o1",
            "label": "2029 Round 2",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Ann",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          }
        ],
        "ownPicksTradedAway": [],
        "counts": {
          "held": 9,
          "own": 8,
          "acquired": 1,
          "ownTradedAway": 0
        },
        "pricedValue": 8200,
        "pricedPickCount": 3,
        "unpricedPickCount": 6,
        "unpricedReasons": {
          "no_board_row_for_ref": 6
        },
        "bySeason": {
          "2026": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2027": {
            "held": 3,
            "own": 2,
            "acquired": 1
          },
          "2028": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2029": {
            "held": 2,
            "own": 2,
            "acquired": 0
          }
        },
        "pickOwnershipState": "observed",
        "pickOwnershipReason": null
      },
      "activity": {
        "trades": 3,
        "waiverClaims": 0,
        "freeAgentAdds": 0,
        "dropsOnly": 0,
        "commissionerMoves": 0,
        "draftPicks": 0,
        "playersAdded": 3,
        "playersAddedByMethod": {
          "TRADE": 3
        },
        "playersDropped": 0,
        "faabSpent": null,
        "faabClaims": 0,
        "uncertainAttribution": 0,
        "events": 3,
        "lastActivityAt": 1791568001000
      },
      "tendencies": {
        "window": "season",
        "season": "2026",
        "tradeCount": 3,
        "excludedUncertain": 0,
        "minSample": 3,
        "minSampleBasis": "PRIOR",
        "basis": "Counts over this manager's completed trades in the window — evidence, not labels. A block below the minimum sample is shown as insufficient.",
        "positions": {
          "n": 4,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "players",
          "rows": [
            {
              "key": "LB",
              "acquired": {
                "count": 1,
                "pricedValue": 1500,
                "pricedCount": 1,
                "unpricedCount": 0
              },
              "sent": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              }
            },
            {
              "key": "RB",
              "acquired": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              },
              "sent": {
                "count": 1,
                "pricedValue": 5000,
                "pricedCount": 1,
                "unpricedCount": 0
              }
            },
            {
              "key": "TE",
              "acquired": {
                "count": 1,
                "pricedValue": 3000,
                "pricedCount": 1,
                "unpricedCount": 0
              },
              "sent": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              }
            },
            {
              "key": "WR",
              "acquired": {
                "count": 1,
                "pricedValue": 4000,
                "pricedCount": 1,
                "unpricedCount": 0
              },
              "sent": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              }
            }
          ]
        },
        "ages": {
          "n": 4,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "players",
          "rows": [
            {
              "key": "unknown",
              "acquired": {
                "count": 3,
                "pricedValue": 8500,
                "pricedCount": 3,
                "unpricedCount": 0
              },
              "sent": {
                "count": 1,
                "pricedValue": 5000,
                "pricedCount": 1,
                "unpricedCount": 0
              }
            }
          ],
          "basis": "current age (Sleeper directory), not age at the time of the trade",
          "buckets": [
            "≤23",
            "24-26",
            "27-29",
            "30+"
          ]
        },
        "pickPlayer": {
          "n": 3,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "trades",
          "counts": {
            "picks_for_players": 0,
            "players_for_picks": 0,
            "players_for_players": 1,
            "picks_for_picks": 0,
            "mixed": 0,
            "other": 2
          }
        },
        "pieces": {
          "n": 3,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "trades",
          "counts": {
            "consolidation": 0,
            "depth": 2,
            "even": 1
          },
          "definition": "consolidation = fewer pieces received than sent; depth = more pieces received than sent (players + picks)",
          "shapes": {
            "1-for-0": 2,
            "1-for-1": 1
          }
        }
      },
      "tendenciesSource": "trade_stream",
      "excluded": {},
      "valueRank": 1,
      "scout": null
    },
    {
      "rosterId": 2,
      "ownerUserId": "u2",
      "displayName": "Bob",
      "teamName": null,
      "orphan": false,
      "coOwnerCount": 1,
      "record": {
        "wins": null,
        "losses": null,
        "ties": null,
        "pointsFor": null
      },
      "roster": {
        "playerCount": 3,
        "rosterSpots": 9,
        "starters": 2,
        "bench": 0,
        "taxi": 0,
        "reserve": 1,
        "pricedCount": 3,
        "unpricedCount": 0,
        "unpricedReasons": {},
        "pricedValue": 8500,
        "byPosition": {
          "WR": {
            "count": 1,
            "pricedCount": 1,
            "unpricedCount": 0,
            "pricedValue": 4000,
            "rank": 1
          },
          "TE": {
            "count": 1,
            "pricedCount": 1,
            "unpricedCount": 0,
            "pricedValue": 3000,
            "rank": 1
          },
          "LB": {
            "count": 1,
            "pricedCount": 1,
            "unpricedCount": 0,
            "pricedValue": 1500,
            "rank": 1
          }
        },
        "topPlayers": [
          {
            "playerId": "B",
            "name": "Bravo Receiver",
            "position": "WR",
            "value": 4000,
            "rank": 30
          },
          {
            "playerId": "C",
            "name": "Charlie End",
            "position": "TE",
            "value": 3000,
            "rank": 45
          },
          {
            "playerId": "D",
            "name": "Delta Backer",
            "position": "LB",
            "value": 1500,
            "rank": 300
          }
        ],
        "players": [
          {
            "playerId": "B",
            "name": "Bravo Receiver",
            "position": "WR",
            "team": "BUF",
            "age": null,
            "isRookie": false,
            "slot": "starter",
            "value": 4000,
            "rank": 30,
            "valueReason": null
          },
          {
            "playerId": "C",
            "name": "Charlie End",
            "position": "TE",
            "team": "DET",
            "age": null,
            "isRookie": false,
            "slot": "starter",
            "value": 3000,
            "rank": 45,
            "valueReason": null
          },
          {
            "playerId": "D",
            "name": "Delta Backer",
            "position": "LB",
            "team": "SF",
            "age": null,
            "isRookie": false,
            "slot": "reserve",
            "value": 1500,
            "rank": 300,
            "valueReason": null
          }
        ],
        "valueNote": null
      },
      "draftCapital": {
        "leagueId": "555000111",
        "name": "Championship Test",
        "season": "2026",
        "format": {
          "teams": 3,
          "season": "2026",
          "status": "in_season",
          "leagueType": "dynasty",
          "superflex": true,
          "startingQb": 1,
          "tePremium": true,
          "teBonus": 0.5,
          "idp": true,
          "kicker": false,
          "teamDefense": false,
          "taxiSlots": 3,
          "bestBall": false
        },
        "coverage": "complete",
        "managerRosterIds": [
          2
        ],
        "rounds": 2,
        "roundsSource": "league_settings",
        "draftYears": {
          "scope": "league",
          "rule": "src/identity/pick_lifecycle.py::league_draft_years",
          "anchorYear": 2026,
          "upcomingDraftYear": 2026,
          "ownedPickSeasons": [
            2026,
            2027,
            2028,
            2029
          ],
          "retiredSeasons": [],
          "reasons": [
            "2026:unknown",
            "2027:unknown",
            "2028:unknown",
            "2029:unknown"
          ],
          "evidence": "league_drafts_read",
          "heldSeasons": [
            2026,
            2027,
            2028,
            2029
          ],
          "draftCompleteSeasons": []
        },
        "picks": [
          {
            "kind": "pick",
            "season": 2026,
            "round": 1,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2026:r1:o2",
            "label": "2026 Round 1",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2026,
            "round": 2,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2026:r2:o2",
            "label": "2026 Round 2",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2027,
            "round": 2,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2027:r2:o2",
            "label": "2027 Round 2",
            "boardRowName": "2027 Round 2",
            "value": 1200,
            "valueBasis": "board_row",
            "valueReason": null,
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2028,
            "round": 1,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2028:r1:o2",
            "label": "2028 Round 1",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2028,
            "round": 2,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2028:r2:o2",
            "label": "2028 Round 2",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2029,
            "round": 1,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2029:r1:o2",
            "label": "2029 Round 1",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          },
          {
            "kind": "pick",
            "season": 2029,
            "round": 2,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2029:r2:o2",
            "label": "2029 Round 2",
            "boardRowName": null,
            "value": null,
            "valueBasis": null,
            "valueReason": "no_board_row_for_ref",
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 2,
            "currentOwnerName": "Bob",
            "own": true
          }
        ],
        "ownPicksTradedAway": [
          {
            "kind": "pick",
            "season": 2027,
            "round": 1,
            "originRosterId": 2,
            "pickId": "pick:sleeper-555000111:2027:r1:o2",
            "label": "2027 Round 1",
            "boardRowName": "2027 Round 1",
            "value": 3500,
            "valueBasis": "board_row",
            "valueReason": null,
            "originOwnerName": "Bob",
            "currentOwnerRosterId": 1,
            "currentOwnerName": "Ann",
            "own": true
          }
        ],
        "counts": {
          "held": 7,
          "own": 7,
          "acquired": 0,
          "ownTradedAway": 1
        },
        "pricedValue": 1200,
        "pricedPickCount": 1,
        "unpricedPickCount": 6,
        "unpricedReasons": {
          "no_board_row_for_ref": 6
        },
        "bySeason": {
          "2026": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2027": {
            "held": 1,
            "own": 1,
            "acquired": 0
          },
          "2028": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2029": {
            "held": 2,
            "own": 2,
            "acquired": 0
          }
        },
        "pickOwnershipState": "observed",
        "pickOwnershipReason": null
      },
      "activity": {
        "trades": 3,
        "waiverClaims": 1,
        "freeAgentAdds": 0,
        "dropsOnly": 0,
        "commissionerMoves": 0,
        "draftPicks": 0,
        "playersAdded": 2,
        "playersAddedByMethod": {
          "TRADE": 1,
          "WAIVER": 1
        },
        "playersDropped": 1,
        "faabSpent": 7,
        "faabClaims": 1,
        "uncertainAttribution": 0,
        "events": 4,
        "lastActivityAt": 1791568001000
      },
      "tendencies": {
        "window": "season",
        "season": "2026",
        "tradeCount": 3,
        "excludedUncertain": 0,
        "minSample": 3,
        "minSampleBasis": "PRIOR",
        "basis": "Counts over this manager's completed trades in the window — evidence, not labels. A block below the minimum sample is shown as insufficient.",
        "positions": {
          "n": 4,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "players",
          "rows": [
            {
              "key": "LB",
              "acquired": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              },
              "sent": {
                "count": 1,
                "pricedValue": 1500,
                "pricedCount": 1,
                "unpricedCount": 0
              }
            },
            {
              "key": "RB",
              "acquired": {
                "count": 1,
                "pricedValue": 5000,
                "pricedCount": 1,
                "unpricedCount": 0
              },
              "sent": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              }
            },
            {
              "key": "TE",
              "acquired": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              },
              "sent": {
                "count": 1,
                "pricedValue": 3000,
                "pricedCount": 1,
                "unpricedCount": 0
              }
            },
            {
              "key": "WR",
              "acquired": {
                "count": 0,
                "pricedValue": null,
                "pricedCount": 0,
                "unpricedCount": 0
              },
              "sent": {
                "count": 1,
                "pricedValue": 4000,
                "pricedCount": 1,
                "unpricedCount": 0
              }
            }
          ]
        },
        "ages": {
          "n": 4,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "players",
          "rows": [
            {
              "key": "unknown",
              "acquired": {
                "count": 1,
                "pricedValue": 5000,
                "pricedCount": 1,
                "unpricedCount": 0
              },
              "sent": {
                "count": 3,
                "pricedValue": 8500,
                "pricedCount": 3,
                "unpricedCount": 0
              }
            }
          ],
          "basis": "current age (Sleeper directory), not age at the time of the trade",
          "buckets": [
            "≤23",
            "24-26",
            "27-29",
            "30+"
          ]
        },
        "pickPlayer": {
          "n": 3,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "trades",
          "counts": {
            "picks_for_players": 0,
            "players_for_picks": 0,
            "players_for_players": 1,
            "picks_for_picks": 0,
            "mixed": 0,
            "other": 2
          }
        },
        "pieces": {
          "n": 3,
          "minSample": 3,
          "sufficientSample": true,
          "unit": "trades",
          "counts": {
            "consolidation": 2,
            "depth": 0,
            "even": 1
          },
          "definition": "consolidation = fewer pieces received than sent; depth = more pieces received than sent (players + picks)",
          "shapes": {
            "0-for-1": 2,
            "1-for-1": 1
          }
        }
      },
      "tendenciesSource": "trade_stream",
      "excluded": {},
      "valueRank": 2,
      "scout": null
    },
    {
      "rosterId": 3,
      "ownerUserId": null,
      "displayName": null,
      "teamName": null,
      "orphan": true,
      "coOwnerCount": 0,
      "record": {
        "wins": null,
        "losses": null,
        "ties": null,
        "pointsFor": null
      },
      "roster": {
        "playerCount": 1,
        "rosterSpots": 9,
        "starters": 0,
        "bench": 1,
        "taxi": 0,
        "reserve": 0,
        "pricedCount": 0,
        "unpricedCount": 1,
        "unpricedReasons": {
          "not_on_board": 1
        },
        "pricedValue": null,
        "byPosition": {
          "RB": {
            "count": 1,
            "pricedCount": 0,
            "unpricedCount": 1,
            "pricedValue": null,
            "rank": null
          }
        },
        "topPlayers": [],
        "players": [
          {
            "playerId": "Y",
            "name": "Yan Unranked",
            "position": "RB",
            "team": "NYG",
            "age": null,
            "isRookie": false,
            "slot": "bench",
            "value": null,
            "rank": null,
            "valueReason": "not_on_board"
          }
        ],
        "valueNote": null
      },
      "draftCapital": {
        "leagueId": "555000111",
        "name": "Championship Test",
        "season": "2026",
        "format": {
          "teams": 3,
          "season": "2026",
          "status": "in_season",
          "leagueType": "dynasty",
          "superflex": true,
          "startingQb": 1,
          "tePremium": true,
          "teBonus": 0.5,
          "idp": true,
          "kicker": false,
          "teamDefense": false,
          "taxiSlots": 3,
          "bestBall": false
        },
        "coverage": "rate_limited",
        "managerRosterIds": [
          3
        ],
        "rounds": 2,
        "roundsSource": "league_settings",
        "draftYears": {
          "scope": "league",
          "rule": "src/identity/pick_lifecycle.py::league_draft_years",
          "anchorYear": 2026,
          "upcomingDraftYear": 2026,
          "ownedPickSeasons": [
            2026,
            2027,
            2028,
            2029
          ],
          "retiredSeasons": [],
          "reasons": [
            "2026:unknown",
            "2027:unknown",
            "2028:unknown",
            "2029:unknown"
          ],
          "evidence": "league_drafts_read",
          "heldSeasons": [
            2026,
            2027,
            2028,
            2029
          ],
          "draftCompleteSeasons": []
        },
        "picks": null,
        "ownPicksTradedAway": [],
        "counts": null,
        "pricedValue": null,
        "pricedPickCount": 2,
        "unpricedPickCount": 6,
        "unpricedReasons": {
          "no_board_row_for_ref": 6
        },
        "bySeason": {
          "2026": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2027": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2028": {
            "held": 2,
            "own": 2,
            "acquired": 0
          },
          "2029": {
            "held": 2,
            "own": 2,
            "acquired": 0
          }
        },
        "pickOwnershipState": "unavailable",
        "pickOwnershipReason": "traded_picks_fetch_failed"
      },
      "activity": {
        "trades": 0,
        "waiverClaims": 0,
        "freeAgentAdds": 0,
        "dropsOnly": 0,
        "commissionerMoves": 0,
        "draftPicks": 0,
        "playersAdded": 0,
        "playersAddedByMethod": {},
        "playersDropped": 0,
        "faabSpent": null,
        "faabClaims": 0,
        "uncertainAttribution": 0,
        "events": 0,
        "lastActivityAt": null
      },
      "tendencies": {
        "window": "season",
        "season": "2026",
        "tradeCount": 0,
        "excludedUncertain": 0,
        "minSample": 3,
        "minSampleBasis": "PRIOR",
        "basis": "Counts over this manager's completed trades in the window — evidence, not labels. A block below the minimum sample is shown as insufficient.",
        "positions": {
          "n": 0,
          "minSample": 3,
          "sufficientSample": false,
          "unit": "players",
          "rows": []
        },
        "ages": {
          "n": 0,
          "minSample": 3,
          "sufficientSample": false,
          "unit": "players",
          "rows": [],
          "basis": "current age (Sleeper directory), not age at the time of the trade",
          "buckets": [
            "≤23",
            "24-26",
            "27-29",
            "30+"
          ]
        },
        "pickPlayer": {
          "n": 0,
          "minSample": 3,
          "sufficientSample": false,
          "unit": "trades",
          "counts": {
            "picks_for_players": 0,
            "players_for_picks": 0,
            "players_for_players": 0,
            "picks_for_picks": 0,
            "mixed": 0,
            "other": 0
          }
        },
        "pieces": {
          "n": 0,
          "minSample": 3,
          "sufficientSample": false,
          "unit": "trades",
          "counts": {
            "consolidation": 0,
            "depth": 0,
            "even": 0
          },
          "definition": "consolidation = fewer pieces received than sent; depth = more pieces received than sent (players + picks)",
          "shapes": {}
        }
      },
      "tendenciesSource": "trade_stream",
      "excluded": {},
      "valueRank": null,
      "scout": null
    }
  ],
  "managerCount": 3,
  "ranking": {
    "rankedRosters": 2,
    "positions": [
      "QB",
      "RB",
      "WR",
      "TE",
      "LB"
    ],
    "withheld": null,
    "basis": "canonical board value (rankDerivedValue) of priced rostered players",
    "note": "Ranks compare the league's rosters on the canonical board, a Superflex / TE-premium board. Totals add priced players only; unpriced players are counted beside them, never as 0."
  },
  "draftCapital": {
    "available": true,
    "reason": null,
    "coverage": "complete",
    "rostersWithPricedPicks": 3,
    "valueNote": "Pick values are the canonical board's at the generic season + round grade — no tier or slot is assumed."
  },
  "tendencies": {
    "source": "trade_stream",
    "minSample": 3,
    "minSampleBasis": "PRIOR"
  },
  "scout": null,
  "coverage": {
    "leagueId": "555000111",
    "name": "Championship Test",
    "season": "2026",
    "format": {
      "teams": 3,
      "season": "2026",
      "status": "in_season",
      "leagueType": "dynasty",
      "superflex": true,
      "startingQb": 1,
      "tePremium": true,
      "teBonus": 0.5,
      "idp": true,
      "kicker": false,
      "teamDefense": false,
      "taxiSlots": 3,
      "bestBall": false
    },
    "rosterHeld": true,
    "rosters": "complete",
    "transactions": "complete",
    "drafts": "complete",
    "tradedPicks": "complete",
    "weeksFetched": 8,
    "weeksFailed": 0,
    "leagueUsers": "complete",
    "legsRequested": [
      0,
      1,
      2,
      3,
      4,
      5,
      6,
      7
    ],
    "budgetExhausted": false,
    "callsSpent": 13,
    "callBudget": 80
  },
  "valueBasis": {
    "field": "rankDerivedValue",
    "board": "canonical Superflex / TE-premium board",
    "note": "Values are the canonical board's (a Superflex / TE-premium board). Roster totals and league ranks are published only for a Superflex league."
  },
  "fetchedAt": 1792000000000
};
