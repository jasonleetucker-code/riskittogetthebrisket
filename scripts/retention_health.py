#!/usr/bin/env python3
"""Report whether every C1A retention stream is actually landing.

    python scripts/retention_health.py
    python scripts/retention_health.py --json
    python scripts/retention_health.py --require C1-RET-01 C1-RET-04

Exit codes: 0 every probed stream ok · 1 error · 2 at least one stream
is stale, missing or unknown.

**Run this on the production host.**  Every store it probes lives under
``data/``, which is gitignored, so a CI runner's checkout honestly holds
none of them and would report eight ``missing`` streams — a true
statement about the runner and a useless one about production.  CI
wiring probes over SSH, the way
``.github/workflows/scoring-snapshot-diagnostics.yml`` already does.

WHY EXIT 2 EXISTS
─────────────────
The failure this whole tranche is built against is a mechanism that
ships, stops, and stays quiet.  A checker that always exits 0 reproduces
it exactly: a green run that never asserted on an artifact is not
evidence the artifact is there.  ``--require`` names the streams whose
absence should FAIL a caller, so a stream that is legitimately not
provisioned yet on a given host can be reported without turning the
signal permanently red — a check nobody trusts is a check nobody reads.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.retention.health import (  # noqa: E402
    STATE_MISSING,
    STATE_OK,
    STATE_STALE,
    STATE_UNKNOWN,
    retention_health,
)

_GLYPH = {
    STATE_OK: "ok     ",
    STATE_STALE: "STALE  ",
    STATE_MISSING: "MISSING",
    STATE_UNKNOWN: "unknown",
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="emit the raw report")
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="override the data directory (default: <repo>/data)",
    )
    ap.add_argument(
        "--require",
        nargs="*",
        default=None,
        metavar="STREAM_ID",
        help=(
            "only these stream ids decide the exit code. Omit to require "
            "every stream. Pass an empty list to report without failing."
        ),
    )
    args = ap.parse_args()

    try:
        report = retention_health(data_dir=args.data_dir)
    except Exception as exc:  # noqa: BLE001
        print(f"retention-health: FAILED to build report: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"retention health @ {report['checkedAt']}  ({report['dataDir']})")
        print("-" * 78)
        for s in report["streams"]:
            age = s.get("ageHours")
            age_txt = f"{age:>8.1f}h" if isinstance(age, (int, float)) else "       --"
            print(f"  {_GLYPH.get(s['state'], s['state'])}  {s['id']:<11} {age_txt}  {s['title']}")
            print(f"                          {s['detail']}")
        counts = report["counts"]
        print("-" * 78)
        print(
            f"  ok={counts[STATE_OK]}  stale={counts[STATE_STALE]}  "
            f"missing={counts[STATE_MISSING]}  unknown={counts[STATE_UNKNOWN]}"
        )

    if args.require is None:
        failing = [s for s in report["streams"] if s.get("state") != STATE_OK]
    else:
        wanted = set(args.require)
        failing = [
            s for s in report["streams"] if s.get("id") in wanted and s.get("state") != STATE_OK
        ]

    if failing:
        ids = ", ".join(f"{s['id']}={s['state']}" for s in failing)
        print(f"retention-health: NOT OK — {ids}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
