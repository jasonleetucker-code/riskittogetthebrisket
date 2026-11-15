"""Study two, library half: independent oracles for the new statistics, gates and decision rule.

Preregistration: ``docs/league-intelligence/TEAM_POINTS_STUDY2_PREREGISTRATION_2026-11-09.md``.
Every expected value is computed by hand or by exhaustive enumeration written out here.
No test computes a value with the function under test and compares it with itself.
"""

from __future__ import annotations

import math
import statistics

import pytest

from src.ros_calibration import team_points as tp

# ── exact sign-flip test ─────────────────────────────────────────────────────────────


def test_sign_flip_five_positive_weeks_is_one_in_thirty_two():
    # Only the all-plus assignment reaches the observed sum of 15.
    assert tp.exact_sign_flip_p([3.0, 1.0, 2.0, 5.0, 4.0]) == pytest.approx(1 / 32)


def test_sign_flip_a_single_losing_week_misses_alpha():
    # Observed 39.9.  Flipping the small loser gives 40.1, so two assignments reach it.
    p = tp.exact_sign_flip_p([10.0, 10.0, 10.0, 10.0, -0.1])
    assert p == pytest.approx(2 / 32)
    assert p > tp.STUDY2_ALPHA


def test_sign_flip_counts_ties_on_the_sum():
    # D = (1, -1): sums over sign flips are 0, 2, -2, 0; three of four reach 0.
    assert tp.exact_sign_flip_p([1.0, -1.0]) == pytest.approx(3 / 4)


def test_sign_flip_three_weeks_hand_enumeration():
    # ±2 ±1 ±1 gives 4, 2, 2, 0, 0, -2, -2, -4; only the first reaches the observed 4.
    assert tp.exact_sign_flip_p([2.0, 1.0, 1.0]) == pytest.approx(1 / 8)


def test_sign_flip_four_weeks_cannot_reach_alpha():
    # The minimum-sample rule: four weeks floor at 1/16 and can never clear 0.05.
    assert tp.exact_sign_flip_p([9.0, 8.0, 7.0, 6.0]) == pytest.approx(1 / 16)
    assert 1 / 16 > tp.STUDY2_ALPHA
    assert 1 / 32 <= tp.STUDY2_ALPHA


def test_sign_flip_refuses_no_weeks():
    with pytest.raises(tp.InsufficientEvidence):
        tp.exact_sign_flip_p([])


def test_weekly_t_statistic_hand_value():
    # mean 2, sd 1, se 1/sqrt(3), so t = 2 * sqrt(3).
    assert tp.weekly_t_statistic([1.0, 2.0, 3.0]) == pytest.approx(2.0 * math.sqrt(3.0))
    assert tp.weekly_t_statistic([4.0, 4.0, 4.0]) is None


# ── two-way bootstrap ────────────────────────────────────────────────────────────────


def _rec(team: str, a: float, b: float) -> tp.Record:
    return tp.Record("team_week", ((team, 1.0),), {"X": {"m": a}, "Y": {"m": b}})


def test_two_way_bootstrap_matches_exhaustive_enumeration():
    # Differences by (week, team): w1 = (1, 3), w2 = (5, 7).  Point estimate 4.
    # Enumerating the resamples of two weeks x two teams by hand gives support {1..7}
    # with P(1) = P(7) = 1/16 > 2.5%, so the symmetric 95% interval is exactly [1, 7].
    grid = {
        1: [_rec("A", 1.0, 0.0), _rec("B", 3.0, 0.0)],
        2: [_rec("A", 5.0, 0.0), _rec("B", 7.0, 0.0)],
    }
    out = tp.two_way_bootstrap(grid, "X", "Y", "m", reps=2000, seed=7)
    assert out["delta"] == pytest.approx(4.0)
    assert (out["lo95"], out["hi95"]) == (pytest.approx(1.0), pytest.approx(7.0))
    assert (out["weeks"], out["teams"]) == (2, 2)


