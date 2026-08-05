#!/usr/bin/env python3
"""Fetch Play for Keeps Dynasty's master dynasty board (rank + value).

PFK (https://playforkeepsdynasty.com) is a React SPA whose data layer
is Supabase PostgREST, read directly by every visitor's browser with
the site's embedded publishable key — the same anonymous, public read
path their own frontend uses (their copy: "Free, no signup required").
The dynasty value shown on each player profile comes from ONE table,
so no per-profile crawling is needed::

    GET {SUPABASE}/rest/v1/pfk_dynasty_rankings
        ?select=sleeper_player_id,rank,tier,value,player_name,position,team,kind
        &order=rank.asc

Row shape::

    {"sleeper_player_id": "5927", "rank": 110, "tier": 11,
     "value": 2778, "player_name": "Terry McLaurin",
     "position": "WR", "team": "WAS", "kind": "player", ...}

Picks share the table as ``position == "PICK"`` rows (probed live
2026-07-25: all 525 rows carry ``kind == "player"``, including the 29
picks — ``kind`` does NOT distinguish them).  Pick rows are dropped
here (picks tether to rookie values downstream), and the position
filter keeps QB/RB/WR/TE only.  This is PFK's own hand-maintained
board — a genuinely independent signal (unlike their
``pfk_ktc_values`` table, which is just a KTC mirror we already
ingest directly).

Output: ``CSVs/site_raw/pfkDynasty.csv`` with
``name,value,rank,sleeper_id`` (competition ranks for tied values;
``sleeper_id`` enables ID-based identity matching downstream).

Run
---

    python3 scripts/fetch_pfk.py
    python3 scripts/fetch_pfk.py --mirror-data-dir
    python3 scripts/fetch_pfk.py --dry-run

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
    print("[fetch_pfk] requests is not installed", file=sys.stderr)
    sys.exit(1)


_SUPABASE = "https://ymwoabgesjqrojurdxmv.supabase.co"
# PFK's PUBLISHABLE (anon) key — shipped to every browser in their JS
# bundle; grants the same anonymous read access their site gives any
# visitor.  Not a secret.
_ANON_KEY = "sb_publishable_8z6jTCr6BPKmltRnNvEVzA_do7BmXKe"
PFK_URL = (
    f"{_SUPABASE}/rest/v1/pfk_dynasty_rankings"
    "?select=sleeper_player_id,rank,tier,value,player_name,position,team,kind"
    "&order=rank.asc"
)
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "pfkDynasty.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "pfkDynasty.csv"

# PFK's master board is a curated ranking (hundreds of rows, players +
# picks).  Floor at 120 players — conservative until a live baseline
# establishes over a few scheduled cycles; then re-pin at ~75-80%.
_PFK_ROW_COUNT_FLOOR: int = 380

# Second, DYNAMIC guard (Codex review on PR #532, round 6 — same
# rationale as fetch_fantasynavigator's): a transiently-partial
# PostgREST response above the absolute floor (say 300 of 496 rows)
# would otherwise overwrite the complete last-good board and delete
# ~200 votes.  An extraction may only replace an existing CSV when it
# retains at least this fraction of the last-good row count; below
# that, exit 2 keeps last-good and the next 2h cycle retries.
_PFK_LAST_GOOD_RETENTION: float = 0.75


_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class PfkSchemaError(RuntimeError):
    """Raised when the PostgREST response shape has changed."""


def _fetch_json(url: str, *, timeout: int = 45) -> Any:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "apikey": _ANON_KEY,
        "Authorization": f"Bearer {_ANON_KEY}",
        # PostgREST default limit is 1000 rows — enough for the whole
        # board; make the intent explicit anyway.
        "Range-Unit": "items",
        "Range": "0-1999",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _parse_players(data: Any) -> list[dict[str, Any]]:
    """Extract offensive player rows (QB/RB/WR/TE), positive value,
    deduped by sleeper_player_id keeping the highest value.  Pick rows
    (``position == "PICK"``) and any future non-offense positions are
    dropped — ``kind`` is uniformly ``"player"`` on this table and
    cannot be used to exclude picks."""
    if not isinstance(data, list):
        raise PfkSchemaError(f"Expected JSON array, got {type(data).__name__}")
    best: dict[str, dict[str, Any]] = {}
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("position") or "").strip().upper() not in _OFFENSE_POSITIONS:
            continue
        name = entry.get("player_name")
        if not isinstance(name, str) or not name.strip():
            continue
        value = entry.get("value")
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        if value_f <= 0:
            continue
        sleeper_id = str(entry.get("sleeper_player_id") or "").strip()
        key = sleeper_id or name.strip()
        row = {
            "name": name.strip(),
            "value": round(value_f, 2),
            "sleeper_id": sleeper_id,
        }
        prev = best.get(key)
        if prev is None or row["value"] > prev["value"]:
            best[key] = row
    return sorted(best.values(), key=lambda r: r["value"], reverse=True)


def _count_csv_rows(path: Path) -> int:
    """Data-row count of an existing CSV (0 when absent/unreadable) —
    the last-good baseline for the retention guard."""
    try:
        with path.open("r", encoding="utf-8") as f:
            return max(0, sum(1 for _ in f) - 1)
    except OSError:
        return 0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # Competition ranking ("1-2-2-4") — same convention as the other
    # fetchers (see PR #530): tied values share a rank so feed
    # ordering can never move the blend.
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "value", "rank", "sleeper_id"]
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
                    "sleeper_id": row["sleeper_id"],
                }
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DEFAULT_DST)
    parser.add_argument("--mirror-data-dir", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--from-file", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        if args.from_file:
            data = json.loads(args.from_file.read_text(encoding="utf-8"))
        else:
            data = _fetch_json(PFK_URL)
    except Exception as exc:
        print(f"[fetch_pfk] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        rows = _parse_players(data)
    except PfkSchemaError as exc:
        print(f"[fetch_pfk] schema regression: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[fetch_pfk] parse failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("[fetch_pfk] no rows extracted", file=sys.stderr)
        return 1
    if len(rows) < _PFK_ROW_COUNT_FLOOR:
        print(
            f"[fetch_pfk] row count below floor: {len(rows)} < {_PFK_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2
    last_good = _count_csv_rows(args.dest)
    if last_good > 0 and len(rows) < last_good * _PFK_LAST_GOOD_RETENTION:
        print(
            f"[fetch_pfk] extraction retains only {len(rows)} of "
            f"{last_good} last-good rows (< {_PFK_LAST_GOOD_RETENTION:.0%}) "
            f"— likely a partial response; keeping last-good CSV",
            file=sys.stderr,
        )
        return 2

    print(f"[fetch_pfk] total={len(rows)} player rows")
    if args.dry_run:
        print("[fetch_pfk] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_pfk] wrote {len(rows)} rows -> {args.dest}")
    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_pfk] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(f"[fetch_pfk] mirror failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
