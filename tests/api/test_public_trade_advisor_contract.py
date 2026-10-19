"""Brisket Trade Advisor — the frozen §4 contract, pinned against REAL responses.

The backend commits ``frontend/__tests__/fixtures/trade-advisor/*.json`` (one
body per case, plus ``index.json`` naming each case's endpoint and HTTP
status).  The frontend's tests and route mocks consume those files; this test
fails whenever a real response's KEY SET drifts from its fixture, so the two
halves cannot silently disagree about the contract.

Regenerate after a deliberate contract change with::

    REGENERATE_TRADE_ADVISOR_FIXTURES=1 python -m pytest \
        tests/api/test_public_trade_advisor_contract.py -q
"""

from __future__ import annotations

import copy
import os
from typing import Any, Callable

import pytest

import server
from src.trade import public_advisor
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

REGENERATE = os.environ.get("REGENERATE_TRADE_ADVISOR_FIXTURES") == "1"


def _crafted(decision: dict[str, Any]) -> Callable[..., Any]:
    def fake(*_a, **_k):
        return {}, {"decision": decision}

    return fake


def _stale_contract() -> dict[str, Any]:
    c = S.contract()
    c["sleeper"]["rosterSource"] = "last_good"
    c["sleeper"]["rosterSnapshotAgeHours"] = 30.0
    return c


def _no_picks_contract() -> dict[str, Any]:
    c = S.contract()
    team = c["sleeper"]["teams"][1]
    team["pickOwnershipState"] = "unavailable"
    team["pickOwnershipReason"] = "traded_picks_fetch_failed"
    team["pickDetails"] = None
    team["picks"] = None
    return c


GOOD = [("p:103", 1, 2), ("p:202", 2, 1)]

#: name -> (method, path, body or None, setup(monkeypatch) or None, status)
CASES: dict[str, tuple] = {
    "teams.success": ("GET", S.TEAMS_URL, None, None, 200),
    "teams.rosters-stale": ("GET", S.TEAMS_URL, None, "stale", 200),
    "assets.value_desc": ("GET", S.assets_url(1, "value_desc"), None, None, 200),
    "assets.alpha": ("GET", S.assets_url(2, "alpha"), None, None, 200),
    "assets.pick-ownership-unavailable": ("GET", S.assets_url(2), None, "no_picks", 200),
    "analyze.favorable": (
        "POST",
        S.ANALYZE,
        S.two_team_body(("p:101", 1, 2), ("p:201", 2, 1)),
        None,
        200,
    ),
    "analyze.strongly-unfavorable": ("POST", S.ANALYZE, S.two_team_body(*GOOD), None, 200),
    "analyze.unavailable-asset": (
        "POST",
        S.ANALYZE,
        S.two_team_body(("p:9999", 1, 2), ("p:202", 2, 1)),
        None,
        200,
    ),
    "analyze.multi-team-unsupported": (
        "POST",
        S.ANALYZE,
        S.two_team_body(("p:103", 1, 2), ("p:202", 2, 3), ("p:302", 3, 1), teams=(1, 2, 3)),
        None,
        200,
    ),
    "analyze.roster-limit": (
        "POST",
        S.ANALYZE,
        S.two_team_body(*GOOD),
        "roster_limit",
        200,
    ),
    "error.invalid-request-schema": (
        "POST",
        S.ANALYZE,
        {"perspectiveRosterId": "1", "teams": [1, 2], "assets": []},
        None,
        400,
    ),
    "error.invalid-request-json": ("POST", S.ANALYZE, b"{not json", None, 400),
    "error.invalid-request-sort": ("GET", S.assets_url(1, "value"), None, None, 400),
    "error.invalid-trade-one-sided": (
        "POST",
        S.ANALYZE,
        S.two_team_body(("p:103", 1, 2)),
        None,
        400,
    ),
    "error.invalid-trade-duplicate-asset": (
        "POST",
        S.ANALYZE,
        S.two_team_body(("p:103", 1, 2), ("p:103", 1, 2), ("p:202", 2, 1)),
        None,
        400,
    ),
    "error.unknown-league": ("GET", S.TEAMS_URL + "?leagueKey=nope", None, None, 400),
    "error.league-not-public": ("GET", S.TEAMS_URL + "?leagueKey=side", None, None, 404),
    "error.unknown-team": ("GET", S.assets_url(7), None, None, 404),
    "error.stale-assets": (
        "POST",
        S.ANALYZE,
        S.two_team_body(("p:201", 1, 2), ("p:202", 2, 1)),
        None,
        409,
    ),
    "error.payload-too-large": ("POST", S.ANALYZE, b"{" + b" " * 20000 + b"}", None, 413),
    "error.unsupported-media-type": ("POST", S.ANALYZE, "text", None, 415),
    "error.rate-limited": ("POST", S.ANALYZE, S.two_team_body(*GOOD), "rate", 429),
    "error.disabled": ("GET", S.TEAMS_URL, None, "disabled", 503),
    "error.not-ready": ("GET", S.TEAMS_URL, None, "not_ready", 503),
}


