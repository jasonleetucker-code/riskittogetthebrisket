"""C2-U1 — the hard invariants of the canonical assignment owner.

Every one is stated as a property, not as an expected answer for one
roster: an assignment engine that is right about ``dynasty_main`` and
wrong about a lineup shape nobody runs yet is the failure mode this unit
exists to end.

Ground truth for optimality is either (a) an independent brute force
that shares no logic with the solver, or (b) Sleeper's OWN awarded
lineup — never the solver's own previous answer.
"""

from __future__ import annotations

import itertools
import random

import pytest

from src.ros.lineup import (
    RosterPlayer,
    assign_lineup,
    player_eligible_for_slot,
    precompute_slot_eligibility,
    solve_optimal_assignment,
)

# dynasty_main's real 21 starting slots.
LIVE_SLOTS = [
    "QB", "RB", "RB", "WR", "WR", "WR", "TE", "TE",
    "FLEX", "FLEX", "SUPER_FLEX", "K",
    "DL", "DL", "DL", "LB", "LB", "LB", "DB", "DB", "DB",
]  # fmt: skip

POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")


def random_roster(rng: random.Random, n: int) -> list[RosterPlayer]:
    out = []
    for i in range(n):
        pos = rng.choice(POSITIONS)
        extra = ()
        if pos in {"DL", "LB", "DB"} and rng.random() < 0.25:
            extra = (rng.choice(["DL", "LB", "DB"]),)
        out.append(
            RosterPlayer(
                player_id=f"p{i}",
                canonical_name=f"P{i}",
                position=pos,
                ros_value=round(rng.uniform(0, 100), 2),
                fantasy_positions=extra,
            )
        )
    return out


def brute_force_best(roster: list[RosterPlayer], slots: list[str]) -> float:
    """Independent reference: exhaustive search over every legal
    assignment.  Deliberately dumb, and shares no code with the solver
    beyond the eligibility predicate it is testing against."""
    values = [p.ros_value or 0.0 for p in roster]
    elig = [[player_eligible_for_slot(slot, p) for p in roster] for slot in slots]
    n = len(roster)

    def search(slot_idx: int, used: int) -> float:
        if slot_idx == len(slots):
            return 0.0
        best = search(slot_idx + 1, used)
        row = elig[slot_idx]
        for p in range(n):
            if row[p] and not (used >> p) & 1:
                best = max(best, values[p] + search(slot_idx + 1, used | (1 << p)))
        return best

    return search(0, 0)


class TestPlayerUniqueness:
    def test_no_player_occupies_two_slots(self):
        rng = random.Random(11)
        for _ in range(40):
            roster = random_roster(rng, 30)
            result = assign_lineup(roster, LIVE_SLOTS)
            ids = [p.player_id for p in result.assignments.values()]
            assert len(ids) == len(set(ids))

    def test_a_roster_carrying_a_player_twice_still_starts_them_once(self):
        dupe = RosterPlayer("x", "X", "RB", 50.0)
        result = assign_lineup([dupe, dupe], ["RB", "FLEX"])
        assert len(result.assignments) == 1
        assert result.duplicate_ids == frozenset({"x"})


class TestSlotCapacity:
    def test_never_more_occupants_than_slots(self):
        rng = random.Random(12)
        for _ in range(40):
            roster = random_roster(rng, 40)
            result = assign_lineup(roster, LIVE_SLOTS)
            assert len(result.assignments) <= len(LIVE_SLOTS)
            assert set(result.assignments).issubset(range(len(LIVE_SLOTS)))

    def test_each_slot_instance_holds_at_most_one(self):
        # The return type is keyed by slot INDEX, which makes double
        # occupancy unrepresentable — asserted so a refactor to a
        # slot-NAME key (where "RB" would collide with "RB") is caught.
        roster = [RosterPlayer(f"r{i}", f"R{i}", "RB", 90.0 - i) for i in range(5)]
        result = assign_lineup(roster, ["RB", "RB"])
        assert sorted(result.assignments) == [0, 1]


