"""Tool-level tests for the private Chase Upside MCP adapter.

Each tool is called through ``call_tool`` against a stub ``server`` namespace
carrying the REAL newest complete archived board (``tests/archive_fixtures``),
so the assertions are invariants over a real contract — order, paging,
canonical ids, ownership, missing states, the licensing allowlist — never a
live-board absolute.  The HTTP/protocol layer is covered in
``tests/api/test_chase_upside_mcp.py``.
"""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from src.api import chase_upside_mcp as mcp
from src.api import league_registry
from tests.trade import multi_team_support as mts

#: Per-source evidence that must never leave the MCP (licensing boundary).
FORBIDDEN_KEYS = (
    "canonicalSiteValues",
    "rawSourceValues",
    "sourceNativeValues",
    "sourceRanks",
    "sourceOriginalRanks",
    "effectiveSourceRanks",
    "ktcMarket",
    "sourceAudit",
)


@pytest.fixture(autouse=True)
def real_registry(tmp_path, monkeypatch):
    """The suite points the registry at a missing file (tests/conftest.py);
    these tests need the real league entries, copied verbatim."""
    real = json.loads((mts.REPO / "config/leagues/registry.json").read_text(encoding="utf-8"))
    path = tmp_path / "registry.json"
    path.write_text(json.dumps(real), encoding="utf-8")
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield
    monkeypatch.undo()
    league_registry.reload_registry()


@pytest.fixture
def pinned_trade_inputs(monkeypatch):
    """No live posture bundle or TTL-cached scarcity read may run (same pins
    as tests/api/test_trade_analyze_multi_route.py)."""
    import src.api.gameplan as gameplan
    from src.trade import trade_ledger

    class _Posture:
        def to_dict(self):
            return {"label": "HOLD", "notes": ["SYNTHETIC_FIXTURE_POSTURE (LABELLED)"]}

    monkeypatch.setattr(
        gameplan,
        "league_competitive_postures",
        lambda league_key, profile, c, *, build_if_missing: (
            {
                str(t.get("ownerId")): _Posture()
                for t in (c.get("sleeper") or {}).get("teams") or []
            },
            {"bundleFreshness": "fresh"},
        ),
    )
    mts.pin_league_scarcity(monkeypatch)
    trade_ledger.clear_snapshot_memo()
    yield
    trade_ledger.clear_snapshot_memo()


def _fresh_board() -> dict:
    contract, _snap, _label = mts.real_board()
    contract = copy.deepcopy(contract)
    # Rosters fetched an hour ago, so the ownership proof is "current".
    contract["sleeper"]["rosterFetchedAt"] = (
        datetime.now(timezone.utc) - timedelta(hours=1)
    ).isoformat()
    contract["meta"]["sleeperDataReady"] = True
    return contract


def _stub_server(contract, *, mismatch=False, overlay=None):
    async def _in_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def _overlay(**_kwargs):
        if isinstance(overlay, Exception):
            raise overlay
        return overlay

    return SimpleNamespace(
        latest_contract_data=contract,
        _league_registry=league_registry,
        _scoring_identity_error=lambda _c, _l: object() if mismatch else None,
        run_in_threadpool=_in_thread,
        _sleeper_overlay=SimpleNamespace(
            fetch_sleeper_overlay=_overlay,
            merge_cross_league_sleeper_block=server._sleeper_overlay.merge_cross_league_sleeper_block,
        ),
        _parse_multi_body=server._parse_multi_body,
        log=SimpleNamespace(
            warning=lambda *a, **k: None,
            error=lambda *a, **k: None,
            exception=lambda *a, **k: None,
        ),
    )


def _call(monkeypatch, stub, name, arguments):
    monkeypatch.setattr(mcp, "_server", lambda: stub)
    return asyncio.run(mcp.call_tool(name, arguments, None))


def _assert_no_source_values(payload):
    text = json.dumps(payload, default=str)
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in text, key


# ── rankings ───────────────────────────────────────────────────────────────


