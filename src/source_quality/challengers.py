"""Equal-family champion and the predeclared source-weight challengers.

Architecture is unchanged and every candidate expresses ONLY the base factor:

    effective = BASE × freshness × health × coverage, then the family cap

Freshness is never learned here (base quality is measured on fresh-enough
observations only, see :func:`metrics.fresh_dates`), so "fresh" and
"historically informative" stay two factors.

Every learned weight is a FAMILY weight copied to each member source.  The
production family cap is the largest member base weight present on a row
(``cap_family_weights``), so a family that publishes three related boards has
exactly the authority of its family weight -- correlated products are never
rewarded three times.  Every weight is shrunk toward 1.0 by an empirical-Bayes
factor and hard-capped: ``w = 1 + clip(alpha * B * z, -cap, +cap)`` where ``z``
is the family's standardized quality and ``B = tau^2 / (tau^2 + se^2)``.  When
the between-family signal does not exceed the sampling noise (``tau^2 = 0``)
every weight is exactly 1.0: the champion.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

ALPHA = 0.10  # preregistered gain on the standardized, shrunk quality
CAP = 0.25  # preregistered hard cap: every base weight within [0.75, 1.25]
MIN_LEARN_BLOCKS = 4  # preregistered: a family needs >= 4 training blocks to move


@dataclass(frozen=True)
class Quality:
    point: float | None
    se: float | None
    blocks: int


def champion(families: Sequence[str]) -> dict[str, float]:
    """Equal authority among independent eligible families (the live registry)."""
    return {f: 1.0 for f in families}


def shrunk_weights(
    quality: Mapping[str, Quality],
    *,
    alpha: float = ALPHA,
    cap: float = CAP,
    min_blocks: int = MIN_LEARN_BLOCKS,
) -> tuple[dict[str, float], dict]:
    """Quality estimates -> capped, EB-shrunk family weights (1.0 = no evidence)."""
    if not (0 <= cap < 1) or alpha < 0:
        raise ValueError("cap must be in [0, 1) and alpha >= 0")
    usable = {
        f: q
        for f, q in quality.items()
        if q.point is not None
        and q.se is not None
        and math.isfinite(q.point)
        and math.isfinite(q.se)
        and q.blocks >= min_blocks
    }
    weights = {f: 1.0 for f in quality}
    diag: dict = {"usable": sorted(usable), "tau2": None, "families": {}}
    if len(usable) < 3:
        diag["reason"] = "fewer than 3 families with enough evidence: champion"
        return weights, diag
    pts = np.array([q.point for q in usable.values()])
    ses = np.array([q.se for q in usable.values()])
    sd = float(pts.std(ddof=1))
    tau2 = max(0.0, float(pts.var(ddof=1)) - float(np.mean(ses**2)))
    diag["tau2"] = round(tau2, 8)
    if sd <= 0 or tau2 <= 0:
        diag["reason"] = "between-family spread does not exceed sampling noise: champion"
        return weights, diag
    mean = float(pts.mean())
    for f, q in usable.items():
        z = (q.point - mean) / sd
        b = tau2 / (tau2 + q.se**2)
        w = 1.0 + max(-cap, min(cap, alpha * b * z))
        weights[f] = w
        diag["families"][f] = {"z": round(z, 4), "shrinkage": round(b, 4), "weight": round(w, 4)}
    return weights, diag


def pooled(estimates: Sequence[tuple[float | None, float | None, int]]) -> Quality:
    """Inverse-variance pool of per-universe estimates of one family's quality."""
    ok = [(p, s, b) for p, s, b in estimates if p is not None and s is not None and s > 0]
    if not ok:
        return Quality(None, None, 0)
    w = np.array([1 / s**2 for _, s, _ in ok])
    p = np.array([p for p, _, _ in ok])
    return Quality(
        float((w * p).sum() / w.sum()), float(1 / math.sqrt(w.sum())), max(b for *_, b in ok)
    )


def to_source_overrides(
    family_weights: Mapping[str, float],
    registry_families: Mapping[str, str],
    per_source: Mapping[str, float] | None = None,
) -> dict[str, float]:
    """``{source_key: weight}`` for the existing override path (``value_replay.build``
    spec ``weights`` -> ``source_overrides`` -> ``_active_sources``).

    Every registered member of a weighted family gets the family weight (or an
    explicit per-source weight, used only by the asset-class-aware challenger
    for single-universe keys).  Validated: finite and within the cap.
    """
    out: dict[str, float] = {}
    for key, fam in sorted(registry_families.items()):
        w = (per_source or {}).get(key, family_weights.get(fam))
        if w is None:
            continue
        validate_weight(w)
        out[key] = float(w)
    return out


def validate_weight(w: float, cap: float = CAP) -> None:
    if (
        not isinstance(w, (int, float))
        or not math.isfinite(w)
        or not (1 - cap - 1e-12 <= w <= 1 + cap + 1e-12)
    ):
        raise ValueError(
            f"pathological weight {w!r}: must be finite and within [{1 - cap}, {1 + cap}]"
        )
