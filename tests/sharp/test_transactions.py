"""The sharp transaction crawl — the piece that was missing entirely.

Discovery mapped the graph and records scored it, but nothing ever
fetched those managers' trades, so the ledger held only Insider
Trading's league-mates.  These tests pin the crawl's scoping, its
budget behaviour, and the failure rules it inherits from the intel
crawler.
"""

from __future__ import annotations

import json

import pytest

from src.intel import crawler, ledger
from src.sharp import transactions

DAY_MS = 24 * 3600 * 1000
NOW = 1_800_000_000_000
BASE = crawler.SLEEPER_BASE


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    yield tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.reset_setup_cache()


def roster(rid, owner, co_owners=None):
    return {"roster_id": rid, "owner_id": owner, "co_owners": co_owners or [], "players": []}


def trade(tx_id, created, adds, drops):
    return {
        "transaction_id": tx_id,
        "type": "trade",
        "status": "complete",
        "created": created,
        "status_updated": created,
        "adds": adds,
        "drops": drops,
        "draft_picks": [],
        "roster_ids": sorted({*adds.values(), *drops.values()}),
    }


class FakeHttp:
    """Faithful enough to matter in two ways.

    Sleeper returns ``[]`` for a week with no transactions, NOT an
    error — so an undefined transactions week must be an empty list.
    Returning ``None`` there would look like a fetch failure and make
    every first-run backfill (which walks back to week 0) report dirty.
    An EXPLICIT ``None`` in ``responses`` is how a test asks for a real
    failure.
    """

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        if url in self.responses:
            return self.responses[url]
        if "/transactions/" in url:
            return []
        return None

    def count(self, url):
        return self.calls.count(url)


def responses_for(league="L1", week=2, txs=None):
    return {
        f"{BASE}/state/nfl": {"week": week},
        f"{BASE}/league/{league}/rosters": [roster(1, "A"), roster(2, "B")],
        f"{BASE}/league/{league}/transactions/{week}": txs
        if txs is not None
        else [trade("t1", NOW - DAY_MS, {"p1": 1}, {"p1": 2})],
    }


def _crawl(responses, league_ids=("L1",), ledger_path=None, budget=100, now_ms=NOW):
    http = FakeHttp(responses)
    result = transactions.crawl_transactions(
        league_ids=None if league_ids is None else list(league_ids),
        budget=budget,
        sleep_s=0.0,
        http_get=http,
        now_ms=now_ms,
        ledger_path=ledger_path,
    )
    return result, http


def _fetch_stamps(ledger_path):
    """The ``last_fetched_ms`` values actually stored, read back from the DB.

    Deliberately read from the ledger rather than assumed from the ``now_ms``
    the fixture passed in: the assertion is about what ``crawl_coverage``
    summarises, so its comparison set has to be the same rows it reads.
    """
    conn = ledger.connect(ledger_path)
    try:
        return [
            int(row["last_fetched_ms"])
            for row in conn.execute(
                "SELECT last_fetched_ms FROM sharp_league_fetch WHERE backfilled = 1"
            ).fetchall()
            if row["last_fetched_ms"] is not None
        ]
    finally:
        conn.close()


class TestItActuallyIngests:
    def test_a_trade_lands_in_the_ledger(self, db):
        result, _ = _crawl(responses_for(), ledger_path=db)
        assert result.movements_ingested == 2
        assert ledger.counts(path=db)["assetMovementCount"] == 2

    def test_both_sides_are_recorded(self, db):
        """The board filters to the qualified cohort at READ time, so
        both sides must exist for a sharp-vs-sharp disagreement to be
        visible at all."""
        _crawl(responses_for(), ledger_path=db)
        rows = ledger.asset_signals(path=db)
        row = next(r for r in rows if r["assetId"] == "p1")
        assert row["buys"] == 1
        assert row["sells"] == 1
        assert row["uniqueManagers"] == 2

    def test_movements_carry_the_roster_slot_key(self, db):
        """D10 applies here too — this crawl reuses the same extraction."""
        _crawl(responses_for(), ledger_path=db)
        conn = ledger.connect(db)
        try:
            ids = [
                r["movement_id"] for r in conn.execute("SELECT movement_id FROM asset_movements")
            ]
        finally:
            conn.close()
        assert all(":r" in mid for mid in ids)

    def test_rerunning_ingests_nothing_new(self, db):
        _crawl(responses_for(), ledger_path=db)
        before = ledger.counts(path=db)
        second, _ = _crawl(responses_for(), ledger_path=db)
        assert second.movements_ingested == 0
        assert ledger.counts(path=db) == before


