"""Does the league-adjusted board order players better than the market board?

The question this answers
─────────────────────────
The league-adjusted lens multiplies market values by measured tilts —
IDP positional scoring fit, reception-distance banding — on the claim
that a player is worth more or less **to this league** than the market
says. That claim has been argued from mechanism and never tested.

It is testable. Both boards exist, and realized fantasy points under
this league's exact scoring exist. If the adjustment carries real
information, the adjusted board should order players closer to what they
actually scored *here* than the unadjusted one does.

**What this measures, and what it does not.** The board is a current
one; realized points are from a completed season. So this is NOT a
forecast test — it cannot tell you whether either board predicts the
future. It compares two orderings of the SAME players against the SAME
target, where the only difference is the adjustment.

That comparison is still sound, and the reason is worth stating: any
lookahead in the board is a **common-mode** error. It inflates both arms
identically and cancels in the difference. What survives is the thing
asked about — does applying the tilt move the ordering toward or away
from this league's scoring reality?

Conflating those two claims would be the mistake. "The adjusted board
aligns better with our scoring" is supported by this. "The adjusted
board predicts next season better" is not, and would need board
snapshots taken before a season that this repo does not keep.

Why Spearman
────────────
The practical use of the board is ORDERING — who to draft, who to trade
for, which side of a deal is ahead. A rank correlation scores exactly
that and is invariant to the fact that value sits on a Hill curve, where
a 4% value change means a different rank move at the top of the board
than at the bottom. Scoring on raw values would let that nonlinearity
masquerade as accuracy.

The paired bootstrap is the part that decides
─────────────────────────────────────────────
A raw difference in correlation is not a result. With ~200 players a
difference of 0.01 is noise. :func:`paired_bootstrap` resamples players
with replacement and reports how often the adjusted board wins, so a
verdict rests on a distribution rather than on one number that happened
to come out ahead.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "BoardComparison",
    "compare_boards",
    "paired_bootstrap",
    "spearman",
]


def _ranks(values: Sequence[float]) -> list[float]:
    """Ranks with ties averaged.

    Ties are common here — the board rounds to integers and many deep
    players share a value — and assigning them arbitrary distinct ranks
    would manufacture ordering information that is not in the data.
    """
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            out[order[k]] = avg
        i = j + 1
    return out


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation. 0.0 for degenerate input rather than raising —
    a diagnostic must not be the thing that fails."""
    if len(xs) != len(ys) or len(xs) < 3:
        return 0.0
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = statistics.fmean(rx), statistics.fmean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = sum((a - mx) ** 2 for a in rx) ** 0.5
    dy = sum((b - my) ** 2 for b in ry) ** 0.5
    if dx <= 0 or dy <= 0:
        return 0.0
    return num / (dx * dy)


@dataclass(frozen=True)
class BoardComparison:
    """One head-to-head, with the evidence that decides it."""

    n: int = 0
    market_rho: float = 0.0
    adjusted_rho: float = 0.0
    delta: float = 0.0
    win_rate: float = 0.0
    """Share of bootstrap resamples where the adjusted board scored
    higher. 0.5 means indistinguishable."""

    ci_low: float = 0.0
    ci_high: float = 0.0
    by_position: dict[str, dict[str, float]] = field(default_factory=dict)
    movers: int = 0
    """How many players the adjustment actually moved. If this is small,
    a null result says nothing about the adjustment — only that it barely
    applied to this population."""

    verdict: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "n": self.n,
            "marketRho": round(self.market_rho, 6),
            "adjustedRho": round(self.adjusted_rho, 6),
            "delta": round(self.delta, 6),
            "winRate": round(self.win_rate, 4),
            "ci95": [round(self.ci_low, 6), round(self.ci_high, 6)],
            "movers": self.movers,
            "byPosition": {
                k: {kk: round(vv, 6) for kk, vv in v.items()}
                for k, v in sorted(self.by_position.items())
            },
            "verdict": self.verdict,
        }


