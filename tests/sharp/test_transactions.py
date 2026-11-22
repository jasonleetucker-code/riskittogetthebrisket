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
        assert cov["oldestCrawlMs"] != max(
            stamps
        ), "min and max coincide, so this fixture cannot tell them apart"
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


# ---------------------------------------------------------------------------
# 404 leagues and the shared Sleeper breaker
#
# 2026-10-26 box audit: ~598 sharp-eligible leagues answer HTTP 404 on
# ``/league/{id}/rosters``.  They have no fetch cursor, so they sorted as
# "never fetched" and headed the queue on every run; the first five 404s
# opened the shared ``sleeper_api`` breaker and every healthy league behind
# them fast-failed -- 0 of 6,092 leagues fetched in 13 of 28 runs, and the
# unit's exit 2 is recorded as success.
# ---------------------------------------------------------------------------

DEFAULT_RECHECK_MS = int(transactions.GONE_RECHECK_AFTER_HOURS * 3600 * 1000)


def _gone_rows(db):
    conn = ledger.connect(db)
    try:
        return {
            r["league_id"]: dict(r)
            for r in conn.execute("SELECT * FROM sharp_league_gone").fetchall()
        }
    finally:
        conn.close()


def _fetch_rows(db):
    conn = ledger.connect(db)
    try:
        return {
            r["league_id"]: dict(r)
            for r in conn.execute("SELECT * FROM sharp_league_fetch").fetchall()
        }
    finally:
        conn.close()


def _mixed(gone, healthy, week=2):
    """Responses: every ``gone`` league 404s on rosters, every ``healthy`` one is
    a normal league with one trade."""
    resp = {f"{BASE}/state/nfl": {"week": week}}
    for lid in gone:
        resp[f"{BASE}/league/{lid}/rosters"] = transactions.NOT_FOUND
    for lid in healthy:
        resp.update(responses_for(lid, week=week))
    return resp


class TestGoneLeaguesAreAnObservedState:
    def test_a_404_league_is_marked_gone_not_failed(self, db):
        result, _ = _crawl(_mixed(["G1"], ["H1"]), league_ids=["G1", "H1"], ledger_path=db)
        assert result.leagues_gone == 1
        assert result.leagues_fetched == 1
        assert result.leagues_failed == 0
        assert "G1" not in result.errors
        assert result.stopped_reason is None
        row = _gone_rows(db)["G1"]
        assert row["first_gone_ms"] == NOW
        assert row["last_checked_ms"] == NOW
        assert row["not_found_count"] == 1
        assert row["endpoint"] == "rosters"

    def test_a_gone_league_is_not_a_crawled_league(self, db):
        """MISSING IS NEVER ZERO: gone is not "crawled, no trades".  It must not
        gain a fetch cursor (``sharp_league_fetch`` rows are read as 'crawled' by
        the completed-trade ledger) and it ingests nothing."""
        _crawl(_mixed(["G1"], ["H1"]), league_ids=["G1", "H1"], ledger_path=db)
        assert "G1" not in _fetch_rows(db)
        assert "H1" in _fetch_rows(db)
        conn = ledger.connect(db)
        try:
            n = conn.execute(
                "SELECT COUNT(*) FROM asset_movements WHERE league_id='G1'"
            ).fetchone()[0]
        finally:
            conn.close()
        assert n == 0

    def test_a_known_gone_league_inside_the_window_costs_nothing(self, db):
        resp = _mixed(["G1"], ["H1"])
        _crawl(resp, league_ids=["G1", "H1"], ledger_path=db)
        result, http = _crawl(resp, league_ids=["G1", "H1"], ledger_path=db, now_ms=NOW + DAY_MS)
        assert http.count(f"{BASE}/league/G1/rosters") == 0
        assert result.leagues_gone_skipped == 1
        assert result.leagues_gone == 0
        assert result.leagues_considered == 2
        assert result.leagues_pending == 0, "a skipped gone league is not pending work"

    def test_past_the_window_gone_leagues_are_rechecked_as_a_bounded_trickle(self, db):
        """Not skipped forever (a mistaken 404 must heal) and not a wall: at most
        GONE_RECHECK_MAX_PER_RUN per run, stalest check first, healthy leagues
        untouched."""
        cap = transactions.GONE_RECHECK_MAX_PER_RUN
        gone = [f"G{i:02d}" for i in range(cap + 5)]
        resp = _mixed(gone, ["H00"])
        everything = gone + ["H00"]
        _crawl(resp, league_ids=everything, ledger_path=db, budget=500)
        assert len(_gone_rows(db)) == cap + 5

        later = NOW + DEFAULT_RECHECK_MS + DAY_MS
        result, http = _crawl(resp, league_ids=everything, ledger_path=db, budget=500, now_ms=later)
        rechecked = [u for u in http.calls if "/league/G" in u and u.endswith("/rosters")]
        assert len(rechecked) == cap, "the re-check must be capped, not the whole wall"
        assert result.leagues_gone == cap
        assert result.leagues_gone_skipped == 5, "due but over the cap: waits for a later run"
        assert result.leagues_fetched == 1, "the healthy league is fetched in the same run"

        # Re-confirmation keeps first_gone_ms and bumps the count.
        rows = _gone_rows(db)
        confirmed = [r for r in rows.values() if r["last_checked_ms"] == later]
        assert len(confirmed) == cap
        assert all(r["not_found_count"] == 2 and r["first_gone_ms"] == NOW for r in confirmed)

        # The next run takes the 5 that were over the cap; the 20 just re-checked
        # are inside a fresh window and are skipped.
        nxt, http2 = _crawl(
            resp, league_ids=everything, ledger_path=db, budget=500, now_ms=later + DAY_MS
        )
        again = [u for u in http2.calls if "/league/G" in u and u.endswith("/rosters")]
        assert len(again) == 5
        assert nxt.leagues_gone == 5 and nxt.leagues_gone_skipped == cap

    def test_the_recheck_trickle_goes_stalest_first(self, db):
        resp = _mixed(["G-old", "G-new"], [])
        _crawl(resp, league_ids=["G-old"], ledger_path=db, now_ms=NOW)
        _crawl(resp, league_ids=["G-new"], ledger_path=db, now_ms=NOW + 2 * DAY_MS)
        later = NOW + DEFAULT_RECHECK_MS + 3 * DAY_MS
        _, http = _crawl(resp, league_ids=["G-new", "G-old"], ledger_path=db, now_ms=later)
        order = [u for u in http.calls if u.endswith("/rosters")]
        assert order == [f"{BASE}/league/G-old/rosters", f"{BASE}/league/G-new/rosters"]

    def test_a_league_that_answers_again_is_no_longer_gone(self, db):
        _crawl(_mixed(["L1"], []), league_ids=["L1"], ledger_path=db)
        assert "L1" in _gone_rows(db)
        later = NOW + DEFAULT_RECHECK_MS + DAY_MS
        result, _ = _crawl(responses_for("L1"), league_ids=["L1"], ledger_path=db, now_ms=later)
        assert result.leagues_recovered == 1
        assert result.leagues_fetched == 1
        assert _gone_rows(db) == {}
        assert "L1" in _fetch_rows(db)

    def test_naming_a_league_explicitly_bypasses_the_skip(self, db):
        resp = _mixed(["G1"], [])
        _crawl(resp, league_ids=["G1"], ledger_path=db)
        http = FakeHttp(resp)
        result = transactions.crawl_transactions(
            league_ids=["G1"],
            budget=100,
            sleep_s=0.0,
            http_get=http,
            now_ms=NOW + DAY_MS,
            ledger_path=db,
            skip_gone=False,
        )
        assert http.count(f"{BASE}/league/G1/rosters") == 1
        assert result.leagues_gone == 1 and result.leagues_gone_skipped == 0

    def test_an_ordinary_failure_is_still_a_failure_not_gone(self, db):
        """``None`` (timeout, 5xx, ...) is "we do not know" and must not be
        recorded as an observation that the league does not exist."""
        resp = {f"{BASE}/state/nfl": {"week": 2}, f"{BASE}/league/L1/rosters": None}
        result, _ = _crawl(resp, league_ids=["L1"], ledger_path=db)
        assert result.leagues_failed == 1
        assert result.errors == {"L1": "rosters_fetch_failed"}
        assert result.leagues_gone == 0
        assert _gone_rows(db) == {}


class TestFirstLeaguesAre404ButTheRestAreFetched:
    GONE = [f"G{i:02d}" for i in range(8)]  # sort before the healthy ids
    HEALTHY = [f"H{i:02d}" for i in range(5)]

    def test_the_healthy_tail_is_fetched_behind_a_wall_of_404s(self, db):
        result, _ = _crawl(
            _mixed(self.GONE, self.HEALTHY),
            league_ids=self.GONE + self.HEALTHY,
            ledger_path=db,
            budget=200,
        )
        assert result.leagues_gone == 8
        assert result.leagues_fetched == 5
        assert result.leagues_failed == 0
        assert result.leagues_pending == 0
        assert result.stopped_reason is None
        assert result.transactions_seen == 5, "each healthy league contributed its trade"
        assert set(_gone_rows(db)) == set(self.GONE)

    def test_a_budget_spent_on_the_wall_resumes_past_it(self, db):
        """Run 1 runs out of budget while still inside the 404 wall; run 2 must
        not walk the wall again (it is recorded) and must reach the tail."""
        resp = _mixed(self.GONE, self.HEALTHY)
        everything = self.GONE + self.HEALTHY
        first, _ = _crawl(resp, league_ids=everything, ledger_path=db, budget=10)
        assert first.stopped_reason == transactions.STOPPED_BUDGET_EXHAUSTED
        assert first.leagues_fetched == 0 and first.leagues_gone == 8
        second, http = _crawl(resp, league_ids=everything, ledger_path=db, budget=200)
        assert [u for u in http.calls if "/league/G" in u] == [], "the wall was walked again"
        assert second.leagues_gone_skipped == 8
        assert second.leagues_fetched == 5
        assert second.leagues_pending == 0


