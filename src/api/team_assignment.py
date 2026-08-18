"""Map each fantasy team in the league to 1–3 NFL teams.

Two assignment sources, layered in this priority:

  1. **Favorite team** — declared in ``config/team_assignment.json``
     under ``favorites.<lowercased manager key>``.  Always assigned
     regardless of roster composition.  ``displayNameAliases``
     resolves Sleeper display_name variants ("JasonLeeTucker" →
     "jason") to the favorites key.

  2. **Roster-based correlation** — score every (fantasy team,
     NFL team) pair using a tiered point model that rewards
     starting QBs, skill-position starters/committee backs, rookie
     draft capital, and IDP starters.  NFL teams scoring ≥
     ``assignmentMinPoints`` (default 15) qualify.

Each fantasy team gets at most ``maxTeamsPerOwner`` (default 3) NFL
teams.  Favorite always counts toward the cap.  When more teams
qualify than the cap, the highest-scoring non-favorites win.

The section's ``debug`` block carries per-player point contributions
so the UI can render a breakdown panel ("Buffalo Bills — 22 pts:
Josh Allen +10 (QB anchor), Stefon Diggs +5 (Starter), …").

**An empty ``assignments`` list is never the answer to a question we
could not ask** (#815).  The section previously returned
``{"assignments": []}`` with HTTP 200 whenever the snapshot carried no
current season, so a degraded Sleeper fetch rendered identically to a
league that genuinely has no rosters — and the frontend printed a
fabricated diagnosis ("current season has no rosters yet") for a cause
it had not measured.  Availability is now stated explicitly, in the
same ``{"available": bool, "reason": ...}`` shape
``data_contract.stamp_optimal_lineups`` already uses for the lineup
stamp.

Three distinct failure states, deliberately not collapsed:

``no_current_season`` / ``no_rosters``
    Total: ``available`` is ``False`` and ``assignments`` is empty
    because there was nothing to assign, not because nothing qualified.

``player_directory_unavailable``
    PARTIAL.  ``snapshot.nfl_players`` is empty — the ~5 MB Sleeper
    dump failed or was not requested — so no player can be scored
    against an NFL team.  Favorites are config-derived and still real,
    so ``available`` stays ``True`` while ``rosterScoringAvailable`` is
    ``False``.  Without this flag a favorite-only card reads as "we
    scored the roster and nothing cleared the threshold", which is a
    confident claim about evidence we never had.

Per assignment, ``playersResolved`` / ``playersTotal`` report how much
of the roster the directory could actually answer for, so a *partial*
directory is visible too rather than silently lowering every score.

Output shape::

    {
      "available": bool,
      "unavailableReason": str | None,
      "rosterScoringAvailable": bool,
      "degradedReasons": [str, ...],
      "assignments": [
        {
          "ownerId": str,
          "displayName": str,
          "teamName": str,            # current Sleeper team name
          "favoriteKey": str | None,  # which favorites entry was matched
          "rosterScored": bool,       # False ⇒ nflTeams is favorite-only
          "playersResolved": int,     # roster ids the directory answered
          "playersTotal": int,
          "nflTeams": [
            {
              "abbr": str,            # 3-letter abbr, e.g. "KC"
              "display": str,         # "Kansas City Chiefs"
              "isFavorite": bool,
              "score": int,           # 0 for favorite-only when no roster contribution
              "contributors": [
                {"player": str, "points": int, "reason": str},
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
from typing import Any

from ..public_league.snapshot import PublicLeagueSnapshot

log = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "team_assignment.json"

# Built-in defaults.  A missing or malformed config file falls back
# to these so the section never crashes — it just degrades to "no
# favorites configured" + the spec's recommended weights.
_DEFAULT_CONFIG: dict[str, Any] = {
    "favorites": {},
    "displayNameAliases": {},
    # Every weight here is read by ``_score_player``.  The set used to
    # be larger — ``eliteProductionTop10``/``Top24`` and ``idpElite``
    # were declared but the first two paid for a signal the tier above
    # had already paid for (see the T3 note in ``_score_player``) and
    # the third was never read at all.  A declared-but-unread knob is
    # worse than no knob: editing it looks like it does something.
    "weights": {
        "qbAnchor": 10,
        "skillStarter": 5,
        "skillCommittee": 2,
        "rookieRound1": 4,
        "rookieRound2": 2,
        "idpStarter": 2,
    },
    # Likewise the ``*Rank`` thresholds: they described a
    # position-rank model this module never had the data for, and
    # nothing read them.  Starter status comes from Sleeper's
    # ``depth_chart_order``, which needs no threshold.
    "thresholds": {
        "assignmentMinPoints": 15,
    },
    "limits": {
        "maxTeamsPerOwner": 3,
    },
}

_SKILL_POSITIONS = frozenset({"RB", "WR", "TE"})
_IDP_POSITIONS = frozenset({"DL", "DE", "DT", "LB", "DB", "CB", "S"})


def load_config(path: Path | None = None) -> dict[str, Any]:
    """Read the team-assignment config from disk, falling back to
    defaults on any error.  ``_doc`` keys are stripped silently —
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


