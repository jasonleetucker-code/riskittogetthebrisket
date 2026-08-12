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

import pytest
from fastapi.testclient import TestClient

import server
from src.api import league_registry
from tests.api.scoring_fixture import (
    OTHER_SCORING_CARD,
    SCORING_CARD,
    install_scoring_snapshots,
)


_install_scoring_snapshots = install_scoring_snapshots


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
    # main and side score identically — this fixture's cross-league tests
    # are about routing, not about scoring compatibility.
    _install_scoring_snapshots(
        tmp_path, monkeypatch, {"L-MAIN": SCORING_CARD, "L-SIDE": SCORING_CARD}
    )

    # Isolate user_kv to a temp file so the PUT paths don't leak.
    from src.api import user_kv

    monkeypatch.setattr(user_kv, "USER_KV_PATH", tmp_path / "user_kv.sqlite")
    user_kv._SETUP_DONE.clear()

    # Bypass the ``_private_api_gate`` middleware: these tests
    # exercise league-routing logic under authenticated conditions.
    # The gate is covered separately in ``test_private_auth.py``.
    # Stub ``_is_authenticated`` to always pass so we don't have to
    # seed a real session for every request.
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)

    yield

    # Reset the registry AFTER the test so later tests (especially
    # public_league tests that set SLEEPER_LEAGUE_ID directly) see
    # the env-var-fallback state, not this test's fixture leagues.
    # Without this, module-level _FILE_LOADED retains {"main",
    # "side", "retired"} — which makes get_default_league() return
    # "main" with sleeper_league_id "L-MAIN", breaking
    # _public_league_id() for downstream tests.
    league_registry.reload_registry()


