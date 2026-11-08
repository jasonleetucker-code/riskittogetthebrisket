"""What playoff bracket does this league actually play?

Why this exists
───────────────
Two simulators answer "will this team make the playoffs", and until
2026-08-19 they disagreed about the question:

* ``src.public_league.playoff_odds`` read ``settings.playoff_teams`` and
  silently fell back to **6** when it was absent;
* ``src.ros.playoff_sim`` never read the setting at all — its
  ``playoff_seeds: int = 6`` / ``bye_seeds: int = 2`` were hardcoded
  defaults and **no caller overrode them**.

Measured 2026-08-19 against the live league
(``GET /v1/league/1312006700437352448``)::

    playoff_teams: 7      playoff_seed_type: 1
    playoff_type:  1      playoff_week_start: 15

So the private engine has been simulating a **six**-seed bracket for a
league that takes **seven**. On a 12-team league that is the whole
difference between sixth and seventh place mattering, and it moves every
team's odds and the entire championship simulation downstream of it.

That is not benign duplication. Two owners of one league rule, one of
them wrong, is what this module removes: the bracket is resolved once,
from the league's own settings, and both simulators consume it.

Byes are DERIVED, not configured
────────────────────────────────
A single-elimination bracket is padded to the next power of two, and the
teams that would have played the empty slots get the byes:

    byes = next_power_of_two(teams) - teams

That reproduces the pair the code already hardcoded — 6 teams → 2 byes —
which is the evidence that it is a generalisation of the existing
behaviour rather than a new invention. It also gives 7 → 1, which is
what the live league plays and what no constant could have produced.

Sleeper's ``playoff_type`` (0 single-elimination, 1 with a third-place
game, 2 two-week rounds) changes how rounds are *scheduled*, not how
many teams qualify or sit out round one, so it is deliberately not
modelled here.

Re-seeding vs a fixed bracket is READ, not assumed (C5-PLAY-01 review B2)
──────────────────────────────────────────────────────────────────────
Sleeper's ``playoff_seed_type`` decides who meets whom after round one:

* ``1`` — **re-seed**: every round the best surviving seed meets the worst;
* ``0`` — **fixed bracket**: the standard power-of-two bracket, byes going
  to the top seeds, pairings never redrawn.  For six teams that is
  1 vs winner(4/5) and 2 vs winner(3/6) — exactly what Sleeper generated
  for ``dynasty_new`` in 2025 and 2026 (``winners_bracket``: round-two
  matches take ``t2_from: {w: 1}`` / ``{w: 2}``), and for five teams 1 vs
  winner(4/5), 2 vs 3 (``dynasty_main`` 2025).

Measured 2026-10-07: ``dynasty_main`` publishes ``1`` and ``dynasty_new``
``0``.  The canonical engine re-seeded both until this was read.  Any
other value (or none) is UNKNOWN: the bracket's pairings cannot be
reproduced, so title odds fail closed (``seed_type is None`` with
``seed_type_reason``) while qualifying — which seeding does not affect —
still resolves.

Divisions: the LEAGUE'S recorded rule decides (owner, 2026-11-08)
───────────────────────────────────────────────────────────────
Sleeper's ``settings.divisions`` splits a league into divisions.  Sleeper's
default qualifies every division winner ("If there are divisions, then each
division winner will qualify for the playoffs",
https://sleeper.com/blog/how-do-fantasy-playoffs-work), but leagues do not all
play that way, and the host settings cannot say which way a league plays.
CW-49 (2026-11-07) therefore refused EVERY league with divisions ON; the owner
corrected that on 2026-11-08: in ``dynasty_main`` divisions decide the
schedule and a separate division-champion payout ONLY — the seven best overall
records qualify, seeded by overall record, standings ties broken by most
points scored, no automatic berth, no seeding advantage, no bye.

So whether divisions touch qualifying is a per-league FACT recorded in
``config/leagues/playoff_rules.json`` (:func:`league_playoff_rules`), never a
universal assumption in either direction:

* a league whose record says ``divisionPlayoffEffect: "none"`` is simulated on
  overall record whatever the host setting says
  (:attr:`PlayoffStructure.division_rule` ``"recorded_no_playoff_effect"``);
* a league with divisions ON and no record keeps the host default, which this
  engine does not model (the seeding of division winners against wild cards is
  unverified): :attr:`PlayoffStructure.division_qualification_unknown` is True
  and qualifying, seeding and title odds are refused with a named reason —
  draft-slot odds, which follow the regular-season record only, are not.

Measured: the live ``dynasty_main`` stated ``divisions: 3`` on 2026-10-26
(``docs/audits/evidence/league_rules_dynasty_main_2026-10-26.json``) and
``divisions: 0`` on 2026-11-08 while its rosters still carry division 1-3.
``0`` is off.  An ABSENT setting is read as no divisions: the host states a
count only for a league that configured divisions (``dynasty_new`` omits the
key); a present value that is not a non-negative integer is unrecognised.

Division CHAMPIONS are a separate question from qualifying
(:func:`resolve_division_assignments`): they need each team's division (the
roster's ``settings.division``) and the league's recorded champion rule.  A
division champion can miss the playoffs and a non-champion can qualify; the
two probabilities are never merged.

Missing is never six
────────────────────
A league that does not publish ``playoff_teams`` has an UNKNOWN bracket,
and :func:`resolve_playoff_structure` says so rather than substituting a
number. Publishing playoff probabilities computed under a format nobody
verified is the same failure class as scoring a season under another
season's card: the output looks completely ordinary and is answering a
different question. Callers must branch on :attr:`PlayoffStructure.known`
and report unavailable — both simulators already have that shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

__all__ = [
    "DIVISION_RULE_NONE",
    "DIVISION_RULE_RECORDED",
    "DIVISION_RULE_UNRECORDED",
    "SEED_TYPE_FIXED",
    "SEED_TYPE_RESEED",
    "DivisionAssignments",
    "LeaguePlayoffRules",
    "PlayoffStructure",
    "byes_for_teams",
    "league_playoff_rules",
    "resolve_division_assignments",
    "resolve_playoff_structure",
]

_RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "leagues" / "playoff_rules.json"

#: :attr:`PlayoffStructure.division_rule` values.
#: the host plays no divisions (setting absent or 0), whatever the record says
DIVISION_RULE_NONE = "no_divisions"
#: the league's record says divisions do not touch qualifying or seeding
DIVISION_RULE_RECORDED = "recorded_no_playoff_effect"
#: divisions are ON (or unreadable) and the league has no record — host default
DIVISION_RULE_UNRECORDED = "unrecorded"

#: The only rule values this engine can play.  Anything else in the record is
#: a rule it does not model, and the league is treated as having no record.
_QUALIFICATION_RULES = {"overall_record"}
_SEEDING_RULES = {"overall_record"}
_TIEBREAKERS = ("points_for",)
_CHAMPION_RULES = {"best_overall_record_in_division"}


@dataclass(frozen=True)
class LeaguePlayoffRules:
    """One league's recorded qualification / seeding / division rules."""

    league_key: str
    qualification: str
    seeding: str
    standings_tiebreakers: tuple[str, ...]
    division_count: int | None
    #: ``"none"``: divisions never affect qualifying or seeding.
    division_playoff_effect: str
    division_champion: str | None
    division_champion_tiebreakers: tuple[str, ...]
    approved_at: str

    @property
    def divisions_affect_playoffs(self) -> bool:
        return self.division_playoff_effect != "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualification": self.qualification,
            "seeding": self.seeding,
            "standingsTiebreakers": list(self.standings_tiebreakers),
            "divisionCount": self.division_count,
            "divisionPlayoffEffect": self.division_playoff_effect,
            "divisionChampion": self.division_champion,
            "divisionChampionTiebreakers": list(self.division_champion_tiebreakers),
            "approvedAt": self.approved_at,
        }


