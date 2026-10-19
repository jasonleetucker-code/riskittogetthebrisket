"""League maturity: verified COMPLETED dynasty seasons over the real chain.

Owner directive 2026-10-19 (V2): the initial Chase Upside Trade Market model
uses leagues with at least THREE verified completed seasons, following the
real ``previous_league_id`` chain; two-season leagues are a separate research
cohort; nothing is relaxed silently.  Synthetic league ids only.
"""

from __future__ import annotations

import sqlite3

import pytest

from src.intel import ledger
from src.intel import league_filter as lf
from src.public_league import sleeper_client as sc


def hop(lid, season, prev=None, *, type_=2, status="complete", best_ball=False):
    return lf.ChainHop(
        league_id=lid,
        previous_league_id=prev,
        season=str(season) if season is not None else None,
        league_type=type_,
        status=status,
        best_ball=best_ball,
    )


def index(*hops):
    return {h.league_id: h for h in hops}


def pit(lid, chain):
    return lf.resolve_league_maturity(lid, chain, reading=lf.READING_POINT_IN_TIME)


def lvl(lid, chain):
    return lf.resolve_league_maturity(lid, chain, reading=lf.READING_LEAGUE_LEVEL)


# A four-season dynasty lineage: 2023 startup .. 2026 in progress.
FOUR = index(
    hop("SYN-26", 2026, "SYN-25", status="in_season"),
    hop("SYN-25", 2025, "SYN-24"),
    hop("SYN-24", 2024, "SYN-23"),
    hop("SYN-23", 2023, None),
)


class TestTerminator:
    def test_zero_string_is_not_a_predecessor(self):
        assert lf.predecessor_league_id({"previous_league_id": "0"}) is None
        assert lf.predecessor_league_id({"previous_league_id": ""}) is None
        assert lf.predecessor_league_id({"previous_league_id": None}) is None
        assert lf.predecessor_league_id({}) is None
        assert lf.predecessor_league_id({"previous_league_id": " SYN-P "}) == "SYN-P"
        assert lf.predecessor_league_id({"previous_league": "SYN-P"}) == "SYN-P"

    def test_league_age_floor_no_longer_counts_the_terminator(self):
        # The defect: "0" is truthy, so every first-season league read age 2.
        assert lf.league_age_seasons({"previous_league_id": "0"}) == 1
        assert lf.league_age_seasons({"previous_league_id": "SYN-P"}) == 2
        assert lf.league_age_seasons({}) == 1
        assert lf.league_age_seasons(None) == 0

    def test_terminator_vocabulary_matches_the_walker(self):
        assert lf.CHAIN_TERMINATORS == sc._CHAIN_TERMINATORS


