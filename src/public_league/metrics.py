"""Shared metric helpers for the public league sections.

Keeping these helpers in one module means every section shares the
same regular-season / playoff partitioning, the same roster→owner
attribution, and the same pre-week standings reconstruction so
results stay consistent across cards.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .identity import ManagerRegistry
from .snapshot import PublicLeagueSnapshot, SeasonSnapshot


# ── Matchup helpers ────────────────────────────────────────────────────────
def matchup_pairs(week_entries: list[dict[str, Any]]) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Group a week's matchup rows into (home, away) pairs by matchup_id.

    The ordering within a pair is stable — we sort by ``roster_id`` so
    the two sides are deterministic for every downstream consumer.
    """
    groups: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for m in week_entries:
        mid = m.get("matchup_id")
        if mid is None:
            continue
        groups[mid].append(m)
    pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for entries in groups.values():
        if len(entries) != 2:
            continue
        entries.sort(key=lambda e: int(e.get("roster_id") or 0))
        pairs.append((entries[0], entries[1]))
    return pairs


def matchup_margin(a: dict[str, Any], b: dict[str, Any]) -> float:
    return float(a.get("points") or 0.0) - float(b.get("points") or 0.0)


def matchup_points(entry: dict[str, Any]) -> float:
    return float(entry.get("points") or 0.0)


def roster_id_of(entry: dict[str, Any]) -> int | None:
    try:
        return int(entry.get("roster_id"))
    except (TypeError, ValueError):
        return None


def is_scored(entry: dict[str, Any]) -> bool:
    """True if Sleeper has a non-zero score for the roster-week."""
    return matchup_points(entry) > 0


def resolve_owner(
    registry: ManagerRegistry,
    league_id: str,
    roster_id: Any,
) -> str:
    try:
        rid_int = int(roster_id)
    except (TypeError, ValueError):
        return ""
    return registry.roster_to_owner.get((str(league_id or ""), rid_int), "")


# ── Standings ────────────────────────────────────────────────────────────
def regular_season_settings_record(roster: dict[str, Any]) -> dict[str, Any]:
    """Return the wins/losses/ties/PF/PA record stored on the Sleeper roster."""
    settings = roster.get("settings") or {}

    def _num(key: str) -> float:
        val = settings.get(key)
        try:
            return float(val or 0)
        except (TypeError, ValueError):
            return 0.0

    points_for = _num("fpts") + (_num("fpts_decimal") / 100.0)
    points_against = _num("fpts_against") + (_num("fpts_against_decimal") / 100.0)
    return {
        "wins": int(_num("wins")),
        "losses": int(_num("losses")),
        "ties": int(_num("ties")),
        "pointsFor": round(points_for, 2),
        "pointsAgainst": round(points_against, 2),
        "sleeperRank": int(_num("rank")) or None,
    }


def season_standings(season: SeasonSnapshot, registry: ManagerRegistry) -> list[dict[str, Any]]:
    """Final regular-season standings from Sleeper roster settings.

    Tiebreaks: higher win%, higher PF, lower PA, lower sleeperRank if set.
    """
    rows: list[dict[str, Any]] = []
    for roster in season.rosters:
        try:
            rid = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            continue
        owner_id = resolve_owner(registry, season.league_id, rid)
        if not owner_id:
            continue
        rec = regular_season_settings_record(roster)
        games = rec["wins"] + rec["losses"] + rec["ties"]
        win_pct = (rec["wins"] + rec["ties"] * 0.5) / games if games else 0.0
        rows.append({
            "ownerId": owner_id,
            "rosterId": rid,
            "leagueId": season.league_id,
            "season": season.season,
            "wins": rec["wins"],
            "losses": rec["losses"],
            "ties": rec["ties"],
            "pointsFor": rec["pointsFor"],
            "pointsAgainst": rec["pointsAgainst"],
            "winPct": round(win_pct, 4),
            "games": games,
            "sleeperRank": rec["sleeperRank"],
        })
    rows.sort(
        key=lambda r: (
            -r["winPct"],
            -r["pointsFor"],
            r["pointsAgainst"],
            r["sleeperRank"] or 999,
        )
    )
    for i, row in enumerate(rows):
        row["standing"] = i + 1
    return rows


