"""Master-site-audit W17-F001 / W17-F002 regression (CW-40, 2026-11-06).

W17-F001: the ROS sims resolved the OLDEST loaded season because
``luck._season_sort_key`` was handed a SeasonSnapshot object (every key 0).
W17-F002: a manager absent from the cached sim got a coerced 0.0 playoff
odds and was told "Seller" -- including the #1 ROS-strength team.

Both are fixed on main; ``test_season_selection.py`` and
``test_trade_deadline_unknown.py`` pin the pieces.  This adds the behavioural
end-to-end checks the audit actually measured: the selector the simulators
call, and the direction table with the audit's exact shape (strongest roster
absent from the sim).
"""

from __future__ import annotations

from types import SimpleNamespace

from src.ros import playoff_sim
from src.ros.trade_deadline import build_team_directions

_SELL_FAMILY_WORDS = ("sell", "seller")


def test_the_simulated_season_is_the_newest_whatever_the_load_order():
    newest_first = SimpleNamespace(
        seasons=[SimpleNamespace(season=y) for y in ("2026", "2025", "2024")]
    )
    oldest_first = SimpleNamespace(seasons=list(reversed(newest_first.seasons)))
    assert playoff_sim._simulated_season(newest_first).season == "2026"
    assert playoff_sim._simulated_season(oldest_first).season == "2026"
    assert playoff_sim._simulated_season(SimpleNamespace(seasons=[])) is None


def test_the_strongest_roster_absent_from_the_sim_is_not_told_to_sell():
    # Owner "new" joined after the simulated season: absent from both sim maps,
    # present (and rank 1 of 3) in the team-strength snapshot.
    rows = build_team_directions(
        playoff_odds_map={"a": {"playoffOdds": 0.9}, "b": {"playoffOdds": 0.1}},
        championship_map={"a": {"championshipOdds": 0.4}, "b": {"championshipOdds": 0.02}},
        team_strength_map={
            "new": {"ownerId": "new", "teamName": "New", "rank": 1},
            "a": {"ownerId": "a", "teamName": "A", "rank": 2},
            "b": {"ownerId": "b", "teamName": "B", "rank": 3},
        },
        read_simulations=False,
    )
    by_owner = {r["ownerId"]: r for r in rows}
    new = by_owner["new"]
    assert new["playoffOdds"] is None and new["championshipOdds"] is None
    assert not any(w in str(new.get("label", "")).lower() for w in _SELL_FAMILY_WORDS)
    # A genuinely measured low-odds team still gets its measured odds, never null.
    assert by_owner["b"]["playoffOdds"] == 0.1
