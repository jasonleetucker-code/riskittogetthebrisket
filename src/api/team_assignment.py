"""Map each fantasy team in the league to 1-3 NFL teams by NFL Team
Affinity — value-weighted roster affinity, not depth-chart points.

Two assignment sources, layered in this priority:

  1. **Favorite team** — declared in ``config/team_assignment.json``
     under ``favorites.<lowercased manager key>``.  Always assigned
     regardless of roster composition.  ``displayNameAliases``
     resolves Sleeper display_name variants ("JasonLeeTucker" ->
     "jason") to the favorites key.  UNCHANGED by this rewrite.

  2. **Roster-based affinity** — the site's EXISTING canonical
     Meaningful Roster Core (``src.roster_intel.core``) and EXISTING
     canonical player values (``rankDerivedValue``, reached via
     ``contract_roster_pools``).  This module never selects players and
     never computes a value; it aggregates what Team Strength's own
     population and values already say, grouped by each player's NFL
     team, with exactly one extra weight: a player who IS his NFL
     team's current starting quarterback counts double.

Formula
-------

For every member of a fantasy team's Meaningful Core::

    multiplier(member) = 2.0  iff member.position == "QB" AND the NFL
                                 depth-chart signal affirmatively shows
                                 depth_chart_order == 1 for his current
                                 NFL team
                        = 1.0  otherwise (backup QB, unknown/stale
                                 signal -- unknown never becomes starter)
    weightedValue(member) = member.canonicalValue * multiplier(member)

    affinityScore(team, nflTeam) = sum(weightedValue) over members whose
                                    NFL team == nflTeam
    totalWeightedCoreValue(team) = sum(weightedValue) over EVERY member,
                                    including members whose NFL team
                                    could not be resolved -- they count
                                    toward the denominator, never toward
                                    any team's numerator
    affinityShare = affinityScore / totalWeightedCoreValue

A non-favorite NFL team qualifies when ``affinityShare >=
rosterAssignmentMinShare`` (default 0.10).  No other position
multipliers exist -- Meaningful Core membership already excludes
players who do not materially contribute, and canonical value already
distinguishes an elite player from a roster-filler one, so a second
"starter" multiplier here would double-count information the core and
the value already carry.

Each fantasy team gets at most ``maxTeamsPerOwner`` (default 3) NFL
teams: the favorite (if configured) plus up to the two highest-
qualifying non-favorites, sorted by (affinityShare desc, affinityScore
desc, NFL abbreviation asc) for determinism.

Truthfulness / degraded states
-------------------------------

Three independent things can be missing, and none of them may read as
a confident answer about something else:

``no_current_season`` / ``no_rosters``
    BLOCKING.  ``available`` is ``False`` and ``assignments`` is empty
    because there was nothing to assign at all.

``rosterScoringAvailable`` (top-level)
    ``False`` when no canonical contract was supplied, or the supplied
    contract's rosters could not be matched against this league at
    all.  Favorites are config-derived and still real, so the section
    stays ``available: True`` -- a favorite-only card must not read as
    "we scored this roster and nothing qualified" when we never had
    the evidence to score it.

Per assignment, ``rosterScored`` / ``rosterUnavailableReason`` cover
the narrower case where the league-wide contract IS usable but THIS
manager's roster specifically could not be matched to a pool (an empty
or colliding Sleeper ``ownerId`` at contract-build time), or that
manager's Meaningful Core itself refused (e.g. the league's starter
slots could not be resolved).

``qbSignalAvailable`` (top-level)
    ``False`` when Sleeper's public NFL player directory was not
    fetched.  This affects ONLY the starting-QB multiplier (every QB
    falls back to 1.0x rather than guessing); it does not block
    roster-based scoring the way a missing contract does.

Per assignment, ``unpricedCount`` names Meaningful-Core-eligible
players the canonical board could not price -- MISSING IS NEVER ZERO,
so those players contribute nothing rather than 0, and the count says
so rather than letting the total look complete.  ``unresolvedNflTeamCount``
does the same for players whose NFL team could not be determined
(including genuine unsigned free agents, who resolve to a real but
non-franchise state and must never be counted as a 33rd NFL team).

Output shape::

    {
      "available": bool,
      "unavailableReason": str | None,
      "rosterScoringAvailable": bool,
      "qbSignalAvailable": bool,
      "degradedReasons": [str, ...],
      "assignments": [
        {
          "ownerId": str,
          "displayName": str,
          "teamName": str,
          "favoriteKey": str | None,
          "rosterScored": bool,
          "rosterUnavailableReason": str | None,
          "scoringComplete": bool,
          "totalWeightedCoreValue": float | None,
          "unpricedCount": int,
          "unresolvedNflTeamCount": int,
          "nflTeams": [
            {
              "abbr": str,
              "display": str,
              "isFavorite": bool,
              "qualifiesByRoster": bool,
              "affinityScore": float,
              "affinityShare": float | None,
              "contributors": [
                {
                  "canonicalName": str,
                  "sleeperPlayerId": str | None,
                  "position": str,
                  "nflTeam": str | None,
                  "role": "starter" | "reserve",
                  "canonicalValue": float,
                  "multiplier": float,
                  "multiplierReason": str,
                  "weightedValue": float,
                },
                ...
              ],
            },
            ...
          ],
        },
        ...
      ],
      "config": {
        "weights": {...},
        "thresholds": {...},
        "limits": {...},
      },
      "currentSeason": str,
      "asOf": str,                    # ISO timestamp
    }
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

from .data_contract import contract_roster_pools, contract_slot_eligibility
from ..public_league.snapshot import PublicLeagueSnapshot
from ..roster_intel.core import MeaningfulCore, build_meaningful_core
from ..roster_intel.exposure import NON_FRANCHISE_TOKENS, nfl_team_by_player

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "team_assignment.json"

# Built-in defaults.  A missing or malformed config file falls back
# to these so the section never crashes -- it just degrades to "no
# favorites configured" + the spec's recommended threshold/multiplier.
_DEFAULT_CONFIG: dict[str, Any] = {
    "favorites": {},
    "displayNameAliases": {},
    # The ONE owner-approved extra weight.  Every RB/WR/TE/IDP multiplier
    # that used to live here (qbAnchor/skillStarter/skillCommittee/
    # rookieRound1/rookieRound2/idpStarter) is retired: Meaningful Core
    # membership already decides who counts, and canonical value already
    # distinguishes how much, so a second per-position weight here would
    # double-count information those two owners already carry.
    "weights": {
        "nflStartingQbMultiplier": 2.0,
    },
    # A SHARE of a manager's total weighted core value, not an absolute
    # point total -- so the threshold does not go stale every time the
    # canonical value scale is refit.  Replaces the old flat
    # ``assignmentMinPoints``.
    "thresholds": {
        "rosterAssignmentMinShare": 0.10,
    },
    "limits": {
        "maxTeamsPerOwner": 3,
    },
}


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read the team-assignment config from disk, falling back to
    defaults on any error.  ``_doc`` keys are stripped silently --
    they're inline documentation in the JSON file, not data.
    """
    target = path or _CONFIG_PATH
    if not target.exists():
        log.info("team_assignment: config not found at %s; using defaults", target)
        return dict(_DEFAULT_CONFIG)
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("team_assignment: config load failed (%s); using defaults", exc)
        return dict(_DEFAULT_CONFIG)
    if not isinstance(raw, dict):
        log.warning("team_assignment: config is not a dict; using defaults")
        return dict(_DEFAULT_CONFIG)
    return _merge_config_with_defaults(raw)


