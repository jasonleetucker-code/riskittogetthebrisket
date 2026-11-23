"""The Ring Club — championship rings for individual NFL players.

Owner directive 2026-11-23 ("BRISKET DYNASTY — BUILD THE RING CLUB").  ONE
owner of "which NFL players earned a Brisket Dynasty championship ring":
the public History tab (``history.build_section`` → ``ringClub``) and the
public player page (``player_journey`` → ``championshipRings``) consume it;
neither recomputes anything.

The rule
────────
A player earns ONE ring for each distinct season in which he was on the
championship-winning franchise's roster **when the championship concluded**.
Starting is not required: bench and injured-reserve players qualify, and so
does a taxi-squad player whenever the league runs a taxi squad and his place
on it at the close is provable.  A player traded away or dropped before the
close, or added after it, earns nothing for that season.  The ring belongs to
the player, not to the manager or franchise: three titles with three
different franchises are three rings.

What "concluded" means, measured on the league's own data
─────────────────────────────────────────────────────────
* The champion is :func:`metrics.season_champion` — a DECIDED final only
  (never a projection, a seed or a stale metadata value).
* The championship's closing week is the final's last scoring week by the
  league's own settings (``playoff_week_start``, the final's bracket round and
  ``playoff_round_type``), and the champion and the final's other team must
  share a ``matchup_id`` in it.  A two-week final therefore closes on its
  second week.  Unknown settings, or a settings week in which the finalists
  did not meet, leave the season UNVERIFIED rather than guessing -- and a
  later pre-generated pairing (Sleeper schedules a week 18) is never mistaken
  for the close.  Measured 2026-11-23 on ``dynasty_main``: 2024 and 2025 both
  played two-week finals (weeks 16-17), so both close on week 17.
* The closing roster is the champion's row in that week's matchups —
  Sleeper's own per-week record of the roster (``players``: starters, bench
  and injured reserve).  It is frozen when the week ends: measured on the
  2025 champion, free-agent adds made during week 16 appear in week 16's
  row, while the waivers processed the following Wednesday appear only in
  week 17's.  The league's CURRENT roster is not used as the source: the
  2025 champion made eight more moves after the final.
* Injured reserve is IN the matchup row (measured on every 2024 roster with
  IR), so a reserve player missing from the row was not on the roster at the
  close and earns nothing.  A taxi squad is the one held slot a row may omit:
  taxi players are credited only when the champion made no roster move from
  the closing week on (so the frozen roster IS the closing roster).  Any such
  move -- which could stash a post-close add on the taxi squad or release a
  taxi player held at the close -- flags the season ``heldSlotsUnverified``
  instead, and only the players the row names are credited.

Missing is never zero
─────────────────────
A decided championship whose closing roster cannot be established is
UNVERIFIED with a reason, never a season with no rings, and the empty state
says so: "no multi-champions yet" is published only when every decided
championship is verified.  Rings are a pure function of the snapshot, keyed
by (player, season), so re-importing, redeploying or re-snapshotting can
never award a duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import metrics
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot

#: A Ring Club member holds at least this many rings.
RING_CLUB_MINIMUM = 2
#: Members at or above this many rings get the "dynasty" treatment.
PRESTIGE_MINIMUM = 3

TITLE = "THE RING CLUB"
SUBTITLE = "Players with Multiple Championships"
DESCRIPTION = (
    "The exclusive club of NFL players who have been part of two or more "
    "Brisket Dynasty championship-winning rosters."
)
EMPTY_CONFIRMED_MESSAGE = (
    "No players have earned multiple Brisket Dynasty championships yet. "
    "The race for the first two-time champion is on."
)

# Season statuses.
STATUS_VERIFIED = "verified"
STATUS_UNVERIFIED = "unverified"
STATUS_UNDECIDED = "undecided"

# Reasons a decided championship's closing roster is not established.
REASON_FINAL_TEAMS_UNKNOWN = "final_teams_unknown"
REASON_FINAL_PAIRING_NOT_FOUND = "final_pairing_not_found"
REASON_SETTINGS_UNKNOWN = "playoff_settings_unknown"
REASON_CLOSING_WEEK_MISMATCH = "closing_week_disagrees_with_league_settings"
REASON_CLOSING_WEEK_NOT_FINAL = "closing_week_not_final"
REASON_CLOSING_ROSTER_EMPTY = "closing_roster_empty"

# Team-defense "players" are units, not individual NFL players.
_TEAM_UNIT_POSITIONS = frozenset({"DEF", "DST", "D/ST"})


@dataclass(frozen=True)
class ChampionshipClose:
    """One season's championship, and the roster that was on it at the close."""

    season: str
    league_id: str
    status: str
    reason: str | None = None
    champion_roster_id: int | None = None
    closing_week: int | None = None
    player_ids: frozenset[str] = field(default_factory=frozenset)
    held_slots_unverified: bool = False


