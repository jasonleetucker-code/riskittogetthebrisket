"""/angle's IDP gate follows the league's lineup, not a constant.

Audit finding W27-F003 (root cause R7).

``find_angle_packages`` / ``find_acquisition_packages`` drop every IDP
row from the CANDIDATE pool unless ``include_idp`` is true, and the
route defaulted that to ``False``.  Nothing reachable set it — there is
no ``includeIdp`` anywhere in ``frontend/`` — so on the live UI path the
exclusion was total and one-directional: in a league that starts nine
IDP, you could give a defender and could never be offered one.

The gate itself is fine.  Its DEFAULT was a constant in a codebase
whose two live leagues disagree about IDP (``dynasty_main`` starts
DL 3 / LB 3 / DB 3, ``dynasty_new`` starts none), and per CLAUDE.md
roster settings are a leagueKey property.  So the default is read from
the league, and an explicit request value still wins in both
directions.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry

_IDP_STARTERS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1, "DL": 3, "LB": 3, "DB": 3}
_OFFENSE_STARTERS = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}


@pytest.fixture()
def registry(monkeypatch, tmp_path):
    """Two leagues on one scoring profile that disagree about IDP.

    That is the live shape: ``dynasty_main`` starts nine defenders and
    ``dynasty_new`` starts none, and they share ``superflex_tep15_ppr1``.
    """
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "defaultLeagueKey": "idp_league",
                "leagues": [
                    {
                        "key": "idp_league",
                        "displayName": "Starts Nine Defenders",
                        "sleeperLeagueId": "L-IDP",
                        "scoringProfile": "prof_a",
                        "idpEnabled": True,
                        "active": True,
                        "rosterSettings": {"teamCount": 2, "starters": _IDP_STARTERS},
                    },
                    {
                        "key": "offense_league",
                        "displayName": "Offense Only",
                        "sleeperLeagueId": "L-OFF",
                        "scoringProfile": "prof_a",
                        "idpEnabled": False,
                        "active": True,
                        "rosterSettings": {"teamCount": 2, "starters": _OFFENSE_STARTERS},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield
    league_registry.reload_registry()


def _rows() -> list[dict]:
    rows: list[dict] = []
    for i in range(12):
        rows.append(
            {
                "canonicalName": f"Off{i}",
                "displayName": f"Off{i}",
                "position": "WR",
                "rankDerivedValue": 9000 - i * 300,
                "canonicalSiteValues": {"ktcSfTep": 9000 - i * 300},
            }
        )
    for i in range(12):
        rows.append(
            {
                "canonicalName": f"Def{i}",
                "displayName": f"Def{i}",
                "position": "LB",
                "rankDerivedValue": 5000 - i * 200,
                "canonicalSiteValues": {"idpTradeCalc": 5000 - i * 200},
            }
        )
    return rows


def _contract(league_key: str) -> dict:
    return {
        "meta": {"leagueKey": league_key, "scoringProfile": "prof_a"},
        "date": "2026-07-27",
        "contractVersion": "2026-03-10.v2",
        "players": {},
        "playersArray": _rows(),
        "sleeper": {
            "teams": [
                {
                    "name": "Mine",
                    "ownerId": "owner-1",
                    "rosterId": 1,
                    "players": ["Off0", "Off1", "Def0"],
                    "picks": [],
                },
                {
                    "name": "Theirs",
                    "ownerId": "owner-2",
                    "rosterId": 2,
                    "players": ["Off2", "Off3", "Def1", "Def2"],
                    "picks": [],
                },
            ]
        },
    }


def _post(monkeypatch, league_key: str, body_extra: dict) -> dict:
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        # Install the stub INSIDE the client context: startup replaces
        # ``latest_contract_data`` with whatever it can load.
        monkeypatch.setattr(server, "latest_contract_data", _contract(league_key))
        res = c.post(
            "/api/angle/packages",
            json={
                "ownerId": "owner-1",
                "playerNames": ["Off0"],
                "leagueKey": league_key,
                **body_extra,
            },
        )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.parametrize(
    "league_key,expected",
    [("idp_league", True), ("offense_league", False)],
)
def test_default_follows_the_league(registry, monkeypatch, league_key, expected):
    body = _post(monkeypatch, league_key, {})
    assert body["thresholds"]["include_idp"] is expected


def test_an_explicit_request_value_still_wins(registry, monkeypatch):
    """Both directions — the derived default is a default, not an override."""
    off = _post(monkeypatch, "idp_league", {"includeIdp": False})
    assert off["thresholds"]["include_idp"] is False
    on = _post(monkeypatch, "offense_league", {"includeIdp": True})
    assert on["thresholds"]["include_idp"] is True


def test_acquire_mode_takes_the_same_default(registry, monkeypatch):
    body = _post(
        monkeypatch,
        "idp_league",
        {"mode": "acquire", "acquirePlayerNames": ["Off2"]},
    )
    assert body["thresholds"]["include_idp"] is True
