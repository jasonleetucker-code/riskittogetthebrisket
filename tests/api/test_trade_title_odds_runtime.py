"""``src/api/trade_title_odds_runtime.py`` — admit, bound, share, cache (DYN10 #4).

Transport rules of the async season-odds route, pinned without the app:

* a successful payload is cached under its key for the TTL, then recomputed;
  the cache is bounded (least recently used evicted) and hands out copies;
* the key needs a user, a league, a board generation and a trade signature —
  no user (or no stamp) means computed alone and never cached;
* a refusal, an exception, a busy answer, a timeout or a key that cannot be
  proven is never cached;
* identical concurrent requests share one computation;
* the admission bound (``src/api/compute_admission.py``): N computations at
  once, the N+1th distinct trade is answered busy without starting; a joiner
  takes no slot; the slot is released when the computation finishes, and only
  then — a timed-out caller does not free it;
* past the deadline the request answers the timeout envelope at once, the
  computation keeps running, and its result is cached when it finishes; a
  request that arrives meanwhile joins it; a leader whose caller goes away does
  not take the computation with it.
"""

from __future__ import annotations

import asyncio
import threading

import pytest

from src.api import compute_admission as ca
from src.api import trade_title_odds_runtime as rt

OK = {"state": "ok", "teams": [{"ownerId": "o1"}]}
REFUSED = {"state": "unavailable", "reason": "no_remaining_schedule", "teams": []}


def _timeout():
    return {"state": "unavailable", "reason": "title_odds_timeout", "teams": []}


def _error():
    return {"state": "unavailable", "reason": "title_odds_error", "teams": []}


def _busy():
    return {"state": "unavailable", "reason": "title_odds_busy", "teams": []}


_ENVELOPES = {"timeout_payload": _timeout, "error_payload": _error, "busy_payload": _busy}


def _admission(max_concurrent=2, timeout=5.0):
    spec = ca.AdmissionSpec(max_concurrent=max_concurrent, timeout_seconds=timeout)
    return ca.ComputeAdmission(ca.ROUTE_TRADE_TITLE_ODDS, spec_provider=lambda: spec)


def _runtime(max_concurrent=2, timeout=5.0, **kw):
    return rt.TitleOddsRuntime(admission=_admission(max_concurrent, timeout), **kw)


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _run(runtime, key, compute):
    return asyncio.run(runtime.run(key, compute, **_ENVELOPES))


def _counter(payload):
    calls = []

    def compute():
        calls.append(1)
        return payload

    return compute, calls


def test_cache_key_needs_every_part_including_the_user():
    parts = {"owner": "alice", "league_key": "l", "board_generation": "g", "trade_signature": "s"}
    assert rt.cache_key(**parts) == ("trade_title_odds", "alice", "l", "g", "s")
    # Two users asking the same question are two keys.
    assert rt.cache_key(**{**parts, "owner": "bob"}) != rt.cache_key(**parts)
    for missing in ("owner", "league_key", "board_generation", "trade_signature"):
        assert rt.cache_key(**{**parts, missing: None}) is None, missing
        assert rt.cache_key(**{**parts, missing: ""}) is None, missing


def test_the_default_admission_is_the_process_wide_title_odds_route():
    ca.reset_for_tests()
    runtime = rt.TitleOddsRuntime()
    assert runtime.admission is ca.admission_for(ca.ROUTE_TRADE_TITLE_ODDS)
    assert runtime.admission.route == ca.ROUTE_TRADE_TITLE_ODDS
    assert ca.spec_for(ca.ROUTE_TRADE_TITLE_ODDS) == ca.DEFAULTS[ca.ROUTE_TRADE_TITLE_ODDS]


