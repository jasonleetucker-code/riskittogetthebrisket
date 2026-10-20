"""Brisket Trade Advisor — the FAIRNESS-ONLY public contract (spec §4), pinned
against REAL responses.

The backend commits ``frontend/__tests__/fixtures/trade-advisor/*.json`` (one
body per case, plus ``index.json`` naming each case's endpoint and HTTP
status).  The frontend's tests and route mocks consume those files
byte-for-byte; this test fails whenever a real response's KEY SET drifts from
its fixture, so the two halves cannot silently disagree about the contract.

Regenerate after a deliberate contract change with::

    REGENERATE_TRADE_ADVISOR_FIXTURES=1 python -m pytest \
        tests/api/test_public_trade_advisor_contract.py -q
"""

from __future__ import annotations

import copy
import os
import re

import pytest

import server
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)

REGENERATE = os.environ.get("REGENERATE_TRADE_ADVISOR_FIXTURES") == "1"


def _no_picks_contract():
    c = S.contract()
    team = c["sleeper"]["teams"][1]
    team["pickOwnershipState"] = "unavailable"
    team["pickOwnershipReason"] = "traded_picks_fetch_failed"
    team["pickDetails"] = None
    team["picks"] = None
    return c


#: name -> (method, path, body or None, setup or None, status)
CASES: dict[str, tuple] = {
    "teams.success": ("GET", S.TEAMS_URL, None, None, 200),
    "teams.rosters-stale": ("GET", S.TEAMS_URL, None, "stale", 200),
    "assets.position_alpha": ("GET", S.assets_url(1, "position_alpha"), None, None, 200),
    "assets.pick-ownership-unavailable": ("GET", S.assets_url(2), None, "no_picks", 200),
    "analyze.fair-two-team": (
        "POST",
        S.ANALYZE,
        S.trade_body(*S.FAIR_TWO, teams=(1, 3)),
        None,
        200,
    ),
    "analyze.not-fair-two-team": ("POST", S.ANALYZE, S.trade_body(*S.NOT_FAIR_TWO), None, 200),
    "analyze.three-team-fair": (
        "POST",
        S.ANALYZE,
        S.trade_body(*S.FAIR_THREE, teams=(1, 3, 4)),
        None,
        200,
    ),
    "analyze.four-team-mixed": (
        "POST",
        S.ANALYZE,
        S.trade_body(*S.MIXED_FOUR, teams=(1, 2, 3, 4), perspective=2),
        None,
        200,
    ),
    "analyze.unable-asset": (
        "POST",
        S.ANALYZE,
        S.trade_body(("p:9999", 1, 2), ("p:202", 2, 1)),
        None,
        200,
    ),
    "analyze.unable-stale-rosters": (
        "POST",
        S.ANALYZE,
        S.trade_body(*S.FAIR_TWO, teams=(1, 3)),
        "stale",
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
    "error.invalid-request-sort": ("GET", S.assets_url(1, "value_desc"), None, None, 400),
    "error.invalid-trade-one-sided": (
        "POST",
        S.ANALYZE,
        S.trade_body(("p:103", 1, 2), ("p:302", 3, 2), teams=(1, 2, 3)),
        None,
        400,
    ),
    "error.invalid-trade-duplicate-asset": (
        "POST",
        S.ANALYZE,
        S.trade_body(("p:103", 1, 2), ("p:103", 1, 2), ("p:202", 2, 1)),
        None,
        400,
    ),
    "error.invalid-trade-perspective": (
        "POST",
        S.ANALYZE,
        S.trade_body(*S.NOT_FAIR_TWO, perspective=3),
        None,
        400,
    ),
    "error.unknown-league": ("GET", S.TEAMS_URL + "?leagueKey=nope", None, None, 400),
    "error.league-not-public": ("GET", S.TEAMS_URL + "?leagueKey=side", None, None, 404),
    "error.unknown-team": ("GET", S.assets_url(7), None, None, 404),
    "error.stale-assets": (
        "POST",
        S.ANALYZE,
        S.trade_body(("p:201", 1, 2), ("p:202", 2, 1)),
        None,
        409,
    ),
    "error.payload-too-large": ("POST", S.ANALYZE, b"{" + b" " * 20000 + b"}", None, 413),
    "error.unsupported-media-type": ("POST", S.ANALYZE, "text", None, 415),
    "error.rate-limited": ("POST", S.ANALYZE, S.trade_body(*S.NOT_FAIR_TWO), "rate", 429),
    "error.disabled": ("GET", S.TEAMS_URL, None, "disabled", 503),
    "error.not-ready": ("GET", S.TEAMS_URL, None, "not_ready", 503),
}


def _run(client, monkeypatch, name: str):
    method, path, body, setup, _status = CASES[name]
    if setup == "stale":
        monkeypatch.setattr(server, "latest_contract_data", S.stale_contract())
    elif setup == "no_picks":
        monkeypatch.setattr(server, "latest_contract_data", _no_picks_contract())
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


#: Values that legitimately change between runs (clock-derived) — compared by
#: shape only.
_VOLATILE = {"asOf", "generation"}


@pytest.mark.parametrize("name", sorted(CASES))
def test_real_response_matches_committed_fixture(advisor_client, monkeypatch, name):
    res = _run(advisor_client, monkeypatch, name)
    _method, _path, _body, _setup, status = CASES[name]
    assert res.status_code == status, (name, res.status_code, res.text)
    body = res.json()
    if REGENERATE:
        S.write_fixture(f"{name}.json", body)
        return
    fixture = S.load_fixture(f"{name}.json")
    assert S.key_shape(body) == S.key_shape(fixture), name

    def strip(obj):
        if isinstance(obj, dict):
            return {k: (None if k in _VOLATILE else strip(v)) for k, v in obj.items()}
        if isinstance(obj, list):
            return [strip(v) for v in obj]
        return obj

    # The fixture is a REAL response: every non-clock value must match too.
    assert strip(body) == strip(fixture), name


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


def test_fixtures_cover_every_public_result_and_team_count():
    seen_results: set[str] = set()
    seen_counts: set[int] = set()
    for name in CASES:
        if not name.startswith("analyze."):
            continue
        body = S.load_fixture(f"{name}.json")
        seen_counts.add(body["teamCount"])
        seen_results.add(body["overall"]["result"])
        seen_results |= {t["result"] for t in body["teams"]}
    assert seen_results == {"FAIR", "NOT_FAIR", "UNABLE_TO_DETERMINE"}
    assert seen_counts == {2, 3, 4}


def test_no_fixture_uses_retired_contract_vocabulary():
    """The 5-way category, ACCEPT/DECLINE recommendations, the value sorts and
    ``multi_team_unsupported`` are gone from every fixture."""
    retired = re.compile(
        r"STRONGLY_|FAVORABLE|APPROXIMATELY_EVEN|ACCEPT|DECLINE|value_desc\"|"
        r"value_asc|multi_team_unsupported|roster_limit|\"category\"|"
        r"\"recommendation\"|\"multiTeam\"",
        re.IGNORECASE,
    )
    for path in S.FIXTURE_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        if path.name == "index.json":
            continue
        assert not retired.search(text), (path.name, retired.search(text).group(0))
