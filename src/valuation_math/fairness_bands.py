"""The ONE fairness-band owner (TC-C owner decision 3, 2026-10-18; v2 owner
decisions 2026-10-20).

Every surface that labels how far apart two packages are -- the /trade meter
and sticky tray, the balancer triggers, the fairness explanation, the Analyze
Trade market lens and private Asset-Only decision, Best Offers, the package
builder, the suggestions badge and any multi-team / public adapter --
classifies the gap here (Python) or through the pinned JS mirror
``frontend/lib/fairness-bands.js``.

``fairness_bands_v2`` (``config/trade/fairness_bands.json``, status
``PRIOR_OWNER_APPROVED_2026-10-20``): a RELATIVE difference with an ABSOLUTE
MINIMUM, where the relative base is the LARGER PACKAGE UTILITY (OD-F2) -- the
active package model's depth-discounted value of each package
(:func:`package_utilities`) -- rather than the larger adjusted side.  The gap a
caller passes is unchanged (``recvAdjusted - sendAdjusted``, which equals
``U_R - U_G`` under ``geom_q078_v1``), so numerator and denominator share one
scale.  The denominator is decided HERE: callers obtain it from
:func:`larger_package_utility` / :func:`fairness_base`, or call
:func:`classify_packages` and never compute a base of their own.

Missing input is REFUSED (:class:`FairnessInputError`), never classified:
MISSING IS NEVER ZERO, and a NaN gap is not "fair".  Refused identically by the
JS mirror (shared fixture ``tests/fixtures/fairness_band_refusal_cases.json``):

* a non-finite gap or base, a negative base, a non-number (code
  ``fairness_input_not_finite``);
* a missing utilities container (``None``, a mapping, a string) and a
  non-finite package PIECE value at :func:`package_utilities` -- the package
  model prices a NaN piece as absent, so the owner checks every piece before
  delegating (same code);
* a zero base beside a gap at or above the absolute minimum (code
  ``fairness_input_inconsistent``): ``|gap| <= max utility`` under every
  package model, and an N-team set with base 0 has every net 0, so that pair
  can only come from missing utilities -- and above the floor the verdict
  depends on the base.  Below the floor every base reads ``fair``, so a zero
  base there is answered.

The package model and q = 0.78 are not touched here.  Stdlib only (plus the
stdlib-only package-model dispatch), so ``src.public_league`` may import it.
"""

from __future__ import annotations

import json
import math
import numbers
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Iterable

from src.valuation_math import package_model

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "fairness_bands.json"

#: Band levels, mildest first.  The keys match the meter's CSS vocabulary.
LEVELS = ("fair", "slight", "unfair", "lopsided")
LABELS = {"fair": "FAIR", "slight": "SLIGHT EDGE", "unfair": "UNFAIR", "lopsided": "LOPSIDED"}

#: The one basis this owner implements.  A config naming another basis is a
#: hard error: the denominator rule lives in code, the config only records it.
BASIS = "larger_package_utility"

#: Machine-readable refusal codes, identical in the JS mirror.
INPUT_ERROR_CODE = "fairness_input_not_finite"
INPUT_INCONSISTENT_CODE = "fairness_input_inconsistent"


class FairnessInputError(ValueError):
    """Input the owner refuses to classify (see the module docstring).

    Refused rather than classified: the old behaviour (JS ``fair``, Python
    ``lopsided`` on ``NaN``) let an unknown quantity read as a verdict.
    ``code`` is :data:`INPUT_ERROR_CODE` for missing / non-finite input and
    :data:`INPUT_INCONSISTENT_CODE` for a zero base beside a gap at or above
    the absolute minimum.
    """

    code = INPUT_ERROR_CODE

    def __init__(self, message: str, code: str = INPUT_ERROR_CODE) -> None:
        super().__init__(message)
        self.code = code


def _load() -> dict[str, Any]:
    raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("absoluteMinimum", "slightPct", "unfairPct", "lopsidedPct"):
        if not isinstance(raw.get(key), (int, float)) or isinstance(raw.get(key), bool):
            raise ValueError(f"fairness_bands.json: {key} must be a number")
    if not raw["slightPct"] < raw["unfairPct"] < raw["lopsidedPct"]:
        raise ValueError("fairness_bands.json: cut points must increase")
    if raw.get("basis") != BASIS:
        raise ValueError(f"fairness_bands.json: basis must be {BASIS!r}")
    levels = raw.get("fairTradeLevels")
    if not isinstance(levels, list) or not levels or not set(levels) <= set(LEVELS):
        raise ValueError(
            "fairness_bands.json: fairTradeLevels must be a non-empty subset of LEVELS"
        )
    for key in ("version", "status"):
        if not isinstance(raw.get(key), str) or not raw[key]:
            raise ValueError(f"fairness_bands.json: {key} must be a non-empty string")
    return raw


