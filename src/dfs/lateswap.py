"""Late swap: re-optimize the slots that have not locked, never the ones that have.

Input is the owner's imported entries (``src/dfs/entries.py``) on one slate
snapshot and a clock.  For each entry:

* a slot is **locked** when its player's game has started; a slot whose player
  has an UNKNOWN start time is treated as locked too — "cannot prove it is
  still open" must preserve the player, never free the slot;
* only players whose game is PROVEN not started may be swapped in;
* the locked players are pinned to their exact slots (``Constraints.slot_pins``)
  and the ordinary optimizer fills the rest under the full rule set.

Each entry is planned independently (no cross-entry exposure — disclosed).
Nothing is submitted: the output is a recommendation plus an entry file the
owner uploads themselves.  An ``unresolved`` entry is never touched.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from src.dfs.entries import DK_EXPORT_LAYOUT, LAYOUT_VERIFICATION, export_row
from src.dfs.imports import ImportError_, SlateAthlete
from src.dfs.optimizer import ConstraintError, Constraints, optimize, validate_lineup
from src.dfs.rules import RuleSet

METHOD_NOTE = (
    "Each entry is re-optimized on its own: locked slots are kept exactly, open slots take the "
    "highest-projected legal replacement. Entries are not coordinated with each other."
)


def _parse_utc(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None  # a naive time cannot be compared honestly with the clock
    return dt.astimezone(timezone.utc)


def player_lock_state(a: SlateAthlete, now: datetime) -> str:
    """``locked`` | ``open`` | ``unknown`` (unknown start time → cannot prove open)."""
    start = _parse_utc(a.start_time_utc)
    if start is None:
        return "unknown"
    return "locked" if start <= now else "open"


def plan_late_swap(
    ruleset: RuleSet,
    athletes: list[SlateAthlete],
    entries: list[dict[str, Any]],
    now: datetime,
    *,
    time_budget_s: float = 10.0,
) -> dict[str, Any]:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    by_id = {a.player_id: a for a in athletes}
    state = {a.player_id: player_lock_state(a, now) for a in athletes}
    slots = [s.name for s in ruleset.slots]
    swappable_out = sorted(pid for pid, st in state.items() if st != "open")
    plans = []
    for e in entries:
        plans.append(
            _plan_entry(ruleset, athletes, by_id, state, slots, swappable_out, e, time_budget_s)
        )
    counts: dict[str, int] = {}
    for p in plans:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    return {
        "asOf": now.isoformat(),
        "methodNote": METHOD_NOTE,
        "playersByLockState": {
            k: sum(1 for v in state.values() if v == k) for k in ("locked", "open", "unknown")
        },
        "entries": plans,
        "counts": counts,
        "submitted": False,
    }


def _plan_entry(
    ruleset: RuleSet,
    athletes: list[SlateAthlete],
    by_id: dict[str, SlateAthlete],
    state: dict[str, str],
    slots: list[str],
    not_open: list[str],
    e: dict[str, Any],
    budget: float,
) -> dict[str, Any]:
    base = {"entryId": e["entry_id"], "contestName": e.get("contest_name")}
    if e.get("state") == "unresolved":
        return {
            **base,
            "status": "entry_unresolved",
            "problems": e.get("problems", []),
            "note": "Left untouched: fix the entry's players first.",
        }
    lineup: list[str | None] = list(e.get("lineup") or [None] * len(slots))
    slot_states = []
    pins: dict[int, str] = {}
    for s_idx, pid in enumerate(lineup):
        if pid is None:
            slot_states.append({"slot": slots[s_idx], "playerId": None, "state": "empty"})
            continue
        st = state.get(pid, "unknown")
        slot_states.append({"slot": slots[s_idx], "playerId": pid, "state": st})
        if st != "open":
            pins[s_idx] = pid
    if len(pins) == len(slots):
        return {
            **base,
            "status": "all_locked",
            "slots": slot_states,
            "finalLineup": lineup,
            "changes": [],
        }
    c = Constraints(
        # Players who cannot be proven open may not come IN; pinned ones stay.
        excludes=[p for p in not_open if p not in set(pins.values())],
        lineups=1,
        slot_pins=pins,
        time_budget_s=budget,
    )
    try:
        result = optimize(ruleset, athletes, c)
    except ConstraintError as exc:
        return {
            **base,
            "status": "no_legal_swap",
            "slots": slot_states,
            "finalLineup": lineup,
            "changes": [],
            "shortfall": {"reason": exc.code, "message": exc.message},
        }
    if not result["lineups"]:
        return {
            **base,
            "status": "no_legal_swap",
            "slots": slot_states,
            "finalLineup": lineup,
            "changes": [],
            "shortfall": result.get("shortfall"),
        }
    new = result["lineups"][0]
    new_ids = [p["playerId"] for p in new["players"]]
    errors = validate_lineup(list(zip(slots, new_ids)), ruleset, by_id, c)
    if errors:  # belt and braces: the optimizer validated already
        return {**base, "status": "no_legal_swap", "slots": slot_states, "errors": errors}
    changes = [
        {"slot": slots[i], "out": lineup[i], "in": new_ids[i]}
        for i in range(len(slots))
        if lineup[i] != new_ids[i]
    ]

    def slot_points(pid: str | None, i: int) -> float | None:
        if pid is None or by_id[pid].projection is None:
            return None
        return by_id[pid].projection * ruleset.points_multiplier(slots[i])  # type: ignore[operator]

    # Locked slots are identical on both sides, so the gain is measured over
    # the OPEN slots — comparable even when a locked player has no projection.
    open_idx = [i for i in range(len(slots)) if i not in pins]
    cur_open = [slot_points(lineup[i], i) for i in open_idx]
    new_open = [slot_points(new_ids[i], i) for i in open_idx]
    gain = (
        round(sum(new_open) - sum(cur_open), 2)  # type: ignore[arg-type]
        if None not in cur_open and None not in new_open
        else None
    )
    # An empty or unprojected open slot is always worth filling; otherwise a
    # change must gain something — a tie or a reshuffle is churn, not advice.
    must_fill = any(v is None for v in cur_open)
    recommend = bool(changes) and (must_fill or (gain is not None and gain > 0))
    final = new_ids if recommend else lineup
    return {
        **base,
        "status": "swap_recommended" if recommend else "keep",
        "slots": slot_states,
        "finalLineup": final,
        "changes": changes if recommend else [],
        "openSlotGain": gain if recommend or gain is None else 0.0,
        "reason": (
            "fills an empty or unprojected open slot"
            if recommend and must_fill
            else "higher projected points in the open slots"
            if recommend
            else "no open-slot change gains projected points"
        ),
        "lineup": new if recommend else None,
    }


def export_late_swap(
    ruleset: RuleSet,
    plan: dict[str, Any],
    entries: list[dict[str, Any]],
    athletes: list[SlateAthlete],
    layout: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Entry file with each planned entry's final lineup (in the file's own layout).  Unresolved and
    unplannable entries are left out and listed — never overwritten."""
    by_id = {a.player_id: a for a in athletes}
    slots = [s.name for s in ruleset.slots]
    meta = {e["entry_id"]: e for e in entries}
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    layout = layout or {**DK_EXPORT_LAYOUT, "header": DK_EXPORT_LAYOUT["header"] + slots}
    w.writerow(layout["header"])
    written, skipped = [], []
    for p in plan["entries"]:
        final = p.get("finalLineup")
        if (
            p["status"] not in ("swap_recommended", "keep", "all_locked")
            or not final
            or None in final
        ):
            skipped.append({"entryId": p["entryId"], "status": p["status"]})
            continue
        errs = validate_lineup(list(zip(slots, final)), ruleset, by_id)
        if errs:
            raise ImportError_(
                "LINEUP_INVALID_AT_EXPORT", f"Entry {p['entryId']} is not valid.", {"errors": errs}
            )
        e = {"entry_id": p["entryId"], **meta.get(p["entryId"], {})}
        w.writerow(export_row(e, final, layout))
        written.append(p["entryId"])
    return out.getvalue(), {
        "written": written,
        "skipped": skipped,
        "layoutVerification": LAYOUT_VERIFICATION["draftkings_entries_csv_v1"],
    }
