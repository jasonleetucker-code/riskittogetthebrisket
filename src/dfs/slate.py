"""The canonical ChaseUpside DFS slate, and the platform-file adapters that build it.

ONE owner for "what is on this slate" (owner addendum 2026-09-30, DFS-ADD-06).
Every provider — an official DraftKings / FanDuel CSV the owner downloads, or a
licensed feed (``src/dfs/providers.py``) — maps INTO :class:`CanonicalSlate`.
Projections, contests, the optimizer and exports read the canonical slate and
never a provider's own objects, so a provider can change or fail without
touching anything downstream.

Slate ≠ contest.  A slate is the player pool, salaries, games and roster rules
that many contests share; a contest (``src/dfs/contests.py``) adds field size,
fee, payouts and entry limits, and points at a slate.

Detection is conservative.  Platform is recognised from the file's own header
signature, sport from the set of positions it contains, format from the roster
labels (a DraftKings ``CPT`` row means Showdown).  A file that matches no
signature, or more than one, is ``UNSUPPORTED_SLATE`` with the evidence — never
a best guess.  A recognised combination whose rule set is not encoded yet (MMA,
Showdown, NBA, NHL today) is ``UNSUPPORTED_FORMAT``: the file WAS understood and
the response says what was found, but no lineup can be built against rules
nobody has encoded.

Detection signatures are the documented layouts of these files and are checked
against synthetic fixtures only; a real template supplied by the owner is what
turns a layout from ``assumed`` into ``verified`` (see ``LAYOUT_VERIFICATION``).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.dfs.imports import (
    DK_COLUMNS,
    FD_COLUMNS,
    SALARY_PARSERS,
    ImportError_,
    SlateAthlete,
    _read_csv,
)
from src.dfs.rules import RuleSet, capability_matrix, get_ruleset

#: A layout is only ``verified`` once an official template fixture exists in
#: ``tests/dfs/fixtures/templates/`` and round-trips.  None does yet.
LAYOUT_VERIFICATION = {
    "draftkings_salary_csv_v1": "assumed",
    "fanduel_player_list_csv_v1": "assumed",
}

# Position signatures per platform.  ``distinct`` must intersect; every
# position must fall inside ``allowed``.  NBA and NHL share "C", and FanDuel's
# NFL defense is "D" like an NHL defenseman, which is why a sport also needs one
# of its distinctive positions.
_SPORT_SIGNATURES: dict[str, list[tuple[str, frozenset[str], frozenset[str]]]] = {
    "draftkings": [
        (
            "nfl",
            frozenset({"QB", "RB", "WR", "TE", "K", "DST"}),
            frozenset({"QB", "RB", "WR", "TE"}),
        ),
        ("nba", frozenset({"PG", "SG", "SF", "PF", "C"}), frozenset({"PG", "SG", "SF", "PF"})),
        (
            "nhl",
            frozenset({"C", "W", "LW", "RW", "D", "G"}),
            frozenset({"W", "LW", "RW", "D", "G"}),
        ),
        ("mma", frozenset({"F"}), frozenset({"F"})),
    ],
    "fanduel": [
        (
            "nfl",
            frozenset({"QB", "RB", "WR", "TE", "K", "D", "DEF"}),
            frozenset({"QB", "RB", "WR", "TE"}),
        ),
        ("nba", frozenset({"PG", "SG", "SF", "PF", "C"}), frozenset({"PG", "SG", "SF", "PF"})),
        ("nhl", frozenset({"C", "W", "LW", "RW", "D", "G"}), frozenset({"W", "LW", "RW", "G"})),
        ("mma", frozenset({"F", "FIGHTER"}), frozenset({"F", "FIGHTER"})),
    ],
}

_CAPTAIN_LABELS = {"CPT": "showdown_captain", "MVP": "single_game_mvp"}


@dataclass
class SlateEvent:
    event_id: str
    participants: list[str]
    start_time_utc: str | None = None
    status: str = "unknown"
    source_ids: dict[str, str] = field(default_factory=dict)


@dataclass
class CanonicalSlate:
    sport: str
    platform: str
    format: str
    athletes: list[SlateAthlete]
    events: list[SlateEvent]
    name: str | None = None
    slate_date: str | None = None
    start_time_utc: str | None = None
    lock_structure: str = "unknown"  # per_event | whole_slate | unknown (platform rule unverified)
    display_timezone: str = "America/New_York"
    external_ids: dict[str, str] = field(default_factory=dict)
    source_salary_cap: int | None = None
    source_roster_slots: list[str] | None = None
    unknown_columns: list[str] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)

    def header(self) -> dict[str, Any]:
        """Everything but the athletes (they are stored and served separately)."""
        d = asdict(self)
        d.pop("athletes")
        return d


@dataclass
class Detection:
    platform: str | None
    sport: str | None
    format: str | None
    layout: str | None
    reasons: list[str]
    positions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_platform_file(text: str) -> Detection:
    """Recognise platform, sport and format from a salary / player-list file."""
    header, rows = _read_csv(text)
    hset = set(header)
    reasons: list[str] = []
    if {"Name + ID", "Roster Position", "TeamAbbrev"} <= hset:
        platform, layout = "draftkings", "draftkings_salary_csv_v1"
        reasons.append("DraftKings salary header (Name + ID, Roster Position, TeamAbbrev)")
    elif {"Id", "FPPG"} <= hset and ("Nickname" in hset or {"First Name", "Last Name"} <= hset):
        platform, layout = "fanduel", "fanduel_player_list_csv_v1"
        reasons.append("FanDuel player-list header (Id, FPPG, Nickname)")
    else:
        return Detection(None, None, None, None, ["Header matches no supported platform file"], [])
    positions = sorted(
        {p.strip().upper() for r in rows for p in (r.get("Position") or "").split("/") if p.strip()}
    )
    slots = {
        s.strip().upper()
        for r in rows
        for s in (r.get("Roster Position") or "").split("/")
        if s.strip()
    }
    matches = [
        sport
        for sport, allowed, distinct in _SPORT_SIGNATURES[platform]
        if positions and set(positions) <= allowed and set(positions) & distinct
    ]
    if len(matches) != 1:
        reasons.append(
            f"Positions {positions} match {'no' if not matches else 'more than one'} supported sport"
        )
        return Detection(platform, None, None, layout, reasons, positions)
    sport = matches[0]
    reasons.append(f"Positions {positions} → {sport.upper()}")
    fmt = "classic"
    for label, name in _CAPTAIN_LABELS.items():
        if label in slots:
            fmt = name
            reasons.append(f"Roster position {label} → {name}")
    return Detection(platform, sport, fmt, layout, reasons, positions)


def _events_from(athletes: list[SlateAthlete]) -> list[SlateEvent]:
    events: dict[str, SlateEvent] = {}
    for a in athletes:
        if not a.game:
            continue
        ev = events.get(a.game)
        if ev is None:
            ev = events[a.game] = SlateEvent(
                event_id=a.game,
                participants=a.game.split("@", 1) if "@" in a.game else [a.game],
                start_time_utc=a.start_time_utc,
                status="scheduled" if a.start_time_utc else "unknown",
            )
        elif a.start_time_utc and ev.start_time_utc and a.start_time_utc != ev.start_time_utc:
            ev.status = "conflicting_start_times"
    return sorted(events.values(), key=lambda e: (e.start_time_utc or "", e.event_id))


def eligibility_cross_check(athletes: list[SlateAthlete], ruleset: RuleSet) -> dict[str, Any]:
    """Compare the platform's own per-player roster slots with the encoded rule set.

    Agreement is evidence FOR an unverified rule set; any disagreement is shown,
    never auto-resolved.
    """
    if ruleset.eligibility_basis == "platform_slots":
        # Eligibility IS the platform's row label here: comparing it with itself
        # would manufacture agreement, so no evidence is claimed.
        return {"checked": 0, "mismatched": 0, "examples": [], "state": "not_applicable"}
    checked = mismatched = 0
    examples: list[dict[str, Any]] = []
    for a in athletes:
        if not a.eligible_slots:
            continue
        platform = set(a.eligible_slots)
        ours = {s.name for s in ruleset.slots if set(a.positions) & set(s.eligible)}
        checked += 1
        if platform != ours:
            mismatched += 1
            if len(examples) < 10:
                examples.append(
                    {"playerId": a.player_id, "platform": sorted(platform), "ruleset": sorted(ours)}
                )
    return {
        "checked": checked,
        "mismatched": mismatched,
        "examples": examples,
        "state": "no_platform_slots"
        if not checked
        else ("agrees" if not mismatched else "disagrees"),
    }


def canonical_from_platform_file(
    text: str, expected: tuple[str, str, str] | None = None, label: str | None = None
) -> tuple[CanonicalSlate, RuleSet, dict[str, Any]]:
    """Official platform salary file → canonical slate (+ its rule set + import report).

    ``expected`` is the (platform, sport, format) the owner selected; a file
    for anything else is refused rather than silently switched.
    """
    det = detect_platform_file(text)
    if det.platform is None or det.sport is None:
        raise ImportError_(
            "UNSUPPORTED_SLATE", "This file is not a supported platform salary file.", det.to_dict()
        )
    if expected and (det.platform, det.sport, det.format) != tuple(expected):
        raise ImportError_(
            "CSV_WRONG_PLATFORM",
            f"This is a {det.platform} {det.sport.upper()} {det.format} file, but "
            f"{expected[0]} {expected[1].upper()} {expected[2]} is selected.",
            det.to_dict(),
        )
    row = next(
        (
            r
            for r in capability_matrix()
            if (r["platform"], r["sport"], r["format"]) == (det.platform, det.sport, det.format)
        ),
        None,
    )
    rs = get_ruleset(row["ruleset"].split("@", 1)[0]) if row and row["ruleset"] else None
    if rs is None:
        raise ImportError_(
            "UNSUPPORTED_FORMAT",
            f"Recognised a {det.platform} {det.sport.upper()} {det.format.replace('_', ' ')} file, but its roster "
            "rules are not encoded yet, so no lineup can be built for it.",
            {**det.to_dict(), "reason": (row or {}).get("reason")},
        )
    athletes, report = SALARY_PARSERS[rs.salary_import](text)
    header, _rows = _read_csv(text)
    known = DK_COLUMNS if det.platform == "draftkings" else FD_COLUMNS
    starts = sorted(a.start_time_utc for a in athletes if a.start_time_utc)
    slate = CanonicalSlate(
        sport=det.sport,
        platform=det.platform,
        format=det.format,
        athletes=athletes,
        events=_events_from(athletes),
        name=label,
        start_time_utc=starts[0] if starts else None,
        slate_date=starts[0][:10] if starts else None,
        unknown_columns=[h for h in header if h and h not in known],
        provenance={
            "sourceKind": "platform_csv",
            "adapter": rs.salary_import,
            "layoutVerification": LAYOUT_VERIFICATION.get(rs.salary_import, "assumed"),
            "fileSha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "importedAt": datetime.now(timezone.utc).isoformat(),
            "detection": det.reasons,
        },
    )
    extra = {
        "importReport": report.to_dict(),
        "eligibilityCrossCheck": eligibility_cross_check(athletes, rs),
    }
    return slate, rs, extra
