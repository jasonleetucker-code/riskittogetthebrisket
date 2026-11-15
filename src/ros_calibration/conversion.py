"""rosValue -> expected weekly points conversions (champion + challengers).

Every model predicts ``mu``: the expected host-native fantasy points of an
appeared player-week, from the pre-kickoff ``rosValue`` snapshot.  Models
(preregistration §3):

    C0  one shared scale        mu = a + b * r                 (champion)
    CG  group scale             mu = a_g + b_g * r, g in OFF / IDP / K
    CF  family scale            mu = a_f + b_f * r
    CR  family rank curve       mu = a_f + b_f * ln(k_f)
    F   production fallback     mu = r / 2.7                    (reference)

``k_f`` is the player's rank by ``rosValue`` within his lineup family over the
WHOLE as-of snapshot, so CR is invariant to a family-wide level step (a rank
basis change moves ``r``, not ``k_f``).

Fallback rules are fixed by the preregistration: a family below
``MIN_FIT_N`` fit rows, or with a wrong-sign slope, takes its group's CG fit; a
group below ``MIN_FIT_N`` takes C0.

MISSING IS NEVER ZERO: ``predict`` returns ``None`` for an unpriced player
(no positive ``rosValue``) or an unknown family — never 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from src.ros.lineup import lineup_position

#: Lineup families the study models (v1 ``SIM_FAMILIES``).
FAMILIES: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
OFF_FAMILIES = frozenset({"QB", "RB", "WR", "TE"})
IDP_FAMILIES = frozenset({"DL", "LB", "DB"})
GROUP_OF: dict[str, str] = {
    **{f: "OFF" for f in OFF_FAMILIES},
    **{f: "IDP" for f in IDP_FAMILIES},
    "K": "K",
}

#: Preregistered fit floor (§3).  Same value as v3's per-family floor.
MIN_FIT_N = 30
#: Production fallback divisor, quoted for the reference model F only.
#: Mirrors ``src.league_intel.sim_calibration.FALLBACK_ROS_VALUE_PER_POINT``;
#: a test pins the two equal so this cannot drift.
FALLBACK_ROS_VALUE_PER_POINT = 2.7

MODEL_IDS: tuple[str, ...] = ("C0", "CG", "CF", "CR", "F")
CHALLENGERS: tuple[str, ...] = ("CG", "CF", "CR")


def family_of(position: str | None) -> str | None:
    """The lineup family for a raw position, or ``None`` when it has none."""
    fam = lineup_position(str(position or ""))
    return fam if fam in GROUP_OF else None


@dataclass(frozen=True)
class FitRow:
    """One fit/eval observation: as-of inputs plus realized points."""

    family: str
    ros_value: float
    family_rank: int
    points: float


@dataclass(frozen=True)
class LinearFit:
    a: float
    b: float
    n: int
    source: str  # which preregistered rule produced it, e.g. "CF:LB" or "CG:IDP(fallback)"

    def to_dict(self) -> dict[str, Any]:
        return {"a": round(self.a, 6), "b": round(self.b, 6), "n": self.n, "source": self.source}


def ols(xs: Sequence[float], ys: Sequence[float]) -> tuple[float, float] | None:
    """Ordinary least squares ``y = a + b x``; ``None`` when x has no spread."""
    n = len(xs)
    if n < 2 or n != len(ys):
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    b = sxy / sxx
    return my - b * mx, b


def _x(model_id: str, row: FitRow) -> float:
    if model_id == "CR":
        return math.log(max(1, int(row.family_rank)))
    return float(row.ros_value)


@dataclass(frozen=True)
class ConversionModel:
    """A fitted conversion.  ``fits`` is keyed by family (``*`` for C0)."""

    model_id: str
    fits: Mapping[str, LinearFit] = field(default_factory=dict)

    def predict(
        self, family: str | None, ros_value: float | None, family_rank: int | None
    ) -> float | None:
        if family not in GROUP_OF:
            return None
        if ros_value is None or not math.isfinite(float(ros_value)) or float(ros_value) <= 0:
            return None
        r = float(ros_value)
        if self.model_id == "F":
            return r / FALLBACK_ROS_VALUE_PER_POINT
        fit = self.fits.get(family) or self.fits.get("*")
        if fit is None:
            return None
        if self.model_id == "CR" and fit.source.startswith("CR:"):
            if family_rank is None or int(family_rank) < 1:
                return None
            x = math.log(int(family_rank))
        else:
            x = r
        return max(0.0, fit.a + fit.b * x)

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "fits": {k: v.to_dict() for k, v in sorted(self.fits.items())},
        }


def _fit_on(rows: Sequence[FitRow], model_id: str, label: str) -> LinearFit | None:
    if len(rows) < MIN_FIT_N:
        return None
    res = ols([_x(model_id, r) for r in rows], [r.points for r in rows])
    if res is None:
        return None
    a, b = res
    wrong_sign = (b >= 0) if model_id == "CR" else (b <= 0)
    if wrong_sign:
        return None
    return LinearFit(a, b, len(rows), label)


def fit_model(model_id: str, rows: Iterable[FitRow]) -> ConversionModel:
    """Fit one preregistered model on fit-window rows."""
    if model_id not in MODEL_IDS:
        raise ValueError(f"unknown model {model_id!r}")
    rows = [r for r in rows if r.family in GROUP_OF and r.ros_value > 0]
    if model_id == "F":
        return ConversionModel("F", {})
    pooled = _fit_on(rows, "C0", "C0:*")
    if model_id == "C0":
        return ConversionModel("C0", {"*": pooled} if pooled else {})

    group_fits: dict[str, LinearFit] = {}
    for g in ("OFF", "IDP", "K"):
        g_rows = [r for r in rows if GROUP_OF[r.family] == g]
        fit = _fit_on(g_rows, "CG", f"CG:{g}")
        if fit is None and pooled is not None:
            fit = LinearFit(pooled.a, pooled.b, pooled.n, f"C0:*(fallback for {g})")
        if fit is not None:
            group_fits[g] = fit

    fits: dict[str, LinearFit] = {}
    for fam in FAMILIES:
        g = GROUP_OF[fam]
        if model_id == "CG":
            if g in group_fits:
                fits[fam] = group_fits[g]
            continue
        f_rows = [r for r in rows if r.family == fam]
        fit = _fit_on(f_rows, model_id, f"{model_id}:{fam}")
        if fit is None and g in group_fits:
            gf = group_fits[g]
            fit = LinearFit(gf.a, gf.b, gf.n, f"{gf.source}(fallback for {fam})")
        if fit is not None:
            fits[fam] = fit
    return ConversionModel(model_id, fits)


def family_ladders(snapshot_players: Iterable[Mapping[str, Any]]) -> dict[str, list[float]]:
    """``{family: positive rosValues, descending}`` over a WHOLE snapshot.

    The family is read from the snapshot row's own position.  Unpriced rows
    and rows without a family are absent (never ranked last).
    """
    by_fam: dict[str, list[float]] = {}
    for p in snapshot_players:
        fam = family_of(p.get("position"))
        try:
            v = float(p.get("rosValue") or 0.0)
        except (TypeError, ValueError):
            continue
        if fam is None or not (math.isfinite(v) and v > 0):
            continue
        by_fam.setdefault(fam, []).append(v)
    for values in by_fam.values():
        values.sort(reverse=True)
    return by_fam


def rank_in_family(
    ladders: Mapping[str, Sequence[float]], family: str | None, ros_value: float | None
) -> int | None:
    """Competition rank of ``ros_value`` in ``family``'s ladder: 1 + the number
    of snapshot players in that family priced strictly higher.

    Defined for any positive value, so a player whose snapshot row carries a
    different position than the directory still gets a rank in the family he
    is predicted in.  ``None`` for an unpriced value or an empty family.
    """
    if family is None or ros_value is None:
        return None
    r = float(ros_value)
    if not (math.isfinite(r) and r > 0):
        return None
    ladder = ladders.get(family)
    if not ladder:
        return None
    lo, hi = 0, len(ladder)
    while lo < hi:  # ladder is descending: count entries > r
        mid = (lo + hi) // 2
        if ladder[mid] > r:
            lo = mid + 1
        else:
            hi = mid
    return lo + 1


__all__ = [
    "CHALLENGERS",
    "FAMILIES",
    "GROUP_OF",
    "IDP_FAMILIES",
    "MIN_FIT_N",
    "MODEL_IDS",
    "OFF_FAMILIES",
    "ConversionModel",
    "FitRow",
    "LinearFit",
    "family_ladders",
    "family_of",
    "rank_in_family",
    "fit_model",
    "ols",
]
