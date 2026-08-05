#!/usr/bin/env python3
"""Refresh the player-context snapshot (contracts, snap share, depth
charts) from nflverse's public datasets.

Downloads land in ``data/playerctx/`` (gitignored raw cache) and the
joined output is written atomically to
``data/playerctx/snapshot.json``.  See ``docs/playerctx.md`` for the
dataset URLs, schemas, and the consumption contract.

Run
---

    python3 scripts/refresh_playerctx.py
    python3 scripts/refresh_playerctx.py --force          # ignore freshness window
    python3 scripts/refresh_playerctx.py --dry-run        # fetch + parse, no snapshot write

Exit codes (repo convention — see scripts/fetch_fantasynavigator.py):
    0  - success, snapshot written (or --dry-run parse OK)
    1  - soft failure (fetch / parse error, missing dataset)
    2  - schema regression (columns missing, row counts below floors,
         or player-count collapse vs the last-good snapshot)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.playerctx import fetch as fetch_mod  # noqa: E402
from src.playerctx import normalize as norm  # noqa: E402
from src.playerctx.normalize import SchemaRegressionError  # noqa: E402
from src.playerctx.service import refresh_playerctx  # noqa: E402


def _dry_run(args: argparse.Namespace) -> int:
    bundle = fetch_mod.fetch_all(
        cache_dir=args.cache_dir, max_age_hours=args.max_age_hours, force=args.force
    )
    for w in bundle.warnings:
        print(f"[refresh_playerctx] warning: {w}", file=sys.stderr)
    if not (bundle.contracts and bundle.snap_counts and bundle.depth_charts):
        print("[refresh_playerctx] dry-run: dataset(s) unavailable", file=sys.stderr)
        return 1
    contracts = norm.parse_contracts(bundle.contracts)
    snaps = norm.aggregate_snaps(norm.parse_snap_counts(bundle.snap_counts))
    depth = norm.parse_depth_charts(bundle.depth_charts)
    print(
        f"[refresh_playerctx] dry-run: contracts={len(contracts)} "
        f"snapPlayers={len(snaps)} (season {bundle.snap_counts_season}) "
        f"depthRows={len(depth)} (season {bundle.depth_charts_season}); "
        "no snapshot written"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-download even if the cache is fresh"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="fetch + parse only; skip join and snapshot write"
    )
    parser.add_argument(
        "--cache-dir", type=Path, default=None, help="raw cache dir (default data/playerctx/)"
    )
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=None,
        help="snapshot output path (default data/playerctx/snapshot.json)",
    )
    parser.add_argument(
        "--retain-history",
        action="store_true",
        help=(
            "also write a dated snaps-only projection under "
            "data/playerctx/history/ for later replay. Off by default: it "
            "commits generated data on a schedule, which should be an "
            "explicit operational choice."
        ),
    )
    parser.add_argument(
        "--history-dir",
        type=Path,
        default=None,
        help="retention output dir (default data/playerctx/history/)",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=fetch_mod.DEFAULT_MAX_AGE_HOURS,
        help="skip re-downloading files younger than this",
    )
    args = parser.parse_args(argv)

    try:
        if args.dry_run:
            return _dry_run(args)
        summary = refresh_playerctx(
            force=args.force,
            max_age_hours=args.max_age_hours,
            cache_dir=args.cache_dir,
            snapshot_path=args.snapshot,
            retain_history=args.retain_history,
            history_dir=args.history_dir,
        )
    except SchemaRegressionError as exc:
        print(f"[refresh_playerctx] schema regression: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001 — CLI boundary: any other failure is a soft fail
        print(f"[refresh_playerctx] failed: {exc}", file=sys.stderr)
        return 1

    for w in summary["warnings"]:
        print(f"[refresh_playerctx] warning: {w}", file=sys.stderr)
    counts = summary["counts"]
    print(
        f"[refresh_playerctx] players={counts.get('players')} "
        f"contractsMatched={counts.get('contracts', {}).get('matched')} "
        f"snapsMatched={counts.get('snapCounts', {}).get('matched')} "
        f"depthMatched={counts.get('depthCharts', {}).get('matched')} "
        f"-> {summary['snapshotPath']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
