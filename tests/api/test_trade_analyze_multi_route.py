"""``POST /api/trade/analyze-multi`` (N-team spec §3.1) and the 2-team
equivalence I4: for N = 2, every team's ``simulation`` + ``analysis`` from the
shared N-team engine equal what the EXISTING ``/api/trade/analyze`` route
returns for that team, driven by the War Room's real request shape on the real
archived board (``tests/trade/multi_team_support.real_board``).

The private flag ships OFF; these tests force it on (spec §6.1: the parity and
route tests run with the flag forced on, whatever the production default).
"""

from __future__ import annotations

import copy
import json
import random
from datetime import datetime, timezone

import pytest

from src.api import feature_flags
from src.trade import analyze_service as svc
from src.trade import trade_ledger as tl
from tests.trade import multi_team_support as mts

#: Fields the 2-team ROUTE stamps on top of the shared simulation (route-level
#: context, not engine output): NFL exposure, the league echo, the valuation
#: lens stamp (which also carries ``packageModel``) and request timing.
ROUTE_ONLY_SIMULATION_KEYS = {
    "nflExposure",
    "leagueKey",
    "valuationMode",
    "valuationNote",
    "packageModel",
    "analysisTiming",
    "analysis",
}
#: Per-request receipt id the route adds to ``analysis``.
ROUTE_ONLY_ANALYSIS_KEYS = {"decisionRunId"}


class _Posture:
    """A LABELLED synthetic posture object (``.to_dict()`` like the owner's)."""

    def __init__(self, owner_id: str) -> None:
        self.owner_id = owner_id

    def to_dict(self) -> dict:
        return {
            "label": "HOLD",
            "probabilities": {"PUSH": 0.3, "HOLD": 0.4, "RETOOL": 0.2, "REBUILD": 0.1},
            "confidence": "LOW",
            "paramsVersion": "posture_v1_prior",
            "notes": ["SYNTHETIC_FIXTURE_POSTURE (LABELLED)", self.owner_id],
        }


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", "1")
    feature_flags.reload()
    yield
    monkeypatch.delenv("RISKIT_FEATURE_TRADE_MULTI_TEAM_ANALYSIS", raising=False)
    feature_flags.reload()


@pytest.fixture
def real_registry(tmp_path, monkeypatch):
    """The suite points the registry at a missing file (tests/conftest.py);
    these tests need the real ``dynasty_main`` entry, copied verbatim."""
    from src.api import league_registry

    real = json.loads((mts.REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    main = next(lg for lg in real["leagues"] if lg["key"] == "dynasty_main")
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps({"schemaVersion": 1, "defaultLeagueKey": "dynasty_main", "leagues": [main]}),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield
    monkeypatch.undo()
    league_registry.reload_registry()


@pytest.fixture
def app(monkeypatch, tmp_path, real_registry):
    import server
    import src.api.gameplan as gameplan

    contract, _snap, _label = mts.real_board()
    contract["sleeper"]["rosterFetchedAt"] = datetime.now(timezone.utc).isoformat()
    owners = {str(t.get("ownerId") or "") for t in contract["sleeper"]["teams"]} - {""}
    monkeypatch.setattr(
        gameplan,
        "league_competitive_postures",
        lambda league_key, profile, c, *, build_if_missing: (
            {o: _Posture(o) for o in owners},
            {"bundleFreshness": "fresh"},
        ),
    )
    monkeypatch.setattr(server, "latest_contract_data", contract)
    monkeypatch.setattr(
        server, "_get_auth_session", lambda _r: {"username": "tester", "sleeper_user_id": "u1"}
    )
    monkeypatch.setenv("RISKIT_TRADE_DECISION_LOG_DIR", str(tmp_path))
    tl.clear_snapshot_memo()
    from fastapi.testclient import TestClient

    with TestClient(server.app, raise_server_exceptions=True) as client:
        monkeypatch.setattr(server, "latest_contract_data", contract)
        yield client, contract
    tl.clear_snapshot_memo()


def _snap(contract):
    return tl.snapshot_for(
        contract,
        league_key="dynasty_main",
        roster_settings=mts._dynasty_main_settings(),
    )


def _body(teams, legs, **extra):
    return {"leagueKey": "dynasty_main", "teams": teams, "assets": legs, **extra}


# ══ Gate, auth, body ═══════════════════════════════════════════════════════


def test_flag_off_by_default_answers_disabled(app):
    client, _contract = app
    feature_flags.reload()
    assert feature_flags._DEFAULTS["trade_multi_team_analysis"] is False
    res = client.post("/api/trade/analyze-multi", json=_body([1, 2], []))
    assert res.status_code == 503
    assert res.json()["error"] == "multi_team_analysis_disabled"
    assert res.headers["cache-control"] == "no-store"


def test_unauthenticated_is_refused(app, flag_on, monkeypatch):
    import server

    client, _contract = app
    monkeypatch.setattr(server, "_get_auth_session", lambda _r: None)
    res = client.post("/api/trade/analyze-multi", json=_body([1, 2], []))
    assert res.status_code == 401


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ([1, 2], "body"),
        ({"teams": "1,2", "assets": []}, "teams"),
        ({"teams": [1, True], "assets": []}, "teams"),
        ({"teams": [1, 2], "assets": [{"id": 5, "from": 1, "to": 2}]}, "assets"),
        ({"teams": [1, 2], "assets": [], "useTeamContext": "yes"}, "useTeamContext"),
        ({"teams": [1, 2], "assets": [], "perspectiveRosterId": "1"}, "perspectiveRosterId"),
        ({"teams": [1, 2], "assets": [], "teamGoals": {"x": "WIN_NOW"}}, "teamGoals"),
    ],
)
def test_malformed_body_is_invalid_request(app, flag_on, body, field):
    client, _contract = app
    res = client.post("/api/trade/analyze-multi", json=body)
    assert res.status_code == 400
    assert res.json() == {
        "error": "invalid_request",
        "message": "The request body is malformed.",
        "field": field,
    }


