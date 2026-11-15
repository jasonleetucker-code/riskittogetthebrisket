"""Team-level weekly points forecasts and their evaluation — RESEARCH ONLY.

Preregistration: ``docs/league-intelligence/TEAM_POINTS_CALIBRATION_PREREGISTRATION_2026-11-08.md``.

The best-ball playoff simulator forecasts each team's weekly score as a Normal
``(mean, sd)`` (``src/ros/playoff_sim.py::_TeamDist``).  This module holds the
pure half of the study that evaluates that forecast against simple baselines
and challengers:

* point-in-time views that RAISE when a forecast reads a realized week at or
  after the week it is forecasting (the leakage guard);
* the preregistered forecasters B0, B1, B2, A and S (§3);
* closed-form Normal scores (CRPS, head-to-head win probability), a Monte Carlo
  median-game probability, concordance, projected-PF and expected-wins errors;
* the team-cluster bootstrap and the gates TG1-TG5 (§4, §5).

A second study, preregistered 2026-11-09, adds its own gates, decision rule, exact
week-level test, two-way bootstrap and descriptive playoff-level scoring below; the
first study's rules are left as they were.

Nothing here does I/O, imports a production owner, or touches a served value.
The incumbent's numbers come from the production simulator, called by the study
script (``scripts/team_points_calibration_eval.py``); this module only scores
them.  MISSING IS NEVER ZERO: a forecaster that lacks the evidence its rule
needs returns ``None`` for that team, never a zero or a league average.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import numpy as np

#: The study's forecaster ids (preregistration §3).
INCUMBENT = "I"
REFERENCE = "B0"
BASELINES: tuple[str, ...] = ("B1", "B2")
CHALLENGERS: tuple[str, ...] = ("B1", "B2", "A", "S")
#: Fitted parameters per forecast (recommendation tie-break, §5).
PARAMETER_COUNT: dict[str, int] = {"A": 3, "S": 4, "B2": 13, "B1": 24}

#: Preregistered gate constants (§5, labelled PRIORs).
MAX_ABS_BIAS = 20.0
ZRMS_BAND = (0.80, 1.25)
COVERAGE80_BAND = (0.68, 0.92)
CONCORDANCE_SLACK = 0.02
CRPS_TIE = 1.0
PROB_CLIP = 1e-6

#: Minimum evidence per rule (§3).
B1_MIN_WEEKS = 2
A_MIN_ROWS = 12
S_MIN_ROWS = 24
S_FIRST_TRAIN_WEEK = 3

_SQRT2 = math.sqrt(2.0)
_INV_SQRT_PI = 1.0 / math.sqrt(math.pi)
_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


class LeakageError(RuntimeError):
    """A forecast for week ``k`` tried to read information from week ``>= k``."""


class InsufficientEvidence(RuntimeError):
    """A required forecast is missing; the evaluation refuses instead of scoring a gap."""


# ── point-in-time views ──────────────────────────────────────────────────────────────


class RealizedView:
    """Realized team-week scores visible to a forecast of ``target_week``.

    Only weeks STRICTLY before ``target_week`` are readable; anything else
    raises ``LeakageError``.  This is the structural no-look-ahead guard: a
    forecaster receives this object, never the raw mapping.
    """

    def __init__(self, realized: Mapping[int, Mapping[str, float]], target_week: int) -> None:
        self._data = realized
        self.target_week = int(target_week)

    def weeks(self) -> list[int]:
        return sorted(int(w) for w in self._data if int(w) < self.target_week)

    def score(self, week: int, team: str) -> float | None:
        if int(week) >= self.target_week:
            raise LeakageError(f"week {week} read while forecasting week {self.target_week}")
        value = (self._data.get(week) or {}).get(team)
        return None if value is None else float(value)

    def team_scores(self, team: str, *, before: int | None = None) -> list[float]:
        """The team's realized scores in week order, for weeks ``< before`` (default target)."""
        stop = self.target_week if before is None else int(before)
        if stop > self.target_week:
            raise LeakageError(
                f"scores before week {stop} read while forecasting {self.target_week}"
            )
        out = []
        for w in self.weeks():
            if w >= stop:
                break
            v = self.score(w, team)
            if v is not None:
                out.append(v)
        return out


class PresimView:
    """As-of presim means visible to a forecast of ``target_week``: weeks ``<= target_week``.

    A week-``j`` presim uses only week ``j``'s pre-kickoff snapshot and roster, so
    it is knowable at week ``j``; a later week's is not.
    """

    def __init__(self, presim: Mapping[int, Mapping[str, float]], target_week: int) -> None:
        self._data = presim
        self.target_week = int(target_week)

    def mean(self, week: int, team: str) -> float | None:
        if int(week) > self.target_week:
            raise LeakageError(f"presim week {week} read while forecasting week {self.target_week}")
        value = (self._data.get(week) or {}).get(team)
        return None if value is None else float(value)


# ── small numerics ───────────────────────────────────────────────────────────────────


def norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / _SQRT2))


def norm_pdf(z: float) -> float:
    return _INV_SQRT_2PI * math.exp(-0.5 * z * z)


def crps_normal(mu: float, sigma: float, y: float) -> float:
    """Closed-form CRPS of ``Normal(mu, sigma)`` at ``y`` (Gneiting & Raftery 2007)."""
    if not sigma > 0:
        raise ValueError("sigma must be positive")
    z = (y - mu) / sigma
    return sigma * (z * (2.0 * norm_cdf(z) - 1.0) + 2.0 * norm_pdf(z) - _INV_SQRT_PI)


def win_probability(mu_a: float, sd_a: float, mu_b: float, sd_b: float) -> float:
    """``P(A > B)`` for independent Normals — the simulator's own independence assumption."""
    scale = math.sqrt(sd_a * sd_a + sd_b * sd_b)
    if not scale > 0:
        raise ValueError("at least one sd must be positive")
    return norm_cdf((mu_a - mu_b) / scale)


def log_loss(p: float, y: float) -> float:
    p = min(1.0 - PROB_CLIP, max(PROB_CLIP, float(p)))
    return -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))


