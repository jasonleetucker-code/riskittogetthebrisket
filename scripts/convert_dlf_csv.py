#!/usr/bin/env python3
"""Convert a raw DLF (Dynasty League Football) export CSV into the
`name,rank` shape that the scope-aware unified ranking pipeline expects
under ``exports/latest/site_raw/``.

The raw DLF IDP file (e.g. ``dlf_idp.csv``) has columns:

    Rank, Avg, Pos, Name, Team, Age, FrankG, Jason K, Justin T, Value, Follow

* ``Avg`` is the expert-consensus average rank (smaller is better).
* ``Rank`` is the DLF-computed ordinal of that average.
* ``Value`` is always empty for the IDP exports.
* The ``Pos`` column encodes both the primitive position ("DE", "LB", "S",
  "DT") and the in-group ordinal ("DL1", "LB3", "DB5").

The scope-aware pipeline treats DLF IDP as an ``overall_idp`` source — DL,
LB and DB players compete on a single full-board ladder — so the primitive
position is irrelevant to the ranking step.  We just need a monotonic
signal ordered the same way as the DLF ranking.

Output CSV schema:

    name,rank

where ``rank`` is taken from the ``Avg`` column if present (falling back
to ``Rank``) so ties from the expert panel are preserved exactly.

Usage
-----

    python scripts/convert_dlf_csv.py \\
        --in dlf_idp.csv \\
        --out exports/latest/site_raw/dlfIdp.csv
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _canonical_name(raw: str) -> str:
    return " ".join(str(raw or "").strip().split())


def _rank_from_row(row: dict[str, str]) -> float | None:
    for key in ("Avg", "avg", "Rank", "rank"):
        val = row.get(key)
        if val is None:
            continue
        try:
            return float(str(val).strip())
        except (TypeError, ValueError):
            continue
    return None


def _name_from_row(row: dict[str, str]) -> str:
    for key in ("Name", "name", "Player", "player"):
        val = row.get(key)
        if val:
            return _canonical_name(val)
    return ""


def convert(src: Path, dst: Path) -> int:
    """Read ``src`` and write a ``name,rank`` CSV to ``dst``.

    Returns the number of rows written.
    """
    if not src.is_file():
        raise FileNotFoundError(f"DLF source file not found: {src}")

    rows_out: list[tuple[str, float]] = []
    with src.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = _name_from_row(row)
            rank = _rank_from_row(row)
            if not name or rank is None or rank <= 0:
                continue
            rows_out.append((name, rank))

    dst.parent.mkdir(parents=True, exist_ok=True)
    with dst.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["name", "rank"])
        for name, rank in rows_out:
            # Keep two decimals when present so the downstream loader can
            # tie-break by the raw Avg rather than collapsing to integers.
            if float(rank).is_integer():
                writer.writerow([name, int(rank)])
            else:
                writer.writerow([name, f"{rank:.2f}"])

    return len(rows_out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in",
        dest="src",
        required=True,
        help="Path to the raw DLF export CSV",
    )
    parser.add_argument(
        "--out",
        dest="dst",
        required=True,
        help="Path to write the normalized name,rank CSV",
    )
    args = parser.parse_args()

    src = Path(args.src).resolve()
    dst = Path(args.dst).resolve()
    count = convert(src, dst)
    print(f"[convert_dlf_csv] {src.name} -> {dst} ({count} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
