"""Effective Cut Cost and the cut ladder.

These pin the three decisions in ``src/draft/displacement.py`` that are easy
to "simplify" back into bugs:

1. **Cost is measured over waiver level, not from zero.**  Releasing a player
   costs the gap between him and his best available replacement.  The
   symmetric statement on the rookie side is what stops the optimizer from
   being degenerate, so the two must not drift apart.

2. **An unranked player costs 0, and says so.**  Measured on the live board,
   19 players sit at exactly 497 and 19 more at exactly 375 — thin-coverage
   rows with no position.  Those numbers are artifacts, and treating them as
   real costs would let an identity-join miss on a genuine asset read as a
   cheap cut.  The ``assumedWaiver`` stamp is what lets the UI warn instead.

3. **Droppability is a matching, not a per-position count.**  With FLEX and
   SUPER_FLEX slots, whether a player is droppable depends on who else is
   being dropped.  A count-based rule is wrong in both directions.
"""

from __future__ import annotations

import itertools

from src.draft.displacement import (
    RosterAsset,
    build_cut_ladder,
    effective_cut_cost,
    scarcity_multiplier,
    waiver_values_by_position,
)
from src.league_intel.replacement import ScarcityComponents


def _sc(waiver: float | None) -> ScarcityComponents:
    return ScarcityComponents(
        position="WR",
        lineup_scarcity=None,
        roster_scarcity=None,
        waiver_scarcity=waiver,
        elite_separation=None,
        starter_separation=None,
        replacement_gap=None,
    )


def _row(pid, name, pos, value, asset_class="offense"):
    return {
        "playerId": pid,
        "canonicalName": name,
        "displayName": name,
        "legacyRef": name,
        "position": pos,
        "rankDerivedValue": value,
        "assetClass": asset_class,
    }


class TestWaiverValues:
    def test_returns_the_best_unrostered_player_at_each_position(self):
        contract = {
            "playersArray": [
                _row("1", "Rostered WR", "WR", 8000),
                _row("2", "Free WR", "WR", 1200),
                _row("3", "Worse Free WR", "WR", 900),
                _row("4", "Free RB", "RB", 1500),
            ]
        }
        out = waiver_values_by_position(contract, {"1"})
        assert out == {"WR": 1200.0, "RB": 1500.0}

    def test_a_player_on_any_roster_is_not_a_waiver_option(self):
        contract = {"playersArray": [_row("1", "Taken", "WR", 5000)]}
        assert waiver_values_by_position(contract, {"taken"}) == {}

    def test_picks_are_not_waiver_replacements_for_a_roster_spot(self):
        contract = {
            "playersArray": [
                {
                    "playerId": None,
                    "canonicalName": "2027 1st",
                    "displayName": "2027 1st",
                    "position": "PICK",
                    "rankDerivedValue": 6000,
                    "assetClass": "pick",
                }
            ]
        }
        assert waiver_values_by_position(contract, set()) == {}

    def test_unranked_rows_do_not_set_a_waiver_level(self):
        contract = {"playersArray": [_row("1", "Unranked", "WR", None)]}
        assert waiver_values_by_position(contract, set()) == {}


class TestEffectiveCutCost:
    def test_costs_the_gap_over_the_best_replacement(self):
        asset = RosterAsset("1", "Bench WR", "WR", 2000.0)
        ecc, base, basis, waiver, mult = effective_cut_cost(asset, {"WR": 1200.0})
        assert ecc == 800.0
        assert (base, basis, waiver, mult) == (2000.0, "board", 1200.0, 1.0)

    def test_a_player_at_or_below_replacement_is_free_to_cut(self):
        asset = RosterAsset("1", "Deep WR", "WR", 900.0)
        ecc, _base, _basis, _waiver, _mult = effective_cut_cost(asset, {"WR": 1200.0})
        assert ecc == 0.0

    def test_an_unranked_player_is_priced_at_waiver_and_stamped(self):
        # The bug this guards: substituting the board's 375/497 floor here
        # would turn an identity-join miss into a confident "cut him" with a
        # small but entirely fictional cost attached.
        asset = RosterAsset("1", "Unknown Body", "WR", None)
        ecc, base, basis, waiver, _mult = effective_cut_cost(asset, {"WR": 1200.0})
        assert ecc == 0.0
        assert basis == "assumedWaiver"
        assert base == waiver == 1200.0

    def test_a_positionless_player_falls_back_to_the_cheapest_waiver_level(self):
        # Using 0.0 would make him look maximally expensive to cut, which is
        # the opposite of the truth for what is almost always a bench body.
        asset = RosterAsset("1", "No Position", "", 2000.0)
        ecc, _base, _basis, waiver, _mult = effective_cut_cost(asset, {"WR": 1200.0, "QB": 4000.0})
        assert waiver == 1200.0
        assert ecc == 800.0

    def test_scarcity_scales_the_cost_within_the_documented_band(self):
        assert scarcity_multiplier(None) == 1.0
        assert scarcity_multiplier(_sc(None)) == 1.0
        assert scarcity_multiplier(_sc(0.0)) == 0.85
        assert round(scarcity_multiplier(_sc(1.0)), 10) == 1.15
        # Clamped, so a signal outside 0-1 cannot blow the band open.
        assert round(scarcity_multiplier(_sc(5.0)), 10) == 1.15

    def test_scarcity_applies_to_the_gap_not_the_whole_value(self):
        asset = RosterAsset("1", "Bench WR", "WR", 2000.0)
        ecc, *_ = effective_cut_cost(asset, {"WR": 1200.0}, {"WR": _sc(1.0)})
        assert round(ecc, 6) == round(800.0 * 1.15, 6)


