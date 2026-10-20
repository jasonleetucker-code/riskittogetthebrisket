"""Brisket Trade Advisor — trade structure, ownership and the launch gate
(spec §2.3 / §4.5 / §6.3).

Validation is the ONE ledger owner (``src/trade/trade_ledger.py``) under the
public policy (``send_and_receive``), against the ONE captured contract,
whatever the client did.  Roster freshness is the ONE reader
``src/api/roster_freshness.py``: only ``current`` rosters prove ownership.
"""

from __future__ import annotations

import copy
import inspect

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
            S.trade_body(("p:103", 1, 2), ("p:202", 2, 1), perspective=3),
            "perspective_not_in_trade",
            {"rosterIds": [3]},
        ),
        (S.trade_body(("p:103", 1, 2), teams=(1, 1)), "too_few_teams", {"rosterIds": [1]}),
        (
            S.trade_body(("p:103", 1, 2), ("p:202", 2, 1), teams=(1, 2, 2)),
            "duplicate_team",
            {"rosterIds": [2]},
        ),
        (
            S.trade_body(("p:103", 1, 7), ("p:202", 7, 1), teams=(1, 7)),
            "team_not_in_league",
            {"rosterIds": [7]},
        ),
        (S.trade_body(), "empty_trade", {}),
        (
            S.trade_body(("p:103", 1, 2), ("q:202", 2, 1)),
            "unknown_asset",
            {"assetIds": ["q:202"]},
        ),
        (
            S.trade_body(("p:103", 1, 2), ("pick:side:2027:r1:o2", 2, 1)),
            "unknown_asset",
            {"assetIds": ["pick:side:2027:r1:o2"]},
        ),
        (
            S.trade_body(("p:103", 1, 2), ("p:55555", 2, 1)),
            "unknown_asset",
            {"assetIds": ["p:55555"]},
        ),
        (
            S.trade_body(("p:103", 1, 2), ("p:103", 1, 2), ("p:202", 2, 1)),
            "duplicate_asset",
            {"assetIds": ["p:103"]},
        ),
        (
            S.trade_body(("p:103", 3, 2), ("p:202", 2, 1)),
            "invalid_origin",
            {"assetIds": ["p:103"]},
        ),
        (
            S.trade_body(("p:103", 1, 3), ("p:202", 2, 1)),
            "invalid_destination",
            {"assetIds": ["p:103"]},
        ),
        (
            S.trade_body(("p:103", 1, 1), ("p:202", 2, 1)),
            "destination_is_origin",
            {"assetIds": ["p:103"]},
        ),
        (
            S.trade_body(("p:103", 1, 2), ("p:202", 2, 1), teams=(1, 2, 3)),
            "idle_team",
            {"rosterIds": [3]},
        ),
        (S.trade_body(("p:103", 1, 2)), "one_sided_trade", {"rosterIds": [1, 2]}),
        (
            # Directive §11 "many to one": team 3 receives only.  A public
            # product rule (SD-5), an availability difference, not a verdict.
            S.trade_body(("p:103", 1, 3), ("p:202", 2, 3), ("p:302", 3, 1), teams=(1, 2, 3)),
            "one_sided_trade",
            {"rosterIds": [2]},
        ),
    ],
)
def test_every_invalid_trade_reason(advisor_client, body, reason, extra):
    res = _post(advisor_client, body)
    assert res.status_code == 400, res.text
    out = res.json()
    assert out["error"] == "invalid_trade"
    assert out["reason"] == reason
    assert out["message"] == public_advisor.ERROR_MESSAGES[("invalid_trade", reason)]
    for k, v in extra.items():
        assert out[k] == v
    assert res.headers["cache-control"] == "no-store"


def test_every_ledger_reason_has_fixed_public_copy():
    from src.trade import trade_ledger

    src = inspect.getsource(trade_ledger.validate_ledger)
    import re

    reasons = set(re.findall(r'LedgerError\(\s*\d+,\s*"[a-z_]+",\s*"([a-z_]+)"', src))
    assert reasons, "no ledger reasons found"
    for r in reasons:
        key = ("stale_assets" if r == "asset_not_owned" else "invalid_trade", r)
        assert key in public_advisor.ERROR_MESSAGES, r


