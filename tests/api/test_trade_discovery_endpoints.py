"""Discovery filters on the trade-discovery routes (owner directive 2026-10-18).

``discovery`` is optional on /api/trade/golden-upgrades, /api/trade/finder and
/api/trade/best-offers: absent = the legacy behaviour, present = validated and
applied by ``src/trade/discovery``; an unknown value is a 400, never a silent
fallback.
"""

from __future__ import annotations

import pytest

import server
from tests.api.test_golden_upgrades_endpoint import _contract
from tests.api.test_trade_protections_endpoint import env  # noqa: F401 — fixture

H = {"x-test-user": "jason"}


def _ranked_contract():
    c = _contract()
    for row in c["playersArray"]:
        row["canonicalConsensusRank"] = 160 if row["displayName"] == "Our LB" else 120
    return c


@pytest.fixture()
def authed(env, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "latest_contract_data", _ranked_contract())
    from src.trade import best_offers as _bo

    monkeypatch.setattr(_bo, "BEST_OFFERS_RUN_LOG_DIR", tmp_path / "bo")
    return env


@pytest.mark.parametrize(
    "url", ["/api/trade/golden-upgrades", "/api/trade/finder", "/api/trade/best-offers"]
)
def test_an_invalid_discovery_object_is_a_400(authed, url):
    body = {"myTeam": "Us", "leagueKey": "main", "discovery": {"targetQuality": "top42"}}
    if url.endswith("finder"):
        body["opponentTeams"] = ["Them"]
    res = authed.client.post(url, json=body, headers=H)
    assert res.status_code == 400, res.text
    assert res.json()["error"] == "invalid_discovery"


def test_golden_route_applies_target_quality(authed):
    url = "/api/trade/golden-upgrades"
    base = {"myTeam": "Us", "leagueKey": "main", "useTeamContext": False}
    ok = authed.client.post(url, json={**base, "discovery": {"targetQuality": "top250"}}, headers=H)
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["discovery"]["filters"]["targetQuality"] == "top250"
    [u] = body["upgrades"]
    assert u["target"]["rank"] == 120 and u["whyItMatters"]
    narrow = authed.client.post(
        url, json={**base, "discovery": {"targetQuality": "top100"}}, headers=H
    ).json()
    assert narrow["upgrades"] == []
    assert narrow["noResultReason"] == "no_upgrade_within_target_quality"
    assert narrow["discovery"]["broaderAvailability"]["top250"] == 1


def test_finder_route_echoes_discovery_metadata(authed):
    res = authed.client.post(
        "/api/trade/finder",
        json={
            "myTeam": "Us",
            "leagueKey": "main",
            "opponentTeams": ["Them"],
            "useTeamContext": False,
            "discovery": {"targetQuality": "top250", "playersToTarget": "defense"},
        },
        headers=H,
    )
    assert res.status_code == 200, res.text
    meta = res.json()["metadata"]["discovery"]
    assert meta["filters"]["playersToTarget"] == "defense"
    assert meta["impactPrior"]["status"] == "PRIOR_UNVALIDATED"


def test_best_offers_route_echoes_discovery(authed):
    res = authed.client.post(
        "/api/trade/best-offers",
        json={
            "myTeam": "Us",
            "leagueKey": "main",
            "useTeamContext": False,
            "discovery": {"targetQuality": "all", "sort": "absolute_gain"},
        },
        headers=H,
    )
    assert res.status_code == 200, res.text
    assert res.json()["discovery"]["filters"]["sort"] == "absolute_gain"