def test_two_way_bootstrap_identical_arms_and_constant_differences():
    same = {
        1: [_rec("A", 2.0, 2.0), _rec("B", 4.0, 4.0)],
        2: [_rec("A", 9.0, 9.0), _rec("B", 3.0, 3.0)],
    }
    out = tp.two_way_bootstrap(same, "X", "Y", "m", reps=500, seed=1)
    assert (out["delta"], out["lo95"], out["hi95"]) == (0.0, 0.0, 0.0)
    constant = {
        1: [_rec("A", 5.0, 3.0), _rec("B", 8.0, 6.0)],
        2: [_rec("A", 7.0, 5.0), _rec("B", 2.0, 0.0)],
    }
    out = tp.two_way_bootstrap(constant, "X", "Y", "m", reps=500, seed=1)
    assert out["delta"] == pytest.approx(2.0)
    assert out["lo95"] == pytest.approx(2.0) == out["hi95"]


def test_two_way_bootstrap_refuses_an_empty_cell():
    # The real grid is balanced; a hole would make some resamples 0/0, so it fails closed.
    with pytest.raises(tp.InsufficientEvidence, match="empty team-week cell"):
        tp.two_way_bootstrap(
            {1: [_rec("A", 1.0, 0.0)], 2: [_rec("A", 1.0, 0.0), _rec("B", 1.0, 0.0)]},
            "X",
            "Y",
            "m",
            reps=10,
            seed=1,
        )


def test_two_way_bootstrap_is_seeded():
    grid = {
        1: [_rec("A", 1.0, 0.0), _rec("B", 3.0, 0.0)],
        2: [_rec("A", 5.0, 0.0), _rec("B", 7.0, 0.0)],
    }
    first = tp.two_way_bootstrap(grid, "X", "Y", "m", reps=300, seed=9)
    assert first == tp.two_way_bootstrap(grid, "X", "Y", "m", reps=300, seed=9)


def test_weekly_mean_diffs_hand_values():
    grid = {1: [_rec("A", 4.0, 1.0), _rec("B", 6.0, 3.0)], 2: [_rec("A", 2.0, 3.0)]}
    assert tp.weekly_mean_diffs(grid, "X", "Y", "m") == {1: 3.0, 2: -1.0}


# ── dispersion repair ────────────────────────────────────────────────────────────────


def test_dispersion_scale_hand_value():
    realized = {
        2: {"A": 999.0, "B": 999.0},  # before first_week: must be ignored
        3: {"A": 110.0, "B": 90.0},
        4: {"A": 100.0, "B": 103.0},
    }
    raw = {
        2: {"A": (0.0, 1.0), "B": (0.0, 1.0)},
        3: {"A": (100.0, 10.0), "B": (100.0, 5.0)},
        4: {"A": (100.0, 10.0), "B": (100.0, 3.0)},
    }
    # z = 1, -2, 0, 1, so mean z² = (1 + 4 + 0 + 1) / 4 = 1.5.
    view = tp.RealizedView(realized, 5)
    assert tp.dispersion_scale(raw, view, first_week=3, min_rows=4) == pytest.approx(math.sqrt(1.5))
    assert tp.dispersion_scale(raw, view, first_week=3, min_rows=5) is None


def test_dispersion_scale_raises_on_the_target_week():
    realized = {3: {"A": 1.0}, 5: {"A": 2.0}}
    view = tp.RealizedView(realized, 5)
    with pytest.raises(tp.LeakageError):
        tp.dispersion_scale({3: {"A": (0.0, 1.0)}, 5: {"A": (0.0, 1.0)}}, view, min_rows=1)


def test_apply_dispersion_and_missing_scale():
    assert tp.apply_dispersion({"A": (100.0, 20.0)}, 1.5) == {"A": (100.0, 30.0)}
    assert tp.apply_dispersion({"A": (100.0, 20.0)}, None) == {"A": None}


# ── gates ────────────────────────────────────────────────────────────────────────────


def _summary(**over):
    base = {
        "crps": 29.5,
        "logLossBinary": 0.42,
        "brierBinary": 0.14,
        "mae": 43.0,
        "bias": -10.0,
        "zRms": 1.0,
        "coverage80": 0.80,
        "calibrationSlope": 1.0,
        "concordance": 0.80,
    }
    base.update(over)
    return base


