"""Tests for ``src/roster_intel/window.py``.

The window is a distribution, not a label. The invariants that make it
one — mutual exclusivity, sum-to-1, and a manual override that stays
distinguishable from a measurement — are pinned here, along with
mechanism-disconnection tests per ORCHESTRATION §2b: each fails if the
placement is quietly swapped for a threshold cut or a headcount.
"""

from __future__ import annotations

import pytest

from src.roster_intel.marginal import to_roster_players
from src.roster_intel.window import (
    COMPETITIVE_STATES,
    ORDERING_CAVEAT,
    STATE_ORDER,
    compute_window,
    league_competitiveness,
    trajectory_score,
)


def _p(pid, pos, value, **kw):
    return {
        "playerId": pid,
        "canonicalName": pid,
        "position": pos,
        "rosValue": value,
        "fantasyPositions": (),
        **kw,
    }


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "SUPER_FLEX"]

ROSTER = to_roster_players(
    [
        _p("qb1", "QB", 90),
        _p("rb1", "RB", 60),
        _p("rb2", "RB", 55),
        _p("wr1", "WR", 58),
        _p("wr2", "WR", 52),
        _p("te1", "TE", 40),
    ]
)


def _odds(mapping):
    return [{"ownerId": k, "championshipOdds": v} for k, v in mapping.items()]


# ── The distribution invariants ────────────────────────────────────


class TestDistributionInvariants:
    @pytest.mark.parametrize("comp", [0.0, 0.25, 0.5, 0.75, 1.0])
    def test_probabilities_sum_to_one(self, comp):
        w = compute_window("me", ROSTER, SLOTS, lineup_scores={"me": comp, "other": 0.5})
        assert sum(w.probabilities.values()) == pytest.approx(1.0)

    def test_every_state_is_present_exactly_once(self):
        w = compute_window("me", ROSTER, SLOTS)
        assert set(w.probabilities) == set(COMPETITIVE_STATES)
        assert len(w.probabilities) == 5

    def test_probabilities_are_non_negative(self):
        w = compute_window("me", ROSTER, SLOTS)
        assert all(v >= 0.0 for v in w.probabilities.values())

    def test_most_likely_matches_the_argmax(self):
        w = compute_window("me", ROSTER, SLOTS, lineup_scores={"me": 9, "a": 1, "b": 2})
        assert w.most_likely == max(w.probabilities, key=lambda k: w.probabilities[k])
        assert w.confidence == w.probabilities[w.most_likely]

    @pytest.mark.parametrize("comp", [0.0, 0.13, 0.37, 0.5, 0.61, 0.88, 1.0])
    def test_serialized_probabilities_also_sum_to_one(self, comp):
        """The invariant must survive SERIALIZATION, not just hold on
        the raw floats. Naive per-key rounding to 4dp drifted to 1.0001,
        so a consumer reading the JSON saw a distribution that did not
        sum to 1 - and the payload is what consumers actually read.
        """
        w = compute_window("me", ROSTER, SLOTS, lineup_scores={"me": comp, "lo": 0.0, "hi": 1.0})
        serialized = w.to_dict()["probabilities"]
        assert sum(serialized.values()) == pytest.approx(1.0, abs=1e-12)
        assert set(serialized) == set(COMPETITIVE_STATES)

    def test_serialized_rounding_is_deterministic(self):
        a = compute_window("me", ROSTER, SLOTS, lineup_scores={"me": 5.0, "x": 1.0})
        b = compute_window("me", ROSTER, SLOTS, lineup_scores={"me": 5.0, "x": 1.0})
        assert a.to_dict()["probabilities"] == b.to_dict()["probabilities"]

    def test_sum_to_one_holds_under_an_override(self):
        w = compute_window("me", ROSTER, SLOTS, override_state="rebuild")
        assert sum(w.probabilities.values()) == pytest.approx(1.0)


# ── Placement responds to the measured axes ────────────────────────


