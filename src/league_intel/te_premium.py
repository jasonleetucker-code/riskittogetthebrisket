"""TE demand: which TE basis a league needs, and how to convert onto it.

Collaborative audit, finding F.

CORRECTION 2026-07-27 — READ THIS FIRST
=======================================
An earlier version of this module measured TE demand from **scoring keys
alone**, found ``bonus_rec_te = 0.0`` with every TE key matched by its
WR/RB equivalent, and concluded the league's TE premium was "exactly
1.000" — implying TE values should be translated DOWN off the TE++
basis.

**That was wrong, and it was wrong in the dangerous direction.**

The league starts **two mandatory tight ends** (``roster_positions``
contains ``TE, TE``) and TE is additionally FLEX- and SFLEX-eligible.
That is real, large TE demand, and it exists whether or not a single
scoring key rewards the position.  A 2-TE league bids up tight ends
because twelve teams must field twenty-four of them every week — the
scarcity is structural, not a scoring artefact.

Reading "no scoring bonus" as "no TE premium" confuses the *mechanism*
with the *demand*.  KTC's TE-premium boards exist for exactly this class
of league.  Translating down would have stripped a premium the league
genuinely has.

The finding that survives the correction — and gets stronger
------------------------------------------------------------
The target basis is TE++, which is what the live blend already assumes
("KTC is the canonical TE++ retail signal and is left untouched; every
other source's TE values are scaled at blend time to align with KTC's
TE++ baseline").  So the direction of the live correction is right.

Its *magnitude* is not.  KTC's own measured TE++ uplift never drops
below 1.209 and reaches 2.053, rank-dependent — while the live
``_TE_BLANKET_NON_NATIVE_MULTIPLIER`` is a flat 1.15, below the entire
observed range.  Non-TEP boards are being lifted **too little**.
Correcting it moves TE values UP.

Two axes, and why double-counting is now structurally impossible
----------------------------------------------------------------
**Axis A — source alignment.**  "Which TE basis is this source's board
already on?"  KTC publishes the same players with and without a TE
premium, so the conversion between bases is directly measurable rather
than assumed.  :func:`tep_uplift` serves that measured curve.

**Axis B — league demand.**  "Which TE basis does this league need?"
A property of roster structure first and scoring second.
:func:`measure_te_demand` answers it.

Axis B deliberately returns a **target basis**, never a multiplier.
That is the guard: a basis cannot be multiplied into anything.  The only
way to move a value is :func:`convert_te_value`, which takes an explicit
``from_basis`` and ``to_basis``, is a no-op when they match, and is
idempotent — calling it twice with the same pair cannot compound.

The previous API returned ``multiplier``, which a caller would naturally
multiply on top of the blend's existing alignment.  That would have
double-counted the premium.  The field is gone.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "TE_BASES",
    "TeDemandMeasurement",
    "convert_te_value",
    "load_tep_curve",
    "measure_te_demand",
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

# KTC's TE-premium ladder, in the order its own payload names them.
# ``Dynasty Scraper.py`` reads ``superflexValues.tepp`` (level 2) and
# knows about ``teppp`` (level 3).
#
# ``base``  no TE premium
# ``tep``   TE+   — level 1
# ``tepp``  TE++  — level 2, what this repo ingests as ``ktcSfTep``
# ``teppp`` TE+++ — level 3, not currently ingested
TE_BASES: tuple[str, ...] = ("base", "tep", "tepp", "teppp")

# How many mandatory TE starters push a league onto each basis.
#
# PROVENANCE: this mapping encodes an operator-supplied domain fact —
# KTC's TE++ setting is aimed at two-tight-end leagues.  It is NOT
# something this repo measured, and it is recorded as an assumption
# rather than dressed up as a finding.  The measurable half is the
# roster requirement, which is read directly from the league.
_REQUIRED_TE_TO_BASIS: tuple[tuple[int, str], ...] = (
    (3, "teppp"),
    (2, "tepp"),
    (1, "base"),
)

# Scoring keys that can advantage TEs, each paired with the equivalent
# keys for the positions a TE competes with for a FLEX slot.  A scoring
# edge exists only where the TE key exceeds BOTH comparators — a league
# that grants every pass-catcher a first-down bonus has not favoured TEs.
#
# NOTE the scoring axis is now SECONDARY.  It can only raise the basis a
# league's roster structure already implies, never lower it: a 2-TE
# league is a 2-TE league whether or not receptions pay extra.
_TE_EDGE_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("bonus_rec_te", ("bonus_rec_wr", "bonus_rec_rb")),
    ("bonus_fd_te", ("bonus_fd_wr", "bonus_fd_rb")),
)


@dataclass(frozen=True)
class TeDemandMeasurement:
    """How much tight end a league actually demands.

    Deliberately carries **no multiplier field**.  A basis cannot be
    multiplied into anything, so a consumer cannot accidentally stack
    this on top of the blend's existing source alignment.  Use
    :func:`convert_te_value` to move a value between bases.
    """

    target_basis: str
    """Which KTC TE-premium basis this league's values should sit on."""

    required_te_starters: int
    te_flex_eligible: bool
    scoring_edges: Mapping[str, float]
    """Per-key TE advantage over the best WR/RB comparator.  Zero means
    measured as no advantage — not that the key was absent."""

    measured: bool
    """False when neither roster settings nor scoring were supplied."""

    reason: str

    @property
    def has_scoring_edge(self) -> bool:
        return any(v > 0 for v in self.scoring_edges.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "targetBasis": self.target_basis,
            "requiredTeStarters": self.required_te_starters,
            "teFlexEligible": self.te_flex_eligible,
            "scoringEdges": dict(self.scoring_edges),
            "hasScoringEdge": self.has_scoring_edge,
            "measured": self.measured,
            "reason": self.reason,
        }