def test_too_many_assets_is_its_own_reason(advisor_client, monkeypatch):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["limits"]["maxLegs"] = 3
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    res = _post(
        advisor_client,
        S.trade_body(("p:101", 1, 2), ("p:102", 1, 2), ("p:103", 1, 2), ("p:202", 2, 1)),
    )
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
        {"perspectiveRosterId": 1, "teams": [1, 2], "assets": [], "expectedGeneration": "a b"},
        [],
    ],
)
def test_schema_violations_are_400_invalid_request(advisor_client, body):
    res = _post(advisor_client, body)
    assert res.status_code == 400
    assert res.json()["error"] == "invalid_request"
    assert res.json()["reason"] == "schema"


def test_team_ceiling_comes_from_config_not_a_hardcoded_four(advisor_client, monkeypatch):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["limits"]["maxTeams"] = 3
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    body = S.trade_body(*S.MIXED_FOUR, teams=(1, 2, 3, 4))
    res = _post(advisor_client, body)
    assert res.status_code == 400 and res.json()["reason"] == "schema"
    assert advisor_client.get(S.TEAMS_URL).json()["limits"]["maxTeams"] == 3
    cfg["limits"]["maxTeams"] = 4
    assert _post(advisor_client, body).status_code == 200


def test_max_teams_is_capped_at_the_league_team_count(advisor_client, monkeypatch):
    cfg = copy.deepcopy(api.advisor_config())
    cfg["limits"]["maxTeams"] = 12
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    assert advisor_client.get(S.TEAMS_URL).json()["limits"]["maxTeams"] == 4


