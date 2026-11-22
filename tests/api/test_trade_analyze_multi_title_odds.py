"""``/api/trade/analyze-multi`` and the title-odds lens (DYN10 #4).

With the owner-held ``trade_title_odds_lens`` flag ON the multi-team route
computes NOTHING: the season simulation (~5.5 s plus ~1.4 s per extra changed
roster) would run inside the route's admission slot (2 at once, 30 s) for a
lens the 3+-team War Room never shows.  Every team's analysis gets the deferred
envelope from ``title_odds_lens.deferred_for_ledger`` instead:

* two teams -> ``deferred_async`` (``POST /api/trade/title-odds`` serves a
  2-team trade);
* three or more -> ``not_computed_multi_team`` (that route answers 2-team
  trades only, so pointing there would be untrue);

named and unavailable, never a zero, and no decision moves.  Flag OFF passes no
provider at all, so every team's analysis stays byte-identical
(``tests/trade/test_title_odds_lens.py`` pins the composer identity).
"""

from __future__ import annotations

import json
import random

import pytest

from src.api import feature_flags
from src.trade import title_odds_lens as tol
from tests.api.test_trade_analyze_multi_route import (  # noqa: F401 — pytest fixtures
    _body,
    _snap,
    _three_team,
    app,
    flag_on,
    real_registry,
)
from tests.trade import multi_team_support as mts

_ENV = "RISKIT_FEATURE_TRADE_TITLE_ODDS_LENS"
_ROUTE = "/api/trade/analyze-multi"


@pytest.fixture
def title_odds(monkeypatch):
    def _set(on: bool):
        monkeypatch.setenv(_ENV, "1" if on else "0")
        feature_flags.reload()

    yield _set
    monkeypatch.delenv(_ENV, raising=False)
    feature_flags.reload()


def _never_compute(monkeypatch):
    import server

    def _fail(*_a, **_k):
        pytest.fail("/api/trade/analyze-multi must not compute the season odds")

    monkeypatch.setattr(tol, "title_odds_for_ledger", _fail)
    monkeypatch.setattr(tol, "compute_title_odds", _fail)
    monkeypatch.setattr(server, "_title_odds_snapshot", _fail)


def _decisions(body):
    return {
        t["rosterId"]: json.dumps(
            {k: t["analysis"][k] for k in ("decision", "recommendation", "confidence")},
            sort_keys=True,
        )
        for t in body["teams"]
    }


def _season_entries(analysis):
    return [d for d in analysis["unavailableDimensions"] if d["dimension"] == "currentSeasonEquity"]


def _check_deferred(body, reason):
    for team in body["teams"]:
        lens = team["analysis"]["lenses"]["titleOdds"]
        assert lens["votes"] is False and lens["available"] is False
        assert lens["unavailableReason"] == reason
        assert "direction" not in lens
        assert lens["detail"]["disclosure"]["text"] == tol.ODDS_DISCLOSURE
        assert [d["reason"] for d in _season_entries(team["analysis"])] == [reason]


@pytest.mark.parametrize("n_teams", [2, 3])
def test_flag_on_defers_the_lens_and_moves_no_decision(
    app,  # noqa: F811
    flag_on,  # noqa: F811
    title_odds,
    monkeypatch,
    n_teams,
):
    client, contract = app
    snap = _snap(contract)
    if n_teams == 2:
        teams, legs = mts.random_ledger(snap, random.Random(42), n_teams=2, max_per_team=2)
    else:
        teams, legs = _three_team(snap)
    body = _body(teams, legs, useTeamContext=True)
    title_odds(False)
    off = client.post(_ROUTE, json=body)
    assert off.status_code == 200, off.text
    off = off.json()
    for team in off["teams"]:
        assert "titleOdds" not in team["analysis"]["lenses"]
        assert [d["reason"] for d in _season_entries(team["analysis"])] == [
            "counterfactual_not_wired"
        ]
    title_odds(True)
    _never_compute(monkeypatch)
    on = client.post(_ROUTE, json=body)
    assert on.status_code == 200, on.text
    on = on.json()
    expected = tol.REASON_DEFERRED_ASYNC if n_teams == 2 else tol.REASON_NOT_COMPUTED_MULTI_TEAM
    _check_deferred(on, expected)
    if n_teams == 2:
        for team in on["teams"]:
            assert tol.ASYNC_ROUTE in team["analysis"]["lenses"]["titleOdds"]["detail"]["note"]
    # Context only: no team's decision moves.
    assert _decisions(on) == _decisions(off)


def test_flag_on_asset_only_is_excluded_by_mode(app, flag_on, title_odds, monkeypatch):  # noqa: F811
    client, contract = app
    teams, legs = _three_team(_snap(contract))
    title_odds(True)
    _never_compute(monkeypatch)
    res = client.post(_ROUTE, json=_body(teams, legs, useTeamContext=False))
    assert res.status_code == 200, res.text
    for team in res.json()["teams"]:
        lens = team["analysis"]["lenses"]["titleOdds"]
        assert lens["available"] is False and lens["unavailableReason"] == tol.REASON_ASSET_ONLY


def test_deferred_for_ledger_names_where_the_odds_are_served():
    class _Ledger:
        def __init__(self, teams):
            self.teams = teams

    two = tol.deferred_for_ledger(_Ledger((1, 2)))
    assert two == tol.deferred()
    assert two["reason"] == tol.REASON_DEFERRED_ASYNC and two["route"] == tol.ASYNC_ROUTE
    for teams in ((1, 2, 3), (1, 2, 3, 4)):
        many = tol.deferred_for_ledger(_Ledger(teams))
        assert many["state"] == tol.STATE_UNAVAILABLE and many["teams"] == []
        assert many["reason"] == tol.REASON_NOT_COMPUTED_MULTI_TEAM
        assert "route" not in many
        assert "two-team" in many["detail"]