class TestScoping:
    def test_only_the_named_leagues_are_fetched(self, db):
        resp = responses_for("L1")
        resp.update(responses_for("L2"))
        _, http = _crawl(resp, league_ids=["L1"], ledger_path=db)
        assert http.count(f"{BASE}/league/L1/rosters") == 1
        assert http.count(f"{BASE}/league/L2/rosters") == 0

    def test_no_eligible_leagues_is_a_clean_no_op(self, db):
        result, http = _crawl({}, league_ids=[], ledger_path=db)
        assert result.leagues_considered == 0
        assert result.movements_ingested == 0
        assert http.calls == [], "must not even ask for the NFL week"

    def test_defaults_to_the_sharp_eligible_set(self, db, monkeypatch):
        """Not merely 'discovered' — sharp-eligible means dynasty only
        and at least two seasons old."""
        seen = {}

        def fake(*, ledger_path=None):
            seen["called"] = True
            return ["L1"]

        monkeypatch.setattr(transactions.discovery, "sharp_eligible_league_ids", fake)
        result, _ = _crawl(responses_for(), league_ids=None, ledger_path=db)
        assert seen.get("called") is True
        assert result.leagues_considered == 1


class TestFailureRules:
    def test_a_failed_roster_fetch_skips_the_league_entirely(self, db):
        """Without a CURRENT owner map, attribution would be a guess —
        the intel crawler's rule, inherited."""
        resp = responses_for()
        resp[f"{BASE}/league/L1/rosters"] = None
        result, http = _crawl(resp, ledger_path=db)
        assert result.leagues_failed == 1
        assert result.errors["L1"] == "rosters_fetch_failed"
        assert http.count(f"{BASE}/league/L1/transactions/2") == 0
        assert ledger.counts(path=db)["assetMovementCount"] == 0

    def test_a_failed_week_does_not_advance_the_cursor(self, db):
        """Advancing past a week we failed to read would filter its
        transactions out permanently."""
        resp = responses_for()
        resp[f"{BASE}/league/L1/transactions/2"] = None
        result, _ = _crawl(resp, ledger_path=db)
        assert result.errors["L1"] == "transactions_fetch_failed"
        conn = ledger.connect(db)
        try:
            row = conn.execute("SELECT * FROM sharp_league_fetch WHERE league_id='L1'").fetchone()
        finally:
            conn.close()
        assert row["backfilled"] == 0
        assert int(row["max_created_ms"] or 0) == 0

    def test_a_recovered_week_ingests_on_the_next_run(self, db):
        resp = responses_for()
        resp[f"{BASE}/league/L1/transactions/2"] = None
        _crawl(resp, ledger_path=db)
        assert ledger.counts(path=db)["assetMovementCount"] == 0
        result, _ = _crawl(responses_for(), ledger_path=db)
        assert result.movements_ingested == 2

    def test_one_bad_league_does_not_stop_the_others(self, db):
        resp = responses_for("L1")
        resp.update(responses_for("L2"))
        resp[f"{BASE}/league/L1/rosters"] = None
        result, _ = _crawl(resp, league_ids=["L1", "L2"], ledger_path=db)
        assert result.leagues_failed == 1
        assert result.leagues_fetched == 1
        assert ledger.counts(path=db)["assetMovementCount"] == 2


