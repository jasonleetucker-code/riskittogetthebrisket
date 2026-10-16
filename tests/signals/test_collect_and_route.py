"""C6-SIG-01 — emitters are read through their owners, and the private route.

The collectors must (a) place every emitter row on the canonical asset key
or report it unresolved — never a fuzzy guess, (b) report an emitter whose
owner cannot answer as ``unobserved`` with the owner's reason, and (c)
carry Consensus Edge's ``Withheld`` and the contract's quarantine through
to the reconciled state.
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags, league_registry, rank_history
from src.signals import collect
from src.signals import reconciler as rec


def _row(name, pid, pos, *, quarantined=False, asset_class="offense"):
    return {
        "displayName": name,
        "canonicalName": name,
        "playerId": pid,
        "assetClass": asset_class,
        "position": pos,
        "pos": pos,
        "rankDerivedValue": 5000,
        "canonicalConsensusRank": 50,
        "quarantined": quarantined,
        "anomalyFlags": ["blend_integrity_violation"] if quarantined else [],
    }


def _contract(league_key="dynasty_main"):
    return {
        "scrapeTimestamp": "2026-10-07T10:00:00+00:00",
        "generatedAt": "2026-10-07T10:00:00+00:00",
        "meta": {"leagueKey": league_key},
        "playersArray": [
            _row("Zed Sigalpha", "90001", "QB"),
            _row("Yan Sigbravo", "90002", "WR"),
            _row("Xia Sigcharlie", "90003", "RB", quarantined=True),
            # Two rows one name, different position groups.
            _row("Sam Twin", "90004", "WR"),
            _row("Sam Twin", "90005", "LB", asset_class="idp"),
        ],
        "sleeper": {
            "teams": [
                {
                    "ownerId": "owner-1",
                    "name": "Alpha Team",
                    "roster_id": 1,
                    "players": ["Zed Sigalpha", "Yan Sigbravo", "Ghost Notonboard"],
                    "picks": [],
                },
            ],
            "trades": [],
        },
    }


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(rank_history, "HISTORY_PATH", tmp_path / "rank_history.jsonl")
    yield
    for name in ("RISKIT_FEATURE_CONSENSUS_EDGE", "RISKIT_FEATURE_BDVM_ENGINE"):
        os.environ.pop(name, None)
    feature_flags.reload()


def _flags(*, consensus_edge: bool, bdvm: bool):
    os.environ["RISKIT_FEATURE_CONSENSUS_EDGE"] = "1" if consensus_edge else "0"
    os.environ["RISKIT_FEATURE_BDVM_ENGINE"] = "1" if bdvm else "0"
    feature_flags.reload()


def _ce_board(rows):
    return {
        "status": "ok",
        "contractScrapedAt": "2026-10-07T10:00:00+00:00",
        "players": rows,
        "sellSideValidation": {"validated": False},
    }


def _ce_row(name, pos, label, reason=None):
    return {
        "playerKey": f"ce::{name}",
        "displayName": name,
        "position": pos,
        "label": label,
        "labelReason": reason,
        "score": 42.0,
        "confidence": 55.0,
        "quarantined": label == "Withheld",
    }


# ── identity ─────────────────────────────────────────────────────────────


def test_identity_index_never_guesses():
    index = collect.build_identity_index(_contract())
    assert index.resolve(player_id="90001") == ("player:90001", None)
    assert index.resolve(name="zed sigalpha") == ("player:90001", None)
    # Same name, two position groups: ambiguous without a position...
    assert index.resolve(name="Sam Twin") == (None, "ambiguous")
    # ...and split by the position group when one is supplied.
    assert index.resolve(name="Sam Twin", position="LB") == ("player:90005", None)
    assert index.resolve(name="Nobody Real") == (None, "unresolved")
    assert index.quarantined == {"player:90003": "blend_integrity_violation"}


# ── collectors through their owners ─────────────────────────────────────


def _build(contract, **kw):
    with mock.patch.object(
        collect, "collect_sharp", lambda index: (rec.unobserved("sharp_market", "error:X"), [])
    ):
        return collect.build_reconciled_signals(contract, league_key="dynasty_main", **kw)


def test_roster_reconciliation_reads_owners_and_keeps_withheld_precedence():
    _flags(consensus_edge=True, bdvm=False)
    contract = _contract()
    board = _ce_board(
        [
            _ce_row("Zed Sigalpha", "QB", "Sell"),
            _ce_row("Yan Sigbravo", "WR", "Withheld", "identity quarantined"),
            _ce_row("Nobody Real", "WR", "Buy"),
        ]
    )
    with mock.patch("src.consensus_edge.api.board_for_contract", return_value=board) as ce:
        payload = _build(
            contract,
            resolved_team=contract["sleeper"]["teams"][0],
            news_items=[],
        )
    ce.assert_called_once()
    assert payload["scope"] == "roster"
    keys = [p["playerKey"] for p in payload["players"]]
    assert keys == ["player:90001", "player:90002"]

    by_id = {e["emitterId"]: e for e in payload["emitters"]}
    assert by_id["terminal_signal"]["state"] == rec.OBSERVED
    assert by_id["bdvm_market_signal"]["reason"] == "feature_disabled:bdvm_engine"
    assert by_id["sharp_market"]["reason"] == "error:X"

    zed = payload["players"][0]
    assert {s["emitter"] for s in zed["signals"]} == {"terminal_signal", "consensus_edge"}
    assert zed["emittersUnobserved"] == ["bdvm_market_signal", "sharp_market"]

    yan = payload["players"][1]
    assert yan["state"] == rec.STATE_WITHHELD
    assert yan["withheldBy"] == [{"source": "consensus_edge", "reason": "identity quarantined"}]

    unresolved = {(u["emitter"], u["name"], u["reason"]) for u in payload["unresolved"]}
    assert ("consensus_edge", "Nobody Real", "unresolved") in unresolved
    assert (None, "Ghost Notonboard", "unresolved") in unresolved


def test_quarantined_row_is_withheld_in_league_scope_even_with_consensus_edge_off():
    _flags(consensus_edge=False, bdvm=False)
    contract = _contract()
    with mock.patch("src.consensus_edge.api.board_for_contract") as ce:
        payload = _build(
            contract,
            resolved_team=contract["sleeper"]["teams"][0],
            news_items=[],
            scope="league",
            player="Xia Sigcharlie",
        )
    ce.assert_not_called()  # flag off: its board is never read
    by_id = {e["emitterId"]: e for e in payload["emitters"]}
    assert by_id["consensus_edge"]["reason"] == "feature_disabled:consensus_edge"
    [xia] = payload["players"]
    assert xia["playerKey"] == "player:90003"
    assert xia["state"] == rec.STATE_WITHHELD
    assert xia["withheldBy"][0]["source"] == "canonical_quarantine"


def test_no_team_means_the_roster_emitter_is_unobserved_not_silent():
    _flags(consensus_edge=False, bdvm=False)
    payload = _build(_contract(), resolved_team=None, news_items=None)
    by_id = {e["emitterId"]: e for e in payload["emitters"]}
    assert by_id["terminal_signal"]["state"] == rec.UNOBSERVED
    assert by_id["terminal_signal"]["reason"] == "no_team_resolved"
    assert payload["scope"] == "league"
    assert payload["players"] == []


def test_missing_news_is_noted_on_the_terminal_run_not_treated_as_quiet():
    _flags(consensus_edge=False, bdvm=False)
    contract = _contract()
    payload = _build(contract, resolved_team=contract["sleeper"]["teams"][0], news_items=None)
    by_id = {e["emitterId"]: e for e in payload["emitters"]}
    assert any(n.startswith("news_unavailable") for n in by_id["terminal_signal"]["notes"])


def test_bdvm_non_ok_status_is_unobserved_with_the_owner_status():
    _flags(consensus_edge=False, bdvm=True)
    contract = _contract()
    with mock.patch(
        "src.api.bdvm_api.get_bdvm_values",
        return_value={"status": "no_projection_snapshot", "players": []},
    ):
        run, missed = collect.collect_bdvm(
            contract,
            collect.build_identity_index(contract),
            league_key="dynasty_main",
            freshness={"state": "fresh"},
        )
    assert run.state == rec.UNOBSERVED
    assert run.reason == "status:no_projection_snapshot"
    assert missed == []


def test_bdvm_is_never_reported_fresh_because_its_projection_leg_has_no_budget():
    _flags(consensus_edge=False, bdvm=True)
    contract = _contract()
    values = {
        "status": "ok",
        "meta": {"asOf": "2026-10-06"},
        "players": [
            {
                "playerId": "90001",
                "name": "Zed Sigalpha",
                "position": "QB",
                "signal": {"signal": "STRONG_BUY", "reason": "alpha +900"},
                "market": {"gap": 900.0, "marketValue": 4000},
            }
        ],
    }
    with mock.patch("src.api.bdvm_api.get_bdvm_values", return_value=values):
        run, _ = collect.collect_bdvm(
            contract,
            collect.build_identity_index(contract),
            league_key="dynasty_main",
            freshness={"state": "fresh", "hoursStale": 1.0},
        )
    assert run.state == rec.OBSERVED
    assert run.freshness["state"] == "unknown"
    [obs] = run.observations
    assert (obs.player_key, obs.native_label) == ("player:90001", "STRONG_BUY")


def test_an_emitter_exception_is_unobserved_and_does_not_hide_the_others():
    _flags(consensus_edge=True, bdvm=False)
    contract = _contract()
    with mock.patch("src.consensus_edge.api.board_for_contract", side_effect=RuntimeError("boom")):
        payload = _build(contract, resolved_team=contract["sleeper"]["teams"][0], news_items=[])
    by_id = {e["emitterId"]: e for e in payload["emitters"]}
    assert by_id["consensus_edge"]["reason"] == "error:RuntimeError"
    assert by_id["terminal_signal"]["state"] == rec.OBSERVED


# ── route ────────────────────────────────────────────────────────────────


@pytest.fixture()
def client(tmp_path, monkeypatch):
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "dynasty_main",
                "leagues": [
                    {
                        "key": "dynasty_main",
                        "displayName": "Main",
                        "sleeperLeagueId": "L-MAIN",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(registry))
    league_registry.reload_registry()
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(
        server, "_get_auth_session", lambda request: {"username": "t", "sleeper_user_id": ""}
    )
    monkeypatch.setattr(server._terminal, "gather_news_items", lambda *a, **k: [])
    monkeypatch.setattr(
        collect, "collect_sharp", lambda index: (rec.unobserved("sharp_market", "error:X"), [])
    )
    _flags(consensus_edge=False, bdvm=False)
    yield TestClient(server.app)
    monkeypatch.undo()
    league_registry.reload_registry()


def test_route_serves_the_reconciled_roster(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    resp = client.get("/api/signals/reconciled", params={"team": "owner-1"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["leagueKey"] == "dynasty_main"
    assert body["team"] == {"ownerId": "owner-1", "name": "Alpha Team"}
    assert body["method"]["numericBlend"] is False
    assert [p["playerKey"] for p in body["players"]] == ["player:90001", "player:90002"]
    assert resp.headers["cache-control"] == "private, no-store"


def test_route_refuses_without_a_contract(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", None)
    resp = client.get("/api/signals/reconciled")
    assert resp.status_code == 503
    assert resp.json()["error"] == "data_not_ready"


def test_route_refuses_a_foreign_league_contract(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract(league_key="someone_else"))
    resp = client.get("/api/signals/reconciled")
    assert resp.status_code == 503
    assert resp.json()["error"] == "data_not_ready"


def test_route_rejects_an_unknown_scope(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    resp = client.get("/api/signals/reconciled", params={"scope": "everything"})
    assert resp.status_code == 400


def test_route_rejects_an_unknown_league(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    resp = client.get("/api/signals/reconciled", params={"leagueKey": "no_such_league"})
    assert resp.status_code == 400
    assert resp.json()["error"] == "unknown_league"


def test_route_is_private(monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: False)
    resp = TestClient(server.app).get("/api/signals/reconciled")
    assert resp.status_code == 401


# ── review follow-ups: placement basis, scope, owner refusals ───────────


def test_roster_resolves_by_player_id_and_reports_ids_off_the_board():
    contract = _contract()
    team = {
        **contract["sleeper"]["teams"][0],
        # Names deliberately disagree with the ids: ids must win.
        "players": ["Wrong Name One", "Wrong Name Two"],
        "playerIds": ["90001", "90002", "77777"],
    }
    keys, missed, basis = collect.roster_keys(collect.build_identity_index(contract), team)
    assert basis == "player_id"
    assert keys == ["player:90001", "player:90002"]
    assert missed == [
        {
            "emitter": None,
            "playerId": "77777",
            "name": None,
            "reason": "not_on_canonical_board",
            "scope": "roster",
        }
    ]


def test_roster_without_ids_falls_back_to_names_and_says_so():
    contract = _contract()
    _keys, _missed, basis = collect.roster_keys(
        collect.build_identity_index(contract), contract["sleeper"]["teams"][0]
    )
    assert basis == "name_fallback"


def test_consensus_edge_rows_are_placed_by_player_key_with_name_as_labelled_fallback():
    _flags(consensus_edge=True, bdvm=False)
    contract = _contract()
    by_key = {**_ce_row("Abbrev Z.", "QB", "Buy"), "playerKey": "Zed Sigalpha"}
    by_name = {**_ce_row("Yan Sigbravo", "WR", "Sell"), "playerKey": "not-a-board-name"}
    with mock.patch(
        "src.consensus_edge.api.board_for_contract", return_value=_ce_board([by_key, by_name])
    ):
        run, missed = collect.collect_consensus_edge(
            contract, collect.build_identity_index(contract), freshness={"state": "fresh"}
        )
    placed = {obs.player_key: obs.placement for obs in run.observations}
    assert placed == {
        "player:90001": "emitter_key",
        "player:90002": "name_fallback:exact_name",
    }
    assert missed == []


def test_bdvm_unpriced_rows_carry_the_owners_reason():
    _flags(consensus_edge=False, bdvm=True)
    contract = _contract()
    values = {
        "status": "ok",
        "meta": {"asOf": "2026-10-06"},
        "players": [],
        "unpriced": [
            {"name": "Yan Sigbravo", "reason": "no_projection", "position": "WR"},
            {"name": "Nobody Real", "reason": "missing_age", "position": "RB"},
        ],
    }
    with mock.patch("src.api.bdvm_api.get_bdvm_values", return_value=values):
        payload = _build(
            contract,
            resolved_team=contract["sleeper"]["teams"][0],
            news_items=[],
            collectors=("bdvm_market_signal",),
        )
    yan = [p for p in payload["players"] if p["playerKey"] == "player:90002"][0]
    assert yan["emittersDeclined"] == [{"emitter": "bdvm_market_signal", "reason": "no_projection"}]
    assert "bdvm_market_signal" not in yan["emittersSilent"]
    assert any(
        u.get("emitterUnpricedReason") == "missing_age" and u["reason"] == "unresolved"
        for u in payload["unresolved"]
    )


def test_league_scope_marks_off_roster_players_out_of_scope_for_the_terminal_engine():
    _flags(consensus_edge=True, bdvm=False)
    contract = _contract()
    board = _ce_board([_ce_row("Sam Twin", "LB", "Buy")])
    with mock.patch("src.consensus_edge.api.board_for_contract", return_value=board):
        payload = _build(
            contract,
            resolved_team=contract["sleeper"]["teams"][0],
            news_items=[],
            scope="league",
        )
    sam = [p for p in payload["players"] if p["playerKey"] == "player:90005"][0]
    assert sam["emittersOutOfScope"] == ["terminal_signal"]
    assert "terminal_signal" not in sam["emittersSilent"]


@pytest.mark.parametrize("limit, expect_truncated", [(1, True), (5, False)])
def test_sharp_beyond_its_asset_limit_is_out_of_scope(monkeypatch, limit, expect_truncated):
    contract = _contract()
    monkeypatch.setattr(collect, "_SHARP_ASSET_LIMIT", limit)
    sharp = {
        "status": "ok",
        "query": {"window": "30d"},
        "assets": [{"assetId": "90001", "displayName": "Zed Sigalpha", "net": 3}],
        "coverage": {"platforms": {}},
    }
    with mock.patch("src.sharp.market.market_payload", return_value=sharp):
        run, _ = collect.collect_sharp(collect.build_identity_index(contract))
    payload = rec.reconcile([run], player_keys=["player:90001", "player:90002"])
    yan = [p for p in payload["players"] if p["playerKey"] == "player:90002"][0]
    if expect_truncated:
        assert yan["emittersOutOfScope"] == ["sharp_market"]
    else:
        assert yan["emittersSilent"] == ["sharp_market"]


# ── N1 (re-review of #1705): an off-board id never lands on a namesake ──


def _namesake_contract():
    return {"playersArray": [_row("Josh Allen", "4984", "QB")]}


def test_an_off_board_id_is_never_filed_on_a_namesake_with_a_different_id():
    """Repro: an emitter row for id 9999 named Josh Allen; the board has QB 4984."""
    index = collect.build_identity_index(_namesake_contract())
    assert index.resolve_with_basis(player_id="9999", name="Josh Allen", position="LB") == (
        None,
        "id_not_on_board",
        None,
    )
    # The candidate's OWN id contradicts the emitter's id, so no position
    # agreement can override it.
    for position in (None, "QB"):
        key = index.resolve_with_basis(player_id="9999", name="Josh Allen", position=position)[0]
        assert key is None, position


def test_a_single_name_candidate_must_agree_on_position_group():
    index = collect.build_identity_index(_namesake_contract())
    assert index.resolve(name="Josh Allen", position="LB") == (None, "position_conflict")
    assert index.resolve(name="Josh Allen", position="QB") == ("player:4984", None)
    assert index.resolve(name="Josh Allen") == ("player:4984", None)


def test_sharp_row_for_an_off_board_namesake_is_not_misattributed():
    index = collect.build_identity_index(_namesake_contract())
    sharp = {
        "status": "ok",
        "query": {"window": "30d"},
        "assets": [{"assetId": "9999", "displayName": "Josh Allen", "position": "LB", "net": 4}],
        "coverage": {"platforms": {}},
    }
    with mock.patch("src.sharp.market.market_payload", return_value=sharp):
        run, missed = collect.collect_sharp(index)
    assert run.observations == ()
    assert [(m["playerId"], m["reason"]) for m in missed] == [("9999", "id_not_on_board")]


def test_player_query_by_name_is_not_treated_as_an_off_board_id():
    _flags(consensus_edge=False, bdvm=False)
    payload = _build(_contract(), resolved_team=None, news_items=None, player="Zed Sigalpha")
    assert payload["playerFilter"]["playerKey"] == "player:90001"
    assert [p["playerKey"] for p in payload["players"]] == ["player:90001"]


def test_the_namesake_reads_unplaced_for_sharp_not_silent():
    contract = {"playersArray": [_row("Josh Allen", "4984", "QB")]}
    sharp = {
        "status": "ok",
        "query": {"window": "30d"},
        "assets": [{"assetId": "9999", "displayName": "Josh Allen", "position": "LB", "net": 4}],
        "coverage": {"platforms": {}},
    }
    with mock.patch("src.sharp.market.market_payload", return_value=sharp):
        run, _ = collect.collect_sharp(collect.build_identity_index(contract))
    payload = rec.reconcile([run], player_keys=["player:4984"])
    [allen] = payload["players"]
    assert allen["emittersUnplaced"] == [{"emitter": "sharp_market", "reason": "id_not_on_board"}]
    assert allen["signals"] == []


def test_bdvm_skipped_quarantined_rows_are_declined_as_quarantined():
    _flags(consensus_edge=False, bdvm=True)
    contract = _contract()
    values = {"status": "ok", "meta": {}, "players": [], "unpriced": []}
    with mock.patch("src.api.bdvm_api.get_bdvm_values", return_value=values):
        run, _ = collect.collect_bdvm(
            contract,
            collect.build_identity_index(contract),
            league_key="dynasty_main",
            freshness={"state": "fresh"},
        )
    assert run.declined == {"player:90003": "quarantined"}


def test_route_flags_an_explicit_team_that_did_not_resolve(client, monkeypatch):
    monkeypatch.setattr(server, "latest_contract_data", _contract())
    body = client.get("/api/signals/reconciled", params={"team": "no-such-owner"}).json()
    assert body["teamResolution"] == {
        "requested": {"ownerId": "no-such-owner", "teamName": None},
        "resolved": False,
        "source": None,
        "reason": "team_not_found",
    }
    ok = client.get("/api/signals/reconciled", params={"team": "owner-1"}).json()
    assert ok["teamResolution"]["resolved"] is True
    assert ok["teamResolution"]["source"] == "explicit"


# ── C6-SIG-02: what a league-wide consumer needs to apply "SELL only for ──
# ── the selected roster" without re-joining identity in the browser ──────


def test_league_scope_publishes_the_resolved_rosters_membership():
    _flags(consensus_edge=True, bdvm=False)
    contract = _contract()
    board = _ce_board([_ce_row("Sam Twin", "LB", "Buy"), _ce_row("Zed Sigalpha", "QB", "Sell")])
    with mock.patch("src.consensus_edge.api.board_for_contract", return_value=board):
        payload = _build(
            contract,
            resolved_team=contract["sleeper"]["teams"][0],
            news_items=[],
            scope="league",
        )
    assert payload["scope"] == "league"
    # Membership comes from the same identity join the roster scope uses;
    # the off-board name is counted, never dropped silently.
    assert payload["roster"] == {
        "playerKeys": ["player:90001", "player:90002"],
        "placement": "name_fallback",
        "unresolvedCount": 1,
    }
    # The league universe is unchanged by publishing membership.
    keys = {p["playerKey"] for p in payload["players"]}
    assert "player:90005" in keys


def test_no_resolved_team_publishes_no_roster_rather_than_an_empty_one():
    _flags(consensus_edge=False, bdvm=False)
    payload = _build(_contract(), resolved_team=None, news_items=None, scope="league")
    assert payload["roster"] is None


def test_each_player_carries_the_contract_rows_own_board_stamps_verbatim():
    _flags(consensus_edge=True, bdvm=False)
    contract = _contract()
    contract["playersArray"][1]["canonicalConsensusRank"] = None  # off the ranked board
    board = _ce_board([_ce_row("Zed Sigalpha", "QB", "Buy"), _ce_row("Yan Sigbravo", "WR", "Buy")])
    with mock.patch("src.consensus_edge.api.board_for_contract", return_value=board):
        payload = _build(contract, resolved_team=None, news_items=[], scope="league")
    by_key = {p["playerKey"]: p for p in payload["players"]}
    assert by_key["player:90001"]["board"] == {
        "canonicalConsensusRank": 50,
        "position": "QB",
        "assetClass": "offense",
    }
    # Rank-less is None — never 0, which would sort it first.
    assert by_key["player:90002"]["board"]["canonicalConsensusRank"] is None
