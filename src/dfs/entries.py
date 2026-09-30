"""Platform ENTRY files: parse existing entries; export lineups into those entry IDs.

An entry file is what a platform lets a user download for contests they have
ALREADY entered: one row per entry (entry ID, contest ID, fee) plus that
entry's current lineup, if any.  Filling it lets the owner re-upload lineups
into entries that exist — ChaseUpside never submits anything itself.

Layout status: ``assumed``.  The DraftKings layout encoded here (``Entry ID``,
``Contest Name``, ``Contest ID``, ``Entry Fee``, then the rule set's slot
columns in order; cells as ``12345678`` or ``Name (12345678)``) is the commonly
documented shape, not a verified template.  A file whose header does not match
is refused (``ENTRY_FILE_UNRECOGNISED``) rather than parsed by guess, and every
lineup cell must resolve to a player on the chosen slate or the entry is
quarantined (``unresolved``) — an unknown ID is never matched by name.
Columns after the slot block (DraftKings appends instructions and a player
list) are ignored and counted, not interpreted.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from src.dfs.contests import ContestError, dollars_to_cents
from src.dfs.imports import ImportError_, SlateAthlete, _read_csv
from src.dfs.optimizer import validate_lineup
from src.dfs.rules import RuleSet

LAYOUT_VERIFICATION = {"draftkings_entries_csv_v1": "assumed"}
_ENTRY_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\-]{0,39}$")
_CELL = re.compile(r"^(?:.*\()?\s*([0-9A-Za-z][0-9A-Za-z\-]{0,39})\s*\)?$")
MAX_ENTRIES = 1000


@dataclass
class Entry:
    entry_id: str
    contest_id: str | None
    contest_name: str | None
    entry_fee_cents: int | None
    lineup: list[str | None]  # player IDs in slot order; None = empty slot
    state: str = "empty"  # empty | complete | partial | unresolved
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_entries(text: str, ruleset: RuleSet, athletes: list[SlateAthlete]) -> dict[str, Any]:
    """DraftKings entry file → entries resolved against ONE slate's athletes."""
    if ruleset.platform != "draftkings":
        raise ImportError_(
            "UNSUPPORTED_FORMAT",
            f"Entry files are only understood for DraftKings so far ({ruleset.platform} is not).",
        )
    header, rows = _read_csv(text)
    slots = [s.name for s in ruleset.slots]
    lead = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]
    if header[: len(lead)] != lead or header[len(lead) : len(lead) + len(slots)] != slots:
        raise ImportError_(
            "ENTRY_FILE_UNRECOGNISED",
            "This does not match the expected entry-file layout for this contest format.",
            {"expected": lead + slots, "found": header[: len(lead) + len(slots) + 2]},
        )
    by_id = {a.player_id: a for a in athletes}
    entries: list[Entry] = []
    ignored_rows = 0
    seen: set[str] = set()
    for r in rows:
        eid = (r.get("Entry ID") or "").strip()
        if not eid:
            ignored_rows += 1  # the appended player-list block has no entry ID
            continue
        if not _ENTRY_ID.match(eid) or eid in seen:
            ignored_rows += 1
            continue
        seen.add(eid)
        if len(entries) >= MAX_ENTRIES:
            raise ImportError_("TOO_MANY_ROWS", f"More than {MAX_ENTRIES} entries.")
        fee = None
        try:
            fee = (
                dollars_to_cents(r.get("Entry Fee"), "Entry fee")
                if (r.get("Entry Fee") or "").strip()
                else None
            )
        except ContestError:
            fee = None
        # Slot columns share names (RB, RB, WR…); csv.DictReader keeps only the
        # last, so read positionally from the raw row instead.
        entries.append(
            Entry(
                entry_id=eid,
                contest_id=(r.get("Contest ID") or "").strip() or None,
                contest_name=(r.get("Contest Name") or "").strip()[:120] or None,
                entry_fee_cents=fee,
                lineup=[],
            )
        )
    # Positional pass for the slot cells.
    raw_rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))[1:]
    by_entry = {e.entry_id: e for e in entries}
    start = len(lead)
    for raw in raw_rows:
        if not raw or not raw[0].strip() or raw[0].strip() not in by_entry:
            continue
        e = by_entry[raw[0].strip()]
        if e.lineup:
            continue
        cells = [
            (raw[start + i].strip() if start + i < len(raw) else "") for i in range(len(slots))
        ]
        lineup: list[str | None] = []
        for slot, cell in zip(slots, cells):
            if not cell:
                lineup.append(None)
                continue
            m = _CELL.match(cell)
            pid = m.group(1) if m else None
            if pid is None or pid not in by_id:
                e.problems.append(f"{slot}: '{cell[:40]}' is not a player on this slate")
                lineup.append(None)
            else:
                lineup.append(pid)
        e.lineup = lineup
        filled = [p for p in lineup if p]
        if e.problems:
            e.state = "unresolved"
        elif not filled:
            e.state = "empty"
        elif len(filled) == len(slots):
            e.state = "complete"
            errs = validate_lineup(list(zip(slots, filled)), ruleset, by_id)
            if errs:
                e.state = "unresolved"
                e.problems.extend(errs)
        else:
            e.state = "partial"
    return {
        "layout": "draftkings_entries_csv_v1",
        "layoutVerification": LAYOUT_VERIFICATION["draftkings_entries_csv_v1"],
        "entries": [e.to_dict() for e in entries],
        "ignoredRows": ignored_rows,
        "counts": {
            s: sum(1 for e in entries if e.state == s)
            for s in ("empty", "complete", "partial", "unresolved")
        },
    }


def export_into_entries(
    ruleset: RuleSet,
    lineups: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    athletes: list[SlateAthlete],
) -> tuple[str, dict[str, Any]]:
    """Fill built lineups into existing entry IDs, in order.  Nothing is submitted.

    Every lineup is re-validated.  Unresolved entries are never overwritten
    (the owner must look at them), and if there are more lineups than usable
    entries the extras are reported, not dropped silently.
    """
    by_id = {a.player_id: a for a in athletes}
    slots = [s.name for s in ruleset.slots]
    usable = [e for e in entries if e["state"] != "unresolved"]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    w.writerow(["Entry ID", "Contest Name", "Contest ID", "Entry Fee", *slots])
    assigned = []
    for lu, e in zip(lineups, usable):
        assignment = [(p["slot"], p["playerId"]) for p in lu["players"]]
        errs = validate_lineup(assignment, ruleset, by_id)
        if errs:
            raise ImportError_(
                "LINEUP_INVALID_AT_EXPORT",
                f"Lineup {lu.get('index')} is no longer valid.",
                {"errors": errs},
            )
        fee = e.get("entry_fee_cents")
        w.writerow(
            [
                e["entry_id"],
                e.get("contest_name") or "",
                e.get("contest_id") or "",
                "" if fee is None else f"${fee // 100}.{fee % 100:02d}",
                *[pid for _, pid in assignment],
            ]
        )
        assigned.append({"entryId": e["entry_id"], "lineupIndex": lu.get("index")})
    return out.getvalue(), {
        "assigned": assigned,
        "unusedLineups": max(0, len(lineups) - len(usable)),
        "untouchedEntries": [e["entry_id"] for e in entries if e["state"] == "unresolved"]
        + [e["entry_id"] for e in usable[len(lineups) :]],
        "layoutVerification": LAYOUT_VERIFICATION["draftkings_entries_csv_v1"],
    }
