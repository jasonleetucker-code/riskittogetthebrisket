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
