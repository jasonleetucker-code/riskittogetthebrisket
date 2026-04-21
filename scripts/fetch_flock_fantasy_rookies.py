#!/usr/bin/env python3
"""Fetch Flock Fantasy Superflex rookie/prospect rankings and write a source CSV.

Flock Fantasy publishes a public JSON API at::

    https://api.flockfantasy.com/rankings?format=PROSPECTS_SF

which returns ``{ format, year, data: [...] }`` with ~98 entries — the
current incoming rookie class only (``isRookie == true`` and
``isDraftPick == false`` for every row, scoped to the upcoming
``draftYear``).  Each entry carries ``playerName``, ``position``,
``averageRank`` (float, lower is better), and ``isRookie``.  After
filtering to offensive positions (QB/RB/WR/TE) ~95+ prospects remain.

Core model
----------

This is a **rank signal** source (not value).  ``averageRank`` is a
multi-expert averaged consensus rank of incoming rookies — lower is
better.  Like ``dlfRookieSf``, the source is registered with
``needs_rookie_translation=True`` so the within-class rank is
crosswalked through KTC's offense rookie ladder before the Hill curve
sees it; that way Flock's #1 rookie inherits KTC's scale-for-top-rookie
rather than being mapped to overall #1 = 9999.

Output CSV
----------

Written to ``CSVs/site_raw/flockFantasySfRookies.csv`` with columns:

    name, Rank

Read by ``_enrich_from_source_csvs`` in ``src/api/data_contract.py``
as a rank-signal source; ``Rank`` drives the downstream blend.

Run::

    python3 scripts/fetch_flock_fantasy_rookies.py [--mirror-data-dir] [--dry-run]

Exit codes:
    0  - success, CSV written
    1  - soft failure (fetch / parse error, or zero rows extracted)
    2  - schema / shape regression:
         * response is not a dict with a ``data`` array, or
         * row count below :data:`_FF_ROOKIE_ROW_COUNT_FLOOR`
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
    print(
        "[fetch_flock_fantasy_rookies] requests is not installed",
        file=sys.stderr,
    )
    sys.exit(1)


FF_URL = "https://api.flockfantasy.com/rankings?format=PROSPECTS_SF"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "flockFantasySfRookies.csv"
DATA_DIR_DST = (
    REPO_ROOT
    / "data"
    / "exports"
    / "latest"
    / "site_raw"
    / "flockFantasySfRookies.csv"
)

# Minimum row count.  The PROSPECTS_SF endpoint currently carries ~98
# entries (one full rookie class).  Floor set at ~60 so a class shrink
# or a scrape regression trips exit 2 rather than silently publishing a
# degraded CSV.  Class sizes vary year-over-year — a small class is
# normal in summers before the next college season fully enters the
# board, so the floor is intentionally permissive.
_FF_ROOKIE_ROW_COUNT_FLOOR: int = 60

# Offensive positions we accept from Flock Fantasy rookies.  The
# PROSPECTS_SF endpoint already excludes IDP and draft picks, but we
# filter defensively.
_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class FlockFantasyRookiesSchemaError(RuntimeError):
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
    """Extract (name, Rank) from a Flock Fantasy PROSPECTS_SF response.

    Only returns players whose position is in _OFFENSE_POSITIONS,
    whose isDraftPick is false, whose isRookie is true, and whose
    averageRank is a positive number.

    The PROSPECTS_SF endpoint is rookie-only by name, but we filter
    defensively on ``isRookie`` because this source is wired with
    ``needs_rookie_translation=True`` downstream — any veteran row
    that slips through would be remapped via the rookie ladder and
    skew blended values.
    """
    if not isinstance(data, dict) or "data" not in data:
        raise FlockFantasyRookiesSchemaError(
            f"Expected dict with 'data' key, got {type(data).__name__}"
        )
    entries = data["data"]
    if not isinstance(entries, list):
        raise FlockFantasyRookiesSchemaError(
            f"Expected 'data' to be a list, got {type(entries).__name__}"
        )
    out: list[dict[str, Any]] = []
    for entry in entries:
        if entry.get("isDraftPick"):
            continue
        if entry.get("isRookie") is False:
            continue
        name = str(entry.get("playerName") or "").strip()
        if not name:
            continue
        pos = str(entry.get("position") or "").strip().upper()
        if pos not in _OFFENSE_POSITIONS:
            continue
        avg_rank = entry.get("averageRank")
        if avg_rank is None:
            continue
        try:
            rank_float = float(avg_rank)
        except (TypeError, ValueError):
            continue
        if rank_float <= 0:
            continue
        out.append(
            {
                "name": name,
                "Rank": rank_float,
            }
        )
    out.sort(key=lambda r: r["Rank"])
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "Rank"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "name": row["name"],
                    "Rank": row["Rank"],
                }
            )


# ── CLI entry ───────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: CSVs/site_raw/flockFantasySfRookies.csv).",
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
            data = _fetch_json(FF_URL)
    except Exception as exc:
        print(
            f"[fetch_flock_fantasy_rookies] fetch failed: {exc}",
            file=sys.stderr,
        )
        return 1

    try:
        rows = _parse_players(data)
    except FlockFantasyRookiesSchemaError as exc:
        print(
            f"[fetch_flock_fantasy_rookies] schema regression: {exc}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(
            f"[fetch_flock_fantasy_rookies] parse failed: {exc}",
            file=sys.stderr,
        )
        return 1

    if not rows:
        print(
            "[fetch_flock_fantasy_rookies] no rows extracted",
            file=sys.stderr,
        )
        return 1

    if len(rows) < _FF_ROOKIE_ROW_COUNT_FLOOR:
        print(
            f"[fetch_flock_fantasy_rookies] row count below floor: "
            f"{len(rows)} < {_FF_ROOKIE_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2

    print(
        f"[fetch_flock_fantasy_rookies] total={len(rows)} rows with valid averageRank"
    )

    if args.dry_run:
        print("[fetch_flock_fantasy_rookies] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(
        f"[fetch_flock_fantasy_rookies] wrote {len(rows)} rows -> {args.dest}"
    )

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(
                f"[fetch_flock_fantasy_rookies] mirrored -> {DATA_DIR_DST}"
            )
        except Exception as exc:
            print(
                f"[fetch_flock_fantasy_rookies] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
