"""TC-B / TCM-O12 — ``POST /api/manager-scout/offer-evidence``.

The /trade counterparty panel asks the ONE Manager Scout owner
(``manager_scout.offer_evidence``) how the opponent's own completed trades
line up with the package being built.  The route only validates, resolves
the two teams against THIS league's loaded rosters and passes through.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.acquisition import store as store_mod
from src.acquisition.events import events_from_transaction
from src.intel import manager_scout as ms
from src.intel import manager_scout_api as api
from tests.intel.test_manager_scout_endpoint import _CONTRACT, LEAGUE, OTHER, T1, scout_env  # noqa: F401

URL = "/api/manager-scout/offer-evidence"


def _post(monkeypatch, body, **params):
    with TestClient(server.app) as c:
        monkeypatch.setattr(server, "latest_contract_data", _CONTRACT)
        return c.post(URL, json=body, params=params or None)


def _seed_trade():
    tx = {
        "transaction_id": "t1",
        "type": "trade",
        "status": "complete",
        "leg": 3,
        "status_updated": T1,
        "adds": {"4034": 1, "1111": 2},
        "drops": {"4034": 2, "1111": 1},
        "draft_picks": [],
    }
    store_mod.write_events(
        events_from_transaction(
            tx, league_key=LEAGUE, season="2026", owner_by_roster={1: "U1", 2: "U2"}
        )
    )


BODY = {
    "myTeam": "Team One",
    "opponent": "Team Two",
    "theyReceive": [
        {"name": "Some WR", "position": "WR"},
        {"name": "2027 Mid 1st", "isPick": True},
    ],
    "theySend": [{"name": "Some RB", "position": "RB"}],
}


def test_serves_the_owners_evidence_for_this_package(scout_env):  # noqa: F811
    _seed_trade()
    res = _post(scout_env, BODY, leagueKey=LEAGUE)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["leagueKey"] == LEAGUE
    assert body["opponent"] == "Team Two"
    assert body["basis"] == ms.OFFER_EVIDENCE_BASIS
    assert body["state"] == "measured"
    assert body["tradeCount"] == 1
    # Team One (the requester) is Team Two's only partner: one trade.
    assert body["tradesWithRequester"] == 1
    assert [p["position"] for p in body["positionsTheyWouldReceive"]] == ["WR"]
    assert body["picksTheyWouldReceive"]["offeredToThem"] == 1
    # Descriptive only: no label, grade or probability field exists.
    for forbidden in ("probability", "acceptance", "grade", "fit", "likes"):
        assert not any(forbidden in k.lower() for k in body)


def test_identical_to_the_owner_called_directly(scout_env):  # noqa: F811
    """The route adds nothing to the owner's answer but leagueKey/opponent."""
    _seed_trade()
    res = _post(scout_env, BODY, leagueKey=LEAGUE)
    teams = api._current_teams(_CONTRACT, LEAGUE)
    scout = ms.cached_manager_scout(
        LEAGUE,
        league_cfg=server._league_registry.get_league_by_key(LEAGUE),
        current_teams=teams,
        contract=_CONTRACT,
    )
    direct = ms.offer_evidence(
        scout,
        opponent_owner_id="U2",
        requester_owner_id="U1",
        they_receive=api.evidence_request(BODY)["theyReceive"],
        they_send=api.evidence_request(BODY)["theySend"],
    )
    body = res.json()
    body.pop("leagueKey")
    body.pop("opponent")
    assert body == direct


def test_a_missing_ledger_is_unavailable_not_zero(scout_env):  # noqa: F811
    res = _post(scout_env, BODY, leagueKey=LEAGUE)
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "unavailable"
    assert "tradeCount" not in body


def test_an_unknown_team_is_400_never_another_teams_history(scout_env):  # noqa: F811
    res = _post(scout_env, {**BODY, "opponent": "Nobody"}, leagueKey=LEAGUE)
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_team"
    assert res.json()["field"] == "opponent"


@pytest.mark.parametrize(
    "patch, field",
    [
        ({"myTeam": ""}, "myTeam"),
        ({"opponent": "Team One"}, "opponent"),
        ({"theyReceive": "WR"}, "theyReceive"),
        ({"theySend": [{"position": "RB"}]}, "theySend.name"),
        ({"theyReceive": [{"name": "x"}] * (api.MAX_EVIDENCE_ASSETS + 1)}, "theyReceive"),
    ],
)
def test_a_bad_body_is_400(scout_env, patch, field):  # noqa: F811
    res = _post(scout_env, {**BODY, **patch}, leagueKey=LEAGUE)
    assert res.status_code == 400
    assert res.json() == {**res.json(), "error": "invalid_body", "field": field}


def test_a_league_mismatch_against_the_loaded_contract_is_503(scout_env):  # noqa: F811
    res = _post(scout_env, BODY, leagueKey=OTHER)
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


def test_the_route_is_private():
    assert server._is_public_api_path(URL) is False
    with TestClient(server.app) as c:
        res = c.post(URL, json=BODY)
    assert res.status_code == 401
