"""Shared synthetic league for the Brisket Trade Advisor tests.

A four-team league on a temporary registry (``main`` public, ``side`` active
but not public, ``retired`` inactive), with Sleeper-style player ids, owned
picks carrying canonical ``pick:main:…`` asset ids, an IDP player per family,
an unpriced kicker and a rostered id with no board row.

``python -m tests.api.trade_advisor_support`` regenerates the frontend
contract fixtures (``frontend/__tests__/fixtures/trade-advisor/*.json``) from
REAL responses of the routes; ``test_public_trade_advisor_contract.py`` fails
whenever a response's key set drifts from the committed fixture.
"""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO / "frontend" / "__tests__" / "fixtures" / "trade-advisor"

ROSTER_SETTINGS = {
    "teamCount": 4,
    "rosterSize": 8,
    "taxiSize": 0,
    "starters": {"QB": 1, "RB": 1, "WR": 1, "TE": 1, "FLEX": 1, "DL": 1, "LB": 1, "DB": 1},
}

#: Sentinel board values: if either string ever appears in a public body or
#: header, a value leaked.
SENTINELS = (987654, 876543)


def registry_json() -> dict[str, Any]:
    return {
        "defaultLeagueKey": "main",
        "leagues": [
            {
                "key": "main",
                "displayName": "Main",
                "sleeperLeagueId": "L-MAIN",
                "active": True,
                "rosterSettings": ROSTER_SETTINGS,
            },
            {
                "key": "side",
                "displayName": "Side",
                "sleeperLeagueId": "L-SIDE",
                "active": True,
                "rosterSettings": {"teamCount": 10},
            },
            {
                "key": "retired",
                "displayName": "Retired",
                "sleeperLeagueId": "L-RET",
                "active": False,
                "rosterSettings": {},
            },
        ],
    }


def _row(pid: str, name: str, pos: str, team: str, value: float | None) -> dict[str, Any]:
    idp = pos in ("DL", "LB", "DB")
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "assetClass": "idp" if idp else "offense",
        "position": pos,
        "pos": pos,
        "team": team,
        "rankDerivedValue": value,
        "values": {"full": value} if value else {},
        "confidenceBucket": "medium",
    }


def _pick_row(name: str, value: float) -> dict[str, Any]:
    return {
        "displayName": name,
        "canonicalName": name,
        "assetClass": "pick",
        "pos": "PICK",
        "position": "PICK",
        "rankDerivedValue": value,
        "values": {"full": value},
    }


PLAYERS = [
    # id, name, pos, nfl team, value, roster
    ("101", "Alpha Quarterback", "QB", "BUF", 6000.0, 1),
    ("102", "Alpha Runner", "RB", "PHI", 3000.0, 1),
    ("103", "Alpha Receiver", "WR", "CIN", 4000.0, 1),
    ("104", "Alpha Lineman", "DL", "DET", 1500.0, 1),
    ("105", "Alpha Backer", "LB", "SF", 1200.0, 1),
    ("201", "Bravo Star", "WR", "MIN", 7000.0, 2),
    ("202", "Bravo Runner", "RB", "ATL", 2500.0, 2),
    ("203", "Bravo Safety", "DB", "KC", 900.0, 2),
    ("204", "Bravo End", "TE", "LV", 1800.0, 2),
    ("205", "Bravo Kicker", "K", "BAL", None, 2),
    ("301", "Charlie Passer", "QB", "CHI", 5000.0, 3),
    ("302", "Charlie Wideout", "WR", "LAR", 3500.0, 3),
    ("303", "Charlie Backer", "LB", "NYJ", 1100.0, 3),
    ("401", "Delta Passer", "QB", "SEA", 4500.0, 4),
    ("402", "Delta Runner", "RB", "HOU", 2800.0, 4),
    ("403", "Delta Corner", "DB", "PIT", 1000.0, 4),
]
#: Rostered by Alpha, absent from the board entirely.
GHOST_ID = "9999"
GHOST_NAME = "Ghost Player"

