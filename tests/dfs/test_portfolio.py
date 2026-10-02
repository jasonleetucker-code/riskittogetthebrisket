"""Portfolio summary: exact counts of what was built, nothing estimated."""

from __future__ import annotations

from src.dfs.portfolio import summarize


def _lu(players, salary=50000):
    return {
        "salary": salary,
        "players": [{"playerId": pid, "team": t, "game": g} for pid, t, g in players],
    }


def test_counts_teams_games_shapes_and_distinct_players():
    a = _lu(
        [("1", "AA", "AA@BB"), ("2", "AA", "AA@BB"), ("3", "BB", "AA@BB"), ("4", "CC", "CC@DD")],
        49000,
    )
    b = _lu(
        [("1", "AA", "AA@BB"), ("5", "CC", "CC@DD"), ("6", "CC", "CC@DD"), ("7", "DD", "CC@DD")],
        50000,
    )
    s = summarize([a, b])
    assert s["lineups"] == 2 and s["distinctPlayers"] == 7
    assert {r["key"]: r["lineups"] for r in s["teams"]} == {"AA": 2, "CC": 2, "BB": 1, "DD": 1}
    assert {r["key"]: r["lineups"] for r in s["games"]} == {"AA@BB": 2, "CC@DD": 2}
    assert {r["key"] for r in s["stackShapes"]} == {"2-1-1"}
    assert s["stackShapes"][0]["lineups"] == 2 and s["salary"] == {"min": 49000, "max": 50000}
    assert s["lineupsWithUnknownGame"] == 0


def test_single_lineup_has_no_portfolio_and_unknown_games_are_counted_not_guessed():
    a = _lu([("1", "AA", None), ("2", "BB", "AA@BB")])
    assert summarize([a]) is None
    s = summarize([a, a])
    assert s["lineupsWithUnknownGame"] == 2
    assert [r["key"] for r in s["games"]] == ["AA@BB"]
