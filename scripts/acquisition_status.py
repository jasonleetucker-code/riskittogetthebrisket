#!/usr/bin/env python3
"""Probe the acquisition ledger (C1-U8).  Counts and stamps only.

Deliberately emits no asset identifier, no manager, no roster and no
transaction id.  A health surface that echoed private acquisition
contents would move the privacy boundary every time someone checked
whether the collector was alive — so the probe reports shape, and
answering "what does it actually say" requires reaching the private
store directly.

Exit codes: 0 present · 2 absent (never 0, so "no ledger" cannot read as
"healthy ledger" in a cron log).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.acquisition.store import coverage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    cov = coverage()
    if args.json:
        print(json.dumps(cov, sort_keys=True, indent=2))
    elif not cov.get("present"):
        print(f"acquisition ledger: ABSENT at {cov.get('path')}")
    else:
        print(f"acquisition ledger: {cov['path']} ({cov['privacyClass']})")
        print(f"  events            {cov['events']} ({cov['undatedEvents']} undated)")
        print(f"  leagues           {cov['leagues']}")
        print(
            f"  holdings          {cov['holdings']} "
            f"({cov['holdingsImportUnknown']} unexplained, "
            f"{cov['holdingsWithBasis']} with a cost basis)"
        )
        print(f"  pick lineage      {cov['lineageHops']} hops over {cov['picksWithLineage']} picks")

    return 0 if cov.get("present") else 2


if __name__ == "__main__":
    raise SystemExit(main())
