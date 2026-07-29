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

# ── Sharp Tracker's stricter gate ────────────────────────────────────
#
# The Sharp cohort is a claim about SKILL, so its evidence bar is higher
# than Insider Trading's.  Two extra restrictions, both deliberate:
#
#   1. DYNASTY ONLY — no keeper.  Keeper trade behaviour is a hybrid
#      (most of the roster resets annually), so it is dynasty-adjacent
#      enough to inform your own league-mates' tendencies but not clean
#      enough to certify someone as a sharp dynasty manager.
#
#   2. LEAGUE AGE >= 2 SEASONS.  A first-year dynasty league is mostly
#      startup-draft fallout: enormous early churn, no established
#      market, and no completed season to judge anyone on.  Counting it
#      would let a manager look prolific purely for having just drafted.
#
# Insider Trading deliberately keeps the looser ELIGIBLE_TYPES gate —
# it answers "what do the managers in MY league do", where a keeper
# league is real evidence about a real person you can trade with.
SHARP_ELIGIBLE_TYPES = frozenset({LEAGUE_TYPE_DYNASTY})
SHARP_MIN_LEAGUE_AGE_SEASONS = 2


def league_age_seasons(league: dict[str, Any] | None) -> int:
    """How many seasons this league has existed, from data already in
    hand.

    Sleeper chains seasons with ``previous_league_id``, so its presence
    proves at least one prior season — i.e. age >= 2 — and that field
    ships inside the ``/user/{id}/leagues`` payload the crawl already
    fetches.  The age-2 check therefore costs ZERO extra API calls,
    which is why 2 is the default bar.

    Returns 2 as a floor-not-exact answer for any chained league:
    establishing age >= 3 requires walking the chain one request per
    link, and nothing currently needs that precision.  Callers wanting
    an exact age must walk ``previous_league_id`` themselves.
    """
    if not isinstance(league, dict):
        return 0
    return 2 if str(league.get("previous_league_id") or "").strip() else 1


def is_sharp_eligible(
    league: dict[str, Any] | None,
    *,
    min_age_seasons: int = SHARP_MIN_LEAGUE_AGE_SEASONS,
) -> bool:
    """May this league's activity count toward SHARP qualification?

    Stricter than :func:`is_eligible` on purpose — see the module note.
    Unlike the discovery gate, an unknown league type is REJECTED here:
    certifying a manager as sharp on a league we cannot confirm is
    dynasty would be a claim we cannot support.
    """
    if not isinstance(league, dict):
        return False
    if is_best_ball(league):
        return False
    if league_type(league) not in SHARP_ELIGIBLE_TYPES:
        return False
    return league_age_seasons(league) >= int(min_age_seasons)


def sharp_exclusion_reason(
    league: dict[str, Any] | None,
    *,
    min_age_seasons: int = SHARP_MIN_LEAGUE_AGE_SEASONS,
) -> str | None:
    """Why a league is not sharp-eligible, or ``None`` when it is.

    Reported rather than silently dropped, so a shrinking sharp pool is
    always explainable.
    """
    if not isinstance(league, dict):
        return "not_a_league"
    if is_best_ball(league):
        return "best_ball"
    lt = league_type(league)
    if lt is None:
        return "unknown_type"
    if lt not in SHARP_ELIGIBLE_TYPES:
        return _TYPE_LABELS.get(lt, "unknown")
    if league_age_seasons(league) < int(min_age_seasons):
        return "too_new"
    return None


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
