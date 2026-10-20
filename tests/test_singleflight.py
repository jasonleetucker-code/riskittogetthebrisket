"""Single-flight has no permanent lock/result registry and permits retry."""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.utils.singleflight import SingleFlight


def test_completed_and_failed_keys_are_released():
    flights = SingleFlight()
    for key in range(100):
        assert flights.run(key, lambda: 1) == (1, False)
    assert not flights._pending

    def fail():
        raise RuntimeError("build failed")

    with pytest.raises(RuntimeError, match="build failed"):
        flights.run("failed", fail)
    assert not flights._pending
    assert flights.run("failed", lambda: 2) == (2, False)


def test_distinct_keys_do_not_serialize():
    flights = SingleFlight()
    building = threading.Barrier(2)

    def run(key):
        return flights.run(key, lambda: building.wait(timeout=5))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["first", "second"]))
    assert sorted(result for result, _ in results) == [0, 1]
    assert all(not shared for _, shared in results)


def test_run_sharing_success_shares_a_success_but_never_a_failure():
    import threading

    from src.utils.singleflight import SingleFlight

    flight = SingleFlight()
    gate = threading.Event()
    calls: list[str] = []

    def leader_fails():
        calls.append("leader")
        gate.wait(5)
        return {}  # failure sentinel

    def follower_build():
        calls.append("follower")
        return {"ok": 1}

    out: dict = {}
    t = threading.Thread(
        target=lambda: out.setdefault(
            "leader", flight.run_sharing_success("k", leader_fails, failed=lambda r: not r)
        )
    )
    t.start()
    while not calls:
        threading.Event().wait(0.01)
    f = threading.Thread(
        target=lambda: out.setdefault(
            "follower", flight.run_sharing_success("k", follower_build, failed=lambda r: not r)
        )
    )
    f.start()
    threading.Event().wait(0.2)
    gate.set()
    t.join(5)
    f.join(5)
    assert out["leader"] == ({}, False)
    assert out["follower"] == ({"ok": 1}, False)  # its own attempt, not the failure
    assert calls == ["leader", "follower"]


def test_run_sharing_success_follower_retries_after_a_leader_exception():
    import threading

    from src.utils.singleflight import SingleFlight

    flight = SingleFlight()
    gate = threading.Event()
    started = threading.Event()

    def boom():
        started.set()
        gate.wait(5)
        raise RuntimeError("transient")

    out: dict = {}

    def lead():
        try:
            flight.run_sharing_success("k", boom)
        except RuntimeError:
            out["leader"] = "raised"

    t = threading.Thread(target=lead)
    t.start()
    started.wait(5)
    f = threading.Thread(
        target=lambda: out.setdefault(
            "follower", flight.run_sharing_success("k", lambda: "ok", retry=lambda: "retried")
        )
    )
    f.start()
    threading.Event().wait(0.2)
    gate.set()
    t.join(5)
    f.join(5)
    assert out == {"leader": "raised", "follower": ("retried", False)}


def _storm(flight, *, retry_fails: bool):
    import threading

    gate = threading.Event()
    builds: list[str] = []
    lock = threading.Lock()

    def leader():
        with lock:
            builds.append("leader")
        gate.wait(5)
        return {}  # failure sentinel

    def attempt():
        with lock:
            builds.append("retry")
        threading.Event().wait(0.05)
        return {} if retry_fails else {"ok": 1}

    out: list = []
    first = threading.Thread(
        target=lambda: out.append(flight.run_sharing_success("k", leader, failed=lambda r: not r))
    )
    first.start()
    while not builds:
        threading.Event().wait(0.01)
    followers = [
        threading.Thread(
            target=lambda: out.append(
                flight.run_sharing_success("k", attempt, failed=lambda r: not r)
            )
        )
        for _ in range(11)
    ]
    for t in followers:
        t.start()
    threading.Event().wait(0.2)
    gate.set()
    for t in [first, *followers]:
        t.join(10)
    return builds, out


def test_a_failed_leader_costs_exactly_one_shared_retry():
    from src.utils.singleflight import SingleFlight

    builds, out = _storm(SingleFlight(), retry_fails=False)
    assert builds == ["leader", "retry"]  # 2 builds for 12 callers, not 12
    followers = [r for r in out if r != ({}, False)]
    assert len(followers) == 11 and all(r[0] == {"ok": 1} for r in followers)
    assert sorted(r[1] for r in followers) == [False] + [True] * 10  # one ran it, 10 shared


def test_a_failed_retry_is_every_followers_answer():
    from src.utils.singleflight import SingleFlight

    builds, out = _storm(SingleFlight(), retry_fails=True)
    assert builds == ["leader", "retry"]  # bounded: no third attempt
    assert all(r[0] == {} for r in out) and len(out) == 12
