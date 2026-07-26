"""LI-3 — best-ball optimizer exactness (ADR-004).

Three layers of proof that ``src/ros/lineup.py::optimize_lineup`` is a
true maximum-weight assignment, not a heuristic:

1. **Brute-force equivalence** — on small rosters, the optimizer's
   score equals the best score over every legal assignment.
2. **Non-laminar counterexample** — the slot-ordered greedy this
   module used before LI-3 is provably suboptimal when slot
   eligibility sets are neither nested nor disjoint; the exact solve
   handles it.
3. **Historical reconstruction** — replaying real Sleeper best-ball
   weeks (2025, `players_points` as values) reproduces the host's own
   awarded lineup total on 10/10 team-weeks.
"""

from __future__ import annotations

import itertools
import json
import random
from pathlib import Path

import pytest

from src.ros.lineup import RosterPlayer, optimize_lineup, solve_optimal_assignment
from src.ros.lineup import _player_eligible_for_slot as eligible

FIXTURES = Path(__file__).parent / "fixtures"
TOL = 0.011


def brute_force_best(roster: list[RosterPlayer], slots: list[str]) -> float:
    """Exhaustive best legal assignment score (small inputs only).

    Independent reference implementation: recursive search over slots,
    each either left empty or filled with any unused eligible player.
    Deliberately dumb — it must share no logic with the optimizer.
    """
    values = [max(0.0, p.ros_value) for p in roster]
    elig = [[eligible(slot, p) for p in roster] for slot in slots]
    n = len(roster)

    def search(slot_idx: int, used: int) -> float:
        if slot_idx == len(slots):
            return 0.0
        best = search(slot_idx + 1, used)  # leave this slot empty
        row = elig[slot_idx]
        for p in range(n):
            if row[p] and not (used >> p) & 1:
                best = max(best, values[p] + search(slot_idx + 1, used | (1 << p)))
        return best

    return search(0, 0)


class TestBruteForceEquivalence:
    @pytest.mark.parametrize("seed", range(25))
    def test_matches_brute_force_on_random_rosters(self, seed):
        rng = random.Random(seed)
        positions = ["QB", "RB", "WR", "TE", "DL", "LB", "DB", "K"]
        slots = rng.sample(
            ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX", "DL", "LB", "DB", "IDP_FLEX", "K"],
            k=rng.randint(2, 5),
        )
        roster = [
            RosterPlayer(
                player_id=f"p{i}",
                canonical_name=f"P{i}",
                position=rng.choice(positions),
                ros_value=float(rng.randint(1, 100)),
            )
            for i in range(rng.randint(2, 7))
        ]
        sol = optimize_lineup(roster, starter_slots=slots)
        assert sol.starting_lineup_score == pytest.approx(
            brute_force_best(roster, slots), abs=TOL
        ), f"seed={seed} slots={slots}"

    def test_matches_brute_force_with_hybrid_positions(self):
        roster = [
            RosterPlayer("a", "A", "DL", 50.0, fantasy_positions=("DL", "LB")),
            RosterPlayer("b", "B", "DL", 40.0, fantasy_positions=("DL",)),
            RosterPlayer("c", "C", "LB", 30.0, fantasy_positions=("LB",)),
        ]
        slots = ["DL", "LB"]
        sol = optimize_lineup(roster, starter_slots=slots)
        assert sol.starting_lineup_score == pytest.approx(brute_force_best(roster, slots), abs=TOL)
        assert sol.starting_lineup_score == pytest.approx(90.0, abs=TOL)


