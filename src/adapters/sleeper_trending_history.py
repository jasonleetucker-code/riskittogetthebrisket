"""On-disk ring of Sleeper trending snapshots — velocity, not just level.

``src/adapters/sleeper_trending.py`` caches a single POINT-IN-TIME
snapshot (15-min TTL, overwritten on refresh — no history retained).
That answers "how many adds does this player have right now"; it
cannot answer "is that count accelerating" (directive Part IV.7:
6h/12h/24h/48h velocity, acceleration).

This module is the retention layer that makes velocity computable: a
bounded, gitignored JSON ring at ``data/waiver/trending_history.json``,
written by ``scripts/refresh_sleeper_trending_history.py``.  Trending
is NFL-wide, not league-scoped, so there is exactly one file — no
per-league fan-out.

Deliberately NOT read by any decision path in this module — the same
posture ``docs/faab-model.md`` documents for
``src/retention/evidence_store.py::trending_series`` ("a value that fed
back into the thing it records would make every measurement taken from
it circular").  Velocity computed here is diagnostic (surfaced as a
factor row) until a real outcome-backtest justifies wiring it into a
dollar figure — that is a DIFFERENT, later decision than persisting the
series at all.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
HISTORY_PATH = REPO_ROOT / "data" / "waiver" / "trending_history.json"

# Bounded ring: enough to answer a 48h velocity question with margin,
# not an unbounded log.  At the ~hourly cadence the systemd timer runs
# on, 96 entries covers 4 days.
_MAX_ENTRIES = 96
_RETENTION_HOURS = 96


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def load_history(path: Path | None = None) -> list[dict[str, Any]]:
    """Every retained snapshot, oldest first.  ``[]`` on missing/corrupt
    file — a broken history must degrade to "no velocity available",
    never raise into a request path."""
    target = path or HISTORY_PATH
    if not target.exists():
        return []
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("trending history unreadable, treating as empty: %s", exc)
        return []
    if not isinstance(raw, list):
        return []
    return [e for e in raw if isinstance(e, dict) and e.get("fetchedAt")]


def record_snapshot(
    *,
    adds: dict[str, int],
    drops: dict[str, int],
    path: Path | None = None,
    now: datetime | None = None,
) -> Path:
    """Append one snapshot, prune anything older than
    ``_RETENTION_HOURS``, and cap the ring at ``_MAX_ENTRIES``."""
    target = path or HISTORY_PATH
    history = load_history(target)
    ts = now or datetime.now(timezone.utc)
    history.append(
        {
            "fetchedAt": ts.isoformat(),
            "adds": {str(k): int(v) for k, v in (adds or {}).items()},
            "drops": {str(k): int(v) for k, v in (drops or {}).items()},
        }
    )

    cutoff = ts - timedelta(hours=_RETENTION_HOURS)

    def _keep(entry: dict[str, Any]) -> bool:
        try:
            entry_time = datetime.fromisoformat(str(entry["fetchedAt"]))
        except (KeyError, ValueError):
            return False
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        return entry_time >= cutoff

    history = [e for e in history if _keep(e)]
    if len(history) > _MAX_ENTRIES:
        history = history[-_MAX_ENTRIES:]

    _atomic_write_json(target, history)
    return target


def _nearest_entry_at_or_before(
    history: list[dict[str, Any]],
    target_time: datetime,
) -> dict[str, Any] | None:
    best: dict[str, Any] | None = None
    best_time: datetime | None = None
    for entry in history:
        try:
            entry_time = datetime.fromisoformat(str(entry["fetchedAt"]))
        except (KeyError, ValueError):
            continue
        if entry_time.tzinfo is None:
            entry_time = entry_time.replace(tzinfo=timezone.utc)
        if entry_time > target_time:
            continue
        if best_time is None or entry_time > best_time:
            best, best_time = entry, entry_time
    return best


def compute_velocity(
    player_id: str,
    *,
    kind: str = "adds",
    window_hours: int = 24,
    history: list[dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Change in trending count for one player over ``window_hours``.

    Returns ``{"delta": int | None, "current": int | None,
    "priorCount": int | None, "hasEvidence": bool}``.  ``hasEvidence``
    is False (never a fabricated 0) when either endpoint of the window
    is not covered by retained history — MISSING IS NEVER ZERO applies
    to a velocity computation exactly as it does to a value.
    """
    hist = history if history is not None else load_history()
    if not hist:
        return {"delta": None, "current": None, "priorCount": None, "hasEvidence": False}

    ts_now = now or datetime.now(timezone.utc)
    latest = _nearest_entry_at_or_before(hist, ts_now)
    prior = _nearest_entry_at_or_before(hist, ts_now - timedelta(hours=window_hours))

    if latest is None or prior is None:
        return {"delta": None, "current": None, "priorCount": None, "hasEvidence": False}

    current = int((latest.get(kind) or {}).get(str(player_id), 0) or 0)
    prior_count = int((prior.get(kind) or {}).get(str(player_id), 0) or 0)
    return {
        "delta": current - prior_count,
        "current": current,
        "priorCount": prior_count,
        "hasEvidence": True,
    }