class TestPlacement:
    def test_strong_roster_leans_contender_weak_leans_rebuild(self):
        """MECHANISM TEST. Fails if competitiveness stops driving
        placement — e.g. if someone wires it to roster headcount."""
        scores = {"strong": 900.0, "mid": 600.0, "weak": 300.0}
        strong = compute_window("strong", ROSTER, SLOTS, lineup_scores=scores)
        weak = compute_window("weak", ROSTER, SLOTS, lineup_scores=scores)

        contender = ("championship_contender", "playoff_contender")
        assert sum(strong.probabilities[s] for s in contender) > sum(
            weak.probabilities[s] for s in contender
        )
        assert weak.probabilities["rebuild"] > strong.probabilities["rebuild"]

    def test_placement_is_continuous_not_a_threshold_cut(self):
        """A threshold implementation makes a team one point either side
        of a cut flip category while its neighbour does not move. This
        asserts neighbouring rosters produce neighbouring
        distributions."""
        base = {f"t{i}": float(i) for i in range(12)}
        prev = None
        for i in range(12):
            w = compute_window(f"t{i}", ROSTER, SLOTS, lineup_scores=base)
            cur = w.probabilities["rebuild"]
            if prev is not None:
                # Monotone decreasing in competitiveness, and no single
                # step swings the whole distribution.
                assert cur <= prev + 1e-9
                assert abs(cur - prev) < 0.85
            prev = cur

    def test_young_and_old_rosters_at_equal_strength_differ(self):
        """Trajectory must matter. Fails if age is collected but never
        reaches the placement."""
        scores = {"me": 500.0, "a": 400.0, "b": 600.0}
        young = compute_window(
            "me",
            ROSTER,
            SLOTS,
            lineup_scores=scores,
            player_meta={p.player_id: {"age": 23} for p in ROSTER},
        )
        old = compute_window(
            "me",
            ROSTER,
            SLOTS,
            lineup_scores=scores,
            player_meta={p.player_id: {"age": 31} for p in ROSTER},
        )
        assert young.probabilities != old.probabilities
        assert young.inputs.trajectory > old.inputs.trajectory


# ── Competitiveness sourcing ───────────────────────────────────────


class TestCompetitivenessSource:
    def test_prefers_simulated_championship_odds(self):
        score, src = league_competitiveness(
            "b",
            playoff_odds=_odds({"a": 0.05, "b": 0.40, "c": 0.10}),
            lineup_scores={"a": 900.0, "b": 100.0, "c": 500.0},
        )
        assert src == "championshipOdds"
        assert score > 0.5  # best odds, despite the worst lineup score

    def test_falls_back_to_lineup_rank_and_stamps_it(self):
        score, src = league_competitiveness("b", lineup_scores={"a": 100.0, "b": 900.0, "c": 500.0})
        assert src == "lineupScoreRank"
        assert score > 0.5

    def test_all_zero_odds_are_not_treated_as_a_signal(self):
        """An unrun simulator returns zeros for everyone; that is
        missing data, not a league of equals."""
        _, src = league_competitiveness(
            "b",
            playoff_odds=_odds({"a": 0.0, "b": 0.0}),
            lineup_scores={"a": 100.0, "b": 900.0},
        )
        assert src == "lineupScoreRank"

    def test_no_source_is_neutral_and_says_so(self):
        score, src = league_competitiveness("b")
        assert score == 0.5
        assert src == "unavailable"
        w = compute_window("b", ROSTER, SLOTS)
        assert any("defaulted to league median" in n for n in w.notes)

    def test_proxy_source_is_flagged_in_notes(self):
        w = compute_window("me", ROSTER, SLOTS, lineup_scores={"me": 5.0, "x": 1.0})
        assert any("structural proxy" in n for n in w.notes)


# ── Trajectory ─────────────────────────────────────────────────────


