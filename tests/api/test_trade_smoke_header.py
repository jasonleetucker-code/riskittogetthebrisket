"""The post-deploy smoke marker (``X-Chase-Smoke: 1``) on both War Room routes.

Honored ONLY for a guest-pass session, and then it skips the decision-receipt
append (the AL-P5 learning ledger must never receive synthetic smoke decisions).
For any other session the header is ignored and the decision is recorded.
"""

from __future__ import annotations

import pytest

from src.trade import trade_decision_log as tdl
from src.trade import trade_ledger as tl

# Fixtures are the multi-team route suite's own (real archived board).
from tests.api.test_trade_analyze_multi_route import (  # noqa: F401 -- fixtures
    _snap,
    _three_team,
    _two_team_ledgers,
    _war_room_request,
    app,
    flag_on,
    real_registry,
)

GUEST = {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": "g1"}
SMOKE = {"X-Chase-Smoke": "1"}


def _lines(tmp_path):
    return [line for _name, line in tdl.iter_decision_log_lines(tmp_path) if line]


def _set_session(monkeypatch, session):
    import server

    monkeypatch.setattr(server, "_get_auth_session", lambda _r: session)


def _multi(client, contract, headers):
    teams, legs = _three_team(_snap(contract))
    return teams, client.post(
        "/api/trade/analyze-multi",
        json={"leagueKey": "dynasty_main", "teams": teams, "assets": legs, "useTeamContext": False},
        headers=headers,
    )


def _two(client, contract, headers):
    snap = _snap(contract)
    teams, legs = _two_team_ledgers(snap)[0]
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
    rid = ledger.teams[0]
    body = _war_room_request(snap, rid, tl.team_flows(ledger, rid), team_context=False)
    return client.post("/api/trade/analyze", json=body, headers=headers)


# ── pure helper ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("headers", "guest", "expected"),
    [
        ({"x-chase-smoke": "1"}, True, True),
        ({"x-chase-smoke": " 1 "}, True, True),
        ({"x-chase-smoke": "1"}, False, False),
        ({"x-chase-smoke": "0"}, True, False),
        ({"x-chase-smoke": "true"}, True, False),
        ({}, True, False),
        (None, True, False),
    ],
)
def test_is_smoke_request(headers, guest, expected):
    assert tdl.is_smoke_request(headers, guest=guest) is expected


def test_record_unless_smoke_skips_only_when_smoke(tmp_path):
    analysis = {"decision": {"headline": "NO"}}
    assert (
        tdl.record_decision_unless_smoke(
            analysis, league_key="k", team="t", smoke=True, log_dir=tmp_path
        )
        is None
    )
    assert _lines(tmp_path) == []
    run_id = tdl.record_decision_unless_smoke(
        analysis, league_key="k", team="t", smoke=False, log_dir=tmp_path
    )
    assert run_id and [ln["runId"] for ln in _lines(tmp_path)] == [run_id]


# ── analyze-multi ──────────────────────────────────────────────────────────


def test_multi_guest_with_header_writes_nothing(app, flag_on, monkeypatch, tmp_path):  # noqa: F811
    client, contract = app
    _set_session(monkeypatch, GUEST)
    _teams, res = _multi(client, contract, SMOKE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["decisionRunIds"] and all(v is None for v in body["decisionRunIds"].values())
    assert _lines(tmp_path) == []


def test_multi_guest_without_header_records(app, flag_on, monkeypatch, tmp_path):  # noqa: F811
    client, contract = app
    _set_session(monkeypatch, GUEST)
    teams, res = _multi(client, contract, {})
    assert res.status_code == 200, res.text
    ids = res.json()["decisionRunIds"]
    assert len(ids) == len(teams) and all(ids.values())
    assert len(_lines(tmp_path)) == len(teams)


def test_multi_non_guest_with_header_still_records(app, flag_on, tmp_path):  # noqa: F811
    client, contract = app  # fixture session: a normal signed-in user
    teams, res = _multi(client, contract, SMOKE)
    assert res.status_code == 200, res.text
    assert all(res.json()["decisionRunIds"].values())
    assert len(_lines(tmp_path)) == len(teams)


# ── analyze (2-team) ───────────────────────────────────────────────────────


def test_two_guest_with_header_writes_nothing(app, monkeypatch, tmp_path):  # noqa: F811
    client, contract = app
    _set_session(monkeypatch, {**GUEST, "sleeper_user_id": "u1"})
    res = _two(client, contract, SMOKE)
    assert res.status_code == 200, res.text
    assert res.json()["analysis"]["decisionRunId"] is None
    assert _lines(tmp_path) == []


def test_two_guest_without_header_records(app, monkeypatch, tmp_path):  # noqa: F811
    client, contract = app
    _set_session(monkeypatch, {**GUEST, "sleeper_user_id": "u1"})
    res = _two(client, contract, {})
    assert res.status_code == 200, res.text
    assert res.json()["analysis"]["decisionRunId"]
    assert len(_lines(tmp_path)) == 1


def test_two_non_guest_with_header_still_records(app, tmp_path):  # noqa: F811
    client, contract = app
    res = _two(client, contract, SMOKE)
    assert res.status_code == 200, res.text
    assert res.json()["analysis"]["decisionRunId"]
    assert len(_lines(tmp_path)) == 1
