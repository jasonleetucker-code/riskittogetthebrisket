"""C2-U1 RED — the invariants that did NOT hold before this unit.

Every test here failed at ``a9be61b`` (the C1-U9 head this branch is
stacked on).  They are kept, not deleted, because a repaired defect with
no test is a defect waiting to return.

Each class names the mechanism and the measurement, so a future reader
can tell an invariant from a preference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ros.lineup import (
    RosterPlayer,
    assign_lineup,
    lineup_position,
    resolve_starter_slots,
    slot_demand,
    solve_optimal_assignment,
)

FIXTURES = Path(__file__).resolve().parents[1] / "league_intel" / "fixtures"


# ── D1 — missing objective was coerced to zero ──────────────────────────


class TestMissingIsNotZero:
    """``float(player.ros_value or 0.0)`` made an UNKNOWN objective a
    known zero — baselined in ``config/coercion_baseline.json`` as
    ``src/ros/lineup.py::base = max(0.0, float(player.ros_value or 0.0))``.

    It is not a rounding nicety at this layer.  A player with no value
    read still WON a slot, so the lineup reported a slot as filled by
    someone we cannot price, and ``health_availability_score`` divided by
    a starter count that included them.  ``src/ros/team_strength.py``
    reaches that state on purpose for every unranked player.
    """

    SLOTS = ["QB", "RB", "WR"]

    def _pool(self, wr_value):
        return [
            RosterPlayer("qb", "QB1", "QB", 100.0),
            RosterPlayer("rb", "RB1", "RB", 50.0),
            RosterPlayer("wr", "WR1", "WR", wr_value),
        ]

    def test_zero_is_a_real_value_and_starts(self):
        result = assign_lineup(self._pool(0.0), self.SLOTS)
        assert result.starter_ids == {"qb", "rb", "wr"}
        assert result.unfilled_slots == []
        assert result.unpriced_ids == frozenset()
        assert result.score == pytest.approx(150.0)

    def test_missing_is_not_zero_and_does_not_silently_start(self):
        result = assign_lineup(self._pool(None), self.SLOTS)
        assert "wr" not in result.starter_ids
        assert result.unpriced_ids == frozenset({"wr"})
        # The slot is UNFILLED-because-unpriced, which is a different
        # statement from "nobody is eligible" and from "filled".
        assert result.unfilled_slots == ["WR"]
        assert result.score == pytest.approx(150.0)

    def test_missing_and_zero_produce_different_answers(self):
        """The whole point: the two must not be the same object."""
        zero = assign_lineup(self._pool(0.0), self.SLOTS)
        missing = assign_lineup(self._pool(None), self.SLOTS)
        assert zero.starter_ids != missing.starter_ids
        assert zero.unfilled_slots != missing.unfilled_slots
        # ...and the SCORE is identical, which is exactly why the old
        # coercion was invisible: nothing that only summed values could
        # have caught it.
        assert zero.score == missing.score

    def test_an_unpriced_player_never_displaces_a_priced_one(self):
        pool = [
            RosterPlayer("known", "Known", "WR", 10.0),
            RosterPlayer("unknown", "Unknown", "WR", None),
        ]
        result = assign_lineup(pool, ["WR"])
        assert result.starter_ids == {"known"}


# ── D2 — the family/position vocabulary lived only in JavaScript ────────


class TestLineupPositionExistsInPython:
    """``lineupPosition`` was a ``frontend/lib/starter-slots.js`` export
    with no Python twin, so the server could not resolve a player to the
    token its own slots are named in.  That is the seam that forced the
    frontend to keep an optimizer.
    """

    @pytest.mark.parametrize("pos", ["DE", "DT", "EDGE", "NT", "DL"])
    def test_dl_family(self, pos):
        assert lineup_position(pos) == "DL"

    @pytest.mark.parametrize("pos", ["OLB", "ILB", "LB"])
    def test_lb_family(self, pos):
        assert lineup_position(pos) == "LB"

    @pytest.mark.parametrize("pos", ["CB", "S", "FS", "SS", "DB"])
    def test_db_family(self, pos):
        assert lineup_position(pos) == "DB"

    @pytest.mark.parametrize("pos", ["QB", "RB", "WR", "TE", "DEF"])
    def test_offense_passes_through(self, pos):
        assert lineup_position(pos) == pos

    def test_kicker_aliases(self):
        assert lineup_position("PK") == "K"
        assert lineup_position("K") == "K"

    def test_idp_families_stay_distinct(self):
        """Collapsing every defender to "IDP" makes each defensive slot
        match every defender, so a roster stacked at one IDP position
        starts players the league has no slot for."""
        assert len({lineup_position(p) for p in ("DE", "OLB", "CB")}) == 3


# ── D3 — the truth ladder was re-implemented per consumer ───────────────


class TestOneStarterSlotTruthLadder:
    """live host ``rosterPositions`` → registry ``starters`` → refuse.

    Three implementations existed (``src/bdvm/league_config.py``,
    ``frontend/lib/starter-slots.js``, and the implicit one in
    ``src/ros/lineup.load_league_starter_slots``), and they disagreed on
    whether an absent lineup means "no slots" or "a default lineup".
    """

    def test_live_host_wins(self):
        slots, source = resolve_starter_slots(
            roster_positions=["QB", "RB", "BN", "IR"],
            roster_settings={"starters": {"QB": 5}},
        )
        assert slots == ["QB", "RB"]
        assert source == "sleeper_roster_positions"

    def test_registry_is_the_second_rung(self):
        slots, source = resolve_starter_slots(
            roster_positions=None,
            roster_settings={"starters": {"QB": 1, "SFLEX": 1}},
        )
        assert slots == ["QB", "SUPER_FLEX"]
        assert source == "registry_starters"

    def test_refusal_is_explicit_and_is_not_a_default_lineup(self):
        slots, source = resolve_starter_slots(roster_positions=None, roster_settings=None)
        assert slots == []
        assert source is None

    def test_empty_is_not_present(self):
        """``[]`` from a timed-out Sleeper call must fall through to the
        registry, not be served as "this league starts nobody"."""
        slots, source = resolve_starter_slots(
            roster_positions=[],
            roster_settings={"starters": {"QB": 1}},
        )
        assert slots == ["QB"]
        assert source == "registry_starters"

    def test_bench_slots_are_never_lineup_slots(self):
        slots, _ = resolve_starter_slots(
            roster_positions=["QB", "BN", "TAXI", "IR", "RB"], roster_settings=None
        )
        assert slots == ["QB", "RB"]


# ── D4 — four independent even-split demand models ──────────────────────


class TestSlotDemandIsOneDeclaredContract:
    """``_slot_demand`` (ros), ``_flex_share`` (trade),
    ``_starter_requirements`` (intel) and ``starter_slot_counts``
    (scoring) each re-derived "flex splits evenly across eligible
    positions" — while ``roster_intel/profiles._required_slots``
    deliberately REFUSES to, because LI-5 measured the even split wrong
    by ~40% at QB (SUPER_FLEX went to a QB in 9 of 12 rosters, not 1 in 4).

    So these are not four answers to one question; they are two different
    questions plus an approximation.  The contract must keep them
    NAMED and SEPARATE rather than averaging them into one number.
    """

    SLOTS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE", "FLEX", "FLEX", "SUPER_FLEX"]

    def test_dedicated_demand_does_not_attribute_flex(self):
        d = slot_demand(self.SLOTS)
        assert d.dedicated == {"QB": 1.0, "RB": 2.0, "WR": 3.0, "TE": 2.0}
        assert "FLEX" not in d.dedicated

    def test_flex_capacity_is_reported_as_itself(self):
        d = slot_demand(self.SLOTS)
        assert d.flex_capacity == {"FLEX": 2, "SUPER_FLEX": 1}

    def test_even_split_is_available_but_declared_an_approximation(self):
        d = slot_demand(self.SLOTS)
        assert d.even_split["QB"] == pytest.approx(1.0 + 1 / 4)
        assert d.even_split["RB"] == pytest.approx(2.0 + 2 / 3 + 1 / 4)
        assert d.even_split_is_approximation is True

    def test_the_two_answers_are_not_equal(self):
        """If they were, the distinction would be cosmetic."""
        d = slot_demand(self.SLOTS)
        assert d.dedicated != d.even_split

    def test_bench_slots_carry_no_demand(self):
        d = slot_demand(["QB", "BN", "BN", "IR", "TAXI"])
        assert d.dedicated == {"QB": 1.0}
        assert d.flex_capacity == {}


# ── D5 — the greedy engines, measured against Sleeper's own answer ──────


class TestGreedyEnginesWereMeasurablyWrong:
    """Ground truth is the HOST's awarded best-ball lineup, not our own
    solver — ``tests/league_intel/fixtures/golden_bestball_lineups.json``
    is 10 real 2025 team-weeks with real ``fantasy_positions``.

    Measured at ``a9be61b``:

        exact solver              10/10 reproduces the host lineup
        trade/team_impact greedy   0/10, short 333.66 pts
        starter-slots.js greedy    5/10, short  50.14 pts

    **Attributed, because the headline number would otherwise mislead.**
    Compared like-for-like (same slots, same eligibility), the two
    engines fail for different dominant reasons:

    * ``team_impact`` — eligibility blindness **238.92 pts**, greedy
      ALGORITHM only **2.76 pts** on 1 of 10 weeks.  Its slot-ordered
      fill is nearly right *on this league* because these slots happen
      to be laminar; the rest of its 333.66 is the ``K`` slot it never
      fills, which does not reach its own reported output.
    * ``starter-slots.js`` — eligibility blindness **34.01 pts**, greedy
      ALGORITHM **16.13 pts** on 1 of 10 weeks.

    So both classes are real and neither engine is fixed by repairing
    only one of them.  The algorithmic residue is what rules out a
    JavaScript port of the eligibility tables as the frontend fix:
    correct data does not rescue a greedy.
    """

    @staticmethod
    def _cases():
        return json.loads((FIXTURES / "golden_bestball_lineups.json").read_text())

    @staticmethod
    def _pool(players):
        return [
            RosterPlayer(
                player_id=pid,
                canonical_name=pid,
                position=str(p.get("position") or "").upper(),
                ros_value=float(p.get("points") or 0.0),
                fantasy_positions=tuple(str(x).upper() for x in (p.get("fantasyPositions") or ())),
            )
            for pid, p in players.items()
        ]

    def test_the_canonical_solver_reproduces_the_host_on_every_week(self):
        for case in self._cases():
            assignment = solve_optimal_assignment(
                self._pool(case["players"]), list(case["starterSlots"])
            )
            got = {p.player_id for p in assignment.values()}
            want = set(case["hostStarters"]) - {"0"}
            assert got == want, f"{case['season']}w{case['week']}r{case['rosterId']}"

    def test_a_two_pass_greedy_loses_even_with_canonical_eligibility(self):
        """The counterexample the campaign requires, taken from real
        data rather than constructed: roster 8 of 2025 week 17.

        Pinned as a regression so nobody reintroduces a two-pass fill on
        the grounds that "it agrees on our league".
        """
        from src.ros.lineup import player_eligible_for_slot

        case = next(c for c in self._cases() if c["rosterId"] == 8)
        pool = self._pool(case["players"])
        slots = list(case["starterSlots"])

        ordered = sorted(pool, key=lambda p: (-(p.ros_value or 0.0), p.player_id))
        flexy = {"FLEX", "SUPER_FLEX", "IDP_FLEX", "DL", "LB", "DB"}
        claimed: set[str] = set()
        for want_flex in (False, True):
            for slot in slots:
                if (slot in flexy) is not want_flex:
                    continue
                for p in ordered:
                    if p.player_id in claimed:
                        continue
                    if player_eligible_for_slot(slot, p):
                        claimed.add(p.player_id)
                        break

        greedy = sum(float(case["players"][p]["points"]) for p in claimed)
        exact = sum(p.ros_value for p in solve_optimal_assignment(pool, slots).values())
        assert exact > greedy
        assert exact - greedy == pytest.approx(16.13, abs=0.02)
        assert exact == pytest.approx(case["hostPoints"], abs=0.011)