def _install_contract_for_league(monkeypatch, league_key: str, *, scoring=SCORING_CARD):
    """Put a stub contract in ``latest_contract_data`` stamped for
    ``league_key``.  Minimal enough to pass the initial guards on
    routes like /api/trade/simulate that bail on missing
    ``playersArray``.

    ``scoring=None`` produces an UNIDENTIFIED contract — one carrying no
    scoring card at all, the pre-W18-F001 shape that used to be treated
    as compatible with every league.

    **Must be called INSIDE the TestClient context** so the
    ``app.lifespan`` startup can't overwrite ``latest_contract_data``
    after we set it.  Called pre-context, the stub is visible for a
    moment but gets clobbered when the TestClient enters — this
    passes locally (where cached scrape data may keep it alive) but
    fails in CI (where no data exists on disk).  See the signal-
    alerts tests (tests/api/test_signal_alerts.py) for the same
    pattern + rationale.
    """
    sleeper = {"teams": [{"ownerId": "oA", "name": "Team A", "players": []}]}
    if scoring is not None:
        sleeper["scoringSettings"] = dict(scoring)
    stub = {
        "meta": {"leagueKey": league_key},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [{"name": "Stub"}],
        "sleeper": sleeper,
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


def test_api_data_returns_200_with_nulled_sleeper_for_compatible_league(
    two_league_registry, monkeypatch
):
    """Proven-compatible scoring, different league → rankings, no sleeper.

    ``main`` and ``side`` carry identical scoring cards in this fixture,
    so the shared board is legitimately servable; the sleeper block is
    nulled because rosters are a leagueKey property.  The 503 path is
    ``test_api_data_503s_when_scoring_differs``.

    This test used to assert the same 200 for a contract stamping NO
    scoring identity at all, on the reasoning that a gate with nothing to
    compare should assume compatibility.  That was W18-F001's fail-open;
    ``test_api_data_503s_for_an_unidentified_contract`` now pins the
    opposite."""
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


def test_api_data_503s_for_an_unidentified_contract(two_league_registry, monkeypatch):
    """W18-F001: no scoring identity is UNPROVEN, not compatible.

    A contract carrying no scoring card cannot be shown to apply to any
    other league, so it is refused for one — while still serving its own
    league normally, which is what bounds the blast radius of failing
    closed to genuine cross-league requests."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main", scoring=None)
        monkeypatch.setattr(server, "latest_data_bytes", None)
        monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
        monkeypatch.setattr(server, "latest_data_etag", None)
        cross = c.get("/api/data?leagueKey=side")
        own = c.get("/api/data?leagueKey=main")
    assert cross.status_code == 503, cross.text
    body = cross.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "side"
    assert body["loadedScoringFingerprint"] is None
    assert own.status_code == 200, own.text


def test_api_data_503s_when_the_requested_league_has_no_snapshot(
    two_league_registry, tmp_path, monkeypatch
):
    """The other unproven direction: an identified contract, but the
    requested league's own scoring was never observed."""
    _install_scoring_snapshots(tmp_path, monkeypatch, {"L-MAIN": SCORING_CARD})
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        monkeypatch.setattr(server, "latest_data_bytes", None)
        monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
        monkeypatch.setattr(server, "latest_data_etag", None)
        res = c.get("/api/data?leagueKey=side")
    assert res.status_code == 503, res.text
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["scoringFingerprint"] is None
    assert body["loadedScoringFingerprint"]


def test_api_data_compact_view_serves_precomputed_bytes(two_league_registry, monkeypatch):
    """``view=compact`` must serve the payload precomputed at refresh time
    (bytes + ETag) rather than re-running ``compact_contract`` +
    ``json.dumps`` + gzip on the event loop for every mobile request."""
    import json as _json

    with TestClient(server.app, raise_server_exceptions=True) as c:
        default_cfg = server._league_registry.get_default_league()
        stub = {
            "meta": {
                "leagueKey": default_cfg.key,
                "scoringProfile": default_cfg.scoring_profile,
            },
            "players": {"stub": {"name": "Stub"}},
            "playersArray": [{"name": "Stub"}],
            "sleeper": {"teams": []},
        }
        compact_obj = {"players": {"stub": {"name": "Stub"}}, "payloadView": "compact"}
        compact_bytes = _json.dumps(compact_obj).encode("utf-8")
        monkeypatch.setattr(server, "latest_contract_data", stub)
        monkeypatch.setattr(server, "latest_compact_data", compact_obj)
        monkeypatch.setattr(server, "latest_compact_data_bytes", compact_bytes)
        monkeypatch.setattr(server, "latest_compact_data_gzip_bytes", None)
        monkeypatch.setattr(server, "latest_compact_data_etag", "compact-etag-xyz")
        # No live overlay → deterministic cached-bytes fast path.
        monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **kw: None)
        res = c.get("/api/data?view=compact")

    assert res.status_code == 200, res.text
    assert res.headers.get("X-Payload-View", "").startswith("compact")
    # ETag present ⇒ the precomputed fast path served it (the on-demand
    # fallback leaves the ETag unset).
    assert res.headers.get("ETag") == "compact-etag-xyz"
    # The negotiated (gzip-or-identity) fast path must advertise Vary so a
    # shared cache doesn't mis-serve encodings.
    assert res.headers.get("Vary") == "Accept-Encoding"
    assert res.json() == compact_obj


# ── /api/trade/simulate ──────────────────────────────────────────