def test_rankings_follow_the_boards_rank_and_page_without_gaps(monkeypatch):
    stub = _stub_server(_fresh_board())
    first = _call(monkeypatch, stub, "get_player_rankings", {"limit": 25})
    second = _call(monkeypatch, stub, "get_player_rankings", {"limit": 25, "offset": 25})

    assert first["status"] in {"ok", "partial"}, first
    assert first["leagueKey"] == league_registry.get_default_league().key
    ranks = [p["canonicalConsensusRank"] for p in first["players"] + second["players"]]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)
    assert first["nextOffset"] == 25 and second["offset"] == 25
    assert first["total"] == second["total"] > 50
    assert first["unrankedRowsExcluded"] >= 0
    for p in first["players"]:
        if p.get("assetClass") != "pick":
            assert p["assetId"] == f"p:{p['playerId']}"
        assert "confidenceBucket" in p
    _assert_no_source_values(first)


def test_rankings_last_page_has_no_next_offset_and_position_filter(monkeypatch):
    stub = _stub_server(_fresh_board())
    qbs = _call(monkeypatch, stub, "get_player_rankings", {"position": "qb", "limit": 100})
    assert {p["position"] for p in qbs["players"]} == {"QB"}
    last = _call(
        monkeypatch, stub, "get_player_rankings", {"position": "QB", "offset": qbs["total"] - 1}
    )
    assert len(last["players"]) == 1
    assert last["nextOffset"] is None


def test_rankings_refuse_unproven_scoring_and_unknown_leagues(monkeypatch):
    contract = _fresh_board()
    mismatch = _call(monkeypatch, _stub_server(contract, mismatch=True), "get_player_rankings", {})
    assert mismatch["status"] == "unavailable"
    assert mismatch["reason"] == "league_scoring_mismatch"
    unknown = _call(
        monkeypatch, _stub_server(contract), "get_player_rankings", {"leagueKey": "nope"}
    )
    assert unknown["reason"] == "unknown_league"
    empty = _call(monkeypatch, _stub_server(None), "get_player_rankings", {})
    assert empty["reason"] == "rankings_not_ready"


# ── rosters ────────────────────────────────────────────────────────────────


def test_roster_carries_canonical_ids_values_picks_and_freshness(monkeypatch):
    contract = _fresh_board()
    team = contract["sleeper"]["teams"][0]
    out = _call(
        monkeypatch,
        _stub_server(contract),
        "get_team_roster",
        {"leagueKey": "dynasty_main", "rosterId": team["roster_id"]},
    )
    assert out["rosterId"] == team["roster_id"]
    assert out["rosters"]["delivery"] == "contract_snapshot"
    assert out["rosters"]["state"] == "current"
    assert [p["assetId"] for p in out["players"]] == [f"p:{pid}" for pid in team["playerIds"]]
    for p in out["players"]:
        # MISSING IS NEVER ZERO: an unpriced player is null with a reason.
        if p["valueState"] == "unpriced":
            assert p["value"] is None and p["reason"]
        else:
            assert p["value"] > 0
    assert out["pickOwnership"]["state"] == "observed"
    assert out["picks"], "an observed pick inventory lists the team's picks"
    assert all(str(p["assetId"]).startswith("pick:dynasty_main:") for p in out["picks"])
    assert any(p["valueState"] == "priced" for p in out["picks"])
    _assert_no_source_values(out)


def test_roster_never_serves_the_loaded_leagues_teams_for_another_league(monkeypatch):
    contract = _fresh_board()
    other = next((lg for lg in league_registry.active_leagues() if lg.key != "dynasty_main"), None)
    if other is None:
        pytest.skip("registry has a single league")
    out = _call(
        monkeypatch,
        _stub_server(contract, overlay=RuntimeError("sleeper down")),
        "get_team_roster",
        {"leagueKey": other.key, "rosterId": 1},
    )
    assert out["status"] == "unavailable"
    assert out["reason"] == "league_roster_overlay_unavailable"


def test_roster_unknown_team_lists_valid_teams_and_pick_unavailable_is_explicit(monkeypatch):
    contract = _fresh_board()
    missing = _call(
        monkeypatch, _stub_server(contract), "get_team_roster", {"teamName": "no such team"}
    )
    assert missing["reason"] == "team_not_found"
    assert len(missing["teams"]) == len(contract["sleeper"]["teams"])

    team = contract["sleeper"]["teams"][0]
    team["picks"] = None
    team["pickDetails"] = None
    team["pickOwnershipState"] = "unavailable"
    team["pickOwnershipReason"] = "traded_picks_fetch_failed"
    out = _call(
        monkeypatch, _stub_server(contract), "get_team_roster", {"rosterId": team["roster_id"]}
    )
    assert out["picks"] is None
    assert out["pickOwnership"] == {"state": "unavailable", "reason": "traded_picks_fetch_failed"}
    assert {"field": "picks", "reason": "traded_picks_fetch_failed"} in out["missingData"]