class _AllNotFound:
    """A fetcher for which EVERYTHING is a 404 -- ``/state/nfl`` included."""

    def __init__(self):
        self.calls = []

    def __call__(self, url):
        self.calls.append(url)
        return transactions.NOT_FOUND


class TestGoneMarksNeedTheRunsOwnCanary:
    """``/state/nfl`` always exists, so a run in which it did not answer cannot
    read a 404 on a league as "this league is deleted" -- the whole of Sleeper (or
    something in front of it) may be answering 404.  No mark is written; the
    leagues are counted as ``not_found_unconfirmed`` and asked again next run."""

    IDS = [f"L{i:02d}" for i in range(6)]

    def _run(self, http, db, ids=None, now_ms=NOW, budget=100):
        return transactions.crawl_transactions(
            league_ids=list(ids or self.IDS),
            budget=budget,
            sleep_s=0.0,
            http_get=http,
            now_ms=now_ms,
            ledger_path=db,
        )

    def test_an_all_404_fetcher_marks_nothing_gone(self, db, caplog):
        http = _AllNotFound()
        with caplog.at_level("INFO", logger=transactions.log.name):
            result = self._run(http, db)
        assert _gone_rows(db) == {}, "a wall of 404s incl. /state/nfl is not evidence"
        assert result.leagues_gone == 0
        assert result.leagues_not_found_unconfirmed == len(self.IDS)
        assert result.state_nfl_confirmed is False
        assert result.leagues_failed == 0 and result.leagues_fetched == 0
        assert _fetch_rows(db) == {}, "and none is dressed up as crawled"
        payload = result.to_dict()
        assert payload["leaguesNotFoundUnconfirmed"] == len(self.IDS)
        assert payload["stateNflConfirmed"] is False
        assert payload["leaguesGone"] == 0
        # every league was actually asked (nothing silently skipped)
        asked = [u for u in http.calls if u.endswith("/rosters")]
        assert len(asked) == len(self.IDS)
        warned = [r for r in caplog.records if "not_found_unconfirmed" in r.getMessage()]
        assert warned, "the unconfirmed 404s must be logged"
        assert any(r.levelname == "WARNING" for r in warned)
        assert f"not_found_unconfirmed={len(self.IDS)}" in " ".join(
            r.getMessage() for r in caplog.records
        )

    @pytest.mark.parametrize(
        "state",
        [None, transactions.NOT_FOUND, transactions.BREAKER_OPEN, [], "ok", 7],
        ids=["failed", "404", "breaker_open", "list", "string", "int"],
    )
    def test_a_state_call_that_is_not_a_dict_leaves_every_404_unconfirmed(self, db, state):
        resp = _mixed(["G1", "G2"], ["H1"])
        resp[f"{BASE}/state/nfl"] = state
        result, _ = _crawl(resp, league_ids=["G1", "G2", "H1"], ledger_path=db)
        assert _gone_rows(db) == {}
        assert result.leagues_gone == 0
        assert result.leagues_not_found_unconfirmed == 2
        assert result.state_nfl_confirmed is False

    def test_the_healthy_leagues_are_still_crawled_while_the_canary_is_down(self, db):
        """Only the gone MARK is withheld.  A league that answers with rosters is
        crawled exactly as before (the week simply defaults)."""
        resp = _mixed(["G1"], ["H1"])
        resp[f"{BASE}/state/nfl"] = None
        result, _ = _crawl(resp, league_ids=["G1", "H1"], ledger_path=db)
        assert result.week == 1
        assert result.leagues_fetched == 1 and "H1" in _fetch_rows(db)
        assert result.leagues_not_found_unconfirmed == 1 and _gone_rows(db) == {}

    def test_an_answering_state_call_keeps_the_existing_behaviour(self, db):
        result, _ = _crawl(_mixed(["G1"], ["H1"]), league_ids=["G1", "H1"], ledger_path=db)
        assert result.state_nfl_confirmed is True
        assert result.leagues_gone == 1 and result.leagues_not_found_unconfirmed == 0
        assert set(_gone_rows(db)) == {"G1"}

    def test_a_dict_without_a_usable_week_still_confirms_the_canary(self, db):
        """The endpoint ANSWERED; only the week defaults."""
        resp = _mixed(["G1"], [])
        resp[f"{BASE}/state/nfl"] = {}
        result, _ = _crawl(resp, league_ids=["G1"], ledger_path=db)
        assert result.state_nfl_confirmed is True and result.week == 1
        assert set(_gone_rows(db)) == {"G1"}

    def test_no_budget_for_the_state_call_cannot_confirm_it(self, db):
        result, http = _crawl(_mixed(["G1"], []), league_ids=["G1"], ledger_path=db, budget=0)
        assert http.calls == []
        assert result.state_nfl_confirmed is False and _gone_rows(db) == {}

    def test_an_unconfirmed_run_does_not_reconfirm_a_known_gone_league(self, db):
        """Re-checks are marks too: a due league that 404s while the canary is down
        keeps its row untouched (so it is simply due again next run)."""
        _crawl(_mixed(["G1"], []), league_ids=["G1"], ledger_path=db)
        before = _gone_rows(db)["G1"]
        later = NOW + DEFAULT_RECHECK_MS + DAY_MS
        resp = _mixed(["G1"], [])
        resp[f"{BASE}/state/nfl"] = None
        result, http = _crawl(resp, league_ids=["G1"], ledger_path=db, now_ms=later)
        assert http.count(f"{BASE}/league/G1/rosters") == 1, "it was re-checked"
        assert result.leagues_not_found_unconfirmed == 1 and result.leagues_gone == 0
        assert _gone_rows(db)["G1"] == before, "nothing re-confirmed, nothing moved"

    def test_the_next_confirmed_run_marks_what_the_unconfirmed_run_would_not(self, db):
        down = _mixed(["G1", "G2"], [])
        down[f"{BASE}/state/nfl"] = None
        _crawl(down, league_ids=["G1", "G2"], ledger_path=db)
        assert _gone_rows(db) == {}
        result, _ = _crawl(
            _mixed(["G1", "G2"], []), league_ids=["G1", "G2"], ledger_path=db, now_ms=NOW + DAY_MS
        )
        assert result.leagues_gone == 2 and set(_gone_rows(db)) == {"G1", "G2"}

    def test_a_gone_league_that_answers_with_rosters_is_still_recovered_unconfirmed(self, db):
        """A live roster list is positive evidence on its own; it needs no canary."""
        _crawl(_mixed(["L1"], []), league_ids=["L1"], ledger_path=db)
        later = NOW + DEFAULT_RECHECK_MS + DAY_MS
        resp = responses_for("L1")
        resp[f"{BASE}/state/nfl"] = None
        result, _ = _crawl(resp, league_ids=["L1"], ledger_path=db, now_ms=later)
        assert result.leagues_recovered == 1 and _gone_rows(db) == {}


class TestBreakerStopIsExplicit:
    def test_a_refused_call_stops_the_pass_and_says_so(self, db):
        ids = [f"L{i}" for i in range(6)]
        resp = {f"{BASE}/state/nfl": {"week": 2}}
        for lid in ids[:2]:
            resp.update(responses_for(lid))
        for lid in ids[2:]:
            resp[f"{BASE}/league/{lid}/rosters"] = transactions.BREAKER_OPEN
        result, http = _crawl(resp, league_ids=ids, ledger_path=db)
        assert result.stopped_reason == transactions.STOPPED_BREAKER_OPEN
        assert result.leagues_fetched == 2
        assert result.leagues_pending == 4, "the refused league and everything after it"
        assert result.errors == {}, "no per-league error flood for leagues never attempted"
        assert result.leagues_gone == 0
        rosters_calls = [u for u in http.calls if u.endswith("/rosters")]
        assert len(rosters_calls) == 3, "must stop at the first refused call, not walk the queue"
        payload = result.to_dict()
        assert payload["stoppedReason"] == "sleeper_breaker_open"
        assert payload["leaguesFetched"] == 2

    def test_a_refusal_mid_league_leaves_that_leagues_cursor_alone(self, db):
        resp = responses_for("L1")
        resp[f"{BASE}/league/L1/transactions/2"] = transactions.BREAKER_OPEN
        resp.update(responses_for("L2"))
        result, _ = _crawl(resp, league_ids=["L1", "L2"], ledger_path=db)
        assert result.stopped_reason == transactions.STOPPED_BREAKER_OPEN
        assert result.leagues_fetched == 0
        assert result.leagues_pending == 1, "only L2 was never reached"
        row = _fetch_rows(db)["L1"]
        assert row["backfilled"] == 0
        assert row["max_created_ms"] == 0, "the cursor must not advance past an unfetched week"
        assert row["last_error"] == transactions.STOPPED_BREAKER_OPEN

    def test_budget_exhaustion_is_named_as_such(self, db):
        resp = responses_for("L1")
        resp.update(responses_for("L2"))
        result, _ = _crawl(resp, league_ids=["L1", "L2"], ledger_path=db, budget=5)
        assert result.leagues_pending == 1
        assert result.stopped_reason == transactions.STOPPED_BUDGET_EXHAUSTED

    def test_a_completed_pass_has_no_stopped_reason(self, db):
        result, _ = _crawl(responses_for(), ledger_path=db)
        assert result.stopped_reason is None
        assert result.to_dict()["stoppedReason"] is None

    def test_the_log_line_says_the_breaker_refused_calls(self, db, caplog):
        resp = {
            f"{BASE}/state/nfl": {"week": 2},
            f"{BASE}/league/L1/rosters": transactions.BREAKER_OPEN,
        }
        with caplog.at_level("INFO", logger=transactions.log.name):
            _crawl(resp, league_ids=["L1"], ledger_path=db)
        stops = [r for r in caplog.records if "REFUSED" in r.getMessage()]
        assert stops and stops[0].levelname == "ERROR"
        assert "stopped=sleeper_breaker_open" in stops[0].getMessage()
        assert "fetched=0" in stops[0].getMessage()


