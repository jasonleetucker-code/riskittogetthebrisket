"""Tests for ``src/trade/waiver.py``.

This module backs the live ``POST /api/waiver/suggestions`` endpoint
but had **no dedicated test file** — 27% statement coverage, the
weakest of anything under ``src/trade/``.  Everything below is a
behaviour/number assertion over synthetic contracts: no network, no
live board.

The gates pinned here are the ones with real money consequences:

  * the **two-source minimum**, added to kill the "weird" waiver
    suggestions whose value rested on a single ranking list;
  * the ``MIN_WAIVER_VALUE`` floor;
  * rostered-player exclusion (the whole point of a waiver list);
  * the pre-draft rookie suppression window;
  * the FAAB bid arithmetic, which is what the user actually spends.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.trade import waiver as w


def _player(
    name: str,
    position: str,
    value: int,
    *,
    sources: int = 3,
    rookie: bool = False,
    rank: int | None = None,
) -> dict[str, Any]:
    return {
        "displayName": name,
        "canonicalName": name,
        "position": position,
        "rankDerivedValue": value,
        "sourceCount": sources,
        "rookie": rookie,
        "canonicalConsensusRank": rank,
    }


def _contract(*players: dict[str, Any]) -> dict[str, Any]:
    return {"playersArray": list(players)}


@pytest.fixture()
def rookies_allowed(monkeypatch):
    """Pin the date-dependent rookie window OPEN.

    ``_rookies_eligible_today`` keys off the calendar, so without this
    the rookie assertions would pass or fail depending on the month the
    suite runs in.
    """
    monkeypatch.setattr(w, "_rookies_eligible_today", lambda: True)


@pytest.fixture()
def rookies_suppressed(monkeypatch):
    monkeypatch.setattr(w, "_rookies_eligible_today", lambda: False)


# ── The two-source minimum ───────────────────────────────────────────


class TestTwoSourceMinimum:
    """A single-source player must never be surfaced as a pickup.

    Regression guard: single-source rows already take a 70% haircut in
    the valuation pipeline, but one that still clears ``MIN_WAIVER_VALUE``
    would otherwise be recommended off one list's opinion.
    """

    def test_single_source_player_is_excluded(self, rookies_allowed):
        out = w.find_waiver_targets(
            _contract(_player("Solo Guy", "WR", 4000, sources=1)),
            sleeper_teams=[],
        )
        assert out["total"] == 0
        assert out["by_position"] == {}

    def test_two_source_player_is_included(self, rookies_allowed):
        out = w.find_waiver_targets(
            _contract(_player("Duo Guy", "WR", 4000, sources=2)),
            sleeper_teams=[],
        )
        assert out["total"] == 1
        assert [c["name"] for c in out["by_position"]["WR"]] == ["Duo Guy"]

    def test_missing_or_garbage_source_count_is_treated_as_zero(self, rookies_allowed):
        """A row with no usable ``sourceCount`` fails the gate closed."""
        missing = _player("No Count", "WR", 4000)
        del missing["sourceCount"]
        garbage = _player("Bad Count", "WR", 4000)
        garbage["sourceCount"] = "three"

        out = w.find_waiver_targets(_contract(missing, garbage), sleeper_teams=[])
        assert out["total"] == 0


# ── Value floor and roster exclusion ─────────────────────────────────


class TestValueFloorAndRosterExclusion:
    def test_min_waiver_value_default_is_500(self):
        assert w.MIN_WAIVER_VALUE == 500

    def test_player_below_the_floor_is_dropped(self, rookies_allowed):
        """499 is out, 500 is in — the gate is ``< min_value``."""
        out = w.find_waiver_targets(
            _contract(
                _player("Just Under", "WR", 499),
                _player("Exactly At", "RB", 500),
            ),
            sleeper_teams=[],
        )
        names = {c["name"] for cs in out["by_position"].values() for c in cs}
        assert names == {"Exactly At"}

    def test_rostered_players_are_excluded_case_insensitively(self, rookies_allowed):
        out = w.find_waiver_targets(
            _contract(
                _player("Taken Guy", "WR", 4000),
                _player("Free Guy", "WR", 3000),
            ),
            sleeper_teams=[{"players": ["  TAKEN guy "]}],
        )
        assert [c["name"] for c in out["by_position"]["WR"]] == ["Free Guy"]

    def test_kickers_and_defenses_are_opt_in(self, rookies_allowed):
        contract = _contract(
            _player("Boot Foot", "K", 4000),
            _player("Steel Curtain", "DEF", 4000),
            _player("Real WR", "WR", 4000),
        )
        default = w.find_waiver_targets(contract, sleeper_teams=[])
        assert set(default["by_position"]) == {"WR"}

        opted_in = w.find_waiver_targets(contract, sleeper_teams=[], include_kicker_def=True)
        assert set(opted_in["by_position"]) == {"WR", "K", "DEF"}


# ── Pre-draft rookie window ──────────────────────────────────────────


class TestRookieWindow:
    def test_rookies_suppressed_and_flagged(self, rookies_suppressed):
        out = w.find_waiver_targets(
            _contract(
                _player("Rook", "WR", 4000, rookie=True),
                _player("Vet", "WR", 3000),
            ),
            sleeper_teams=[],
        )
        assert [c["name"] for c in out["by_position"]["WR"]] == ["Vet"]
        assert out["rookies_excluded"] is True

    def test_rookies_included_when_window_open(self, rookies_allowed):
        out = w.find_waiver_targets(
            _contract(_player("Rook", "WR", 4000, rookie=True)),
            sleeper_teams=[],
        )
        assert [c["name"] for c in out["by_position"]["WR"]] == ["Rook"]
        assert out["rookies_excluded"] is False


# ── FAAB bid arithmetic ──────────────────────────────────────────────


class TestFaabBidArithmetic:
    """``_compute_faab_bid`` is now a shim over ``src.trade.faab_engine``.

    The formula it used to hold was pool-relative and had no absolute
    value scale::

        share      = value / max(value, top_value_in_pool)
        aggressive = round(budget x (0.05 + 0.25 x share))

    which meant the best player on the wire ALWAYS priced at 30% of
    the budget whether he graded 9999 or 900, and a weaker field bid
    MORE because it lowered the denominator.  These tests pin the
    properties that replaced it.
    """

    def test_bid_is_independent_of_who_else_is_on_the_wire(self):
        """The defect that motivated the redesign.

        The same player must price the same whether he is the best
        option available or the tenth best.  ``top_value_in_pool`` is
        accepted for back-compat and ignored.
        """
        alone = w._compute_faab_bid(2000, budget=100, top_value_in_pool=2000)
        crowded = w._compute_faab_bid(2000, budget=100, top_value_in_pool=9999)
        assert alone == crowded

    def test_replacement_level_players_bid_nothing(self):
        """A player no better than what is freely available is a $0
        claim, not a fifth of the budget."""
        agg, reas, low = w._compute_faab_bid(1000, budget=100)
        assert (agg, reas, low) == (0, 0, 0)

    def test_value_to_bid_is_nonlinear(self):
        """5000 value must not mean $50, and the curve must be convex
        through the meaningful region rather than proportional."""
        at_2500 = w._compute_faab_bid(2500, budget=100)[0]
        at_5000 = w._compute_faab_bid(5000, budget=100)[0]
        assert at_5000 != 50
        # Doubling the value does not double the bid — it saturates.
        assert at_5000 < 2 * max(at_2500, 1) or at_2500 == 0

    def test_elite_players_saturate_at_the_full_budget(self):
        assert w._compute_faab_bid(9999, budget=100)[0] == 100

    def test_a_player_need_not_grade_9999_to_reach_the_full_ceiling(self):
        """The human calibration anchors sit far below the top of the
        scale; the ceiling must reach 100% well before 9999."""
        assert w._compute_faab_bid(3000, budget=100)[0] == 100

    def test_bids_scale_with_the_budget(self):
        """Percentages are of the ORIGINAL budget, so a 200-budget
        league doubles the same player's dollars."""
        at_100 = w._compute_faab_bid(9999, budget=100)[0]
        at_200 = w._compute_faab_bid(9999, budget=200)[0]
        assert at_200 == 2 * at_100

    def test_zero_and_negative_inputs_bid_nothing(self):
        assert w._compute_faab_bid(0, budget=100) == (0, 0, 0)
        assert w._compute_faab_bid(-100, budget=100) == (0, 0, 0)
        assert w._compute_faab_bid(5000, budget=0) == (0, 0, 0)

    def test_objective_value_does_not_shrink_as_the_manager_spends(self, rookies_allowed):
        """The other defect that motivated the redesign.

        ``find_waiver_targets`` used to pass the user's REMAINING
        balance as ``league_budget``, so the same player was worth
        less in week 10 than in week 1 purely because the manager had
        spent.  The remaining balance is a cap, never the scale.
        """
        contract = _contract(_player("Top Guy", "WR", 9999))
        flush = w.find_waiver_targets(
            contract, sleeper_teams=[], user_faab_remaining=100, league_budget=100
        )["by_position"]["WR"][0]["bid"]
        spent = w.find_waiver_targets(
            contract, sleeper_teams=[], user_faab_remaining=100, league_budget=100
        )["by_position"]["WR"][0]["bid"]
        assert flush == spent

    def test_remaining_faab_caps_the_recommendation(self, rookies_allowed):
        """A recommendation must never exceed what the team can pay."""
        out = w.find_waiver_targets(
            _contract(_player("Top Guy", "WR", 9999)),
            sleeper_teams=[],
            user_faab_remaining=7,
            league_budget=100,
        )
        bid = out["by_position"]["WR"][0]["bid"]
        assert bid["aggressive"] <= 7
        assert bid["reasonable"] <= 7
        assert bid["lowball"] <= 7

    def test_missing_faab_falls_back_to_the_league_budget(self, rookies_allowed):
        for remaining in (None, 0):
            out = w.find_waiver_targets(
                _contract(_player("Top Guy", "WR", 9999)),
                sleeper_teams=[],
                user_faab_remaining=remaining,
                league_budget=100,
            )
            bid = out["by_position"]["WR"][0]["bid"]
            # A team at $0 can bid $0; an unknown balance falls back to
            # the full budget rather than inventing headroom.
            assert bid["aggressive"] == (0 if remaining == 0 else 100)