def test_a_success_is_cached_for_the_ttl_then_recomputed():
    clock = _Clock()
    runtime = _runtime(ttl_seconds=60, clock=clock)
    compute, calls = _counter(OK)
    assert _run(runtime, ("k",), compute) == (OK, rt.SOURCE_COMPUTED)
    clock.now += 59
    assert _run(runtime, ("k",), compute) == (OK, rt.SOURCE_CACHE)
    clock.now += 1
    assert _run(runtime, ("k",), compute) == (OK, rt.SOURCE_COMPUTED)
    assert len(calls) == 2


def test_the_cache_hands_out_copies():
    runtime = _runtime()
    compute, _calls = _counter(OK)
    first, _ = _run(runtime, ("k",), compute)
    first["teams"].append("mutated")
    second, source = _run(runtime, ("k",), compute)
    assert source == rt.SOURCE_CACHE and second == OK


def test_the_cache_is_bounded_least_recently_used_first():
    runtime = _runtime(max_entries=2)
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
    runtime = _runtime()
    compute, calls = _counter(REFUSED)
    for _ in range(2):
        assert _run(runtime, key, compute) == (REFUSED, rt.SOURCE_COMPUTED)
    assert len(calls) == 2


def test_an_unprovable_key_is_never_cached():
    runtime = _runtime()
    compute, calls = _counter(OK)
    _run(runtime, None, compute)
    _run(runtime, None, compute)
    assert len(calls) == 2 and not runtime._cache


def test_an_exception_is_the_error_envelope_and_never_cached():
    runtime = _runtime()
    calls = []

    def boom():
        calls.append(1)
        raise RuntimeError("simulator moved")

    for _ in range(2):
        payload, _source = _run(runtime, ("k",), boom)
        assert payload["state"] == "unavailable" and payload["reason"] == "title_odds_error"
    assert len(calls) == 2 and not runtime._cache


def test_identical_concurrent_requests_share_one_computation():
    runtime = _runtime()
    release = threading.Event()
    calls = []

    def compute():
        calls.append(1)
        assert release.wait(5)
        return OK

    async def scenario():
        first = asyncio.ensure_future(runtime.run(("k",), compute, **_ENVELOPES))
        await asyncio.sleep(0.05)
        second = asyncio.ensure_future(runtime.run(("k",), compute, **_ENVELOPES))
        await asyncio.sleep(0.05)
        release.set()
        return await first, await second

    (p1, s1), (p2, s2) = asyncio.run(scenario())
    assert len(calls) == 1
    assert p1 == p2 == OK
    assert {s1, s2} == {rt.SOURCE_COMPUTED, rt.SOURCE_JOINED}


def test_past_the_bound_it_answers_at_once_and_caches_the_late_result():
    runtime = _runtime(timeout=0.05)
    release = threading.Event()
    calls = []

    def compute():
        calls.append(1)
        assert release.wait(5)
        return OK

    async def scenario():
        timed_out = await runtime.run(("k",), compute, **_ENVELOPES)
        release.set()
        for _ in range(500):
            if runtime.cached(("k",)) is not None:
                break
            await asyncio.sleep(0.01)
        later = await runtime.run(("k",), compute, **_ENVELOPES)
        return timed_out, later

    (timed_out, s1), (later, s2) = asyncio.run(scenario())
    assert s1 == rt.SOURCE_TIMEOUT and timed_out["reason"] == "title_odds_timeout"
    assert timed_out["teams"] == []
    assert (later, s2) == (OK, rt.SOURCE_CACHE)
    assert len(calls) == 1


# ── the admission bound (src/api/compute_admission.py) ───────────────────


class _Gate:
    """A blocking computation per key: records the start, waits for release."""

    def __init__(self):
        self.started: list[str] = []
        self.release = threading.Event()

    def compute(self, name, payload=OK):
        def run():
            self.started.append(name)
            assert self.release.wait(5), "the test never released the computation"
            return payload

        return run


async def _until(predicate, tries=500):
    for _ in range(tries):
        if predicate():
            return True
        await asyncio.sleep(0.01)
    return False


