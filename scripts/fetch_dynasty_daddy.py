#!/usr/bin/env python3
"""Fetch Dynasty Daddy Superflex trade values and write a source CSV.

Dynasty Daddy publishes a public JSON API at::

    https://dynasty-daddy.com/api/v1/player/all/today?market=14

which returns ~641 players with ``sf_trade_value`` (Superflex trade
value), ``sf_overall_rank``, ``sf_position_rank``, ``position``, and
``full_name``.  Market 14 is the SF/dynasty format.  No auth or
paywall bypass is needed — a plain ``requests.get`` returns JSON.

Core model
----------

The API returns a flat array of player objects.  Each player carries a
crowd-sourced trade value (``sf_trade_value``), an overall SF rank
(``sf_overall_rank``), a position rank (``sf_position_rank``), a
position (``position``), and a name (``full_name``).  This script
filters to offensive positions (QB/RB/WR/TE) and writes the trade
value as the primary signal.

Output CSV
----------

Written to ``CSVs/site_raw/dynastyDaddySf.csv`` with columns:

    name, value

Read by ``_enrich_from_source_csvs`` in ``src/api/data_contract.py``
as a value-signal source; ``value`` drives the downstream blend.

Run::

    python3 scripts/fetch_dynasty_daddy.py [--mirror-data-dir] [--dry-run]

Exit codes:
    0  - success, CSV written
    1  - soft failure (fetch / parse error, or zero rows extracted)
    2  - schema / shape regression:
         * response is not a JSON array, or
         * row count below :data:`_DD_ROW_COUNT_FLOOR`
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_dynasty_daddy] requests is not installed", file=sys.stderr)
    sys.exit(1)


DD_URL = "https://dynasty-daddy.com/api/v1/player/all/today?market=14"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "dynastyDaddySf.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "dynastyDaddySf.csv"

# Minimum row count.  The Dynasty Daddy API currently carries ~641
# players across all positions; after filtering to offense-only with
# positive sf_trade_value we get ~320+ players.  Floor set at ~78% of
# live baseline so a scrape regression trips exit 2 rather than
# silently publishing a degraded CSV.
_DD_ROW_COUNT_FLOOR: int = 250

# Offensive positions we accept from Dynasty Daddy.  IDP positions
# and picks appearing in the API response are silently dropped.
_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class DynastyDaddySchemaError(RuntimeError):
    """Raised when the API response shape has changed unexpectedly."""


# ── JSON fetch / parse ─────────────────────────────────────────────────
def _fetch_json(url: str, *, timeout: int = 30) -> Any:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _parse_players(data: Any) -> list[dict[str, Any]]:
    """Extract (name, value) from a Dynasty Daddy API response.

    Only returns players whose position is in _OFFENSE_POSITIONS and
    whose sf_trade_value is a positive number.
    """
    if not isinstance(data, list):
        raise DynastyDaddySchemaError(
            f"Expected JSON array, got {type(data).__name__}"
        )
    out: list[dict[str, Any]] = []
    for entry in data:
        name = str(entry.get("full_name") or "").strip()
        if not name:
            continue
        pos = str(entry.get("position") or "").strip().upper()
        # Filter to offense-only positions.
        if pos not in _OFFENSE_POSITIONS:
            continue
        value = entry.get("sf_trade_value")
        if value is None:
            continue
        try:
            value_int = int(float(value))
        except (TypeError, ValueError):
            continue
        if value_int <= 0:
            continue
        out.append(
            {
                "name": name,
                "value": value_int,
            }
        )
    # Sort descending by value so the CSV reads naturally.
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # ``rows`` arrives sorted by value descending from ``_parse_players``,
    # so emitting ``rank`` as a 1-indexed position mirrors the input
    # order exactly.  The contract-side reader routes dynastyDaddySf
    # through the rank-signal path (see
    # ``_SOURCE_CSV_PATHS["dynastyDaddySf"]`` in
    # ``src/api/data_contract.py``): without a ``rank`` column in the
    # CSV, that join silently produces zero coverage.
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "value", "rank"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for idx, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    "name": row["name"],
                    "value": row["value"],
                    "rank": idx,
                }
            )


# ── CLI entry ───────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: CSVs/site_raw/dynastyDaddySf.csv).",
    )
    parser.add_argument(
        "--mirror-data-dir",
        action="store_true",
        help="Also mirror to data/exports/latest/site_raw/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print row counts and a sample without writing the CSV.",
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        default=None,
        help="Read JSON from file instead of fetching (for dev / tests).",
    )
    args = parser.parse_args(argv)

    try:
        if args.from_file:
            raw_text = args.from_file.read_text(encoding="utf-8")
            data = json.loads(raw_text)
        else:
            data = _fetch_json(DD_URL)
    except Exception as exc:
        print(f"[fetch_dynasty_daddy] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        rows = _parse_players(data)
    except DynastyDaddySchemaError as exc:
        print(
            f"[fetch_dynasty_daddy] schema regression: {exc}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"[fetch_dynasty_daddy] parse failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("[fetch_dynasty_daddy] no rows extracted", file=sys.stderr)
        return 1

    if len(rows) < _DD_ROW_COUNT_FLOOR:
        print(
            f"[fetch_dynasty_daddy] row count below floor: "
            f"{len(rows)} < {_DD_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2

    # Position breakdown diagnostics.
    pos_counts: dict[str, int] = {}
    for r in rows:
        # Value-only CSV doesn't carry position — count from parse step.
        pass
    print(
        f"[fetch_dynasty_daddy] total={len(rows)} rows with positive sf_trade_value"
    )

    if args.dry_run:
        print("[fetch_dynasty_daddy] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_dynasty_daddy] wrote {len(rows)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_dynasty_daddy] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(
                f"[fetch_dynasty_daddy] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
