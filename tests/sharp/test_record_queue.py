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
