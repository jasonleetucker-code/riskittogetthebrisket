"""Roster Construction V1 — payload assembly over existing owners.

Reads the league snapshot (Sleeper matchups: weekly rosters as owned and every
rostered player's realized points), the player-impact computation (marginal
contribution), and the live contract (canonical ``rankDerivedValue``, read
only), and hands them to the pure calculation in
:mod:`src.roster_intel.construction`.  No value, lineup or rule is computed
here.  The route that serves it is ``GET /api/roster-construction`` in
``server.py``, private and gated by the ``roster_construction`` flag.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.public_league import metrics
from src.public_league import player_impact as pi
from src.public_league.snapshot import PublicLeagueSnapshot, SeasonSnapshot
from src.roster_intel import construction as rc
from src.ros.lineup import lineup_position, resolve_starter_slots

REPO_ROOT = Path(__file__).resolve().parents[2]
PRIORS_PATH = REPO_ROOT / "config" / "roster_construction" / "v1.json"

R_MARGINAL_REGULAR_ONLY = "player_impact_regular_season_only"
R_MARGINAL_UNAVAILABLE = "player_impact_unavailable"
R_VALUE_CONTRACT_MISSING = "contract_not_loaded"
R_VALUE_LEAGUE_MISMATCH = "contract_league_mismatch"
R_VALUE_NO_TEAMS = "contract_has_no_rosters"


@lru_cache(maxsize=1)
def _priors_cached(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_priors(path: Path | None = None) -> dict[str, Any]:
    return json.loads(_priors_cached(str(path or PRIORS_PATH)))


def lineup_mode_of(best_ball: bool | None) -> str:
    if best_ball is True:
        return rc.LINEUP_BEST_BALL
    if best_ball is False:
        return rc.LINEUP_MANAGED
    return rc.LINEUP_UNVERIFIED


def season_input_from_snapshot(
    snapshot: PublicLeagueSnapshot,
    season: SeasonSnapshot,
    *,
    include_playoffs: bool = False,
    impact: Mapping[str, Any] | None = None,
    roster_limit: int | None = None,
) -> rc.SeasonInput:
    """Snapshot season → :class:`construction.SeasonInput` (pure conversion)."""
    weeks, not_final = pi.season_team_weeks(snapshot, season, include_playoffs=include_playoffs)
    slots, slot_source = resolve_starter_slots(
        roster_positions=season.league.get("roster_positions")
    )
    best_ball = pi.best_ball_rule(season)
    pids = sorted({p for teams in weeks.values() for t in teams for p in (*t.roster, *t.counted)})
    infos = {pid: pi.player_info(snapshot, pid) for pid in pids}
    rules = pi.WeekRules(starter_slots=tuple(slots), best_ball=best_ball, median_enabled=None)
    contradicted = pi.detect_contradictions(weeks, rules, infos)
    players = {
        pid: rc.PlayerMeta(
            position=info.host_position or info.position,
            fantasy_positions=tuple(info.fantasy_positions),
            name=snapshot.player_display(pid),
        )
        for pid, info in infos.items()
    }
    week_in: dict[int, list[rc.TeamWeekIn]] = {}
    last_owner: dict[int, str] = {}
    for wk in sorted(weeks):
        week_in[wk] = []
        for t in weeks[wk]:
            last_owner[t.roster_id] = t.owner_id
            week_in[wk].append(
                rc.TeamWeekIn(
                    roster_id=t.roster_id,
                    roster=tuple(t.roster),
                    points=dict(t.points),
                    counted=tuple(t.counted),
                    score=t.score,
                    owner_id=t.owner_id,
                )
            )
    labels = {
        rid: (metrics.display_name_for(snapshot, oid) if oid else "") or f"Team {rid}"
        for rid, oid in last_owner.items()
    }
    marginal: dict[tuple[str, int, int], dict[str, Any]] = {}
    regular = set(season.regular_season_weeks)
    if impact is not None:
        for rec in impact.get("_records") or []:
            gc = rec.get("gameChangerPoints") or {}
            marginal[(str(rec["playerId"]), int(rec["rosterId"]), int(rec["week"]))] = {
                "value": gc.get("value"),
                "reason": gc.get("reason"),
            }
        for wk, teams in week_in.items():
            if wk in regular:
                continue
            for t in teams:
                for pid in t.roster:
                    marginal[(pid, t.roster_id, wk)] = {
                        "value": None,
                        "reason": R_MARGINAL_REGULAR_ONLY,
                    }
    return rc.SeasonInput(
        season=str(season.season),
        slots=tuple(slots),
        slot_source=slot_source,
        lineup_mode=lineup_mode_of(best_ball),
        weeks=week_in,
        players=players,
        excluded_weeks=[{"week": w, "reason": "not_final"} for w in not_final],
        contradicted={wk: tuple(r) for wk, r in contradicted.items()},
        regular_weeks=frozenset(regular),
        include_playoffs=include_playoffs,
        roster_limit=roster_limit,
        team_labels=labels,
        marginal=marginal,
        marginal_unavailable_reason=None if impact is not None else R_MARGINAL_UNAVAILABLE,
    )


def value_input_from_contract(
    contract: Mapping[str, Any] | None,
    league_key: str,
    snapshot: PublicLeagueSnapshot | None = None,
) -> rc.ValueInput:
    """Current rosters × canonical ``rankDerivedValue`` (read only).

    Fails closed: a contract built for another league is never used, because
    its rosters belong to that league and its values to its scoring.
    """
    if not contract:
        return rc.ValueInput(available=False, reason=R_VALUE_CONTRACT_MISSING)
    meta = contract.get("meta") or {}
    if str(meta.get("leagueKey") or "") != str(league_key):
        return rc.ValueInput(available=False, reason=R_VALUE_LEAGUE_MISMATCH)
    sleeper = contract.get("sleeper") or {}
    teams = sleeper.get("teams") if isinstance(sleeper, dict) else None
    if not isinstance(teams, list) or not teams:
        return rc.ValueInput(available=False, reason=R_VALUE_NO_TEAMS)
    name_to_id = sleeper.get("playerIds") if isinstance(sleeper.get("playerIds"), dict) else {}
    rows: dict[str, Mapping[str, Any]] = {}
    for row in contract.get("playersArray") or []:
        if not isinstance(row, dict) or row.get("assetClass") == "pick":
            continue
        pid = str(row.get("playerId") or "").strip()
        if pid and pid not in rows:
            rows[pid] = row
    nfl = snapshot.nfl_players if snapshot is not None else {}
    out: dict[int, list[rc.ValuePlayer]] = {}
    for team in teams:
        if not isinstance(team, dict):
            continue
        try:
            rid = int(team.get("roster_id", team.get("rosterId")))
        except (TypeError, ValueError):
            continue
        ids = [str(p) for p in (team.get("playerIds") or []) if p]
        if not ids:
            ids = [str(name_to_id[n]) for n in team.get("players") or [] if n in name_to_id]
        players: list[rc.ValuePlayer] = []
        for pid in ids:
            row = rows.get(pid) or {}
            raw = row.get("rankDerivedValue")
            pos = str(row.get("position") or "")
            if not pos and snapshot is not None:
                pos = snapshot.player_position(pid)
            host = nfl.get(pid) if isinstance(nfl.get(pid), dict) else {}
            age = row.get("age")
            injury = host.get("injury_status") or None
            players.append(
                rc.ValuePlayer(
                    player_id=pid,
                    name=str(row.get("displayName") or row.get("canonicalName") or "")
                    or (snapshot.player_display(pid) if snapshot is not None else ""),
                    position=lineup_position(pos),
                    value=None if raw is None else float(raw),
                    age=None if age is None else float(age),
                    injury=str(injury) if injury else None,
                )
            )
        out[rid] = players
    as_of = meta.get("generatedAt") or contract.get("generatedAt") or meta.get("builtAt")
    return rc.ValueInput(available=True, as_of=None if as_of is None else str(as_of), teams=out)


def build_payload(
    ls: rc.LeagueSeason,
    *,
    league_key: str,
    roster_id: int | None,
    value: rc.ValueInput,
    posture: Mapping[str, Any] | None,
    excluded_weeks_extra: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    si = ls.si
    excluded = list(si.excluded_weeks) + list(excluded_weeks_extra or [])
    payload: dict[str, Any] = {
        "schemaVersion": rc.SCHEMA_VERSION,
        "methodVersion": rc.METHOD_VERSION,
        "leagueKey": league_key,
        "season": si.season,
        "rules": {
            "starterSlots": list(si.slots),
            "slotSource": si.slot_source,
            "lineupMode": si.lineup_mode,
            "lineupBasis": rc.lineup_basis(si.lineup_mode),
            "positionGroups": list(ls.groups),
            "teamCount": len(ls.team_ids),
            "rosterLimit": si.roster_limit,
            "includePlayoffs": si.include_playoffs,
        },
        "coverage": {
            "weeksIncluded": ls.included_weeks,
            "weeksExcluded": sorted(excluded, key=lambda r: r["week"]),
            "contradictedWeeks": [
                {"week": wk, "reasons": list(r)} for wk, r in sorted(si.contradicted.items())
            ],
            "marginalUnavailableReason": si.marginal_unavailable_reason,
        },
        "teams": rc.league_overview(ls)["teams"],
        "valueBlock": {"available": value.available, "reason": value.reason, "asOf": value.as_of},
        "assumptions": rc.assumptions(si),
        "priors": dict(ls.priors),
        "notComputed": {
            "lineupEntryProbability": "Forward-looking LEP is owned by "
            "src/roster_intel/best_ball_utility.py and is not part of V1.",
            "freeAgentPoints": "Weeks a player was on no league roster are not sourced in V1.",
        },
    }
    if roster_id is not None:
        payload.update(rc.build_team_view(ls, roster_id, value, posture=posture))
    return payload
