"""Persistence of calibration runs.

Runs live under ``data/idp_calibration/runs/{run_id}.json`` and a
``latest.json`` pointer sits alongside. Uses the shared
``src.utils.config_loader`` helpers so filesystem behaviour matches
the rest of the repo.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from src.utils.config_loader import load_json, repo_root, save_json


def _runs_dir(base: Path | None = None) -> Path:
    root = base or repo_root()
    return root / "data" / "idp_calibration" / "runs"


def _latest_path(base: Path | None = None) -> Path:
    root = base or repo_root()
    return root / "data" / "idp_calibration" / "latest.json"


def save_run(artifact: dict[str, Any], *, base: Path | None = None) -> str:
    """Persist ``artifact`` and update the ``latest.json`` pointer.

    Returns the saved run's ``run_id``.
    """
    run_id = str(artifact.get("run_id") or "").strip()
    if not run_id:
        raise ValueError("Artifact is missing run_id")
    runs_dir = _runs_dir(base)
    runs_dir.mkdir(parents=True, exist_ok=True)
    target = runs_dir / f"{run_id}.json"
    save_json(target, artifact)
    save_json(_latest_path(base), {"run_id": run_id, "path": str(target)})
    return run_id


def load_run(run_id: str, *, base: Path | None = None) -> dict[str, Any] | None:
    runs_dir = _runs_dir(base)
    target = runs_dir / f"{run_id}.json"
    if not target.exists():
        return None
    return load_json(target)


def list_runs(*, base: Path | None = None, limit: int = 50) -> list[dict[str, Any]]:
    runs_dir = _runs_dir(base)
    if not runs_dir.exists():
        return []
    files = sorted(runs_dir.glob("*.json"), reverse=True)
    summaries: list[dict[str, Any]] = []
    for path in files[:limit]:
        data = load_json(path) or {}
        summaries.append(
            {
                "run_id": data.get("run_id"),
                "generated_at": data.get("generated_at"),
                "test_league_id": (data.get("inputs") or {}).get("test_league_id"),
                "my_league_id": (data.get("inputs") or {}).get("my_league_id"),
                "resolved_seasons": data.get("resolved_seasons") or [],
                "warning_count": len(data.get("warnings") or []),
                "path": str(path),
            }
        )
    return summaries


def get_latest(*, base: Path | None = None) -> dict[str, Any] | None:
    pointer = load_json(_latest_path(base))
    if not isinstance(pointer, dict):
        return None
    run_id = str(pointer.get("run_id") or "").strip()
    if not run_id:
        return None
    return load_run(run_id, base=base)