def test_ledger_refusals_use_the_private_error_shape(app, flag_on):
    client, contract = app
    snap = _snap(contract)
    rids = sorted(snap.teams_by_roster_id)
    a, b = rids[0], rids[1]
    asset_a = mts.team_assets(snap, a)[0]
    asset_b = mts.team_assets(snap, b)[0]
    res = client.post(
        "/api/trade/analyze-multi",
        json=_body([a, b], [{"id": asset_a, "from": a, "to": a}]),
    )
    assert res.status_code == 400
    assert res.json()["reason"] == "destination_is_origin"
    assert res.json()["assetIds"] == [asset_a]
    res = client.post(
        "/api/trade/analyze-multi",
        json=_body([a, b], [{"id": asset_b, "from": a, "to": b}]),
    )
    assert res.status_code == 409
    body = res.json()
    assert (body["error"], body["reason"], body["assetIds"]) == (
        "stale_assets",
        "asset_not_owned",
        [asset_b],
    )
    assert "rosterIds" not in body  # the actual owner is never revealed
    res = client.post(
        "/api/trade/analyze-multi",
        json=_body(
            [a, b],
            [{"id": asset_a, "from": a, "to": b}, {"id": asset_b, "from": b, "to": a}],
            perspectiveRosterId=rids[2],
        ),
    )
    assert res.status_code == 400
    assert res.json()["reason"] == "perspective_not_in_trade"


def test_ktc_rollback_model_refuses(app, flag_on, monkeypatch):
    from src.valuation_math import package_model

    client, contract = app
    monkeypatch.setattr(
        package_model, "_config", lambda: {"active": "ktc_2026_04", "shadow": [], "state": "ok"}
    )
    res = client.post("/api/trade/analyze-multi", json=_body([1, 2], []))
    assert res.status_code == 503
    assert res.json()["error"] == "package_model_unavailable"


# ══ Success contract ═══════════════════════════════════════════════════════


def _three_team(snap, seed=3):
    teams, legs = mts.random_ledger(snap, random.Random(seed), n_teams=3, max_per_team=2)
    return teams, legs


