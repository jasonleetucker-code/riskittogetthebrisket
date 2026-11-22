"""League maturity wired into the Market Trade Ledger (DYN10-3).

The daily build stamps ``leagueMaturity`` (point-in-time at the trade and
league-level as of the build) from ``league_filter.resolve_league_maturity``
over the ``previous_league_id`` chain the box ALREADY holds: the intel
ledger's ``leagues`` + capture tables and the own-league format store.  No
network, no crawl.  Pinned here:

* both stores load read-only into one chain index (the own-league store wins);
* the hook mapping keeps MISSING NEVER ZERO (an unwalked league, or a lower
  bound of zero, is ``unknown`` with no count);
* wiring the resolver changes ``leagueMaturity`` and nothing else -- the same
  trades are kept and grouped, with the same dispositions.

Synthetic ids only.
"""

from __future__ import annotations

import json
import sqlite3

from src.intel import league_filter as lf
from src.intel import ledger
from src.sharp import league_format_capture as lfc
from src.trade import market_trade_eval as E
from src.trade import market_trade_report as R
from src.trade import own_league_format_capture as olfc
from tests.trade.market_trade_fixtures import sleeper_league
from tests.trade.test_market_trade_report import _build, _seed, env  # noqa: F401 — fixture


def _own_store(path, seasons):
    """An own-league store as ``refresh_own_league_formats`` writes it:
    one chain row per fetched season-league plus its capture / check."""
    conn = olfc.connect(path)
    try:
        for i, (lid, season, prev, status) in enumerate(seasons):
            lg = sleeper_league(lid) | {
                "season": season,
                "status": status,
                "previous_league_id": prev or "0",
            }
            lfc.record_capture(conn, lg, captured_ms=1_000 + i, source="t", league_id=lid)
            conn.execute(
                "INSERT INTO own_league_season_chain (league_key, league_id, season,"
                " previous_league_id, first_seen_ms) VALUES ('own_syn', ?, ?, ?, ?)",
                (lid, season, olfc._clean_id(prev), 1_000 + i),
            )
        conn.commit()
    finally:
        conn.close()


OWN_FOUR = [
    ("OWN-26", "2026", "OWN-25", "in_season"),
    ("OWN-25", "2025", "OWN-24", "complete"),
    ("OWN-24", "2024", "OWN-23", "complete"),
    ("OWN-23", "2023", None, "complete"),
]


class TestOwnLeagueStoreChain:
    def test_missing_store_is_a_state(self, tmp_path):
        chain, state = olfc.load_league_chain(tmp_path / "nope.sqlite")
        assert chain == {} and state == "own_league_format_store_missing"
        assert not (tmp_path / "nope.sqlite").exists(), "a reader never creates the store"

    def test_chain_rows_become_hops_with_status_and_type(self, tmp_path):
        path = tmp_path / "own.sqlite"
        _own_store(path, OWN_FOUR)
        chain, state = olfc.load_league_chain(path)
        assert state == "available" and set(chain) == {"OWN-26", "OWN-25", "OWN-24", "OWN-23"}
        assert chain["OWN-23"].previous_league_id is None, "a stored NULL is the stated terminator"
        assert chain["OWN-25"].status == "complete" and chain["OWN-25"].is_dynasty
        m = lf.resolve_league_maturity("OWN-26", chain)
        assert (m.completed_seasons, m.state) == (3, lf.MATURITY_EXACT)