def test_trade_simulate_accepts_league_key_in_body(two_league_registry, monkeypatch):
    """Valid leagueKey passes validation — the downstream
    ``team_not_found`` surfaces because the stub sleeper block is
    minimal, which is fine: the test asserts validation succeeded by
    checking the 404 response still echoes the leagueKey back."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_for_league(monkeypatch, "main")
        monkeypatch.setattr(
            server,
            "_get_auth_session",
            lambda request: {
                "username": "alice",
                "auth_method": "sleeper",
                "sleeper_user_id": "oA",
            },
        )
        res = c.post(
            "/api/trade/simulate",
            json={
                "leagueKey": "main",
                "teamName": "Nonexistent",
                "playersIn": [],
                "playersOut": [],
            },
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
            server,
            "_get_auth_session",
            lambda request: {
                "username": "alice",
                "auth_method": "sleeper",
                "sleeper_user_id": "oA",
            },
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
    # The labels above are what the fixture is NAMED for, but they no
    # longer decide anything (W18-F001).  The cards do: main and twin
    # score identically, stranger does not.
    _install_scoring_snapshots(
        tmp_path,
        monkeypatch,
        {"LM": SCORING_CARD, "LT": SCORING_CARD, "LS": OTHER_SCORING_CARD},
    )
    # Bypass the private-api middleware — separately tested in
    # test_private_auth.py.  Without this, /api/data + /api/terminal
    # 401 before the scoring-compatibility logic can run.
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    yield
    league_registry.reload_registry()


def _install_contract_with_profile(
    monkeypatch, league_key: str, profile: str, *, scoring=SCORING_CARD
):
    sleeper = {"teams": [{"ownerId": "oA", "name": "Team A", "players": []}]}
    if scoring is not None:
        sleeper["scoringSettings"] = dict(scoring)
    stub = {
        "meta": {"leagueKey": league_key, "scoringProfile": profile},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [{"name": "Stub"}],
        "sleeper": sleeper,
    }
    monkeypatch.setattr(server, "latest_contract_data", stub)
    # Skip the pre-serialized bytes path so our hand-edited sleeper
    # scrubbing branch is exercised.
    monkeypatch.setattr(server, "latest_data_bytes", None)
    monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
    monkeypatch.setattr(server, "latest_data_etag", None)


def test_api_data_serves_shared_rankings_for_same_profile(shared_scoring_registry, monkeypatch):
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


def test_api_data_serves_full_contract_when_sleeper_matches(shared_scoring_registry, monkeypatch):
    """When the loaded contract's leagueKey matches the requested
    league AND the live Sleeper overlay is unavailable, the baked-in
    sleeper block falls through unchanged.

    The overlay path is the new default (so post-trade roster moves
    reflect within ~15 min), but /api/data must still serve a
    coherent response when Sleeper is down — that fallback is what
    this test pins.
    """
    monkeypatch.setattr(
        server._sleeper_overlay,
        "fetch_sleeper_overlay",
        lambda **_kw: None,  # overlay unavailable → fall back to baked
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=main")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sleeper"] is not None
    assert body["sleeper"]["teams"][0]["ownerId"] == "oA"


def test_api_data_overlays_fresh_sleeper_for_loaded_league(shared_scoring_registry, monkeypatch):
    """When the live overlay is available, /api/data splices it onto
    the loaded league's response so the rosters reflect Sleeper
    activity within the overlay's 15-min cache window — even for
    the default league.  This is the contract that makes /waivers,
    /trade, /rosters, /draft converge on a 15-min staleness ceiling
    instead of inheriting the 2h scrape cadence.
    """
    fresh_overlay = {
        "teams": [
            {"ownerId": "oA", "name": "Team A", "players": ["fresh-player-1"]},
        ],
        "leagueId": "L-MAIN",
        "overlaySource": "live",
        "overlayFetchedAt": "2026-04-29T11:30:00+00:00",
    }
    monkeypatch.setattr(
        server._sleeper_overlay,
        "fetch_sleeper_overlay",
        lambda **_kw: fresh_overlay,
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=main")
    assert res.status_code == 200, res.text
    body = res.json()
    # The overlay's roster wins over the baked-in empty roster.
    assert body["sleeper"]["teams"][0]["players"] == ["fresh-player-1"]
    assert body["meta"]["sleeperSource"] == "overlay"
    assert body["meta"]["sleeperDataReady"] is True
    # X-Payload-View header tags the overlay path so ops can grep
    # logs to confirm the overlay merge fired.
    assert "overlay" in res.headers.get("X-Payload-View", "")


def test_api_data_overlay_response_is_offloaded_and_cached(shared_scoring_registry, monkeypatch):
    """The live-overlay response is serialized off the event loop and the
    encoded bytes are cached by (league, view, overlay-freshness, base
    ETag), so repeat requests within the overlay window reuse the dump
    instead of re-encoding the multi-MB payload.  It also gains an ETag
    with If-None-Match 304 support and Vary: Accept-Encoding."""
    fresh_overlay = {
        "teams": [{"ownerId": "oA", "name": "Team A", "players": ["p1"]}],
        "leagueId": "L-MAIN",
        "overlaySource": "live",
        "overlayFetchedAt": "2026-04-29T11:30:00+00:00",
    }
    monkeypatch.setattr(
        server._sleeper_overlay, "fetch_sleeper_overlay", lambda **_kw: fresh_overlay
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        # A base ETag is required for the overlay response cache to engage.
        monkeypatch.setattr(server, "latest_data_etag", "base-etag-1")
        server._OVERLAY_RESPONSE_CACHE.clear()

        # Count real encodes: gzip.compress runs once per fresh encode and
        # is skipped on a cache hit.
        encode_calls = {"n": 0}
        real_compress = server.gzip.compress

        def _counting(data, *a, **k):
            encode_calls["n"] += 1
            return real_compress(data, *a, **k)

        monkeypatch.setattr(server.gzip, "compress", _counting)

        r1 = c.get("/api/data?leagueKey=main")
        r2 = c.get("/api/data?leagueKey=main")
        etag = r1.headers.get("ETag")
        r3 = c.get("/api/data?leagueKey=main", headers={"If-None-Match": etag})

    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200
    # Overlay content is intact and the path is tagged.
    assert r1.json()["sleeper"]["teams"][0]["players"] == ["p1"]
    assert "overlay" in r1.headers.get("X-Payload-View", "")
    # Negotiated fast path advertises Vary + carries an ETag.
    assert r1.headers.get("Vary") == "Accept-Encoding"
    assert etag and r2.headers.get("ETag") == etag
    # Encoded exactly once across two identical requests (2nd = cache hit).
    assert encode_calls["n"] == 1
    assert len(server._OVERLAY_RESPONSE_CACHE) == 1
    # Conditional request short-circuits to 304 (no body re-encode).
    assert r3.status_code == 304


def test_overlay_serialize_single_flights_concurrent_misses(monkeypatch):
    """Concurrent cache misses for the same key must coalesce onto a
    single encode — the rest await the per-key lock and read the cached
    result — so a burst can't fan out into N multi-MB serializations."""
    import asyncio
    import time

    server._OVERLAY_RESPONSE_CACHE.clear()
    server._OVERLAY_ENCODE_LOCKS.clear()

    encode_calls = {"n": 0}
    real_compress = server.gzip.compress

    def slow_compress(data, *a, **k):
        encode_calls["n"] += 1
        time.sleep(0.2)  # widen the miss window so the burst overlaps
        return real_compress(data, *a, **k)

    monkeypatch.setattr(server.gzip, "compress", slow_compress)

    class _FakeReq:
        headers = {}  # .get("if-none-match") / .get("accept-encoding") → None

    scrubbed = {"players": {"x": 1}, "meta": {"leagueKey": "main"}}
    # Cache key is now stable (no version info); version is passed separately
    key = ("overlay", "main", "", "full", True)
    version = ("2026-04-29T11:30:00+00:00", "base-etag-1")

    async def _fire():
        return await asyncio.gather(
            *[
                server._serialize_overlaid_response(_FakeReq(), scrubbed, {}, key, version)
                for _ in range(5)
            ]
        )

    results = asyncio.run(_fire())

    # Exactly one encode across five concurrent requests.
    assert encode_calls["n"] == 1
    assert all(r.status_code == 200 for r in results)
    assert len(server._OVERLAY_RESPONSE_CACHE) == 1