def _merge_config_with_defaults(raw: dict[str, Any]) -> dict[str, Any]:
    """Merge user config over defaults so a partial file still works.
    Strips inline ``_doc`` keys.
    """

    def _strip_doc(d: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in d.items() if k != "_doc"}

    merged: dict[str, Any] = {}
    for key, default_val in _DEFAULT_CONFIG.items():
        user_val = raw.get(key)
        if isinstance(default_val, dict) and isinstance(user_val, dict):
            merged[key] = {**default_val, **_strip_doc(user_val)}
        elif user_val is not None:
            merged[key] = user_val
        else:
            merged[key] = default_val
    # Strip top-level _doc.
    return _strip_doc(merged)


def _resolve_favorite_key(
    display_name: str,
    favorites: dict[str, Any],
    aliases: dict[str, str],
) -> str | None:
    """Map a Sleeper display_name to a favorites key.  Lowercased
    direct match wins; falls back to alias map.  Returns None when
    no favorite is configured for this manager.
    """
    needle = (display_name or "").strip().lower()
    if not needle:
        return None
    if needle in favorites:
        return needle
    aliased = aliases.get(needle)
    if aliased and aliased in favorites:
        return aliased
    return None


def _player_meta(snapshot: PublicLeagueSnapshot, player_id: str | None) -> dict[str, Any]:
    """Look up Sleeper's player record.  Returns ``{}`` when missing
    so callers can early-return.  The lookup tolerates ``None`` and
    non-string ids defensively.
    """
    if not player_id:
        return {}
    p = snapshot.nfl_players.get(str(player_id))
    return p if isinstance(p, dict) else {}