class TestEligibilityIsAbsolute:
    def test_every_assigned_player_is_eligible_for_their_slot(self):
        rng = random.Random(13)
        for _ in range(60):
            roster = random_roster(rng, 30)
            result = assign_lineup(roster, LIVE_SLOTS)
            for idx, player in result.assignments.items():
                assert player_eligible_for_slot(LIVE_SLOTS[idx], player)

    def test_an_ineligible_player_is_never_started_even_when_the_slot_is_empty(self):
        # A lone QB cannot fill a TE slot, however much the lineup would
        # rather be full. An empty slot is the correct answer.
        result = assign_lineup([RosterPlayer("q", "Q", "QB", 9999.0)], ["TE"])
        assert result.assignments == {}
        assert result.unfilled_slots == ["TE"]

    def test_multi_position_eligibility_is_honoured(self):
        hybrid = RosterPlayer("h", "H", "DL", 10.0, fantasy_positions=("DL", "LB"))
        assert assign_lineup([hybrid], ["LB"]).starter_ids == {"h"}
        assert assign_lineup([hybrid], ["DL"]).starter_ids == {"h"}
        assert assign_lineup([hybrid], ["WR"]).assignments == {}


class TestGlobalOptimality:
    @pytest.mark.parametrize("seed", range(20))
    def test_matches_an_independent_brute_force(self, seed):
        rng = random.Random(1000 + seed)
        roster = random_roster(rng, rng.randint(4, 9))
        slots = [rng.choice(LIVE_SLOTS) for _ in range(rng.randint(2, 5))]
        assert assign_lineup(roster, slots).score == pytest.approx(
            brute_force_best(roster, slots), abs=1e-6
        )

    def test_the_greedy_counterexample_that_motivated_the_exact_solver(self):
        """Non-laminar eligibility, and the greedy strands a slot.

        ``REC_FLEX`` accepts WR/TE and ``WR_RB_FLEX`` accepts RB/WR:
        they overlap on WR and neither contains the other, so they are
        not a laminar family. With a WR and a TE on the roster and no
        RB, a slot-order greedy — which is exactly what both retired
        engines were — gives ``REC_FLEX`` the best eligible player (the
        100 WR) and then finds nothing left for ``WR_RB_FLEX``, scoring
        100 and leaving a slot empty it could have filled.

        The optimum puts the TE in ``REC_FLEX`` so the WR can take
        ``WR_RB_FLEX``: 190, both slots filled.
        """
        roster = [
            RosterPlayer("wr", "WR", "WR", 100.0),
            RosterPlayer("te", "TE", "TE", 90.0),
        ]
        slots = ["REC_FLEX", "WR_RB_FLEX"]
        result = assign_lineup(roster, slots)
        assert result.score == pytest.approx(190.0)
        assert result.starter_ids == {"wr", "te"}
        assert result.unfilled_slots == []

        # And the greedy really would have scored 100 — computed, so the
        # counterexample is PROVEN to be one rather than asserted to be.
        greedy_total, claimed = 0.0, set()
        for slot in slots:
            best = max(
                (
                    p
                    for p in roster
                    if p.player_id not in claimed and player_eligible_for_slot(slot, p)
                ),
                key=lambda p: p.ros_value,
                default=None,
            )
            if best:
                claimed.add(best.player_id)
                greedy_total += best.ros_value
        assert greedy_total == pytest.approx(100.0)
        assert result.score > greedy_total


def _elig(slot: str) -> frozenset[str]:
    from src.ros.lineup import slot_eligible_positions

    return slot_eligible_positions(slot)


class TestPermutationInvarianceAndDeterminism:
    ROSTER = [
        RosterPlayer("a", "A", "RB", 50.0),
        RosterPlayer("b", "B", "WR", 50.0),
        RosterPlayer("c", "C", "TE", 50.0),
        RosterPlayer("d", "D", "QB", 50.0),
    ]
    SLOTS = ["QB", "FLEX", "SUPER_FLEX"]

    def test_input_order_changes_nothing(self):
        """All four players share a value, so any tie-break bias shows."""
        first = assign_lineup(self.ROSTER, self.SLOTS)
        for perm in itertools.permutations(self.ROSTER):
            other = assign_lineup(list(perm), self.SLOTS)
            assert other.score == first.score
            assert other.starter_ids == first.starter_ids
            assert {i: p.player_id for i, p in other.assignments.items()} == {
                i: p.player_id for i, p in first.assignments.items()
            }

    def test_repeated_solves_are_identical(self):
        runs = {
            tuple(
                sorted(
                    (i, p.player_id)
                    for i, p in assign_lineup(self.ROSTER, self.SLOTS).assignments.items()
                )
            )
            for _ in range(25)
        }
        assert len(runs) == 1

    def test_ties_resolve_by_player_id_not_by_luck(self):
        tied = [RosterPlayer("z", "Z", "RB", 7.0), RosterPlayer("a", "A", "RB", 7.0)]
        assert assign_lineup(tied, ["RB"]).starter_ids == {"a"}
        assert assign_lineup(list(reversed(tied)), ["RB"]).starter_ids == {"a"}


