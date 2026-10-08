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