class TestLoadMaturityChain:
    def test_both_stores_merge_and_the_state_names_no_id(self, tmp_path):
        intel = tmp_path / "intel.sqlite"
        conn = sqlite3.connect(intel)
        conn.execute(
            "CREATE TABLE leagues (league_id TEXT PRIMARY KEY, season TEXT,"
            " previous_league_id TEXT, settings_json TEXT)"
        )
        conn.executemany(
            "INSERT INTO leagues VALUES (?, ?, ?, ?)",
            [
                ("SHARP-26", "2026", "SHARP-25", json.dumps({"type": 2})),
                # Same id as the own store, with no status: the own store wins.
                ("OWN-25", "2025", "OWN-24", json.dumps({"type": 2})),
            ],
        )
        conn.commit()
        conn.close()
        own = tmp_path / "own.sqlite"
        _own_store(own, OWN_FOUR)
        chain, state = R.load_maturity_chain(intel_ledger_path=intel, own_league_store_path=own)
        assert set(chain) == {"SHARP-26", "OWN-26", "OWN-25", "OWN-24", "OWN-23"}
        assert chain["OWN-25"].status == "complete"
        assert state == {
            "intelLedger": "available",
            "intelLedgerHops": 2,
            "ownLeagueStore": "available",
            "ownLeagueStoreHops": 4,
            "hops": 5,
        }
        assert "SHARP" not in json.dumps(state) and "OWN" not in json.dumps(state)

    def test_missing_stores_are_states_never_errors(self, tmp_path):
        chain, state = R.load_maturity_chain(
            intel_ledger_path=tmp_path / "no_intel.sqlite",
            own_league_store_path=tmp_path / "no_own.sqlite",
        )
        assert chain == {} and state["hops"] == 0
        assert state["intelLedger"] == "intel_ledger_missing"
        assert state["ownLeagueStore"] == "own_league_format_store_missing"
        assert not (tmp_path / "no_intel.sqlite").exists()


def _hop(lid, season, prev, status="complete"):
    return lf.ChainHop(lid, prev, season, 2, status, False)


CHAIN = {
    h.league_id: h
    for h in (
        _hop("L-26", "2026", "L-25", "in_season"),
        _hop("L-25", "2025", "L-24"),
        _hop("L-24", "2024", "L-23"),
        _hop("L-23", "2023", None),
        _hop("P-26", "2026", "P-25", "in_season"),
        _hop("P-25", "2025", "P-X"),  # P-X never stored
        _hop("Q-26", "2026", "Q-25", "in_season"),  # Q-25 never stored
    )
}


class TestResolverMapping:
    def setup_method(self):
        self.resolve = R.league_maturity_resolver(CHAIN)

    def test_exact_three_is_cohort_a_and_league_level_is_a_lower_bound(self):
        out = self.resolve({"host": "sleeper", "hostLeagueId": "L-26"})
        assert out["pointInTime"] == {"completedSeasons": 3, "certainty": "exact"}
        assert out["asOfBuild"] == {"completedSeasons": 3, "certainty": "lower_bound"}
        assert out["basis"] == R.MATURITY_BASIS_PERSISTED_CHAIN
        assert E.maturity_cohort(**_kw(out["pointInTime"])) == E.COHORT_A

    def test_older_trade_reads_point_in_time_from_its_own_season(self):
        out = self.resolve({"host": "sleeper", "hostLeagueId": "L-24"})
        assert out["pointInTime"] == {"completedSeasons": 1, "certainty": "exact"}
        assert out["asOfBuild"]["completedSeasons"] == 3

    def test_partial_chain_is_a_lower_bound(self):
        out = self.resolve({"host": "sleeper", "hostLeagueId": "P-26"})
        assert out["pointInTime"] == {"completedSeasons": 1, "certainty": "lower_bound"}
        assert E.maturity_cohort(**_kw(out["pointInTime"])) == E.COHORT_UNKNOWN

    def test_lower_bound_of_zero_is_unknown_not_zero(self):
        out = self.resolve({"host": "sleeper", "hostLeagueId": "Q-26"})
        assert out["pointInTime"] == {"completedSeasons": None, "certainty": "unknown"}

    def test_unwalked_league_is_unknown_not_zero(self):
        out = self.resolve({"host": "sleeper", "hostLeagueId": "NOT-STORED"})
        assert out["pointInTime"] == {"completedSeasons": None, "certainty": "unknown"}
        assert out["asOfBuild"] == {"completedSeasons": None, "certainty": "unknown"}

    def test_non_sleeper_or_leagueless_trade_returns_nothing(self):
        assert self.resolve({"host": "mfl", "hostLeagueId": "L-26"}) is None
        assert self.resolve({"host": "sleeper"}) is None

    def test_own_league_row_without_event_id_uses_the_resolved_season_league(self):
        out = self.resolve({"host": "sleeper", "formatEvidence": {"seasonLeagueId": "L-25"}})
        assert out["pointInTime"] == {"completedSeasons": 2, "certainty": "exact"}