def top_seed(standings: list[dict[str, Any]]) -> dict[str, Any] | None:
    return standings[0] if standings else None


# ── Pre-week standings reconstruction ─────────────────────────────────────
def _reg_season_weeks_actual(season: SeasonSnapshot) -> list[int]:
    """Regular-season weeks that actually have any scored games."""
    weeks = []
    for wk in season.regular_season_weeks:
        entries = season.matchups_by_week.get(wk) or []
        if any(is_scored(e) for e in entries):
            weeks.append(wk)
    return sorted(weeks)


def pre_week_standings(
    season: SeasonSnapshot,
    registry: ManagerRegistry,
    week: int,
) -> list[dict[str, Any]]:
    """Standings as of the start of ``week`` — only regular-season games
    completed strictly before ``week`` count.

    Returns a list sorted by standings rank with per-owner totals.
    """
    by_owner: dict[str, dict[str, Any]] = {}

    def _ensure(owner_id: str) -> dict[str, Any]:
        if owner_id not in by_owner:
            by_owner[owner_id] = {
                "ownerId": owner_id,
                "wins": 0,
                "losses": 0,
                "ties": 0,
                "pointsFor": 0.0,
                "pointsAgainst": 0.0,
            }
        return by_owner[owner_id]

    for wk in season.regular_season_weeks:
        if wk >= week:
            break
        for a, b in matchup_pairs(season.matchups_by_week.get(wk) or []):
            if not is_scored(a) and not is_scored(b):
                continue
            pa, pb = matchup_points(a), matchup_points(b)
            oa = resolve_owner(registry, season.league_id, a.get("roster_id"))
            ob = resolve_owner(registry, season.league_id, b.get("roster_id"))
            if oa:
                rec_a = _ensure(oa)
                rec_a["pointsFor"] += pa
                rec_a["pointsAgainst"] += pb
                if pa > pb:
                    rec_a["wins"] += 1
                elif pa < pb:
                    rec_a["losses"] += 1
                else:
                    rec_a["ties"] += 1
            if ob:
                rec_b = _ensure(ob)
                rec_b["pointsFor"] += pb
                rec_b["pointsAgainst"] += pa
                if pb > pa:
                    rec_b["wins"] += 1
                elif pb < pa:
                    rec_b["losses"] += 1
                else:
                    rec_b["ties"] += 1

    rows = list(by_owner.values())
    for r in rows:
        g = r["wins"] + r["losses"] + r["ties"]
        r["games"] = g
        r["winPct"] = round((r["wins"] + r["ties"] * 0.5) / g, 4) if g else 0.0
        r["pointsFor"] = round(r["pointsFor"], 2)
        r["pointsAgainst"] = round(r["pointsAgainst"], 2)
    rows.sort(key=lambda r: (-r["winPct"], -r["pointsFor"], r["pointsAgainst"]))
    for i, r in enumerate(rows):
        r["standing"] = i + 1
    return rows


# ── Playoff helpers ────────────────────────────────────────────────────────
def playoff_placement(bracket: list[dict[str, Any]]) -> dict[int, int]:
    """Return roster_id -> final playoff place (1 = champion).

    Sleeper's winners_bracket only annotates ``p`` (place) on terminal
    matchups.  The loser of a ``p=1`` matchup places 2, the loser of a
    ``p=3`` matchup places 4, etc.
    """
    placement: dict[int, int] = {}
    for m in bracket:
        if not isinstance(m, dict):
            continue
        p = m.get("p")
        if p is None:
            continue
        try:
            place = int(p)
        except (TypeError, ValueError):
            continue
        w = m.get("w")
        l = m.get("l")
        if w is not None:
            try:
                placement.setdefault(int(w), place)
            except (TypeError, ValueError):
                pass
        if l is not None:
            try:
                placement.setdefault(int(l), place + 1)
            except (TypeError, ValueError):
                pass
    return placement