# Loaded once; a missing or malformed owner is a hard error, never a silent
# default band.
CONFIG: dict[str, Any] = _load()
ABSOLUTE_MINIMUM: float = float(CONFIG["absoluteMinimum"])
SLIGHT_PCT: float = float(CONFIG["slightPct"])
UNFAIR_PCT: float = float(CONFIG["unfairPct"])
LOPSIDED_PCT: float = float(CONFIG["lopsidedPct"])
#: OD-F1 (2026-10-20): the band level(s) that count as a FAIR TRADE in a
#: binary fair / not-fair answer.  Read it through :func:`counts_as_fair_trade`.
FAIR_TRADE_LEVELS: tuple[str, ...] = tuple(CONFIG["fairTradeLevels"])


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
        "fairTradeLevels": list(FAIR_TRADE_LEVELS),
        "postLaunchValidation": (CONFIG.get("postLaunchValidation") or {}).get("id"),
    }


# ── Inputs ─────────────────────────────────────────────────────────────────


def _is_finite_number(x: Any) -> bool:
    # numbers.Real, so numpy.int64 and numpy.float64 are treated alike; bool is
    # excluded (True is not a value).
    return isinstance(x, numbers.Real) and not isinstance(x, bool) and math.isfinite(x)


def _require_container(values: Any, what: str) -> list[Any]:
    """A list of the entries of an iterable; ``None``, a mapping, a string or a
    non-iterable is a missing container, refused (JS: anything but an array)."""
    if values is None or isinstance(values, (Mapping, str, bytes)):
        raise FairnessInputError(f"{INPUT_ERROR_CODE}: {what}={values!r}")
    try:
        return list(values)
    except TypeError:
        raise FairnessInputError(f"{INPUT_ERROR_CODE}: {what}={values!r}") from None


def _require_pieces(values: Any, what: str) -> list[float]:
    """Every package piece must be a finite number (a NaN piece is missing,
    never an absent piece worth 0).  Non-positive pieces stay as given: the
    package model already treats them as contributing nothing."""
    pieces = _require_container(values, what)
    for v in pieces:
        if not _is_finite_number(v):
            raise FairnessInputError(f"{INPUT_ERROR_CODE}: {what} piece={v!r}")
    return [float(v) for v in pieces]


def _js_round(x: float) -> int:
    """JavaScript ``Math.round`` for the published numbers (half toward +inf,
    exact: ``x - floor(x)`` is exact for finite doubles), so the rounded
    ``relativePct`` / ``absoluteGap`` match the JS mirror bit for bit."""
    r = math.floor(x)
    return r + 1 if x - r >= 0.5 else r


def _require_gap(gap: Any) -> float:
    if not _is_finite_number(gap):
        raise FairnessInputError(f"{INPUT_ERROR_CODE}: gap={gap!r}")
    return float(gap)


def _require_base(base: Any) -> float:
    if not _is_finite_number(base) or base < 0:
        raise FairnessInputError(f"{INPUT_ERROR_CODE}: base={base!r}")
    return float(base)


# ── The denominator (OD-F2) ────────────────────────────────────────────────


def package_utilities(
    side_a_values: Iterable[float],
    side_b_values: Iterable[float],
    *,
    model_id: str | None = None,
) -> tuple[float, float]:
    """``(U_A, U_B)``: each package's utility under the package model.

    ``geom`` family: the depth-discounted utility ``package_model.geom_utility``
    (the same IEEE-754 operations as ``trade-logic.js::geomPackageUtility``).
    ``ktc`` family (the rollback model) has no per-package utility, so the
    pair's adjusted totals stand in -- exactly the v1 basis, so a package-model
    rollback restores v1 denominators.  ``model_id=None`` = the ACTIVE model.

    Every piece must be a finite number (:class:`FairnessInputError`
    otherwise): the package model drops a NaN piece as if it were absent, so
    without this check a missing value would be priced as 0.
    """
    a = _require_pieces(side_a_values, "side_a_values")
    b = _require_pieces(side_b_values, "side_b_values")
    mid = package_model.resolve_model_id(model_id)
    spec = package_model.PACKAGE_MODELS[mid]
    if spec["family"] == "geom":
        q = spec["q"]
        return package_model.geom_utility(a, q), package_model.geom_utility(b, q)
    a_adj, b_adj, _, _ = package_model.adjusted_pair_totals(a, b, model_id=mid)
    return float(a_adj), float(b_adj)


