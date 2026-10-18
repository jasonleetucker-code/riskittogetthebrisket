"""P0 audit (owner master package 2026-10-17): the best-ball presim drew every
rostered player in every simulated week, so a player out for the season still
lifted his team's simulated scores and playoff odds."""

from __future__ import annotations

import random

from src.ros import playoff_sim

SLOTS = ["QB", "RB", "WR", "TE", "SUPER_FLEX"]


def _p(pid, pos, ros):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": ros,
        "fantasyPositions": [pos],
    }


ROSTER = {
    "starters": [
        _p("qb_star", "QB", 9000.0),
        _p("qb_two", "QB", 3000.0),
        _p("rb", "RB", 4000.0),
        _p("wr", "WR", 4000.0),
        _p("te", "TE", 2500.0),
    ],
    "bench": [],
}


def _mean(weeks=None, unavailable=None):
    out = playoff_sim._bestball_presim(
        {"t": ROSTER}, SLOTS, random.Random(7), weeks=weeks, unavailable=unavailable
    )
    return out["t"][0]


def test_season_ending_player_no_longer_lifts_the_presim():
    weeks = list(range(6, 18))
    with_star = _mean()
    star_out = _mean(weeks, {("qb_star", w) for w in weeks})
    without = playoff_sim._bestball_presim(
        {
            "t": {
                "starters": [p for p in ROSTER["starters"] if p["playerId"] != "qb_star"],
                "bench": [],
            }
        },
        SLOTS,
        random.Random(7),
    )["t"][0]
    assert star_out < with_star
    # Out every remaining week == not on the roster (same draws, same model).
    assert abs(star_out - without) / without < 0.05


def test_partial_absence_is_between_the_two():
    weeks = list(range(6, 18))
    full = _mean(weeks, set())
    half = _mean(weeks, {("qb_star", w) for w in weeks[:6]})
    out = _mean(weeks, {("qb_star", w) for w in weeks})
    assert out < half < full


def test_no_calendar_is_the_previous_behaviour():
    assert _mean() == _mean(None, None)
