"""Phase-11 backtesting harness: rolling-origin folds, baselines, metrics.

Infrastructure only runs on caller-supplied observation rows — it never
fetches, and it enforces the as-of leakage rule structurally: every
observation carries ``feature_as_of`` and the harness refuses rows
whose features postdate the fold's prediction timestamp.

An observation row (plain dict)::

    {"player_key", "season", "position",
     "feature_as_of": "YYYY-MM-DD",       # when the inputs were known
     "predicted": float,                   # model output being tested
     "actual": float,                      # realized target
     ...optional extras used by baselines: "prior_ppg", "age",
     "projection_fpg", "market_value"}

Baselines (§13.5 / reference B0–B4)::

    B0  prior-season PPG carried forward
    B1  blended projection alone
    B2  projection × linear age penalty (−4%/yr past 26)
    B3  market consensus
    B4  projection + age penalty + position dummy shift

The harness scores the model and every runnable baseline per fold with
Spearman/MAE/RMSE (value targets) or Brier/calibration (probability
targets).  Results are plain dicts ready for a ``model_experiments``
ledger.  The option-value ablation runs the same engine at each
``surplus_mode`` and compares rank orderings.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Any, Callable, Iterable, Mapping, Sequence


class LeakageError(ValueError):
    """A feature timestamp postdates the fold's prediction timestamp."""


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def mae(pred: Sequence[float], actual: Sequence[float]) -> float:
    _check_lengths(pred, actual)
    return sum(abs(p - a) for p, a in zip(pred, actual)) / len(pred)


def rmse(pred: Sequence[float], actual: Sequence[float]) -> float:
    _check_lengths(pred, actual)
    return math.sqrt(sum((p - a) ** 2 for p, a in zip(pred, actual)) / len(pred))


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks (ties share the mean rank)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(pred: Sequence[float], actual: Sequence[float]) -> float:
    _check_lengths(pred, actual)
    if len(pred) < 3:
        return 0.0
    rp, ra = _ranks(pred), _ranks(actual)
    mp = sum(rp) / len(rp)
    ma = sum(ra) / len(ra)
    num = sum((x - mp) * (y - ma) for x, y in zip(rp, ra))
    dp = math.sqrt(sum((x - mp) ** 2 for x in rp))
    da = math.sqrt(sum((y - ma) ** 2 for y in ra))
    if dp <= 0 or da <= 0:
        return 0.0
    return num / (dp * da)


def brier(pred_prob: Sequence[float], outcome: Sequence[int]) -> float:
    _check_lengths(pred_prob, outcome)
    return sum((p - o) ** 2 for p, o in zip(pred_prob, outcome)) / len(pred_prob)


def calibration(
    pred_prob: Sequence[float], outcome: Sequence[int], *, n_bins: int = 10
) -> dict[str, Any]:
    """Decile reliability curve + least-squares slope/intercept."""
    _check_lengths(pred_prob, outcome)
    bins: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, o in zip(pred_prob, outcome):
        idx = min(n_bins - 1, max(0, int(p * n_bins)))
        bins[idx].append((p, o))
    curve = []
    xs, ys = [], []
    for rows in bins:
        if not rows:
            continue
        mean_p = sum(p for p, _ in rows) / len(rows)
        obs = sum(o for _, o in rows) / len(rows)
        curve.append({"predicted": round(mean_p, 4), "observed": round(obs, 4), "n": len(rows)})
        xs.append(mean_p)
        ys.append(obs)
    slope, intercept = _least_squares(xs, ys)
    return {"curve": curve, "slope": round(slope, 4), "intercept": round(intercept, 4)}


def _least_squares(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float]:
    n = len(xs)
    if n < 2:
        return 1.0, 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom <= 0:
        return 1.0, 0.0
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return slope, my - slope * mx


def _check_lengths(a: Sequence, b: Sequence) -> None:
    if len(a) != len(b) or not a:
        raise ValueError(f"metric inputs must be equal-length and non-empty ({len(a)} vs {len(b)})")


# ---------------------------------------------------------------------------
# Baselines (B0–B4)
# ---------------------------------------------------------------------------


def _age_penalty(age: float | None) -> float:
    if age is None:
        return 1.0
    return max(0.3, 1.0 - 0.04 * max(0.0, float(age) - 26.0))


_POSITION_SHIFT = {"QB": 1.0, "TE": -0.5}  # crude B4 dummy, documented


def baseline_predictions(row: Mapping[str, Any]) -> dict[str, float | None]:
    proj = row.get("projection_fpg")
    age = row.get("age")
    return {
        "B0_prior_ppg": row.get("prior_ppg"),
        "B1_projection": proj,
        "B2_projection_age": (float(proj) * _age_penalty(age)) if proj is not None else None,
        "B3_market": row.get("market_value"),
        "B4_proj_age_pos": (
            float(proj) * _age_penalty(age)
            + _POSITION_SHIFT.get(str(row.get("position") or "").upper(), 0.0)
            if proj is not None
            else None
        ),
    }


# ---------------------------------------------------------------------------
# Rolling-origin harness
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fold:
    train_through: int  # last season usable for fitting
    test_season: int


def rolling_origin_folds(seasons: Iterable[int], *, min_train: int = 1) -> list[Fold]:
    """Expanding-window folds; never shuffles across time."""
    ordered = sorted(set(int(s) for s in seasons))
    folds = []
    for i, test in enumerate(ordered):
        if i < min_train:
            continue
        folds.append(Fold(train_through=ordered[i - 1], test_season=test))
    return folds