def test_overlay_serialize_cache_invalidates_on_version_change(monkeypatch):
    """When the overlay refreshes (overlayFetchedAt or baseETag changes),
    the cache key remains stable but the stored version is checked; a
    mismatch triggers a re-encode in place, bounding memory to one
    generation per slot."""
    import asyncio

    server._OVERLAY_RESPONSE_CACHE.clear()
    server._OVERLAY_ENCODE_LOCKS.clear()

    encode_calls = {"n": 0}
    real_compress = server.gzip.compress

    def _counting(data, *a, **k):
        encode_calls["n"] += 1
        return real_compress(data, *a, **k)

    monkeypatch.setattr(server.gzip, "compress", _counting)

    class _FakeReq:
        headers = {}

    scrubbed = {"players": {"x": 1}, "meta": {"leagueKey": "main"}}
    key = ("overlay", "main", "", "full", True)
    version_1 = ("2026-04-29T11:30:00+00:00", "base-etag-1")
    version_2 = ("2026-04-29T11:45:00+00:00", "base-etag-1")  # different overlayFetchedAt

    async def _run():
        # First request with version_1 — encodes and caches
        r1 = await server._serialize_overlaid_response(_FakeReq(), scrubbed, {}, key, version_1)
        # Second request with same version_1 — cache hit, no encode
        r2 = await server._serialize_overlaid_response(_FakeReq(), scrubbed, {}, key, version_1)
        # Third request with version_2 (refresh) — version mismatch, re-encode in place
        r3 = await server._serialize_overlaid_response(_FakeReq(), scrubbed, {}, key, version_2)
        # Fourth request with version_2 — cache hit, no encode
        r4 = await server._serialize_overlaid_response(_FakeReq(), scrubbed, {}, key, version_2)
        return [r1, r2, r3, r4]

    results = asyncio.run(_run())

    assert all(r.status_code == 200 for r in results)
    # Encoded twice: once for version_1, once for version_2 refresh
    assert encode_calls["n"] == 2
    # Cache has only one entry: same slot, version replaced
    assert len(server._OVERLAY_RESPONSE_CACHE) == 1