class TestDefaultFetcherClassifiesTheOutcome:
    @pytest.mark.parametrize(
        "kind, payload, expected",
        [
            ("ok", [1], [1]),
            ("error", None, None),
            ("not_found", None, "NOT_FOUND"),
            ("breaker_open", None, "BREAKER_OPEN"),
        ],
    )
    def test_kind_to_return(self, monkeypatch, kind, payload, expected):
        from src.api import sleeper_overlay

        monkeypatch.setattr(
            sleeper_overlay, "_http_get_json_classified", lambda url: (kind, payload)
        )
        got = transactions._default_http_get("u")
        if expected == "NOT_FOUND":
            assert got is transactions.NOT_FOUND
        elif expected == "BREAKER_OPEN":
            assert got is transactions.BREAKER_OPEN
        else:
            assert got == expected


class TestWithTheRealBreaker:
    """The incident end to end: the production fetcher, the real shared breaker,
    only the socket faked."""

    @pytest.fixture()
    def wire(self, monkeypatch):
        import io
        import urllib.error

        from src.api import sleeper_overlay
        from src.utils import circuit_breaker

        circuit_breaker.reset_all_for_tests()
        responses: dict = {}
        calls: list[str] = []

        class _Resp:
            def __init__(self, body):
                self._body = body

            def read(self):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(req, timeout=None):
            url = req.full_url
            calls.append(url)
            outcome = responses.get(url)
            if outcome is None and "/transactions/" in url:
                outcome = []
            if isinstance(outcome, int):
                raise urllib.error.HTTPError(url, outcome, "status", {}, io.BytesIO(b""))
            if isinstance(outcome, tuple):  # (status, raw body bytes)
                code, raw = outcome
                raise urllib.error.HTTPError(url, code, "status", {}, io.BytesIO(raw))
            return _Resp(json.dumps(outcome).encode())

        monkeypatch.setattr(sleeper_overlay.urllib.request, "urlopen", fake_urlopen)
        yield responses, calls, circuit_breaker
        circuit_breaker.reset_all_for_tests()

    def _crawl(self, ids, db, budget=500):
        return transactions.crawl_transactions(
            league_ids=ids, budget=budget, sleep_s=0.0, now_ms=NOW, ledger_path=db
        )

    def test_eight_404_leagues_ahead_of_the_healthy_ones_do_not_stop_the_crawl(self, db, wire):
        responses, _calls, circuit_breaker = wire
        gone = [f"G{i:02d}" for i in range(8)]
        healthy = [f"H{i:02d}" for i in range(3)]
        responses[f"{BASE}/state/nfl"] = {"week": 2}
        for lid in gone:
            responses[f"{BASE}/league/{lid}/rosters"] = 404
        for lid in healthy:
            responses.update(responses_for(lid))
        result = self._crawl(gone + healthy, db)
        assert result.leagues_gone == 8
        assert result.leagues_fetched == 3, "the healthy leagues behind the 404 wall were starved"
        assert result.stopped_reason is None
        snap = circuit_breaker.get_or_create("sleeper_api").snapshot()
        assert snap["state"] == "closed" and snap["counters"]["opens"] == 0

    def test_a_real_outage_still_opens_the_breaker_and_stops_early(self, db, wire):
        responses, calls, circuit_breaker = wire
        ids = [f"L{i:02d}" for i in range(40)]
        responses[f"{BASE}/state/nfl"] = {"week": 2}
        for lid in ids:
            responses[f"{BASE}/league/{lid}/rosters"] = 503
        result = self._crawl(ids, db)
        snap = circuit_breaker.get_or_create("sleeper_api").snapshot()
        assert snap["state"] == "open"
        assert result.stopped_reason == transactions.STOPPED_BREAKER_OPEN
        assert result.leagues_fetched == 0
        assert result.leagues_failed == 5, "the five genuine failures that tripped it"
        assert result.leagues_pending == 35
        assert len(calls) == 1 + 5, "state + five 503s; the open breaker made no more calls"
        assert result.leagues_gone == 0

    def test_everything_answering_404_incl_state_marks_no_league_gone(self, db, wire):
        """The production fetcher, the real breaker, the socket faked: Sleeper's own
        empty 404 for ``/state/nfl`` AND every league.  The breaker stays closed
        (those are answers) yet nothing is written, because the canary never
        answered."""
        responses, _calls, circuit_breaker = wire
        ids = [f"L{i:02d}" for i in range(10)]
        responses[f"{BASE}/state/nfl"] = 404
        for lid in ids:
            responses[f"{BASE}/league/{lid}/rosters"] = 404
        result = self._crawl(ids, db)
        assert _gone_rows(db) == {}
        assert result.leagues_gone == 0
        assert result.leagues_not_found_unconfirmed == 10
        assert result.stopped_reason is None
        snap = circuit_breaker.get_or_create("sleeper_api").snapshot()
        assert snap["state"] == "closed" and snap["counters"]["failure"] == 0

    def test_a_gateway_404_page_is_an_outage_not_ten_deleted_leagues(self, db, wire):
        """The same all-404 world, but the 404s carry an HTML body: not Sleeper's
        answer, so they count, the breaker opens, the pass stops and nothing is
        marked gone."""
        responses, calls, circuit_breaker = wire
        ids = [f"L{i:02d}" for i in range(40)]
        page = (404, b"<html><body>404 - blocked by gateway</body></html>")
        responses[f"{BASE}/state/nfl"] = page
        for lid in ids:
            responses[f"{BASE}/league/{lid}/rosters"] = page
        result = self._crawl(ids, db)
        snap = circuit_breaker.get_or_create("sleeper_api").snapshot()
        assert snap["state"] == "open"
        assert result.stopped_reason == transactions.STOPPED_BREAKER_OPEN
        assert result.leagues_gone == 0 and _gone_rows(db) == {}
        assert result.leagues_fetched == 0
        assert len(calls) < 1 + len(ids), "the open breaker must have cut the pass short"

    def test_sleepers_own_404s_are_still_marked_gone_when_the_canary_answers(self, db, wire):
        responses, _calls, circuit_breaker = wire
        responses[f"{BASE}/state/nfl"] = {"week": 2}
        for lid in ("G1", "G2"):
            responses[f"{BASE}/league/{lid}/rosters"] = (404, b"null")
        result = self._crawl(["G1", "G2"], db)
        assert result.leagues_gone == 2 and set(_gone_rows(db)) == {"G1", "G2"}
        assert result.leagues_not_found_unconfirmed == 0
        snap = circuit_breaker.get_or_create("sleeper_api").snapshot()
        assert snap["counters"]["failure"] == 0


