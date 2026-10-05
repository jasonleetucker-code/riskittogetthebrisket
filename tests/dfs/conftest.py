"""Shared DFS test clock.

The DFS fixtures describe a slate that locks at 2026-10-04T17:00Z, and the
point-in-time store stamps every import / observation / decision with the wall
clock.  Run against the real clock, every "made before lock" assertion turns
false the moment the real date passes the fixture's lock — the suite went red on
2026-10-04 at 16:00Z and again at 17:00Z without any code change.

So the store's two clocks (``store.now_iso`` and ``pit.now``) run from a fixed
instant safely before the fixture lock and ADVANCE one millisecond per read, so
"recorded later" still means later.  A test that needs a specific time keeps
passing it explicitly (``recorded_at=``, ``now=``), which wins over this clock.
"""

from __future__ import annotations

import itertools
from datetime import datetime, timedelta, timezone

import pytest

#: Before every fixture lock in tests/dfs (the earliest is 2026-10-04T17:00Z).
DFS_TEST_CLOCK_START = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _pinned_dfs_clock(monkeypatch):
    from src.dfs import pit, store

    ticks = itertools.count()

    def _now() -> datetime:
        return DFS_TEST_CLOCK_START + timedelta(milliseconds=next(ticks))

    monkeypatch.setattr(store, "now_iso", lambda: _now().isoformat())
    monkeypatch.setattr(pit, "now", lambda: pit._utc(_now()))
    yield