def _normalize_position(raw: str) -> str:
    """Uppercase + canonical alias fold (DE/DT → DL family kept as
    raw codes; we don't collapse here because ``_IDP_POSITIONS`` and
    ``_SKILL_POSITIONS`` are keyed on the canonical Sleeper code).
    """
    return str(raw or "").strip().upper()


def _player_meta(snapshot: PublicLeagueSnapshot, player_id: str) -> dict[str, Any]:
    """Look up Sleeper's player record.  Returns ``{}`` when missing
    so callers can early-return.  The lookup tolerates ``None`` and
    non-string ids defensively.
    """
    if not player_id:
        return {}
    p = snapshot.nfl_players.get(str(player_id))
    return p if isinstance(p, dict) else {}


def _is_rookie(meta: dict[str, Any]) -> bool:
    """True when the Sleeper record indicates ``years_exp == 0``.
    Falls back to False on missing fields.
    """
    try:
        return int(meta.get("years_exp") or 0) == 0
    except (TypeError, ValueError):
        return False


def _draft_round(meta: dict[str, Any]) -> int | None:
    """Extract NFL draft round from Sleeper's player record.  Returns
    None when unknown.  Used for rookie capital scoring.
    """
    raw = meta.get("draft_round") or meta.get("draftRound")
    try:
        n = int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None
    return n if isinstance(n, int) and n > 0 else None


def _score_player(
    meta: dict[str, Any],
    *,
    config: dict[str, Any],
    league_idp_enabled: bool,
) -> tuple[int, list[dict[str, Any]]]:
    """Score one player against their NFL team.  Returns
    ``(total_points, contributors)`` where contributors is a list of
    ``{points, reason}`` dicts so the debug UI can show the
    breakdown.

    All scoring rules layer additively, and each one pays for a
    DISTINCT signal:
      - QB anchor (T1): primary depth-chart QB → +qbAnchor
      - Skill starter / committee (T2): RB/WR/TE
      - Rookie capital (T4): NFL draft round 1 / 2
      - IDP starter (T5): depth-chart-based, only when league has IDP

    There is no T3.  It was an "elite production" tier that fired on
    ``depth_order == 1`` for QB/RB/WR/TE — the exact condition T1 and
    T2 already pay for — so being primary on the depth chart scored
    twice: a starting RB was worth 8 points where the config reads 5,
    and a starting QB 13 where it reads 10.  Its own comment called it
    a "stand-in" for a top-10/top-24 list, and a stand-in for a signal
    we already have is a double-count, not a proxy.  Reinstating an
    elite tier needs a genuinely independent input (projections, or
    ``canonicalConsensusRank``) — not another read of depth order.
    """
    weights = config["weights"]
    # config["thresholds"] is deliberately not read here.  main's version
    # of this comment described those keys as forward-looking scaffolding
    # for a future canonicalConsensusRank drop-in; that stopped being true
    # in the same change that removed T3 — the *Rank keys went with it
    # because nothing read them (see the T3 note in _score_player and the
    # config's own _doc).  The one threshold in live use,
    # assignmentMinPoints, is read where it is applied.
    pos = _normalize_position(meta.get("position"))
    if not pos:
        return 0, []

    contributors: list[dict[str, Any]] = []
    points = 0

    # Depth-chart order — Sleeper's primary indicator of starter
    # status.  ``None`` when unknown; the heuristic below falls
    # through to "no starter credit".
    order_raw = meta.get("depth_chart_order")
    try:
        depth_order = int(order_raw) if order_raw is not None else None
    except (TypeError, ValueError):
        depth_order = None

    # T1 — QB anchor.
    if pos == "QB" and depth_order == 1:
        pts = int(weights["qbAnchor"])
        points += pts
        contributors.append({"points": pts, "reason": "QB anchor"})

    # T2 — Skill position starter / committee.
    if pos in _SKILL_POSITIONS and depth_order is not None:
        if depth_order == 1:
            pts = int(weights["skillStarter"])
            points += pts
            contributors.append({"points": pts, "reason": f"{pos} starter"})
        elif depth_order in (2, 3):
            pts = int(weights["skillCommittee"])
            points += pts
            contributors.append({"points": pts, "reason": f"{pos} committee"})
        # depth_order >= 4 → 0 (bench / camp body)

    # T4 — Rookie capital.
    if _is_rookie(meta):
        rd = _draft_round(meta)
        if rd == 1:
            pts = int(weights["rookieRound1"])
            points += pts
            contributors.append({"points": pts, "reason": "1st-round rookie"})
        elif rd == 2:
            pts = int(weights["rookieRound2"])
            points += pts
            contributors.append({"points": pts, "reason": "2nd-round rookie"})

    # T5 — IDP starter.
    if league_idp_enabled and pos in _IDP_POSITIONS and depth_order is not None:
        if depth_order == 1:
            pts = int(weights["idpStarter"])
            points += pts
            contributors.append({"points": pts, "reason": f"IDP {pos} starter"})
        # An elite-IDP tier would need projection data we don't carry.
        # Its ``idpElite`` weight was removed from the config rather
        # than left sitting there unread.

    return points, contributors


