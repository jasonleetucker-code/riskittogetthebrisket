"""CW-49 repairs in the canonical playoff engine (owner directive 2026-11-07).

1. DIVISIONS.  Sleeper's DEFAULT qualifies every division winner for the
   playoffs ("If there are divisions, then each division winner will qualify
   for the playoffs" — https://sleeper.com/blog/how-do-fantasy-playoffs-work),
   whatever its overall record, and ``simulate_playoff_odds`` seeds on overall
   record and Points For only.  CW-49 refused every league with divisions ON;
   the owner corrected that on 2026-11-08 — ``dynasty_main``'s divisions bear
   on nothing but the schedule and a payout (``config/leagues/playoff_rules.json``,
   pinned in ``tests/ros/test_league_division_rules.py``).  What stays here is
   the UNRECORDED league: divisions ON and no record of how they are played.
   Its qualifying keeps the unverified host default, so playoff / bye / seed /
   title odds are withheld with a named, qualification-scoped reason — while
   the regular season, which decides the draft order, is still simulated.

2. TRADE IMPACT.  ``simulate_trade_impact`` fell through a REFUSED simulation
   with empty deltas, ``meaningfulDeltas: 0`` and the requested count as
   ``nSimulations`` (``0 or n_simulations``) — a zero-impact trade over
   simulations that never ran.  It now carries the refusal.
"""

from __future__ import annotations

import random
from types import SimpleNamespace
from unittest import mock

import pytest

from src.public_league import playoff_odds
from src.public_league.playoff_structure import resolve_playoff_structure
from src.ros import playoff_sim

_OWNERS = ["a", "b", "c", "d"]


def _season(**settings):
    base = {"playoff_teams": 2, "playoff_seed_type": 1, "playoff_week_start": 15}
    base.update(settings)
    base = {k: v for k, v in base.items() if v is not _ABSENT}
    return SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": base},
        rosters=[],
        matchups_by_week={},
        regular_season_weeks=[],
        num_teams=4,
    )


_ABSENT = object()


def _snapshot(**settings):
    season = _season(**settings)
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}), current_season=season, seasons=[season]
    )


#: A league with no recorded playoff rule (``config/leagues/playoff_rules.json``).
_UNRECORDED = "unrecorded_test_league"


def _patched(record, schedule, league_key=_UNRECORDED):
    dists = {
        o: playoff_sim._TeamDist(
            owner_id=o, mean=100.0 + 5 * i, sd=12.0, pf_to_date=900.0, basis="empirical"
        )
        for i, o in enumerate(_OWNERS)
    }
    pf = {o: 900.0 + i for i, o in enumerate(_OWNERS)}
    return (
        mock.patch.object(
            playoff_sim,
            "_current_standings",
            lambda *a, **k: (record, {"medianGame": False, "state": "not_applicable"}),
        ),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: list(schedule)),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        mock.patch.object(
            playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, dict(pf))
        ),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: set(range(1, 9))),
        mock.patch("src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: league_key),
    )


_RECORD = {o: {"wins": 4, "losses": 4, "ties": 0} for o in _OWNERS}
_SCHEDULE = [(9, "a", "b"), (9, "c", "d")]


def _simulate(snapshot, record=_RECORD, schedule=_SCHEDULE):
    patches = _patched(record, schedule)
    for p in patches:
        p.start()
    try:
        return playoff_sim.simulate_playoff_odds(snapshot, n_simulations=500, rng=random.Random(1))
    finally:
        for p in patches:
            p.stop()


# ── the structure reads the setting ────────────────────────────────────


@pytest.mark.parametrize(
    "raw, divisions, in_play, reason",
    [
        (3, 3, True, ""),
        ("2", 2, True, ""),
        (0, 0, False, ""),
        (_ABSENT, None, False, ""),
        ("three", None, True, "divisions_setting_not_recognised"),
        (-1, None, True, "divisions_setting_not_recognised"),
        (True, None, True, "divisions_setting_not_recognised"),
        # Review of #2134: a fractional value used to truncate (0.5 -> 0, so
        # the league was simulated — failing open; 2.5 -> "2 divisions").
        (2.0, 2, True, ""),
        (0.5, None, True, "divisions_setting_not_recognised"),
        (2.5, None, True, "divisions_setting_not_recognised"),
        ("2.5", None, True, "divisions_setting_not_recognised"),
        # A key that is PRESENT but null is not a statement of zero.
        (None, None, True, "divisions_setting_not_recognised"),
    ],
)
def test_the_structure_reads_the_divisions_setting(raw, divisions, in_play, reason):
    structure = resolve_playoff_structure(_season(divisions=raw))
    assert structure.divisions == divisions
    assert structure.divisions_in_play is in_play
    assert structure.divisions_reason == reason
    assert structure.to_dict()["divisions"] == divisions
    # No league key -> no record: divisions ON leave qualifying unknown.
    assert structure.division_qualification_unknown is in_play
    assert structure.division_rule == ("unrecorded" if in_play else "no_divisions")


