"""Per-season Draft Capital views (owner request 2026-10-01).

The /league Draft Capital tab gains an "All Years | <season>..." selector.
The selector changes WHICH picks are included, never HOW they are valued, so
every test here checks the season views against the per-pick dollars the two
existing builders already publish:

* the Sleeper-derived fallback (``build_sleeper_derived``), which spans more
  than one season and sums integer per-pick dollars into ``teamTotals``;
* the default league's workbook path (``server._fetch_draft_capital``), which
  carries exactly one season and forms its totals from the sheet.

Offline: Sleeper and the workbook are stubbed.
"""

from __future__ import annotations

import copy

import pytest

from src.api import draft_capital_fallback as dcf
from src.api.draft_capital_years import (
    BASIS_PER_PICK_SUM,
    BASIS_SINGLE_SEASON_TOTAL,
    attach_year_views,
)


def _stub_fetch_json(responses):
    def fake(url):
        for key, resp in responses.items():
            if key in url:
                return resp
        return None

    return fake


def _league(n=4, traded=None):
    return {
        "/rosters": [{"roster_id": i, "owner_id": f"u{i}"} for i in range(1, n + 1)],
        "/users": [{"user_id": f"u{i}", "display_name": f"Team{i}"} for i in range(1, n + 1)],
        "/traded_picks": traded or [],
    }


def _contract(rows):
    return {
        "playersArray": [
            {
                "displayName": name,
                "canonicalName": name,
                "rankDerivedValue": v,
                "assetClass": "pick",
            }
            for name, v in rows.items()
        ]
    }


# Prices both seasons through the generic-grade rows the canonical board
# publishes for future years (C1-U6); slot rows are absent on purpose so
# the stand-in future "slot" never claims a known position.
_TWO_SEASON_CONTRACT = _contract(
    {
        "2027 Round 1": 6000,
        "2027 Round 2": 2000,
        "2028 Round 1": 4000,
        "2028 Round 2": 1000,
    }
)


@pytest.fixture(autouse=True)
def _pin_draft_year(monkeypatch):
    # ``_pick_value_from_contract`` answers generic grades only for seasons at
    # or after the current rookie draft year; pin it so the test is not
    # calendar-dependent.
    import src.api.data_contract as dc

    monkeypatch.setattr(dc, "current_rookie_draft_year", lambda *a, **k: 2027)


def _build(monkeypatch, *, traded=None, n=4, contract=_TWO_SEASON_CONTRACT, season=2027):
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(_league(n, traded)))
    return dcf.build_sleeper_derived("L1", contract, current_season=season, draft_rounds=2)


def _team(result, name):
    return next(t for t in result["teamTotals"] if t["team"] == name)


def _year_row(result, year, name):
    return next(r for r in result["teamTotalsByYear"][str(year)] if r["team"] == name)


def _manual_year_sum(result, year, team):
    return sum(
        p["dollarValue"]
        for p in result["picks"]
        if p["season"] == year and p["currentOwner"] == team and not p["isUnpriced"]
    )


# ── 1-4, 13: All Years is today's number; each season is its own slice ──


def test_all_years_is_the_sum_of_every_priced_pick_and_unchanged(monkeypatch):
    result = _build(monkeypatch)
    assert result["yearViewBasis"] == BASIS_PER_PICK_SUM
    # (13) the existing all-season total is untouched: still the full budget,
    # still each team's sum of priced per-pick dollars across every season.
    assert sum(t["auctionDollars"] for t in result["teamTotals"]) == 1200
    for t in result["teamTotals"]:
        all_seasons = sum(
            p["dollarValue"]
            for p in result["picks"]
            if p["currentOwner"] == t["team"] and not p["isUnpriced"]
        )
        assert t["auctionDollars"] == all_seasons
        # The season slices add back up to it — no per-season renormalization.
        assert sum(t["draftCapitalByYear"].values()) == t["auctionDollars"]


