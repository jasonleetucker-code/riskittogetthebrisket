"""Analyze Trade prerequisites are warmed off the request path.

Measured (owner directive 2026-10-19, part 4): a process-cold
``/api/trade/analyze`` built the league's posture bundle, the projection
ensemble and the players DB on the user's request.  ``server.
_warm_trade_analysis_prerequisites`` builds them on the overlay-warm daemon
thread instead, through the SAME cached owners — so it can only make the
request find them warm, never change an answer.
"""

from __future__ import annotations

from types import SimpleNamespace

import server


def _cfg(key):
    return SimpleNamespace(key=key, sleeper_league_id=f"L-{key}")


def _contract():
    return {
        "meta": {"leagueKey": "main"},
        "sleeper": {
            "scoringSettings": {"rec": 1.0},
            "teams": [{"playerIds": ["1", "2"]}, {"playerIds": ["2", "3"]}],
        },
    }


def _patch(monkeypatch, *, identity_ok=("main",), bundle_error=None):
    calls: dict = {"bundle": [], "ensemble": [], "players": []}
    from src.api import gameplan
    from src.api import matchup_intel
    from src.roster_intel import best_ball_utility as bbu

    monkeypatch.setattr(
        server._league_registry, "active_leagues", lambda: [_cfg("main"), _cfg("side"), _cfg("x")]
    )
    monkeypatch.setattr(server._league_registry, "get_scoring_profile", lambda key: f"p-{key}")
    monkeypatch.setattr(
        server,
        "_scoring_identity_error",
        lambda contract, cfg: None if cfg.key in identity_ok else object(),
    )

    def bundle(key, profile, contract):
        if bundle_error:
            raise bundle_error
        calls["bundle"].append((key, profile))
        return object(), False

    monkeypatch.setattr(gameplan, "get_league_bundle", bundle)
    monkeypatch.setattr(
        bbu, "_ensemble_index", lambda season, card: calls["ensemble"].append((season, card))
    )
    monkeypatch.setattr("src.bdvm.actuals.current_nfl_season", lambda today=None: 2026)
    monkeypatch.setattr(
        matchup_intel, "players_meta_for_rosters", lambda rosters: calls["players"].append(rosters)
    )
    return calls


def _served(monkeypatch, contract):
    monkeypatch.setattr(server, "latest_contract_data", contract)
    return contract


def test_warms_bundle_projections_and_players_for_servable_leagues(monkeypatch):
    calls = _patch(monkeypatch, identity_ok=("side",))
    server._warm_trade_analysis_prerequisites(_served(monkeypatch, _contract()))
    # The loaded league always; another only when its scoring is proven
    # identical (it could not be served otherwise).
    assert calls["bundle"] == [("main", "p-main"), ("side", "p-side")]
    assert calls["ensemble"] == [(2026, {"rec": 1.0})]
    assert calls["players"] == [[{"players": ["1", "2", "3"]}]]


def test_a_failing_step_never_raises(monkeypatch):
    calls = _patch(monkeypatch, bundle_error=RuntimeError("no snapshot"))
    server._warm_trade_analysis_prerequisites(_served(monkeypatch, _contract()))  # no raise
    assert calls["ensemble"] and calls["players"]


def test_the_lifespan_marks_serving_started():
    from fastapi.testclient import TestClient

    server._SERVING_STARTED.clear()
    with TestClient(server.app):
        assert server._SERVING_STARTED.is_set()


def test_the_warm_thread_runs_only_behind_the_overlay_warm_flag(monkeypatch):
    import threading

    from src.adapters import sleeper_trending

    ran = threading.Event()
    monkeypatch.setattr(server, "_warm_trade_analysis_prerequisites", lambda _c, **_k: ran.set())
    monkeypatch.setattr(server._league_registry, "active_leagues", lambda: [])
    monkeypatch.setattr(sleeper_trending, "warm", lambda: False)
    server._SERVING_STARTED.set()

    monkeypatch.setattr(server, "SLEEPER_OVERLAY_WARM_ENABLED", False)
    server._warm_overlays_in_background({})
    assert not ran.wait(0.3)  # the unit suite's network boundary holds

    monkeypatch.setattr(server, "SLEEPER_OVERLAY_WARM_ENABLED", True)
    server._warm_overlays_in_background({})
    assert ran.wait(5)