def _tables(afco=None):
    summaries = {
        "I": _summary(
            crps=69.0,
            logLossBinary=0.675,
            brierBinary=0.169,
            mae=81.8,
            bias=55.9,
            zRms=4.5,
            coverage80=0.27,
            calibrationSlope=0.49,
            concordance=0.81,
        ),
        "B1": _summary(crps=30.2, logLossBinary=0.419, mae=42.0),
        "B2": _summary(crps=29.0, logLossBinary=0.423, mae=42.0),
        "AFCO": _summary(**(afco or {})),
        "CO": _summary(bias=69.0),
        "AF": _summary(calibrationSlope=0.5),
    }
    inference = {
        a: {"signFlipP": 1 / 32, "twoWayCrps": {"lo95": 10.0}} for a in tp.STUDY2_CHALLENGERS
    }
    sequence = tp.primary_sequence({a: inference[a]["signFlipP"] for a in tp.STUDY2_ELIGIBLE})
    return summaries, inference, sequence


def test_primary_sequence_is_fixed_and_stops_at_the_first_non_rejection():
    assert tp.primary_sequence({"AFCO": 1 / 32, "CO": 1 / 32}) == {
        "AFCO": tp.REJECTED,
        "CO": tp.REJECTED,
    }
    # CO's own p is minimal here, and it still may not be tested.
    assert tp.primary_sequence({"AFCO": 0.0625, "CO": 1 / 32}) == {
        "AFCO": tp.NOT_REJECTED,
        "CO": tp.NOT_TESTED,
    }


def test_the_gate_set_is_jointly_satisfiable():
    # Non-contradiction witness (§8).  Non-inferior to the best baseline on every metric,
    # in band everywhere, better than the incumbent: every gate passes.
    summaries, inference, sequence = _tables()
    verdict = tp.evaluate_study2_gates(summaries, inference, sequence, "AFCO")
    assert verdict["verdict"] == "PASSES_ALL_GATES", verdict
    assert verdict["eligible"] is True


def test_a_candidate_equal_to_the_best_baseline_is_not_blocked():
    # Strict inequality against a baseline was study one's flaw.  Exact equality passes here.
    summaries, inference, sequence = _tables(
        afco={"crps": 29.0, "logLossBinary": 0.419, "mae": 42.0}
    )
    verdict = tp.evaluate_study2_gates(summaries, inference, sequence, "AFCO")
    assert verdict["gates"]["SG6"] == "PASS"
    assert verdict["gates"]["SG3"] == "PASS"
    assert verdict["gates"]["SG2"] == "PASS"


def test_identical_baselines_cannot_block_anyone_and_the_old_rule_still_can():
    # The completed study's rule is untouched, and its flaw is exactly what this repairs.
    assert tp.best_baseline(
        {"B1": {"mae": 42.0}, "B2": {"mae": 42.0}, "I": {"mae": 90.0}}, "mae"
    ) == pytest.approx(42.0)
    summaries, inference, sequence = _tables()
    assert (
        tp.evaluate_study2_gates(summaries, inference, sequence, "AFCO")["gates"]["SG3"] == "PASS"
    )
    old_summaries = {
        "I": {
            "crps": 69.0,
            "logLossBinary": 0.675,
            "brierBinary": 0.169,
            "mae": 81.8,
            "bias": 55.9,
            "zRms": 4.5,
            "coverage80": 0.27,
            "concordance": 0.81,
        },
        **{
            b: {
                "crps": 29.0,
                "logLossBinary": 0.419,
                "brierBinary": 0.13,
                "mae": 42.0,
                "bias": -10.0,
                "zRms": 1.0,
                "coverage80": 0.80,
                "concordance": 0.80,
            }
            for b in ("B1", "B2")
        },
    }
    deltas = {"B1": {m: {"lo95": 1.0, "delta": 5.0, "hi95": 9.0} for m in ("crps", "ll", "abs")}}
    assert "TG3" in tp.evaluate_gates(old_summaries, deltas, "B1")["failed"]


def test_baselines_and_the_incumbent_are_never_candidates():
    summaries, inference, sequence = _tables()
    for arm in ("B1", "B2", "I"):
        with pytest.raises(ValueError):
            tp.evaluate_study2_gates(summaries, inference, sequence, arm)


