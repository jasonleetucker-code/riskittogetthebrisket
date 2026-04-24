"""Tests for league-aware routing on backend endpoints.

These pin down the contract around ``?leagueKey=`` on the routes
that read from the live contract:

* Unknown or inactive keys return 400 with a ``unknown_league`` /
  ``inactive_league`` code.
* A valid key that doesn't match the loaded contract returns 503
  ``data_not_ready`` (so single-league instances don't silently
  serve the wrong league's data when the switcher points at a
  league that hasn't been scraped yet).
* No key means "use the session's activeLeagueKey, else the
  registry default" — backward-compat for existing callers.

The fixture path builds an in-memory contract stamped with the
test league's key so ``_resolve_league_for_request`` has something
to match against.  We stub out Sleeper-hitting endpoints where we
can to keep the tests local.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry


@pytest.fixture
def two_league_registry(tmp_path, monkeypatch):
    """A registry with two active leagues (main + side) and a test
    user_kv DB so state writes don't bleed between tests."""
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
                        "aliases": ["primary"],
                    },
                    {
                        "key": "side",
                        "displayName": "Side",
                        "sleeperLeagueId": "L-SIDE",
                        "active": True,
                        "rosterSettings": {"teamCount": 10},
                    },
                    {
                        "key": "retired",
                        "displayName": "Retired",
                        "sleeperLeagueId": "L-RET",
                        "active": False,
                        "rosterSettings": {},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    # Isolate user_kv to a temp file so the PUT paths don't leak.
    from src.api import user_kv
    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    yield

    # Reset the registry AFTER the test so later tests (especially
    # public_league tests that set SLEEPER_LEAGUE_ID directly) see
    # the env-var-fallback state, not this test's fixture leagues.
    # Without this, module-level _FILE_LOADED retains {"main",
    # "side", "retired"} — which makes get_default_league() return
    # "main" with sleeper_league_id "L-MAIN", breaking
    # _public_league_id() for downstream tests.
    league_registry.reload_registry()


def _install_contract_for_league(monkeypatch, league_key: str):
    """Put a stub contract in ``latest_contract_data`` stamped for
    ``league_key``.  Minimal enough to pass the initial guards on
    routes like /api/trade/simulate that bail on missing
    ``playersArray``.

    **Must be called INSIDE the TestClient context** so the
    ``app.lifespan`` startup can't overwrite ``latest_contract_data``
    after we set it.  Called pre-context, the stub is visible for a
    moment but gets clobbered when the TestClient enters — this
    passes locally (where cached scrape data may keep it alive) but
    fails in CI (where no data exists on disk).  See the signal-
    alerts tests (tests/api/test_signal_alerts.py) for the same
    pattern + rationale.
    """
    stub = {
        "meta": {"leagueKey": league_key},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [{"name": "Stub"}],
        "sleeper": {"teams": [{"ownerId": "oA", "name": "Team A", "players": []}]},
    }
    monkeypatch.setattr(server, "latest_contract_data", stub)
    return stub


# ── Unknown / inactive keys ──────────────────────────────────────


def test_unknown_league_key_returns_400(two_league_registry, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        res = c.get("/api/terminal?leagueKey=ghost")
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"


def test_inactive_league_key_returns_400(two_league_registry, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        res = c.get("/api/terminal?leagueKey=retired")
    assert res.status_code == 400
    assert res.json()["error"] == "inactive_league"


def test_data_not_ready_for_non_loaded_league(two_league_registry, monkeypatch):
    """The loaded contract is for 'main' — asking for 'side' must
    return 503 ``data_not_ready`` with the league key echoed back."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        res = c.get("/api/terminal?leagueKey=side")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "side"


def test_alias_resolves_to_canonical_key(two_league_registry, monkeypatch):
    """Passing ``primary`` (an alias for ``main``) should work —
    same as passing ``main`` directly."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        res = c.get("/api/terminal?leagueKey=primary")
    # 200 means validation accepted the alias.
    assert res.status_code == 200, res.text


# ── Default fallback ─────────────────────────────────────────────


def test_no_league_key_falls_back_to_default(two_league_registry, monkeypatch):
    """Omitting ``leagueKey`` must continue to work — backward-compat
    for every existing caller that predates multi-league."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        res = c.get("/api/terminal")
    assert res.status_code == 200, res.text


# ── /api/data ────────────────────────────────────────────────────


def test_api_data_rejects_unknown_league(two_league_registry, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        # latest_data_bytes is referenced by the response path; make it
        # non-None so we hit the league validation first.
        monkeypatch.setattr(server, "latest_data_bytes", None)
        monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
        monkeypatch.setattr(server, "latest_data_etag", None)
        res = c.get("/api/data?leagueKey=ghost")
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"


def test_api_data_returns_200_with_nulled_sleeper_for_legacy_stub(
    two_league_registry, monkeypatch
):
    """Legacy test: the stub contract in this fixture doesn't stamp
    ``meta.scoringProfile``, which means the endpoint can't enforce
    profile matching.  In that case the pre-refactor behavior applies
    — same-scoring-profile pass-through is assumed, sleeper is
    nulled for the non-matching league.  Upgrading the stub to
    include a profile would push this into the ``stranger`` (503)
    path; see ``test_api_data_503s_when_scoring_profile_differs``."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        monkeypatch.setattr(server, "latest_data_bytes", None)
        monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
        monkeypatch.setattr(server, "latest_data_etag", None)
        res = c.get("/api/data?leagueKey=side")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sleeper"] is None
    assert body["meta"]["leagueKey"] == "side"
    assert body["meta"]["sleeperDataReady"] is False


# ── /api/trade/simulate ──────────────────────────────────────────


def test_trade_simulate_accepts_league_key_in_body(two_league_registry, monkeypatch):
    """Valid leagueKey passes validation — the downstream
    ``team_not_found`` surfaces because the stub sleeper block is
    minimal, which is fine: the test asserts validation succeeded by
    checking the 404 response still echoes the leagueKey back."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        monkeypatch.setattr(
            server, "_get_auth_session",
            lambda request: {"username": "alice", "auth_method": "sleeper", "sleeper_user_id": "oA"},
        )
        res = c.post(
            "/api/trade/simulate",
            json={"leagueKey": "main", "teamName": "Nonexistent", "playersIn": [], "playersOut": []},
        )
    # 404 team_not_found is the NEXT validation step after league
    # resolution — proves we got past the league check.
    assert res.status_code == 404, res.text
    body = res.json()
    assert body["error"] == "team_not_found"
    assert body["leagueKey"] == "main"


def test_trade_simulate_rejects_wrong_league_in_body(two_league_registry, monkeypatch):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        monkeypatch.setattr(
            server, "_get_auth_session",
            lambda request: {"username": "alice", "auth_method": "sleeper", "sleeper_user_id": "oA"},
        )
        res = c.post(
            "/api/trade/simulate",
            json={"leagueKey": "side", "teamName": "Team A"},
        )
    assert res.status_code == 503
    assert res.json()["error"] == "data_not_ready"


# ── Scoring-profile sharing ──────────────────────────────────────
# Leagues that share a scoring profile share one ranking pipeline
# output.  When the server has loaded the contract for League A
# but the client requests League B (same profile), the response
# carries the shared rankings with the ``sleeper`` block nulled
# and ``meta.sleeperDataReady: false``.  Only when profiles
# actually differ does the server 503.


@pytest.fixture
def shared_scoring_registry(tmp_path, monkeypatch):
    """Two leagues with the SAME scoring profile + one with a
    different profile.  Tests around scoring-vs-sleeper distinction
    use this fixture to verify that profile-match serves shared
    rankings and profile-mismatch returns 503."""
    path = tmp_path / "registry.json"
    path.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "main",
                "leagues": [
                    {
                        "key": "main",
                        "displayName": "Main",
                        "sleeperLeagueId": "LM",
                        "scoringProfile": "superflex_tep15_ppr1",
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                    {
                        "key": "twin",
                        "displayName": "Twin",
                        "sleeperLeagueId": "LT",
                        "scoringProfile": "superflex_tep15_ppr1",  # same
                        "active": True,
                        "rosterSettings": {"teamCount": 10},
                    },
                    {
                        "key": "stranger",
                        "displayName": "Stranger",
                        "sleeperLeagueId": "LS",
                        "scoringProfile": "standard_1qb_ppr1",  # different
                        "active": True,
                        "rosterSettings": {"teamCount": 12},
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()
    yield
    league_registry.reload_registry()


def _install_contract_with_profile(monkeypatch, league_key: str, profile: str):
    stub = {
        "meta": {"leagueKey": league_key, "scoringProfile": profile},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [{"name": "Stub"}],
        "sleeper": {"teams": [{"ownerId": "oA", "name": "Team A", "players": []}]},
    }
    monkeypatch.setattr(server, "latest_contract_data", stub)
    # Skip the pre-serialized bytes path so our hand-edited sleeper
    # scrubbing branch is exercised.
    monkeypatch.setattr(server, "latest_data_bytes", None)
    monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
    monkeypatch.setattr(server, "latest_data_etag", None)


def test_api_data_serves_shared_rankings_for_same_profile(
    shared_scoring_registry, monkeypatch
):
    """Loaded contract is for League 'main' (superflex_tep15_ppr1).
    Request for 'twin' (same profile) should succeed with 200,
    serve the rankings, and null the sleeper block so the UI
    doesn't render League main's teams under Twin's name.

    IMPORTANT: monkeypatch inside the TestClient context so app
    startup can't re-populate ``latest_contract_data`` after our
    stub.  Same pattern as the signal-alerts tests."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=twin")
    assert res.status_code == 200, res.text
    body = res.json()
    # Rankings are intact.
    assert body["players"]["stub"]["name"] == "Stub"
    # Sleeper is nulled + meta flags the state.
    assert body["sleeper"] is None
    assert body["meta"]["leagueKey"] == "twin"
    assert body["meta"]["scoringProfile"] == "superflex_tep15_ppr1"
    assert body["meta"]["sleeperDataReady"] is False
    assert body["meta"]["sleeperLoadedLeagueKey"] == "main"


def test_api_data_serves_full_contract_when_sleeper_matches(
    shared_scoring_registry, monkeypatch
):
    """When the loaded contract's leagueKey matches the requested
    league, the sleeper block is returned intact."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=main")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sleeper"] is not None
    assert body["sleeper"]["teams"][0]["ownerId"] == "oA"


def test_api_data_503s_when_scoring_profile_differs(
    shared_scoring_registry, monkeypatch
):
    """Loaded contract is superflex_tep15_ppr1.  Requesting the
    'stranger' league (standard_1qb_ppr1) must 503 — rankings
    genuinely can't be reused across different scoring."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=stranger")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "stranger"
    assert body["scoringProfile"] == "standard_1qb_ppr1"


def test_registry_helpers_share_scoring(shared_scoring_registry):
    """Unit-level check on the registry helpers themselves."""
    assert league_registry.leagues_share_scoring("main", "twin") is True
    assert league_registry.leagues_share_scoring("main", "stranger") is False
    assert league_registry.leagues_share_scoring("main", "unknown") is False
    assert league_registry.leagues_share_scoring(None, "main") is False
    assert league_registry.get_scoring_profile("twin") == "superflex_tep15_ppr1"


# ── /api/leagues stays coherent ──────────────────────────────────


def test_api_leagues_excludes_inactive(two_league_registry):
    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/leagues")
    assert res.status_code == 200
    keys = [lg["key"] for lg in res.json()["leagues"]]
    assert "main" in keys
    assert "side" in keys
    assert "retired" not in keys
