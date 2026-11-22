"""``src/api/trade_title_odds_runtime.py`` — bound, share, cache (DYN10 #4).

Transport rules of the async season-odds route, pinned without the app:

* a successful payload is cached under its key for the TTL, then recomputed;
  the cache is bounded (least recently used evicted) and hands out copies;
* a refusal, an exception, a timeout or a key that cannot be proven is never
  cached;
* identical concurrent requests share one computation;
* past the bound the request answers the timeout envelope at once, the
  computation keeps running, and its result is cached when it finishes.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.api import trade_title_odds_runtime as rt

OK = {"state": "ok", "teams": [{"ownerId": "o1"}]}
REFUSED = {"state": "unavailable", "reason": "no_remaining_schedule", "teams": []}


def _timeout():
    return {"state": "unavailable", "reason": "title_odds_timeout", "teams": []}


def _error():
    return {"state": "unavailable", "reason": "title_odds_error", "teams": []}


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _run(runtime, key, compute):
    return asyncio.run(runtime.run(key, compute, timeout_payload=_timeout, error_payload=_error))


def _counter(payload):
    calls = []

    def compute():
        calls.append(1)
        return payload

    return compute, calls


def test_cache_key_needs_every_part():
    assert rt.cache_key(league_key="l", board_generation="g", trade_signature="s") == (
        "trade_title_odds",
        "l",
        "g",
        "s",
    )
    for missing in ("league_key", "board_generation", "trade_signature"):
        parts = {"league_key": "l", "board_generation": "g", "trade_signature": "s"}
        parts[missing] = None
        assert rt.cache_key(**parts) is None, missing


def test_a_success_is_cached_for_the_ttl_then_recomputed():
    clock = _Clock()
    runtime = rt.TitleOddsRuntime(ttl_seconds=60, clock=clock)
    compute, calls = _counter(OK)
    assert _run(runtime, ("k",), compute) == (OK, rt.SOURCE_COMPUTED)
    clock.now += 59
    assert _run(runtime, ("k",), compute) == (OK, rt.SOURCE_CACHE)
    clock.now += 1
    assert _run(runtime, ("k",), compute) == (OK, rt.SOURCE_COMPUTED)
    assert len(calls) == 2


def test_the_cache_hands_out_copies():
    runtime = rt.TitleOddsRuntime()
    compute, _calls = _counter(OK)
    first, _ = _run(runtime, ("k",), compute)
    first["teams"].append("mutated")
    second, source = _run(runtime, ("k",), compute)
    assert source == rt.SOURCE_CACHE and second == OK


def test_the_cache_is_bounded_least_recently_used_first():
    runtime = rt.TitleOddsRuntime(max_entries=2)
    compute, calls = _counter(OK)
    _run(runtime, ("a",), compute)
    _run(runtime, ("b",), compute)
    _run(runtime, ("a",), compute)  # touch a: b is now the oldest
    _run(runtime, ("c",), compute)
    assert _run(runtime, ("a",), compute)[1] == rt.SOURCE_CACHE
    assert _run(runtime, ("b",), compute)[1] == rt.SOURCE_COMPUTED
    assert len(calls) == 4


@pytest.mark.parametrize("key", [("k",), None])
def test_a_refusal_is_never_cached(key):
    runtime = rt.TitleOddsRuntime()
    compute, calls = _counter(REFUSED)
    for _ in range(2):
        assert _run(runtime, key, compute) == (REFUSED, rt.SOURCE_COMPUTED)
    assert len(calls) == 2


def test_an_unprovable_key_is_never_cached():
    runtime = rt.TitleOddsRuntime()
    compute, calls = _counter(OK)
    _run(runtime, None, compute)
    _run(runtime, None, compute)
    assert len(calls) == 2 and not runtime._cache


def test_an_exception_is_the_error_envelope_and_never_cached():
    runtime = rt.TitleOddsRuntime()
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("simulator moved")

    for _ in range(2):
        payload, _source = _run(runtime, ("k",), boom)
        assert payload["state"] == "unavailable" and payload["reason"] == "title_odds_error"
    assert len(calls) == 2 and not runtime._cache


def test_identical_concurrent_requests_share_one_computation():
    runtime = rt.TitleOddsRuntime()
    release = threading.Event()
    calls = []

    def compute():
        calls.append(1)
        assert release.wait(5)
        return OK

    async def scenario():
        first = asyncio.ensure_future(
            runtime.run(("k",), compute, timeout_payload=_timeout, error_payload=_error)
        )
        await asyncio.sleep(0.05)
        second = asyncio.ensure_future(
            runtime.run(("k",), compute, timeout_payload=_timeout, error_payload=_error)
        )
        await asyncio.sleep(0.05)
        release.set()
        return await first, await second

    (p1, s1), (p2, s2) = asyncio.run(scenario())
    assert len(calls) == 1
    assert p1 == p2 == OK
    assert {s1, s2} == {rt.SOURCE_COMPUTED, rt.SOURCE_JOINED}


def test_past_the_bound_it_answers_at_once_and_caches_the_late_result():
    runtime = rt.TitleOddsRuntime(timeout_seconds=0.05)
    release = threading.Event()
    calls = []

    def compute():
        calls.append(1)
        assert release.wait(5)
        return OK

    async def scenario():
        timed_out = await runtime.run(
            ("k",), compute, timeout_payload=_timeout, error_payload=_error
        )
        release.set()
        for _ in range(500):
            if runtime.cached(("k",)) is not None:
                break
            await asyncio.sleep(0.01)
        later = await runtime.run(("k",), compute, timeout_payload=_timeout, error_payload=_error)
        return timed_out, later

    (timed_out, s1), (later, s2) = asyncio.run(scenario())
    assert s1 == rt.SOURCE_TIMEOUT and timed_out["reason"] == "title_odds_timeout"
    assert timed_out["teams"] == []
    assert (later, s2) == (OK, rt.SOURCE_CACHE)
    assert len(calls) == 1
