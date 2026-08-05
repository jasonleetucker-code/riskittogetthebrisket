#!/usr/bin/env python3
"""Fetch Fantasy Navigator's superflex dynasty rankings + values.

Fantasy Navigator (https://www.fantasynavigator.com) is a Vue SPA whose
backend is a public, unauthenticated REST API on Render::

    https://fantasy-navigator-latest.onrender.com/ranks?platform=sf

The response is a JSON array mixing roster types and rank types.  Row
shape::

    {"player_full_name": "Bijan Robinson", "pos_rank": "RB 1",
     "team": "ATL", "age": 24, "is_rookie": "false",
     "ktc_player_id": "1414", "player_value": 9939, "player_rank": 1,
     "_position": "RB", "roster_type": "sf_value",
     "rank_type": "dynasty", "_insert_date": "2026-06-27"}

We keep only ``roster_type == "sf_value"`` + ``rank_type == "dynasty"``
rows (superflex dynasty — the board that matches our league).  NOTE:
rows carry ``ktc_player_id`` and the site credits KeepTradeCut as a
data source, so FN's values are KTC-derived and partially correlated
with our ``ktcSfTep`` vote — this is documented on the registry entry;
the count-aware blend and Hampel filter tolerate correlated sources.

Output: ``CSVs/site_raw/fantasyNavigatorSf.csv`` with ``name,value,rank``
(competition ranks — tied values share a rank, same convention as
``fetch_otcffb.py`` / ``fetch_fantasycalc.py``).

Run
---

    python3 scripts/fetch_fantasynavigator.py
    python3 scripts/fetch_fantasynavigator.py --mirror-data-dir
    python3 scripts/fetch_fantasynavigator.py --dry-run

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
    print("[fetch_fantasynavigator] requests is not installed", file=sys.stderr)
    sys.exit(1)


FN_URL = "https://fantasy-navigator-latest.onrender.com/ranks?platform=sf"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "fantasyNavigatorSf.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "fantasyNavigatorSf.csv"

# FN's dynasty SF board carries roughly a full offensive universe
# (~400+ rows observed at integration time).  Floor at 200 leaves wide
# headroom so a partial response trips exit 2 instead of publishing a
# half board.  Re-pin to ~75-80% of the live baseline once a few
# scheduled cycles have established one (same policy as
# _DEFAULT_SOURCE_ROW_FLOORS).
_FN_ROW_COUNT_FLOOR: int = 360

# Second, DYNAMIC guard (Codex review on PR #532, round 4): because
# the parser keeps only the newest global ``_insert_date`` snapshot, a
# fetch that lands MID-INSERT sees a partial new snapshot — 400 rows
# with today's date would clear the absolute floor above yet silently
# delete ~350 votes from the complete 758-row board.  So an extraction
# may only replace an existing CSV when it retains at least this
# fraction of the last-good row count; below that we exit 2 and keep
# last-good (the next 2h cycle picks up the completed snapshot).  A
# legitimate vendor board shrink >25% will hold last-good and stay
# loudly stale until this pin is revisited — that is the correct
# failure mode for an unattended pipeline.
_FN_LAST_GOOD_RETENTION: float = 0.75

_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class FantasyNavigatorSchemaError(RuntimeError):
    """Raised when the API response shape has changed unexpectedly."""


def _fetch_json(url: str, *, timeout: int = 45) -> Any:
    headers = {
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _parse_players(data: Any) -> list[dict[str, Any]]:
    """Extract superflex-dynasty ``(name, value)`` rows.

    Filters: ``roster_type == "sf_value"``, ``rank_type == "dynasty"``,
    offensive positions, positive value — then restricts to the feed's
    NEWEST GLOBAL ``_insert_date`` snapshot before deduplicating
    (Codex reviews on PR #532, rounds 1+2).  The feed re-inserts the
    whole board on each snapshot (probed 2026-07-25: newest date
    carried 770 of 811 rows; the remainder were stragglers from
    2025-2026 dates — players no longer on the current board whose
    stale values must not keep voting).  Per-name newest-date selection
    is not enough: a player absent from the newest snapshot would keep
    their last historical row forever.  A partial newest snapshot is
    caught by ``_FN_ROW_COUNT_FLOOR`` (exit 2, keep last-good CSV).
    Within the snapshot, dedupe by name keeping the highest value.
    ISO ``YYYY-MM-DD`` dates compare correctly as strings; if no row
    carries a date the whole feed is treated as one snapshot.
    """
    if not isinstance(data, list):
        raise FantasyNavigatorSchemaError(f"Expected JSON array, got {type(data).__name__}")
    candidates: list[tuple[str, str, float]] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        if str(entry.get("roster_type") or "") != "sf_value":
            continue
        if str(entry.get("rank_type") or "") != "dynasty":
            continue
        name = entry.get("player_full_name")
        if not isinstance(name, str) or not name.strip():
            continue
        pos = str(entry.get("_position") or "").strip().upper()
        if pos not in _OFFENSE_POSITIONS:
            continue
        value = entry.get("player_value")
        try:
            value_f = float(value)
        except (TypeError, ValueError):
            continue
        if value_f <= 0:
            continue
        insert_date = str(entry.get("_insert_date") or "")
        candidates.append((name.strip(), insert_date, round(value_f, 2)))
    if not candidates:
        return []
    newest_date = max(d for _, d, _ in candidates)
    best: dict[str, dict[str, Any]] = {}
    for name, insert_date, value_f in candidates:
        if insert_date != newest_date:
            continue
        row = {"name": name, "value": value_f}
        prev = best.get(name)
        if prev is None or row["value"] > prev["value"]:
            best[name] = row
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
    # Competition ranking ("1-2-2-4"): rows sharing a value share a
    # rank, so ties never become distinct rank-signal contributions
    # based on feed ordering (same convention as fetch_otcffb.py —
    # see PR #530).  ``rows`` arrive value-sorted descending.
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
            writer.writerow({"name": row["name"], "value": row["value"], "rank": rank})


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
            data = _fetch_json(FN_URL)
    except Exception as exc:
        print(f"[fetch_fantasynavigator] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        rows = _parse_players(data)
    except FantasyNavigatorSchemaError as exc:
        print(f"[fetch_fantasynavigator] schema regression: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"[fetch_fantasynavigator] parse failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("[fetch_fantasynavigator] no rows extracted", file=sys.stderr)
        return 1
    if len(rows) < _FN_ROW_COUNT_FLOOR:
        print(
            f"[fetch_fantasynavigator] row count below floor: {len(rows)} < {_FN_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2
    last_good = _count_csv_rows(args.dest)
    if last_good > 0 and len(rows) < last_good * _FN_LAST_GOOD_RETENTION:
        print(
            f"[fetch_fantasynavigator] newest snapshot retains only "
            f"{len(rows)} of {last_good} last-good rows "
            f"(< {_FN_LAST_GOOD_RETENTION:.0%}) — likely a mid-insert "
            f"partial snapshot; keeping last-good CSV",
            file=sys.stderr,
        )
        return 2

    print(f"[fetch_fantasynavigator] total={len(rows)} sf-dynasty rows")
    if args.dry_run:
        print("[fetch_fantasynavigator] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_fantasynavigator] wrote {len(rows)} rows -> {args.dest}")
    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_fantasynavigator] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(f"[fetch_fantasynavigator] mirror failed: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