# ── supersession (independent review of #1828) ───────────────────────────


def test_a_board_that_is_not_served_is_not_warmed(monkeypatch):
    calls = _patch(monkeypatch)
    monkeypatch.setattr(server, "latest_contract_data", {"meta": {"leagueKey": "main"}})
    server._warm_trade_analysis_prerequisites(_contract())
    assert calls == {"bundle": [], "ensemble": [], "players": []}


def test_a_superseded_generation_exits_without_warming(monkeypatch):
    calls = _patch(monkeypatch)
    board = _served(monkeypatch, _contract())
    monkeypatch.setattr(server, "_analysis_warm_generation", 5)
    server._warm_trade_analysis_prerequisites(board, generation=4)
    assert calls == {"bundle": [], "ensemble": [], "players": []}


def test_a_warm_waits_for_its_board_to_be_published(monkeypatch):
    import threading

    calls = _patch(monkeypatch)
    board = _contract()
    monkeypatch.setattr(server, "latest_contract_data", None)
    monkeypatch.setattr(server, "_analysis_warm_generation", 3)
    threading.Timer(0.3, lambda: setattr(server, "latest_contract_data", board)).start()
    server._warm_trade_analysis_prerequisites(board, generation=3)
    assert calls["bundle"] == [("main", "p-main")]
    # ...and gives up, writing nothing, when its board is never published.
    calls2 = _patch(monkeypatch)
    monkeypatch.setattr(server, "_ANALYSIS_WARM_PUBLISH_WAIT_SECONDS", 0.3)
    server._warm_trade_analysis_prerequisites(_contract(), generation=3)
    assert calls2 == {"bundle": [], "ensemble": [], "players": []}


def test_a_board_superseded_mid_warm_stops_the_remaining_steps(monkeypatch):
    from src.api import gameplan

    calls = _patch(monkeypatch)
    board = _served(monkeypatch, _contract())

    def bundle_then_new_board(key, profile, contract):
        calls["bundle"].append((key, profile))
        server.latest_contract_data = {"meta": {"leagueKey": "main"}}  # a newer board lands
        return object(), False

    monkeypatch.setattr(gameplan, "get_league_bundle", bundle_then_new_board)
    server._warm_trade_analysis_prerequisites(board)
    assert calls["bundle"] == [("main", "p-main")]
    assert calls["ensemble"] == [] and calls["players"] == []


def test_repeated_primes_warm_once_newest_board_only(monkeypatch):
    """Startup recovery primes more than once: only the newest board's warm
    runs, and warms never overlap."""
    import threading
    import time

    from src.adapters import sleeper_trending
    from src.api import draft_class_evidence

    seen: list = []
    active = {"n": 0, "max": 0}
    lock = threading.Lock()

    def fake_warm(contract, *, generation=None):
        with lock:
            active["n"] += 1
            active["max"] = max(active["max"], active["n"])
        if server._analysis_warm_is_current(contract, generation):
            seen.append(contract["meta"]["tag"])
        time.sleep(0.05)
        with lock:
            active["n"] -= 1

    monkeypatch.setattr(server, "_warm_trade_analysis_prerequisites", fake_warm)
    monkeypatch.setattr(server._league_registry, "active_leagues", lambda: [])
    monkeypatch.setattr(sleeper_trending, "warm", lambda: False)
    monkeypatch.setattr(draft_class_evidence, "refresh_draft_class_snapshot", lambda cfg: None)
    monkeypatch.setattr(server, "SLEEPER_OVERLAY_WARM_ENABLED", True)
    server._SERVING_STARTED.clear()
    boards = [{"meta": {"leagueKey": "main", "tag": t}} for t in ("a", "b", "c")]
    for b in boards:
        server._warm_overlays_in_background(b)
    monkeypatch.setattr(server, "latest_contract_data", boards[-1])
    server._SERVING_STARTED.set()
    deadline = time.monotonic() + 5
    while not seen and time.monotonic() < deadline:
        time.sleep(0.02)
    time.sleep(0.3)
    assert seen == ["c"]
    assert active["max"] <= 1
