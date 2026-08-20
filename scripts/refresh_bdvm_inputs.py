#!/usr/bin/env python3
"""Warm the nflverse inputs the BDVM request path may only READ.

WHY THIS EXISTS
---------------

``/api/bdvm/*`` used to fill these caches itself, as a side effect of the
first interactive request. On a cold cache that meant six seasons of
weekly stats plus six of snap counts — ~112,450 and ~157,615 rows — plus
a schedule download, parsed inside the uvicorn process that was
simultaneously trying to stream ``/api/data``. CSV parsing is CPU/GIL
heavy, so the unrelated request starved past the Next bridge's 4s idle
timeout and the browser rendered *"Rankings unavailable — 503,
backend_idle_timeout"* on a page that has nothing to do with BDVM.
``run_in_threadpool`` did not prevent it and could not: the contention is
the GIL, not the event loop. Proven by PR #938's E2E investigation.

The request path is now cache-only. That closes the starvation, and it
makes THIS script the thing that keeps BDVM's evidence fresh: the split
is **the refresh owner decides when to fetch; the request path decides
only whether an artifact exists, and reports its age honestly.**

Without this running, BDVM does not serve wrong numbers — it degrades to
the neutral priors it has always used when a fetch failed, and says so in
``meta.auxiliaryInputs``. Missing is never zero.

It is deliberately NOT a new scheduler: it is wired into the existing
``dynasty-bdvm-refresh`` timer, which already runs weekly for the
projection snapshots this evidence sits beside.

Run
---

    python3 scripts/refresh_bdvm_inputs.py
    python3 scripts/refresh_bdvm_inputs.py --season 2026
    python3 scripts/refresh_bdvm_inputs.py --dry-run

Exit codes (repo convention):
    0 - every input warmed, or already fresh
    1 - soft failure; at least one input could not be fetched. The
        last-known-good artifact is LEFT IN PLACE — a failed refresh
        must never delete evidence that is merely old.
    2 - bad arguments, or the nfl_data_ingest feature flag is off
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_LOGGER = logging.getLogger("refresh_bdvm_inputs")


def _warm(label: str, fn, *args, **kwargs) -> tuple[str, int, bool]:
    """Fetch one input. Returns (label, row count, ok).

    A failure is reported, never raised past the caller and never
    converted into a cache write — ``_cached_or_fetch`` already declines
    to ``put()`` an empty fetch, so a bad upstream leaves the previous
    artifact exactly where it was.
    """
    try:
        rows = fn(*args, **kwargs) or []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("%s: FAILED (%s) — last-known-good left in place", label, exc)
        return (label, 0, False)
    if not rows:
        _LOGGER.warning("%s: fetch returned nothing — last-known-good left in place", label)
        return (label, 0, False)
    _LOGGER.info("%s: %d rows", label, len(rows))
    return (label, len(rows), True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=None, help="NFL season (default: derived)")
    parser.add_argument("--dry-run", action="store_true", help="report the plan, fetch nothing")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="[%(levelname)s] %(message)s",
    )

    from src.api import feature_flags

    if not feature_flags.is_enabled("nfl_data_ingest"):
        _LOGGER.error("nfl_data_ingest is OFF — nothing to warm")
        return 2

    from src.bdvm.actuals import nfl_projection_season
    from src.bdvm.context import DEFAULT_SEASONS_BACK

    # The window is READ from the consumer, never restated here: warming
    # a different span than the request path reads fills entries nothing
    # asks for and leaves the ones it does ask for missing.
    season = args.season or nfl_projection_season()
    years = list(range(season - DEFAULT_SEASONS_BACK, season))

    if args.dry_run:
        _LOGGER.info(
            "would warm: id_map, weekly_stats%s, snap_counts%s, schedules[%s], "
            "then materialise the player context for %s",
            years,
            years,
            season,
            season,
        )
        return 0

    from src.nfl_data import ingest

    results = [
        _warm("id_map", ingest.fetch_id_map),
        _warm(f"weekly_stats{years}", ingest.fetch_weekly_stats, years),
        _warm(f"snap_counts{years}", ingest.fetch_snap_counts, years),
        _warm(f"schedules[{season}]", ingest.fetch_schedules, [season]),
    ]

    # The in-progress season gets its OWN cache entry — bdvm/actuals.py
    # fetches ``[season]`` alone so the current season refreshes without
    # dragging six years of history with it. Warm the same key it reads.
    from src.bdvm.actuals import current_nfl_season

    actuals_season = current_nfl_season()
    if actuals_season is not None:
        results.append(
            _warm(
                f"weekly_stats[{actuals_season}] (in-season actuals)",
                ingest.fetch_weekly_stats,
                [actuals_season],
            )
        )
    else:
        _LOGGER.info("outside the Sept-Jan window — no in-season actuals to warm")

    # ── Stage A proper: MATERIALISE what the request path reads ──────
    # Warming the raw feeds is not enough.  The request path used to build
    # the player context from them, and that is 9.0s of GIL-bound parsing
    # off a 369 MB weekly-stats entry even with nothing downloaded — still
    # long enough to starve /api/data past the Next bridge's 4s idle
    # timeout.  The built context is 6.2 MB and rehydrates in 0.20s, so the
    # build happens HERE, once, and the request only loads it.
    #
    # Gated on the feeds actually arriving: writing a snapshot built from a
    # failed fetch would replace a good context with a thin one, which is
    # the "a failed refresh must not destroy last-known-good" rule applied
    # one level up.
    feeds_ok = all(ok for _, _, ok in results)
    if feeds_ok:
        from src.bdvm.context import fetch_and_build_context
        from src.bdvm.context_store import write_snapshot

        try:
            ctx = fetch_and_build_context(season)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("player context: build FAILED (%s) — snapshot left in place", exc)
            ctx = {}
        if ctx:
            path = write_snapshot(season, ctx)
            _LOGGER.info("player context: %d players -> %s", len(ctx), path)
            results.append(("player_context_snapshot", len(ctx), True))
        else:
            _LOGGER.warning("player context: built empty — snapshot left in place")
            results.append(("player_context_snapshot", 0, False))
    else:
        _LOGGER.warning("player context: skipped — an input feed failed; snapshot left in place")
        results.append(("player_context_snapshot", 0, False))

    failed = [label for label, _, ok in results if not ok]
    if failed:
        _LOGGER.error("%d of %d inputs failed: %s", len(failed), len(results), ", ".join(failed))
        return 1
    _LOGGER.info("all %d BDVM inputs warmed", len(results))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