class TestPointInTime:
    def test_trade_season_never_counts(self):
        m = pit("SYN-26", FOUR)
        assert (m.completed_seasons, m.state, m.stop_reason) == (3, lf.MATURITY_EXACT, "terminator")
        assert m.cohort == lf.COHORT_A
        # A trade in 2025 sees only 2024 and 2023 before it.
        m25 = pit("SYN-25", FOUR)
        assert m25.completed_seasons == 2 and m25.cohort == lf.COHORT_B_EXACT

    def test_startup_season_counts_once_complete(self):
        m = pit("SYN-24", FOUR)
        assert m.completed_seasons == 1 and m.cohort == lf.COHORT_BELOW_TWO

    def test_first_season_has_zero_and_is_exact(self):
        m = pit("SYN-23", FOUR)
        assert m.completed_seasons == 0 and m.state == lf.MATURITY_EXACT

    def test_unwalked_link_is_a_lower_bound_never_a_pass(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"), hop("SYN-25", 2025, "SYN-X")
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 1 and m.state == lf.MATURITY_LOWER_BOUND
        assert m.stop_reason == lf.STOP_NOT_WALKED
        assert m.meets(3) is None and m.cohort == lf.COHORT_UNKNOWN_BELOW_TWO

    def test_two_lower_bound_is_research_not_primary(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"),
            hop("SYN-25", 2025, "SYN-24"),
            hop("SYN-24", 2024, "SYN-X"),
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 2 and m.cohort == lf.COHORT_B_UNRESOLVED
        assert m.meets(3) is None and m.meets(2) is True

    def test_redraft_predecessor_ends_the_chain_exactly(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"),
            hop("SYN-25", 2025, "SYN-24"),
            hop("SYN-24", 2024, "SYN-23", type_=0),
            hop("SYN-23", 2023, None),
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 1 and m.state == lf.MATURITY_EXACT
        assert m.stop_reason == lf.STOP_NON_DYNASTY and m.cohort == lf.COHORT_BELOW_TWO

    def test_untyped_predecessor_fails_closed(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"), hop("SYN-25", 2025, None, type_=None)
        )
        m = pit("SYN-26", chain)
        assert m.stop_reason == lf.STOP_TYPE_UNKNOWN and m.state == lf.MATURITY_LOWER_BOUND

    def test_incomplete_predecessor_does_not_count_and_is_unverified(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"),
            hop("SYN-25", 2025, "SYN-24", status="in_season"),  # stale observation
            hop("SYN-24", 2024, None),
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 1 and m.state == lf.MATURITY_LOWER_BOUND
        assert lf.FLAG_STATUS_UNVERIFIED in m.flags

    def test_recreated_id_in_the_same_season_is_not_a_season(self):
        chain = index(
            hop("SYN-26b", 2026, "SYN-26a", status="in_season"),
            hop("SYN-26a", 2026, "SYN-25", status="pre_draft"),
            hop("SYN-25", 2025, None),
        )
        m = pit("SYN-26b", chain)
        assert m.completed_seasons == 1 and lf.FLAG_RECREATED_SAME_SEASON in m.flags

    def test_two_predecessors_of_one_season_count_once(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25b", status="in_season"),
            hop("SYN-25b", 2025, "SYN-25a"),
            hop("SYN-25a", 2025, None),
        )
        assert pit("SYN-26", chain).completed_seasons == 1

    def test_season_going_forward_is_a_violation(self):
        chain = index(hop("SYN-25", 2025, "SYN-27"), hop("SYN-27", 2027, None))
        m = pit("SYN-25", chain)
        assert m.stop_reason == lf.STOP_SEASON_ORDER and m.state == lf.MATURITY_LOWER_BOUND

    def test_loop_and_cap(self):
        loop = index(hop("SYN-B", 2025, "SYN-A"), hop("SYN-A", 2024, "SYN-B"))
        assert pit("SYN-B", loop).stop_reason == lf.STOP_LOOP
        long = index(*(hop(f"SYN-{y}", y, f"SYN-{y - 1}") for y in range(2000, 2027)))
        m = lf.resolve_league_maturity("SYN-2026", long, max_hops=5)
        assert m.stop_reason == lf.STOP_CAP and m.state == lf.MATURITY_LOWER_BOUND

    def test_unwalked_start_is_not_walked_not_new(self):
        m = pit("SYN-NOPE", FOUR)
        assert m.cohort == lf.COHORT_NOT_WALKED and m.completed_seasons == 0
        assert m.meets(1) is None  # unknown, never "0 seasons"

    def test_best_ball_dynasty_season_counts_and_is_flagged(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"),
            hop("SYN-25", 2025, None, best_ball=True),
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 1 and lf.FLAG_BEST_BALL_SEASON in m.flags


class TestLeagueLevel:
    def test_league_level_reads_from_the_newest_season(self):
        # A trade in 2024 (point-in-time 1) belongs to a lineage with 3
        # completed seasons today (2023-2025; 2026 still in progress).
        assert pit("SYN-24", FOUR).completed_seasons == 1
        m = lvl("SYN-24", FOUR)
        assert m.completed_seasons == 3 and m.state == lf.MATURITY_EXACT
        assert m.cohort == lf.COHORT_A

    def test_newest_counts_itself_once_complete(self):
        chain = dict(FOUR)
        chain["SYN-26"] = hop("SYN-26", 2026, "SYN-25", status="complete")
        assert lvl("SYN-23", chain).completed_seasons == 4

    def test_fork_is_flagged_and_deterministic(self):
        chain = dict(FOUR)
        chain["SYN-26x"] = hop("SYN-26x", 2026, "SYN-25", status="in_season")
        m = lvl("SYN-23", chain)
        assert lf.FLAG_FORKED_SUCCESSORS in m.flags and m.completed_seasons == 3

    def test_unknown_reading_is_refused(self):
        with pytest.raises(ValueError):
            lf.resolve_league_maturity("SYN-26", FOUR, reading="calendar")


class TestLineage:
    def test_all_seasons_share_one_lineage_whatever_the_walk_depth(self):
        lin = lf.lineage_index(FOUR)
        assert len({lin[k] for k in FOUR}) == 1
        truncated = index(hop("SYN-26", 2026, "SYN-25"), hop("SYN-24", 2024, "SYN-23"))
        lin2 = lf.lineage_index(truncated)
        assert lin2["SYN-26"] != lin2["SYN-24"]  # not yet known to be one
        assert lin2["SYN-26"] == lin2["SYN-25"]  # the unwalked predecessor joins
        assert lin["SYN-26"].startswith("lineage:") and "SYN" not in lin["SYN-26"]

    def test_separate_leagues_stay_separate(self):
        lin = lf.lineage_index(index(hop("SYN-A", 2026, None), hop("SYN-B", 2026, None)))
        assert lin["SYN-A"] != lin["SYN-B"]


class TestCohortsAreDisjoint:
    @pytest.mark.parametrize(
        "count,state,cohort",
        [
            (3, lf.MATURITY_EXACT, lf.COHORT_A),
            (5, lf.MATURITY_LOWER_BOUND, lf.COHORT_A),
            (2, lf.MATURITY_EXACT, lf.COHORT_B_EXACT),
            (2, lf.MATURITY_LOWER_BOUND, lf.COHORT_B_UNRESOLVED),
            (1, lf.MATURITY_EXACT, lf.COHORT_BELOW_TWO),
            (1, lf.MATURITY_LOWER_BOUND, lf.COHORT_UNKNOWN_BELOW_TWO),
        ],
    )
    def test_cohort_ladder(self, count, state, cohort):
        m = lf.LeagueMaturity(lf.READING_POINT_IN_TIME, "SYN", count, state, "x", count)
        assert m.cohort == cohort

    def test_report_dict_carries_no_id(self):
        d = pit("SYN-26", FOUR).to_report_dict()
        assert "SYN" not in repr(d)


class TestChainStore:
    def _conn(self):
        conn = sqlite3.connect(":memory:")
        ledger.ensure_league_chain_schema(conn)
        return conn

    def _league(self, lid, prev, status="complete", season="2025"):
        return {
            "league_id": lid,
            "previous_league_id": prev,
            "season": season,
            "status": status,
            "settings": {"type": 2, "best_ball": 0},
        }

    def test_append_only_dedupes_unchanged_and_records_changes(self):
        conn = self._conn()
        lg = self._league("SYN-25", "SYN-24", status="in_season")
        assert ledger.record_league_chain_hop(conn, lg, observed_ms=1, source="t") == "new"
        assert ledger.record_league_chain_hop(conn, lg, observed_ms=2, source="t") == "unchanged"
        done = dict(lg, status="complete")
        assert ledger.record_league_chain_hop(conn, done, observed_ms=3, source="t") == "new"
        rows = conn.execute("SELECT status FROM league_season_chain ORDER BY hop_id").fetchall()
        assert [r[0] for r in rows] == ["in_season", "complete"]
        latest = ledger.load_league_chain(conn)["SYN-25"]
        assert latest.status == "complete" and latest.previous_league_id == "SYN-24"

    def test_terminator_is_stored_as_a_fact(self):
        conn = self._conn()
        ledger.record_league_chain_hop(conn, self._league("SYN-23", "0"), observed_ms=1, source="t")
        row = conn.execute(
            "SELECT previous_league_id, link_state FROM league_season_chain"
        ).fetchone()
        assert row == (None, ledger.LINK_TERMINATOR)
        assert ledger.load_league_chain(conn)["SYN-23"].previous_league_id is None

    def test_no_id_records_nothing(self):
        conn = self._conn()
        assert ledger.record_league_chain_hop(conn, {}, observed_ms=1, source="t") == "no_league_id"

    def test_missing_table_is_a_state_not_an_error(self):
        conn = sqlite3.connect(":memory:")
        assert ledger.load_league_chain(conn) == {}
        assert ledger.league_chain_store_state(conn) == "missing"
        ledger.ensure_league_chain_schema(conn)
        assert ledger.league_chain_store_state(conn) == "empty"

    def test_resolver_reads_the_store(self):
        conn = self._conn()
        for lid, prev, season, status in (
            ("SYN-26", "SYN-25", "2026", "in_season"),
            ("SYN-25", "SYN-24", "2025", "complete"),
            ("SYN-24", "SYN-23", "2024", "complete"),
            ("SYN-23", "0", "2023", "complete"),
        ):
            ledger.record_league_chain_hop(
                conn, self._league(lid, prev, status, season), observed_ms=1, source="t"
            )
        m = pit("SYN-26", ledger.load_league_chain(conn))
        assert m.completed_seasons == 3 and m.cohort == lf.COHORT_A

    def test_not_wired_to_the_movement_migration(self):
        assert ledger.LEAGUE_CHAIN_TABLE not in {
            t for tables in ledger._MIGRATION_CLEARS.values() for t in tables
        }
        assert "league_season_chain" not in ledger._SCHEMA