def test_stale_rosters_are_labelled_not_presented_as_current(monkeypatch):
    contract = _fresh_board()
    contract["sleeper"]["rosterFetchedAt"] = (
        datetime.now(timezone.utc) - timedelta(days=3)
    ).isoformat()
    out = _call(
        monkeypatch,
        _stub_server(contract),
        "get_team_roster",
        {"rosterId": contract["sleeper"]["teams"][0]["roster_id"]},
    )
    assert out["status"] == "partial"
    assert out["rosters"]["state"] == "stale"
    assert {"field": "rosterFreshness", "reason": "rosters_stale"} in out["missingData"]


# ── trade analysis ─────────────────────────────────────────────────────────


def _two_team_trade(contract):
    snap = mts.tl.build_trade_snapshot(
        contract, league_key="dynasty_main", roster_settings=mts._dynasty_main_settings()
    )
    rids = sorted(snap.teams_by_roster_id)
    a, b = rids[0], rids[1]
    give_a = [x for x in mts.team_assets(snap, a) if x.startswith("p:")][0]
    give_b = [x for x in mts.team_assets(snap, b) if x.startswith("p:")][0]
    return a, b, [{"id": give_a, "from": a, "to": b}, {"id": give_b, "from": b, "to": a}]


def test_trade_runs_the_one_composer_and_records_nothing(monkeypatch, pinned_trade_inputs):
    from src.trade import analyze_service

    if not analyze_service.package_model_ready():
        pytest.skip("active package model is not geom")
    contract = _fresh_board()
    a, b, assets = _two_team_trade(contract)
    calls = []
    real = analyze_service.analyze_trade_n
    monkeypatch.setattr(
        analyze_service,
        "analyze_trade_n",
        lambda *args, **kw: calls.append(kw) or real(*args, **kw),
    )
    out = _call(
        monkeypatch,
        _stub_server(contract),
        "analyze_trade",
        {"leagueKey": "dynasty_main", "teams": [a, b], "assets": assets},
    )
    assert calls and calls[0]["mode"] == "team_context"
    assert calls[0]["counterfactuals"] is False
    assert out["status"] in {"ok", "partial"}
    assert out["recorded"] is False and out["recommendationOnly"] is True
    assert [t["rosterId"] for t in out["teams"]] == [a, b]
    assert all(t["decision"] is not None for t in out["teams"])
    assert all("simulation" not in t for t in out["teams"])
    _assert_no_source_values(out)


def test_trade_refuses_an_asset_the_sender_does_not_hold(monkeypatch, pinned_trade_inputs):
    from src.trade import analyze_service

    if not analyze_service.package_model_ready():
        pytest.skip("active package model is not geom")
    contract = _fresh_board()
    a, b, assets = _two_team_trade(contract)
    # Team A "sends" the asset team B holds.
    assets[1] = {"id": assets[1]["id"], "from": a, "to": b}
    out = _call(
        monkeypatch,
        _stub_server(contract),
        "analyze_trade",
        {"teams": [a, b], "assets": assets},
    )
    assert out["status"] == "unavailable"
    assert out["reason"] in {"asset_not_owned", "one_sided_trade", "idle_team"}


def test_three_team_trades_stay_behind_the_multi_team_flag(monkeypatch):
    from src.api import feature_flags

    monkeypatch.setattr(feature_flags, "is_enabled", lambda name: False)
    out = _call(
        monkeypatch,
        _stub_server(_fresh_board()),
        "analyze_trade",
        {
            "teams": [1, 2, 3],
            "assets": [
                {"id": "p:1", "from": 1, "to": 2},
                {"id": "p:2", "from": 2, "to": 3},
                {"id": "p:3", "from": 3, "to": 1},
            ],
        },
    )
    assert out["reason"] == "multi_team_analysis_disabled"


# ── value history ──────────────────────────────────────────────────────────


def test_history_before_the_floor_is_unavailable_never_todays_value(monkeypatch):
    out = _call(
        monkeypatch,
        _stub_server(_fresh_board()),
        "get_value_history",
        {"playerId": "4046", "asOfDate": "2026-01-01"},
    )
    assert out["status"] == "unavailable"
    assert out["point"]["value"] is None
    assert out["missingData"] == ["before_history_boundary"]
    assert out["lane"] == "canonical_board"