def test_three_team_success_contract(app, flag_on):
    client, contract = app
    snap = _snap(contract)
    teams, legs = _three_team(snap)
    res = client.post(
        "/api/trade/analyze-multi",
        json=_body(teams, legs, useTeamContext=False, perspectiveRosterId=teams[1]),
    )
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    assert "server-timing" in res.headers and ":" not in res.headers["server-timing"]
    body = res.json()
    for key in (
        "multiTeamVersion",
        "leagueKey",
        "valuationMode",
        "generation",
        "snapshotChanged",
        "rosters",
        "mode",
        "perspectiveRosterId",
        "teamCount",
        "teams",
        "summary",
        "ledger",
        "packageModel",
        "fairnessBands",
        "decisionRunIds",
        "tradeRunId",
        "analysisTiming",
    ):
        assert key in body, key
    assert body["mode"] == "asset_only" and body["teamCount"] == 3
    assert body["valuationMode"] == "market"
    assert body["packageModel"]["id"] == "geom_q078_v1"
    assert body["snapshotChanged"] is None
    assert [t["rosterId"] for t in body["teams"]] == sorted(teams)
    assert set(body["decisionRunIds"]) == {str(r) for r in teams}
    for t in body["teams"]:
        assert t["analysis"]["decision"]["recommendationOnly"] is True
        assert t["analysis"]["decision"]["executes"] is False
        assert t["category"] in (
            "STRONGLY_FAVORABLE",
            "FAVORABLE",
            "APPROXIMATELY_EVEN",
            "UNFAVORABLE",
            "STRONGLY_UNFAVORABLE",
            "UNAVAILABLE",
        )
        assert t["fairness"]["state"] in ("FAIR", "NOT_FAIR", "UNABLE")
    summary = body["summary"]
    assert summary["conservation"]["balanced"] is True
    for banned in ("overallRecommendation", "winner", "headline"):
        assert banned not in summary


def test_route_is_team_order_and_asset_order_independent(app, flag_on):
    """I1 / I2 through the route: byte-identical apart from the perspective
    echo, timing and receipt ids."""
    client, contract = app
    snap = _snap(contract)
    teams, legs = _three_team(snap, seed=5)

    def _post(t, lg):
        res = client.post("/api/trade/analyze-multi", json=_body(t, lg, useTeamContext=False))
        assert res.status_code == 200, res.text
        body = res.json()
        for key in ("analysisTiming", "decisionRunIds", "tradeRunId", "perspectiveRosterId"):
            body.pop(key, None)
        for team in body["teams"]:
            team["analysis"].pop("decisionRunId", None)
        return json.dumps(body, sort_keys=True)

    ref = _post(teams, legs)
    assert _post(teams[::-1], legs[::-1]) == ref


def test_snapshot_changed_reports_a_moved_board(app, flag_on):
    client, contract = app
    snap = _snap(contract)
    teams, legs = _three_team(snap)
    res = client.post(
        "/api/trade/analyze-multi",
        json=_body(teams, legs, useTeamContext=False, expectedGeneration="older-board"),
    )
    assert res.json()["snapshotChanged"] is True
    res = client.post(
        "/api/trade/analyze-multi",
        json=_body(teams, legs, useTeamContext=False, expectedGeneration=snap.generation),
    )
    assert res.json()["snapshotChanged"] is False


def test_guest_sessions_get_total_timing_only(app, flag_on, monkeypatch):
    import server

    client, contract = app
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda _r: {"username": "guest", "auth_method": "guest_pass", "guest_pass_id": "g1"},
    )
    snap = _snap(contract)
    teams, legs = _three_team(snap)
    res = client.post("/api/trade/analyze-multi", json=_body(teams, legs, useTeamContext=False))
    assert res.status_code == 200
    timing = res.json()["analysisTiming"]
    assert timing["detail"] == "total_only" and "stages" not in timing


def test_invariant_violation_fails_closed_with_500(app, flag_on, monkeypatch):
    client, contract = app

    def boom(*_a, **_k):
        raise svc.ConservationViolation("LABELLED test injection")

    monkeypatch.setattr(svc, "analyze_trade_n", boom)
    snap = _snap(contract)
    teams, legs = _three_team(snap)
    res = client.post("/api/trade/analyze-multi", json=_body(teams, legs))
    assert res.status_code == 500
    assert res.json()["error"] == "internal_error"


# ══ I4: N = 2 through the engine == the existing /api/trade/analyze route ══


def _war_room_request(snap, rid, flows, *, team_context: bool) -> dict:
    """The War Room's real request shape for one team of a 2-team ledger:
    labels + parallel ``playerIds*`` / ``pickAssetIds*``, canonical order."""
    team = snap.teams_by_roster_id[rid]
    return {
        "leagueKey": "dynasty_main",
        "team": str(team.get("ownerId") or ""),
        "teamName": str(team.get("name") or ""),
        "playersIn": [tl.player_label(snap, p) for p in flows.player_ids_in],
        "playerIdsIn": list(flows.player_ids_in),
        "playersOut": [tl.player_label(snap, p) for p in flows.player_ids_out],
        "playerIdsOut": list(flows.player_ids_out),
        "picksIn": [tl.pick_label(snap, a) for a in flows.pick_ids_in],
        "pickAssetIdsIn": list(flows.pick_ids_in),
        "picksOut": [tl.pick_label(snap, a) for a in flows.pick_ids_out],
        "pickAssetIdsOut": list(flows.pick_ids_out),
        "useTeamContext": team_context,
    }