class TestOrderingAndCoverage:
    def test_the_healthy_order_is_unchanged_by_the_gone_work(self):
        fetch = {"L1": {"backfilled": True, "lastFetchedMs": NOW}}
        assert transactions._league_order(["L1", "L2"], fetch) == ["L2", "L1"]

    def test_split_gone_window_boundary(self):
        gone = {"L1": {"lastCheckedMs": NOW}}
        inside, past = NOW + DEFAULT_RECHECK_MS - 1, NOW + DEFAULT_RECHECK_MS
        assert transactions._split_gone(["L1", "L2"], gone, now_ms=inside) == (["L2"], [], ["L1"])
        assert transactions._split_gone(["L1", "L2"], gone, now_ms=past) == (["L2"], ["L1"], [])

    def test_split_gone_caps_the_trickle_and_defers_the_rest(self):
        gone = {f"G{i}": {"lastCheckedMs": NOW + i} for i in range(5)}
        healthy, recheck, skipped = transactions._split_gone(
            ["H", *gone], gone, now_ms=NOW + 2 * DEFAULT_RECHECK_MS, max_recheck=2
        )
        assert healthy == ["H"]
        assert recheck == ["G0", "G1"], "stalest check first"
        assert skipped == ["G2", "G3", "G4"], "deferred, never dropped"

    def test_split_gone_with_a_zero_cap_rechecks_nothing(self):
        gone = {"G": {"lastCheckedMs": NOW}}
        _, recheck, skipped = transactions._split_gone(
            ["G"], gone, now_ms=NOW + 2 * DEFAULT_RECHECK_MS, max_recheck=0
        )
        assert recheck == [] and skipped == ["G"]

    def test_a_ledger_without_the_table_reads_as_none_gone(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        assert transactions._load_gone_state(conn) == {}

    def test_ensure_gone_schema_is_additive_and_repeatable(self, db):
        conn = ledger.connect(db)
        try:
            transactions.ensure_gone_schema(conn)
            transactions.ensure_gone_schema(conn)
            assert transactions._load_gone_state(conn) == {}
        finally:
            conn.close()
        assert ledger.SCHEMA_VERSION == 2, "the gone table must not ride a ledger migration"

    def test_coverage_separates_gone_from_work_still_to_do(self, db, monkeypatch):
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["G1", "H1", "H2"],
        )
        _crawl(_mixed(["G1"], ["H1"]), league_ids=["G1", "H1"], ledger_path=db)
        cov = transactions.crawl_coverage(ledger_path=db)
        assert cov["sharpEligibleLeagues"] == 3
        assert cov["leaguesCrawled"] == 1
        assert cov["leaguesUncrawled"] == 2, "existing definition is unchanged"
        assert cov["leaguesGone"] == 1
        assert cov["leaguesUncrawledReachable"] == 1, "only H2 is real work"

    def test_coverage_on_a_ledger_that_never_ran_the_crawl(self, db, monkeypatch):
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1"],
        )
        cov = transactions.crawl_coverage(ledger_path=db)
        assert cov["leaguesGone"] == 0
        assert cov["leaguesUncrawledReachable"] == 1


# ---------------------------------------------------------------------------
# Week coverage (CTM-1, 2026-11-22)
#
# A backfilled league used to fetch ONLY the current week, and leagues are
# visited oldest-first under a budget far smaller than the graph -- so a league
# not visited while week N was current lost all of week N's trades for good,
# and the next visit carried the cursor past them.  Each league now fetches
# every week from the one after its last gap-free coverage to the current one.
# ---------------------------------------------------------------------------

SEASON = "2026"
HOUR_MS = 3600 * 1000


def clocked(week, season=SEASON):
    return {f"{BASE}/state/nfl": {"week": week, "season": season}}


def league_weeks(lid, by_week, *, week, season=SEASON):
    """One league's responses: a clocked ``/state/nfl``, rosters, and the given
    per-week transactions (every other week answers ``[]`` via FakeHttp)."""
    resp = clocked(week, season)
    resp[f"{BASE}/league/{lid}/rosters"] = [roster(1, "A"), roster(2, "B")]
    for w, txs in by_week.items():
        resp[f"{BASE}/league/{lid}/transactions/{w}"] = txs
    return resp


def _weeks_called(http, lid="L1"):
    prefix = f"{BASE}/league/{lid}/transactions/"
    return [int(u[len(prefix) :]) for u in http.calls if u.startswith(prefix)]


def _coverage_rows(db):
    conn = ledger.connect(db)
    try:
        return {
            r["league_id"]: dict(r)
            for r in conn.execute("SELECT * FROM sharp_league_week_coverage").fetchall()
        }
    finally:
        conn.close()


def _trade_ids(db):
    conn = ledger.connect(db)
    try:
        return {
            r["tx_id"]
            for r in conn.execute("SELECT DISTINCT tx_id FROM asset_movements").fetchall()
        }
    finally:
        conn.close()


def _cov(resume, through=None, season=SEASON):
    return transactions._WeekCoverage(
        season=season,
        through_week=resume if through is None else through,
        resume_week=resume,
    )


BACKFILLED = {"backfilled": True, "lastFetchedMs": NOW - DAY_MS}


def _plan(coverage, week, *, season=SEASON, in_grace=False, state=None, week_known=True):
    return transactions._plan_weeks(
        BACKFILLED if state is None else state,
        coverage,
        week=week,
        season=season,
        week_known=week_known,
        in_grace=in_grace,
        now_ms=NOW,
    )


class TestWeekPlan:
    """The pure week-selection rule, every branch."""

    def test_steady_state_is_the_current_week(self):
        plan = _plan(_cov(12), 12)
        assert plan.weeks == [12]
        assert not plan.capped and not plan.caught_up

    def test_inside_the_rollover_grace_the_previous_week_is_fetched_too(self):
        assert _plan(_cov(12), 12, in_grace=True).weeks == [11, 12]

    def test_missed_weeks_are_fetched_oldest_first(self):
        plan = _plan(_cov(9), 12)
        assert plan.weeks == [9, 10, 11, 12]
        assert plan.caught_up and not plan.capped

    def test_the_catch_up_is_capped_per_visit(self):
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        plan = _plan(_cov(1), 12)
        assert plan.weeks == list(range(1, 1 + cap)), "oldest first, so progress is a prefix"
        assert plan.capped

    def test_resume_after_a_visit(self):
        # complete visit: the next one resumes at the current week ...
        assert transactions._next_resume_week(12, 12, in_grace=False) == 12
        # ... or at the previous one if this visit was inside its rollover grace
        assert transactions._next_resume_week(12, 12, in_grace=True) == 11
        # capped visit: right after the last week it reached
        assert transactions._next_resume_week(6, 12, in_grace=False) == 7
        # offseason: both degenerate buckets stay open
        assert transactions._next_resume_week(1, 0, in_grace=False) == 0
        assert transactions._next_resume_week(1, 1, in_grace=False) == 0

    def test_a_new_season_restarts_at_week_zero(self):
        assert _plan(_cov(17, season="2025"), 3, season="2026").weeks == [0, 1, 2, 3]

    def test_the_offseason_always_covers_both_degenerate_buckets(self):
        assert _plan(_cov(17, season="2025"), 0, season="2026").weeks == [0, 1]
        assert _plan(_cov(17, season="2025"), 1, season="2026").weeks == [0, 1]
        assert _plan(_cov(0), 1).weeks == [0, 1]

    def test_week_numbering_going_backwards_reads_as_a_new_season_when_unknown(self):
        assert _plan(_cov(17, season=""), 2, season=None).weeks == [0, 1, 2]

    def test_the_post_grace_re_read_of_a_covered_week_is_not_a_catch_up(self):
        """Review NIT 1: after an in-grace visit the resume is the previous week
        (re-read for late rows), but that week WAS covered.  Only weeks past
        ``through_week`` count as caught up."""
        plan = _plan(_cov(11, through=12), 12, in_grace=False)
        assert plan.weeks == [11, 12]
        assert not plan.caught_up
        assert _plan(_cov(10, through=10), 12).caught_up, "week 11 was never covered"
        assert not _plan(_cov(11, through=12), 12, in_grace=True).caught_up

    def test_a_season_restart_is_one_bounded_sweep(self):
        """Review NIT 5: a season-string change (spurious or not) mid-season is
        one sweep of the backfill window, never a re-walk from week 0."""
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        plan = _plan(_cov(12, season="2026"), 12, season="2027")
        assert plan.weeks == list(range(12 - cap + 1, 13))
        assert not plan.capped and plan.restarted
        # week numbering going backwards with the season unknown: same bound
        plan = _plan(_cov(17, season=""), 15, season=None)
        assert plan.weeks == list(range(15 - cap + 1, 16)) and plan.restarted
        # a real new season is first seen in the offseason: the sweep reaches 0
        assert _plan(_cov(17, season="2025"), 0, season="2026").weeks == [0, 1]

    def test_a_regressed_week_in_the_same_season_takes_the_steady_window(self):
        assert _plan(_cov(12), 10, in_grace=False).weeks == [10]

    def test_first_visit_is_the_crawlers_backfill_unchanged(self):
        plan = _plan(None, 12, state={"backfilled": False})
        assert plan.weeks == crawler._weeks_to_fetch(
            {"fetchState": {"backfilled": False}}, 12, None, NOW
        )
        assert plan.mode == transactions._MODE_BACKFILL

    def test_no_usable_week_keeps_the_old_rule_and_reads_no_coverage(self):
        plan = _plan(_cov(3), 12, week_known=False)
        assert plan.weeks == [12]
        assert plan.mode == transactions._MODE_UNCLOCKED

    def test_recovery_sweep_is_the_backfill_window_whatever_the_last_visit(self):
        """Review NIT 4: the one-time sweep used to start at the last old-code
        visit's week minus one, which missed late-filed rows in older weeks.  It
        now always covers ``week - cap + 1 .. week`` (still bounded by the
        30-day read-back), about three more calls per league, once."""
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        for last in (NOW - 5 * DAY_MS, NOW - HOUR_MS, NOW - 60 * DAY_MS):
            plan = _plan(None, 12, state={"backfilled": True, "lastFetchedMs": last})
            assert plan.weeks == list(range(12 - cap + 1, 13))
            assert plan.mode == transactions._MODE_RECOVERY
            assert not plan.capped, "a sweep is never more than one visit"

    def test_recovery_sweep_without_a_usable_stamp_is_the_backfill_window(self):
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        plan = _plan(None, 12, state={"backfilled": True, "lastFetchedMs": 0})
        assert plan.weeks == list(range(12 - cap + 1, 13))
        assert not plan.capped

    def test_the_intel_crawlers_rule_is_untouched(self):
        """The other caller of ``_weeks_to_fetch`` keeps its exact behaviour."""
        entry = {"fetchState": {"backfilled": True}}
        assert crawler._weeks_to_fetch(entry, 12, None, NOW) == [12]
        assert crawler._weeks_to_fetch(entry, 12, NOW - HOUR_MS, NOW) == [12, 11]


