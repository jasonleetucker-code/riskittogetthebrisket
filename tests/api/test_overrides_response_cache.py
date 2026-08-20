"""Tests for the ``POST /api/rankings/overrides`` response memo.

The endpoint used to rebuild the full ranking pipeline synchronously on
the event loop for every request — and since the frontend's stock
settings post a body on every page load, that meant one multi-second
pipeline run per page view.  ``server._OVERRIDES_RESPONSE_CACHE``
memoizes the encoded response bytes keyed on (canonical body, view,
league, sleeper-match) and versioned on ``latest_data_etag``.

Pinned here:
    1. Two identical POSTs → one pipeline build, byte-identical bodies.
    2. Distinct DERIVED inputs (tep knobs) → distinct slots (no
       cross-body bleed).
    3. A new contract generation (etag change) → rebuild.
    4. ``_prime_latest_payload`` clears the memo outright.
    5. leagueAdjusted requests bypass the cache (rebuilt every time).
    6. Bodies that normalize to the SAME derived inputs share one slot:
       with custom source weighting withdrawn
       (``_SOURCE_OVERRIDES_DISABLED``), every source-toggle body maps
       to the same empty override map, so keying the memo on the raw
       body burned a full pipeline rebuild per distinct client body
       while producing byte-identical responses.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from tests.api.test_source_overrides import _fixture_raw_payload


@pytest.fixture
def overrides_env(tmp_path, monkeypatch):
    """Single-league registry + stub contract + clean memo."""
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
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
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    server._OVERRIDES_RESPONSE_CACHE.clear()
    server._OVERRIDES_ENCODE_LOCKS.clear()

    yield

    server._OVERRIDES_RESPONSE_CACHE.clear()
    server._OVERRIDES_ENCODE_LOCKS.clear()
    league_registry.reload_registry()


def _install_data(monkeypatch, etag: str = "etag-gen-1"):
    """Install the raw fixture payload + a contract meta stamped for
    the registry's ``main`` league.  Must run inside the TestClient
    context (same rationale as test_league_routing)."""
    monkeypatch.setattr(server, "latest_data", _fixture_raw_payload())
    monkeypatch.setattr(
        server,
        "latest_contract_data",
        {"meta": {"leagueKey": "main"}},
    )
    monkeypatch.setattr(server, "latest_data_etag", etag)


def _count_builds(monkeypatch):
    """Wrap the delta builder with a call counter."""
    calls = {"n": 0}
    real = server.build_rankings_delta_payload

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(server, "build_rankings_delta_payload", counting)
    return calls


STOCK_BODY = {"tep_multiplier": 1.15}


def test_identical_posts_build_once_and_match_bytes(overrides_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_data(monkeypatch)
        calls = _count_builds(monkeypatch)

        r1 = c.post("/api/rankings/overrides?view=delta", json=STOCK_BODY)
        r2 = c.post("/api/rankings/overrides?view=delta", json=STOCK_BODY)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert calls["n"] == 1, "second identical POST must be served from the memo"
    assert r1.content == r2.content
    assert r1.headers["X-Payload-View"] == "rankings-overrides-delta"
    assert r1.headers["Cache-Control"] == "no-store"


def test_distinct_bodies_get_distinct_slots(overrides_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_data(monkeypatch)
        calls = _count_builds(monkeypatch)

        r1 = c.post("/api/rankings/overrides?view=delta", json={"tep_multiplier": 1.15})
        r2 = c.post("/api/rankings/overrides?view=delta", json={"tep_multiplier": 1.30})

    assert r1.status_code == 200 and r2.status_code == 200
    assert calls["n"] == 2
    assert r1.content != r2.content


def test_new_contract_generation_invalidates(overrides_env, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_data(monkeypatch, etag="etag-gen-1")
        calls = _count_builds(monkeypatch)

        r1 = c.post("/api/rankings/overrides?view=delta", json=STOCK_BODY)
        assert r1.status_code == 200
        assert calls["n"] == 1

        # Simulate a scrape promotion: same raw data, new generation.
        monkeypatch.setattr(server, "latest_data_etag", "etag-gen-2")
        r2 = c.post("/api/rankings/overrides?view=delta", json=STOCK_BODY)
        assert r2.status_code == 200

    assert calls["n"] == 2, "stale-generation entry must be rebuilt"


def test_prime_latest_payload_clears_memo(overrides_env):
    server._OVERRIDES_RESPONSE_CACHE[("overrides", "x", True, "main", False)] = (
        b"raw",
        b"gz",
        "etag-gen-1",
    )
    # Falsy data → prime resets globals (incl. our memo) and returns.
    server._prime_latest_payload(None)
    assert server._OVERRIDES_RESPONSE_CACHE == {}


def test_league_adjusted_requests_are_now_memoized_like_any_other(overrides_env, monkeypatch):
    """Was ``test_league_adjusted_requests_bypass_cache``.

    The bypass existed for a real reason: the lens's factors came from
    the gameplan module, whose freshness this cache cannot see, so
    memoizing a response built from them could serve a board keyed to a
    roster snapshot that had since moved.

    B9a withdrew the lens from this endpoint, so there are no factors
    and nothing unseeable left to exclude. ``valuation_mode`` is part of
    the canonical body JSON, so a request carrying it keys separately
    from one that does not — which is what the differing
    ``valuationNote`` needs — and both are cacheable.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_data(monkeypatch)
        calls = _count_builds(monkeypatch)

        body = {"tep_multiplier": 1.15, "valuation_mode": "leagueAdjusted"}
        r1 = c.post("/api/rankings/overrides?view=delta", json=body)
        r2 = c.post("/api/rankings/overrides?view=delta", json=body)

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r1.content == r2.content
    assert calls["n"] == 1, "the second identical request rebuilt instead of hitting the memo"
    assert server._OVERRIDES_RESPONSE_CACHE, "no slot was written"


def test_withdrawn_source_toggle_bodies_share_one_slot(overrides_env, monkeypatch):
    """Two bodies disabling DIFFERENT sources build once and answer
    byte-identically while custom source weighting is withdrawn.

    ``normalize_source_overrides`` maps both bodies to the same (empty)
    override map — the withdrawal is the whole point of #875 — so the
    responses cannot differ.  The memo key is therefore derived from the
    NORMALIZED inputs the build actually consumes, not the raw posted
    body: a raw-body key made every distinct client body pay a full
    pipeline rebuild (measured ~1.2s each on the live contract) for a
    response the memo already held.
    """
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_data(monkeypatch)
        calls = _count_builds(monkeypatch)

        r1 = c.post(
            "/api/rankings/overrides?view=delta",
            json={"ktcSfTep": {"include": False}},
        )
        r2 = c.post(
            "/api/rankings/overrides?view=delta",
            json={"fantasyCalc": {"include": False}},
        )

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert calls["n"] == 1, (
        "bodies that normalize identically must share one memo slot — "
        "a second full rebuild means the key is reading the raw body"
    )
    assert r1.content == r2.content