def test_the_cap_holds_the_extra_distinct_trade_is_busy_and_never_started():
    runtime = _runtime(max_concurrent=2)
    gate = _Gate()

    async def scenario():
        first = asyncio.ensure_future(runtime.run(("a",), gate.compute("a"), **_ENVELOPES))
        second = asyncio.ensure_future(runtime.run(("b",), gate.compute("b"), **_ENVELOPES))
        assert await _until(lambda: len(gate.started) == 2)
        assert runtime.admission.active == 2
        # N + 1: a third DISTINCT trade is answered at once, never queued.
        busy = await asyncio.wait_for(
            runtime.run(("c",), gate.compute("c"), **_ENVELOPES), timeout=1.0
        )
        gate.release.set()
        return busy, await first, await second

    (busy, s3), (p1, s1), (p2, s2) = asyncio.run(scenario())
    assert s3 == rt.SOURCE_BUSY
    assert busy["state"] == "unavailable" and busy["reason"] == "title_odds_busy"
    assert busy["teams"] == []  # unavailable, never a zero
    assert gate.started == ["a", "b"]  # "c" was never started
    assert (p1, s1) == (OK, rt.SOURCE_COMPUTED) and (p2, s2) == (OK, rt.SOURCE_COMPUTED)
    # A busy answer is never cached: asked again with room, it computes.
    assert runtime.cached(("c",)) is None
    assert runtime.admission.active == 0
    compute, calls = _counter(OK)
    assert _run(runtime, ("c",), compute) == (OK, rt.SOURCE_COMPUTED) and calls == [1]


def test_a_joiner_takes_no_slot():
    runtime = _runtime(max_concurrent=1)
    gate = _Gate()

    async def scenario():
        leader = asyncio.ensure_future(runtime.run(("k",), gate.compute("k"), **_ENVELOPES))
        assert await _until(lambda: gate.started == ["k"])
        joiners = [
            asyncio.ensure_future(runtime.run(("k",), gate.compute("dup"), **_ENVELOPES))
            for _ in range(3)
        ]
        await asyncio.sleep(0.05)
        # Still one slot in use, by the leader alone ...
        assert runtime.admission.active == 1
        # ... and it is the only one: a distinct trade is busy.
        other = await runtime.run(("other",), gate.compute("other"), **_ENVELOPES)
        gate.release.set()
        return await leader, [await j for j in joiners], other

    (lp, ls), joined, (op, os_) = asyncio.run(scenario())
    assert gate.started == ["k"]
    assert (lp, ls) == (OK, rt.SOURCE_COMPUTED)
    assert joined == [(OK, rt.SOURCE_JOINED)] * 3
    assert os_ == rt.SOURCE_BUSY and op["reason"] == "title_odds_busy"
    assert runtime.admission.active == 0


def test_the_slot_is_released_after_completion_and_after_an_error():
    runtime = _runtime(max_concurrent=1)
    compute, _calls = _counter(OK)
    assert _run(runtime, ("a",), compute)[1] == rt.SOURCE_COMPUTED
    assert runtime.admission.active == 0

    def boom():
        raise RuntimeError("simulator moved")

    payload, _source = _run(runtime, ("b",), boom)
    assert payload["reason"] == "title_odds_error"
    assert runtime.admission.active == 0
    assert _run(runtime, ("c",), compute)[1] == rt.SOURCE_COMPUTED


def test_a_timed_out_caller_keeps_the_slot_until_the_computation_finishes():
    runtime = _runtime(max_concurrent=1, timeout=0.05)
    gate = _Gate()

    async def scenario():
        timed_out = await runtime.run(("a",), gate.compute("a"), **_ENVELOPES)
        # The caller was answered; the work was not abandoned and still holds
        # its slot, so the bound is on real work, not on waiting callers.
        assert runtime.admission.active == 1
        busy = await runtime.run(("b",), gate.compute("b"), **_ENVELOPES)
        gate.release.set()
        assert await _until(lambda: runtime.admission.active == 0)
        assert await _until(lambda: runtime.cached(("a",)) is not None)
        after = await runtime.run(("b",), gate.compute("b"), **_ENVELOPES)
        return timed_out, busy, after

    (tp, ts), (bp, bs), (ap, as_) = asyncio.run(scenario())
    assert ts == rt.SOURCE_TIMEOUT and tp["reason"] == "title_odds_timeout"
    assert bs == rt.SOURCE_BUSY and bp["reason"] == "title_odds_busy"
    assert (ap, as_) == (OK, rt.SOURCE_COMPUTED)
    assert gate.started == ["a", "b"]


