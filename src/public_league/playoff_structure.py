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

Divisions are READ, not ignored (CW-49, 2026-11-07)
─────────────────────────────────────────────────
Sleeper's ``settings.divisions`` splits a league into divisions, and the host
qualifies every division winner for the playoffs ("If there are divisions,
then each division winner will qualify for the playoffs",
https://sleeper.com/blog/how-do-fantasy-playoffs-work), whatever its overall
record.  The canonical simulator seeds on overall record only, and the host's
rules for seeding division winners against wild cards and for breaking a
division tie are not verified, so a league whose divisions are ON is not a
format the simulator can play: :attr:`PlayoffStructure.divisions_in_play`
says so and the simulator refuses with a named reason.  Measured: the live
``dynasty_main`` stated ``divisions: 3`` on 2026-10-26
(``docs/audits/evidence/league_rules_dynasty_main_2026-10-26.json``) and
``divisions: 0`` on 2026-11-07, so its odds were computed without the
division-winner rule while divisions were on.  ``0`` is off.  An ABSENT
setting is read as no divisions: the host states a count only for a league
that configured divisions (``dynasty_new`` omits the key); a present value
that is not a non-negative integer is unknown and refused too.

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

from dataclasses import dataclass
from typing import Any

__all__ = [
    "SEED_TYPE_FIXED",
    "SEED_TYPE_RESEED",
    "PlayoffStructure",
    "byes_for_teams",
    "resolve_playoff_structure",
]

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

    @property
    def divisions_in_play(self) -> bool:
        """True when qualifying may depend on a division rule the simulator
        does not model: divisions are ON, or the setting is unreadable."""
        return bool(self.divisions_reason) or (self.divisions is not None and self.divisions > 0)

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


def resolve_playoff_structure(season: Any) -> PlayoffStructure:
    """Read this season's bracket off its own Sleeper league settings.

    ``season`` is a ``SeasonSnapshot`` (or anything exposing ``.league``);
    ``None`` is accepted and answers unknown, because "there is no current
    season" is a real state the public builders already handle.
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
    return PlayoffStructure(
        teams,
        byes_for_teams(teams),
        week_start,
        "league_settings",
        seed_type=seed_type,
        seed_type_reason=seed_reason,
        divisions=divisions,
        divisions_reason=divisions_reason,
    )
