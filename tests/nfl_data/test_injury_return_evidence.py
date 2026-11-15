"""ESPN per-player return evidence (src/nfl_data/injury_return_evidence.py).

No network: a fake fetcher serves recorded-shape payloads.  The Dart payload
is the shape ESPN served on 2026-10-17 (IR, returnDate 2027-01-17) for a
player whose Sleeper record carries no espn_id — the case the league-wide
feed's 25-per-team cap dropped.
"""

from __future__ import annotations

import urllib.error

from src.identity.resolution import build_sleeper_index
from src.nfl_data import injury_return_evidence as ire

DIRECTORY = {
    "12508": {
        "player_id": "12508",
        "full_name": "Jaxson Dart",
        "first_name": "Jaxson",
        "last_name": "Dart",
        "position": "QB",
        "team": "NYG",
        "fantasy_positions": ["QB"],
        "active": True,
    },
    "777": {
        "player_id": "777",
        "full_name": "Healthy Guy",
        "first_name": "Healthy",
        "last_name": "Guy",
        "position": "WR",
        "team": "NYG",
        "espn_id": "999",
        "fantasy_positions": ["WR"],
        "active": True,
    },
}


def _roster(team="NYG", dart_group="injuredReserveOrOut"):
    return {
        "team": {"abbreviation": team},
        "athletes": [
            {
                "position": dart_group,
                "items": [
                    {
                        "id": "4689114",
                        "displayName": "Jaxson Dart",
                        "position": {"abbreviation": "QB"},
                        "injuries": [{"status": "Injured Reserve", "date": "2026-09-30T20:35Z"}],
                    }
                ],
            },
            {
                "position": "offense",
                "items": [
                    {
                        "id": "999",
                        "displayName": "Healthy Guy",
                        "position": {"abbreviation": "WR"},
                        "injuries": [],
                    }
                ],
            },
        ],
    }


DART_ATHLETE = {
    "athlete": {
        "injuries": [
            {
                "status": "Injured Reserve",
                "date": "2026-09-30T20:35:00.000+00:00",
                "type": {"abbreviation": "IR"},
                "details": {
                    "fantasyStatus": {"abbreviation": "IR"},
                    "type": "Knee - Meniscus",
                    "detail": "Surgery",
                    "returnDate": "2027-01-17T00:00Z",
                },
            }
        ]
    }
}


class Fetch:
    def __init__(self, roster_teams=None, fail_roster=(), fail_athlete=False):
        self.calls: list[str] = []
        self.roster_teams = roster_teams or {19: _roster()}
        self.fail_roster = set(fail_roster)
        self.fail_athlete = fail_athlete

    def __call__(self, url):
        self.calls.append(url)
        if "/roster" in url:
            team_id = int(url.split("/teams/")[1].split("/")[0])
            if team_id in self.fail_roster:
                raise urllib.error.URLError("down")
            return self.roster_teams.get(team_id, {"team": {}, "athletes": []})
        if self.fail_athlete:
            raise urllib.error.URLError("down")
        return DART_ATHLETE


def _index():
    return build_sleeper_index(DIRECTORY)


def test_dart_resolves_by_name_team_position_and_carries_the_return_date():
    out = ire.collect(sleeper_index=_index(), fetch=Fetch(), now=1_000.0)
    rec = out["players"]["12508"]
    assert rec["current"]["returnDate"] == "2027-01-17"
    assert rec["current"]["statusCode"] == "IR"
    assert rec["identity"].startswith("name:")
    # Only out-type athletes are fetched individually; the healthy WR is not.
    assert "777" not in out["players"]
    assert out["census"]["outType"] == 1 and out["census"]["athleteFetches"] == 1


def test_refetch_is_incremental():
    first = ire.collect(sleeper_index=_index(), fetch=Fetch(), now=1_000.0)
    f = Fetch()
    second = ire.collect(previous=first, sleeper_index=_index(), fetch=f, now=2_000.0)
    assert not any("/athletes/" in c for c in f.calls)  # report date unchanged
    assert second["players"]["12508"]["current"]["returnDate"] == "2027-01-17"
    stale = ire.collect(
        previous=first, sleeper_index=_index(), fetch=Fetch(), now=1_000.0 + 2 * 86_400
    )
    assert stale["census"]["athleteFetches"] == 1  # re-read after a day


def test_a_failed_roster_keeps_previous_records_labelled_never_healthy():
    first = ire.collect(sleeper_index=_index(), fetch=Fetch(), now=1_000.0)
    out = ire.collect(
        previous=first, sleeper_index=_index(), fetch=Fetch(fail_roster={19}), now=2_000.0
    )
    assert out["players"]["12508"]["carriedForward"] is True
    assert 19 in out["census"]["rosterFailures"]


def test_a_failed_athlete_fetch_keeps_previous_record_labelled():
    first = ire.collect(sleeper_index=_index(), fetch=Fetch(), now=1_000.0)
    changed = {19: _roster()}
    changed[19]["athletes"][0]["items"][0]["injuries"][0]["date"] = "2026-10-15T00:00Z"
    out = ire.collect(
        previous=first,
        sleeper_index=_index(),
        fetch=Fetch(roster_teams=changed, fail_athlete=True),
        now=2_000.0,
    )
    assert out["players"]["12508"]["carriedForward"] is True
    assert out["census"]["athleteFetchFailures"] == 1


def test_unresolvable_athlete_is_counted_not_guessed():
    out = ire.collect(sleeper_index=build_sleeper_index({}), fetch=Fetch(), now=1.0)
    assert out["players"] == {} and out["census"]["unresolved"] == 1


def test_write_and_load_round_trip(tmp_path):
    out = ire.collect(sleeper_index=_index(), fetch=Fetch(), now=1_000.0)
    path = tmp_path / "ev.json"
    ire.write_evidence(out, path)
    loaded = ire.load_evidence(path)
    assert loaded["players"]["12508"]["current"]["returnDate"] == "2027-01-17"
    assert ire.load_evidence(tmp_path / "missing.json") is None
