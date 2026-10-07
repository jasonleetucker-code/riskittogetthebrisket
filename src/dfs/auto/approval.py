"""Owner approval of the schedule source behind automatic NBA / NHL slates (ADR-DFS-025).

NBA / NHL automatic slates are timed by ESPN's public scoreboard.  ESPN is an
owner-attested Calculator provider, but the attestation record
(``docs/game-day/SOURCE_ACCESS_EVIDENCE_2026-09-25.md``) requires a NEW owner
decision for a use "materially outside the intended integration" — and reading
ESPN's NBA / NHL scoreboards for DFS is plausibly that.  So the whole NBA / NHL
path is built and tested but gated on a recorded owner decision, per sport, in
``config/dfs/auto_sources.json``:

* approved ONLY when the entry says ``approval: "approved"`` AND carries an
  ``approvedOn`` date AND ``evidence`` — anything else (pending, missing file,
  malformed entry, unknown sport) fails CLOSED;
* NFL automatic slates never read this record (their sources are approved under
  ADR-DFS-024), so they are unaffected.

This is a source-approval RECORD (like ``config/dfs/source_seeds.json`` access
states and ``config/dfs/rulesets.json`` verification states), not a rollout
toggle; the rollout lever for all automatic slates stays the ``dfs_auto_slates``
feature flag.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PATH = Path(__file__).resolve().parents[3] / "config" / "dfs" / "auto_sources.json"
APPROVED = "approved"
PENDING = "pending_owner_decision"
GATED_SPORTS = ("nba", "nhl")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load(path: Path | None = None) -> dict[str, Any]:
    try:
        data = json.loads((path or PATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def sport_status(sport: str, path: Path | None = None) -> dict[str, Any]:
    """The schedule-source approval state for one daily sport (fails closed)."""
    entry = ((_load(path).get("sports") or {}).get(sport)) if sport in GATED_SPORTS else None
    if not isinstance(entry, dict):
        return {
            "sport": sport,
            "approved": False,
            "approval": "missing",
            "scheduleSource": None,
            "decisionRecord": None,
            "question": None,
        }
    approval = str(entry.get("approval") or "")
    approved = (
        approval == APPROVED
        and bool(_DATE.match(str(entry.get("approvedOn") or "")))
        and bool(str(entry.get("evidence") or "").strip())
    )
    return {
        "sport": sport,
        "approved": approved,
        "approval": approval if approved or approval != APPROVED else "approved_without_evidence",
        "scheduleSource": entry.get("scheduleSource"),
        "decisionRecord": entry.get("decisionRecord"),
        "question": entry.get("question"),
    }


def awaiting_reason(sport: str) -> str:
    label = sport.upper()
    return (
        f"Automatic {label} slates are built and waiting for the owner to approve their schedule "
        f"source (ESPN's public {label} scoreboard, for start times and lock). Until then, load "
        "the platform's salary file under Advanced."
    )
