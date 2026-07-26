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
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

__all__ = [
    "CARDINAL_MIN_DYNAMIC_RANGE",
    "CONTROL_POSITIONS",
    "PairedCalibration",
    "measure_paired_te_premium",
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