def _league_idp_enabled(snapshot: PublicLeagueSnapshot) -> bool:
    """Inspect the current season's roster_positions to detect IDP
    slots.  IDP is enabled when any starting slot is in the IDP
    family (DL/LB/DB/IDP_FLEX/etc.).  Falls back to False when
    settings are missing.
    """
    season = snapshot.current_season
    if season is None:
        return False
    raw = season.league.get("roster_positions") or []
    for slot in raw:
        s = str(slot or "").upper()
        if s in _IDP_POSITIONS or s in ("IDP", "IDP_FLEX", "IDP_DL", "IDP_LB", "IDP_DB"):
            return True
    return False


def _player_display(meta: dict[str, Any], pid: str) -> str:
    full = meta.get("full_name")
    if full:
        return str(full)
    first = str(meta.get("first_name") or "").strip()
    last = str(meta.get("last_name") or "").strip()
    name = f"{first} {last}".strip()
    return name or str(pid)


#: Machine-readable reasons the section cannot be produced at all.
UNAVAILABLE_NO_CURRENT_SEASON = "no_current_season"
UNAVAILABLE_NO_ROSTERS = "no_rosters"
#: Degraded — the section is produced, but part of its evidence is absent.
DEGRADED_NO_PLAYER_DIRECTORY = "player_directory_unavailable"


