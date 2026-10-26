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

from src.dfs.auto import PlatformIdsUnavailable, refuse_synthetic_ids
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


_ID_NAMES = ("entry id", "entry_id", "entryid")
_CONTEST_ID_NAMES = ("contest id", "contest_id", "contestid")
_CONTEST_NAME_NAMES = ("contest name", "contest_name", "contest")
_FEE_NAMES = ("entry fee", "entry_fee", "fee")


def _layout(header: list[str], ruleset: RuleSet) -> dict[str, Any]:
    """Where each needed column is.  DraftKings: its strict documented shape.
    Anything else: HEADER-DETECTED — entry-ID column and the rule set's slot
    columns, consecutive and in order, found by name; otherwise refused."""
    slots = [s.name for s in ruleset.slots]
    if ruleset.platform == "draftkings":
        lead = ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"]
        if header[: len(lead)] != lead or header[len(lead) : len(lead) + len(slots)] != slots:
            raise ImportError_(
                "ENTRY_FILE_UNRECOGNISED",
                "This does not match the expected entry-file layout for this contest format.",
                {"expected": lead + slots, "found": header[: len(lead) + len(slots) + 2]},
            )
        return {
            "name": "draftkings_entries_csv_v1",
            "entry": 0,
            "contestName": 1,
            "contestId": 2,
            "fee": 3,
            "slotStart": len(lead),
        }
    low = [h.strip().lower() for h in header]

    def find(names):
        return next((i for i, h in enumerate(low) if h in names), None)

    entry = find(_ID_NAMES)
    upper = [h.strip().upper() for h in header]
    want = [x.upper() for x in slots]
    start = next(
        (i for i in range(len(upper) - len(want) + 1) if upper[i : i + len(want)] == want), None
    )
    if entry is None or start is None:
        raise ImportError_(
            "ENTRY_FILE_UNRECOGNISED",
            "No entry-ID column, or this contest format's slot columns in order, were found.",
            {"expectedSlots": slots, "found": header[:24]},
        )
    lay = {
        "name": f"{ruleset.platform}_entries_header_detected_v1",
        "entry": entry,
        "contestName": find(_CONTEST_NAME_NAMES),
        "contestId": find(_CONTEST_ID_NAMES),
        "fee": find(_FEE_NAMES),
        "slotStart": start,
    }
    return lay


LAYOUT_VERIFICATION.setdefault("header_detected", "assumed")
DK_EXPORT_LAYOUT = {
    "header": ["Entry ID", "Contest Name", "Contest ID", "Entry Fee"],
    "roles": ["entry", "contestName", "contestId", "fee"],
}


def export_layout(lay: dict[str, Any], header: list[str], n_slots: int) -> dict[str, Any]:
    """The columns an export writes back: the file's own names, in its own order."""
    roles = sorted(
        (r for r in ("entry", "contestName", "contestId", "fee") if lay.get(r) is not None),
        key=lambda r: lay[r],
    )
    return {
        "header": [header[lay[r]] for r in roles]
        + header[lay["slotStart"] : lay["slotStart"] + n_slots],
        "roles": roles,
    }


def export_row(e: dict[str, Any], lineup: list[str], layout: dict[str, Any]) -> list[str]:
    fee = e.get("entry_fee_cents")
    values = {
        "entry": e["entry_id"],
        "contestName": e.get("contest_name") or "",
        "contestId": e.get("contest_id") or "",
        "fee": "" if fee is None else f"${fee // 100}.{fee % 100:02d}",
    }
    return [values[r] for r in layout["roles"]] + list(lineup)


def parse_entries(text: str, ruleset: RuleSet, athletes: list[SlateAthlete]) -> dict[str, Any]:
    """A platform entry file → entries resolved against ONE slate's athletes."""
    # Same guards as every upload (empty, size, malformed, row count) BEFORE parsing.
    _read_csv(text)
    raw_rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    header = [h.strip() for h in raw_rows[0]]
    lay = _layout(header, ruleset)
    slots = [s.name for s in ruleset.slots]
    by_id = {a.player_id: a for a in athletes}
    entries: list[Entry] = []
    ignored_rows = 0
    seen: set[str] = set()

    def cell(raw: list[str], idx: int | None) -> str:
        return raw[idx].strip() if idx is not None and idx < len(raw) else ""

    # Read positionally: slot columns share names (RB, RB, WR…), so a dict
    # reader would keep only the last of each.
    for raw in raw_rows[1:]:
        eid = cell(raw, lay["entry"])
        if not eid:
            ignored_rows += 1  # e.g. DraftKings appends a player-list block with no entry ID
            continue
        if not _ENTRY_ID.match(eid) or eid in seen:
            ignored_rows += 1
            continue
        seen.add(eid)
        if len(entries) >= MAX_ENTRIES:
            raise ImportError_("TOO_MANY_ROWS", f"More than {MAX_ENTRIES} entries.")
        fee = None
        try:
            fee_text = cell(raw, lay["fee"])
            fee = dollars_to_cents(fee_text, "Entry fee") if fee_text else None
        except ContestError:
            fee = None
        e = Entry(
            entry_id=eid,
            contest_id=cell(raw, lay["contestId"]) or None,
            contest_name=cell(raw, lay["contestName"])[:120] or None,
            entry_fee_cents=fee,
            lineup=[],
        )
        lineup: list[str | None] = []
        for i, slot in enumerate(slots):
            c = cell(raw, lay["slotStart"] + i)
            if not c:
                lineup.append(None)
                continue
            m = _CELL.match(c)
            pid = m.group(1) if m else None
            if pid is None or pid not in by_id:
                e.problems.append(f"{slot}: '{c[:40]}' is not a player on this slate")
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
        entries.append(e)
    verification = LAYOUT_VERIFICATION.get(lay["name"], LAYOUT_VERIFICATION["header_detected"])
    return {
        "layout": lay["name"],
        "layoutVerification": verification,
        "exportLayout": export_layout(lay, header, len(slots)),
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
    layout: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Fill built lineups into existing entry IDs, in order.  Nothing is submitted.

    ``layout`` (from ``parse_entries``) writes the file back in the columns it
    was read with; the default is the DraftKings layout.

    Every lineup is re-validated.  Unresolved entries are never overwritten
    (the owner must look at them), and if there are more lineups than usable
    entries the extras are reported, not dropped silently.
    """
    by_id = {a.player_id: a for a in athletes}
    slots = [s.name for s in ruleset.slots]
    usable = [e for e in entries if e["state"] != "unresolved"]
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\r\n")
    layout = layout or {**DK_EXPORT_LAYOUT, "header": DK_EXPORT_LAYOUT["header"] + slots}
    w.writerow(layout["header"])
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
        try:
            refuse_synthetic_ids([pid for _, pid in assignment])
        except PlatformIdsUnavailable as exc:
            raise ImportError_(exc.code, exc.message, exc.detail) from exc
        w.writerow(export_row(e, [pid for _, pid in assignment], layout))
        assigned.append({"entryId": e["entry_id"], "lineupIndex": lu.get("index")})
    return out.getvalue(), {
        "assigned": assigned,
        "unusedLineups": max(0, len(lineups) - len(usable)),
        "untouchedEntries": [e["entry_id"] for e in entries if e["state"] == "unresolved"]
        + [e["entry_id"] for e in usable[len(lineups) :]],
        "layoutVerification": LAYOUT_VERIFICATION["draftkings_entries_csv_v1"],
    }
