"""Lineup duplication: how many OTHER entries share this exact lineup (DFS-MOD-06).

Two models, always both reported:

* **naive** (``duplication.naive_product``) — ``E[copies] = N × Π own_i``,
  ownership as a fraction.  The textbook baseline; kept because a better model
  has to beat it.
* **parametric** (``duplication.loglinear``) —
  ``E[copies] = N × exp(a) × Π own_i^b × exp(c × salary_left_in_$1K)``.  With
  ``a=0, b=1, c=0`` it IS the naive model, so the fit can only move away from
  the baseline where the data say so.  Salary left matters because fields
  crowd onto max-salary builds.

Fitting uses the results files' duplication sample (``results.duplication``).
Those files only list lineups somebody entered, so the likelihood is
ZERO-TRUNCATED Poisson — treating unseen lineups as absent rather than as zeros
would bias every parameter.  Single-entry lineups are a weighted sample
(weight = inverse sampling rate).  Scored on a HOLDOUT, never the fit data:
promotion over the naive baseline goes through ``pit.promote``.
"""

from __future__ import annotations

import math
from typing import Any

NAIVE_ID = "duplication.naive_product"
MODEL_ID = "duplication.loglinear"
NAIVE_PARAMS = {"a": 0.0, "b": 1.0, "c": 0.0}
_OWN_FLOOR = 0.001  # 0.1%: a projected 0% player still appears in real fields; log(0) is undefined


def features(
    players: list[str], own_pct: dict[str, float], salary: dict[str, int], cap: int
) -> tuple[float, float] | None:
    """(Σ log ownership fraction, salary left in $1K), or None when any ownership is unknown."""
    if any(own_pct.get(p) is None for p in players):
        return None
    lpo = sum(math.log(max(own_pct[p] / 100.0, _OWN_FLOOR)) for p in players)
    left = (cap - sum(salary[p] for p in players)) / 1000.0
    return lpo, left


def expected_copies(field_size: int, feats: tuple[float, float], params: dict[str, float]) -> float:
    lpo, left = feats
    return field_size * math.exp(params["a"] + params["b"] * lpo + params["c"] * left)


