"""Dynamic source-weight fitter with 4-week smoothing +
approval-gate on large swings.

Input: list of ``SourceAccuracy`` from the correlation module.
Output: ``{source: weight}`` dict, normalized to sum to 1.0.

Smoothing
---------
A 4-week exponential moving average tempers week-to-week noise.
``alpha=0.25`` means last week's score contributes 25%, prior
weeks 75% — moderate responsiveness.

Approval gate
-------------
When the proposed new weights move any single source by more
than ``tolerance_pct`` (default 0.15 → 15%), ``propose_weights``
returns ``{...status: "pending_approval"}`` instead of
finalizing.  The monthly-refit cron honors that and opens a
PR rather than committing.

Read gate
---------
The live contract builder ONLY reads dynamic weights when the
``dynamic_source_weights`` feature flag is on.  Without it, the
existing ``config/weights/default.json`` (or whatever the
canonical pipeline uses today) is unchanged.  Shipping this
module can't regress rankings until the flag flips.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.backtesting.correlation import SourceAccuracy

_LOGGER = logging.getLogger(__name__)

# Minimum n_players for a source to be considered — prevents a
# source with only 5 common players from earning a huge weight.
_MIN_N_PLAYERS = 40


@dataclass(frozen=True)
class ProposedWeights:
    weights: dict[str, float]
    status: str  # "approved" | "pending_approval" | "no_change"
    max_drift_pct: float
    drift_by_source: dict[str, float]


def raw_weights_from_accuracy(
    accuracies: list[SourceAccuracy],
    *,
    floor: float = 0.05,
) -> dict[str, float]:
    """Convert Spearman rhos to raw weights via a shifted softmax.

    Negative rho doesn't contribute — we still give eligible sources
    a ``floor`` so no source gets zero weight until a human says so.
    """
    eligible = [a for a in accuracies if a.n_players >= _MIN_N_PLAYERS]
    if not eligible:
        return {}
    # Shift to [0, 2] — rho=1 → weight exp(2), rho=-1 → exp(-0).
    import math
    weights_raw = {a.source: math.exp(max(0.0, a.spearman_rho + 1.0)) for a in eligible}
    total = sum(weights_raw.values())
    normalized = {s: max(floor, w / total) for s, w in weights_raw.items()}
    # Renormalize after floor.
    total2 = sum(normalized.values())
    return {s: w / total2 for s, w in normalized.items()}


def smooth_weights_ewma(
    prior: dict[str, float],
    new: dict[str, float],
    *,
    alpha: float = 0.25,
) -> dict[str, float]:
    """Exponential moving average per source.

    ``alpha`` is the weight of the new observation; (1-alpha) is
    the weight of prior.  Default 0.25 → gentle month-over-month
    drift.  Sources present in one dict but not the other are
    carried verbatim (no halving to zero).
    """
    out: dict[str, float] = {}
    all_sources = set(prior.keys()) | set(new.keys())
    for s in all_sources:
        p = prior.get(s)
        n = new.get(s)
        if p is None:
            out[s] = float(n)
        elif n is None:
            out[s] = float(p)
        else:
            out[s] = (1 - alpha) * float(p) + alpha * float(n)
    # Renormalize so it still sums to 1.
    total = sum(out.values())
    if total <= 0:
        return out
    return {s: w / total for s, w in out.items()}


def propose_weights(
    accuracies: list[SourceAccuracy],
    prior_weights: dict[str, float],
    *,
    alpha: float = 0.25,
    tolerance_pct: float = 0.15,
) -> ProposedWeights:
    """Full pipeline: rho → raw weights → smoothed → approval gate.

    Returns ``{weights, status, max_drift_pct, drift_by_source}``.
    """
    raw = raw_weights_from_accuracy(accuracies)
    if not raw:
        return ProposedWeights(
            weights=dict(prior_weights),
            status="no_change",
            max_drift_pct=0.0,
            drift_by_source={},
        )
    smoothed = smooth_weights_ewma(prior_weights, raw, alpha=alpha)

    # Drift check: largest |pct change| from prior to smoothed.
    drift_by: dict[str, float] = {}
    max_drift = 0.0
    for s, new_w in smoothed.items():
        p = prior_weights.get(s)
        if p is None or p <= 0:
            drift_by[s] = 1.0  # brand-new source
            max_drift = max(max_drift, 1.0)
            continue
        pct = (new_w - p) / p
        drift_by[s] = round(pct, 4)
        if abs(pct) > max_drift:
            max_drift = abs(pct)

    status = "pending_approval" if max_drift > tolerance_pct else "approved"
    return ProposedWeights(
        weights=smoothed,
        status=status,
        max_drift_pct=round(max_drift, 4),
        drift_by_source=drift_by,
    )


def load_prior_weights(path: Path | None = None) -> dict[str, float]:
    """Load weights from disk, returning {} if absent.

    File shape:
        {"fetched_at": "...", "alpha": 0.25, "weights": {...}}
    """
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "weights" / "dynamic_source_weights.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    weights = raw.get("weights") if isinstance(raw, dict) else raw
    if not isinstance(weights, dict):
        return {}
    return {str(k): float(v) for k, v in weights.items() if isinstance(v, (int, float))}


def save_weights(
    weights: dict[str, float],
    *,
    path: Path | None = None,
    meta: dict[str, Any] | None = None,
) -> Path:
    """Write weights atomically.  ``meta`` captures provenance
    (refit date, n_players, methodology hash, etc.)."""
    if path is None:
        repo = Path(__file__).resolve().parents[2]
        path = repo / "config" / "weights" / "dynamic_source_weights.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {
        "weights": {s: round(float(w), 4) for s, w in weights.items()},
        "meta": meta or {},
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path