class TestAMissedWeekIsFetchedOnTheNextVisit:
    def test_a_whole_missed_week_arrives_with_the_next_visit(self, db):
        """Visited in week 10, not again until week 13: weeks 11 and 12 used to
        be lost for good.  Week 11 sits below even the rollover-grace window,
        so only the coverage catch-up can reach it."""
        t10 = trade("t10", NOW - DAY_MS, {"p1": 1}, {"p1": 2})
        _crawl(league_weeks("L1", {10: [t10]}, week=10), ledger_path=db)
        resp = league_weeks(
            "L1",
            {
                10: [t10],
                11: [trade("t11", NOW + 8 * DAY_MS, {"p2": 1}, {"p2": 2})],
                12: [trade("t12", NOW + 15 * DAY_MS, {"p3": 2}, {"p3": 1})],
                13: [trade("t13", NOW + 21 * DAY_MS, {"p4": 1}, {"p4": 2})],
            },
            week=13,
        )
        result, http = _crawl(resp, ledger_path=db, now_ms=NOW + 22 * DAY_MS)
        assert transactions._steady_floor(13, True) == 12, "week 11 is outside the steady window"
        assert _weeks_called(http) == [9, 10, 11, 12, 13]
        assert {"t11", "t12", "t13"} <= _trade_ids(db)
        assert result.leagues_fetched == 1 and result.leagues_caught_up == 1
        row = _coverage_rows(db)["L1"]
        assert (row["season"], row["through_week"]) == (SEASON, 13)

    def test_late_rows_in_the_previous_week_after_an_in_grace_visit(self, db):
        """A visit inside the rollover grace resumes next time from the PREVIOUS
        week, so a late row filed into it afterwards is still collected -- even
        by a visit made after the grace has ended."""
        _crawl(league_weeks("L1", {}, week=10), ledger_path=db)  # week 10 first seen at NOW
        _, h2 = _crawl(league_weeks("L1", {}, week=10), ledger_path=db, now_ms=NOW + DAY_MS)
        assert _weeks_called(h2) == [9, 10], "inside the grace"
        late = trade("late9", NOW + DAY_MS + 12 * HOUR_MS, {"p9": 1}, {"p9": 2})
        r3, h3 = _crawl(
            league_weeks("L1", {9: [late]}, week=10), ledger_path=db, now_ms=NOW + 3 * DAY_MS
        )
        assert _weeks_called(h3) == [9, 10], "the last visit was in the grace, so 9 again"
        assert "late9" in _trade_ids(db)
        # Review NIT 1: week 9 was covered already; re-reading it after the
        # grace is routine, not a catch-up.
        assert r3.leagues_caught_up == 0 and r3.leagues_fetched == 1
        _, h4 = _crawl(league_weeks("L1", {}, week=10), ledger_path=db, now_ms=NOW + 4 * DAY_MS)
        assert _weeks_called(h4) == [10], "the last visit was past the grace: steady state"


class TestCatchUpIsCappedAndRetried:
    def _setup(self, db):
        t2 = trade("t2", NOW - DAY_MS, {"p1": 1}, {"p1": 2})
        _crawl(league_weeks("L1", {2: [t2]}, week=2), ledger_path=db)

    def _week12(self, extra=None):
        by_week = {
            4: [trade("t4", NOW + 14 * DAY_MS, {"p4": 1}, {"p4": 2})],
            10: [trade("t10", NOW + 56 * DAY_MS, {"p10": 2}, {"p10": 1})],
        }
        resp = league_weeks("L1", by_week, week=12)
        resp.update(extra or {})
        return resp

    def test_a_capped_league_is_not_fetched_and_keeps_its_cursor(self, db):
        self._setup(db)
        before = _fetch_rows(db)["L1"]
        result, http = _crawl(self._week12(), ledger_path=db, now_ms=NOW + 70 * DAY_MS)
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        assert _weeks_called(http) == list(range(1, 1 + cap))
        assert result.leagues_catchup_capped == 1
        assert result.leagues_fetched == 0, "capped is not 'fetched'"
        assert result.leagues_failed == 0 and result.errors == {}
        after = _fetch_rows(db)["L1"]
        assert after["last_fetched_ms"] == before["last_fetched_ms"], "stays stalest"
        assert after["max_created_ms"] == before["max_created_ms"], "cursor not advanced"
        cov = _coverage_rows(db)["L1"]
        assert (cov["through_week"], cov["resume_week"]) == (cap, cap + 1)
        assert "t4" in _trade_ids(db), "what it reached is ingested"
        assert "t10" not in _trade_ids(db)
        payload = result.to_dict()
        assert payload["leaguesCatchupCapped"] == 1 and payload["leaguesCaughtUp"] == 1

    def test_the_capped_league_is_retried_first_and_completes(self, db):
        self._setup(db)
        resp = self._week12(league_weeks("L2", {}, week=12))
        _crawl(resp, league_ids=["L1", "L2"], ledger_path=db, now_ms=NOW + 70 * DAY_MS)
        conn = ledger.connect(db)
        try:
            order = transactions._league_order(["L2", "L1"], transactions._load_fetch_state(conn))
        finally:
            conn.close()
        assert order == ["L1", "L2"], "the capped league heads the next run's queue"

        result, http = _crawl(self._week12(), ledger_path=db, now_ms=NOW + 70 * DAY_MS + HOUR_MS)
        assert _weeks_called(http) == [7, 8, 9, 10, 11, 12]
        assert result.leagues_fetched == 1 and result.leagues_catchup_capped == 0
        assert {"t2", "t4", "t10"} <= _trade_ids(db)
        cov = _coverage_rows(db)["L1"]
        assert cov["through_week"] == 12
        assert cov["resume_week"] == 11, "week 12 was first seen an hour ago: inside the grace"
        assert _fetch_rows(db)["L1"]["max_created_ms"] == NOW + 56 * DAY_MS

    def test_the_coverage_metric_counts_the_league_as_behind(self, db, monkeypatch):
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1", "L9"],
        )
        self._setup(db)
        _crawl(self._week12(), ledger_path=db, now_ms=NOW + 70 * DAY_MS)
        week_cov = transactions.crawl_coverage(ledger_path=db)["weekCoverage"]
        assert week_cov == {
            "season": SEASON,
            "currentWeek": 12,
            "leaguesWithWeekCoverage": 1,
            "leaguesBehind": 1,
            "leaguesTwoPlusWeeksBehind": 1,
            "maxWeeksBehind": 12 - transactions.CATCHUP_MAX_WEEKS_PER_VISIT,
            "leaguesWithoutWeekCoverage": 1,
            "weeksAbandoned": 0,
            "leaguesWithAbandonedWeek": 0,
        }
        assert "L1" not in json.dumps(week_cov) and "L9" not in json.dumps(week_cov)


class TestNoDuplicatesFromRefetchedWeeks:
    def test_an_overlapping_window_ingests_nothing_twice(self, db):
        t10 = trade("t10", NOW - DAY_MS, {"p1": 1}, {"p1": 2})
        resp = league_weeks("L1", {10: [t10]}, week=10)
        _crawl(resp, ledger_path=db)
        before = ledger.counts(path=db)
        # Same week, inside the grace: weeks 9 and 10 are read again.
        again, http = _crawl(resp, ledger_path=db, now_ms=NOW + HOUR_MS)
        assert _weeks_called(http) == [9, 10]
        assert again.movements_ingested == 0
        assert ledger.counts(path=db) == before

    def test_a_catch_up_over_already_stored_weeks_ingests_nothing_twice(self, db):
        by_week = {
            9: [trade("t9", NOW - 3 * DAY_MS, {"p9": 1}, {"p9": 2})],
            10: [trade("t10", NOW - DAY_MS, {"p1": 1}, {"p1": 2})],
        }
        _crawl(league_weeks("L1", by_week, week=10), ledger_path=db)
        before = ledger.counts(path=db)
        result, http = _crawl(
            league_weeks("L1", by_week, week=12), ledger_path=db, now_ms=NOW + 15 * DAY_MS
        )
        assert 9 in _weeks_called(http) and 10 in _weeks_called(http)
        assert result.movements_ingested == 0
        assert ledger.counts(path=db) == before


