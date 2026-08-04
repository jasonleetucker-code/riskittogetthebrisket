"""Rolling out-of-sample validation for Consensus Edge components.

No weight in this system may reach production without passing through here.
That is the whole point: the repository already contains several buy/sell
formulas whose constants were chosen because they seemed reasonable, and the
purpose of this module is to stop adding to that pile.

──────────────────────────────────────────────────────────────────────
Validation design
──────────────────────────────────────────────────────────────────────
**Rolling temporal folds, never a random split.** Two rows for the same player
on consecutive days are almost the same observation; a random split puts one in
train and one in test and reports a score that cannot be earned in production.
Folds are contiguous date ranges, always train-before-test.

**A purge gap between train and test.** A row's label looks ``H`` days forward,
so a training row dated ``T`` already knows about ``T+H``. Testing on ``T+1``
without a gap leaks that. Every fold therefore drops ``H`` days between the end
of train and the start of test.

**Benchmarks are the point, not a formality.** A signal that beats nothing is
not a signal. Each candidate is scored against:

    zero          predict no change — the honest null
    trailing_7d   short-horizon momentum
    trailing_30d  long-horizon momentum
    market_value  do expensive players simply drift up?
    log_gap       the mispricing signal alone

Measured on this repository's own panel, ``trailing_30d`` scores about +0.43
Spearman against the 30-day outcome while ``log_gap`` scores about +0.13. Any
claim that a mispricing model "predicts the market" must clear the momentum
benchmark, not the null. This is stated up front because it is the result most
likely to be quietly dropped.

**Two targets, never merged.** ``log_return_Hd`` is a MARKET-outcome target: it
answers "will the price move", not "is this a good buy at this price". A
production-outcome target needs league-scored future points, which this panel
does not carry. Consensus Edge must not present a market-outcome model as if it
had validated the production question.
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

log = logging.getLogger(__name__)

#: Rows below this market value are dropped from every fitted statistic. At the
#: deep end the anchor quantises to a handful of distinct numbers, so "return"
#: is mostly rounding and the correlation it produces is an artefact.
MIN_MARKET_VALUE = 200.0

#: Minimum rows in a test fold before its score is reported. A fold of forty
#: rows produces a confident-looking number that means nothing.
MIN_FOLD_ROWS = 200


@dataclass(frozen=True)
class Fold:
    train_start: date
    train_end: date
    test_start: date
    test_end: date

    def to_dict(self) -> dict[str, str]:
        return {
            "trainStart": self.train_start.isoformat(),
            "trainEnd": self.train_end.isoformat(),
            "testStart": self.test_start.isoformat(),
            "testEnd": self.test_end.isoformat(),
        }


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Rank correlation with average ranks for ties.

    Ties are common here — many players share a market value — and assigning
    them sequential ranks would invent an ordering the data does not contain.
    """
    n = len(xs)
    if n < 10 or n != len(ys):
        return None

    def ranked(values: Sequence[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            average = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = average
            i = j + 1
        return out

    rx, ry = ranked(xs), ranked(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denominator = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return numerator / denominator if denominator else None


def decile_spread(pairs: Sequence[tuple[float, float]]) -> dict[str, float | None]:
    """Mean outcome of the top decile minus the bottom decile by predictor.

    The economically meaningful statistic: a correlation of 0.1 is invisible in
    practice, but "the ten players this ranked highest gained 6% and the ten it
    ranked lowest lost 1%" is a decision someone can act on.
    """
    if len(pairs) < 100:
        return {"top": None, "bottom": None, "spread": None, "n": len(pairs)}
    ordered = sorted(pairs, key=lambda item: item[0])
    size = max(1, len(ordered) // 10)
    top = [outcome for _predictor, outcome in ordered[-size:]]
    bottom = [outcome for _predictor, outcome in ordered[:size]]
    top_mean = sum(top) / len(top)
    bottom_mean = sum(bottom) / len(bottom)
    return {
        "top": top_mean,
        "bottom": bottom_mean,
        "spread": top_mean - bottom_mean,
        "n": len(pairs),
    }


def directional_accuracy(pairs: Sequence[tuple[float, float]]) -> float | None:
    """Share of non-zero predictions whose sign matched the outcome."""
    considered = [(p, o) for p, o in pairs if p != 0.0 and o != 0.0]
    if not considered:
        return None
    hits = sum(1 for p, o in considered if (p > 0) == (o > 0))
    return hits / len(considered)


def load_panel(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def eligible(row: dict[str, Any], target: str) -> bool:
    return (
        row.get("outcomes", {}).get(target) is not None
        and float(row.get("market_value") or 0.0) >= MIN_MARKET_VALUE
    )


# ── candidate predictors ───────────────────────────────────────────────
#
# Each returns None when its input is missing, so a row without the input is
# EXCLUDED from that predictor's score rather than scored as zero. Treating
# missing as neutral would credit a predictor for rows it could not answer.


def predictor_zero(_row: dict[str, Any]) -> float | None:
    return 0.0


def predictor_log_gap(row: dict[str, Any]) -> float | None:
    return row.get("log_gap")


def predictor_trailing(days: int) -> Callable[[dict[str, Any]], float | None]:
    def inner(row: dict[str, Any]) -> float | None:
        return (row.get("trailing_log_change") or {}).get(f"log_change_{days}d")

    return inner


def predictor_market_value(row: dict[str, Any]) -> float | None:
    value = row.get("market_value")
    return math.log(value) if value and value > 0 else None


def combined(weights: dict[str, float]) -> Callable[[dict[str, Any]], float | None]:
    """A linear blend of standardized-ish components.

    Deliberately crude: the point of the backtest is to find out whether a
    combination beats its parts, and a complicated combiner would confound
    "the blend helps" with "the combiner helps".
    """

    def inner(row: dict[str, Any]) -> float | None:
        total = 0.0
        seen = False
        for name, weight in weights.items():
            if name == "log_gap":
                value = row.get("log_gap")
            elif name.startswith("trailing_"):
                value = (row.get("trailing_log_change") or {}).get(
                    f"log_change_{name.split('_')[1]}"
                )
            else:
                value = None
            if value is None:
                continue
            total += weight * value
            seen = True
        return total if seen else None

    return inner


def rolling_folds(
    dates: Sequence[date],
    *,
    horizon_days: int,
    train_days: int = 30,
    test_days: int = 14,
) -> list[Fold]:
    """Contiguous train -> purge -> test windows walked forward.

    The purge is ``horizon_days`` wide because that is exactly how far a
    training label can see.
    """
    if not dates:
        return []
    start, end = min(dates), max(dates)
    folds: list[Fold] = []
    train_start = start
    while True:
        train_end = train_start + timedelta(days=train_days - 1)
        test_start = train_end + timedelta(days=horizon_days + 1)
        test_end = test_start + timedelta(days=test_days - 1)
        if test_start > end:
            break
        folds.append(
            Fold(
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=min(test_end, end),
            )
        )
        train_start = train_start + timedelta(days=test_days)
    return folds


def score_predictor(
    rows: Iterable[dict[str, Any]],
    predictor: Callable[[dict[str, Any]], float | None],
    target: str,
) -> dict[str, Any]:
    pairs: list[tuple[float, float]] = []
    for row in rows:
        if not eligible(row, target):
            continue
        value = predictor(row)
        if value is None:
            continue
        pairs.append((float(value), float(row["outcomes"][target])))
    if len(pairs) < MIN_FOLD_ROWS:
        return {"n": len(pairs), "spearman": None, "insufficient": True}
    xs = [p for p, _o in pairs]
    ys = [o for _p, o in pairs]
    return {
        "n": len(pairs),
        "spearman": spearman(xs, ys),
        "directionalAccuracy": directional_accuracy(pairs),
        "decile": decile_spread(pairs),
        "insufficient": False,
    }


@dataclass
class BacktestResult:
    target: str
    folds: list[Fold]
    per_predictor: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {"target": self.target, "folds": len(self.folds), "predictors": {}}
        for name, scores in self.per_predictor.items():
            usable = [
                s for s in scores if not s.get("insufficient") and s.get("spearman") is not None
            ]
            if not usable:
                out["predictors"][name] = {"foldsScored": 0, "note": "insufficient data"}
                continue
            rhos = [s["spearman"] for s in usable]
            spreads = [
                s["decile"]["spread"]
                for s in usable
                if s.get("decile") and s["decile"].get("spread") is not None
            ]
            out["predictors"][name] = {
                "foldsScored": len(usable),
                "meanSpearman": sum(rhos) / len(rhos),
                "medianSpearman": sorted(rhos)[len(rhos) // 2],
                "worstFoldSpearman": min(rhos),
                "foldsPositive": sum(1 for r in rhos if r > 0),
                "meanDecileSpread": (sum(spreads) / len(spreads)) if spreads else None,
            }
        return out


def run_backtest(
    panel_rows: Sequence[dict[str, Any]],
    *,
    target: str = "log_return_30d",
    horizon_days: int = 30,
    train_days: int = 30,
    test_days: int = 14,
    predictors: dict[str, Callable[[dict[str, Any]], float | None]] | None = None,
) -> BacktestResult:
    """Score every predictor on every out-of-sample fold.

    Note what is deliberately NOT here: no predictor is fitted on the training
    window. Every candidate is a fixed function, so the training window's only
    job is to be excluded from the test window. That keeps this run a clean
    measurement of signal rather than a search over models — and a search is
    only worth running once something has cleared the momentum benchmark.
    """
    if predictors is None:
        predictors = {
            "zero": predictor_zero,
            "log_gap": predictor_log_gap,
            "trailing_7d": predictor_trailing(7),
            "trailing_30d": predictor_trailing(30),
            "market_value": predictor_market_value,
            "gap_plus_momentum": combined({"log_gap": 1.0, "trailing_30d": 1.0}),
        }
    dates = sorted({date.fromisoformat(row["as_of"]) for row in panel_rows})
    folds = rolling_folds(
        dates, horizon_days=horizon_days, train_days=train_days, test_days=test_days
    )
    by_date: dict[date, list[dict[str, Any]]] = {}
    for row in panel_rows:
        by_date.setdefault(date.fromisoformat(row["as_of"]), []).append(row)

    result = BacktestResult(target=target, folds=folds)
    for name, predictor in predictors.items():
        scores: list[dict[str, Any]] = []
        for fold in folds:
            test_rows: list[dict[str, Any]] = []
            day = fold.test_start
            while day <= fold.test_end:
                test_rows.extend(by_date.get(day, ()))
                day += timedelta(days=1)
            scores.append(score_predictor(test_rows, predictor, target))
        result.per_predictor[name] = scores
    return result