class TestZeroIsRealAndMissingIsNot:
    """The distinction the retired ``or 0.0`` coercion erased."""

    def test_a_zero_valued_player_fills_a_slot_nobody_else_can(self):
        result = assign_lineup([RosterPlayer("k", "K", "K", 0.0)], ["K"])
        assert result.starter_ids == {"k"}
        assert result.unfilled_slots == []
        assert result.score == 0.0

    def test_an_unpriced_player_does_not(self):
        result = assign_lineup([RosterPlayer("k", "K", "K", None)], ["K"])
        assert result.starter_ids == set()
        assert result.unfilled_slots == ["K"]
        assert result.unpriced_ids == frozenset({"k"})

    def test_unpriced_players_are_in_neither_starters_nor_bench(self):
        pool = [
            RosterPlayer("s", "S", "RB", 10.0),
            RosterPlayer("b", "B", "RB", 5.0),
            RosterPlayer("u", "U", "RB", None),
        ]
        result = assign_lineup(pool, ["RB"])
        assert result.starter_ids == {"s"}
        assert result.bench_ids(pool) == {"b"}
        assert result.unpriced_ids == frozenset({"u"})

    def test_a_negative_value_is_clamped_but_still_assignable(self):
        # Clamping to 0 is pre-existing behaviour and is deliberate: a
        # negative ROS read is still a read. It must not become UNKNOWN.
        result = assign_lineup([RosterPlayer("n", "N", "RB", -5.0)], ["RB"])
        assert result.starter_ids == {"n"}
        assert result.score == 0.0
        assert result.unpriced_ids == frozenset()


class TestConfiguredEligibility:
    """Sleeper lets a league configure what its flex accepts, so the
    solver takes it as data — without letting a caller invent a private
    vocabulary (see ``_eligibility_predicate``)."""

    def test_a_league_configured_flex_is_respected(self):
        pool = [
            RosterPlayer("qb", "QB", "QB", 100.0),
            RosterPlayer("rb", "RB", "RB", 50.0),
        ]
        # A FLEX this league configured as QB-only.
        result = assign_lineup(pool, ["FLEX"], slot_eligibility={"FLEX": ["QB"]})
        assert result.starter_ids == {"qb"}
        # ...and unconfigured, the declared table applies: no QB in FLEX.
        assert assign_lineup(pool, ["FLEX"]).starter_ids == {"rb"}

    def test_slots_the_override_does_not_name_keep_the_declared_table(self):
        pool = [RosterPlayer("rb", "RB", "RB", 50.0)]
        result = assign_lineup(pool, ["RB", "FLEX"], slot_eligibility={"FLEX": ["QB"]})
        assert result.starter_ids == {"rb"}
        assert result.unfilled_slots == ["FLEX"]

    def test_configured_eligibility_stays_exact(self):
        """An override must not quietly drop the solver to a heuristic."""
        rng = random.Random(77)
        override = {"FLEX": ["QB", "RB"], "SUPER_FLEX": ["WR", "TE"]}
        for _ in range(15):
            roster = random_roster(rng, 6)
            slots = ["FLEX", "SUPER_FLEX", "RB"]
            got = solve_optimal_assignment(roster, slots, slot_eligibility=override)
            total = sum(p.ros_value or 0.0 for p in got.values())

            # Brute force under the SAME override.
            def elig(slot, player, _o=override):
                allowed = _o.get(slot)
                if allowed is None:
                    return player_eligible_for_slot(slot, player)
                return any(p in allowed for p in player.eligible_positions())

            # Over which SLOTS are used as well as which players, since a
            # legal assignment may leave an earlier slot empty and fill a
            # later one — pinning only the first k slots would understate
            # the optimum and pass a suboptimal solver.
            best = 0.0
            for k in range(len(slots) + 1):
                for chosen_slots in itertools.combinations(range(len(slots)), k):
                    for combo in itertools.permutations(roster, k):
                        if all(elig(slots[chosen_slots[i]], combo[i]) for i in range(k)):
                            best = max(best, sum(p.ros_value or 0.0 for p in combo))
            assert total == pytest.approx(best, abs=1e-6)