def _int_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _row_for(rows: list[dict[str, Any]], roster_id: int) -> dict[str, Any] | None:
    for row in rows or []:
        if isinstance(row, dict) and metrics.roster_id_of(row) == roster_id:
            return row
    return None


def _final_pair_weeks(season: SeasonSnapshot, champion: int, opponent: int) -> list[int]:
    """Playoff weeks in which the two finalists share a ``matchup_id``."""
    weeks: list[int] = []
    for wk in sorted(season.matchups_by_week):
        if wk < season.playoff_week_start:
            continue
        rows = season.matchups_by_week[wk]
        a, b = _row_for(rows, champion), _row_for(rows, opponent)
        if a is None or b is None:
            continue
        mid = a.get("matchup_id")
        if mid is not None and mid == b.get("matchup_id"):
            weeks.append(wk)
    return weeks


def _settings_closing_week(season: SeasonSnapshot, final_round: int | None) -> int | None:
    """The final's last week by the league's own settings, or ``None``.

    ``playoff_round_type``: 0 = one week per round, 1 = two-week championship,
    2 = two weeks per round.  Unknown settings answer ``None`` (no check), never
    a guessed default.
    """
    settings = season.league.get("settings") or {}
    if final_round is None or final_round < 1:
        return None
    start = _int_or_none(settings.get("playoff_week_start"))
    round_type = _int_or_none(settings.get("playoff_round_type"))
    if start is None or start < 1 or round_type not in (0, 1, 2):
        return None
    if round_type == 2:
        return start + 2 * final_round - 1
    return start + final_round - 1 + (1 if round_type == 1 else 0)


def _clean_ids(values: Any) -> set[str]:
    return {str(v) for v in (values or []) if v not in (None, "", "0", 0)}


def championship_close(season: SeasonSnapshot) -> ChampionshipClose:
    """The season's decided championship and its closing roster, or why not."""
    champion = metrics.season_champion(season)
    if champion is None:
        return ChampionshipClose(
            season=season.season, league_id=season.league_id, status=STATUS_UNDECIDED
        )

    def unverified(reason: str, week: int | None = None) -> ChampionshipClose:
        return ChampionshipClose(
            season=season.season,
            league_id=season.league_id,
            status=STATUS_UNVERIFIED,
            reason=reason,
            champion_roster_id=champion,
            closing_week=week,
        )

    final = metrics.final_playoff_matchup(season.winners_bracket)
    t1 = _int_or_none(final.get("t1")) if final else None
    t2 = _int_or_none(final.get("t2")) if final else None
    if t1 is None or t2 is None or champion not in (t1, t2):
        return unverified(REASON_FINAL_TEAMS_UNKNOWN)
    opponent = t2 if champion == t1 else t1

    weeks = _final_pair_weeks(season, champion, opponent)
    if not weeks:
        return unverified(REASON_FINAL_PAIRING_NOT_FOUND)
    # The settings name the closing week; the matchups must confirm the
    # finalists met in it.  The data alone is not trusted to bound the search:
    # Sleeper pre-generates later pairings (a week 18) with real matchup ids.
    closing_week = _settings_closing_week(season, _int_or_none(final.get("r")))
    if closing_week is None:
        return unverified(REASON_SETTINGS_UNKNOWN)
    if closing_week not in weeks:
        return unverified(REASON_CLOSING_WEEK_MISMATCH, closing_week)
    if closing_week not in set(metrics.final_weeks(season)):
        return unverified(REASON_CLOSING_WEEK_NOT_FINAL, closing_week)

    row = _row_for(season.matchups_by_week[closing_week], champion) or {}
    players = _clean_ids(row.get("players"))
    if not players:
        return unverified(REASON_CLOSING_ROSTER_EMPTY, closing_week)

    held_unverified = False
    roster = next(
        (
            r
            for r in season.rosters
            if isinstance(r, dict) and _int_or_none(r.get("roster_id")) == champion
        ),
        None,
    )
    taxi = _clean_ids((roster or {}).get("taxi"))
    # An absent setting is "no taxi squad stated", never a zero-slot fact; a
    # roster that holds taxi players proves the league runs one either way.
    taxi_slots = _int_or_none((season.league.get("settings") or {}).get("taxi_slots"))
    if (taxi_slots is not None and taxi_slots > 0) or taxi:
        # Injured reserve is in the row; only the taxi squad can be missing.
        frozen = _clean_ids((roster or {}).get("players"))
        complete = str(season.league.get("status") or "").lower() == "complete"
        moved = _moved_since(season, champion, closing_week)
        if roster is not None and complete and not moved and frozen - taxi == players:
            players |= taxi
        elif moved or (taxi - players) or roster is None:
            held_unverified = True

    return ChampionshipClose(
        season=season.season,
        league_id=season.league_id,
        status=STATUS_VERIFIED,
        champion_roster_id=champion,
        closing_week=closing_week,
        player_ids=frozenset(players),
        held_slots_unverified=held_unverified,
    )