def fairness_base(utilities: Iterable[Any]) -> float:
    """The band's relative base: the LARGEST package utility among the sides.

    Every entry must be a finite, non-negative number and the container must
    be present (else :class:`FairnessInputError`); no sides is an empty pairing
    with base 0.  The JS twin is ``fairness-bands.js::fairnessBase``.
    """
    base = 0.0
    for u in _require_container(utilities, "utilities"):
        base = max(base, _require_base(u))
    return base


def larger_package_utility(
    side_a_values: Iterable[float],
    side_b_values: Iterable[float],
    *,
    model_id: str | None = None,
) -> float:
    """``max(U_A, U_B)`` -- the denominator every consumer passes to
    :func:`classify` (never the larger ADJUSTED side, which was v1)."""
    return fairness_base(package_utilities(side_a_values, side_b_values, model_id=model_id))


# ── Classification ─────────────────────────────────────────────────────────


def relative_pct(gap: float, larger_utility: float) -> float | None:
    """``|gap|`` as a percentage of the larger package utility; ``None`` when
    the base is 0 (an empty pairing: nothing to be relative to).  Refuses
    non-finite input."""
    g = _require_gap(gap)
    base = _require_base(larger_utility)
    if base == 0:
        return None
    return abs(g) / base * 100.0


def classify(gap: float, larger_utility: float) -> dict[str, Any]:
    """Classify one package gap.

    ``gap`` is signed (either convention: only its size is classified);
    ``larger_utility`` is the larger PACKAGE UTILITY -- obtain it from
    :func:`larger_package_utility` or :func:`fairness_base`.  An empty pairing
    (base 0, gap under the absolute minimum) is ``fair`` with ``relativePct``
    ``None`` -- there is nothing to be unfair about -- and callers that must
    refuse an empty trade do so before asking.  Non-finite input, and a zero
    base beside a gap at or above the absolute minimum, raise
    :class:`FairnessInputError`.
    """
    g = _require_gap(gap)
    absolute = abs(g)
    rel = relative_pct(g, larger_utility)
    if rel is None and absolute >= ABSOLUTE_MINIMUM:
        raise FairnessInputError(
            f"{INPUT_INCONSISTENT_CODE}: gap={g!r} base=0", code=INPUT_INCONSISTENT_CODE
        )
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
        "absoluteGap": _js_round(absolute * 10.0) / 10.0,
        "relativePct": None if rel is None else _js_round(rel * 100.0) / 100.0,
        "bands": CONFIG["version"],
        "status": CONFIG["status"],
    }


def classify_packages(
    gap: float,
    side_a_values: Iterable[float],
    side_b_values: Iterable[float],
    *,
    model_id: str | None = None,
) -> dict[str, Any]:
    """:func:`classify` with the denominator computed here from the two
    packages' values (the form to prefer when the values are at hand)."""
    return classify(gap, larger_package_utility(side_a_values, side_b_values, model_id=model_id))


def fair_threshold(larger_utility: float) -> float:
    """The absolute gap at which a pairing with this base leaves the fair band."""
    return max(ABSOLUTE_MINIMUM, SLIGHT_PCT / 100.0 * _require_base(larger_utility))


def counts_as_fair_trade(level: Any) -> bool:
    """OD-F1: whether a band level counts as a FAIR TRADE (``fair`` only in
    v2).  Anything that is not a known level is not fair (fail closed)."""
    return level in FAIR_TRADE_LEVELS


def legacy_magnitude(level: str) -> str:
    """The market-lens / suggestions vocabulary (``even`` / ``lean`` /
    ``stretch``) for a band level, so existing consumers keep their keys while
    the boundaries come from this owner."""
    return {"fair": "even", "slight": "lean"}.get(level, "stretch")


def is_even(gap: float, larger_utility: float) -> bool:
    """True when the gap is inside the fair band (no balancing needed)."""
    return classify(gap, larger_utility)["level"] == "fair"
