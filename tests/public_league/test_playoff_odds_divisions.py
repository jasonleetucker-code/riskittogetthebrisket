"""The public ``playoffOdds`` section carries division-title odds (owner 2026-11-08).

Division titles are a separate question from qualifying: the section publishes
the engine's ``divisionChampionOdds`` beside — never merged into — each team's
playoff probability, and keeps publishing them when only qualifying was
withheld (a league whose division rule is unrecorded).
"""

from __future__ import annotations

from unittest import mock

import pytest

from src.public_league import playoff_odds


def _pair(matchup_id, roster_id, points):
    return {"matchup_id": matchup_id, "roster_id": roster_id, "points": points}


_ENTRIES = {
    1: [_pair(10, 1, 120.0), _pair(10, 2, 110.0), _pair(11, 3, 95.0), _pair(11, 4, 105.0)],
    2: [_pair(20, 1, 130.0), _pair(20, 3, 115.0), _pair(21, 2, 140.0), _pair(21, 4, 98.0)],
    **{
        wk: [
            _pair(wk * 10, 1, 1.0),
            _pair(wk * 10, 2, 1.0),
            _pair(wk * 10 + 1, 3, 1.0),
            _pair(wk * 10 + 1, 4, 1.0),
        ]
        for wk in range(3, 5)
    },
}


class _Season:
    season = "2026"
    league_id = "L1"
    league = {"settings": {"playoff_week_start": 5, "playoff_teams": 2, "playoff_seed_type": 1}}
    rosters = [{"roster_id": r} for r in (1, 2, 3, 4)]
    num_teams = 4
    matchups_by_week = _ENTRIES

    @property
    def regular_season_weeks(self):
        return [1, 2, 3, 4]


class _Snapshot:
    def __init__(self):
        self._s = _Season()
        self.managers = type("R", (), {"by_owner_id": {}})()

    @property
    def current_season(self):
        return self._s


_DIVISIONS = {
    "state": "available",
    "reason": "",
    "count": 2,
    "names": {"1": "The Pit", "2": "Barbacoa"},
    "championRule": {
        "rule": "best_overall_record_in_division",
        "tiebreakers": ["points_for"],
        "affectsPlayoffs": False,
    },
}


def _rows(with_playoff=True):
    rows = []
    for rid, (playoff, div, title) in {
        1: (1.0, 1, 0.6),
        2: (0.9, 1, 0.4),
        3: (0.05, 2, 0.75),  # wins its division, misses the playoffs
        4: (0.05, 2, 0.25),
    }.items():
        row = {
            "ownerId": f"owner-{rid}",
            "expectedWins": 3.0,
            "division": div,
            "divisionName": _DIVISIONS["names"][str(div)],
            "divisionChampionOdds": title,
        }
        if with_playoff:
            row["playoffOdds"] = playoff
        rows.append(row)
    return rows


def _compute(forecast):
    with (
        mock.patch.object(playoff_odds.metrics, "display_name_for", lambda s, o: o),
        mock.patch.object(
            playoff_odds.metrics, "resolve_owner", lambda reg, lid, rid, *a: f"owner-{rid}"
        ),
        mock.patch.object(playoff_odds, "_final_week_set", lambda *a, **k: {1, 2, 3, 4}),
        mock.patch(
            "src.ros.team_strength.resolve_snapshot_league_key", lambda *a, **k: "dynasty_main"
        ),
    ):
        return playoff_odds.compute_playoff_odds(_Snapshot(), forecast=forecast)


def test_division_title_odds_travel_beside_playoff_odds_not_merged():
    out = _compute({"n_simulations": 4000, "playoffOdds": _rows(), "divisionOdds": _DIVISIONS})
    assert out["divisionOdds"] == _DIVISIONS
    by_owner = {o["ownerId"]: o for o in out["owners"]}
    assert by_owner["owner-3"]["divisionChampionProbability"] == pytest.approx(0.75)
    assert by_owner["owner-3"]["playoffProbability"] == pytest.approx(0.05)
    assert by_owner["owner-3"]["divisionName"] == "Barbacoa"
    assert by_owner["owner-2"]["divisionChampionProbability"] == pytest.approx(0.4)
    assert by_owner["owner-2"]["playoffProbability"] == pytest.approx(0.9)


def test_division_title_odds_survive_a_qualification_only_refusal():
    forecast = {
        "n_simulations": 4000,
        "playoffOdds": [],
        "regularSeasonOdds": _rows(with_playoff=False),
        "unsimulable": {"reason": "league_divisions_unmodeled", "scope": "qualification"},
        "divisionOdds": _DIVISIONS,
    }
    out = _compute(forecast)
    assert out["simulated"] is False
    assert out["unsimulable"]["scope"] == "qualification"
    for o in out["owners"]:
        assert o["playoffProbability"] is None
        assert o["divisionChampionProbability"] is not None


def test_no_division_fields_when_the_league_plays_no_divisions():
    rows = [{k: v for k, v in r.items() if not k.startswith("division")} for r in _rows()]
    out = _compute(
        {
            "n_simulations": 4000,
            "playoffOdds": rows,
            "divisionOdds": {"state": "not_applicable", "reason": "no_divisions"},
        }
    )
    assert all("divisionChampionProbability" not in o for o in out["owners"])
    assert out["divisionOdds"]["state"] == "not_applicable"
