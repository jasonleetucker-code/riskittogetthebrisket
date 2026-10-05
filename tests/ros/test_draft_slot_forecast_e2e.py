"""B6 producer → consumer: the season sim's slot forecast reaches the finder.

The review that found these defects (2026-10-04) noted the unit tests handed
``owned_pick_forecasts`` hand-built integers, while the real simulator wrote a
float — so in production every forecast silently carried zero weight.  These
tests run the REAL ``simulate_playoff_odds``, round-trip its payload through
JSON exactly as the cache does, and feed it to the consumer.
"""

from __future__ import annotations

import json
import random
from types import SimpleNamespace
from unittest import mock

import pytest

from src.public_league import playoff_odds
from src.ros import playoff_sim
from src.trade.pick_market import PROVISIONAL_CONFIDENCE_CAP, owned_pick_forecasts

_NAMES = ["aa", "bb", "cc", "dd"]
_CONTRACT = {
    "sleeper": {"teams": [{"ownerId": o, "roster_id": i + 1} for i, o in enumerate(_NAMES)]}
}


def _snapshot():
    season = SimpleNamespace(
        season="2026",
        league_id="L1",
        league={"settings": {"playoff_teams": 2, "playoff_week_start": 15}},
        rosters=[],
        matchups_by_week={},
        regular_season_weeks=[],
    )
    return SimpleNamespace(
        managers=SimpleNamespace(by_owner_id={}), current_season=season, seasons=[season]
    )


def _simulate(*, record, schedule, final_weeks, pf=None, means=None, sd=10.0, sims=400):
    means = means or {"aa": 80.0, "bb": 95.0, "cc": 110.0, "dd": 125.0}
    pf = pf or {o: 0.0 for o in _NAMES}
    dists = {
        o: playoff_sim._TeamDist(owner_id=o, mean=means[o], sd=sd, pf_to_date=pf[o]) for o in _NAMES
    }
    with (
        mock.patch.object(playoff_sim, "_current_record", lambda *a, **k: record),
        mock.patch.object(playoff_sim, "_remaining_schedule", lambda *a, **k: schedule),
        mock.patch.object(playoff_sim, "_load_ros_strength_map", lambda *a, **k: {}),
        mock.patch.object(playoff_sim, "_league_best_ball", lambda *a, **k: False),
        mock.patch.object(
            playoff_sim, "_build_team_distributions", lambda *a, **k: (dists, dict(pf))
        ),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: set(final_weeks)),
        mock.patch(
            "src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: "dynasty_main"
        ),
    ):
        out = playoff_sim.simulate_playoff_odds(
            _snapshot(),
            n_simulations=sims,
            min_simulations=sims,
            max_simulations=sims,
            rng=random.Random(3),
        )
    return json.loads(json.dumps(out))  # exactly what the cache hands back


def _mid_season_record():
    return {o: {"wins": 3, "losses": 4, "ties": 0} for o in _NAMES}


def _schedule(weeks):
    return [
        (w, _NAMES[i], _NAMES[j])
        for w in weeks
        for i in range(len(_NAMES))
        for j in range(i + 1, len(_NAMES))
    ]


def test_a_real_mid_season_simulation_gives_the_forecast_weight():
    out = _simulate(
        record=_mid_season_record(), schedule=_schedule(range(8, 15)), final_weeks=range(1, 8)
    )
    assert out["regularSeasonProgress"] == {"weeksFinal": 7, "weeksTotal": 14, "complete": False}
    forecasts = owned_pick_forecasts(out, _CONTRACT)
    assert set(forecasts) == {1, 2, 3, 4}
    year, f = forecasts[1]
    assert year == 2027
    # Half the regular season final → half the provisional cap.  Not 0 (the
    # float/int defect) and not the over-count the game-unit mismatch gave.
    assert f.confidence == pytest.approx(PROVISIONAL_CONFIDENCE_CAP * 7 / 14)
    assert f.provenance["confidenceBasis"] == "provisional_season_progress"
    # The weakest team leans Early.
    assert f.probabilities["early"] > f.probabilities["late"]


def test_unposted_future_matchups_are_not_a_finished_season():
    # Week 8 onward never posted: the remaining schedule is EMPTY mid-season.
    out = _simulate(record=_mid_season_record(), schedule=[], final_weeks=range(1, 8))
    assert out["regularSeasonProgress"]["complete"] is False
    f = owned_pick_forecasts(out, _CONTRACT)[1][1]
    assert f.confidence < 1.0
    assert f.provenance["confidenceBasis"] != "final_standings_observed"


def test_a_finished_season_is_observed_standings():
    out = _simulate(record=_mid_season_record(), schedule=[], final_weeks=range(1, 15))
    assert out["regularSeasonProgress"]["complete"] is True
    f = owned_pick_forecasts(out, _CONTRACT)[1][1]
    assert (f.confidence, f.provenance["confidenceBasis"]) == (1.0, "final_standings_observed")


def test_a_tied_game_counts_half_a_win_in_the_draft_order():
    # Season over.  aa 3-4-0 and bb 3-3-1: bb's record is 3.5, so aa picks
    # before bb even though aa scored MORE points.  Seeding from wins alone
    # would tie them at 3 and hand bb (lower PF) the earlier pick.
    record = {
        "aa": {"wins": 3, "losses": 4, "ties": 0},
        "bb": {"wins": 3, "losses": 3, "ties": 1},
        "cc": {"wins": 5, "losses": 2, "ties": 0},
        "dd": {"wins": 6, "losses": 1, "ties": 0},
    }
    pf = {"aa": 1000.0, "bb": 900.0, "cc": 1100.0, "dd": 1200.0}
    out = _simulate(record=record, schedule=[], final_weeks=range(1, 15), pf=pf)
    rows = {r["ownerId"]: r for r in out["playoffOdds"]}
    assert rows["aa"]["draftSlotDistribution"][0] == pytest.approx(1.0)
    assert rows["bb"]["draftSlotDistribution"][1] == pytest.approx(1.0)
    assert rows["bb"]["finalWins"]["mean"] == pytest.approx(3.5)


def test_unknown_regular_season_length_is_unknown_progress():
    snap = _snapshot()
    snap.current_season.league = {"settings": {"playoff_teams": 2}}
    structure = playoff_sim.resolve_playoff_structure(snap.current_season)
    assert playoff_sim._regular_season_progress(snap, structure) == {
        "weeksTotal": None,
        "weeksFinal": None,
        "complete": None,
    }