def test_a_request_that_arrives_after_the_leader_timed_out_joins_the_computation():
    spec = {"now": ca.AdmissionSpec(max_concurrent=1, timeout_seconds=0.05)}
    adm = ca.ComputeAdmission(ca.ROUTE_TRADE_TITLE_ODDS, spec_provider=lambda: spec["now"])
    runtime = rt.TitleOddsRuntime(admission=adm)
    gate = _Gate()

    async def scenario():
        timed_out = await runtime.run(("k",), gate.compute("k"), **_ENVELOPES)
        # Same question while the first computation is still running: it
        # joins (no second simulation, no slot) instead of starting another.
        spec["now"] = ca.AdmissionSpec(max_concurrent=1, timeout_seconds=5.0)
        joiner = asyncio.ensure_future(runtime.run(("k",), gate.compute("dup"), **_ENVELOPES))
        await asyncio.sleep(0.05)
        assert runtime.admission.active == 1
        gate.release.set()
        return timed_out, await joiner

    (tp, ts), (jp, js) = asyncio.run(scenario())
    assert ts == rt.SOURCE_TIMEOUT and tp["reason"] == "title_odds_timeout"
    assert (jp, js) == (OK, rt.SOURCE_JOINED)
    assert gate.started == ["k"]


def test_a_cancelled_leader_does_not_take_the_computation_with_it():
    runtime = _runtime(max_concurrent=1)
    gate = _Gate()

    async def scenario():
        leader = asyncio.ensure_future(runtime.run(("k",), gate.compute("k"), **_ENVELOPES))
        assert await _until(lambda: gate.started == ["k"])
        joiner = asyncio.ensure_future(runtime.run(("k",), gate.compute("dup"), **_ENVELOPES))
        await asyncio.sleep(0.02)
        # The leader's caller goes away (client disconnected).
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        assert runtime.admission.active == 1  # the work still holds its slot
        gate.release.set()
        joined = await joiner
        assert await _until(lambda: runtime.admission.active == 0)
        return joined

    payload, source = asyncio.run(scenario())
    assert (payload, source) == (OK, rt.SOURCE_JOINED)
    assert gate.started == ["k"]
    # The finished result was cached for the next identical request.
    assert runtime.cached(("k",)) == OK


def test_a_finished_computation_is_reused_before_its_done_callback_runs():
    runtime = _runtime(max_concurrent=1)
    calls: list[int] = []

    async def scenario():
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        done.set_result(OK)  # finished; no done-callback ever ran for it
        runtime._inflight[(id(loop), ("k",))] = done

        def compute():
            calls.append(1)
            return OK

        return await runtime.run(("k",), compute, **_ENVELOPES)

    assert asyncio.run(scenario()) == (OK, rt.SOURCE_CACHE)
    assert calls == []


def test_a_finished_refusal_is_not_reused_and_is_recomputed():
    runtime = _runtime(max_concurrent=1)
    calls: list[int] = []

    async def scenario():
        loop = asyncio.get_running_loop()
        done = loop.create_future()
        done.set_result(REFUSED)
        runtime._inflight[(id(loop), ("k",))] = done

        def compute():
            calls.append(1)
            return OK

        return await runtime.run(("k",), compute, **_ENVELOPES)

    assert asyncio.run(scenario()) == (OK, rt.SOURCE_COMPUTED)
    assert calls == [1]
