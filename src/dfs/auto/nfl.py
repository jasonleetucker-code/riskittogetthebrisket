"""NFL automated slates (DFS-AUTO-02/03/05/06/09/10): DraftKings + FanDuel, no uploads.

Pure functions — every input is injected, so a captured page / schedule /
projection batch replays deterministically.  ``refresh.py`` does the I/O.

Inputs, and what each one is trusted for:

* **Daily Fantasy Fuel** platform pages (owner-authorised, seed A-020) — the
  week's player POOL and each player's platform SALARY and position, plus DFF's
  own projection (one projection family) and its injury flag.  The page states
  when it was last updated; that stamp, not our fetch time, is its as-of.
* **nflverse schedule** (the Calculator's one schedule owner,
  ``src/nfl_data/ingest.fetch_schedules``) — games, kickoff times (published in
  US Eastern), and therefore each slate's LOCK.
* **Sleeper weekly projections** (RotoWire model, the Calculator's existing
  lane) — raw projected STAT LINES, rescored under the platform's scoring card
  (``scoring_cards.py``) by the Calculator's exact scorer.  A second, separately
  sourced projection family; website fantasy totals are never averaged across
  scoring systems.
* **Sleeper player directory** — identity (``resolve_canonical_v2``, the
  canonical owner; ambiguity is refused, never first-wins) and injury status.

Slates are DERIVED from the schedule — Main (Sunday 1:00–4:25 pm ET), Early,
Afternoon, Primetime (night games), Full week — and every one is labelled
``derived_from_schedule`` / unverified: the platforms' own slate lists are not
available from a permitted source, so a derived slate is the conventional game
set, not a confirmed platform slate.  Salaries are the platform's week-pool
salaries (the same classic salary across that week's classic slates — also
labelled as an assumption).  DraftKings and FanDuel slates are separate objects
with separate salaries, positions, scoring and rule sets; nothing is shared but
the schedule.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from src.dfs.auto import AUTO_ID_PREFIX
from src.dfs.imports import SlateAthlete, content_hash
from src.dfs.rules import get_ruleset
from src.dfs.slate import CanonicalSlate, SlateEvent

ET = ZoneInfo("America/New_York")
SPORT = "nfl"
PLATFORMS = ("draftkings", "fanduel")
RULESETS = {"draftkings": "draftkings.nfl.classic", "fanduel": "fanduel.nfl.classic"}
#: The platforms' team-defense position labels (the rule sets' own vocabulary).
DST_POSITION = {"draftkings": "DST", "fanduel": "D"}
#: nflverse abbreviations that differ from the DFS platforms'.
NFLVERSE_TO_DFS_TEAM = {"LA": "LAR"}
#: Sleeper injury statuses under which a player is not projected at all.  The
#: projection is WITHHELD (so the optimizer cannot select him), never set to 0.
WITHHELD_STATUSES = frozenset({"Out", "IR", "PUP", "Suspended", "NA", "COV", "DNR"})
#: Two families disagreeing by more than this (relative to their mean) is flagged.
DISAGREEMENT_FLAG = 0.30
_SAFE_SOURCE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\-]{0,30}$")

DERIVATION = "derived_from_schedule"
DERIVATION_NOTE = (
    "Game set derived from the NFL schedule using the platforms' conventional slate "
    "windows. Not confirmed against the platform's own slate list."
)


@dataclass(frozen=True)
class Game:
    event_id: str  # "AWAY@HOME" in DFS team codes
    away: str
    home: str
    kickoff_utc: str
    kickoff_et: datetime
    week: int
    season: int
    spread_line: float | None
    total_line: float | None
    source_game_id: str


@dataclass(frozen=True)
class SlateDef:
    key: str
    name: str
    games: tuple[Game, ...]

    @property
    def lock_utc(self) -> str:
        return min(g.kickoff_utc for g in self.games)


@dataclass
class PoolReport:
    rows_read: int = 0
    used: int = 0
    rejected: list[dict[str, Any]] = field(default_factory=list)
    identity: dict[str, int] = field(default_factory=dict)
    quarantined_identity: list[dict[str, Any]] = field(default_factory=list)
    families: dict[str, int] = field(default_factory=dict)
    withheld_for_status: list[str] = field(default_factory=list)
    disagreements: int = 0

    def reject(self, row: Mapping[str, Any], reason: str) -> None:
        if len(self.rejected) < 200:
            self.rejected.append(
                {"name": str(row.get("name") or "")[:60], "team": row.get("team"), "reason": reason}
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "rowsRead": self.rows_read,
            "rowsUsed": self.used,
            "rejected": self.rejected,
            "identity": dict(sorted(self.identity.items())),
            "quarantinedIdentity": self.quarantined_identity[:50],
            "projectionFamilies": dict(sorted(self.families.items())),
            "withheldForStatus": self.withheld_for_status[:50],
            "familyDisagreements": self.disagreements,
        }


# ── schedule ─────────────────────────────────────────────────────────────


def _team(code: Any) -> str:
    c = str(code or "").strip().upper()
    return NFLVERSE_TO_DFS_TEAM.get(c, c)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is missing


def games_from_schedule(rows: list[Mapping[str, Any]], season: int) -> list[Game]:
    """Schedule rows → games with UTC kickoffs.  A row without a parseable date
    AND time is dropped (no guessed kickoff, so no guessed lock)."""
    out = []
    for r in rows:
        try:
            if int(float(r.get("season"))) != season:
                continue
            week = int(float(r.get("week")))
            local = datetime.strptime(f"{r.get('gameday')} {r.get('gametime')}", "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            continue
        if str(r.get("game_type") or "REG").upper() not in ("REG", "WC", "DIV", "CON", "SB"):
            continue
        away, home = _team(r.get("away_team")), _team(r.get("home_team"))
        if not away or not home:
            continue
        et = local.replace(tzinfo=ET)
        out.append(
            Game(
                event_id=f"{away}@{home}",
                away=away,
                home=home,
                kickoff_utc=et.astimezone(timezone.utc).isoformat(),
                kickoff_et=et,
                week=week,
                season=season,
                spread_line=_num(r.get("spread_line")),
                total_line=_num(r.get("total_line")),
                source_game_id=str(r.get("game_id") or ""),
            )
        )
    return sorted(out, key=lambda g: (g.kickoff_utc, g.event_id))


def current_week(games: list[Game], now: datetime) -> int | None:
    """The week of the next game not yet finished (a game is treated as live for
    4 h after kickoff).  None when the season has no games left."""
    cutoff = now - timedelta(hours=4)
    upcoming = [g for g in games if datetime.fromisoformat(g.kickoff_utc) >= cutoff]
    return min(upcoming, key=lambda g: g.kickoff_utc).week if upcoming else None


def derive_slates(week_games: list[Game]) -> list[SlateDef]:
    """The conventional classic slates for one week's games.  A window with fewer
    than two games is not a slate; a window identical to a bigger one is dropped."""

    def minutes(g: Game) -> int:
        return g.kickoff_et.hour * 60 + g.kickoff_et.minute

    sunday = [g for g in week_games if g.kickoff_et.weekday() == 6]
    windows = [
        ("main", "Main", [g for g in sunday if 13 * 60 <= minutes(g) < 17 * 60]),
        ("early", "Early", [g for g in sunday if 13 * 60 <= minutes(g) < 14 * 60]),
        ("afternoon", "Afternoon", [g for g in sunday if 16 * 60 <= minutes(g) < 17 * 60]),
        ("primetime", "Primetime", [g for g in week_games if minutes(g) >= 19 * 60]),
        ("full_week", "Full week", list(week_games)),
    ]
    seen: set[frozenset[str]] = set()
    out = []
    for key, name, games in windows:
        ids = frozenset(g.event_id for g in games)
        if len(games) < 2 or ids in seen:
            continue
        seen.add(ids)
        out.append(SlateDef(key, name, tuple(sorted(games, key=lambda g: g.kickoff_utc))))
    return out


# ── the player pool ──────────────────────────────────────────────────────


def ensemble(values: list[float]) -> float | None:
    """Independent projection families → one number.  n=1 passthrough, n=2 mean,
    n≥3 median — the count-aware ladder the Calculator's blend uses at small n."""
    if not values:
        return None
    if len(values) <= 2:
        return round(sum(values) / len(values), 2)
    return round(float(median(values)), 2)


