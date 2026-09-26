"""Waiver King counts each (roster, player, week) at most once.

The per-add loop asked "was this player started by this roster in week w"
for every week after EACH add.  Add -> drop -> re-add made the first add's
window overlap the re-add's, so every week after the re-add counted twice.
Measured on the persisted snapshot 2026-09-26: 799.6 double-counted points in
2025 and 182.1 in 2024, flipping both winners (2025 Jason -> Brent, 2024
Jason -> Roy).
"""

from __future__ import annotations

import unittest

from src.public_league import awards
from src.public_league.identity import build_manager_registry
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot

_OWNERS = ["owner-A", "owner-B"]
_USERS = [{"user_id": o, "display_name": o[-1], "metadata": {}} for o in _OWNERS]
_ROSTERS = [
    {"roster_id": i, "owner_id": o, "players": [], "settings": {}}
    for i, o in enumerate(_OWNERS, start=1)
]


def _week(w1_points: float | None) -> list[dict]:
    """Roster 1 starts waiver pickup ``w1`` when ``w1_points`` is not None."""
    a_starters = ["base_a"] + (["w1"] if w1_points is not None else [])
    a_points = {"base_a": 50.0}
    if w1_points is not None:
        a_points["w1"] = w1_points
    return [
        {
            "matchup_id": 1,
            "roster_id": 1,
            "points": sum(a_points.values()),
            "starters": a_starters,
            "players_points": a_points,
        },
        {
            "matchup_id": 1,
            "roster_id": 2,
            "points": 40.0,
            "starters": ["base_b"],
            "players_points": {"base_b": 40.0},
        },
    ]


def _tx(tx_id: str, created: int, *, adds=None, drops=None) -> dict:
    return {
        "transaction_id": tx_id,
        "type": "free_agent",
        "status": "complete",
        "created": created,
        "roster_ids": [1],
        "adds": adds,
        "drops": drops,
    }


def _snapshot() -> PublicLeagueSnapshot:
    # Week 1: add w1.  Week 2: he starts (10) then is dropped.  Week 3: not
    # rostered.  Week 3 transaction: re-added.  Week 4: he starts (20).
    league = {
        "league_id": "L1",
        "season": "2025",
        "status": "complete",
        "total_rosters": 2,
        "settings": {"playoff_week_start": 15, "last_scored_leg": 4},
    }
    season = SeasonSnapshot(
        season="2025",
        league_id="L1",
        league=league,
        users=_USERS,
        rosters=_ROSTERS,
        matchups_by_week={1: _week(None), 2: _week(10.0), 3: _week(None), 4: _week(20.0)},
        transactions_by_week={
            1: [_tx("add-1", 100, adds={"w1": 1})],
            2: [_tx("drop-1", 200, drops={"w1": 1})],
            3: [_tx("add-2", 300, adds={"w1": 1})],
        },
        drafts=[],
        draft_picks_by_draft={},
        traded_picks=[],
        winners_bracket=[],
        losers_bracket=[],
    )
    return PublicLeagueSnapshot(
        root_league_id="L1",
        generated_at="2025-12-31T00:00:00Z",
        seasons=[season],
        managers=build_manager_registry([{"league": league, "users": _USERS, "rosters": _ROSTERS}]),
    )


class WaiverKingReAddTests(unittest.TestCase):
    def setUp(self):
        snap = _snapshot()
        rows = awards._waiver_king_scores(snap, snap.seasons[0])
        self.row = next(r for r in rows if r["ownerId"] == "owner-A")

    def test_each_roster_week_counts_once(self):
        # 10 (week 2) + 20 (week 4).  The old loop reported 50: week 4
        # counted for the first add AND the re-add.
        self.assertEqual(self.row["pointsGained"], 30.0)

    def test_both_stints_are_credited_to_the_add_that_produced_them(self):
        self.assertEqual(self.row["addCount"], 2)
        self.assertEqual(self.row["usefulAdds"], 2)


if __name__ == "__main__":
    unittest.main()
