#!/usr/bin/env python3
"""Fetch Dynasty Nerds SF-TEP rankings and write a source CSV.

Dynasty Nerds publishes their dynasty rankings board inline in the
page HTML as a JavaScript constant::

    window.DR_DATA = { PPR: [...], SFLEX: [...], STD: [...], SFLEXTEP: [...], _meta: {...} };

No JS execution, no auth, and no paywall bypass are needed — a plain
``requests.get`` with a browser UA returns the full payload in the
static HTML.  This script extracts the SFLEXTEP (Superflex + TE
Premium) array, filters out rows whose ``value`` is 0 (deep rookies
Dynasty Nerds lists but has not yet valued), and writes a CSV at the
authoritative source-CSV location:

    exports/latest/site_raw/dynastyNerdsSfTep.csv

Columns: Name, Rank, Value, SleeperId

The file is read by ``_enrich_from_source_csvs`` in
``src/api/data_contract.py`` as a rank-signal source (``signal="rank"``)
so the ``Rank`` column is what drives the downstream blend.  The
``Value`` and ``SleeperId`` columns are for human auditing and future
sleeper-id join work.

Run::

    python3 scripts/fetch_dynasty_nerds.py

Exits 0 on success, 1 on failure.  Safe to call from the scraper's
post-run hook or directly from cron.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_dynasty_nerds] requests is not installed", file=sys.stderr)
    sys.exit(1)


DN_URL = "https://www.dynastynerds.com/dynasty-rankings/sf-tep/"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
# Authoritative CSV location — read by src/api/data_contract.py
DEFAULT_DST = REPO_ROOT / "exports" / "latest" / "site_raw" / "dynastyNerdsSfTep.csv"
# Mirror location — populated by the legacy scraper pipeline
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "dynastyNerdsSfTep.csv"


def _fetch_html(url: str = DN_URL, *, timeout: int = 30) -> str:
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def _extract_dr_data(html: str) -> dict:
    """Parse the ``DR_DATA = {...};`` blob out of the page HTML.

    Uses a balanced-brace walk because the JSON payload spans several
    MB and contains nested objects, so a lazy regex is not safe.
    """
    marker = re.search(r"DR_DATA\s*=\s*(\{)", html)
    if not marker:
        raise RuntimeError("DR_DATA marker not found in page HTML")
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
        raise RuntimeError("DR_DATA payload had unbalanced braces")
    payload = html[start:end]
    return json.loads(payload)


def _build_rows(data: dict, key: str = "SFLEXTEP") -> list[dict]:
    if key not in data:
        raise RuntimeError(f"DR_DATA missing expected key {key!r}")
    raw = data[key]
    rows = []
    for entry in raw:
        val = entry.get("value") or 0
        if val <= 0:
            # Deep rookies Dynasty Nerds lists but has not yet valued.
            continue
        first = (entry.get("firstName") or "").strip()
        last = (entry.get("lastName") or "").strip()
        name = f"{first} {last}".strip()
        if not name:
            continue
        rank = entry.get("rank")
        sleeper_id = str(entry.get("sleeperId") or "").strip()
        pos = (entry.get("pos") or "").strip()
        team = (entry.get("team") or "").strip()
        rows.append(
            {
                "Name": name,
                "Rank": rank,
                "Value": val,
                "SleeperId": sleeper_id,
                "Pos": pos,
                "Team": team,
            }
        )
    # Sort by rank (already sorted but defensive).
    rows.sort(key=lambda r: r["Rank"] if r["Rank"] is not None else 99999)
    return rows


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["Name", "Rank", "Value", "SleeperId", "Pos", "Team"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=DN_URL,
        help="Override the Dynasty Nerds URL to fetch.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: exports/latest/site_raw/dynastyNerdsSfTep.csv).",
    )
    parser.add_argument(
        "--mirror-data-dir",
        action="store_true",
        help="Also mirror to data/exports/latest/site_raw/ for legacy consumers.",
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
            html = _fetch_html(args.url)
    except Exception as exc:
        print(f"[fetch_dynasty_nerds] fetch failed: {exc}", file=sys.stderr)
        return 1

    try:
        data = _extract_dr_data(html)
        rows = _build_rows(data, "SFLEXTEP")
    except Exception as exc:
        print(f"[fetch_dynasty_nerds] parse failed: {exc}", file=sys.stderr)
        return 1

    if not rows:
        print("[fetch_dynasty_nerds] no rows extracted", file=sys.stderr)
        return 1

    _write_csv(args.dest, rows)
    print(f"[fetch_dynasty_nerds] wrote {len(rows)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, rows)
            print(f"[fetch_dynasty_nerds] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(f"[fetch_dynasty_nerds] mirror failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