def outcome(a: float, b: float) -> float:
    """1 / 0.5 / 0 for a win / tie / loss of ``a`` against ``b``."""
    return 1.0 if a > b else 0.5 if a == b else 0.0


@dataclass(frozen=True)
class OlsFit:
    coef: tuple[float, ...]
    xtx_inv: tuple[tuple[float, ...], ...]
    s: float  # residual standard error
    n: int
    dof: int

    def predict(self, x0: Sequence[float]) -> tuple[float, float]:
        """``(mean, prediction sd)`` at ``x0`` (intercept included): ``s·√(1 + x₀ᵀ(XᵀX)⁻¹x₀)``."""
        x = np.asarray(x0, dtype=float)
        mean = float(np.dot(np.asarray(self.coef), x))
        lev = float(x @ np.asarray(self.xtx_inv) @ x)
        return mean, self.s * math.sqrt(1.0 + lev)


def ols(rows: Sequence[Sequence[float]], y: Sequence[float]) -> OlsFit | None:
    """OLS with an explicit design (first column = 1).  ``None`` when singular or no dof."""
    x = np.asarray(rows, dtype=float)
    yy = np.asarray(y, dtype=float)
    if x.ndim != 2 or x.shape[0] != yy.shape[0]:
        return None
    n, p = x.shape
    dof = n - p
    if dof < 1:
        return None
    xtx = x.T @ x
    if np.linalg.matrix_rank(xtx) < p:
        return None
    inv = np.linalg.inv(xtx)
    coef = inv @ x.T @ yy
    resid = yy - x @ coef
    s = math.sqrt(float(resid @ resid) / dof)
    return OlsFit(
        coef=tuple(float(c) for c in coef),
        xtx_inv=tuple(tuple(float(v) for v in r) for r in inv),
        s=s,
        n=n,
        dof=dof,
    )


# ── forecasters (§3) ─────────────────────────────────────────────────────────────────

Dist = tuple[float, float]


def forecast_b0(view: RealizedView, teams: Iterable[str]) -> dict[str, Dist | None]:
    """League climatology: every team gets the pooled mean and predictive sd."""
    teams = list(teams)
    pool = [x for t in teams for x in view.team_scores(t)]
    if len(pool) < 2:
        return {t: None for t in teams}
    mu = statistics.fmean(pool)
    sd = statistics.stdev(pool) * math.sqrt(1.0 + 1.0 / len(pool))
    return {t: (mu, sd) for t in teams}


def forecast_b1(view: RealizedView, teams: Iterable[str]) -> dict[str, Dist | None]:
    """Team trailing mean, team sample sd × √(1 + 1/n)."""
    out: dict[str, Dist | None] = {}
    for t in teams:
        xs = view.team_scores(t)
        if len(xs) < B1_MIN_WEEKS:
            out[t] = None
            continue
        sd = statistics.stdev(xs)
        out[t] = (statistics.fmean(xs), sd * math.sqrt(1.0 + 1.0 / len(xs))) if sd > 0 else None
    return out


def pooled_within_sd(groups: Iterable[Sequence[float]]) -> float | None:
    """``√(Σ_t Σ_j (y − ȳ_t)² / Σ_t (n_t − 1))``; ``None`` without dof."""
    ss = 0.0
    dof = 0
    for xs in groups:
        if len(xs) < 2:
            continue
        m = statistics.fmean(xs)
        ss += sum((x - m) ** 2 for x in xs)
        dof += len(xs) - 1
    if dof < 1 or ss <= 0:
        return None
    return math.sqrt(ss / dof)


def forecast_b2(view: RealizedView, teams: Iterable[str]) -> dict[str, Dist | None]:
    """Team trailing mean, league-pooled within-team sd × √(1 + 1/n_t)."""
    teams = list(teams)
    series = {t: view.team_scores(t) for t in teams}
    sp = pooled_within_sd(series.values())
    out: dict[str, Dist | None] = {}
    for t, xs in series.items():
        if sp is None or len(xs) < 1:
            out[t] = None
            continue
        out[t] = (statistics.fmean(xs), sp * math.sqrt(1.0 + 1.0 / len(xs)))
    return out


def _affine_rows(
    view: RealizedView, presim: PresimView, teams: Sequence[str], weeks: Iterable[int]
) -> tuple[list[list[float]], list[float]]:
    rows, ys = [], []
    for j in weeks:
        for t in teams:
            y = view.score(j, t)
            p = presim.mean(j, t)
            if y is None or p is None:
                continue
            rows.append([1.0, p])
            ys.append(y)
    return rows, ys


def forecast_affine(
    view: RealizedView, presim: PresimView, teams: Iterable[str]
) -> tuple[dict[str, Dist | None], OlsFit | None]:
    """A: ``y = α + β·P`` over every team-week before the target; OLS prediction sd."""
    teams = list(teams)
    k = view.target_week
    rows, ys = _affine_rows(view, presim, teams, view.weeks())
    fit = ols(rows, ys) if len(rows) >= A_MIN_ROWS else None
    out: dict[str, Dist | None] = {}
    for t in teams:
        p = presim.mean(k, t)
        out[t] = None if fit is None or p is None else fit.predict([1.0, p])
    return out, fit


def forecast_s(
    view: RealizedView, presim: PresimView, teams: Iterable[str]
) -> tuple[dict[str, Dist | None], OlsFit | None]:
    """S: ``y = α + β·P + γ·M`` over training weeks ``j ∈ [3, k−1]``; ``M`` = team mean of weeks ``< j``."""
    teams = list(teams)
    k = view.target_week
    rows, ys = [], []
    for j in view.weeks():
        if j < S_FIRST_TRAIN_WEEK:
            continue
        for t in teams:
            y = view.score(j, t)
            p = presim.mean(j, t)
            hist = view.team_scores(t, before=j)
            if y is None or p is None or not hist:
                continue
            rows.append([1.0, p, statistics.fmean(hist)])
            ys.append(y)
    fit = ols(rows, ys) if len(rows) >= S_MIN_ROWS else None
    out: dict[str, Dist | None] = {}
    for t in teams:
        p = presim.mean(k, t)
        hist = view.team_scores(t)
        if fit is None or p is None or not hist:
            out[t] = None
            continue
        out[t] = fit.predict([1.0, p, statistics.fmean(hist)])
    return out, fit