@lru_cache(maxsize=8)
def _read_rules_file(path: str, mtime_ns: int) -> Any:
    """The parsed rules file, cached per (path, mtime) — the structure is
    resolved on every cached-forecast check, so the file is read once per
    edit rather than once per request.  ``None`` when unreadable."""
    del mtime_ns  # part of the cache key only
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def league_playoff_rules(
    league_key: str | None, *, path: Path | None = None
) -> LeaguePlayoffRules | None:
    """The league's recorded playoff rules, or ``None`` when it has none.

    A record this engine cannot play (an unknown qualification rule, a
    tiebreaker other than Points For, an unrecognised division effect) is
    treated as NO record — the league then fails closed exactly as an
    unrecorded league does, rather than being simulated under a rule nobody
    stated.  An unreadable file is no record too.
    """
    if not league_key:
        return None
    rules_path = path or _RULES_PATH
    try:
        mtime = rules_path.stat().st_mtime_ns
    except OSError:
        return None
    data = _read_rules_file(str(rules_path), mtime)
    entry = (data.get("rules") or {}).get(str(league_key)) if isinstance(data, Mapping) else None
    if not isinstance(entry, Mapping):
        return None
    tiebreakers = tuple(entry.get("standingsTiebreakers") or ())
    champ_tiebreakers = tuple(entry.get("divisionChampionTiebreakers") or ())
    effect = entry.get("divisionPlayoffEffect")
    champion = entry.get("divisionChampion")
    count = _whole_count_or_none(entry.get("divisionCount"))
    if (
        entry.get("qualification") not in _QUALIFICATION_RULES
        or entry.get("seeding") not in _SEEDING_RULES
        or tiebreakers != _TIEBREAKERS
        or effect != "none"
        or (champion is not None and champion not in _CHAMPION_RULES)
        or (champion is not None and champ_tiebreakers != _TIEBREAKERS)
        or (count is not None and count < 1)
    ):
        return None
    return LeaguePlayoffRules(
        league_key=str(league_key),
        qualification=str(entry["qualification"]),
        seeding=str(entry["seeding"]),
        standings_tiebreakers=tiebreakers,
        division_count=count,
        division_playoff_effect=str(effect),
        division_champion=str(champion) if champion is not None else None,
        division_champion_tiebreakers=champ_tiebreakers if champion is not None else (),
        approved_at=str(entry.get("approvedAt") or ""),
    )