class TestRecoverySweep:
    """A league backfilled before week coverage existed has no row saying which
    weeks it reached, and its cursor may sit past a week no visit fetched."""

    def _legacy(self, db, *, max_created, last_fetched, boundary):
        conn = ledger.connect(db)
        try:
            conn.execute("DELETE FROM sharp_league_week_coverage WHERE league_id='L1'")
            conn.execute(
                "UPDATE sharp_league_fetch SET max_created_ms=?, last_fetched_ms=?,"
                " boundary_tx_ids=? WHERE league_id='L1'",
                (max_created, last_fetched, json.dumps(boundary)),
            )
            conn.commit()
        finally:
            conn.close()

    def test_rows_behind_the_cursor_are_recovered_within_the_backfill_window(self, db):
        t10 = trade("t10", NOW - DAY_MS, {"p1": 1}, {"p1": 2})
        _crawl(league_weeks("L1", {10: [t10]}, week=10), ledger_path=db)
        # The pre-coverage crawl visited in week 12 and fetched only week 12,
        # carrying the cursor past week 11, which nothing ever fetched.
        self._legacy(
            db, max_created=NOW + 15 * DAY_MS, last_fetched=NOW + 15 * DAY_MS, boundary=["t12"]
        )
        assert "t11" not in _trade_ids(db)
        now = NOW + 20 * DAY_MS
        stale = trade("stale", now - 35 * DAY_MS, {"p8": 1}, {"p8": 2})
        resp = league_weeks(
            "L1",
            {
                10: [t10, stale],
                11: [trade("t11", NOW + 8 * DAY_MS, {"p2": 1}, {"p2": 2})],
                12: [trade("t12", NOW + 15 * DAY_MS, {"p3": 2}, {"p3": 1})],
            },
            week=12,
        )
        result, http = _crawl(resp, ledger_path=db, now_ms=now)
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        assert _weeks_called(http) == list(range(12 - cap + 1, 13)), "week - cap + 1 .. week"
        ids = _trade_ids(db)
        assert {"t11", "t12"} <= ids, "recovered from behind the cursor"
        assert "stale" not in ids, "never past the backfill age window"
        assert result.movements_ingested == 4, "t10 was already stored: nothing twice"
        assert result.leagues_recovery_swept == 1
        assert _coverage_rows(db)["L1"]["through_week"] == 12

        # From now on it is an ordinary catch-up league.
        nxt, _ = _crawl(resp, ledger_path=db, now_ms=now + HOUR_MS)
        assert nxt.leagues_recovery_swept == 0 and nxt.movements_ingested == 0


class TestSeasonBoundary:
    def test_a_new_season_starts_from_its_first_bucket(self, db):
        _crawl(league_weeks("L1", {}, week=17, season="2025"), ledger_path=db)
        assert _coverage_rows(db)["L1"]["season"] == "2025"
        _, http = _crawl(
            league_weeks("L1", {}, week=2, season="2026"),
            ledger_path=db,
            now_ms=NOW + 250 * DAY_MS,
        )
        assert _weeks_called(http) == [0, 1, 2]
        row = _coverage_rows(db)["L1"]
        assert (row["season"], row["through_week"]) == ("2026", 2)

    def test_the_offseason_steady_state_is_both_degenerate_buckets(self, db):
        _crawl(league_weeks("L1", {}, week=17, season="2025"), ledger_path=db)
        _, http = _crawl(
            league_weeks("L1", {}, week=0, season="2026"),
            ledger_path=db,
            now_ms=NOW + 200 * DAY_MS,
        )
        assert sorted(_weeks_called(http)) == [0, 1]
        _, http = _crawl(
            league_weeks("L1", {}, week=1, season="2026"),
            ledger_path=db,
            now_ms=NOW + 230 * DAY_MS,
        )
        assert sorted(_weeks_called(http)) == [0, 1]
        assert _coverage_rows(db)["L1"]["resume_week"] == 0


class TestBudgetAndBreakerDuringCatchUp:
    def _setup(self, db):
        t9 = trade("t9", NOW - DAY_MS, {"p1": 1}, {"p1": 2})
        _crawl(league_weeks("L1", {9: [t9]}, week=9), ledger_path=db)
        return _fetch_rows(db)["L1"]

    def _week12(self, **overrides):
        by_week = {
            10: [trade("t10", NOW + 8 * DAY_MS, {"p2": 1}, {"p2": 2})],
            11: [trade("t11", NOW + 15 * DAY_MS, {"p3": 1}, {"p3": 2})],
        }
        resp = league_weeks("L1", by_week, week=12)
        resp.update(overrides)
        return resp

    def test_a_budget_cut_mid_catch_up_is_pending_and_resumes(self, db):
        before = self._setup(db)
        later = NOW + 21 * DAY_MS
        # /state/nfl + rosters + weeks 8 and 9, then the budget is gone.
        result, http = _crawl(self._week12(), ledger_path=db, budget=4, now_ms=later)
        assert _weeks_called(http) == [8, 9]
        assert result.stopped_reason == transactions.STOPPED_BUDGET_EXHAUSTED
        assert result.leagues_pending == 1 and result.leagues_failed == 0
        assert result.errors == {}
        row = _fetch_rows(db)["L1"]
        assert row["max_created_ms"] == before["max_created_ms"]
        assert row["last_fetched_ms"] == before["last_fetched_ms"]
        assert row["last_error"] == transactions.STOPPED_BUDGET_EXHAUSTED
        cov = _coverage_rows(db)["L1"]
        assert (cov["through_week"], cov["resume_week"]) == (9, 10), "never marked covered"

        nxt, http = _crawl(self._week12(), ledger_path=db, now_ms=later + HOUR_MS)
        assert _weeks_called(http) == [10, 11, 12]
        assert nxt.leagues_fetched == 1
        assert {"t9", "t10", "t11"} <= _trade_ids(db)

    def test_a_failed_week_stops_the_coverage_before_it(self, db):
        before = self._setup(db)
        later = NOW + 21 * DAY_MS
        resp = self._week12(**{f"{BASE}/league/L1/transactions/10": None})
        result, http = _crawl(resp, ledger_path=db, now_ms=later)
        assert _weeks_called(http) == [8, 9, 10, 11, 12]
        assert result.errors["L1"] == "transactions_fetch_failed"
        assert result.leagues_failed == 1
        assert _fetch_rows(db)["L1"]["max_created_ms"] == before["max_created_ms"]
        cov = _coverage_rows(db)["L1"]
        assert (cov["through_week"], cov["resume_week"]) == (9, 10)
        assert "t11" in _trade_ids(db), "clean weeks after the gap still ingest"

        nxt, http = _crawl(self._week12(), ledger_path=db, now_ms=later + HOUR_MS)
        assert _weeks_called(http) == [10, 11, 12], "the failed week is fetched again"
        assert nxt.leagues_fetched == 1 and nxt.movements_ingested == 2
        assert "t10" in _trade_ids(db)

    def test_a_refused_call_mid_catch_up_stops_the_pass(self, db):
        before = self._setup(db)
        resp = self._week12(**{f"{BASE}/league/L1/transactions/10": transactions.BREAKER_OPEN})
        result, http = _crawl(resp, ledger_path=db, now_ms=NOW + 21 * DAY_MS)
        assert _weeks_called(http) == [8, 9, 10]
        assert result.stopped_reason == transactions.STOPPED_BREAKER_OPEN
        assert _fetch_rows(db)["L1"]["max_created_ms"] == before["max_created_ms"]
        assert _coverage_rows(db)["L1"]["through_week"] == 9


class TestUnclockedRunsLeaveCoverageAlone:
    @pytest.mark.parametrize("state", [None, {}], ids=["failed", "no_week"])
    def test_no_usable_week_keeps_the_old_rule(self, db, state):
        _crawl(league_weeks("L1", {}, week=10), ledger_path=db)
        before = _coverage_rows(db)["L1"]
        resp = league_weeks("L1", {}, week=10)
        resp[f"{BASE}/state/nfl"] = state
        result, http = _crawl(resp, ledger_path=db, now_ms=NOW + DAY_MS)
        assert result.week_clocked is False and result.week == 1
        assert sorted(_weeks_called(http)) == [0, 1], "the old default-week rule"
        assert _coverage_rows(db)["L1"] == before, "a week nobody observed records nothing"

    @pytest.mark.parametrize("state", [None, {}], ids=["failed", "no_week"])
    def test_an_unclocked_visit_moves_no_cursor_and_no_queue_position(self, db, state):
        """Review NIT 2: a visit on a defaulted week used to stamp
        ``lastFetchedMs`` and advance the cursor.  It still ingests what it
        fetched, but nothing a later visit plans from may move on it."""
        _crawl(league_weeks("L1", {}, week=10), ledger_path=db)
        before = _fetch_rows(db)["L1"]
        resp = league_weeks(
            "L1", {1: [trade("t1", NOW + 2 * DAY_MS, {"p1": 1}, {"p1": 2})]}, week=10
        )
        resp[f"{BASE}/state/nfl"] = state
        result, _ = _crawl(resp, ledger_path=db, now_ms=NOW + 3 * DAY_MS)
        assert result.leagues_fetched == 1 and result.leagues_failed == 0
        assert "t1" in _trade_ids(db), "what it fetched is still ingested"
        after = _fetch_rows(db)["L1"]
        assert after["last_fetched_ms"] == before["last_fetched_ms"], "keeps its queue place"
        assert after["max_created_ms"] == before["max_created_ms"], "cursor not moved"
        assert after["backfilled"] == 1

    @pytest.mark.parametrize("state", [None, {}], ids=["failed", "no_week"])
    def test_a_new_league_is_not_backfilled_on_a_week_nobody_observed(self, db, state):
        """A new league visited on a defaulted week used to be marked backfilled
        after fetching only buckets 1 and 0, so its real backfill walk never
        ran.  It now stays un-backfilled and walks from the real week next run."""
        resp = league_weeks("L1", {}, week=10)
        resp[f"{BASE}/state/nfl"] = state
        result, http = _crawl(resp, ledger_path=db)
        assert sorted(_weeks_called(http)) == [0, 1]
        assert result.leagues_fetched == 1
        row = _fetch_rows(db)["L1"]
        assert (row["backfilled"], row["last_fetched_ms"], row["max_created_ms"]) == (0, 0, 0)
        assert "L1" not in _coverage_rows(db)

        nxt, http = _crawl(league_weeks("L1", {}, week=10), ledger_path=db, now_ms=NOW + HOUR_MS)
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        assert _weeks_called(http) == list(range(10, 10 - cap, -1)), "the real backfill walk"
        assert _fetch_rows(db)["L1"]["backfilled"] == 1
        assert _coverage_rows(db)["L1"]["through_week"] == 10
        assert nxt.leagues_fetched == 1


