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
