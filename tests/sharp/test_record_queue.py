import json

import pytest

from src.sharp import record_queue
from src.sharp.record_queue import prioritize_league_ids


def test_uncrawled_leagues_are_prioritized_before_oldest_crawled() -> None:
    assert prioritize_league_ids(
        ["league-b", "league-a", "league-c", "league-d"],
        {
            "league-a": 200,
            "league-b": 100,
            "league-d": 300,
        },
    ) == ["league-c", "league-b", "league-a", "league-d"]


def test_queue_deduplicates_strips_and_stably_orders_uncrawled_leagues() -> None:
    assert prioritize_league_ids(
        [" league-b ", "league-a", "league-b", "", "league-c"],
        {},
    ) == ["league-a", "league-b", "league-c"]


def test_invalid_crawl_timestamp_is_treated_as_uncrawled() -> None:
    assert prioritize_league_ids(
        ["league-a", "league-b", "league-c"],
        {
            "league-a": "not-a-timestamp",
            "league-b": 100,
            "league-c": None,
        },
    ) == ["league-a", "league-c", "league-b"]


# ── queue_stats: the staleness figure operators actually read ───────
#
# ``oldestCrawlMs`` had no deterministic coverage on either producer
# (`record_queue.queue_stats` and `transactions.crawl_coverage`), so the
# property was confirmed by reading the source. These pin it.


@pytest.fixture()
def ledger_db(tmp_path, monkeypatch):
    from src.intel import ledger, store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    yield tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.reset_setup_cache()


def _seed(path, leagues, crawls):
    """``leagues``: {league_id: sharp_eligible}.  ``crawls``: {league_id: ms}."""
    from src.intel import ledger

    conn = ledger.connect(path)
    try:
        for league_id, eligible in leagues.items():
            conn.execute(
                "INSERT OR REPLACE INTO leagues(league_id, settings_json) VALUES (?, ?)",
                (league_id, json.dumps({"sharpEligible": bool(eligible)})),
            )
        for index, (league_id, crawled_ms) in enumerate(crawls.items()):
            conn.execute(
                "INSERT OR REPLACE INTO manager_seasons"
                "(league_id, season, user_id, crawled_ms) VALUES (?, ?, ?, ?)",
                (league_id, "2026", f"u{index}", crawled_ms),
            )
        conn.commit()
    finally:
        conn.close()


def test_oldest_crawl_is_the_minimum_not_the_most_recent(ledger_db) -> None:
    """The figure answers "how stale is the STALEST league".

    Publishing the newest instead would make a badly-lagging queue look
    current — the reassuring direction, and therefore the one that goes
    unnoticed. ``newestCrawlMs`` is published beside it precisely so the two
    questions stay separate, and this asserts they are not the same number.
    """
    _seed(
        ledger_db,
        {"L1": True, "L2": True, "L3": True},
        {"L1": 300, "L2": 100, "L3": 200},
    )
    stats = record_queue.queue_stats(ledger_path=ledger_db)
    assert stats["crawledLeagues"] == 3, "fixture must crawl three leagues or it proves nothing"
    assert stats["oldestCrawlMs"] == 100
    assert stats["newestCrawlMs"] == 300
    assert stats["oldestCrawlMs"] != stats["newestCrawlMs"]


def test_no_crawled_league_publishes_none_never_zero(ledger_db) -> None:
    """MISSING IS NEVER ZERO, on the axis where zero is the worst value.

    These are epoch milliseconds, so ``0`` is 1970 — the oldest timestamp
    expressible. "We have never crawled anything" would render as "our crawl
    is 56 years stale", and any consumer comparing against a staleness budget
    would read an absence as a maximal alarm.
    """
    _seed(ledger_db, {"L1": True, "L2": True}, {})
    stats = record_queue.queue_stats(ledger_path=ledger_db)
    assert stats["crawledLeagues"] == 0
    assert stats["oldestCrawlMs"] is None
    assert stats["newestCrawlMs"] is None
    assert stats["oldestCrawlMs"] != 0
    # The denominator survives, so "nothing crawled" keeps its own scale and
    # cannot read as "nothing eligible".
    assert stats["eligibleLeagues"] == 2
    assert stats["uncrawledLeagues"] == 2


def test_a_crawl_for_an_ineligible_league_does_not_move_the_oldest(ledger_db) -> None:
    """The figure is scoped to the SHARP-ELIGIBLE set.

    An older crawl of a league outside that set must not drag the number
    down, or the queue would report staleness it is not responsible for.
    """
    _seed(
        ledger_db,
        {"L1": True, "L2": False},
        {"L1": 500, "L2": 1},
    )
    stats = record_queue.queue_stats(ledger_path=ledger_db)
    assert stats["eligibleLeagues"] == 1
    assert stats["oldestCrawlMs"] == 500
