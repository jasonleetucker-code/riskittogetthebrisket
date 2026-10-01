#!/usr/bin/env python3
"""Archive the published playoff / title forecasts into the private archive (AL-P6).

Run by ``deploy/deploy.sh`` after every deploy on the production box. The
refresh that produces forecasts runs on an ephemeral GitHub Actions runner, so
the box receives each forecast as ``data/ros/sims/<stem>.json`` plus its
identity sidecar ``<stem>.identity.json`` in the deployed commit. This script
joins the two into ``data/forecast_archive/`` (gitignored, never committed).

A sim file with no sidecar -- on disk or in a commit -- is counted as
``skipped:pre_archive`` and never archived identity-less, by both paths.

``--git-history`` additionally walks the commits touching the sim files, newest
first, until it reaches a forecast that was already archived before this run,
so a deploy that was skipped, cancelled or stalled for days does not lose the
forecasts of the refreshes it would have shipped. ``--max-commits`` is only a
safety cap on that walk; hitting it is logged as a warning.

Idempotent: re-archiving a forecast already in the archive writes nothing.

Prints one line of JSON counts. Exit codes: 0 completed (including "nothing
new"); 1 at least one forecast could not be archived (``error`` counts); 2 bad
arguments.

Capture only -- see ``src/ros/forecast_archive.py``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ros import forecast_archive  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="archive_ros_forecasts", description=__doc__)
    parser.add_argument(
        "--dir", type=Path, default=forecast_archive.DEFAULT_DIR, help="archive directory"
    )
    parser.add_argument(
        "--git-history",
        action="store_true",
        help="also archive sidecar-bearing forecasts from commits since the last archived one",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=forecast_archive.HISTORY_SAFETY_CAP,
        help=(
            "safety cap on commits walked per sim file with --git-history "
            f"(default {forecast_archive.HISTORY_SAFETY_CAP})"
        ),
    )
    args = parser.parse_args(argv)
    if args.max_commits < 1:
        parser.error("--max-commits must be at least 1")
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    # The history walk's stop condition must be the archive as it stood BEFORE
    # this run: the published ingest below archives the deploy's own HEAD
    # forecast, and stopping on that key would skip every commit since the last
    # deploy (``forecast_archive.ingest_git_history``).
    prior = forecast_archive.recorded_keys(args.dir)
    summary = {"published": forecast_archive.ingest_published(args.dir)}
    if args.git_history:
        summary["gitHistory"] = forecast_archive.ingest_git_history(
            args.dir, max_commits=args.max_commits, stop_keys=prior
        )
    print(json.dumps(summary, sort_keys=True))
    errors = sum(n for part in summary.values() for k, n in part.items() if k.startswith("error"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
