"""Refresh private prepared league views without running the canonical scrape."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.serving.league_views import refresh_league_serving  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lease-wait-seconds", type=float, default=600)
    args = parser.parse_args()
    if not 0 <= args.lease_wait_seconds <= 600:
        parser.error("--lease-wait-seconds must be in [0,600]")
    report = refresh_league_serving(lease_wait_seconds=args.lease_wait_seconds)
    print(json.dumps(report))
    raise SystemExit(3 if report.get("outcome") == "busy" else 1 if report["failed"] else 0)
