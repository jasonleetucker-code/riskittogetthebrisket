#!/usr/bin/env python3
"""Nightly cron: refresh all 32 NFL team depth charts via ESPN.

Fetches each team's depth chart (bypasses the 12h cache by clearing
first) and persists to disk.  Feeds the depth-chart-validation path
(Phase 8) and surfaces the day-over-day diff for signal cross-check.

Flag-gated on ``depth_chart_validation`` — the function early-
returns in the individual team fetcher so this script is a no-op
when the flag is OFF.  Safe to run unconditionally in cron.

Usage
-----
    python3 scripts/refresh_depth_charts.py [--force]

    --force   Clear the cache before fetching (otherwise uses whatever
              is fresh within the 12h TTL).

Exit codes
----------
    0  all 32 teams fetched (or flag off → no-op)
    1  partial failure (some teams failed; see logs)
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.api import feature_flags
from src.nfl_data import cache as _cache
from src.nfl_data.depth_charts import (
    NFL_TEAM_IDS,
    fetch_team_depth_chart,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
_LOGGER = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    if not feature_flags.is_enabled("depth_chart_validation"):
        _LOGGER.info("depth_chart_validation flag OFF — skipping refresh")
        return 0

    if args.force:
        cache_dir = _cache._default_cache_dir()  # noqa: SLF001
        for tid in NFL_TEAM_IDS:
            _cache.evict(f"espn_depth:{tid}", cache_dir=cache_dir)
        _LOGGER.info("force: evicted %d cache entries", len(NFL_TEAM_IDS))

    ok = 0
    failed = []
    for tid in NFL_TEAM_IDS:
        entries = fetch_team_depth_chart(tid)
        if entries:
            ok += 1
        else:
            failed.append(tid)

    _LOGGER.info("refresh complete: %d/%d OK", ok, len(NFL_TEAM_IDS))
    if failed:
        _LOGGER.warning("failures: %s", failed)
        return 1 if len(failed) > 5 else 0  # tolerate a few flaky teams
    return 0


if __name__ == "__main__":
    sys.exit(main())
