"""Season-records crawl: chain walking, completed-only scoring, and the
derivation of ManagerRecord from stored seasons."""

from __future__ import annotations

import pytest

from src.intel import ledger
from src.sharp import records

BASE = records.SLEEPER_BASE


class FakeSleeper:
    def __init__(self, responses=None):
        self.responses = dict(responses or {})
        self.calls: list[str] = []

    def __call__(self, url):
        self.calls.append(url)
        return self.responses.get(url)


def league(lid, season, *, previous=None, status="complete", type_=2, teams=2):
    lg = {
        "league_id": lid,
        "season": season,
        "status": status,
        "total_rosters": teams,
        "settings": {"type": type_, "best_ball": 0},
    }
    if previous is not None:
        lg["previous_league_id"] = previous
    return lg


def roster(rid, owner, wins=8, losses=6, fpts=1500, dec=50):
    return {
        "roster_id": rid,
        "owner_id": owner,
        "settings": {
            "wins": wins,
            "losses": losses,
            "ties": 0,
            "fpts": fpts,
            "fpts_decimal": dec,
            "fpts_against": 1400,
            "fpts_against_decimal": 0,
        },
    }


def bracket(champion_rid, runner_up_rid):
    return [
        {
            "m": 1,
            "r": 1,
            "t1": champion_rid,
            "t2": runner_up_rid,
            "w": champion_rid,
            "l": runner_up_rid,
            "p": 1,
        }
    ]


@pytest.fixture()
def db(tmp_path, monkeypatch):
    from src.intel import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path / "intel")
    ledger.reset_setup_cache()
    yield tmp_path / "intel" / ledger.LEDGER_FILENAME
    ledger.reset_setup_cache()


class TestChainWalk:
    def test_walks_previous_league_ids(self, db):
        http = FakeSleeper(
            {
                f"{BASE}/league/L2026": league("L2026", "2026", previous="L2025"),
                f"{BASE}/league/L2026/rosters": [roster(1, "a"), roster(2, "b")],
                f"{BASE}/league/L2026/winners_bracket": bracket(1, 2),
                f"{BASE}/league/L2025": league("L2025", "2025", previous="0"),
                f"{BASE}/league/L2025/rosters": [roster(1, "a"), roster(2, "b")],
                f"{BASE}/league/L2025/winners_bracket": bracket(2, 1),
            }
        )
        res = records.crawl_records(league_ids=["L2026"], http_get=http, ledger_path=db, sleep_s=0)
        assert res.leagues_examined == 2
        assert res.completed_seasons == 2

    def test_string_zero_terminates_the_chain(self, db):
        """Sleeper ends a chain with the STRING "0", not null — a
        falsy-only check walks off the end into a bogus fetch."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="0"),
                f"{BASE}/league/L1/rosters": [roster(1, "a")],
                f"{BASE}/league/L1/winners_bracket": [],
            }
        )
        records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        assert not any(url.endswith("/league/0") for url in http.calls)

    def test_loop_guard_stops_a_self_referential_chain(self, db):
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="L1"),
                f"{BASE}/league/L1/rosters": [roster(1, "a")],
                f"{BASE}/league/L1/winners_bracket": [],
            }
        )
        res = records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        assert res.leagues_examined == 1

    def test_budget_stops_the_walk_cleanly(self, db):
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="L0"),
                f"{BASE}/league/L1/rosters": [roster(1, "a")],
                f"{BASE}/league/L1/winners_bracket": [],
            }
        )
        res = records.crawl_records(
            league_ids=["L1"], http_get=http, ledger_path=db, budget=2, sleep_s=0
        )
        assert res.calls_used <= 2
        assert res.budget_exhausted is True

    def test_fetch_failure_is_recorded_not_raised(self, db):
        http = FakeSleeper({f"{BASE}/league/L1": None})
        res = records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        assert any("league_fetch_failed" in e for e in res.errors)


class TestCompletedOnly:
    def test_in_season_league_skips_the_bracket_fetch(self, db):
        """No bracket exists mid-season; fetching one wastes a call."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="0", status="in_season"),
                f"{BASE}/league/L1/rosters": [roster(1, "a")],
            }
        )
        res = records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        assert res.completed_seasons == 0
        assert not any("winners_bracket" in u for u in http.calls)

    def test_in_season_rows_are_stored_but_not_scoreable(self, db):
        """A 3-0 start must never read as a perfect completed season."""
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="0", status="in_season"),
                f"{BASE}/league/L1/rosters": [roster(1, "a", wins=3, losses=0)],
            }
        )
        records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        assert records.records_coverage(ledger_path=db)["seasonRows"] == 1
        assert records.build_manager_records(ledger_path=db) == []


