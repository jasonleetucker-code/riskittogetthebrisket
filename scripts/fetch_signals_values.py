#!/usr/bin/env python3
"""Collect Signals' AUTHENTICATED native dynasty values into the private box store.

    python scripts/fetch_signals_values.py                        # offense + IDP
    python scripts/fetch_signals_values.py --dataset idp
    python scripts/fetch_signals_values.py --min-interval-hours 5
    python scripts/fetch_signals_values.py --store-dir /tmp/x --state-dir /tmp/y   # measurement

Exit codes: 0 every requested dataset ok (published / unchanged / skipped by
interval) · 1 a dataset failed, or the session refused (auth stop) · 2 a
dataset was quarantined for schema drift / collapse (and none hard-failed).

All logic lives in ``src/sources/signals.py`` (the one Signals owner); this is
a thin CLI.  Since the owner addendum of 2026-10-03 these values are an ACTIVE
canonical source (registry keys ``signalsSf`` / ``signalsIdp``): the board CSV
this writes under ``data/sources/signals/board/`` is what the contract build
on the box reads.  Bounded: at most ``MAX_VALUE_REQUESTS_PER_RUN`` GraphQL
requests (~23 measured), paced, 429-aware, one fresh renewal on 401/403 and
then a recorded stop — never a retry loop and never a login.  The session is
the owner's (``RISKIT_SIGNALS_AUTH_DIR``); no token is ever printed.  Output
is gitignored and never force-added by any workflow.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sources import signals as S  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
DEFAULT_STORE = REPO / "data" / "sources" / "signals"
DEFAULT_STATE_DIR = REPO / "data" / "scrape_state"

_OK = {"published", "unchanged_content"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dataset", choices=["all", *S.VALUE_DATASETS], default="all")
    ap.add_argument("--store-dir", type=Path, default=DEFAULT_STORE)
    ap.add_argument(
        "--state-dir",
        type=Path,
        default=DEFAULT_STATE_DIR,
        help="where <key>_dataset.json / <key>_last_success are written",
    )
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=REPO,
        help="where the newest raw payload (offense universe) is read from",
    )
    ap.add_argument("--auth-dir", default=None, help="owner session store (default: env/OS)")
    ap.add_argument("--season", type=int, default=None, help="IDP season board (default: auto)")
    ap.add_argument(
        "--min-interval-hours",
        type=float,
        default=None,
        help="skip the run if the last SUCCESSFUL run is younger than this",
    )
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args(argv)

    datasets = list(S.VALUE_DATASETS) if args.dataset == "all" else [args.dataset]
    summary = S.collect_values(
        args.store_dir,
        repo_root=args.repo_root,
        state_dir=args.state_dir,
        tokens=S.SignalsAuthTokens(args.auth_dir),
        datasets=datasets,
        season=args.season,
        min_interval_hours=args.min_interval_hours,
        force=args.force,
    )
    print(f"[signals-values] {json.dumps(summary, sort_keys=True, default=str)}")
    if summary.get("skipped"):
        return 0
    kinds = {str(d.get("outcome")) for d in summary.get("datasets", {}).values()}
    if len(summary.get("datasets", {})) < len(datasets):
        return 1
    if kinds <= _OK:
        return 0
    if kinds - _OK == {"quarantined"}:
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
