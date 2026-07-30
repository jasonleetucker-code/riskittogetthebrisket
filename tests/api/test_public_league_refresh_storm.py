"""A failing public-league rebuild must not amplify into a threadpool storm.

Backlog defect #1, "forced public-league rebuild makes the whole API
unresponsive", was carried as OPEN/unproven for several sessions. It is
real; this module pins the mechanism and the bound.

**The mechanism.** Every ``/api/public/league*`` handler resolves its
snapshot inside ``run_in_threadpool(_build)``, so a caller waiting on a
rebuild occupies an AnyIO worker token for the whole wait. Those tokens
come from the process-wide default limiter that *every* sync endpoint and
every other ``run_in_threadpool`` call in ``server.py`` draws on — so
enough waiters starve unrelated endpoints, ``/api/health`` included.

``_rebuild_public_snapshot`` holds ``_public_league_refresh_lock`` and
re-checks the cache after acquiring it, which its docstring describes as
stopping "a burst of requests ... [from multiplying] work". On the
success path it does: measured 8 concurrent force-refreshes against a
0.5s builder produced **1** upstream call.

**Where it fails.** ``fetched_at`` is only advanced *after* a successful
build, so when the upstream errors the post-lock re-check can never be
satisfied and every waiter re-attempts in turn. The same 8 callers
against a failing 0.5s builder produced **8 serial upstream attempts**,
4.01s wall and 18.02 thread-seconds for 0.5s of nominal work — and it
grows with N, without limit.

That is the worst possible time for it: the burst happens precisely when
the vendor is down and users are mashing refresh.

This is the same hazard the ``playoffOdds`` single-flight cache was built
for a few hundred lines up ("Offloaded naively, a burst of concurrent
requests would each launch an independent simulation and saturate the
shared threadpool"). The snapshot rebuild simply never got the
equivalent treatment.

Both tests below fail against the pre-fix server: the first on the
attempt count, the second on thread occupancy.
"""

from __future__ import annotations

import threading
import time

import pytest

import server


REBUILD_SECONDS = 0.4
CALLERS = 8


@pytest.fixture
def cold_cache(monkeypatch):
    """A cold snapshot cache pinned to a synthetic league.

    Restores the real cache contents afterwards — ``_public_league_cache``
    is a module-level global shared with every other test in the run.
    """
    saved = dict(server._public_league_cache)
    saved_metrics = dict(server._public_league_metrics)
    monkeypatch.setattr(
        server._league_registry,
        "get_sleeper_league_id",
        lambda *a, **k: "STORMTEST",
    )
    server._public_league_cache.update(
        {
            "snapshot": None,
            "snapshot_league_id": None,
            "fetched_at": 0.0,
            "refreshing": False,
            "last_failure_at": 0.0,
            "last_failure_error": None,
        }
    )
    yield
    server._public_league_cache.clear()
    server._public_league_cache.update(saved)
    server._public_league_metrics.clear()
    server._public_league_metrics.update(saved_metrics)