def candidate_forecasts(
    realized: Mapping[int, Mapping[str, float]],
    presim: Mapping[int, Mapping[str, float]],
    teams: Iterable[str],
    target_week: int,
) -> tuple[dict[str, dict[str, Dist | None]], dict[str, OlsFit | None]]:
    """B0, B1, B2, A and S for ``target_week``, each reading only point-in-time views."""
    teams = sorted(teams)
    view = RealizedView(realized, target_week)
    pview = PresimView(presim, target_week)
    a, fit_a = forecast_affine(view, pview, teams)
    s, fit_s = forecast_s(view, pview, teams)
    out = {
        "B0": forecast_b0(view, teams),
        "B1": forecast_b1(view, teams),
        "B2": forecast_b2(view, teams),
        "A": a,
        "S": s,
    }
    return out, {"A": fit_a, "S": fit_s}


# ── scoring records ──────────────────────────────────────────────────────────────────


def median_win_probabilities(
    dists: Mapping[str, Dist],
    threshold: Callable[[Sequence[float]], float],
    *,
    draws: int,
    seed: int,
) -> dict[str, float]:
    """P(team beats the week's league median) by Monte Carlo of independent Normals.

    ``threshold`` is the league's median rule (the study passes production
    ``game_day_sim.median_threshold``).  Ties score 0.5, as realized ties do.
    """
    teams = sorted(dists)
    rng = np.random.default_rng(seed)
    mus = np.array([dists[t][0] for t in teams])
    sds = np.array([dists[t][1] for t in teams])
    mat = rng.normal(mus, sds, size=(draws, len(teams)))
    wins = np.zeros(len(teams))
    for row in mat:
        thr = threshold(list(row))
        wins += np.where(row > thr, 1.0, np.where(row == thr, 0.5, 0.0))
    return {t: float(wins[i] / draws) for i, t in enumerate(teams)}


@dataclass(frozen=True)
class WeekInputs:
    """One target week: realized scores, head-to-head pairs and every arm's forecasts."""

    week: int
    realized: Mapping[str, float]
    pairs: Sequence[tuple[str, str]]
    forecasts: Mapping[str, Mapping[str, Dist]]  # arm -> team -> (mu, sd)


def require_complete(week: WeekInputs, arms: Iterable[str]) -> None:
    """Fail closed: every arm must forecast every realized team, with a finite mean and sd > 0."""
    for arm in arms:
        f = week.forecasts.get(arm)
        if f is None:
            raise InsufficientEvidence(f"arm {arm} has no forecasts for week {week.week}")
        for team in week.realized:
            d = f.get(team)
            if d is None:
                raise InsufficientEvidence(
                    f"arm {arm} has no forecast for {team} in week {week.week}"
                )
            mu, sd = d
            if not (math.isfinite(mu) and math.isfinite(sd) and sd > 0):
                raise InsufficientEvidence(
                    f"arm {arm} forecast for {team} wk{week.week} is invalid"
                )
    teams = set(week.realized)
    for a, b in week.pairs:
        if a not in teams or b not in teams:
            raise InsufficientEvidence(f"pair {a}-{b} in week {week.week} has no realized score")


@dataclass
class Record:
    """One scored outcome: a value per arm and the team clusters it belongs to (with weights)."""

    kind: str  # "team_week" | "h2h" | "median"
    clusters: tuple[tuple[str, float], ...]
    values: dict[str, dict[str, float]]  # arm -> metric -> value


def score_week(
    week: WeekInputs,
    arms: Sequence[str],
    threshold: Callable[[Sequence[float]], float],
    *,
    draws: int,
    seed: int,
) -> tuple[list[Record], dict[str, dict[str, float]]]:
    """Every record for one week, and the median-win probabilities per arm (reused by M7)."""
    require_complete(week, arms)
    recs: list[Record] = []
    median_p: dict[str, dict[str, float]] = {}
    for arm in arms:
        median_p[arm] = median_win_probabilities(
            {t: week.forecasts[arm][t] for t in week.realized}, threshold, draws=draws, seed=seed
        )
    real_thr = threshold([week.realized[t] for t in sorted(week.realized)])
    for team, y in sorted(week.realized.items()):
        vals: dict[str, dict[str, float]] = {}
        for arm in arms:
            mu, sd = week.forecasts[arm][team]
            z = (y - mu) / sd
            lo, hi = mu - 1.2815515655446004 * sd, mu + 1.2815515655446004 * sd
            vals[arm] = {
                "err": y - mu,
                "abs": abs(y - mu),
                "z2": z * z,
                "cov80": 1.0 if lo <= y <= hi else 0.0,
                "crps": crps_normal(mu, sd, y),
                "mu": mu,
                "sd": sd,
                "y": y,
            }
        recs.append(Record("team_week", ((team, 1.0),), vals))
        o = outcome(y, real_thr)
        mvals = {}
        for arm in arms:
            p = median_p[arm][team]
            mvals[arm] = {"ll": log_loss(p, o), "brier": (p - o) ** 2, "p": p, "y": o}
        recs.append(Record("median", ((team, 1.0),), mvals))
    for a, b in week.pairs:
        o = outcome(week.realized[a], week.realized[b])
        hvals = {}
        for arm in arms:
            ma, sa = week.forecasts[arm][a]
            mb, sb = week.forecasts[arm][b]
            p = win_probability(ma, sa, mb, sb)
            hvals[arm] = {"ll": log_loss(p, o), "brier": (p - o) ** 2, "p": p, "y": o}
        recs.append(Record("h2h", ((a, 0.5), (b, 0.5)), hvals))
    return recs, median_p


def concordance(mu: Mapping[str, float], y: Mapping[str, float]) -> tuple[float, int]:
    """(concordant share, pair count) over team pairs with distinct realized scores."""
    teams = sorted(y)
    good = 0.0
    n = 0
    for i, a in enumerate(teams):
        for b in teams[i + 1 :]:
            if y[a] == y[b]:
                continue
            n += 1
            dm = mu[a] - mu[b]
            if dm == 0:
                good += 0.5
            elif (dm > 0) == (y[a] > y[b]):
                good += 1.0
    return (good / n if n else float("nan")), n


