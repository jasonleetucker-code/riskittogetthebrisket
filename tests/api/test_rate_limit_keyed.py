"""Keyed token buckets (per-user limits on expensive private endpoints)."""

from __future__ import annotations

import pytest

from src.api import rate_limit


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    rate_limit.reset_for_tests()
    now = {"t": 1_000_000.0}
    monkeypatch.setattr(rate_limit, "_keyed_now", lambda: now["t"])
    yield now
    rate_limit.reset_for_tests()


def test_capacity_then_limited_with_retry_after(_clock):
    for _ in range(20):
        assert rate_limit.should_rate_limit_key("u:a", capacity=20, window_seconds=600) == (
            False,
            0,
        )
    limited, retry = rate_limit.should_rate_limit_key("u:a", capacity=20, window_seconds=600)
    assert limited is True and retry == 30  # one token every 600/20 s


def test_refills_continuously(_clock):
    for _ in range(20):
        rate_limit.should_rate_limit_key("u:a", capacity=20, window_seconds=600)
    _clock["t"] += 31
    assert rate_limit.should_rate_limit_key("u:a", capacity=20, window_seconds=600)[0] is False
    assert rate_limit.should_rate_limit_key("u:a", capacity=20, window_seconds=600)[0] is True


def test_keys_are_independent_and_separate_from_ip_buckets(_clock):
    for _ in range(3):
        rate_limit.should_rate_limit_key("u:a", capacity=3, window_seconds=60)
    assert rate_limit.should_rate_limit_key("u:a", capacity=3, window_seconds=60)[0] is True
    assert rate_limit.should_rate_limit_key("u:b", capacity=3, window_seconds=60)[0] is False
    assert rate_limit.should_rate_limit("1.2.3.4") == (False, 0)


def test_degenerate_inputs_are_never_limited():
    assert rate_limit.should_rate_limit_key("", capacity=1, window_seconds=60) == (False, 0)
    assert rate_limit.should_rate_limit_key("k", capacity=0, window_seconds=60) == (False, 0)