TEAMS = {1: "Alpha", 2: "Bravo", 3: "Charlie", 4: "Delta"}


def _pick_detail(season: int, rnd: int, origin: int, owner: int, base: str) -> dict[str, Any]:
    tail = "(own)" if origin == owner else f"(from {TEAMS[origin]})"
    return {
        "season": season,
        "round": rnd,
        "fromRosterId": origin,
        "fromTeam": TEAMS[origin],
        "ownerRosterId": owner,
        "slot": None,
        "label": f"{base} {tail}",
        "baseLabel": base,
        "assetId": f"pick:main:{season}:r{rnd}:o{origin}",
    }


def contract() -> dict[str, Any]:
    rows = [_row(pid, name, pos, team, value) for pid, name, pos, team, value, _r in PLAYERS]
    rows += [
        _pick_row("2027 Mid 1st", 3500.0),
        _pick_row("2027 Mid 2nd", 1500.0),
        _pick_row("2028 Mid 1st", 3300.0),
    ]
    teams = []
    for rid, name in TEAMS.items():
        ids = [pid for pid, _n, _p, _t, _v, r in PLAYERS if r == rid]
        names = [n for _pid, n, _p, _t, _v, r in PLAYERS if r == rid]
        if rid == 1:
            ids.append(GHOST_ID)
            names.append(GHOST_NAME)
        teams.append(
            {
                "name": name,
                "sleeperTeamName": f"The {name}s",
                "roster_id": rid,
                "ownerId": f"owner{rid}",
                "players": names,
                "playerIds": ids,
                "pickOwnershipState": "observed",
                "pickOwnershipReason": None,
            }
        )
    teams[0]["pickDetails"] = [
        _pick_detail(2027, 1, 1, 1, "2027 Mid 1st"),
        _pick_detail(2027, 2, 2, 1, "2027 Mid 2nd"),
    ]
    teams[1]["pickDetails"] = [
        _pick_detail(2027, 1, 2, 2, "2027 Mid 1st"),
        _pick_detail(2028, 1, 2, 2, "2028 Mid 1st"),
    ]
    teams[2]["pickDetails"] = [
        _pick_detail(2027, 1, 3, 3, "2027 Mid 1st"),
        _pick_detail(2027, 2, 3, 3, "2027 Mid 2nd"),
    ]
    teams[3]["pickDetails"] = [
        _pick_detail(2027, 1, 4, 4, "2027 Mid 1st"),
        _pick_detail(2028, 1, 4, 4, "2028 Mid 1st"),
    ]
    for t in teams:
        t["picks"] = [d["label"] for d in t["pickDetails"]]
    id_to_player = {pid: n for pid, n, _p, _t, _v, _r in PLAYERS}
    id_to_player[GHOST_ID] = GHOST_NAME
    return {
        "generatedAt": "2026-10-19T12:00:00+00:00",
        "scrapeTimestamp": "2026-10-19T11:58:00+00:00",
        "meta": {"leagueKey": "main"},
        "playersArray": rows,
        "sleeper": {
            "teams": teams,
            # Live rosters fetched an hour ago: ``current`` by the ONE roster
            # freshness reader (src/api/roster_freshness.py), so ownership is
            # provable.  Stale / unknown rosters are their own tests.
            "rosterSource": "live",
            "rosterFetchedAt": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "idToPlayer": id_to_player,
            "positions": {n: p for _pid, n, p, _t, _v, _r in PLAYERS},
            "playerIds": {n: pid for pid, n, _p, _t, _v, _r in PLAYERS},
        },
    }


def with_sentinels(c: dict[str, Any]) -> dict[str, Any]:
    """A copy whose two most valuable players carry the sentinel values."""
    c = copy.deepcopy(c)
    for row in c["playersArray"]:
        if row.get("playerId") == "201":
            row["rankDerivedValue"] = float(SENTINELS[0])
            row["values"] = {"full": float(SENTINELS[0])}
        if row.get("playerId") == "101":
            row["rankDerivedValue"] = float(SENTINELS[1])
            row["values"] = {"full": float(SENTINELS[1])}
    return c