@pytest.mark.parametrize("year,other", [(2027, 2028), (2028, 2027)])
def test_each_season_counts_only_its_own_picks(monkeypatch, year, other):
    result = _build(monkeypatch)
    for t in result["teamTotals"]:
        assert t["draftCapitalByYear"][str(year)] == _manual_year_sum(result, year, t["team"])
        row = _year_row(result, year, t["team"])
        assert row["auctionDollars"] == _manual_year_sum(result, year, t["team"])
        assert row["pickCount"] == sum(
            1 for p in result["picks"] if p["season"] == year and p["currentOwner"] == t["team"]
        )
    summary = result["yearSummaries"][str(year)]
    assert summary["totalDollars"] == sum(
        p["dollarValue"] for p in result["picks"] if p["season"] == year
    )
    assert summary["totalDollars"] != result["yearSummaries"][str(other)]["totalDollars"]


def test_no_per_season_renormalization(monkeypatch):
    """A season's league total is its share of the ONE $1200 pool, not $1200."""
    result = _build(monkeypatch)
    totals = {y: s["totalDollars"] for y, s in result["yearSummaries"].items()}
    assert sum(totals.values()) == 1200
    assert all(0 < v < 1200 for v in totals.values())
    # 4 teams × (6000 + 2000) vs 4 × (4000 + 1000) → 8 : 5 of the pool.
    assert totals["2027"] == pytest.approx(1200 * 8 / 13, abs=2)


# ── 5: rankings genuinely reorder ────────────────────────────────────────


def test_rankings_reorder_between_seasons(monkeypatch):
    # Team1 owns everyone's 2027 1st; Team4 owns everyone's 2028 1st.
    traded = [
        {"season": "2027", "round": 1, "roster_id": rid, "owner_id": 1} for rid in (2, 3, 4)
    ] + [{"season": "2028", "round": 1, "roster_id": rid, "owner_id": 4} for rid in (1, 2, 3)]
    result = _build(monkeypatch, traded=traded)
    first_2027 = result["teamTotalsByYear"]["2027"][0]
    first_2028 = result["teamTotalsByYear"]["2028"][0]
    assert first_2027["team"] == "Team1" and first_2027["rank"] == 1
    assert first_2028["team"] == "Team4" and first_2028["rank"] == 1
    assert _year_row(result, 2028, "Team1")["rank"] > 1
    # Ranked on that season's capital, descending.
    for rows in result["teamTotalsByYear"].values():
        vals = [r["auctionDollars"] for r in rows]
        assert vals == sorted(vals, reverse=True)


# ── 6: a team with no picks in a season stays, at zero ──────────────────


def test_zero_pick_team_stays_with_zero_capital(monkeypatch):
    traded = [{"season": "2027", "round": r, "roster_id": 2, "owner_id": 1} for r in (1, 2)]
    result = _build(monkeypatch, traded=traded)
    row = _year_row(result, 2027, "Team2")
    assert row["auctionDollars"] == 0
    assert row["pickCount"] == 0
    assert row["rank"] is not None
    assert len(result["teamTotalsByYear"]["2027"]) == 4
    assert _team(result, "Team2")["draftCapitalByYear"]["2027"] == 0


# ── 7, 8: acquired picks count for the CURRENT owner; distinct picks both count ──


def test_acquired_pick_counts_for_current_owner_not_original(monkeypatch):
    traded = [{"season": "2028", "round": 1, "roster_id": 3, "owner_id": 1}]
    result = _build(monkeypatch, traded=traded)
    first_value = next(
        p["dollarValue"] for p in result["picks"] if p["season"] == 2028 and p["round"] == 1
    )
    t1 = _year_row(result, 2028, "Team1")
    t3 = _year_row(result, 2028, "Team3")
    assert t1["pickCount"] == 3 and t3["pickCount"] == 1
    # Team1: own 1st + 2nd + Team3's 1st.  Team3: its 2nd only.
    assert t1["auctionDollars"] - t3["auctionDollars"] == 2 * first_value