def _resolve(
    row: Mapping[str, Any], dst: bool, index: Any, report: PoolReport
) -> tuple[str | None, str]:
    """Sleeper id (or None) + the identity state, through the canonical owner."""
    if dst:
        report.identity["team_defense"] = report.identity.get("team_defense", 0) + 1
        return _team(row["team"]), "team_defense"
    if index is None:
        report.identity["directory_unavailable"] = (
            report.identity.get("directory_unavailable", 0) + 1
        )
        return None, "directory_unavailable"
    from src.identity.resolution import resolve_canonical_v2

    res = resolve_canonical_v2(
        index, name=row["name"], position=row["position"] or None, team=row["team"]
    )
    if res.status == "resolved" and res.sleeper_id and not res.tie_detected:
        report.identity["resolved"] = report.identity.get("resolved", 0) + 1
        return str(res.sleeper_id), f"resolved:{res.method}"
    state = "ambiguous" if res.tie_detected or len(res.candidate_ids) > 1 else "unresolved"
    report.identity[state] = report.identity.get(state, 0) + 1
    report.quarantined_identity.append(
        {
            "name": str(row["name"])[:60],
            "team": row["team"],
            "state": state,
            "reason": res.reason,
            "candidates": list(res.candidate_ids)[:5],
        }
    )
    return None, state