def _depth_chart_order(meta: dict[str, Any]) -> int | None:
    """Sleeper's primary starter-status indicator.  ``None`` when
    unknown -- the caller's heuristic falls through to "unknown", never
    a guess.
    """
    raw = meta.get("depth_chart_order")
    try:
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


#: Machine-readable reasons the section cannot be produced at all.
UNAVAILABLE_NO_CURRENT_SEASON = "no_current_season"
UNAVAILABLE_NO_ROSTERS = "no_rosters"
#: Degraded -- the section is produced, but part of its evidence is absent.
DEGRADED_NO_CONTRACT = "canonical_contract_unavailable"
DEGRADED_NO_QB_SIGNAL = "qb_starter_signal_unavailable"

#: Per-assignment reasons roster-based scoring could not be produced
#: for THIS manager even though the league-wide contract is usable.
ROSTER_REASON_NOT_IN_CONTRACT = "team_not_in_contract_pool"

#: Multiplier reasons, exposed per contributor for the breakdown UI.
_REASON_STARTING_QB = "nfl_starting_qb"
_REASON_BACKUP_QB = "qb_not_starting"
_REASON_QB_UNKNOWN = "starter_status_unknown"
_REASON_NOT_QB = "not_qb"


def _sleeper_id_by_canonical_name(contract: Mapping[str, Any] | None) -> dict[str, str]:
    """``{canonicalOrDisplayName: sleeperPlayerId}`` from the canonical
    board.

    Keyed the same way ``contract_roster_pools`` / ``nfl_team_by_player``
    key players, so this join cannot silently disagree with the pool a
    ``CoreMember`` came from.  A name with no Sleeper id (unmatched
    ``_sleeperId``) is simply absent -- the caller treats that as
    "starter status unknown", never a guess.
    """
    out: dict[str, str] = {}
    if not isinstance(contract, Mapping):
        return out
    for row in contract.get("playersArray") or []:
        if not isinstance(row, Mapping) or row.get("assetClass") == "pick":
            continue
        pid = row.get("playerId")
        if not pid:
            continue
        for key in (row.get("canonicalName"), row.get("displayName")):
            if key:
                out.setdefault(str(key), str(pid))
    return out


