"""CW-49 repairs in the canonical playoff engine (owner directive 2026-11-07).

1. DIVISIONS.  Sleeper qualifies every division winner for the playoffs
   ("If there are divisions, then each division winner will qualify for the
   playoffs" — https://sleeper.com/blog/how-do-fantasy-playoffs-work), whatever
   its overall record.  ``simulate_playoff_odds`` seeds on overall record and
   Points For only and never read ``settings.divisions``, so a league with
   divisions ON was simulated as if it had none.  Not hypothetical: the live
   ``dynasty_main`` stated ``divisions: 3`` on 2026-10-26
   (``docs/audits/evidence/league_rules_dynasty_main_2026-10-26.json``) and
   ``divisions: 0`` on 2026-11-07.  PLAYOFF_PREDICTOR_SPEC §3 requires the
   division / wild-card rule or a fail-closed refusal; the host's seeding of
   division winners is not verified, so the engine now refuses with a named
   reason.  A division winner with a losing record is the counter-example the
   engine could not express: it would publish that team's playoff odds as 0.

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


def _patched(record, schedule):
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
        mock.patch(
            "src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: "dynasty_main"
        ),
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
    ],
)
def test_the_structure_reads_the_divisions_setting(raw, divisions, in_play, reason):
    structure = resolve_playoff_structure(_season(divisions=raw))
    assert structure.divisions == divisions
    assert structure.divisions_in_play is in_play
    assert structure.divisions_reason == reason
    assert structure.to_dict()["divisions"] == divisions


# ── the engine refuses a league with divisions ON ──────────────────────


def test_a_league_with_divisions_is_refused_with_a_named_reason_not_simulated():
    out = _simulate(_snapshot(divisions=3))
    assert out["playoffOdds"] == []
    assert out["n_simulations"] == 0
    assert out["unsimulable"]["reason"] == "league_divisions_unmodeled"
    assert out["unsimulable"]["divisions"] == 3
    assert "not a 0% chance" in out["unsimulable"]["detail"]
    assert out["playoffStructure"]["divisions"] == 3


def test_an_unreadable_divisions_setting_is_refused_too():
    out = _simulate(_snapshot(divisions="three"))
    assert out["playoffOdds"] == []
    assert out["unsimulable"]["reason"] == "divisions_setting_not_recognised"


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
