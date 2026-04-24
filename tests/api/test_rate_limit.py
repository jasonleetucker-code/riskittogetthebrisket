"""Tests for the public-endpoint rate limiter."""
from __future__ import annotations

import pytest

from src.api import rate_limit


@pytest.fixture(autouse=True)
def _reset():
    rate_limit.reset_for_tests()
    yield
    rate_limit.reset_for_tests()


def test_first_request_is_never_limited():
    limited, _ = rate_limit.should_rate_limit("1.2.3.4")
    assert limited is False


def test_bypass_ip_never_limited(monkeypatch):
    monkeypatch.setattr(
        rate_limit, "_BYPASS_IPS", frozenset({"127.0.0.1"}),
    )
    for _ in range(200):
        limited, _ = rate_limit.should_rate_limit("127.0.0.1")
        assert limited is False


def test_empty_ip_treated_as_bypass():
    """If we can't resolve the client IP (unusual), don't limit.
    Better to let the request through than 429 every user."""
    limited, _ = rate_limit.should_rate_limit("")
    assert limited is False


def test_over_per_minute_limit_returns_limited(monkeypatch):
    # Tighten limits for the test.
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 5.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    ip = "5.5.5.5"
    # First N allowed...
    for i in range(5):
        limited, _ = rate_limit.should_rate_limit(ip)
        assert limited is False, f"request {i} was limited unexpectedly"
    # ... then N+1 gets 429.
    limited, retry = rate_limit.should_rate_limit(ip)
    assert limited is True
    assert retry > 0


def test_over_per_hour_limit_returns_limited(monkeypatch):
    # Minute rate high so we don't hit it; hour rate low.
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 100.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 3.0)
    ip = "6.6.6.6"
    for _ in range(3):
        rate_limit.should_rate_limit(ip)
    limited, _ = rate_limit.should_rate_limit(ip)
    assert limited is True


def test_separate_ips_have_separate_buckets(monkeypatch):
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 2.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    # Exhaust IP A.
    rate_limit.should_rate_limit("A")
    rate_limit.should_rate_limit("A")
    a_limited, _ = rate_limit.should_rate_limit("A")
    assert a_limited is True
    # IP B starts fresh.
    b_limited, _ = rate_limit.should_rate_limit("B")
    assert b_limited is False


def test_snapshot_reports_counts(monkeypatch):
    rate_limit.should_rate_limit("A")
    rate_limit.should_rate_limit("B")
    snap = rate_limit.snapshot()
    assert snap["trackedIps"] >= 2
    assert snap["perMinuteLimit"] > 0
