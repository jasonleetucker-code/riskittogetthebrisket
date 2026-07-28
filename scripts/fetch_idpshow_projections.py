#!/usr/bin/env python3
"""Fetch The IDP Show 2026 IDP projections into a BDVM snapshot.

The projections article
(https://www.theidpshow.com/p/2026-idp-fantasy-football-projections-rankings)
is paywalled, following the exact pattern of the dynasty-rankings post:
the article HTML (auth via ``idpshow_session.json`` cookies) names the
embeds, and the data itself is served from publicly-readable endpoints
— Datawrapper ``dataset.csv`` and/or a shared Google Sheet.  This
script reuses the session machinery from ``scripts/fetch_idpshow.py``.

Flow
----
1. Build a cookie session (``idpshow_session.json``; see the cookie
   refresh notes in fetch_idpshow.py).  Missing/expired cookies →
   paywall sentinel → exit 1 without touching any snapshot.
2. GET the projections article; collect EVERY Datawrapper chart id and
   every shared Google Sheet id in the HTML.
3. Fetch each candidate table (Datawrapper: resolve the live version,
   pull dataset.csv; Sheets: /export?format=csv).
4. Parse with the schema-tolerant adapter
   (src/bdvm/idpshow_projections.py) — tables that don't clearly look
   like player projections are rejected; the parse report says which
   columns mapped and which approximations applied.
5. Merge into the latest BDVM projection snapshot: real records
   supersede reconstructed-baseline proxies for the players covered;
   write a NEW immutable snapshot (never mutate the old one).

Manual path (no cookies needed): download the sheet from the post and

    python3 scripts/fetch_idpshow_projections.py --season 2026 --csv ~/idp_projections.csv

Run
---
    python3 scripts/fetch_idpshow_projections.py --season 2026
    python3 scripts/fetch_idpshow_projections.py --season 2026 --dry-run

Exit codes: 0 snapshot written (or today's already exists — no-op),
1 no usable data / paywalled, 2 error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from scripts import fetch_idpshow as _rankings_fetcher  # noqa: E402
from src.bdvm.idpshow_projections import (  # noqa: E402
    merge_into_snapshot,
    pick_best_table,
    records_from_rows,
)
from src.bdvm.projections import ProjectionError  # noqa: E402
from src.utils.name_clean import normalize_player_name  # noqa: E402

ARTICLE_URL = "https://www.theidpshow.com/p/2026-idp-fantasy-football-projections-rankings"

_DW_RE = re.compile(r"datawrapper\.dwcdn\.net/([A-Za-z0-9]+)/(\d+)/")
_SHEET_RE = re.compile(r"docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{20,})")


def _collect_candidates(session, html: str) -> list[tuple[str, str]]:
    """(label, csv_text) for every table-ish embed in the article."""
    out: list[tuple[str, str]] = []
    seen_charts: set[str] = set()
    for chart_id, _ver in _DW_RE.findall(html):
        if chart_id in seen_charts:
            continue
        seen_charts.add(chart_id)
        version = _rankings_fetcher._resolve_latest_version(session, chart_id)
        if version is None:
            continue
        try:
            csv_text = _rankings_fetcher._fetch_dataset_csv(session, chart_id, version)
        except Exception as exc:  # noqa: BLE001
            print(f"warn: datawrapper {chart_id} v{version} fetch failed: {exc}", file=sys.stderr)
            continue
        out.append((f"datawrapper:{chart_id}/v{version}", csv_text))
    for sheet_id in dict.fromkeys(_SHEET_RE.findall(html)):
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        try:
            r = session.get(url, timeout=45)
            if r.status_code == 200 and r.text.strip():
                out.append((f"gsheet:{sheet_id}", r.text))
        except Exception as exc:  # noqa: BLE001
            print(f"warn: sheet {sheet_id} fetch failed: {exc}", file=sys.stderr)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument(
        "--csv", type=Path, default=None, help="parse a locally downloaded CSV instead of fetching"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    as_of = datetime.now(timezone.utc).date().isoformat()

    if args.csv is not None:
        if not args.csv.exists():
            print(f"ERROR: {args.csv} not found", file=sys.stderr)
            return 2
        candidates = [(f"file:{args.csv.name}", args.csv.read_text(encoding="utf-8-sig"))]
    else:
        session = _rankings_fetcher._build_session()
        try:
            r = session.get(ARTICLE_URL, timeout=45)
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: GET {ARTICLE_URL} failed: {exc}", file=sys.stderr)
            return 2
        if r.status_code != 200:
            print(f"ERROR: GET {ARTICLE_URL} → HTTP {r.status_code}", file=sys.stderr)
            return 2
        html = r.text
        if _rankings_fetcher._looks_paywalled(html):
            print(
                "paywall: projections article is locked — refresh "
                "idpshow_session.json (see scripts/fetch_idpshow.py header) "
                "or use --csv with a downloaded sheet",
                file=sys.stderr,
            )
            return 1
        candidates = _collect_candidates(session, html)
        if not candidates:
            print("no embedded tables found in the article HTML", file=sys.stderr)
            return 1

    rows, summary = pick_best_table(candidates)
    print(json.dumps(summary, indent=1))
    if not rows:
        print("no usable projection table — nothing written", file=sys.stderr)
        return 1

    records = records_from_rows(
        rows, season=args.season, as_of=as_of, name_normalizer=normalize_player_name
    )
    print(f"projection records: {len(records)}")
    if args.dry_run:
        print("dry run — snapshot not written")
        return 0
    try:
        _path, merge_summary = merge_into_snapshot(records, season=args.season, as_of=as_of)
    except ProjectionError as exc:
        # Snapshots are immutable and date-stamped: a same-day rerun
        # (boot catch-up, manual restart) collides with today's file.
        # The day's merge already happened — no-op success, not a
        # failure the journal blames on cookies.
        print(f"snapshot for today already exists — no-op ({exc})")
        return 0
    print(json.dumps(merge_summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
