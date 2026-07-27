"""Measure a league's TE scoring premium, and KTC's TE++ uplift curve.

Collaborative audit, finding F.  Two axes that must never be stacked:

**Axis A — source alignment.**  "Which TE basis is this source's board
on?"  KTC publishes the same players with and without a TE premium, so
the conversion between the two bases is directly measurable rather than
assumed.  :func:`tep_uplift` serves that measured curve.

**Axis B — league scoring.**  "Which TE basis do we WANT the output in?"
That is a property of the league's scoring rules, not of any board.
:func:`measure_league_te_premium` answers it.

Conflating the two is how the live constant went wrong.
``_TE_BLANKET_NON_NATIVE_MULTIPLIER = 1.15`` is doing Axis A's job
(nudging non-TEP boards toward a TEP basis) while being *justified* as
Axis B (the league's TE premium).  It is wrong on both counts: KTC's own
measured uplift never drops below 1.209, so 1.15 is below the entire
observed range for Axis A; and the league's measured premium is 1.000,
so Axis B wants no uplift at all.

Why this module refuses to convert a scoring edge into a multiplier
-------------------------------------------------------------------
When a league DOES grant a TE premium, turning "+0.5 points per
reception" into "TEs are worth X% more" requires knowing how much of a
TE's scoring comes from receptions relative to everyone else's — i.e.
per-player volume data.  The repo does not persist player-week actuals
(audit finding Q), so that conversion cannot be measured here.

Rather than invent a slope, :func:`measure_league_te_premium` reports the
edge it can measure and says explicitly when a multiplier is not
derivable.  For a league with no positional TE edge — which is the
operator's league in 2026 — the answer is exactly 1.0 and needs no
conversion at all, so the missing data does not bite.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "TePremiumMeasurement",
    "load_tep_curve",
    "measure_league_te_premium",
    "tep_uplift",
]

_CURVE_PATH = Path(__file__).resolve().parents[2] / "config" / "weights" / "te_premium_curve.json"

# Fallback curve parameters, used only when the config file is missing.
# These ARE the measured 2026-07-27 values; duplicating them keeps a
# fresh checkout working without silently substituting a made-up curve.
_FALLBACK_A = 43.555794
_FALLBACK_K = 0.632839
# The smallest uplift KTC actually applies to any TE on the board.  The
# unconstrained fit reads ~1.146 at the most valuable TE against an
# observed 1.209 — a smooth curve through 73 points cannot also honour
# its own endpoint.  Clamping to the observed minimum is a measured
# bound, not a fudge: no tight end receives less than this.
_FALLBACK_FLOOR = 1.2092

# Scoring keys that can advantage TEs, each paired with the equivalent
# keys for the positions a TE competes with for a FLEX slot.  A premium
# exists only where the TE key exceeds BOTH comparators — a league that
# grants every pass-catcher a first-down bonus has not favoured TEs.
_TE_EDGE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bonus_rec_te", ("bonus_rec_wr", "bonus_rec_rb")),
    ("bonus_fd_te", ("bonus_fd_wr", "bonus_fd_rb")),
)


@dataclass(frozen=True)
class TePremiumMeasurement:
    """What a league's scoring rules say about tight ends."""

    multiplier: float | None
    """The value multiplier, or ``None`` when it is not derivable.

    ``1.0`` when the league grants no positional TE edge — exact, not a
    default.  ``None`` when an edge exists but converting it to a value
    multiplier would need volume data this repo does not persist.
    """

    has_positional_edge: bool
    edges: Mapping[str, float]
    """Per-key TE advantage over the best comparator.  Zero means the key
    was present and measured as no advantage — not that it was absent."""

    measured: bool
    """False when the league context carried no scoring settings at all."""

    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "multiplier": self.multiplier,
            "hasPositionalEdge": self.has_positional_edge,
            "edges": dict(self.edges),
            "measured": self.measured,
            "reason": self.reason,
        }


def _as_float(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def measure_league_te_premium(
    scoring: Mapping[str, Any] | None,
) -> TePremiumMeasurement:
    """Measure the TE premium implied by a league's scoring settings.

    ``scoring`` is Sleeper's ``scoring_settings`` dict (or the
    ``league_context`` that carries those keys).

    A missing comparator key is treated as ``0.0`` — Sleeper omits keys
    set to zero in some payloads, and reading "absent" as "unknown" here
    would make every league look TE-premium.  A missing TE key is
    likewise ``0.0``: no bonus.
    """
    if not isinstance(scoring, Mapping) or not scoring:
        return TePremiumMeasurement(
            multiplier=None,
            has_positional_edge=False,
            edges={},
            measured=False,
            reason="no scoring settings supplied; TE premium not measurable",
        )

    edges: dict[str, float] = {}
    for te_key, comparators in _TE_EDGE_KEYS:
        te_val = _as_float(scoring.get(te_key)) or 0.0
        best_comparator = max(
            (_as_float(scoring.get(c)) or 0.0) for c in comparators
        )
        edges[te_key] = round(te_val - best_comparator, 6)

    positive = {k: v for k, v in edges.items() if v > 0}

    if not positive:
        return TePremiumMeasurement(
            multiplier=1.0,
            has_positional_edge=False,
            edges=edges,
            measured=True,
            reason=(
                "no scoring key advantages TE over WR/RB; measured premium is "
                "exactly 1.0"
            ),
        )

    # An edge exists.  Say so, and say why a number is not offered.
    detail = ", ".join(f"{k} +{v:g}" for k, v in sorted(positive.items()))
    return TePremiumMeasurement(
        multiplier=None,
        has_positional_edge=True,
        edges=edges,
        measured=True,
        reason=(
            f"league advantages TE ({detail}), but converting a scoring edge "
            "to a value multiplier needs per-player volume data this repo does "
            "not persist (audit finding Q). Reporting the edge rather than "
            "inventing a slope."
        ),
    )


def load_tep_curve() -> tuple[float, float, float]:
    """``(a, k, floor)`` for ``ratio(v) = max(floor, 1 + a * v**-k)``.

    Falls back to the measured 2026-07-27 constants when the config file
    is absent, so a fresh checkout behaves identically rather than
    silently disabling the curve.
    """
    try:
        payload = json.loads(_CURVE_PATH.read_text(encoding="utf-8"))
        a = _as_float(payload.get("a"))
        k = _as_float(payload.get("k"))
        floor = _as_float(payload.get("floor"))
        if a is not None and k is not None and a > 0 and k > 0:
            return a, k, floor if (floor is not None and floor >= 1.0) else 1.0
    except (OSError, ValueError):
        pass
    return _FALLBACK_A, _FALLBACK_K, _FALLBACK_FLOOR


def tep_uplift(
    value: float,
    *,
    a: float | None = None,
    k: float | None = None,
    floor: float | None = None,
) -> float:
    """KTC's measured TE++ uplift ratio for a base-board TE value.

    Monotone non-increasing in ``value`` and ``>= 1.0`` by construction: a
    TE premium can never lower a tight end's value, and a functional form
    that permits it is wrong regardless of its fit statistic.
    """
    if a is None or k is None or floor is None:
        _a, _k, _floor = load_tep_curve()
        a = _a if a is None else a
        k = _k if k is None else k
        floor = _floor if floor is None else floor
    v = _as_float(value)
    if v is None or v <= 0:
        return max(1.0, floor)
    return max(floor, 1.0 + a * v**-k)