def decision(
    headline: str,
    *,
    leaning: str = "LEAN_MAKE",
    direction: str | None = "favors",
    magnitude: str | None = "modest",
    deciding: str = "objectiveValue",
    gaps: list[str] | None = None,
) -> dict[str, Any]:
    """A minimal ``decide()``-shaped dict for mapping / wiring tests."""
    out: dict[str, Any] = {
        "headline": headline,
        "leaning": leaning,
        "deciding": deciding,
        "missingEvidence": [
            {"code": g, "text": "x", "evidence": {"assets": []}} for g in (gaps or [])
        ],
        "components": {},
    }
    if headline in ("YES", "NO", "NO_TOO_CLOSE") and deciding != "executionGate":
        out["components"] = {
            "objectiveValue": {"direction": direction, "magnitude": magnitude},
            "rosterBenefit": {"evaluated": False},
        }
    return out


def key_shape(obj: Any) -> Any:
    """The nested KEY structure of a JSON value (values discarded).  Lists
    collapse to the sorted set of their item shapes, so a list of players and
    picks is compared as {player shape, pick shape}."""
    if isinstance(obj, dict):
        return {k: key_shape(v) for k, v in sorted(obj.items())}
    if isinstance(obj, list):
        shapes = {json.dumps(key_shape(v), sort_keys=True) for v in obj}
        return sorted(shapes)
    return None


def write_fixture(name: str, body: Any) -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURE_DIR / name).write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n")


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text())


POSTURE = {
    "available": True,
    "label": "PUSH",
    "evidence": "measured",
    "probabilities": {"PUSH": 0.7, "HOLD": 0.2, "RETOOL": 0.05, "REBUILD": 0.05},
    "confidence": "medium",
    "paramsVersion": "posture_v1_prior",
}

#: League-scored projections injected at the best-ball seam so Team Context
#: lenses are measurable in tests (the WIRING is under test, not the data).
PPG = {
    "alpha quarterback": 21.0,
    "alpha runner": 12.0,
    "alpha receiver": 14.0,
    "alpha lineman": 7.0,
    "alpha backer": 8.0,
    "bravo star": 19.0,
    "bravo runner": 10.0,
    "bravo safety": 6.0,
    "bravo end": 9.0,
    "charlie passer": 18.0,
    "charlie wideout": 13.0,
    "charlie backer": 7.5,
    "delta passer": 17.0,
    "delta runner": 11.0,
    "delta corner": 5.5,
}