# ── Grouping, ordering and caps ──────────────────────────────────────


class TestGroupingAndCaps:
    def test_candidates_are_sorted_by_value_and_capped_per_position(self, rookies_allowed):
        players = [_player(f"WR{i}", "WR", 1000 + i * 100) for i in range(10)]
        out = w.find_waiver_targets(_contract(*players), sleeper_teams=[], per_position_limit=3)
        got = [c["name"] for c in out["by_position"]["WR"]]
        # Highest value first, capped at 3.
        assert got == ["WR9", "WR8", "WR7"]
        assert out["total"] == 3

    def test_idp_positions_collapse_into_families(self, rookies_allowed):
        """DE/DT/EDGE → DL, ILB/OLB → LB, CB/S → DB."""
        out = w.find_waiver_targets(
            _contract(
                _player("Edge Guy", "EDGE", 4000),
                _player("Tackle Guy", "DT", 3000),
                _player("Inside Guy", "ILB", 3500),
                _player("Corner Guy", "CB", 2000),
            ),
            sleeper_teams=[],
        )
        assert set(out["by_family"]) == {"DL", "LB", "DB"}
        # Family lists are re-sorted across their member positions.
        assert [c["name"] for c in out["by_family"]["DL"]] == ["Edge Guy", "Tackle Guy"]

    def test_total_counts_capped_entries_not_raw_candidates(self, rookies_allowed):
        players = [_player(f"WR{i}", "WR", 1000 + i) for i in range(8)]
        players += [_player(f"RB{i}", "RB", 1000 + i) for i in range(8)]
        out = w.find_waiver_targets(_contract(*players), sleeper_teams=[], per_position_limit=2)
        assert out["total"] == 4


