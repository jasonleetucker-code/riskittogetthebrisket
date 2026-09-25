"""Drive ``build_matchup_intel`` through its non-blocking cold path (Game Day G).

A background compute started by the call (pending, or a stale generation
refreshing) is always joined before returning, so no thread outlives the
caller's patches.

With no usable generation the endpoint answers a PENDING payload at once
and computes the forecast on ONE background thread.  Tests whose subject is
the ASSEMBLY (what the forecast says) rather than the serving path use
:func:`served_after_background`: the first call must be pending, the
background compute is joined, and the second call serves the generation it
wrote — through the real serving path, with the network seams still
patched by the caller (the background thread runs inside the caller's
``mock.patch`` block, because it is joined there).

``collector_active`` is held True for the second call only so that a
replay's captured clock (hours before the wall clock the test runs at)
does not read as a stale generation and start ANOTHER background compute
after the caller's patches are gone.
"""

from __future__ import annotations

from collections.abc import Callable
from unittest import mock

from src.ros import game_day_live

BACKGROUND_TIMEOUT_SECONDS = 600.0


def served_after_background(build: Callable[[], dict]) -> dict:
    first = build()
    fresh = first.get("freshness") or {}
    refreshing = (fresh.get("backgroundCompute") or {}).get("state") == "running"
    if fresh.get("servedFrom") != game_day_live.SERVED_PENDING and not refreshing:
        return first
    assert game_day_live.wait_for_background(
        timeout=BACKGROUND_TIMEOUT_SECONDS
    ), "background compute did not finish"
    with mock.patch.object(game_day_live, "collector_active", return_value=True):
        second = build()
    served = second.get("freshness") or {}
    assert served.get("servedFrom") != game_day_live.SERVED_PENDING, served
    return second