def test_cross_league_cache_slot_is_reused_across_refreshes(shared_scoring_registry, monkeypatch):
    """The cross-league (overlay-unavailable) fallback must use the same
    stable-slot scheme as the overlay path: a scrape refresh changes the
    base ETag, which is the entry VERSION, not part of the key — so the
    slot is replaced rather than accumulating a second multi-MB
    generation beside it."""
    # Overlay unavailable → the `not sleeper_matches` fallback branch.
    monkeypatch.setattr(server._sleeper_overlay, "fetch_sleeper_overlay", lambda **_kw: None)

    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        server._OVERLAY_RESPONSE_CACHE.clear()
        server._OVERLAY_ENCODE_LOCKS.clear()

        monkeypatch.setattr(server, "latest_data_etag", "base-etag-1")
        r1 = c.get("/api/data?leagueKey=twin")
        r2 = c.get("/api/data?leagueKey=twin")
        assert len(server._OVERLAY_RESPONSE_CACHE) == 1
        key_after_first = next(iter(server._OVERLAY_RESPONSE_CACHE))

        # A scrape lands: same league/view, new base payload version.
        monkeypatch.setattr(server, "latest_data_etag", "base-etag-2")
        r3 = c.get("/api/data?leagueKey=twin")

    assert all(r.status_code == 200 for r in (r1, r2, r3))
    # Still ONE entry — the refresh replaced the slot instead of adding one.
    assert len(server._OVERLAY_RESPONSE_CACHE) == 1
    assert next(iter(server._OVERLAY_RESPONSE_CACHE)) == key_after_first
    # The base ETag is the entry version, never part of the key.
    assert "base-etag-1" not in key_after_first
    assert "base-etag-2" not in key_after_first