class TestIdempotency:
    def test_recrawl_upserts_rather_than_duplicating(self, db):
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="0"),
                f"{BASE}/league/L1/rosters": [roster(1, "a"), roster(2, "b")],
                f"{BASE}/league/L1/winners_bracket": bracket(1, 2),
            }
        )
        for _ in range(3):
            records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        assert records.records_coverage(ledger_path=db)["seasonRows"] == 2


class TestDerivation:
    def _crawl(self, db, *, rosters, champ=1, runner=2, season="2025"):
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", season, previous="0", teams=len(rosters)),
                f"{BASE}/league/L1/rosters": rosters,
                f"{BASE}/league/L1/winners_bracket": bracket(champ, runner),
            }
        )
        records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)

    def test_champion_is_credited_from_the_p1_match(self, db):
        self._crawl(db, rosters=[roster(1, "winner"), roster(2, "loser")])
        conn = ledger.connect(db)
        try:
            rows = {r["user_id"]: r for r in conn.execute("SELECT * FROM manager_seasons")}
        finally:
            conn.close()
        assert rows["winner"]["is_champion"] == 1
        assert rows["loser"]["is_champion"] == 0
        assert rows["loser"]["is_runner_up"] == 1

    def test_playoff_participants_come_from_the_bracket(self, db):
        self._crawl(db, rosters=[roster(1, "in1"), roster(2, "in2"), roster(3, "out")])
        conn = ledger.connect(db)
        try:
            rows = {r["user_id"]: r for r in conn.execute("SELECT * FROM manager_seasons")}
        finally:
            conn.close()
        assert rows["in1"]["made_playoffs"] == 1
        assert rows["in2"]["made_playoffs"] == 1
        assert rows["out"]["made_playoffs"] == 0

    def test_finish_rank_orders_by_wins_then_points(self, db):
        self._crawl(
            db,
            rosters=[
                roster(1, "second", wins=9, fpts=1000),
                roster(2, "first", wins=9, fpts=2000),
                roster(3, "third", wins=2, fpts=3000),
            ],
        )
        conn = ledger.connect(db)
        try:
            rows = {
                r["user_id"]: r["finish_rank"]
                for r in conn.execute("SELECT * FROM manager_seasons")
            }
        finally:
            conn.close()
        assert rows["first"] == 1
        assert rows["second"] == 2
        assert rows["third"] == 3

    def test_orphaned_roster_is_skipped(self, db):
        """No owner_id means no manager to credit."""
        orphan = roster(3, "x")
        orphan["owner_id"] = None
        self._crawl(db, rosters=[roster(1, "a"), roster(2, "b"), orphan])
        assert records.records_coverage(ledger_path=db)["managersWithRecords"] == 2

    def test_manager_record_aggregates_across_seasons(self, db):
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2026", previous="L0"),
                f"{BASE}/league/L1/rosters": [roster(1, "a", wins=10, losses=4), roster(2, "b")],
                f"{BASE}/league/L1/winners_bracket": bracket(1, 2),
                f"{BASE}/league/L0": league("L0", "2025", previous="0"),
                f"{BASE}/league/L0/rosters": [roster(1, "a", wins=9, losses=5), roster(2, "b")],
                f"{BASE}/league/L0/winners_bracket": bracket(1, 2),
            }
        )
        records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        recs = {r.user_id: r for r in records.build_manager_records(ledger_path=db)}
        a = recs["a"]
        assert a.completed_seasons == 2
        assert a.wins == 19 and a.losses == 9
        assert a.championships == 2
        assert a.playoff_appearances == 2
        assert a.completed_games == 28

    def test_only_sharp_eligible_leagues_contribute(self, db):
        """A redraft league's results must not certify anyone."""
        http = FakeSleeper(
            {
                f"{BASE}/league/R1": league("R1", "2025", previous="0", type_=0),
                f"{BASE}/league/R1/rosters": [roster(1, "a"), roster(2, "b")],
                f"{BASE}/league/R1/winners_bracket": bracket(1, 2),
            }
        )
        records.crawl_records(league_ids=["R1"], http_get=http, ledger_path=db, sleep_s=0)
        assert records.records_coverage(ledger_path=db)["seasonRows"] == 2
        assert records.build_manager_records(ledger_path=db) == []


