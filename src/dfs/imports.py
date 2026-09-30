"""Owner-imported DFS files: platform salary lists and projection CSVs.

Every file is UNTRUSTED input.  The parsers enforce size/row limits, require
their declared header contract (a header mismatch fails loud with the expected
and found columns — never a best-effort column guess), keep platform player
IDs as strings, and report every row they could not use.

Identity (projection → slate athlete) is joined inside ONE slate only:

1. exact platform player ID;
2. otherwise exact normalized name (``src.utils.name_clean`` — the shared
   normalizer, not a DFS-local one) + team, narrowed by position if given.

More than one candidate is AMBIGUOUS and quarantined; zero is UNMATCHED.  There
is no fuzzy rung: an unresolved identity is not a best guess.

MISSING IS NEVER ZERO.  A slate athlete with no projection carries
``projection=None`` and is excluded from projection-objective optimization and
reported, never scored as 0.  The platform's own season average may be used
only when the owner explicitly selects it, and it is labelled
``platform_season_average`` — it is an observation, not a forecast.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.utils.name_clean import normalize_player_name, normalize_team

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000

PROJECTION_SOURCES = ("owner_import", "platform_season_average")


class ImportError_(ValueError):
    """A structured, user-facing import failure."""

    def __init__(self, code: str, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


@dataclass
class SlateAthlete:
    player_id: str
    name: str
    positions: list[str]
    team: str
    opponent: str | None
    game: str | None
    salary: int
    start_time_utc: str | None = None
    status: str | None = None
    platform_average: float | None = None
    projection: float | None = None
    projection_source: str | None = None
    projection_match: str | None = None
    # Roster slots the PLATFORM says this athlete may fill (its own labels,
    # e.g. ["RB", "FLEX"]).  Evidence, not rules: it is cross-checked against
    # the rule set, never used to override it.
    eligible_slots: list[str] = field(default_factory=list)
    # Every source column this adapter does not consume, verbatim.
    extra: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ImportReport:
    rows_read: int = 0
    rows_used: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)

    def reject(self, row_number: int, reason: str, raw: dict[str, Any] | None = None) -> None:
        if len(self.rejected) < 200:
            self.rejected.append({"row": row_number, "reason": reason, "raw": _safe_raw(raw)})

    def to_dict(self) -> dict[str, Any]:
        return {"rowsRead": self.rows_read, "rowsUsed": self.rows_used, "rejected": self.rejected}


def _safe_raw(raw: dict[str, Any] | None) -> dict[str, str] | None:
    if raw is None:
        return None
    return {str(k)[:40]: str(v)[:80] for k, v in list(raw.items())[:20]}


def _read_csv(text: str) -> tuple[list[str], list[dict[str, str]]]:
    if not isinstance(text, str) or not text.strip():
        raise ImportError_("EMPTY_FILE", "The file is empty.")
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportError_("FILE_TOO_LARGE", f"Files over {MAX_FILE_BYTES // 1024} KB are refused.")
    text = text.lstrip("﻿")
    reader = csv.reader(io.StringIO(text))
    try:
        header = [h.strip() for h in next(reader)]
    except (StopIteration, csv.Error) as exc:
        raise ImportError_("MALFORMED_CSV", "Could not read a CSV header row.") from exc
    rows: list[dict[str, str]] = []
    try:
        for i, cells in enumerate(reader):
            if i >= MAX_ROWS:
                raise ImportError_("TOO_MANY_ROWS", f"Files over {MAX_ROWS} rows are refused.")
            if not any(c.strip() for c in cells):
                continue
            rows.append(
                {
                    header[j]: (cells[j].strip() if j < len(cells) else "")
                    for j in range(len(header))
                }
            )
    except csv.Error as exc:
        raise ImportError_("MALFORMED_CSV", f"CSV parse error: {exc}") from exc
    return header, rows


def _require(header: list[str], required: list[str], fmt: str) -> None:
    missing = [c for c in required if c not in header]
    if missing:
        raise ImportError_(
            "HEADER_MISMATCH",
            f"This does not look like a {fmt} file: missing column(s) {', '.join(missing)}.",
            {"expected": required, "found": header[:40]},
        )


def _int_salary(raw: str) -> int | None:
    s = raw.replace("$", "").replace(",", "").strip()
    if not re.fullmatch(r"\d{1,7}", s):
        return None
    return int(s)


def _float_or_none(raw: str | None) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if s == "":
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


_DK_GAME_RE = re.compile(
    r"^(?P<away>[A-Za-z]{2,4})@(?P<home>[A-Za-z]{2,4})\s+(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<time>\d{1,2}:\d{2}[AP]M)\s+ET$"
)
_ET = ZoneInfo("America/New_York")


def _parse_dk_game(info: str) -> tuple[str | None, str | None]:
    """``"NYG@DAL 10/05/2026 01:00PM ET"`` → (``"NYG@DAL"``, UTC ISO start)."""
    info = (info or "").strip()
    m = _DK_GAME_RE.match(info)
    if not m:
        token = info.split(" ", 1)[0] if "@" in info.split(" ", 1)[0] else None
        return (token.upper() if token else None), None
    game = f"{m['away'].upper()}@{m['home'].upper()}"
    try:
        local = datetime.strptime(f"{m['date']} {m['time']}", "%m/%d/%Y %I:%M%p").replace(
            tzinfo=_ET
        )
        return game, local.astimezone(timezone.utc).isoformat()
    except ValueError:
        return game, None


def _opponent_from_game(game: str | None, team: str) -> str | None:
    if not game or "@" not in game:
        return None
    away, home = game.split("@", 1)
    if team == away:
        return home
    if team == home:
        return away
    return None


def parse_draftkings_salaries(text: str) -> tuple[list[SlateAthlete], ImportReport]:
    header, rows = _read_csv(text)
    _require(header, ["Position", "Name", "ID", "Salary", "TeamAbbrev"], "DraftKings salary")
    report = ImportReport(rows_read=len(rows))
    out: list[SlateAthlete] = []
    seen: set[str] = set()
    for i, r in enumerate(rows, start=2):
        pid = r.get("ID", "").strip()
        salary = _int_salary(r.get("Salary", ""))
        positions = [p.strip().upper() for p in r.get("Position", "").split("/") if p.strip()]
        team = normalize_team(r.get("TeamAbbrev"))
        if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z\-]{0,39}", pid):
            report.reject(i, "invalid_or_missing_player_id", r)
            continue
        if pid in seen:
            report.reject(i, "duplicate_player_id", r)
            continue
        if salary is None:
            report.reject(i, "invalid_salary", r)
            continue
        if not positions or not team or not r.get("Name", "").strip():
            report.reject(i, "missing_name_position_or_team", r)
            continue
        game, start = _parse_dk_game(r.get("Game Info", ""))
        avg = _float_or_none(r.get("AvgPointsPerGame"))
        seen.add(pid)
        out.append(
            SlateAthlete(
                player_id=pid,
                name=r["Name"].strip(),
                positions=positions,
                team=team,
                opponent=_opponent_from_game(game, team),
                game=game,
                salary=salary,
                start_time_utc=start,
                # DK publishes no games-played count, so an average of exactly
                # 0 cannot be told apart from "has not played": treat as missing.
                platform_average=avg if avg not in (None, 0.0) else None,
                eligible_slots=_slots(r.get("Roster Position")),
                extra=_extra(r, DK_COLUMNS),
            )
        )
    report.rows_used = len(out)
    return out, report


def parse_fanduel_players(text: str) -> tuple[list[SlateAthlete], ImportReport]:
    header, rows = _read_csv(text)
    _require(header, ["Id", "Position", "Salary", "Team", "Opponent"], "FanDuel player list")
    if "Nickname" not in header and not {"First Name", "Last Name"} <= set(header):
        raise ImportError_(
            "HEADER_MISMATCH",
            "This does not look like a FanDuel player list: need Nickname or First Name + Last Name.",
            {"found": header[:40]},
        )
    report = ImportReport(rows_read=len(rows))
    out: list[SlateAthlete] = []
    seen: set[str] = set()
    for i, r in enumerate(rows, start=2):
        pid = r.get("Id", "").strip()
        salary = _int_salary(r.get("Salary", ""))
        positions = [p.strip().upper() for p in r.get("Position", "").split("/") if p.strip()]
        team = normalize_team(r.get("Team"))
        opp = normalize_team(r.get("Opponent")) or None
        name = (
            r.get("Nickname", "").strip()
            or f"{r.get('First Name', '').strip()} {r.get('Last Name', '').strip()}".strip()
        )
        if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z\-]{0,39}", pid):
            report.reject(i, "invalid_or_missing_player_id", r)
            continue
        if pid in seen:
            report.reject(i, "duplicate_player_id", r)
            continue
        if salary is None:
            report.reject(i, "invalid_salary", r)
            continue
        if not positions or not team or not name:
            report.reject(i, "missing_name_position_or_team", r)
            continue
        game = (r.get("Game") or "").strip().upper() or None
        if game is None and opp:
            game = "@".join(sorted([team, opp]))
        played = _float_or_none(r.get("Played"))
        avg = _float_or_none(r.get("FPPG"))
        seen.add(pid)
        out.append(
            SlateAthlete(
                player_id=pid,
                name=name,
                positions=positions,
                team=team,
                opponent=opp,
                game=game,
                salary=salary,
                status=(r.get("Injury Indicator") or "").strip() or None,
                platform_average=avg if (avg is not None and (played or 0) > 0) else None,
                eligible_slots=_slots(r.get("Roster Position")),
                extra=_extra(r, FD_COLUMNS),
            )
        )
    report.rows_used = len(out)
    return out, report


DK_COLUMNS = frozenset(
    [
        "Position",
        "Name + ID",
        "Name",
        "ID",
        "Roster Position",
        "Salary",
        "Game Info",
        "TeamAbbrev",
        "AvgPointsPerGame",
    ]
)
FD_COLUMNS = frozenset(
    [
        "Id",
        "Position",
        "First Name",
        "Nickname",
        "Last Name",
        "FPPG",
        "Played",
        "Salary",
        "Game",
        "Team",
        "Opponent",
        "Injury Indicator",
        "Injury Details",
        "Tier",
        "Roster Position",
    ]
)


def _slots(raw: str | None) -> list[str]:
    return [s.strip().upper() for s in (raw or "").split("/") if s.strip()]


def _extra(row: dict[str, str], known: frozenset[str]) -> dict[str, str]:
    return {k[:60]: v[:200] for k, v in row.items() if k not in known and k and v}


SALARY_PARSERS = {
    "draftkings_salary_csv_v1": parse_draftkings_salaries,
    "fanduel_player_list_csv_v1": parse_fanduel_players,
}

_PROJ_COLUMNS = ("projection", "proj", "fpts", "points", "projected points")
_ID_COLUMNS = ("id", "player id", "playerid", "dfs id")


def _col(header: list[str], candidates: tuple[str, ...]) -> str | None:
    lower = {h.lower().strip(): h for h in header}
    for c in candidates:
        if c in lower:
            return lower[c]
    return None


def apply_projection_csv(athletes: list[SlateAthlete], text: str) -> dict[str, Any]:
    """Join an owner projection CSV onto ``athletes`` in place; return the identity report."""
    header, rows = _read_csv(text)
    proj_col = _col(header, _PROJ_COLUMNS)
    id_col = _col(header, _ID_COLUMNS)
    name_col = _col(header, ("name", "player", "player name"))
    team_col = _col(header, ("team", "teamabbrev", "tm"))
    pos_col = _col(header, ("position", "pos"))
    if proj_col is None:
        raise ImportError_(
            "HEADER_MISMATCH",
            "Projection file needs a projection column (one of: projection, proj, fpts, points).",
            {"found": header[:40]},
        )
    if id_col is None and not (name_col and team_col):
        raise ImportError_(
            "HEADER_MISMATCH",
            "Projection file needs a platform player ID column, or Name + Team columns.",
            {"found": header[:40]},
        )
    by_id = {a.player_id: a for a in athletes}
    by_name_team: dict[tuple[str, str], list[SlateAthlete]] = {}
    for a in athletes:
        by_name_team.setdefault((normalize_player_name(a.name), a.team), []).append(a)

    matched: dict[str, tuple[float, str]] = {}
    unmatched: list[dict[str, Any]] = []
    ambiguous: list[dict[str, Any]] = []
    invalid: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    for i, r in enumerate(rows, start=2):
        value = _float_or_none(r.get(proj_col))
        label = r.get(name_col, "") if name_col else r.get(id_col or "", "")
        if value is None:
            invalid.append(
                {"row": i, "name": label[:80], "reason": "projection_not_numeric_or_blank"}
            )
            continue
        target: SlateAthlete | None = None
        method = None
        if id_col and r.get(id_col, "").strip():
            # A supplied platform ID is authoritative: an ID that is not on
            # this slate is unmatched (never re-tried by name, which could
            # attach it to someone else), and an ID whose name column names
            # a different player is quarantined rather than trusted.
            target = by_id.get(r[id_col].strip())
            if target is None:
                unmatched.append(
                    {"row": i, "name": label[:80], "reason": "platform_id_not_on_slate"}
                )
                continue
            if name_col and r.get(name_col, "").strip():
                if normalize_player_name(r[name_col]) != normalize_player_name(target.name):
                    conflicts.append(
                        {"row": i, "playerId": target.player_id, "reason": "id_name_mismatch"}
                    )
                    continue
            method = "platform_id"
        if target is None and name_col and team_col:
            cands = by_name_team.get(
                (normalize_player_name(r.get(name_col)), normalize_team(r.get(team_col))), []
            )
            if pos_col and r.get(pos_col, "").strip():
                pos = r[pos_col].strip().upper()
                cands = [c for c in cands if pos in c.positions]
            if len(cands) == 1:
                target, method = cands[0], "name_team"
            elif len(cands) > 1:
                ambiguous.append(
                    {
                        "row": i,
                        "name": label[:80],
                        "candidates": [c.player_id for c in cands],
                        "reason": "ambiguous_identity",
                    }
                )
                continue
        if target is None:
            unmatched.append({"row": i, "name": label[:80], "reason": "no_slate_athlete"})
            continue
        prior = matched.get(target.player_id)
        if prior is not None and prior[0] != value:
            conflicts.append(
                {"row": i, "playerId": target.player_id, "reason": "two_rows_disagree"}
            )
            continue
        matched[target.player_id] = (value, method or "")

    # Two disagreeing rows for one athlete → that athlete is unresolved, never first-wins.
    for c in conflicts:
        matched.pop(c["playerId"], None)
    for a in athletes:
        hit = matched.get(a.player_id)
        if hit is not None:
            a.projection, a.projection_match = hit
            a.projection_source = "owner_import"
    return {
        "rowsRead": len(rows),
        "matched": len(matched),
        "unmatched": unmatched[:200],
        "ambiguous": ambiguous[:200],
        "invalid": invalid[:200],
        "conflicts": conflicts[:200],
        "athletesWithoutProjection": sum(1 for a in athletes if a.projection is None),
    }


def apply_platform_average(athletes: list[SlateAthlete]) -> int:
    """Owner-selected fallback: use the platform's season average where no projection exists."""
    n = 0
    for a in athletes:
        if a.projection is None and a.platform_average is not None:
            a.projection = a.platform_average
            a.projection_source = "platform_season_average"
            a.projection_match = "platform_id"
            n += 1
    return n


def content_hash(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
