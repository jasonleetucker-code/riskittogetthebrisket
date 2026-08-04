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
    """``_compute_faab_bid`` decides what the user actually spends.

    share          = value / max(value, top_value_in_pool)
    aggressive_raw = budget × (0.05 + 0.25 × share)
    aggressive     = half_up(aggressive_raw)
    reasonable     = half_up(aggressive_raw × 0.70)
    lowball        = half_up(aggressive_raw × 0.35)

    Every tier scales the UNROUNDED aggressive figure, and the rounding
    is explicitly half-up so the server and
    ``frontend/lib/waiver-logic.js::computeFaabHint`` return the same
    dollars — pinned case-by-case in
    ``tests/trade/test_faab_bid_parity.py``.
    """

    def test_top_of_pool_gets_the_full_30_percent_band(self):
        """share = 1.0 → 0.05 + 0.25 = 0.30 → 100 × 0.30 = 30.

        reasonable = 30 × 0.70 = 21
        lowball    = 30 × 0.35 = 10.5 → 11 (half-up; the built-in
                     ``round`` would say 10 and the page says 11)
        """
        agg, reas, low = w._compute_faab_bid(5000, budget=100, top_value_in_pool=5000)
        assert agg == 30
        assert reas == 21
        assert low == 11

    def test_half_value_player_gets_a_smaller_share(self):
        """share = 0.5 → 0.05 + 0.125 = 0.175 → 100 × 0.175 = 17.5.

        aggressive rounds to 18, but the lower tiers are percentages of
        the raw 17.5: 12.25 → 12 and 6.125 → 6.
        """
        agg, reas, low = w._compute_faab_bid(2500, budget=100, top_value_in_pool=5000)
        assert agg == 18
        assert reas == 12
        assert low == 6

    def test_bids_scale_with_the_budget(self):
        """A 50-point budget halves the same share's bid: 50 × 0.30 = 15."""
        agg, _, _ = w._compute_faab_bid(5000, budget=50, top_value_in_pool=5000)
        assert agg == 15

    def test_zero_and_negative_inputs_bid_nothing(self):
        assert w._compute_faab_bid(0, budget=100) == (0, 0, 0)
        assert w._compute_faab_bid(-100, budget=100) == (0, 0, 0)
        assert w._compute_faab_bid(5000, budget=0) == (0, 0, 0)
        assert w._compute_faab_bid(5000, budget=-5) == (0, 0, 0)

    def test_every_nonzero_bid_is_at_least_one_dollar(self):
        """A tiny share must never round down to a $0 bid."""
        agg, reas, low = w._compute_faab_bid(1, budget=1, top_value_in_pool=9999)
        assert agg >= 1 and reas >= 1 and low >= 1

    def test_bids_are_attached_to_candidates_and_use_remaining_faab(self, rookies_allowed):
        """The user's remaining FAAB is the budget, not a flat 100."""
        out = w.find_waiver_targets(
            _contract(_player("Top Guy", "WR", 5000)),
            sleeper_teams=[],
            user_faab_remaining=40,
        )
        bid = out["by_position"]["WR"][0]["bid"]
        # Sole candidate ⇒ share 1.0 ⇒ 40 × 0.30 = 12; 70% of 12 = 8.4.
        assert bid["aggressive"] == 12
        assert bid["reasonable"] == 8

    def test_unknown_faab_falls_back_to_a_100_budget(self, rookies_allowed):
        """``None`` is "we don't know the balance", not "no money"."""
        out = w.find_waiver_targets(
            _contract(_player("Top Guy", "WR", 5000)),
            sleeper_teams=[],
            user_faab_remaining=None,
        )
        assert out["by_position"]["WR"][0]["bid"]["aggressive"] == 30

    def test_spent_out_manager_bids_nothing(self, rookies_allowed):
        """$0 remaining is a KNOWN balance — a manager with no money
        cannot bid.  This used to be folded into the ``None`` fallback
        and produced full-$100-budget bids, the exact inverse of the
        cap it was meant to apply.
        """
        for remaining in (0, -5):
            out = w.find_waiver_targets(
                _contract(_player("Top Guy", "WR", 5000)),
                sleeper_teams=[],
                user_faab_remaining=remaining,
            )
            assert out["by_position"]["WR"][0]["bid"] == {
                "aggressive": 0,
                "reasonable": 0,
                "lowball": 0,
            }


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


# ── Drop candidates ──────────────────────────────────────────────────


class TestDropCandidates:
    def test_returns_lowest_value_roster_players_bottom_up(self):
        out = w.find_drop_candidates(
            _contract(
                _player("Stud", "WR", 9000),
                _player("Mid", "RB", 4000),
                _player("Scrub", "TE", 300),
                _player("Not Mine", "WR", 100),
            ),
            user_team_players=["Stud", "Mid", "Scrub"],
            limit=2,
        )
        assert [c["name"] for c in out] == ["Scrub", "Mid"]

    def test_empty_roster_returns_nothing(self):
        assert w.find_drop_candidates(_contract(_player("A", "WR", 100)), []) == []

    def test_missing_players_array_returns_empty(self):
        assert w.find_drop_candidates({}, ["Anyone"]) == []
        assert w.find_drop_candidates({"playersArray": "nope"}, ["Anyone"]) == []

    def test_deep_rank_gets_an_explicit_rationale(self):
        out = w.find_drop_candidates(
            _contract(_player("Deep Guy", "WR", 400, rank=250)),
            user_team_players=["Deep Guy"],
        )
        assert out[0]["rationale"] == "rank #250 on consensus"

    def test_shallow_rank_falls_back_to_generic_rationale(self):
        out = w.find_drop_candidates(
            _contract(_player("Shallow Guy", "WR", 400, rank=12)),
            user_team_players=["Shallow Guy"],
        )
        assert out[0]["rationale"] == "low value vs roster average"

    def test_zero_and_negative_values_are_skipped(self):
        out = w.find_drop_candidates(
            _contract(
                _player("Zero Guy", "WR", 0),
                _player("Neg Guy", "WR", -50),
                _player("Real Guy", "WR", 100),
            ),
            user_team_players=["Zero Guy", "Neg Guy", "Real Guy"],
        )
        assert [c["name"] for c in out] == ["Real Guy"]
