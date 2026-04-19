#!/usr/bin/env python3
"""Fetch Justin Boone's Yahoo dynasty trade value charts and write a source CSV.

Justin Boone publishes monthly dynasty trade value charts on Yahoo Sports
for QB, RB, WR, and TE.  Each chart is a single HTML ``<table
class="content-table">`` inside the article body, with columns like::

    Rank | Player | 1QB | 2QB            (QB chart)
    Rank | Player | PPR                  (RB and WR charts)
    Rank | Player | PPR | TE Prem.       (TE chart)

Risk It To Get The Brisket is a Superflex + TE-premium league, so this
scraper pulls the ``2QB`` column for QBs and the ``TE Prem.`` column for
TEs (falling back to ``PPR`` for RB and WR, which have no format split).
All four positions are already on a single cross-positional scale by
design — Boone's 2QB QB values are comparable to his PPR RB/WR values and
his TE-premium TE values, which is how his charts are meant to be read.

"Find the latest monthly update"
---------------------------------

Yahoo does not publish a dedicated Justin Boone author index page or
RSS feed.  Instead, older article URLs serve a 308 redirect to the most
recent monthly update in the same series.  For example, the January
2026 RB URL (``...running-back-dynasty-rankings-...-january-183116536``)
redirects to the April 2026 RB URL
(``...rb-dynasty-rankings-and-trade-value-chart-updates-183116190``).

The scraper relies on that redirect chain: we keep a list of known
"seed" URLs per position (one per historical update, appended in
publish order) and request each seed with ``allow_redirects=True``.
Yahoo resolves to the newest live article, we parse it, done.  When
the monthly update stops redirecting (because Yahoo stops maintaining
the chain), append the new canonical URL to ``_SEED_URLS`` below.

A best-effort publication-date check warns (but does not fail) when
the resolved article appears older than ``_STALE_DAYS`` days.

Output CSV
----------

Written to ``CSVs/site_raw/yahooBoone.csv`` with columns::

    name, pos, rank, boone_value

``rank`` holds the **competition rank** computed across all four
positions combined — ties share a rank and the next rank is skipped
(1, 2, 3, 3, 5).  Both canonical readers pick this column up: the
legacy-payload enrichment in ``src/api/data_contract.py``
(``_parse_source_csv_cached`` with ``signal=rank``) resolves via
``_RANK_ALIASES``, and the modular pipeline's ``ScraperBridgeAdapter``
falls back to the ``rank`` column when no ``value`` column is present.
The ``boone_value`` column carries the original published chart
number for human eyeballing and is ignored by both readers.

Run::

    python3 scripts/fetch_yahoo_boone.py [--mirror-data-dir] [--dry-run]

Exit codes:
    0 — success, CSV written
    1 — soft failure (fetch / parse error for all positions, or zero rows)
    2 — schema regression (no parseable table on a successful response,
        or total row count below ``_YB_ROW_COUNT_FLOOR``)
"""
from __future__ import annotations

import argparse
import csv
import html as html_module
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("[fetch_yahoo_boone] requests is not installed", file=sys.stderr)
    sys.exit(1)


UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DST = REPO_ROOT / "CSVs" / "site_raw" / "yahooBoone.csv"
DATA_DIR_DST = REPO_ROOT / "data" / "exports" / "latest" / "site_raw" / "yahooBoone.csv"


# Seed URLs per position — Yahoo redirects each stale entry to the
# newest live article in the same monthly series.  If the redirect
# chain ever breaks for a position, append the new live URL to that
# position's list; the scraper tries each entry in order and uses the
# first successful fetch.
_SEED_URLS: dict[str, list[str]] = {
    "QB": [
        "https://sports.yahoo.com/fantasy/article/fantasy-football-dynasty-rankings-2026-trade-value-charts-justin-boone-qb-182445989.html",
    ],
    "RB": [
        "https://sports.yahoo.com/fantasy/article/justin-boones-2026-running-back-dynasty-rankings-and-trade-value-charts-for-january-183116536.html",
    ],
    "WR": [
        "https://sports.yahoo.com/fantasy/article/justin-boones-2026-wide-receiver-dynasty-rankings-and-trade-value-charts-for-january-182932060.html",
    ],
    "TE": [
        "https://sports.yahoo.com/fantasy/article/fantasy-football-dynasty-rankings-2026-trade-value-charts-justin-boone-te-182938019.html",
    ],
}

# Which HTML column holds the value we want, per position.  The rest
# are ignored (e.g. 1QB is dropped because the league format is 2QB).
_VALUE_COLUMN: dict[str, str] = {
    "QB": "2QB",
    "RB": "PPR",
    "WR": "PPR",
    "TE": "TE Prem.",
}

# Row-count floor for total (QB+RB+WR+TE combined).  Boone's April
# 2026 charts held ~100 QBs, ~80 RBs, ~130 WRs, ~70 TEs = ~380 rows.
# Floor at ~60% of observed so a real regression trips exit 2.
_YB_ROW_COUNT_FLOOR: int = 225

