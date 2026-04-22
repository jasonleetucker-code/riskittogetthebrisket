#!/usr/bin/env python3
"""Fetch FantasyPros Dynasty Trade Value Chart (Fitzmaurice column).

FantasyPros publishes Pat Fitzmaurice's monthly Dynasty Trade Value
Chart as an article with a date-rotating URL.  Each monthly update
embeds four Datawrapper iframes (one per position), and Datawrapper
exposes the underlying table as a tab-separated CSV we can fetch
directly — no HTML scraping of the article body required.

URL pattern
-----------

The article slug rotates monthly::

    https://www.fantasypros.com/{YYYY}/{MM}/
        fantasy-football-rankings-dynasty-trade-value-chart-
        {month-name}-{YYYY}-update/

We start from the current month, fall back through up to 3 previous
months when the current URL 404s (FP usually publishes within the
first week, but a fresh-of-the-month run may hit a window where the
new article hasn't landed yet).

League scoring
--------------

Our league is Superflex + TE Premium, so per-position column pick:

* QB  → ``SF Value``         (e.g. Josh Allen 101, not 1QB 51)
* RB  → ``Trade Value``      (position has no league-scoring split)
* WR  → ``Trade Value``
* TE  → ``TEP Value``        (e.g. Brock Bowers 82, not baseline 69)

This matches the yahooBoone source pattern (2QB + TE-Prem columns).

Output
------

    CSVs/site_raw/fantasyProsFitzmaurice.csv

Columns: ``name,team,position,value``.  The ranking pipeline reads
the ``value`` column via ``_VALUE_ALIASES`` and rescales every
player linearly so Fitzmaurice's top player contributes 9999.

Run
---

    python3 scripts/fetch_fantasypros_fitzmaurice.py
    python3 scripts/fetch_fantasypros_fitzmaurice.py --dry-run
    python3 scripts/fetch_fantasypros_fitzmaurice.py --url <article-url>
"""
from __future__ import annotations

import argparse
import calendar
import csv
import re
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT_PATH = REPO / "CSVs" / "site_raw" / "fantasyProsFitzmaurice.csv"

# Per-position column to use for our Superflex + TE-Premium league.
# Keys are the position label we stamp onto each row; values are
# the CSV column-name alternatives we search for in priority order
# (the first present column wins).
_POSITION_VALUE_COLUMNS = {
    "QB": ("SF Value", "Superflex Value", "2QB Value", "Trade Value"),
    "RB": ("Trade Value", "Value"),
    "WR": ("Trade Value", "Value"),
    "TE": ("TEP Value", "TE Premium Value", "Trade Value", "Value"),
}

# Datawrapper chart IDs sometimes appear multiple times per article;
# we only want the four rankings tables.  Identify them by matching
# the position label in the containing heading / caption.
_POSITION_HEADINGS = (
    ("QB", ("Dynasty Trade Values: Quarterbacks", "Quarterbacks")),
    ("RB", ("Dynasty Trade Values: Running Backs", "Running Backs")),
    ("WR", ("Dynasty Trade Values: Wide Receivers", "Wide Receivers")),
    ("TE", ("Dynasty Trade Value Chart: Tight Ends",
            "Dynasty Trade Values: Tight Ends", "Tight Ends")),
)


def _build_candidate_urls(today: date | None = None) -> list[str]:
    """Return article URLs to try, newest month first.

    Falls back up to 3 months back so a run on the 2nd of the month
    before Fitzmaurice's update lands still finds last month's data.
    """
    t = today or date.today()
    urls: list[str] = []
    for offset in range(0, 4):
        y = t.year
        m = t.month - offset
        while m <= 0:
            m += 12
            y -= 1
        month_name = calendar.month_name[m].lower()
        urls.append(
            f"https://www.fantasypros.com/{y}/{m:02d}/"
            f"fantasy-football-rankings-dynasty-trade-value-chart-"
            f"{month_name}-{y}-update/"
        )
    return urls


def _fetch_article_html(url: str) -> str | None:
    """GET the FP article; return text on 200, None on 404/error."""
    try:
        import requests
    except ImportError:
        raise SystemExit(
            "requests is not installed.  `pip install requests` first."
        )
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
            },
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[fitzmaurice] GET {url} failed: {exc}", file=sys.stderr)
        return None
    if r.status_code != 200:
        return None
    return r.text


