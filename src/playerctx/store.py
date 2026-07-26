"""Atomic snapshot persistence for the player-context data layer.

One compact JSON file — ``data/playerctx/snapshot.json`` — written
atomically (same tmp-then-replace pattern as
``src/public_league/snapshot_store.py::_atomic_write_json``) so a
crashed refresh can never leave a half-written file for
``load_snapshot`` to trip over.

``data/`` is gitignored repo-wide, so the snapshot is generated
infrastructure, not a committed artifact: production materializes it
via ``scripts/refresh_playerctx.py``.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT_PATH = REPO_ROOT / "data" / "playerctx" / "snapshot.json"

SCHEMA_VERSION = "playerctx.v1"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    try:
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_snapshot(
    players: dict[str, dict[str, Any]],
    *,
    counts: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
    path: Path | None = None,
) -> Path:
    """Persist the snapshot; returns the path written."""
    target = path or SNAPSHOT_PATH
    payload = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "counts": counts or {},
        "sources": sources or {},
        # sleeper_id → gsis_id so UI callers holding Sleeper IDs can
        # index straight into ``players`` without a scan.
        "sleeperIndex": {
            rec["sleeperId"]: gsis for gsis, rec in players.items() if rec.get("sleeperId")
        },
        "players": players,
    }
    _atomic_write_json(target, payload)
    return target


def load_snapshot(path: Path | None = None) -> dict[str, Any] | None:
    """Defensive read: ``None`` for missing / corrupt / wrong-shape
    files — callers must treat 'no context available' as normal."""
    target = path or SNAPSHOT_PATH
    if not target.exists():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("playerctx: failed to load %s: %s", target, exc)
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("players"), dict):
        log.warning("playerctx: %s has unexpected shape; ignoring", target)
        return None
    return payload
