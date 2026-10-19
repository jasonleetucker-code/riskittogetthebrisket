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


def test_warms_bundle_projections_and_players_for_servable_leagues(monkeypatch):
    calls = _patch(monkeypatch, identity_ok=("side",))
    server._warm_trade_analysis_prerequisites(_contract())
    # The loaded league always; another only when its scoring is proven
    # identical (it could not be served otherwise).
    assert calls["bundle"] == [("main", "p-main"), ("side", "p-side")]
    assert calls["ensemble"] == [(2026, {"rec": 1.0})]
    assert calls["players"] == [[{"players": ["1", "2", "3"]}]]


def test_a_failing_step_never_raises(monkeypatch):
    calls = _patch(monkeypatch, bundle_error=RuntimeError("no snapshot"))
    server._warm_trade_analysis_prerequisites(_contract())  # must not raise
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
    monkeypatch.setattr(server, "_warm_trade_analysis_prerequisites", lambda _c: ran.set())
    monkeypatch.setattr(server._league_registry, "active_leagues", lambda: [])
    monkeypatch.setattr(sleeper_trending, "warm", lambda: False)
    server._SERVING_STARTED.set()

    monkeypatch.setattr(server, "SLEEPER_OVERLAY_WARM_ENABLED", False)
    server._warm_overlays_in_background({})
    assert not ran.wait(0.3)  # the unit suite's network boundary holds

    monkeypatch.setattr(server, "SLEEPER_OVERLAY_WARM_ENABLED", True)
    server._warm_overlays_in_background({})
    assert ran.wait(5)