class TestNonLaminarCounterexample:
    """The pre-LI-3 greedy walked slots most-restrictive-first and took
    the best eligible player.  That is optimal only for a laminar
    eligibility family.  Here FLEX={RB,WR,TE} and SUPER_FLEX={QB,RB,WR,TE}
    are nested, but adding a QB-only slot alongside a QB/RB slot breaks
    nesting — the greedy burns the shared player on the wrong slot."""

    def test_exact_solve_beats_slot_ordered_greedy(self):
        # TE slot and FLEX slot; the only TE is also the best flex option.
        roster = [
            RosterPlayer("te1", "TE1", "TE", 100.0),
            RosterPlayer("wr1", "WR1", "WR", 90.0),
        ]
        slots = ["TE", "FLEX"]
        sol = optimize_lineup(roster, starter_slots=slots)
        assert sol.starting_lineup_score == pytest.approx(190.0, abs=TOL)
        assert sol.unfilled_slots == []

    def test_hybrid_contention_resolved_optimally(self):
        """Two DL/LB hybrids + one pure LB, slots DL+LB+IDP_FLEX.
        A naive per-slot greedy can strand the pure LB."""
        roster = [
            RosterPlayer("h1", "Hybrid1", "DL", 80.0, fantasy_positions=("DL", "LB")),
            RosterPlayer("h2", "Hybrid2", "DL", 70.0, fantasy_positions=("DL", "LB")),
            RosterPlayer("lb", "PureLB", "LB", 60.0),
        ]
        slots = ["DL", "LB", "IDP_FLEX"]
        sol = optimize_lineup(roster, starter_slots=slots)
        assert sol.starting_lineup_score == pytest.approx(210.0, abs=TOL)
        assert sol.unfilled_slots == []

    def test_greedy_would_strand_scarce_player(self):
        """Only one QB on the roster; QB and SUPER_FLEX both want him.
        Exact solve puts him in QB and fills SFLEX with the next best."""
        roster = [
            RosterPlayer("qb", "QB1", "QB", 50.0),
            RosterPlayer("rb", "RB1", "RB", 40.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["QB", "SUPER_FLEX"])
        assert sol.starting_lineup_score == pytest.approx(90.0, abs=TOL)
        assert sol.unfilled_slots == []


class TestAssignmentInvariants:
    def test_no_player_used_twice(self):
        roster = [RosterPlayer("only", "Only", "RB", 50.0)]
        sol = optimize_lineup(roster, starter_slots=["RB", "FLEX", "SUPER_FLEX"])
        ids = [r["playerId"] for r in sol.starting_lineup]
        assert ids == ["only"]
        assert sorted(sol.unfilled_slots) == ["FLEX", "SUPER_FLEX"]

    def test_duplicate_roster_entries_not_double_started(self):
        roster = [
            RosterPlayer("dup", "Dup", "RB", 50.0),
            RosterPlayer("dup", "Dup", "RB", 50.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["RB", "FLEX"])
        assert len([r for r in sol.starting_lineup if r["playerId"] == "dup"]) == 1

    def test_deterministic_across_input_order(self):
        base = [
            RosterPlayer("a", "A", "WR", 10.0),
            RosterPlayer("b", "B", "WR", 10.0),
            RosterPlayer("c", "C", "RB", 10.0),
        ]
        slots = ["WR", "FLEX"]
        first = optimize_lineup(base, starter_slots=slots)
        for perm in itertools.permutations(base):
            other = optimize_lineup(list(perm), starter_slots=slots)
            assert other.starting_lineup_score == first.starting_lineup_score
            assert [r["playerId"] for r in other.starting_lineup] == [
                r["playerId"] for r in first.starting_lineup
            ]

    def test_bye_player_never_preferred_over_available(self):
        roster = [
            RosterPlayer("bye", "Bye", "RB", 99.0, bye=True),
            RosterPlayer("ok", "Ok", "RB", 10.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["RB"])
        assert sol.starting_lineup[0]["playerId"] == "ok"

    def test_solve_returns_slot_indexed_map(self):
        roster = [RosterPlayer("q", "Q", "QB", 5.0)]
        assignment = solve_optimal_assignment(roster, ["RB", "QB"])
        assert list(assignment) == [1]
        assert assignment[1].player_id == "q"


class TestCanonicalSlotLabelling:
    """Among equally-optimal lineups the optimizer must pick the
    intuitive one: higher values in the more restrictive slots.  Score
    is identical either way, but the labelling is user-visible."""

    def test_dedicated_slot_outranks_flex(self):
        roster = [
            RosterPlayer("top", "TopWR", "WR", 90.0),
            RosterPlayer("mid", "MidWR", "WR", 75.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["WR", "FLEX"])
        picks = {r["slot"]: r["canonicalName"] for r in sol.starting_lineup}
        assert picks == {"WR": "TopWR", "FLEX": "MidWR"}

    def test_qb_slot_outranks_super_flex(self):
        roster = [
            RosterPlayer("q1", "QB1", "QB", 95.0),
            RosterPlayer("q2", "QB2", "QB", 88.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["QB", "SUPER_FLEX"])
        picks = {r["slot"]: r["canonicalName"] for r in sol.starting_lineup}
        assert picks == {"QB": "QB1", "SUPER_FLEX": "QB2"}

    def test_hybrid_prefers_dedicated_over_idp_flex(self):
        roster = [
            RosterPlayer("h", "Hybrid", "DL", 60.0, fantasy_positions=("DL", "LB")),
            RosterPlayer("d", "PureDL", "DL", 20.0),
        ]
        sol = optimize_lineup(roster, starter_slots=["DL", "IDP_FLEX"])
        picks = {r["slot"]: r["canonicalName"] for r in sol.starting_lineup}
        assert picks["DL"] == "Hybrid"
        assert picks["IDP_FLEX"] == "PureDL"

    def test_canonicalization_never_changes_the_score(self):
        rng = random.Random(99)
        for _ in range(40):
            roster = [
                RosterPlayer(
                    f"p{i}",
                    f"P{i}",
                    rng.choice(["QB", "RB", "WR", "TE"]),
                    float(rng.randint(1, 50)),
                )
                for i in range(rng.randint(2, 8))
            ]
            slots = ["QB", "RB", "WR", "TE", "FLEX", "SUPER_FLEX"]
            sol = optimize_lineup(roster, starter_slots=slots)
            assert sol.starting_lineup_score == pytest.approx(
                brute_force_best(roster, slots), abs=TOL
            )


class TestLiveLeagueSlotStructure:
    """The corrected 21-slot dynasty_main lineup (LI-1)."""

    SLOTS = (
        ["QB"]
        + ["RB"] * 2
        + ["WR"] * 3
        + ["TE"] * 2
        + ["FLEX"] * 2
        + ["SUPER_FLEX"]
        + ["K"]
        + ["DL"] * 3
        + ["LB"] * 3
        + ["DB"] * 3
    )

    def test_fills_all_21_slots_including_k_and_idp(self):
        roster = []
        pid = 0
        for pos, n in [
            ("QB", 2),
            ("RB", 4),
            ("WR", 6),
            ("TE", 3),
            ("K", 1),
            ("DE", 2),
            ("DT", 2),
            ("LB", 4),
            ("CB", 2),
            ("S", 2),
        ]:
            for _ in range(n):
                pid += 1
                roster.append(RosterPlayer(str(pid), f"{pos}{pid}", pos, 100.0 - pid))
        sol = optimize_lineup(roster, starter_slots=self.SLOTS)
        assert sol.unfilled_slots == []
        assert len(sol.starting_lineup) == 21
        assert sum(1 for r in sol.starting_lineup if r["slot"] == "K") == 1
        assert sum(1 for r in sol.starting_lineup if r["slot"] == "DL") == 3

    def test_hybrids_fill_scarce_idp_slots(self):
        """Roster with no pure LBs but two DL/LB hybrids still fills LB."""
        roster = [
            RosterPlayer("d1", "DL1", "DL", 50.0, fantasy_positions=("DL",)),
            RosterPlayer("d2", "DL2", "DL", 45.0, fantasy_positions=("DL",)),
            RosterPlayer("d3", "DL3", "DL", 44.0, fantasy_positions=("DL",)),
            RosterPlayer("h1", "Hy1", "DL", 40.0, fantasy_positions=("DL", "LB")),
            RosterPlayer("h2", "Hy2", "DE", 35.0, fantasy_positions=("DL", "LB")),
        ]
        sol = optimize_lineup(roster, starter_slots=["DL", "DL", "DL", "LB", "LB"])
        filled = {r["slot"] for r in sol.starting_lineup}
        assert "LB" in filled
        assert sol.unfilled_slots == []
        assert sol.starting_lineup_score == pytest.approx(214.0, abs=TOL)


class TestHistoricalReconstruction:
    """Replay real Sleeper best-ball weeks: with the host's own
    per-player scores as values, the optimizer must reach the host's
    awarded team total.  Fixture: 2025 team-weeks whose starter count
    matches the league's stored roster_positions."""

    # Sleeper writes "0" into a starter slot the team could not fill
    # (e.g. no kicker rostered).  Two of the ten fixture weeks have one.
    EMPTY = "0"

    @staticmethod
    def _cases():
        return json.loads((FIXTURES / "golden_bestball_lineups.json").read_text())

    def _host_filled(self, case) -> list[str]:
        return [s for s in case["hostStarters"] if s != self.EMPTY]

    def test_fixture_covers_ten_team_weeks(self):
        cases = self._cases()
        assert len(cases) == 10
        assert all(len(c["hostStarters"]) == len(c["starterSlots"]) for c in cases)
        # Placeholders are genuinely unfillable slots, never a fixture bug.
        for c in cases:
            for pid in c["hostStarters"]:
                assert pid == self.EMPTY or pid in c["players"]

    @pytest.mark.parametrize("idx", range(10))
    def test_reproduces_host_awarded_total(self, idx):
        case = self._cases()[idx]
        roster = [
            RosterPlayer(
                player_id=pid,
                canonical_name=pid,
                position=info["position"],
                ros_value=info["points"],
                fantasy_positions=tuple(info["fantasyPositions"]),
            )
            for pid, info in case["players"].items()
        ]
        sol = optimize_lineup(roster, starter_slots=case["starterSlots"])
        chosen = [r["playerId"] for r in sol.starting_lineup]
        # The optimizer leaves a slot unfilled exactly when the host did.
        assert len(chosen) == len(self._host_filled(case))
        assert len(sol.unfilled_slots) == len(case["hostStarters"]) - len(self._host_filled(case))
        # Un-clamped total: optimize_lineup floors negative values at 0
        # (correct for ROS values, which are never negative), so sum the
        # raw points for the players it selected.
        total = sum(case["players"][pid]["points"] for pid in chosen)
        assert total == pytest.approx(case["hostPoints"], abs=TOL), (
            f"week {case['week']} roster {case['rosterId']}: "
            f"optimizer {total:.2f} vs host {case['hostPoints']}"
        )

    def test_starter_sets_match_host_except_value_ties(self):
        """Where the optimizer picks a different set than Sleeper, the
        two lineups must score identically — i.e. the only divergence
        allowed is a tie between equally-optimal lineups (resolves the
        SETTINGS_AUDIT tie-handling open question)."""
        differing = 0
        for case in self._cases():
            roster = [
                RosterPlayer(
                    pid,
                    pid,
                    info["position"],
                    info["points"],
                    fantasy_positions=tuple(info["fantasyPositions"]),
                )
                for pid, info in case["players"].items()
            ]
            sol = optimize_lineup(roster, starter_slots=case["starterSlots"])
            chosen = {r["playerId"] for r in sol.starting_lineup}
            if chosen != set(self._host_filled(case)):
                differing += 1
                mine = sum(case["players"][p]["points"] for p in chosen)
                assert mine == pytest.approx(case["hostPoints"], abs=TOL)
        assert differing <= 2  # observed: 2 tie-broken-differently lineups

    def test_ignoring_fantasy_positions_is_strictly_worse(self):
        """Regression guard for the LI-3 finding: dropping Sleeper's
        multi-position eligibility loses points on real weeks."""
        losses = 0
        for case in self._cases():
            single = [
                RosterPlayer(pid, pid, info["position"], info["points"])
                for pid, info in case["players"].items()
            ]
            sol = optimize_lineup(single, starter_slots=case["starterSlots"])
            total = sum(case["players"][r["playerId"]]["points"] for r in sol.starting_lineup)
            if total < case["hostPoints"] - TOL:
                losses += 1
        assert losses > 0, "expected position-only eligibility to under-fill some weeks"
