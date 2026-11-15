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
        rate_limit,
        "_BYPASS_IPS",
        frozenset({"127.0.0.1"}),
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


# ── R2-12: IPv6 keyed at /64, IPv4 unchanged ───────────────────────────────


def test_ipv6_addresses_in_one_slash64_share_one_bucket(monkeypatch):
    """Rotating the low 64 bits must not mint fresh buckets."""
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 3.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    for i in range(3):
        limited, _ = rate_limit.should_rate_limit(f"2001:db8:1:2::{i + 1:x}")
        assert limited is False
    limited, retry = rate_limit.should_rate_limit("2001:db8:1:2:ffff:ffff:ffff:ffff")
    assert limited is True and retry > 0
    assert rate_limit.snapshot()["trackedIps"] == 1


def test_ipv6_neighbouring_slash64s_are_separate_clients(monkeypatch):
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 1.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    assert rate_limit.should_rate_limit("2001:db8:1:2::1")[0] is False
    assert rate_limit.should_rate_limit("2001:db8:1:2::2")[0] is True
    assert rate_limit.should_rate_limit("2001:db8:1:3::1")[0] is False


def test_ipv4_keying_is_unchanged(monkeypatch):
    """IPv4 stays per exact address: two hosts in one /24 do not share."""
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 1.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    assert rate_limit.should_rate_limit("203.0.113.7")[0] is False
    assert rate_limit.should_rate_limit("203.0.113.7")[0] is True
    assert rate_limit.should_rate_limit("203.0.113.8")[0] is False
    assert rate_limit._site_bucket_key("203.0.113.7") == "203.0.113.7"


def test_ipv4_mapped_ipv6_is_the_ipv4_client(monkeypatch):
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 1.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    assert rate_limit.should_rate_limit("::ffff:198.51.100.4")[0] is False
    assert rate_limit.should_rate_limit("198.51.100.4")[0] is True


def test_non_ip_identity_passes_through(monkeypatch):
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 1.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    assert rate_limit._site_bucket_key("testclient") == "testclient"
    assert rate_limit.should_rate_limit("testclient")[0] is False
    assert rate_limit.should_rate_limit("testclient")[0] is True


def test_bypass_matches_exact_address_or_its_slash64(monkeypatch):
    monkeypatch.setattr(rate_limit, "_RATE_PER_MIN", 1.0)
    monkeypatch.setattr(rate_limit, "_RATE_PER_HOUR", 1000.0)
    monkeypatch.setattr(rate_limit, "_BYPASS_IPS", frozenset({"2001:db8:9:9::/64"}))
    for i in range(5):
        assert rate_limit.should_rate_limit(f"2001:db8:9:9::{i + 1}")[0] is False
