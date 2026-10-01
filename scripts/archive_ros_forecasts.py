#!/usr/bin/env python3
"""Archive the published playoff / title forecasts into the private archive (AL-P6).

Run by ``deploy/deploy.sh`` after every deploy on the production box. The
refresh that produces forecasts runs on an ephemeral GitHub Actions runner, so
the box receives each forecast as ``data/ros/sims/<stem>.json`` plus its
identity sidecar ``<stem>.identity.json`` in the deployed commit. This script
joins the two into ``data/forecast_archive/`` (gitignored, never committed).

``--git-history`` additionally walks recent commits touching the sim files, so
a deploy that was skipped or cancelled does not lose the forecasts of the
refresh it would have shipped. Only commits that carry an identity sidecar are
archived; earlier commits are counted, never backfilled here.

Idempotent: re-archiving a forecast already in the archive writes nothing.

Exit codes: 0 completed (including "nothing new"); 1 at least one forecast
could not be archived (``error`` counts); 2 bad arguments.

Capture only -- see ``src/ros/forecast_archive.py``.
"""

from __future__ import annotations

import argparse
import json
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
        help="also archive sidecar-bearing forecasts from recent commits",
    )
    parser.add_argument(
        "--max-commits",
        type=int,
        default=50,
        help="commits per sim file to walk with --git-history (default 50)",
    )
    args = parser.parse_args(argv)
    if args.max_commits < 1:
        parser.error("--max-commits must be at least 1")

    summary = {"published": forecast_archive.ingest_published(args.dir)}
    if args.git_history:
        summary["gitHistory"] = forecast_archive.ingest_git_history(
            args.dir, max_commits=args.max_commits
        )
    print(json.dumps(summary, indent=2, sort_keys=True))
    errors = sum(n for part in summary.values() for k, n in part.items() if k.startswith("error"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
