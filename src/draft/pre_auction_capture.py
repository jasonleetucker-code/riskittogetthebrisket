"""Pre-auction snapshot gate: WHEN a pre-draft capture may be recorded, and where.

The pre-draft board and every team's roster context stop being recoverable once
the first rookie pick lands (``scripts/backtest_perfect_draft.py`` docstring), so
the capture is automated rather than left to an operator remembering.  This module
is the pure decision layer; ``scripts/capture_pre_auction_snapshot.py`` wires it to
Sleeper (through ``src.public_league.sleeper_client``) and to ``build_snapshot``.

Rules (all fail closed):

* A draft for the target season that is ``drafting`` / ``complete``, or whose
  ``start_time`` has passed, means the auction has started: NEVER record.
* An unreadable drafts list is unknown, not "not started": refuse (transient).
* ``<year>-pre.json`` is first-valid-wins and never overwritten.  It is written
  only when Sleeper states a future ``start_time`` inside ``window_days``.
* Before that window (or while no start is scheduled) one
  ``<year>-early-<ISO week>.json`` per ISO week is kept as an insurance copy,
  also never overwritten.  Early copies are labelled and never stand in for the
  pre-auction snapshot.

Limitation, stated rather than hidden: "started" is read from Sleeper draft
state; an in-app auction run with no Sleeper draft object cannot be seen here.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = "pre_auction_capture.v1"
DEFAULT_WINDOW_DAYS = 7
#: A start this close is treated as already begun (clock skew / Sleeper lag).
START_MARGIN = timedelta(minutes=15)
STARTED_STATUSES = frozenset({"drafting", "complete"})


@dataclass(frozen=True)
class Decision:
    action: str  # "record_pre" | "record_early" | "refuse"
    reason: str
    start_time: datetime | None = None
    drafts: tuple[dict[str, Any], ...] = ()


def _start(raw: Any) -> datetime | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or raw <= 0:
        return None
    return datetime.fromtimestamp(raw / 1000.0, tz=timezone.utc)


def decide(
    drafts: Sequence[Mapping[str, Any]],
    draft_year: int,
    now: datetime,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> Decision:
    """Pure: what may be recorded for ``draft_year`` right now."""
    mine = [d for d in drafts if isinstance(d, Mapping) and str(d.get("season")) == str(draft_year)]
    summary = tuple(
        {
            "draftId": str(d.get("draft_id")),
            "status": d.get("status"),
            "type": d.get("type"),
            "startTime": d.get("start_time"),
        }
        for d in mine
    )
    starts: list[datetime] = []
    for d in mine:
        if str(d.get("status") or "").lower() in STARTED_STATUSES:
            return Decision(
                "refuse", f"draft_started:{d.get('draft_id')}:{d.get('status')}", None, summary
            )
        st = _start(d.get("start_time"))
        if st is not None:
            if st - START_MARGIN <= now:
                return Decision(
                    "refuse", f"draft_start_time_passed:{d.get('draft_id')}", st, summary
                )
            starts.append(st)
    if not starts:
        return Decision("record_early", "no_scheduled_start", None, summary)
    first = min(starts)
    if first - now <= timedelta(days=window_days):
        return Decision("record_pre", "inside_window", first, summary)
    return Decision("record_early", "before_window", first, summary)


def pre_path(out_dir: Path, draft_year: int) -> Path:
    return out_dir / f"{int(draft_year)}-pre.json"


def early_path(out_dir: Path, draft_year: int, now: datetime) -> Path:
    iso = now.isocalendar()
    return out_dir / f"{int(draft_year)}-early-{iso[0]}W{iso[1]:02d}.json"


def write_once(path: Path, payload: Mapping[str, Any]) -> bool:
    """Atomic no-replace write.  ``False`` when ``path`` already exists."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return False
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True, default=str)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            return False
    finally:
        tmp.unlink(missing_ok=True)
    return True


def stamp(
    payload: dict[str, Any], decision: Decision, draft_year: int, now: datetime
) -> dict[str, Any]:
    out = dict(payload)
    out["captureReceipt"] = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "pre" if decision.action == "record_pre" else "early",
        "draftYear": int(draft_year),
        "recordedAt": now.isoformat(),
        "reason": decision.reason,
        "scheduledStart": decision.start_time.isoformat() if decision.start_time else None,
        "sleeperDrafts": list(decision.drafts),
    }
    return out
