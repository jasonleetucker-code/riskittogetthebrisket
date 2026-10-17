"""Player-week AVAILABILITY — one owner for "can this player score in week w?".

Owner master package 2026-10-17, Workstream A (P0).  Forward-looking
simulations drew every rostered player's points for every simulated week from
a full-season per-game mean, so a quarterback on injured reserve with an
expected return after the regular season still "entered the optimal lineup in
82% of simulated weeks".  This module answers the missing question; it never
touches a projection, a value or a lineup — consumers keep their own model and
drop the player-weeks this says cannot score.

States (MISSING IS NEVER ZERO, UNKNOWN IS NEVER AVAILABLE):

* ``available``   — no evidence of absence.
* ``unavailable`` — positive, dated evidence the player cannot score that
  week: a bye, an owner-recorded override, an out-type injury whose stated
  expected return is after that week's game, or a host-declared
  out/reserve designation for the CURRENT week.
* ``uncertain``   — evidence of risk without a decision: Questionable /
  Doubtful this week, a reserve list with no stated return, the first week
  after a stated return.
* ``unknown``     — the player has no host metadata at all.

Consumers that must place a player in a week or not (a lineup solve) drop
``unavailable`` only; ``uncertain`` and ``unknown`` stay in and are REPORTED,
so a simulated number never silently rests on a guess either way.

Rules, in precedence order (first match decides):

1. owner override (``config/availability/overrides.json``) — dated, sourced;
2. bye (nflverse schedule, the canonical schedule owner) — certain;
3. host reports the player ACTIVE (Sleeper ``injury_status`` empty) and no
   NEWER return report exists — a stale ESPN return date never benches an
   activated player, and a lagging host record never hides a fresh IR move;
4. ESPN structured return evidence for an out-type status
   (``src.nfl_data.injury_return_evidence``): weeks whose game is before the
   expected return are unavailable; the first week on/after it is uncertain;
5. host designation with no return evidence: Out / IR / PUP / NA / Sus / DNR
   make the CURRENT week unavailable and later reserve-list weeks uncertain;
   Questionable / Doubtful make the current week uncertain;
6. no host metadata: unknown.  Otherwise: available.

IR alone is never treated as season-ending; only a stated return date, an
override, or a week-specific designation removes a week.
"""

from __future__ import annotations

import json
import math
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

AVAILABLE = "available"
UNAVAILABLE = "unavailable"
UNCERTAIN = "uncertain"
UNKNOWN = "unknown"
STATES = (AVAILABLE, UNAVAILABLE, UNCERTAIN, UNKNOWN)

REPO_ROOT = Path(__file__).resolve().parents[2]
OVERRIDES_PATH = REPO_ROOT / "config" / "availability" / "overrides.json"

#: Sleeper designations that remove the current week (host-declared).
_HOST_OUT = frozenset({"OUT", "IR", "PUP", "NA", "SUS", "DNR", "COV"})
#: Of those, the reserve lists: no week-specific end, so later weeks are a risk.
_HOST_RESERVE = frozenset({"IR", "PUP", "NA", "SUS", "DNR"})
_HOST_RISK = frozenset({"QUESTIONABLE", "DOUBTFUL"})
#: ESPN status codes that make a stated return date binding.
_ESPN_OUT_CODES = frozenset({"IR", "O", "OUT", "SUSP", "PUP", "SUS"})


def _SEASON_OVER(season: int) -> date:  # noqa: N802 — reads as a constant
    """A date by which every fantasy week of ``season`` has been played (the
    NFL regular season ends in the first half of January).  Used ONLY when no
    schedule places a return date against a week: a return on or after it is
    after the whole fantasy season (ESPN writes season-ending returns as
    Jan 17 / Feb 15 of the next year)."""
    return date(season + 1, 1, 15)


@dataclass(frozen=True)
class WeekState:
    state: str
    reason: str


