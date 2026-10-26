"""NBA / NHL automated slates (DFS-AUTO-19): DraftKings + FanDuel, no uploads.

Pure functions — every input is injected, so a captured page / scoreboard
replays deterministically.  ``refresh.refresh_daily`` does the I/O.

Inputs, and what each one is trusted for:

* **Daily Fantasy Fuel** platform pages (owner-authorised seed A-020; robots.txt
  disallows only ``/lineup/*``) — the slate's player POOL, each player's
  platform SALARY and position(s), DFF's own projection (the ONE projection
  family available for these sports today), its injury flag, and on NHL pages
  DFF's projected even-strength / power-play line and starter flag.  The page
  states when it was last updated; that stamp, not our fetch time, is its as-of.
* **ESPN scoreboard** (``league_schedule``) — games, start times and therefore
  each slate's LOCK, plus the cross-check that a listed team is actually
  playing that opponent that day.

The slate is THE ONE DFF's page lists for that platform (NFL derives several
windows from a week; a daily sport's page lists a single dated slate).  Its game
set is DFF's, timed by the schedule, and labelled ``dff_listed_slate`` /
unverified: the platforms' own slate lists have no permitted source.  A listed
game the schedule does not show (preseason, postponed, a wrong team code) is
refused with a reason, never timed by a guess.  A slate with fewer than two
games is not a CLASSIC slate (single-game formats are separate rule sets) and is
not built.

Identity is sport-scoped (DFS-§9-03): every athlete carries
``athlete:<sport>:dailyfantasyfuel:<id>`` and a synthetic ``auto-<sport>-<id>``
player id.  No permitted NBA/NHL player directory is wired, so these athletes
are PROVIDER-SCOPED, and the slate says so; nothing is resolved against the NFL
directory.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Mapping

from src.dfs.auto import auto_player_id
from src.dfs.auto.common import SAFE_SOURCE_ID, PoolReport, ensemble, projection_report
from src.dfs.auto.league_schedule import ET, ScheduledGame
from src.dfs.imports import SlateAthlete
from src.dfs.rules import get_ruleset
from src.dfs.slate import CanonicalSlate, SlateEvent
from src.identity.athletes import PROVIDER_SCOPED_REASON, athlete_key, canonical_team

SPORTS = ("nba", "nhl")
PLATFORMS = ("draftkings", "fanduel")
SOURCE = "dailyfantasyfuel"
SLATE_KEY = "listed"
#: DFF injury flags under which a player is not projected at all.  WITHHELD (so
#: the optimizer cannot select him), never projected as 0.  Questionable /
#: day-to-day / game-time designations stay projected and are shown.
WITHHELD_FLAGS = frozenset({"O", "OUT", "IR", "IR-LT", "IR-NR", "LTIR", "SUSP", "SUS", "NA"})
MAX_DATES = 3
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SPLIT = re.compile(r"[/,\s]+")

DERIVATION = "dff_listed_slate"
SPORT_LABEL = {"nba": "NBA", "nhl": "NHL"}
PLATFORM_LABEL = {"draftkings": "DraftKings", "fanduel": "FanDuel"}


def derivation_note(sport: str) -> str:
    return (
        f"Game set is the {SPORT_LABEL.get(sport, sport.upper())} slate Daily Fantasy Fuel lists "
        "for each platform, timed from the league schedule (ESPN scoreboard). Not confirmed "
        "against the platform's own slate list."
    )


def ruleset_for(platform: str, sport: str) -> str:
    return f"{platform}.{sport}.classic"


def season_for(day: str) -> int:
    """The season a date belongs to, by its START year (Oct–Jun seasons)."""
    y, m = int(day[:4]), int(day[5:7])
    return y if m >= 8 else y - 1


def slate_dates(rows: list[Mapping[str, Any]]) -> list[str]:
    """The distinct, well-formed start dates a page lists (bounded)."""
    days = sorted(
        {str(r.get("startDate")) for r in rows if _DAY.match(str(r.get("startDate") or ""))}
    )
    return days[:MAX_DATES]


def _positions(row: Mapping[str, Any]) -> list[str]:
    out: list[str] = []
    for raw in (row.get("position"), row.get("positionAlt")):
        for p in _SPLIT.split(str(raw or "").upper()):
            if p and p not in out:
                out.append(p)
    return out


def build_pool(
    sport: str,
    platform: str,
    dff_rows: list[Mapping[str, Any]],
    games: list[ScheduledGame],
) -> tuple[list[SlateAthlete], PoolReport]:
    """One platform's listed pool, every athlete timed by a scheduled game."""
    by_day_team: dict[tuple[str, str], ScheduledGame] = {}
    for g in games:
        by_day_team[(g.date_et, g.away)] = g
        by_day_team[(g.date_et, g.home)] = g
    report = PoolReport(rows_read=len(dff_rows))
    athletes: list[SlateAthlete] = []
    seen: set[str] = set()
    unconfirmed_goalies = 0
    for row in dff_rows:
        sid_raw = str(row.get("sourcePlayerId") or "")
        if not SAFE_SOURCE_ID.match(sid_raw):
            report.reject(row, "missing_source_player_id")
            continue
        pid = auto_player_id(sport, sid_raw)
        if pid in seen:
            report.reject(row, "duplicate_source_player_id")
            continue
        if not isinstance(row.get("salary"), int) or row["salary"] <= 0:
            report.reject(row, "missing_salary")  # never priced at zero
            continue
        team = canonical_team(sport, row.get("team"))
        if team is None:
            report.reject(row, "team_unknown_for_sport")
            continue
        day = str(row.get("startDate") or "")
        if not _DAY.match(day):
            report.reject(row, "missing_start_date")
            continue
        game = by_day_team.get((day, team))
        if game is None:
            report.reject(row, "game_not_on_schedule")
            continue
        opponent = game.home if team == game.away else game.away
        if row.get("opponent") and canonical_team(sport, row["opponent"]) != opponent:
            report.reject(row, "opponent_disagrees_with_schedule")
            continue
        side = "away" if team == game.away else "home"
        if row.get("homeAway") and row["homeAway"] != side:
            report.reject(row, "home_away_disagrees_with_schedule")
            continue
        positions = _positions(row)
        if not positions:
            report.reject(row, "missing_position")
            continue
        seen.add(pid)
        report.identity["provider_scoped"] = report.identity.get("provider_scoped", 0) + 1

        families: dict[str, float] = {}
        zero = False
        proj = row.get("projection")
        if proj is not None:
            if float(proj) > 0:
                families[SOURCE] = float(proj)
            else:
                # A 0.0 line is the source not projecting him (no expected
                # minutes / not dressing), not a forecast of zero: excluded.
                zero = True
                report.families[f"{SOURCE}_zero_line_excluded"] = (
                    report.families.get(f"{SOURCE}_zero_line_excluded", 0) + 1
                )
        for fam in families:
            report.families[fam] = report.families.get(fam, 0) + 1
        value = ensemble(list(families.values()))
        source = "auto_ensemble:" + "+".join(sorted(families)) if families else None
        flag = str(row.get("injury") or "").strip().upper()
        if flag in WITHHELD_FLAGS:
            report.withheld_for_status.append(f"{row.get('name')} ({flag})")
            value, source = None, f"withheld:status_{flag}"

        extra = {
            "sourcePlayerId": sid_raw,
            "athleteKey": athlete_key(sport, SOURCE, sid_raw),
            "identity": "provider_scoped",
            "identityReason": PROVIDER_SCOPED_REASON[sport],
            "projectionFamilies": ";".join(f"{k}={v:g}" for k, v in sorted(families.items())),
        }
        if row.get("injury"):
            extra["dffInjury"] = str(row["injury"])
        if zero:
            extra["excludedFamily"] = f"{SOURCE}:zero_line"
        for k in ("spread", "overUnder", "impliedTeamTotal"):
            if row.get(k) is not None:
                extra[f"dff_{k}"] = f"{row[k]:g}"
        if sport == "nhl":
            # DFF's PROJECTED lines — evidence carried with the athlete, not yet a
            # constraint or a correlation input (see ADR-DFS-025).
            if row.get("regLine") is not None:
                extra["dffRegLine"] = str(row["regLine"])
            if row.get("ppLine") is not None:
                extra["dffPpLine"] = str(row["ppLine"])
            if row.get("starterFlag") is not None:
                extra["dffStarterFlag"] = str(row["starterFlag"])
            if "G" in positions and str(row.get("starterFlag") or "") != "1":
                unconfirmed_goalies += 1
        athletes.append(
            SlateAthlete(
                player_id=pid,
                name=str(row.get("name") or ""),
                positions=positions,
                team=team,
                opponent=opponent,
                game=game.event_id,
                salary=int(row["salary"]),
                start_time_utc=game.start_utc,
                status=str(row["injury"]) if row.get("injury") else None,
                projection=value,
                projection_source=source,
                projection_match="auto" if families else None,
                extra=extra,
            )
        )
        report.used += 1
    if unconfirmed_goalies:
        report.notes.append(
            f"{unconfirmed_goalies} goalie(s) not marked as confirmed starters by the source: a "
            "goalie who does not start scores nothing. Confirm your goalie before lock."
        )
    return athletes, report


