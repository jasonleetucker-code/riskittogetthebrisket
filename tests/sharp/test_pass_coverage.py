"""Honest per-run coverage for the four Sharp crawl passes.

Every pass runs under a hard Sleeper call budget against a far larger
population, and used to report only ``budgetExhausted``.  These tests pin the
additive ``passCoverage`` block (see ``src/sharp/pass_coverage.py``):

* a budget stop with work left says ``budget_exhausted`` and counts what was
  attempted, what succeeded, what failed and what was never reached;
* a queue that was drained says ``completed`` -- even when the budget happens to
  be spent at that moment, which the old flag reported as an exhaustion;
* a quantity that could not be measured is ``None``, never ``0``;
* nothing about selection, ordering, scoring or exit codes moved.

Every Sleeper call is faked.  No network anywhere.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import sys
import time
from pathlib import Path

import pytest

from src.intel import ledger, platform_ledger
from src.platforms.base import NormalizedLeague, NormalizedManager, NormalizedMembership
from src.sharp import discovery, pass_coverage, records
from src.sharp import record_queue as rq
from src.sharp import roster_collect as rc

REPO = Path(__file__).resolve().parents[2]
# The wall clock at import: rows the ledger stamps itself (``time.time()``) are
# never earlier than this, so ages computed against it cannot go negative.
NOW = int(time.time() * 1000)
DAY = 86_400_000


@pytest.fixture(autouse=True)
def _fixed_clock(monkeypatch):
    """Every age in this file is measured against one fixed instant."""
    monkeypatch.setattr(pass_coverage, "now_ms", lambda: NOW)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    yield tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.reset_setup_cache()


class FakeSleeper:
    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        return self.responses.get(url)


def _boom(*_args, **_kwargs):
    """Stands in for a coverage helper that has a bug in it."""
    raise RuntimeError("coverage helper exploded")


#: The only fields a coverage fault may change.
_COVERAGE_KEYS = ("stoppedReason", "passCoverage")


def without_coverage(payload):
    return {k: v for k, v in payload.items() if k not in _COVERAGE_KEYS}


def coverage_failure_warnings(caplog):
    return [r for r in caplog.records if "could not build pass coverage" in r.getMessage()]


# ── the shared vocabulary ────────────────────────────────────────────


class TestSharedHelpers:
    @pytest.mark.parametrize(
        ("kwargs", "expected"),
        [
            # A drained queue is completed however spent the budget is.
            ({"budget_stopped": True, "work_remains": False}, "completed"),
            ({"budget_stopped": False, "work_remains": False}, "completed"),
            ({"budget_stopped": True, "work_remains": True}, "budget_exhausted"),
            # Work left over for a reason other than the budget is not a budget stop.
            ({"budget_stopped": False, "work_remains": True}, "completed"),
            ({"budget_stopped": False, "work_remains": False, "capped": True}, "cap_reached"),
            ({"budget_stopped": True, "work_remains": True, "capped": True}, "budget_exhausted"),
            (
                {"budget_stopped": True, "work_remains": True, "breaker_blocked": True},
                "sleeper_breaker_open",
            ),
        ],
    )
    def test_classify_stop(self, kwargs, expected):
        assert pass_coverage.classify_stop(**kwargs) == expected

    def test_an_unobserved_visit_has_no_age_rather_than_an_age_of_zero(self):
        assert pass_coverage.age_days(None, as_of_ms=NOW) is None
        assert pass_coverage.age_days(NOW - 82 * DAY, as_of_ms=NOW) == 82.0
        # Clock skew reads as "just now", not as a negative age.
        assert pass_coverage.age_days(NOW + DAY, as_of_ms=NOW) == 0.0

    def test_unmeasured_figures_are_null_not_zero(self):
        block = pass_coverage.build_pass_coverage(
            pass_name="records",
            unit="leagues",
            attempted=None,
            succeeded=None,
            failed=None,
            eligible_total=None,
            remaining_unvisited=None,
            stopped_reason="unknown",
            calls_used=None,
        )
        for key in (
            "attempted",
            "succeeded",
            "failed",
            "eligibleTotal",
            "remainingUnvisited",
            "neverVisited",
            "oldestCrawlMs",
            "oldestCrawlAgeDays",
            "callsUsed",
            "callBudget",
        ):
            assert block[key] is None, key
        assert json.loads(json.dumps(block))["remainingUnvisited"] is None

    @pytest.mark.parametrize(
        ("reason", "level"),
        [
            ("budget_exhausted", logging.WARNING),
            ("sleeper_breaker_open", logging.WARNING),
            ("work_pending", logging.WARNING),
            ("cap_reached", logging.WARNING),
            ("upstream_data_missing", logging.WARNING),
            ("unknown", logging.WARNING),
            ("completed", logging.INFO),
            ("no_work", logging.INFO),
            ("skipped_by_caller", logging.INFO),
        ],
    )
    def test_one_summary_line_warns_only_when_the_run_stopped_short(self, caplog, reason, level):
        coverage = pass_coverage.build_pass_coverage(
            pass_name="rosters",
            unit="leagues",
            attempted=10,
            succeeded=9,
            failed=1,
            eligible_total=100,
            remaining_unvisited=90,
            stopped_reason=reason,
            calls_used=20,
            call_budget=20,
        )
        logger = logging.getLogger("test.pass_coverage")
        with caplog.at_level(logging.DEBUG, logger="test.pass_coverage"):
            used = pass_coverage.log_pass_summary(logger, coverage)
        assert used == level
        lines = [r for r in caplog.records if r.name == "test.pass_coverage"]
        assert len(lines) == 1
        assert lines[0].levelno == level
        message = lines[0].getMessage()
        assert f"stoppedReason={reason}" in message
        assert "attempted=10" in message
        assert "remainingUnvisited=90" in message

    def test_the_stop_vocabulary_is_the_transactions_pass_vocabulary(self):
        """One ``stoppedReason`` value per cause across the Sharp passes.

        ``transactions.py`` owns its constants; a drift here would make the same
        breaker stop read as two different strings to whoever aggregates the
        passes' output.
        """
        from src.sharp import transactions

        assert pass_coverage.STOPPED_BREAKER_OPEN == transactions.STOPPED_BREAKER_OPEN
        assert pass_coverage.STOPPED_BUDGET_EXHAUSTED == transactions.STOPPED_BUDGET_EXHAUSTED
        assert pass_coverage.STOPPED_BREAKER_OPEN == "sleeper_breaker_open"

    @pytest.mark.parametrize(
        ("attempted", "succeeded", "level"),
        [
            # Every attempt failed: the queue may have drained, the run is not healthy.
            (5, 0, logging.WARNING),
            (5, 1, logging.INFO),
            # Nothing attempted is not "everything failed".
            (0, 0, logging.INFO),
            # Unmeasured is not "everything failed" either.
            (None, None, logging.INFO),
            (5, None, logging.INFO),
        ],
    )
    def test_a_completed_run_whose_every_attempt_failed_warns(
        self, caplog, attempted, succeeded, level
    ):
        coverage = pass_coverage.build_pass_coverage(
            pass_name="rosters",
            unit="leagues",
            attempted=attempted,
            succeeded=succeeded,
            failed=None if attempted is None else attempted - (succeeded or 0),
            eligible_total=attempted,
            remaining_unvisited=0,
            stopped_reason="completed",
            calls_used=10,
            call_budget=100,
        )
        logger = logging.getLogger("test.pass_coverage.failed")
        with caplog.at_level(logging.DEBUG, logger="test.pass_coverage.failed"):
            assert pass_coverage.log_pass_summary(logger, coverage) == level
        # The reason itself is not rewritten by the log level.
        assert coverage["stoppedReason"] == "completed"
        assert "stoppedReason=completed" in caplog.records[-1].getMessage()

    def test_the_summary_line_prints_null_as_na_never_zero(self, caplog):
        coverage = pass_coverage.build_pass_coverage(
            pass_name="rosters",
            unit="leagues",
            attempted=0,
            succeeded=0,
            failed=0,
            eligible_total=None,
            remaining_unvisited=None,
            stopped_reason="skipped_by_caller",
            calls_used=0,
        )
        assert "eligibleTotal=n/a" in pass_coverage.format_summary(coverage)
        assert "oldestCrawlAgeDays=n/a" in pass_coverage.format_summary(coverage)

    def test_breaker_refusals_need_both_readings(self):
        assert pass_coverage.breaker_refusals(3, 10) == 7
        assert pass_coverage.breaker_refusals(None, 10) is None
        assert pass_coverage.breaker_refusals(3, None) is None


# ── discovery ────────────────────────────────────────────────────────

D_BASE = discovery.SLEEPER_BASE


def d_league(league_id, rosters=12):
    return {
        "league_id": league_id,
        "name": f"League {league_id}",
        "season": "2026",
        "total_rosters": rosters,
        "settings": {"type": 2, "best_ball": 0},
    }


def d_user(uid):
    return {"user_id": uid, "username": f"u{uid}", "display_name": f"U{uid}"}


def d_seeds(seed_leagues=None, seed_users=None, *, max_leagues=5000, **traversal):
    trav = {
        "maxGenerations": 4,
        "seasons": ["2026"],
        "perUserLeagueCap": 40,
        "maxLeagueRosters": 32,
        "minLeagueRosters": 6,
        "callBudgetPerRun": 500,
        "sleepSecondsBetweenCalls": 0,
    }
    trav.update(traversal)
    return {
        "seedLeagues": [{"leagueId": lid} for lid in (seed_leagues or [])],
        "seedUsers": [{"userId": uid} for uid in (seed_users or [])],
        "traversal": trav,
        "limits": {"maxUsersPerRun": 20000, "maxLeaguesPerRun": max_leagues},
    }


def wide_graph(*, expand_leagues=False):
    """A seed league with ten members, each in one league of their own.

    ``expand_leagues`` also answers each of those leagues' member lists (empty),
    so the whole graph can be walked to its end without a failed fetch.
    """
    responses = {
        f"{D_BASE}/league/L0/users": [d_user(f"u{i}") for i in range(10)],
        **{f"{D_BASE}/user/u{i}/leagues/nfl/2026": [d_league(f"L{i}")] for i in range(10)},
    }
    if expand_leagues:
        responses.update({f"{D_BASE}/league/L{i}/users": [] for i in range(1, 10)})
    return FakeSleeper(responses)


class TestDiscoveryCoverage:
    def test_a_budget_stop_reports_what_was_reached_and_what_was_not(self, db):
        res = discovery.discover(
            http_get=wide_graph(),
            seeds=d_seeds(seed_leagues=["L0"], callBudgetPerRun=3),
            ledger_path=db,
        )
        cov = res.to_dict()["passCoverage"]

        assert res.to_dict()["stoppedReason"] == "budget_exhausted"
        assert cov["pass"] == "discovery"
        assert cov["stoppedReason"] == "budget_exhausted"
        # L0's member list, then u0 and u1's league lists.
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (3, 3, 0)
        # u2..u9 (gen 1) and L1 (gen 2) are queued and expandable.
        assert cov["remainingUnvisited"] == 9
        assert cov["eligibleTotal"] == 12
        assert cov["eligibleTotalIsLowerBound"] is True
        assert (cov["callsUsed"], cov["callBudget"]) == (3, 3)

    def test_a_drained_queue_is_completed(self, db):
        res = discovery.discover(
            http_get=wide_graph(expand_leagues=True),
            seeds=d_seeds(seed_leagues=["L0"]),
            ledger_path=db,
        )
        cov = res.pass_coverage
        assert cov["stoppedReason"] == "completed"
        assert cov["remainingUnvisited"] == 0
        assert cov["failed"] == 0
        assert cov["attempted"] == cov["succeeded"] > 0

    def test_nodes_past_max_generations_are_not_work_left_undone(self, db):
        """The walk never expands them, so a spent budget beside them is not a stop.

        The old flag reads True here (the queue is non-empty); the coverage block
        says what actually happened.
        """
        http = FakeSleeper(
            {
                f"{D_BASE}/league/L0/users": [d_user("u1")],
                f"{D_BASE}/user/u1/leagues/nfl/2026": [d_league("D1")],
            }
        )
        res = discovery.discover(
            http_get=http,
            seeds=d_seeds(seed_leagues=["L0"], maxGenerations=1, callBudgetPerRun=2),
            ledger_path=db,
        )
        assert res.budget_exhausted is True  # the existing flag, unchanged
        assert res.pass_coverage["remainingUnvisited"] == 0
        assert res.pass_coverage["stoppedReason"] == "completed"

    def test_failures_are_counted_not_just_listed(self, db):
        http = FakeSleeper(
            {
                f"{D_BASE}/league/L0/users": [d_user("u1"), d_user("u2")],
                f"{D_BASE}/user/u1/leagues/nfl/2026": [],
                # u2's league list is absent: a failed fetch.
            }
        )
        res = discovery.discover(http_get=http, seeds=d_seeds(seed_leagues=["L0"]), ledger_path=db)
        cov = res.pass_coverage
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (3, 2, 1)
        assert any("user_leagues_fetch_failed" in e for e in res.errors)

    def test_the_size_cap_is_reported_as_a_cap_not_a_budget(self, db):
        http = FakeSleeper(
            {
                f"{D_BASE}/league/L0/users": [],
                f"{D_BASE}/league/L1/users": [],
            }
        )
        res = discovery.discover(
            http_get=http,
            seeds=d_seeds(seed_leagues=["L0", "L1"], max_leagues=1),
            ledger_path=db,
        )
        assert res.capped is True
        assert res.pass_coverage["stoppedReason"] == "cap_reached"

    def test_calls_the_breaker_refused_are_reported_as_sleeper_breaker_open(self, db, monkeypatch):
        readings = iter([0, 4])
        monkeypatch.setattr(
            pass_coverage, "sleeper_breaker_fast_fails", lambda: next(readings, None)
        )
        res = discovery.discover(
            http_get=wide_graph(),
            seeds=d_seeds(seed_leagues=["L0"], callBudgetPerRun=3),
            ledger_path=db,
        )
        assert res.pass_coverage["stoppedReason"] == "sleeper_breaker_open"
        assert res.pass_coverage["breakerRefusedCalls"] == 4

    def test_the_oldest_observation_is_the_stalest_league_discovery_still_holds(self, db):
        ledger.upsert_leagues([{"league_id": "ANCIENT", "season": "2024"}], path=db)
        conn = ledger.connect(db)
        try:
            conn.execute(
                "UPDATE leagues SET last_crawled_ms=? WHERE league_id='ANCIENT'",
                (NOW - 40 * DAY,),
            )
            conn.commit()
        finally:
            conn.close()
        res = discovery.discover(
            http_get=wide_graph(expand_leagues=True),
            seeds=d_seeds(seed_leagues=["L0"]),
            ledger_path=db,
        )
        assert res.pass_coverage["oldestCrawlMs"] == NOW - 40 * DAY
        assert res.pass_coverage["oldestCrawlAgeDays"] == 40.0

    def test_the_summary_line_is_logged_once_and_warns_on_a_budget_stop(self, db, caplog):
        with caplog.at_level(logging.INFO, logger=discovery.log.name):
            discovery.discover(
                http_get=wide_graph(),
                seeds=d_seeds(seed_leagues=["L0"], callBudgetPerRun=3),
                ledger_path=db,
            )
        lines = [r for r in caplog.records if r.getMessage().startswith("sharp.coverage ")]
        assert len(lines) == 1
        assert lines[0].levelno == logging.WARNING
        assert "pass=discovery" in lines[0].getMessage()


# ── records ──────────────────────────────────────────────────────────

R_BASE = records.SLEEPER_BASE


def r_league(lid, season="2026", *, previous="0", status="complete"):
    return {
        "league_id": lid,
        "season": season,
        "status": status,
        "total_rosters": 2,
        "previous_league_id": previous,
        "settings": {"type": 2, "best_ball": 0},
    }


def r_roster(rid, owner):
    return {
        "roster_id": rid,
        "owner_id": owner,
        "settings": {"wins": 8, "losses": 6, "ties": 0, "fpts": 1500, "fpts_decimal": 50},
    }


def r_bracket():
    return [{"m": 1, "r": 1, "t1": 1, "t2": 2, "w": 1, "l": 2, "p": 1}]


def single_season_leagues(*ids):
    """One completed season per league: league + rosters + winners_bracket = 3 calls."""
    responses = {}
    for lid in ids:
        responses[f"{R_BASE}/league/{lid}"] = r_league(lid)
        responses[f"{R_BASE}/league/{lid}/rosters"] = [r_roster(1, "a"), r_roster(2, "b")]
        responses[f"{R_BASE}/league/{lid}/winners_bracket"] = r_bracket()
    return FakeSleeper(responses)


def seed_eligible_leagues(db, *ids):
    ledger.upsert_leagues(
        [
            {
                "league_id": lid,
                "season": "2026",
                "settings_json": json.dumps({"sharpEligible": True}),
            }
            for lid in ids
        ],
        path=db,
    )


def seed_old_crawl(db, league_id, crawled_ms):
    conn = ledger.connect(db)
    try:
        conn.execute(
            "INSERT INTO manager_seasons (league_id, season, user_id, crawled_ms) "
            "VALUES (?, '2025', 'z', ?)",
            (league_id, crawled_ms),
        )
        conn.commit()
    finally:
        conn.close()


class TestRecordsCoverage:
    def test_a_budget_stop_with_queued_leagues_left_says_so_with_counts(self, db):
        seed_eligible_leagues(db, "L1", "L2", "L3")
        res = records.crawl_records(
            league_ids=["L1", "L2", "L3"],
            http_get=single_season_leagues("L1", "L2", "L3"),
            budget=7,  # a chain needs 4 in hand to start: two chains, then 1 left
            ledger_path=db,
            sleep_s=0,
        )
        cov = res.to_dict()["passCoverage"]

        assert res.to_dict()["stoppedReason"] == "budget_exhausted"
        assert cov["pass"] == "records"
        assert cov["stoppedReason"] == "budget_exhausted"
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (2, 2, 0)
        assert (cov["eligibleTotal"], cov["remainingUnvisited"]) == (3, 1)
        assert (cov["callsUsed"], cov["callBudget"]) == (6, 7)
        # The ledger's own view, after the run: one eligible league never crawled.
        assert cov["neverVisited"] == 1
        assert cov["ledgerEligibleLeagues"] == 3

    def test_a_drained_queue_is_completed_even_with_the_budget_spent(self, db):
        """Two chains cost six calls and need four in hand to start the second.

        With a budget of seven both chains run and one call is left, which is
        below the four a further chain needs: ``budget_exhausted`` (the
        pre-existing flag, behind the exit code) is True because the budget is
        short NOW, though nothing was left undone.
        """
        seed_eligible_leagues(db, "L1", "L2")
        res = records.crawl_records(
            league_ids=["L1", "L2"],
            http_get=single_season_leagues("L1", "L2"),
            budget=7,
            ledger_path=db,
            sleep_s=0,
        )
        assert res.budget_exhausted is True  # unchanged
        cov = res.pass_coverage
        assert cov["stoppedReason"] == "completed"
        assert cov["remainingUnvisited"] == 0
        assert (cov["attempted"], cov["succeeded"]) == (2, 2)
        assert cov["neverVisited"] == 0

    def test_a_chain_cut_off_mid_walk_is_a_budget_stop_even_with_no_chain_unreached(self, db):
        http = FakeSleeper(
            {
                f"{R_BASE}/league/L1": r_league("L1", "2026", previous="L0"),
                f"{R_BASE}/league/L1/rosters": [r_roster(1, "a"), r_roster(2, "b")],
                f"{R_BASE}/league/L1/winners_bracket": r_bracket(),
                f"{R_BASE}/league/L0": r_league("L0", "2025"),
                f"{R_BASE}/league/L0/rosters": [r_roster(1, "a"), r_roster(2, "b")],
                f"{R_BASE}/league/L0/winners_bracket": r_bracket(),
            }
        )
        res = records.crawl_records(
            league_ids=["L1"], http_get=http, budget=6, ledger_path=db, sleep_s=0
        )
        cov = res.pass_coverage
        assert cov["remainingUnvisited"] == 0
        assert cov["chainsCutByBudget"] == 1
        assert cov["stoppedReason"] == "budget_exhausted"
        assert cov["succeeded"] == 1  # the current season was recorded

    def test_failed_chains_are_counted(self, db):
        seed_eligible_leagues(db, "L1", "BROKEN")
        http = single_season_leagues("L1")  # BROKEN has no payloads at all
        res = records.crawl_records(
            league_ids=["L1", "BROKEN"], http_get=http, budget=100, ledger_path=db, sleep_s=0
        )
        cov = res.pass_coverage
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (2, 1, 1)
        assert cov["stoppedReason"] == "completed"
        assert cov["neverVisited"] == 1  # BROKEN has nothing on record

    def test_the_oldest_crawl_age_is_the_stalest_league_ever_crawled(self, db):
        seed_eligible_leagues(db, "L1", "OLD")
        seed_old_crawl(db, "OLD", NOW - 82 * DAY)
        res = records.crawl_records(
            league_ids=["L1"],
            http_get=single_season_leagues("L1"),
            budget=100,
            ledger_path=db,
            sleep_s=0,
        )
        cov = res.pass_coverage
        assert cov["oldestCrawlMs"] == NOW - 82 * DAY
        assert cov["oldestCrawlAgeDays"] == 82.0
        assert cov["neverVisited"] == 0

    def test_an_empty_queue_is_no_work_not_an_exhaustion(self, db):
        res = records.crawl_records(
            league_ids=[], http_get=FakeSleeper(), budget=100, ledger_path=db, sleep_s=0
        )
        assert res.pass_coverage["stoppedReason"] == "no_work"
        assert res.pass_coverage["eligibleTotal"] == 0
        assert res.pass_coverage["oldestCrawlMs"] is None
        assert res.pass_coverage["oldestCrawlAgeDays"] is None

    def test_the_queue_order_is_exactly_what_it_was(self, db):
        """Reporting must not change which league is visited first."""
        seed_eligible_leagues(db, "A", "B", "C")
        seed_old_crawl(db, "A", NOW - 5 * DAY)
        seed_old_crawl(db, "B", NOW - 50 * DAY)
        # never-crawled first, then oldest crawl first -- unchanged.
        assert rq.prioritized_league_ids(ledger_path=db) == ["C", "B", "A"]
        http = single_season_leagues("A", "B", "C")
        records.crawl_records(
            league_ids=rq.prioritized_league_ids(ledger_path=db),
            http_get=http,
            budget=100,
            ledger_path=db,
            sleep_s=0,
        )
        visited = [u.split("/league/")[1] for u in http.calls if u.endswith(tuple("ABC"))]
        assert visited == ["C", "B", "A"]


# ── rosters ──────────────────────────────────────────────────────────


def league_payload(league_id="L1", **overrides):
    base = {
        "league_id": league_id,
        "season": "2026",
        "status": "in_season",
        "total_rosters": 12,
        "previous_league_id": "L0",
        "settings": {"type": 2},
        "roster_positions": ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "K", "BN"],
        "scoring_settings": {"rec": 1.0},
    }
    base.update(overrides)
    return base


def roster_payload(roster_id="1", owner="u1", players=("4046", "6794")):
    return {
        "roster_id": roster_id,
        "owner_id": owner,
        "players": list(players),
        "settings": {"wins": 8, "losses": 2, "ties": 0},
    }


@pytest.fixture
def rledger(tmp_path):
    return tmp_path / "ledger.sqlite3"


def seed_membership(path, manager_key="sleeper:u1", league_key="sleeper:L1"):
    conn = platform_ledger.ensure_platform_schema(path)
    try:
        platform_ledger.upsert_manager(
            NormalizedManager.build("sleeper", manager_key.split(":", 1)[1]), conn=conn
        )
        platform_ledger.upsert_league(
            NormalizedLeague.build("sleeper", league_key.split(":", 1)[1]), conn=conn
        )
        platform_ledger.upsert_membership(
            NormalizedMembership(
                platform="sleeper",
                league_key=league_key,
                manager_key=manager_key,
                roster_id="1",
            ),
            conn=conn,
        )
        conn.commit()
    finally:
        conn.close()


def routed_http(*, broken=(), strangers=()):
    """Fake Sleeper keyed by league id: ``broken`` leagues never answer,
    ``strangers`` leagues answer with rosters nobody in the cohort owns."""

    def _get(url):
        if url.endswith("/players/nfl"):
            return {"4046": {"full_name": "Justin Jefferson", "position": "WR", "team": "MIN"}}
        league_id = url.split("/league/")[1].split("/")[0]
        if league_id in broken:
            return None
        if url.endswith("/rosters"):
            owner = "stranger" if league_id in strangers else "u1"
            return [roster_payload(owner=owner)]
        return league_payload(league_id)

    return _get


def collect(path, *, budget, http, now=NOW):
    return rc.collect_sleeper_rosters(
        manager_keys=["sleeper:u1"],
        http_get=http,
        budget=budget,
        ledger_path=path,
        sleep_fn=lambda _s: None,
        now_ms=now,
    )


class TestRostersCoverage:
    def test_a_budget_stop_reports_the_unvisited_remainder_and_staleness(self, rledger):
        for i in range(1, 7):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        res = collect(rledger, budget=4, http=routed_http())
        cov = res.to_dict()["passCoverage"]

        assert res.to_dict()["stoppedReason"] == "budget_exhausted"
        assert cov["pass"] == "rosters" and cov["lane"] == "sleeper"
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (2, 2, 0)
        assert (cov["eligibleTotal"], cov["remainingUnvisited"]) == (6, 4)
        assert cov["neverVisited"] == 4
        assert cov["oldestCrawlMs"] == NOW
        assert cov["oldestCrawlAgeDays"] == 0.0
        assert (cov["callsUsed"], cov["callBudget"]) == (4, 4)
        # The pre-existing figure is untouched.
        assert res.to_dict()["leaguesRemaining"] == 4

    def test_a_drained_queue_is_completed(self, rledger):
        for i in range(1, 4):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        res = collect(rledger, budget=100, http=routed_http())
        cov = res.pass_coverage
        assert cov["stoppedReason"] == "completed"
        assert cov["remainingUnvisited"] == 0
        assert cov["neverVisited"] == 0
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (3, 3, 0)

    def test_completed_even_when_the_last_league_spent_the_last_call(self, rledger):
        for i in range(1, 3):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        res = collect(rledger, budget=4, http=routed_http())
        assert res.budget_exhausted is True  # the old flag, which drives exit code 2
        assert res.pass_coverage["stoppedReason"] == "completed"
        assert res.pass_coverage["remainingUnvisited"] == 0

    def test_a_league_that_fails_to_fetch_is_a_failure_and_stays_unvisited(self, rledger):
        for i in range(1, 4):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        res = collect(rledger, budget=100, http=routed_http(broken={"L2"}))
        cov = res.pass_coverage
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (3, 2, 1)
        assert cov["stoppedReason"] == "completed"
        assert cov["neverVisited"] == 1
        # ``leaguesExamined`` only ever counted successes, so the old
        # "remaining" reading would have been 1 here.
        assert res.leagues_examined == 2

    def test_a_drained_queue_where_every_fetch_failed_is_completed_but_logged_at_warning(
        self, rledger, caplog
    ):
        for i in range(1, 4):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        with caplog.at_level(logging.INFO, logger=rc.log.name):
            res = collect(rledger, budget=100, http=routed_http(broken={"L1", "L2", "L3"}))
        cov = res.pass_coverage
        # The queue really did drain, so the reason is unchanged...
        assert cov["stoppedReason"] == "completed"
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (3, 0, 3)
        assert cov["neverVisited"] == 3
        # ...but a run that reached nothing is not an INFO line.
        lines = [r for r in caplog.records if r.getMessage().startswith("sharp.coverage ")]
        assert len(lines) == 1
        assert lines[0].levelno == logging.WARNING
        assert "stoppedReason=completed" in lines[0].getMessage()

    def test_a_league_with_no_cohort_roster_is_counted_because_it_stays_unvisited(self, rledger):
        seed_membership(rledger, "sleeper:u1", "sleeper:L1")
        seed_membership(rledger, "sleeper:u1", "sleeper:L2")
        res = collect(rledger, budget=100, http=routed_http(strangers={"L2"}))
        cov = res.pass_coverage
        assert cov["succeeded"] == 2
        assert cov["succeededWithoutCohortRoster"] == 1
        # It was fetched in full and still has no observation on record.
        assert cov["neverVisited"] == 1

    def test_an_empty_cohort_is_no_work_with_an_empty_queue_measured(self, rledger):
        res = rc.collect_sleeper_rosters(manager_keys=[], ledger_path=rledger)
        cov = res.pass_coverage
        assert cov["stoppedReason"] == "no_work"
        assert cov["eligibleTotal"] == 0
        assert cov["attempted"] == 0

    def test_a_budgeted_run_still_rotates_through_the_queue(self, rledger):
        """The ordering is untouched: each run reaches leagues the last one did not."""
        for i in range(1, 7):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        remaining = []
        for run in range(3):
            res = collect(rledger, budget=4, http=routed_http(), now=NOW + run * DAY)
            remaining.append(res.pass_coverage["remainingUnvisited"])
        assert remaining == [4, 4, 4]

    def test_summary_line_warns_once_on_a_budget_stop(self, rledger, caplog):
        for i in range(1, 7):
            seed_membership(rledger, "sleeper:u1", f"sleeper:L{i}")
        with caplog.at_level(logging.INFO, logger=rc.log.name):
            collect(rledger, budget=4, http=routed_http())
        lines = [r for r in caplog.records if r.getMessage().startswith("sharp.coverage ")]
        assert len(lines) == 1
        assert lines[0].levelno == logging.WARNING


class TestFfpcLaneCoverage:
    def seed(self, path, *, roster_assets, manager="ffpc:league:F1:team:7"):
        conn = platform_ledger.ensure_platform_schema(path)
        try:
            conn.execute(
                """
                INSERT INTO platform_managers
                  (manager_key, platform, source_manager_id, source_identity_type,
                   identity_scope, identity_confidence, first_seen_ms, last_seen_ms,
                   metadata_json)
                VALUES (?, 'ffpc', ?, 'league_scoped_team', 'league', 0.7, ?, ?, '{}')
                """,
                (manager, manager.split(":", 1)[1], NOW, NOW),
            )
            platform_ledger.upsert_league(
                NormalizedLeague.build("ffpc", "F1", season="2026", sharp_eligible=True), conn=conn
            )
            metadata = {} if roster_assets is None else {"rosterAssets": roster_assets}
            platform_ledger.upsert_membership(
                NormalizedMembership(
                    platform="ffpc",
                    league_key="ffpc:F1",
                    manager_key=manager,
                    source_team_id="7",
                    roster_id="7",
                    team_name="North Stars",
                    metadata=metadata,
                ),
                conn=conn,
            )
            conn.commit()
        finally:
            conn.close()

    def test_no_ffpc_manager_in_the_cohort_says_so_and_does_not_invent_a_total(self, rledger):
        res = rc.collect_ffpc_rosters(manager_keys=["sleeper:u1"], ledger_path=rledger)
        cov = res.to_dict()["passCoverage"]
        assert cov["stoppedReason"] == "no_cohort_managers_on_platform"
        assert cov["lane"] == "ffpc"
        assert cov["attempted"] == 0
        assert cov["eligibleTotal"] is None
        assert cov["remainingUnvisited"] is None

    def test_memberships_with_no_roster_table_explain_a_zero(self, rledger):
        self.seed(rledger, roster_assets=None)
        res = rc.collect_ffpc_rosters(
            manager_keys=["ffpc:league:F1:team:7"], ledger_path=rledger, now_ms=NOW
        )
        cov = res.pass_coverage
        assert res.rosters_recorded == 0
        assert res.status == rc.STATUS_OK  # the lane ran; the status is unchanged
        assert cov["stoppedReason"] == "upstream_data_missing"
        assert (cov["eligibleTotal"], cov["attempted"], cov["remainingUnvisited"]) == (1, 0, 1)
        assert cov["membershipsWithoutRosterTable"] == 1
        assert cov["cohortManagers"] == 1

    def test_a_lifted_roster_is_completed(self, rledger):
        self.seed(rledger, roster_assets=[{"canonicalAssetId": "4046"}])
        res = rc.collect_ffpc_rosters(
            manager_keys=["ffpc:league:F1:team:7"], ledger_path=rledger, now_ms=NOW
        )
        cov = res.pass_coverage
        assert cov["stoppedReason"] == "completed"
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (1, 1, 0)
        assert cov["callsUsed"] == 0

    def test_a_coverage_fault_does_not_fail_the_lane(self, rledger, monkeypatch, caplog):
        self.seed(rledger, roster_assets=[{"canonicalAssetId": "4046"}])
        monkeypatch.setattr(rc, "_attach_ffpc_coverage", _boom)
        with caplog.at_level(logging.INFO, logger=rc.log.name):
            res = rc.collect_ffpc_rosters(
                manager_keys=["ffpc:league:F1:team:7"], ledger_path=rledger, now_ms=NOW
            )
        # The roster was stored and the lane reports what it always did.
        assert res.status == rc.STATUS_OK
        assert res.rosters_recorded == 1
        assert res.to_dict()["stoppedReason"] is None
        assert res.to_dict()["passCoverage"] is None
        assert len(coverage_failure_warnings(caplog)) == 1
        assert not [r for r in caplog.records if r.getMessage().startswith("sharp.coverage ")]

    def test_a_skipped_lane_is_reported_as_skipped_not_empty(self, rledger, monkeypatch):
        monkeypatch.setattr(rc.sharp_cohort, "cohort_members", lambda **kw: ([], {"note": "empty"}))
        summary = rc.collect_all(ledger_path=rledger, run_id="r1", skip_sleeper=True)
        assert summary["sleeper"]["passCoverage"]["stoppedReason"] == "skipped_by_caller"
        assert summary["sleeper"]["passCoverage"]["eligibleTotal"] is None


# ── activity ─────────────────────────────────────────────────────────


def iso(ms):
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def activity_state(**overrides):
    state = {
        "generatedAt": iso(NOW),
        "members": {
            "1": {"lastCrawledAt": iso(NOW - 3 * DAY)},
            "2": {"lastCrawledAt": iso(NOW - 10 * DAY)},
            "3": {"lastCrawledAt": None},
        },
        "leagues": {
            "La": {"fetchState": {"lastFetchedAt": iso(NOW - 5 * DAY)}},
            "Lb": {"fetchState": {}},
            "Lgone": {"inactive": True, "fetchState": {"lastFetchedAt": iso(NOW - 99 * DAY)}},
        },
        "cursor": {"pendingMembers": ["3"], "pendingLeagues": ["La", "Lb"]},
        "lastRun": {"retryLeagueIds": ["Lb"]},
    }
    state.update(overrides)
    return state


def activity_coverage(**kwargs):
    base = {
        "eligible_managers": 5,
        "selected_managers": 3,
        "call_budget": 2500,
        "refresh": {"callsUsed": 2500, "budgetExhausted": True, "failedMemberIds": ["2"]},
        "state": activity_state(),
        "breaker_refused_calls": 0,
        "as_of_ms": NOW,
    }
    base.update(kwargs)
    return pass_coverage.build_activity_coverage(**base)


class TestActivityCoverage:
    def test_a_budget_stop_counts_managers_including_those_past_the_cap(self):
        cov = activity_coverage()
        assert cov["pass"] == "activity" and cov["unit"] == "managers"
        # 3 selected, 1 still pending => 2 attempted; one of them failed.
        assert (cov["attempted"], cov["succeeded"], cov["failed"]) == (2, 1, 1)
        # 5 qualified: the pending member plus the two the cap left out.
        assert cov["eligibleTotal"] == 5
        assert cov["remainingUnvisited"] == 3
        assert cov["neverVisited"] == 3
        assert cov["stoppedReason"] == "budget_exhausted"
        assert cov["managers"] == {
            "qualified": 5,
            "selected": 3,
            "notSelectedByCap": 2,
            "pendingMembers": 1,
        }
        assert cov["oldestCrawlMs"] == NOW - 10 * DAY
        assert cov["oldestCrawlAgeDays"] == 10.0
        assert (cov["callsUsed"], cov["callBudget"]) == (2500, 2500)

    def test_the_league_phase_is_reported_beside_the_manager_phase(self):
        phase = activity_coverage()["leaguePhase"]
        assert phase["trackedLeagues"] == 2  # the inactive league is not tracked
        assert phase["pendingLeagues"] == 2
        assert phase["retryLeagues"] == 1
        assert phase["neverFetchedLeagues"] == 1
        assert phase["oldestFetchMs"] == NOW - 5 * DAY
        assert phase["oldestFetchAgeDays"] == 5.0

    def test_a_cap_alone_is_reported_as_a_cap(self):
        cov = activity_coverage(
            refresh={"callsUsed": 40, "budgetExhausted": False, "failedMemberIds": []},
            state=activity_state(cursor=None),
        )
        assert cov["stoppedReason"] == "cap_reached"
        assert cov["managers"]["notSelectedByCap"] == 2
        assert cov["remainingUnvisited"] == 2

    def test_no_cap_and_no_budget_stop_is_completed(self):
        cov = activity_coverage(
            eligible_managers=3,
            refresh={"callsUsed": 40, "budgetExhausted": False, "failedMemberIds": []},
            state=activity_state(cursor=None),
        )
        assert cov["stoppedReason"] == "completed"
        assert cov["remainingUnvisited"] == 0

    def test_pending_retry_leagues_are_never_completed(self):
        """``budgetExhausted`` is False and ``completed`` is False: only leagues
        whose fetch failed this run are queued for retry.  The old reading was
        ``completed``; the crawler's own ``completed`` flag says otherwise."""
        cov = activity_coverage(
            eligible_managers=3,
            refresh={
                "callsUsed": 40,
                "budgetExhausted": False,
                "completed": False,
                "failedMemberIds": [],
            },
            state=activity_state(cursor={"pendingMembers": [], "pendingLeagues": ["La", "Lb"]}),
        )
        assert cov["stoppedReason"] == "work_pending"
        assert cov["leaguePhase"]["pendingLeagues"] == 2
        assert cov["managers"]["pendingMembers"] == 0

    def test_the_saved_cursor_alone_is_enough_to_see_pending_work(self):
        # The summary says the budget did not stop the run and does not say it
        # completed; the cursor the crawler persisted still lists pending leagues.
        cov = activity_coverage(
            eligible_managers=3,
            refresh={"callsUsed": 40, "budgetExhausted": False, "failedMemberIds": []},
            state=activity_state(cursor={"pendingMembers": [], "pendingLeagues": ["Lb"]}),
        )
        assert cov["stoppedReason"] == "work_pending"

    def test_the_crawlers_completed_flag_is_enough_when_the_snapshot_is_unreadable(self):
        pending = activity_coverage(
            eligible_managers=3,
            refresh={"callsUsed": 40, "budgetExhausted": False, "completed": False},
            state=None,
        )
        assert pending["stoppedReason"] == "work_pending"
        assert pending["remainingUnvisited"] is None  # still not guessed
        done = activity_coverage(
            eligible_managers=3,
            refresh={"callsUsed": 40, "budgetExhausted": False, "completed": True},
            state=None,
        )
        assert done["stoppedReason"] == "completed"

    def test_completed_needs_positive_evidence_that_nothing_is_pending(self):
        # Budget did not stop the run, and neither the summary nor a snapshot
        # says whether anything is queued: that is unknown, not completed.
        cov = activity_coverage(
            eligible_managers=3,
            refresh={"callsUsed": 40, "budgetExhausted": False},
            state=None,
        )
        assert cov["stoppedReason"] == "unknown"

    def test_a_budget_stop_is_still_a_budget_stop_when_the_crawler_says_not_completed(self):
        cov = activity_coverage(
            refresh={
                "callsUsed": 2500,
                "budgetExhausted": True,
                "completed": False,
                "failedMemberIds": ["2"],
            }
        )
        assert cov["stoppedReason"] == "budget_exhausted"

    def test_a_cap_still_wins_over_the_pending_label(self):
        cov = activity_coverage(
            refresh={"callsUsed": 40, "budgetExhausted": False, "completed": False},
            state=activity_state(cursor={"pendingMembers": [], "pendingLeagues": ["Lb"]}),
        )
        assert cov["stoppedReason"] == "cap_reached"

    def test_refused_breaker_calls_win_over_every_other_reason(self):
        cov = activity_coverage(breaker_refused_calls=7)
        assert cov["stoppedReason"] == "sleeper_breaker_open"
        assert cov["breakerRefusedCalls"] == 7

    def test_an_unreadable_snapshot_leaves_the_dependent_figures_null(self):
        cov = activity_coverage(state=None)
        for key in (
            "attempted",
            "succeeded",
            "remainingUnvisited",
            "neverVisited",
            "oldestCrawlMs",
        ):
            assert cov[key] is None, key
        assert cov["leaguePhase"]["trackedLeagues"] is None
        # What the refresh summary itself said is still reported.
        assert cov["failed"] == 1
        assert cov["stoppedReason"] == "budget_exhausted"

    def test_a_snapshot_that_was_never_saved_is_not_read_as_no_pending_work(self):
        cov = activity_coverage(state={"cursor": None, "generatedAt": None, "members": {}})
        assert cov["attempted"] is None
        assert cov["remainingUnvisited"] is None

    def test_a_summary_that_does_not_say_whether_the_budget_stopped_it_is_unknown(self):
        cov = activity_coverage(refresh={"callsUsed": 19})
        assert cov["stoppedReason"] == "unknown"

    def test_an_unknown_stop_is_not_proven_healthy_so_it_logs_at_warning(self, caplog):
        """``unknown`` means nothing established the pass finished.  It used to
        log at INFO beside ``completed``; it is now in the WARNING set with the
        other not-proven-healthy states."""
        assert pass_coverage.STOPPED_UNKNOWN == "unknown"
        assert pass_coverage.STOPPED_UNKNOWN in pass_coverage.STOPPED_SHORT
        assert pass_coverage.STOPPED_COMPLETED not in pass_coverage.STOPPED_SHORT

        # A real activity run whose summary says nothing about how it ended.
        cov = activity_coverage(refresh={"callsUsed": 19})
        assert cov["stoppedReason"] == pass_coverage.STOPPED_UNKNOWN
        logger = logging.getLogger("test.pass_coverage.unknown")
        with caplog.at_level(logging.DEBUG, logger="test.pass_coverage.unknown"):
            used = pass_coverage.log_pass_summary(logger, cov)
        assert used == logging.WARNING
        lines = [r for r in caplog.records if r.name == "test.pass_coverage.unknown"]
        assert len(lines) == 1 and lines[0].levelno == logging.WARNING
        assert "stoppedReason=unknown" in lines[0].getMessage()
        # The level is logging only: the reason is not rewritten.
        assert cov["stoppedReason"] == "unknown"

    def test_an_empty_cohort_is_a_measured_zero(self):
        cov = pass_coverage.build_activity_coverage(
            eligible_managers=0,
            selected_managers=0,
            call_budget=100,
            refresh=None,
            state=None,
            breaker_refused_calls=None,
            as_of_ms=NOW,
        )
        assert cov["stoppedReason"] == "no_work"
        assert (cov["attempted"], cov["eligibleTotal"], cov["remainingUnvisited"]) == (0, 0, 0)


