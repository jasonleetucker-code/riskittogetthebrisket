"""Endpoint tests for ``POST /api/waiver/best-available-idp``.

Pins: 503 when no contract is loaded, 503 ``data_not_ready`` on a league
mismatch (via the shared ``_resolve_league_for_request`` gate every other
waiver endpoint uses), the 200 response shape, and — the structural
guarantee this whole feature rests on — that a row with a strong
``rankDerivedValue`` but no ``idpTradeCalc``/``idpShowCombined`` coverage
never appears, proving the endpoint never falls back to the canonical
board.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry


@pytest.fixture
def idp_env(tmp_path, monkeypatch):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "L-SIDE",
                        "active": True,
                        "rosterSettings": {"teamCount": 10},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    yield

    league_registry.reload_registry()


def _idp_row(name, position, *, idptc=None, idpshow_rank=None, team="XX"):
    row = {
        "displayName": name,
        "canonicalName": name,
        "position": position,
        "team": team,
        "assetClass": "idp",
        "canonicalSiteValues": {},
        "sourceOriginalRanks": {},
    }
    if idptc is not None:
        row["canonicalSiteValues"]["idpTradeCalc"] = idptc
    if idpshow_rank is not None:
        row["sourceOriginalRanks"]["idpShowCombined"] = idpshow_rank
    return row


def _install_contract(monkeypatch, league_key, rows, *, rostered=None):
    sleeper = {"teams": [{"ownerId": "oA", "name": "Team A", "players": rostered or []}]}
    stub = {
        "meta": {"leagueKey": league_key},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": rows,
        "sleeper": sleeper,
        "dataFreshness": {
            "sourceTimestamps": {
                "idpTradeCalc": {"ageHours": 1.0, "staleness": "fresh"},
                "idpShowCombined": {"ageHours": 2.0, "staleness": "fresh"},
            }
        },
    }
    monkeypatch.setattr(server, "latest_contract_data", stub)
    return stub


def test_503_when_no_contract_loaded(idp_env, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", {})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/waiver/best-available-idp", json={})
    assert res.status_code == 503


def test_503_data_not_ready_on_league_mismatch(idp_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, "main", [_idp_row("A", "LB", idptc=100)])
        res = c.post("/api/waiver/best-available-idp", json={"leagueKey": "side"})
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert "side" in body["message"]


def test_200_response_shape(idp_env, monkeypatch):
    rows = [
        _idp_row("Alpha", "LB", idptc=9000, idpshow_rank=1),
        _idp_row("Bravo", "DB", idptc=8000, idpshow_rank=2),
    ]
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, "main", rows)
        res = c.post("/api/waiver/best-available-idp", json={"leagueKey": "main"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["leagueKey"] == "main"
    assert body["ownershipResolved"] is True
    assert body["availableCount"] == 2
    assert len(body["candidates"]) == 2
    assert body["sourceFreshness"]["idpTradeCalc"]["staleness"] == "fresh"
    assert body["sourceFreshness"]["idpShowCombined"]["staleness"] == "fresh"
    assert set(body["sources"].keys()) == {"idpTradeCalc", "idpShowCombined"}


def test_rostered_player_never_appears(idp_env, monkeypatch):
    rows = [_idp_row("Rostered", "LB", idptc=9999, idpshow_rank=1)]
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, "main", rows, rostered=["Rostered"])
        res = c.post("/api/waiver/best-available-idp", json={"leagueKey": "main"})
    assert res.status_code == 200, res.text
    names = {c["name"] for c in res.json()["candidates"]}
    assert "Rostered" not in names


def test_never_falls_back_to_canonical_board_value(idp_env, monkeypatch):
    """A row with a strong ``rankDerivedValue`` but no IDPTC/IDP-Show
    coverage must never appear -- proves the endpoint sources exactly
    the two named sources and nothing else."""
    row = _idp_row("CanonicalOnly", "LB")
    row["rankDerivedValue"] = 9999
    row["canonicalConsensusRank"] = 1
    row["sourceCount"] = 5
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, "main", [row])
        res = c.post("/api/waiver/best-available-idp", json={"leagueKey": "main"})
    assert res.status_code == 200, res.text
    assert res.json()["candidates"] == []


def test_no_league_key_falls_back_to_default(idp_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract(monkeypatch, "main", [_idp_row("A", "LB", idptc=100)])
        res = c.post("/api/waiver/best-available-idp", json={})
    assert res.status_code == 200, res.text
    assert res.json()["leagueKey"] == "main"
