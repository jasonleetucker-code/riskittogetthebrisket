"""League maturity: verified COMPLETED dynasty seasons over the real chain.

Owner directive 2026-10-19 (V2) / intake DYN10-3 (2026-11-21): the Chase
Trade Market reports leagues by VERIFIED completed dynasty seasons, following
the real ``previous_league_id`` chain, under two readings (point-in-time at
the trade, league-level as of today); unknown is never zero.  The resolver
tests are ported from PR #1852; the loader tests cover the read-only chain
index built from what the intel ledger already holds.  Synthetic ids only.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from src.intel import league_filter as lf
from src.intel import ledger
from src.public_league import sleeper_client as sc
from src.sharp import league_format_capture as lfc


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
    def test_zero_is_not_a_predecessor(self):
        for raw in ("0", 0, "", " ", None):
            assert lf.predecessor_league_id({"previous_league_id": raw}) is None, raw
        assert lf.predecessor_league_id({}) is None
        assert lf.predecessor_league_id(None) is None
        assert lf.predecessor_league_id({"previous_league_id": " SYN-P "}) == "SYN-P"
        assert lf.predecessor_league_id({"previous_league": "SYN-P"}) == "SYN-P"
        # An explicit terminator is never overridden by the legacy spelling.
        assert lf.predecessor_league_id({"previous_league_id": "0", "previous_league": "X"}) is None

    def test_league_age_floor_no_longer_counts_the_terminator(self):
        # The defect: "0" is truthy, so every first-season league read age 2.
        assert lf.league_age_seasons({"previous_league_id": "0"}) == 1
        assert lf.league_age_seasons({"previous_league_id": 0}) == 1
        assert lf.league_age_seasons({"previous_league_id": "SYN-P"}) == 2
        assert lf.league_age_seasons({}) == 1
        assert lf.league_age_seasons(None) == 0

    def test_terminator_vocabulary_matches_the_walker(self):
        assert lf.CHAIN_TERMINATORS == sc._CHAIN_TERMINATORS

    def test_hop_from_a_league_object_reads_the_terminator(self):
        h = lf.ChainHop.from_league(
            {
                "league_id": "SYN-23",
                "previous_league_id": "0",
                "season": 2023,
                "status": "Complete",
                "settings": {"type": 2, "best_ball": 1},
            }
        )
        assert h.previous_league_id is None and h.season == "2023"
        assert h.is_dynasty and h.is_complete and h.best_ball is True
        assert lf.ChainHop.from_league({"previous_league_id": "0"}) is None


class TestPointInTime:
    def test_trade_season_never_counts(self):
        m = pit("SYN-26", FOUR)
        assert (m.completed_seasons, m.state, m.stop_reason) == (3, lf.MATURITY_EXACT, "terminator")
        # A trade in 2025 sees only 2024 and 2023 before it.
        m25 = pit("SYN-25", FOUR)
        assert m25.completed_seasons == 2 and m25.state == lf.MATURITY_EXACT

    def test_startup_season_counts_once_complete(self):
        assert pit("SYN-24", FOUR).completed_seasons == 1

    def test_first_season_has_zero_and_is_exact(self):
        m = pit("SYN-23", FOUR)
        assert m.completed_seasons == 0 and m.state == lf.MATURITY_EXACT
        assert m.meets(1) is False  # proven not, because the walk is exact

    def test_unwalked_link_is_a_lower_bound_never_a_pass(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"), hop("SYN-25", 2025, "SYN-X")
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 1 and m.state == lf.MATURITY_LOWER_BOUND
        assert m.stop_reason == lf.STOP_NOT_WALKED
        assert m.meets(3) is None

    def test_two_lower_bound_meets_two_but_not_three(self):
        chain = index(
            hop("SYN-26", 2026, "SYN-25", status="in_season"),
            hop("SYN-25", 2025, "SYN-24"),
            hop("SYN-24", 2024, "SYN-X"),
        )
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 2 and m.state == lf.MATURITY_LOWER_BOUND
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
        assert m.stop_reason == lf.STOP_NON_DYNASTY

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

    def test_unknown_status_is_not_complete(self):
        chain = index(hop("SYN-26", 2026, "SYN-25"), hop("SYN-25", 2025, None, status=None))
        m = pit("SYN-26", chain)
        assert m.completed_seasons == 0 and m.state == lf.MATURITY_LOWER_BOUND

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

    def test_unknown_start_season_cannot_order_anything(self):
        chain = index(hop("SYN-26", None, "SYN-25"), hop("SYN-25", 2025, None))
        m = pit("SYN-26", chain)
        assert m.stop_reason == lf.STOP_SEASON_UNKNOWN and m.state == lf.MATURITY_LOWER_BOUND

    def test_loop_and_cap(self):
        loop = index(hop("SYN-B", 2025, "SYN-A"), hop("SYN-A", 2024, "SYN-B"))
        assert pit("SYN-B", loop).stop_reason == lf.STOP_LOOP
        long = index(*(hop(f"SYN-{y}", y, f"SYN-{y - 1}") for y in range(2000, 2027)))
        m = lf.resolve_league_maturity("SYN-2026", long, max_hops=5)
        assert m.stop_reason == lf.STOP_CAP and m.state == lf.MATURITY_LOWER_BOUND

    def test_unwalked_start_is_unknown_not_new(self):
        m = pit("SYN-NOPE", FOUR)
        assert m.walked is False and m.stop_reason == lf.STOP_START_NOT_WALKED
        assert m.state == lf.MATURITY_LOWER_BOUND
        assert m.meets(1) is None  # unknown, never "0 seasons"
        assert pit(None, FOUR).walked is False

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
        assert m.completed_seasons == 3
        # "As of today" is at least 3: no store can prove the lineage has no
        # newer season-league (Sleeper links backward only).
        assert m.state == lf.MATURITY_LOWER_BOUND
        assert lf.FLAG_SUCCESSOR_UNPROVABLE in m.flags

    def test_league_level_is_never_exact_below_the_bar(self):
        chain = index(
            hop("SYN-24", 2024, "SYN-23", status="in_season"),
            hop("SYN-23", 2023, None),
        )
        m = lvl("SYN-23", chain)
        assert m.completed_seasons == 1 and m.state == lf.MATURITY_LOWER_BOUND
        assert m.meets(2) is None
        # Even a newest hop observed complete cannot rule out a successor.
        chain["SYN-24"] = hop("SYN-24", 2024, "SYN-23")
        m2 = lvl("SYN-23", chain)
        assert m2.completed_seasons == 2 and m2.state == lf.MATURITY_LOWER_BOUND
        # The point-in-time reading is unchanged: its walk ends at the terminator.
        assert pit("SYN-24", chain).state == lf.MATURITY_EXACT

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


# ── the read-only chain index the intel ledger already holds ──────────────


def _ledger(rows, *, captures=(), checks=()):
    """An in-memory intel ledger with the ``leagues`` table and the capture
    tables, exactly as discovery / the capture owner write them."""
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE leagues (league_id TEXT PRIMARY KEY, season TEXT, previous_league_id TEXT,"
        " name TEXT, total_rosters INTEGER, settings_json TEXT, first_seen_ms INTEGER,"
        " last_crawled_ms INTEGER)"
    )
    for lid, season, prev, settings in rows:
        conn.execute(
            "INSERT INTO leagues (league_id, season, previous_league_id, settings_json)"
            " VALUES (?, ?, ?, ?)",
            (lid, season, prev, None if settings is None else json.dumps(settings)),
        )
    conn.executescript(lfc._SCHEMA)
    for i, (lid, season, ms, settings, status) in enumerate(captures):
        conn.execute(
            "INSERT INTO sharp_league_format_captures (league_id, season, payload_sha256,"
            " captured_ms, capture_source, league_status, payload_json)"
            " VALUES (?, ?, ?, ?, 't', ?, ?)",
            (lid, season, f"sha{i}", ms, status, json.dumps({"settings": settings})),
        )
    for lid, status in checks:
        conn.execute(
            "INSERT INTO sharp_league_format_checks (league_id, last_checked_ms, last_result,"
            " last_status) VALUES (?, 1, 'new', ?)",
            (lid, status),
        )
    return conn


DYN = {"type": 2, "bestBall": 0}


class TestIntelLedgerChain:
    def test_missing_table_is_empty(self):
        assert ledger.load_league_chain(sqlite3.connect(":memory:")) == {}

    def test_terminator_is_a_fact_and_null_link_is_left_out(self):
        conn = _ledger(
            [
                ("SYN-26", "2026", "SYN-25", DYN),
                ("SYN-25", "2025", "0", DYN),
                # Insider ingest rows carry no link at all: unknown, not a start.
                ("SYN-IN", "2026", None, None),
            ],
            checks=[("SYN-26", "in_season"), ("SYN-25", "complete")],
        )
        chain = ledger.load_league_chain(conn)
        assert set(chain) == {"SYN-26", "SYN-25"}
        assert chain["SYN-26"].previous_league_id == "SYN-25"
        assert chain["SYN-25"].previous_league_id is None
        assert chain["SYN-25"].status == "complete" and chain["SYN-25"].is_dynasty
        m = pit("SYN-26", chain)
        assert (m.completed_seasons, m.state) == (1, lf.MATURITY_EXACT)
        assert pit("SYN-IN", chain).walked is False

    def test_status_and_type_come_from_the_capture_tables(self):
        conn = _ledger(
            [("SYN-25", "2025", "SYN-24", None)],
            captures=[
                ("SYN-25", "2025", 1, {"type": 2, "best_ball": 0}, "in_season"),
                ("SYN-25", "2025", 2, {"type": 2, "best_ball": 1}, "in_season"),
            ],
            checks=[("SYN-25", "complete")],
        )
        h = ledger.load_league_chain(conn)["SYN-25"]
        # Latest observed status (the check table), newest capture's settings.
        assert h.status == "complete" and h.league_type == 2 and h.best_ball is True

    def test_no_status_observed_stays_none(self):
        conn = _ledger([("SYN-25", "2025", "0", DYN)])
        h = ledger.load_league_chain(conn)["SYN-25"]
        assert h.status is None and h.is_complete is False

    def test_not_dynasty_check_leaves_type_unknown(self):
        # The capture owner records no payload for a redraft / keeper league;
        # its type stays None (the walk stops as a lower bound, never guesses).
        conn = _ledger([("SYN-26", "2026", "SYN-25", DYN), ("SYN-25", "2025", "0", None)])
        conn.execute(
            "INSERT INTO sharp_league_format_checks (league_id, last_checked_ms, last_result,"
            " last_status) VALUES ('SYN-25', 1, 'not_dynasty', 'complete')"
        )
        m = pit("SYN-26", ledger.load_league_chain(conn))
        assert m.stop_reason == lf.STOP_TYPE_UNKNOWN and m.state == lf.MATURITY_LOWER_BOUND

    def test_facts_reader_is_read_only_and_absent_tables_are_empty(self):
        assert lfc.load_league_facts(sqlite3.connect(":memory:")) == {}