def estimate(
    players: list[str],
    own_pct: dict[str, float],
    salary: dict[str, int],
    cap: int,
    field_size: int,
    params: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Expected OTHER entries identical to this lineup, under naive and (if given) fitted params."""
    f = features(players, own_pct, salary, cap)
    if f is None:
        return {"state": "unavailable", "reason": "ownership unknown for a player in the lineup"}
    others = max(field_size - 1, 0)
    out = {"state": "estimated", "naive": round(expected_copies(others, f, NAIVE_PARAMS), 6)}
    if params:
        out["fitted"] = round(expected_copies(others, f, params), 6)
        out["params"] = params
    out["pDuplicated"] = {  # P(at least one other copy) under Poisson
        k: round(1.0 - math.exp(-v), 6) for k, v in out.items() if k in ("naive", "fitted")
    }
    return out


def _ztp_nll(theta, rows) -> float:
    a, b, c = theta
    total = 0.0
    for n, lpo, left, count, w in rows:
        lam = n * math.exp(min(a + b * lpo + c * left, 30.0))
        if lam < 1e-300:
            lam = 1e-300
        # log P(count | count >= 1) for Poisson(lam)
        log_trunc = math.log(-math.expm1(-lam))
        total -= w * (count * math.log(lam) - lam - math.lgamma(count + 1) - log_trunc)
    return total


def fit(rows: list[tuple[int, float, float, int, float]]) -> dict[str, Any]:
    """Zero-truncated Poisson MLE for (a, b, c).  rows: (field_size, lpo, left, count, weight)."""
    if len(rows) < 50:
        return {"params": None, "reason": f"{len(rows)} observations; at least 50 needed"}
    from scipy.optimize import minimize

    res = minimize(
        _ztp_nll,
        x0=[0.0, 1.0, 0.0],
        args=(rows,),
        method="L-BFGS-B",
        bounds=[(-20, 20), (0.0, 3.0), (-5.0, 5.0)],
    )
    a, b, c = (round(float(x), 6) for x in res.x)
    return {
        "params": {"a": a, "b": b, "c": c},
        "trainingNll": round(float(res.fun), 4),
        "naiveTrainingNll": round(_ztp_nll([0.0, 1.0, 0.0], rows), 4),
        "converged": bool(res.success),
        "n": len(rows),
        "note": "Training fit — improvement over the naive baseline must be shown on a holdout.",
    }


def holdout_score(
    rows: list[tuple[int, float, float, int, float]], params: dict[str, float]
) -> dict[str, Any]:
    """Mean weighted negative log-likelihood per observation, model vs naive (lower is better)."""
    if not rows:
        return {"n": 0}
    wsum = sum(r[4] for r in rows)
    return {
        "n": len(rows),
        "nll": round(_ztp_nll([params["a"], params["b"], params["c"]], rows) / wsum, 6),
        "naiveNll": round(_ztp_nll([0.0, 1.0, 0.0], rows) / wsum, 6),
    }


def rows_from_result(
    fit_sample: dict[str, Any],
    own_pct: dict[str, float],
    salary: dict[str, int],
    cap: int,
    field_size: int,
) -> list[tuple[int, float, float, int, float]]:
    """Duplication observations from one settled contest, using PRE-LOCK ownership forecasts."""
    rows = []
    for item in (fit_sample or {}).get("repeated", []) + (fit_sample or {}).get("singles", []):
        f = features(item["players"], own_pct, salary, cap)
        if f is not None and item.get("weight"):
            rows.append((field_size, f[0], f[1], int(item["count"]), float(item["weight"])))
    return rows


def calibration(
    rows: list[tuple[int, float, float, int, float]], params: dict[str, float]
) -> list[dict[str, Any]]:
    """Predicted vs observed mean copies (given at least one), by predicted-rate band."""
    bands: dict[str, list[tuple[float, float, float]]] = {}
    for n, lpo, left, count, w in rows:
        lam = expected_copies(n, (lpo, left), params)
        mean_given_seen = lam / -math.expm1(-lam) if lam > 1e-12 else 1.0
        key = (
            "<0.01"
            if lam < 0.01
            else "0.01-0.1"
            if lam < 0.1
            else "0.1-1"
            if lam < 1
            else "1-10"
            if lam < 10
            else "10+"
        )
        bands.setdefault(key, []).append((mean_given_seen, float(count), w))
    order = ["<0.01", "0.01-0.1", "0.1-1", "1-10", "10+"]
    out = []
    for k in order:
        if k in bands:
            v = bands[k]
            ws = sum(w for *_, w in v)
            out.append(
                {
                    "band": k,
                    "n": len(v),
                    "predictedMeanCopies": round(sum(p * w for p, _, w in v) / ws, 4),
                    "observedMeanCopies": round(sum(c * w for _, c, w in v) / ws, 4),
                }
            )
    return out


def evaluate_result(
    owner: str,
    scope: dict[str, Any],
    refs: dict[str, Any],
    rows: list[tuple[int, float, float, int, float]],
) -> dict[str, Any]:
    """Score the naive baseline on one settled contest and store it (pit); fit comes later."""
    from src.dfs import pit

    if not rows:
        return {"state": "unavailable", "reason": "no duplication sample with forecast ownership"}
    score = holdout_score(rows, NAIVE_PARAMS)
    card = {"nll": score["naiveNll"], "calibration": calibration(rows, NAIVE_PARAMS)}
    pit.record_evaluation(owner, "duplication", NAIVE_ID, scope, len(rows), card, refs)
    return {
        "state": "evaluated",
        "n": len(rows),
        **card,
        "note": "Naive baseline scored. A fitted model needs several contests and must beat this on a holdout.",
    }