def _as_float(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _required_te_starters(roster: Mapping[str, Any] | None) -> tuple[int, bool]:
    """``(required TE starters, TE is flex-eligible)``.

    Accepts either a Sleeper ``roster_positions`` list or this repo's
    ``rosterSettings`` shape, because both are in the tree.
    """
    if not isinstance(roster, Mapping):
        return 0, False

    positions = roster.get("roster_positions")
    if isinstance(positions, (list, tuple)):
        required = sum(1 for p in positions if str(p).upper() == "TE")
        flex_ok = any(str(p).upper() in ("FLEX", "SUPER_FLEX") for p in positions)
        return required, flex_ok

    starters = roster.get("starters")
    if isinstance(starters, Mapping):
        required = int(_as_float(starters.get("TE")) or 0)
        flex_ok = any(
            "TE" in [str(x).upper() for x in (roster.get(key) or [])]
            for key in ("flexEligible", "sflexEligible")
        )
        return required, flex_ok

    return 0, False


def measure_te_demand(
    roster: Mapping[str, Any] | None,
    scoring: Mapping[str, Any] | None = None,
) -> TeDemandMeasurement:
    """Which TE basis this league needs.

    Roster structure leads; scoring can only raise the result.

    ``roster`` is a Sleeper league dict (``roster_positions``) or this
    repo's ``rosterSettings`` block.  ``scoring`` is Sleeper's
    ``scoring_settings``.
    """
    required, flex_ok = _required_te_starters(roster)

    edges: dict[str, float] = {}
    if isinstance(scoring, Mapping) and scoring:
        for te_key, comparators in _TE_EDGE_KEYS:
            te_val = _as_float(scoring.get(te_key)) or 0.0
            best = max((_as_float(scoring.get(c)) or 0.0) for c in comparators)
            edges[te_key] = round(te_val - best, 6)

    if required <= 0 and not edges:
        return TeDemandMeasurement(
            target_basis="base",
            required_te_starters=0,
            te_flex_eligible=False,
            scoring_edges={},
            measured=False,
            reason=(
                "neither roster settings nor scoring supplied; defaulting to the "
                "base basis, which applies no TE adjustment"
            ),
        )

    basis = "base"
    for threshold, candidate in _REQUIRED_TE_TO_BASIS:
        if required >= threshold:
            basis = candidate
            break

    reasons = [f"{required} mandatory TE starter(s)"]
    if flex_ok:
        reasons.append("TE is FLEX/SFLEX eligible, adding demand above the required count")

    # Scoring can only RAISE the basis. A 2-TE league does not become a
    # 1-TE league because receptions pay the same for everyone — that
    # inversion is the bug this correction exists to prevent.
    if any(v > 0 for v in edges.values()):
        idx = TE_BASES.index(basis)
        if idx < len(TE_BASES) - 1:
            basis = TE_BASES[idx + 1]
        detail = ", ".join(f"{k} +{v:g}" for k, v in sorted(edges.items()) if v > 0)
        reasons.append(f"scoring also advantages TE ({detail}), raising the basis one step")
    elif edges:
        reasons.append("no scoring key advantages TE over WR/RB, so scoring adds nothing")

    return TeDemandMeasurement(
        target_basis=basis,
        required_te_starters=required,
        te_flex_eligible=flex_ok,
        scoring_edges=edges,
        measured=True,
        reason="; ".join(reasons),
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


def convert_te_value(value: float, *, from_basis: str, to_basis: str) -> float:
    """Move one TE value between TE-premium bases.  The ONLY mover.

    This is the double-count guard, and it works by construction rather
    than by discipline:

    * ``from_basis == to_basis`` returns the value untouched, so a source
      already on the target basis is never adjusted.  ``ktcSfTep`` is
      already ``tepp``; asking to put it on ``tepp`` is a no-op.
    * The conversion is defined between two named bases, so calling it a
      second time with the same pair changes nothing — the second call
      sees ``from == to``.  A multiplier API cannot offer that: two
      multiplications always compound.
    * Unknown bases raise rather than silently returning ``value``. A
      typo that quietly skips a conversion is worse than a crash.

    Only ``base`` <-> ``tepp`` is measured (from KTC's own two boards).
    ``tep`` and ``teppp`` are declared in :data:`TE_BASES` but have no
    fitted curve, so requesting them raises instead of interpolating —
    inventing an intermediate uplift is exactly the kind of unmeasured
    number this audit exists to remove.
    """
    for name, basis in (("from_basis", from_basis), ("to_basis", to_basis)):
        if basis not in TE_BASES:
            raise ValueError(f"{name}={basis!r} is not one of {TE_BASES}")

    if from_basis == to_basis:
        return float(value)

    measured = {"base", "tepp"}
    if {from_basis, to_basis} != measured:
        raise ValueError(
            f"no measured curve between {from_basis!r} and {to_basis!r}; only "
            "base <-> tepp is fitted (from KTC's own base and TE++ boards). "
            "Interpolating an intermediate uplift would be an unmeasured number."
        )

    v = _as_float(value)
    if v is None or v <= 0:
        return float(value)

    if from_basis == "base":
        return v * tep_uplift(v)

    # tepp -> base.  The curve is parameterised on the BASE value, so
    # invert rather than dividing by the uplift at the tepp value, which
    # would be the uplift for the wrong point on the curve.
    lo, hi = v / 3.0, v
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if mid * tep_uplift(mid) < v:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0