# ── an UNRECORDED league with divisions ON withholds qualifying only ───


def test_an_unrecorded_league_with_divisions_withholds_qualifying_with_a_named_reason():
    out = _simulate(_snapshot(divisions=3))
    assert out["playoffOdds"] == []
    assert out["unsimulable"]["reason"] == "league_divisions_unmodeled"
    assert out["unsimulable"]["scope"] == "qualification"
    assert out["unsimulable"]["divisions"] == 3
    assert "not a 0% chance" in out["unsimulable"]["detail"]
    assert out["playoffStructure"]["divisions"] == 3
    assert out["playoffStructure"]["divisionRule"] == "unrecorded"
    # The regular season WAS simulated: its outputs that do not depend on
    # who qualifies are published, and nothing that does depend on it is.
    assert out["n_simulations"] == 500
    rows = out["regularSeasonOdds"]
    assert {r["ownerId"] for r in rows} == set(_OWNERS)
    for r in rows:
        assert r["expectedWins"] > 0
        for withheld in ("playoffOdds", "seedDistribution", "byeOdds", "championshipOdds"):
            assert withheld not in r
    # No recorded champion rule either: division titles are unavailable.
    assert out["divisionOdds"]["state"] == "unavailable"
    assert out["divisionOdds"]["reason"] == "division_champion_rule_unrecorded"


def test_an_unreadable_divisions_setting_is_refused_too():
    out = _simulate(_snapshot(divisions="three"))
    assert out["playoffOdds"] == []
    assert out["unsimulable"]["reason"] == "divisions_setting_not_recognised"
    assert out["unsimulable"]["scope"] == "qualification"


@pytest.mark.parametrize("raw", [0, _ABSENT])
def test_a_league_without_divisions_still_simulates(raw):
    out = _simulate(_snapshot(divisions=raw))
    assert "unsimulable" not in out
    assert out["n_simulations"] == 500
    assert sum(r["playoffOdds"] for r in out["playoffOdds"]) == pytest.approx(2.0, abs=1e-3)


def test_a_cached_forecast_from_before_divisions_turned_on_is_not_served():
    """A forecast computed while divisions were off must not be laid beside a
    league that now plays in divisions: the structure it carries differs."""
    off = _snapshot(divisions=0, league_average_match=0)
    cached = _simulate(off)
    with mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: set(range(1, 9))):
        assert playoff_sim.cached_forecast_matches_snapshot(cached, off) is True
        on = _snapshot(divisions=3, league_average_match=0)
        assert playoff_sim.cached_forecast_matches_snapshot(cached, on) is False


# ── a refused trade arm is not a zero-impact trade ─────────────────────


def test_trade_impact_carries_the_refusal_instead_of_zero_deltas():
    # Nothing played and nothing scheduled: the simulator refuses.
    patches = _patched({o: {} for o in _OWNERS}, [])
    for p in patches:
        p.start()
    try:
        out = playoff_sim.simulate_trade_impact(
            _snapshot(divisions=0), strength_delta={"a": 20.0}, n_simulations=400
        )
    finally:
        for p in patches:
            p.stop()
    assert out["unsimulable"]["reason"] == "no_games_played_and_none_scheduled"
    assert out["nSimulations"] == 0
    assert out["playoff"] == [] and out["championship"] == []


def test_trade_impact_on_a_league_with_divisions_is_refused():
    patches = _patched(_RECORD, _SCHEDULE)
    for p in patches:
        p.start()
    try:
        out = playoff_sim.simulate_trade_impact(
            _snapshot(divisions=3), strength_delta={"a": 20.0}, n_simulations=400
        )
    finally:
        for p in patches:
            p.stop()
    assert out["unsimulable"]["reason"] == "league_divisions_unmodeled"
    assert out["nSimulations"] == 0


def test_a_simulated_trade_still_reports_its_real_count():
    patches = _patched(_RECORD, _SCHEDULE)
    for p in patches:
        p.start()
    try:
        out = playoff_sim.simulate_trade_impact(
            _snapshot(divisions=0), strength_delta={"a": 20.0}, n_simulations=400
        )
    finally:
        for p in patches:
            p.stop()
    assert "unsimulable" not in out
    assert out["nSimulations"] == 400
    assert {r["ownerId"] for r in out["playoff"]} == set(_OWNERS)
