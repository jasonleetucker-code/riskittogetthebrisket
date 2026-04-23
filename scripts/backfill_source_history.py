"""One-shot backfill for ``data/source_value_history.jsonl``.

Mines every historical ``data/dynasty_data_*.json`` export and writes
a per-source value snapshot per date.  Idempotent — re-running won't
duplicate entries, and existing snapshots (from the live scrape loop)
are preserved when newer than the export.

Run:
    python3 scripts/backfill_source_history.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import source_history  # noqa: E402

DEFAULT_EXPORT_GLOB = "dynasty_data_*.json"
DEFAULT_EXPORT_DIR = REPO_ROOT / "data"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dir",
        default=str(DEFAULT_EXPORT_DIR),
        help="Directory to scan for dynasty_data_*.json exports (default: data/).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=(
            "Override output JSONL path.  Defaults to "
            "src.api.source_history.HISTORY_PATH."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover and parse files but don't write the output.",
    )
    args = parser.parse_args()

    export_dir = Path(args.dir)
    if not export_dir.is_dir():
        print(f"[backfill] {export_dir} is not a directory", file=sys.stderr)
        return 2

    paths = sorted(export_dir.glob(DEFAULT_EXPORT_GLOB))
    if not paths:
        print(f"[backfill] no files matching {DEFAULT_EXPORT_GLOB} in {export_dir}")
        return 1

    print(f"[backfill] scanning {len(paths)} export files in {export_dir}")
    if args.dry_run:
        for p in paths:
            print(f"  would ingest {p.name}")
        return 0

    output_path = Path(args.output) if args.output else None
    written = source_history.backfill_from_exports(paths, path=output_path)
    target = output_path or source_history.HISTORY_PATH
    print(f"[backfill] wrote {written} snapshots into {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