def _mean(recs: Sequence[Record], arm: str, metric: str) -> float | None:
    vals = [r.values[arm][metric] for r in recs]
    return statistics.fmean(vals) if vals else None


def calibration_slope(mu: Sequence[float], y: Sequence[float]) -> float | None:
    n = len(mu)
    if n < 2:
        return None
    mm = statistics.fmean(mu)
    my = statistics.fmean(y)
    sxx = sum((m - mm) ** 2 for m in mu)
    if sxx <= 0:
        return None
    return sum((m - mm) * (v - my) for m, v in zip(mu, y)) / sxx


def summarize_arm(recs: Sequence[Record], weeks: Sequence[WeekInputs], arm: str) -> dict[str, Any]:
    """M1-M5 and M8 for one arm over the given records/weeks."""
    tw = [r for r in recs if r.kind == "team_week"]
    h2h = [r for r in recs if r.kind == "h2h"]
    med = [r for r in recs if r.kind == "median"]
    binary = h2h + med
    mu = [r.values[arm]["mu"] for r in tw]
    ys = [r.values[arm]["y"] for r in tw]
    conc_num = 0.0
    conc_n = 0
    for w in weeks:
        share, n = concordance({t: w.forecasts[arm][t][0] for t in w.realized}, w.realized)
        if n:
            conc_num += share * n
            conc_n += n
    per_team_mu: dict[str, list[float]] = {}
    per_team_y: dict[str, list[float]] = {}
    for r in tw:
        team = r.clusters[0][0]
        per_team_mu.setdefault(team, []).append(r.values[arm]["mu"])
        per_team_y.setdefault(team, []).append(r.values[arm]["y"])
    sd_mu = statistics.pstdev([statistics.fmean(v) for v in per_team_mu.values()])
    sd_y = statistics.pstdev([statistics.fmean(v) for v in per_team_y.values()])
    zr = _mean(tw, arm, "z2")
    zs = [r.values[arm]["err"] / r.values[arm]["sd"] for r in tw]
    return {
        "nTeamWeeks": len(tw),
        "nH2h": len(h2h),
        "nMedian": len(med),
        "bias": _mean(tw, arm, "err"),
        "mae": _mean(tw, arm, "abs"),
        "calibrationSlope": calibration_slope(mu, ys),
        "zRms": math.sqrt(zr) if zr is not None else None,
        # SD of standardized errors with their mean removed: the spread part of z-RMS
        # alone (z-RMS² = mean(z)² + zSd²), so a bias cannot read as a spread error.
        "zSd": statistics.pstdev(zs) if len(zs) > 1 else None,
        "zMean": statistics.fmean(zs) if zs else None,
        "coverage80": _mean(tw, arm, "cov80"),
        "crps": _mean(tw, arm, "crps"),
        "meanSd": _mean(tw, arm, "sd"),
        "concordance": conc_num / conc_n if conc_n else None,
        "concordancePairs": conc_n,
        "logLossBinary": _mean(binary, arm, "ll"),
        "brierBinary": _mean(binary, arm, "brier"),
        "logLossH2h": _mean(h2h, arm, "ll"),
        "logLossMedian": _mean(med, arm, "ll"),
        "brierH2h": _mean(h2h, arm, "brier"),
        "brierMedian": _mean(med, arm, "brier"),
        "betweenTeamSpreadRatio": (sd_mu / sd_y) if sd_y > 0 else None,
    }


# ── team-cluster bootstrap ───────────────────────────────────────────────────────────


def symmetric_interval(values: Sequence[float], level: float = 0.95) -> tuple[float, float]:
    """Percentile interval with the same count of values strictly outside on each side.

    ``k = floor((1 − level)/2 · n)``; ``lo`` is the (k+1)-th smallest and ``hi`` the
    (k+1)-th largest, so exactly ``k`` values lie below ``lo`` and ``k`` above ``hi``
    for any ``n``.
    """
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise InsufficientEvidence("no values for an interval")
    k = int((1.0 - level) / 2.0 * n)
    return ordered[k], ordered[n - 1 - k]


def paired_cluster_bootstrap(
    recs: Sequence[Record],
    arm_a: str,
    arm_b: str,
    metric: str,
    *,
    reps: int,
    seed: int,
) -> dict[str, float]:
    """Δ = mean(metric | arm_a) − mean(metric | arm_b), resampling TEAMS with replacement.

    A record attached to clusters ``((t, w), ...)`` contributes weight ``w`` to each
    drawn copy of ``t``; head-to-head games carry 0.5 per team so the full-sample
    weighted mean equals the plain mean.
    """
    sums: dict[str, float] = {}
    weights: dict[str, float] = {}
    for r in recs:
        d = r.values[arm_a][metric] - r.values[arm_b][metric]
        for team, w in r.clusters:
            sums[team] = sums.get(team, 0.0) + w * d
            weights[team] = weights.get(team, 0.0) + w
    teams = sorted(weights)
    if not teams:
        raise InsufficientEvidence("no records to bootstrap")
    s = np.array([sums[t] for t in teams])
    wv = np.array([weights[t] for t in teams])
    point = float(s.sum() / wv.sum())
    rng = random.Random(seed)
    stats_ = []
    for _ in range(reps):
        counts = np.zeros(len(teams))
        for _ in teams:
            counts[rng.randrange(len(teams))] += 1
        stats_.append(float((counts * s).sum() / (counts * wv).sum()))
    lo, hi = symmetric_interval(stats_)
    return {"delta": point, "lo95": lo, "hi95": hi, "reps": reps, "clusters": len(teams)}


# ── season-horizon descriptives (M6, M7) ─────────────────────────────────────────────