class TestTrajectory:
    def test_only_lineup_entrants_count(self):
        """MECHANISM TEST. A bench dart throw's age says nothing about
        the window; fails if the restriction is dropped."""
        pool = to_roster_players([_p("qb1", "QB", 90), _p("qb2", "QB", 1), _p("rb1", "RB", 60)])
        # qb2 is ancient but never starts on a QB-only slot set.
        score, n = trajectory_score(
            pool, ["QB"], {"qb1": {"age": 24}, "qb2": {"age": 40}, "rb1": {"age": 40}}
        )
        assert n == 1
        assert score == pytest.approx((32.0 - 24.0) / (32.0 - 22.0))

    def test_weighting_stops_scrubs_hiding_an_old_anchor(self):
        """Unweighted, five 22-year-olds would drown one 33-year-old
        anchor. Weighted by value, the anchor dominates."""
        pool = to_roster_players(
            [_p("anchor", "QB", 95)] + [_p(f"kid{i}", "RB", 3) for i in range(5)]
        )
        slots = ["QB", "RB", "RB", "RB", "RB", "RB"]
        meta = {"anchor": {"age": 33}}
        meta.update({f"kid{i}": {"age": 22} for i in range(5)})
        score, n = trajectory_score(pool, slots, meta)
        assert n == 6
        unweighted = (33 + 22 * 5) / 6  # 23.83 -> would read 'young'
        weighted_age = 32.0 - score * (32.0 - 22.0)
        assert weighted_age > unweighted

    def test_missing_ages_are_neutral_not_zero(self):
        score, n = trajectory_score(ROSTER, SLOTS, {})
        assert (score, n) == (0.5, 0)

    def test_zero_value_players_do_not_skew_the_weighting(self):
        pool = to_roster_players([_p("a", "QB", 50), _p("b", "QB", 0)])
        score, n = trajectory_score(
            pool, ["QB", "SUPER_FLEX"], {"a": {"age": 25}, "b": {"age": 40}}
        )
        assert n == 1


# ── Manual override ────────────────────────────────────────────────


class TestOverride:
    def test_override_pins_the_state_and_is_stamped(self):
        w = compute_window(
            "me",
            ROSTER,
            SLOTS,
            lineup_scores={"me": 900.0, "x": 100.0},  # model would say contender
            override_state="rebuild",
            override_reason="manager stated intent",
        )
        assert w.overridden is True
        assert w.most_likely == "rebuild"
        assert w.probabilities["rebuild"] == 1.0
        assert w.probabilities["championship_contender"] == 0.0
        assert w.override_reason == "manager stated intent"

    def test_override_retains_model_inputs_for_audit(self):
        """A pinned state must not erase what the model measured, or a
        wrong override becomes undetectable."""
        w = compute_window(
            "me",
            ROSTER,
            SLOTS,
            lineup_scores={"me": 900.0, "x": 100.0},
            override_state="rebuild",
        )
        assert w.inputs.competitiveness > 0.5
        assert w.inputs.competitiveness_source == "lineupScoreRank"

    def test_unknown_override_state_raises(self):
        with pytest.raises(ValueError, match="unknown competitive state"):
            compute_window("me", ROSTER, SLOTS, override_state="tanking")


# ── Ordering contract (relayed to the design agent) ────────────────


class TestOrderingContract:
    def test_state_order_runs_contend_to_rebuild(self):
        assert STATE_ORDER[0] == "championship_contender"
        assert STATE_ORDER[-1] == "rebuild"
        assert len(STATE_ORDER) == len(COMPETITIVE_STATES)

    def test_the_soft_pair_is_documented(self):
        """The caveat is part of the contract: a consumer choosing a
        diverging visual needs to know which adjacency is weak."""
        assert "retool" in ORDERING_CAVEAT
        assert "productive_struggle" in ORDERING_CAVEAT
        w = compute_window("me", ROSTER, SLOTS)
        assert w.to_dict()["orderingCaveat"] == ORDERING_CAVEAT
        assert w.to_dict()["stateOrder"] == list(STATE_ORDER)


# ── Variation guard ────────────────────────────────────────────────


class TestVariation:
    def test_windows_differ_across_twelve_distinct_rosters(self):
        """A constant distribution would be the `_positional_coverage`
        defect in probability clothing."""
        scores = {f"t{i}": 300.0 + i * 55.0 for i in range(12)}
        seen = set()
        for i in range(12):
            w = compute_window(
                f"t{i}",
                ROSTER,
                SLOTS,
                lineup_scores=scores,
                player_meta={p.player_id: {"age": 22 + i} for p in ROSTER},
            )
            seen.add(tuple(round(w.probabilities[s], 4) for s in COMPETITIVE_STATES))
        assert len(seen) == 12, "competitive window is constant across distinct rosters"

    def test_low_confidence_rosters_are_flagged(self):
        """When no state clears 30% the single label is misleading and
        must not be presented alone."""
        found = False
        for i in range(12):
            w = compute_window(
                f"t{i}",
                ROSTER,
                SLOTS,
                lineup_scores={f"t{j}": 300.0 + j * 55.0 for j in range(12)},
                temperature=2.0,  # deliberately indecisive
            )
            if w.confidence < 0.30:
                assert any("should not be presented alone" in n for n in w.notes)
                found = True
        assert found