#: Reason codes, so an unavailable bracket says WHICH way it failed.
REASON_NO_SEASON = "no_current_season"
REASON_NO_SETTINGS = "league_has_no_settings_block"
REASON_NO_PLAYOFF_TEAMS = "league_settings_omit_playoff_teams"
REASON_IMPLAUSIBLE = "playoff_teams_outside_a_plausible_range"
REASON_NO_SEED_TYPE = "league_settings_omit_playoff_seed_type"
REASON_UNKNOWN_SEED_TYPE = "playoff_seed_type_not_recognised"
REASON_UNKNOWN_DIVISIONS = "divisions_setting_not_recognised"

#: ``playoff_seed_type`` -> bracket rule.  Only the two values the host
#: documents in its settings UI (default / re-seed) are recognised.
SEED_TYPE_FIXED = "fixed"
SEED_TYPE_RESEED = "reseed"
_SEED_TYPES = {0: SEED_TYPE_FIXED, 1: SEED_TYPE_RESEED}

#: A bracket smaller than two cannot be played, and one larger than the
#: league cannot be filled.  Both are refusals rather than clamps: a
#: clamp would turn a corrupt setting into a confident simulation.
_MIN_TEAMS = 2
_MAX_TEAMS = 32


def byes_for_teams(teams: int) -> int:
    """First-round byes in a bracket of ``teams``, padded to a power of two."""
    n = int(teams)
    if n < _MIN_TEAMS:
        raise ValueError(f"a bracket needs at least {_MIN_TEAMS} teams, got {n}")
    size = 1
    while size < n:
        size *= 2
    return size - n


@dataclass(frozen=True)
class PlayoffStructure:
    """The league's own bracket, or an explicit statement that it is unknown."""

    teams: int | None
    byes: int | None
    week_start: int | None
    source: str
    reason: str = ""
    #: ``"reseed"`` / ``"fixed"`` from ``playoff_seed_type``, or ``None`` when
    #: the league does not say (``seed_type_reason`` names why).  Affects the
    #: bracket only — qualifying (``known``) does not depend on it.
    seed_type: str | None = None
    seed_type_reason: str = ""
    #: ``settings.divisions``: ``0`` = off, ``n >= 1`` = the league plays in
    #: ``n`` divisions.  ``None`` when the setting is absent (no division
    #: structure configured) or unreadable (``divisions_reason`` names it).
    divisions: int | None = None
    divisions_reason: str = ""
    #: How divisions bear on qualifying and seeding: ``DIVISION_RULE_NONE``
    #: (the host plays none), ``DIVISION_RULE_RECORDED`` (the league's record
    #: says they bear on nothing) or ``DIVISION_RULE_UNRECORDED`` (they are ON,
    #: or unreadable, and no record says how the league plays them).
    division_rule: str = DIVISION_RULE_NONE
    #: The league's recorded rules (``config/leagues/playoff_rules.json``), or
    #: ``None`` when it has no record.
    rules: LeaguePlayoffRules | None = None

    @property
    def divisions_in_play(self) -> bool:
        """True when the HOST plays with divisions: the setting is ON, or it
        is unreadable.  Says nothing about whether they affect qualifying --
        that is :attr:`division_qualification_unknown`."""
        return bool(self.divisions_reason) or (self.divisions is not None and self.divisions > 0)

    @property
    def division_qualification_unknown(self) -> bool:
        """True when qualifying may depend on a division rule the simulator
        does not model: divisions are ON (or unreadable) and the league has no
        record saying they leave qualifying and seeding alone."""
        return self.division_rule == DIVISION_RULE_UNRECORDED

    @property
    def known(self) -> bool:
        """True only when the league published a usable bracket.

        Callers must branch on this. A ``False`` here means the simulators
        do not know what qualifying means, which is a different statement
        from "nobody qualifies" and from "six qualify".
        """
        return self.teams is not None

    @property
    def bracket_known(self) -> bool:
        """True only when the bracket can be PLAYED as the host plays it:
        the field is known and so is how its later rounds are paired."""
        return self.known and self.seed_type is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "playoffTeams": self.teams,
            "byeTeams": self.byes,
            "playoffWeekStart": self.week_start,
            "source": self.source,
            "reason": self.reason,
            "seedType": self.seed_type,
            "seedTypeReason": self.seed_type_reason,
            "divisions": self.divisions,
            "divisionsReason": self.divisions_reason,
            "divisionRule": self.division_rule,
            "leagueRules": self.rules.to_dict() if self.rules is not None else None,
        }