def horizon_errors(
    origin_forecasts: Mapping[int, Mapping[str, Dist]],
    origin_median_p: Mapping[int, Mapping[str, float]],
    realized: Mapping[int, Mapping[str, float]],
    pairs_by_week: Mapping[int, Sequence[tuple[str, str]]],
    threshold: Callable[[Sequence[float]], float],
    last_week: int,
) -> dict[str, Any]:
    """M6 projected-PF and M7 expected-wins errors for one arm.

    For each origin ``k``, the week-``k`` forecast is held constant over weeks
    ``k..last_week`` (as the simulator does).  Errors are realized − projected.
    """
    pf_err, win_err = [], []
    for k, dists in sorted(origin_forecasts.items()):
        horizon = list(range(k, last_week + 1))
        if any(w not in realized for w in horizon):
            raise InsufficientEvidence(f"horizon {k}..{last_week} has an unrealized week")
        for team, (mu, sd) in sorted(dists.items()):
            proj_pf = mu * len(horizon)
            real_pf = sum(realized[w][team] for w in horizon)
            pf_err.append(real_pf - proj_pf)
            exp_w = 0.0
            real_w = 0.0
            for w in horizon:
                thr = threshold([realized[w][t] for t in sorted(realized[w])])
                exp_w += origin_median_p[k][team]
                real_w += outcome(realized[w][team], thr)
                for a, b in pairs_by_week[w]:
                    if team not in (a, b):
                        continue
                    opp = b if team == a else a
                    om, osd = dists[opp]
                    exp_w += win_probability(mu, sd, om, osd)
                    real_w += outcome(realized[w][team], realized[w][opp])
            win_err.append(real_w - exp_w)
    return {
        "n": len(pf_err),
        "projectedPfMae": statistics.fmean(abs(e) for e in pf_err),
        "projectedPfBias": statistics.fmean(pf_err),
        "expectedWinsMae": statistics.fmean(abs(e) for e in win_err),
        "expectedWinsBias": statistics.fmean(win_err),
    }


# ── diagnosis: contributor effects ───────────────────────────────────────────────────

#: How far an arm is from calibrated, per metric family.  Level: |bias|, MAE.  Spread:
#: |between-team spread ratio − 1|, |calibration slope − 1|.
CONTRIBUTOR_ERRORS: dict[str, Callable[[Mapping[str, Any]], float]] = {
    "absBias": lambda s: abs(s["bias"]),
    "mae": lambda s: s["mae"],
    "spreadRatioError": lambda s: abs(s["betweenTeamSpreadRatio"] - 1.0),
    "slopeError": lambda s: abs(s["calibrationSlope"] - 1.0),
}


def rank_contributors(
    summaries: Mapping[str, Mapping[str, Any] | None],
    contributors: Sequence[tuple[str, str, str]],
) -> dict[str, Any]:
    """Effect of each contributor = error(arm WITH it) − error(arm WITHOUT it), per metric.

    ``contributors`` are ``(name, with_arm, without_arm)``.  A positive effect means the
    contributor adds that error.  Each effect is measured ALONE against its own
    comparison arm: no interaction or ordering check, so effects need not add up.
    Rankings are per metric, largest effect first; an effect that cannot be measured
    (an arm or metric is missing) is ``None`` and left out of the ranking.
    """
    effects = []
    for name, with_arm, without_arm in contributors:
        sw, so = summaries.get(with_arm), summaries.get(without_arm)
        row: dict[str, Any] = {"contributor": name, "with": with_arm, "without": without_arm}
        for metric, err in CONTRIBUTOR_ERRORS.items():
            try:
                row[metric] = err(sw) - err(so)  # type: ignore[arg-type]
            except (TypeError, KeyError):
                row[metric] = None
        effects.append(row)
    rankings = {
        metric: [
            r["contributor"]
            for r in sorted((r for r in effects if r[metric] is not None), key=lambda r: -r[metric])
        ]
        for metric in CONTRIBUTOR_ERRORS
    }
    return {
        "method": (
            "effect = error(with) - error(without); each measured alone against its own "
            "comparison arm, no interaction or ordering check"
        ),
        "effects": effects,
        "rankings": rankings,
    }


# ── gates (§5) ───────────────────────────────────────────────────────────────────────


def evaluate_gates(
    summaries: Mapping[str, Mapping[str, Any]],
    deltas: Mapping[str, Mapping[str, Mapping[str, float]]],
    challenger: str,
) -> dict[str, Any]:
    """TG1-TG5 for one challenger.

    ``summaries[arm]`` is ``summarize_arm`` output; ``deltas[challenger][metric]`` is
    the paired bootstrap of (incumbent − challenger) for ``crps``, ``ll`` and ``abs``.
    """
    s = summaries[challenger]
    inc = summaries[INCUMBENT]
    refs = [b for b in BASELINES if b != challenger]
    d = deltas[challenger]

    def beats_refs(metric: str) -> bool:
        return all(s[metric] < summaries[b][metric] for b in refs)

    tg1 = d["crps"]["lo95"] > 0 and beats_refs("crps")
    tg2 = (
        d["ll"]["lo95"] > 0
        and beats_refs("logLossBinary")
        and s["brierBinary"] <= inc["brierBinary"]
    )
    tg3 = abs(s["bias"]) <= MAX_ABS_BIAS and d["abs"]["lo95"] > 0 and beats_refs("mae")
    tg4 = (
        ZRMS_BAND[0] <= s["zRms"] <= ZRMS_BAND[1]
        and COVERAGE80_BAND[0] <= s["coverage80"] <= COVERAGE80_BAND[1]
    )
    tg5 = s["concordance"] >= inc["concordance"] - CONCORDANCE_SLACK
    gates = {"TG1": tg1, "TG2": tg2, "TG3": tg3, "TG4": tg4, "TG5": tg5}
    failed = [g for g, ok in gates.items() if not ok]
    return {
        "references": refs,
        "gates": {g: ("PASS" if ok else "FAIL") for g, ok in gates.items()},
        "failed": failed,
        "verdict": "PASSES_ALL_GATES" if not failed else "DOES_NOT_PASS",
    }


