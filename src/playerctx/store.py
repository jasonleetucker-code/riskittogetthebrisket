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
from datetime import date, datetime, timezone
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


# ── Dated retention ──────────────────────────────────────────────────

HISTORY_DIR = REPO_ROOT / "data" / "playerctx" / "history"

# Fields kept in a retained snapshot. A SNAPS-ONLY projection: the axis
# retention exists for is `snapTrend`, and the contract block is both the
# largest and the one whose upstream (OTC) churns most week to week.
# ~320 KB per file against ~1.1 MB for the full snapshot.
_HISTORY_PLAYER_FIELDS = ("gsisId", "sleeperId", "name", "team", "position")


def history_path(as_of: str, directory: Path | None = None) -> Path:
    """Path for one dated snapshot.

    ``snapshot_YYYY-MM-DD.json``, and the format is load-bearing rather
    than stylistic: :func:`consensus_edge.panel.payload_asof` picks the
    lexically-greatest matching filename in a commit, so a name that does
    not sort chronologically silently replays the wrong day.
    """
    return (directory or HISTORY_DIR) / f"snapshot_{str(as_of)[:10]}.json"


def write_history_snapshot(
    players: dict[str, dict[str, Any]],
    *,
    as_of: str,
    counts: dict[str, Any] | None = None,
    sources: dict[str, Any] | None = None,
    directory: Path | None = None,
) -> Path | None:
    """Persist the snaps-only projection for ``as_of``; None if nothing to keep.

    Separate from :func:`write_snapshot` because the two have different
    jobs: that one produces the live artifact the API reads, this one
    produces a durable record a study can replay. Writing one file for
    both would mean the retention format could not change without
    changing what production serves.

    Returns None rather than an empty file when no player carries a snap
    block — a study reading a zero-player day cannot distinguish "the
    refresh ran and found nothing" from "the refresh did not run", and an
    absent file at least says the second honestly.
    """
    projected: dict[str, dict[str, Any]] = {}
    for key, record in (players or {}).items():
        snaps = record.get("snaps")
        if not isinstance(snaps, dict):
            continue
        entry = {f: record.get(f) for f in _HISTORY_PLAYER_FIELDS if record.get(f)}
        entry["snaps"] = snaps
        projected[key] = entry
    if not projected:
        return None

    target = history_path(as_of, directory)
    _atomic_write_json(
        target,
        {
            "schemaVersion": SCHEMA_VERSION,
            "asOf": str(as_of)[:10],
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "projection": "snapsOnly",
            "counts": counts or {},
            "sources": sources or {},
            "sleeperIndex": {
                rec["sleeperId"]: key for key, rec in projected.items() if rec.get("sleeperId")
            },
            "players": projected,
        },
    )
    return target


def history_coverage(directory: Path | None = None) -> dict[str, Any]:
    """What the retained history does and does not cover.

    Mirrors ``src.api.rank_history.coverage`` field-for-field, including
    the reason it exists: a raw file count cannot distinguish 60
    consecutive days from a tree that stopped growing in April.
    ``missingDays`` is calendar gaps inside the span and ``staleDays``
    is the live-stall signal, so a halted timer is visible before a study
    needs the data rather than after it produces a wrong answer.
    """
    target = directory or HISTORY_DIR
    if not target.is_dir():
        return {"path": str(target), "exists": False, "snapshots": 0, "reason": "no history dir"}

    dates: list[date] = []
    for path in target.glob("snapshot_*.json"):
        stem = path.stem.replace("snapshot_", "", 1)
        try:
            dates.append(date.fromisoformat(stem))
        except ValueError:
            continue
    if not dates:
        return {
            "path": str(target),
            "exists": True,
            "snapshots": 0,
            "reason": "no dated snapshots",
        }

    dates.sort()
    span_days = (dates[-1] - dates[0]).days + 1
    stale_days = (datetime.now(timezone.utc).date() - dates[-1]).days
    return {
        "path": str(target),
        "exists": True,
        "snapshots": len(dates),
        "firstDate": dates[0].isoformat(),
        "lastDate": dates[-1].isoformat(),
        "spanDays": span_days,
        "missingDays": max(0, span_days - len(set(dates))),
        "staleDays": stale_days,
    }