def build_pool(
    platform: str,
    dff_rows: list[Mapping[str, Any]],
    week_games: list[Game],
    *,
    sleeper_points: Mapping[str, Mapping[str, Any]] | None = None,
    directory: Mapping[str, Mapping[str, Any]] | None = None,
    directory_index: Any = None,
) -> tuple[list[SlateAthlete], PoolReport]:
    """One platform's week pool.  ``sleeper_points`` maps a Sleeper id to
    ``{"points", "team", "uncovered"}`` already scored under THIS platform's card."""
    by_team: dict[str, Game] = {}
    for g in week_games:
        by_team[g.away] = g
        by_team[g.home] = g
    report = PoolReport(rows_read=len(dff_rows))
    athletes: list[SlateAthlete] = []
    seen: set[str] = set()
    for row in dff_rows:
        team = _team(row.get("team"))
        game = by_team.get(team)
        sid_raw = str(row.get("sourcePlayerId") or "")
        dst = str(row.get("position") or "").upper() in ("DST", "D", "DEF")
        if not _SAFE_SOURCE_ID.match(sid_raw):
            report.reject(row, "missing_source_player_id")
            continue
        pid = AUTO_ID_PREFIX + sid_raw
        if pid in seen:
            report.reject(row, "duplicate_source_player_id")
            continue
        if not isinstance(row.get("salary"), int) or row["salary"] <= 0:
            report.reject(row, "missing_salary")  # never priced at zero
            continue
        if game is None:
            report.reject(row, "team_not_on_this_weeks_schedule")
            continue
        opponent = game.home if team == game.away else game.away
        if row.get("opponent") and _team(row["opponent"]) != opponent:
            report.reject(row, "opponent_disagrees_with_schedule")
            continue
        position = DST_POSITION[platform] if dst else str(row["position"]).upper()
        seen.add(pid)
        sleeper_id, identity_state = _resolve(row, dst, directory_index, report)
        meta = (directory or {}).get(sleeper_id or "", {}) if sleeper_id else {}
        sleeper_status = (meta.get("injury_status") or None) if isinstance(meta, Mapping) else None

        families: dict[str, float] = {}
        if row.get("projection") is not None:
            families["dailyfantasyfuel"] = float(row["projection"])
        uncovered: list[str] = []
        sp = (sleeper_points or {}).get(sleeper_id or "")
        zero_line = False
        if sp is not None and _team(sp.get("team")) in ("", team):
            if float(sp["points"]) > 0:
                families["sleeper_rotowire"] = float(sp["points"])
                uncovered = list(sp.get("uncovered") or [])
            else:
                # An all-zero stat line is the provider not projecting him, not a
                # forecast of zero: it is excluded, never averaged in as 0.
                zero_line = True
                report.families["sleeper_rotowire_zero_line_excluded"] = (
                    report.families.get("sleeper_rotowire_zero_line_excluded", 0) + 1
                )
        for fam in list(families):
            report.families[fam] = report.families.get(fam, 0) + 1
        value = ensemble(list(families.values()))
        disagreement = None
        if len(families) >= 2:
            vals = list(families.values())
            mean = sum(vals) / len(vals)
            disagreement = round((max(vals) - min(vals)) / mean, 3) if mean > 0 else None
            if disagreement is not None and disagreement > DISAGREEMENT_FLAG:
                report.disagreements += 1
        source = "auto_ensemble:" + "+".join(sorted(families)) if families else None
        if sleeper_status in WITHHELD_STATUSES:
            report.withheld_for_status.append(f"{row['name']} ({sleeper_status})")
            value, source = None, f"withheld:status_{sleeper_status}"
        extra = {
            "sourcePlayerId": sid_raw,
            "identity": identity_state,
            "projectionFamilies": ";".join(f"{k}={v:g}" for k, v in sorted(families.items())),
        }
        if sleeper_id:
            extra["sleeperId"] = sleeper_id
        if sleeper_status:
            extra["sleeperInjuryStatus"] = str(sleeper_status)
        if row.get("injury"):
            extra["dffInjury"] = str(row["injury"])
        if disagreement is not None:
            extra["familyDisagreement"] = f"{disagreement:g}"
        if uncovered:
            extra["uncoveredScoringKeys"] = ",".join(uncovered)
        if zero_line:
            extra["excludedFamily"] = "sleeper_rotowire:zero_line"
        for k in ("spread", "overUnder", "impliedTeamTotal"):
            if row.get(k) is not None:
                extra[f"dff_{k}"] = f"{row[k]:g}"
        athletes.append(
            SlateAthlete(
                player_id=pid,
                name=str(row["name"]),
                positions=[position],
                team=team,
                opponent=opponent,
                game=game.event_id,
                salary=int(row["salary"]),
                start_time_utc=game.kickoff_utc,
                status=sleeper_status or row.get("injury") or None,
                projection=value,
                projection_source=source,
                projection_match="auto" if families else None,
                extra=extra,
            )
        )
        report.used += 1
    return athletes, report


