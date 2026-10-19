"""One 2-team analysis owner (Brisket Trade Advisor B0-c).

* both private routes call ``src.trade.analyze_service`` (AST guard), and no
  other module composes ``simulate_trade`` with ``analyze_trade`` — a copy of
  the orchestration is a second owner;
* the posture build rule (``build_if_missing = for_analysis and
  team_context``) and the roster-utility rule are the service's;
* provenance comes from the contract passed in, not a global;
* the War Room fixtures are generated through the service and stay
  byte-equal (``tests/trade/test_war_room_ui_fixtures.py``).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from src.trade import analyze_service

REPO = Path(__file__).resolve().parents[2]


def _calls(node: ast.AST) -> set[str]:
    """Every function REFERENCED in ``node`` — called directly or handed to
    ``run_in_threadpool`` (which is how the routes invoke sync work)."""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, ast.Name):
            out.add(n.id)
    return out


def _server_functions() -> dict[str, ast.AST]:
    tree = ast.parse((REPO / "server.py").read_text(encoding="utf-8"))
    return {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def test_private_routes_delegate_to_the_service():
    fns = _server_functions()
    build = _calls(fns["_build_trade_simulation"])
    assert "simulate_for_team" in build
    assert "simulate_trade" not in build, "the route must not call the simulator directly"
    assert "competitive_posture_for" not in build, "the posture rule belongs to the service"
    analyze = _calls(fns["post_trade_analyze"])
    assert "analyze_for_team" in analyze
    assert "analyze_trade" not in analyze
    simulate = _calls(fns["post_trade_simulate"])
    assert "_build_trade_simulation" in simulate


def test_nothing_else_composes_simulate_trade_with_analyze_trade():
    offenders = []
    allowed = {
        REPO / "src/trade/analyze_service.py",
        REPO / "src/api/trade_simulator.py",
    }
    for path in [REPO / "server.py", *sorted((REPO / "src").rglob("*.py"))]:
        if path in allowed:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                calls = _calls(fn)
                if "simulate_trade" in calls and "analyze_trade" in calls:
                    offenders.append(f"{path.relative_to(REPO)}::{fn.name}")
                if "simulate_trade" in calls and "competitive_posture_for" in calls:
                    offenders.append(f"{path.relative_to(REPO)}::{fn.name} (posture)")
    assert offenders == []


@pytest.mark.parametrize(
    ("team_context", "for_analysis", "build", "utility"),
    [(True, True, True, True), (False, True, False, False), (True, False, False, False)],
)
def test_posture_and_utility_rules(monkeypatch, team_context, for_analysis, build, utility):
    seen = {}

    def resolver(contract, league_key, team, *, build_if_missing):
        seen["build"] = build_if_missing
        return {"available": False, "unavailableReason": "test"}

    def fake_sim(contract, **kw):
        seen["utility"] = kw["include_roster_utility"]
        seen["posture"] = kw["competitive_posture"]
        return {"team": None}

    monkeypatch.setattr(analyze_service.trade_simulator, "simulate_trade", fake_sim)
    out = analyze_service.simulate_for_team(
        {},
        league_key="k",
        roster_settings={},
        resolved_team={"name": "x"},
        team_context=team_context,
        for_analysis=for_analysis,
        posture_resolver=resolver,
    )
    assert seen["build"] is build and seen["utility"] is utility
    assert seen["posture"] == {"available": False, "unavailableReason": "test"}
    if for_analysis:
        assert out["teamContext"] == {
            "applied": team_context,
            "mode": "team" if team_context else "asset_only",
        }
    else:
        assert "teamContext" not in out


def test_stage_hook_observes_each_step():
    from contextlib import contextmanager

    names = []

    @contextmanager
    def stage(name):
        names.append(name)
        yield

    analyze_service.simulate_for_team(
        {"playersArray": []},
        league_key=None,
        roster_settings=None,
        resolved_team=None,
        team_context=False,
        for_analysis=False,
        posture_resolver=lambda *a, **k: None,
        stage=stage,
    )
    assert names == ["posture", "simulation"]


def test_provenance_comes_from_the_passed_contract(monkeypatch):
    captured = {}

    def fake_analyze(simulation, **kw):
        captured.update(kw)
        return {"decision": {}}

    import src.trade.analyze_trade as at

    monkeypatch.setattr(at, "analyze_trade", fake_analyze)
    contract = {"meta": {"generatedAt": "G1", "scoringFingerprint": "sf2:abc"}}
    analyze_service.analyze_for_team({}, contract=contract, counterfactuals=False)
    assert captured["provenance"] == {"boardStamp": "G1", "scoringFingerprint": "sf2:abc"}
    assert captured["counterfactuals"] is False
    assert analyze_service.contract_provenance(None) == {
        "boardStamp": None,
        "scoringFingerprint": None,
    }


# ── through the real route ───────────────────────────────────────────────


from tests.api.test_league_routing import two_league_registry  # noqa: E402,F401 — fixture


def test_simulate_route_accepts_parallel_player_ids(two_league_registry, monkeypatch):  # noqa: F811
    import server
    from tests.api.test_trade_nfl_exposure import _contract

    c = _contract(league_key="main")
    for r in c["playersArray"]:
        if r.get("assetClass") != "pick":
            r["playerId"] = r["displayName"].lower()
    seen = {}
    real = analyze_service.simulate_for_team

    def spy(contract, **kw):
        seen.update(kw)
        return real(contract, **kw)

    monkeypatch.setattr(analyze_service, "simulate_for_team", spy)
    from fastapi.testclient import TestClient

    with TestClient(server.app, raise_server_exceptions=True) as client:
        monkeypatch.setattr(server, "latest_contract_data", c)
        monkeypatch.setattr(server, "_get_auth_session", lambda _r: {"sleeper_user_id": "o1"})
        res = client.post(
            "/api/trade/simulate",
            json={
                "leagueKey": "main",
                "team": "o1",
                "playersIn": ["WR Buf Star"],
                "playerIdsIn": ["wr buf star"],
                "playersOut": ["Whatever Name", "WR Phi"],
                "playerIdsOut": ["wr kc", None],
            },
        )
    assert res.status_code == 200, res.text
    assert seen["player_ids_in"] == ["wr buf star"]
    assert seen["player_ids_out"] == ["wr kc", None]
    body = res.json()
    assert sorted(a["name"] for a in body["sending"]) == ["WR Kc", "WR Phi"]
    assert body["unresolvedOut"] == []