class TestReportingNeverFailsACrawl:
    """A fault in the coverage code costs the coverage fields, never the crawl."""

    def test_discovery_finishes_unchanged_when_the_coverage_helper_raises(
        self, db, tmp_path, monkeypatch, caplog
    ):
        seeds = d_seeds(seed_leagues=["L0"], callBudgetPerRun=3)
        baseline = discovery.discover(http_get=wide_graph(), seeds=seeds, ledger_path=db)
        monkeypatch.setattr(discovery, "_attach_pass_coverage", _boom)
        caplog.clear()  # only the faulted run's log lines
        with caplog.at_level(logging.INFO, logger=discovery.log.name):
            res = discovery.discover(
                http_get=wide_graph(), seeds=seeds, ledger_path=tmp_path / "second.sqlite3"
            )
        assert baseline.pass_coverage is not None
        assert res.stopped_reason == ""
        assert res.pass_coverage is None
        assert res.to_dict()["stoppedReason"] is None
        assert res.to_dict()["passCoverage"] is None
        # Everything the walk reports besides the coverage fields is identical.
        assert without_coverage(res.to_dict()) == without_coverage(baseline.to_dict())
        assert res.budget_exhausted is True
        warnings = coverage_failure_warnings(caplog)
        assert len(warnings) == 1 and warnings[0].levelno == logging.WARNING
        assert not [r for r in caplog.records if r.getMessage().startswith("sharp.coverage ")]

    def test_a_non_numeric_oldest_observation_reads_as_unknown_not_a_crash(self, caplog):
        from types import SimpleNamespace

        class Conn:
            def execute(self, _sql):
                return SimpleNamespace(fetchone=lambda: {"oldest": "not-a-number"})

        with caplog.at_level(logging.WARNING, logger=discovery.log.name):
            assert discovery._oldest_league_seen_ms(Conn()) is None
        assert [r for r in caplog.records if r.levelno == logging.WARNING]

    def test_records_finishes_unchanged_when_the_coverage_helper_raises(
        self, db, tmp_path, monkeypatch, caplog
    ):
        second = tmp_path / "second.sqlite3"
        for path in (db, second):
            seed_eligible_leagues(path, "L1", "L2", "L3")
        kwargs = {"league_ids": ["L1", "L2", "L3"], "budget": 7, "sleep_s": 0}
        baseline = records.crawl_records(
            http_get=single_season_leagues("L1", "L2", "L3"), ledger_path=db, **kwargs
        )
        monkeypatch.setattr(records, "_attach_pass_coverage", _boom)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=records.log.name):
            res = records.crawl_records(
                http_get=single_season_leagues("L1", "L2", "L3"), ledger_path=second, **kwargs
            )
        assert baseline.pass_coverage is not None
        assert res.pass_coverage is None and res.stopped_reason == ""
        assert without_coverage(res.to_dict()) == without_coverage(baseline.to_dict())
        assert res.budget_exhausted is True
        assert len(coverage_failure_warnings(caplog)) == 1

    def test_sleeper_rosters_finish_unchanged_when_the_coverage_helper_raises(
        self, rledger, tmp_path, monkeypatch, caplog
    ):
        second = tmp_path / "second.sqlite3"
        for path in (rledger, second):
            for i in range(1, 4):
                seed_membership(path, "sleeper:u1", f"sleeper:L{i}")
        baseline = collect(rledger, budget=100, http=routed_http())
        monkeypatch.setattr(rc, "_attach_sleeper_coverage", _boom)
        caplog.clear()
        with caplog.at_level(logging.INFO, logger=rc.log.name):
            res = collect(second, budget=100, http=routed_http())
        assert baseline.pass_coverage is not None
        assert res.pass_coverage is None and res.stopped_reason == ""
        assert res.rosters_recorded == baseline.rosters_recorded == 3
        assert without_coverage(res.to_dict()) == without_coverage(baseline.to_dict())
        assert len(coverage_failure_warnings(caplog)) == 1

    def test_an_empty_cohort_survives_a_coverage_fault(self, rledger, monkeypatch, caplog):
        monkeypatch.setattr(rc, "_attach_sleeper_coverage", _boom)
        with caplog.at_level(logging.INFO, logger=rc.log.name):
            res = rc.collect_sleeper_rosters(manager_keys=[], ledger_path=rledger)
        assert res.leagues_queued == 0
        assert res.pass_coverage is None
        assert len(coverage_failure_warnings(caplog)) == 1

    def test_a_failing_summary_logger_never_raises(self):
        class BrokenLogger:
            def log(self, *_a, **_k):
                raise RuntimeError("handler exploded")

            def warning(self, *_a, **_k):
                pass

        assert pass_coverage.log_pass_summary(BrokenLogger(), {"stoppedReason": "completed"})