def playoff_teams(bracket: list[dict[str, Any]]) -> list[int]:
    """Every roster_id that appears anywhere in the winners bracket."""
    teams: set[int] = set()
    for m in bracket:
        if not isinstance(m, dict):
            continue
        for key in ("t1", "t2", "w", "l"):
            v = m.get(key)
            if v is None:
                continue
            try:
                teams.add(int(v))
            except (TypeError, ValueError):
                continue
    return sorted(teams)


def final_playoff_matchup(bracket: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the matchup with ``p=1`` (the championship game) if any."""
    for m in bracket:
        if isinstance(m, dict) and m.get("p") == 1:
            return m
    return None


def season_champion(season: SeasonSnapshot) -> int | None:
    """Primary: winner of ``p=1`` matchup.  Fallback: min place winner.
    Final fallback: ``league.metadata.latest_league_winner_roster_id``.
    """
    final = final_playoff_matchup(season.winners_bracket)
    if final is not None:
        w = final.get("w")
        if w is not None:
            try:
                return int(w)
            except (TypeError, ValueError):
                pass
    placement = playoff_placement(season.winners_bracket)
    if placement:
        return min(placement, key=lambda rid: placement[rid])
    metadata = season.league.get("metadata") or {}
    explicit = metadata.get("latest_league_winner_roster_id") or season.league.get("last_league_winner_roster_id")
    try:
        return int(explicit) if explicit is not None else None
    except (TypeError, ValueError):
        return None


def season_runner_up(season: SeasonSnapshot) -> int | None:
    placement = playoff_placement(season.winners_bracket)
    candidates = [rid for rid, p in placement.items() if p == 2]
    if candidates:
        return candidates[0]
    # Fallback: loser of the final matchup.
    final = final_playoff_matchup(season.winners_bracket)
    if final is not None:
        l = final.get("l")
        try:
            return int(l) if l is not None else None
        except (TypeError, ValueError):
            return None
    return None


# ── Iteration helpers ────────────────────────────────────────────────────
def walk_weekly_scores(
    snapshot: PublicLeagueSnapshot,
    include_playoffs: bool = True,
) -> Iterable[tuple[SeasonSnapshot, int, dict[str, Any]]]:
    """Yield (season, week, entry) for every scored roster-week."""
    for season in snapshot.seasons:
        weeks = season.all_weeks if include_playoffs else season.regular_season_weeks
        for wk in sorted(weeks):
            for entry in season.matchups_by_week.get(wk) or []:
                if is_scored(entry):
                    yield season, wk, entry


def walk_matchup_pairs(
    snapshot: PublicLeagueSnapshot,
    include_playoffs: bool = True,
) -> Iterable[tuple[SeasonSnapshot, int, dict[str, Any], dict[str, Any], bool]]:
    """Yield (season, week, a, b, is_playoff) for every scored pair."""
    for season in snapshot.seasons:
        for wk in sorted(season.matchups_by_week.keys()):
            is_playoff = wk >= season.playoff_week_start
            if is_playoff and not include_playoffs:
                continue
            for a, b in matchup_pairs(season.matchups_by_week[wk]):
                if not is_scored(a) and not is_scored(b):
                    continue
                yield season, wk, a, b, is_playoff


# ── Shared team-name resolver ────────────────────────────────────────────
def team_name(snapshot: PublicLeagueSnapshot, league_id: str, roster_id: int | None) -> str:
    """Historical team name for a roster in a league."""
    if roster_id is None:
        return ""
    owner_id = resolve_owner(snapshot.managers, league_id, roster_id)
    manager = snapshot.managers.by_owner_id.get(owner_id) if owner_id else None
    if not manager:
        return f"Team {roster_id}"
    for alias in manager.aliases:
        if alias.league_id == league_id and alias.roster_id == roster_id:
            return alias.team_name
    return manager.current_team_name or manager.display_name or f"Team {roster_id}"


def display_name_for(snapshot: PublicLeagueSnapshot, owner_id: str) -> str:
    mgr = snapshot.managers.by_owner_id.get(owner_id) if owner_id else None
    if not mgr:
        return owner_id or ""
    return mgr.display_name or mgr.current_team_name or owner_id
