"""Preregistered v2 study: a per-family-scale, within-player-CV challenger against the fallback.

Research and shadow only (RPA-LGI-008, v2). The preregistration is
``docs/league-intelligence/SIM_CALIBRATION_V2_PREREGISTRATION_2026-10-26.md``, committed alone (commit
``ad8ab042f``) before this file existed and before any v2 number was computed. This script implements
it.

Nothing in ``src/`` or ``server.py`` imports this file. It does NOT modify
``src/league_intel/sim_calibration.py``: the challenger is a RESEARCH CANDIDATE that lives here. Every
write goes through v1's ``assert_safe_output``, which refuses ``data/league_intel/`` (the directory whose
files auto-load into served playoff odds, Game Day, best-ball marginal utility and the forecast archive)
and the served artifact's file name anywhere.

What it does:

1. Loads exactly v1's data path by importing v1's functions (cache, card fingerprint, host-native scorer,
   appearance rule, exclusion census, point-in-time rosValue join). There is no second copy.
2. Fits the challenger V2 on v1's fit split:

   * a per-family ``rosValuePerPoint``, from the owner's ``build_calibration`` scale fit run on v1's
     scale-call inputs partitioned by lineup family. The owner's 30 player-week floor applies, below
     which a family takes the pooled scale.
   * a per-family within-player CV, which is v1's preregistered D2 statistic.

3. Evaluates V2, the frozen v1 candidate (V1, by sha256) and ``PointsModel()`` (F) on 2026 weeks 5-6
   with v1's metrics, team-week sim and seeds. It applies v1's SC-G1..SC-G5 with V2 in C's place, and
   SC-G1 reads PIT coverage.
4. Checks that F and V1 reproduce v1's published ``evaluation.json`` field by field.

Every output carries ``promotes: false``, the code SHA, the preregistration commit, the card fingerprint
and input hashes.

Reproduce::

    python scripts/sim_calibration_v2_study.py --offline
    python scripts/sim_calibration_v2_study.py --offline --frozen-challenger \
        docs/league-intelligence/evidence/sim_calibration_v2/challenger_v2_points_model.json \
        --expect-sha256 <sha256> --eval-weeks 7 --out-name evaluation_v2_week7.json

Exit codes: 0 when the run completed (whatever the verdict), 2 when it refused, 1 on an unexpected error.
"""

from __future__ import annotations

import argparse
import dataclasses
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
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import sim_calibration_study as v1  # noqa: E402
from src.league_intel import sim_calibration as sc  # noqa: E402
from src.ros.lineup import lineup_position  # noqa: E402

# ── preregistered constants (change only with a dated addendum to the v2 preregistration) ───────

PREREGISTRATION = "docs/league-intelligence/SIM_CALIBRATION_V2_PREREGISTRATION_2026-10-26.md"
PREREGISTRATION_COMMIT = "ad8ab042f3b5d1edbaf55f3ac34a28f0a3e8ba46"

V1_CANDIDATE = (
    REPO / "docs" / "league-intelligence" / "evidence" / "sim_calibration" / v1.CANDIDATE_NAME
)
V1_CANDIDATE_SHA256 = "cee877c2901a9f01d24222bc872e5a96c4acce795a5d239db6a696814c92fbb3"
V1_EVALUATION = (
    REPO / "docs" / "league-intelligence" / "evidence" / "sim_calibration" / "evaluation.json"
)
V1_POOLED_SCALE = 1.4764

OUT_DIR = REPO / "docs" / "league-intelligence" / "evidence" / "sim_calibration_v2"
CHALLENGER_NAME = "challenger_v2_points_model.json"
EVAL_NAME = "evaluation_v2.json"

#: A STRING schema version: ``load_points_model`` treats it as a mismatch and serves the fallback,
#: so copying this research file into the served path cannot change a served number.
CHALLENGER_SCHEMA = "research-sim-points-v2"

CHALLENGER, V1_NAME, CHAMPION = "V2", "V1", "F"
MODEL_ORDER = (CHALLENGER, V1_NAME, CHAMPION)
#: (a, b): dLS = LS_a - LS_b and dCRPS = CRPS_b - CRPS_a, so positive favours ``a``.
DELTA_PAIRS = ((CHALLENGER, CHAMPION), (CHALLENGER, V1_NAME), (V1_NAME, CHAMPION))

FAMILY_FLOOR = sc.MIN_SAMPLES_PER_POSITION  # 30 player-weeks, the owner's floor and unit
PIT80 = (0.10, 0.90)
PIT95 = (0.025, 0.975)


def _rel(p: Path) -> str:
    p = Path(p).resolve()
    return p.relative_to(REPO).as_posix() if REPO in p.parents else p.as_posix()


# ── the research challenger ────────────────────────────────────────────────────────────────────


@dataclass
class FamilyScalePointsModel(sc.PointsModel):
    """RESEARCH CANDIDATE, not served: ``PointsModel`` with a per-family scale and a per-family CV.

    The sim calls ``draw(rosValue, raw_position, rng)``. This resolves the raw directory position to a
    lineup family (``lineup_position``, then the fit window's modal-family table, then pooled), divides
    by that family's ``rosValuePerPoint``, and hands the mean to the parent's unchanged
    ``draw_from_mean``. The position-free ``mean_points`` raises, so no path can silently fall back to
    one scale.
    """

    scale_by_family: Mapping[str, float] = field(default_factory=dict)
    cv_by_family: Mapping[str, float] = field(default_factory=dict)
    raw_family: Mapping[str, str] = field(default_factory=dict)
    pooled_scale: float = sc.FALLBACK_ROS_VALUE_PER_POINT
    pooled_cv: float = sc.FALLBACK_DEFAULT_CV

    def family_for(self, position: str) -> str | None:
        raw = (position or "").strip().upper()
        fam = lineup_position(raw)
        if fam in v1.SIM_FAMILIES:
            return fam
        return self.raw_family.get(raw)

    def scale_for(self, position: str) -> float:
        fam = self.family_for(position)
        k = self.scale_by_family.get(fam) if fam else None
        return float(k) if k and k > 0 else float(self.pooled_scale)

    def cv_for(self, position: str) -> float:
        fam = self.family_for(position)
        cv = self.cv_by_family.get(fam) if fam else None
        return float(cv) if cv and cv > 0 else float(self.pooled_cv)

    def mean_for(self, ros_value: float, position: str) -> float:
        k = self.scale_for(position)
        return max(0.0, float(ros_value) / k) if k > 0 else 0.0

    def mean_points(self, ros_value: float) -> float:  # noqa: ARG002 - deliberately unusable
        raise TypeError("FamilyScalePointsModel has no position-free mean: use mean_for(rv, pos)")

    def draw(self, ros_value: float, position: str, rng: Any) -> float:
        return self.draw_from_mean(self.mean_for(ros_value, position), position, rng)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "scaleByFamily": dict(self.scale_by_family),
            "cvByFamily": dict(self.cv_by_family),
            "rawFamily": dict(self.raw_family),
            "pooledScale": self.pooled_scale,
            "pooledCv": self.pooled_cv,
            "sampleSize": self.sample_size,
        }


