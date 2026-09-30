"""Milestone B: the timing-only model is checked against brute force over
every ordering of the matchings (the declared distribution itself)."""

from __future__ import annotations

import itertools
import math
import random
import time
from fractions import Fraction

import pytest

from src.public_league.schedule_impact import WeekInput, comparison_credit
from src.public_league.schedule_timing import (
    MODEL_TIMING_ONLY,
    compute_timing_only,
    sample_finishes,
)


def _season(n_teams: int, n_weeks: int, seed: int, *, ties: bool = False) -> list[WeekInput]:
    rng = random.Random(seed)
    teams = [f"t{i}" for i in range(n_teams)]
    weeks = []
    for w in range(1, n_weeks + 1):
        order = teams[:]
        rng.shuffle(order)
        pairs = tuple((order[i], order[i + 1]) for i in range(0, n_teams, 2))
        if ties:
            scores = {t: float(rng.randint(90, 96)) for t in teams}
        else:
            scores = {t: round(rng.uniform(80, 150), 2) for t in teams}
        weeks.append(WeekInput(week=w, scores=scores, pairs=pairs))
    return weeks


def _matchings(weeks):
    return [dict([*wk.pairs, *[(b, a) for a, b in wk.pairs]]) for wk in weeks]


def _brute(weeks):
    teams = sorted({t for wk in weeks for p in wk.pairs for t in p})
    matchings = _matchings(weeks)
    dist = {t: {} for t in teams}
    for perm in itertools.permutations(range(len(weeks))):
        for t in teams:
            x = sum(
                comparison_credit(wk.scores[t], wk.scores[matchings[perm[w]][t]])
                for w, wk in enumerate(weeks)
            )
            dist[t][x] = dist[t].get(x, 0) + 1
    return dist


@pytest.mark.parametrize("seed,ties", [(1, False), (2, False), (3, True), (4, True)])
def test_exact_distribution_matches_brute_force(seed, ties):
    weeks = _season(6, 6, seed, ties=ties)
    out = compute_timing_only(weeks)
    assert out["state"] == "complete"
    assert out["model"]["id"] == MODEL_TIMING_ONLY
    assert out["totalCalendars"] == math.factorial(6)
    brute = _brute(weeks)
    for team, counts in brute.items():
        row = out["teams"][team]
        total = sum(counts.values())
        assert row["calendarsCounted"] == total
        got = {d["credits"]: d["probability"] for d in row["distribution"]}
        assert got.keys() == counts.keys()
        for x, c in counts.items():
            assert got[x] == pytest.approx(c / total, abs=1e-12)
        mean = sum(Fraction(x) * c for x, c in counts.items()) / total
        assert row["timingOnlyExpectedCredits"] == pytest.approx(float(mean), abs=1e-12)
        assert row["minCredits"] == min(counts) and row["maxCredits"] == max(counts)


def test_actual_calendar_is_one_of_the_counted_orderings():
    out = compute_timing_only(_season(8, 5, 7))
    for row in out["teams"].values():
        assert row["minCredits"] <= row["actualCredits"] <= row["maxCredits"]
        assert row["probEqualActual"] > 0
        assert row["probBelowActual"] + row["probEqualActual"] + row[
            "probAboveActual"
        ] == pytest.approx(1.0)
        assert row["timingOnlyImpact"] == pytest.approx(
            row["actualCredits"] - row["timingOnlyExpectedCredits"]
        )


def test_league_total_is_conserved():
    weeks = _season(10, 6, 11, ties=True)
    out = compute_timing_only(weeks)
    games = sum(len(wk.pairs) for wk in weeks)
    rows = out["teams"].values()
    assert sum(r["timingOnlyExpectedCredits"] for r in rows) == pytest.approx(games)
    assert sum(r["actualCredits"] for r in rows) == pytest.approx(games)
    assert sum(r["timingOnlyImpact"] for r in rows) == pytest.approx(0.0, abs=1e-9)


