#!/usr/bin/env python3
"""Fetch FantasyCalc dynasty rankings and write a source CSV.

FantasyCalc publishes a public JSON API at::

    https://api.fantasycalc.com/values/current

which returns crowd-sourced dynasty trade values.  No auth or paywall
bypass is needed — a plain ``requests.get`` returns JSON.  The same
data backs the public board at https://www.fantasycalc.com/dynasty-rankings.

Query parameters
----------------

Dynasty Superflex scoring is requested via::

    isDynasty=true   — dynasty (vs redraft) values
    numQbs=2         — Superflex (two QB slots)
    numTeams=12      — 12-team league context
    ppr=1            — full PPR

FantasyCalc's dynasty SF crowd values natively bake in the Superflex
QB premium (numQbs=2), so ``includes_sf=True`` in ``config/sources``
and no extra SF adjustment is applied downstream.  The crowd does
NOT natively price in TE premium, so the registry entry sets
``is_tep_premium=False`` and the global ``tepMultiplier`` boost
applies to this source's blended contribution like any other non-
TEP-native SF board (Dynasty Daddy, FlockFantasy, etc.).

Output CSV
----------

Written to ``CSVs/site_raw/fantasyCalc.csv`` with columns::

    name, value

Read by ``_enrich_from_source_csvs`` in ``src/api/data_contract.py``
as a value-signal source; ``value`` drives the downstream Hill curve
blend.

Run::

    python3 scripts/fetch_fantasycalc.py [--mirror-data-dir] [--dry-run]

Exit codes:
    0  - success, CSV written
    1  - soft failure (fetch / parse error, or zero rows extracted)
    2  - schema / shape regression:
         * response is not a JSON array, or
         * row count below :data:`_FC_ROW_COUNT_FLOOR`
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
    print("[fetch_fantasycalc] requests is not installed", file=sys.stderr)
    sys.exit(1)


FC_URL = (
    "https://api.fantasycalc.com/values/current"
    "?isDynasty=true&numQbs=2&numTeams=12&ppr=1"
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "fantasyCalc.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "fantasyCalc.csv"

# Minimum row count.  The FantasyCalc dynasty SF API currently carries
# ~450+ players across QB/RB/WR/TE after filtering to offense.  Floor
# set at ~75% of historical baseline (458 rows on 2026-03-25 snapshot)
# so a scrape regression trips exit 2 rather than silently publishing
# a degraded CSV.
_FC_ROW_COUNT_FLOOR: int = 340

# Offensive positions we accept from FantasyCalc.  IDP positions, K/DEF,
# and picks (position "PICK") appearing in the API response are silently
# dropped — picks are tethered to rookie values in a dedicated pipeline
# phase downstream and don't need to flow through this CSV.
_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class FantasyCalcSchemaError(RuntimeError):
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


def _extract_player_name(player_obj: Any) -> str:
    """Pull the player display name from a FantasyCalc API entry.

    The API nests player metadata under a ``player`` sub-object with
    a ``name`` field.  Some historical responses also expose a flat
    ``name`` at the top level; we check both for resilience.
    """
    if not isinstance(player_obj, dict):
        return ""
    nested = player_obj.get("player")
    if isinstance(nested, dict):
        name = nested.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    name = player_obj.get("name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return ""


def _extract_player_position(player_obj: Any) -> str:
    if not isinstance(player_obj, dict):
        return ""
    nested = player_obj.get("player")
    if isinstance(nested, dict):
        pos = nested.get("position")
        if isinstance(pos, str):
            return pos.strip().upper()
    pos = player_obj.get("position")
    if isinstance(pos, str):
        return pos.strip().upper()
    return ""


def _parse_players(data: Any) -> list[dict[str, Any]]:
    """Extract (name, value) from a FantasyCalc API response.

    Only returns players whose position is in _OFFENSE_POSITIONS and
    whose value is a positive number.
    """
    if not isinstance(data, list):
        raise FantasyCalcSchemaError(
            f"Expected JSON array, got {type(data).__name__}"
        )
    out: list[dict[str, Any]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        name = _extract_player_name(entry)
        if not name:
            continue
        pos = _extract_player_position(entry)
        if pos not in _OFFENSE_POSITIONS:
            continue
        value = entry.get("value")
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
    # Sort descending by value so the CSV reads naturally and the
    # synthetic ``rank`` column matches the natural value order.
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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
        help="CSV path to write (default: CSVs/site_raw/fantasyCalc.csv).",
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
            data = _fetch_json(FC_URL)
    except Exception as exc:
        print(f"[fetch_fantasycalc] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        rows = _parse_players(data)
    except FantasyCalcSchemaError as exc:
        print(
            f"[fetch_fantasycalc] schema regression: {exc}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"[fetch_fantasycalc] parse failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("[fetch_fantasycalc] no rows extracted", file=sys.stderr)
        return 1

    if len(rows) < _FC_ROW_COUNT_FLOOR:
        print(
            f"[fetch_fantasycalc] row count below floor: "
            f"{len(rows)} < {_FC_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2

    print(
        f"[fetch_fantasycalc] total={len(rows)} rows with positive value"
    )

    if args.dry_run:
        print("[fetch_fantasycalc] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_fantasycalc] wrote {len(rows)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_fantasycalc] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(
                f"[fetch_fantasycalc] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
