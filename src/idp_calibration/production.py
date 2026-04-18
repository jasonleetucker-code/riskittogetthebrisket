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


def _position_has_real_data(position_block: Any) -> bool:
    """Bucket data is "real" only when at least one bucket has count > 0.

    A buckets list of only zero-count entries is produced by a run that
    failed to resolve any seasons — treating it as valid would cause the
    anchor-floor fallback to fire for every rank. Guard at read time so
    even an accidentally-promoted empty config is a strict no-op instead
    of a silent 95% value cut.
    """
    if not isinstance(position_block, dict):
        return False
    buckets = position_block.get("buckets")
    if isinstance(buckets, list):
        for bucket in buckets:
            try:
                if int(bucket.get("count") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
        return False
    # Flat {label: value} shape carries no count, so trust its presence.
    return any(isinstance(k, str) and "-" in k for k in position_block.keys())


def _interpolate_anchor_curve(anchors_block: list[Any], rank: int) -> float | None:
    """Piecewise-linear interpolation between anchor points.

    Returns ``None`` when the anchor list is empty or malformed. Falls
    below the first anchor ⇒ returns the first anchor's value. Past
    the last ⇒ returns the last anchor's value. This smooths the
    step-function cliffs that per-bucket lookups produce at bucket
    boundaries.
    """
    if not isinstance(anchors_block, list) or not anchors_block:
        return None
    points: list[tuple[int, float]] = []
    for point in anchors_block:
        try:
            r = int(point.get("rank"))
            v = float(point.get("value"))
            points.append((r, v))
        except (TypeError, ValueError, AttributeError):
            continue
    if not points:
        return None
    points.sort(key=lambda p: p[0])
    r_target = int(rank)
    if r_target <= points[0][0]:
        return points[0][1]
    if r_target >= points[-1][0]:
        return points[-1][1]
    # Find the two adjacent anchors that bracket the target rank.
    for i in range(len(points) - 1):
        r0, v0 = points[i]
        r1, v1 = points[i + 1]
        if r0 <= r_target <= r1:
            if r1 == r0:
                return v0
            t = (r_target - r0) / (r1 - r0)
            return v0 + t * (v1 - v0)
    return points[-1][1]


def _bucket_lookup_for(position: str, rank: int, config: dict[str, Any], mode: str) -> float:
    """Smooth multiplier lookup for an IDP rank.

    Strategy: use the anchor curve as the PRIMARY source with
    piecewise-linear interpolation between anchor ranks. This replaces
    the old step-function bucket lookup so consecutive ranks never
    face the ~90% cliffs that the bucket edges produced (e.g. DL12 →
    DL13 jumping from 0.67 to 0.05). Buckets are still how the engine
    *computes* robust centers; the anchor curve is how we *apply*
    them smoothly.

    Falls back to bucket lookup if no anchor data is present (older
    promoted configs). Returns ``1.0`` (identity) when the promoted
    config has no real per-bucket data for the position — safety net
    that prevents an empty-calibration promotion from cutting every
    IDP value through the anchor floor.
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

    if kind in multipliers and isinstance(multipliers[kind], dict):
        position_block = multipliers[kind].get(position)
    else:
        position_block = multipliers.get(position)
    if not isinstance(position_block, dict):
        position_block = None

    # Safety: empty buckets ⇒ identity, never let the anchor floor
    # silently cut every IDP value.
    if not _position_has_real_data(position_block):
        return 1.0

    # PRIMARY: smooth anchor-curve interpolation.
    anchors_block = (config.get("anchors") or {}).get(kind, {}).get(position)
    anchor_value = _interpolate_anchor_curve(anchors_block, int(rank))
    if anchor_value is not None:
        return float(anchor_value)

    # FALLBACK: bucket-lookup (legacy step-function behaviour) when a
    # promoted config lacks anchor data. New runs always include
    # anchors so this path only exercises against pre-anchor configs.
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
        for label, value in position_block.items():
            try:
                lo, _, hi = str(label).partition("-")
                if int(lo) <= int(rank) <= int(hi):
                    return float(value)
            except (TypeError, ValueError):
                continue
    return 1.0


def _family_scale_for(config: dict[str, Any], mode: str) -> float:
    """Return the cross-family IDP scale from the promoted config.

    Applied multiplicatively on top of the within-position bucket
    multiplier so the live pipeline produces:

        final = rankDerivedValue × family_scale × bucket_multiplier

    A family scale > 1.0 lifts every IDP row in lockstep (because my
    league values IDP as a class more than the market); < 1.0 discounts
    the class. Missing block → 1.0 (identity, backward compat with
    pre-Family-Scale promoted configs).
    """
    fs = config.get("family_scale")
    if not isinstance(fs, dict):
        return 1.0
    kind = {
        "intrinsic_only": "intrinsic",
        "market_only": "market",
        "blended": "final",
    }.get(mode, "final")
    val = fs.get(kind)
    try:
        scale = float(val)
    except (TypeError, ValueError):
        return 1.0
    # Hard sanity clamp to the same bounds the engine's
    # compute_family_scale uses. Defends production against a
    # hand-edited config with a nonsense value.
    return max(0.25, min(4.0, scale))


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

    Combines the cross-family IDP scale (from ``config['family_scale']``)
    with the within-position bucket multiplier. See
    :func:`_family_scale_for` for the class-level lift/discount
    semantics.
    """
    config = _load_if_stale(base)
    if not config:
        return 1.0
    effective_mode = mode or str(config.get("active_mode") or "blended")
    if effective_mode not in {"intrinsic_only", "market_only", "blended"}:
        effective_mode = "blended"
    try:
        bucket = float(_bucket_lookup_for(position, int(rank), config, effective_mode))
        family = _family_scale_for(config, effective_mode)
        return bucket * family
    except Exception:
        return 1.0


def _offense_bucket_lookup_for(
    position: str, rank: int, config: dict[str, Any], mode: str
) -> float:
    """Offense analog of :func:`_bucket_lookup_for`.

    Reads from ``config['offense_multipliers']`` instead of
    ``multipliers``, and falls back to ``config['offense_anchors']``
    when the rank is past the last labelled bucket. Returns identity
    whenever offense calibration is absent from the promoted config
    (backward-compat with pre-offense-calibration promoted files).
    """
    position = position.upper()
    if position not in {"QB", "RB", "WR", "TE"}:
        return 1.0
    multipliers = config.get("offense_multipliers") or {}
    if not multipliers:
        return 1.0

    kind = {
        "intrinsic_only": "intrinsic",
        "market_only": "market",
        "blended": "final",
    }.get(mode, "final")

    if kind in multipliers and isinstance(multipliers[kind], dict):
        position_block = multipliers[kind].get(position)
    else:
        position_block = multipliers.get(position)
    if not isinstance(position_block, dict):
        position_block = None

    if not _position_has_real_data(position_block):
        return 1.0

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
        for label, value in position_block.items():
            try:
                lo, _, hi = str(label).partition("-")
                if int(lo) <= int(rank) <= int(hi):
                    return float(value)
            except (TypeError, ValueError):
                continue

    anchors_block = (config.get("offense_anchors") or {}).get(kind, {}).get(position)
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


def get_offense_bucket_multiplier(
    position: str,
    rank: int,
    *,
    mode: str | None = None,
    base: Path | None = None,
) -> float:
    """Return the multiplier for a QB/RB/WR/TE row.

    Unlike :func:`get_idp_bucket_multiplier` this does NOT apply the
    family_scale — family_scale is IDP-vs-offense, and offense is the
    reference. Offense calibration only reshapes the within-position
    curve (e.g. "my league's tiered PPR values WR 13-24 8% higher than
    market"). Identity when no offense calibration is promoted.
    """
    config = _load_if_stale(base)
    if not config:
        return 1.0
    effective_mode = mode or str(config.get("active_mode") or "blended")
    if effective_mode not in {"intrinsic_only", "market_only", "blended"}:
        effective_mode = "blended"
    try:
        return float(_offense_bucket_lookup_for(position, int(rank), config, effective_mode))
    except Exception:
        return 1.0


def is_promoted(base: Path | None = None) -> bool:
    return _load_if_stale(base) is not None
