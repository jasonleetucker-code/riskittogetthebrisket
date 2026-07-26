"""Measure a source's TE-premium calibration from paired boards (LI-7).

Some publishers ship two variants of the same board differing only in
TE posture — a standard version and a TE-premium version.  That is a
natural experiment: the ratio between them, measured against the
non-TE positions, isolates how much TE premium that publisher actually
charges.  No assumption about a "typical league" required.

**Two conditions must hold, and the second is the one that bites.**

1. *Controls at unity* — if the pair really differs on one axis, the
   non-TE positions must agree.
2. *Cardinal scale* — the values must be real magnitudes, not a rank
   encoding.

Condition 2 exists because condition 1 passes **vacuously** without it.
A rank-encoded source (FantasyPros ships ~953800-999900, a 1.05x
dynamic range) compresses every ratio to ~1.0 including the controls,
so it looks like a perfectly clean pair and then reports "no TE
premium" — an artifact of the encoding, not a measurement.  Requiring a
genuine dynamic range rejects those before they can mislead.

Applied to the live board, exactly ONE source passes both conditions
(KTC), and its control is not merely "at unity" but byte-identical on
all 388 non-TE rows.  Everything else is uncalibratable and must not be
assigned a premium by analogy — see ADR-009.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "CARDINAL_MIN_DYNAMIC_RANGE",
    "CONTROL_POSITIONS",
    "MIN_POSITIVE_CONTROL_POWER",
    "DerivedStructuralPremium",
    "PairedCalibration",
    "PremiumConsensus",
    "RankDisplacement",
    "compare_premium_estimates",
    "derive_structural_te_premium",
    "measure_paired_te_premium",
    "measure_rank_displacement",
]

CARDINAL_MIN_DYNAMIC_RANGE = 3.0
"""Minimum max/min ratio for a source's values to count as cardinal.
Real value boards run hundreds-fold (KTC is ~526x); rank encodings sit
just above 1.0."""

CONTROL_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR")

CONTROL_DRIFT_TOLERANCE = 0.02
"""How far a control position's median ratio may sit from 1.0 before
the pair is treated as confounded."""

MIN_ROWS_PER_POSITION = 8


@dataclass(frozen=True)
class PairedCalibration:
    """Result of a paired-board TE-premium measurement."""

    base_key: str
    premium_key: str
    usable: bool
    reason: str
    te_premium: float | None = None
    control_ratio: float | None = None
    control_drift: float | None = None
    identical_control_rows: int = 0
    control_rows: int = 0
    te_rows: int = 0
    depth_bands: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseKey": self.base_key,
            "premiumKey": self.premium_key,
            "usable": self.usable,
            "reason": self.reason,
            "tePremium": self.te_premium,
            "controlRatio": self.control_ratio,
            "controlDrift": self.control_drift,
            "identicalControlRows": self.identical_control_rows,
            "controlRows": self.control_rows,
            "teRows": self.te_rows,
            "depthBands": dict(self.depth_bands) if self.depth_bands else None,
        }


def _positive(raw: Any) -> float | None:
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _dynamic_range(rows: Iterable[Mapping[str, Any]], key: str) -> float:
    vals = []
    for r in rows:
        v = _positive((r.get("canonicalSiteValues") or {}).get(key))
        if v is not None:
            vals.append(v)
    if len(vals) < 10:
        return 0.0
    lo, hi = min(vals), max(vals)
    return hi / lo if lo > 0 else 0.0


DEFAULT_DEPTH_BANDS: tuple[tuple[str, int, int], ...] = (
    ("TE1-12", 0, 12),
    ("TE13-24", 12, 24),
    ("TE25-40", 24, 40),
    ("TE41+", 40, 10_000),
)


def measure_paired_te_premium(
    rows: list[Mapping[str, Any]],
    base_key: str,
    premium_key: str,
    *,
    depth_bands: tuple[tuple[str, int, int], ...] = DEFAULT_DEPTH_BANDS,
) -> PairedCalibration:
    """Measure the TE premium between two variants of one publisher's board.

    Returns a :class:`PairedCalibration` whose ``usable`` flag says
    whether the measurement may be trusted.  An unusable result carries
    ``te_premium=None`` — never a fallback number, because a guessed
    calibration is exactly what this module exists to prevent.
    """
    rows = list(rows)
    dr = min(_dynamic_range(rows, base_key), _dynamic_range(rows, premium_key))
    if dr < CARDINAL_MIN_DYNAMIC_RANGE:
        return PairedCalibration(
            base_key=base_key,
            premium_key=premium_key,
            usable=False,
            reason=(
                f"scale is not cardinal (dynamic range {dr:.2f} < "
                f"{CARDINAL_MIN_DYNAMIC_RANGE}); ratios on a rank encoding are "
                "uninformative and the control positions pass vacuously"
            ),
        )

    by_pos: dict[str, list[tuple[float, float]]] = {}
    identical = 0
    control_rows = 0
    for r in rows:
        sv = r.get("canonicalSiteValues") or {}
        a, b = _positive(sv.get(base_key)), _positive(sv.get(premium_key))
        if a is None or b is None:
            continue
        pos = str(r.get("position") or "?").upper()
        by_pos.setdefault(pos, []).append((a, b))
        if pos in CONTROL_POSITIONS:
            control_rows += 1
            if a == b:
                identical += 1

    te_pairs = by_pos.get("TE") or []
    controls = [
        statistics.median(b / a for a, b in by_pos[p])
        for p in CONTROL_POSITIONS
        if len(by_pos.get(p) or []) >= MIN_ROWS_PER_POSITION
    ]
    if not controls or len(te_pairs) < MIN_ROWS_PER_POSITION:
        return PairedCalibration(
            base_key=base_key,
            premium_key=premium_key,
            usable=False,
            reason="insufficient overlapping rows to measure",
            control_rows=control_rows,
            te_rows=len(te_pairs),
        )

    drift = max(abs(c - 1.0) for c in controls)
    control_ratio = statistics.median(controls)
    if drift > CONTROL_DRIFT_TOLERANCE:
        return PairedCalibration(
            base_key=base_key,
            premium_key=premium_key,
            usable=False,
            reason=(
                f"confounded — control positions drift up to {drift:.2%} from unity, "
                "so the pair differs on more than TE posture"
            ),
            control_ratio=control_ratio,
            control_drift=drift,
            identical_control_rows=identical,
            control_rows=control_rows,
            te_rows=len(te_pairs),
        )

    te_ratio = statistics.median(b / a for a, b in te_pairs)
    ranked = sorted(te_pairs, key=lambda ab: -ab[1])
    bands: dict[str, float] = {}
    for label, lo, hi in depth_bands:
        chunk = ranked[lo:hi]
        if chunk:
            bands[label] = statistics.median(b / a for a, b in chunk) / control_ratio

    return PairedCalibration(
        base_key=base_key,
        premium_key=premium_key,
        usable=True,
        reason="controls at unity on a cardinal scale",
        te_premium=te_ratio / control_ratio,
        control_ratio=control_ratio,
        control_drift=drift,
        identical_control_rows=identical,
        control_rows=control_rows,
        te_rows=len(te_pairs),
        depth_bands=bands,
    )


# ── Ordinal fallback: rank displacement ───────────────────────────────
#
# Scale compression destroys CARDINAL comparison but leaves ORDINAL
# information intact.  If a board applies a TE premium, its TEs should
# sit systematically higher in rank space than on a board without one,
# relative to how the control positions move.
#
# Only trustworthy WITH A POSITIVE CONTROL.  A null from an
# underpowered test is worthless, so run the method first on a pair
# whose answer is known and confirm it fires.  On the live board the
# KTC pair (known premium 1.368) gives signal/sd 14.4 — the method has
# power; FantasyPros then gives 0.21, a genuine null rather than an
# absence of sensitivity.

MIN_POSITIVE_CONTROL_POWER = 2.0
"""Minimum signal/sd a known-premium pair must produce before a null
from the same method may be believed."""


@dataclass(frozen=True)
class RankDisplacement:
    """Ordinal TE-posture comparison between two boards."""

    base_key: str
    compare_key: str
    intersection: int
    te_rows: int
    control_rows: int
    te_median_shift: float | None
    control_median_shift: float | None
    signal_ranks: float | None
    control_dispersion: float | None
    signal_over_sd: float | None

    @property
    def detected(self) -> bool:
        """True when the TE shift stands clear of control dispersion."""
        return self.signal_over_sd is not None and abs(self.signal_over_sd) >= 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseKey": self.base_key,
            "compareKey": self.compare_key,
            "intersection": self.intersection,
            "teRows": self.te_rows,
            "controlRows": self.control_rows,
            "teMedianShift": self.te_median_shift,
            "controlMedianShift": self.control_median_shift,
            "signalRanks": self.signal_ranks,
            "controlDispersion": self.control_dispersion,
            "signalOverSd": self.signal_over_sd,
            "detected": self.detected,
        }


def measure_rank_displacement(
    rows: list[Mapping[str, Any]],
    base_key: str,
    compare_key: str,
) -> RankDisplacement:
    """Compare TE placement between two boards in RANK space.

    Both boards are ranked over their intersection so the ranks are
    commensurable.  Positive ``signal_ranks`` means the comparison
    board places TEs higher than the base board, beyond whatever shift
    the control positions show.

    Works on rank-encoded sources that
    :func:`measure_paired_te_premium` must reject — but validate on a
    known pair (see ``MIN_POSITIVE_CONTROL_POWER``) before believing a
    null.
    """
    pairs: list[tuple[str, float, float]] = []
    for r in rows:
        sv = r.get("canonicalSiteValues") or {}
        a, b = _positive(sv.get(base_key)), _positive(sv.get(compare_key))
        if a is not None and b is not None:
            pairs.append((str(r.get("position") or "?").upper(), a, b))

    empty = RankDisplacement(base_key, compare_key, len(pairs), 0, 0, None, None, None, None, None)
    if len(pairs) < MIN_ROWS_PER_POSITION * 2:
        return empty

    base_rank = {
        i: n for n, i in enumerate(sorted(range(len(pairs)), key=lambda i: -pairs[i][1]), 1)
    }
    cmp_rank = {
        i: n for n, i in enumerate(sorted(range(len(pairs)), key=lambda i: -pairs[i][2]), 1)
    }

    te_shifts: list[float] = []
    control_shifts: list[float] = []
    for i, (pos, _, _) in enumerate(pairs):
        shift = base_rank[i] - cmp_rank[i]  # positive = compare ranks better
        if pos == "TE":
            te_shifts.append(shift)
        elif pos in CONTROL_POSITIONS:
            control_shifts.append(shift)

    if len(te_shifts) < MIN_ROWS_PER_POSITION or len(control_shifts) < MIN_ROWS_PER_POSITION:
        return RankDisplacement(
            base_key,
            compare_key,
            len(pairs),
            len(te_shifts),
            len(control_shifts),
            None,
            None,
            None,
            None,
            None,
        )

    te_med = statistics.median(te_shifts)
    ctrl_med = statistics.median(control_shifts)
    dispersion = statistics.pstdev(control_shifts)
    signal = te_med - ctrl_med
    return RankDisplacement(
        base_key=base_key,
        compare_key=compare_key,
        intersection=len(pairs),
        te_rows=len(te_shifts),
        control_rows=len(control_shifts),
        te_median_shift=te_med,
        control_median_shift=ctrl_med,
        signal_ranks=signal,
        control_dispersion=dispersion,
        signal_over_sd=(signal / dispersion) if dispersion > 0 else None,
    )


# ── First-principles derivation from our own replacement levels ───────


@dataclass(frozen=True)
class DerivedStructuralPremium:
    """TE premium derived from replacement levels, not from any vendor.

    Comparable to :class:`PairedCalibration` by design so the two
    independent routes can be diffed directly.
    """

    required_starters_reference: int
    required_starters_league: int
    replacement_reference: float
    replacement_league: float
    additive_shift: float
    premium_at_median: float | None
    depth_bands: dict[str, float] = field(default_factory=dict)
    pool_size: int = 0
    form: str = "additive_shift"

    def premium_for(self, value: float) -> float | None:
        """Depth-graded multiplier for a TE worth ``value``."""
        if value is None or value <= 0:
            return None
        return 1.0 + (self.additive_shift / value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "requiredStartersReference": self.required_starters_reference,
            "requiredStartersLeague": self.required_starters_league,
            "replacementReference": self.replacement_reference,
            "replacementLeague": self.replacement_league,
            "additiveShift": self.additive_shift,
            "premiumAtMedian": self.premium_at_median,
            "depthBands": dict(self.depth_bands),
            "poolSize": self.pool_size,
            "form": self.form,
        }


def derive_structural_te_premium(
    te_values: Sequence[float],
    *,
    required_starters_reference: int = 12,
    required_starters_league: int = 24,
    band: int = 2,
    depth_bands: tuple[tuple[str, int, int], ...] = DEFAULT_DEPTH_BANDS,
) -> DerivedStructuralPremium | None:
    """Derive the 2-TE structural premium from OUR pool's replacement levels.

    Independent of any vendor: the only inputs are this league's TE
    value curve and how many TE starters each calibration requires.

    **Form matters more than the concept.**  The obvious VOR ratio

        premium(V) = (V - R_league) / (V - R_reference)

    is REJECTED.  It has a pole at ``V == R_reference`` and, tested
    against KTC's own paired boards, predicts a **negative** premium
    (-0.30) for the TE13-24 band where the true value is 1.27.  Its
    hidden premise — that value is proportional to value-over-
    replacement — is empirically false for these boards: a
    replacement-level TE is priced around 2,500, not 0.

    The additive-shift form used here carries no such premise:

        premium(V) = 1 + (R_reference - R_league) / V

    Doubling required starters pushes replacement down by a fixed
    amount, and that fixed amount is worth proportionally more to a
    cheap player than a expensive one — which reproduces the observed
    depth grading rather than assuming it.

    **IDP-invariant by construction.**  Only TE values enter.  Adding
    or removing IDP players cannot change which TE is 12th or 24th, so
    the premium is unaffected by board composition — provable, not
    assumed, and pinned by test.

    Returns ``None`` when the pool is too shallow to locate both
    replacement levels.
    """
    values = sorted((float(v) for v in te_values if v and float(v) > 0), reverse=True)
    if len(values) < max(required_starters_league, required_starters_reference) + band:
        return None

    def banded(rank: int) -> float:
        idx = min(max(1, rank), len(values)) - 1
        lo, hi = max(0, idx - band), min(len(values), idx + band + 1)
        return statistics.fmean(values[lo:hi])

    r_ref = banded(required_starters_reference)
    r_league = banded(required_starters_league)
    shift = r_ref - r_league

    bands: dict[str, float] = {}
    for label, lo, hi in depth_bands:
        chunk = values[lo:hi]
        if chunk:
            bands[label] = statistics.median(1.0 + (shift / v) for v in chunk)

    median_value = statistics.median(values[:required_starters_league])
    return DerivedStructuralPremium(
        required_starters_reference=required_starters_reference,
        required_starters_league=required_starters_league,
        replacement_reference=r_ref,
        replacement_league=r_league,
        additive_shift=shift,
        premium_at_median=(1.0 + shift / median_value) if median_value > 0 else None,
        depth_bands=bands,
        pool_size=len(values),
    )


# ── Reconciling the independent estimates ─────────────────────────────

CLUSTER_TOLERANCE = 0.10
"""Estimates within this absolute spread are treated as agreeing.  Wide
enough to tolerate real board differences, tight enough that a house
view stands out."""


@dataclass(frozen=True)
class PremiumConsensus:
    """Reconciliation of independent TE-premium estimates.

    ``operative`` is ALWAYS the derived value when present.  Market
    measurements are cross-checks: they are observations of
    offense-only boards that structurally cannot contain half this
    league's starters, so their agreement validates the method rather
    than making their number more applicable than ours.
    """

    operative: float | None
    operative_source: str
    estimates: dict[str, float] = field(default_factory=dict)
    spread: float | None = None
    clustered: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "operative": self.operative,
            "operativeSource": self.operative_source,
            "estimates": dict(self.estimates),
            "spread": self.spread,
            "clustered": self.clustered,
            "notes": list(self.notes),
        }


def compare_premium_estimates(
    *,
    derived: float | None,
    market: Mapping[str, float | None] | None = None,
    tolerance: float = CLUSTER_TOLERANCE,
) -> PremiumConsensus:
    """Reconcile the derived premium against market measurements.

    ``market`` maps a publisher label to its measured premium (``None``
    for publishers that could not be measured — they are recorded as
    absent rather than dropped, so thin coverage never reads as
    disagreement).
    """
    estimates: dict[str, float] = {}
    notes: list[str] = []
    for label, value in (market or {}).items():
        if value is None:
            notes.append(f"{label}: not measurable — absent, NOT evidence of disagreement")
        else:
            estimates[label] = float(value)

    if derived is not None:
        estimates["derived"] = float(derived)

    values = list(estimates.values())
    spread = (max(values) - min(values)) if len(values) >= 2 else None
    clustered = spread is not None and spread <= tolerance
    if spread is not None and not clustered:
        notes.append(
            f"estimates span {spread:.3f} (> {tolerance:.2f}) — investigate before applying"
        )
    if len(values) < 2:
        notes.append("single estimate only — no cross-check available")

    return PremiumConsensus(
        operative=derived,
        operative_source="derived (our pool, our replacement levels)"
        if derived is not None
        else "none",
        estimates=estimates,
        spread=spread,
        clustered=clustered,
        notes=notes,
    )
