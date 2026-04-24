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
                "name": "Josh Allen", "team": "BUF", "pos": "QB",
                "rankDerivedValue": 9200,
                "valueBand": {"p10": 8500, "p50": 9200, "p90": 9900},
            }
        ],
        "sideB": [
            {
                "name": "Jalen Hurts", "team": "PHI", "pos": "QB",
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
    assert body["method"] == "consensus_based_win_rate"
    assert body["labelHint"] == "consensus_based_win_rate"
    assert "disclaimer" in body
    assert "NOT" in body["disclaimer"]


def test_invalid_body_returns_400(monkeypatch):
    monkeypatch.setenv("RISKIT_FEATURE_MONTE_CARLO_TRADE", "1")
    feature_flags.reload()
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "test"})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.post("/api/trade/simulate-mc", content=b"not json",
                     headers={"content-type": "application/json"})
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
    # Guard clamps to 200k.
    assert res.json()["nSims"] <= 200_000