class TestPrecomputedEligibilityHoist:
    """``precompute_slot_eligibility`` / ``precomputed_eligibility`` (Defect
    1 fix, 2026-09-06): a Monte Carlo simulation re-solves the SAME pool
    composition against different drawn VALUES thousands of times per
    team, and eligibility depends only on position/fantasy_positions —
    never on value — so it can be computed once and reused. Two things
    must hold for that to be safe: the result must be IDENTICAL to
    deriving eligibility fresh on every call, and it must actually be
    faster (a hoist that isn't need not exist).
    """

    def test_precomputed_eligibility_matches_derived_on_every_call(self):
        """Same pool identity, many different value draws (the exact
        access pattern `game_day_sim._team_score` uses): the precomputed
        path and the derive-every-time path must agree on every draw."""
        rng = random.Random(2026)
        pool_template = random_roster(rng, 45)
        elig = precompute_slot_eligibility(pool_template, LIVE_SLOTS)

        for _ in range(50):
            drawn = [
                RosterPlayer(
                    player_id=p.player_id,
                    canonical_name=p.canonical_name,
                    position=p.position,
                    ros_value=round(rng.uniform(0, 100), 2),
                    fantasy_positions=p.fantasy_positions,
                )
                for p in pool_template
            ]
            derived = solve_optimal_assignment(drawn, LIVE_SLOTS)
            precomputed = solve_optimal_assignment(drawn, LIVE_SLOTS, precomputed_eligibility=elig)
            assert {i: p.player_id for i, p in derived.items()} == {
                i: p.player_id for i, p in precomputed.items()
            }

    def test_precomputed_eligibility_is_not_slower_than_deriving_it(self):
        """The actual production defect: `_eligibility_predicate` was
        rederived from scratch on every one of 24,000 per-request solver
        calls at realistic scale (2000 draws x 12 teams), measured at
        45-51s in production. This does not assert an absolute wall-clock
        budget — that is a CI-runner-speed test, not a correctness one —
        it asserts the RELATIONSHIP the fix depends on, timed within one
        run so environment speed cancels out: reusing a precomputed
        eligibility map must not be slower than rederiving it every call.
        A future change that quietly stops the hoist from doing anything
        (e.g. an accidental copy that rebuilds the map internally anyway)
        would show up here as the ratio collapsing to ~1, not as a
        several-seconds-slower CI run someone has to notice separately.
        """
        import time

        rng = random.Random(99)
        pool_template = random_roster(rng, 45)
        elig = precompute_slot_eligibility(pool_template, LIVE_SLOTS)

        draws = [
            [
                RosterPlayer(
                    player_id=p.player_id,
                    canonical_name=p.canonical_name,
                    position=p.position,
                    ros_value=round(random.Random(i).uniform(0, 100), 2),
                    fantasy_positions=p.fantasy_positions,
                )
                for p in pool_template
            ]
            for i in range(300)
        ]

        t0 = time.perf_counter()
        for pool in draws:
            solve_optimal_assignment(pool, LIVE_SLOTS)
        without_precompute = time.perf_counter() - t0

        t0 = time.perf_counter()
        for pool in draws:
            solve_optimal_assignment(pool, LIVE_SLOTS, precomputed_eligibility=elig)
        with_precompute = time.perf_counter() - t0

        assert with_precompute < without_precompute, (
            f"precomputed eligibility ({with_precompute:.3f}s over 300 calls) was not "
            f"faster than deriving it every call ({without_precompute:.3f}s) — the hoist "
            "this test exists to guard has stopped doing anything."
        )
