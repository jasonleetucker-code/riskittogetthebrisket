"""Concurrency + staleness tests for the Sleeper overlay cache.

A cold overlay build is ~50-100 Sleeper round-trips.  Before the
single-flight/stale-serve work, every request after the 15-min TTL
expiry paid that storm inline (~8-12s), and N concurrent expirees each
launched their own.  Pinned here:

    1. Concurrent cold fetches coalesce onto ONE build (single-flight).
    2. Within one build, a URL is fetched at most once (build memo) —
       the trades and waivers builders share the weekly feeds.
    3. A stale entry (15-30 min) is served immediately while exactly
       one background refresh runs.
    4. A stale entry past the 30-min ceiling blocks and rebuilds.
    5. Output parity: the memoized/prefetched build returns the same
       trades/waivers the sequential builders produce.
"""

from __future__ import annotations

import threading
import time

from src.api import sleeper_overlay

_FIXED_TS = int(time.time() * 1000)

LEAGUE = "L100"


def _fake_sleeper(calls):
    """Minimal but complete fake Sleeper API.  Records every URL."""

    def fake(url: str):
        calls.append(url)
        if url.endswith("/rosters"):
            return [
                {"roster_id": 1, "owner_id": "u1", "players": ["1111"]},
                {"roster_id": 2, "owner_id": "u2", "players": ["2222"]},
            ]
        if url.endswith("/users"):
            return [
                {"user_id": "u1", "display_name": "Alpha"},
                {"user_id": "u2", "display_name": "Beta"},
            ]
        if url.endswith("/traded_picks"):
            return []
        if url.endswith("/drafts"):
            return []
        if "/transactions/" in url:
            week = int(url.rsplit("/", 1)[1])
            if week == 3:
                return [
                    {
                        "type": "trade",
                        "status": "complete",
                        "status_updated": _FIXED_TS,
                        "transaction_id": "t1",
                        "roster_ids": [1, 2],
                        "adds": {"1111": 2, "2222": 1},
                        "drops": {"1111": 1, "2222": 2},
                        "draft_picks": [],
                    },
                    {
                        "type": "waiver",
                        "status": "complete",
                        "status_updated": _FIXED_TS,
                        "transaction_id": "w1",
                        "roster_ids": [1],
                        "adds": {"3333": 1},
                        "drops": {},
                        "settings": {"waiver_bid": 7},
                    },
                ]
            return []
        # League meta (no previous league → chain depth 1).
        return {"name": "Fake League", "settings": {"waiver_budget": 100}}

    return fake


def _reset():
    sleeper_overlay.invalidate_overlay_cache()
    with sleeper_overlay._CACHE_LOCK:
        sleeper_overlay._BUILD_LOCKS.clear()
        sleeper_overlay._REFRESHING.clear()


def test_concurrent_cold_fetches_single_flight(monkeypatch):
    _reset()
    calls: list[str] = []
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _fake_sleeper(calls))

    results = [None] * 6
    threads = [
        threading.Thread(
            target=lambda i=i: results.__setitem__(
                i,
                sleeper_overlay.fetch_sleeper_overlay(
                    sleeper_league_id=LEAGUE, id_to_player={"1111": "P One"}
                ),
            )
        )
        for i in range(6)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert all(r is not None for r in results)
    assert all(r["leagueId"] == LEAGUE for r in results)
    # Single-flight + per-build memo: each unique URL fetched exactly
    # once across ALL six concurrent requests.
    rosters_calls = [u for u in calls if u.endswith("/rosters")]
    week3_calls = [u for u in calls if u.endswith("/transactions/3")]
    assert len(rosters_calls) == 1, calls
    assert len(week3_calls) == 1, calls


def test_stale_entry_served_instantly_with_one_background_refresh(monkeypatch):
    _reset()
    calls: list[str] = []
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _fake_sleeper(calls))

    stale_payload = {"leagueId": LEAGUE, "leagueName": "Stale", "teams": [{"name": "Old"}]}
    with sleeper_overlay._CACHE_LOCK:
        sleeper_overlay._CACHE[LEAGUE] = {
            "payload": dict(stale_payload),
            "_cached_at": time.time() - (16 * 60),  # 16 min: stale, within ceiling
        }

    got = sleeper_overlay.fetch_sleeper_overlay(sleeper_league_id=LEAGUE)
    assert got["leagueName"] == "Stale", "stale entry must be served immediately"

    # Second stale hit while refresh may be in flight must not stack a
    # second refresher (the _REFRESHING guard) and still serves data.
    got2 = sleeper_overlay.fetch_sleeper_overlay(sleeper_league_id=LEAGUE)
    assert got2 is not None

    # Wait for the background refresh to land.
    deadline = time.time() + 15
    while time.time() < deadline:
        with sleeper_overlay._CACHE_LOCK:
            entry = sleeper_overlay._CACHE.get(LEAGUE)
            refreshing = LEAGUE in sleeper_overlay._REFRESHING
        if entry and entry["payload"].get("leagueName") == "Fake League" and not refreshing:
            break
        time.sleep(0.05)
    else:
        raise AssertionError("background refresh never replaced the stale entry")


