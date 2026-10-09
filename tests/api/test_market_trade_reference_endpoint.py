"""Route tests for ``GET /api/market/trades/reference`` (C3-CALC-01 / TC-07).

The projection itself is pinned in ``tests/trade/test_market_trade_reference.py``;
these pin the route: the private API gate, league resolution, query parsing
(comma-separated, one value per key as the Next bridge forwards it), the
unavailable state and that names come from the loaded board.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from src.trade import market_trade_archive as archive
from src.trade import market_trade_format as mtf
from src.trade import market_trade_reference as ref
from src.trade import market_trade_report as report

LEAGUE = "main"


def _registry(tmp_path):
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": LEAGUE,
                "leagues": [
                    {
                        "key": LEAGUE,
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _ktc_group(gid, date_, sides):
    fmt = mtf.format_from_ktc_settings({"teams": 12, "tep": 1})
    return {
        "underlyingTradeId": gid,
        "dedupeState": "CONFIRMED_UNIQUE",
        "members": [f"ktc_trade_database:{gid}"],
        "observationCount": 1,
        "sourceFamilies": ["ktc_trade_database"],
        "provenance": ["KTC_MARKET"],
        "possibleOverlapWith": [],
        "representativeObservationId": f"ktc_trade_database:{gid}",
        "occurredDate": date_,
        "occurredAtMs": None,
        "teamCount": 2,
        "sides": sides,
        "formatSource": "ktc_vendor_settings",
        "formatEvidence": None,
        "_format": fmt,
        "marketFormat": fmt.to_dict(),
        "caveats": [],
        "targetLeague": "dynasty_main",
        "disposition": "BROAD_CONTEXT",
        "strongestUnsupportedAxis": None,
        "targetPriceAuthority": 0,
    }


def _player(sid):
    cid = f"player:{sid}"
    return {"kind": "player", "canonicalId": cid, "matchKey": cid}


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(_registry(tmp_path)))
    league_registry.reload_registry()
    monkeypatch.setattr(archive, "DEFAULT_DIR", tmp_path / "market_trades")
    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {
            "playersArray": [
                {"playerId": "6794", "canonicalName": "Justin Jefferson", "position": "WR"}
            ]
        },
    )
    yield tmp_path
    league_registry.reload_registry()


def _build(tmp_path, today_iso="2026-10-01"):
    report.persist_canonical_ledger(
        [_ktc_group("utrade:k1", today_iso, [[_player("6794")], [_player("7564")]])],
        root=tmp_path / "market_trades",
        built_at="2026-10-08T08:52:00Z",
        extra_meta={"targetLeague": "dynasty_main"},
    )


def test_anonymous_request_is_refused_by_the_private_gate(env):
    _build(env)
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades/reference?players=6794")
    assert resp.status_code == 401


def test_unavailable_without_a_ledger(env, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades/reference?players=6794")
    assert resp.status_code == 503
    body = resp.json()
    assert body["error"] == "trade_ledger_unavailable"
    assert body["state"] == "unavailable" and body["trades"] == []


def test_ok_with_board_names_and_csv_parsing(env, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    # Pin "today" so the fixture date stays inside the lookback.
    real = ref.reference_trades
    monkeypatch.setattr(
        ref,
        "reference_trades",
        lambda *a, **k: real(*a, **{**k, "today": date(2026, 10, 8)}),
    )
    _build(env)
    with TestClient(server.app) as c:
        resp = c.get(
            "/api/market/trades/reference",
            params={"players": "6794, 1234", "picks": "2027 Early 1st,not a pick", "limit": "5"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["leagueKey"] == LEAGUE and body["state"] == "ok"
    assert body["query"]["players"] == ["6794", "1234"]
    assert body["query"]["picks"] == ["2027 Early 1st"]
    assert body["query"]["unresolved"] == [{"ref": "not a pick", "reason": "unparseable_pick_name"}]
    assert len(body["trades"]) == 1
    assert body["trades"][0]["sides"][0][0]["label"] == "Justin Jefferson"
    assert resp.headers["cache-control"].startswith("private")


def test_unknown_league_is_400(env, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades/reference?leagueKey=nope&players=6794")
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_league"


def test_bad_limit_is_400(env, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    with TestClient(server.app) as c:
        resp = c.get("/api/market/trades/reference?players=6794&limit=abc")
    assert resp.status_code == 400