# ── slate snapshots ──────────────────────────────────────────────────────


def slate_body(
    platform: str,
    slate: SlateDef,
    pool: list[SlateAthlete],
    report: PoolReport,
    sources: dict[str, Any],
) -> dict[str, Any] | None:
    """One derived slate → the same immutable snapshot body a file import makes.

    None when the slate has no priced players (a platform page that has not yet
    listed that window's games yields no slate, never an empty one)."""
    rs = get_ruleset(RULESETS[platform])
    game_ids = {g.event_id for g in slate.games}
    athletes = [a for a in pool if a.game in game_ids]
    if rs is None or not athletes:
        return None
    week = slate.games[0].week
    season = slate.games[0].season
    label = (
        f"{'DraftKings' if platform == 'draftkings' else 'FanDuel'} NFL {slate.name} · Week {week}"
    )
    canonical = CanonicalSlate(
        sport=SPORT,
        platform=platform,
        format="classic",
        athletes=athletes,
        events=[
            SlateEvent(
                event_id=g.event_id,
                participants=[g.away, g.home],
                start_time_utc=g.kickoff_utc,
                status="scheduled",
                source_ids={"nflverseGameId": g.source_game_id},
            )
            for g in slate.games
        ],
        name=label,
        slate_date=slate.games[0].kickoff_et.date().isoformat(),
        start_time_utc=slate.lock_utc,
        external_ids={"autoSlateKey": f"{platform}:nfl:{season}:w{week}:{slate.key}"},
        source_salary_cap=None,
        provenance={
            "sourceKind": "auto_derived",
            "adapter": "dfs.auto.nfl",
            "slateDerivation": DERIVATION,
            "slateDerivationNote": DERIVATION_NOTE,
            "salaryScope": "week_pool_assumed_identical_across_classic_slates",
            "platformIds": "unavailable",
            "sources": sources,
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
        "projectionReport": {
            "source": "auto_ensemble",
            "matched": projected,
            "unmatched": len(athletes) - projected,
            "note": "Automatic: independent projection families, rescored per platform where "
            "built from stat lines. Players without a projection are left out, never scored 0.",
        },
        "ownershipReport": None,
        "platformAverageApplied": 0,
        "positionsNotInRuleset": sorted({p for a in athletes for p in a.positions} - rs.positions),
        "auto": {
            "slateKey": slate.key,
            "slateName": slate.name,
            "week": week,
            "season": season,
            "lockAt": slate.lock_utc,
            "games": [
                {
                    "eventId": g.event_id,
                    "kickoff": g.kickoff_utc,
                    "spreadLine": g.spread_line,
                    "totalLine": g.total_line,
                }
                for g in slate.games
            ],
            "poolReport": report.to_dict(),
            "derivation": DERIVATION,
            "platformIds": "unavailable",
        },
    }


def body_hash(body: dict[str, Any]) -> str:
    return content_hash({"ruleset": body["ruleset"], "athletes": body["athletes"]})