def challenger_payload(model: FamilyScalePointsModel, fit_receipts: Mapping[str, Any]) -> dict:
    return {
        "schemaVersion": CHALLENGER_SCHEMA,
        "kind": "RESEARCH_CANDIDATE_NOT_SERVED",
        "promotes": False,
        "model": model.to_dict(),
        "fit": dict(fit_receipts),
    }


def load_challenger(path: Path) -> FamilyScalePointsModel:
    """The research loader (never the production one, which refuses this schema)."""
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    if blob.get("schemaVersion") != CHALLENGER_SCHEMA:
        raise v1.StudyRefusal(f"{path} is not a {CHALLENGER_SCHEMA} file")
    m = blob["model"]
    return FamilyScalePointsModel(
        ros_value_per_point=float(m["pooledScale"]),
        cv_by_family={str(k): float(v) for k, v in m["cvByFamily"].items()},
        scale_by_family={str(k): float(v) for k, v in m["scaleByFamily"].items()},
        raw_family={str(k): str(v) for k, v in m["rawFamily"].items()},
        pooled_scale=float(m["pooledScale"]),
        pooled_cv=float(m["pooledCv"]),
        source="research-v2-challenger",
        sample_size=int(m.get("sampleSize") or 0),
    )


# ── fitting (fit weeks only) ───────────────────────────────────────────────────────────────────


def _fit_only(player_weeks: Iterable[v1.PlayerWeek], split: v1.Split) -> list[v1.PlayerWeek]:
    """Appeared fit player-weeks. Refuses if an evaluated week would survive the filter."""
    fit = set(split.fit)
    evaluated = set(split.holdout) | set(split.confirm)
    out = [pw for pw in player_weeks if pw.status == v1.APPEARED and (pw.season, pw.week) in fit]
    leaked = {(pw.season, pw.week) for pw in out} & evaluated
    if leaked:
        raise v1.StudyRefusal(f"evaluated weeks reached the v2 fit: {sorted(leaked)}")
    return out


