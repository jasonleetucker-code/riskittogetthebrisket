"""The ONE fairness-band owner (TC-C, owner decision 3, 2026-10-18).

Every surface that labels how far apart two packages are -- the /trade meter
and sticky tray, the balancer triggers, the fairness explanation, the Analyze
Trade market lens and decision, Best Offers, the package builder and the
suggestions badge -- classifies the gap here (Python) or through the pinned JS
mirror ``frontend/lib/fairness-bands.js``.  Before this module each surface
carried its own absolute band (meter 350 / 900 / 1800, market lens 256 / 769,
balancers 350 / 256, explanation and winner text 3%), calibrated under the KTC
package model and blind to package size.

Owner decision 3: a RELATIVE difference with an ABSOLUTE MINIMUM, provisional
until validated on offense, IDP, picks, consolidation and large packages.  The
numbers live in ``config/trade/fairness_bands.json`` (status ``PROVISIONAL``)
with their derivation.  The basis is always the ADJUSTED package totals (raw +
the active package model's adjustment); the package model and q = 0.78 are not
touched here.

Stdlib only, so ``src.public_league`` may import it.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "fairness_bands.json"

#: Band levels, mildest first.  The keys match the meter's CSS vocabulary.
LEVELS = ("fair", "slight", "unfair", "lopsided")
LABELS = {"fair": "FAIR", "slight": "SLIGHT EDGE", "unfair": "UNFAIR", "lopsided": "LOPSIDED"}


def _load() -> dict[str, Any]:
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("absoluteMinimum", "slightPct", "unfairPct", "lopsidedPct"):
        if not isinstance(raw.get(key), (int, float)) or isinstance(raw.get(key), bool):
            raise ValueError(f"fairness_bands.json: {key} must be a number")
    if not raw["slightPct"] < raw["unfairPct"] < raw["lopsidedPct"]:
        raise ValueError("fairness_bands.json: cut points must increase")
    return raw


# Loaded once; a missing or malformed owner is a hard error, never a silent
# default band.
CONFIG: dict[str, Any] = _load()
ABSOLUTE_MINIMUM: float = float(CONFIG["absoluteMinimum"])
SLIGHT_PCT: float = float(CONFIG["slightPct"])
UNFAIR_PCT: float = float(CONFIG["unfairPct"])
LOPSIDED_PCT: float = float(CONFIG["lopsidedPct"])


def receipt() -> dict[str, Any]:
    """What a consumer stamps so a reader knows which bands produced a label."""
    return {
        "version": CONFIG["version"],
        "status": CONFIG["status"],
        "basis": CONFIG["basis"],
        "absoluteMinimum": ABSOLUTE_MINIMUM,
        "slightPct": SLIGHT_PCT,
        "unfairPct": UNFAIR_PCT,
        "lopsidedPct": LOPSIDED_PCT,
    }


def relative_pct(gap: float, larger_side: float) -> float | None:
    """``|gap|`` as a percentage of the larger adjusted side; ``None`` when the
    larger side is not a positive number (nothing to be relative to)."""
    if not isinstance(larger_side, (int, float)) or not math.isfinite(larger_side):
        return None
    if larger_side <= 0:
        return None
    return abs(float(gap)) / float(larger_side) * 100.0


def classify(gap: float, larger_side: float) -> dict[str, Any]:
    """Classify one package gap.

    ``gap`` is signed (either convention: only its size is classified);
    ``larger_side`` is the larger ADJUSTED package total.  An empty pairing
    (no positive side) is ``fair`` with ``relativePct`` ``None`` -- there is
    nothing to be unfair about -- and callers that must refuse an empty trade
    do so before asking.
    """
    absolute = abs(float(gap))
    rel = relative_pct(gap, larger_side)
    if absolute < ABSOLUTE_MINIMUM or rel is None or rel < SLIGHT_PCT:
        level = "fair"
    elif rel < UNFAIR_PCT:
        level = "slight"
    elif rel < LOPSIDED_PCT:
        level = "unfair"
    else:
        level = "lopsided"
    return {
        "level": level,
        "label": LABELS[level],
        "absoluteGap": round(absolute, 1),
        "relativePct": None if rel is None else round(rel, 2),
        "bands": CONFIG["version"],
        "status": CONFIG["status"],
    }


def legacy_magnitude(level: str) -> str:
    """The market-lens / suggestions vocabulary (``even`` / ``lean`` /
    ``stretch``) for a band level, so existing consumers keep their keys while
    the boundaries come from this owner."""
    return {"fair": "even", "slight": "lean"}.get(level, "stretch")


def is_even(gap: float, larger_side: float) -> bool:
    """True when the gap is inside the fair band (no balancing needed)."""
    return classify(gap, larger_side)["level"] == "fair"
