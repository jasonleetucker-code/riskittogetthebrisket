#!/usr/bin/env python3
"""Fetch FantasyPros Dynasty Superflex offensive rankings and write a source CSV.

FantasyPros publishes its dynasty rankings inline in the page HTML as a
JavaScript constant::

    var ecrData = { ..., "players": [...], ... };

No JS execution, no auth, and no paywall bypass are needed — a plain
``requests.get`` with a browser UA returns the full payload in the
static HTML.  This script extracts the ``players`` array from the
FantasyPros dynasty superflex rankings page:

    https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php

Core model
----------

The dynasty superflex page is a single flat board covering QB/RB/WR/TE.
Each player carries a consensus ECR rank (``rank_ecr``), position rank
(``pos_rank``), position (``player_position_id``), and team
(``player_team_id``).  No anchor-curve extension is needed — the single
page is the complete source.

Output CSV
----------

Written to ``exports/latest/site_raw/fantasyProsSf.csv`` with columns:

    name, Rank, position, team

Read by ``_enrich_from_source_csvs`` in ``src/api/data_contract.py``
as a rank-signal source; ``Rank`` drives the downstream blend.

Run::

    python3 scripts/fetch_fantasypros_offense.py [--mirror-data-dir] [--dry-run]

Exit codes:
    0  - success, CSV written
    1  - soft failure (fetch / parse error, or zero rows extracted)
    2  - schema / shape regression:
         * ecrData missing the ``players`` key, or
         * row count below :data:`_FP_ROW_COUNT_FLOOR`
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_fantasypros_offense] requests is not installed", file=sys.stderr)
    sys.exit(1)


FP_URL = "https://www.fantasypros.com/nfl/rankings/dynasty-superflex.php"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "exports" / "latest" / "site_raw" / "fantasyProsSf.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "fantasyProsSf.csv"

# Minimum row count.  The dynasty superflex board currently carries
# ~250+ players.  Floor set at ~70% of live baseline so a scrape
# regression trips exit 2 rather than silently publishing a degraded CSV.
_FP_ROW_COUNT_FLOOR: int = 150

# Offensive positions we accept from FantasyPros.  IDP positions
# appearing on the superflex board are silently dropped.
_OFFENSE_POSITIONS: frozenset[str] = frozenset({"QB", "RB", "WR", "TE"})


class FantasyProsOffenseSchemaError(RuntimeError):
    """Raised when ecrData is missing the expected structure."""


# ── HTML fetch / ecrData extraction ─────────────────────────────────────
def _fetch_html(url: str, *, timeout: int = 30) -> str:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_ecr_data(html: str) -> dict[str, Any]:
    """Walk ``ecrData = {...}`` out of FantasyPros page HTML.

    Uses a balanced-brace walk because the payload is a multi-KB JS
    object literal with nested ``players`` array; a lazy regex can't
    find the closing brace reliably.
    """
    marker = re.search(r"ecrData\s*=\s*(\{)", html)
    if not marker:
        raise FantasyProsOffenseSchemaError("ecrData marker not found in page HTML")
    start = marker.start(1)
    depth = 0
    end = None
    for i in range(start, len(html)):
        ch = html[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    if end is None:
        raise FantasyProsOffenseSchemaError("ecrData payload had unbalanced braces")
    payload = html[start:end]
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise FantasyProsOffenseSchemaError(
            f"ecrData expected dict, got {type(parsed).__name__}"
        )
    if "players" not in parsed or not isinstance(parsed["players"], list):
        raise FantasyProsOffenseSchemaError(
            "ecrData shape changed: missing 'players' list "
            f"(available keys: {sorted(parsed.keys())[:10]})"
        )
    return parsed


def _parse_players(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract (rank, name, pos_id, team) from an ecrData payload.

    Only returns players whose position is in _OFFENSE_POSITIONS.
    """
    out: list[dict[str, Any]] = []
    for entry in data["players"]:
        name = str(entry.get("player_name") or "").strip()
        if not name:
            continue
        rank = entry.get("rank_ecr")
        if rank is None:
            continue
        try:
            rank_int = int(rank)
        except (TypeError, ValueError):
            continue
        pos_id = str(entry.get("player_position_id") or "").strip().upper()
        # Filter to offense-only positions.
        if pos_id not in _OFFENSE_POSITIONS:
            continue
        team = str(entry.get("player_team_id") or "").strip()
        out.append(
            {
                "rank": rank_int,
                "name": name,
                "position": pos_id,
                "team": team,
            }
        )
    # Defensive sort; FP returns sorted but don't rely on it.
    out.sort(key=lambda r: r["rank"])
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["name", "Rank", "position", "team"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "name": row["name"],
                    "Rank": row["rank"],
                    "position": row["position"],
                    "team": row["team"],
                }
            )


# ── CLI entry ───────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: exports/latest/site_raw/fantasyProsSf.csv).",
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
        help="Read HTML from file instead of fetching (for dev / tests).",
    )
    args = parser.parse_args(argv)

    try:
        if args.from_file:
            html = args.from_file.read_text(encoding="utf-8")
        else:
            html = _fetch_html(FP_URL)
    except Exception as exc:
        print(f"[fetch_fantasypros_offense] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        data = _extract_ecr_data(html)
    except FantasyProsOffenseSchemaError as exc:
        print(
            f"[fetch_fantasypros_offense] schema regression: {exc}",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"[fetch_fantasypros_offense] parse failed: {exc}", file=sys.stderr)
        return 1

    rows = _parse_players(data)

    if not rows:
        print("[fetch_fantasypros_offense] no rows extracted", file=sys.stderr)
        return 1

    if len(rows) < _FP_ROW_COUNT_FLOOR:
        print(
            f"[fetch_fantasypros_offense] row count below floor: "
            f"{len(rows)} < {_FP_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2

    # Position breakdown diagnostics.
    pos_counts: dict[str, int] = {}
    for r in rows:
        pos_counts[r["position"]] = pos_counts.get(r["position"], 0) + 1
    pos_summary = " ".join(f"{p}={c}" for p, c in sorted(pos_counts.items()))
    print(
        f"[fetch_fantasypros_offense] total={len(rows)} {pos_summary}"
    )

    if args.dry_run:
        print("[fetch_fantasypros_offense] --dry-run; not writing CSV")
        for r in rows[:5]:
            print("  ", r)
        return 0

    _write_csv(args.dest, rows)
    print(f"[fetch_fantasypros_offense] wrote {len(rows)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_fantasypros_offense] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(
                f"[fetch_fantasypros_offense] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