class TestWeekCoverageStorage:
    def test_the_tables_are_additive_and_ride_no_migration(self, db):
        conn = ledger.connect(db)
        try:
            transactions.ensure_week_coverage_schema(conn)
            transactions.ensure_week_coverage_schema(conn)
            assert transactions._load_week_coverage(conn) == {}
            version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        finally:
            conn.close()
        assert str(version[0]) == str(ledger.SCHEMA_VERSION)

    def test_a_ledger_without_the_tables_reads_as_no_coverage(self, tmp_path):
        import sqlite3

        conn = sqlite3.connect(tmp_path / "bare.sqlite3")
        conn.row_factory = sqlite3.Row
        try:
            assert transactions._load_week_coverage(conn) == {}
            assert transactions._week_coverage_summary(conn, {"L1"})["currentWeek"] is None
        finally:
            conn.close()

    def test_coverage_before_any_clocked_run_is_unmeasured_not_zero(self, db, monkeypatch):
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1"],
        )
        week_cov = transactions.crawl_coverage(ledger_path=db)["weekCoverage"]
        assert set(week_cov.values()) == {None}

    def test_the_run_receipt_carries_the_new_counts(self, db):
        result, _ = _crawl(league_weeks("L1", {}, week=10), ledger_path=db)
        payload = result.to_dict()
        assert payload["season"] == SEASON and payload["weekClocked"] is True
        for key in ("leaguesCaughtUp", "leaguesCatchupCapped", "leaguesRecoverySwept"):
            assert payload[key] == 0


# ---------------------------------------------------------------------------
# Review fixes (PR #2311, 2026-11-22)
# ---------------------------------------------------------------------------

MAX_ATTEMPTS = transactions.WEEK_FETCH_MAX_ATTEMPTS


def _progress(weeks, outcomes, fail_week=None, fail_count=0, abandon_below=99):
    return transactions._week_progress(
        weeks,
        outcomes,
        prior_fail_week=fail_week,
        prior_fail_count=fail_count,
        abandon_below=abandon_below,
    )


class TestWeekProgress:
    """Where one ascending visit's gap-free run ends, and when a failing week
    is given up on.  Pure function, every branch."""

    def test_a_clean_run_reaches_its_last_week(self):
        p = _progress([4, 5, 6], {4: True, 5: True, 6: True})
        assert (p.through, p.stall_week, p.stall_count, p.abandoned) == (6, None, 0, ())

    def test_a_first_failure_stops_the_run_and_counts_once(self):
        p = _progress([4, 5, 6], {4: True, 5: False, 6: True})
        assert (p.through, p.stall_week, p.stall_count) == (4, 5, 1)

    def test_the_same_week_failing_again_counts_up(self):
        p = _progress([5, 6], {5: False, 6: True}, fail_week=5, fail_count=1)
        assert (p.through, p.stall_week, p.stall_count) == (4, 5, 2)

    def test_a_different_week_failing_starts_a_new_count(self):
        p = _progress([5, 6, 7], {5: True, 6: False}, fail_week=5, fail_count=2)
        assert (p.stall_week, p.stall_count) == (6, 1)

    def test_at_the_limit_the_week_is_abandoned_and_the_run_continues(self):
        p = _progress([5, 6, 7, 8], {5: False, 6: True, 7: True, 8: True}, 5, MAX_ATTEMPTS - 1)
        assert (p.through, p.stall_week, p.abandoned) == (8, None, (5,))

    def test_past_an_abandoned_week_the_next_failure_counts_from_one(self):
        p = _progress([5, 6, 7], {5: False, 6: True, 7: False}, 5, MAX_ATTEMPTS - 1)
        assert (p.through, p.stall_week, p.stall_count, p.abandoned) == (6, 7, 1, (5,))

    def test_a_week_inside_the_steady_window_keeps_counting_and_is_not_abandoned(self):
        """It is fetched on every visit anyway, so abandoning it would neither
        unblock anything nor be true; it is abandoned (once) after it leaves."""
        p = _progress([11, 12], {11: True, 12: False}, 12, MAX_ATTEMPTS + 2, abandon_below=12)
        assert (p.through, p.stall_week, p.stall_count, p.abandoned) == (
            11,
            12,
            MAX_ATTEMPTS + 3,
            (),
        )
        # A week later week 12 is below the floor: its next failure abandons it.
        p = _progress([12, 13], {12: False, 13: True}, 12, MAX_ATTEMPTS + 3, abandon_below=13)
        assert (p.through, p.abandoned) == (13, (12,))

    def test_a_week_that_answers_clears_the_count(self):
        p = _progress([5, 6], {5: True, 6: True}, fail_week=5, fail_count=2)
        assert (p.through, p.stall_week, p.stall_count) == (6, None, 0)

    def test_an_unreached_pending_week_is_neither_counted_nor_cleared(self):
        """A budget cut or a refused call is not an attempt: the outcome is
        absent, so the failure recorded on an earlier visit stands as it was."""
        p = _progress([4, 5, 6], {4: True}, fail_week=6, fail_count=2)
        assert (p.through, p.stall_week, p.stall_count) == (4, 6, 2)
        p = _progress([5, 6], {}, fail_week=5, fail_count=2)
        assert (p.through, p.stall_week, p.stall_count) == (4, 5, 2)


