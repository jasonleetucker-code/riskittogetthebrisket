"""Does the signal predict anything? Measured, not assumed.

The rule this module exists to enforce: **no weight, threshold, or claim
of usefulness ships without an out-of-sample number behind it.**

Design decisions that matter more than the code:

*Non-overlapping folds only.*  With a 110-day panel and a 14-day horizon
there are 96 possible origin dates but only 7 independent observations —
consecutive origins share almost all of their holding period, so treating
them as independent would shrink the error bars by a factor of ~4 and
manufacture significance from nothing.  ``folds`` walks disjoint windows.

*Rank correlation, not accuracy.*  The question is "does a higher score
mean a better subsequent return", which is a ranking question.  Spearman
answers it without assuming linearity and without being dominated by the
tail, and it is directly comparable across folds of different sizes.

*Benchmarks are mandatory.*  A signal is only interesting relative to the
cheapest alternative.  Every fold scores the candidate alongside
``market_value`` (are we just rediscovering that cheap players bounce?)
and ``random`` (what does zero skill look like at this sample size?).
A candidate that cannot beat those is reported as not beating them.

*The verdict is allowed to be "underpowered".*  With single-digit folds
the honest output is often "no difference detected", and that is a
finding, not a failure to produce one.  ``summarise`` reports the fold
count and the spread alongside the mean so a reader can see the evidence
is thin without having to infer it.
"""

from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Sequence

# Below this many paired observations a fold's correlation is noise; the
# fold is recorded as unusable rather than contributing a wild number to
# the mean.
MIN_PAIRS_PER_FOLD = 30

# Folds needed before the summary will call a direction at all.  Three is
# not a real power calculation — it is a floor below which the phrase
# "out-of-sample" would be misleading.
MIN_FOLDS_FOR_A_VERDICT = 3


@dataclass(frozen=True)
class Fold:
    """One independent evaluation window."""

    origin: date
    horizon: date
    horizon_days: int


@dataclass
class FoldResult:
    fold: Fold
    n_pairs: int
    spearman: float | None = None
    benchmarks: dict[str, float | None] = field(default_factory=dict)
    usable: bool = True
    reason: str | None = None