def paired_bootstrap(
    market: Sequence[float],
    adjusted: Sequence[float],
    actual: Sequence[float],
    *,
    iterations: int = 2000,
    seed: int = 20260728,
) -> tuple[float, float, float]:
    """Resample players and report (win_rate, ci_low, ci_high) on the
    correlation difference.

    PAIRED — the same resampled index set scores both boards, so the
    comparison is not contaminated by drawing different players for each
    arm. Seeded, because a verdict that changes between runs is not a
    verdict.
    """
    rng = random.Random(seed)
    n = len(actual)
    if n < 10:
        return 0.5, 0.0, 0.0
    deltas: list[float] = []
    wins = 0
    for _ in range(iterations):
        idx = [rng.randrange(n) for _ in range(n)]
        a = [actual[i] for i in idx]
        d = spearman([adjusted[i] for i in idx], a) - spearman([market[i] for i in idx], a)
        deltas.append(d)
        if d > 0:
            wins += 1
    deltas.sort()
    lo = deltas[int(0.025 * len(deltas))]
    hi = deltas[int(0.975 * len(deltas)) - 1]
    return wins / iterations, lo, hi


def compare_boards(
    rows: Sequence[Mapping[str, Any]],
    *,
    iterations: int = 2000,
    min_players: int = 30,
) -> BoardComparison:
    """Score the adjusted board against the market board.

    ``rows`` need ``market``, ``adjusted``, ``actual`` and optionally
    ``position``.
    """
    usable = [
        r
        for r in rows
        if r.get("market") is not None
        and r.get("adjusted") is not None
        and r.get("actual") is not None
    ]
    if len(usable) < min_players:
        return BoardComparison(
            n=len(usable),
            verdict=f"too few joined players ({len(usable)} < {min_players}) to decide anything",
        )

    market = [float(r["market"]) for r in usable]
    adjusted = [float(r["adjusted"]) for r in usable]
    actual = [float(r["actual"]) for r in usable]
    movers = sum(1 for m, a in zip(market, adjusted) if abs(a - m) > 1e-9)

    m_rho = spearman(market, actual)
    a_rho = spearman(adjusted, actual)
    win_rate, lo, hi = paired_bootstrap(market, adjusted, actual, iterations=iterations)

    by_pos: dict[str, dict[str, float]] = {}
    for pos in sorted({str(r.get("position") or "?").upper() for r in usable}):
        sub = [r for r in usable if str(r.get("position") or "?").upper() == pos]
        if len(sub) < 10:
            continue
        sm = [float(r["market"]) for r in sub]
        sa = [float(r["adjusted"]) for r in sub]
        sy = [float(r["actual"]) for r in sub]
        by_pos[pos] = {
            "n": float(len(sub)),
            "marketRho": spearman(sm, sy),
            "adjustedRho": spearman(sa, sy),
            "delta": spearman(sa, sy) - spearman(sm, sy),
        }

    delta = a_rho - m_rho
    if movers < min_players // 2:
        verdict = (
            f"INCONCLUSIVE — the adjustment moved only {movers} of {len(usable)} "
            "players, so this says little about the adjustment itself"
        )
    elif lo > 0:
        verdict = "ADJUSTED WINS — the 95% interval on the difference excludes zero"
    elif hi < 0:
        verdict = "MARKET WINS — the adjusted board is measurably worse"
    else:
        verdict = (
            "NO DIFFERENCE DETECTED — the 95% interval spans zero, so the "
            "adjustment neither helps nor hurts at this sample size"
        )

    return BoardComparison(
        n=len(usable),
        market_rho=m_rho,
        adjusted_rho=a_rho,
        delta=delta,
        win_rate=win_rate,
        ci_low=lo,
        ci_high=hi,
        by_position=by_pos,
        movers=movers,
        verdict=verdict,
    )
