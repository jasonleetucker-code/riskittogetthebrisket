"""Tests for the circuit breaker."""
from __future__ import annotations

import time
import pytest

from src.utils import circuit_breaker as cb


@pytest.fixture(autouse=True)
def _reset():
    cb.reset_all_for_tests()
    yield
    cb.reset_all_for_tests()


def test_closed_breaker_allows_calls():
    bp = cb.get_or_create("test")
    assert bp.can_call() is True


def test_failures_under_threshold_stay_closed():
    bp = cb.get_or_create("test", failure_threshold=5)
    for _ in range(4):
        bp.report_failure("err")
    assert bp.can_call() is True


def test_failures_at_threshold_open_the_breaker():
    bp = cb.get_or_create("test", failure_threshold=3, failure_window_sec=60)
    for _ in range(3):
        bp.report_failure("err")
    assert bp.can_call() is False
    assert bp.snapshot()["state"] == "open"


def test_opens_then_half_opens_after_duration():
    bp = cb.get_or_create(
        "test", failure_threshold=2,
        failure_window_sec=60, open_duration_sec=0.05,
    )
    bp.report_failure("x")
    bp.report_failure("y")
    assert bp.can_call() is False
    time.sleep(0.1)
    # After open_duration: can_call() transitions to half_open.
    assert bp.can_call() is True
    assert bp.snapshot()["state"] == "half_open"


def test_success_in_half_open_closes():
    bp = cb.get_or_create(
        "test", failure_threshold=1,
        failure_window_sec=60, open_duration_sec=0.05,
    )
    bp.report_failure("x")
    time.sleep(0.1)
    bp.can_call()  # triggers half_open
    bp.report_success()
    assert bp.snapshot()["state"] == "closed"


def test_failure_in_half_open_reopens():
    bp = cb.get_or_create(
        "test", failure_threshold=1,
        failure_window_sec=60, open_duration_sec=0.05,
    )
    bp.report_failure("first")
    time.sleep(0.1)
    bp.can_call()  # half_open
    bp.report_failure("second")
    assert bp.snapshot()["state"] == "open"


def test_sliding_window_evicts_old_failures():
    bp = cb.get_or_create(
        "test", failure_threshold=3, failure_window_sec=0.05,
    )
    bp.report_failure("a")
    bp.report_failure("b")
    time.sleep(0.1)  # both failures age out
    bp.report_failure("c")
    # Only "c" in the window → below threshold.
    assert bp.can_call() is True


def test_fast_fail_counter_increments_when_open():
    bp = cb.get_or_create(
        "test", failure_threshold=1, failure_window_sec=60,
        open_duration_sec=60,
    )
    bp.report_failure("x")
    for _ in range(5):
        bp.can_call()
    assert bp.snapshot()["counters"]["fastFail"] == 5


def test_force_close_resets_state():
    bp = cb.get_or_create(
        "test", failure_threshold=1, failure_window_sec=60,
    )
    bp.report_failure("x")
    assert bp.snapshot()["state"] == "open"
    bp.force_close()
    assert bp.snapshot()["state"] == "closed"
    assert bp.can_call() is True


def test_get_or_create_returns_same_instance():
    a = cb.get_or_create("shared")
    b = cb.get_or_create("shared")
    assert a is b


def test_snapshot_all_lists_every_breaker():
    cb.get_or_create("alpha")
    cb.get_or_create("beta")
    cb.get_or_create("gamma")
    names = [s["name"] for s in cb.snapshot_all()]
    assert names == ["alpha", "beta", "gamma"]  # sorted


def test_open_transition_logs_warning(caplog):
    import logging
    bp = cb.get_or_create("loud", failure_threshold=1, failure_window_sec=60)
    with caplog.at_level(logging.WARNING):
        bp.report_failure("boom")
    assert any("circuit_breaker=open" in r.message for r in caplog.records)


def test_close_transition_logs_info(caplog):
    import logging
    bp = cb.get_or_create(
        "quiet", failure_threshold=1,
        failure_window_sec=60, open_duration_sec=0.05,
    )
    bp.report_failure("x")
    time.sleep(0.1)
    bp.can_call()  # half_open
    with caplog.at_level(logging.INFO):
        bp.report_success()
    assert any("circuit_breaker=closed" in r.message for r in caplog.records)
