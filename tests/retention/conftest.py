"""Retention-test fixtures that keep wall-clock semantics deterministic.

The production retention owner intentionally ages dated filenames.  One legacy
probe test uses a fixed 2026-08-10 playerctx filename only to prove that the
stream is discovered and counted.  Freeze that single test near its fixture
date so calendar time cannot silently turn a discovery test into a stale-data
test.  Dedicated freshness tests continue to exercise the real clock semantics.
"""

from datetime import datetime, timezone

import pytest

from src.retention import health


@pytest.fixture(autouse=True)
def _freeze_legacy_playerctx_probe_clock(request, monkeypatch):
    if request.node.name != "test_playerctx_snapshots_are_probed":
        return

    frozen = datetime(2026, 8, 10, 12, 0, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(health, "_now", lambda: frozen)
