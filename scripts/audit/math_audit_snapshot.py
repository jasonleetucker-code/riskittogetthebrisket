#!/usr/bin/env python3
"""Board-value snapshot for the sitewide math audit's before/after evidence.

Every value-moving fix in the math audit has to answer "how far did the
board move, and for whom".  Reading the diff off a running server is not
reproducible — the scrape underneath it changes.  This script rebuilds the
canonical contract from a FIXED raw payload, so two runs differ only by the
code between them.

    python scripts/audit/math_audit_snapshot.py --out before.json
    # ... apply a fix ...
    python scripts/audit/math_audit_snapshot.py --out after.json
    python scripts/audit/math_audit_snapshot.py --diff before.json after.json

``src/api/data_contract.py`` imports with no third-party dependencies, so
this runs offline with no server and no network.

What the diff can and cannot say
--------------------------------
It bounds how far the board moves and names the rows that moved most.  It
does NOT say which side is more accurate — there is no ground truth for a
dynasty asset's value.  The reason to prefer a post-fix number is the
documented defect the fix closes, never the diff itself.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Match tests/conftest.py: never reach the live Sleeper API from an audit
# tool, or the "before" and "after" runs resolve different league context.
os.environ.pop("SLEEPER_LEAGUE_ID", None)
os.environ["LEAGUE_REGISTRY_PATH"] = "/nonexistent/path/for/audit.json"


def _latest_payload() -> Path:
    """Newest export under ``exports/latest/``.

    Pinning a dated filename here rots: the scheduled refresh renames the
    export every run.  Resolve it instead — and note that a before/after
    diff is only meaningful if BOTH runs used the SAME payload, so pass
    ``--payload`` explicitly when comparing across a data refresh.
    """
    candidates = sorted((_REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
    return candidates[-1] if candidates else _REPO_ROOT / "exports" / "latest" / "dynasty_data.json"


def _load_payload(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def build_snapshot(payload_path: Path) -> dict[str, Any]:
    """Rebuild the contract and reduce it to the fields a math diff needs."""
    from src.api import data_contract  # noqa: PLC0415 — after sys.path setup

    raw = _load_payload(payload_path)
    contract = data_contract.build_api_data_contract(raw)

    rows: dict[str, Any] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict):
            continue
        name = row.get("displayName")
        if not isinstance(name, str) or not name:
            continue
        values = row.get("values") if isinstance(row.get("values"), dict) else {}
        rows[name] = {
            "rankDerivedValue": row.get("rankDerivedValue"),
            "canonicalConsensusRank": row.get("canonicalConsensusRank"),
            "tierId": row.get("tierId"),
            "position": row.get("position"),
            "assetClass": row.get("assetClass"),
            "confidenceBucket": row.get("confidenceBucket"),
            "sourceCount": row.get("sourceCount"),
            # values.* is where the composite-scale fallback shows up, so the
            # diff has to carry it even though it mirrors rankDerivedValue on
            # every row the board priced.
            "valuesOverall": values.get("overall"),
            "valuesDisplayValue": values.get("displayValue"),
        }

    ranked = [r for r in rows.values() if isinstance(r["rankDerivedValue"], (int, float))]
    return {
        "payload": str(payload_path.relative_to(_REPO_ROOT)),
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "rowCount": len(rows),
        "rankedCount": sum(1 for r in rows.values() if r["canonicalConsensusRank"]),
        "pricedCount": len(ranked),
        "rows": rows,
    }


def _fmt(v: Any) -> str:
    return "—" if v is None else str(v)


def diff_snapshots(before: dict[str, Any], after: dict[str, Any], *, top: int) -> int:
    b_rows: dict[str, Any] = before.get("rows") or {}
    a_rows: dict[str, Any] = after.get("rows") or {}

    if before.get("payload") != after.get("payload"):
        print(
            f"WARNING: payloads differ ({before.get('payload')} vs {after.get('payload')}) "
            "— this diff measures a data change, not a code change.",
            file=sys.stderr,
        )

    print(f"rows       {before.get('rowCount')} -> {after.get('rowCount')}")
    print(f"ranked     {before.get('rankedCount')} -> {after.get('rankedCount')}")
    print(f"priced     {before.get('pricedCount')} -> {after.get('pricedCount')}")

    added = sorted(set(a_rows) - set(b_rows))
    removed = sorted(set(b_rows) - set(a_rows))
    if added:
        print(f"\nrows added ({len(added)}): {', '.join(added[:12])}")
    if removed:
        print(f"\nrows removed ({len(removed)}): {', '.join(removed[:12])}")

    moved: list[tuple[float, str, Any, Any, Any, Any]] = []
    rank_moved = 0
    for name in sorted(set(b_rows) & set(a_rows)):
        b, a = b_rows[name], a_rows[name]
        bv, av = b["rankDerivedValue"], a["rankDerivedValue"]
        if bv != av:
            delta = float(av or 0) - float(bv or 0)
            moved.append(
                (abs(delta), name, bv, av, b["canonicalConsensusRank"], a["canonicalConsensusRank"])
            )
        if b["canonicalConsensusRank"] != a["canonicalConsensusRank"]:
            rank_moved += 1

    print(f"\nvalues changed: {len(moved)}   ranks changed: {rank_moved}")
    if moved:
        moved.sort(reverse=True)
        print(f"\ntop {min(top, len(moved))} moves by |Δvalue|:")
        print(f"  {'player':34s} {'before':>8s} {'after':>8s} {'Δ':>8s}  rank")
        for _, name, bv, av, br, ar in moved[:top]:
            d = float(av or 0) - float(bv or 0)
            print(
                f"  {name[:34]:34s} {_fmt(bv):>8s} {_fmt(av):>8s} {d:>+8.0f}  {_fmt(br)}->{_fmt(ar)}"
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--payload",
        type=Path,
        default=_latest_payload(),
        help="raw scraper payload to rebuild from",
    )
    ap.add_argument("--out", type=Path, help="write a snapshot JSON here")
    ap.add_argument(
        "--diff", nargs=2, type=Path, metavar=("BEFORE", "AFTER"), help="diff two snapshot files"
    )
    ap.add_argument("--top", type=int, default=25, help="how many movers to print (default 25)")
    args = ap.parse_args(argv)

    if args.diff:
        with args.diff[0].open(encoding="utf-8") as fh:
            before = json.load(fh)
        with args.diff[1].open(encoding="utf-8") as fh:
            after = json.load(fh)
        return diff_snapshots(before, after, top=args.top)

    if not args.payload.exists():
        print(f"payload not found: {args.payload}", file=sys.stderr)
        return 2

    snap = build_snapshot(args.payload)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open("w", encoding="utf-8") as fh:
            json.dump(snap, fh, indent=1, sort_keys=True)
        print(f"wrote {args.out}  ({snap['rowCount']} rows, {snap['pricedCount']} priced)")
    else:
        print(json.dumps({k: v for k, v in snap.items() if k != "rows"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