@pytest.mark.parametrize(
    "change, gate",
    [
        ({"crps": 62.2}, "SG1"),  # 10% improvement needs CRPS <= 62.1
        ({"logLossBinary": 0.70}, "SG2"),
        ({"brierBinary": 0.20}, "SG2"),
        ({"logLossBinary": 0.45}, "SG2"),  # over 1.05 x 0.419
        ({"bias": -20.18}, "SG3"),  # the no-rounding case from study one
        ({"mae": 82.0}, "SG3"),
        ({"mae": 44.2}, "SG3"),  # over 1.05 x 42
        ({"zRms": 1.26}, "SG4"),
        ({"zRms": 0.79}, "SG4"),
        ({"coverage80": 0.93}, "SG4"),
        ({"coverage80": 0.67}, "SG4"),
        ({"calibrationSlope": 0.69}, "SG4"),
        ({"calibrationSlope": 1.41}, "SG4"),
        ({"calibrationSlope": None}, "SG4"),
        ({"concordance": 0.789}, "SG5"),  # below 0.81 - 0.02
        ({"crps": 30.46}, "SG6"),  # over 1.05 x 29.0
    ],
)
def test_each_gate_fails_alone(change, gate):
    summaries, inference, sequence = _tables(afco=change)
    verdict = tp.evaluate_study2_gates(summaries, inference, sequence, "AFCO")
    assert verdict["gates"][gate] == "FAIL", verdict
    assert verdict["verdict"] == "DOES_NOT_PASS"


@pytest.mark.parametrize(
    "change",
    [
        {"bias": 20.0},
        {"bias": -20.0},
        {"crps": 30.45},
        {"mae": 44.1},
        {"zRms": 1.25},
        {"zRms": 0.80},
    ],
)
def test_gate_boundaries_pass_on_unrounded_values(change):
    summaries, inference, sequence = _tables(afco=change)
    assert tp.evaluate_study2_gates(summaries, inference, sequence, "AFCO")["verdict"] == (
        "PASSES_ALL_GATES"
    )


def test_primary_gate_needs_both_the_sequence_and_the_two_way_interval():
    summaries, inference, _ = _tables()
    inference["AFCO"]["twoWayCrps"]["lo95"] = 0.0
    sequence = tp.primary_sequence({"AFCO": 1 / 32, "CO": 1 / 32})
    assert (
        tp.evaluate_study2_gates(summaries, inference, sequence, "AFCO")["gates"]["SG1"] == "FAIL"
    )
    inference["AFCO"]["twoWayCrps"]["lo95"] = 10.0
    blocked = {"AFCO": tp.NOT_REJECTED, "CO": tp.NOT_TESTED}
    assert tp.evaluate_study2_gates(summaries, inference, blocked, "CO")["gates"]["SG1"] == "FAIL"


def test_the_factorial_arm_reads_its_own_p_and_stays_ineligible():
    summaries, inference, sequence = _tables()
    verdict = tp.evaluate_study2_gates(summaries, inference, sequence, "AF")
    assert verdict["eligible"] is False
    assert verdict["gates"]["SG1"] == "PASS"  # own p, outside the sequence
    assert verdict["gates"]["SG4"] == "FAIL"  # slope 0.5 in the fixture


# ── decision rule ────────────────────────────────────────────────────────────────────


def _verdict(passes: bool, sg1: bool = True):
    failed = [] if passes else ([] if sg1 else ["SG1"]) + ["SG4"]
    return {
        "verdict": "PASSES_ALL_GATES" if passes else "DOES_NOT_PASS",
        "gates": {"SG1": "PASS" if (passes or sg1) else "FAIL"},
        "failed": failed,
    }


def test_decision_void_and_too_few_weeks_win_first():
    verdicts = {"AFCO": _verdict(True), "CO": _verdict(True)}
    assert (
        tp.decide_study2(verdicts, weeks_scored=5, void_reasons=["x"])["outcome"] == tp.OUTCOME_VOID
    )
    out = tp.decide_study2(verdicts, weeks_scored=4)
    assert (out["outcome"], out["reason"]) == (tp.OUTCOME_INCONCLUSIVE, "insufficient_weeks")


def test_decision_recommends_the_first_passing_arm_in_sequence():
    out = tp.decide_study2({"AFCO": _verdict(True), "CO": _verdict(True)}, weeks_scored=5)
    assert (out["outcome"], out["arm"]) == (tp.OUTCOME_PROMOTE, "AFCO")
    out = tp.decide_study2({"AFCO": _verdict(False), "CO": _verdict(True)}, weeks_scored=5)
    assert (out["outcome"], out["arm"]) == (tp.OUTCOME_PROMOTE, "CO")


