#!/usr/bin/env python3
"""Fetch OTC Fantasy Football's superflex trade-derived dynasty values.

OTCFFB (https://otcffb.com) publishes a community trade-derived value
board at::

    https://otcffb.com/api/trade-values?format=sf

The endpoint is a public JSON API — no auth, no Playwright, no
paywall.  The response shape is::

    {
        "format": "sf",
        "updatedAt": "2026-05-15T16:37:14.906Z",
        "playerCount": 471,
        "pickCount": 82,
        "tradeCount": 354473,
        "players": [
            {"id": "9509", "pos": "RB", "name": "Bijan Robinson",
             "value": 100, "source": "trade", "trades": 2269},
            ...
        ],
        "picks": [...]
    }

Values are on a 0-100 scale (top player = 100).  We filter to
offensive positions (QB/RB/WR/TE) and write the standard
``name,value,rank`` shape.  Picks live in a separate ``picks``
array and are dropped here — current-year picks get tethered to
rookie values downstream and don't need a per-source pick CSV.

Output
------

Written to ``CSVs/site_raw/otcffbSf.csv`` with columns::

    name, value, rank

Run
---

    python3 scripts/fetch_otcffb.py
    python3 scripts/fetch_otcffb.py --mirror-data-dir
    python3 scripts/fetch_otcffb.py --dry-run

Exit codes:
    0  - success, CSV written
    1  - soft failure (fetch / parse error, zero rows extracted)
    2  - schema regression (shape changed, row count below floor)
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
    print("[fetch_otcffb] requests is not installed", file=sys.stderr)
    sys.exit(1)


OTC_URL = "https://otcffb.com/api/trade-values?format=sf"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "otcffbSf.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "otcffbSf.csv"

# Minimum row count floor.  OTCFFB's SF board carries ~470 players
# across all positions; after offense-only filtering ~350-400 remain.
# Floor set at 250 leaves ~30% headroom over the typical post-filter
# count so a regression trips exit 2 rather than silently publishing.
_OTC_ROW_COUNT_FLOOR: int = 275

_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class OtcffbSchemaError(RuntimeError):
    """Raised when the API response shape has changed unexpectedly."""


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
    """Extract ``(name, value)`` rows from the OTCFFB trade-values
    response.

    Filters to ``_OFFENSE_POSITIONS`` and positive values.  Values are
    stored as floats (the API returns one decimal place — Bijan=100.0,
    Allen=96.0, Gibbs=95.1) so we round to two decimals on output to
    preserve the slight sub-integer separation the trade-derived
    blend produces.
    """
    if not isinstance(data, dict):
        raise OtcffbSchemaError(f"Expected JSON object, got {type(data).__name__}")
    players = data.get("players")
    if not isinstance(players, list):
        raise OtcffbSchemaError(
            f"Expected dict.players to be a list, got " f"{type(players).__name__}"
        )
    out: list[dict[str, Any]] = []
    for entry in players:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        pos_raw = entry.get("pos")
        if not isinstance(pos_raw, str):
            continue
        pos = pos_raw.strip().upper()
        if pos not in _OFFENSE_POSITIONS:
            continue
        value = entry.get("value")
        if value is None:
            continue
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        if value_f <= 0:
            continue
        out.append(
            {
                "name": name.strip(),
                "value": round(value_f, 2),
            }
        )
    out.sort(key=lambda r: r["value"], reverse=True)
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # Competition ranking ("1-2-2-4"): rows sharing a published value
    # share a rank.  OTC's 0-100 one-decimal scale ties 300+ of ~460
    # rows (14-way groups deep on the board); a sequential index would
    # convert those ties into distinct rank-signal contributions based
    # purely on API response order, letting arbitrary ordering move the
    # blend (Codex review on PR #530).  ``rows`` arrive value-sorted
    # descending from ``_parse_players``.
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "value", "rank"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        prev_value: Any = object()
        rank = 1
        for idx, row in enumerate(rows, start=1):
            if row["value"] != prev_value:
                rank = idx
                prev_value = row["value"]
            writer.writerow(
                {
                    "name": row["name"],
                    "value": row["value"],
                    "rank": rank,
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: CSVs/site_raw/otcffbSf.csv).",
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
            data = _fetch_json(OTC_URL)
    except Exception as exc:
        print(f"[fetch_otcffb] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        rows = _parse_players(data)
    except OtcffbSchemaError as exc:
        print(f"[fetch_otcffb] schema regression: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[fetch_otcffb] parse failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("[fetch_otcffb] no rows extracted", file=sys.stderr)
        return 1

    if len(rows) < _OTC_ROW_COUNT_FLOOR:
        print(
            f"[fetch_otcffb] row count below floor: " f"{len(rows)} < {_OTC_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2

    print(f"[fetch_otcffb] total={len(rows)} rows with positive value")

    if args.dry_run:
        print("[fetch_otcffb] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_otcffb] wrote {len(rows)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_otcffb] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(
                f"[fetch_otcffb] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
