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

# Sentinel stored in the cache when the on-disk config has been read
# and rejected (e.g. schema version below :data:`_MIN_SUPPORTED_VERSION`
# or not a JSON dict).  Having a distinct value from ``None`` lets the
# mtime fast-path short-circuit **without re-reading the file**, which
# matters during the pre-re-promotion rollout window where a stale
# config is present — otherwise every per-player multiplier lookup
# would load_json() a ~200 KB file off disk on every call.
_STALE_SENTINEL: object = object()

_lock = threading.Lock()
# ``stale_version`` is cached alongside the sentinel so
# :func:`promoted_state` can surface the on-disk schema version to
# operators without re-reading the file.  ``None`` when the config
# is absent or actively applied.
_cache: dict[str, Any] = {"mtime": None, "config": None, "stale_version": None}

# Minimum config version the runtime will apply. Configs written by the
# v1 engine encoded ``final`` as a top-bucket-normalised VOR decay
# curve; under the v2 engine the same field carries a cross-league
# relativity ratio. Applying a v1 config under v2 semantics would
# mis-interpret the numbers, so we refuse to load anything older than
# :data:`_MIN_SUPPORTED_VERSION` and leave calibration as a strict
# no-op until the lab re-promotes on the current engine.
_MIN_SUPPORTED_VERSION: int = 2

_stale_version_warned = False


def _load_if_stale(base: Path | None = None) -> dict[str, Any] | None:
    global _stale_version_warned
    path = production_config_path(base)
    if not path.exists():
        with _lock:
            _cache["mtime"] = None
            _cache["config"] = None
            _cache["stale_version"] = None
        _stale_version_warned = False
        return None
    mtime = path.stat().st_mtime
    with _lock:
        cached = _cache["config"]
        if _cache["mtime"] == mtime:
            # Fast path covers both outcomes:
            #   * valid dict cached → return it
            #   * stale-version sentinel cached → return None
            # without re-parsing the JSON every call.
            if cached is _STALE_SENTINEL:
                return None
            if cached is not None:
                return cached
        data = load_json(path)
        if isinstance(data, dict):
            try:
                cfg_version = int(data.get("version") or 0)
            except (TypeError, ValueError):
                cfg_version = 0
            if cfg_version < _MIN_SUPPORTED_VERSION:
                if not _stale_version_warned:
                    import logging

                    logging.getLogger(__name__).warning(
                        "config/idp_calibration.json is schema v%s "
                        "(minimum supported: v%s). IDP calibration is a "
                        "strict no-op until the lab re-promotes a run on "
                        "the current engine.",
                        cfg_version,
                        _MIN_SUPPORTED_VERSION,
                    )
                    _stale_version_warned = True
                _cache["mtime"] = mtime
                _cache["config"] = _STALE_SENTINEL
                _cache["stale_version"] = cfg_version
                return None
            _stale_version_warned = False
            _cache["mtime"] = mtime
            _cache["config"] = data
            _cache["stale_version"] = None
            return data
        # Non-dict JSON (corrupt file) — treat as stale so we don't
        # re-read and parse every call.
        _cache["mtime"] = mtime
        _cache["config"] = _STALE_SENTINEL
        _cache["stale_version"] = 0
        return None


def reset_cache() -> None:
    """Test hook — drop the in-memory cache."""
    global _stale_version_warned
    with _lock:
        _cache["mtime"] = None
        _cache["config"] = None
        _cache["stale_version"] = None
    _stale_version_warned = False


def load_production_config(base: Path | None = None) -> dict[str, Any] | None:
    """Public read: current promoted config, or ``None`` if absent."""
    return _load_if_stale(base)


def promoted_state(base: Path | None = None) -> dict[str, Any]:
    """Structured snapshot of the promoted-config state.

    Single source of truth for every operator-facing endpoint
    (``/api/idp-calibration/production`` and ``/status``), so both
    surfaces can't contradict each other about whether calibration
    is live — a real concern during the rollout window where a
    schema-stale config may sit on disk while the runtime ignores it.

    Fields:

    * ``present`` — the live pipeline is applying this config right
      now. ``True`` only when the file exists **and** passes the
      schema-version gate.
    * ``stale`` — a file exists on disk but the loader refused it
      (version below :data:`_MIN_SUPPORTED_VERSION` or corrupt JSON).
      When ``stale`` is ``True``, ``present`` is ``False``.
    * ``stale_version`` — the on-disk schema version when ``stale``
      is ``True``; ``None`` otherwise. Helpful for operators to see
      "you're on v1, need v2" at a glance.
    * ``required_version`` — the minimum schema version the runtime
      accepts. Constant per build.
    * ``config`` — the active config dict when ``present`` is
      ``True``; ``None`` otherwise.
    """
    path = production_config_path(base)
    if not path.exists():
        return {
            "present": False,
            "stale": False,
            "stale_version": None,
            "required_version": _MIN_SUPPORTED_VERSION,
            "config": None,
        }
    cfg = _load_if_stale(base)
    if cfg is not None:
        return {
            "present": True,
            "stale": False,
            "stale_version": None,
            "required_version": _MIN_SUPPORTED_VERSION,
            "config": cfg,
        }
    # File is on disk but was rejected. Surface the cached version
    # so operators can see why without another read.
    with _lock:
        stale_version = _cache["stale_version"]
    return {
        "present": False,
        "stale": True,
        "stale_version": stale_version,
        "required_version": _MIN_SUPPORTED_VERSION,
        "config": None,
    }


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

    A family scale > 1.0 lifts every IDP row in lockstep (because the
    operator's league values IDP as a class more than the market);
    < 1.0 discounts the class.  Missing block → 1.0 (identity).

    **Market-sensibility cap (2026-04-20)**: we clamp to
    ``[0.85, 1.15]`` — max ±15% class-wide adjustment.  The engine's
    ``compute_family_scale`` technically permits up to ±300% based on
    league scoring differences, but applying a 25%+ lift uniformly to
    every IDP pushes top IDPs past top-20 offense and "too far above
    market" (per user directive).  15% is a ~5-rank lift for top
    IDPs on the Hill curve — enough to reflect league premium,
    bounded enough to stay near retail ordering.
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
    return max(0.85, min(1.15, scale))


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
    # Schema v2 safety rail: the ``intrinsic`` / ``market`` channels
    # carry offense-anchored absolute VOR magnitudes (unbounded above
    # 1.0), not applied multipliers. The promotion factory already
    # refuses non-blended modes under v2, but a hand-edited config
    # could still smuggle one in — coerce to ``blended`` so
    # ``_bucket_lookup_for`` reads the ``final`` relativity ratio
    # regardless.
    try:
        cfg_version = int(config.get("version") or 0)
    except (TypeError, ValueError):
        cfg_version = 0
    if cfg_version >= 2 and effective_mode != "blended":
        effective_mode = "blended"
    try:
        bucket = float(_bucket_lookup_for(position, int(rank), config, effective_mode))
        family = _family_scale_for(config, effective_mode)
        return bucket * family
    except Exception:
        return 1.0


def is_promoted(base: Path | None = None) -> bool:
    return _load_if_stale(base) is not None
