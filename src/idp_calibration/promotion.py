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

CONFIG_FILENAME = "idp_calibration.json"
BACKUPS_DIR = "idp_calibration.backups"

VALID_MODES: tuple[str, ...] = ("intrinsic_only", "market_only", "blended")


def production_config_path(base: Path | None = None) -> Path:
    return (base or repo_root()) / "config" / CONFIG_FILENAME


def backups_dir(base: Path | None = None) -> Path:
    return (base or repo_root()) / "config" / BACKUPS_DIR


def _sanitize_ts(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_-]", "_", value)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_production_config(
    artifact: dict[str, Any],
    *,
    active_mode: str = "blended",
    promoted_by: str = "internal",
) -> dict[str, Any]:
    """Shape a saved run artifact into the production config schema."""
    if active_mode not in VALID_MODES:
        raise ValueError(f"active_mode must be one of {VALID_MODES}, got {active_mode!r}")
    settings = artifact.get("settings") or {}
    inputs = artifact.get("inputs") or {}
    return {
        "version": 1,
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
        "multipliers": dict(artifact.get("multipliers") or {}),
        "anchors": dict(artifact.get("anchors") or {}),
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