class TestBudget:
    def test_a_capped_run_reports_what_it_did_not_reach(self, db):
        resp = responses_for("L1")
        resp.update(responses_for("L2"))
        # A first run backfills weeks 2/1/0, so L1 costs 4 calls on
        # top of the single /state/nfl call — leaving nothing for L2.
        result, _ = _crawl(resp, league_ids=["L1", "L2"], ledger_path=db, budget=5)
        assert result.leagues_pending == 1
        assert result.leagues_fetched == 1

    def test_pending_leagues_are_picked_up_next_run(self, db):
        resp = responses_for("L1")
        resp.update(responses_for("L2"))
        _crawl(resp, league_ids=["L1", "L2"], ledger_path=db, budget=5)
        result, _ = _crawl(resp, league_ids=["L1", "L2"], ledger_path=db, budget=100)
        assert result.leagues_fetched == 2

    def test_uncrawled_leagues_are_ordered_before_crawled_ones(self, db):
        """Otherwise a budget-capped run re-walks the same head forever
        and the tail of the graph is never reached."""
        state = {"L1": {"backfilled": True, "lastFetchedMs": NOW}}
        assert transactions._league_order(["L1", "L2"], state) == ["L2", "L1"]

    def test_stalest_first_among_already_crawled(self, db):
        state = {
            "L1": {"backfilled": True, "lastFetchedMs": NOW},
            "L2": {"backfilled": True, "lastFetchedMs": NOW - DAY_MS},
        }
        assert transactions._league_order(["L1", "L2"], state) == ["L2", "L1"]


class TestCoverageHonesty:
    def test_coverage_separates_crawled_from_eligible(self, db, monkeypatch):
        """'No signal' and 'not crawled yet' must never read the same."""
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1", "L2"],
        )
        _crawl(responses_for("L1"), league_ids=["L1"], ledger_path=db)
        cov = transactions.crawl_coverage(ledger_path=db)
        assert cov["sharpEligibleLeagues"] == 2
        assert cov["leaguesCrawled"] == 1
        assert cov["leaguesUncrawled"] == 1

    def test_oldest_crawl_is_the_minimum_not_the_most_recent(self, db, monkeypatch):
        """``oldestCrawlMs`` answers "how stale is the STALEST league".

        It is the number an operator reads to decide whether the crawl is
        keeping up, so publishing the newest timestamp instead would make a
        badly-lagging crawl look current — the reassuring direction, which is
        the one that goes unnoticed.

        Three leagues crawled a day apart: the answer must be the oldest of
        the three, and must not equal the newest.
        """
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1", "L2", "L3"],
        )
        for league, when in (("L1", NOW), ("L2", NOW - DAY_MS), ("L3", NOW - 2 * DAY_MS)):
            _crawl(responses_for(league), league_ids=[league], ledger_path=db, now_ms=when)

        cov = transactions.crawl_coverage(ledger_path=db)
        stamps = _fetch_stamps(db)
        assert len(stamps) == 3, "the fixture must crawl three leagues or it proves nothing"
        assert cov["oldestCrawlMs"] == min(stamps)
        assert cov["oldestCrawlMs"] != max(stamps), (
            "min and max coincide, so this fixture cannot tell them apart"
        )
        # ...and the denominator behaviour already pinned above is untouched.
        assert cov["sharpEligibleLeagues"] == 3
        assert cov["leaguesCrawled"] == 3

    def test_no_crawled_league_publishes_none_never_zero(self, db, monkeypatch):
        """MISSING IS NEVER ZERO, on the axis where zero is worst.

        ``oldestCrawlMs`` is an epoch millisecond, so ``0`` is 1970 — the
        oldest timestamp expressible. "We have never crawled anything" would
        therefore render as "our crawl is 56 years stale", and any consumer
        comparing against a staleness budget would read the empty state as a
        maximal alarm rather than as an absence.
        """
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1", "L2"],
        )
        cov = transactions.crawl_coverage(ledger_path=db)
        assert cov["leaguesCrawled"] == 0
        assert cov["oldestCrawlMs"] is None
        assert cov["oldestCrawlMs"] != 0
        # The denominator is still stated, so "nothing crawled" keeps its
        # own denominator and cannot read as "nothing eligible".
        assert cov["sharpEligibleLeagues"] == 2
        assert cov["leaguesUncrawled"] == 2


