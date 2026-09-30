"""Schedule Intelligence, Milestone B — the timing-only model (``timing_only_v1``).

Question: with every team's weekly scores FIXED and every actual weekly
pairing KEPT, how would the season have gone if those same pairings had
fallen in different weeks?

Model ``timing_only_v1`` (declared, see docs/SCHEDULE_INTELLIGENCE_SPEC.md):

* **fixed** -- every team-week score, points for, median results, and the
  set of weekly matchings actually played (so each team's opponent mix,
  divisions, repeat opponents and byes are exactly the real ones);
* **varies** -- which finalized week each matching is played in;
* **distribution** -- uniform over all W! orderings of the W finalized
  weeks' matchings (season-to-date: only finalized weeks are permuted; the
  unplayed remainder is not modelled and no future score is invented);
* **not** -- a forecast, a league-valid *different-opponent* model, or a
  schedule to adopt (X-01).

Exact results, no sampling:

* expected H2H credits: ``E[X_i] = (1/W) sum_w sum_k c(s_iw, s_{opp_k(i), w})``
  where ``opp_k(i)`` is i's opponent in the matching played in week k;
* the full per-team distribution of H2H credits, by dynamic programming over
  the subset of matchings already placed (exact integer counts over W!).

League-wide finishing positions need joint calendars, so they are estimated
by sampling uniform random permutations (Fisher-Yates -- the sampler IS the
declared distribution), with a seed and a reported Monte Carlo error.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from fractions import Fraction
from typing import Any

import numpy as np

from .schedule_impact import (
    STATE_COMPLETE,
    STATE_UNAVAILABLE,
    STATE_UNSUPPORTED,
    WeekInput,
    comparison_credit,
)

MODEL_TIMING_ONLY = "timing_only_v1"
ALGORITHM_VERSION = "schedule-timing-2026.09-b1"
#: Exact per-team distributions are computed up to this many permuted weeks
#: (2^W DP states); beyond it the distribution is reported unavailable, not
#: approximated.  A regular season is 13-14 weeks.
MAX_EXACT_WEEKS = 18

TIMING_MODEL = {
    "id": MODEL_TIMING_ONLY,
    "baseline": "timing-only",
    "fixed": [
        "every team's weekly score",
        "median / league-average game results",
        "every weekly pairing actually played (opponent mix, divisions, repeats, byes)",
    ],
    "varies": ["which finalized week each weekly pairing is played in"],
    "distribution": "every ordering of the finalized weeks' pairings is equally likely",
    "method": "exact (per-team distributions); uniform permutation sampling (league-wide finishes)",
    "notA": ["forecast", "different-opponent model", "schedule to adopt"],
}


def _pairings(week: WeekInput) -> dict[str, str]:
    out: dict[str, str] = {}
    for a, b in week.pairs:
        out[a] = b
        out[b] = a
    return out


def _validate(weeks: Sequence[WeekInput]) -> str | None:
    """A reason this model cannot be applied, or None."""
    for wk in weeks:
        seen: dict[str, int] = {}
        for a, b in wk.pairs:
            if a == b:
                return "self_matchup"
            for t in (a, b):
                seen[t] = seen.get(t, 0) + 1
                if t not in wk.scores:
                    return "missing_score"
        if any(n > 1 for n in seen.values()):
            return "multiple_games_per_week"
        if getattr(wk, "structural_issues", ()):
            return "structural_issues"
    return None


def _credit_matrix(
    team: str, weeks: Sequence[WeekInput], pairings: list[dict[str, str]]
) -> list[list[float | None]]:
    """A[w][k]: team's H2H credit if week k's matching is played in week w
    (scores from week w).  None when the team has no game in matching k."""
    rows: list[list[float | None]] = []
    for w, wk in enumerate(weeks):
        row: list[float | None] = []
        for k in range(len(weeks)):
            opp = pairings[k].get(team)
            if opp is None or team not in wk.scores or opp not in wk.scores:
                row.append(None)
            else:
                row.append(comparison_credit(float(wk.scores[team]), float(wk.scores[opp])))
        rows.append(row)
    return rows


def _exact_distribution(matrix: list[list[float | None]]) -> dict[int, int] | None:
    """Counts of permutations by total credit in HALF-credit units.

    DP over masks of placed matchings, processing weeks in order: state
    (mask) -> vector of counts indexed by half-credits.  None when a
    matching without a game for this team would change the game count
    (byes): that case is reported unavailable rather than mixed."""
    W = len(matrix)
    if any(v is None for row in matrix for v in row):
        return None
    half = [[int(round(2 * v)) for v in row] for row in matrix]
    size = 2 * W + 1
    dp: dict[int, np.ndarray] = {0: np.zeros(size, dtype=np.int64)}
    dp[0][0] = 1
    for w in range(W):
        nxt: dict[int, np.ndarray] = {}
        for mask, vec in dp.items():
            for k in range(W):
                if mask >> k & 1:
                    continue
                shift = half[w][k]
                nm = mask | (1 << k)
                tgt = nxt.get(nm)
                if tgt is None:
                    tgt = np.zeros(size, dtype=np.int64)
                    nxt[nm] = tgt
                if shift:
                    tgt[shift:] += vec[: size - shift]
                else:
                    tgt += vec
        dp = nxt
    (final,) = dp.values()
    return {i: int(c) for i, c in enumerate(final) if c}


def _summarize(counts: dict[int, int], actual_half: int) -> dict[str, Any]:
    total = sum(counts.values())
    pmf = {i / 2: Fraction(c, total) for i, c in sorted(counts.items())}
    lower = sum((p for x, p in pmf.items() if x * 2 < actual_half), Fraction(0))
    equal = pmf.get(actual_half / 2, Fraction(0))
    upper = sum((p for x, p in pmf.items() if x * 2 > actual_half), Fraction(0))
    # Central 80% interval: smallest/largest credit values leaving at most
    # 10% in each tail.
    cum = Fraction(0)
    lo = hi = None
    for x, p in pmf.items():
        cum += p
        if lo is None and cum > Fraction(1, 10):
            lo = x
        if hi is None and cum >= Fraction(9, 10):
            hi = x
    mean = sum((x * p for x, p in pmf.items()), Fraction(0))
    return {
        "calendarsCounted": total,
        "distribution": [{"credits": x, "probability": float(p)} for x, p in pmf.items()],
        "expectedCredits": float(mean),
        # Tail direction is explicit: "atOrBelowActual" = share of orderings
        # where the same scores earn no more than the actual credits.
        "probBelowActual": float(lower),
        "probEqualActual": float(equal),
        "probAboveActual": float(upper),
        "probAtOrBelowActual": float(lower + equal),
        "central80": {"low": lo, "high": hi},
        "minCredits": min(pmf),
        "maxCredits": max(pmf),
        "extremaAreExact": True,
    }


def compute_timing_only(weeks: Sequence[WeekInput]) -> dict[str, Any]:
    """Exact per-team timing-only results for the given finalized weeks."""
    ordered = sorted(weeks, key=lambda w: w.week)
    if not ordered:
        return {"state": STATE_UNAVAILABLE, "reason": "no_finalized_weeks", "teams": {}}
    reason = _validate(ordered)
    if reason:
        return {"state": STATE_UNSUPPORTED, "reason": reason, "teams": {}}
    if len(ordered) > MAX_EXACT_WEEKS:
        return {"state": STATE_UNSUPPORTED, "reason": "too_many_weeks_for_exact", "teams": {}}
    pairings = [_pairings(w) for w in ordered]
    teams = sorted({t for p in pairings for t in p})
    out: dict[str, Any] = {}
    for team in teams:
        matrix = _credit_matrix(team, ordered, pairings)
        actual = sum(
            comparison_credit(float(wk.scores[team]), float(wk.scores[pairings[w][team]]))
            for w, wk in enumerate(ordered)
            if team in pairings[w]
        )
        counts = _exact_distribution(matrix)
        if counts is None:
            out[team] = {
                "state": "unavailable",
                "reason": "bye_weeks_change_game_count",
                "actualCredits": actual,
            }
            continue
        W = len(ordered)
        expected = sum(v for row in matrix for v in row) / W
        summary = _summarize(counts, int(round(2 * actual)))
        # The DP mean and the closed form must agree; a disagreement is a
        # defect in this module, never something to publish.
        if not math.isclose(summary["expectedCredits"], expected, abs_tol=1e-9):
            raise RuntimeError(f"timing-only mean mismatch for {team}")
        out[team] = {
            "state": "complete",
            "actualCredits": actual,
            "timingOnlyExpectedCredits": expected,
            "timingOnlyImpact": actual - expected,
            **summary,
        }
    return {
        "state": STATE_COMPLETE,
        "model": TIMING_MODEL,
        "algorithmVersion": ALGORITHM_VERSION,
        "permutedWeeks": [w.week for w in ordered],
        "totalCalendars": math.factorial(len(ordered)),
        "teams": out,
    }


def sample_finishes(
    weeks: Sequence[WeekInput],
    *,
    other_credits: Mapping[str, float] | None = None,
    samples: int = 20000,
    seed: int = 20260930,
) -> dict[str, Any]:
    """League-wide finishing-position distribution under ``timing_only_v1``.

    Each sample is a uniform random ordering of the matchings (the declared
    distribution itself -- no approximation in the sampler).  Standings order:
    total credits (H2H under the ordering + ``other_credits``, e.g. verified
    median results, which timing cannot change), then points for (fixed),
    then points against (recomputed per ordering, lower first).  Teams still
    tied after those share the tied positions equally (reported as
    ``unresolvedTieShare``) -- no host tiebreak is invented.
    """
    ordered = sorted(weeks, key=lambda w: w.week)
    reason = _validate(ordered) if ordered else "no_finalized_weeks"
    if reason:
        return {"state": STATE_UNSUPPORTED if ordered else STATE_UNAVAILABLE, "reason": reason}
    pairings = [_pairings(w) for w in ordered]
    teams = sorted({t for p in pairings for t in p})
    idx = {t: i for i, t in enumerate(teams)}
    n, W = len(teams), len(ordered)
    extra = np.array([float((other_credits or {}).get(t, 0.0)) for t in teams])
    pf = np.zeros(n)
    for wk in ordered:
        for t in teams:
            if t in wk.scores:
                pf[idx[t]] += float(wk.scores[t])
    rng = random.Random(seed)
    pos_counts = np.zeros((n, n))
    unresolved = np.zeros(n)
    order = list(range(W))
    for _ in range(samples):
        rng.shuffle(order)  # week w plays matching order[w]
        cred = extra.copy()
        pa = np.zeros(n)
        for w, wk in enumerate(ordered):
            m = pairings[order[w]]
            for t, o in m.items():
                i = idx[t]
                cred[i] += comparison_credit(float(wk.scores[t]), float(wk.scores[o]))
                pa[i] += float(wk.scores[o])
        keys = sorted(range(n), key=lambda i: (-cred[i], -pf[i], pa[i]))
        p = 0
        while p < n:
            q = p
            while q + 1 < n and (cred[keys[q + 1]], pf[keys[q + 1]], pa[keys[q + 1]]) == (
                cred[keys[p]],
                pf[keys[p]],
                pa[keys[p]],
            ):
                q += 1
            share = 1.0 / (q - p + 1)
            for i in keys[p : q + 1]:
                for pos in range(p, q + 1):
                    pos_counts[i, pos] += share
                if q > p:
                    unresolved[i] += 1
            p = q + 1
    probs = pos_counts / samples
    # Standard error of each position probability (binomial approximation).
    se = np.sqrt(probs * (1 - probs) / samples)
    return {
        "state": STATE_COMPLETE,
        "method": "uniform_permutation_sampling",
        "samples": samples,
        "seed": seed,
        "tieOrder": ["total credits", "points for", "points against (lower first)"],
        "teams": {
            t: {
                "finishProbabilities": [round(float(x), 6) for x in probs[idx[t]]],
                "finishStandardErrors": [round(float(x), 6) for x in se[idx[t]]],
                "expectedFinish": round(
                    float(sum((k + 1) * probs[idx[t], k] for k in range(n))), 4
                ),
                "unresolvedTieShare": round(float(unresolved[idx[t]] / samples), 6),
            }
            for t in teams
        },
    }