def _int_or_none(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _whole_count_or_none(value: Any) -> int | None:
    """A count that Sleeper stated exactly, or ``None``.

    Stricter than :func:`_int_or_none`, which truncates: ``int(0.5)`` is 0,
    so a malformed ``divisions: 0.5`` would read as "no divisions" and the
    league would be simulated — failing OPEN.  Here only an int, a string of
    digits, or a float with no fractional part is a count; anything else is
    unrecognised and the caller fails closed.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def resolve_playoff_structure(season: Any, league_key: str | None = None) -> PlayoffStructure:
    """Read this season's bracket off its own Sleeper league settings.

    ``season`` is a ``SeasonSnapshot`` (or anything exposing ``.league``);
    ``None`` is accepted and answers unknown, because "there is no current
    season" is a real state the public builders already handle.

    ``league_key`` selects the league's recorded rules
    (:func:`league_playoff_rules`) -- whether divisions bear on qualifying.
    Without it a league with divisions ON is ``DIVISION_RULE_UNRECORDED``.
    """
    if season is None:
        return PlayoffStructure(None, None, None, "unavailable", REASON_NO_SEASON)

    league = getattr(season, "league", None) or {}
    settings = league.get("settings") if isinstance(league, dict) else None
    if not isinstance(settings, dict) or not settings:
        return PlayoffStructure(None, None, None, "unavailable", REASON_NO_SETTINGS)

    week_start = _int_or_none(settings.get("playoff_week_start"))
    teams = _int_or_none(settings.get("playoff_teams"))
    if teams is None:
        return PlayoffStructure(None, None, week_start, "unavailable", REASON_NO_PLAYOFF_TEAMS)
    if not (_MIN_TEAMS <= teams <= _MAX_TEAMS):
        # Refused, not clamped — see ``_MIN_TEAMS``.
        return PlayoffStructure(None, None, week_start, "unavailable", REASON_IMPLAUSIBLE)

    raw_seed_type = settings.get("playoff_seed_type")
    seed_type: str | None
    if raw_seed_type is None:
        seed_type, seed_reason = None, REASON_NO_SEED_TYPE
    else:
        code = _int_or_none(raw_seed_type)
        seed_type = _SEED_TYPES.get(code) if code is not None else None
        seed_reason = "" if seed_type is not None else REASON_UNKNOWN_SEED_TYPE
    # A MISSING key is "no divisions" (dynasty_new and the pre-draft league
    # omit it; the 2025 dynasty_main stored an explicit 0 once divisions were
    # off).  A key that is PRESENT but null, fractional or unparseable is not
    # a statement of zero — it is unrecognised, and the engine refuses.
    divisions_present = isinstance(settings, dict) and "divisions" in settings
    raw_divisions = settings.get("divisions")
    divisions = _whole_count_or_none(raw_divisions)
    divisions_reason = ""
    if divisions_present and (divisions is None or divisions < 0):
        divisions, divisions_reason = None, REASON_UNKNOWN_DIVISIONS
    rules = league_playoff_rules(league_key)
    host_divisions_on = bool(divisions_reason) or (divisions is not None and divisions > 0)
    if rules is not None:
        division_rule = DIVISION_RULE_RECORDED
    elif host_divisions_on:
        division_rule = DIVISION_RULE_UNRECORDED
    else:
        division_rule = DIVISION_RULE_NONE
    return PlayoffStructure(
        teams,
        byes_for_teams(teams),
        week_start,
        "league_settings",
        seed_type=seed_type,
        seed_type_reason=seed_reason,
        divisions=divisions,
        divisions_reason=divisions_reason,
        division_rule=division_rule,
        rules=rules,
    )


#: Why division-champion odds are not published.
REASON_NO_DIVISIONS = "no_divisions"
REASON_DIVISION_RULE_UNRECORDED = "division_champion_rule_unrecorded"
REASON_DIVISION_COUNT_CONFLICT = "division_count_conflicts_with_host_setting"
REASON_ROSTER_DIVISION_MISSING = "roster_division_missing_or_out_of_range"
REASON_DIVISION_EMPTY = "division_has_no_teams"
REASON_DIVISION_OWNER_UNRESOLVED = "roster_owner_unresolved"


@dataclass(frozen=True)
class DivisionAssignments:
    """Which division each team plays in -- or why that is not established.

    ``state`` is ``"available"`` (every team has exactly one division and the
    league records how a champion is decided), ``"unavailable"`` (divisions
    exist but something needed is missing -- ``reason`` names it) or
    ``"not_applicable"`` (the league plays no divisions).
    """

    state: str
    reason: str = ""
    count: int | None = None
    by_owner: Mapping[str, int] = field(default_factory=dict)
    names: Mapping[int, str] = field(default_factory=dict)
    rules: LeaguePlayoffRules | None = None

    @property
    def available(self) -> bool:
        return self.state == "available"

    def members(self) -> dict[int, list[str]]:
        out: dict[int, list[str]] = {}
        for owner, div in sorted(self.by_owner.items()):
            out.setdefault(div, []).append(owner)
        return dict(sorted(out.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reason": self.reason,
            "count": self.count,
            "names": {str(k): v for k, v in sorted(self.names.items())},
            "championRule": (
                {
                    "rule": self.rules.division_champion,
                    "tiebreakers": list(self.rules.division_champion_tiebreakers),
                    # The record the league's standings show: the weekly
                    # median game counts in it when the league counts it.
                    "recordBasis": "host_standings_record",
                    "affectsPlayoffs": self.rules.divisions_affect_playoffs,
                }
                if self.rules is not None and self.rules.division_champion
                else None
            ),
        }


def resolve_division_assignments(
    season: Any,
    structure: PlayoffStructure,
    owner_of: Any,
) -> DivisionAssignments:
    """Each team's division for ``season``, or why it is not established.

    ``owner_of(roster_id)`` maps a roster to the owner id the simulator keys
    teams by (the roster's CURRENT owner).  Divisions come from each roster's
    ``settings.division`` (Sleeper numbers them 1..n); names from the league's
    ``metadata["division_<n>"]`` when it sets them.

    Fails closed, with a named reason, when the league records no champion
    rule, when a roster's division is missing or outside 1..n, when a
    division has no team, or when the host setting states a different count
    than the record.  A league that plays no divisions is ``not_applicable``.
    """
    rules = getattr(structure, "rules", None)
    if rules is None or rules.division_count is None or rules.division_champion is None:
        if getattr(structure, "divisions_in_play", False):
            return DivisionAssignments("unavailable", REASON_DIVISION_RULE_UNRECORDED)
        return DivisionAssignments("not_applicable", REASON_NO_DIVISIONS)
    count = rules.division_count
    host = getattr(structure, "divisions", None)
    if host is not None and host > 0 and host != count:
        return DivisionAssignments("unavailable", REASON_DIVISION_COUNT_CONFLICT, count=count)
    league = getattr(season, "league", None) or {}
    metadata = league.get("metadata") if isinstance(league, dict) else None
    names: dict[int, str] = {}
    if isinstance(metadata, dict):
        for n in range(1, count + 1):
            name = metadata.get(f"division_{n}")
            if isinstance(name, str) and name.strip():
                names[n] = name.strip()
    by_owner: dict[str, int] = {}
    for roster in getattr(season, "rosters", None) or []:
        settings = roster.get("settings") if isinstance(roster, dict) else None
        div = _whole_count_or_none((settings or {}).get("division"))
        if div is None or not (1 <= div <= count):
            return DivisionAssignments("unavailable", REASON_ROSTER_DIVISION_MISSING, count=count)
        owner = owner_of(roster.get("roster_id")) if isinstance(roster, dict) else ""
        if not owner or owner in by_owner:
            return DivisionAssignments("unavailable", REASON_DIVISION_OWNER_UNRESOLVED, count=count)
        by_owner[owner] = div
    if set(by_owner.values()) != set(range(1, count + 1)):
        return DivisionAssignments("unavailable", REASON_DIVISION_EMPTY, count=count)
    return DivisionAssignments(
        "available", count=count, by_owner=by_owner, names=names, rules=rules
    )