def test_history_series_is_bounded_and_canonical_lane_only(monkeypatch):
    from src.history import asof

    seen = {}

    def fake_series(asset_key, **kwargs):
        seen.update(kwargs, asset_key=asset_key)
        return {
            "start": "2026-07-14",
            "end": None,
            "points": [
                {"observedDate": f"d{i}", "value": i, "rank": 1, "tier": None, "confidence": None}
                for i in range(mcp.MAX_HISTORY_POINTS + 5)
            ],
        }

    monkeypatch.setattr(asof, "series", fake_series)
    out = _call(
        monkeypatch,
        _stub_server(_fresh_board()),
        "get_value_history",
        {"pickName": "2027 Early 1st"},
    )
    assert seen["asset_key"].startswith("mpick:")
    assert "lane" not in seen  # the default lane IS canonical_board
    assert len(out["points"]) == mcp.MAX_HISTORY_POINTS
    assert out["points"][-1]["value"] == mcp.MAX_HISTORY_POINTS + 4
    assert out["truncatedToLatest"] == mcp.MAX_HISTORY_POINTS


# ── identity ───────────────────────────────────────────────────────────────


def test_identity_refusal_is_explicit_with_candidates(monkeypatch):
    from src.identity import directory_cache, resolution

    monkeypatch.setattr(directory_cache, "get_default_sleeper_index", lambda: object())
    monkeypatch.setattr(
        resolution,
        "resolve_canonical_v2",
        lambda _index, **_kw: resolution.Resolution(
            status=resolution.UNRESOLVED,
            policy="CANONICAL_V2",
            method="none",
            reason="ambiguous_name",
            candidate_ids=("1", "2"),
        ),
    )
    out = _call(monkeypatch, _stub_server(None), "resolve_player_identity", {"name": "Mike Smith"})
    assert out["status"] == "unresolved"
    assert out["candidates"] == ["1", "2"]
    assert out["missingData"] == ["ambiguous_name"]


# ── argument validation and auth hardening ────────────────────────────────


@pytest.mark.parametrize(
    ("arguments", "reason"),
    [
        ({"teams": [1, 2], "assets": [{"id": "p:1", "from": 1}]}, "required_argument_missing"),
        (
            {"teams": [1, 2], "assets": [{"id": "p:1", "from": 1, "to": 2, "x": 1}]},
            "unexpected_argument",
        ),
        (
            {"teams": [True, 2], "assets": [{"id": "p:1", "from": 1, "to": 2}]},
            "invalid_argument_type",
        ),
        ({"teams": [1], "assets": [{"id": "p:1", "from": 1, "to": 2}]}, "invalid_argument_range"),
        (
            {
                "teams": [1, 2],
                "assets": [{"id": "p:1", "from": 1, "to": 2}],
                "teamGoals": {"1": "YOLO"},
            },
            "invalid_argument_value",
        ),
    ],
)
def test_nested_arguments_are_validated_against_the_published_schema(arguments, reason):
    with pytest.raises(ValueError, match=reason):
        mcp._validate_arguments("analyze_trade", arguments)


def test_every_published_schema_keyword_is_enforced():
    for tool in mcp.TOOLS:
        mcp._assert_supported(tool["inputSchema"])
    with pytest.raises(RuntimeError):
        mcp._assert_supported({"type": "string", "pattern": "^x$"})


def test_non_ascii_credentials_are_rejected_not_crashed(monkeypatch):
    monkeypatch.setenv("CHASE_UPSIDE_MCP_API_TOKEN", "t" * 48)
    monkeypatch.setenv("CHASE_UPSIDE_MCP_OWNER_USER_ID", "site-owner-1")
    client = TestClient(server.app)
    response = client.post(
        "/api/chase-upside/mcp",
        headers={
            "Authorization": b"Bearer " + "é".encode() * 48,
            "X-Chase-Upside-Owner-Id": "site-owner-1",
        },
        json={},
    )
    assert response.status_code == 401
    owner = client.post(
        "/api/chase-upside/mcp",
        headers={"Authorization": "Bearer " + "t" * 48, "X-Chase-Upside-Owner-Id": "é".encode()},
        json={},
    )
    assert owner.status_code == 403
