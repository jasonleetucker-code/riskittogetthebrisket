"""Preregistered v3 study: an as-of, prediction-error-calibrated challenger to the sim's fallback points model.

Research and shadow only. The preregistration is
``docs/league-intelligence/SIM_CALIBRATION_V3_PREREGISTRATION_2026-10-27.md``, committed alone (commit
``c52ff4d7f``) before this file existed and before any v3 number was computed. This script implements it.

Nothing in ``src/`` or ``server.py`` imports this file, and it modifies no owner module. The challenger is a
RESEARCH SUBCLASS of ``PointsModel`` that production's ``playoff_sim._bestball_weekly_score`` runs unmodified.
Every write goes through v1's ``assert_safe_output`` (refuses ``data/league_intel/`` and the served file name).

V3, per evaluated week ``h``, fitted on 2026 weeks ``1..h-1`` only, each with its own as-of snapshot:

* re-anchored rosValue ``r~ = r / mean_r(family, week)`` (snapshot drift is a family-wide level step);
* a FORWARD per-family mean fit, points on ``r~`` with intercept (the conditional-mean direction, not v2's
  inverted rosValue-on-points fit);
* a total CV per family chosen by out-of-sample (prequential) censored log score — prediction error, not
  within-player spread;
* league-week and roster-week multiplicative shocks from the prequential residuals' cross-products;
* a censoring-corrected location so the censored draw's mean equals the predicted mean.

Subcommands::

    python scripts/sim_calibration_v3_study.py evaluate [--offline]     # gates, metrics, C2-a
    python scripts/sim_calibration_v3_study.py downstream               # C2-b (network) + C2-c

Exit codes: 0 when the run completed (whatever the verdict), 2 when it refused, 1 on an unexpected error.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import random
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import sim_calibration_study as v1  # noqa: E402
from scripts import sim_calibration_v2_study as v2  # noqa: E402
from src.league_intel import sim_calibration as sc  # noqa: E402
from src.ros import playoff_sim  # noqa: E402
from src.ros.lineup import lineup_position  # noqa: E402

# ── preregistered constants (change only with a dated addendum to the v3 preregistration) ───────

PREREGISTRATION = "docs/league-intelligence/SIM_CALIBRATION_V3_PREREGISTRATION_2026-10-27.md"
PREREGISTRATION_COMMIT = "c52ff4d7f0b41e27a6422f25ad4b661d8d145f1f"

SEASON = v1.SEASON
PRIMARY_WEEKS: tuple[int, ...] = (7,)
DEV_WEEKS: tuple[int, ...] = (5, 6)
CONFIRM_WEEK = 8

V2_CHALLENGER = (
    REPO / "docs" / "league-intelligence" / "evidence" / "sim_calibration_v2" / v2.CHALLENGER_NAME
)
V2_CHALLENGER_SHA256 = "b7826d44c73a1a974b10c5562822648879e97cec737f1b6792d016ba577ceceb"

OUT_DIR = REPO / "docs" / "league-intelligence" / "evidence" / "sim_calibration_v3"
EVAL_NAME = "evaluation_v3.json"
DOWNSTREAM_NAME = "downstream_c2.json"
FRESH_GAMES_CACHE = v1.CACHE_DIR / "nflverse" / "schedules__games__v3_20261027.csv"

#: A STRING schema version: ``load_points_model`` treats it as a mismatch and serves the fallback.
CHALLENGER_SCHEMA = "research-sim-points-v3"

FLOOR = sc.MIN_SAMPLES_PER_POSITION  # 30
CV_LO, CV_HI = sc.CV_CLAMP
CV_STEP = 0.005
SIGMA_FLOOR = 0.5

V3, V3_NOANCHOR, V3_NOSHOCK, V3_ASOF = "V3", "V3-noAnchor", "V3-noShock", "V3-asofAnchor"
F, V2N, FSTAR = "F", "V2", "F*"
PLAYER_MODELS = (V3, V3_NOANCHOR, V3_ASOF, V2N, F)
TEAM_MODELS = (V3, V3_NOANCHOR, V3_NOSHOCK, V3_ASOF, V2N, F)

G6_BIAS_BAND = (-30.0, 30.0)
G9_RATIO_BAND = (0.80, 1.25)
BRIER_COIN = 0.25
PROB_CLIP = 1e-6


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(REPO).as_posix() if REPO in p.parents else p.as_posix()


def _seed(*parts: Any) -> int:
    return int(
        hashlib.sha256(":".join(str(x) for x in (v1.SEED, *parts)).encode()).hexdigest()[:12], 16
    )


# ── observations ───────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Obs:
    """One appeared, priced 2026 player-week from the production join (``y`` is host-native points)."""

    week: int
    rid: int
    pid: str
    position: str  # raw directory position (what the sim's draw is asked)
    family: str
    r: float  # as-of rosValue
    y: float


def anchors(rows: Iterable[Obs]) -> dict[tuple[int, str], float]:
    """§3.1: ``{(week, family): mean as-of rosValue over that week's pool}``."""
    acc: dict[tuple[int, str], list[float]] = defaultdict(list)
    for o in rows:
        if o.r > 0:
            acc[(o.week, o.family)].append(o.r)
    return {k: statistics.fmean(v) for k, v in acc.items()}


def r_tilde(o: Obs, anchor: Mapping[tuple[int, str], float] | None) -> float:
    if anchor is None:
        return o.r
    a = anchor.get((o.week, o.family))
    return o.r / a if a and a > 0 else 0.0


# ── §3.2 forward mean model ────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class FamilyMean:
    a: float
    b: float
    mode: str  # "ols" | "level" (ratio through the origin) | "pooled_level"
    n: int

    def predict(self, x: float) -> float:
        return max(0.0, self.a + self.b * x)


def _ratio(xs: Sequence[float], ys: Sequence[float]) -> float:
    sx = sum(xs)
    return sum(ys) / sx if sx > 0 else 0.0


def fit_mean_model(
    rows: Sequence[Obs], anchor: Mapping[tuple[int, str], float] | None
) -> tuple[dict[str, FamilyMean], FamilyMean]:
    """Per family OLS of ``y`` on ``r~`` (intercept); below the floor or ``b <= 0`` the level-only ratio."""
    by: dict[str, tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    allx: list[float] = []
    ally: list[float] = []
    for o in rows:
        x = r_tilde(o, anchor)
        if x <= 0:
            continue
        by[o.family][0].append(x)
        by[o.family][1].append(o.y)
        allx.append(x)
        ally.append(o.y)
    pooled = FamilyMean(0.0, _ratio(allx, ally), "pooled_level", len(allx))
    out: dict[str, FamilyMean] = {}
    for fam, (xs, ys) in by.items():
        n = len(xs)
        level = FamilyMean(0.0, _ratio(xs, ys), "level", n)
        if n < FLOOR:
            out[fam] = level
            continue
        mx, my = statistics.fmean(xs), statistics.fmean(ys)
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx <= 0:
            out[fam] = level
            continue
        b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
        out[fam] = FamilyMean(my - b * mx, b, "ols", n) if b > 0 else level
    return out, pooled


# ── §3.3 / §3.5 spread and location ────────────────────────────────────────────────────────────


def g_censored_mean(c: float) -> float:
    """``E[max(0, N(m, (c m)^2))] / m`` = ``Phi(1/c) + c phi(1/c)``."""
    z = 1.0 / c
    return v1.norm_cdf(z) + c * v1.norm_pdf(z)


def cv_grid() -> list[float]:
    n = int(round((CV_HI - CV_LO) / CV_STEP))
    return [round(CV_LO + i * CV_STEP, 4) for i in range(n + 1)]


def best_cv(pairs: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """``(c, mean censored log score)`` maximizing the prequential log score over ``(mu, y)`` pairs."""
    best = (CV_LO, -math.inf)
    for c in cv_grid():
        g = g_censored_mean(c)
        tot = 0.0
        for mu, y in pairs:
            m = mu / g
            tot += v1.censored_log_score(y, m, max(SIGMA_FLOOR, m * c))
        score = tot / len(pairs)
        if score > best[1] + 1e-12:
            best = (c, score)
    return best


@dataclass(frozen=True)
class Resid:
    week: int
    rid: int
    pid: str
    family: str
    mu: float
    y: float


def prequential(
    rows: Sequence[Obs], h: int, anchor: Mapping[tuple[int, str], float] | None
) -> list[Resid]:
    """Week ``t`` in ``2..h-1`` predicted from weeks ``< t`` only."""
    out: list[Resid] = []
    for t in range(2, h):
        past = [o for o in rows if o.week < t]
        if not past:
            continue
        fam_fit, pooled = fit_mean_model(past, anchor)
        for o in rows:
            if o.week != t:
                continue
            x = r_tilde(o, anchor)
            if x <= 0:
                continue
            mdl = fam_fit.get(o.family, pooled)
            out.append(Resid(t, o.rid, o.pid, o.family, mdl.predict(x), o.y))
    return out


def fit_cvs(resid: Sequence[Resid]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    by: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for e in resid:
        by[e.family].append((e.mu, e.y))
    allp = [(e.mu, e.y) for e in resid]
    c_pool, ls_pool = best_cv(allp) if allp else (sc.FALLBACK_DEFAULT_CV, None)
    pooled = {"cv": c_pool, "n": len(allp), "meanLogScore": ls_pool}
    out: dict[str, dict[str, Any]] = {}
    for fam, pairs in by.items():
        if len(pairs) < FLOOR:
            out[fam] = {"cv": c_pool, "n": len(pairs), "measured": False}
            continue
        c, ls = best_cv(pairs)
        out[fam] = {"cv": c, "n": len(pairs), "measured": True, "meanLogScore": round(ls, 5)}
    return out, pooled


def fit_shocks(resid: Sequence[Resid], cv_of: Mapping[str, float], pooled_cv: float) -> dict:
    """§3.4 method of moments: ``tau_L^2`` (different rosters, same week), ``tau_R^2`` (same roster excess)."""
    by_week: dict[int, list[tuple[int, float, float]]] = defaultdict(list)
    for e in resid:
        c = cv_of.get(e.family, pooled_cv)
        m = e.mu / g_censored_mean(c)
        by_week[e.week].append((e.rid, e.y - e.mu, m))
    within_e = within_m = all_e = all_m = 0.0
    for items in by_week.values():
        se = sum(x for _, x, _ in items)
        sm = sum(m for _, _, m in items)
        all_e += (se * se - sum(x * x for _, x, _ in items)) / 2.0
        all_m += (sm * sm - sum(m * m for _, _, m in items)) / 2.0
        per: dict[int, list[tuple[float, float]]] = defaultdict(list)
        for rid, x, m in items:
            per[rid].append((x, m))
        for lst in per.values():
            re = sum(x for x, _ in lst)
            rm = sum(m for _, m in lst)
            within_e += (re * re - sum(x * x for x, _ in lst)) / 2.0
            within_m += (rm * rm - sum(m * m for _, m in lst)) / 2.0
    cross_e, cross_m = all_e - within_e, all_m - within_m
    tau_l2_raw = cross_e / cross_m if cross_m > 0 else 0.0
    tau_w2_raw = within_e / within_m if within_m > 0 else 0.0
    tau_l2 = max(0.0, tau_l2_raw)
    tau_r2 = max(0.0, tau_w2_raw - tau_l2)
    return {
        "tauL2": tau_l2,
        "tauR2": tau_r2,
        "tauL2Raw": tau_l2_raw,
        "tauW2Raw": tau_w2_raw,
        "pairsCross": cross_m > 0,
        "residualPlayerWeeks": len(resid),
    }


# ── the research challenger ────────────────────────────────────────────────────────────────────


@dataclass
class V3PointsModel(sc.PointsModel):
    """RESEARCH CANDIDATE, not served (§3). ``draw`` is production-compatible; ``mean_points`` raises."""

    fam_mean: Mapping[str, FamilyMean] = field(default_factory=dict)
    pooled_mean: FamilyMean = FamilyMean(0.0, 0.0, "pooled_level", 0)
    anchor_by_family: Mapping[str, float] | None = None  # None ⇒ r~ = r (no re-anchoring)
    cv_by_family: Mapping[str, float] = field(default_factory=dict)
    pooled_cv: float = sc.FALLBACK_DEFAULT_CV
    raw_family: Mapping[str, str] = field(default_factory=dict)
    tau_l2: float = 0.0
    tau_r2: float = 0.0
    shock: float = 0.0

    def family_for(self, position: str) -> str | None:
        raw = (position or "").strip().upper()
        fam = lineup_position(raw)
        if fam in v1.SIM_FAMILIES:
            return fam
        return self.raw_family.get(raw)

    def cv_for(self, position: str) -> float:
        fam = self.family_for(position)
        cv = self.cv_by_family.get(fam) if fam else None
        return float(cv) if cv and cv > 0 else float(self.pooled_cv)

    def mean_for(self, ros_value: float, position: str) -> float:
        fam = self.family_for(position)
        if self.anchor_by_family is None:
            x = float(ros_value)
        else:
            a = self.anchor_by_family.get(fam) if fam else None
            if not a or a <= 0:
                return 0.0
            x = float(ros_value) / a
        if x <= 0:
            return 0.0
        mdl = self.fam_mean.get(fam) if fam else None
        return (mdl or self.pooled_mean).predict(x)

    def location(self, ros_value: float, position: str) -> float:
        return self.mean_for(ros_value, position) / g_censored_mean(self.cv_for(position))

    def sigma_total(self, m: float, position: str) -> float:
        return max(SIGMA_FLOOR, m * self.cv_for(position))

    def sigma_idio(self, m: float, position: str) -> float:
        tau2 = self.tau_l2 + self.tau_r2
        if tau2 <= 0:
            return self.sigma_total(m, position)
        v = self.sigma_total(m, position) ** 2 - m * m * tau2
        if v > 0:
            return math.sqrt(v)
        c_idio = math.sqrt(max(CV_LO**2, self.cv_for(position) ** 2 - tau2))
        return max(SIGMA_FLOOR, m * c_idio)

    def mean_points(self, ros_value: float) -> float:  # noqa: ARG002 - deliberately unusable
        raise TypeError("V3PointsModel has no position-free mean: use mean_for(rv, pos)")

    def draw(self, ros_value: float, position: str, rng: Any) -> float:
        m = self.location(ros_value, position)
        if m <= 0:
            return 0.0
        return max(0.0, rng.gauss(m * (1.0 + self.shock), self.sigma_idio(m, position)))

    def draw_from_mean(self, mean: float, position: str, rng: Any) -> float:
        """A caller-supplied mean in points (BBLI, Game Day): V3's spread and censoring, no shocks."""
        if mean <= 0.0:
            return 0.0
        m = mean / g_censored_mean(self.cv_for(position))
        return max(0.0, rng.gauss(m, self.sigma_total(m, position)))

    def with_shock(self, s: float) -> "V3PointsModel":
        return dataclasses.replace(self, shock=float(s))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "meanByFamily": {
                f: {"a": round(m.a, 6), "b": round(m.b, 6), "mode": m.mode, "n": m.n}
                for f, m in sorted(self.fam_mean.items())
            },
            "pooledMean": {
                "a": self.pooled_mean.a,
                "b": round(self.pooled_mean.b, 6),
                "n": self.pooled_mean.n,
            },
            "reAnchored": self.anchor_by_family is not None,
            "cvByFamily": dict(sorted(self.cv_by_family.items())),
            "pooledCv": self.pooled_cv,
            "rawFamily": dict(self.raw_family),
            "tauL2": round(self.tau_l2, 6),
            "tauR2": round(self.tau_r2, 6),
        }


def raw_family_table(rows: Iterable[Obs]) -> dict[str, str]:
    counts: dict[str, Counter] = defaultdict(Counter)
    for o in rows:
        raw = (o.position or "").upper()
        if raw and lineup_position(raw) not in v1.SIM_FAMILIES and o.family:
            counts[raw][o.family] += 1
    order = {f: i for i, f in enumerate(v1.FAMILY_ORDER)}
    return {
        raw: sorted(c.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99)))[0][0]
        for raw, c in sorted(counts.items())
    }


def fit_v3(
    rows: Sequence[Obs],
    h: int,
    *,
    anchor: Mapping[tuple[int, str], float] | None,
    shocks: bool = True,
) -> tuple[V3PointsModel, dict[str, Any]]:
    """§3 for evaluated week ``h``: only weeks ``< h`` are read (refuses otherwise)."""
    fit_rows = [o for o in rows if o.week < h]
    if any(o.week >= h for o in fit_rows):  # defensive: the filter above is the contract
        raise v1.StudyRefusal(f"week >= {h} reached the v3 fit")
    fam_mean, pooled = fit_mean_model(fit_rows, anchor)
    resid = prequential(fit_rows, h, anchor)
    if any(e.week >= h for e in resid):
        raise v1.StudyRefusal(f"week >= {h} reached the v3 prequential residuals")
    cvs, pooled_cv = fit_cvs(resid)
    cv_of = {f: float(e["cv"]) for f, e in cvs.items()}
    sh = (
        fit_shocks(resid, cv_of, float(pooled_cv["cv"])) if shocks else {"tauL2": 0.0, "tauR2": 0.0}
    )
    model = V3PointsModel(
        ros_value_per_point=1.0,
        cv_by_position={},
        fam_mean=fam_mean,
        pooled_mean=pooled,
        anchor_by_family=None,
        cv_by_family=cv_of,
        pooled_cv=float(pooled_cv["cv"]),
        raw_family=raw_family_table(fit_rows),
        tau_l2=float(sh["tauL2"]),
        tau_r2=float(sh["tauR2"]),
        source="research-v3-challenger",
        sample_size=len(fit_rows),
    )
    tau2 = model.tau_l2 + model.tau_r2
    receipts = {
        "fitWeeks": sorted({o.week for o in fit_rows}),
        "fitPlayerWeeks": len(fit_rows),
        "prequentialPlayerWeeks": len(resid),
        "prequentialWeeks": sorted({e.week for e in resid}),
        "cv": cvs,
        "pooledCv": pooled_cv,
        "shocks": sh,
        "cIdioByFamily": {
            f: round(math.sqrt(max(CV_LO**2, c * c - tau2)), 4) for f, c in sorted(cv_of.items())
        },
    }
    return model, receipts


def for_week(
    model: V3PointsModel, anchor: Mapping[tuple[int, str], float] | None, week: int
) -> V3PointsModel:
    """The fitted model with the target week's family anchors attached (inputs only)."""
    if anchor is None:
        return dataclasses.replace(model, anchor_by_family=None)
    return dataclasses.replace(
        model, anchor_by_family={f: a for (w, f), a in anchor.items() if w == week}
    )


def challenger_payload(model: V3PointsModel, receipts: Mapping[str, Any], h: int) -> dict:
    return {
        "schemaVersion": CHALLENGER_SCHEMA,
        "kind": "RESEARCH_CANDIDATE_NOT_SERVED",
        "promotes": False,
        "evaluatedWeek": h,
        "model": model.to_dict(),
        "fit": dict(receipts),
        "note": (
            "Family anchors are inputs of the evaluated week (mean as-of rosValue over its pool, §3.1) and "
            "are attached at evaluation time; they are not part of this file."
        ),
    }


def load_challenger(path: Path) -> V3PointsModel:
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    if blob.get("schemaVersion") != CHALLENGER_SCHEMA:
        raise v1.StudyRefusal(f"{path} is not a {CHALLENGER_SCHEMA} file")
    m = blob["model"]
    return V3PointsModel(
        ros_value_per_point=1.0,
        cv_by_position={},
        fam_mean={
            f: FamilyMean(float(e["a"]), float(e["b"]), str(e["mode"]), int(e["n"]))
            for f, e in m["meanByFamily"].items()
        },
        pooled_mean=FamilyMean(
            float(m["pooledMean"]["a"]),
            float(m["pooledMean"]["b"]),
            "pooled_level",
            int(m["pooledMean"]["n"]),
        ),
        anchor_by_family={} if m.get("reAnchored") else None,
        cv_by_family={str(k): float(v) for k, v in m["cvByFamily"].items()},
        pooled_cv=float(m["pooledCv"]),
        raw_family={str(k): str(v) for k, v in m["rawFamily"].items()},
        tau_l2=float(m["tauL2"]),
        tau_r2=float(m["tauR2"]),
        source="research-v3-challenger",
    )


# ── predictions and player-level metrics ───────────────────────────────────────────────────────


def predictive(model: sc.PointsModel, ros_value: float, position: str) -> tuple[float, float]:
    """``(location, sigma)`` of the censored-normal marginal each model's draw implies."""
    if isinstance(model, V3PointsModel):
        m = model.location(ros_value, position)
        return m, model.sigma_total(m, position)
    return v2.predictive(model, ros_value, position)


def predicted_mean(model: sc.PointsModel, ros_value: float, position: str) -> float:
    """The mean of the censored draw ``max(0, N(loc, sigma^2))``, the same formula for every model.

    For V3 this equals ``mu`` (§3.5) up to the 0.5 sigma floor.
    """
    loc, sigma = predictive(model, ros_value, position)
    if loc <= 0 and sigma <= 0:
        return 0.0
    z = loc / sigma
    return loc * v1.norm_cdf(z) + sigma * v1.norm_pdf(z)


@dataclass
class Scored(v1.Scored):
    mean: dict[str, float] = field(default_factory=dict)


def score_rows(
    rows: Sequence[Obs], models_by_week: Mapping[int, Mapping[str, sc.PointsModel]]
) -> list[Scored]:
    """v1's metrics, one uniform per row (in row order, shared by every model)."""
    rng = random.Random(v1.SEED)
    out: list[Scored] = []
    for o in rows:
        u = rng.random()
        rec = Scored(o.pid, o.week, o.family, o.position, o.r, o.y, {}, {}, {}, {}, {}, {}, {})
        for name, model in models_by_week[o.week].items():
            mu, sigma = predictive(model, o.r, o.position)
            rec.mu[name] = mu
            rec.mean[name] = predicted_mean(model, o.r, o.position)
            rec.sigma[name] = sigma
            rec.ls[name] = v1.censored_log_score(o.y, mu, sigma)
            rec.crps[name] = v1.censored_crps(o.y, mu, sigma)
            rec.cov80[name] = v1.covered(o.y, mu, sigma, 0.80)
            rec.cov95[name] = v1.covered(o.y, mu, sigma, 0.95)
            rec.pit[name] = v1.censored_pit(o.y, mu, sigma, u)
        out.append(rec)
    return out


def cluster_ratio_bootstrap(
    ys: Sequence[float], mus: Sequence[float], clusters: Sequence[str], *, b: int, seed: int
) -> dict[str, Any]:
    """``Σy / Σmu`` with a 95% percentile CI, resampling clusters."""
    sy: dict[str, float] = defaultdict(float)
    sm: dict[str, float] = defaultdict(float)
    for y, m, c in zip(ys, mus, clusters):
        sy[c] += y
        sm[c] += m
    keys = sorted(sy)
    if not keys or sum(sm.values()) <= 0:
        return {"ratio": None, "ci95": [None, None]}
    rng = random.Random(seed)
    stats = []
    for _ in range(b):
        ty = tm = 0.0
        for _j in keys:
            k = keys[rng.randrange(len(keys))]
            ty += sy[k]
            tm += sm[k]
        stats.append(ty / tm if tm > 0 else float("inf"))
    stats.sort()
    return {
        "ratio": round(sum(sy.values()) / sum(sm.values()), 5),
        "ci95": [
            round(v1.sample_quantile(stats, 0.025), 5),
            round(v1.sample_quantile(stats, 0.975), 5),
        ],
        "clusters": len(keys),
    }


def summarize(recs: list[Scored], names: Sequence[str], *, b: int) -> dict[str, Any]:
    """v2's per-model summary (location-based fields) plus V3's mean-based bias / ratio and V3 deltas."""
    if not recs:
        return {"n": 0}
    out = v2.summarize(recs, names=names, b=b, seed=v1.SEED)
    clusters = [r.pid for r in recs]
    ys = [max(0.0, r.y) for r in recs]
    for m in names:
        means = [r.mean[m] for r in recs]
        out[m]["meanPredictedDrawMean"] = round(statistics.fmean(means), 4)
        out[m]["meanBiasOfDrawMean"] = round(statistics.fmean(p - y for p, y in zip(means, ys)), 4)
        out[m]["realizedOverPredictedDrawMean"] = cluster_ratio_bootstrap(
            ys, means, clusters, b=b, seed=v1.SEED
        )
    for a, bb in ((V3, F), (V3, V2N), (V3_NOANCHOR, F), (V3_ASOF, F), (V2N, F)):
        if a in names and bb in names:
            out["deltas"][f"{a}-{bb}"] = {
                "deltaLogScore": v1.cluster_bootstrap(
                    [r.ls[a] - r.ls[bb] for r in recs], clusters, b=b, seed=v1.SEED
                ),
                "deltaCrps": v1.cluster_bootstrap(
                    [r.crps[bb] - r.crps[a] for r in recs], clusters, b=b, seed=v1.SEED
                ),
            }
    return out


def player_block(recs: list[Scored], names: Sequence[str], *, b: int) -> dict[str, Any]:
    by_fam: dict[str, list[Scored]] = defaultdict(list)
    for r in recs:
        by_fam[r.family].append(r)
    return {
        "pooled": summarize(recs, names, b=b),
        "byFamily": {
            fam: summarize(by_fam[fam], names, b=b) for fam in v1.FAMILY_ORDER if by_fam.get(fam)
        },
    }


# ── team-week sims ─────────────────────────────────────────────────────────────────────────────


def shock_streams(week: int, rid: int, model: V3PointsModel, draws: int) -> list[float]:
    """``s_L + s_R`` per draw: ``s_L`` from one stream per week (every roster), ``s_R`` per roster."""
    rl = random.Random(_seed(week, "L"))
    rr = random.Random(_seed(week, rid, "R"))
    sl, sr = math.sqrt(model.tau_l2), math.sqrt(model.tau_r2)
    return [rl.gauss(0.0, 1.0) * sl + rr.gauss(0.0, 1.0) * sr for _ in range(draws)]


def simulate_team_week(
    pool: list[dict[str, Any]],
    slots: list[str],
    model: sc.PointsModel,
    seed: int,
    draws: int,
    *,
    week: int,
    rid: int,
) -> list[float]:
    """Production ``_bestball_weekly_score`` per draw; a V3 model gets that draw's shared shock."""
    if not isinstance(model, V3PointsModel):
        return v1.simulate_team_week(pool, slots, model, seed, draws)
    rng = random.Random(seed)
    shocks = shock_streams(week, rid, model, draws)
    return [
        playoff_sim._bestball_weekly_score(pool, slots, rng, model.with_shock(s)) for s in shocks
    ]


def bias_ci(results: Sequence[Mapping[str, Any]], m: str, *, b: int) -> dict[str, Any]:
    vals = [statistics.fmean(it["draws"][m]) - float(it["realized"]) for it in results]
    return v1.cluster_bootstrap(vals, [str(i) for i in range(len(vals))], b=b, seed=v1.SEED)


def allplay(results: Sequence[Mapping[str, Any]], m: str) -> list[dict[str, Any]]:
    """Every same-week pair of rosters: ``P(A > B)`` from aligned draw indices, and the outcome."""
    by_week: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for it in results:
        by_week[int(it["week"])].append(it)
    out = []
    for w, items in sorted(by_week.items()):
        items = sorted(items, key=lambda it: it["rid"])
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                a, bb = items[i]["draws"][m], items[j]["draws"][m]
                p = sum(1.0 if x > y else 0.5 if x == y else 0.0 for x, y in zip(a, bb)) / len(a)
                ra, rb = float(items[i]["realized"]), float(items[j]["realized"])
                yy = 1.0 if ra > rb else 0.5 if ra == rb else 0.0
                h2h = items[i].get("matchupId") is not None and items[i].get("matchupId") == items[
                    j
                ].get("matchupId")
                out.append({"week": w, "i": i, "j": j, "p": p, "y": yy, "h2h": h2h})
    return out


def _ll(p: float, y: float) -> float:
    p = min(1 - PROB_CLIP, max(PROB_CLIP, p))
    return -(y * math.log(p) + (1 - y) * math.log(1 - p))


def _rank(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2.0 + 1
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den > 0 else None


def kendall_tau(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n < 2:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            if s > 0:
                conc += 1
            elif s < 0:
                disc += 1
    tot = n * (n - 1) / 2
    return (conc - disc) / tot if tot else None


def ranking_block(results: Sequence[Mapping[str, Any]], names: Sequence[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    pairs = {m: allplay(results, m) for m in names}
    weeks = sorted({int(it["week"]) for it in results})
    for m in names:
        ap = pairs[m]
        hh = [r for r in ap if r["h2h"]]
        rho = {}
        tau_vs_f = {}
        for w in weeks:
            items = sorted((it for it in results if int(it["week"]) == w), key=lambda it: it["rid"])
            sim = [statistics.fmean(it["draws"][m]) for it in items]
            real = [float(it["realized"]) for it in items]
            rho[str(w)] = None if (s := spearman(sim, real)) is None else round(s, 4)
            if F in names:
                fm = [statistics.fmean(it["draws"][F]) for it in items]
                tau_vs_f[str(w)] = None if (t := kendall_tau(sim, fm)) is None else round(t, 4)
        dp = [abs(r["p"] - q["p"]) for r, q in zip(ap, pairs[F])] if F in pairs else []
        out[m] = {
            "allPlayPairs": len(ap),
            "allPlayBrier": round(statistics.fmean((r["p"] - r["y"]) ** 2 for r in ap), 5)
            if ap
            else None,
            "allPlayLogLoss": round(statistics.fmean(_ll(r["p"], r["y"]) for r in ap), 5)
            if ap
            else None,
            "h2hGames": len(hh),
            "h2hBrier": round(statistics.fmean((r["p"] - r["y"]) ** 2 for r in hh), 5)
            if hh
            else None,
            "h2hLogLoss": round(statistics.fmean(_ll(r["p"], r["y"]) for r in hh), 5)
            if hh
            else None,
            "spearmanSimMeanVsRealized": rho,
            "kendallTauTeamOrderVsF": tau_vs_f,
            "allPlayAbsDeltaPVsF": {
                "mean": round(statistics.fmean(dp), 5) if dp else None,
                "max": round(max(dp), 5) if dp else None,
            },
            "reliability": _reliability(ap),
        }
    return out


def _reliability(ap: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    bins = [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.0001)]
    rows = []
    for lo, hi in bins:
        sel = []
        for r in ap:  # fold each pair to the favourite's side so bins are symmetric
            p, y = (r["p"], r["y"]) if r["p"] >= 0.5 else (1 - r["p"], 1 - r["y"])
            if lo <= p < hi:
                sel.append((p, y))
        if sel:
            rows.append(
                {
                    "bin": [lo, min(hi, 1.0)],
                    "n": len(sel),
                    "meanP": round(statistics.fmean(p for p, _ in sel), 4),
                    "winRate": round(statistics.fmean(y for _, y in sel), 4),
                }
            )
    return rows


# ── gates ──────────────────────────────────────────────────────────────────────────────────────


def apply_gates_v3(
    player: Mapping[str, Any],
    team: Mapping[str, Any],
    team_results: Sequence[Mapping[str, Any]],
    ranking: Mapping[str, Any],
    *,
    b: int,
) -> dict[str, Any]:
    """SC-G1..SC-G5 (v2's function, verbatim, V3 in the challenger seat) plus V3-G6..V3-G9."""
    base = v2.apply_gates_v2(player, team, challenger=V3, champion=F)
    gates = dict(base["gates"])
    gated = gates["SC-G1"]["gatedFamilies"]

    ci = bias_ci(team_results, V3, b=b)
    lo, hi = ci["ci95"]
    g6 = lo is not None and G6_BIAS_BAND[0] <= lo and hi <= G6_BIAS_BAND[1]
    pt_inside = ci["mean"] is not None and G6_BIAS_BAND[0] <= ci["mean"] <= G6_BIAS_BAND[1]
    gates["V3-G6"] = {
        "pass": bool(g6),
        "underpowered": (not g6) and pt_inside,
        "bias": ci,
        "rule": f"95% team-week bias CI inside {list(G6_BIAS_BAND)}",
    }

    pit = team[V3]["pit"]
    crit = v2.ks_critical_95(int(team["n"])) if team["n"] else None
    g7 = pit["ksD"] is not None and crit is not None and pit["ksD"] <= crit
    gates["V3-G7"] = {
        "pass": bool(g7),
        "ksD": pit["ksD"],
        "ksP": pit["ksP"],
        "ksCritical95": None if crit is None else round(crit, 5),
        "rule": "team-week PIT KS D <= 95% critical value at n",
    }

    bv, bf = ranking[V3]["allPlayBrier"], ranking[F]["allPlayBrier"]
    g8 = bv is not None and bf is not None and bv <= bf and bv < BRIER_COIN
    gates["V3-G8"] = {
        "pass": bool(g8),
        "allPlayBrier": {V3: bv, F: bf},
        "rule": f"all-play Brier({V3}) <= Brier({F}) and < {BRIER_COIN}",
    }

    fails, under = [], []
    detail = {}
    for f in gated:
        rr = player["byFamily"][f][V3]["realizedOverPredictedDrawMean"]
        detail[f] = rr
        lo9, hi9 = rr["ci95"]
        ok = lo9 is not None and G9_RATIO_BAND[0] <= lo9 and hi9 <= G9_RATIO_BAND[1]
        if not ok:
            fails.append(f)
            if rr["ratio"] is not None and G9_RATIO_BAND[0] <= rr["ratio"] <= G9_RATIO_BAND[1]:
                under.append(f)
    gates["V3-G9"] = {
        "pass": not fails,
        "failingFamilies": fails,
        "underpoweredFamilies": under,
        "ratioByFamily": detail,
        "rule": f"each gated family's 95% CI of Σy/Σmu inside {list(G9_RATIO_BAND)}",
    }
    all_pass = all(g["pass"] for g in gates.values())
    return {
        "gates": gates,
        "verdict": "V3_BEATS_FALLBACK" if all_pass else "V3_DOES_NOT_BEAT_FALLBACK",
        "failingGates": [k for k, g in gates.items() if not g["pass"]],
    }


# ── provenance ─────────────────────────────────────────────────────────────────────────────────


def code_identity() -> dict[str, Any]:
    sha = v2._git("rev-parse", "HEAD")
    dirty = v2._git(
        "status",
        "--porcelain",
        "--",
        "scripts/sim_calibration_v3_study.py",
        "scripts/sim_calibration_v2_study.py",
        "scripts/sim_calibration_study.py",
        "src",
    )
    try:
        anc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", PREREGISTRATION_COMMIT, "HEAD"],
            cwd=REPO,
            capture_output=True,
            timeout=30,
            check=False,
        ).returncode
        is_anc = {0: True, 1: False}.get(anc)
    except (OSError, subprocess.SubprocessError):
        is_anc = None
    return {
        "codeSha": sha or "UNKNOWN",
        "studyCodeDirty": None if dirty is None else bool(dirty),
        "scriptSha256": v2.sha256_file(Path(__file__)),
        "preregistration": {
            "path": PREREGISTRATION,
            "commit": PREREGISTRATION_COMMIT,
            "committedAt": v2._git("log", "-1", "--format=%cI", PREREGISTRATION_COMMIT),
            "isAncestorOfCodeSha": is_anc,
        },
    }


# ── data loading (v1's path, reused) ───────────────────────────────────────────────────────────


@dataclass
class Loaded:
    fetcher: Any
    fingerprint: str
    slots: list[str]
    sched: dict[int, Any]
    directory: dict[str, Any]
    obs: list[Obs]  # appeared, priced
    rostered: list[Obs]  # every priced rostered row, any status (y = nan when not appeared)
    pools: dict[tuple[int, int], list[dict[str, Any]]]  # (week, rid) -> appeared pool rows
    full: dict[tuple[int, int], list[dict[str, Any]]]  # (week, rid) -> every row
    realized: dict[tuple[int, int], float]
    matchup_id: dict[tuple[int, int], Any]
    snapshots: dict[str, Any]
    census: dict[str, Any]


def load(args: argparse.Namespace, weeks: Sequence[int]) -> Loaded:
    f = v1.CachedFetcher(Path(args.cache_dir), offline=args.offline)
    league = f.get_json(f"{v1.SLEEPER}/league/{v1.LEAGUE_ID}")
    card = {str(k): float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    fp = v1.scoring_fingerprint(league.get("scoring_settings"))
    if fp != v1.PINNED_SCORING_FINGERPRINT:
        raise v1.StudyRefusal(f"card fingerprint {fp} != pinned {v1.PINNED_SCORING_FINGERPRINT}")
    slots = v1.starter_slots_from_roster_positions(league.get("roster_positions"))
    games = f.get_csv(v1.NFLVERSE_GAMES, Path(args.games_cache))
    sched = v1.schedule_by_week(games, SEASON)
    for w in weeks:
        if w not in sched or not sched[w].is_final:
            s = sched.get(w)
            raise v1.StudyRefusal(
                f"2026 week {w} not final ({s.final_games if s else 0}/{s.games if s else 0})"
            )
    directory = f.get_json(f"{v1.SLEEPER}/players/nfl")
    stats = sc.fetch_stat_lines(str(SEASON), list(weeks), fetcher=f.get_json, sleep_s=0.0)
    missing = sorted(set(weeks) - set(stats))
    if missing:
        raise v1.StudyRefusal(f"stat lines unavailable for 2026 weeks {missing}")

    obs: list[Obs] = []
    rostered: list[Obs] = []
    pools: dict[tuple[int, int], list[dict[str, Any]]] = {}
    full_by: dict[tuple[int, int], list[dict[str, Any]]] = {}
    realized: dict[tuple[int, int], float] = {}
    mid: dict[tuple[int, int], Any] = {}
    snapshots: dict[str, Any] = {}
    statuses: list[v1.PlayerWeek] = []
    for w in weeks:
        matchups = f.get_json(f"{v1.SLEEPER}/league/{v1.LEAGUE_ID}/matchups/{w}")
        rost = v1.rostered_by_week(matchups)
        body = stats[w]
        pw_by = {}
        for pid in sorted({p for lst in rost.values() for p in lst}):
            pw = v1.classify_player_week(pid, body.get(pid), directory.get(pid), card, SEASON, w)
            pw_by[pid] = pw
            statuses.append(pw)
        snap = v1.snapshot_before(sched[w].first_kickoff_utc)
        snapshots[f"week{w}"] = {
            "file": _rel(snap),
            "sha256": v2.sha256_file(snap),
            "cutoffUtc": sched[w].first_kickoff_utc.isoformat(),
        }
        full = v1.as_of_full_rosters(rost, directory, v1.load_snapshot_players(snap), slots)
        for m in matchups:
            rid = int(m["roster_id"])
            realized[(w, rid)] = float(m.get("points") or 0.0)
            mid[(w, rid)] = m.get("matchup_id")
        for rid, rows in sorted(full.items()):
            pool = []
            full_by[(w, rid)] = list(rows)
            for r in rows:
                pid = str(r["playerId"])
                pw = pw_by.get(pid)
                rv = float(r.get("rosValue") or 0.0)
                fam = v1.lineup_family(directory.get(pid))
                pos = str(r.get("position") or (pw.position if pw else "")).upper()
                if rv > 0 and fam:
                    appeared = pw is not None and pw.status == v1.APPEARED
                    rostered.append(
                        Obs(w, rid, pid, pos, fam, rv, float(pw.points) if appeared else math.nan)
                    )
                if pw is None or pw.status != v1.APPEARED:
                    continue
                pool.append(r)
                if rv > 0:
                    obs.append(Obs(w, rid, pid, pos, pw.family, rv, float(pw.points)))
            pools[(w, rid)] = pool
    return Loaded(
        f,
        fp,
        slots,
        sched,
        directory,
        obs,
        rostered,
        pools,
        full_by,
        realized,
        mid,
        snapshots,
        v1._census(statuses),
    )


# ── evaluate ───────────────────────────────────────────────────────────────────────────────────


def _team_results(
    ld: Loaded,
    weeks: Sequence[int],
    models_by_week: Mapping[int, Mapping[str, sc.PointsModel]],
    draws: int,
) -> list[dict[str, Any]]:
    out = []
    for w in weeks:
        for rid in sorted(rid for (ww, rid) in ld.pools if ww == w):
            pool = ld.pools[(w, rid)]
            seed = v1.team_week_seed(w, rid)
            out.append(
                {
                    "week": w,
                    "rid": rid,
                    "matchupId": ld.matchup_id.get((w, rid)),
                    "realized": ld.realized[(w, rid)],
                    "draws": {
                        m: simulate_team_week(pool, ld.slots, mod, seed, draws, week=w, rid=rid)
                        for m, mod in models_by_week[w].items()
                    },
                }
            )
    return out


def _block(
    ld: Loaded,
    weeks: Sequence[int],
    scored: list[Scored],
    team_results: list[dict[str, Any]],
    *,
    b: int,
) -> dict[str, Any]:
    recs = [r for r in scored if r.week in weeks]
    res = [t for t in team_results if t["week"] in weeks]
    player = player_block(recs, PLAYER_MODELS, b=b)
    team = v2.team_metrics(res, TEAM_MODELS)
    for m in TEAM_MODELS:
        team[m]["biasCi"] = bias_ci(res, m, b=b)
    ranking = ranking_block(res, TEAM_MODELS)
    decision = apply_gates_v3(player, team, res, ranking, b=b)
    return {
        "weeks": list(weeks),
        "playerLevel": player,
        "teamWeek": team,
        "ranking": ranking,
        "sizeAware": {
            fam: v2.size_aware(player["byFamily"][fam], model=V3)
            for fam in decision["gates"]["SC-G1"]["gatedFamilies"]
        },
        **decision,
    }


def nfl_team_tau(ld: Loaded, model: V3PointsModel, anchor: Mapping, h: int) -> dict[str, Any]:
    """V3-D4: same-roster, same-NFL-team pairs' method-of-moments tau, prequential residuals (< h)."""
    rows = [o for o in ld.obs if o.week < h]
    resid = prequential(rows, h, anchor)
    num = den = 0.0
    pairs = 0
    groups: dict[tuple[int, int, str], list[tuple[float, float]]] = defaultdict(list)
    for e in resid:
        team = str((ld.directory.get(e.pid) or {}).get("team") or "")
        if not team:
            continue
        m = e.mu / g_censored_mean(model.cv_by_family.get(e.family, model.pooled_cv))
        groups[(e.week, e.rid, team)].append((e.y - e.mu, m))
    for lst in groups.values():
        se = sum(x for x, _ in lst)
        sm = sum(m for _, m in lst)
        num += (se * se - sum(x * x for x, _ in lst)) / 2.0
        den += (sm * sm - sum(m * m for _, m in lst)) / 2.0
        pairs += len(lst) * (len(lst) - 1) // 2
    return {
        "pairs": pairs,
        "tau2SameRosterSameNflTeam": round(num / den, 6) if den > 0 else None,
        "note": "NFL team is today's directory team (inherited positions caveat)",
    }


def evaluate(args: argparse.Namespace) -> dict[str, Any]:
    dev_only = bool(getattr(args, "dev_only", False))
    eval_weeks = DEV_WEEKS if dev_only else tuple(sorted({*DEV_WEEKS, *PRIMARY_WEEKS}))
    weeks = tuple(range(1, max(eval_weeks) + 1))
    fit_weeks = eval_weeks if dev_only else (*eval_weeks, CONFIRM_WEEK)
    out_dir = v1.assert_safe_output(Path(args.out_dir))
    eval_path = v1.assert_safe_output(out_dir / args.out_name)
    v2_sha = v2.sha256_file(V2_CHALLENGER)
    if v2_sha != V2_CHALLENGER_SHA256:
        raise v1.StudyRefusal(f"v2 challenger sha256 {v2_sha} != {V2_CHALLENGER_SHA256}")
    ld = load(args, weeks)
    code = code_identity()

    anc_app = anchors(ld.obs)
    anc_ros = anchors(ld.rostered)
    v2_model = v2.load_challenger(V2_CHALLENGER)
    fallback = sc.PointsModel()

    models_by_week: dict[int, dict[str, sc.PointsModel]] = {}
    fits: dict[str, Any] = {}
    challengers: dict[str, Any] = {}
    for h in fit_weeks:
        base, rec = fit_v3(ld.obs, h, anchor=anc_app)
        noanc, rec_na = fit_v3(ld.obs, h, anchor=None)
        fits[f"week{h}"] = {"V3": rec, "V3-noAnchor": rec_na}
        payload = challenger_payload(base, rec, h)
        payload["study"] = {
            "promotes": False,
            "status": "RESEARCH_CANDIDATE_NOT_SERVED",
            "cardFingerprint": ld.fingerprint,
            **code,
        }
        p = v1.assert_safe_output(out_dir / f"challenger_v3_week{h}.json")
        v1.write_json(p, payload)
        challengers[f"week{h}"] = {
            "path": _rel(p),
            "sha256": v2.sha256_file(p),
            "productionLoaderSource": sc.load_points_model(p).source,
            "model": base.to_dict(),
        }
        if h == CONFIRM_WEEK:
            continue
        # V3-asofAnchor (post-hoc sensitivity, §results): anchors over every priced rostered player.
        asof_model, rec_as = fit_v3(ld.obs, h, anchor=anc_ros)
        fits[f"week{h}"]["V3-asofAnchor"] = rec_as
        noshock = dataclasses.replace(base, tau_l2=0.0, tau_r2=0.0)
        models_by_week[h] = {
            V3: for_week(base, anc_app, h),
            V3_NOANCHOR: for_week(noanc, None, h),
            V3_NOSHOCK: for_week(noshock, anc_app, h),
            V3_ASOF: for_week(asof_model, anc_ros, h),
            V2N: v2_model,
            F: fallback,
        }

    eval_rows = [o for o in ld.obs if o.week in eval_weeks]
    player_models = {
        w: {k: m for k, m in mods.items() if k in PLAYER_MODELS}
        for w, mods in models_by_week.items()
    }
    scored = score_rows(eval_rows, player_models)
    team_results = _team_results(ld, eval_weeks, models_by_week, args.draws)

    dev = _block(ld, DEV_WEEKS, scored, team_results, b=args.bootstrap)
    if dev_only:
        smoke = {
            "schema": "sim-calibration-v3-study/smoke-dev-only",
            "promotes": False,
            "status": "SMOKE_DEVELOPMENT_WEEKS_ONLY",
            **code,
            "fits": fits,
            "V3-D5_development": dev,
        }
        v1.write_json(eval_path, smoke)
        return {"verdict": "SMOKE", "failingGates": dev["failingGates"], "primary": dev}
    primary = _block(ld, PRIMARY_WEEKS, scored, team_results, b=args.bootstrap)

    # C2-a: the oracle F* rescale and the week-7 F* sims.
    sum_f = sum(statistics.fmean(t["draws"][F]) for t in team_results)
    sum_r = sum(float(t["realized"]) for t in team_results)
    scale_b = sum_r / sum_f
    fstar = sc.PointsModel(ros_value_per_point=sc.FALLBACK_ROS_VALUE_PER_POINT / scale_b)
    fstar_res = []
    for t in team_results:
        if t["week"] not in PRIMARY_WEEKS:
            continue
        seed = v1.team_week_seed(t["week"], t["rid"])
        fs = v1.simulate_team_week(
            ld.pools[(t["week"], t["rid"])], ld.slots, fstar, seed, args.draws
        )
        fstar_res.append({**t, "draws": {F: t["draws"][F], FSTAR: fs, V3: t["draws"][V3]}})
    c2a = {
        "oracleScaleB": round(scale_b, 5),
        "fStarRosValuePerPoint": round(fstar.ros_value_per_point, 5),
        "note": "F* is an ORACLE rescale (uses outcomes) whose only purpose is to isolate absolute level",
        "week7": {
            "teamWeek": {
                m: {
                    k: v
                    for k, v in v2.team_metrics(fstar_res, (F, FSTAR, V3))[m].items()
                    if k != "pitSorted"
                }
                for m in (F, FSTAR, V3)
            },
            "ranking": ranking_block(fstar_res, (F, FSTAR, V3)),
        },
    }

    drift = {
        f"week{w}": {f: round(a, 3) for (ww, f), a in sorted(anc_app.items()) if ww == w}
        for w in weeks
    }
    drift_ros = {
        f"week{w}": {f: round(a, 3) for (ww, f), a in sorted(anc_ros.items()) if ww == w}
        for w in weeks
    }
    evaluation = {
        "schema": "sim-calibration-v3-study/1",
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        **code,
        "card": {"leagueKey": v1.LEAGUE_KEY, "fingerprint": ld.fingerprint},
        "split": {
            "primaryHoldout": [f"{SEASON}-w{w:02d}" for w in PRIMARY_WEEKS],
            "development": [f"{SEASON}-w{w:02d}" for w in DEV_WEEKS],
            "confirmationDeferred": f"{SEASON}-w{CONFIRM_WEEK:02d}",
            "rule": "week h fitted on 2026 weeks 1..h-1 only, each with its own as-of snapshot",
            "weekFinality": {
                f"w{w}": {"games": ld.sched[w].games, "final": ld.sched[w].final_games}
                for w in weeks
            },
            "runClockUtc": datetime.now(timezone.utc).isoformat(),
        },
        "seeds": {
            "seed": v1.SEED,
            "bootstrapB": args.bootstrap,
            "teamWeekDraws": args.draws,
            "teamWeekSeed": "v1.team_week_seed(week, rosterId), shared by every model",
            "shockStreams": "sha256(seed:week:L) per week (all rosters); sha256(seed:week:rid:R) per roster",
        },
        "challengers": challengers,
        "comparators": {
            V2N: {"path": _rel(V2_CHALLENGER), "sha256": v2_sha},
            F: {"model": "PointsModel()", "source": "fallback-constants"},
        },
        "fits": fits,
        "census": {
            "playerWeekStatus": ld.census,
            "appearedPricedByWeek": dict(Counter(o.week for o in ld.obs)),
            "evaluatedPlayerWeeks": {
                str(w): sum(1 for o in eval_rows if o.week == w) for w in eval_weeks
            },
        },
        "V3-D3_anchorsAppearedPool": drift,
        "anchorsRosteredPricedPool": drift_ros,
        "V3-D4_nflTeamCorrelation": nfl_team_tau(
            ld, models_by_week[PRIMARY_WEEKS[0]][V3], anc_app, PRIMARY_WEEKS[0]
        ),
        "primary": primary,
        "verdict": primary["verdict"],
        "failingGates": primary["failingGates"],
        "V3-D5_development": dev,
        "C2a_relativeOutcomes": c2a,
        "inputs": {
            "sleeperAndNflverseBodies": dict(sorted(ld.fetcher.receipts.items())),
            "rosSnapshots": ld.snapshots,
            "networkCalls": ld.fetcher.network_calls,
        },
    }
    v1.write_json(eval_path, evaluation)
    return evaluation


# ── downstream (C2-b, C2-c) ────────────────────────────────────────────────────────────────────


def _family_of_row(p: Mapping[str, Any]) -> str | None:
    return v1.lineup_family(
        {"position": p.get("position"), "fantasy_positions": p.get("fantasyPositions") or ()}
    )


def rostered_anchor_from_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    acc: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        for p in r.get("fullRoster") or []:
            rv = float(p.get("rosValue") or 0.0)
            fam = _family_of_row(p)
            if rv > 0 and fam:
                acc[fam].append(rv)
    return {f: statistics.fmean(v) for f, v in acc.items()}


def c2b_playoff(models: Mapping[str, sc.PointsModel]) -> dict[str, Any]:
    """Production playoff/title odds today, once per points model, through the D11 harness."""
    from unittest import mock  # noqa: PLC0415

    from scripts import evaluate_playoff_ros_once as d11  # noqa: PLC0415

    real_rows = d11._team_strength_rows
    out: dict[str, Any] = {}
    owners_order: list[str] | None = None
    for name, model in models.items():

        def _rows(*a: Any, _m: Any = model, **k: Any) -> Any:
            rows = real_rows(*a, **k)
            if isinstance(_m, V3PointsModel) and _m.anchor_by_family is not None:
                _m.anchor_by_family = rostered_anchor_from_rows(rows)
            return rows

        with mock.patch.object(d11, "_team_strength_rows", _rows):
            st = d11.current_state(v1.LEAGUE_KEY, model)
        out[name] = st
        if owners_order is None:
            owners_order = [t["ownerId"] for t in st["arms"]["incumbent"]["teams"]]
    # anonymize: team index by F's incumbent order
    idx = {o: i for i, o in enumerate(owners_order or [])}
    result: dict[str, Any] = {"models": list(models)}
    for arm in ("incumbent", "corrected"):
        per = {}
        base = {t["ownerId"]: t for t in out[F]["arms"][arm]["teams"]}
        for name in models:
            teams = {t["ownerId"]: t for t in out[name]["arms"][arm]["teams"]}
            po = {o: teams[o].get("playoffOdds") for o in idx if o in teams}
            ch = {o: teams[o].get("championshipOdds") for o in idx if o in teams}
            mean = {o: teams[o].get("mean") for o in idx if o in teams}
            dpo = [abs((po[o] or 0) - (base[o].get("playoffOdds") or 0)) for o in po if o in base]
            dch = [
                abs(ch[o] - base[o].get("championshipOdds"))
                for o in ch
                if o in base and ch[o] is not None and base[o].get("championshipOdds") is not None
            ]
            keys = sorted(idx, key=lambda o: idx[o])
            per[name] = {
                "teams": [
                    {
                        "team": idx[o],
                        "playoffOdds": po.get(o),
                        "championshipOdds": ch.get(o),
                        "weeklyMean": mean.get(o),
                    }
                    for o in keys
                ],
                "maxAbsDeltaPlayoffVsF": round(max(dpo), 4) if dpo else None,
                "meanAbsDeltaPlayoffVsF": round(statistics.fmean(dpo), 4) if dpo else None,
                "maxAbsDeltaTitleVsF": round(max(dch), 4) if dch else None,
                "kendallTauPlayoffVsF": kendall_tau(
                    [po.get(o) or 0 for o in keys], [base[o].get("playoffOdds") or 0 for o in keys]
                ),
                "kendallTauTitleVsF": kendall_tau(
                    [ch.get(o) or 0 for o in keys],
                    [base[o].get("championshipOdds") or 0 for o in keys],
                ),
                "kendallTauWeeklyMeanVsF": kendall_tau(
                    [mean.get(o) or 0 for o in keys], [base[o].get("mean") or 0 for o in keys]
                ),
                "nSimulations": out[name]["arms"][arm]["nSimulations"],
            }
        result[arm] = per
    result["availability"] = out[F].get("availability")
    result["servedArm"] = "incumbent (playoff_ros_counted_once defaults OFF)"
    return result


def c2c_utility(
    ld: Loaded, model_w7: V3PointsModel, *, draws: int, top: int = 12
) -> dict[str, Any]:
    """Drop-one BBLI ordering per week-7 roster under three configurations (production function)."""
    from src.roster_intel import best_ball_utility as bbu  # noqa: PLC0415

    fallback = sc.PointsModel()
    configs = {
        "A_commonMean_Fcv": (lambda r, pos: model_w7.mean_for(r, pos), fallback),
        "B_commonMean_V3spread": (lambda r, pos: model_w7.mean_for(r, pos), model_w7),
        "C_Fmean_Fcv": (lambda r, pos: r / sc.FALLBACK_ROS_VALUE_PER_POINT, fallback),
    }
    w = PRIMARY_WEEKS[0]
    per_roster: list[dict[str, Any]] = []
    for (ww, rid), rows in sorted(ld.full.items()):
        if ww != w:
            continue
        priced = [r for r in rows if float(r.get("rosValue") or 0.0) > 0]
        cand = sorted(priced, key=lambda r: -float(r["rosValue"]))[:top]
        res: dict[str, list[float]] = {}
        for cname, (mean_fn, model) in configs.items():

            def up(r: Mapping[str, Any], _fn: Any = mean_fn) -> Any:
                pos = str(r.get("position") or "").upper()
                return bbu.UtilityPlayer(
                    player_id=str(r["playerId"]),
                    name=str(r["playerId"]),
                    position=pos,
                    ppg=float(_fn(float(r["rosValue"]), pos)),
                    fantasy_positions=tuple(r.get("fantasyPositions") or ()),
                )

            before = [up(r) for r in priced]
            vals = []
            for c in cand:
                after = [p for p in before if p.player_id != str(c["playerId"])]
                out = bbu.evaluate_trade_utility(
                    before=before,
                    after=after,
                    slots=ld.slots,
                    roles={str(c["playerId"]): "outgoing"},
                    points_model=model,
                    draws=draws,
                    cache_scope=(cname, str(w), str(rid)),
                )
                vals.append(-float(out["impact"]["ppg"]))  # value of keeping him
            res[cname] = vals
        fams = [_family_of_row(c) for c in cand]

        def top3(v: Sequence[float]) -> set[int]:
            return set(sorted(range(len(v)), key=lambda i: -v[i])[:3])

        per_roster.append(
            {
                "candidates": len(cand),
                "families": Counter(f or "?" for f in fams),
                "tauAvsB_varianceOnly": kendall_tau(
                    res["A_commonMean_Fcv"], res["B_commonMean_V3spread"]
                ),
                "tauCvsB_fullModel": kendall_tau(res["C_Fmean_Fcv"], res["B_commonMean_V3spread"]),
                "top3OverlapAvsB": len(
                    top3(res["A_commonMean_Fcv"]) & top3(res["B_commonMean_V3spread"])
                ),
                "top3OverlapCvsB": len(
                    top3(res["C_Fmean_Fcv"]) & top3(res["B_commonMean_V3spread"])
                ),
            }
        )
    bbu.clear_before_side_cache()

    def agg(key: str) -> dict[str, Any]:
        vals = [r[key] for r in per_roster if r[key] is not None]
        return {
            "mean": round(statistics.fmean(vals), 4) if vals else None,
            "min": round(min(vals), 4) if vals else None,
        }

    return {
        "week": w,
        "rosters": len(per_roster),
        "drawsPerEvaluation": draws,
        "candidatesPerRoster": top,
        "configs": {
            "A_commonMean_Fcv": "means = V3 week-7 mu, spread = F's CV (production BBLI shape: means "
            "from the ROS ensemble, only the points model's variance used)",
            "B_commonMean_V3spread": "means = V3 week-7 mu, spread = V3",
            "C_Fmean_Fcv": "means = rosValue / 2.7, spread = F's CV (what a rosValue-mean surface sees)",
        },
        "kendallTauVarianceOnly_AvsB": agg("tauAvsB_varianceOnly"),
        "kendallTauFullModel_CvsB": agg("tauCvsB_fullModel"),
        "top3OverlapVarianceOnly": agg("top3OverlapAvsB"),
        "top3OverlapFullModel": agg("top3OverlapCvsB"),
        "perRoster": [{k: v for k, v in r.items() if k != "families"} for r in per_roster],
    }


def downstream(args: argparse.Namespace) -> dict[str, Any]:
    out_dir = v1.assert_safe_output(Path(args.out_dir))
    path = v1.assert_safe_output(out_dir / DOWNSTREAM_NAME)
    ev = json.loads((out_dir / EVAL_NAME).read_text(encoding="utf-8"))
    w8 = out_dir / f"challenger_v3_week{CONFIRM_WEEK}.json"
    w7 = out_dir / f"challenger_v3_week{PRIMARY_WEEKS[0]}.json"
    code = code_identity()
    result: dict[str, Any] = {
        "schema": "sim-calibration-v3-downstream/1",
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        **code,
        "challengerWeek8": {"path": _rel(w8), "sha256": v2.sha256_file(w8)},
    }
    if not args.skip_utility:
        args.offline = True
        ld = load(args, tuple(range(1, PRIMARY_WEEKS[0] + 1)))
        anc = anchors(ld.obs)
        m7 = for_week(load_challenger(w7), anc, PRIMARY_WEEKS[0])
        result["C2c_tradeMarginalUtility"] = c2c_utility(ld, m7, draws=args.utility_draws)
    if not args.skip_playoff:
        b = float(ev["C2a_relativeOutcomes"]["oracleScaleB"])
        v3m = load_challenger(w8)
        v3m = dataclasses.replace(v3m, tau_l2=0.0, tau_r2=0.0, anchor_by_family={})
        models = {
            F: sc.PointsModel(),
            FSTAR: sc.PointsModel(ros_value_per_point=sc.FALLBACK_ROS_VALUE_PER_POINT / b),
            V2N: v2.load_challenger(V2_CHALLENGER),
            "V3-marginal": v3m,
        }
        try:
            result["C2b_playoffAndTitle"] = c2b_playoff(models)
        except Exception as exc:  # noqa: BLE001 - reported, never hidden
            result["C2b_playoffAndTitle"] = {
                "state": "BLOCKED",
                "reason": f"{type(exc).__name__}: {exc}",
            }
    v1.write_json(path, result)
    return result


# ── CLI ────────────────────────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("evaluate", "downstream"):
        s = sub.add_parser(name)
        s.add_argument("--out-dir", default=str(OUT_DIR))
        s.add_argument("--cache-dir", default=str(v1.CACHE_DIR))
        s.add_argument("--games-cache", default=str(FRESH_GAMES_CACHE))
        s.add_argument("--offline", action="store_true")
        s.add_argument("--draws", type=int, default=v1.TEAM_WEEK_DRAWS)
        s.add_argument("--bootstrap", type=int, default=v1.BOOTSTRAP_B)
    sub.choices["evaluate"].add_argument("--out-name", default=EVAL_NAME)
    sub.choices["evaluate"].add_argument(
        "--dev-only", action="store_true", help="smoke: development weeks 5-6 only (never week 7)"
    )
    d = sub.choices["downstream"]
    d.add_argument("--utility-draws", type=int, default=400)
    d.add_argument("--skip-utility", action="store_true")
    d.add_argument("--skip-playoff", action="store_true")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.cmd == "evaluate":
            ev = evaluate(args)
            print(f"verdict: {ev['verdict']}  failing: {ev['failingGates']}")
            for k, g in ev["primary"]["gates"].items():
                print(f"  {k}: {'PASS' if g['pass'] else 'FAIL'}")
        else:
            downstream(args)
            print("downstream written")
    except v1.StudyRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
