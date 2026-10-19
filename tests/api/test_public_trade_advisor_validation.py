"""Brisket Trade Advisor — trade structure and asset ownership (design §11 group C).

Backend validation must stand on its own: every rule here is enforced by
``public_advisor.validate_trade`` against the ONE captured contract, whatever
the client did.
"""

from __future__ import annotations

import copy

import pytest

import server
from src.api import public_trade_advisor_api as api
from src.trade import public_advisor
from tests.api import trade_advisor_support as S
from tests.api.trade_advisor_support import (  # noqa: F401 — pytest fixtures, used by name
    advisor_app_fixture,
    advisor_client_fixture,
)


def _post(client, body):
    return client.post(S.ANALYZE, json=body)


@pytest.mark.parametrize(
    ("body", "reason", "extra"),
    [
        (
            S.two_team_body(("p:103", 1, 2), ("p:202", 2, 1), perspective=3),
            "perspective_not_in_trade",
            {"rosterIds": [3]},
        ),
        (S.two_team_body(("p:103", 1, 2), teams=(1, 1)), "duplicate_team", {"rosterIds": [1]}),
        (
            S.two_team_body(("p:103", 1, 7), ("p:202", 7, 1), teams=(1, 7)),
            "unknown_team",
            {"rosterIds": [7]},
        ),
        (
            S.two_team_body(("p:103", 1, 2), ("q:202", 2, 1)),
            "unknown_asset",
            {"assetIds": ["q:202"]},
        ),
        (
            S.two_team_body(("p:103", 1, 2), ("pick:side:2027:r1:o2", 2, 1)),
            "unknown_asset",
            {"assetIds": ["pick:side:2027:r1:o2"]},
        ),
        (
            S.two_team_body(("p:103", 1, 2), ("p:103", 1, 2), ("p:202", 2, 1)),
            "duplicate_asset",
            {"assetIds": ["p:103"]},
        ),
        (
            S.two_team_body(("p:103", 3, 2), ("p:202", 2, 1)),
            "invalid_origin",
            {"assetIds": ["p:103"]},
        ),
        (
            S.two_team_body(("p:103", 1, 3), ("p:202", 2, 1)),
            "invalid_destination",
            {"assetIds": ["p:103"]},
        ),
        (
            S.two_team_body(("p:103", 1, 1), ("p:202", 2, 1)),
            "destination_is_origin",
            {"assetIds": ["p:103"]},
        ),
        (S.two_team_body(("p:103", 1, 2)), "one_sided_trade", {"rosterIds": [2]}),
        (S.two_team_body(), "one_sided_trade", {"rosterIds": [1, 2]}),
        (
            S.two_team_body(("p:103", 1, 2), ("p:202", 2, 1), teams=(1, 2, 3)),
            "idle_team",
            {"rosterIds": [3]},
        ),
    ],
)
def test_every_invalid_trade_reason(advisor_client, body, reason, extra):
    res = _post(advisor_client, body)
    assert res.status_code == 400, res.text
    out = res.json()
    assert out["error"] == "invalid_trade"
    assert out["reason"] == reason
    for k, v in extra.items():
        assert out[k] == v


def test_too_many_assets_is_its_own_reason(advisor_client):
    legs = [(f"p:{i}", 1, 2) for i in range(1000, 1130)]
    res = _post(advisor_client, S.two_team_body(*legs, ("p:202", 2, 1)))
    assert res.status_code == 400
    assert res.json()["reason"] == "too_many_assets"


@pytest.mark.parametrize(
    "body",
    [
        {"perspectiveRosterId": 1, "teams": [1, 2], "assets": [], "extra": 1},
        {"perspectiveRosterId": 1, "teams": [1, 2, 3, 4, 5], "assets": []},
        {"perspectiveRosterId": 1, "teams": [1], "assets": []},
        {"perspectiveRosterId": 1, "teams": [1, 2], "assets": [{"id": "p:1", "from": 0, "to": 2}]},
        {
            "perspectiveRosterId": 1,
            "teams": [1, 2],
            "assets": [{"id": "p:1", "from": 1, "to": 100}],
        },
        {"perspectiveRosterId": 1, "teams": [1, 2], "assets": [{"id": "p 1", "from": 1, "to": 2}]},
        {"perspectiveRosterId": True, "teams": [1, 2], "assets": []},
        {"perspectiveRosterId": 1.0, "teams": [1, 2], "assets": []},
        [],
    ],
)
def test_schema_violations_are_400_invalid_request(advisor_client, body):
    res = _post(advisor_client, body)
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_request"
    assert res.json()["reason"] == "schema"