def _unavailable(config: dict[str, Any], reason: str) -> dict[str, Any]:
    """A shaped payload that says WHY it is empty.

    Same field set as the healthy path so the frontend's
    destructure-and-map flow still never hits ``undefined`` — the
    difference is that ``available: False`` names the cause instead of
    letting an empty list imply one (#815).
    """
    return {
        "available": False,
        "unavailableReason": reason,
        "rosterScoringAvailable": False,
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


def build_section(snapshot: PublicLeagueSnapshot) -> dict[str, Any]:
    """Assemble the team-assignment payload for the public-league
    aggregate response.  Always emits a fully-shaped payload so the
    frontend's destructure-and-map flow never hits ``undefined``.

    See the module docstring for the availability semantics: an empty
    ``assignments`` list is only ever a real answer when ``available``
    is ``True``.
    """
    config = load_config()
    favorites = config.get("favorites") or {}
    aliases = {
        k.lower(): v.lower()
        for k, v in (config.get("displayNameAliases") or {}).items()
        if isinstance(k, str) and isinstance(v, str)
    }
    threshold = int(config.get("thresholds", {}).get("assignmentMinPoints", 15))
    max_teams = int(config.get("limits", {}).get("maxTeamsPerOwner", 3))
    idp_enabled = _league_idp_enabled(snapshot)

    season = snapshot.current_season
    if season is None:
        # #815: this branch used to return a bare ``assignments: []``,
        # which is a degraded snapshot presented as a real empty result.
        return _unavailable(config, UNAVAILABLE_NO_CURRENT_SEASON)
    if not season.rosters:
        return _unavailable(config, UNAVAILABLE_NO_ROSTERS)

    # Roster-based scoring needs Sleeper's player directory.  It is
    # fetched on a separate future that falls back to ``{}`` on error
    # (``snapshot.build`` swallows the exception), and tests / cheap
    # callers pass ``include_nfl_players=False`` — so "no directory" is
    # a REACHABLE state that scores every player zero.  Detected up
    # front rather than inferred from a run of zeros.
    roster_scoring_available = bool(snapshot.nfl_players)
    degraded_reasons: list[str] = (
        [] if roster_scoring_available else [DEGRADED_NO_PLAYER_DIRECTORY]
    )

    # Walk every roster in the current season.  Score per (owner,
    # NFL team) pair.  Track contributors so the breakdown panel can
    # render the per-player point list.
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

        # Aggregator: nfl_team_abbr -> (score, contributors_list).
        scored: dict[str, dict[str, Any]] = defaultdict(lambda: {"score": 0, "contributors": []})

        player_ids = roster.get("players") or []
        players_resolved = 0
        for pid in player_ids:
            meta = _player_meta(snapshot, pid)
            if not meta:
                continue
            players_resolved += 1
            nfl_team = str(meta.get("team") or "").upper()
            if not nfl_team:
                continue
            pts, contributors = _score_player(
                meta,
                config=config,
                league_idp_enabled=idp_enabled,
            )
            if pts <= 0:
                continue
            slot = scored[nfl_team]
            slot["score"] += pts
            display = _player_display(meta, pid)
            for c in contributors:
                slot["contributors"].append(
                    {
                        "player": display,
                        "points": int(c["points"]),
                        "reason": str(c["reason"]),
                    }
                )

        # Build the NFL-teams list for this owner.
        nfl_teams_out: list[dict[str, Any]] = []

        # 1. Always emit the favorite (with whatever roster score it earned).
        if favorite_entry:
            fav_abbr = str(favorite_entry.get("abbr") or "").upper()
            fav_display = str(favorite_entry.get("display") or fav_abbr)
            slot = scored.get(fav_abbr, {"score": 0, "contributors": []})
            nfl_teams_out.append(
                {
                    "abbr": fav_abbr,
                    "display": fav_display,
                    "isFavorite": True,
                    "score": int(slot["score"]),
                    "contributors": list(slot["contributors"]),
                }
            )

        # 2. Roster-based qualifiers — anyone else above threshold,
        #    sorted by score desc.  Skip the favorite (already added).
        favorite_abbr = nfl_teams_out[0]["abbr"] if nfl_teams_out else None
        roster_based = sorted(
            (
                {
                    "abbr": abbr,
                    "display": _NFL_TEAM_NAMES.get(abbr, abbr),
                    "isFavorite": False,
                    "score": int(slot["score"]),
                    "contributors": list(slot["contributors"]),
                }
                for abbr, slot in scored.items()
                if abbr != favorite_abbr and slot["score"] >= threshold
            ),
            key=lambda r: (-int(r["score"]), r["abbr"]),
        )

        # 3. Cap at max_teams total (favorite counts).
        remaining_capacity = max(0, max_teams - len(nfl_teams_out))
        nfl_teams_out.extend(roster_based[:remaining_capacity])

        assignments.append(
            {
                "ownerId": owner_id,
                "displayName": display_name or team_name or owner_id,
                "teamName": team_name,
                "favoriteKey": favorite_key,
                # A favorite-only card must not read as "we scored this
                # roster and nothing qualified" when we could not score
                # it at all.
                "rosterScored": roster_scoring_available,
                "playersResolved": players_resolved,
                "playersTotal": len(player_ids),
                "nflTeams": nfl_teams_out,
            }
        )

    # Sort by display name for stable rendering — alphabetical so
    # the page is predictable across reloads.
    assignments.sort(key=lambda a: a["displayName"].lower())

    return {
        "available": True,
        "unavailableReason": None,
        "rosterScoringAvailable": roster_scoring_available,
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
