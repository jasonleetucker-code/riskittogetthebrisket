"""Map each fantasy team in the league to a FIXED 5 NFL teams by NFL
Team Affinity — value-weighted roster affinity, not depth-chart points,
and not a percentage threshold.

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

Per-manager scoring formula (unchanged by this rewrite)
---------------------------------------------------------

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

No other position multipliers exist -- Meaningful Core membership
already excludes players who do not materially contribute, and
canonical value already distinguishes an elite player from a
roster-filler one, so a second "starter" multiplier here would
double-count information the core and the value already carry.

Selection: coverage-maximizing, not threshold-gated (2026-09-01)
-------------------------------------------------------------------

A flat percentage threshold (``affinityShare >= X%``) was tried and
retired: it answers "is this NFL team a large share of everything this
manager owns", which is denominator-sensitive and not the question
that matters -- a manager can legitimately own a team's starting QB
and several of its best assets and still fall under any fixed
percentage simply because their overall roster is large and
well-rounded.  MEASURED on the live league: exactly this happened
(a manager holding a real NFL team's starting QB and multiple of its
top assets scored under a 10% share and was silently excluded).

The replacement, owner-mandated and LOCKED IN (not configurable):
every manager gets exactly ``1 (favorite, if configured) + up to
_NON_FAVORITE_TEAMS_PER_OWNER (4)`` NFL teams, chosen by
``_assign_coverage_maximizing_teams`` in two steps, run ONCE across
the whole league after every manager's ``affinityScore`` is known:

  1. **Natural top-4** -- each manager's own 4 highest-``affinityScore``
     non-favorite teams (ties broken toward whoever holds that team's
     starting QB, then NFL abbreviation ascending).
  2. **Coverage repair** -- a single deterministic pass that finds
     which of the 32 real NFL teams remain unrepresented by ANYONE in
     the league (no manager's favorite, no manager's natural top-4),
     and swaps each such gap onto the single best-fit manager who has
     real (nonzero) affinity for it, donating that manager's weakest
     natural slot -- but ONLY when the donated team stays covered by
     someone else afterward (never trade one gap for a new one), and
     ONLY a ``"top_affinity"`` slot may ever be donated (a repaired
     slot is never later evicted, which is what makes one pass
     sufficient).  If the best-fit manager cannot safely donate any
     slot, the next-best-fit manager is tried.  A tie between two
     candidate managers for the same team is broken toward whoever
     holds that team's starting QB -- verbatim owner instruction:
     "ties go to who has the quarterback."

  Two invariants hold no matter what: **a team is never assigned to a
  manager with zero affinity for it**, even to pad a coverage count
  (a team nobody in the league owns any Meaningful-Core player from
  is reported in ``uncoverableTeams``, never faked); and **a manager
  is never reduced below the real teams they have** just to improve
  someone else's coverage -- the repair pass only ever SWAPS a
  manager's own slot, never removes one to leave them short, and it
  backs off to ``unresolvedCoverageGaps`` rather than stranding
  anyone (expected empty on real league data; see the function's
  docstring for the termination argument).

  ``qualifiesByRoster`` on a non-favorite entry is therefore always
  ``True`` once assigned (nothing zero-affinity is ever placed) --
  the field survives from the retired-threshold era for the favorite
  entry, where it still distinguishes a favorite backed by real roster
  value from one that is not.

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
              "assignmentReason": "favorite" | "top_affinity" | "coverage_repair",
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
      "uncoverableTeams": [str, ...],       # real NFL abbrs with ZERO
                                             # affinity anywhere in the
                                             # league -- never assigned
      "unresolvedCoverageGaps": [str, ...], # real affinity exists but
                                             # this pass could not place
                                             # it without stranding a
                                             # manager -- expected empty
      "coverageSummary": {
        "totalNflTeams": int,               # 32
        "coveredTeams": int,
        "uncoverableCount": int,
        "unresolvedGapCount": int,
      },
      "config": {
        "weights": {...},
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
    "limits": {},
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

#: Fixed, owner-locked count of non-favorite NFL teams per manager
#: ("I want this behavior to be locked in") -- deliberately a code
#: constant, not a config knob.
_NON_FAVORITE_TEAMS_PER_OWNER = 4

#: Per-team assignment-reason tags, exposed for UI transparency (same
#: spirit as ``multiplierReason``): WHY a team is on a manager's list.
_REASON_FAVORITE = "favorite"
_REASON_TOP_AFFINITY = "top_affinity"
_REASON_COVERAGE_REPAIR = "coverage_repair"


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
        "uncoverableTeams": [],
        "unresolvedCoverageGaps": [],
        "coverageSummary": {
            "totalNflTeams": len(_NFL_TEAM_NAMES),
            "coveredTeams": 0,
            "uncoverableCount": 0,
            "unresolvedGapCount": 0,
        },
        "config": {
            "weights": config["weights"],
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


def _holds_starting_qb(core: _TeamCore, abbr: str) -> bool:
    """Rule 5's tiebreak signal: does this manager's Meaningful Core
    include this NFL team's CONFIRMED current starting QB.  Reads the
    already-computed ``multiplierReason`` -- never re-derives it.
    """
    return any(
        c.get("multiplierReason") == _REASON_STARTING_QB
        for c in core.by_team_contributors.get(abbr, [])
    )


def _assign_coverage_maximizing_teams(
    owner_ids: list[str],
    scores: dict[str, dict[str, float]],
    holds_qb: dict[str, dict[str, bool]],
    favorite_abbrs: dict[str, str | None],
    *,
    all_teams: frozenset[str] = frozenset(),
    slots_per_owner: int = _NON_FAVORITE_TEAMS_PER_OWNER,
) -> tuple[dict[str, list[dict[str, Any]]], list[str], list[str]]:
    """Cross-manager, coverage-maximizing NFL-team selection.  Runs
    ONCE, after every manager's per-team ``affinityScore`` is known.

    Pure function over plain dicts -- no ``_TeamCore``/snapshot
    dependency, so it is independently testable without full
    contract/snapshot fixtures.

    Two-phase design:

      1. **Natural top-4** -- each owner's ``slots_per_owner`` highest
         ``affinityScore`` non-favorite teams (ties: QB-holder wins,
         then abbr ascending).
      2. **Coverage repair, single forward pass** -- every real NFL
         team not covered by ANY favorite or ANY owner's natural top-4
         is a "gap".  Gaps are processed most-confident-first (highest
         best-available score across the whole league).  For each gap
         team, candidate owners (real nonzero affinity for it) are
         tried best-score-first (QB-holder wins ties); the first
         candidate who can safely donate one of their OWN natural
         slots -- i.e. the donated team stays covered by someone else
         afterward -- takes the gap team in that slot.  A donated slot
         is chosen weakest-first (QB-holder loses this internal sort,
         so a QB-backed team is the last thing donated).

      Only ``"top_affinity"`` slots are ever donor-eligible -- a
      ``"coverage_repair"`` slot, once placed, is never later evicted.
      That is what makes a SINGLE pass sufficient: each successful
      repair strictly increases total coverage by exactly one team (a
      valid donation requires the donated team to remain covered
      elsewhere, so coverage never regresses), coverage is bounded by
      ``len(all_teams)``, and the gap list is fixed and finite -- so
      the pass always terminates and never oscillates.  It is a
      deliberate greedy heuristic, not a formally-optimal matching
      solver (an exhaustive augmenting-path search could occasionally
      find a chained re-donation this cannot) -- acceptable per the
      owner's explicit direction that this does not need to be
      provably optimal.  A gap this pass cannot place without
      stranding a manager below their real candidate count is reported
      in ``unresolved_gap_teams`` rather than forced -- expected to be
      empty on real league data (12 managers can supply up to 60
      team-slots against a 32-team universe).

    Invariants, both structural (never violated even under weird
    input): a team is NEVER assigned to an owner with
    ``scores[owner].get(abbr, 0) <= 0`` for it, even to pad coverage;
    an owner is NEVER left with fewer non-favorite teams than they
    started with in phase 1 (repair only swaps, never removes without
    replacing).

    Args:
        owner_ids: every owner to consider, in a FIXED, caller-sorted
            order -- output must not depend on dict iteration order.
        scores: ``{ownerId: {abbr: affinityScore}}``, positive-only
            (an owner/abbr pair the owner has zero affinity for should
            simply be absent, not present at 0).
        holds_qb: ``{ownerId: {abbr: bool}}``, keys a subset of (or
            equal to) ``scores[ownerId]``'s keys.
        favorite_abbrs: ``{ownerId: abbr | None}``.
        all_teams: the full universe of real NFL team abbreviations to
            evaluate coverage against.  Empty by default so a caller
            who forgets it fails loudly rather than silently checking
            coverage against nothing; ``build_section`` always passes
            ``frozenset(_NFL_TEAM_NAMES)``.
        slots_per_owner: non-favorite team count per owner.

    Returns:
        ``(non_favorite_by_owner, uncoverable_teams, unresolved_gap_teams)``.
        ``non_favorite_by_owner[ownerId]`` is a list (length <=
        ``slots_per_owner``) of ``{"abbr", "score", "holdsQb", "reason"}``
        dicts, ``reason`` one of ``_REASON_TOP_AFFINITY`` /
        ``_REASON_COVERAGE_REPAIR``.  ``uncoverable_teams`` -- real NFL
        teams with ZERO affinity anywhere in the league (never
        assigned to anyone).  ``unresolved_gap_teams`` -- real,
        nonzero-affinity teams this pass could not place; both lists
        are sorted and disjoint from each other and from every
        assigned team.
    """
    natural: dict[str, list[dict[str, Any]]] = {}
    for oid in owner_ids:
        fav = favorite_abbrs.get(oid)
        owner_scores = scores.get(oid) or {}
        owner_qb = holds_qb.get(oid) or {}
        candidates = [
            {"abbr": abbr, "score": score, "holdsQb": bool(owner_qb.get(abbr))}
            for abbr, score in owner_scores.items()
            if abbr != fav and score > 0
        ]
        candidates.sort(key=lambda c: (-c["score"], not c["holdsQb"], c["abbr"]))
        natural[oid] = [dict(c, reason=_REASON_TOP_AFFINITY) for c in candidates[:slots_per_owner]]

    covered: set[str] = {abbr for abbr in favorite_abbrs.values() if abbr}
    for oid in owner_ids:
        covered.update(c["abbr"] for c in natural[oid])

    league_wide: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for oid in owner_ids:
        owner_scores = scores.get(oid) or {}
        owner_qb = holds_qb.get(oid) or {}
        for abbr, score in owner_scores.items():
            if score > 0:
                league_wide[abbr].append(
                    {"ownerId": oid, "score": score, "holdsQb": bool(owner_qb.get(abbr))}
                )

    uncoverable = sorted(
        abbr for abbr in all_teams if abbr not in covered and abbr not in league_wide
    )
    gaps = [abbr for abbr in all_teams if abbr not in covered and abbr in league_wide]

    def _best_score(abbr: str) -> float:
        return max(entry["score"] for entry in league_wide[abbr])

    gaps.sort(key=lambda abbr: (-_best_score(abbr), abbr))

    def _covered_without(oid: str, abbr: str) -> bool:
        """Would ``abbr`` still be covered if it were removed from
        ``oid``'s assigned list (favorite or any OTHER owner's list)?
        """
        if abbr in favorite_abbrs.values():
            return True
        return any(
            other != oid and any(c["abbr"] == abbr for c in natural[other]) for other in owner_ids
        )

    unresolved: list[str] = []
    for gap_abbr in gaps:
        candidates = sorted(
            league_wide[gap_abbr], key=lambda e: (-e["score"], not e["holdsQb"], e["ownerId"])
        )
        placed = False
        for cand in candidates:
            oid = cand["ownerId"]
            slots = natural[oid]
            donors = [i for i, s in enumerate(slots) if s["reason"] == _REASON_TOP_AFFINITY]
            donors.sort(
                key=lambda i: (slots[i]["score"], not slots[i]["holdsQb"], slots[i]["abbr"])
            )
            for i in donors:
                donated_abbr = slots[i]["abbr"]
                if _covered_without(oid, donated_abbr):
                    slots[i] = {
                        "abbr": gap_abbr,
                        "score": cand["score"],
                        "holdsQb": cand["holdsQb"],
                        "reason": _REASON_COVERAGE_REPAIR,
                    }
                    placed = True
                    break
            if placed:
                break
        if not placed:
            unresolved.append(gap_abbr)

    for oid in owner_ids:
        natural[oid].sort(key=lambda c: (-c["score"], c["abbr"]))

    return natural, uncoverable, sorted(unresolved)


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

    # Phase 1 -- score every owner's Meaningful Core (unchanged from the
    # prior rewrite).  Collected rather than rendered inline, because
    # team SELECTION (phase 2, below) needs every owner's scores at
    # once -- it is a cross-manager, whole-league step, not a per-owner
    # one.
    owner_meta: dict[str, dict[str, Any]] = {}
    owner_cores: dict[str, _TeamCore] = {}
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
        favorite_abbr = str(favorite_entry.get("abbr") or "").upper() if favorite_entry else None
        favorite_display = (
            str(favorite_entry.get("display") or favorite_abbr) if favorite_entry else None
        )

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

        owner_meta[owner_id] = {
            "displayName": display_name or team_name or owner_id,
            "teamName": team_name,
            "favoriteKey": favorite_key,
            "favoriteAbbr": favorite_abbr,
            "favoriteDisplay": favorite_display,
        }
        owner_cores[owner_id] = team_core

    # Phase 2 -- one cross-manager, coverage-maximizing selection pass.
    # See ``_assign_coverage_maximizing_teams`` and the module docstring
    # for the algorithm.
    owner_ids_sorted = sorted(owner_meta)
    favorite_abbrs = {oid: owner_meta[oid]["favoriteAbbr"] for oid in owner_ids_sorted}
    scores_by_owner = {
        oid: {a: s for a, s in owner_cores[oid].by_team_score.items() if s > 0}
        for oid in owner_ids_sorted
        if owner_cores[oid].scored
    }
    holds_qb_by_owner = {
        oid: {a: _holds_starting_qb(owner_cores[oid], a) for a in scores_by_owner.get(oid, {})}
        for oid in owner_ids_sorted
        if owner_cores[oid].scored
    }
    non_fav_by_owner, uncoverable_teams, unresolved_gap_teams = _assign_coverage_maximizing_teams(
        owner_ids_sorted,
        scores_by_owner,
        holds_qb_by_owner,
        favorite_abbrs,
        all_teams=frozenset(_NFL_TEAM_NAMES),
    )

    # Phase 3 -- render.  Favorite entry keeps its historical shape;
    # non-favorite entries come straight from the selection result.
    assignments: list[dict[str, Any]] = []
    for owner_id in owner_ids_sorted:
        meta = owner_meta[owner_id]
        team_core = owner_cores[owner_id]
        fav_abbr = meta["favoriteAbbr"]

        nfl_teams_out: list[dict[str, Any]] = []
        if fav_abbr:
            score = team_core.by_team_score.get(fav_abbr, 0.0)
            share = (
                score / team_core.total_weighted_value
                if team_core.total_weighted_value > 0
                else None
            )
            nfl_teams_out.append(
                {
                    "abbr": fav_abbr,
                    "display": meta["favoriteDisplay"],
                    "isFavorite": True,
                    "qualifiesByRoster": score > 0,
                    "assignmentReason": _REASON_FAVORITE,
                    "affinityScore": round(score, 3),
                    "affinityShare": round(share, 4) if share is not None else None,
                    "contributors": list(team_core.by_team_contributors.get(fav_abbr, [])),
                }
            )

        for entry in non_fav_by_owner.get(owner_id, []):
            abbr = entry["abbr"]
            score = entry["score"]
            share = (
                score / team_core.total_weighted_value
                if team_core.total_weighted_value > 0
                else None
            )
            nfl_teams_out.append(
                {
                    "abbr": abbr,
                    "display": _NFL_TEAM_NAMES.get(abbr, abbr),
                    "isFavorite": False,
                    "qualifiesByRoster": True,
                    "assignmentReason": entry["reason"],
                    "affinityScore": round(score, 3),
                    "affinityShare": round(share, 4) if share is not None else None,
                    "contributors": list(team_core.by_team_contributors.get(abbr, [])),
                }
            )

        assignments.append(
            {
                "ownerId": owner_id,
                "displayName": meta["displayName"],
                "teamName": meta["teamName"],
                "favoriteKey": meta["favoriteKey"],
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

    total_teams = len(_NFL_TEAM_NAMES)
    covered_count = total_teams - len(uncoverable_teams) - len(unresolved_gap_teams)

    return {
        "available": True,
        "unavailableReason": None,
        "rosterScoringAvailable": roster_scoring_available,
        "qbSignalAvailable": qb_signal_available,
        "degradedReasons": degraded_reasons,
        "assignments": assignments,
        "uncoverableTeams": uncoverable_teams,
        "unresolvedCoverageGaps": unresolved_gap_teams,
        "coverageSummary": {
            "totalNflTeams": total_teams,
            "coveredTeams": covered_count,
            "uncoverableCount": len(uncoverable_teams),
            "unresolvedGapCount": len(unresolved_gap_teams),
        },
        "config": {
            "weights": config["weights"],
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