# Warn if the resolved article's publication date is older than this
# many days — Boone updates roughly monthly, so anything beyond ~45
# days suggests Yahoo stopped redirecting and the seed list needs
# maintenance.  Warning only, never fatal.
_STALE_DAYS: int = 45


@dataclass(frozen=True)
class YahooRow:
    name: str
    pos: str  # QB | RB | WR | TE
    value: int


class YahooBooneSchemaError(RuntimeError):
    """Raised when the HTML layout has changed unexpectedly."""


# ── HTTP fetch ─────────────────────────────────────────────────────────
def _fetch_html(url: str, *, timeout: int = 30) -> tuple[str, str]:
    """Fetch an article; return (final_url, html_body)."""
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    return resp.url, resp.text


# ── Table extraction ──────────────────────────────────────────────────
_TABLE_RE = re.compile(
    r'<table\s+class="content-table"[^>]*>(.*?)</table>',
    re.DOTALL | re.IGNORECASE,
)
_ROW_RE = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_CELL_RE = re.compile(r"<t[hd][^>]*>(.*?)</t[hd]>", re.DOTALL | re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean_cell(raw: str) -> str:
    text = _TAG_RE.sub("", raw)
    text = html_module.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    return text


def _extract_table_rows(page_html: str) -> list[list[str]]:
    """Return list of cell lists (first entry = header, rest = data)."""
    m = _TABLE_RE.search(page_html)
    if not m:
        raise YahooBooneSchemaError("no <table class='content-table'> found")
    table_html = m.group(1)
    rows: list[list[str]] = []
    for row_match in _ROW_RE.finditer(table_html):
        cells = [_clean_cell(c.group(1)) for c in _CELL_RE.finditer(row_match.group(1))]
        if cells:
            rows.append(cells)
    if len(rows) < 2:
        raise YahooBooneSchemaError(f"table had only {len(rows)} row(s)")
    return rows


def _parse_position_table(page_html: str, position: str) -> list[YahooRow]:
    """Parse one article's trade-value table into ``YahooRow`` records."""
    rows = _extract_table_rows(page_html)
    header = [c.strip() for c in rows[0]]
    wanted = _VALUE_COLUMN[position]

    try:
        player_idx = next(
            i for i, col in enumerate(header) if col.lower() == "player"
        )
    except StopIteration as exc:
        raise YahooBooneSchemaError(
            f"{position}: no 'Player' column in header {header!r}"
        ) from exc

    try:
        value_idx = next(
            i for i, col in enumerate(header) if col.lower() == wanted.lower()
        )
    except StopIteration as exc:
        raise YahooBooneSchemaError(
            f"{position}: no '{wanted}' column in header {header!r}"
        ) from exc

    out: list[YahooRow] = []
    for row in rows[1:]:
        if len(row) <= max(player_idx, value_idx):
            continue
        name = row[player_idx].strip()
        raw_val = row[value_idx].strip()
        if not name or not raw_val:
            continue
        try:
            value_int = int(float(raw_val))
        except (TypeError, ValueError):
            continue
        out.append(YahooRow(name=name, pos=position, value=value_int))
    return out


# ── Article metadata ──────────────────────────────────────────────────
_PUB_RE = re.compile(
    r'"datePublished"\s*:\s*"([0-9T:\-\+Z\.]+)"',
    re.IGNORECASE,
)
_MOD_RE = re.compile(
    r'"dateModified"\s*:\s*"([0-9T:\-\+Z\.]+)"',
    re.IGNORECASE,
)


def _extract_article_date(page_html: str) -> datetime | None:
    """Pull the JSON-LD dateModified / datePublished out of the page."""
    for pattern in (_MOD_RE, _PUB_RE):
        m = pattern.search(page_html)
        if not m:
            continue
        raw = m.group(1).replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            continue
    return None


# ── Rank synthesis ────────────────────────────────────────────────────
def _assign_ranks(rows: list[YahooRow]) -> list[tuple[YahooRow, int]]:
    """Competition-rank rows by value descending.

    Ties share a rank and the next rank is skipped (1, 2, 3, 3, 5).
    Stable secondary sort by (position, name) keeps the CSV
    deterministic across runs.
    """
    sorted_rows = sorted(rows, key=lambda r: (-r.value, r.pos, r.name.lower()))
    ranked: list[tuple[YahooRow, int]] = []
    last_value: int | None = None
    last_rank = 0
    for idx, row in enumerate(sorted_rows, start=1):
        if last_value is None or row.value != last_value:
            last_rank = idx
            last_value = row.value
        ranked.append((row, last_rank))
    return ranked


# ── CSV writer ────────────────────────────────────────────────────────
def _write_csv(path: Path, ranked: list[tuple[YahooRow, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # ``rank`` is the pipeline signal (competition rank across all
    # positions), named to match the _RANK_ALIASES alias list in
    # src/api/data_contract.py so the legacy-payload enrichment reader
    # picks it up.  ``boone_value`` preserves the original Yahoo chart
    # number for human eyeballing; both readers ignore it.
    fields = ["name", "pos", "rank", "boone_value"]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row, rank in ranked:
            writer.writerow(
                {
                    "name": row.name,
                    "pos": row.pos,
                    "rank": rank,
                    "boone_value": row.value,
                }
            )


# ── Orchestration ─────────────────────────────────────────────────────
def _fetch_one_position(position: str, urls: list[str]) -> tuple[list[YahooRow], str, datetime | None]:
    """Try each seed URL for a position; return (rows, final_url, pub_date)."""
    last_exc: Exception | None = None
    for url in urls:
        try:
            final_url, body = _fetch_html(url)
        except Exception as exc:
            last_exc = exc
            continue
        try:
            parsed = _parse_position_table(body, position)
        except YahooBooneSchemaError as exc:
            last_exc = exc
            continue
        if not parsed:
            last_exc = RuntimeError(f"{position}: table parsed to zero rows")
            continue
        return parsed, final_url, _extract_article_date(body)
    raise RuntimeError(f"{position}: all {len(urls)} seed URL(s) failed: {last_exc}")


def fetch_all(
    seed_urls: dict[str, list[str]] | None = None,
    *,
    fetcher=_fetch_html,
) -> tuple[list[YahooRow], list[str]]:
    """Fetch every position; return (combined rows, warning strings).

    Exposed (and parameterised on ``fetcher``) so tests can inject a
    fake HTTP client without hitting the network.
    """
    seeds = seed_urls if seed_urls is not None else _SEED_URLS
    warnings: list[str] = []
    combined: list[YahooRow] = []
    now = datetime.now(timezone.utc)

    for position, urls in seeds.items():
        last_exc: Exception | None = None
        parsed: list[YahooRow] = []
        final_url = ""
        pub_date: datetime | None = None
        for url in urls:
            try:
                final_url, body = fetcher(url)
            except Exception as exc:
                last_exc = exc
                continue
            try:
                parsed = _parse_position_table(body, position)
            except YahooBooneSchemaError as exc:
                last_exc = exc
                parsed = []
                continue
            pub_date = _extract_article_date(body)
            if parsed:
                last_exc = None
                break
            last_exc = RuntimeError(f"{position}: table parsed to zero rows")

        if not parsed:
            warnings.append(f"{position}: fetch/parse failed — {last_exc}")
            continue

        if pub_date is not None:
            age = (now - pub_date.astimezone(timezone.utc)).days
            if age > _STALE_DAYS:
                warnings.append(
                    f"{position}: article is {age}d old (>{_STALE_DAYS}d) "
                    f"at {final_url} — check _SEED_URLS for a fresher entry"
                )
        combined.extend(parsed)
        print(
            f"[fetch_yahoo_boone] {position}: {len(parsed)} rows "
            f"from {final_url}"
        )

    return combined, warnings


# ── CLI entry ─────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=DEFAULT_DST,
        help="CSV path to write (default: CSVs/site_raw/yahooBoone.csv).",
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
    args = parser.parse_args(argv)

    try:
        rows, warnings = fetch_all()
    except Exception as exc:
        print(f"[fetch_yahoo_boone] unhandled fetch error: {exc}", file=sys.stderr)
        return 1

    for w in warnings:
        print(f"[fetch_yahoo_boone] WARN: {w}", file=sys.stderr)

    if not rows:
        print("[fetch_yahoo_boone] no rows extracted from any position", file=sys.stderr)
        return 1

    if len(rows) < _YB_ROW_COUNT_FLOOR:
        print(
            f"[fetch_yahoo_boone] row count below floor: "
            f"{len(rows)} < {_YB_ROW_COUNT_FLOOR}",
            file=sys.stderr,
        )
        return 2

    ranked = _assign_ranks(rows)

    pos_counts: dict[str, int] = {}
    for row in rows:
        pos_counts[row.pos] = pos_counts.get(row.pos, 0) + 1
    breakdown = " ".join(f"{p}={c}" for p, c in sorted(pos_counts.items()))
    print(f"[fetch_yahoo_boone] total={len(rows)} rows | {breakdown}")

    if args.dry_run:
        print("[fetch_yahoo_boone] --dry-run; not writing CSV")
        for row, rank in ranked[:5]:
            print(f"  rank={rank:>3} {row.pos} {row.name} (value={row.value})")
        return 0

    _write_csv(args.dest, ranked)
    print(f"[fetch_yahoo_boone] wrote {len(ranked)} rows -> {args.dest}")

    if args.mirror_data_dir:
        try:
            _write_csv(DATA_DIR_DST, ranked)
            print(f"[fetch_yahoo_boone] mirrored -> {DATA_DIR_DST}")
        except Exception as exc:
            print(
                f"[fetch_yahoo_boone] mirror failed: {exc}",
                file=sys.stderr,
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
