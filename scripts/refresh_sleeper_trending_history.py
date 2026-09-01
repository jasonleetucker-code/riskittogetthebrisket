#!/usr/bin/env python3
"""Warm Sleeper trending adds+drops and append a snapshot to the history ring.

Part of the Live Waiver Opportunity layer
(docs/faab-live-opportunity-model.md, directive Part IV.7).
``src/adapters/sleeper_trending.py`` caches a single point-in-time
snapshot with no retention; this script is what makes 6h/12h/24h/48h
velocity computable via ``src/adapters/sleeper_trending_history.py``.

Usage
-----
    python3 scripts/refresh_sleeper_trending_history.py

Exit codes
----------
    0  ok (a snapshot was recorded — adds and/or drops)
    1  both fetches failed; nothing recorded this run
"""

from __future__ import annotations

import logging
import sys

from src.adapters import sleeper_trending as _trending
from src.adapters import sleeper_trending_history as _history

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    adds_ok = _trending.warm()
    drops_ok = _trending.warm_drops()

    if not adds_ok and not drops_ok:
        _LOGGER.error("both trending fetches failed; nothing recorded")
        return 1

    adds_snapshot = _trending.get_trending_adds() or {}
    drops_snapshot = _trending.get_trending_drops() or {}

    path = _history.record_snapshot(
        adds=adds_snapshot.get("counts") or {},
        drops=drops_snapshot.get("counts") or {},
    )
    _LOGGER.info(
        "recorded trending snapshot to %s (%d adds rows, %d drops rows)",
        path,
        len(adds_snapshot.get("counts") or {}),
        len(drops_snapshot.get("counts") or {}),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