def test_api_data_overlay_layers_fresh_trades_in_baked_shape(shared_scoring_registry, monkeypatch):
    """The overlay's ``trades`` block now produces the same
    ``[{leagueId, week, timestamp, sides[]}, ...]`` shape that the
    offline scraper bakes into ``sleeper.trades`` (see
    ``src/api/sleeper_overlay.py::_build_trades_block``).  That
    parity lets the overlay merge override baked trades with FRESH
    trades — what makes the /trades page reflect Sleeper activity
    within the overlay's 15-min cache window.

    Regression pin: when the overlay was returning raw Sleeper
    transactions in ``trades`` instead of the processed shape, the
    merge couldn't safely use them; trades were either blanked
    (older buggy state) or pinned to the ~2h scrape cadence (the
    interim fix).  Both regressions are covered by this test going
    green.
    """
    baked_trades = [
        {
            "leagueId": "L-MAIN",
            "sides": [{"a": 1}, {"b": 2}],
            "timestamp": 1700000000000,
            "week": 3,
        },
    ]
    fresh_overlay_trade = {
        "leagueId": "L-MAIN",
        "week": 5,
        "timestamp": 1730000000000,
        "sides": [
            {"team": "Team A", "rosterId": 1, "ownerId": "oA", "got": ["Fresh Player"], "gave": []},
            {"team": "Team B", "rosterId": 2, "ownerId": "oB", "got": [], "gave": ["Fresh Player"]},
        ],
    }
    overlay_payload = {
        "teams": [
            {"ownerId": "oA", "name": "Team A", "players": ["fresh-player-1"]},
        ],
        # Overlay now emits the same processed shape as the bake.
        "trades": [fresh_overlay_trade],
        "tradeWindowDays": 365,
        "leagueId": "L-MAIN",
        "overlaySource": "live",
        "overlayFetchedAt": "2026-04-29T12:00:00+00:00",
    }
    monkeypatch.setattr(
        server._sleeper_overlay,
        "fetch_sleeper_overlay",
        lambda **_kw: overlay_payload,
    )
    stub = {
        "meta": {"leagueKey": "main", "scoringProfile": "superflex_tep15_ppr1"},
        "players": {"stub": {"name": "Stub"}},
        "playersArray": [{"name": "Stub"}],
        "sleeper": {
            "teams": [{"ownerId": "oA", "name": "Team A", "players": []}],
            "trades": baked_trades,
            "positions": {"WR": ["A"]},
            "leagueSettings": {"sample": True},
        },
    }
    with TestClient(server.app, raise_server_exceptions=True) as c:
        monkeypatch.setattr(server, "latest_contract_data", stub)
        monkeypatch.setattr(server, "latest_data_bytes", None)
        monkeypatch.setattr(server, "latest_data_gzip_bytes", None)
        monkeypatch.setattr(server, "latest_data_etag", None)
        res = c.get("/api/data?leagueKey=main")
    assert res.status_code == 200, res.text
    body = res.json()
    sleeper = body["sleeper"]
    # Teams + trades come from overlay (fresh).
    assert sleeper["teams"][0]["players"] == ["fresh-player-1"]
    assert sleeper["trades"] == [fresh_overlay_trade]
    # Every overlay trade carries the baked-shape ``sides`` array so
    # frontend trade-grading can parse it.
    assert "sides" in sleeper["trades"][0]
    # Non-overlaid baked fields (positions, leagueSettings, …) are
    # preserved — the overlay merge must not strip them.
    assert sleeper["positions"] == {"WR": ["A"]}
    assert sleeper["leagueSettings"] == {"sample": True}
    # Diagnostic stamp identifies the new merge path.
    assert sleeper.get("overlaySource") == "live-merge"


