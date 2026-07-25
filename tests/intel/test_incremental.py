"""Incremental transaction fetching: created-timestamp boundary with
txId tie-breaking, and the offseason all-in-week-1 degeneracy."""

from __future__ import annotations

from src.intel import crawler
from tests.intel.conftest import (
    DAY_MS,
    NOW_MS,
    FakeSleeper,
    leagues_url,
    make_league,
    make_roster,
    make_waiver_tx,
    rosters_url,
    state_url,
    tx_url,
)

SEASON = "2026"


def _responses_with_txs(txs):
    return {
        state_url(): {"week": 1, "season_type": "off", "league_season": SEASON},
        leagues_url("A", SEASON): [make_league("L1")],
        rosters_url("L1"): [make_roster(1, "A", players=["held1"])],
        tx_url("L1", 1): txs,
    }


def _crawl(responses, prev_state=None):
    fake = FakeSleeper(responses)
    return crawler.crawl(
        ["A"], SEASON, prev_state, budget=900, sleep_s=0, http_get=fake, now_ms=NOW_MS
    )


class TestBoundaryTies:
    def test_boundary_txid_ties_at_max_created(self):
        boundary_ts = NOW_MS - DAY_MS
        tx1 = make_waiver_tx("tx1", boundary_ts, 1, add_player="p1")
        tx2 = make_waiver_tx("tx2", boundary_ts, 1, add_player="p2")

        result1 = _crawl(_responses_with_txs([tx1, tx2]))
        fs = result1.state["leagues"]["L1"]["fetchState"]
        assert fs["maxCreatedSeen"] == boundary_ts
        assert sorted(fs["boundaryTxIds"]) == ["tx1", "tx2"]
        assert result1.new_event_count == 2

        # Run 2: a THIRD transaction lands at exactly the same created
        # timestamp (tie at the boundary).  Only it produces events.
        tx3 = make_waiver_tx("tx3", boundary_ts, 1, add_player="p3")
        result2 = _crawl(_responses_with_txs([tx1, tx2, tx3]), prev_state=result1.state)
        assert result2.new_event_count == 1
        assert {e["assetId"] for e in result2.state["events"]} == {"p1", "p2", "p3"}
        fs2 = result2.state["leagues"]["L1"]["fetchState"]
        assert fs2["maxCreatedSeen"] == boundary_ts
        assert sorted(fs2["boundaryTxIds"]) == ["tx1", "tx2", "tx3"]

    def test_older_transactions_below_boundary_skipped(self):
        newer = make_waiver_tx("new", NOW_MS - DAY_MS, 1, add_player="pnew")
        result1 = _crawl(_responses_with_txs([newer]))

        # Run 2 re-serves an OLDER transaction (below maxCreatedSeen)
        # that run 1 never saw — it must not be ingested.
        older = make_waiver_tx("old", NOW_MS - 2 * DAY_MS, 1, add_player="pold")
        result2 = _crawl(_responses_with_txs([older, newer]), prev_state=result1.state)
        assert result2.new_event_count == 0
        assert {e["assetId"] for e in result2.state["events"]} == {"pnew"}


class TestOffseasonWeekOneDedup:
    def test_refetching_week_one_produces_no_duplicates(self):
        # Offseason: every transaction sits in week 1.  Three crawls
        # over the same feed must count each transaction exactly once.
        txs = [
            make_waiver_tx("w1", NOW_MS - 3 * DAY_MS, 1, add_player="p1", bid=7),
            make_waiver_tx("w2", NOW_MS - 2 * DAY_MS, 1, add_player="p2", drop_player="p9"),
        ]
        responses = _responses_with_txs(txs)

        state = None
        for _ in range(3):
            result = _crawl(responses, prev_state=state)
            state = result.state
        assert len(state["events"]) == 3  # p1 add, p2 add, p9 drop
        event_ids = [e["eventId"] for e in state["events"]]
        assert len(event_ids) == len(set(event_ids))

    def test_event_dedupe_survives_lost_fetch_state(self):
        # Even if fetchState is wiped (e.g. a budget-interrupted league
        # never advanced it), the global eventId dedupe holds.
        txs = [make_waiver_tx("w1", NOW_MS - DAY_MS, 1, add_player="p1")]
        responses = _responses_with_txs(txs)
        result1 = _crawl(responses)
        state = result1.state
        state["leagues"]["L1"]["fetchState"] = {}

        result2 = _crawl(responses, prev_state=state)
        assert result2.new_event_count == 0
        assert len(result2.state["events"]) == 1


class TestBackfillWindow:
    def test_first_run_backfills_at_most_six_weeks(self):
        responses = {
            state_url(): {"week": 10, "season_type": "regular", "league_season": SEASON},
            leagues_url("A", SEASON): [make_league("L1")],
            rosters_url("L1"): [make_roster(1, "A")],
        }
        for w in range(1, 19):
            responses[tx_url("L1", w)] = []
        fake = FakeSleeper(responses)
        crawler.crawl(["A"], SEASON, None, budget=900, sleep_s=0, http_get=fake, now_ms=NOW_MS)
        fetched_weeks = sorted(
            int(c.rsplit("/", 1)[1]) for c in fake.calls if "/transactions/" in c
        )
        assert fetched_weeks == [5, 6, 7, 8, 9, 10]

    def test_backfill_age_stop_and_thirty_day_filter(self):
        # Week 10 has only ancient transactions (older than 30 days):
        # they are filtered out AND the walk stops before older weeks.
        ancient = make_waiver_tx("anc", NOW_MS - 40 * DAY_MS, 1, add_player="pold")
        responses = {
            state_url(): {"week": 10, "season_type": "regular", "league_season": SEASON},
            leagues_url("A", SEASON): [make_league("L1")],
            rosters_url("L1"): [make_roster(1, "A")],
            tx_url("L1", 10): [ancient],
            tx_url("L1", 9): [make_waiver_tx("w9", NOW_MS - 41 * DAY_MS, 1, add_player="p9")],
        }
        fake = FakeSleeper(responses)
        result = crawler.crawl(
            ["A"], SEASON, None, budget=900, sleep_s=0, http_get=fake, now_ms=NOW_MS
        )
        tx_calls = [c for c in fake.calls if "/transactions/" in c]
        assert tx_calls == [tx_url("L1", 10)]  # stopped after the stale week
        assert result.state["events"] == []  # >30d events filtered

    def test_steady_state_fetches_previous_week_within_rollover_grace(self):
        # A backfilled league whose week just rolled 9 → 10 fetches
        # week 9 too while inside the 48h grace window.
        responses = {
            state_url(): {"week": 9, "season_type": "regular", "league_season": SEASON},
            leagues_url("A", SEASON): [make_league("L1")],
            rosters_url("L1"): [make_roster(1, "A")],
        }
        for w in range(1, 19):
            responses[tx_url("L1", w)] = []
        result1 = _crawl_with(responses, None, now_ms=NOW_MS - 3 * DAY_MS)

        responses[state_url()] = {"week": 10, "season_type": "regular", "league_season": SEASON}
        fake = FakeSleeper(responses)
        crawler.crawl(
            ["A"], SEASON, result1.state, budget=900, sleep_s=0, http_get=fake, now_ms=NOW_MS
        )
        fetched_weeks = sorted(
            int(c.rsplit("/", 1)[1]) for c in fake.calls if "/transactions/" in c
        )
        assert fetched_weeks == [9, 10]


def _crawl_with(responses, prev_state, now_ms):
    fake = FakeSleeper(responses)
    return crawler.crawl(
        ["A"], SEASON, prev_state, budget=900, sleep_s=0, http_get=fake, now_ms=now_ms
    )
