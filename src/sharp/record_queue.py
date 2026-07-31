"""Fair, resumable ordering for the Sharp Tracker season-records crawl.

The records crawler has a hard per-run Sleeper API budget. Feeding it the
same insertion-ordered league list every day means a large graph can spend
that budget re-reading the same first leagues forever while later leagues
never receive a first pass. This module turns the discovered
sharp-eligible leagues into a round-robin queue:

* leagues with no stored season rows are first;
* previously crawled leagues follow, oldest crawl first;
* ties are stable by league id.

``manager_seasons`` always receives a row for the current/root league when a
crawl reaches its rosters, including in-season leagues. Its latest
``crawled_ms`` is therefore a durable, idempotent cursor without adding a
second queue table or competing state machine.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from src.intel import ledger


def prioritize_league_ids(
    league_ids: Iterable[str],
    last_crawled_ms: Mapping[str, int | None],
) -> list[str]:
    """Return unique league ids in fair crawl order.

    Uncrawled leagues sort before crawled leagues. Among crawled leagues,
    the oldest successful write sorts first so repeated budgeted runs rotate
    through the full graph instead of restarting at the same prefix.
    """

    unique: set[str] = set()
    for league_id in league_ids:
        if league_id is None:
            continue
        normalized = str(league_id).strip()
        if normalized:
            unique.add(normalized)

    def key(league_id: str) -> tuple[int, int, str]:
        raw = last_crawled_ms.get(league_id)
        if raw is None:
            return (0, 0, league_id)
        try:
            crawled = int(raw)
        except (TypeError, ValueError):
            return (0, 0, league_id)
        return (1, crawled, league_id)

    return sorted(unique, key=key)


def _queue_inputs(*, ledger_path: Path | None = None) -> tuple[list[str], dict[str, int]]:
    conn = ledger.connect(ledger_path)
    try:
        league_rows = conn.execute("SELECT league_id, settings_json FROM leagues").fetchall()
        crawl_rows = conn.execute(
            """
            SELECT league_id, MAX(crawled_ms) AS last_crawled_ms
              FROM manager_seasons
             GROUP BY league_id
            """
        ).fetchall()
    finally:
        conn.close()

    eligible: list[str] = []
    for row in league_rows:
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (TypeError, ValueError):
            continue
        if settings.get("sharpEligible"):
            eligible.append(str(row["league_id"]))

    last_crawled = {
        str(row["league_id"]): int(row["last_crawled_ms"])
        for row in crawl_rows
        if row["last_crawled_ms"] is not None
    }
    return eligible, last_crawled


def prioritized_league_ids(*, ledger_path: Path | None = None) -> list[str]:
    """Return every sharp-eligible league in resumable crawl order."""

    eligible, last_crawled = _queue_inputs(ledger_path=ledger_path)
    return prioritize_league_ids(eligible, last_crawled)


def queue_stats(*, ledger_path: Path | None = None) -> dict[str, Any]:
    """Inspectable queue coverage for logs and operator diagnostics."""

    eligible, last_crawled = _queue_inputs(ledger_path=ledger_path)
    unique_eligible = {str(league_id) for league_id in eligible}
    crawled = unique_eligible.intersection(last_crawled)
    timestamps = [last_crawled[league_id] for league_id in crawled]
    return {
        "eligibleLeagues": len(unique_eligible),
        "uncrawledLeagues": len(unique_eligible - crawled),
        "crawledLeagues": len(crawled),
        "oldestCrawlMs": min(timestamps) if timestamps else None,
        "newestCrawlMs": max(timestamps) if timestamps else None,
    }