def _extract_chart_ids_by_position(html: str) -> dict[str, str]:
    """Find the four Datawrapper iframes and match each to its
    position (QB/RB/WR/TE) by inspecting the nearest preceding
    heading.  Returns ``{position: chart_id}``.

    FantasyPros lays the article out as::

        <h3>Dynasty Trade Values: Quarterbacks</h3>
        <iframe ... src="https://datawrapper.dwcdn.net/yqKj2/1/" ...>
        <h3>Dynasty Trade Values: Running Backs</h3>
        <iframe ... src="https://datawrapper.dwcdn.net/ZVpNh/1/" ...>

    We scan sequentially, keeping track of the last position heading
    we saw, and map each iframe's chart_id to that position.
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        raise SystemExit(
            "beautifulsoup4 not installed.  `pip install beautifulsoup4`."
        )
    soup = BeautifulSoup(html, "html.parser")
    # Walk the document tree in source order, tracking the most
    # recent heading we saw for each position match.
    out: dict[str, str] = {}
    current_pos: str | None = None
    # Only look in the article body (skip footer / sidebar).  FP
    # wraps the article in <article> or <main> on most templates.
    scope = soup.find("article") or soup.find("main") or soup
    for node in scope.find_all(["h2", "h3", "iframe"]):
        if node.name in ("h2", "h3"):
            text = node.get_text(" ", strip=True)
            for pos, needles in _POSITION_HEADINGS:
                if any(n.lower() in text.lower() for n in needles):
                    current_pos = pos
                    break
            else:
                # Non-position heading (e.g. "Dynasty Rookie Draft Pick
                # Values") — clear the current position so any iframe
                # belonging to a non-player chart doesn't get stamped.
                current_pos = None
        elif node.name == "iframe":
            src = node.get("src") or ""
            m = re.search(r"datawrapper\.dwcdn\.net/([A-Za-z0-9]+)/", src)
            if not m:
                continue
            chart_id = m.group(1)
            if current_pos and current_pos not in out:
                out[current_pos] = chart_id
    return out


def _fetch_chart_csv(chart_id: str) -> str | None:
    """Fetch the Datawrapper dataset CSV (tab-separated)."""
    try:
        import requests
    except ImportError:
        raise SystemExit(
            "requests is not installed.  `pip install requests` first."
        )
    url = f"https://datawrapper.dwcdn.net/{chart_id}/1/dataset.csv"
    try:
        r = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) "
                              "AppleWebKit/537.36 Chrome/131",
                "Referer": "https://www.fantasypros.com/",
            },
            timeout=20,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[fitzmaurice] chart {chart_id} fetch failed: {exc}",
              file=sys.stderr)
        return None
    if r.status_code != 200:
        print(f"[fitzmaurice] chart {chart_id} status={r.status_code}",
              file=sys.stderr)
        return None
    return r.text


def _parse_chart_rows(csv_text: str, position: str) -> list[dict]:
    """Parse one Datawrapper TSV and return ``[{name, team, value}]``.

    Picks the value column per the per-position priority list.  Rows
    whose value does not parse as a positive number (e.g. FP's
    trailing "All Other <POS>s	1" row with value 1 — a filler bucket
    that should not enter the blend) are dropped.
    """
    # Datawrapper's CSV is tab-separated despite the .csv extension.
    rdr = csv.DictReader(csv_text.splitlines(), delimiter="\t")
    col_choices = _POSITION_VALUE_COLUMNS.get(position, ("Trade Value",))
    rows_out: list[dict] = []
    for row in rdr:
        name = (row.get("Name") or row.get("name") or "").strip()
        if not name:
            continue
        # Skip FP's trailing "All Other <Position>s" bucket row.
        if name.lower().startswith("all other "):
            continue
        team = (row.get("Team") or row.get("team") or "").strip()
        raw_val: str | None = None
        for col in col_choices:
            if col in row and row[col] not in (None, ""):
                raw_val = str(row[col]).strip()
                if raw_val:
                    break
        if raw_val is None:
            continue
        try:
            val = int(float(raw_val))
        except (TypeError, ValueError):
            continue
        # Filler bucket rows sometimes carry value 1; skip them so
        # they don't pollute the tail of the combined pool.
        if val <= 1:
            continue
        rows_out.append({
            "name": name,
            "team": team,
            "position": position,
            "value": val,
        })
    return rows_out


def _write_csv(path: Path, rows: list[dict]) -> int:
    """Write the combined ``name,team,position,value,rank`` CSV.

    ``rank`` is a 1-indexed global rank over the value-sorted set — the
    contract-side reader routes this source through the rank-signal
    path (see ``_SOURCE_CSV_PATHS["fantasyProsFitzmaurice"]`` in
    ``src/api/data_contract.py``): without a ``rank`` column in the
    CSV, that join would silently produce zero coverage.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    # Sort by value desc so the top player is the first row.
    rows_sorted = sorted(rows, key=lambda r: -int(r["value"]))
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "team", "position", "value", "rank"])
        for idx, r in enumerate(rows_sorted, start=1):
            w.writerow([r["name"], r["team"], r["position"], r["value"], idx])
    return len(rows_sorted)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape but don't write the CSV.")
    parser.add_argument(
        "--url", metavar="ARTICLE_URL",
        help="Skip URL discovery and use this article URL directly.",
    )
    args = parser.parse_args()

    candidate_urls: list[str] = (
        [args.url] if args.url else _build_candidate_urls()
    )
    html: str | None = None
    used_url: str | None = None
    for candidate in candidate_urls:
        print(f"[fitzmaurice] trying {candidate}")
        html = _fetch_article_html(candidate)
        if html is not None:
            used_url = candidate
            print(f"[fitzmaurice] fetched article ({len(html):,} bytes)")
            break
    if html is None or used_url is None:
        print(
            "[fitzmaurice] ERROR: could not fetch any candidate "
            "article URL.  Monthly update may not have been published "
            "yet — retry in a day.  URLs tried:",
            file=sys.stderr,
        )
        for url in candidate_urls:
            print(f"  {url}", file=sys.stderr)
        return 1

    chart_ids = _extract_chart_ids_by_position(html)
    print(f"[fitzmaurice] detected charts: {chart_ids}")
    if set(chart_ids) != {"QB", "RB", "WR", "TE"}:
        missing = sorted({"QB", "RB", "WR", "TE"} - set(chart_ids))
        print(
            f"[fitzmaurice] WARN: missing chart IDs for {missing} — "
            f"FP article structure may have changed.",
            file=sys.stderr,
        )
        if not chart_ids:
            return 1

    all_rows: list[dict] = []
    for position in ("QB", "RB", "WR", "TE"):
        chart_id = chart_ids.get(position)
        if chart_id is None:
            continue
        csv_text = _fetch_chart_csv(chart_id)
        if csv_text is None:
            print(
                f"[fitzmaurice] WARN: chart {chart_id} ({position}) "
                f"fetch failed — dropping {position} from this run.",
                file=sys.stderr,
            )
            continue
        rows = _parse_chart_rows(csv_text, position)
        print(f"[fitzmaurice] {position} ({chart_id}): parsed {len(rows)} rows")
        all_rows.extend(rows)

    if not all_rows:
        print("[fitzmaurice] ERROR: no rows extracted from any position",
              file=sys.stderr)
        return 1

    # Sanity floor — each position should have at least ~20 rows in
    # a normal chart.  A big shortfall suggests FP changed the
    # Datawrapper layout.
    pos_counts: dict[str, int] = {}
    for r in all_rows:
        pos_counts[r["position"]] = pos_counts.get(r["position"], 0) + 1
    print(f"[fitzmaurice] position counts: {pos_counts}")
    for pos in ("QB", "RB", "WR", "TE"):
        if pos_counts.get(pos, 0) < 10:
            print(
                f"[fitzmaurice] WARN: {pos} only has "
                f"{pos_counts.get(pos, 0)} rows — expected ≥10.",
                file=sys.stderr,
            )

    if args.dry_run:
        print(
            f"[fitzmaurice] dry-run: {len(all_rows)} total rows "
            f"(top 5 by value):"
        )
        for r in sorted(all_rows, key=lambda r: -r["value"])[:5]:
            print(
                f"  {r['position']:<3} {r['name']:<25} "
                f"{r['team']:<4} value={r['value']}"
            )
        return 0

    count = _write_csv(OUT_PATH, all_rows)
    print(f"[fitzmaurice] wrote {count} rows → {OUT_PATH.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
