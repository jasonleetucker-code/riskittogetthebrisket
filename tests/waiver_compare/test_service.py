"""Roster + waiver assembly for the waiver-compare page."""

from __future__ import annotations

import json
from datetime import date

from src.waiver_compare.service import (
    WaiverCompareService,
    build_payload,
    roster_player_ids,
)

LEAGUE = {"key": "dynasty_main", "name": "Risk It To Get The Brisket", "sleeperLeagueId": "L1"}


def _row(pid, name, ktc=None, idptc=None, pos="WR", age=25):
    sites = {}
    if ktc is not None:
        sites["ktcCrowdTradesSfTep"] = ktc
    if idptc is not None:
        sites["idpTradeCalc"] = idptc
    return {
        "playerId": pid,
        "displayName": name,
        "position": pos,
        "assetClass": "offense",
        "team": "DET",
        "age": age,
        "canonicalSiteValues": sites,
        "rankDerivedValue": 9999,
    }


CONTRACT = {
    "scrapeTimestamp": "2026-10-21T18:58:55+00:00",
    "generatedAt": "g1",
    "playersArray": [
        _row("1", "Owned Star", ktc=8000, idptc=9000),
        _row("2", "Taxi Kid", ktc=3000),
        _row("3", "IR Vet", idptc=2000),
        _row("4", "Free Agent A", ktc=2400, idptc=2500),
        _row("5", "Free Agent B", ktc=3000, idptc=3001, age=None),
        _row("6", "Free Agent C", idptc=1000, pos="LB"),
        {
            "playerId": "P",
            "assetClass": "pick",
            "displayName": "2027 Early 1st",
            "canonicalSiteValues": {"ktcCrowdTradesSfTep": 6000},
        },
    ],
}

ROSTERS = [
    {"roster_id": 1, "owner_id": "u1", "players": ["1", "9"], "taxi": ["2"], "reserve": ["3"]},
    {"roster_id": 2, "owner_id": "u2", "players": None, "taxi": None, "reserve": None},
]
USERS = [
    {"user_id": "u1", "display_name": "alpha", "metadata": {"team_name": "Zeta Squad "}},
    {"user_id": "u2", "display_name": "beta", "metadata": {}},
]
NFL = {
    "9": {
        "full_name": "Unvalued Guy",
        "position": "DE",
        "fantasy_positions": ["DL"],
        "team": "NE",
        "birth_date": "2000-12-01",
    },
}


def _payload(**kw):
    args = dict(
        contract=CONTRACT,
        rosters=ROSTERS,
        users=USERS,
        nfl_players=NFL,
        league=LEAGUE,
        rosters_fetched_at="t",
        rosters_state="live",
        today=date(2026, 10, 21),
    )
    args.update(kw)
    return build_payload(**args)


def test_roster_includes_bench_taxi_and_ir():
    assert roster_player_ids(ROSTERS[0]) == ["1", "9", "2", "3"]
    assert roster_player_ids(ROSTERS[1]) == []


def test_every_team_listed_sorted_by_name():
    body = _payload()
    assert [t["teamName"] for t in body["teams"]] == ["beta", "Zeta Squad"]


def test_selected_roster_sorted_by_value_with_unvalued_last():
    body = _payload()
    zeta = next(t for t in body["teams"] if t["rosterId"] == 1)
    assert zeta["playerIds"] == ["1", "2", "3", "9"]
    unvalued = body["players"]["9"]
    assert unvalued["value"] is None and unvalued["ktc"] is None
    assert unvalued["pos"] == "DL" and unvalued["team"] == "NE" and unvalued["age"] == 25


def test_owned_players_never_on_waivers():
    body = _payload()
    assert body["waiverIds"] == ["5", "4", "6"]
    assert not {"1", "2", "3", "9"} & set(body["waiverIds"])
    assert "P" not in body["waiverIds"]


def test_values_are_exact_and_canonical_value_absent():
    p = _payload()["players"]
    assert p["1"]["value"] == 8500
    assert p["5"]["value"] == 3000.5
    assert p["2"]["value"] == 3000 and p["2"]["idptc"] is None
    for rec in p.values():
        assert set(rec) == {"id", "name", "pos", "team", "age", "ktc", "idptc", "value"}


def test_missing_age_stays_missing():
    assert _payload()["players"]["5"]["age"] is None


def test_no_sleeper_league_id_in_payload():
    assert "L1" not in json.dumps(_payload())


class _Fetch:
    def __init__(self, result):
        self.result = result
        self.calls = 0

    def __call__(self, *_a):
        self.calls += 1
        return self.result


def _svc(rosters=("ok", ROSTERS), clock=None):
    fr = _Fetch(rosters)
    svc = WaiverCompareService(
        fetch_rosters=fr,
        fetch_users=_Fetch(("ok", USERS)),
        fetch_players=lambda: NFL,
        clock=clock or (lambda: 0.0),
    )
    return svc, fr


def test_service_caches_within_ttl():
    svc, fr = _svc()
    assert svc.payload(CONTRACT, LEAGUE)[0] == 200
    assert svc.payload(CONTRACT, LEAGUE)[0] == 200
    assert fr.calls == 1


def test_roster_failure_with_no_history_is_503_not_empty_league():
    svc, _ = _svc(rosters=("error", None))
    status, body = svc.payload(CONTRACT, LEAGUE)
    assert status == 503 and body["error"] == "rosters_unavailable"


def test_roster_failure_after_success_serves_labelled_stale():
    now = [0.0]
    svc, fr = _svc(clock=lambda: now[0])
    svc.payload(CONTRACT, LEAGUE)
    fr.result = ("error", None)
    now[0] = 1000.0
    status, body = svc.payload(CONTRACT, LEAGUE)
    assert status == 200 and body["rosters"]["state"] == "stale"
    assert "1" not in body["waiverIds"]


def test_missing_contract_is_503():
    svc, _ = _svc()
    assert svc.payload(None, LEAGUE) == (503, {"ok": False, "error": "values_unavailable"})
