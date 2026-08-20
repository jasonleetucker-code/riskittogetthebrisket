#!/usr/bin/env python3
"""Build the BDVM reconstructed-baseline projection snapshot.

Fetches the last N completed seasons of nflverse weekly stats, scores
them under the league's exact Sleeper scoring settings (read from the
latest committed contract export by default), builds the BDVM §8.3
proxy projections, and writes an immutable snapshot under
``data/bdvm/projections/<season>/``.

Real (non-proxy) records from the previous latest snapshot are carried
forward over the fresh proxy baseline: a weekly baseline rebuild must
never silently downgrade the serving board from real projections back
to proxies just because the real source's stage failed that week.
Carried records keep their original per-record ``asOf``, so the
consensus staleness penalty downweights them as they age instead of
this script deleting them.

Snapshots are immutable and date-stamped, so a same-day rerun (boot
catch-up, manual ``systemctl start``) is a NO-OP success, not a
failure — the expensive nflverse fetch is skipped entirely.

Usage::

    python scripts/bdvm_build_baseline.py --season 2026
    python scripts/bdvm_build_baseline.py --season 2026 \
        --contract exports/latest/dynasty_data_2026-07-27.json \
        --seasons-back 3 --label baseline

Exit codes: 0 success (including the same-day no-op), 1 nothing built,
2 error.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.bdvm import projections as _proj  # noqa: E402
from src.bdvm.baseline import fetch_and_build_baseline  # noqa: E402
from src.nfl_data.pbp_weekly import SeasonPbpIndex  # noqa: E402
from src.bdvm.projections import (  # noqa: E402
    ProjectionError,
    latest_snapshot_path,
    load_snapshot,
    write_snapshot,
)


def _default_contract_path() -> Path | None:
    candidates = sorted(glob.glob(str(REPO_ROOT / "exports" / "latest" / "dynasty_data_*.json")))
    return Path(candidates[-1]) if candidates else None


def _target_path(season: int, as_of: str, label: str) -> Path:
    """The exact path write_snapshot would use (kept in lockstep)."""
    suffix = f"_{label}" if label else ""
    return _proj.SNAPSHOT_DIR / str(season) / f"projections_{str(as_of)[:10]}{suffix}.json"


def merge_baseline_over_prior(new_records, prior_records):
    """Carry prior real (non-proxy) records forward over a fresh proxy
    baseline.

    Real records win per player: the new proxy for a player covered by
    a carried real record is dropped (same policy as
    idpshow_projections.merge_into_snapshot, from the other side).
    Returns (merged_records, carried_count).
    """
    real = [r for r in prior_records if not r.is_proxy]
    covered = {r.player_key for r in real}
    kept = [r for r in new_records if r.player_key not in covered]
    return kept + real, len(real)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True, help="target (upcoming) season")
    parser.add_argument(
        "--contract",
        type=Path,
        default=None,
        help="contract export with sleeper.scoringSettings "
        "(default: newest exports/latest/dynasty_data_*.json)",
    )
    parser.add_argument("--seasons-back", type=int, default=3)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--dry-run", action="store_true", help="build but do not write")
    parser.add_argument(
        "--no-pbp-supplement",
        action="store_true",
        help="do NOT join the play-by-play artifact. The six reception bands "
        "and the player special-teams rules then score nothing — roughly two "
        "thirds of a receiver's reception points on this card. Reported as "
        "unscored either way; use only to reproduce a pre-2026-08-18 build.",
    )
    args = parser.parse_args()

    as_of = datetime.now(timezone.utc).date().isoformat()

    # Same-day rerun → no-op success BEFORE the expensive fetch.
    target = _target_path(args.season, as_of, args.label)
    if not args.dry_run and target.exists():
        print(f"snapshot for today already exists — no-op: {target}")
        return 0

    contract_path = args.contract or _default_contract_path()
    if contract_path is None or not contract_path.exists():
        print("ERROR: no contract export found for scoring settings", file=sys.stderr)
        return 2
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
    if not scoring:
        print(f"ERROR: {contract_path} has no sleeper.scoringSettings", file=sys.stderr)
        return 2

    pbp_for_season = None
    if not args.no_pbp_supplement:
        # Built by scripts/build_pbp_weekly.py.  A season with no artifact
        # resolves to None and its ten play-by-play rules stay UNAVAILABLE
        # rather than zero — the index reports which seasons those were.
        pbp_index = SeasonPbpIndex()
        pbp_for_season = pbp_index.for_season

    try:
        records, summary = fetch_and_build_baseline(
            season=args.season,
            as_of=as_of,
            scoring_settings=scoring,
            seasons_back=args.seasons_back,
            pbp_for_season=pbp_for_season,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: baseline build failed: {exc}", file=sys.stderr)
        return 2

    print(f"scoring settings: {len(scoring)} keys from {contract_path.name}")
    if pbp_for_season is None:
        print("play-by-play supplement: NOT joined (--no-pbp-supplement)")
    else:
        missing = pbp_index.seasons_missing
        print(
            "play-by-play supplement: joined"
            + (
                f"; NO artifact for {list(missing)} — run scripts/build_pbp_weekly.py "
                f"--seasons {' '.join(str(s) for s in missing)}"
                if missing
                else ""
            )
        )
    for k, v in summary.items():
        print(f"{k}: {v}")
    if not records:
        print("nothing built (no realized history?)", file=sys.stderr)
        return 1

    prior = latest_snapshot_path(args.season)
    if prior is not None:
        try:
            _prior_as_of, prior_records = load_snapshot(prior)
        except (OSError, ValueError) as exc:
            print(f"WARN: could not read prior snapshot {prior}: {exc}", file=sys.stderr)
            prior_records = []
        records, carried = merge_baseline_over_prior(records, prior_records)
        if carried:
            print(f"carried forward {carried} real (non-proxy) records from {prior.name}")

    if args.dry_run:
        print("dry run — snapshot not written")
        return 0
    try:
        path = write_snapshot(records, season=args.season, as_of=as_of, label=args.label)
    except ProjectionError as exc:
        # Race with a concurrent same-day run — the snapshot exists, so
        # the day's work is done.
        print(f"snapshot for today already exists — no-op ({exc})")
        return 0
    print(f"snapshot written: {path} ({len(records)} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