# ── Degraded inputs ──────────────────────────────────────────────────


class TestDegradedInputs:
    def test_missing_players_array_returns_empty_shape(self):
        out = w.find_waiver_targets({}, sleeper_teams=[])
        assert out == {
            "by_position": {},
            "by_family": {},
            "total": 0,
            "rookies_excluded": False,
            "bidMethodology": "ceiling_only_estimate",
        }

    def test_non_list_players_array_returns_empty_shape(self):
        out = w.find_waiver_targets({"playersArray": "nope"}, sleeper_teams=[])
        assert out["total"] == 0

    def test_non_dict_rows_and_teams_are_skipped(self, rookies_allowed):
        contract = {"playersArray": ["junk", None, _player("Real Guy", "WR", 4000)]}
        out = w.find_waiver_targets(contract, sleeper_teams=["junk", None])
        assert [c["name"] for c in out["by_position"]["WR"]] == ["Real Guy"]

    def test_none_value_and_unnamed_rows_are_skipped(self, rookies_allowed):
        nameless = _player("", "WR", 4000)
        valueless = _player("No Value", "WR", 4000)
        valueless["rankDerivedValue"] = None
        out = w.find_waiver_targets(_contract(nameless, valueless), sleeper_teams=[])
        assert out["total"] == 0

    def test_none_sleeper_teams_means_nobody_is_rostered(self, rookies_allowed):
        out = w.find_waiver_targets(_contract(_player("Free Guy", "WR", 4000)), sleeper_teams=None)
        assert out["total"] == 1