def folds(available: Sequence[date], horizon_days: int) -> list[Fold]:
    """Disjoint (origin, horizon) windows over ``available``.

    Each window ends where the next begins, so no two folds share a day
    of holding period and their results can be averaged as independent
    observations.
    """
    if not available or horizon_days <= 0:
        return []
    ordered = sorted(available)
    out: list[Fold] = []
    i = 0
    while i < len(ordered):
        origin = ordered[i]
        target_idx = None
        for j in range(i + 1, len(ordered)):
            if (ordered[j] - origin).days >= horizon_days:
                target_idx = j
                break
        if target_idx is None:
            break
        out.append(
            Fold(
                origin=origin,
                horizon=ordered[target_idx],
                horizon_days=(ordered[target_idx] - origin).days,
            )
        )
        i = target_idx
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation, ties averaged. None when undefined."""
    n = len(xs)
    if n != len(ys) or n < 3:
        return None

    def ranks(values: Sequence[float]) -> list[float]:
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

    rx, ry = ranks(xs), ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    if denx <= 0 or deny <= 0:
        return None
    return num / (denx * deny)


def evaluate_fold(
    fold: Fold,
    signal: dict[str, float],
    outcome: dict[str, float],
    *,
    benchmarks: dict[str, dict[str, float]] | None = None,
    seed: int = 0,
) -> FoldResult:
    """Score one fold: candidate signal and every benchmark, same pairs.

    All series are evaluated on the SAME intersection of players, so a
    benchmark can never look worse merely because it was measured on a
    harder subset.
    """
    keys = sorted(set(signal) & set(outcome))
    for series in (benchmarks or {}).values():
        keys = [k for k in keys if k in series]

    if len(keys) < MIN_PAIRS_PER_FOLD:
        return FoldResult(
            fold=fold,
            n_pairs=len(keys),
            usable=False,
            reason=f"only {len(keys)} paired rows (need {MIN_PAIRS_PER_FOLD})",
        )

    ys = [outcome[k] for k in keys]
    result = FoldResult(fold=fold, n_pairs=len(keys))
    result.spearman = spearman([signal[k] for k in keys], ys)

    if result.spearman is None:
        # Undefined correlation — every signal value identical, or every
        # outcome identical.  Marked unusable rather than left as a
        # usable fold carrying None, which would crash any consumer that
        # reasonably assumed usable implies a number.
        result.usable = False
        result.reason = "correlation undefined (zero variance in signal or outcome)"
        return result

    scored: dict[str, float | None] = {}
    for name, series in (benchmarks or {}).items():
        scored[name] = spearman([series[k] for k in keys], ys)

    # Zero-skill reference at this exact sample size, so a reader can see
    # how large a correlation this many rows produces by chance.
    rng = random.Random(seed + fold.origin.toordinal())
    scored["random"] = spearman([rng.random() for _ in keys], ys)

    result.benchmarks = scored
    return result


def summarise(results: Sequence[FoldResult]) -> dict[str, Any]:
    """Aggregate folds into a verdict that states its own evidence.

    Deliberately reports ``foldsUsable`` and the per-fold spread next to
    the mean.  A mean correlation of 0.08 over 3 folds and over 300 folds
    are different claims, and a summary that shows only the mean invites
    the reader to treat them alike.
    """
    usable = [r for r in results if r.usable and r.spearman is not None]
    out: dict[str, Any] = {
        "foldsAttempted": len(results),
        "foldsUsable": len(usable),
        "unusableReasons": [r.reason for r in results if not r.usable],
        "meanSpearman": None,
        "medianSpearman": None,
        "spearmanByFold": [
            {"origin": r.fold.origin.isoformat(), "n": r.n_pairs, "rho": r.spearman} for r in usable
        ],
        "benchmarks": {},
        "verdict": None,
    }
    if not usable:
        out["verdict"] = "no usable folds — nothing was measured"
        return out

    rhos = [r.spearman for r in usable]
    out["meanSpearman"] = statistics.fmean(rhos)
    out["medianSpearman"] = statistics.median(rhos)
    out["foldsPositive"] = sum(1 for r in rhos if r > 0)

    names: set[str] = set()
    for r in usable:
        names.update(r.benchmarks)
    for name in sorted(names):
        vals = [r.benchmarks.get(name) for r in usable]
        vals = [v for v in vals if v is not None]
        if not vals:
            continue
        out["benchmarks"][name] = {
            "meanSpearman": statistics.fmean(vals),
            "beatenInFolds": sum(
                1
                for r in usable
                if r.benchmarks.get(name) is not None and r.spearman > r.benchmarks[name]
            ),
        }

    out["verdict"] = _verdict(out)
    return out


def _verdict(summary: dict[str, Any]) -> str:
    """One sentence a non-statistician can act on, with the caveat inline."""
    n = summary["foldsUsable"]
    mean = summary["meanSpearman"]
    if n < MIN_FOLDS_FOR_A_VERDICT:
        return (
            f"underpowered: {n} usable fold(s). A direction cannot be called "
            f"from this; mean rho {mean:+.3f} is reported for completeness only."
        )
    positive = summary.get("foldsPositive", 0)
    beat = summary["benchmarks"].get("marketValue", {}).get("beatenInFolds")
    consistent = positive == n or positive == 0
    direction = "positive" if mean > 0 else "negative"
    # Count the folds that agree with the MEAN's direction. Reporting
    # `positive` under a "negative" label — which is what this did — turns
    # 3-of-5-negative into the sentence "2/5 folds negative". Nobody
    # noticed while every measured mean happened to be positive; the
    # momentum axis produced the first negative one.
    agreeing = positive if mean > 0 else n - positive
    parts = [
        f"mean rho {mean:+.3f} over {n} non-overlapping folds",
        f"{agreeing}/{n} folds {direction}",
    ]
    if beat is not None:
        parts.append(f"beat market-value benchmark in {beat}/{n}")
    if abs(mean) < 0.05:
        return "no effect detected (" + "; ".join(parts) + ")"
    if not consistent:
        return "inconsistent across folds (" + "; ".join(parts) + ")"
    return f"{direction} and consistent (" + "; ".join(parts) + ")"


def run_backtest(
    available: Sequence[date],
    horizon_days: int,
    signal_fn: Callable[[date], dict[str, float]],
    outcome_fn: Callable[[date, date], dict[str, float]],
    *,
    benchmark_fns: dict[str, Callable[[date], dict[str, float]]] | None = None,
    max_folds: int | None = None,
    on_fold: Callable[[FoldResult], None] | None = None,
) -> dict[str, Any]:
    """Walk disjoint folds, scoring the signal against its benchmarks.

    ``signal_fn(origin)`` and ``benchmark_fns[name](origin)`` may only
    consult data at or before ``origin``; ``outcome_fn(origin, horizon)``
    is the only function permitted to look forward.  That split is the
    whole leakage discipline, and it is enforced by construction rather
    than by review: nothing else here receives a future date.

    ``max_folds`` caps work for a smoke run.  When it truncates, the cap
    is reported in the result — a silently truncated backtest reads as a
    complete one.
    """
    all_folds = folds(available, horizon_days)
    truncated = False
    if max_folds is not None and len(all_folds) > max_folds:
        all_folds = all_folds[:max_folds]
        truncated = True

    results: list[FoldResult] = []
    for fold in all_folds:
        signal = signal_fn(fold.origin)
        outcome = outcome_fn(fold.origin, fold.horizon)
        benches = {name: fn(fold.origin) for name, fn in (benchmark_fns or {}).items()}
        result = evaluate_fold(fold, signal, outcome, benchmarks=benches)
        results.append(result)
        if on_fold is not None:
            on_fold(result)

    summary = summarise(results)
    summary["horizonDays"] = horizon_days
    summary["panelStart"] = min(available).isoformat() if available else None
    summary["panelEnd"] = max(available).isoformat() if available else None
    summary["foldsTruncated"] = truncated
    return summary