def test_a_player_the_origin_team_does_not_hold_is_409_without_naming_the_owner(advisor_client):
    res = _post(advisor_client, S.trade_body(("p:201", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 409
    assert res.json() == {
        "error": "stale_assets",
        "message": public_advisor.ERROR_MESSAGES[("stale_assets", "asset_not_owned")],
        "reason": "asset_not_owned",
        "assetIds": ["p:201"],
    }


def test_a_pick_the_origin_team_does_not_hold_is_409(advisor_client):
    # Bravo's 2027 2nd belongs to Alpha now (traded).
    res = _post(advisor_client, S.trade_body(("p:103", 1, 2), ("pick:main:2027:r2:o2", 2, 1)))
    assert res.status_code == 409
    assert res.json()["assetIds"] == ["pick:main:2027:r2:o2"]
    # ... and Alpha CAN send it: current owner, not original owner.
    res = _post(advisor_client, S.trade_body(("pick:main:2027:r2:o2", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 200, res.text


def test_contract_swap_moves_ownership_and_the_list(advisor_client, monkeypatch):
    first = advisor_client.get(S.assets_url(1)).json()
    assert "p:103" in {a["id"] for a in first["assets"]}
    c2 = S.contract()
    c2["generatedAt"] = "2026-10-19T14:00:00+00:00"
    teams = c2["sleeper"]["teams"]
    teams[0]["playerIds"].remove("103")
    teams[0]["players"].remove("Alpha Receiver")
    teams[2]["playerIds"].append("103")
    teams[2]["players"].append("Alpha Receiver")
    monkeypatch.setattr(server, "latest_contract_data", c2)
    res = _post(advisor_client, S.trade_body(("p:103", 1, 2), ("p:202", 2, 1)))
    assert res.status_code == 409
    assert res.json()["assetIds"] == ["p:103"]
    second = advisor_client.get(S.assets_url(1)).json()
    assert second["generation"] != first["generation"]
    assert "p:103" not in {a["id"] for a in second["assets"]}
    assert "p:103" in {a["id"] for a in advisor_client.get(S.assets_url(3)).json()["assets"]}


def test_expected_generation_reports_snapshot_changes(advisor_client):
    gen = advisor_client.get(S.TEAMS_URL).json()["generation"]
    body = S.trade_body(*S.NOT_FAIR_TWO)
    assert _post(advisor_client, body).json()["snapshotChanged"] is None
    assert (
        _post(advisor_client, {**body, "expectedGeneration": gen}).json()["snapshotChanged"]
        is False
    )
    assert (
        _post(advisor_client, {**body, "expectedGeneration": "deadbeef"}).json()["snapshotChanged"]
        is True
    )


def _unable(res, reason):
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["overall"]["result"] == "UNABLE_TO_DETERMINE"
    for t in out["teams"]:
        assert t["result"] == "UNABLE_TO_DETERMINE"
        assert t["reasonCode"] == reason
    return out


def test_unknown_pick_inventory_is_unable_never_409(advisor_client, monkeypatch):
    c = S.contract()
    c["sleeper"]["teams"][2]["pickDetails"] = None  # Charlie's inventory unpublished
    c["sleeper"]["teams"][2]["pickOwnershipState"] = "unavailable"
    monkeypatch.setattr(server, "latest_contract_data", c)
    # A pick absent from every PUBLISHED inventory while one inventory is
    # unpublished cannot be ruled in or out: never a 409, never a verdict.
    # (With no published detail it also has no slot/tier label, and the
    # engine's gate order reports the unpriced asset first.)
    res = _post(
        advisor_client,
        S.trade_body(("pick:main:2027:r1:o3", 3, 2), ("p:202", 2, 3), teams=(2, 3), perspective=2),
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["overall"]["result"] == "UNABLE_TO_DETERMINE"
    for t in out["teams"]:
        assert t["result"] == "UNABLE_TO_DETERMINE"
        assert t["reasonCode"] in ("asset_not_evaluable", "ownership_unverifiable")
        assert t["unavailableAssetIds"] == ["pick:main:2027:r1:o3"]


def test_conflicting_pick_claims_are_unable_ownership_unverifiable(advisor_client, monkeypatch):
    c = S.contract()
    # Bravo ALSO claims Charlie's 2027 1st: two published owners.
    claim = dict(c["sleeper"]["teams"][2]["pickDetails"][0], ownerRosterId=2)
    c["sleeper"]["teams"][1]["pickDetails"].append(claim)
    monkeypatch.setattr(server, "latest_contract_data", c)
    out = _unable(
        _post(
            advisor_client,
            S.trade_body(
                ("pick:main:2027:r1:o3", 3, 4), ("p:402", 4, 3), teams=(3, 4), perspective=3
            ),
        ),
        "ownership_unverifiable",
    )
    assert [t["unavailableAssetIds"] for t in out["teams"]] == [["pick:main:2027:r1:o3"]] * 2


def test_conflicting_player_claims_are_unverifiable_not_guessed(advisor_client, monkeypatch):
    c = S.contract()
    c["sleeper"]["teams"][1]["playerIds"].append("103")  # 103 on Alpha AND Bravo
    monkeypatch.setattr(server, "latest_contract_data", c)
    out = _unable(
        _post(advisor_client, S.trade_body(("p:103", 1, 2), ("p:202", 2, 1))),
        "ownership_unverifiable",
    )
    assert out["teams"][0]["unavailableAssetIds"] == ["p:103"]


@pytest.mark.parametrize("state", ["stale", "unknown"])
def test_non_current_rosters_make_every_team_unable(advisor_client, monkeypatch, state):
    """SD-7: only ``current`` rosters (the canonical reader) prove ownership.
    Stale or unprovable rosters skip the 409 check and fail closed per team."""
    c = S.stale_contract() if state == "stale" else S.contract()
    if state == "unknown":
        c["sleeper"].pop("rosterSource")
        c["sleeper"].pop("rosterFetchedAt")
    monkeypatch.setattr(server, "latest_contract_data", c)
    assert advisor_client.get(S.TEAMS_URL).json()["rosters"]["state"] == state
    _unable(
        _post(advisor_client, S.trade_body(*S.FAIR_TWO, teams=(1, 3))), "ownership_unverifiable"
    )
    # Not even a mismatched owner is a 409 then (stale proves nothing).
    _unable(
        _post(advisor_client, S.trade_body(("p:201", 1, 2), ("p:202", 2, 1))),
        "ownership_unverifiable",
    )


def test_roster_freshness_has_one_reader():
    """Directive §14: the advisor's private ``roster_freshness`` copy is
    deleted; the snapshot's state is the canonical reader's answer."""
    from src.api.roster_freshness import roster_freshness

    assert not hasattr(public_advisor, "roster_freshness")
    src = inspect.getsource(public_advisor) + inspect.getsource(api)
    assert "rosterSource" not in src and "rosterSnapshotAgeHours" not in src
    for c in (S.contract(), S.stale_contract()):
        snap = public_advisor.snapshot(c, league_key="main")
        assert snap.rosters_state == roster_freshness(c)["state"]
        assert snap.rosters_as_of == roster_freshness(c)["asOf"]


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
    generations: the engine runs on the snapshot of the captured contract."""
    from src.trade import analyze_service

    seen = []
    real = analyze_service.analyze_trade_n

    def spy(snap, ledger, **kw):
        monkeypatch.setattr(server, "latest_contract_data", {"meta": {"leagueKey": "main"}})
        seen.append(public_advisor.public_generation(snap))
        return real(snap, ledger, **kw)

    monkeypatch.setattr(analyze_service, "analyze_trade_n", spy)
    res = _post(advisor_client, S.trade_body(*S.NOT_FAIR_TWO))
    assert res.status_code == 200
    assert res.json()["generation"] == seen[0]


def test_a_rostered_player_with_no_board_row_is_listed_and_not_evaluable(advisor_client):
    assets = advisor_client.get(S.assets_url(1)).json()["assets"]
    ghost = next(a for a in assets if a["id"] == f"p:{S.GHOST_ID}")
    assert ghost["label"] == S.GHOST_NAME
    assert ghost["evaluable"] is False
    out = _unable(
        _post(advisor_client, S.trade_body((f"p:{S.GHOST_ID}", 1, 2), ("p:202", 2, 1))),
        "asset_not_evaluable",
    )
    assert [t["unavailableAssetIds"] for t in out["teams"]] == [[f"p:{S.GHOST_ID}"]] * 2


def test_unpriced_kicker_is_not_evaluable_through_the_engine(advisor_client):
    kicker = next(
        a for a in advisor_client.get(S.assets_url(2)).json()["assets"] if a["id"] == "p:205"
    )
    assert kicker["evaluable"] is False
    out = _unable(
        _post(advisor_client, S.trade_body(("p:205", 2, 1), ("p:102", 1, 2))),
        "asset_not_evaluable",
    )
    assert out["teams"][1]["unavailableAssetIds"] == ["p:205"]


def test_evaluable_is_exactly_the_engines_single_asset_answer(advisor_client):
    """Spec §4.2 P2: ``evaluable`` comes from the engine's own resolution, so
    it is true exactly when a single-asset trade does NOT come back
    ``asset_not_evaluable`` for that asset."""
    for rid, partner in ((1, 2), (2, 1), (3, 4), (4, 3)):
        assets = advisor_client.get(S.assets_url(rid)).json()["assets"]
        partner_asset = next(
            a["id"]
            for a in advisor_client.get(S.assets_url(partner)).json()["assets"]
            if a["evaluable"]
        )
        for a in assets:
            res = _post(
                advisor_client,
                S.trade_body(
                    (a["id"], rid, partner),
                    (partner_asset, partner, rid),
                    teams=(rid, partner),
                    perspective=rid,
                ),
            )
            assert res.status_code == 200, (a["id"], res.text)
            mine = next(t for t in res.json()["teams"] if t["rosterId"] == rid)
            flagged = a["id"] in mine["unavailableAssetIds"]
            assert flagged == (not a["evaluable"]), a["id"]


def test_a_name_collision_cannot_price_someone_else(advisor_client, monkeypatch):
    """Identity is the Sleeper id: an unrostered row sharing a display name
    with player 102 does not change 102's result."""
    body = S.trade_body(("p:102", 1, 2), ("p:202", 2, 1))
    before = _post(advisor_client, body).json()
    c = S.contract()
    clone = copy.deepcopy(next(r for r in c["playersArray"] if r["playerId"] == "102"))
    clone["playerId"] = "777"
    clone["rankDerivedValue"] = 50.0
    c["playersArray"].append(clone)
    monkeypatch.setattr(server, "latest_contract_data", c)
    after = _post(advisor_client, body).json()
    assert after["teams"] == before["teams"]
    assert after["overall"] == before["overall"]


def test_idp_players_of_every_family_are_listed_and_evaluated(advisor_client):
    a1 = advisor_client.get(S.assets_url(1)).json()["assets"]
    a2 = advisor_client.get(S.assets_url(2)).json()["assets"]
    positions = {a["position"]: a["side"] for a in a1 + a2 if a["kind"] == "player"}
    assert positions["DL"] == positions["LB"] == positions["DB"] == "defense"
    res = _post(advisor_client, S.trade_body(("p:104", 1, 2), ("p:203", 2, 1)))
    assert res.status_code == 200
    assert {t["result"] for t in res.json()["teams"]} <= {"FAIR", "NOT_FAIR"}


@pytest.mark.parametrize(
    ("legs", "teams"),
    [
        (S.FAIR_THREE, (1, 3, 4)),
        ([("p:103", 1, 2), ("p:202", 2, 3), ("p:302", 3, 1)], (1, 2, 3)),
        (S.MIXED_FOUR, (1, 2, 3, 4)),
        (
            # One team sending to several destinations (directive §11).
            [("p:101", 1, 2), ("p:102", 1, 3), ("p:201", 2, 1), ("p:302", 3, 1)],
            (1, 2, 3),
        ),
        (
            # Picks-only, four teams.
            [
                ("pick:main:2027:r1:o1", 1, 2),
                ("pick:main:2027:r1:o2", 2, 3),
                ("pick:main:2027:r1:o3", 3, 4),
                ("pick:main:2027:r1:o4", 4, 1),
            ],
            (1, 2, 3, 4),
        ),
    ],
)
def test_multi_team_trades_are_evaluated_never_unsupported(advisor_client, legs, teams):
    res = _post(advisor_client, S.trade_body(*legs, teams=teams, perspective=teams[0]))
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["teamCount"] == len(teams)
    assert [t["rosterId"] for t in out["teams"]] == sorted(teams)
    assert {t["result"] for t in out["teams"]} <= {"FAIR", "NOT_FAIR"}
    assert out["overall"]["note"] == public_advisor.MULTI_TEAM_NOTE
    states = [t["result"] for t in out["teams"]]
    expected = "NOT_FAIR" if "NOT_FAIR" in states else "FAIR"
    assert out["overall"]["result"] == expected
    assert "multi_team_unsupported" not in res.text


def test_ownership_is_still_enforced_at_four_teams(advisor_client):
    bad = S.trade_body(
        ("p:201", 1, 2), ("p:202", 2, 3), ("p:302", 3, 4), ("p:402", 4, 1), teams=(1, 2, 3, 4)
    )
    res = _post(advisor_client, bad)
    assert res.status_code == 409
    assert res.json()["assetIds"] == ["p:201"]


def test_flag_off_answers_disabled_on_every_route(advisor_client, monkeypatch):
    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_BRISKET_TRADE_ADVISOR", "0")
    feature_flags.reload()
    for res in (
        advisor_client.get(S.TEAMS_URL),
        advisor_client.get(S.assets_url(1)),
        _post(advisor_client, S.trade_body(*S.NOT_FAIR_TWO)),
    ):
        assert res.status_code == 503
        assert res.json()["reason"] == "disabled"


def test_flags_default_off():
    from src.api.feature_flags import _DEFAULTS

    assert _DEFAULTS["brisket_trade_advisor"] is False
    assert _DEFAULTS["trade_multi_team_analysis"] is False


def test_public_product_works_with_the_private_multi_team_flag_off(advisor_client, monkeypatch):
    """The private flag gates the private route only, never the shared engine."""
    from src.api import feature_flags

    monkeypatch.setenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", "0")
    feature_flags.reload()
    res = _post(advisor_client, S.trade_body(*S.FAIR_THREE, teams=(1, 3, 4)))
    assert res.status_code == 200 and res.json()["overall"]["result"] == "FAIR"


def test_a_contract_for_another_league_is_not_ready(advisor_client, monkeypatch):
    c = S.contract()
    c["meta"]["leagueKey"] = "side"
    monkeypatch.setattr(server, "latest_contract_data", c)
    res = advisor_client.get(S.TEAMS_URL)
    assert res.status_code == 503
    assert res.json()["reason"] == "not_ready"


def test_package_model_refusal_mid_request_is_not_ready(advisor_client, monkeypatch):
    from src.trade import analyze_service

    monkeypatch.setattr(analyze_service, "package_model_ready", lambda: False)
    res = _post(advisor_client, S.trade_body(*S.NOT_FAIR_TWO))
    assert res.status_code == 503
    assert res.json()["reason"] == "not_ready"


def test_snapshot_memo_is_the_ledger_owners(advisor_client, monkeypatch):
    from src.trade import trade_ledger

    advisor_client.get(S.TEAMS_URL)
    advisor_client.get(S.TEAMS_URL)
    assert len(trade_ledger._MEMO) == 1
    monkeypatch.setattr(server, "latest_contract_data", S.contract())
    advisor_client.get(S.TEAMS_URL)
    assert len(trade_ledger._MEMO) == 2
    monkeypatch.setattr(server, "latest_contract_data", S.contract())
    advisor_client.get(S.TEAMS_URL)
    assert len(trade_ledger._MEMO) == 2  # LRU 2
    assert not hasattr(api, "_SNAPSHOT_MEMO")


# ── Launch gate (spec §6.3) ────────────────────────────────────────────────

# Captured at import, before the advisor_client fixture swaps in its
# launched-box seam.
_REAL_LAUNCH_GATE = api._launch_gate_reason


_RECORD_REL = "docs/owner/TEST_SOURCE_PERMISSION.json"


def _valid_permission_record() -> dict:
    """A complete, current owner approval covering every voting source — a
    TEST fixture only (the real record is the owner's, OD-3)."""
    import datetime as dt

    from src.trade import public_advisor_permission as perm

    today = perm._today()
    return {
        "recordType": perm.RECORD_TYPE,
        "schemaVersion": perm.SCHEMA_VERSION,
        "scope": perm.SCOPE,
        "approvedBy": "test-owner",
        "approvedAt": (today - dt.timedelta(days=1)).isoformat(),
        "reviewBy": (today + dt.timedelta(days=30)).isoformat(),
        "providers": {},
        "sources": {k: "approved" for k in perm.voting_source_keys()},
    }


def _write_record(monkeypatch, tmp_path, record) -> None:
    """Point the permission check at a temp repo holding ``record`` (never
    writes into the real ``docs/owner``)."""
    import json

    from src.trade import public_advisor_permission as perm

    target = tmp_path / _RECORD_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(record if isinstance(record, str) else json.dumps(record), encoding="utf-8")
    monkeypatch.setattr(perm, "_REPO", tmp_path)


def _launch_cfg(monkeypatch, tmp_path, **overrides):
    from src.valuation_math import fairness_bands

    _write_record(monkeypatch, tmp_path, _valid_permission_record())
    cfg = copy.deepcopy(api.advisor_config())
    cfg.update(
        responseFloorMs=900,
        approvedFairnessVersion=fairness_bands.receipt()["version"],
        approvedSourcePermissionRecord=_RECORD_REL,
    )
    cfg.update(overrides)
    monkeypatch.setattr(api, "advisor_config", lambda: cfg)
    monkeypatch.setattr(api, "_launch_gate_reason", _REAL_LAUNCH_GATE)
    return cfg


def _approved_bands(monkeypatch, status="APPROVED"):
    from src.valuation_math import fairness_bands

    real = fairness_bands.receipt()
    monkeypatch.setattr(fairness_bands, "receipt", lambda: {**real, "status": status})


def test_the_committed_config_keeps_the_launch_gate_closed():
    api.advisor_config.cache_clear()
    try:
        cfg = api.advisor_config()
        assert cfg["responseFloorMs"] is None
        assert cfg["approvedFairnessVersion"] is None
        assert cfg["approvedSourcePermissionRecord"] is None
        assert "multiTeamRecommendations" not in cfg
        assert _REAL_LAUNCH_GATE() == "response_floor_unset"
    finally:
        api.advisor_config.cache_clear()


@pytest.mark.parametrize(
    ("override", "bands_status", "reason"),
    [
        ({"responseFloorMs": None}, "APPROVED", "response_floor_unset"),
        ({"approvedFairnessVersion": None}, "APPROVED", "fairness_version_unapproved"),
        (
            {"approvedFairnessVersion": "fairness_bands_v0"},
            "APPROVED",
            "fairness_version_unapproved",
        ),
        ({}, "PROVISIONAL", "fairness_bands_provisional"),
        ({"approvedSourcePermissionRecord": None}, "APPROVED", "source_permission_unrecorded"),
        (
            {"approvedSourcePermissionRecord": "docs/owner/NO_SUCH_RECORD.json"},
            "APPROVED",
            "source_permission_invalid:missing",
        ),
        (
            {"approvedSourcePermissionRecord": "docs/owner/NO_SUCH_RECORD.md"},
            "APPROVED",
            "source_permission_invalid:path_not_allowed",
        ),
        (
            {"approvedSourcePermissionRecord": "../../etc/passwd"},
            "APPROVED",
            "source_permission_invalid:path_not_allowed",
        ),
        # R2-10: an arbitrary existing repo file no longer opens the leg.
        (
            {"approvedSourcePermissionRecord": "README.md"},
            "APPROVED",
            "source_permission_invalid:path_not_allowed",
        ),
    ],
)
def test_each_missing_launch_input_keeps_every_route_closed(
    advisor_client, monkeypatch, tmp_path, override, bands_status, reason
):
    _launch_cfg(monkeypatch, tmp_path, **override)
    _approved_bands(monkeypatch, bands_status)
    assert api._launch_gate_reason() == reason
    for method, url in (("GET", S.TEAMS_URL), ("GET", S.assets_url(1)), ("POST", S.ANALYZE)):
        body = S.trade_body(*S.NOT_FAIR_TWO) if method == "POST" else None
        res = advisor_client.request(method, url, json=body)
        assert res.status_code == 503, (url, res.text)
        assert res.json()["reason"] == "not_ready"


def test_package_model_not_geom_keeps_the_gate_closed(advisor_client, monkeypatch, tmp_path):
    from src.valuation_math import package_model

    _launch_cfg(monkeypatch, tmp_path)
    _approved_bands(monkeypatch)
    monkeypatch.setattr(package_model, "active_model_id", lambda: package_model.KTC_2026_04)
    assert api._launch_gate_reason() == "package_model_unavailable"


def test_every_launch_input_present_opens_the_gate(advisor_client, monkeypatch, tmp_path):
    _launch_cfg(monkeypatch, tmp_path, responseFloorMs={2: 400, 3: 600, 4: 800})
    _approved_bands(monkeypatch)
    assert api._launch_gate_reason() is None
    assert advisor_client.get(S.TEAMS_URL).status_code == 200


def test_floor_config_parsing():
    assert api._parse_floor(900) == 900
    assert api._parse_floor({"2": 400, "3": 600}) == {2: 400, 3: 600}
    for bad in (None, 0, -5, 1.5, True, "900", {}, {"2": 0}, {"x": 400}, {"2": 1.5}):
        assert api._parse_floor(bad) is None, bad