def install_league(monkeypatch, tmp_path, *, enabled: bool = True, posture=None) -> None:
    """Registry, flag, projections and posture seams for one test."""
    from src.api import feature_flags, league_registry, rate_limit, trade_simulator
    from src.api import public_trade_advisor_api as api
    from src.roster_intel import best_ball_utility as bbu

    path = tmp_path / "registry.json"
    path.write_text(json.dumps(registry_json()), encoding="utf-8")
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "1" if enabled else "0")
    feature_flags.reload()
    api.reset_for_tests()
    rate_limit.reset_for_tests()

    by_id = {pid: PPG[name.lower()] for pid, name, *_rest in PLAYERS if name.lower() in PPG}

    def fake_ppg(ids, season, scoring_settings):
        return (
            {i: by_id[str(i)] for i in ids if str(i) in by_id},
            {"state": "available", "source": "TEST_PROJECTIONS", "season": season},
        )

    monkeypatch.setattr(bbu, "league_scored_ppg_by_id", fake_ppg)
    monkeypatch.setattr("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026)
    block = POSTURE if posture is None else posture
    monkeypatch.setattr(
        trade_simulator,
        "competitive_posture_for",
        lambda contract, league_key, team, *, build_if_missing: dict(block),
    )


def teardown_league() -> None:
    from src.api import feature_flags, league_registry, rate_limit
    from src.api import public_trade_advisor_api as api

    league_registry.reload_registry()
    feature_flags.reload()
    api.reset_for_tests()
    rate_limit.reset_for_tests()


import pytest  # noqa: E402


@pytest.fixture(scope="module", name="_advisor_app")
def advisor_app_fixture(tmp_path_factory):
    """One TestClient (one lifespan startup) per test module."""
    from fastapi.testclient import TestClient

    import server

    mp = pytest.MonkeyPatch()
    install_league(mp, tmp_path_factory.mktemp("advisor"))
    try:
        with TestClient(server.app) as client:
            yield client, mp
    finally:
        mp.undo()
        teardown_league()


@pytest.fixture(name="advisor_client")
def advisor_client_fixture(_advisor_app, monkeypatch):
    """The module's client with a fresh synthetic contract, flag ON, and the
    advisor / limiter state reset for this test."""
    import server
    from src.api import feature_flags, rate_limit
    from src.api import public_trade_advisor_api as api

    client, _mp = _advisor_app
    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "1")
    feature_flags.reload()
    api.reset_for_tests()
    rate_limit.reset_for_tests()
    monkeypatch.setattr(server, "latest_contract_data", contract())
    # A launched box has a measured response floor; the launch gate itself is
    # pinned in test_public_trade_advisor_validation.
    monkeypatch.setattr(api, "_launch_gate_reason", lambda: None)
    yield client
    feature_flags.reload()
    api.reset_for_tests()
    rate_limit.reset_for_tests()


ANALYZE = "/api/public/league/trade-advisor/analyze"
TEAMS_URL = "/api/public/league/trade-advisor/teams"


def assets_url(rid: Any, sort: str | None = None) -> str:
    base = f"/api/public/league/trade-advisor/teams/{rid}/assets"
    return base if sort is None else f"{base}?sort={sort}"


def two_team_body(*legs: tuple[str, int, int], perspective: int = 1, teams=(1, 2)) -> dict:
    return {
        "perspectiveRosterId": perspective,
        "teams": list(teams),
        "assets": [{"id": a, "from": f, "to": t} for a, f, t in legs],
    }


#: Any team count — the name ``two_team_body`` predates multi-team support.
trade_body = two_team_body


def stale_contract() -> dict[str, Any]:
    """Rosters restored from the last good snapshot: ``stale`` by the ONE
    roster freshness reader, so ownership is unprovable (SD-7)."""
    c = contract()
    c["sleeper"]["rosterSource"] = "last_good"
    c["sleeper"]["rosterFetchedAt"] = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    return c


# Named trades (values: 101 6000, 201 7000, 105 1200, 303 1100, 403 1000,
# 202 2500, 402 2800).  Fairness is the band owner's verdict, never asserted
# from these numbers in a public body.
FAIR_TWO = [("p:105", 1, 3), ("p:303", 3, 1)]  # |gap| 100 < 250 -> fair both
NOT_FAIR_TWO = [("p:101", 1, 2), ("p:201", 2, 1)]  # 1000 / 7000 = 14% -> unfair
FAIR_THREE = [("p:105", 1, 3), ("p:303", 3, 4), ("p:403", 4, 1)]  # each |gap| <= 200
MIXED_FOUR = [  # 1<->3 fair; 2<->4 300 / 2800 = 10.7% -> not fair
    ("p:105", 1, 3),
    ("p:303", 3, 1),
    ("p:202", 2, 4),
    ("p:402", 4, 2),
]


if __name__ == "__main__":  # pragma: no cover — fixture regeneration
    import sys

    sys.exit(
        "Regenerate with: REGENERATE_TRADE_ADVISOR_FIXTURES=1 python -m pytest "
        "tests/api/test_public_trade_advisor_contract.py -q"
    )
