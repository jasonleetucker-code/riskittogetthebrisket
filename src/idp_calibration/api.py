"""HTTP handlers for the IDP calibration lab.

Pure-function handlers exposed to server.py so route registration
matches the existing ``@app.get/post`` convention without dragging a
FastAPI dependency into this package. Every handler returns a
``(status, payload)`` tuple — server.py wraps them in ``JSONResponse``
and applies the standard auth gate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .engine import AnalysisSettings, run_analysis
from .promotion import VALID_MODES, load_production, promote_run
from .production import is_promoted
from .storage import get_latest, list_runs, load_run, save_run


def _error(status: int, message: str, **extra: Any) -> tuple[int, dict[str, Any]]:
    payload: dict[str, Any] = {"ok": False, "error": message}
    payload.update(extra)
    return status, payload


def analyze(body: dict[str, Any] | None, *, base: Path | None = None) -> tuple[int, dict[str, Any]]:
    body = body or {}
    test_id = str(body.get("test_league_id") or "").strip()
    my_id = str(body.get("my_league_id") or "").strip()
    if not test_id or not my_id:
        return _error(
            422,
            "Both test_league_id and my_league_id are required.",
        )
    settings = AnalysisSettings.from_payload(body.get("settings"))
    try:
        artifact = run_analysis(test_id, my_id, settings)
    except Exception as exc:  # noqa: BLE001 — surface as user-friendly 500
        return _error(500, f"Analysis failed: {exc}")
    try:
        save_run(artifact, base=base)
    except Exception as exc:  # noqa: BLE001
        artifact.setdefault("warnings", []).append(f"Failed to persist run: {exc}")
    return 200, {"ok": True, "run": artifact}


def runs_index(*, base: Path | None = None) -> tuple[int, dict[str, Any]]:
    latest = get_latest(base=base)
    return 200, {
        "ok": True,
        "runs": list_runs(base=base),
        "latest_run_id": (latest or {}).get("run_id"),
    }


def run_detail(run_id: str, *, base: Path | None = None) -> tuple[int, dict[str, Any]]:
    if not run_id:
        return _error(422, "run_id is required.")
    data = load_run(run_id, base=base)
    if not data:
        return _error(404, f"Run {run_id!r} not found.")
    return 200, {"ok": True, "run": data}


def promote(body: dict[str, Any] | None, *, base: Path | None = None) -> tuple[int, dict[str, Any]]:
    body = body or {}
    run_id = str(body.get("run_id") or "").strip()
    active_mode = str(body.get("active_mode") or "blended").strip()
    promoted_by = str(body.get("promoted_by") or "internal").strip() or "internal"
    if not run_id:
        return _error(422, "run_id is required.")
    if active_mode not in VALID_MODES:
        return _error(
            422,
            f"active_mode must be one of {list(VALID_MODES)}, got {active_mode!r}.",
        )
    try:
        result = promote_run(
            run_id, active_mode=active_mode, promoted_by=promoted_by, base=base
        )
    except FileNotFoundError as exc:
        return _error(404, str(exc))
    except Exception as exc:  # noqa: BLE001
        return _error(500, f"Promotion failed: {exc}")
    return 200, result


def production(*, base: Path | None = None) -> tuple[int, dict[str, Any]]:
    cfg = load_production(base)
    if not cfg:
        return 200, {"ok": True, "present": False, "config": None}
    return 200, {"ok": True, "present": True, "config": cfg}


def status(*, base: Path | None = None) -> tuple[int, dict[str, Any]]:
    latest = get_latest(base=base)
    return 200, {
        "ok": True,
        "latest_run_id": (latest or {}).get("run_id"),
        "latest_generated_at": (latest or {}).get("generated_at"),
        "production_present": is_promoted(base=base),
        "valid_modes": list(VALID_MODES),
    }