def _assert_no_leakage(rows: Sequence[Mapping[str, Any]], prediction_date: str) -> None:
    cutoff = date.fromisoformat(prediction_date[:10])
    for row in rows:
        feat = str(row.get("feature_as_of") or "")
        if not feat:
            raise LeakageError(f"row for {row.get('player_key')!r} has no feature_as_of stamp")
        if date.fromisoformat(feat[:10]) > cutoff:
            raise LeakageError(
                f"feature_as_of {feat} postdates prediction date {prediction_date} "
                f"for {row.get('player_key')!r}"
            )


def evaluate_fold(
    rows: Sequence[Mapping[str, Any]],
    *,
    fold: Fold,
    prediction_date: str,
    by_position: bool = True,
) -> dict[str, Any]:
    """Score model vs. every runnable baseline on one fold's test rows."""
    test_rows = [r for r in rows if int(r.get("season", -1)) == fold.test_season]
    if not test_rows:
        return {"fold": fold.__dict__, "n": 0, "results": {}}
    _assert_no_leakage(test_rows, prediction_date)

    def _score(pred_getter: Callable[[Mapping[str, Any]], float | None]) -> dict[str, float] | None:
        pairs = [(pred_getter(r), float(r["actual"])) for r in test_rows]
        pairs = [(p, a) for p, a in pairs if p is not None]
        if len(pairs) < 3:
            return None
        preds = [float(p) for p, _ in pairs]
        acts = [a for _, a in pairs]
        return {
            "n": len(pairs),
            "spearman": round(spearman(preds, acts), 4),
            "mae": round(mae(preds, acts), 4),
            "rmse": round(rmse(preds, acts), 4),
        }

    results: dict[str, Any] = {"model": _score(lambda r: r.get("predicted"))}
    for name in (
        "B0_prior_ppg",
        "B1_projection",
        "B2_projection_age",
        "B3_market",
        "B4_proj_age_pos",
    ):
        results[name] = _score(lambda r, _n=name: baseline_predictions(r).get(_n))

    out: dict[str, Any] = {
        "fold": {"trainThrough": fold.train_through, "testSeason": fold.test_season},
        "n": len(test_rows),
        "results": results,
    }
    if by_position:
        by_pos: dict[str, Any] = {}
        positions = sorted({str(r.get("position") or "?") for r in test_rows})
        for pos in positions:
            sub = [r for r in test_rows if str(r.get("position") or "?") == pos]
            if len(sub) < 5:
                continue
            preds = [float(r["predicted"]) for r in sub if r.get("predicted") is not None]
            acts = [float(r["actual"]) for r in sub if r.get("predicted") is not None]
            if len(preds) >= 5:
                by_pos[pos] = {"n": len(preds), "spearman": round(spearman(preds, acts), 4)}
        out["byPosition"] = by_pos
    return out


def run_backtest(
    rows: Sequence[Mapping[str, Any]],
    *,
    prediction_dates: Mapping[int, str],
    min_train: int = 1,
) -> dict[str, Any]:
    """Full rolling-origin run over every season present in ``rows``.

    ``prediction_dates`` maps test season → the as-of date predictions
    were (or would have been) made; leakage is enforced against it.
    """
    seasons = {int(r["season"]) for r in rows}
    folds = rolling_origin_folds(seasons, min_train=min_train)
    fold_results = []
    for fold in folds:
        pd = prediction_dates.get(fold.test_season)
        if pd is None:
            raise LeakageError(f"no prediction date declared for test season {fold.test_season}")
        fold_results.append(evaluate_fold(rows, fold=fold, prediction_date=pd))
    return {"folds": fold_results, "foldCount": len(fold_results)}


# ---------------------------------------------------------------------------
# S(3) calibration + ablation comparison
# ---------------------------------------------------------------------------


def s3_calibration(
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Compare predicted S(3) vs observed 3-year startable retention.

    Rows: {"position", "predicted_s3": float, "still_startable": 0/1}.
    The §5.8 primary calibration target, by position.
    """
    by_pos: dict[str, list[tuple[float, int]]] = {}
    for r in rows:
        by_pos.setdefault(str(r["position"]).upper(), []).append(
            (float(r["predicted_s3"]), int(r["still_startable"]))
        )
    out = {}
    for pos, pairs in sorted(by_pos.items()):
        pred = sum(p for p, _ in pairs) / len(pairs)
        obs = sum(o for _, o in pairs) / len(pairs)
        out[pos] = {
            "n": len(pairs),
            "meanPredictedS3": round(pred, 4),
            "observedRetention": round(obs, 4),
            "gap": round(pred - obs, 4),
            "brier": round(brier([p for p, _ in pairs], [o for _, o in pairs]), 4),
        }
    return out


def compare_surplus_modes(
    valuations_by_mode: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """Rank-agreement diagnostics between surplus formulations.

    Input: mode → {player_key: balanced trade value}.  This quantifies
    HOW MUCH the §3.3 ablation reorders the board; which ordering is
    RIGHT is decided by ``run_backtest`` against realized outcomes.
    """
    modes = sorted(valuations_by_mode)
    out: dict[str, Any] = {"modes": modes}
    pairs = []
    for i, m1 in enumerate(modes):
        for m2 in modes[i + 1 :]:
            keys = sorted(set(valuations_by_mode[m1]) & set(valuations_by_mode[m2]))
            if len(keys) < 3:
                continue
            v1 = [valuations_by_mode[m1][k] for k in keys]
            v2 = [valuations_by_mode[m2][k] for k in keys]
            pairs.append(
                {"pair": f"{m1}~{m2}", "n": len(keys), "spearman": round(spearman(v1, v2), 4)}
            )
    out["rankAgreement"] = pairs
    return out
