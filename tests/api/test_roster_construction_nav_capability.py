"""Roster Construction's nav capability tracks the route's own flag gate.

Owner decision D1 (2026-11-01) / docs/EXECUTION_PLAN.md owner decision 1:
the capability-gated My Team nav entry is added only after production
verification of the private page.  The entry must be offered exactly when
``GET /api/roster-construction`` does not refuse ``feature_disabled``, and it
must never be offered to an anonymous viewer (the signed-out
``/api/auth/status`` carries no features at all).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import server
from src.api import feature_flags


@pytest.fixture(autouse=True)
def _reset_rate_limit():
    from src.api import rate_limit  # noqa: PLC0415

    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def _set_flag(monkeypatch, value: bool) -> None:
    real = feature_flags.is_enabled
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda n, *a, _r=real, **k: value if n == "roster_construction" else _r(n, *a, **k),
    )


@pytest.mark.parametrize("enabled", [True, False])
def test_capability_agrees_with_the_route_gate(monkeypatch, enabled):
    monkeypatch.setattr(server, "_is_authenticated", lambda r: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: {"username": "u"})
    _set_flag(monkeypatch, enabled)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        cap = c.get("/api/auth/status").json()["features"]["rosterConstruction"]["available"]
        route = c.get("/api/roster-construction")
    assert cap is enabled
    disabled = route.status_code == 503 and route.json().get("error") == "feature_disabled"
    assert disabled is (not enabled)


def test_signed_out_status_offers_nothing(monkeypatch):
    _set_flag(monkeypatch, True)
    monkeypatch.setattr(server, "_get_auth_session", lambda r: None)
    monkeypatch.setattr(server, "_is_authenticated", lambda r: False)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        body = c.get("/api/auth/status").json()
        assert body == {"authenticated": False}
        assert c.get("/api/roster-construction").status_code == 401


def test_never_a_public_route():
    assert not server._is_public_api_path("/api/roster-construction")