def _kw(reading):
    return {"completed_seasons": reading["completedSeasons"], "certainty": reading["certainty"]}


def _seed_chain(intel):
    """Persist a three-completed-season chain behind the fixture's L-IDP."""
    conn = ledger.connect(intel)
    try:
        conn.execute("UPDATE leagues SET previous_league_id = 'L-IDP-25' WHERE league_id = 'L-IDP'")
        for lid, season, prev in (
            ("L-IDP-25", "2025", "L-IDP-24"),
            ("L-IDP-24", "2024", "L-IDP-23"),
            ("L-IDP-23", "2023", "0"),
        ):
            conn.execute(
                "INSERT INTO leagues (league_id, season, previous_league_id, settings_json)"
                " VALUES (?, ?, ?, ?)",
                (lid, season, prev, json.dumps({"type": 2, "bestBall": 0})),
            )
        lfc.ensure_schema(conn)
        for lid in ("L-IDP-25", "L-IDP-24", "L-IDP-23"):
            conn.execute(
                "INSERT OR REPLACE INTO sharp_league_format_checks"
                " (league_id, last_checked_ms, last_result, last_status) VALUES (?, 1, 'new', ?)",
                (lid, "complete"),
            )
        conn.commit()
    finally:
        conn.close()


def test_build_stamps_maturity_and_changes_nothing_else(env, tmp_path):  # noqa: F811
    _seed(env)
    _seed_chain(env["intel"])
    chain, state = R.load_maturity_chain(
        intel_ledger_path=env["intel"], own_league_store_path=tmp_path / "no_own.sqlite"
    )
    assert state["intelLedger"] == "available"
    without = _build(env)
    with_ = _build(env, maturity_resolver=R.league_maturity_resolver(chain))

    def strip(result):
        return [
            json.loads(json.dumps(R._jsonable_group(g), default=str, sort_keys=True))
            for g in result["grouping"].groups
        ]

    a, b = strip(without), strip(with_)
    assert [g["underlyingTradeId"] for g in a] == [g["underlyingTradeId"] for g in b]
    assert [{k: v for k, v in g.items() if k != "leagueMaturity"} for g in a] == [
        {k: v for k, v in g.items() if k != "leagueMaturity"} for g in b
    ], "maturity keeps, groups and disposes of every trade exactly as before"
    assert R.coverage_report(without) == R.coverage_report(with_)

    groups = {g["underlyingTradeId"]: g for g in with_["grouping"].groups}
    lm = groups["utrade:sleeper:L-IDP:T1"]["leagueMaturity"]
    assert lm["state"] == R.MATURITY_RESOLVED and lm["basis"] == R.MATURITY_BASIS_PERSISTED_CHAIN
    assert lm["pointInTime"] == {
        "completedSeasons": 3,
        "certainty": "exact",
        "cohort": E.COHORT_A,
    }
    assert lm["asOfBuild"]["cohort"] == E.COHORT_A
    # A league whose link was never stored stays unknown.
    off = groups["utrade:sleeper:L-OFF:T2"]["leagueMaturity"]
    assert off["pointInTime"]["cohort"] == E.COHORT_UNKNOWN
    assert off["pointInTime"]["completedSeasons"] is None
    # Without the resolver every reading is unknown, as before.
    for g in without["grouping"].groups:
        assert g["leagueMaturity"]["pointInTime"]["cohort"] == E.COHORT_UNKNOWN