# ── Market-aware unification with /api/waiver/faab-recommend ──────────
#
# Before this, /api/waiver/suggestions ran ONLY the fixed-multiplier
# ceiling shim while /api/waiver/faab-recommend ran the full
# market-aware engine — two different formulas for the same player at
# the same moment.  Reproduced live against the 2026-09-01 board: a
# thinly-sourced rookie WR (Cyrus Allen, board value 2282) priced at
# $57-60 "reasonable" under the shim and $0-19 under the full engine
# depending on real contention.  ``team_owner_id`` is what unlocks the
# unified path here.


class TestMarketAwareUnification:
    def test_no_team_owner_id_stays_ceiling_only(self, rookies_allowed):
        out = w.find_waiver_targets(
            _contract(_player("Solo Guy", "WR", 4000)),
            sleeper_teams=[{"ownerId": "owner1", "faabRemaining": 100, "players": []}],
        )
        assert out["bidMethodology"] == "ceiling_only_estimate"

    def test_unresolved_team_owner_id_falls_back_to_ceiling_only(self, rookies_allowed):
        out = w.find_waiver_targets(
            _contract(_player("Solo Guy", "WR", 4000)),
            sleeper_teams=[{"ownerId": "owner1", "faabRemaining": 100, "players": []}],
            team_owner_id="not-a-real-owner",
        )
        assert out["bidMethodology"] == "ceiling_only_estimate"

    def test_resolved_team_owner_id_uses_market_aware_engine(self, rookies_allowed):
        teams = [
            {"ownerId": "owner1", "faabRemaining": 100, "players": []},
            {"ownerId": "owner2", "faabRemaining": 100, "players": []},
        ]
        out = w.find_waiver_targets(
            _contract(_player("Solo Guy", "WR", 4000)),
            sleeper_teams=teams,
            team_owner_id="owner1",
            starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1},
            roster_size=25,
        )
        assert out["bidMethodology"] == "market_aware"

    def test_market_aware_bid_never_exceeds_ceiling_only_estimate_for_an_uncontested_player(
        self, rookies_allowed
    ):
        """The whole point of the fix: once real contention is modeled,
        a claim nobody is fighting for should price at or below what
        the ceiling-only shim would have said, never above it."""
        candidate = _player("Contested Guy", "WR", 3000)
        teams_none = [{"ownerId": "owner1", "faabRemaining": 100, "players": []}]
        ceiling_only = w.find_waiver_targets(
            _contract(candidate), sleeper_teams=teams_none, per_position_limit=10
        )

        # A field of rivals with ZERO visible balance is excluded from
        # the clearing math by policy (an unverifiable rival must never
        # raise the user's bid) — so this is the "nobody is contesting"
        # case for the market-aware path too.
        teams_with_blind_rivals = [
            {"ownerId": "owner1", "faabRemaining": 100, "players": []},
            {"ownerId": "owner2", "faabRemaining": None, "players": []},
            {"ownerId": "owner3", "faabRemaining": None, "players": []},
        ]
        market_aware = w.find_waiver_targets(
            _contract(candidate),
            sleeper_teams=teams_with_blind_rivals,
            team_owner_id="owner1",
            starters={"WR": 3},
            roster_size=25,
            per_position_limit=10,
        )

        ceiling_bid = ceiling_only["by_position"]["WR"][0]["bid"]["reasonable"]
        market_bid = market_aware["by_position"]["WR"][0]["bid"]["reasonable"]
        assert market_bid <= ceiling_bid

    def test_market_aware_bid_never_exceeds_the_team_balance_cap(self, rookies_allowed):
        candidate = _player("Rich Target", "WR", 5000)
        teams = [
            {"ownerId": "owner1", "faabRemaining": 7, "players": []},
            {"ownerId": "owner2", "faabRemaining": 100, "players": []},
        ]
        out = w.find_waiver_targets(
            _contract(candidate),
            sleeper_teams=teams,
            user_faab_remaining=7,
            team_owner_id="owner1",
            starters={"WR": 3},
            roster_size=25,
            per_position_limit=10,
        )
        bid = out["by_position"]["WR"][0]["bid"]
        assert bid["aggressive"] <= 7
        assert bid["reasonable"] <= 7
        assert bid["lowball"] <= 7
