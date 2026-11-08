"""Offline diagnostics for the BDVM directional signal — EVALUATION ONLY.

Nothing here is imported by the serving path (``service.py`` /
``market.py`` / ``bdvm_api.py``) and nothing here changes a served value,
threshold or label.  It exists so the question "does ``buy_hold_sell``
discriminate, and would a different comparison scale do better?" is
answered by reproducible, hand-checkable arithmetic instead of by looking
at a label histogram.  Preregistration:
``docs/research/bdvm-v1/SIGNAL_SATURATION_DIAGNOSIS_2026-11-08.md``.

Champion != challenger: a challenger scored here is an experiment record,
never an activation.
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

SELL_CLASSES = frozenset({"SELL", "STRONG_SELL"})
BUY_CLASSES = frozenset({"BUY", "STRONG_BUY"})


# --------------------------------------------------------------------- ranks
def average_ranks(values: Sequence[float]) -> list[float]:
    """0-based average ranks (ties share the mean of their positions)."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        mean_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = mean_rank
        i = j + 1
    return ranks


def percentiles(values: Sequence[float]) -> list[float]:
    """Within-pool percentile in [0, 1] (average ranks; one value -> 0.5)."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [0.5]
    return [r / (n - 1) for r in average_ranks(values)]


def pearson(a: Sequence[float], b: Sequence[float]) -> float | None:
    n = len(a)
    if n != len(b) or n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va <= 0 or vb <= 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman rank correlation, ``None`` when undefined (never 0)."""
    if len(a) != len(b):
        return None
    return pearson(average_ranks(a), average_ranks(b))


def quantile(sorted_values: Sequence[float], p: float) -> float:
    """Linear-interpolated quantile of an ascending list (numpy 'linear')."""
    if not sorted_values:
        raise ValueError("empty")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = p * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


# ---------------------------------------------------------- scale alignment
def quantile_match(source: Sequence[float], target: Sequence[float]) -> list[float]:
    """Map each ``source`` value onto ``target``'s distribution by percentile.

    A strictly monotone transform of ``source`` (order is preserved, ties
    stay tied) whose empirical distribution equals ``target``'s.  Used to
    ask "if the fundamental were on the market's scale, how many players
    would clear the incumbent's absolute alpha thresholds?" — it removes a
    curve-shape / level difference and nothing else.
    """
    tgt = sorted(target)
    return [quantile(tgt, p) for p in percentiles(source)]


# ----------------------------------------------------------------- labels
def incumbent_label(alpha: float, th: Mapping[str, float]) -> str:
    """The ABSOLUTE-alpha ladder of ``market.buy_hold_sell`` minus its
    liquidity / persistence / collapse side-conditions (reproduced
    separately so the gate effect can be measured).  Pinned against the
    served function by a test."""
    if alpha > th["buy_alpha"]:
        return "STRONG_BUY" if alpha > th["strong_buy_alpha"] else "BUY"
    if alpha < th["sell_alpha"]:
        return "STRONG_SELL" if alpha < th["strong_sell_alpha"] else "SELL"
    return "HOLD"


def percentile_gap_labels(
    fund: Sequence[float],
    market: Sequence[float],
    *,
    strong: float,
    weak: float,
) -> list[str]:
    """CHALLENGER C1: gap = fundamental percentile - market percentile,
    both within the SAME pool (so both sides share one 0-1 scale)."""
    pf, pm = percentiles(fund), percentiles(market)
    out = []
    for a, b in zip(pf, pm):
        g = a - b
        if g > strong:
            out.append("STRONG_BUY")
        elif g > weak:
            out.append("BUY")
        elif g < -strong:
            out.append("STRONG_SELL")
        elif g < -weak:
            out.append("SELL")
        else:
            out.append("HOLD")
    return out


def scale_aligned_labels(
    fund: Sequence[float],
    market: Sequence[float],
    liquidity: Sequence[float],
    th: Mapping[str, float],
) -> list[str]:
    """CHALLENGER C2: quantile-match the fundamental onto the market's
    distribution, then apply the INCUMBENT's alpha thresholds unchanged
    (alpha = aligned gap x liquidity)."""
    aligned = quantile_match(fund, market)
    return [incumbent_label((f - m) * liq, th) for f, m, liq in zip(aligned, market, liquidity)]


def position_percentile_gap_labels(
    fund: Sequence[float],
    market: Sequence[float],
    groups: Sequence[str],
    *,
    strong: float,
    weak: float,
) -> list[str]:
    """CHALLENGER C3: C1 computed within each position group."""
    out = ["HOLD"] * len(fund)
    by_group: dict[str, list[int]] = {}
    for i, g in enumerate(groups):
        by_group.setdefault(g, []).append(i)
    for idxs in by_group.values():
        labels = percentile_gap_labels(
            [fund[i] for i in idxs], [market[i] for i in idxs], strong=strong, weak=weak
        )
        for i, lab in zip(idxs, labels):
            out[i] = lab
    return out


# ------------------------------------------------------------- evaluation
def label_census(labels: Sequence[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for lab in labels:
        out[lab] = out.get(lab, 0) + 1
    return dict(sorted(out.items()))


def excess_forward_change(m0: Sequence[float], m1: Sequence[float]) -> list[float]:
    """Relative market change net of the cross-sectional median change.

    Removing the board-wide median at the same origin keeps a market-wide
    drift (everything repricing at a season boundary) from being read as
    asset-level skill.
    """
    rel = [(b - a) / a for a, b in zip(m0, m1)]
    med = quantile(sorted(rel), 0.5)
    return [r - med for r in rel]


def evaluate_origin(
    labels: Sequence[str],
    score: Sequence[float],
    forward_excess: Sequence[float],
) -> dict[str, float | int | None]:
    """One origin's directional scores for one labelling.

    * ``ic`` — Spearman(score, forward excess).  ``score`` is positive
      when the method says BUY (fundamental above market).
    * ``sell_hit`` — P(forward excess < 0 | label in SELL classes);
      ``buy_hit`` — P(forward excess > 0 | label in BUY classes).
    * ``base_down`` / ``base_up`` — the unconditional rates, so a hit rate
      is read against what a coin weighted by the pool would give.
    ``None`` (never 0) whenever a statistic has no support.
    """
    n = len(labels)
    sells = [fe for lab, fe in zip(labels, forward_excess) if lab in SELL_CLASSES]
    buys = [fe for lab, fe in zip(labels, forward_excess) if lab in BUY_CLASSES]
    return {
        "n": n,
        "ic": spearman(score, forward_excess),
        "n_sell": len(sells),
        "sell_hit": (sum(1 for x in sells if x < 0) / len(sells)) if sells else None,
        "mean_sell_excess": (sum(sells) / len(sells)) if sells else None,
        "n_buy": len(buys),
        "buy_hit": (sum(1 for x in buys if x > 0) / len(buys)) if buys else None,
        "mean_buy_excess": (sum(buys) / len(buys)) if buys else None,
        "base_down": sum(1 for x in forward_excess if x < 0) / n if n else None,
        "base_up": sum(1 for x in forward_excess if x > 0) / n if n else None,
    }