def test_api_data_503s_when_scoring_differs(shared_scoring_registry, monkeypatch):
    """'stranger' scores differently → 503; rankings can't be reused."""
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=stranger")
    assert res.status_code == 503
    body = res.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "stranger"
    assert body["scoringProfile"] == "standard_1qb_ppr1"
    # Both sides identified — this is a proven MISMATCH, not an
    # unverifiable one, and the response says which.
    assert body["scoringFingerprint"]
    assert body["loadedScoringFingerprint"]
    assert body["scoringFingerprint"] != body["loadedScoringFingerprint"]


def test_api_data_503s_when_only_the_label_matches(shared_scoring_registry, tmp_path, monkeypatch):
    """The live defect, in miniature (W18-F001).

    ``twin`` carries the SAME ``scoringProfile`` label as ``main``.  Give
    it a genuinely different scoring card — which is the repo's real
    situation, where both live leagues are labelled
    ``superflex_tep15_ppr1`` and differ on 35 of 48 shared keys — and the
    board must be refused despite the matching label."""
    _install_scoring_snapshots(
        tmp_path, monkeypatch, {"LM": SCORING_CARD, "LT": OTHER_SCORING_CARD}
    )
    with TestClient(server.app, raise_server_exceptions=True) as c:
        _install_contract_with_profile(monkeypatch, "main", "superflex_tep15_ppr1")
        res = c.get("/api/data?leagueKey=twin")
    assert res.status_code == 503, res.text
    assert res.json()["error"] == "data_not_ready"
    assert league_registry.get_scoring_profile("twin") == league_registry.get_scoring_profile(
        "main"
    )


def test_registry_helpers_share_scoring(shared_scoring_registry):
    """Unit-level check on the registry helpers themselves.

    ``leagues_share_scoring`` answers from the factual cards; the profile
    label is still readable and still means what it always meant, it just
    no longer decides this."""
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


# ── userDefaultTeam auto-resolve for leagues missing defaultTeamMap ──
#
# When a user is signed in and the registry has NO defaultTeamMap entry
# for them on a given league (typical for newly-added leagues), the
# /api/leagues endpoint must fall back to Sleeper: look up the user's
# Sleeper user_id in that league's /users and stamp the team name so
# the frontend team picker can auto-select it.  Without this the
# dashboard stays at "Pick your team" until the user manually selects.


def test_api_leagues_autoresolves_user_team_via_sleeper(
    two_league_registry,
    monkeypatch,
):
    """Registry has no defaultTeamMap for "main" → server should
    resolve the user's team from Sleeper via their sleeper_user_id."""
    # Seed an in-memory session with a Sleeper user_id.
    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda request: {
            "username": "jasonleetucker",
            "sleeper_user_id": "U-JASON",
        },
    )

    # Stub the Sleeper user-team lookup to pretend Jason is in "main"
    # as "Rossini Panini" and in "side" as "Blood Sweat Crew".
    def _stub_fetch(league_id, user_id):
        assert user_id == "U-JASON"
        if league_id == "L-MAIN":
            return {"ownerId": "U-JASON", "teamName": "Rossini Panini"}
        if league_id == "L-SIDE":
            return {"ownerId": "U-JASON", "teamName": "Blood Sweat Crew"}
        return None

    monkeypatch.setattr(server, "_fetch_sleeper_user_team", _stub_fetch)
    # Avoid the live Sleeper name fetch in the test.
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _id: None)

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/leagues")
    assert res.status_code == 200
    body = res.json()
    by_key = {lg["key"]: lg for lg in body["leagues"]}
    assert by_key["main"]["userDefaultTeam"]["teamName"] == "Rossini Panini"
    assert by_key["side"]["userDefaultTeam"]["teamName"] == "Blood Sweat Crew"