class TestWaiverSeparation:
    def test_waivers_are_stored_but_never_become_trade_buys(self, db):
        resp = responses_for(
            txs=[
                {
                    "transaction_id": "w1",
                    "type": "waiver",
                    "status": "complete",
                    "created": NOW - DAY_MS,
                    "adds": {"p9": 1},
                    "drops": {},
                    "draft_picks": [],
                    "settings": {"waiver_bid": 5},
                    "roster_ids": [1],
                }
            ]
        )
        result, _ = _crawl(resp, ledger_path=db)
        # The row is STORED — waiver activity is real data...
        assert result.movements_ingested == 1
        conn = ledger.connect(db)
        try:
            stored = conn.execute(
                "SELECT tx_type FROM asset_movements WHERE asset_id = 'p9'"
            ).fetchone()
        finally:
            conn.close()
        assert stored["tx_type"] == "waiver"
        # ...but it is not a trade, so it reaches neither the trade
        # counts nor the buy/sell board.  This is D1, still holding.
        assert ledger.counts(path=db)["assetMovementCount"] == 0
        assert [r for r in ledger.asset_signals(path=db) if r["assetId"] == "p9"] == []


class TestCursorPersistence:
    def test_the_cursor_survives_across_runs(self, db):
        _crawl(responses_for(), ledger_path=db)
        conn = ledger.connect(db)
        try:
            row = conn.execute("SELECT * FROM sharp_league_fetch WHERE league_id='L1'").fetchone()
        finally:
            conn.close()
        assert row["backfilled"] == 1
        assert int(row["max_created_ms"]) == NOW - DAY_MS
        assert json.loads(row["boundary_tx_ids"]) == ["t1"]

    def test_a_new_transaction_after_the_boundary_still_ingests(self, db):
        _crawl(responses_for(), ledger_path=db)
        later = responses_for(
            txs=[
                trade("t1", NOW - DAY_MS, {"p1": 1}, {"p1": 2}),
                trade("t2", NOW - 3600_000, {"p2": 2}, {"p2": 1}),
            ]
        )
        result, _ = _crawl(later, ledger_path=db)
        assert result.movements_ingested == 2
        assert ledger.counts(path=db)["tradeCount"] == 2


class TestWriterLockWindows:
    def test_each_league_commits_before_the_next_network_call(self, db):
        """V1-59: the crawl must never hold the SQLite writer lock across
        network I/O.

        A single end-of-crawl commit left the implicit transaction opened
        by the FIRST league's ``_save_fetch_state`` upsert pending for the
        whole budgeted run — on production, minutes of writer lock in a
        quiet period (no new events, so ``ingest_events`` never commits),
        starving every concurrent sharp unit past its 30 s busy_timeout
        (measured 2026-08-25: discovery, records and rosters all raising
        ``database is locked``).  The observable property, mirrored from
        ``test_records.TestWriterLockWindows``: by the time the crawl asks
        Sleeper about the SECOND league, the FIRST league's fetch-state row
        is already visible to an independent connection.  Under the retired
        single-commit shape this count is 0 until the crawl returns.
        """
        import sqlite3

        observed: list[int] = []
        responses = {
            f"{BASE}/state/nfl": {"week": 2},
            f"{BASE}/league/L1/rosters": [roster(1, "A"), roster(2, "B")],
            f"{BASE}/league/L2/rosters": [roster(1, "A"), roster(2, "B")],
            # No transactions entries on purpose: FakeHttp answers [] for
            # every transactions week, which is the quiet-period shape —
            # nothing but _save_fetch_state writes, so only the per-league
            # commit can make the row visible.
        }

        class SpyingHttp(FakeHttp):
            def __call__(self, url):
                if url == f"{BASE}/league/L2/rosters":
                    probe = sqlite3.connect(db)
                    try:
                        n = probe.execute(
                            "SELECT COUNT(*) FROM sharp_league_fetch WHERE league_id='L1'"
                        ).fetchone()[0]
                    finally:
                        probe.close()
                    observed.append(n)
                return super().__call__(url)

        http = SpyingHttp(responses)
        transactions.crawl_transactions(
            league_ids=["L1", "L2"],
            budget=100,
            sleep_s=0.0,
            http_get=http,
            now_ms=NOW,
            ledger_path=db,
        )

        assert observed, "the crawl never reached the second league — vacuous"
        assert observed[0] > 0, (
            "the first league's fetch state was invisible to an independent "
            "reader while the crawl performed its next network call — the "
            "writer transaction is still spanning network I/O (V1-59)"
        )