def _moved_since(season: SeasonSnapshot, roster_id: int, week: int) -> bool:
    """True if a completed transaction touching ``roster_id`` sits in a leg
    at or after ``week`` -- the frozen roster may then differ from the close."""
    for leg, txs in season.transactions_by_week.items():
        if _int_or_none(leg) is None or int(leg) < week:
            continue
        for tx in txs or []:
            if not isinstance(tx, dict) or str(tx.get("status") or "").lower() != "complete":
                continue
            touched = {_int_or_none(r) for r in tx.get("roster_ids") or []}
            touched |= {_int_or_none(r) for r in (tx.get("adds") or {}).values()}
            touched |= {_int_or_none(r) for r in (tx.get("drops") or {}).values()}
            if roster_id in touched:
                return True
    return False


def _franchise(snapshot: PublicLeagueSnapshot, close: ChampionshipClose) -> dict[str, Any]:
    """The championship franchise as it stood at the close (manager and name)."""
    rid = close.champion_roster_id
    owner_id = metrics.resolve_owner(snapshot.managers, close.league_id, rid, close.closing_week)
    return {
        "season": close.season,
        "ownerId": owner_id or None,
        "rosterId": rid,
        "teamName": metrics.team_name_for_owner(snapshot, close.league_id, rid, owner_id),
        "displayName": metrics.display_name_for(snapshot, owner_id) if owner_id else None,
    }


def _is_team_unit(snapshot: PublicLeagueSnapshot, player_id: str) -> bool:
    """Team defenses are units, not players.  Sleeper keys them by the team
    abbreviation ("BUF"), so that shape counts even without a player dump."""
    p = snapshot.nfl_players.get(player_id)
    raw = str((p or {}).get("position") or "").upper()
    if raw in _TEAM_UNIT_POSITIONS:
        return True
    return player_id.isalpha() and player_id.isupper() and 2 <= len(player_id) <= 3


@dataclass
class RingLedger:
    closes: list[ChampionshipClose]
    #: player_id → {season: franchise block}; one entry per (player, season).
    rings: dict[str, dict[str, dict[str, Any]]]


def ring_ledger(snapshot: PublicLeagueSnapshot) -> RingLedger:
    """Every season's championship close and every player's rings.

    Seasons are de-duplicated by season label (first occurrence wins), and a
    player holds at most one ring per season, so the ledger is idempotent.
    """
    closes: list[ChampionshipClose] = []
    seen: set[str] = set()
    for season in snapshot.seasons:
        if season.season in seen:
            continue
        seen.add(season.season)
        closes.append(championship_close(season))
    closes.sort(key=lambda c: c.season)

    rings: dict[str, dict[str, dict[str, Any]]] = {}
    for close in closes:
        if close.status != STATUS_VERIFIED:
            continue
        franchise = _franchise(snapshot, close)
        for pid in sorted(close.player_ids):
            if _is_team_unit(snapshot, pid):
                continue
            rings.setdefault(pid, {})[close.season] = franchise
    return RingLedger(closes=closes, rings=rings)


def _player_block(snapshot: PublicLeagueSnapshot, pid: str) -> dict[str, Any]:
    p = snapshot.nfl_players.get(pid) or {}
    name = snapshot.player_display(pid)
    team = p.get("team") if isinstance(p, dict) else None
    return {
        "playerId": pid,
        "playerName": name or f"Player {pid}",
        "position": snapshot.player_position(pid) or None,
        "nflTeam": str(team) if team else None,
    }