def _load_script(name):
    path = REPO / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"cov_test_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestScriptsKeepTheirExitCodes:
    """The scripts report more; they do not exit differently."""

    def test_activity_script_reports_coverage_and_still_exits_zero(self, monkeypatch, caplog):
        activity = _load_script("crawl_sharp_activity")
        monkeypatch.setattr(
            activity,
            "qualified_sleeper_ids",
            lambda: (["1", "2", "3"], {"qualifiedSleeperManagers": 3}),
        )
        monkeypatch.setattr(activity.platform_ledger, "platform_coverage", lambda: {"sleeper": {}})
        monkeypatch.setattr(
            activity.intel_service,
            "refresh_intel",
            lambda **kw: {"callsUsed": 9, "budgetExhausted": True, "failedMemberIds": []},
        )
        monkeypatch.setattr(activity.intel_store, "load_state", lambda key: activity_state())
        monkeypatch.setattr(sys, "argv", ["crawl_sharp_activity.py", "--max-managers", "2"])
        with caplog.at_level(logging.INFO, logger="crawl_sharp_activity"):
            result = activity.run_activity_crawl(max_managers=2)
            code = activity.main([])
        assert code == 0
        assert result["status"] == "success"
        assert result["stoppedReason"] == "budget_exhausted"
        assert result["passCoverage"]["managers"]["notSelectedByCap"] == 1
        lines = [r for r in caplog.records if r.getMessage().startswith("sharp.coverage ")]
        assert lines and all(r.levelno == logging.WARNING for r in lines)

    def test_activity_script_cohort_building_carries_a_measured_zero(self, monkeypatch):
        activity = _load_script("crawl_sharp_activity")
        monkeypatch.setattr(activity, "qualified_sleeper_ids", lambda: ([], {}))
        monkeypatch.setattr(activity.platform_ledger, "platform_coverage", lambda: {"sleeper": {}})
        result = activity.run_activity_crawl()
        assert result["status"] == "cohort_building"
        assert result["passCoverage"]["stoppedReason"] == "no_work"
        assert result["passCoverage"]["eligibleTotal"] == 0

    @pytest.mark.parametrize(("flag", "code"), [(True, 2), (False, 0)])
    def test_rosters_script_exit_code_follows_the_old_flag_not_the_new_reason(
        self, monkeypatch, capsys, caplog, flag, code
    ):
        script = _load_script("crawl_sharp_rosters")
        summary = {
            "sleeper": {
                "budgetExhausted": flag,
                "passCoverage": {"stoppedReason": "completed", "remainingUnvisited": 0},
            },
            "ffpc": {},
        }
        monkeypatch.setattr(script.roster_collect, "collect_all", lambda **kw: summary)
        monkeypatch.setattr(script.roster_collect, "record_collection_run", lambda *a, **k: None)
        monkeypatch.setattr(sys, "argv", ["crawl_sharp_rosters.py"])
        with caplog.at_level(logging.WARNING, logger="crawl_sharp_rosters"):
            assert script.main() == code
        printed = json.loads(capsys.readouterr().out)
        assert printed["sleeper"]["passCoverage"]["stoppedReason"] == "completed"

    @pytest.mark.parametrize(
        ("coverage", "says_rerun"),
        [
            # The last league was collected with the last call: nothing to continue.
            ({"stoppedReason": "completed", "remainingUnvisited": 0}, False),
            ({"stoppedReason": "budget_exhausted", "remainingUnvisited": 40}, True),
            # No coverage block: the script cannot tell, so it keeps the old advice.
            (None, True),
        ],
    )
    def test_rosters_script_only_says_rerun_when_the_coverage_says_work_is_left(
        self, monkeypatch, capsys, caplog, coverage, says_rerun
    ):
        script = _load_script("crawl_sharp_rosters")
        summary = {"sleeper": {"budgetExhausted": True, "passCoverage": coverage}, "ffpc": {}}
        monkeypatch.setattr(script.roster_collect, "collect_all", lambda **kw: summary)
        monkeypatch.setattr(script.roster_collect, "record_collection_run", lambda *a, **k: None)
        monkeypatch.setattr(sys, "argv", ["crawl_sharp_rosters.py"])
        with caplog.at_level(logging.INFO, logger="crawl_sharp_rosters"):
            # Same exit code whichever message is chosen.
            assert script.main() == 2
        capsys.readouterr()
        records_ = [r for r in caplog.records if r.name == "crawl_sharp_rosters"]
        rerun = [r for r in records_ if "re-run to continue" in r.getMessage()]
        assert bool(rerun) is says_rerun
        if says_rerun:
            assert all(r.levelno == logging.WARNING for r in rerun)
        else:
            drained = [r for r in records_ if "queue drained" in r.getMessage()]
            assert len(drained) == 1 and drained[0].levelno == logging.INFO

    def _patch_activity_run(self, activity, monkeypatch):
        monkeypatch.setattr(
            activity,
            "qualified_sleeper_ids",
            lambda: (["1", "2", "3"], {"qualifiedSleeperManagers": 3}),
        )
        monkeypatch.setattr(activity.platform_ledger, "platform_coverage", lambda: {"sleeper": {}})
        monkeypatch.setattr(
            activity.intel_service,
            "refresh_intel",
            lambda **kw: {"callsUsed": 9, "budgetExhausted": True, "failedMemberIds": []},
        )
        monkeypatch.setattr(activity.intel_store, "load_state", lambda key: activity_state())
        monkeypatch.setattr(sys, "argv", ["crawl_sharp_activity.py", "--max-managers", "2"])

    def test_activity_script_still_succeeds_when_the_coverage_builder_raises(
        self, monkeypatch, caplog, capsys
    ):
        activity = _load_script("crawl_sharp_activity")
        self._patch_activity_run(activity, monkeypatch)
        monkeypatch.setattr(pass_coverage, "build_activity_coverage", _boom)
        with caplog.at_level(logging.INFO, logger="crawl_sharp_activity"):
            result = activity.run_activity_crawl(max_managers=2)
            code = activity.main([])
        capsys.readouterr()
        assert code == 0
        assert result["status"] == "success"
        # The refresh summary is still carried; only the coverage fields are null.
        assert result["refresh"]["callsUsed"] == 9
        assert result["stoppedReason"] is None
        assert result["passCoverage"] is None
        assert coverage_failure_warnings(caplog)

    def test_activity_script_empty_cohort_survives_a_coverage_fault(self, monkeypatch, caplog):
        activity = _load_script("crawl_sharp_activity")
        monkeypatch.setattr(activity, "qualified_sleeper_ids", lambda: ([], {}))
        monkeypatch.setattr(activity.platform_ledger, "platform_coverage", lambda: {"sleeper": {}})
        monkeypatch.setattr(pass_coverage, "build_activity_coverage", _boom)
        with caplog.at_level(logging.INFO, logger="crawl_sharp_activity"):
            result = activity.run_activity_crawl()
        assert result["status"] == "cohort_building"
        assert result["stoppedReason"] is None and result["passCoverage"] is None
        assert coverage_failure_warnings(caplog)

    @pytest.mark.parametrize("fault", [False, True])
    def test_discovery_script_exit_code_is_the_same_when_coverage_raises(
        self, monkeypatch, capsys, db, fault
    ):
        script = _load_script("discover_sharp_graph")
        real_discover = discovery.discover
        http = wide_graph()
        seeds = d_seeds(seed_leagues=["L0"], callBudgetPerRun=3)
        monkeypatch.setattr(
            script.discovery,
            "discover",
            lambda **kw: real_discover(http_get=http, seeds=seeds, ledger_path=db, **kw),
        )
        monkeypatch.setattr(script.discovery, "graph_stats", lambda: {})
        if fault:
            monkeypatch.setattr(discovery, "_attach_pass_coverage", _boom)
        monkeypatch.setattr(sys, "argv", ["discover_sharp_graph.py"])
        # The budget ended the walk with work queued: exit 2, as it always did.
        assert script.main() == 2
        printed = json.loads(capsys.readouterr().out)
        assert printed["budgetExhausted"] is True
        assert (printed["passCoverage"] is None) is fault
        assert (printed["stoppedReason"] is None) is fault

    @pytest.mark.parametrize(("flag", "code"), [(True, 2), (False, 0)])
    def test_records_script_exit_code_and_payload(self, monkeypatch, capsys, flag, code):
        script = _load_script("crawl_sharp_records")
        result = records.RecordsResult(budget_exhausted=flag, chains_queued=3, chains_attempted=2)
        result.pass_coverage = {"stoppedReason": "budget_exhausted", "remainingUnvisited": 1}
        monkeypatch.setattr(script.record_queue, "prioritized_league_ids", lambda: ["a", "b", "c"])
        monkeypatch.setattr(script.records, "crawl_records", lambda **kw: result)
        monkeypatch.setattr(script.records, "records_coverage", lambda: {})
        monkeypatch.setattr(script.record_queue, "queue_stats", lambda: {})
        monkeypatch.setattr(script.discovery, "sharp_eligible_league_ids", lambda: [])
        monkeypatch.setattr(sys, "argv", ["crawl_sharp_records.py"])
        assert script.main() == code
        printed = json.loads(capsys.readouterr().out)
        assert printed["passCoverage"]["remainingUnvisited"] == 1
        # The pre-existing records-coverage key is not displaced by the new one.
        assert "coverage" in printed

    @pytest.mark.parametrize(("flag", "code"), [(True, 2), (False, 0)])
    def test_discovery_script_exit_code_and_payload(self, monkeypatch, capsys, flag, code):
        script = _load_script("discover_sharp_graph")
        result = discovery.DiscoveryResult(budget_exhausted=flag)
        result.pass_coverage = {"stoppedReason": "completed"}
        monkeypatch.setattr(script.discovery, "discover", lambda **kw: result)
        monkeypatch.setattr(script.discovery, "graph_stats", lambda: {})
        monkeypatch.setattr(sys, "argv", ["discover_sharp_graph.py"])
        assert script.main() == code
        assert json.loads(capsys.readouterr().out)["passCoverage"]["stoppedReason"] == "completed"