def test_same_matching_every_week_has_no_timing_effect():
    base = _season(4, 1, 3)[0]
    rng = random.Random(5)
    weeks = [
        WeekInput(week=w, scores={t: rng.uniform(80, 140) for t in base.scores}, pairs=base.pairs)
        for w in range(1, 6)
    ]
    for row in compute_timing_only(weeks)["teams"].values():
        assert row["minCredits"] == row["maxCredits"] == row["actualCredits"]
        assert row["timingOnlyImpact"] == pytest.approx(0.0)


def test_input_order_does_not_matter():
    weeks = _season(6, 5, 13)
    shuffled = weeks[:]
    random.Random(1).shuffle(shuffled)
    assert compute_timing_only(weeks)["teams"] == compute_timing_only(shuffled)["teams"]


def test_bye_is_reported_unavailable_not_mixed():
    weeks = _season(6, 3, 17)
    wk = weeks[0]
    bye_team = wk.pairs[0][0]
    weeks[0] = WeekInput(week=1, scores=wk.scores, pairs=wk.pairs[1:])
    out = compute_timing_only(weeks)
    assert out["teams"][bye_team]["state"] == "unavailable"
    assert out["teams"][bye_team]["reason"] == "bye_weeks_change_game_count"


def test_structural_problems_fail_closed():
    assert compute_timing_only([])["state"] == "unavailable"
    wk = WeekInput(week=1, scores={"a": 1.0, "b": 2.0, "c": 3.0}, pairs=(("a", "b"), ("a", "c")))
    assert compute_timing_only([wk])["reason"] == "multiple_games_per_week"
    wk = WeekInput(week=1, scores={"a": 1.0}, pairs=(("a", "b"),))
    assert compute_timing_only([wk])["reason"] == "missing_score"


def test_finish_sampler_is_seeded_and_normalized():
    weeks = _season(6, 5, 21)
    a = sample_finishes(weeks, samples=2000, seed=3)
    assert a == sample_finishes(weeks, samples=2000, seed=3)
    for row in a["teams"].values():
        assert sum(row["finishProbabilities"]) == pytest.approx(1.0, abs=1e-5)
        assert 1 <= row["expectedFinish"] <= 6
    for pos in range(6):
        assert sum(r["finishProbabilities"][pos] for r in a["teams"].values()) == pytest.approx(
            1.0, abs=1e-5
        )


def test_finish_sampler_agrees_with_exhaustive_enumeration():
    weeks = _season(4, 4, 29)
    samp = sample_finishes(weeks, samples=40000, seed=9)
    teams = sorted(samp["teams"])
    matchings = _matchings(weeks)
    pf = {t: sum(wk.scores[t] for wk in weeks) for t in teams}
    counts = {t: [0] * 4 for t in teams}
    perms = list(itertools.permutations(range(4)))
    for perm in perms:
        cred = dict.fromkeys(teams, 0.0)
        pa = dict.fromkeys(teams, 0.0)
        for w, wk in enumerate(weeks):
            for t, o in matchings[perm[w]].items():
                cred[t] += comparison_credit(wk.scores[t], wk.scores[o])
                pa[t] += wk.scores[o]
        for pos, t in enumerate(sorted(teams, key=lambda t: (-cred[t], -pf[t], pa[t]))):
            counts[t][pos] += 1
    for t in teams:
        for pos in range(4):
            exact = counts[t][pos] / len(perms)
            got = samp["teams"][t]["finishProbabilities"][pos]
            se = max(samp["teams"][t]["finishStandardErrors"][pos], 1e-3)
            assert abs(got - exact) <= 5 * se


def test_fourteen_week_season_is_exact_and_bounded():
    weeks = _season(12, 14, 31)
    t0 = time.perf_counter()
    out = compute_timing_only(weeks)
    elapsed = time.perf_counter() - t0
    assert out["state"] == "complete"
    for row in out["teams"].values():
        assert row["calendarsCounted"] == math.factorial(14)
    assert elapsed < 60
