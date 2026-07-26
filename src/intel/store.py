"""Persistence layer for the Sleeper intel snapshot.

Writes the crawl state (members, leagues, events, cursor) to
``data/intel/snapshot_<leagueKey>.json``.  Mirrors the atomic-write
pattern from ``src/public_league/snapshot_store.py::_atomic_write_json``
— write to a uniquely-named temp file in the same directory, then
``Path.replace`` onto the target so a reader never observes a
half-written file.

Snapshots are PARTITIONED BY LEAGUE KEY: intel is roster-scoped, and
per CLAUDE.md roster-scoped data is league-scoped — each active
league's member pool gets its own snapshot file so refreshing one
league can never clobber (or leak into) another's.

Guarantees:
    * ``load_state`` NEVER raises on a missing or corrupt snapshot —
      it returns a fresh empty state so the crawler can rebuild.
    * ``save_state`` prunes events older than ``EVENT_RETENTION_DAYS``
      before writing.
    * ``merge_member_results`` preserves the previous run's data for
      any member whose fetch failed this run.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data" / "intel"

DEFAULT_LEAGUE_KEY = "default"
STATE_VERSION = 1
EVENT_RETENTION_DAYS = 45


def snapshot_path(league_key: str = DEFAULT_LEAGUE_KEY) -> Path:
    """Per-league snapshot file.  The key is sanitised so a registry
    key can never traverse outside ``DATA_DIR``."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", str(league_key or DEFAULT_LEAGUE_KEY))
    return DATA_DIR / f"snapshot_{safe}.json"


def _utc_now_ms() -> int:
    return int(time.time() * 1000)


def default_state(season: str | None = None) -> dict[str, Any]:
    """A fresh, empty crawl state.  All persisted shapes start here so
    loaders can ``setdefault`` missing keys on older snapshots."""
    return {
        "version": STATE_VERSION,
        "season": str(season or ""),
        "generatedAt": None,
        "week": None,
        "weekFirstSeenAt": {},
        "memberNames": {},
        "members": {},
        "leagues": {},
        "events": [],
        "cursor": None,
        "lastRun": None,
    }


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{int(time.time() * 1000)}")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def load_state(
    league_key: str = DEFAULT_LEAGUE_KEY,
    path: Path | None = None,
) -> dict[str, Any]:
    """Load the persisted snapshot for one league.  Returns a fresh
    empty state when the file is missing, unreadable, or corrupt —
    never raises."""
    target = path or snapshot_path(league_key)
    try:
        if not target.exists():
            return default_state()
    except OSError:
        return default_state()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        log.warning("intel.store: failed to load %s: %s", target, exc)
        return default_state()
    if not isinstance(payload, dict):
        log.warning("intel.store: snapshot at %s is not a dict — resetting", target)
        return default_state()
    state = default_state()
    state.update(payload)
    # Defensive re-typing for the collection keys a corrupt writer
    # could have mangled.
    if not isinstance(state.get("members"), dict):
        state["members"] = {}
    if not isinstance(state.get("leagues"), dict):
        state["leagues"] = {}
    if not isinstance(state.get("events"), list):
        state["events"] = []
    if not isinstance(state.get("memberNames"), dict):
        state["memberNames"] = {}
    if not isinstance(state.get("weekFirstSeenAt"), dict):
        state["weekFirstSeenAt"] = {}
    return state


def prune_events(state: dict[str, Any], now_ms: int | None = None) -> int:
    """Drop events older than ``EVENT_RETENTION_DAYS``.  Mutates
    ``state`` in place; returns the number of events removed."""
    now = now_ms if now_ms is not None else _utc_now_ms()
    cutoff = now - EVENT_RETENTION_DAYS * 24 * 3600 * 1000
    events = state.get("events") or []
    kept = [
        e
        for e in events
        if isinstance(e, dict) and isinstance(e.get("ts"), (int, float)) and e["ts"] >= cutoff
    ]
    removed = len(events) - len(kept)
    state["events"] = kept
    return removed


def save_state(
    state: dict[str, Any],
    league_key: str = DEFAULT_LEAGUE_KEY,
    path: Path | None = None,
    now_ms: int | None = None,
) -> None:
    """Prune old events, stamp ``generatedAt``, atomically persist to
    the league's partition."""
    prune_events(state, now_ms=now_ms)
    now = now_ms if now_ms is not None else _utc_now_ms()
    state["generatedAt"] = datetime.fromtimestamp(now / 1000, tz=timezone.utc).isoformat()
    _atomic_write_json(path or snapshot_path(league_key), state)


def merge_member_results(
    prev_state: dict[str, Any],
    new_state: dict[str, Any],
    failed_member_ids: list[str] | None,
) -> dict[str, Any]:
    """Return ``new_state`` with the previous run's data restored for
    every member whose fetch failed this run.

    For each failed member:
      * the member entry keeps its previous ``leagues`` / ``truncated``
        / ``lastCrawledAt`` fields (only ``lastError`` is taken from
        the new run so the failure is visible),
      * any league the member belonged to that is missing from the new
        state is copied back, and
      * previous events that vanished from the new state are re-added
        (dedup by ``eventId``).
    """
    merged = new_state
    failed = [str(f) for f in (failed_member_ids or []) if str(f or "").strip()]
    if not failed or not isinstance(prev_state, dict):
        return merged

    prev_members = prev_state.get("members") or {}
    prev_leagues = prev_state.get("leagues") or {}
    merged_members = merged.setdefault("members", {})
    merged_leagues = merged.setdefault("leagues", {})

    restored_league_ids: set[str] = set()
    for oid in failed:
        prev_entry = prev_members.get(oid)
        if not isinstance(prev_entry, dict):
            continue
        new_entry = merged_members.get(oid)
        preserved = copy.deepcopy(prev_entry)
        if isinstance(new_entry, dict) and new_entry.get("lastError"):
            preserved["lastError"] = new_entry["lastError"]
        merged_members[oid] = preserved
        for lid in preserved.get("leagues") or []:
            lid = str(lid)
            if lid not in merged_leagues and lid in prev_leagues:
                merged_leagues[lid] = copy.deepcopy(prev_leagues[lid])
                restored_league_ids.add(lid)

    if restored_league_ids:
        existing_ids = {e.get("eventId") for e in merged.get("events") or [] if isinstance(e, dict)}
        for event in prev_state.get("events") or []:
            if not isinstance(event, dict):
                continue
            if str(event.get("leagueId") or "") not in restored_league_ids:
                continue
            if event.get("eventId") in existing_ids:
                continue
            merged.setdefault("events", []).append(copy.deepcopy(event))
            existing_ids.add(event.get("eventId"))
    return merged