def test_api_leagues_registry_default_team_wins_over_sleeper_fallback(
    tmp_path,
    monkeypatch,
):
    """When the registry DOES have a defaultTeamMap entry, that
    takes precedence — the Sleeper fallback is only for leagues the
    registry hasn't been edited for."""
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
                        "rosterSettings": {},
                        "defaultTeamMap": {
                            "jasonleetucker": {"teamName": "Registry-Override"},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LEAGUE_REGISTRY_PATH", str(path))
    league_registry.reload_registry()

    monkeypatch.setattr(
        server,
        "_get_auth_session",
        lambda request: {
            "username": "jasonleetucker",
            "sleeper_user_id": "U-JASON",
        },
    )
    # This stub should NEVER be called if the registry entry wins.
    calls = []

    def _should_not_be_called(*a, **kw):
        calls.append((a, kw))
        return {"ownerId": "U-JASON", "teamName": "Sleeper-Fallback"}

    monkeypatch.setattr(server, "_fetch_sleeper_user_team", _should_not_be_called)
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _id: None)

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/leagues")
    assert res.status_code == 200
    body = res.json()
    main = next(lg for lg in body["leagues"] if lg["key"] == "main")
    assert main["userDefaultTeam"]["teamName"] == "Registry-Override"
    assert calls == [], "Sleeper fallback should not run when registry has a mapping"

    league_registry.reload_registry()


def test_api_leagues_anonymous_users_get_no_user_default_team(
    two_league_registry,
    monkeypatch,
):
    """Anonymous callers (no session) must not get a userDefaultTeam
    block — we don't leak any user's team-in-league on an unauthed
    response."""
    monkeypatch.setattr(server, "_get_auth_session", lambda request: None)
    monkeypatch.setattr(server, "_fetch_sleeper_league_name", lambda _id: None)

    with TestClient(server.app, raise_server_exceptions=True) as c:
        res = c.get("/api/leagues")
    body = res.json()
    for lg in body["leagues"]:
        assert "userDefaultTeam" not in lg


def test_fetch_sleeper_user_team_returns_none_for_unknown_user(monkeypatch):
    """Direct unit test on the helper: an unknown user_id → None
    (not an exception)."""
    import io

    def _fake_urlopen(req, timeout=5.0):
        return io.BytesIO(b'[{"user_id":"OTHER","metadata":{"team_name":"Not Mine"}}]')

    monkeypatch.setattr(server.urllib.request, "urlopen", _fake_urlopen)
    # Clear cache so this call actually hits the stub.
    server._SLEEPER_USER_TEAM_CACHE.clear()
    result = server._fetch_sleeper_user_team("L-MAIN", "U-JASON")
    assert result is None


def test_fetch_sleeper_user_team_resolves_team_name(monkeypatch):
    """Helper returns {ownerId, teamName} when the user is present in
    the league's users list."""
    import io

    def _fake_urlopen(req, timeout=5.0):
        return io.BytesIO(
            b'[{"user_id":"U-JASON","metadata":{"team_name":"Brisket Crew"},'
            b'"display_name":"jasonleetucker"}]'
        )

    monkeypatch.setattr(server.urllib.request, "urlopen", _fake_urlopen)
    server._SLEEPER_USER_TEAM_CACHE.clear()
    result = server._fetch_sleeper_user_team("L-MAIN", "U-JASON")
    assert result == {"ownerId": "U-JASON", "teamName": "Brisket Crew"}


def test_fetch_sleeper_user_team_falls_back_to_display_name(monkeypatch):
    """When ``metadata.team_name`` is absent, fall back to
    ``display_name`` so the team picker shows SOMETHING instead of
    blank."""
    import io

    def _fake_urlopen(req, timeout=5.0):
        return io.BytesIO(b'[{"user_id":"U-JASON","display_name":"jasonleetucker"}]')

    monkeypatch.setattr(server.urllib.request, "urlopen", _fake_urlopen)
    server._SLEEPER_USER_TEAM_CACHE.clear()
    result = server._fetch_sleeper_user_team("L-MAIN", "U-JASON")
    assert result == {"ownerId": "U-JASON", "teamName": "jasonleetucker"}