def test_two_distinct_picks_same_round_and_season_both_count(monkeypatch):
    traded = [{"season": "2027", "round": 1, "roster_id": 2, "owner_id": 1}]
    result = _build(monkeypatch, traded=traded)
    team1_firsts = [
        p
        for p in result["picks"]
        if p["season"] == 2027 and p["round"] == 1 and p["currentOwner"] == "Team1"
    ]
    assert len(team1_firsts) == 2  # its own + Team2's: two assets, not one label
    assert {p["originalOwner"] for p in team1_firsts} == {"Team1", "Team2"}
    assert _year_row(result, 2027, "Team1")["auctionDollars"] == sum(
        p["dollarValue"]
        for p in result["picks"]
        if p["season"] == 2027 and p["currentOwner"] == "Team1"
    )


# ── 9: one unique pick cannot be counted twice ──────────────────────────


def test_duplicate_trade_rows_do_not_duplicate_a_pick(monkeypatch):
    row = {"season": "2027", "round": 1, "roster_id": 2, "owner_id": 1}
    result = _build(monkeypatch, traded=[row, dict(row), dict(row)])
    keys = [(p["season"], p["round"], p["slot"]) for p in result["picks"]]
    assert len(keys) == len(set(keys))
    assert _year_row(result, 2027, "Team1")["pickCount"] == 3  # own 1st + 2nd, + one acquired
    assert result["yearSummaries"]["2027"]["pickCount"] == 4 * 2


# ── 10, 11: retired seasons absent; available years are data ────────────


def test_retired_season_is_absent_and_years_follow_the_inventory(monkeypatch):
    # The endpoint passes the first NON-retired class as ``current_season``
    # (#1414).  A completed 2026 class must not appear, and the next class
    # must appear with no code change.
    contract = _contract(
        {
            "2026 Round 1": 9999,
            "2027 Round 1": 6000,
            "2028 Round 1": 4000,
            "2029 Round 1": 3000,
        }
    )
    a = _build(monkeypatch, contract=contract, season=2027)
    b = _build(monkeypatch, contract=contract, season=2028)
    assert a["availableYears"] == [2027, 2028]
    assert b["availableYears"] == [2028, 2029]
    assert 2026 not in a["availableYears"]
    assert set(a["teamTotalsByYear"]) == {"2027", "2028"}
    assert all(p["season"] in a["availableYears"] for p in a["picks"])


# ── MISSING IS NEVER ZERO ────────────────────────────────────────────────


def test_unpriced_picks_are_counted_and_never_zero_filled(monkeypatch):
    # 2028 is not priced at all; 2027 round 2 is not priced either.
    contract = _contract({"2027 Round 1": 6000})
    result = _build(monkeypatch, contract=contract)
    assert result["availableYears"] == [2027, 2028]  # the picks still exist
    s28 = result["yearSummaries"]["2028"]
    assert s28["pricedPickCount"] == 0 and s28["unpricedPickCount"] == 8
    for row in result["teamTotalsByYear"]["2028"]:
        assert row["auctionDollars"] is None  # holds picks, none priced: unknown
        assert row["rank"] is None
        assert row["unpricedPickCount"] == 2
    row27 = _year_row(result, 2027, "Team1")
    assert row27["unpricedPickCount"] == 1  # its 2027 2nd
    assert row27["auctionDollars"] == 300  # the priced 1st only
    t1 = _team(result, "Team1")
    assert t1["draftCapitalByYear"]["2028"] is None
    assert t1["unpricedPickCount"] == 3


def test_unknown_capital_sinks_below_a_true_zero():
    result = {
        "season": 2027,
        "teamTotals": [{"team": "A", "auctionDollars": 10}, {"team": "B", "auctionDollars": 0}],
        "picks": [
            {"season": 2027, "currentOwner": "A", "dollarValue": None, "isUnpriced": True},
        ],
    }
    attach_year_views(result)
    rows = result["teamTotalsByYear"]["2027"]
    assert [r["team"] for r in rows] == ["B", "A"]
    assert rows[0]["auctionDollars"] == 0 and rows[0]["rank"] == 1
    assert rows[1]["auctionDollars"] is None and rows[1]["rank"] is None