class TestFinishPercentiles:
    def test_first_place_is_one_and_last_is_zero(self, db):
        http = FakeSleeper(
            {
                f"{BASE}/league/L1": league("L1", "2025", previous="0", teams=3),
                f"{BASE}/league/L1/rosters": [
                    roster(1, "top", wins=12),
                    roster(2, "mid", wins=7),
                    roster(3, "bot", wins=1),
                ],
                f"{BASE}/league/L1/winners_bracket": bracket(1, 2),
            }
        )
        records.crawl_records(league_ids=["L1"], http_get=http, ledger_path=db, sleep_s=0)
        recs = {r.user_id: r for r in records.build_manager_records(ledger_path=db)}
        assert recs["top"].finish_percentiles == [1.0]
        assert recs["bot"].finish_percentiles == [0.0]
        assert recs["mid"].finish_percentiles == [0.5]


class TestWriterLockWindows:
    def test_each_season_commits_before_the_next_network_call(self, db):
        """V1-59 residual: the crawl must never hold the SQLite writer
        lock across network I/O.

        A single end-of-crawl commit kept one write transaction open for
        the whole budget — on production, an hour-long writer lock
        overlapping the 05:20 FFPC ingestion window.  The observable
        property: by the time the crawl asks Sleeper about the SECOND
        chain hop, the FIRST hop's rows are already visible to an
        independent connection.  Under the retired single-commit shape
        this count is 0 until the crawl returns.
        """
        import sqlite3

        observed: list[int] = []
        responses = {
            f"{BASE}/league/L2026": league("L2026", "2026", previous="L2025"),
            f"{BASE}/league/L2026/rosters": [roster(1, "a"), roster(2, "b")],
            f"{BASE}/league/L2026/winners_bracket": bracket(1, 2),
            f"{BASE}/league/L2025": league("L2025", "2025", previous="0"),
            f"{BASE}/league/L2025/rosters": [roster(1, "a"), roster(2, "b")],
            f"{BASE}/league/L2025/winners_bracket": bracket(2, 1),
        }

        class SpyingSleeper(FakeSleeper):
            def __call__(self, url):
                if url == f"{BASE}/league/L2025":
                    probe = sqlite3.connect(db)
                    try:
                        n = probe.execute(
                            "SELECT COUNT(*) FROM manager_seasons WHERE league_id='L2026'"
                        ).fetchone()[0]
                    finally:
                        probe.close()
                    observed.append(n)
                return super().__call__(url)

        http = SpyingSleeper(responses)
        records.crawl_records(league_ids=["L2026"], http_get=http, ledger_path=db, sleep_s=0)

        assert observed, "the crawl never reached the second chain hop — vacuous"
        assert observed[0] > 0, (
            "the first season's rows were invisible to an independent reader "
            "while the crawl performed its next network call — the writer "
            "transaction is still spanning network I/O (V1-59)"
        )
