"""Read path for the promoted IDP calibration config.

Exposes a single entry point — :func:`get_idp_bucket_multiplier` —
used by the live valuation pipeline. Results are cached by file
mtime so operational edits to ``config/idp_calibration.json`` take
effect on the next request without a server restart.

If no promoted config exists, every call returns ``1.0`` (identity
multiplier) so the presence of this module is a strict no-op until
an explicit promotion has occurred.
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from src.utils.config_loader import load_json

from .promotion import production_config_path

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": None, "config": None}


def _load_if_stale(base: Path | None = None) -> dict[str, Any] | None:
    path = production_config_path(base)
    if not path.exists():
        with _lock:
            _cache["mtime"] = None
            _cache["config"] = None
        return None
    mtime = path.stat().st_mtime
    with _lock:
        if _cache["mtime"] == mtime and _cache["config"] is not None:
            return _cache["config"]
        data = load_json(path)
        _cache["mtime"] = mtime
        _cache["config"] = data if isinstance(data, dict) else None
        return _cache["config"]


def reset_cache() -> None:
    """Test hook — drop the in-memory cache."""
    with _lock:
        _cache["mtime"] = None
        _cache["config"] = None


def load_production_config(base: Path | None = None) -> dict[str, Any] | None:
    """Public read: current promoted config, or ``None`` if absent."""
    return _load_if_stale(base)


def _bucket_lookup_for(position: str, rank: int, config: dict[str, Any], mode: str) -> float:
    """Pick the right multiplier from the promoted config.

    Handles both of the shapes the storage layer emits: flat
    ``multipliers[position] = {label: value}`` and the richer
    ``multipliers[kind][position] = {...}``.
    """
    position = position.upper()
    if position not in {"DL", "LB", "DB"}:
        return 1.0
    multipliers = config.get("multipliers") or {}

    kind = {
        "intrinsic_only": "intrinsic",
        "market_only": "market",
        "blended": "final",
    }.get(mode, "final")

    # Shape A: kind-first — multipliers[kind][position] = {label: value}
    if kind in multipliers and isinstance(multipliers[kind], dict):
        position_block = multipliers[kind].get(position)
    else:
        position_block = multipliers.get(position)
    if not isinstance(position_block, dict):
        # Some shapes embed {"buckets": [...]}. Fall through to anchor lookup.
        position_block = None

    if isinstance(position_block, dict):
        buckets = position_block.get("buckets") if "buckets" in position_block else None
        if isinstance(buckets, list):
            for bucket in buckets:
                try:
                    lo, _, hi = str(bucket.get("label") or "").partition("-")
                    if int(lo) <= int(rank) <= int(hi):
                        val = bucket.get(kind)
                        if val is None:
                            val = bucket.get("final")
                        return float(val) if val is not None else 1.0
                except (TypeError, ValueError):
                    continue
        # flat { "1-6": 1.05, ... }
        for label, value in position_block.items():
            try:
                lo, _, hi = str(label).partition("-")
                if int(lo) <= int(rank) <= int(hi):
                    return float(value)
            except (TypeError, ValueError):
                continue

    # Fall back to anchors if multipliers lookup failed.
    anchors_block = (config.get("anchors") or {}).get(kind, {}).get(position)
    if isinstance(anchors_block, list):
        best_val = 1.0
        best_rank = -1
        for point in anchors_block:
            try:
                ar = int(point.get("rank"))
                if ar <= int(rank) and ar > best_rank:
                    best_rank = ar
                    best_val = float(point.get("value"))
            except (TypeError, ValueError):
                continue
        return best_val
    return 1.0


def get_idp_bucket_multiplier(
    position: str,
    rank: int,
    *,
    mode: str | None = None,
    base: Path | None = None,
) -> float:
    """Return the multiplier to apply to an IDP row.

    * ``position`` must be ``DL``, ``LB``, or ``DB``. Anything else
      returns 1.0.
    * ``rank`` is the player's position-specific rank (1 = DL1 etc.).
    * ``mode`` overrides the config's ``active_mode``. When ``None``
      the config's own ``active_mode`` is used (default ``"blended"``).

    Returns ``1.0`` whenever no promoted config exists so this is a
    strict no-op for a freshly-cloned repo.
    """
    config = _load_if_stale(base)
    if not config:
        return 1.0
    effective_mode = mode or str(config.get("active_mode") or "blended")
    if effective_mode not in {"intrinsic_only", "market_only", "blended"}:
        effective_mode = "blended"
    try:
        return float(_bucket_lookup_for(position, int(rank), config, effective_mode))
    except Exception:
        return 1.0


def is_promoted(base: Path | None = None) -> bool:
    return _load_if_stale(base) is not None