def test_a_player_the_origin_team_does_not_hold_is_409(advisor_client):
    res = _post(advisor_client, S.two_team_body(("p:201", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 409
    assert res.json() == {
        "error": "stale_assets",
        "message": res.json()["message"],
        "reason": "asset_not_owned",
        "assetIds": ["p:201"],
    }


def test_a_pick_the_origin_team_does_not_hold_is_409(advisor_client):
    # Bravo's 2027 2nd belongs to Alpha now (traded).
    res = _post(advisor_client, S.two_team_body(("p:103", 1, 2), ("pick:main:2027:r2:o2", 2, 1)))
    assert res.status_code == 409
    assert res.json()["assetIds"] == ["pick:main:2027:r2:o2"]
    # ... and Alpha CAN send it: current owner, not original owner.
    res = _post(advisor_client, S.two_team_body(("pick:main:2027:r2:o2", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 200, res.text


def test_a_player_on_no_roster_is_409(advisor_client):
    res = _post(advisor_client, S.two_team_body(("p:55555", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 409


def test_contract_swap_moves_ownership_and_the_list(advisor_client, monkeypatch):
    first = advisor_client.get(S.assets_url(1)).json()
    assert "p:103" in {a["id"] for a in first["assets"]}
    # S2: Alpha Receiver moved to Charlie, under a new generation.
    c2 = S.contract()
    c2["generatedAt"] = "2026-10-19T14:00:00+00:00"
    teams = c2["sleeper"]["teams"]
    teams[0]["playerIds"].remove("103")
    teams[0]["players"].remove("Alpha Receiver")
    teams[2]["playerIds"].append("103")
    teams[2]["players"].append("Alpha Receiver")
    monkeypatch.setattr(server, "latest_contract_data", c2)
    res = _post(advisor_client, S.two_team_body(("p:103", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 409
    assert res.json()["assetIds"] == ["p:103"]
    second = advisor_client.get(S.assets_url(1)).json()
    assert second["generation"] != first["generation"]
    assert "p:103" not in {a["id"] for a in second["assets"]}
    assert "p:103" in {a["id"] for a in advisor_client.get(S.assets_url(3)).json()["assets"]}


def test_unknown_pick_inventory_is_unavailable_ownership_unverifiable(advisor_client, monkeypatch):
    c = S.contract()
    c["sleeper"]["teams"][2]["pickDetails"] = None  # Charlie's inventory unpublished
    c["sleeper"]["teams"][2]["pickOwnershipState"] = "unavailable"
    monkeypatch.setattr(server, "latest_contract_data", c)
    # A pick absent from every PUBLISHED inventory while one inventory is
    # unpublished cannot be ruled in or out: never a 409, never a verdict.
    res = _post(advisor_client, S.two_team_body(("pick:main:2029:r1:o3", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 200, res.text
    assert res.json()["category"] == "UNAVAILABLE"
    assert res.json()["reasonCode"] == "ownership_unverifiable"


def test_conflicting_player_claims_are_unverifiable_not_guessed(advisor_client, monkeypatch):
    c = S.contract()
    c["sleeper"]["teams"][1]["playerIds"].append("103")  # 103 on Alpha AND Bravo
    monkeypatch.setattr(server, "latest_contract_data", c)
    res = _post(advisor_client, S.two_team_body(("p:103", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 200
    assert res.json()["category"] == "UNAVAILABLE"
    assert res.json()["reasonCode"] == "ownership_unverifiable"


def test_pick_ownership_unavailable_lists_no_picks(advisor_client, monkeypatch):
    c = S.contract()
    team = c["sleeper"]["teams"][1]
    team["pickOwnershipState"] = "unavailable"
    team["pickOwnershipReason"] = "traded_picks_fetch_failed"
    monkeypatch.setattr(server, "latest_contract_data", c)
    body = advisor_client.get(S.assets_url(2)).json()
    assert body["pickOwnership"] == "unavailable"
    assert not [a for a in body["assets"] if a["kind"] == "pick"]


def test_evaluation_uses_the_contract_captured_at_request_start(advisor_client, monkeypatch):
    """A publish mid-request must not split one evaluation across two
    generations: the handler hands the snapshot of the contract it captured
    to the engine, whatever ``latest_contract_data`` says afterwards."""
    seen = []
    real = public_advisor._engine_analyze

    def spy(snap, team, **kw):
        # Simulate a publish that lands after capture.
        monkeypatch.setattr(server, "latest_contract_data", {"meta": {"leagueKey": "main"}})
        seen.append(snap.generation)
        return real(snap, team, **kw)

    monkeypatch.setattr(public_advisor, "_engine_analyze", spy)
    res = _post(advisor_client, S.two_team_body(("p:101", 1, 2), ("p:201", 2, 1)))
    assert res.status_code == 200
    assert res.json()["category"] != "UNAVAILABLE"
    assert res.json()["generation"] == seen[0]


def test_a_rostered_player_with_no_board_row_is_listed_and_not_evaluable(advisor_client):
    assets = advisor_client.get(S.assets_url(1)).json()["assets"]
    ghost = next(a for a in assets if a["id"] == f"p:{S.GHOST_ID}")
    assert ghost["label"] == S.GHOST_NAME
    assert ghost["evaluable"] is False
    res = _post(advisor_client, S.two_team_body((f"p:{S.GHOST_ID}", 1, 2), ("p:202", 2, 1)))
    assert res.json()["category"] == "UNAVAILABLE"
    assert res.json()["reasonCode"] == "asset_not_evaluable"
    assert res.json()["unavailableAssetIds"] == [f"p:{S.GHOST_ID}"]


def test_unpriced_kicker_is_not_evaluable_through_the_engine(advisor_client):
    res = _post(advisor_client, S.two_team_body(("p:205", 2, 1), ("p:102", 1, 2)))
    body = res.json()
    assert body["category"] == "UNAVAILABLE"
    assert body["reasonCode"] == "asset_not_evaluable"
    assert body["unavailableAssetIds"] == ["p:205"]


def test_a_name_collision_fails_closed_instead_of_pricing_someone_else(advisor_client, monkeypatch):
    c = S.contract()
    # A second, unrostered "Alpha Runner" row: the engine's name index now
    # resolves that name to a DIFFERENT player than id 102.
    clone = copy.deepcopy(next(r for r in c["playersArray"] if r["playerId"] == "102"))
    clone["playerId"] = "777"
    clone["rankDerivedValue"] = 50.0
    c["playersArray"].append(clone)
    monkeypatch.setattr(server, "latest_contract_data", c)
    res = _post(advisor_client, S.two_team_body(("p:102", 1, 2), ("p:202", 2, 1)))
    assert res.json()["category"] == "UNAVAILABLE"
    assert res.json()["unavailableAssetIds"] == ["p:102"]


def test_idp_players_of_every_family_are_listed_and_evaluated(advisor_client):
    a1 = advisor_client.get(S.assets_url(1)).json()["assets"]
    a2 = advisor_client.get(S.assets_url(2)).json()["assets"]
    positions = {a["position"]: a["side"] for a in a1 + a2 if a["kind"] == "player"}
    assert positions["DL"] == positions["LB"] == positions["DB"] == "defense"
    res = _post(advisor_client, S.two_team_body(("p:104", 1, 2), ("p:203", 2, 1)))
    assert res.status_code == 200
    assert res.json()["category"] != "UNAVAILABLE" or res.json()["reasonCode"] is None


def test_three_team_trade_validates_then_answers_multi_team_unsupported(advisor_client):
    body = S.two_team_body(("p:103", 1, 2), ("p:202", 2, 3), ("p:302", 3, 1), teams=(1, 2, 3))
    res = _post(advisor_client, body)
    assert res.status_code == 200
    out = res.json()
    assert out["teamCount"] == 3
    assert out["category"] == "UNAVAILABLE"
    assert out["reasonCode"] == "multi_team_unsupported"
    # Ownership is still enforced at N = 3.
    bad = S.two_team_body(("p:201", 1, 2), ("p:202", 2, 3), ("p:302", 3, 1), teams=(1, 2, 3))
    assert _post(advisor_client, bad).status_code == 409


def test_flag_off_answers_disabled_on_every_route(advisor_client, monkeypatch):
    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "0")
    feature_flags.reload()
    for res in (
        advisor_client.get(S.TEAMS_URL),
        advisor_client.get(S.assets_url(1)),
        _post(advisor_client, S.two_team_body(("p:103", 1, 2), ("p:202", 2, 1))),
    ):
        assert res.status_code == 503
        assert res.json()["reason"] == "disabled"


def test_flag_defaults_off():
    from src.api.feature_flags import _DEFAULTS

    assert _DEFAULTS["brisket_trade_advisor"] is False


def test_a_contract_for_another_league_is_not_ready(advisor_client, monkeypatch):
    c = S.contract()
    c["meta"]["leagueKey"] = "side"
    monkeypatch.setattr(server, "latest_contract_data", c)
    res = advisor_client.get(S.TEAMS_URL)
    assert res.status_code == 503
    assert res.json()["reason"] == "not_ready"


def test_package_model_mismatch_fails_closed(advisor_client, monkeypatch):
    from src.valuation_math import package_model

    monkeypatch.setattr(package_model, "active_model_id", lambda: package_model.KTC_2026_04)
    res = _post(advisor_client, S.two_team_body(("p:101", 1, 2), ("p:201", 2, 1)))
    assert res.json()["category"] == "UNAVAILABLE"
    assert res.json()["reasonCode"] is None


def test_snapshot_memo_is_keyed_by_contract_identity(advisor_client, monkeypatch):
    advisor_client.get(S.TEAMS_URL)
    advisor_client.get(S.TEAMS_URL)
    assert len(api._SNAPSHOT_MEMO) == 1
    monkeypatch.setattr(server, "latest_contract_data", S.contract())
    advisor_client.get(S.TEAMS_URL)
    assert len(api._SNAPSHOT_MEMO) == 2
    monkeypatch.setattr(server, "latest_contract_data", S.contract())
    advisor_client.get(S.TEAMS_URL)
    assert len(api._SNAPSHOT_MEMO) == 2  # LRU 2
