#!/usr/bin/env python3
"""Print the owner's OD-3 source-permission checklist for the public advisor.

Read-only.  Lists, from the LIVE voting-source registry, every provider (and
any provider-less source) the owner's record must approve before the public
Brisket Trade Advisor launch gate can open
(``src/trade/public_advisor_permission.py``).  It never writes, proposes or
infers an approval.

``--template`` prints a schema-shaped record with every answer left open
(no approver, no dates, every provider ``"unknown"``); the validator refuses
it as it stands, so it is a form, not an approval.

Exit codes: 0 printed; 2 bad arguments.
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
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--json", action="store_true", help="print the checklist as JSON")
    p.add_argument("--template", action="store_true", help="print the unanswered record form")
    args = p.parse_args(argv)

    from src.trade import public_advisor_permission as perm  # noqa: PLC0415

    if args.template:
        print(json.dumps(perm.unanswered_template(), indent=2))
        return 0
    rows = perm.permission_checklist()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    print("| # | provider | voting sources covered | approve with | or with ALL of |")
    print("|---|---|---|---|---|")
    for i, r in enumerate(rows, 1):
        provider = r["provider"] or "(no recorded provider)"
        entry = f"`{r['providerEntry']}`" if r["providerEntry"] else "(none)"
        print(
            f"| {i} | `{provider}` | {', '.join(f'`{s}`' for s in r['sources'])} | {entry} | "
            f"{', '.join(f'`{x}`' for x in r['orEverySourceEntry'])} |"
        )
    total = sum(len(r["sources"]) for r in rows)
    print(f"\n{len(rows)} provider rows, {total} voting sources.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