class TestCutLadder:
    ROSTER = [
        RosterAsset("qb1", "Star QB", "QB", 8000.0, ros_value=95),
        RosterAsset("wr1", "Star WR", "WR", 7000.0, ros_value=90),
        RosterAsset("wr2", "Good WR", "WR", 3000.0, ros_value=60),
        RosterAsset("wr3", "Bench WR", "WR", 1500.0, ros_value=30),
        RosterAsset("k1", "Only K", "K", 400.0, ros_value=10),
        RosterAsset("x1", "Unranked", "WR", None, ros_value=1),
    ]
    WAIVER = {"QB": 3000.0, "WR": 1200.0, "K": 380.0}

    def test_orders_cheapest_first_and_numbers_the_rungs(self):
        ladder = build_cut_ladder(self.ROSTER, ["QB", "WR", "K"], self.WAIVER)
        costs = [r.effective_cut_cost for r in ladder.rungs]
        assert costs == sorted(costs)
        assert [r.rung for r in ladder.rungs] == list(range(1, len(ladder.rungs) + 1))

    def test_never_offers_a_cut_that_breaks_the_starting_lineup(self):
        ladder = build_cut_ladder(self.ROSTER, ["QB", "WR", "K"], self.WAIVER)
        undroppable = {u["playerId"] for u in ladder.undroppable}
        # The only kicker fills a required K slot even though he is nearly
        # worthless — a value-ordered ladder without the feasibility guard
        # would cut him second.
        assert "k1" in undroppable
        assert "qb1" in undroppable
        assert "k1" not in {r.player_id for r in ladder.rungs}

    def test_the_unranked_body_is_the_first_cut_and_is_flagged(self):
        ladder = build_cut_ladder(self.ROSTER, ["QB", "WR", "K"], self.WAIVER)
        first = ladder.rungs[0]
        assert first.player_id == "x1"
        assert first.value_basis == "assumedWaiver"
        assert first.effective_cut_cost == 0.0

    def test_greedy_ladder_matches_brute_force_at_every_cardinality(self):
        # The matroid claim, checked rather than asserted: for each k, the
        # greedy prefix must equal the cheapest FEASIBLE k-subset found by
        # exhaustive search.  If someone replaces the feasibility check with
        # a per-position count, this breaks.
        slots = ["QB", "WR", "WR", "K"]
        ladder = build_cut_ladder(self.ROSTER, slots, self.WAIVER)

        def feasible(keep):
            from src.ros.lineup import solve_optimal_assignment

            return len(solve_optimal_assignment([a.to_lineup_player() for a in keep], slots))

        baseline = feasible(self.ROSTER)
        costs = {a.player_id: effective_cut_cost(a, self.WAIVER)[0] for a in self.ROSTER}
        for k in range(1, len(ladder.rungs) + 1):
            greedy = sum(r.effective_cut_cost for r in ladder.rungs[:k])
            best = None
            for combo in itertools.combinations(self.ROSTER, k):
                cut_ids = {a.player_id for a in combo}
                keep = [a for a in self.ROSTER if a.player_id not in cut_ids]
                if feasible(keep) < baseline:
                    continue
                total = sum(costs[a.player_id] for a in combo)
                best = total if best is None else min(best, total)
            assert best is not None, f"no feasible cut set of size {k}"
            assert round(greedy, 6) == round(best, 6), f"greedy suboptimal at k={k}"

    def test_a_roster_that_cannot_fill_its_lineup_still_yields_a_ladder(self):
        # Measured against the BASELINE fill count, not len(slots).  Against
        # len(slots) this roster would report nobody as droppable, which reads
        # as "you are stuck" when the truth is "nothing gets worse".
        roster = [RosterAsset("wr1", "Lone WR", "WR", 2000.0, ros_value=50)]
        ladder = build_cut_ladder(roster, ["QB", "WR", "K"], {"WR": 1200.0})
        assert ladder.unfilled_slots_at_baseline == 2
        assert any("cannot fill" in n for n in ladder.notes)

    def test_no_starter_slots_degrades_with_a_note_rather_than_failing(self):
        ladder = build_cut_ladder(self.ROSTER, [], self.WAIVER)
        assert len(ladder.rungs) == len(self.ROSTER)
        assert any("no starter slots" in n for n in ladder.notes)

    def test_an_empty_roster_is_handled(self):
        ladder = build_cut_ladder([], ["QB"], {})
        assert ladder.rungs == []
        assert ladder.notes

    def test_is_deterministic_across_runs(self):
        a = build_cut_ladder(self.ROSTER, ["QB", "WR", "K"], self.WAIVER)
        b = build_cut_ladder(list(reversed(self.ROSTER)), ["QB", "WR", "K"], self.WAIVER)
        assert [r.player_id for r in a.rungs] == [r.player_id for r in b.rungs]
