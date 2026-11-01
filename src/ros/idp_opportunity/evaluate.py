"""Expanding-window evaluation driver and metrics (preregistration §3–§5).

The driver is the ONLY code that reads a week-``W`` outcome, and it does so to score
a projection already made.  Hyper-parameters for week ``W`` are fit from rows of weeks
``2 … W−1``; the outcomes of those fit weeks are read through the week-``W`` view, so
even the fit cannot see week ``W``.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.ros.idp_opportunity.leakage import AsOfView, SeasonData
from src.ros.idp_opportunity.model import (
    MODELS,
    Card,
    Context,
    FitRow,
    Row,
    build_context,
    build_rows,
    effective_model,
    fit_params,
    opt_float,
    played,
    project_points,
    residual_quantiles,
)
from src.ros.idp_opportunity.positions import UNKNOWN

__all__ = [
    "Prediction",
    "bootstrap_delta_mae",
    "metrics",
    "population",
    "run_season",
    "spearman",
]

FIRST_FIT_WEEK = 2


@dataclass(frozen=True)
class Prediction:
    season: int
    week: int
    pid: str
    family: str
    subgroup: str
    challenger: str | None
    model: str
    effective_model: str
    projected: float
    actual: float
    lo: float | None
    hi: float | None
    reasons: tuple[str, ...]


def population(data: SeasonData, week: int) -> list[str]:
    """Players scored for week ``week``: IDP family, played week ``week`` and at least
    one earlier week (preregistration §1).  Outcome-side selection, identical for
    every model."""
    cur = data.stats.get(week, {})
    out = []
    for pid in sorted(cur):
        if data.positions.get(pid) is None or not played(cur[pid]):
            continue
        if any(played(data.stats.get(w, {}).get(pid)) for w in data.stats if w < week):
            out.append(pid)
    return out


def _fit_rows(
    view_w: AsOfView,
    card: Card,
    rows_by_week: Mapping[int, list[Row]],
) -> list[FitRow]:
    out: list[FitRow] = []
    for w in sorted(rows_by_week):
        if w >= view_w.cutoff:
            continue
        outcomes = view_w.stats_week(w)  # guarded: w < W
        for r in rows_by_week[w]:
            line = outcomes.get(r.pid) or {}
            out.append(FitRow(r, card.points(line), opt_float(line, "def_snp")))
    return out


def run_season(
    data: SeasonData,
    card: Card,
    eval_weeks: Sequence[int],
) -> tuple[list[Prediction], dict[str, Any]]:
    """Predictions for every model on every evaluation week, plus fit diagnostics."""
    contexts: dict[int, Context] = {}
    rows_by_week: dict[int, list[Row]] = {}
    last = max(eval_weeks) if eval_weeks else 0
    for w in range(FIRST_FIT_WEEK, last + 1):
        if w not in data.stats:
            continue
        view = data.view(w)
        ctx = build_context(view, card)
        contexts[w] = ctx
        rows_by_week[w] = build_rows(view, ctx, card, population(data, w))

    preds: list[Prediction] = []
    diag: dict[str, Any] = {"weeks": {}}
    for week in sorted(eval_weeks):
        view = data.view(week)
        fit_rows = _fit_rows(view, card, {w: r for w, r in rows_by_week.items() if w < week})
        params = fit_params(fit_rows)
        quant = {m: residual_quantiles(fit_rows, m, params[m]) for m in MODELS}
        outcomes = data.stats.get(week, {})
        week_rows = rows_by_week.get(week, [])
        for r in week_rows:
            actual = card.points(outcomes.get(r.pid) or {})
            for m in MODELS:
                proj = project_points(r, m, params[m], card)
                q = quant[m].get(r.family)
                preds.append(
                    Prediction(
                        season=data.season,
                        week=week,
                        pid=r.pid,
                        family=r.family,
                        subgroup=r.subgroup,
                        challenger=r.challenger,
                        model=m,
                        effective_model=effective_model(r, m),
                        projected=proj,
                        actual=actual,
                        lo=(proj + q[0]) if q else None,
                        hi=(proj + q[1]) if q else None,
                        reasons=r.reasons,
                    )
                )
        reasons: dict[str, int] = defaultdict(int)
        for r in week_rows:
            for x in r.reasons:
                reasons[x] += 1
        diag["weeks"][str(week)] = {
            "fitRows": len(fit_rows),
            "evalRows": len(week_rows),
            "params": {m: params[m].to_dict() for m in MODELS},
            "fallbackReasons": dict(sorted(reasons.items())),
            "contextDiagnostics": dict(contexts[week].diagnostics) if week in contexts else {},
            "rowsWithVacatedSnaps": sum(1 for r in week_rows if r.x_vac > 0),
        }
    return preds, diag


# ── metrics ──────────────────────────────────────────────────────────────────


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: (values[i], i))
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    return ranks


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3 or len(x) != len(y):
        return None
    rx, ry = _ranks(x), _ranks(y)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def _top_n_hit(rows: Sequence[Prediction], n: int) -> float | None:
    if len(rows) < n or n <= 0:
        return None
    by_pred = sorted(rows, key=lambda r: (-r.projected, r.pid))[:n]
    by_act = sorted(rows, key=lambda r: (-r.actual, r.pid))[:n]
    return len({r.pid for r in by_pred} & {r.pid for r in by_act}) / n


def metrics(rows: Sequence[Prediction], top_n: int) -> dict[str, Any]:
    """MAE, RMSE, bias, 80% coverage, mean weekly Spearman, mean weekly top-N hit."""
    n = len(rows)
    if n == 0:
        return {"n": 0}
    err = [r.projected - r.actual for r in rows]
    with_iv = [r for r in rows if r.lo is not None and r.hi is not None]
    by_week: dict[int, list[Prediction]] = defaultdict(list)
    for r in rows:
        by_week[r.week].append(r)
    sp = [
        spearman([r.projected for r in v], [r.actual for r in v])
        for _, v in sorted(by_week.items())
    ]
    sp = [s for s in sp if s is not None]
    hits = [_top_n_hit(v, top_n) for _, v in sorted(by_week.items())]
    hits = [h for h in hits if h is not None]
    return {
        "n": n,
        "players": len({r.pid for r in rows}),
        "weeks": len(by_week),
        "mae": sum(abs(e) for e in err) / n,
        "rmse": math.sqrt(sum(e * e for e in err) / n),
        "bias": sum(err) / n,
        "coverage80": (
            sum(1 for r in with_iv if r.lo <= r.actual <= r.hi) / len(with_iv) if with_iv else None
        ),
        "coverageN": len(with_iv),
        "spearmanMeanWeekly": sum(sp) / len(sp) if sp else None,
        "topN": top_n,
        "topNHitMeanWeekly": sum(hits) / len(hits) if hits else None,
        "fallbackRows": sum(1 for r in rows if r.effective_model != r.model),
    }


def bootstrap_delta_mae(
    challenger: Sequence[Prediction],
    champion: Sequence[Prediction],
    *,
    resamples: int = 2000,
    seed: int = 20261101,
    levels: Iterable[float] = (0.95, 0.9833),
) -> dict[str, Any]:
    """Player-clustered bootstrap of MAE(challenger) − MAE(champion) on paired rows."""
    champ = {(r.week, r.pid): r for r in champion}
    pairs: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in challenger:
        c = champ.get((r.week, r.pid))
        if c is None:
            continue
        pairs[r.pid].append((abs(r.projected - r.actual), abs(c.projected - c.actual)))
    players = sorted(pairs)
    if not players:
        return {"n": 0}
    tot = [
        (sum(a for a, _ in pairs[p]), sum(b for _, b in pairs[p]), len(pairs[p])) for p in players
    ]

    def delta(sample: Iterable[int]) -> float:
        sa = sb = cnt = 0.0
        for i in sample:
            a, b, k = tot[i]
            sa += a
            sb += b
            cnt += k
        return (sa - sb) / cnt if cnt else math.nan

    point = delta(range(len(players)))
    rng = random.Random(seed)
    k = len(players)
    draws = sorted(delta([rng.randrange(k) for _ in range(k)]) for _ in range(resamples))
    out: dict[str, Any] = {
        "deltaMae": point,
        "nRows": sum(t[2] for t in tot),
        "nPlayers": k,
        "resamples": resamples,
        "seed": seed,
    }
    for lvl in levels:
        a = (1 - lvl) / 2
        lo = draws[max(0, int(math.floor(a * resamples)))]
        hi = draws[min(resamples - 1, int(math.ceil((1 - a) * resamples)) - 1)]
        out[f"ci{round(lvl * 100, 2)}"] = [lo, hi]
    return out


def subgroup_known(r: Prediction) -> bool:
    return r.subgroup != UNKNOWN