def recommend(
    summaries: Mapping[str, Mapping[str, Any]], verdicts: Mapping[str, Mapping[str, Any]]
) -> str | None:
    """The preregistered recommendation rule; ``None`` when no challenger passes."""
    passing = [c for c, v in verdicts.items() if v["verdict"] == "PASSES_ALL_GATES"]
    if not passing:
        return None
    best = min(summaries[c]["crps"] for c in passing)
    near = [c for c in passing if summaries[c]["crps"] - best <= CRPS_TIE]
    return min(near, key=lambda c: (PARAMETER_COUNT[c], summaries[c]["crps"]))


# ── study two: preregistered 2026-11-09 ──────────────────────────────────────────────
#
# Preregistration: ``docs/league-intelligence/TEAM_POINTS_STUDY2_PREREGISTRATION_2026-11-09.md``.
# Everything below is separate from study one: ``evaluate_gates`` and ``recommend`` above
# keep the completed study's rules, including its disclosed flaw.

#: The fixed test sequence (§7).  Order is the preregistration's and is part of the error control.
STUDY2_ELIGIBLE: tuple[str, ...] = ("AFCO", "CO")
#: The factorial arm.  Gates are computed and published; it can never earn a recommendation.
STUDY2_FACTORIAL: tuple[str, ...] = ("AF",)
STUDY2_CHALLENGERS: tuple[str, ...] = STUDY2_ELIGIBLE + STUDY2_FACTORIAL
#: References only (§8): best of these, per metric.  Never candidates, so never compared to themselves.
STUDY2_BASELINES: tuple[str, ...] = ("B1", "B2")
STUDY2_REQUIRED_WEEKS = 5

STUDY2_ALPHA = 0.05
NONINFERIORITY_MARGIN = 0.05
MIN_CRPS_IMPROVEMENT = 0.10
SLOPE_BAND = (0.70, 1.40)
DISPERSION_FIRST_WEEK = 3
DISPERSION_MIN_ROWS = 48
EXTREME_PROBABILITY = 0.01

OUTCOME_PROMOTE = "PROMOTE_RECOMMENDATION"
OUTCOME_RETAIN = "RETAIN"
OUTCOME_INCONCLUSIVE = "INCONCLUSIVE"
OUTCOME_VOID = "VOID"

REJECTED = "REJECTED"
NOT_REJECTED = "NOT_REJECTED"
NOT_TESTED = "NOT_TESTED"


def dispersion_scale(
    raw_by_week: Mapping[int, Mapping[str, Dist]],
    view: RealizedView,
    *,
    first_week: int = DISPERSION_FIRST_WEEK,
    min_rows: int = DISPERSION_MIN_ROWS,
) -> float | None:
    """``d_k = √(mean z²)`` over walk-forward forecasts of weeks ``[first_week, k−1]`` (§4).

    ``raw_by_week`` holds each week's own walk-forward ``(mu, raw sd)``, and every score is
    read through ``view``, so a week at or after the target raises ``LeakageError``.
    ``None`` below ``min_rows``: too little evidence, never a default of 1.
    """
    total = 0.0
    rows = 0
    for j in sorted(raw_by_week):
        if j < first_week:
            continue
        for team, (mu, sd) in sorted(raw_by_week[j].items()):
            y = view.score(j, team)
            if y is None:
                continue
            z = (y - mu) / sd
            total += z * z
            rows += 1
    if rows < min_rows or total <= 0:
        return None
    return math.sqrt(total / rows)


def apply_dispersion(raw: Mapping[str, Dist], scale: float | None) -> dict[str, Dist | None]:
    """Scale every sd by ``scale``; a missing scale leaves the arm with no forecast."""
    if scale is None:
        return {team: None for team in raw}
    return {team: (mu, sd * scale) for team, (mu, sd) in raw.items()}


def weekly_mean_diffs(
    recs_by_week: Mapping[int, Sequence[Record]], arm_a: str, arm_b: str, metric: str
) -> dict[int, float]:
    """Per week, mean(metric | arm_a) − mean(metric | arm_b) over the given records."""
    out: dict[int, float] = {}
    for week, recs in sorted(recs_by_week.items()):
        if not recs:
            raise InsufficientEvidence(f"week {week} has no records")
        out[week] = statistics.fmean(
            r.values[arm_a][metric] - r.values[arm_b][metric] for r in recs
        )
    return out


def exact_sign_flip_p(diffs: Sequence[float]) -> float:
    """One-sided exact sign-flip p: ``#{s : Σ s·D ≥ Σ D} / 2^W`` (§7).

    Float slack only (1e-9), so a tie on the sum counts as a tie.  With five weeks the
    smallest possible value is 1/32.
    """
    values = [float(x) for x in diffs]
    weeks = len(values)
    if weeks == 0:
        raise InsufficientEvidence("no weeks for a sign-flip test")
    if weeks > 20:
        raise ValueError("exact enumeration is limited to 20 weeks")
    observed = sum(values)
    hits = 0
    for mask in range(1 << weeks):
        flipped = sum(v if (mask >> i) & 1 else -v for i, v in enumerate(values))
        if flipped >= observed - 1e-9:
            hits += 1
    return hits / (1 << weeks)


def weekly_t_statistic(diffs: Sequence[float]) -> float | None:
    """Mean / (sd/√W) of the weekly differences.  Reported only (§7)."""
    values = [float(x) for x in diffs]
    if len(values) < 2:
        return None
    sd = statistics.stdev(values)
    if not sd > 0:
        return None
    return statistics.fmean(values) / (sd / math.sqrt(len(values)))