def _run(client, monkeypatch, name: str):
    method, path, body, setup, _status = CASES[name]
    if setup == "stale":
        monkeypatch.setattr(server, "latest_contract_data", _stale_contract())
    elif setup == "no_picks":
        monkeypatch.setattr(server, "latest_contract_data", _no_picks_contract())
    elif setup == "roster_limit":
        monkeypatch.setattr(
            public_advisor,
            "_engine_analyze",
            _crafted(S.decision("NO", deciding="executionGate", leaning="TOO_CLOSE")),
        )
    elif setup == "rate":
        from src.api import public_trade_advisor_api as api

        cfg = copy.deepcopy(api.advisor_config())
        cfg["rateLimits"]["perKeyBurst"] = {"capacity": 1, "windowSeconds": 600}
        monkeypatch.setattr(api, "advisor_config", lambda: cfg)
        client.post(S.ANALYZE, json=body)
    elif setup == "disabled":
        from src.api import feature_flags

        monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "0")
        feature_flags.reload()
    elif setup == "not_ready":
        monkeypatch.setattr(server, "latest_contract_data", None)
    if method == "GET":
        return client.get(path)
    if isinstance(body, bytes):
        return client.post(path, content=body, headers={"Content-Type": "application/json"})
    if isinstance(body, str):
        return client.post(path, content=body, headers={"Content-Type": "text/plain"})
    return client.post(path, json=body)


@pytest.mark.parametrize("name", sorted(CASES))
def test_real_response_matches_committed_fixture_key_set(advisor_client, monkeypatch, name):
    res = _run(advisor_client, monkeypatch, name)
    method, path, _body, _setup, status = CASES[name]
    assert res.status_code == status, (name, res.status_code, res.text)
    body = res.json()
    if REGENERATE:
        S.write_fixture(f"{name}.json", body)
        return
    fixture = S.load_fixture(f"{name}.json")
    assert S.key_shape(body) == S.key_shape(fixture), name
    # The fixture is a REAL response, so its enums are real too.
    for key in ("error", "reason", "category", "recommendation", "reasonCode", "sort"):
        if key in fixture:
            assert body[key] == fixture[key], (name, key)


def test_index_names_every_case_with_its_status_and_endpoint():
    index = {
        name: {"method": m, "path": p.split("?")[0], "status": st}
        for name, (m, p, _b, _s, st) in CASES.items()
    }
    if REGENERATE:
        S.write_fixture("index.json", index)
        return
    assert S.load_fixture("index.json") == index


def test_every_fixture_file_is_a_known_case():
    files = {p.stem for p in S.FIXTURE_DIR.glob("*.json")} - {"index"}
    assert files == set(CASES), "stale or missing fixture files"