@dataclass
class AvailabilityContext:
    """Everything the rules need, resolved once per request.

    ``team_game_dates[team][week]`` is the kickoff DATE of that team's game in
    that week, ``None`` for a bye; a team absent from the map means the
    schedule is unknown for it (no bye is inferred).
    """

    season: int
    weeks: tuple[int, ...]
    current_week: int | None
    team_game_dates: Mapping[str, Mapping[int, date | None]] = field(default_factory=dict)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    overrides: Sequence[Mapping[str, Any]] = ()
    basis: dict[str, Any] = field(default_factory=dict)


def _norm_team(code: Any) -> str:
    from src.playerctx.normalize import normalize_team_code  # noqa: PLC0415

    raw = str(code or "").strip().upper()
    return (normalize_team_code(raw) or raw) if raw else ""


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


# ── horizon ──────────────────────────────────────────────────────────────


def fantasy_week_horizon(
    league_settings: Mapping[str, Any] | None, *, fallback_current_week: int | None = None
) -> tuple[tuple[int, ...], dict[str, Any]]:
    """The league's REMAINING fantasy weeks, from its own settings.

    Current week = Sleeper's league ``leg`` (the host's week); last week = the
    championship week (``playoff_week_start`` + bracket rounds - 1, two-week
    rounds doubling).  Each fallback is labelled in the returned basis.
    """
    s = league_settings or {}

    def _int(v: Any) -> int | None:
        try:
            return None if v is None or isinstance(v, bool) else int(v)
        except (TypeError, ValueError):
            return None

    current = _int(s.get("leg"))
    current_source = "league_leg"
    if current is None or current < 1:
        current = fallback_current_week
        current_source = "calendar_fallback" if current is not None else "unresolved"
    pws, teams = _int(s.get("playoff_week_start")), _int(s.get("playoff_teams"))
    if pws and teams and teams >= 2:
        rounds = max(1, math.ceil(math.log2(teams)))
        if _int(s.get("playoff_type")) == 2:
            rounds *= 2
        last, last_source = pws + rounds - 1, "championship_week"
    elif pws:
        last, last_source = pws - 1, "regular_season_only_bracket_unknown"
    else:
        last, last_source = 18, "nfl_regular_season_league_unknown"
    basis = {
        "currentWeek": current,
        "currentWeekSource": current_source,
        "lastWeek": last,
        "lastWeekSource": last_source,
    }
    if current is None:
        return (), {**basis, "reason": "current_week_unresolved"}
    return tuple(range(max(1, current), last + 1)), basis


def team_game_dates_from_schedule(
    rows: Iterable[Mapping[str, Any]], weeks: Iterable[int]
) -> dict[str, dict[int, date | None]]:
    """team -> week -> game date (``None`` = bye) from nflverse schedule rows.

    A team appearing in no regular-season row is left out (unknown), never
    given byes everywhere.
    """
    wanted = set(weeks)
    played: dict[str, dict[int, date | None]] = {}
    for row in rows:
        if str(row.get("game_type") or "REG").upper() != "REG":
            continue
        try:
            wk = int(float(row.get("week") or 0))
        except (TypeError, ValueError):
            continue
        gd = _parse_date(row.get("gameday"))
        for side in ("home_team", "away_team"):
            team = _norm_team(row.get(side))
            if team:
                played.setdefault(team, {})
                if wk in wanted:
                    played[team][wk] = gd
    regular = set(range(1, 19))
    out: dict[str, dict[int, date | None]] = {}
    for team, by_week in played.items():
        out[team] = {wk: by_week.get(wk) for wk in wanted if wk in regular}
    return out


# ── overrides ────────────────────────────────────────────────────────────

_ov_lock = threading.Lock()
_ov_cache: tuple[tuple[int, int], list[dict[str, Any]]] | None = None


def load_overrides(path: Path = OVERRIDES_PATH) -> list[dict[str, Any]]:
    """Owner-recorded, dated unavailability entries (rule 1)."""
    global _ov_cache
    try:
        st = path.stat()
    except OSError:
        return []
    key = (st.st_mtime_ns, st.st_size)
    with _ov_lock:
        if _ov_cache and _ov_cache[0] == key:
            return _ov_cache[1]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    entries = [e for e in (data.get("entries") or []) if isinstance(e, dict)]
    with _ov_lock:
        _ov_cache = (key, entries)
    return entries