def two_way_bootstrap(
    recs_by_week: Mapping[int, Sequence[Record]],
    arm_a: str,
    arm_b: str,
    metric: str,
    *,
    reps: int,
    seed: int,
) -> dict[str, float]:
    """Pigeonhole bootstrap over teams and weeks (§7): both resampled, statistic on the product cells.

    A record's weight on team ``t`` is the same ``(t, w)`` as the team-cluster bootstrap,
    so the full-sample weighted mean equals the plain mean.
    """
    weeks = sorted(recs_by_week)
    teams = sorted({t for recs in recs_by_week.values() for r in recs for t, _ in r.clusters})
    if not weeks or not teams:
        raise InsufficientEvidence("no records to bootstrap")
    index = {t: i for i, t in enumerate(teams)}
    sums = np.zeros((len(weeks), len(teams)))
    weights = np.zeros((len(weeks), len(teams)))
    for i, week in enumerate(weeks):
        for r in recs_by_week[week]:
            d = r.values[arm_a][metric] - r.values[arm_b][metric]
            for team, w in r.clusters:
                sums[i, index[team]] += w * d
                weights[i, index[team]] += w
    if (weights <= 0).any():
        raise InsufficientEvidence("two-way grid has an empty team-week cell")
    point = float(sums.sum() / weights.sum())
    rng = random.Random(seed)
    stats_ = []
    for _ in range(reps):
        week_counts = np.zeros(len(weeks))
        for _ in weeks:
            week_counts[rng.randrange(len(weeks))] += 1
        team_counts = np.zeros(len(teams))
        for _ in teams:
            team_counts[rng.randrange(len(teams))] += 1
        stats_.append(
            float(week_counts @ sums @ team_counts / (week_counts @ weights @ team_counts))
        )
    lo, hi = symmetric_interval(stats_)
    return {
        "delta": point,
        "lo95": lo,
        "hi95": hi,
        "reps": reps,
        "weeks": len(weeks),
        "teams": len(teams),
    }


def primary_sequence(p_values: Mapping[str, float]) -> dict[str, str]:
    """Fixed-sequence gatekeeping over the eligible arms (§7).

    The second arm is tested only if the first rejects; otherwise it is ``NOT_TESTED``.
    """
    status: dict[str, str] = {}
    open_gate = True
    for arm in STUDY2_ELIGIBLE:
        if not open_gate:
            status[arm] = NOT_TESTED
            continue
        if p_values[arm] <= STUDY2_ALPHA:
            status[arm] = REJECTED
        else:
            status[arm] = NOT_REJECTED
            open_gate = False
    return status


def best_baseline(summaries: Mapping[str, Mapping[str, Any]], metric: str) -> float:
    """The best simple baseline on one metric (§8).  Identical baselines cannot block anyone."""
    return min(float(summaries[b][metric]) for b in STUDY2_BASELINES)


def evaluate_study2_gates(
    summaries: Mapping[str, Mapping[str, Any]],
    inference: Mapping[str, Mapping[str, Any]],
    sequence: Mapping[str, str],
    challenger: str,
) -> dict[str, Any]:
    """SG1-SG6 for one challenger (§8), on unrounded values.

    ``inference[arm]`` carries ``signFlipP`` and ``twoWayCrps`` (the bootstrap of
    incumbent − challenger).  An eligible arm's SG1(a) follows the sequence; the factorial
    arm is outside the family and reads its own p, as information only.
    """
    if challenger in STUDY2_BASELINES or challenger == INCUMBENT:
        raise ValueError(f"{challenger} is a reference in study two, never a candidate")
    s = summaries[challenger]
    inc = summaries[INCUMBENT]
    inf = inference[challenger]
    margin = 1.0 + NONINFERIORITY_MARGIN

    if challenger in STUDY2_ELIGIBLE:
        sg1a = sequence.get(challenger) == REJECTED
    else:
        sg1a = inf["signFlipP"] <= STUDY2_ALPHA
    delta = inc["crps"] - s["crps"]
    sg1 = sg1a and inf["twoWayCrps"]["lo95"] > 0 and delta >= MIN_CRPS_IMPROVEMENT * inc["crps"]
    sg2 = (
        s["logLossBinary"] < inc["logLossBinary"]
        and s["brierBinary"] <= inc["brierBinary"]
        and s["logLossBinary"] <= margin * best_baseline(summaries, "logLossBinary")
    )
    sg3 = (
        abs(s["bias"]) <= MAX_ABS_BIAS
        and s["mae"] < inc["mae"]
        and s["mae"] <= margin * best_baseline(summaries, "mae")
    )
    slope = s["calibrationSlope"]
    sg4 = (
        ZRMS_BAND[0] <= s["zRms"] <= ZRMS_BAND[1]
        and COVERAGE80_BAND[0] <= s["coverage80"] <= COVERAGE80_BAND[1]
        and slope is not None
        and SLOPE_BAND[0] <= slope <= SLOPE_BAND[1]
    )
    sg5 = s["concordance"] >= inc["concordance"] - CONCORDANCE_SLACK
    sg6 = s["crps"] <= margin * best_baseline(summaries, "crps")
    gates = {"SG1": sg1, "SG2": sg2, "SG3": sg3, "SG4": sg4, "SG5": sg5, "SG6": sg6}
    failed = [g for g, ok in gates.items() if not ok]
    return {
        "eligible": challenger in STUDY2_ELIGIBLE,
        "primary": sequence.get(challenger),
        "gates": {g: ("PASS" if ok else "FAIL") for g, ok in gates.items()},
        "failed": failed,
        "verdict": "PASSES_ALL_GATES" if not failed else "DOES_NOT_PASS",
    }


