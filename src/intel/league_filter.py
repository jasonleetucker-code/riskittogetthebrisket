"""Which discovered Sleeper leagues belong in a DYNASTY signal.

The crawler discovers every league a pool member plays in and, until
now, registered all of them unconditionally — the only filter was
``lg.get("league_id")`` being truthy.  Redraft and best-ball leagues
therefore fed the same buy/sell board as dynasty leagues.

That is not a cosmetic mismatch.  Redraft transaction behaviour is the
OPPOSITE of dynasty behaviour for the same player: a rebuilding dynasty
manager sells a 30-year-old RB whom a redraft manager in the same week
is buying for the playoff push.  Mixed together they cancel, and the
asset reads "no signal" when the dynasty signal was actually strong.
Rookie picks are worse still — a redraft league has no future picks, so
its presence only ever dilutes.

Sleeper exposes league type at ``settings.type``:

    0 = redraft
    1 = keeper
    2 = dynasty

``best_ball`` is a separate ``settings`` flag.  Keeper leagues are
retained by default (they carry real multi-year asset value and their
trade behaviour is dynasty-adjacent), but are reported separately so
the choice is visible and reversible rather than silent.
"""

from __future__ import annotations

from typing import Any

LEAGUE_TYPE_REDRAFT = 0
LEAGUE_TYPE_KEEPER = 1
LEAGUE_TYPE_DYNASTY = 2

_TYPE_LABELS = {
    LEAGUE_TYPE_REDRAFT: "redraft",
    LEAGUE_TYPE_KEEPER: "keeper",
    LEAGUE_TYPE_DYNASTY: "dynasty",
}

# Keeper included: multi-year asset value makes its trade behaviour
# dynasty-adjacent.  Flip to just {DYNASTY} to tighten.
ELIGIBLE_TYPES = frozenset({LEAGUE_TYPE_DYNASTY, LEAGUE_TYPE_KEEPER})


def league_type(league: dict[str, Any] | None) -> int | None:
    """Sleeper's ``settings.type``, or ``None`` when absent.

    ``None`` is meaningfully different from ``0``: absent means we do
    not know, and unknown leagues are ADMITTED rather than dropped, so
    a Sleeper response shape change degrades toward the old inclusive
    behaviour instead of silently emptying the pool.
    """
    if not isinstance(league, dict):
        return None
    settings = league.get("settings")
    if not isinstance(settings, dict):
        return None
    raw = settings.get("type")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def is_best_ball(league: dict[str, Any] | None) -> bool:
    if not isinstance(league, dict):
        return False
    settings = league.get("settings")
    if not isinstance(settings, dict):
        return False
    try:
        return int(settings.get("best_ball") or 0) == 1
    except (TypeError, ValueError):
        return False


def type_label(league: dict[str, Any] | None) -> str:
    if is_best_ball(league):
        return "best_ball"
    return _TYPE_LABELS.get(league_type(league), "unknown")


def is_eligible(league: dict[str, Any] | None) -> bool:
    """True when this league's transactions should feed the board."""
    if is_best_ball(league):
        return False
    lt = league_type(league)
    if lt is None:
        return True  # unknown → admit, and let the caller report it
    return lt in ELIGIBLE_TYPES


def partition(leagues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """``(eligible_leagues, {label: dropped_count})``.

    The counts are returned so the crawl can report exactly what it
    excluded — an unexplained drop in tracked leagues must never look
    like a crawl failure.
    """
    eligible: list[dict[str, Any]] = []
    excluded: dict[str, int] = {}
    for lg in leagues or []:
        if is_eligible(lg):
            eligible.append(lg)
        else:
            label = type_label(lg)
            excluded[label] = excluded.get(label, 0) + 1
    return eligible, excluded
