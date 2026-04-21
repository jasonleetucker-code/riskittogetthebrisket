"""Manual promotion flow.

Writes the approved calibration output from a saved run into
``config/idp_calibration.json``. The prior production file (if any)
is moved to ``config/idp_calibration.backups/{promoted_at}.json``
before the new file is written, so promotion is always reversible.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.config_loader import load_json, repo_root, save_json

from .storage import load_run
from .translation import CALIBRATION_SCHEMA_VERSION

CONFIG_FILENAME = "idp_calibration.json"
BACKUPS_DIR = "idp_calibration.backups"

VALID_MODES: tuple[str, ...] = ("intrinsic_only", "market_only", "blended")

# Under schema v2 the per-bucket ``final`` is the only channel that
# carries a cross-league relativity ratio; ``intrinsic`` / ``market``
# are offense-anchored absolute VOR magnitudes used for display only.
# Promoting a v2 run with ``active_mode="intrinsic_only"`` or
# ``"market_only"`` would make ``production.get_idp_bucket_multiplier``
# read an unbounded VOR magnitude and apply it as a multiplier to
# live values — a silent catastrophic mis-scale. The only mode that
# produces a valid applied quantity under v2 is ``blended`` (reads
# the ``final`` ratio), so we gate promotion on that at the factory.
V2_VALID_MODES: tuple[str, ...] = ("blended",)


class StaleArtifactSchemaError(ValueError):
    """Raised when a run artifact predates the current engine schema.

    Promoting a pre-v2 artifact would stamp ``"version": 2`` on a
    config whose ``final`` field still encodes the old top-bucket-
    normalised VOR decay, silently bypassing the loader gate in
    :func:`production.load_production_config`. We refuse at the
    promotion factory so stale runs can never reach production — the
    operator must re-run the calibration on the current engine.
    """


class EmptyCalibrationError(ValueError):
    """Raised when a run has no usable per-bucket multiplier data.

    Promoting such a run would make :func:`production.get_idp_bucket_multiplier`
    fall through to the anchor curve, which is floored at ``anchor_floor``
    (default ``0.05``) and would silently cut every IDP value in the live
    calculator by ~95%. The calibration lab must reject these promotions
    at the gate rather than ship a quiet regression.
    """


def production_config_path(base: Path | None = None) -> Path:
    return (base or repo_root()) / "config" / CONFIG_FILENAME


def backups_dir(base: Path | None = None) -> Path:
    return (base or repo_root()) / "config" / BACKUPS_DIR


def _sanitize_ts(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "_", value)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _has_usable_bucket_data(artifact: dict[str, Any]) -> bool:
    """Return ``True`` when at least one DL/LB/DB bucket has ``count > 0``.

    Anchor curves alone are not enough — they can be produced from empty
    bucket tables and default to the anchor floor, which is a dangerous
    no-op. Bucket counts are the ground truth that real players backed
    the multiplier.
    """
    multipliers = (artifact or {}).get("multipliers") or {}
    for pos in ("DL", "LB", "DB"):
        buckets = (multipliers.get(pos) or {}).get("buckets") or []
        for bucket in buckets:
            try:
                if int(bucket.get("count") or 0) > 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def build_production_config(
    artifact: dict[str, Any],
    *,
    active_mode: str = "blended",
    promoted_by: str = "internal",
) -> dict[str, Any]:
    """Shape a saved run artifact into the production config schema."""
    if active_mode not in VALID_MODES:
        raise ValueError(f"active_mode must be one of {VALID_MODES}, got {active_mode!r}")
    # Gate 1: refuse pre-v2 artifacts. The promoted config will be
    # stamped with ``version = CALIBRATION_SCHEMA_VERSION`` below, so
    # without this check a v1 run's top-bucket-normalised VOR decay
    # values would ship under a v2 tag and be read as relativity
    # ratios by the live loader.
    try:
        artifact_version = int(artifact.get("schema_version") or 0)
    except (TypeError, ValueError):
        artifact_version = 0
    if artifact_version < CALIBRATION_SCHEMA_VERSION:
        raise StaleArtifactSchemaError(
            f"Run artifact is schema v{artifact_version}; the current engine "
            f"produces v{CALIBRATION_SCHEMA_VERSION}. Re-run the calibration "
            f"on the current engine before promoting — promoting a stale "
            f"artifact would mis-interpret its multiplier field under the "
            f"new semantics."
        )
    # Gate 2: under v2, only ``blended`` is a valid applied mode
    # (``intrinsic`` / ``market`` are offense-anchored VOR magnitudes,
    # not multipliers — see ``translation.compute_position_multipliers``).
    if active_mode not in V2_VALID_MODES:
        raise ValueError(
            f"active_mode={active_mode!r} is not applicable under schema "
            f"v{CALIBRATION_SCHEMA_VERSION}. Only {V2_VALID_MODES} produce "
            f"a valid applied multiplier; intrinsic/market are display-only "
            f"diagnostic channels in the v2 artifact."
        )
    if not _has_usable_bucket_data(artifact):
        raise EmptyCalibrationError(
            "Run has no resolved seasons with per-bucket IDP data; refusing "
            "to promote because the live pipeline would fall through to the "
            "anchor floor and cut every IDP value by ~95%.",
        )
    settings = artifact.get("settings") or {}
    inputs = artifact.get("inputs") or {}
    # Schema v2: per-bucket ``final`` already carries the offense-
    # anchored cross-league relativity ratio, so ``family_scale`` is
    # redundant class-wide lift and would double-count if applied on
    # top. We keep the field in the artifact for the lab UI's display
    # but pin the applied value to identity (1.0 / 1.0 / 1.0) in the
    # promoted config. If a future schema needs a separate class-wide
    # lever, bump the version and plug it back in.
    return {
        "version": CALIBRATION_SCHEMA_VERSION,
        "promoted_at": _utc_now_iso(),
        "source_run_id": str(artifact.get("run_id") or ""),
        "promoted_by": str(promoted_by or "internal"),
        "league_ids": {
            "test": inputs.get("test_league_id"),
            "mine": inputs.get("my_league_id"),
        },
        "year_coverage": list(artifact.get("resolved_seasons") or []),
        "blend_weights": dict(settings.get("blend") or {}),
        "replacement_settings": dict(settings.get("replacement") or {}),
        "active_mode": active_mode,
        "bucket_edges": list(settings.get("bucket_edges") or []),
        "offense_anchor_vor_mine": float(
            artifact.get("offense_anchor_vor_mine") or 0.0
        ),
        "offense_anchor_vor_test": float(
            artifact.get("offense_anchor_vor_test") or 0.0
        ),
        "multipliers": dict(artifact.get("multipliers") or {}),
        "offense_multipliers": dict(artifact.get("offense_multipliers") or {}),
        "family_scale": {"intrinsic": 1.0, "market": 1.0, "final": 1.0},
        "family_scale_diagnostic": dict(artifact.get("family_scale") or {}),
        "anchors": dict(artifact.get("anchors") or {}),
        "offense_anchors": dict(artifact.get("offense_anchors") or {}),
    }


def promote_run(
    run_id: str,
    *,
    active_mode: str = "blended",
    promoted_by: str = "internal",
    base: Path | None = None,
) -> dict[str, Any]:
    """Promote ``run_id`` to production.

    Returns a dict with ``{ok, promoted_at, config_path, backup_path}``.
    Raises :class:`FileNotFoundError` when the run does not exist.
    """
    artifact = load_run(run_id, base=base)
    if not artifact:
        raise FileNotFoundError(f"Run {run_id!r} not found.")
    cfg_path = production_config_path(base)
    backup_path: str | None = None
    if cfg_path.exists():
        backup_dir = backups_dir(base)
        backup_dir.mkdir(parents=True, exist_ok=True)
        ts = _sanitize_ts(_utc_now_iso())
        backup_target = backup_dir / f"{ts}.json"
        prior = load_json(cfg_path)
        if prior is not None:
            save_json(backup_target, prior)
            backup_path = str(backup_target)
    production = build_production_config(
        artifact, active_mode=active_mode, promoted_by=promoted_by
    )
    save_json(cfg_path, production)
    return {
        "ok": True,
        "promoted_at": production["promoted_at"],
        "config_path": str(cfg_path),
        "backup_path": backup_path,
        "source_run_id": production["source_run_id"],
        "active_mode": production["active_mode"],
    }


def load_production(base: Path | None = None) -> dict[str, Any] | None:
    """Return the current production config or ``None`` if unset."""
    data = load_json(production_config_path(base))
    return data if isinstance(data, dict) else None