def decide_study2(
    verdicts: Mapping[str, Mapping[str, Any]],
    *,
    weeks_scored: int,
    void_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    """The preregistered decision rule (§9), applied in table order."""
    if void_reasons:
        return {"outcome": OUTCOME_VOID, "reasons": list(void_reasons)}
    if weeks_scored < STUDY2_REQUIRED_WEEKS:
        return {
            "outcome": OUTCOME_INCONCLUSIVE,
            "reason": "insufficient_weeks",
            "weeksScored": weeks_scored,
        }
    for arm in STUDY2_ELIGIBLE:
        if verdicts[arm]["verdict"] == "PASSES_ALL_GATES":
            return {"outcome": OUTCOME_PROMOTE, "arm": arm}
    if any(verdicts[arm]["gates"]["SG1"] == "PASS" for arm in STUDY2_ELIGIBLE):
        return {
            "outcome": OUTCOME_INCONCLUSIVE,
            "reason": "beats_incumbent_fails_gate",
            "failed": {arm: list(verdicts[arm]["failed"]) for arm in STUDY2_ELIGIBLE},
        }
    return {
        "outcome": OUTCOME_RETAIN,
        "reason": "no_eligible_arm_demonstrated_superiority",
        "failed": {arm: list(verdicts[arm]["failed"]) for arm in STUDY2_ELIGIBLE},
    }


# ── binary playoff level (descriptive, §6) ───────────────────────────────────────────


def standings_through(
    realized: Mapping[int, Mapping[str, float]],
    pairs_by_week: Mapping[int, Sequence[tuple[str, str]]],
    threshold: Callable[[Sequence[float]], float],
    weeks: Iterable[int],
) -> tuple[dict[str, float], dict[str, float]]:
    """``(wins, points for)`` over realized ``weeks``: head-to-head plus median game, ties ½."""
    weeks = sorted(weeks)
    wins: dict[str, float] = {}
    pf: dict[str, float] = {}
    for w in weeks:
        for team in realized[w]:
            wins.setdefault(team, 0.0)
            pf.setdefault(team, 0.0)
        thr = threshold([realized[w][t] for t in sorted(realized[w])])
        for team, score in realized[w].items():
            wins[team] += outcome(score, thr)
            pf[team] += score
        for a, b in pairs_by_week[w]:
            result = outcome(realized[w][a], realized[w][b])
            wins[a] += result
            wins[b] += 1.0 - result
    return wins, pf


def qualifiers(
    wins: Mapping[str, float], pf: Mapping[str, float], playoff_teams: int
) -> list[str] | None:
    """The top ``playoff_teams`` by (wins, points for).  ``None`` if the cut is an exact tie."""
    ranked = sorted(wins, key=lambda t: (-wins[t], -pf[t], t))
    if len(ranked) > playoff_teams:
        last_in, first_out = ranked[playoff_teams - 1], ranked[playoff_teams]
        if wins[last_in] == wins[first_out] and pf[last_in] == pf[first_out]:
            return None
    return ranked[:playoff_teams]


def qualification_probabilities(
    dists: Mapping[str, Dist],
    wins_to_date: Mapping[str, float],
    pf_to_date: Mapping[str, float],
    schedule: Mapping[int, Sequence[tuple[str, str]]],
    threshold: Callable[[Sequence[float]], float],
    *,
    playoff_teams: int,
    draws: int,
    seed: int,
) -> dict[str, float]:
    """P(qualify) from a record to date, each ``(mu, sd)`` held constant over ``schedule`` (§6).

    Scores are drawn ``max(0, Normal)``, as the simulator draws them.  An exact tie on wins
    and points for at the cut is broken by a seeded coin.
    """
    teams = sorted(dists)
    index = {t: i for i, t in enumerate(teams)}
    rng = np.random.default_rng(seed)
    mus = np.array([dists[t][0] for t in teams])
    sds = np.array([dists[t][1] for t in teams])
    wins = np.tile(np.array([float(wins_to_date.get(t, 0.0)) for t in teams]), (draws, 1))
    pf = np.tile(np.array([float(pf_to_date.get(t, 0.0)) for t in teams]), (draws, 1))
    for week in sorted(schedule):
        scores = np.maximum(0.0, rng.normal(mus, sds, size=(draws, len(teams))))
        thresholds = np.array([threshold(list(row)) for row in scores])
        wins += np.where(
            scores > thresholds[:, None], 1.0, np.where(scores == thresholds[:, None], 0.5, 0.0)
        )
        for a, b in schedule[week]:
            ia, ib = index[a], index[b]
            win_a = np.where(
                scores[:, ia] > scores[:, ib],
                1.0,
                np.where(scores[:, ia] == scores[:, ib], 0.5, 0.0),
            )
            wins[:, ia] += win_a
            wins[:, ib] += 1.0 - win_a
        pf += scores
    order = np.lexsort((rng.random(size=wins.shape), pf, wins), axis=1)
    counts = np.zeros(len(teams))
    for row in order[:, -playoff_teams:]:
        counts[row] += 1
    return {t: float(counts[index[t]] / draws) for t in teams}


def playoff_scores(
    probabilities: Mapping[str, float], qualified: Iterable[str]
) -> dict[str, float | int]:
    """Brier and log loss of P(qualify), and how many probabilities sit at or beyond 1% / 99%."""
    made = set(qualified)
    brier, ll, extreme = [], [], 0
    for team, p in sorted(probabilities.items()):
        y = 1.0 if team in made else 0.0
        brier.append((p - y) ** 2)
        ll.append(log_loss(p, y))
        extreme += int(p <= EXTREME_PROBABILITY or p >= 1.0 - EXTREME_PROBABILITY)
    return {
        "teams": len(brier),
        "brier": statistics.fmean(brier),
        "logLoss": statistics.fmean(ll),
        "extremeProbabilities": extreme,
    }


__all__ = [
    "BASELINES",
    "CHALLENGERS",
    "INCUMBENT",
    "InsufficientEvidence",
    "LeakageError",
    "OUTCOME_INCONCLUSIVE",
    "OUTCOME_PROMOTE",
    "OUTCOME_RETAIN",
    "OUTCOME_VOID",
    "OlsFit",
    "PresimView",
    "RealizedView",
    "Record",
    "STUDY2_BASELINES",
    "STUDY2_CHALLENGERS",
    "STUDY2_ELIGIBLE",
    "STUDY2_FACTORIAL",
    "WeekInputs",
    "apply_dispersion",
    "best_baseline",
    "calibration_slope",
    "candidate_forecasts",
    "concordance",
    "crps_normal",
    "decide_study2",
    "dispersion_scale",
    "evaluate_gates",
    "evaluate_study2_gates",
    "exact_sign_flip_p",
    "forecast_affine",
    "forecast_b0",
    "forecast_b1",
    "forecast_b2",
    "forecast_s",
    "horizon_errors",
    "log_loss",
    "median_win_probabilities",
    "ols",
    "outcome",
    "paired_cluster_bootstrap",
    "playoff_scores",
    "pooled_within_sd",
    "primary_sequence",
    "qualification_probabilities",
    "qualifiers",
    "rank_contributors",
    "recommend",
    "require_complete",
    "score_week",
    "standings_through",
    "summarize_arm",
    "symmetric_interval",
    "two_way_bootstrap",
    "weekly_mean_diffs",
    "weekly_t_statistic",
    "win_probability",
]
