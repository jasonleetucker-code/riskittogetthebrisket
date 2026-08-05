"""Tests for /api/trade/simulate-mc.

Pins:
  * Auth required (401 without session).
  * Feature flag off → 503 feature_disabled.
  * Flag on + valid body → 200 with expected shape.
  * Disclaimer + labelHint always present in the response.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags


@pytest.fixture(autouse=True)
def _flags():
    feature_flags.reload()
    yield
    feature_flags.reload()


def _sample_body():
    return {
        "sideA": [
            {
                "name": "Josh Allen",
                "team": "BUF",
                "pos": "QB",
                "rankDerivedValue": 9200,
                "valueBand": {"p10": 8500, "p50": 9200, "p90": 9900},
            }
        ],
        "sideB": [
            {
                "name": "Jalen Hurts",
                "team": "PHI",
                "pos": "QB",
                "rankDerivedValue": 8500,
                "valueBand": {"p10": 7800, "p50": 8500, "p90": 9200},
            }
        ],
        "nSims": 2000,
        "seed": 42,
    }


def test_unauth_returns_401(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", json=_sample_body())
    # Middleware gate fires first, regardless of feature flag.
    assert res.status_code == 401


def test_flag_off_returns_503(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "0")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", json=_sample_body())
    assert res.status_code == 503
    assert res.json()["error"] == "feature_disabled"


def test_flag_on_returns_simulation_result(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", json=_sample_body())
    assert res.status_code == 200, res.text
    body = res.json()
    assert "winProbA" in body
    assert "winProbB" in body
    assert "meanDelta" in body
    assert "deltaRange" in body
    # After the Phase-11 integration pass, the endpoint routes
    # through the symmetrize+enrich pipeline, so:
    #   - method = "consensus_based_win_rate_symmetrized"
    #   - labelHint = "consensus_based_win_rate"  (frontend label)
    #   - decision-layer fields are present: valueDelta,
    #     adjustedDelta, winPct, riskLevel, tierImpact
    assert body["method"] in (
        "consensus_based_win_rate",
        "consensus_based_win_rate_symmetrized",
    )
    assert body["labelHint"] == "consensus_based_win_rate"
    assert "disclaimer" in body
    assert "NOT" in body["disclaimer"]
    # Decision-layer fields from enrich_with_decision_shape.
    assert "valueDelta" in body
    assert "adjustedDelta" in body
    assert "winPct" in body
    assert body["riskLevel"] in ("low", "medium", "high")
    assert body["tierImpact"] in ("even", "minor", "moderate", "significant")


def test_invalid_body_returns_400(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post(
            "/api/trade/simulate-mc",
            content=b"not json",
            headers={"content-type": "application/json"},
        )
    assert res.status_code == 400


def test_sides_must_be_lists(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", json={"sideA": "nope", "sideB": []})
    assert res.status_code == 400


def test_n_sims_clamped_to_max(monkeypatch):
    """A user asking for 10M sims gets clamped to the guardrail."""
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    body = _sample_body()
    body["nSims"] = 10_000_000
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", json=body)
    assert res.status_code == 200
    # Guard clamps each direction to SIMULATE_MC_MAX_SIMS (50k — bounds
    # worst-case event-loop-free compute).  ``nSims`` reports the clamped
    # REQUEST; ``nDraws`` reports that the symmetrize pipeline ran the
    # sim in both directions.  It reported the doubled number as nSims
    # until W09-F016, which the UI rendered as the simulation count.
    body_out = res.json()
    assert body_out["nSims"] == server.SIMULATE_MC_MAX_SIMS
    assert body_out["nDraws"] == 2 * server.SIMULATE_MC_MAX_SIMS


def test_timeout_returns_clean_504(monkeypatch):
    """A run exceeding the wall-clock budget yields a clean 504, never
    an open-ended hang that would also have frozen the event loop."""
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    monkeypatch.setattr(server, "SIMULATE_MC_TIMEOUT_SECONDS", 0.2)

    import src.trade.symmetrize as _sym

    def _slow(*a, **k):
        import time as _t

        _t.sleep(1.5)
        raise AssertionError("should have timed out before returning")

    monkeypatch.setattr(_sym, "simulate_symmetric", _slow)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", json=_sample_body())
    assert res.status_code == 504
    assert res.json()["error"] == "timeout"