class TestAWeekThatKeepsFailingCannotStallTheLeague:
    """Review IMPORTANT 1.  Week 4 fails on every call and the crawl runs in
    week 15.  The catch-up used to fetch ``[4..9]`` forever: the gap-free run
    never passed week 4, the cap never let it reach week 10, and the league,
    never clean, kept its old ``lastFetchedMs`` and headed the queue every run
    -- weeks 10-14 were never stored.  Week 4 is now abandoned after
    ``WEEK_FETCH_MAX_ATTEMPTS`` visits, counted, and the league moves on."""

    def _setup(self, db):
        _crawl(league_weeks("L1", {}, week=2), ledger_path=db)

    def _week15(self):
        by_week = {
            w: [trade(f"t{w}", NOW + w * DAY_MS, {f"p{w}": 1}, {f"p{w}": 2})] for w in range(1, 15)
        }
        resp = league_weeks("L1", by_week, week=15)
        resp[f"{BASE}/league/L1/transactions/4"] = None  # fails on every call
        return resp

    def test_the_weeks_behind_a_failing_week_are_collected(self, db, monkeypatch):
        monkeypatch.setattr(
            transactions.discovery,
            "sharp_eligible_league_ids",
            lambda *, ledger_path=None: ["L1"],
        )
        self._setup(db)
        start = NOW + 91 * DAY_MS
        runs = []
        for i in range(MAX_ATTEMPTS + 1):
            runs.append(_crawl(self._week15(), ledger_path=db, now_ms=start + i * 6 * HOUR_MS))

        calls_to_week_4 = sum(_weeks_called(http).count(4) for _r, http in runs)
        assert calls_to_week_4 == MAX_ATTEMPTS, "week 4 is tried, then given up on"
        ids = _trade_ids(db)
        assert {f"t{w}" for w in range(10, 15)} <= ids, "weeks 10-14 now arrive"
        assert {f"t{w}" for w in (1, 2, 3, 5, 6, 7, 8, 9)} <= ids
        assert "t4" not in ids, "the abandoned week's rows really are lost"

        results = [r for r, _h in runs]
        assert sum(r.weeks_abandoned for r in results) == 1
        assert [r.leagues_with_abandoned_week for r in results] == [0] * (MAX_ATTEMPTS - 1) + [1, 0]
        assert results[MAX_ATTEMPTS - 1].to_dict()["weeksAbandoned"] == 1
        assert results[-1].leagues_fetched == 1, "the league completes a clean visit"
        assert _fetch_rows(db)["L1"]["max_created_ms"] == NOW + 14 * DAY_MS, "cursor advanced"

        cov = _coverage_rows(db)["L1"]
        assert cov["abandoned_weeks"] == 1 and cov["fail_week"] is None
        assert cov["through_week"] == 15
        week_cov = transactions.crawl_coverage(ledger_path=db)["weekCoverage"]
        assert week_cov["weeksAbandoned"] == 1 and week_cov["leaguesWithAbandonedWeek"] == 1

    def test_the_failure_count_is_persisted_between_visits(self, db):
        self._setup(db)
        start = NOW + 91 * DAY_MS
        _crawl(self._week15(), ledger_path=db, now_ms=start)
        cov = _coverage_rows(db)["L1"]
        assert (cov["through_week"], cov["resume_week"]) == (3, 4)
        assert (cov["fail_week"], cov["fail_count"]) == (4, 1)
        # Second visit: week 4 is the plan's first week and fails again.  The
        # row is still written, so the count survives a visit with no progress.
        _crawl(self._week15(), ledger_path=db, now_ms=start + 6 * HOUR_MS)
        cov = _coverage_rows(db)["L1"]
        assert (cov["through_week"], cov["resume_week"]) == (3, 4)
        assert (cov["fail_week"], cov["fail_count"]) == (4, 2)

    def test_a_week_that_recovers_before_the_limit_is_not_abandoned(self, db):
        self._setup(db)
        start = NOW + 91 * DAY_MS
        for i in range(MAX_ATTEMPTS - 1):
            _crawl(self._week15(), ledger_path=db, now_ms=start + i * 6 * HOUR_MS)
        healthy = self._week15()
        healthy[f"{BASE}/league/L1/transactions/4"] = [
            trade("t4", NOW + 4 * DAY_MS, {"p4": 1}, {"p4": 2})
        ]
        result, _ = _crawl(healthy, ledger_path=db, now_ms=start + 12 * HOUR_MS)
        assert result.weeks_abandoned == 0
        assert "t4" in _trade_ids(db)
        cov = _coverage_rows(db)["L1"]
        assert (cov["fail_week"], cov["fail_count"], cov["abandoned_weeks"]) == (None, 0, 0)

    def test_a_refused_call_on_the_failing_week_is_not_an_attempt(self, db):
        self._setup(db)
        start = NOW + 91 * DAY_MS
        _crawl(self._week15(), ledger_path=db, now_ms=start)
        refused = self._week15()
        refused[f"{BASE}/league/L1/transactions/4"] = transactions.BREAKER_OPEN
        result, _ = _crawl(refused, ledger_path=db, now_ms=start + 6 * HOUR_MS)
        assert result.stopped_reason == transactions.STOPPED_BREAKER_OPEN
        cov = _coverage_rows(db)["L1"]
        assert (cov["fail_week"], cov["fail_count"]) == (4, 1), "unchanged"

    def test_a_failed_re_read_of_a_covered_week_does_not_uncover_it(self, db):
        """After an in-grace visit the previous week is re-read; if that re-read
        fails, the week stays covered (no lag reported) while the resume still
        retries it."""
        _crawl(league_weeks("L1", {}, week=10), ledger_path=db)  # in grace: resume 9
        resp = league_weeks("L1", {}, week=10)
        resp[f"{BASE}/league/L1/transactions/9"] = None
        result, http = _crawl(resp, ledger_path=db, now_ms=NOW + 3 * DAY_MS)
        assert _weeks_called(http) == [9, 10]
        assert result.leagues_failed == 1
        cov = _coverage_rows(db)["L1"]
        assert (cov["through_week"], cov["resume_week"]) == (10, 9)
        assert (cov["fail_week"], cov["fail_count"]) == (9, 1)


class TestASeasonRestartIsBounded:
    def test_a_spurious_season_change_mid_season_costs_one_sweep(self, db):
        """Review NIT 5: a new season string at week 12 used to restart the
        walk at week 0 -- 13 weeks, three capped visits per league."""
        _crawl(league_weeks("L1", {}, week=12, season="2026"), ledger_path=db)
        result, http = _crawl(
            league_weeks("L1", {}, week=12, season="2027"),
            ledger_path=db,
            now_ms=NOW + 3 * DAY_MS,
        )
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        assert _weeks_called(http) == list(range(12 - cap + 1, 13))
        assert result.leagues_catchup_capped == 0 and result.leagues_fetched == 1
        row = _coverage_rows(db)["L1"]
        assert (row["season"], row["through_week"]) == ("2027", 12)


class TestStaleCoverageAfterAMigration:
    """Review NIT 3: a migration that clears ``sharp_league_fetch`` leaves the
    coverage row behind.  The crawl must never resume from it."""

    def _migrate(self, db):
        conn = ledger.connect(db)
        try:
            conn.execute("DELETE FROM sharp_league_fetch")
            conn.commit()
        finally:
            conn.close()

    def test_an_unclocked_run_after_a_migration_cannot_resume_from_the_stale_row(self, db):
        _crawl(league_weeks("L1", {}, week=12), ledger_path=db)
        self._migrate(db)
        down = league_weeks("L1", {}, week=12)
        down[f"{BASE}/state/nfl"] = None
        _crawl(down, ledger_path=db, now_ms=NOW + DAY_MS)
        assert _fetch_rows(db)["L1"]["backfilled"] == 0, "not backfilled on a guessed week"

        _, http = _crawl(league_weeks("L1", {}, week=14), ledger_path=db, now_ms=NOW + 15 * DAY_MS)
        cap = transactions.CATCHUP_MAX_WEEKS_PER_VISIT
        assert _weeks_called(http) == list(range(14, 14 - cap, -1)), "a backfill, not a resume"
        row = _coverage_rows(db)["L1"]
        assert row["through_week"] == 14 and row["updated_ms"] == NOW + 15 * DAY_MS

    def test_a_backfill_that_writes_no_coverage_deletes_the_stale_row(self, db, monkeypatch):
        _crawl(league_weeks("L1", {}, week=12), ledger_path=db)
        self._migrate(db)
        assert "L1" in _coverage_rows(db)
        monkeypatch.setattr(
            transactions,
            "_plan_weeks",
            lambda *a, **k: transactions._WeekPlan(weeks=[], mode=transactions._MODE_BACKFILL),
        )
        _crawl(league_weeks("L1", {}, week=12), ledger_path=db, now_ms=NOW + DAY_MS)
        assert _fetch_rows(db)["L1"]["backfilled"] == 1
        assert "L1" not in _coverage_rows(db), "no stale row survives a backfill"

    def test_any_later_migration_that_clears_the_cursor_clears_the_coverage(self):
        """The rule ``ensure_week_coverage_schema`` documents.  Version 2 runs
        inside ``ledger.connect`` before the coverage table can exist; every
        later step that clears ``sharp_league_fetch`` must clear the coverage
        table too, or ``crawl_coverage`` reports deleted weeks as covered."""
        for version, tables in ledger._MIGRATION_CLEARS.items():
            if version > 2 and "sharp_league_fetch" in tables:
                assert "sharp_league_week_coverage" in tables, version


class TestWeekCoverageColumnsAreAddedToAnExistingTable:
    _OLD_SHAPE = """
        CREATE TABLE sharp_league_week_coverage (
          league_id    TEXT PRIMARY KEY,
          season       TEXT NOT NULL,
          through_week INTEGER NOT NULL,
          resume_week  INTEGER NOT NULL,
          updated_ms   INTEGER NOT NULL
        )
    """

    def test_an_old_shaped_table_reads_and_then_gains_the_columns(self, db):
        conn = ledger.connect(db)
        try:
            conn.execute(self._OLD_SHAPE)
            conn.execute(
                "INSERT INTO sharp_league_week_coverage VALUES ('L1', ?, 7, 7, ?)", (SEASON, NOW)
            )
            conn.commit()
            # Read-only callers (crawl_coverage) see the old shape: defaults.
            cov = transactions._load_week_coverage(conn)["L1"]
            assert (cov.fail_week, cov.fail_count, cov.abandoned_weeks) == (None, 0, 0)
            transactions.ensure_week_coverage_schema(conn)
            transactions.ensure_week_coverage_schema(conn)  # repeatable
            cols = {r[1] for r in conn.execute("PRAGMA table_info(sharp_league_week_coverage)")}
            assert {"fail_week", "fail_count", "abandoned_weeks"} <= cols
            row = conn.execute("SELECT * FROM sharp_league_week_coverage").fetchone()
            assert (row["through_week"], row["fail_count"], row["abandoned_weeks"]) == (7, 0, 0)
        finally:
            conn.close()

    def test_a_crawl_over_an_old_shaped_table_works(self, db):
        _crawl(league_weeks("L1", {}, week=7), ledger_path=db)
        conn = ledger.connect(db)
        try:
            conn.execute("DROP TABLE sharp_league_week_coverage")
            conn.execute(self._OLD_SHAPE)
            conn.execute(
                "INSERT INTO sharp_league_week_coverage VALUES ('L1', ?, 7, 7, ?)", (SEASON, NOW)
            )
            conn.commit()
        finally:
            conn.close()
        result, http = _crawl(
            league_weeks("L1", {}, week=9), ledger_path=db, now_ms=NOW + 14 * DAY_MS
        )
        assert _weeks_called(http) == [7, 8, 9]
        assert result.leagues_fetched == 1
        row = _coverage_rows(db)["L1"]
        assert (row["through_week"], row["fail_count"], row["abandoned_weeks"]) == (9, 0, 0)
