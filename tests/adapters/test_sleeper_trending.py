"""Tests for ``src/adapters/sleeper_trending.py``.

Pins the TTL-cache contract (mirrors the ``_PlayerMapCache``
pattern): fresh-hit reuse, force-refresh bust, stale-on-failure
degradation, and the never-raise cold-failure path.  All Sleeper
traffic goes through a fake session — no live network.
"""

from __future__ import annotations

import pytest

from src.adapters import sleeper_trending


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeSession:
    """Counts calls; serves a queue of payloads (or raises)."""

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        item = self.payloads.pop(0) if self.payloads else RuntimeError("exhausted")
        if isinstance(item, Exception):
            raise item
        return _FakeResponse(item)


@pytest.fixture(autouse=True)
def _fresh_cache():
    sleeper_trending._reset_cache_for_tests()
    yield
    sleeper_trending._reset_cache_for_tests()


_ROWS = [
    {"player_id": "1234", "count": 18432},
    {"player_id": "5678", "count": 900},
    {"player_id": "", "count": 50},  # dropped: no id
    {"player_id": "9999", "count": 0},  # dropped: zero count
    "junk",  # dropped: not a dict
]


def test_fetch_normalizes_counts_map():
    session = _FakeSession([_ROWS])
    snap = sleeper_trending.get_trending_adds(session=session)
    assert snap is not None
    assert snap["counts"] == {"1234": 18432, "5678": 900}
    assert snap["lookbackHours"] == sleeper_trending.DEFAULT_LOOKBACK_HOURS
    assert isinstance(snap["fetchedAt"], str) and snap["fetchedAt"]


def test_ttl_cache_serves_second_call_without_refetch():
    session = _FakeSession([_ROWS])
    first = sleeper_trending.get_trending_adds(session=session)
    second = sleeper_trending.get_trending_adds(session=session)
    assert session.calls == 1  # second call was a cache hit
    assert second is first


def test_force_refresh_busts_the_cache():
    session = _FakeSession([_ROWS, [{"player_id": "42", "count": 7}]])
    sleeper_trending.get_trending_adds(session=session)
    snap = sleeper_trending.get_trending_adds(session=session, force_refresh=True)
    assert session.calls == 2
    assert snap["counts"] == {"42": 7}


def test_warm_failure_returns_stale_snapshot():
    session = _FakeSession([_ROWS, RuntimeError("sleeper down")])
    first = sleeper_trending.get_trending_adds(session=session)
    stale = sleeper_trending.get_trending_adds(session=session, force_refresh=True)
    assert session.calls == 2
    assert stale is first  # degraded to the previous snapshot


def test_cold_failure_returns_none_without_raising():
    session = _FakeSession([RuntimeError("sleeper down")])
    assert sleeper_trending.get_trending_adds(session=session) is None


def test_cold_failure_negative_caches_no_repeat_fetch():
    """A failed fetch is negative-cached: within the failure TTL the
    recommendation path must NOT re-block on the network — the cache
    answers immediately with what it has (here: nothing)."""
    session = _FakeSession([RuntimeError("sleeper down"), _ROWS])
    assert sleeper_trending.get_trending_adds(session=session) is None
    assert sleeper_trending.get_trending_adds(session=session) is None
    assert sleeper_trending.get_trending_adds(session=session) is None
    assert session.calls == 1  # only the first call touched the network


def test_stale_failure_negative_caches_and_serves_stale():
    """Warm-but-expired cache + outage: the failure is negative-cached
    too, so follow-up calls inside the window serve the stale snapshot
    without another blocking fetch attempt."""
    session = _FakeSession([_ROWS, RuntimeError("sleeper down"), RuntimeError("sleeper down")])
    first = sleeper_trending.get_trending_adds(session=session)
    sleeper_trending._CACHE._expires_at = 0.0  # force TTL expiry
    stale = sleeper_trending.get_trending_adds(session=session)  # refetch fails → stale
    assert stale is first
    assert session.calls == 2
    again = sleeper_trending.get_trending_adds(session=session)  # inside failure window
    assert again is first
    assert session.calls == 2  # the negative cache absorbed this call


def test_force_refresh_bypasses_negative_cache():
    """The explicit post-scrape warm may retry inside the failure
    window — force_refresh punches through the negative cache."""
    session = _FakeSession([RuntimeError("sleeper down"), _ROWS])
    assert sleeper_trending.get_trending_adds(session=session) is None
    snap = sleeper_trending.get_trending_adds(session=session, force_refresh=True)
    assert session.calls == 2
    assert snap is not None and snap["counts"] == {"1234": 18432, "5678": 900}


def test_warm_helper_never_raises():
    session = _FakeSession([RuntimeError("sleeper down")])
    assert sleeper_trending.warm(session=session) is False
    ok_session = _FakeSession([_ROWS])
    assert sleeper_trending.warm(session=ok_session) is True
