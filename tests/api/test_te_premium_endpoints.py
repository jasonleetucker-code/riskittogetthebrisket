"""Endpoint contract tests for the TE Premium Lab sandbox.

Coverage:

* All four endpoints respond 200 with the documented payload shape
  when ``latest_contract_data`` carries TE rows.
* Mutation safety: ``latest_contract_data`` is byte-identical before
  and after every endpoint call (the most important invariant — these
  endpoints must never reach into the live contract).
* Stable schema across runs: a second call to ``run-analysis``
  returns the same top-level keys.
* Graceful behaviour when the contract is empty (no scrape yet).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry as _league_registry
from src.research import te_premium as tep


def _make_te_row(
    name: str,
    sleeper_id: str,
    *,
    composite: float = 5000,
    age: int = 26,
    ppg_baseline: float = 11.0,
    ppg_league: float = 10.5,
    ktc: float | None = 6500,
    ktc_sf_tep: float | None = 7000,
) -> dict:
    return {
        "displayName": name,
        "_sleeperId": sleeper_id,
        "position": "TE",
        "age": age,
        "team": "BUF",
        "_composite": composite,
        "rankDerivedValue": composite,
        "ktc": ktc,
        "ktcSfTep": ktc_sf_tep,
        "_formatFitPPGTest": ppg_baseline,
        "_formatFitPPGCustom": ppg_league,
        "_scoringAdjustment": {
            "final_scoring_delta_points": -0.5,
            "rule_contributions": {
                "te_premium": -0.4,
                "first_downs": 2.5,
                "receptions": -2.6,
            },
            "archetype": "chain_mover",
            "confidence": 0.7,
        },
    }


@pytest.fixture
def client_with_te_contract(tmp_path, monkeypatch):
    """Install a synthetic contract with a TE pool, point the league
    registry at a real test fixture, bypass auth, and yield a
    TestClient that talks to ``server.app``.

    The global conftest deliberately points
    ``LEAGUE_REGISTRY_PATH`` at a missing file so tests don't leak
    onto the operator's real registry.  We override that for the
    duration of this fixture so ``_resolve_league_for_request``
    actually has a default league to resolve.  Same pattern as
    ``tests/api/test_league_routing.py::two_league_registry``."""
    # Real test registry — minimal but enough for resolution.
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "dynasty_main",
                "leagues": [
                    {
                        "key": "dynasty_main",
                        "displayName": "Risk It (Test)",
                        "sleeperLeagueId": "L-TEST",
                        "scoringProfile": "superflex_tep15_ppr1",
                        "active": True,
                        "rosterSettings": {
                            "teamCount": 12,
                            "starters": {
                                "QB": 1, "RB": 2, "WR": 3, "TE": 1,
                                "FLEX": 2, "SFLEX": 1,
                            },
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(reg_path))
    _league_registry.reload_registry()

    rows = [
        _make_te_row(f"TE Player {i}", f"te_id_{i}", composite=9000 - i * 200)
        for i in range(20)
    ]
    contract = {
        "meta": {"leagueKey": "dynasty_main", "scoringProfile": "superflex_tep15_ppr1"},
        "players": {row["displayName"]: row for row in rows},
        "playersArray": [],
        "playerCount": len(rows),
    }
    original = server.latest_contract_data
    monkeypatch.setattr(server, "latest_contract_data", contract)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(
        server, "_get_auth_session",
        lambda r: {"username": "jasonleetucker"},
    )
    yield TestClient(server.app), contract
    monkeypatch.setattr(server, "latest_contract_data", original)
    # Restore the conftest's registry state so later tests don't see
    # this fixture's leagues bleed in.
    _league_registry.reload_registry()


def _snapshot(contract: dict) -> str:
    return json.dumps(contract, sort_keys=True, default=str)


# ── Overview ─────────────────────────────────────────────────────────


def test_overview_returns_sandbox_envelope(client_with_te_contract):
    client, _ = client_with_te_contract
    res = client.get("/api/te-premium/overview")
    assert res.status_code == 200, f"body: {res.text}"
    body = res.json()
    assert body["sandbox"] is True
    assert body["appliesToLiveValues"] is False
    assert body["te_count"] == 20
    assert body.get("note", "").lower().startswith("research-only")
    assert isinstance(body.get("sources"), list) and len(body["sources"]) >= 1
    assert isinstance(body.get("warnings"), list)


def test_overview_does_not_mutate_contract(client_with_te_contract):
    client, contract = client_with_te_contract
    before = _snapshot(contract)
    client.get("/api/te-premium/overview")
    after = _snapshot(contract)
    assert before == after, "Overview endpoint mutated latest_contract_data"


# ── Source comparison ───────────────────────────────────────────────


def test_source_comparison_shape(client_with_te_contract, monkeypatch):
    # Force the boards to be available so the response carries data.
    monkeypatch.setattr(
        tep,
        "load_external_ktc_boards",
        lambda **_: {
            "normal": {f"te player {i}": 9000 - i * 200 for i in range(20)},
            "premium": {f"te player {i}": (9000 - i * 200) * 1.1 for i in range(20)},
            "normal_path": "test",
            "premium_path": "test",
            "normal_available": True,
            "premium_available": True,
        },
    )
    client, _ = client_with_te_contract
    res = client.get("/api/te-premium/source-comparison")
    assert res.status_code == 200
    body = res.json()
    assert body["sandbox"] is True
    assert body["te_count"] == 20
    assert isinstance(body.get("boosts"), list)
    assert len(body["boosts"]) == 20
    # Every boost has the documented fields
    for b in body["boosts"]:
        assert {"source", "player_id", "display_name", "normal_value",
                "premium_value", "boost_pct", "reliable"}.issubset(b.keys())


def test_source_comparison_does_not_mutate_contract(client_with_te_contract):
    client, contract = client_with_te_contract
    before = _snapshot(contract)
    client.get("/api/te-premium/source-comparison")
    after = _snapshot(contract)
    assert before == after


# ── League scenarios ────────────────────────────────────────────────


def test_league_scenarios_returns_both_arrays(client_with_te_contract):
    client, _ = client_with_te_contract
    res = client.get("/api/te-premium/league-scenarios")
    assert res.status_code == 200
    body = res.json()
    assert body["sandbox"] is True
    assert isinstance(body.get("scoring_effect"), list)
    assert isinstance(body.get("scarcity_effect"), list)
    assert "scarcity_summary" in body
    assert "lineup" in body


def test_league_scenarios_does_not_mutate_contract(client_with_te_contract):
    client, contract = client_with_te_contract
    before = _snapshot(contract)
    client.get("/api/te-premium/league-scenarios")
    after = _snapshot(contract)
    assert before == after


# ── Run analysis ────────────────────────────────────────────────────


def test_run_analysis_default_scenario(client_with_te_contract):
    client, _ = client_with_te_contract
    res = client.post("/api/te-premium/run-analysis", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["sandbox"] is True
    assert body["appliesToLiveValues"] is False
    assert body["scenario"]["remove_te_reception_bonus"] is True
    assert body["scenario"]["remove_te_first_down_bonus"] is True
    assert body["scenario"]["use_two_te_starters"] is True
    assert "summary" in body
    assert "recommendations" in body
    assert "tier_summary" in body
    # Recommendations are clipped to ±25%
    for r in body["recommendations"]:
        assert -0.25 <= r["recommended_adjustment_pct"] <= 0.25


def test_run_analysis_respects_toggle_overrides(client_with_te_contract):
    client, _ = client_with_te_contract
    res = client.post(
        "/api/te-premium/run-analysis",
        json={
            "remove_te_reception_bonus": False,
            "remove_te_first_down_bonus": False,
            "use_two_te_starters": False,
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["scenario"]["remove_te_reception_bonus"] is False
    assert body["scenario"]["remove_te_first_down_bonus"] is False
    assert body["scenario"]["use_two_te_starters"] is False
    # Scoring swing should be zero when neither rule is removed.
    assert all(abs(s["scoring_swing_ppg"]) < 1e-6 for s in body["scoring_effect"])


def test_run_analysis_does_not_mutate_contract(client_with_te_contract):
    """Most important safety property — run twice with different
    scenarios and verify the contract bytes never change."""
    client, contract = client_with_te_contract
    before = _snapshot(contract)
    client.post("/api/te-premium/run-analysis", json={})
    client.post(
        "/api/te-premium/run-analysis",
        json={"use_two_te_starters": False, "remove_te_reception_bonus": False},
    )
    after = _snapshot(contract)
    assert before == after, "run-analysis mutated latest_contract_data"


def test_run_analysis_does_not_persist_by_default(client_with_te_contract, tmp_path, monkeypatch):
    # Note: tmp_path is shared with the fixture's registry.json, so we
    # filter for the sandbox naming prefix rather than checking the
    # whole directory.
    sandbox_dir = tmp_path / "sandbox"
    sandbox_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(tep, "_DEFAULT_SANDBOX_DIR", sandbox_dir)
    client, _ = client_with_te_contract
    client.post("/api/te-premium/run-analysis", json={})
    assert list(sandbox_dir.glob("te_premium_*.json")) == []


def test_run_analysis_persist_writes_sidecar(client_with_te_contract, tmp_path, monkeypatch):
    sandbox_dir = tmp_path / "sandbox_persist"
    sandbox_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(tep, "_DEFAULT_SANDBOX_DIR", sandbox_dir)
    client, _ = client_with_te_contract
    res = client.post("/api/te-premium/run-analysis", json={"persist": True})
    assert res.status_code == 200
    body = res.json()
    files = list(sandbox_dir.glob("te_premium_*.json"))
    assert len(files) == 1
    assert body.get("persisted_path") == str(files[0])


def test_run_analysis_handles_empty_contract(client_with_te_contract, monkeypatch):
    client, _ = client_with_te_contract
    monkeypatch.setattr(server, "latest_contract_data", {"meta": {}, "players": {}, "playersArray": []})
    res = client.post("/api/te-premium/run-analysis", json={})
    assert res.status_code == 200
    body = res.json()
    assert body["summary"]["te_count"] == 0
    assert body["recommendations"] == []


# ── Recommendations ─────────────────────────────────────────────────


def test_recommendations_endpoint_returns_summary_slice(client_with_te_contract):
    client, _ = client_with_te_contract
    res = client.get("/api/te-premium/recommendations")
    assert res.status_code == 200
    body = res.json()
    assert body["sandbox"] is True
    assert "summary" in body
    assert "recommendations" in body
    assert "tier_summary" in body
    # Slice should NOT include the bulky external_boost / scoring_effect arrays
    assert "external_boost" not in body
    assert "scoring_effect" not in body


def test_recommendations_does_not_mutate_contract(client_with_te_contract):
    client, contract = client_with_te_contract
    before = _snapshot(contract)
    client.get("/api/te-premium/recommendations")
    after = _snapshot(contract)
    assert before == after


# ── Schema stability ────────────────────────────────────────────────


def test_run_analysis_returns_stable_top_level_keys(client_with_te_contract):
    client, _ = client_with_te_contract
    keys_first = set(client.post("/api/te-premium/run-analysis", json={}).json().keys())
    keys_second = set(client.post("/api/te-premium/run-analysis", json={}).json().keys())
    assert keys_first == keys_second
    expected = {
        "ok", "sandbox", "appliesToLiveValues",
        "run_id", "generated_at", "leagueKey", "scoringProfile",
        "scenario", "summary", "scarcity_summary", "external_boards",
        "players", "external_boost", "scoring_effect", "scarcity_effect",
        "recommendations", "tier_summary", "warnings",
    }
    assert expected.issubset(keys_first)
