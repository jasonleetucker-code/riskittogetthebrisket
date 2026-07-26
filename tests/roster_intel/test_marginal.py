"""Tests for ``src/roster_intel/marginal.py``.

The brief's single most important constraint is that positional strength
must reflect MARGINAL BEST-BALL CONTRIBUTION, not summed value and not
player count.  Most of this file is therefore written as
mechanism-disconnection tests per ORCHESTRATION §2b: each one is
constructed so that it FAILS if the implementation is quietly swapped for
a name-value proxy, rather than merely passing when the real thing works.

The anchor case is the hoarded-QB roster.  With one QB slot and one
SUPER_FLEX, five elite QBs can contribute at most two lineup spots.
    * summed value  would rank that room ~2.5x its true worth
    * player count  would call it five-deep
    * marginal      sees exactly what the optimizer sees
Every assertion below that mentions "proxy" is checking that gap.
"""

from __future__ import annotations

import pytest

from src.roster_intel.marginal import (
    absence_impacts,
    optimal_score,
    position_marginals,
    solve_summary,
    to_roster_players,
)


def _p(pid: str, pos: str, value: float, **kw) -> dict:
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": kw.pop("fpos", ()),
        **kw,
    }


# The live league's shape, trimmed to the offensive core for legibility.
SLOTS_SF = ["QB", "RB", "RB", "WR", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]


# ── Mechanism: marginal is not summed value ────────────────────────


class TestNotSummedValue:
    def test_hoarded_qbs_do_not_scale_with_count(self):
        """Five elite QBs cannot be worth five QBs' value.

        Fails if strength is computed as sum(values): the sum would keep
        climbing with every QB added, while the true marginal saturates
        once both QB-capable slots are filled.
        """
        base = [
            _p("rb1", "RB", 60),
            _p("rb2", "RB", 55),
            _p("wr1", "WR", 58),
            _p("wr2", "WR", 52),
            _p("wr3", "WR", 48),
            _p("te1", "TE", 40),
        ]
        two_qbs = to_roster_players(base + [_p("qb1", "QB", 90), _p("qb2", "QB", 88)])
        five_qbs = to_roster_players(
            base
            + [
                _p("qb1", "QB", 90),
                _p("qb2", "QB", 88),
                _p("qb3", "QB", 86),
                _p("qb4", "QB", 84),
                _p("qb5", "QB", 82),
            ]
        )

        m2 = position_marginals(two_qbs, SLOTS_SF).by_position["QB"]
        m5 = position_marginals(five_qbs, SLOTS_SF).by_position["QB"]

        # The proxy would report 5/2 = 2.5x. Marginal must not.
        assert m5.marginal_points == pytest.approx(m2.marginal_points, abs=1e-6)
        assert m5.rostered == 5 and m2.rostered == 2
        # And the extra three are visible as clog, not as strength.
        assert m5.non_entering_priced == 3
        assert m5.clogger_value == pytest.approx(86 + 84 + 82)
        assert m2.non_entering_priced == 0

    def test_entry_rate_falls_as_hoarding_grows(self):
        """Count-based strength cannot see this; entry rate must."""
        base = [
            _p("rb1", "RB", 60),
            _p("rb2", "RB", 55),
            _p("wr1", "WR", 58),
            _p("wr2", "WR", 52),
            _p("wr3", "WR", 48),
            _p("te1", "TE", 40),
        ]
        rates = []
        for n in (1, 2, 3, 5):
            qbs = [_p(f"qb{i}", "QB", 90 - i) for i in range(n)]
            pool = to_roster_players(base + qbs)
            rates.append(position_marginals(pool, SLOTS_SF).by_position["QB"].entry_rate)
        # Monotonically non-increasing, and strictly below 1 once hoarding.
        assert rates == sorted(rates, reverse=True)
        assert rates[0] == 1.0
        assert rates[-1] < 0.5

    def test_a_high_value_player_who_never_plays_adds_zero_marginal(self):
        """The cleanest disconnection test: a K with huge nominal value
        in a league with NO kicker slot contributes exactly nothing.

        Summed value would rank this roster's K room enormous.
        """
        pool = to_roster_players(
            [
                _p("qb1", "QB", 90),
                _p("rb1", "RB", 60),
                _p("rb2", "RB", 55),
                _p("wr1", "WR", 58),
                _p("wr2", "WR", 52),
                _p("wr3", "WR", 48),
                _p("te1", "TE", 40),
                _p("k1", "K", 999),  # nominally the most valuable asset
            ]
        )
        marg = position_marginals(pool, SLOTS_SF)
        assert marg.by_position["K"].marginal_points == 0.0
        assert marg.by_position["K"].entered_lineup == 0
        assert marg.by_position["K"].clogger_value == 999


