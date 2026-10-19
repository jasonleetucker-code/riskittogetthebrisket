"""Package Value Adjustment model dispatch — the ONE place a model is chosen.

Owner package 2026-10-17 (``CLAUDE_MASTER_IMPLEMENTATION_PROMPT_TRADE_CALCULATOR``
and its sitewide spec): every surface that publishes package-level trade
equity must use the SAME named, versioned model, so the calculator, trade
history, public league grades, finder, suggestions, angles, analyze and Monte
Carlo cannot disagree about one trade.  Before this module each of them called
KTC's port directly and nothing could say which model produced a number.

Two models are registered:

* ``ktc_2026_04`` — the retained rollback model: KTC's ``adjustPackage``
  (``ktc_va_core.adjust_package_raw``), unchanged.  Its known non-monotone
  cases (adding a positive asset can WORSEN the adding side, e.g. ``[7200]``
  vs ``[6000, 500]``) are pinned as known defects, not fixed silently, because
  the method label promises KTC's behaviour.
* ``geom_q078_v1`` — owner-approved active model (2026-10-17); independent
  held-out real-trade results remain inconclusive. Sorted package utility
  ``U(P) = sum q**(i-1) * v_i`` (values descending, ``q = 0.78`` — a PRIOR,
  not a fitted constant), shown as KTC's familiar positive-only adjustment:
  with ``D = raw - U`` per side, the side that discarded less depth receives
  ``|D_A - D_B|``, so ``adjusted_A - adjusted_B == U_A - U_B`` (up to integer
  rounding).  Monotone, side-symmetric, permutation invariant, positively
  homogeneous, and 1-for-1 carries no adjustment.

The dispatch keeps KTC's ``(value, side, displayed)`` shape (``side`` 1 =
team1 receives, 2 = team2, 0 = none) so every consumer's contract is
unchanged; :func:`receipt` is what responses stamp as ``packageModel``.

Stdlib only and free of private business logic, so ``src.public_league`` may
import it (``tests/public_league/test_public_contract.py::ImportSurfaceTests``).
The JS twin is ``frontend/lib/trade-logic.js::packageAdjustPair``; parity is
pinned by ``tests/fixtures/package_model_parity_cases.json``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Literal

from src.valuation_math.ktc_va_core import adjust_package_raw, js_round

KTC_2026_04 = "ktc_2026_04"
GEOM_Q078_V1 = "geom_q078_v1"

PACKAGE_MODELS: dict[str, dict[str, Any]] = {
    KTC_2026_04: {
        "id": KTC_2026_04,
        "family": "ktc",
        "version": "2026-04",
        "label": "KTC Value Adjustment (port of keeptradecut.com adjustPackage, April 2026)",
        "classification": "FALLBACK",
    },
    GEOM_Q078_V1: {
        "id": GEOM_Q078_V1,
        "family": "geom",
        "version": "1",
        "q": 0.78,
        "label": "Geometric Value Adjustment (q = 0.78)",
        "classification": "ACTIVE",
    },
}

DEFAULT_ACTIVE = KTC_2026_04
_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "package_model.json"


ConfigState = Literal["ok", "unreadable", "unknown_active"]


@lru_cache(maxsize=1)
def _config() -> dict[str, Any]:
    """The committed config; any unreadable or unknown value falls back to the
    incumbent — a broken config must never silently promote a challenger.

    ``state`` records what was actually read (:func:`config_state`), so a
    caller that must not run on the fallback can tell it happened.
    """
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("package model config is not an object")
    except (OSError, ValueError):
        return {"active": DEFAULT_ACTIVE, "shadow": [], "state": "unreadable"}
    known = raw.get("active") in PACKAGE_MODELS
    active = raw.get("active") if known else DEFAULT_ACTIVE
    shadow = [m for m in raw.get("shadow") or [] if m in PACKAGE_MODELS and m != active]
    return {"active": active, "shadow": shadow, "state": "ok" if known else "unknown_active"}


def config_state() -> ConfigState:
    """What :func:`_config` saw: ``"ok"`` (the committed active model was
    read), ``"unreadable"`` (missing / malformed file) or ``"unknown_active"``
    (a model id this module does not register).  In both failure states the
    dispatch is running on the ``DEFAULT_ACTIVE`` fallback, not the
    committed choice — a surface that must not silently change model (the
    public Brisket Trade Advisor) refuses instead of answering."""
    return _config()["state"]


def active_model_id() -> str:
    return _config()["active"]


def shadow_model_ids() -> list[str]:
    return list(_config()["shadow"])


def resolve_model_id(model_id: str | None = None) -> str:
    if model_id is None:
        return active_model_id()
    if model_id not in PACKAGE_MODELS:
        raise ValueError(f"unknown package model {model_id!r}")
    return model_id


def receipt(model_id: str | None = None) -> dict[str, Any]:
    """``packageModel`` stamp: which model produced a package-equity number."""
    spec = PACKAGE_MODELS[resolve_model_id(model_id)]
    return {
        "id": spec["id"],
        "family": spec["family"],
        "version": spec["version"],
        "label": spec["label"],
        "classification": spec["classification"],
    }


def _positive_desc(values: Iterable[float]) -> list[float]:
    return sorted(
        (float(v) for v in values if v is not None and float(v) > 0),
        reverse=True,
    )


def _left_sum(values: Iterable[float]) -> float:
    """Plain left-to-right float addition — what JavaScript's ``reduce`` does.

    Deliberately NOT ``sum()``: CPython 3.12+ compensates float ``sum()``,
    so the two languages could disagree in the last bit on the same inputs.
    """
    total = 0.0
    for v in values:
        total += v
    return total


def geom_utility(values: Iterable[float], q: float = PACKAGE_MODELS[GEOM_Q078_V1]["q"]) -> float:
    """``sum q**i * v_i`` over positive values sorted descending.

    Weights are built iteratively (``w *= q``) and summed with a left fold —
    never ``**`` / ``Math.pow``, whose results differ between CPython and V8
    from ``i = 4`` — so this and ``trade-logic.js::geomPackageUtility`` are
    the same IEEE-754 operations in the same order (bit-identical; pinned by
    ``tests/fixtures/package_model_float_cases.json``).
    """
    total = 0.0
    w = 1.0
    for v in _positive_desc(values):
        total += v * w
        w *= q
    return total


def _geom_pair(t1: list[float], t2: list[float], q: float) -> tuple[int, int, bool]:
    depth1 = _left_sum(t1) - geom_utility(t1, q)
    depth2 = _left_sum(t2) - geom_utility(t2, q)
    value = js_round(abs(depth1 - depth2))
    if value <= 0:
        return 0, 0, False
    # The side that discarded LESS depth receives the difference.
    return value, (1 if depth2 > depth1 else 2), True


def adjust_pair(
    team1_vals: Iterable[float],
    team2_vals: Iterable[float],
    *,
    model_id: str | None = None,
) -> tuple[int, int, bool]:
    """``(value, side, displayed)`` for one package pairing under a model.

    ``model_id=None`` uses the ACTIVE model.  Empty sides answer no
    adjustment, exactly as KTC does.
    """
    mid = resolve_model_id(model_id)
    t1 = _positive_desc(team1_vals)
    t2 = _positive_desc(team2_vals)
    if not t1 or not t2:
        return 0, 0, False
    if PACKAGE_MODELS[mid]["family"] == "ktc":
        return adjust_package_raw(t1, t2)
    return _geom_pair(t1, t2, PACKAGE_MODELS[mid]["q"])


def adjusted_pair_totals(
    small_values: Iterable[float],
    large_values: Iterable[float],
    *,
    model_id: str | None = None,
) -> tuple[float, float, float, float]:
    """``(small_adjusted, large_adjusted, small_va, large_va)`` under a model.

    The model-dispatched form of ``src.trade.ktc_va.adjusted_pair_totals``:
    each side's adjusted total is its raw sum plus its (>= 0) adjustment.
    """
    small = _positive_desc(small_values)
    large = _positive_desc(large_values)
    small_sum, large_sum = sum(small), sum(large)
    value, side, displayed = adjust_pair(small, large, model_id=model_id)
    if not displayed or value <= 0:
        return small_sum, large_sum, 0.0, 0.0
    if side == 1:
        return small_sum + value, large_sum, float(value), 0.0
    return small_sum, large_sum + value, 0.0, float(value)