def fit_family_scales(
    player_weeks: Iterable[v1.PlayerWeek],
    preseason_ros: Mapping[str, float],
    split: v1.Split,
    *,
    builder: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """§3.1: v1's scale-call inputs, partitioned by family, each through ``build_calibration``."""
    build = builder or sc.build_calibration
    fit = _fit_only(player_weeks, split)
    lines: dict[int, dict[str, dict[str, float]]] = defaultdict(dict)
    positions: dict[str, str] = {}
    family_of: dict[str, str] = {}
    ros: dict[str, float] = {}
    for pw in fit:
        positions[pw.pid] = pw.position
        if pw.season != v1.SEASON:
            continue
        rv = float(preseason_ros.get(pw.pid) or 0.0)
        if rv <= 0:
            continue
        lines[v1.week_key(pw.season, pw.week)][pw.pid] = {v1.POINTS_KEY: float(pw.points or 0.0)}
        ros[pw.pid] = rv
        family_of[pw.pid] = pw.family
    evaluated_keys = {v1.week_key(s, w) for s, w in (*split.holdout, *split.confirm)}
    if set(lines) & evaluated_keys:
        raise v1.StudyRefusal(
            f"evaluated weeks reached the scale fit: {sorted(set(lines) & evaluated_keys)}"
        )

    def _call(pids: set[str]) -> dict[str, Any]:
        sub = {wk: {p: ln for p, ln in rows.items() if p in pids} for wk, rows in lines.items()}
        sub = {wk: rows for wk, rows in sub.items() if rows}
        res = build(
            stat_lines_by_week=sub,
            positions={p: positions[p] for p in pids},
            ros_values={p: ros[p] for p in pids},
            config=dict(v1.UNIT_CONFIG),
            season=str(v1.SEASON),
        )
        return {"scale": dict(res["scale"]), "playerWeeks": int(res.get("sampleSize") or 0)}

    pooled = _call(set(ros))
    by_family: dict[str, Any] = {}
    for fam in v1.FAMILY_ORDER:
        pids = {p for p, f in family_of.items() if f == fam}
        if not pids:
            by_family[fam] = {"playerWeeks": 0, "used": "pooled", "reason": "no_scale_input"}
            by_family[fam]["rosValuePerPoint"] = pooled["scale"]["rosValuePerPoint"]
            continue
        own = _call(pids)
        ok = own["playerWeeks"] >= FAMILY_FLOOR and int(own["scale"].get("n") or 0) >= 2
        by_family[fam] = {
            **own,
            "used": "own" if ok else "pooled",
            "rosValuePerPoint": own["scale"]["rosValuePerPoint"]
            if ok
            else pooled["scale"]["rosValuePerPoint"],
        }
        if not ok:
            by_family[fam]["reason"] = "below_floor"
    return {"pooled": pooled, "byFamily": by_family, "pricedPlayers": len(ros)}


def _clamp(cv: float) -> float:
    lo, hi = sc.CV_CLAMP
    return max(lo, min(hi, cv))


def fit_family_cvs(player_weeks: Iterable[v1.PlayerWeek], split: v1.Split) -> dict[str, Any]:
    """§3.2: v1's D2 within-player CV over every appeared fit player-week, the owner's floor and clamp."""
    fit = _fit_only(player_weeks, split)
    d2 = v1.within_player_cv(fit)
    # Pooled over all families by the SAME rule: relabel every row to one family and reuse D2.
    pooled_d2 = v1.within_player_cv(dataclasses.replace(pw, family="QB") for pw in fit).get(
        "QB", {}
    )
    by_family: dict[str, Any] = {}
    for fam in v1.FAMILY_ORDER:
        entry = d2.get(fam)
        fallback = sc.FALLBACK_CV_BY_POSITION.get(fam, sc.FALLBACK_DEFAULT_CV)
        if not entry or entry["playerWeeks"] < FAMILY_FLOOR:
            by_family[fam] = {**(entry or {}), "cv": fallback, "measured": False}
            continue
        by_family[fam] = {
            **entry,
            "cv": round(_clamp(entry["withinPlayerCv"]), 4),
            "measured": True,
        }
    pooled_cv = (
        round(_clamp(pooled_d2["withinPlayerCv"]), 4)
        if pooled_d2.get("playerWeeks", 0) >= FAMILY_FLOOR
        else sc.FALLBACK_DEFAULT_CV
    )
    return {"byFamily": by_family, "pooled": {**pooled_d2, "cv": pooled_cv}}


def raw_family_table(player_weeks: Iterable[v1.PlayerWeek], split: v1.Split) -> dict[str, str]:
    """§3.3 step 2: modal fit-window family for raw positions ``lineup_position`` cannot place."""
    counts: dict[str, Counter] = defaultdict(Counter)
    for pw in _fit_only(player_weeks, split):
        raw = (pw.position or "").upper()
        if not raw or lineup_position(raw) in v1.SIM_FAMILIES or not pw.family:
            continue
        counts[raw][pw.family] += 1
    order = {f: i for i, f in enumerate(v1.FAMILY_ORDER)}
    return {
        raw: sorted(c.items(), key=lambda kv: (-kv[1], order.get(kv[0], 99)))[0][0]
        for raw, c in sorted(counts.items())
    }


def fit_challenger(
    player_weeks: Sequence[v1.PlayerWeek],
    preseason_ros: Mapping[str, float],
    split: v1.Split,
    *,
    builder: Callable[..., dict[str, Any]] | None = None,
) -> tuple[FamilyScalePointsModel, dict[str, Any]]:
    scales = fit_family_scales(player_weeks, preseason_ros, split, builder=builder)
    cvs = fit_family_cvs(player_weeks, split)
    table = raw_family_table(player_weeks, split)
    model = FamilyScalePointsModel(
        ros_value_per_point=float(scales["pooled"]["scale"]["rosValuePerPoint"]),
        scale_by_family={f: float(e["rosValuePerPoint"]) for f, e in scales["byFamily"].items()},
        cv_by_family={f: float(e["cv"]) for f, e in cvs["byFamily"].items()},
        raw_family=table,
        pooled_scale=float(scales["pooled"]["scale"]["rosValuePerPoint"]),
        pooled_cv=float(cvs["pooled"]["cv"]),
        source="research-v2-challenger",
        sample_size=sum(int(e.get("playerWeeks") or 0) for e in cvs["byFamily"].values()),
    )
    return model, {"scales": scales, "cvs": cvs, "rawFamily": table}


# ── predictions and metrics (v1's primitives) ──────────────────────────────────────────────────


def predictive(model: sc.PointsModel, ros_value: float, position: str) -> tuple[float, float]:
    """``(mu, sigma)`` exactly as the model's own ``draw`` uses them."""
    if isinstance(model, FamilyScalePointsModel):
        mu = model.mean_for(ros_value, position)
        return mu, max(0.5, mu * model.cv_for(position))
    return v1.predictive_params(model, ros_value, position)


def score_rows(
    rows: Iterable[tuple[str, int, str, str, float, float]],
    models: Mapping[str, sc.PointsModel],
    *,
    seed: int = v1.SEED,
) -> list[v1.Scored]:
    """v1's ``score_predictions`` with a per-family mean: one uniform per row, shared by all models."""
    rng = random.Random(seed)
    out: list[v1.Scored] = []
    for pid, week, position, family, ros_value, y in rows:
        u = rng.random()
        rec = v1.Scored(pid, week, family, position, ros_value, y, {}, {}, {}, {}, {}, {}, {})
        for name, model in models.items():
            mu, sigma = predictive(model, ros_value, position)
            rec.mu[name] = mu
            rec.sigma[name] = sigma
            rec.ls[name] = v1.censored_log_score(y, mu, sigma)
            rec.crps[name] = v1.censored_crps(y, mu, sigma)
            rec.cov80[name] = v1.covered(y, mu, sigma, 0.80)
            rec.cov95[name] = v1.covered(y, mu, sigma, 0.95)
            rec.pit[name] = v1.censored_pit(y, mu, sigma, u)
        out.append(rec)
    return out


def pit_coverage(pits: Sequence[float], band: tuple[float, float]) -> float:
    return statistics.fmean(1.0 if band[0] <= p <= band[1] else 0.0 for p in pits)


def binomial_central_range(n: int, p: float) -> tuple[float, float]:
    """Exact central 95% range of a Binomial(n, p) share."""
    cdf = 0.0
    lo = hi = None
    for k in range(n + 1):
        cdf += math.comb(n, k) * p**k * (1 - p) ** (n - k)
        if lo is None and cdf >= 0.025:
            lo = k
        if hi is None and cdf >= 0.975:
            hi = k
            break
    return (lo or 0) / n, (hi if hi is not None else n) / n


def ks_critical_95(n: int) -> float:
    """Asymptotic 95% Kolmogorov critical D with Stephens' correction."""
    root = math.sqrt(n)
    return 1.358 / (root + 0.12 + 0.11 / root)


def summarize(
    recs: list[v1.Scored], *, names: Sequence[str] = MODEL_ORDER, b: int, seed: int
) -> dict[str, Any]:
    """v1's ``summarize_group`` for N models (same fields), plus top-level PIT coverage and deltas."""
    if not recs:
        return {"n": 0}
    clusters = [r.pid for r in recs]
    out: dict[str, Any] = {"n": len(recs), "players": len(set(clusters))}
    ys = [max(0.0, r.y) for r in recs]
    for m in names:
        mus = [r.mu[m] for r in recs]
        pits = [r.pit[m] for r in recs]
        out[m] = {
            "meanLogScore": round(statistics.fmean(r.ls[m] for r in recs), 5),
            "meanCrps": round(statistics.fmean(r.crps[m] for r in recs), 5),
            "coverage80": round(statistics.fmean(1.0 if r.cov80[m] else 0.0 for r in recs), 5),
            "coverage95": round(statistics.fmean(1.0 if r.cov95[m] else 0.0 for r in recs), 5),
            "pitCoverage80": round(pit_coverage(pits, PIT80), 5),
            "pitCoverage95": round(pit_coverage(pits, PIT95), 5),
            "postHoc": {
                "coverage80ModelImplied": round(
                    statistics.fmean(v1.interval_content(r.mu[m], r.sigma[m], 0.80) for r in recs),
                    5,
                ),
                "coverage95ModelImplied": round(
                    statistics.fmean(v1.interval_content(r.mu[m], r.sigma[m], 0.95) for r in recs),
                    5,
                ),
                "pitCoverage80": round(pit_coverage(pits, PIT80), 5),
                "pitCoverage95": round(pit_coverage(pits, PIT95), 5),
            },
            "pit": v1.ks_uniform(pits),
            "meanPredictedMean": round(statistics.fmean(mus), 4),
            "meanRealized": round(statistics.fmean(ys), 4),
            "meanBias": round(statistics.fmean(mu - y for mu, y in zip(mus, ys)), 4),
            "realizedOverPredicted": round(statistics.fmean(ys) / statistics.fmean(mus), 4)
            if statistics.fmean(mus) > 0
            else None,
            "meanPredictedSigma": round(statistics.fmean(r.sigma[m] for r in recs), 4),
            "observedZeroShare": round(statistics.fmean(1.0 if y <= 0 else 0.0 for y in ys), 5),
            "predictedZeroMass": round(
                statistics.fmean(v1.norm_cdf(-r.mu[m] / r.sigma[m]) for r in recs), 5
            ),
        }
    deltas: dict[str, Any] = {}
    for a, bb in DELTA_PAIRS:
        if a not in names or bb not in names:
            continue
        deltas[f"{a}-{bb}"] = {
            "deltaLogScore": v1.cluster_bootstrap(
                [r.ls[a] - r.ls[bb] for r in recs], clusters, b=b, seed=seed
            ),
            "deltaCrps": v1.cluster_bootstrap(
                [r.crps[bb] - r.crps[a] for r in recs], clusters, b=b, seed=seed
            ),
        }
    out["deltas"] = deltas
    return out


def size_aware(group: Mapping[str, Any], model: str = CHALLENGER) -> dict[str, Any]:
    """V2-D2 (never gated): KS p, D against the 95% critical value, PIT coverage against Binomial."""
    n = int(group["n"])
    g = group[model]
    lo80, hi80 = binomial_central_range(n, 0.80)
    lo95, hi95 = binomial_central_range(n, 0.95)
    crit = ks_critical_95(n)
    return {
        "n": n,
        "ksD": g["pit"]["ksD"],
        "ksP": g["pit"]["ksP"],
        "ksCritical95": round(crit, 5),
        "ksDExceedsCritical95": g["pit"]["ksD"] > crit,
        "pitCoverage80": g["pitCoverage80"],
        "binomial95Range80": [round(lo80, 5), round(hi80, 5)],
        "pitCoverage80InsideBinomialRange": lo80 - 1e-9 <= g["pitCoverage80"] <= hi80 + 1e-9,
        "pitCoverage95": g["pitCoverage95"],
        "binomial95Range95": [round(lo95, 5), round(hi95, 5)],
        "pitCoverage95InsideBinomialRange": lo95 - 1e-9 <= g["pitCoverage95"] <= hi95 + 1e-9,
    }


def team_metrics(results: list[dict[str, Any]], names: Sequence[str] = MODEL_ORDER) -> dict:
    """v1's ``team_week_metrics`` for N models (same uniforms, same fields)."""
    rng = random.Random(v1.SEED + 1)
    out: dict[str, Any] = {"n": len(results)}
    us = [rng.random() for _ in results]
    for m in names:
        crps, pits, c80, c95, bias = [], [], [], [], []
        for item, u in zip(results, us):
            x = sorted(item["draws"][m])
            y = float(item["realized"])
            crps.append(v1.sample_crps(x, y))
            pits.append(v1.sample_pit(x, y, u))
            c80.append(v1.sample_quantile(x, 0.10) <= y <= v1.sample_quantile(x, 0.90))
            c95.append(v1.sample_quantile(x, 0.025) <= y <= v1.sample_quantile(x, 0.975))
            bias.append(statistics.fmean(x) - y)
        out[m] = {
            "meanCrps": round(statistics.fmean(crps), 4) if crps else None,
            "coverage80": round(statistics.fmean(1.0 if c else 0.0 for c in c80), 5)
            if c80
            else None,
            "coverage95": round(statistics.fmean(1.0 if c else 0.0 for c in c95), 5)
            if c95
            else None,
            "meanBias": round(statistics.fmean(bias), 4) if bias else None,
            "pitSorted": [round(p, 4) for p in sorted(pits)],
            "pit": v1.ks_uniform(pits),
        }
    return out


# ── gates ──────────────────────────────────────────────────────────────────────────────────────


def apply_gates_v2(
    player: Mapping[str, Any],
    team: Mapping[str, Any],
    *,
    challenger: str = CHALLENGER,
    champion: str = CHAMPION,
) -> dict[str, Any]:
    """v1's SC-G1..SC-G5 with ``challenger`` in C's place; SC-G1 reads PIT coverage (prereg §6)."""
    fams = player["byFamily"]
    gated = [f for f in v1.FAMILY_ORDER if fams.get(f, {}).get("n", 0) >= v1.GATE_MIN_N]
    pooled = player["pooled"]
    key = f"{challenger}-{champion}"

    def _g1(cov80_field: str, cov95_field: str) -> list[str]:
        return [
            f
            for f in gated
            if not (
                v1._within(fams[f][challenger][cov80_field], v1.G1_COV80)
                and v1._within(fams[f][challenger][cov95_field], v1.G1_COV95)
            )
        ]

    g1_fail = _g1("pitCoverage80", "pitCoverage95")
    g1_literal_fail = _g1("coverage80", "coverage95")

    def _ci_gate(metric: str) -> tuple[bool, list[str], dict[str, Any]]:
        p = pooled["deltas"][key][metric]
        ok = p["mean"] is not None and p["mean"] > 0 and p["ci95"][0] > 0
        worse = [f for f in gated if fams[f]["deltas"][key][metric]["ci95"][1] < 0]
        return ok and not worse, worse, {"pooled": p}

    g2_pass, g2_worse, g2_detail = _ci_gate("deltaLogScore")
    g3_pass, g3_worse, g3_detail = _ci_gate("deltaCrps")

    g4_fail = [f for f in gated if (fams[f][challenger]["pit"]["ksD"] or 1.0) > v1.G4_MAX_KS_D]
    g4_pooled_ok = pooled[challenger]["pit"]["ksD"] < pooled[champion]["pit"]["ksD"]

    tc, tf = team[challenger], team[champion]
    g5_pass = (
        v1._within(tc["coverage80"], v1.G5_COV80)
        and tc["coverage95"] is not None
        and tc["coverage95"] >= v1.G5_MIN_COV95 - 1e-9
        and tc["meanCrps"] is not None
        and tf["meanCrps"] is not None
        and tc["meanCrps"] <= tf["meanCrps"]
    )

    gates = {
        "SC-G1": {
            "pass": not g1_fail,
            "gatedFamilies": gated,
            "failingFamilies": g1_fail,
            "rule": (
                f"{challenger} PIT coverage80 (PIT in {list(PIT80)}) in {list(v1.G1_COV80)} and PIT "
                f"coverage95 (PIT in {list(PIT95)}) in {list(v1.G1_COV95)}, every gated family"
            ),
            "nonGatingLiteralV1": {
                "pass": not g1_literal_fail,
                "failingFamilies": g1_literal_fail,
                "rule": "v1's censored central-interval coverage, reported for comparability only",
            },
        },
        "SC-G2": {
            "pass": g2_pass,
            "familiesSignificantlyWorse": g2_worse,
            **g2_detail,
            "rule": f"pooled mean dLS ({key}) > 0, CI lower > 0; no gated family CI upper < 0",
        },
        "SC-G3": {
            "pass": g3_pass,
            "familiesSignificantlyWorse": g3_worse,
            **g3_detail,
            "rule": f"pooled mean dCRPS ({champion} - {challenger}) > 0, CI lower > 0; no gated family CI upper < 0",
        },
        "SC-G4": {
            "pass": not g4_fail and g4_pooled_ok,
            "failingFamilies": g4_fail,
            "pooledKsD": {
                challenger: pooled[challenger]["pit"]["ksD"],
                champion: pooled[champion]["pit"]["ksD"],
            },
            "rule": f"{challenger} ks D <= {v1.G4_MAX_KS_D} every gated family; pooled D below {champion}'s",
        },
        "SC-G5": {
            "pass": bool(g5_pass),
            challenger: {k: tc[k] for k in ("coverage80", "coverage95", "meanCrps", "meanBias")},
            champion: {k: tf[k] for k in ("coverage80", "coverage95", "meanCrps", "meanBias")},
            "n": team["n"],
            "rule": (
                f"{challenger} coverage80 in {list(v1.G5_COV80)}, coverage95 >= {v1.G5_MIN_COV95}, "
                f"meanCrps <= {champion}'s"
            ),
        },
    }
    all_pass = all(g["pass"] for g in gates.values())
    return {
        "gates": gates,
        "verdict": "CHALLENGER_BEATS_FALLBACK" if all_pass else "CHALLENGER_DOES_NOT_BEAT_FALLBACK",
        "failingGates": [k for k, g in gates.items() if not g["pass"]],
    }


# ── descriptive analyses (never gated) ─────────────────────────────────────────────────────────


def scale_estimators_fit_window(
    player_weeks: Sequence[v1.PlayerWeek],
    preseason_ros: Mapping[str, float],
    split: v1.Split,
    owner_k: Mapping[str, float],
) -> dict[str, Any]:
    """V2-D3, fit window ONLY: the owner's inverse fit, a forward fit and a ratio estimator, per family."""
    fit = [pw for pw in _fit_only(player_weeks, split) if pw.season == v1.SEASON]
    per_player: dict[str, list[float]] = defaultdict(list)
    fam: dict[str, str] = {}
    for pw in fit:
        if float(preseason_ros.get(pw.pid) or 0.0) > 0:
            per_player[pw.pid].append(float(pw.points or 0.0))
            fam[pw.pid] = pw.family
    fit_weeks = {(v1.SEASON, w) for w in v1.FIT_2026_WEEKS}
    out: dict[str, Any] = {}
    for f in v1.FAMILY_ORDER:
        pairs = [
            (float(preseason_ros[p]), statistics.fmean(pts))
            for p, pts in sorted(per_player.items())
            if fam[p] == f and statistics.fmean(pts) > 0
        ]
        if len(pairs) < 2:
            continue
        srr = sum(r * r for r, _ in pairs)
        sry = sum(r * y for r, y in pairs)
        k_fwd = srr / sry if sry > 0 else None
        k_ratio = sum(r for r, _ in pairs) / sum(y for _, y in pairs)
        row: dict[str, Any] = {"players": len(pairs)}
        for name, k in (("ownerInverse", owner_k.get(f)), ("forward", k_fwd), ("ratio", k_ratio)):
            if not k:
                row[name] = None
                continue
            chk = v1.scale_check_by_family(fit, preseason_ros, float(k), fit_weeks).get(f, {})
            row[name] = {
                "rosValuePerPoint": round(float(k), 4),
                "fitWindowRealizedOverPredicted": chk.get("realizedOverPredicted"),
            }
        out[f] = row
    return out


def residual_cv_fit_window(
    player_weeks: Sequence[v1.PlayerWeek],
    preseason_ros: Mapping[str, float],
    split: v1.Split,
    model: FamilyScalePointsModel,
) -> dict[str, Any]:
    """V2-D7: sqrt(mean((y - r/k_f)^2)) / mean(r/k_f) over the priced 2026 fit player-weeks."""
    acc: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for pw in _fit_only(player_weeks, split):
        rv = float(preseason_ros.get(pw.pid) or 0.0)
        if pw.season != v1.SEASON or rv <= 0:
            continue
        acc[pw.family].append((float(pw.points or 0.0), model.mean_for(rv, pw.position)))
    out = {}
    for f in v1.FAMILY_ORDER:
        items = acc.get(f) or []
        if not items:
            continue
        mean_mu = statistics.fmean(m for _, m in items)
        rmse = math.sqrt(statistics.fmean((y - m) ** 2 for y, m in items))
        out[f] = {
            "n": len(items),
            "residualCv": round(rmse / mean_mu, 4) if mean_mu > 0 else None,
            "withinPlayerCv": model.cv_by_family.get(f),
        }
    return out


#: (v2 field path, v1 field path) pairs compared by the reproduction check, per player group.
_REPRO_FIELDS = (
    "meanLogScore",
    "meanCrps",
    "coverage80",
    "coverage95",
    "meanPredictedMean",
    "meanRealized",
    "meanBias",
    "realizedOverPredicted",
    "observedZeroShare",
    "predictedZeroMass",
)


def reproduction_check(v2_eval: Mapping[str, Any], v1_eval: Mapping[str, Any]) -> dict[str, Any]:
    """V2-D6: F and V1 must equal v1's published numbers field by field (v1's C is our V1)."""
    mismatches: list[dict[str, Any]] = []
    compared = 0

    def _cmp(where: str, a: Any, b: Any) -> None:
        nonlocal compared
        compared += 1
        if a != b:
            mismatches.append({"field": where, "v2Run": a, "v1Published": b})

    groups = [("pooled", v2_eval["playerLevel"]["pooled"], v1_eval["playerLevel"]["pooled"])]
    for f, g in v1_eval["playerLevel"]["byFamily"].items():
        groups.append((f, v2_eval["playerLevel"]["byFamily"].get(f, {}), g))
    for name, g2, g1 in groups:
        _cmp(f"{name}.n", g2.get("n"), g1.get("n"))
        for ours, theirs in ((V1_NAME, "C"), (CHAMPION, "F")):
            for k in _REPRO_FIELDS:
                _cmp(
                    f"{name}.{ours}.{k}", (g2.get(ours) or {}).get(k), (g1.get(theirs) or {}).get(k)
                )
            _cmp(
                f"{name}.{ours}.pit.ksD",
                ((g2.get(ours) or {}).get("pit") or {}).get("ksD"),
                ((g1.get(theirs) or {}).get("pit") or {}).get("ksD"),
            )
            for k in ("pitCoverage80", "pitCoverage95"):
                _cmp(
                    f"{name}.{ours}.postHoc.{k}",
                    ((g2.get(ours) or {}).get("postHoc") or {}).get(k),
                    ((g1.get(theirs) or {}).get("postHoc") or {}).get(k),
                )
        d = (g2.get("deltas") or {}).get(f"{V1_NAME}-{CHAMPION}") or {}
        for k in ("deltaLogScore", "deltaCrps"):
            _cmp(f"{name}.{V1_NAME}-{CHAMPION}.{k}", d.get(k), g1.get(k))
    for block in ("teamWeek", "D4_teamWeekNoAvailabilityFilter"):
        t2, t1 = v2_eval.get(block) or {}, v1_eval.get(block) or {}
        if not t1:
            continue
        for ours, theirs in ((V1_NAME, "C"), (CHAMPION, "F")):
            for k in ("meanCrps", "coverage80", "coverage95", "meanBias", "pitSorted"):
                _cmp(
                    f"{block}.{ours}.{k}",
                    (t2.get(ours) or {}).get(k),
                    (t1.get(theirs) or {}).get(k),
                )
    _cmp("census.D5.total", v2_eval["census"]["D5"]["total"], v1_eval["census"]["D5"]["total"])
    _cmp(
        "census.evaluatedPlayerWeeks",
        v2_eval["census"]["evaluatedPlayerWeeks"],
        v1_eval["census"]["evaluatedPlayerWeeks"],
    )
    _cmp(
        "teamWeek.realizedCrossCheck",
        v2_eval["teamWeek"]["realizedCrossCheck"],
        v1_eval["teamWeek"]["realizedCrossCheck"],
    )
    pooled_k = (((v2_eval.get("fit") or {}).get("scales") or {}).get("pooled") or {}).get("scale")
    if pooled_k is not None:
        _cmp("fit.pooledScale", pooled_k.get("rosValuePerPoint"), V1_POOLED_SCALE)
    return {
        "fieldsCompared": compared,
        "mismatches": mismatches,
        "reproduced": not mismatches,
    }


# ── provenance ─────────────────────────────────────────────────────────────────────────────────


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args], cwd=REPO, capture_output=True, text=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def code_identity() -> dict[str, Any]:
    sha = _git("rev-parse", "HEAD")
    dirty = _git(
        "status",
        "--porcelain",
        "--",
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
        prereg_is_ancestor = {0: True, 1: False}.get(anc)
    except (OSError, subprocess.SubprocessError):
        prereg_is_ancestor = None
    prereg_time = _git("log", "-1", "--format=%cI", PREREGISTRATION_COMMIT)
    return {
        "codeSha": sha or "UNKNOWN",
        "studyCodeDirty": None if dirty is None else bool(dirty),
        "scriptSha256": v1.sha256_file(Path(__file__)),
        "v1ScriptSha256": v1.sha256_file(Path(v1.__file__)),
        "preregistration": {
            "path": PREREGISTRATION,
            "commit": PREREGISTRATION_COMMIT,
            "committedAt": prereg_time,
            "isAncestorOfCodeSha": prereg_is_ancestor,
        },
    }


# ── driver ─────────────────────────────────────────────────────────────────────────────────────


def run(args: argparse.Namespace) -> dict[str, Any]:
    split = v1.preregistered_split()
    eval_weeks = tuple(int(w) for w in args.eval_weeks)
    for w in eval_weeks:
        if (v1.SEASON, w) in set(split.fit):
            raise v1.StudyRefusal(f"eval week {w} is a fit week")
    out_dir = v1.assert_safe_output(Path(args.out_dir))
    challenger_path = v1.assert_safe_output(out_dir / CHALLENGER_NAME)
    eval_path = v1.assert_safe_output(out_dir / args.out_name)

    v1_cand = Path(args.v1_candidate)
    v1_sha = v1.sha256_file(v1_cand)
    if v1_sha != V1_CANDIDATE_SHA256:
        raise v1.StudyRefusal(
            f"v1 candidate sha256 {v1_sha} != preregistered {V1_CANDIDATE_SHA256}"
        )

    f = v1.CachedFetcher(Path(args.cache_dir), offline=args.offline)
    league = f.get_json(f"{v1.SLEEPER}/league/{v1.LEAGUE_ID}")
    card = {str(k): float(v) for k, v in (league.get("scoring_settings") or {}).items()}
    fingerprint = v1.scoring_fingerprint(league.get("scoring_settings"))
    if fingerprint != v1.PINNED_SCORING_FINGERPRINT:
        raise v1.StudyRefusal(
            f"live card fingerprint {fingerprint} != pinned {v1.PINNED_SCORING_FINGERPRINT}: numbers void"
        )
    slots = v1.starter_slots_from_roster_positions(league.get("roster_positions"))
    prev_id = str(league.get("previous_league_id") or "")
    if not prev_id:
        raise v1.StudyRefusal("live league carries no previous_league_id; 2025 rosters unavailable")

    games = f.get_csv(v1.NFLVERSE_GAMES, Path(args.cache_dir) / "nflverse" / "schedules__games.csv")
    sched = v1.schedule_by_week(games, v1.SEASON)
    week_status = {
        f"{v1.SEASON}-w{w:02d}": {
            "games": s.games,
            "finalGames": s.final_games,
            "final": s.is_final,
        }
        for w, s in sorted(sched.items())
        if w in (*v1.HOLDOUT_2026_WEEKS, *v1.CONFIRM_2026_WEEKS)
    }
    for w in eval_weeks:
        if w not in sched or not sched[w].is_final:
            s = sched.get(w)
            raise v1.StudyRefusal(
                f"2026 week {w} is not final ({s.final_games if s else 0}/{s.games if s else 0} games): "
                "preregistration §2 admits only final weeks"
            )

    directory = f.get_json(f"{v1.SLEEPER}/players/nfl")

    weeks_needed: list[tuple[int, int]] = list(split.fit)
    weeks_needed += [(v1.SEASON, w) for w in eval_weeks]
    stats: dict[tuple[int, int], dict[str, Any]] = {}
    for season in sorted({s for s, _ in weeks_needed}):
        wks = [w for s, w in weeks_needed if s == season]
        got = sc.fetch_stat_lines(str(season), wks, fetcher=f.get_json, sleep_s=0.0)
        missing = sorted(set(wks) - set(got))
        if missing:
            raise v1.StudyRefusal(f"stat lines unavailable for {season} weeks {missing}")
        for w, body in got.items():
            stats[(season, w)] = body

    rosters: dict[tuple[int, int], dict[int, list[str]]] = {}
    for season, w in weeks_needed:
        lid = v1.LEAGUE_ID if season == v1.SEASON else prev_id
        rosters[(season, w)] = v1.rostered_by_week(
            f.get_json(f"{v1.SLEEPER}/league/{lid}/matchups/{w}")
        )

    player_weeks: list[v1.PlayerWeek] = []
    no_roster_weeks: list[str] = []
    for season, w in weeks_needed:
        body = stats[(season, w)]
        pids = sorted({p for lst in rosters[(season, w)].values() for p in lst})
        if not pids:
            no_roster_weeks.append(f"{season}-w{w:02d}")
            continue
        for pid in pids:
            player_weeks.append(
                v1.classify_player_week(pid, body.get(pid), directory.get(pid), card, season, w)
            )

    snapshots: dict[str, dict[str, Any]] = {}

    def _snap(label: str, cutoff: datetime) -> list[dict[str, Any]]:
        p = v1.snapshot_before(cutoff)
        snapshots[label] = {
            "file": _rel(p),
            "sha256": v1.sha256_file(p),
            "cutoffUtc": cutoff.isoformat(),
        }
        return v1.load_snapshot_players(p)

    code = code_identity()
    pre_players = _snap("preseason", sched[1].first_kickoff_utc)
    fit26 = [(v1.SEASON, w) for w in v1.FIT_2026_WEEKS]
    preseason_ros: dict[str, float] = {}
    for key in fit26:
        for rows in v1.as_of_full_rosters(rosters[key], directory, pre_players, slots).values():
            for r in rows:
                if float(r.get("rosValue") or 0.0) > 0:
                    preseason_ros[str(r["playerId"])] = float(r["rosValue"])

    if args.frozen_challenger:
        src = Path(args.frozen_challenger)
        ch_sha = v1.sha256_file(src)
        if args.expect_sha256 and ch_sha != args.expect_sha256:
            raise v1.StudyRefusal(
                f"frozen challenger sha256 {ch_sha} != expected {args.expect_sha256}"
            )
        challenger = load_challenger(src)
        challenger_record = {"path": _rel(src), "sha256": ch_sha, "frozen": True}
        fit_block: dict[str, Any] = {"refit": False}
    else:
        fitted, receipts = fit_challenger(player_weeks, preseason_ros, split)
        payload = challenger_payload(fitted, receipts)
        payload["study"] = {
            "promotes": False,
            "status": "RESEARCH_CANDIDATE_NOT_SERVED",
            "cardFingerprint": fingerprint,
            "fitWeeks": [f"{s}-w{w:02d}" for s, w in split.fit],
            "scaleFitWeeks": [f"{s}-w{w:02d}" for s, w in fit26],
            "rosSnapshot": snapshots["preseason"],
            **code,
        }
        v1.write_json(challenger_path, payload)
        challenger = load_challenger(challenger_path)
        challenger_record = {
            "path": _rel(challenger_path),
            "sha256": v1.sha256_file(challenger_path),
            "frozen": False,
            "productionLoaderSource": sc.load_points_model(challenger_path).source,
        }
        fit_block = {
            "refit": True,
            **receipts,
            "V2-D3_scaleEstimatorsFitWindow": scale_estimators_fit_window(
                player_weeks,
                preseason_ros,
                split,
                {
                    fam: e["scale"]["rosValuePerPoint"]
                    for fam, e in receipts["scales"]["byFamily"].items()
                    if "scale" in e
                },
            ),
            "V2-D7_residualCvFitWindow": residual_cv_fit_window(
                player_weeks, preseason_ros, split, challenger
            ),
        }

    v1_model = sc.load_points_model(v1_cand)
    if v1_model.source != "calibrated":
        raise v1.StudyRefusal(f"v1 candidate did not load as calibrated (source={v1_model.source})")
    models: dict[str, sc.PointsModel] = {
        CHALLENGER: challenger,
        V1_NAME: v1_model,
        CHAMPION: sc.PointsModel(),
    }

    eval_rows: list[tuple[str, int, str, str, float, float]] = []
    unpriced = Counter()
    team_results: list[dict[str, Any]] = []
    team_results_all: list[dict[str, Any]] = []
    realized_checks = {"teamWeeks": 0, "matchWithin0.01": 0, "maxAbsDelta": 0.0}
    drift: dict[str, list[tuple[float, float]]] = defaultdict(list)
    status_by = {(pw.season, pw.week, pw.pid): pw for pw in player_weeks}
    for w in eval_weeks:
        snap_players = _snap(f"week{w}", sched[w].first_kickoff_utc)
        full = v1.as_of_full_rosters(rosters[(v1.SEASON, w)], directory, snap_players, slots)
        pre_full = v1.as_of_full_rosters(rosters[(v1.SEASON, w)], directory, pre_players, slots)
        pre_rv = {
            str(r["playerId"]): float(r.get("rosValue") or 0.0)
            for rows in pre_full.values()
            for r in rows
        }
        matchups = f.get_json(f"{v1.SLEEPER}/league/{v1.LEAGUE_ID}/matchups/{w}")
        awarded = {int(m["roster_id"]): float(m.get("points") or 0.0) for m in matchups}
        for rid, rows in sorted(full.items()):
            roster_pids = rosters[(v1.SEASON, w)][rid]
            pts_by_pid = {
                pid: float(status_by[(v1.SEASON, w, pid)].points)
                for pid in roster_pids
                if (v1.SEASON, w, pid) in status_by
                and status_by[(v1.SEASON, w, pid)].points is not None
            }
            pool_appeared = []
            for r in rows:
                pid = str(r["playerId"])
                pw = status_by.get((v1.SEASON, w, pid))
                if pw is None or pw.status != v1.APPEARED:
                    continue
                pool_appeared.append(r)
                rv = float(r.get("rosValue") or 0.0)
                if rv <= 0:
                    unpriced[f"{v1.SEASON}-w{w:02d}"] += 1
                    continue
                eval_rows.append(
                    (
                        pid,
                        w,
                        str(r.get("position") or pw.position).upper(),
                        pw.family,
                        rv,
                        float(pw.points),
                    )
                )
                if pre_rv.get(pid, 0.0) > 0:
                    drift[f"{pw.family}|w{w}"].append((rv, pre_rv[pid]))
            own = v1.realized_best_ball_total(roster_pids, pts_by_pid, directory, slots)
            d = abs(own - awarded.get(rid, float("nan")))
            realized_checks["teamWeeks"] += 1
            if d <= 0.01:
                realized_checks["matchWithin0.01"] += 1
            realized_checks["maxAbsDelta"] = round(max(realized_checks["maxAbsDelta"], d), 4)
            seed = v1.team_week_seed(w, rid)
            team_results.append(
                {
                    "realized": awarded[rid],
                    "draws": {
                        m: v1.simulate_team_week(pool_appeared, slots, mod, seed, args.draws)
                        for m, mod in models.items()
                    },
                }
            )
            if not args.skip_sensitivity:
                team_results_all.append(
                    {
                        "realized": awarded[rid],
                        "draws": {
                            m: v1.simulate_team_week(rows, slots, mod, seed, args.draws)
                            for m, mod in models.items()
                        },
                    }
                )

    scored = score_rows(eval_rows, models)
    by_fam: dict[str, list[v1.Scored]] = defaultdict(list)
    for r in scored:
        by_fam[r.family].append(r)
    player = {
        "pooled": summarize(scored, b=args.bootstrap, seed=v1.SEED),
        "byFamily": {
            fam: summarize(by_fam[fam], b=args.bootstrap, seed=v1.SEED)
            for fam in v1.FAMILY_ORDER
            if by_fam.get(fam)
        },
    }
    team = team_metrics(team_results)
    decision = apply_gates_v2(player, team)

    drift_out: dict[str, Any] = {}
    for key, items in sorted(drift.items()):
        fam, wk = key.split("|")
        a = statistics.fmean(x for x, _ in items)
        p = statistics.fmean(y for _, y in items)
        drift_out.setdefault(fam, {})[wk] = {
            "n": len(items),
            "meanAsOfRosValue": round(a, 3),
            "meanPreseasonRosValue": round(p, 3),
            "asOfOverPreseason": round(a / p, 4) if p > 0 else None,
        }

    evaluation: dict[str, Any] = {
        "schema": "sim-calibration-v2-study/1",
        "promotes": False,
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        **code,
        "card": {
            "leagueKey": v1.LEAGUE_KEY,
            "fingerprint": fingerprint,
            "pinned": v1.PINNED_SCORING_FINGERPRINT,
            "source": f"GET /v1/league/{v1.LEAGUE_ID} scoring_settings",
        },
        "split": {
            "fit": [f"{s}-w{w:02d}" for s, w in split.fit],
            "evaluated": [f"{v1.SEASON}-w{w:02d}" for w in eval_weeks],
            "confirmation": [f"{s}-w{w:02d}" for s, w in split.confirm],
            "weekStatusFromScheduleBody": week_status,
            "runClockUtc": datetime.now(timezone.utc).isoformat(),
            "rostersWithoutPlayersExcludedWeeks": no_roster_weeks,
        },
        "seeds": {
            "seed": v1.SEED,
            "bootstrapB": args.bootstrap,
            "teamWeekDraws": args.draws,
            "teamWeekSeed": "int(sha256(f'{seed}:{week}:{rosterId}')[:12], 16), shared by V2, V1 and F",
            "pitUniforms": "random.Random(seed) one per evaluated row in row order, shared by all models",
        },
        "challenger": challenger_record,
        "comparators": {
            V1_NAME: {"path": _rel(v1_cand), "sha256": v1_sha, "loadedSource": v1_model.source},
            CHAMPION: {"model": "PointsModel()", "source": "fallback-constants"},
        },
        "models": {m: mod.to_dict() for m, mod in models.items()},
        "fit": fit_block,
        "census": {
            "D5": v1._census(player_weeks),
            "evaluatedPlayerWeeks": len(scored),
            "unpricedEvaluatedPlayerWeeks": dict(unpriced),
        },
        "playerLevel": player,
        "V2-D2_sizeAwareReading": {
            fam: size_aware(player["byFamily"][fam])
            for fam in decision["gates"]["SC-G1"]["gatedFamilies"]
        },
        "V2-D5_snapshotDrift": drift_out,
        "teamWeek": {
            "pool": "oracle availability: rostered players who appeared that week",
            "realizedCrossCheck": realized_checks,
            **team,
        },
        "D4_teamWeekNoAvailabilityFilter": team_metrics(team_results_all)
        if team_results_all
        else None,
        **decision,
        "inputs": {
            "sleeperAndNflverseBodies": dict(sorted(f.receipts.items())),
            "rosSnapshots": snapshots,
            "v1Candidate": {"path": _rel(v1_cand), "sha256": v1_sha},
            "networkCalls": f.network_calls,
        },
    }
    if (
        not args.frozen_challenger
        and Path(args.v1_evaluation).exists()
        and eval_weeks == v1.HOLDOUT_2026_WEEKS
    ):
        v1_eval = json.loads(Path(args.v1_evaluation).read_text(encoding="utf-8"))
        evaluation["V2-D6_reproductionOfV1"] = {
            "v1Evaluation": _rel(Path(args.v1_evaluation)),
            "v1EvaluationSha256": v1.sha256_file(Path(args.v1_evaluation)),
            **reproduction_check(evaluation, v1_eval),
        }
    v1.write_json(eval_path, evaluation)
    return evaluation


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out-dir", default=str(OUT_DIR))
    p.add_argument("--out-name", default=EVAL_NAME)
    p.add_argument("--cache-dir", default=str(v1.CACHE_DIR))
    p.add_argument("--offline", action="store_true", help="never touch the network")
    p.add_argument("--eval-weeks", nargs="+", type=int, default=list(v1.HOLDOUT_2026_WEEKS))
    p.add_argument("--frozen-challenger", default=None, help="evaluate this file; no refit")
    p.add_argument(
        "--expect-sha256", default=None, help="refuse unless the frozen file hashes to this"
    )
    p.add_argument("--v1-candidate", default=str(V1_CANDIDATE))
    p.add_argument("--v1-evaluation", default=str(V1_EVALUATION))
    p.add_argument("--draws", type=int, default=v1.TEAM_WEEK_DRAWS)
    p.add_argument("--bootstrap", type=int, default=v1.BOOTSTRAP_B)
    p.add_argument("--skip-sensitivity", action="store_true", help="skip D4 (debug only)")
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        ev = run(args)
    except v1.StudyRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    print(f"verdict: {ev['verdict']}  failing: {ev['failingGates']}")
    for k, g in ev["gates"].items():
        print(f"  {k}: {'PASS' if g['pass'] else 'FAIL'}")
    repro = ev.get("V2-D6_reproductionOfV1")
    if repro is not None:
        print(
            f"  reproduction of v1: {repro['reproduced']} ({len(repro['mismatches'])} mismatches)"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