def _storm(builder, monkeypatch, *, callers: int = CALLERS):
    """Fire ``callers`` concurrent force-refreshes; return occupancy stats."""
    monkeypatch.setattr(server, "build_public_snapshot", builder)
    occupancy: list[float] = []
    occ_lock = threading.Lock()

    def caller():
        t0 = time.time()
        try:
            server._get_public_snapshot(force_refresh=True)
        except Exception:  # noqa: BLE001 — a 503 is a fine outcome here
            pass
        with occ_lock:
            occupancy.append(time.time() - t0)

    threads = [threading.Thread(target=caller) for _ in range(callers)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return {
        "wall": time.time() - t0,
        "occupancy": occupancy,
        "thread_seconds": sum(occupancy),
        "max_occupancy": max(occupancy) if occupancy else 0.0,
    }


def test_a_failing_upstream_is_attempted_once_not_once_per_caller(cold_cache, monkeypatch):
    """THE GUARD, shown firing.

    Pre-fix this records ``callers`` attempts. The cooldown collapses it
    to one: the first caller learns the upstream is down and every
    subsequent caller is told so from memory rather than by asking again.
    """
    attempts: list[float] = []
    a_lock = threading.Lock()

    def failing_builder(league_id, max_seasons=None):
        with a_lock:
            attempts.append(time.time())
        time.sleep(REBUILD_SECONDS)
        raise RuntimeError("sleeper 503")

    _storm(failing_builder, monkeypatch)

    assert len(attempts) == 1, (
        f"{len(attempts)} upstream attempts for {CALLERS} concurrent callers. "
        "Each one occupies a shared AnyIO worker for the full retry chain, so "
        "this scales the outage into the rest of the API."
    )


def test_waiters_do_not_hold_worker_tokens_for_the_whole_retry_chain(cold_cache, monkeypatch):
    """The bound that makes the API stay up.

    Nobody should wait longer than roughly one rebuild. Pre-fix the last
    caller waits ``CALLERS x REBUILD_SECONDS`` because the retries are
    serialised behind the lock.
    """

    def failing_builder(league_id, max_seasons=None):
        time.sleep(REBUILD_SECONDS)
        raise RuntimeError("sleeper 503")

    stats = _storm(failing_builder, monkeypatch)

    ceiling = REBUILD_SECONDS * 3
    assert stats["max_occupancy"] < ceiling, (
        f"a caller held a worker token for {stats['max_occupancy']:.2f}s "
        f"(ceiling {ceiling:.2f}s, one rebuild is {REBUILD_SECONDS}s). "
        f"Total {stats['thread_seconds']:.2f} thread-seconds across "
        f"{CALLERS} callers."
    )


def test_the_cooldown_expires_so_the_outage_is_not_sticky(cold_cache, monkeypatch):
    """Non-vacuity, and the reason the cooldown is short.

    A cooldown with no expiry would turn one vendor blip into a
    permanently dead endpoint — the failure mode ORCHESTRATION.md 6.15
    keeps catching. Once it lapses, a recovered upstream must be reached
    on the very next call.
    """
    monkeypatch.setattr(server, "_PUBLIC_LEAGUE_FAILURE_COOLDOWN_SECONDS", 0.2)

    def failing_builder(league_id, max_seasons=None):
        raise RuntimeError("sleeper 503")

    monkeypatch.setattr(server, "build_public_snapshot", failing_builder)
    with pytest.raises(Exception):
        server._get_public_snapshot(force_refresh=True)

    # Still inside the cooldown: served from memory, upstream untouched.
    def exploding_builder(league_id, max_seasons=None):
        raise AssertionError("upstream must not be called during cooldown")

    monkeypatch.setattr(server, "build_public_snapshot", exploding_builder)
    with pytest.raises(Exception) as caught:
        server._get_public_snapshot(force_refresh=True)
    assert not isinstance(caught.value, AssertionError)

    time.sleep(0.25)

    # Cooldown lapsed — a recovered upstream is reached immediately.
    reached = []

    def recovered_builder(league_id, max_seasons=None):
        reached.append(1)

        class _Snap:
            # Non-empty: a zero-season rebuild is now treated as a
            # FAILURE by _rebuild_public_snapshot (see
            # tests/api/test_public_league_empty_snapshot.py — an empty
            # snapshot was served to production as HTTP 200 with every
            # health signal green). These two tests are about
            # single-flight and cooldown behaviour, so their stub just
            # has to be a VALID snapshot.
            seasons: list = ["2026"]
            root_league_id = "STORMTEST"
            generated_at = "2026-07-28T00:00:00Z"

            class managers:
                by_owner_id: dict = {}

        return _Snap()

    monkeypatch.setattr(server, "build_public_snapshot", recovered_builder)
    server._get_public_snapshot(force_refresh=True)
    assert reached == [1], "cooldown did not expire; a blip became a permanent outage"


def test_a_healthy_upstream_still_rebuilds_exactly_once(cold_cache, monkeypatch):
    """The control.

    Without this, every assertion above would pass against a server that
    had simply stopped refreshing.
    """
    calls: list[float] = []
    c_lock = threading.Lock()

    def slow_builder(league_id, max_seasons=None):
        with c_lock:
            calls.append(time.time())
        time.sleep(REBUILD_SECONDS)

        class _Snap:
            # Non-empty: a zero-season rebuild is now treated as a
            # FAILURE by _rebuild_public_snapshot (see
            # tests/api/test_public_league_empty_snapshot.py — an empty
            # snapshot was served to production as HTTP 200 with every
            # health signal green). These two tests are about
            # single-flight and cooldown behaviour, so their stub just
            # has to be a VALID snapshot.
            seasons: list = ["2026"]
            root_league_id = "STORMTEST"
            generated_at = "2026-07-28T00:00:00Z"

            class managers:
                by_owner_id: dict = {}

        return _Snap()

    _storm(slow_builder, monkeypatch)

    assert len(calls) == 1, f"expected single-flight, got {len(calls)} rebuilds"
    assert server._public_league_cache["snapshot"] is not None, (
        "the healthy path must still populate the cache"
    )