def _championships(by_season: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [dict(by_season[s]) for s in sorted(by_season)]


def _coverage(ledger: RingLedger, snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    seasons: list[dict[str, Any]] = []
    for close in ledger.closes:
        row: dict[str, Any] = {"season": close.season, "status": close.status}
        if close.status == STATUS_VERIFIED:
            franchise = _franchise(snapshot, close)
            row.update(
                closingWeek=close.closing_week,
                championTeamName=franchise["teamName"],
                championDisplayName=franchise["displayName"],
                rosterSize=len(close.player_ids),
                heldSlotsUnverified=close.held_slots_unverified,
            )
        elif close.status == STATUS_UNVERIFIED:
            row.update(reason=close.reason, closingWeek=close.closing_week)
        seasons.append(row)
    decided = [c for c in ledger.closes if c.status != STATUS_UNDECIDED]
    unverified = [c for c in decided if c.status == STATUS_UNVERIFIED]
    partial = [c for c in decided if c.held_slots_unverified]
    # The league-history walk must have reached the league's FIRST season
    # (``history_coverage`` state ``complete``); a truncated or unreadable
    # walk -- or no record of the walk at all -- may hide older champions.
    history_state = (getattr(snapshot, "history_coverage", None) or {}).get("state")
    # ``non_dynasty_predecessor``: the walk stopped at a predecessor that was
    # not a dynasty league -- the dynasty history itself is complete.
    history_complete = history_state in {"complete", "non_dynasty_predecessor"}
    if unverified or partial or not history_complete:
        state = "incomplete"
    elif not decided:
        state = "none"
    else:
        state = "complete"
    return {
        "state": state,
        "historyComplete": history_complete,
        "historyState": history_state,
        "seasons": seasons,
        "verifiedSeasons": [c.season for c in decided if c.status == STATUS_VERIFIED],
        "unverifiedSeasons": [c.season for c in unverified],
        "partialSeasons": [c.season for c in partial],
        "decidedChampionships": len(decided),
    }


def _empty_state(coverage: dict[str, Any]) -> dict[str, Any]:
    if coverage["state"] == "incomplete":
        missing = coverage["unverifiedSeasons"] + [
            s for s in coverage["partialSeasons"] if s not in coverage["unverifiedSeasons"]
        ]
        if missing:
            detail = "the championship roster records for " + ", ".join(missing) + " are incomplete"
        else:
            detail = "the league's earlier seasons could not all be read"
        return {
            "kind": "coverage_incomplete",
            "title": TITLE,
            "message": (
                "No two-time champion is confirmed yet, but "
                + detail
                + ", so the club cannot be confirmed empty."
            ),
        }
    if coverage["state"] == "none":
        return {
            "kind": "no_championships_yet",
            "title": TITLE,
            "message": (
                "No Brisket Dynasty championship has been decided yet. "
                "The race for the first two-time champion is on."
            ),
        }
    return {"kind": "no_multi_champions", "title": TITLE, "message": EMPTY_CONFIRMED_MESSAGE}


def build_ring_club(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """The public Ring Club block: members with two or more rings, ranked."""
    ledger = ring_ledger(snapshot)
    members: list[dict[str, Any]] = []
    for pid, by_season in ledger.rings.items():
        count = len(by_season)
        if count < RING_CLUB_MINIMUM:
            continue
        members.append(
            {
                **_player_block(snapshot, pid),
                "rings": count,
                "prestige": count >= PRESTIGE_MINIMUM,
                "seasons": sorted(by_season),
                "championships": _championships(by_season),
            }
        )
    # Most rings first; equal counts are tied and ordered by name, then id,
    # so the secondary order never reads as a ranking advantage.
    members.sort(key=lambda m: (-m["rings"], m["playerName"].casefold(), m["playerId"]))
    counts = [m["rings"] for m in members]
    for m in members:
        m["rank"] = 1 + sum(1 for c in counts if c > m["rings"])
        m["tied"] = counts.count(m["rings"]) > 1

    coverage = _coverage(ledger, snapshot)
    coverage["singleRingPlayers"] = sum(1 for by in ledger.rings.values() if len(by) == 1)
    coverage["ringedPlayers"] = len(ledger.rings)
    return {
        "title": TITLE,
        "subtitle": SUBTITLE,
        "description": DESCRIPTION,
        "minimumRings": RING_CLUB_MINIMUM,
        "prestigeRings": PRESTIGE_MINIMUM,
        "members": members,
        "memberCount": len(members),
        "coverage": coverage,
        "emptyState": None if members else _empty_state(coverage),
    }


def player_rings(snapshot: PublicLeagueSnapshot, player_id: str) -> dict[str, Any]:
    """One player's verified rings, for his public profile (one ring counts)."""
    ledger = ring_ledger(snapshot)
    by_season = ledger.rings.get(str(player_id), {})
    coverage = _coverage(ledger, snapshot)
    return {
        "rings": len(by_season),
        "ringClubMember": len(by_season) >= RING_CLUB_MINIMUM,
        "championships": _championships(by_season),
        "coverageState": coverage["state"],
        "unverifiedSeasons": coverage["unverifiedSeasons"],
        "partialSeasons": coverage["partialSeasons"],
        "historyComplete": coverage["historyComplete"],
    }