def _two_team_ledgers(snap):
    out = [(r["teams"], r["legs"]) for r in mts.reverse_replays(snap, sides=2)[:3]]
    rng = random.Random(42)
    for _ in range(2):
        out.append(mts.random_ledger(snap, rng, n_teams=2, max_per_team=3))
    return out


@pytest.mark.parametrize("team_context", [True, False])
def test_i4_two_team_engine_equals_the_existing_analyze_route(app, team_context):
    client, contract = app
    snap = _snap(contract)
    from src.trade import comparable_trades as _comparable

    import server

    def provider(flows, simulation):
        return _comparable.comparable_trades(
            "dynasty_main",
            side_a=_comparable.side_refs_from_assets(simulation.get("receiving") or []),
            side_b=_comparable.side_refs_from_assets(simulation.get("sending") or []),
            names=server._board_names_by_player_id(),
        )

    checked = 0
    for teams, legs in _two_team_ledgers(snap):
        ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
        for rid in ledger.teams:
            flows = tl.team_flows(ledger, rid)
            res = client.post(
                "/api/trade/analyze",
                json=_war_room_request(snap, rid, flows, team_context=team_context),
            )
            assert res.status_code == 200, res.text
            route = res.json()
            # Engine second: any shared before-roster cache the route warmed is
            # exact (content-addressed), so the order cannot change the answer.
            out = svc.analyze_trade_n(
                snap,
                ledger,
                mode="team_context" if team_context else "asset_only",
                counterfactuals=True,
                comparables_provider=provider,
            )
            engine = json.loads(json.dumps(out["teams"][rid], default=str))
            if not str(snap.teams_by_roster_id[rid].get("ownerId") or ""):
                # The ONE listed difference (spec R15, a correctness fix): an
                # orphan team (no ownerId) cannot be looked up in the
                # ownerId-keyed posture bundle.  The 2-team route reports
                # ``team_not_in_league_bundle``; the engine names the cause,
                # ``owner_identity_ambiguous``.  Both are unavailable, so both
                # raise ``posture_unknown`` and decide the same headline.
                assert (
                    engine["simulation"]["competitivePosture"]["unavailableReason"]
                    == "owner_identity_ambiguous"
                )
                assert route["competitivePosture"]["available"] is False
                assert (
                    engine["analysis"]["decision"]["headline"]
                    == route["analysis"]["decision"]["headline"]
                )
                checked += 1
                continue
            route_sim = {k: v for k, v in route.items() if k not in ROUTE_ONLY_SIMULATION_KEYS}
            route_analysis = {
                k: v for k, v in route["analysis"].items() if k not in ROUTE_ONLY_ANALYSIS_KEYS
            }
            assert json.dumps(engine["simulation"], sort_keys=True) == json.dumps(
                route_sim, sort_keys=True
            ), (teams, rid)
            assert json.dumps(engine["analysis"], sort_keys=True) == json.dumps(
                route_analysis, sort_keys=True
            ), (teams, rid)
            checked += 1
    assert checked >= 4


def test_two_team_route_is_unchanged_by_this_feature(app):
    """``/api/trade/analyze`` still answers with the flag OFF and carries no
    multi-team field."""
    client, contract = app
    feature_flags.reload()
    snap = _snap(contract)
    teams, legs = mts.random_ledger(snap, random.Random(8), n_teams=2)
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
    flows = tl.team_flows(ledger, ledger.teams[0])
    res = client.post(
        "/api/trade/analyze",
        json=_war_room_request(snap, ledger.teams[0], flows, team_context=False),
    )
    assert res.status_code == 200
    body = res.json()
    for key in ("multiTeamVersion", "summary", "ownershipEvidence", "teams"):
        assert key not in body
    assert copy.deepcopy(body["analysis"]["decision"]["headline"]) in (
        "YES",
        "NO",
        "NO_TOO_CLOSE",
        "NOT_ENOUGH_EVIDENCE",
    )
