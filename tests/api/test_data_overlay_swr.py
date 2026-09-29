"""Stale-while-revalidate for the encoded ``/api/data`` overlay response.

Production 2026-09-28 (#1338): every 15-min Sleeper overlay refresh mints a
new ``overlayFetchedAt``, and the next ``/api/data`` request re-ran the
lineup solve + multi-MB JSON encode + gzip on the request path -- the ~1-2 s
warm outliers on Rankings/Trade.

Pinned: when ONLY the overlay observation changed and the previous one is
still inside the overlay owner's own stale-serve window, the previous encoded
generation is served and one background task re-encodes; anything else (new
board, new canonical rows, new roster rules, an observation past the window)
still encodes on the request exactly as before.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import time

import httpx
import pytest

import server
from src.api import sleeper_overlay
from tests.api.test_data_overlay_preparation import overlay_case  # noqa: F401
from tests.api.test_league_routing import shared_scoring_registry  # noqa: F401

NOW = dt.datetime.now(dt.timezone.utc)


def _iso(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def _stamp(seconds_ago: float) -> str:
    # Relative to the LIVE clock the server reads, never a collection-time
    # constant: a long suite must not age a fixture past the window.
    return _iso(time.time() - seconds_ago)


def _fixed(seconds_ago: float) -> str:
    return _iso(NOW.timestamp() - seconds_ago)


def _starters(response):
    assert response.status_code == 200
    return response.json()["sleeper"]["teams"][0]["optimalLineup"]["starters"]


def _served_players(response):
    return response.json()["sleeper"]["teams"][0]["players"]


def _run(steps):
    """Drive the real app on one event loop; ``steps(get, drain)``."""

    async def main():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://fixture"
        ) as client:

            async def get(headers=None):
                return await client.get("/api/data?leagueKey=main", headers=headers or {})

            async def drain():
                while server._OVERLAY_REFRESH_TASKS:
                    await asyncio.gather(*list(server._OVERLAY_REFRESH_TASKS))
                    # A finished task leaves the set in its done-callback;
                    # awaiting an already-done gather never yields, so let
                    # the loop run that callback.
                    await asyncio.sleep(0)

            return await steps(get, drain)

    return asyncio.run(main())


@pytest.fixture
def swr_case(overlay_case, monkeypatch):  # noqa: F811
    contract, settings, overlay = overlay_case
    overlay["overlayFetchedAt"] = _stamp(20 * 60)
    monkeypatch.setattr(server, "_OVERLAY_REFRESHING", set())
    monkeypatch.setattr(server, "_OVERLAY_REFRESH_TASKS", set())
    calls = []
    real = server._stamp_optimal_lineups_owner

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(server, "_stamp_optimal_lineups_owner", counted)

    def refresh_overlay(players, seconds_ago=0.0):
        # The overlay owner publishes a NEW dict per observation.
        overlay["teams"] = [{"ownerId": "fixture", "players": list(players)}]
        overlay["overlayFetchedAt"] = _stamp(seconds_ago)

    return contract, settings, refresh_overlay, calls


def test_a_new_observation_serves_the_previous_encoding_then_the_new_one(swr_case):
    _, _, refresh_overlay, calls = swr_case

    async def steps(get, drain):
        first = await get()
        refresh_overlay(["wr"])  # roster move: the RB left
        stale = await get()
        await drain()
        fresh = await get()
        revalidated = await get({"If-None-Match": fresh.headers["etag"]})
        return first, stale, fresh, revalidated

    first, stale, fresh, revalidated = _run(steps)
    # Served immediately from the previous generation, labelled as such.
    assert stale.content == first.content
    assert stale.headers["etag"] == first.headers["etag"]
    assert stale.headers["x-overlay-encode"] == "stale-while-revalidate"
    # Superseded bytes are never handed a browser freshness lifetime.
    assert stale.headers["cache-control"] == "private, no-cache"
    assert "no-cache" not in first.headers["cache-control"]
    assert "no-cache" not in fresh.headers["cache-control"]
    assert _served_players(stale) == ["rb", "wr"]
    # The background encode published the new observation, solved once.
    assert _served_players(fresh) == ["wr"]
    assert _starters(fresh) == ["wr"]
    assert "x-overlay-encode" not in fresh.headers
    assert fresh.headers["etag"] != first.headers["etag"]
    assert revalidated.status_code == 304
    assert len(calls) == 2


def test_an_observation_past_the_owner_window_encodes_on_the_request(swr_case):
    _, _, refresh_overlay, calls = swr_case

    async def steps(get, drain):
        # The cached generation's observation is 31 min old: past the
        # overlay owner's 30-min stale-serve ceiling.
        refresh_overlay(["rb", "wr"], seconds_ago=31 * 60)
        first = await get()
        refresh_overlay(["wr"])
        second = await get()
        return first, second

    first, second = _run(steps)
    assert _served_players(second) == ["wr"]
    assert "x-overlay-encode" not in second.headers
    assert not server._OVERLAY_REFRESH_TASKS
    assert len(calls) == 2


@pytest.mark.parametrize("change", ["board", "roster_rules"])
def test_anything_beyond_the_observation_encodes_on_the_request(swr_case, monkeypatch, change):
    _, settings, refresh_overlay, calls = swr_case

    async def steps(get, drain):
        first = await get()
        refresh_overlay(["rb", "wr"])
        if change == "board":
            monkeypatch.setattr(server, "latest_data_etag", "canonical-B")
        else:
            settings["flexEligible"] = ["WR"]
        second = await get()
        return first, second

    first, second = _run(steps)
    assert "x-overlay-encode" not in second.headers
    assert not server._OVERLAY_REFRESH_TASKS
    assert second.headers["etag"] != first.headers["etag"]
    if change == "roster_rules":
        assert _starters(second) == ["wr"]
    assert len(calls) == 2


def test_a_burst_during_revalidation_starts_one_background_encode(swr_case):
    _, _, refresh_overlay, calls = swr_case

    async def steps(get, drain):
        first = await get()
        refresh_overlay(["wr"])
        burst = await asyncio.gather(*[get() for _ in range(6)])
        await drain()
        after = await get()
        return first, burst, after

    first, burst, after = _run(steps)
    # Each burst request gets the previous generation or -- once the one
    # background encode has landed -- the new one; never a third encode.
    assert {r.headers["etag"] for r in burst} <= {first.headers["etag"], after.headers["etag"]}
    assert burst[0].headers["etag"] == first.headers["etag"]
    assert _served_players(after) == ["wr"]
    assert len(calls) == 2


def test_a_failed_background_encode_keeps_the_previous_generation(swr_case, monkeypatch):
    _, _, refresh_overlay, calls = swr_case
    real_compress = server.gzip.compress
    failures = {"left": 1}

    def flaky(data, *a, **k):
        if failures["left"]:
            failures["left"] -= 1
            raise MemoryError("fixture")
        return real_compress(data, *a, **k)

    async def steps(get, drain):
        first = await get()
        monkeypatch.setattr(server.gzip, "compress", flaky)
        refresh_overlay(["wr"])
        stale = await get()
        await drain()  # fails, logged, never raised
        retry = await get()  # still the previous generation; kicks a retry
        await drain()
        fresh = await get()
        return first, stale, retry, fresh

    first, stale, retry, fresh = _run(steps)
    assert stale.content == first.content == retry.content
    assert retry.headers["x-overlay-encode"] == "stale-while-revalidate"
    assert _served_players(fresh) == ["wr"]


@pytest.mark.parametrize(
    ("stamp", "servable"),
    [
        (None, False),
        ("", False),
        ("fixed-observation", False),
        ("2026-09-28T12:00:00", False),  # no zone: unknown age
        (_fixed(-60), False),  # future
        (_fixed(29 * 60), True),
        (_fixed(31 * 60), False),
    ],
)
def test_observation_servability_follows_the_owner_window(stamp, servable):
    assert sleeper_overlay.overlay_observation_servable(stamp, now=NOW.timestamp()) is servable


def test_a_background_encode_never_overwrites_a_newer_generation(monkeypatch):
    """A board publish lands between the stale serve and the background
    encode: the request-path encode of the NEW board wins the lock first,
    and the older-board background result must not replace it."""
    monkeypatch.setattr(server, "_OVERLAY_RESPONSE_CACHE", {})
    monkeypatch.setattr(server, "_OVERLAY_ENCODE_LOCKS", {})
    monkeypatch.setattr(server, "_OVERLAY_REFRESHING", set())
    monkeypatch.setattr(server, "_OVERLAY_REFRESH_TASKS", set())

    class _Req:
        headers = {}

    key = ("overlay", "main", "", "compact", True)
    v1 = (_stamp(60), "board-1", "canon-1", "ctx")
    v2 = (_stamp(0), "board-1", "canon-1", "ctx")  # new observation, old board
    v3 = (_stamp(0), "board-2", "canon-2", "ctx")  # new board

    def servable(old):
        return old[1:] == v2[1:]

    async def run():
        ser = server._serialize_overlaid_response
        await ser(_Req(), {"g": 1}, {}, key, v1)
        stale = await ser(_Req(), {"g": 2}, {}, key, v2, stale_servable=servable)
        assert server._OVERLAY_REFRESH_TASKS  # kicked, not yet run
        await ser(_Req(), {"g": 3}, {}, key, v3)  # takes the lock first
        while server._OVERLAY_REFRESH_TASKS:
            await asyncio.gather(*list(server._OVERLAY_REFRESH_TASKS))
            await asyncio.sleep(0)
        return stale

    stale = asyncio.run(run())
    assert stale.headers["X-Overlay-Encode"] == "stale-while-revalidate"
    assert server._OVERLAY_RESPONSE_CACHE[key][3] == v3
    assert not server._OVERLAY_REFRESHING


def test_an_unchanged_overlay_keeps_its_bytes_and_etag(swr_case):
    """A refresh that changes nothing but the per-fetch stamps must not mint
    a new generation: clients revalidate to a 304 instead of re-downloading
    the whole board (the warm Rankings/Trade outlier, production 2026-09-29)."""
    _, _, refresh_overlay, calls = swr_case

    async def steps(get, drain):
        first = await get()
        refresh_overlay(["rb", "wr"])  # same rosters, new fetch stamp
        again = await get()
        revalidated = await get({"If-None-Match": first.headers["etag"]})
        return first, again, revalidated

    first, again, revalidated = _run(steps)
    assert again.content == first.content
    assert again.headers["etag"] == first.headers["etag"]
    assert "x-overlay-encode" not in again.headers  # a plain hit, not a stale serve
    assert revalidated.status_code == 304
    assert len(calls) == 1


def test_the_stale_bound_measures_from_the_last_confirmation(swr_case):
    """Content first observed 40 min ago but CONFIRMED a minute ago is still
    inside the owner's window when it is superseded; the bound follows the
    confirmation, not the first sighting."""
    _, _, refresh_overlay, calls = swr_case

    async def steps(get, drain):
        refresh_overlay(["rb", "wr"], seconds_ago=40 * 60)
        first = await get()
        refresh_overlay(["rb", "wr"], seconds_ago=60)  # re-confirmed, unchanged
        await get()
        refresh_overlay(["wr"])  # now it changes
        stale = await get()
        await drain()
        fresh = await get()
        return first, stale, fresh

    first, stale, fresh = _run(steps)
    assert stale.content == first.content
    assert stale.headers["x-overlay-encode"] == "stale-while-revalidate"
    assert _served_players(fresh) == ["wr"]
    assert len(calls) == 2
