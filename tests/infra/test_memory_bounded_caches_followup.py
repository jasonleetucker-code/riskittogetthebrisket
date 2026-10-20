"""Memory bounds, follow-up to the 2026-10-19 production memory-pressure incident.

``test_memory_bounded_caches.py`` pins the three retentions #1848 bounded.
The W8 retention audit of 2026-10-20 (module-global deep-size scan plus a
promotion-churn harness, after #1848) ranked the largest retentions still
able to grow:

* ``manager_activity._memo`` -- raw Sleeper responses, ~46 KB each, capped
  at 8192 (~380 MB) with LAZY expiry: an entry left only when the same key
  was re-read past its TTL, or at the cap;
* the intel payload memos (activity / profile / career / league scouting)
  -- the same lazy expiry, ~350 KB per activity payload;
* ``server._OVERRIDES_RESPONSE_CACHE`` -- 16 entries of raw+gzip bytes keyed
  on the posted ``tep_multiplier``: ~105 MB (delta) / ~280 MB (full) worst
  case;
* ``server._player_impact_cache`` -- keyed by snapshot generation, so up to
  three dead generations (~8.7 MB each) stayed resident.

Each test pins BOTH halves of the fix: what a caller is served is unchanged,
and the retention is bounded.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.intel import manager_activity as ma
from src.intel import manager_career as mc
from src.intel import manager_league as ml
from src.intel import manager_portfolio as mp

# ── manager_activity._memo ────────────────────────────────────────────


@pytest.fixture
def clean_memo():
    ma.reset_caches()
    yield
    ma.reset_caches()


def test_memo_ttl_answers_unchanged(clean_memo):
    ma._memo_put(("week", "L1", "3"), {"w": 3}, 300.0, 1000.0)
    assert ma._memo_get(("week", "L1", "3"), 1299.0) == {"w": 3}, "live entry served"
    assert ma._memo_get(("week", "L1", "3"), 1300.0) is None, "expired entry never served"


def test_memo_cap_is_bounded_and_fits_two_full_budget_requests():
    assert ma._MEMO_MAX_ENTRIES <= 2048
    # One request puts at most CALL_BUDGET entries, so two concurrent
    # full-budget requests never evict each other's entries.
    assert ma._MEMO_MAX_ENTRIES >= 2 * ma.CALL_BUDGET


def test_memo_sweep_drops_only_entries_no_running_request_can_read(clean_memo):
    ttl = 300.0
    grace = ma._MEMO_SWEEP_GRACE_SECONDS
    for i in range(50):
        ma._memo_put(("week", "L1", str(i)), {"w": i}, ttl, 1000.0)
    # Expired, but inside the grace: a request that started at t=1000 and is
    # still running reads with its own clock and must still be answered.
    ma._memo_put(("week", "L2", "0"), {"w": "x"}, ttl, 1000.0 + ttl + 10.0)
    assert len(ma._memo) == 51
    assert ma._memo_get(("week", "L1", "7"), 1000.0) == {"w": 7}
    # Past TTL + grace: nothing running can read it any more, so a put sweeps.
    late = 1000.0 + ttl + grace + 1.0
    ma._memo_put(("week", "L3", "0"), {"w": "fresh"}, ttl, late)
    assert ("week", "L1", "7") not in ma._memo
    assert set(ma._memo) == {("week", "L2", "0"), ("week", "L3", "0")}


def test_memo_sweep_is_amortized(clean_memo, monkeypatch):
    calls = []
    real = ma._sweep_memo_locked
    monkeypatch.setattr(ma, "_sweep_memo_locked", lambda now: (calls.append(now), real(now)))
    for i in range(500):
        ma._memo_put(("week", "L1", str(i)), i, 300.0, 1000.0 + i * 0.01)
    assert len(calls) == 1, "one sweep per interval, not one per put"
    ma._memo_put(("week", "L1", "x"), "x", 300.0, 1000.0 + ma._MEMO_SWEEP_INTERVAL_SECONDS)
    assert len(calls) == 2


def test_memo_cap_evicts_oldest_live_entry(clean_memo, monkeypatch):
    monkeypatch.setattr(ma, "_MEMO_MAX_ENTRIES", 8)
    for i in range(12):
        ma._memo_put(("k", str(i)), i, 3600.0, 1000.0 + i)
    assert len(ma._memo) == 8
    assert set(ma._memo) == {("k", str(i)) for i in range(4, 12)}
    # Re-putting a key already present never evicts a different one.
    ma._memo_put(("k", "11"), "again", 3600.0, 1020.0)
    assert len(ma._memo) == 8 and ("k", "4") in ma._memo


# ── intel payload memos ───────────────────────────────────────────────


def _ok(tag):
    return {"status": mp.STATUS_OK, "tag": tag}


_PAYLOAD_CACHES = [
    pytest.param(
        "activity",
        lambda u, now: ma.cached_manager_activity(u, contract=None, now=now),
        (ma, "build_manager_activity"),
        lambda: ma._payload_cache,
        ma.PAYLOAD_TTL_SECONDS,
        ma.reset_caches,
        id="activity",
    ),
    pytest.param(
        "profile",
        lambda u, now: mp.cached_manager_profile(u, contract=None, now=now),
        (mp, "build_manager_profile"),
        lambda: mp._cache,
        mp.CACHE_TTL_SECONDS,
        mp.reset_cache,
        id="profile",
    ),
    pytest.param(
        "career",
        lambda u, now: mc.cached_manager_career(u, contract=None, now=now),
        (mc, "build_manager_career"),
        lambda: mc._cache,
        mc.PAYLOAD_TTL_SECONDS,
        mc.reset_cache,
        id="career",
    ),
    pytest.param(
        "league",
        lambda u, now: ml.cached_league_scouting(u, contract=None, now=now),
        (ml, "build_league_scouting"),
        lambda: ml._payload_cache,
        ml.PAYLOAD_TTL_SECONDS,
        ml.reset_cache,
        id="league",
    ),
]


@pytest.mark.parametrize("name, call, builder, cache, ttl, reset", _PAYLOAD_CACHES)
def test_payload_memo_answers_unchanged_and_expired_entries_swept(
    name, call, builder, cache, ttl, reset, monkeypatch
):
    module, attr = builder
    built: list[str] = []

    def _build(key, **kwargs):
        built.append(key)
        return _ok(f"{key}@{len(built)}")

    monkeypatch.setattr(module, attr, _build)
    reset()
    try:
        clock = {"t": 1000.0}

        def now():
            return clock["t"]

        first = call("alice", now)
        assert first["cached"] is False
        clock["t"] = 1000.0 + ttl - 1
        hit = call("alice", now)
        assert hit["cached"] is True and hit["tag"] == first["tag"], "live entry served"
        for i in range(20):
            call(f"user{i}", now)
        assert len(cache()) == 21
        clock["t"] = 1000.0 + 2 * ttl + 5  # every entry is past its TTL
        miss = call("alice", now)
        assert miss["cached"] is False, "expired entry never served (unchanged)"
        # The put swept every expired entry; only the fresh one remains.
        assert len(cache()) == 1
    finally:
        reset()


def test_payload_memo_sweep_never_drops_a_live_entry():
    cache = {"live": (100.0, "a"), "edge": (40.0, "b"), "dead": (39.0, "c")}
    mp.drop_expired_payloads_locked(cache, 100.0, 60.0)
    # ``t - stamp < ttl`` is served; exactly those survive.
    assert set(cache) == {"live"}
    cache = {"live": (100.0, "a"), "edge": (40.1, "b")}
    mp.drop_expired_payloads_locked(cache, 100.0, 60.0)
    assert set(cache) == {"live", "edge"}


# ── server: rankings-overrides response memo ──────────────────────────


@pytest.fixture
def overrides_cache():
    import server

    saved = dict(server._OVERRIDES_RESPONSE_CACHE)
    server._OVERRIDES_RESPONSE_CACHE.clear()
    yield server
    server._OVERRIDES_RESPONSE_CACHE.clear()
    server._OVERRIDES_RESPONSE_CACHE.update(saved)


def test_overrides_memo_byte_budget_admits_the_stock_working_set(overrides_cache):
    server = overrides_cache
    mb = 1024 * 1024
    # Measured 2026-10-20: delta entry ~6.5 MB, full-view entry ~17.3 MB
    # (raw + gzip).  Stock traffic = one body per league x {delta, full}.
    stock = 2 * (int(6.5 * mb) + int(17.3 * mb))
    assert stock < server._OVERRIDES_RESPONSE_CACHE_MAX_BYTES
    assert server._OVERRIDES_RESPONSE_CACHE_MAX_BYTES <= 64 * mb
    for i, size in enumerate([6.5, 17.3, 6.5]):
        server._OVERRIDES_RESPONSE_CACHE[("stock", i)] = (b"r" * int(size * mb), b"", 1)
    server._evict_overrides_cache_if_oversized(("stock", 3))
    assert len(server._OVERRIDES_RESPONSE_CACHE) == 3, "stock entries are not evicted"


def test_overrides_memo_is_byte_bounded(overrides_cache):
    server = overrides_cache
    mb = 1024 * 1024
    # A client spraying distinct tep values: full-view sized entries.
    for i in range(16):
        server._evict_overrides_cache_if_oversized(("tep", i))
        server._OVERRIDES_RESPONSE_CACHE[("tep", i)] = (b"r" * (12 * mb), b"g" * (5 * mb), 1)
        assert server._overrides_cache_bytes() <= server._OVERRIDES_RESPONSE_CACHE_MAX_BYTES + (
            17 * mb
        ), "never more than the budget plus the entry being stored"
    assert len(server._OVERRIDES_RESPONSE_CACHE) < 16


def test_overrides_memo_count_cap_still_applies(overrides_cache):
    server = overrides_cache
    for i in range(server._OVERRIDES_RESPONSE_CACHE_MAX):
        server._OVERRIDES_RESPONSE_CACHE[("tiny", i)] = (b"x", b"y", 1)
    keep = ("tiny", 3)
    server._evict_overrides_cache_if_oversized(keep)
    assert list(server._OVERRIDES_RESPONSE_CACHE) == [keep]


# ── server: player-impact cache across snapshot generations ───────────


def test_player_impact_drops_dead_generations_and_answers_unchanged(monkeypatch):
    from fastapi.testclient import TestClient

    import server
    from src.public_league import player_impact as pi
    from tests.public_league.test_player_impact import _snapshot

    snap, _season = _snapshot()
    league = SimpleNamespace(key="main", sleeper_league_id="L1")
    monkeypatch.setattr(server, "_get_public_snapshot", lambda force_refresh=False: snap)
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda request: league)
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    monkeypatch.setattr(server, "_get_auth_session", lambda request: {"username": "t"})
    computed: list[str] = []
    real_compute = pi.compute_season
    monkeypatch.setattr(
        pi,
        "compute_season",
        lambda s, t: (computed.append(str(s.generated_at)), real_compute(s, t))[1],
    )
    saved = dict(server._player_impact_cache)
    server._player_impact_cache.clear()
    other = ("OTHER-ROOT", "g0", "x")
    server._player_impact_cache[other] = {"other": True}
    try:
        client = TestClient(server.app)
        snap.generated_at = "gen-1"
        a = client.get("/api/league/player-impact?playerId=t").json()
        snap.generated_at = "gen-2"
        b = client.get("/api/league/player-impact?playerId=t").json()
        assert computed == ["gen-1", "gen-2"]
        # Same snapshot content: the answer differs only in its stamp.
        assert {**a, "generatedAt": None} == {**b, "generatedAt": None}
        keys = set(server._player_impact_cache)
        assert other in keys, "another league's entry is untouched"
        assert all(k[1] != "gen-1" for k in keys if k[0] == snap.root_league_id)
        assert len(keys) == 2
        # Same generation again: served from the cache, not recomputed.
        client.get("/api/league/player-impact?playerId=t")
        assert computed == ["gen-1", "gen-2"]
    finally:
        server._player_impact_cache.clear()
        server._player_impact_cache.update(saved)