def slates(
    pool: list[SlateAthlete], games: list[ScheduledGame]
) -> list[tuple[str, list[ScheduledGame]]]:
    """(date, games) per listed day with at least two priced games — classic slates only."""
    used = {a.game for a in pool}
    by_day: dict[str, list[ScheduledGame]] = {}
    for g in games:
        if g.event_id in used:
            by_day.setdefault(g.date_et, []).append(g)
    return [
        (d, sorted(gs, key=lambda g: (g.start_utc, g.event_id)))
        for d, gs in sorted(by_day.items())
        if len(gs) >= 2
    ]


def slate_body(
    sport: str,
    platform: str,
    day: str,
    slate_games: list[ScheduledGame],
    pool: list[SlateAthlete],
    report: PoolReport,
    sources: dict[str, Any],
    schedule_games_that_day: int,
) -> dict[str, Any] | None:
    """One listed slate → the same immutable snapshot body a file import makes."""
    rs = get_ruleset(ruleset_for(platform, sport))
    ids = {g.event_id for g in slate_games}
    athletes = [a for a in pool if a.game in ids]
    if rs is None or not athletes or len(ids) < 2:
        return None
    lock = min(g.start_utc for g in slate_games)
    when = datetime.fromisoformat(lock).astimezone(ET)
    label = (
        f"{PLATFORM_LABEL[platform]} {SPORT_LABEL[sport]} · {when:%a %b} {when.day} · "
        f"{len(slate_games)} games"
    )
    season = season_for(day)
    yyyymmdd = int(day.replace("-", ""))
    canonical = CanonicalSlate(
        sport=sport,
        platform=platform,
        format="classic",
        athletes=athletes,
        events=[
            SlateEvent(
                event_id=g.event_id,
                participants=[g.away, g.home],
                start_time_utc=g.start_utc,
                status="scheduled",
                source_ids={"espnEventId": g.source_game_id},
            )
            for g in slate_games
        ],
        name=label,
        slate_date=day,
        start_time_utc=lock,
        external_ids={"autoSlateKey": f"{platform}:{sport}:{season}:d{yyyymmdd}:{SLATE_KEY}"},
        source_salary_cap=None,
        provenance={
            "sourceKind": "auto_derived",
            "adapter": "dfs.auto.daily",
            "slateDerivation": DERIVATION,
            "slateDerivationNote": derivation_note(sport),
            "salaryScope": "salaries_as_listed_for_this_slate",
            "platformIds": "unavailable",
            "identityScope": "provider_scoped",
            "sources": sources,
            "notes": list(report.notes),
            "importedAt": sources.get("builtAt"),
        },
    )
    projected = sum(1 for a in athletes if a.projection is not None)
    return {
        "ruleset": rs.key,
        "label": label,
        "slate": canonical.header(),
        "athletes": [a.to_dict() for a in athletes],
        "importReport": None,
        "providerReport": None,
        "eligibilityCrossCheck": {
            "checked": 0,
            "mismatched": 0,
            "examples": [],
            "state": "no_platform_slots",
        },
        "salaryCapCrossCheck": None,
        "projectionReport": projection_report(
            report,
            athletes,
            projected,
            "Automatic: one projection family (Daily Fantasy Fuel) — no second permitted "
            f"{SPORT_LABEL[sport]} projection source is connected. Players without a projection "
            "are left out, never scored 0. Identity is provider-scoped (no NBA/NHL directory).",
        ),
        "ownershipReport": None,
        "platformAverageApplied": 0,
        "positionsNotInRuleset": sorted({p for a in athletes for p in a.positions} - rs.positions),
        "auto": {
            "sport": sport,
            "autoKey": f"{platform}:{sport}:{season}:d{yyyymmdd}:{SLATE_KEY}",
            "periodKey": yyyymmdd,
            "slateKey": SLATE_KEY,
            "slateName": "Listed slate",
            "slateDate": day,
            "season": season,
            "week": None,
            "lockAt": lock,
            "games": [
                {"eventId": g.event_id, "kickoff": g.start_utc, "status": g.status}
                for g in slate_games
            ],
            "scheduleGamesThatDay": schedule_games_that_day,
            "poolReport": report.to_dict(),
            "derivation": DERIVATION,
            "platformIds": "unavailable",
        },
    }