def _override_for(overrides: Sequence[Mapping[str, Any]], pid: str, season: int, week: int):
    for e in overrides:
        if str(e.get("sleeperId") or "") != pid or int(e.get("season") or 0) != season:
            continue
        lo = int(e.get("fromWeek") or 1)
        hi = e.get("throughWeek")
        if week >= lo and (hi is None or week <= int(hi)):
            return e
    return None


# ── the rules ────────────────────────────────────────────────────────────


def _is_newer(reported_at: Any, host_news_updated_ms: Any) -> bool:
    """True when an ESPN report time is later than the host record's last
    news update.  Unknown on either side is NOT newer (the host stands)."""
    from datetime import datetime, timezone  # noqa: PLC0415

    try:
        rep = datetime.fromisoformat(str(reported_at).replace("Z", "+00:00"))
        host = datetime.fromtimestamp(float(host_news_updated_ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    if rep.tzinfo is None:
        rep = rep.replace(tzinfo=timezone.utc)
    return rep > host


def player_week_states(
    player_id: str,
    meta: Mapping[str, Any] | None,
    ctx: AvailabilityContext,
) -> dict[int, WeekState]:
    """Rules 1-6 for every week in ``ctx.weeks``."""
    pid = str(player_id)
    has_meta = isinstance(meta, Mapping) and bool(meta)
    host = str((meta or {}).get("injury_status") or "").strip().upper()
    team = _norm_team((meta or {}).get("team"))
    dates = ctx.team_game_dates.get(team) if team else None
    ev = ((ctx.evidence or {}).get(pid) or {}).get("current") or {}
    ev_code = str(ev.get("statusCode") or ev.get("fantasyStatus") or "").upper()
    ret = _parse_date(ev.get("returnDate")) if ev_code in _ESPN_OUT_CODES else None
    # The host's active report wins over an OLDER return report (an activated
    # player is never benched by a stale ESPN date), but not over a NEWER one
    # (the host's players DB is refreshed daily and can lag a fresh IR move).
    evidence_newer = ret is not None and _is_newer(
        ev.get("reportedAt"), (meta or {}).get("news_updated")
    )
    out: dict[int, WeekState] = {}
    first_back: int | None = None
    for wk in ctx.weeks:
        ov = _override_for(ctx.overrides, pid, ctx.season, wk)
        if ov is not None:
            out[wk] = WeekState(UNAVAILABLE, "owner_override")
            continue
        if dates is not None and wk in dates and dates[wk] is None:
            out[wk] = WeekState(UNAVAILABLE, "bye")
            continue
        if not has_meta:
            out[wk] = WeekState(UNKNOWN, "no_host_metadata")
            continue
        if not host and not evidence_newer:
            out[wk] = WeekState(AVAILABLE, "host_reports_active")
            continue
        if ret is not None:
            game_day = dates.get(wk) if dates else None
            if game_day is not None:
                if game_day < ret:
                    out[wk] = WeekState(UNAVAILABLE, "expected_return_after_game")
                    continue
                if first_back is None:
                    first_back = wk
                    out[wk] = WeekState(UNCERTAIN, "first_week_after_expected_return")
                    continue
                out[wk] = WeekState(AVAILABLE, "past_expected_return")
                continue
            # No game date for this team-week (schedule unknown): only a
            # return after the whole season is decisive.
            if ret >= _SEASON_OVER(ctx.season):
                out[wk] = WeekState(UNAVAILABLE, "expected_return_after_season")
            else:
                out[wk] = WeekState(UNCERTAIN, "return_date_unplaceable_no_schedule")
            continue
        is_current = ctx.current_week is not None and wk == ctx.current_week
        if host in _HOST_OUT:
            if is_current:
                out[wk] = WeekState(UNAVAILABLE, f"host_designation_{host.lower()}")
            elif host in _HOST_RESERVE:
                out[wk] = WeekState(UNCERTAIN, f"reserve_list_{host.lower()}_no_return_evidence")
            else:
                out[wk] = WeekState(
                    AVAILABLE, f"weekly_designation_{host.lower()}_current_week_only"
                )
            continue
        if host in _HOST_RISK and is_current:
            out[wk] = WeekState(UNCERTAIN, f"host_designation_{host.lower()}")
            continue
        out[wk] = WeekState(AVAILABLE, "no_absence_evidence")
    return out


def summarize(states: Mapping[int, WeekState]) -> dict[str, Any]:
    """Counts + the distinct reasons, for reporting beside a simulated number."""
    counts = {s: 0 for s in STATES}
    reasons: dict[str, int] = {}
    for st in states.values():
        counts[st.state] += 1
        if st.state != AVAILABLE:
            reasons[st.reason] = reasons.get(st.reason, 0) + 1
    n = len(states)
    if n and counts[UNAVAILABLE] == n:
        overall = UNAVAILABLE
    elif counts[UNKNOWN]:
        overall = UNKNOWN
    elif counts[UNCERTAIN] or counts[UNAVAILABLE]:
        overall = UNCERTAIN if counts[UNCERTAIN] else "partially_unavailable"
    else:
        overall = AVAILABLE
    return {
        "state": overall,
        "weeks": n,
        "eligibleWeeks": n - counts[UNAVAILABLE],
        "unavailableWeeks": counts[UNAVAILABLE],
        "uncertainWeeks": counts[UNCERTAIN],
        "unknownWeeks": counts[UNKNOWN],
        "reasons": dict(sorted(reasons.items())),
    }


# ── assembly (request path: no network) ──────────────────────────────────


def build_context(
    *,
    season: int,
    league_settings: Mapping[str, Any] | None,
    schedule_rows: Iterable[Mapping[str, Any]] | None = None,
    evidence_payload: Mapping[str, Any] | None = None,
    overrides: Sequence[Mapping[str, Any]] | None = None,
    fallback_current_week: int | None = None,
) -> AvailabilityContext:
    weeks, horizon = fantasy_week_horizon(
        league_settings, fallback_current_week=fallback_current_week
    )
    rows = list(schedule_rows or [])
    dates = team_game_dates_from_schedule(rows, weeks) if rows else {}
    ev_players = dict((evidence_payload or {}).get("players") or {})
    basis = {
        **horizon,
        "weeks": list(weeks),
        "schedule": "available" if dates else "unavailable",
        "returnEvidence": {
            "state": "available" if evidence_payload else "unavailable",
            "asOf": (evidence_payload or {}).get("asOf"),
            "players": len(ev_players),
            "source": "espn_athlete_current_injury",
        },
        "overrides": len(overrides or ()),
        "rules": "src/ros/availability.py (bye, override, host status, stated return date)",
    }
    return AvailabilityContext(
        season=int(season),
        weeks=weeks,
        current_week=horizon.get("currentWeek"),
        team_game_dates=dates,
        evidence=ev_players,
        overrides=tuple(overrides or ()),
        basis=basis,
    )


def load_context(*, season: int, league_settings: Mapping[str, Any] | None) -> AvailabilityContext:
    """Request-path assembly from the box's own caches — never a network call:
    the nflverse schedule cache (``cache_only``), the persisted return
    evidence, and the override file.  Each missing input is named in
    ``basis``; none is fabricated.

    The current week is the LEAGUE's own (``leg``) — no calendar fallback on
    this path: a week we would have to guess makes the calendar
    ``not_applied`` (and says so) rather than simulate the wrong weeks."""
    from src.bdvm.schedule import fetch_schedule_rows  # noqa: PLC0415
    from src.nfl_data.injury_return_evidence import load_evidence  # noqa: PLC0415

    try:
        rows = fetch_schedule_rows(int(season), cache_only=True)
    except Exception:  # noqa: BLE001 — a degraded input, named in basis
        rows = []
    return build_context(
        season=season,
        league_settings=league_settings,
        schedule_rows=rows,
        evidence_payload=load_evidence(),
        overrides=load_overrides(),
    )
