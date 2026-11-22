"""``/api/trade/analyze`` and the title-odds lens (DYN10 #4) — the route half.

Flag OFF (the default): the route computes nothing, passes nothing, adds no
timing stage, and the analysis is exactly the pre-lens one.  Flag ON: the
route STILL computes nothing — the odds cost ~5.5 s and are served by
``POST /api/trade/title-odds`` (``tests/api/test_trade_title_odds_async_route.py``)
— so the non-voting ``analysis.lenses.titleOdds`` is named unavailable with the
reason ``deferred_async``, no ``titleOdds`` stage is timed and the decision is
unchanged; under Asset-Only the lens is excluded by mode.  The lens computation
itself is pinned in ``tests/trade/test_title_odds_lens.py``.
"""

from __future__ import annotations

import json

import pytest

import server
from src.api import feature_flags
from src.trade import title_odds_lens as tol
from tests.api.test_league_routing import two_league_registry  # noqa: F401 — fixture
from tests.api.test_trade_analyze_runtime import (  # noqa: F401 — fixtures
    _BODY,
    STAGES,
    _app_client,
    _strip,
    client,
)

_ENV = "RISKIT_FEATURE_TRADE_TITLE_ODDS_LENS"


def _canned(owner: str = "o1") -> dict:
    return {
        "version": tol.LENS_VERSION,
        "state": "ok",
        "teams": [
            {
                "ownerId": owner,
                "displayName": "Us",
                "rosterChanged": True,
                "strengthDelta": {"ownerId": owner, "meanDelta": 3.0},
                "available": True,
                "playoff": {
                    "before": 0.4,
                    "after": 0.47,
                    "delta": 0.07,
                    "deltaCi": [0.03, 0.11],
                    "significant": True,
                },
                "championship": {
                    "before": 0.08,
                    "after": 0.09,
                    "delta": 0.01,
                    "deltaCi": [-0.01, 0.03],
                    "significant": False,
                },
            }
        ],
        "disclosure": tol.disclosure(),
        "role": "context_not_vote",
    }


@pytest.fixture
def flag(monkeypatch):
    def _set(on: bool):
        monkeypatch.setenv(_ENV, "1" if on else "0")
        feature_flags.reload()

    yield _set
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()


def test_flag_off_route_is_the_pre_lens_analysis(client, flag, monkeypatch):  # noqa: F811
    flag(False)
    called = []
    monkeypatch.setattr(
        server, "_trade_title_odds_two_team", lambda *a, **k: called.append(a) or _canned()
    )
    res = client.post("/api/trade/analyze", json=_BODY)
    assert res.status_code == 200, res.text
    body = res.json()
    assert called == []
    assert "titleOdds" not in body["analysis"]["lenses"]
    assert [s["stage"] for s in body["analysisTiming"]["stages"]] == STAGES
    reasons = {d["dimension"]: d["reason"] for d in body["analysis"]["unavailableDimensions"]}
    assert reasons["currentSeasonEquity"] == "counterfactual_not_wired"


def test_flag_on_route_defers_the_lens_and_moves_no_decision(client, flag, monkeypatch):  # noqa: F811
    """The War Room never waits for the season simulation: with the flag ON the
    analyze route computes nothing, times no ``titleOdds`` stage, and names the
    dimension ``deferred_async`` — unavailable, never a zero delta."""
    flag(False)
    off = _strip(client.post("/api/trade/analyze", json=_BODY).json())
    flag(True)
    monkeypatch.setattr(
        server,
        "_trade_title_odds_two_team",
        lambda *_a, **_k: pytest.fail("/api/trade/analyze must not compute the season odds"),
    )
    res = client.post("/api/trade/analyze", json=_BODY)
    assert res.status_code == 200, res.text
    on = res.json()
    assert [s["stage"] for s in on["analysisTiming"]["stages"]] == STAGES
    lens = on["analysis"]["lenses"]["titleOdds"]
    assert lens["votes"] is False and lens["available"] is False
    assert lens["unavailableReason"] == tol.REASON_DEFERRED_ASYNC
    assert "direction" not in lens
    assert lens["detail"]["disclosure"]["text"] == tol.ODDS_DISCLOSURE
    assert tol.ASYNC_ROUTE in lens["detail"]["note"]
    # The "not included yet" entry states the lens's own reason, not the
    # pre-lens "not wired" one.
    entries = [
        d
        for d in on["analysis"]["unavailableDimensions"]
        if d["dimension"] == "currentSeasonEquity"
    ]
    assert [d["reason"] for d in entries] == [tol.REASON_DEFERRED_ASYNC]
    on = _strip(on)
    for key in ("decision", "statusQuo", "recommendation", "confidence", "reasonsFor"):
        assert json.dumps(on["analysis"][key], sort_keys=True) == json.dumps(
            off["analysis"][key], sort_keys=True
        ), key
    # Everything outside the analysis packet is untouched.
    assert {k: v for k, v in on.items() if k != "analysis"} == {
        k: v for k, v in off.items() if k != "analysis"
    }


def test_flag_on_asset_only_computes_nothing(client, flag, monkeypatch):  # noqa: F811
    flag(True)
    called = []
    monkeypatch.setattr(
        server, "_trade_title_odds_two_team", lambda *a, **k: called.append(a) or _canned()
    )
    res = client.post("/api/trade/analyze", json={**_BODY, "useTeamContext": False})
    assert res.status_code == 200, res.text
    lens = res.json()["analysis"]["lenses"]["titleOdds"]
    assert called == []
    assert lens["available"] is False and lens["votes"] is False
    assert lens["unavailableReason"] == tol.REASON_ASSET_ONLY
    reasons = {d["dimension"]: d["reason"] for d in res.json()["analysis"]["unavailableDimensions"]}
    assert reasons["currentSeasonEquity"] == tol.REASON_ASSET_ONLY


def test_the_route_helper_refuses_an_unconfigured_league_without_reading_anything(monkeypatch):
    monkeypatch.setattr(
        server,
        "_roster_construction_snapshot",
        lambda *_a, **_k: pytest.fail("no snapshot may be read for an unconfigured league"),
    )
    out = server._trade_title_odds_two_team({"team": {"ownerId": "o1"}}, "dynasty_new", None)
    assert out["state"] == "unavailable"
    assert out["reason"] == tol.REASON_LEAGUE_NOT_CONFIGURED