def test_decision_beats_incumbent_but_fails_a_gate_is_inconclusive():
    out = tp.decide_study2(
        {"AFCO": _verdict(False, sg1=True), "CO": _verdict(False, sg1=False)}, weeks_scored=5
    )
    assert (out["outcome"], out["reason"]) == (
        tp.OUTCOME_INCONCLUSIVE,
        "beats_incumbent_fails_gate",
    )


def test_decision_no_superiority_is_retain():
    out = tp.decide_study2(
        {"AFCO": _verdict(False, sg1=False), "CO": _verdict(False, sg1=False)}, weeks_scored=5
    )
    assert out["outcome"] == tp.OUTCOME_RETAIN


def test_a_factorial_pass_never_changes_the_outcome():
    verdicts = {
        "AFCO": _verdict(False, sg1=False),
        "CO": _verdict(False, sg1=False),
        "AF": _verdict(True),
    }
    assert tp.decide_study2(verdicts, weeks_scored=5)["outcome"] == tp.OUTCOME_RETAIN


# ── binary playoff level ─────────────────────────────────────────────────────────────


def test_standings_hand_example_with_a_tie_at_the_median():
    realized = {1: {"A": 100.0, "B": 90.0, "C": 80.0, "D": 70.0}}
    pairs = {1: [("A", "B"), ("C", "D")]}
    # Median of the four is 85: A and B beat it.  A: 2 wins; B: 1; C: 1; D: 0.
    wins, pf = tp.standings_through(realized, pairs, statistics.median, [1])
    assert wins == {"A": 2.0, "B": 1.0, "C": 1.0, "D": 0.0}
    assert pf["A"] == 100.0
    # A team exactly on the threshold scores half a median win; a head-to-head tie is half each.
    tied = {1: {"A": 85.0, "B": 85.0}}
    wins, _ = tp.standings_through(tied, {1: [("A", "B")]}, statistics.median, [1])
    assert wins == {"A": 1.0, "B": 1.0}  # 0.5 median + 0.5 head-to-head each


def test_qualifiers_rank_by_wins_then_points_for():
    wins = {"A": 8.0, "B": 8.0, "C": 7.0}
    pf = {"A": 900.0, "B": 950.0, "C": 999.0}
    assert tp.qualifiers(wins, pf, 2) == ["B", "A"]
    # An exact tie on both at the cut has no recorded rule, so no outcome is invented.
    assert tp.qualifiers({"A": 8.0, "B": 8.0}, {"A": 900.0, "B": 900.0}, 1) is None


def test_qualification_probability_matches_the_closed_form():
    # A ~ N(110, 3), B ~ N(100, 4), one game, one seat: A qualifies with probability Φ(2).
    p = tp.qualification_probabilities(
        {"A": (110.0, 3.0), "B": (100.0, 4.0)},
        {"A": 0.0, "B": 0.0},
        {"A": 0.0, "B": 0.0},
        {14: [("A", "B")]},
        lambda _scores: 1e9,  # no one clears this median
        playoff_teams=1,
        draws=200_000,
        seed=3,
    )
    assert p["A"] == pytest.approx(0.9772498680518208, abs=0.002)
    assert p["A"] + p["B"] == pytest.approx(1.0)


def test_qualification_with_no_games_left_is_the_standings():
    p = tp.qualification_probabilities(
        {"A": (100.0, 10.0), "B": (100.0, 10.0)},
        {"A": 5.0, "B": 5.0},
        {"A": 700.0, "B": 650.0},
        {},
        statistics.median,
        playoff_teams=1,
        draws=100,
        seed=3,
    )
    assert p == {"A": 1.0, "B": 0.0}


def test_playoff_scores_hand_values():
    out = tp.playoff_scores({"A": 0.8, "B": 0.3, "C": 0.995}, ["A", "C"])
    assert out["teams"] == 3
    assert out["brier"] == pytest.approx((0.04 + 0.09 + 0.000025) / 3)
    assert out["logLoss"] == pytest.approx(-(math.log(0.8) + math.log(0.7) + math.log(0.995)) / 3)
    assert out["extremeProbabilities"] == 1
