"""Refresh the automatic DFS slates (DFS-AUTO-07) — the timer's entry point.

Exit codes: 0 refreshed, 1 a source failed (last good slates kept, labelled
SOURCE_ERROR), 2 nothing due.  ``--force`` ignores the cadence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="refresh even when nothing is due")
    args = ap.parse_args(argv)
    from src.dfs.auto import live

    result = live.refresh_nfl_live(force=args.force)
    print(json.dumps({k: v for k, v in result.items() if k != "platforms"}, default=str))
    for platform, detail in (result.get("platforms") or {}).items():
        print(platform, json.dumps({k: v for k, v in detail.items() if k != "pool"}, default=str))
    if result["outcome"] == "not_due":
        return 2
    return 0 if result["outcome"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