def test_error_payload_is_left_alone():
    assert attach_year_views({"error": "sleeper_unreachable"}) == {"error": "sleeper_unreachable"}


# ── Workbook (default league) path ──────────────────────────────────────


def _fake_workbook():
    # 2 teams × 2 rounds.  The sheet's Q value (``value``) differs from its
    # L per-pick dollar on purpose: team totals come from Q, rows display L.
    workbook_picks = [
        {"round": 1, "pick": 1, "value": 700.4, "owner": "Ann"},
        {"round": 1, "pick": 2, "value": 300.2, "owner": "Ann"},
        {"round": 2, "pick": 1, "value": 120.1, "owner": "Bob"},
        {"round": 2, "pick": 2, "value": 79.3, "owner": "Bob"},
    ]
    pick_values_l = [690.5, 310.0, 120.0, 79.5]
    return [], workbook_picks, {1: "Ann", 2: "Bob"}, {}, [], pick_values_l


def test_workbook_single_season_equals_existing_total(monkeypatch):
    server = pytest.importorskip("server")
    monkeypatch.setattr(server, "_parse_draft_data", _fake_workbook)
    monkeypatch.setattr(server, "_sleeper_league_id_for_draft", lambda _k=None: None)
    monkeypatch.setattr(server, "_our_rookie_pool", lambda *_a, **_k: [])
    result = server._fetch_draft_capital(apply_sleeper_trades=False)
    season = result["season"]
    assert result["yearViewBasis"] == BASIS_SINGLE_SEASON_TOTAL
    assert result["availableYears"] == [season]
    assert all(p["season"] == season for p in result["picks"])
    for t in result["teamTotals"]:
        # The one season's capital IS the existing total (Q-based), not a
        # re-sum of the L-column row dollars, which would disagree.
        assert t["draftCapitalByYear"] == {str(season): t["auctionDollars"]}
        assert _year_row(result, season, t["team"])["auctionDollars"] == t["auctionDollars"]
    assert [r["team"] for r in result["teamTotalsByYear"][str(season)]] == [
        t["team"] for t in result["teamTotals"]
    ]
    assert result["yearSummaries"][str(season)]["totalDollars"] == result["totalBudget"]


# ── Public boundary ─────────────────────────────────────────────────────


def test_public_redaction_strips_rookie_fields_and_never_mutates_the_cache(monkeypatch):
    server = pytest.importorskip("server")
    rookies = [
        {
            "name": f"R{i}",
            "pos": "WR",
            "dollar": 10,
            "boardValue": 5000 - i,
            "ktcDollar": 9,
            "idpTradeCalcDollar": 8,
            "dispersionCV": 0.1,
            "singleSource": False,
        }
        for i in range(8)
    ]
    monkeypatch.setattr(dcf, "_fetch_json", _stub_fetch_json(_league()))
    result = dcf.build_sleeper_derived(
        "L1", _TWO_SEASON_CONTRACT, current_season=2027, draft_rounds=2, rookies=rookies
    )
    before = copy.deepcopy(result)
    public = server._redact_draft_capital_for_public(result)
    assert result == before  # the cached object is untouched
    for key in ("availableYears", "teamTotalsByYear", "yearSummaries", "yearViewBasis"):
        assert public[key] == result[key]
    private = set(server._DRAFT_CAPITAL_PRIVATE_PICK_FIELDS)
    # The season views carry only public quantities.
    for rows in public["teamTotalsByYear"].values():
        for r in rows:
            assert set(r) == {"team", "auctionDollars", "pickCount", "unpricedPickCount", "rank"}
    for t in public["teamTotals"]:
        assert not (set(t) & private)
    for p in public["picks"]:
        assert not (set(p) & private)