# ── Mechanism: group leave-out, not summed individual leave-outs ───


class TestGroupLeaveOut:
    def test_individual_marginals_do_not_sum_to_the_group_marginal(self):
        """Documents WHY the implementation leaves out the whole group.

        Removing RB1 promotes RB2 into the same slot, so each individual
        drop is small while the group drop is large.  An implementation
        that summed individual leave-outs would understate deep
        positions; this test fails if someone "simplifies" it that way.
        """
        # Explicit minimal slots so rb3 is genuinely benched. On the
        # full board FLEX + SUPER_FLEX would start him, making the two
        # quantities exactly equal and the test vacuous.
        slots = ["RB", "RB"]
        pool = to_roster_players([_p("rb1", "RB", 60), _p("rb2", "RB", 59), _p("rb3", "RB", 58)])
        group = position_marginals(pool, slots).by_position["RB"].marginal_points

        full = optimal_score(pool, slots)
        individual_sum = 0.0
        for target in [p for p in pool if p.position == "RB"]:
            remaining = [p for p in pool if p.player_id != target.player_id]
            individual_sum += full - optimal_score(remaining, slots)

        assert group > individual_sum
        assert individual_sum < group * 0.75  # substantially, not marginally


# ── Mechanism: hybrid eligibility is honored ───────────────────────


class TestHybridEligibility:
    def test_hybrid_idp_counts_toward_both_slot_families(self):
        """Fails if fantasy_positions is dropped on the way into the
        optimizer — the LI-3/ADR-007 bug, re-guarded here because this
        module builds its own RosterPlayer rows."""
        pool = to_roster_players(
            [
                _p("hybrid", "DL", 30, fpos=("DL", "LB")),
                _p("dl1", "DL", 28),
            ]
        )
        summary = solve_summary(pool, ["DL", "LB"])
        # Both slots fill only when the hybrid is legal at LB.
        assert summary.filled_slots == 2
        assert summary.score == pytest.approx(58.0)


# ── Absence / fragility ────────────────────────────────────────────


class TestAbsenceImpacts:
    def test_fragility_separates_deep_from_thin(self):
        """The 'preserve output during absences' half of the brief.

        MECHANISM TEST. The first implementation normalized mean_drop by
        the position's marginal contribution, which collapses to ~1/n
        for any position with no bench — it reported the identical
        0.3333 for a deep RB room and a thin WR room. This asserts the
        two are distinguishable, and fails again if the denominator is
        ever changed back.

        Uses an explicit minimal slot set. On the full superflex board
        FLEX + SUPER_FLEX absorb almost everyone, so a nominal "backup"
        is really a starter and NEITHER position has depth — which is
        what made the first two attempts at this test degenerate.
        Here RB has three bodies for two slots (rb3 is genuinely
        benched) and WR has exactly two for two.
        """
        slots = ["RB", "RB", "WR", "WR"]
        pool = to_roster_players(
            [
                _p("rb1", "RB", 60),
                _p("rb2", "RB", 59),
                _p("rb3", "RB", 58),
                _p("wr1", "WR", 60),
                _p("wr2", "WR", 55),
            ]
        )
        imp = absence_impacts(pool, slots)
        assert imp["RB"].fragility < imp["WR"].fragility
        # Concretely: an RB absence costs ~1 point (rb3 steps in); a WR
        # absence costs the whole player.
        assert imp["RB"].fragility < 0.10
        assert imp["WR"].fragility > 0.90

    def test_worst_drop_is_at_least_the_mean(self):
        pool = to_roster_players(
            [
                _p("qb1", "QB", 95),
                _p("rb1", "RB", 70),
                _p("rb2", "RB", 30),
                _p("wr1", "WR", 65),
                _p("wr2", "WR", 40),
                _p("wr3", "WR", 20),
                _p("te1", "TE", 35),
            ]
        )
        for imp in absence_impacts(pool, SLOTS_SF).values():
            assert imp.worst_drop >= imp.mean_drop - 1e-9

    def test_absence_drops_are_never_negative(self):
        """Removing a player can never IMPROVE an optimal lineup.  A
        negative drop would mean the optimizer is not optimal."""
        pool = to_roster_players(
            [_p(f"wr{i}", "WR", 50 - i) for i in range(8)]
            + [_p("qb1", "QB", 80), _p("rb1", "RB", 45), _p("te1", "TE", 30)]
        )
        for imp in absence_impacts(pool, SLOTS_SF).values():
            assert imp.mean_drop >= 0.0
            assert imp.worst_drop >= 0.0

    def test_only_lineup_entrants_are_tested(self):
        """Benched players cannot have an absence impact — their removal
        changes nothing."""
        pool = to_roster_players(
            [
                _p("qb1", "QB", 90),
                _p("qb2", "QB", 89),
                _p("qb3", "QB", 88),
                _p("qb4", "QB", 87),
                _p("rb1", "RB", 60),
                _p("rb2", "RB", 55),
                _p("wr1", "WR", 58),
                _p("wr2", "WR", 52),
                _p("wr3", "WR", 48),
                _p("te1", "TE", 40),
            ]
        )
        imp = absence_impacts(pool, SLOTS_SF)
        assert imp["QB"].starters_tested == 2  # QB slot + SUPER_FLEX