def _qb_multiplier(
    *,
    position: str,
    canonical_name: str,
    sleeper_ids: Mapping[str, str],
    snapshot: PublicLeagueSnapshot,
    qb_signal_available: bool,
    weight: float,
) -> tuple[float, str]:
    """The ONE owner-approved extra weight.  Returns ``(multiplier, reason)``.

    Never guesses: a backup QB and an UNKNOWN starter both resolve to
    1.0x, and the reason string distinguishes them for the breakdown UI.
    """
    if position != "QB":
        return 1.0, _REASON_NOT_QB
    if not qb_signal_available:
        return 1.0, _REASON_QB_UNKNOWN
    sleeper_id = sleeper_ids.get(canonical_name)
    if not sleeper_id:
        return 1.0, _REASON_QB_UNKNOWN
    meta = _player_meta(snapshot, sleeper_id)
    if not meta:
        return 1.0, _REASON_QB_UNKNOWN
    depth = _depth_chart_order(meta)
    if depth is None:
        return 1.0, _REASON_QB_UNKNOWN
    if depth == 1:
        return float(weight), _REASON_STARTING_QB
    return 1.0, _REASON_BACKUP_QB


def _unavailable(config: dict[str, Any], reason: str) -> dict[str, Any]:
    """A shaped payload that says WHY it is empty.

    Same field set as the healthy path so the frontend's
    destructure-and-map flow still never hits ``undefined`` -- the
    difference is that ``available: False`` names the cause instead of
    letting an empty list imply one (#815).
    """
    return {
        "available": False,
        "unavailableReason": reason,
        "rosterScoringAvailable": False,
        "qbSignalAvailable": False,
        "degradedReasons": [],
        "assignments": [],
        "config": {
            "weights": config["weights"],
            "thresholds": config["thresholds"],
            "limits": config["limits"],
        },
        "currentSeason": None,
        "asOf": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


class _TeamCore:
    """One manager's resolved Meaningful Core + affinity aggregation,
    or the reason it could not be produced.
    """

    __slots__ = (
        "scored",
        "reason",
        "total_weighted_value",
        "unpriced_count",
        "unresolved_team_count",
        "scoring_complete",
        "by_team_score",
        "by_team_contributors",
    )

    def __init__(self) -> None:
        self.scored = False
        self.reason: str | None = None
        self.total_weighted_value = 0.0
        self.unpriced_count = 0
        self.unresolved_team_count = 0
        self.scoring_complete = False
        self.by_team_score: dict[str, float] = defaultdict(float)
        self.by_team_contributors: dict[str, list[dict[str, Any]]] = defaultdict(list)


def _score_team_core(
    core: MeaningfulCore,
    *,
    team_map: Mapping[str, str],
    sleeper_ids: Mapping[str, str],
    snapshot: PublicLeagueSnapshot,
    qb_signal_available: bool,
    qb_weight: float,
) -> _TeamCore:
    out = _TeamCore()
    if not core.available:
        out.reason = core.unavailable_reason
        return out

    out.scored = True
    out.unpriced_count = len(core.unpriced_ids)
    out.scoring_complete = not (
        core.unpriced_ids or core.unfilled_starter_slots or core.unfilled_reserve_slots
    )

    for member in core.members:
        canonical_name = member.canonical_name or member.player_id
        multiplier, reason = _qb_multiplier(
            position=member.position,
            canonical_name=canonical_name,
            sleeper_ids=sleeper_ids,
            snapshot=snapshot,
            qb_signal_available=qb_signal_available,
            weight=qb_weight,
        )
        weighted = float(member.value) * multiplier
        out.total_weighted_value += weighted

        nfl_team = team_map.get(canonical_name)
        contributor = {
            "canonicalName": canonical_name,
            "sleeperPlayerId": sleeper_ids.get(canonical_name),
            "position": member.position,
            "nflTeam": nfl_team if nfl_team else None,
            "role": member.role,
            "canonicalValue": round(float(member.value), 3),
            "multiplier": multiplier,
            "multiplierReason": reason,
            "weightedValue": round(weighted, 3),
        }

        if not nfl_team or nfl_team in NON_FRANCHISE_TOKENS:
            out.unresolved_team_count += 1
            continue

        out.by_team_score[nfl_team] += weighted
        out.by_team_contributors[nfl_team].append(contributor)

    return out


def build_section(
    snapshot: PublicLeagueSnapshot,
    contract: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the team-assignment payload for the public-league
    aggregate response.  Always emits a fully-shaped payload so the
    frontend's destructure-and-map flow never hits ``undefined``.

    ``contract`` is the internal canonical ``/api/data`` contract
    (``latest_contract_data`` in ``server.py``) -- the SAME source Team
    Strength reads.  ``None`` (or a contract whose rosters cannot be
    matched to this league at all) degrades to a favorites-only
    payload; it never fails the whole section, and it never scores a
    Meaningful-Core-eligible player at 0 -- see the module docstring.

    See the module docstring for the full availability semantics.
    """
    config = load_config()
    favorites = config.get("favorites") or {}
    aliases = {
        k.lower(): v.lower()
        for k, v in (config.get("displayNameAliases") or {}).items()
        if isinstance(k, str) and isinstance(v, str)
    }
    min_share = float(config.get("thresholds", {}).get("rosterAssignmentMinShare", 0.10))
    max_teams = int(config.get("limits", {}).get("maxTeamsPerOwner", 3))
    qb_weight = float(config.get("weights", {}).get("nflStartingQbMultiplier", 2.0))

    season = snapshot.current_season
    if season is None:
        # #815: this branch used to return a bare ``assignments: []``,
        # which is a degraded snapshot presented as a real empty result.
        return _unavailable(config, UNAVAILABLE_NO_CURRENT_SEASON)
    if not season.rosters:
        return _unavailable(config, UNAVAILABLE_NO_ROSTERS)

    qb_signal_available = bool(snapshot.nfl_players)

    # Resolve the canonical contract into per-team Meaningful Cores.
    # A missing/mismatched contract degrades to favorites-only rather
    # than failing the section -- "roster affinity unavailable", never
    # "no roster-based NFL teams" (which would look like a confident
    # empty answer).
    pools: dict[str, list[Any]] = {}
    slots: list[str] = []
    eligibility: dict[str, Any] | None = None
    team_map: dict[str, str] = {}
    sleeper_ids: dict[str, str] = {}
    if isinstance(contract, Mapping) and contract:
        pools, slots, _slot_source = contract_roster_pools(dict(contract))
        eligibility = contract_slot_eligibility(contract) or None
        team_map = nfl_team_by_player(contract)
        sleeper_ids = _sleeper_id_by_canonical_name(contract)

    roster_scoring_available = bool(pools) and bool(slots)

    degraded_reasons: list[str] = []
    if not roster_scoring_available:
        degraded_reasons.append(DEGRADED_NO_CONTRACT)
    if not qb_signal_available:
        degraded_reasons.append(DEGRADED_NO_QB_SIGNAL)

    # Walk every roster in the current season.  Score per (owner,
    # NFL team) pair via the canonical Meaningful Core.
    assignments: list[dict[str, Any]] = []
    for roster in season.rosters:
        if not isinstance(roster, dict):
            continue
        owner_id = str(roster.get("owner_id") or "")
        if not owner_id:
            continue
        manager = snapshot.managers.by_owner_id.get(owner_id)
        display_name = (manager.display_name if manager else "").strip()
        team_name = (manager.current_team_name if manager else "").strip()

        favorite_key = _resolve_favorite_key(display_name, favorites, aliases)
        favorite_entry = favorites.get(favorite_key) if favorite_key else None

        team_core = _TeamCore()
        team_core.reason = DEGRADED_NO_CONTRACT if not roster_scoring_available else None
        pool = pools.get(owner_id) if roster_scoring_available else None
        if roster_scoring_available and pool is None:
            team_core.reason = ROSTER_REASON_NOT_IN_CONTRACT
        elif roster_scoring_available and pool is not None:
            core = build_meaningful_core(pool, slots, slot_eligibility=eligibility)
            team_core = _score_team_core(
                core,
                team_map=team_map,
                sleeper_ids=sleeper_ids,
                snapshot=snapshot,
                qb_signal_available=qb_signal_available,
                qb_weight=qb_weight,
            )

        # Build the NFL-teams list for this owner.
        nfl_teams_out: list[dict[str, Any]] = []
        favorite_abbr: str | None = None

        if favorite_entry:
            fav_abbr = str(favorite_entry.get("abbr") or "").upper()
            fav_display = str(favorite_entry.get("display") or fav_abbr)
            favorite_abbr = fav_abbr
            score = team_core.by_team_score.get(fav_abbr, 0.0)
            share = (
                score / team_core.total_weighted_value
                if team_core.total_weighted_value > 0
                else None
            )
            nfl_teams_out.append(
                {
                    "abbr": fav_abbr,
                    "display": fav_display,
                    "isFavorite": True,
                    "qualifiesByRoster": bool(share is not None and share >= min_share),
                    "affinityScore": round(score, 3),
                    "affinityShare": round(share, 4) if share is not None else None,
                    "contributors": list(team_core.by_team_contributors.get(fav_abbr, [])),
                }
            )

        roster_based = []
        if team_core.total_weighted_value > 0:
            for abbr, score in team_core.by_team_score.items():
                if abbr == favorite_abbr:
                    continue
                share = score / team_core.total_weighted_value
                if share < min_share:
                    continue
                roster_based.append(
                    {
                        "abbr": abbr,
                        "display": _NFL_TEAM_NAMES.get(abbr, abbr),
                        "isFavorite": False,
                        "qualifiesByRoster": True,
                        "affinityScore": round(score, 3),
                        "affinityShare": round(share, 4),
                        "contributors": list(team_core.by_team_contributors.get(abbr, [])),
                    }
                )
        roster_based.sort(key=lambda r: (-r["affinityShare"], -r["affinityScore"], r["abbr"]))

        remaining_capacity = max(0, max_teams - len(nfl_teams_out))
        nfl_teams_out.extend(roster_based[:remaining_capacity])

        assignments.append(
            {
                "ownerId": owner_id,
                "displayName": display_name or team_name or owner_id,
                "teamName": team_name,
                "favoriteKey": favorite_key,
                "rosterScored": team_core.scored,
                "rosterUnavailableReason": None if team_core.scored else team_core.reason,
                "scoringComplete": team_core.scoring_complete,
                "totalWeightedCoreValue": (
                    round(team_core.total_weighted_value, 3) if team_core.scored else None
                ),
                "unpricedCount": team_core.unpriced_count,
                "unresolvedNflTeamCount": team_core.unresolved_team_count,
                "nflTeams": nfl_teams_out,
            }
        )

    # Sort by display name for stable rendering -- alphabetical so
    # the page is predictable across reloads.
    assignments.sort(key=lambda a: a["displayName"].lower())

    return {
        "available": True,
        "unavailableReason": None,
        "rosterScoringAvailable": roster_scoring_available,
        "qbSignalAvailable": qb_signal_available,
        "degradedReasons": degraded_reasons,
        "assignments": assignments,
        "config": {
            "weights": config["weights"],
            "thresholds": config["thresholds"],
            "limits": config["limits"],
        },
        "currentSeason": season.season,
        "asOf": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }


# Canonical 3-letter abbr -> full team name.  Sleeper's player record
# carries the abbreviation; this map is the only place the full name
# is referenced.  The frontend's ``NflTeamLogo`` component takes the
# abbreviation directly so the image side doesn't need this map.
_NFL_TEAM_NAMES: dict[str, str] = {
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}