def test_stale_past_ceiling_blocks_and_rebuilds(monkeypatch):
    _reset()
    calls: list[str] = []
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _fake_sleeper(calls))

    with sleeper_overlay._CACHE_LOCK:
        sleeper_overlay._CACHE[LEAGUE] = {
            "payload": {"leagueId": LEAGUE, "leagueName": "Ancient", "teams": []},
            "_cached_at": time.time() - (31 * 60),  # past the 30-min ceiling
        }

    got = sleeper_overlay.fetch_sleeper_overlay(sleeper_league_id=LEAGUE)
    assert got["leagueName"] == "Fake League", "past the ceiling the build must block"


def test_memoized_build_matches_sequential_builders(monkeypatch):
    _reset()
    calls: list[str] = []
    fake = _fake_sleeper(calls)
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", fake)

    id_map = {"1111": "P One", "2222": "P Two", "3333": "P Three"}
    seq_trades = sleeper_overlay._build_trades_block(LEAGUE, id_to_player=id_map)
    seq_waivers = sleeper_overlay._build_waivers_block(LEAGUE, id_to_player=id_map)

    overlay = sleeper_overlay.fetch_sleeper_overlay(
        sleeper_league_id=LEAGUE, id_to_player=id_map, force_refresh=True
    )
    assert overlay["trades"] == seq_trades
    assert overlay["waivers"] == seq_waivers
    assert overlay["meta"]["tradeCount"] == 1
    assert overlay["meta"]["waiverCount"] == 1


# ── Request-path budget (max_wait_sec) ────────────────────────────────
#
# The boot warm calls fetch_sleeper_overlay(force_refresh=True), which
# skips the cache read entirely and holds the per-league build lock for
# the whole ~47-70-URL build. Before the budget, an /api/data request
# landing in that window blocked for the REMAINDER of that build.
#
# That is not a slow page, it is a broken one: the Next bridge in front
# of /api/data aborts on a 4s idle timeout and falls back to an on-disk
# snapshot, which carries no rank stamps, which makes buildRows
# fail-fast. Blocking on a decorative overlay produced an empty board.


def test_request_budget_returns_none_rather_than_blocking(monkeypatch):
    """A caller with a budget gives up instead of waiting for the build."""
    _reset()
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _fake_sleeper([]))

    lock = sleeper_overlay._overlay_build_lock(LEAGUE)
    lock.acquire()  # stand in for the boot warm holding it
    try:
        t0 = time.time()
        got = sleeper_overlay.fetch_sleeper_overlay(
            sleeper_league_id=LEAGUE,
            id_to_player={},
            max_wait_sec=0.25,
        )
        elapsed = time.time() - t0
    finally:
        lock.release()

    # No cache entry exists, so there is nothing to fall back to.
    assert got is None
    # The budget is what bounds it. Generous upper bound so this cannot
    # flake on a loaded runner while still failing an unbounded wait,
    # which would hang until the test timeout.
    assert elapsed < 5.0, f"waited {elapsed:.2f}s despite a 0.25s budget"


def test_request_budget_prefers_stale_payload_over_waiting(monkeypatch):
    """With a cached payload, a blocked caller gets stale rather than None.

    Freshness is the only thing given up; the board still renders with
    live Sleeper data from the previous build.
    """
    _reset()
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _fake_sleeper([]))

    # Populate the cache with a real build first.
    warm = sleeper_overlay.fetch_sleeper_overlay(
        sleeper_league_id=LEAGUE, id_to_player={"1111": "P One"}
    )
    assert warm and warm.get("teams")

    # Age it past the TTL so the fast path cannot serve it, then hold the
    # build lock as the warm would.
    with sleeper_overlay._CACHE_LOCK:
        sleeper_overlay._CACHE[LEAGUE]["_cached_at"] = (
            time.time() - sleeper_overlay._STALE_SERVE_MAX_SEC - 1
        )
    lock = sleeper_overlay._overlay_build_lock(LEAGUE)
    lock.acquire()
    try:
        t0 = time.time()
        got = sleeper_overlay.fetch_sleeper_overlay(
            sleeper_league_id=LEAGUE,
            id_to_player={},
            max_wait_sec=0.25,
        )
        elapsed = time.time() - t0
    finally:
        lock.release()

    assert got is not None, "should serve the stale payload rather than nothing"
    assert got["leagueId"] == LEAGUE
    assert elapsed < 5.0, f"waited {elapsed:.2f}s despite a 0.25s budget"


def test_warm_path_keeps_its_unbounded_wait(monkeypatch):
    """No budget => the old behaviour, which the warm and scrapes rely on.

    Guards against 'fixing' this by making every caller give up: a warm
    that skipped its build would leave the cache cold forever.
    """
    _reset()
    calls: list[str] = []
    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _fake_sleeper(calls))

    got = sleeper_overlay.fetch_sleeper_overlay(
        sleeper_league_id=LEAGUE, id_to_player={"1111": "P One"}, force_refresh=True
    )
    assert got and got.get("teams"), "unbudgeted caller must still build"
    assert any(u.endswith("/rosters") for u in calls), calls