# ── Solve summary invariants ───────────────────────────────────────


class TestSolveSummary:
    def test_empty_inputs_are_zero_not_an_error(self):
        assert solve_summary([], ["QB"]).score == 0.0
        assert solve_summary(to_roster_players([_p("a", "QB", 5)]), []).score == 0.0

    def test_duplicate_slot_labels_do_not_collide(self):
        """Two RB slots must both appear in the assignment map; a naive
        dict keyed on the bare label would silently keep only one."""
        pool = to_roster_players([_p("rb1", "RB", 60), _p("rb2", "RB", 55)])
        summary = solve_summary(pool, ["RB", "RB"])
        assert summary.filled_slots == 2
        assert len(summary.slot_assignment) == 2
        assert summary.score == pytest.approx(115.0)

    def test_unfilled_slots_are_reported(self):
        # One player fills exactly one slot — he cannot occupy both QB
        # and SUPER_FLEX. Everything else on a 9-slot lineup is unfilled.
        pool = to_roster_players([_p("qb1", "QB", 90)])
        summary = solve_summary(pool, SLOTS_SF)
        assert summary.filled_slots == 1
        assert summary.unfilled_slots == len(SLOTS_SF) - 1

    def test_marginal_share_sums_sensibly(self):
        """Shares are per-position contributions over the full score.
        They need not sum to 1 (slot competition means the parts
        overlap), but no single share may exceed 1."""
        pool = to_roster_players(
            [
                _p("qb1", "QB", 90),
                _p("rb1", "RB", 60),
                _p("rb2", "RB", 55),
                _p("wr1", "WR", 58),
                _p("wr2", "WR", 52),
                _p("wr3", "WR", 48),
                _p("te1", "TE", 40),
            ]
        )
        marg = position_marginals(pool, SLOTS_SF)
        for pm in marg.by_position.values():
            assert 0.0 <= pm.marginal_share <= 1.0


# ── Variation guard (the _positional_coverage lesson) ──────────────


class TestMetricsActuallyVary:
    """`_positional_coverage` once returned exactly 100.00 for all 12
    teams — a constant masquerading as a score.  These assert the
    marginal metrics discriminate between genuinely different rosters
    rather than collapsing to a shared value."""

    def _roster(self, seed: int) -> list:
        # Deterministically distinct rosters.
        return to_roster_players(
            [
                _p("qb1", "QB", 60 + seed * 3),
                _p("rb1", "RB", 55 - seed),
                _p("rb2", "RB", 40 + seed * 2),
                _p("wr1", "WR", 58 - seed * 2),
                _p("wr2", "WR", 45),
                _p("wr3", "WR", 30 + seed),
                _p("te1", "TE", 25 + seed * 4),
            ]
        )

    def test_lineup_scores_vary_across_rosters(self):
        scores = {position_marginals(self._roster(i), SLOTS_SF).lineup_score for i in range(12)}
        assert len(scores) > 1, "lineup score is constant across 12 distinct rosters"

    def test_position_marginals_vary_across_rosters(self):
        for pos in ("QB", "RB", "WR", "TE"):
            vals = {
                round(
                    position_marginals(self._roster(i), SLOTS_SF).by_position[pos].marginal_points,
                    4,
                )
                for i in range(12)
            }
            assert len(vals) > 1, f"{pos} marginal is constant across 12 distinct rosters"
