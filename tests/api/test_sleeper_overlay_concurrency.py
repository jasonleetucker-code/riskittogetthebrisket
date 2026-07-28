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
