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

import hashlib
from dataclasses import dataclass
from typing import Any, Mapping

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


#: Sleeper's ``previous_league_id`` for a league with NO predecessor.  It is
#: the STRING ``"0"`` (not null, not absent -- verified live, see
#: ``src/sharp/records.py``); an empty value means the same.  A terminator is
#: never a predecessor.
CHAIN_TERMINATORS = frozenset({"", "0"})


def predecessor_league_id(league: Mapping[str, Any] | None) -> str | None:
    """The ONE reader of a Sleeper league's predecessor link.

    ``None`` when the league has no predecessor -- Sleeper's ``"0"``
    terminator, an empty value, or no link at all.  Every chain consumer
    routes through this, so the terminator can never again be read as a
    real prior season (the defect this replaced counted ``"0"`` as one).
    ``previous_league`` is accepted as the legacy spelling the public
    walker already tolerates.
    """
    if not isinstance(league, Mapping):
        return None
    raw = league.get("previous_league_id")
    if raw is None or str(raw).strip() == "":
        raw = league.get("previous_league")
    text = str(raw or "").strip()
    return None if text in CHAIN_TERMINATORS else text


def league_age_seasons(league: dict[str, Any] | None) -> int:
    """How many seasons this league has existed -- a FLOOR from the one
    league object in hand, never the exact age.

    Sleeper chains seasons with ``previous_league_id``, so a real
    predecessor link proves at least one prior season -- i.e. age >= 2 --
    and that field ships inside the ``/user/{id}/leagues`` payload the
    crawl already fetches.  The age-2 check therefore costs ZERO extra API
    calls, which is why 2 is the Sharp gate's bar.

    Returns ``2`` for a league with a real predecessor, ``1`` otherwise
    (including Sleeper's ``"0"`` terminator, which is NOT a predecessor),
    ``0`` for a non-league.  It says nothing about whether those seasons
    were COMPLETED or were dynasty.  The exact answer -- verified completed
    dynasty seasons over the persisted ``previous_league_id`` chain, in both
    readings (point-in-time at a trade, league-level as of today) -- is
    :func:`resolve_league_maturity`; this floor is its fallback when no
    chain has been walked.
    """
    if not isinstance(league, dict):
        return 0
    return 2 if predecessor_league_id(league) else 1


def _gate_age(league: dict[str, Any], known_age_seasons: int | None) -> int:
    floor = league_age_seasons(league)
    return max(floor, int(known_age_seasons)) if known_age_seasons is not None else floor


def is_sharp_eligible(
    league: dict[str, Any] | None,
    *,
    min_age_seasons: int = SHARP_MIN_LEAGUE_AGE_SEASONS,
    known_age_seasons: int | None = None,
) -> bool:
    """May this league's activity count toward SHARP qualification?

    Stricter than :func:`is_eligible` on purpose — see the module note.
    Unlike the discovery gate, an unknown league type is REJECTED here:
    certifying a manager as sharp on a league we cannot confirm is
    dynasty would be a claim we cannot support.

    ``known_age_seasons`` lets a caller that has walked the lineage pass
    what it proved (e.g. the records crawl: a predecessor reached from a
    newer season belongs to a lineage at least that many seasons long, so
    the league's FIRST season counts once a second exists).  The gate uses
    the larger of it and :func:`league_age_seasons`' floor.
    """
    if not isinstance(league, dict):
        return False
    if is_best_ball(league):
        return False
    if league_type(league) not in SHARP_ELIGIBLE_TYPES:
        return False
    return _gate_age(league, known_age_seasons) >= int(min_age_seasons)


def sharp_exclusion_reason(
    league: dict[str, Any] | None,
    *,
    min_age_seasons: int = SHARP_MIN_LEAGUE_AGE_SEASONS,
    known_age_seasons: int | None = None,
) -> str | None:
    """Why a league is not sharp-eligible, or ``None`` when it is.

    Reported rather than silently dropped, so a shrinking sharp pool is
    always explainable.  ``known_age_seasons`` as :func:`is_sharp_eligible`.
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
    if _gate_age(league, known_age_seasons) < int(min_age_seasons):
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


# ── League maturity: verified COMPLETED dynasty seasons ─────────────────
#
# The ONE owner of "how established is this league".  Owner directive
# 2026-10-19 (V2, Chase Upside Trade Market): the initial trade-derived
# model prioritizes leagues with at least THREE VERIFIED COMPLETED SEASONS,
# established by following the real ``previous_league_id`` chain -- never
# calendar age, never a count of linked ids.  Two-season leagues are a
# separately reported research cohort; the three-season bar is never
# silently relaxed.
#
# What counts as one completed season (fail closed):
#   * a season-league reached by following ``previous_league_id`` links;
#   * whose Sleeper ``settings.type`` is 2 (dynasty) -- a redraft / keeper
#     predecessor ENDS the chain (it is not this dynasty's history);
#   * whose last observed ``status`` is ``complete`` -- an older season seen
#     only while in progress is UNVERIFIED (the state becomes a lower bound),
#     never assumed complete;
#   * whose season is strictly older than the season-league after it.  A
#     predecessor carrying the SAME season is a recreated league id inside
#     one season: walked past, flagged ``recreated_same_season``, never
#     counted as a season of its own.
#
# A walk that ends at Sleeper's terminator is EXACT.  Anything else (a link
# no walk has recorded yet, a predecessor with no type or season, a loop,
# the safety cap) is a LOWER BOUND: "at least k".  A lower bound below the
# bar is "maturity unknown", never a pass.
#
# Two readings, both always reported (neither is chosen silently):
#   * point-in-time at the trade -- predecessors of the trade's own
#     season-league; the trade's own season never counts;
#   * league-level as of today -- the newest season-league of the lineage
#     the chain store knows, inclusive of itself once it is complete.  It is
#     ALWAYS a lower bound (``newest_season_successor_unprovable``): Sleeper
#     links backward only, so no store can prove the lineage has no newer
#     season-league, nor that a newest hop last seen in progress has not
#     completed since.  It can prove "at least k", never "proven not k".

#: The V2 directive's primary bar and the research cohort's bar.
MATURITY_PRIMARY_MIN_COMPLETED_SEASONS = 3
MATURITY_RESEARCH_MIN_COMPLETED_SEASONS = 2

READING_POINT_IN_TIME = "point_in_time_at_trade"
READING_LEAGUE_LEVEL = "league_level_as_of_today"
MATURITY_READINGS = (READING_POINT_IN_TIME, READING_LEAGUE_LEVEL)

MATURITY_EXACT = "exact"
MATURITY_LOWER_BOUND = "lower_bound"

#: Disjoint maturity cohorts.  ``B_two_plus_unresolved`` is "at least two,
#: possibly three": it is in the >=2 research population but NEVER in A.
COHORT_A = "A_three_plus_completed"
COHORT_B_EXACT = "B_two_completed"
COHORT_B_UNRESOLVED = "B_two_plus_unresolved"
COHORT_BELOW_TWO = "below_two_completed"
COHORT_UNKNOWN_BELOW_TWO = "unknown_below_two_lower_bound"
COHORT_NOT_WALKED = "chain_not_walked"
MATURITY_COHORTS = (
    COHORT_A,
    COHORT_B_EXACT,
    COHORT_B_UNRESOLVED,
    COHORT_BELOW_TWO,
    COHORT_UNKNOWN_BELOW_TWO,
    COHORT_NOT_WALKED,
)

#: Why a maturity walk stopped.
STOP_TERMINATOR = "terminator"
STOP_NON_DYNASTY = "non_dynasty_predecessor"
STOP_NOT_WALKED = "predecessor_not_walked"
STOP_START_NOT_WALKED = "start_not_walked"
STOP_TYPE_UNKNOWN = "predecessor_type_unknown"
STOP_SEASON_UNKNOWN = "season_unknown"
STOP_SEASON_ORDER = "season_order_violation"
STOP_LOOP = "chain_loop"
STOP_CAP = "safety_cap"

#: Walk flags (diagnostic; none of them counts a season).
FLAG_RECREATED_SAME_SEASON = "recreated_same_season"
FLAG_STATUS_UNVERIFIED = "predecessor_status_unverified"
FLAG_BEST_BALL_SEASON = "best_ball_season_counted"
FLAG_FORKED_SUCCESSORS = "forked_successors"
FLAG_SUCCESSOR_UNPROVABLE = "newest_season_successor_unprovable"

#: Safety cap on hops -- a guard against a malformed chain, far past any real
#: league's age (same posture as the public walker's 25-season cap).
MATURITY_MAX_HOPS = 25


@dataclass(frozen=True)
class ChainHop:
    """One observed season-league link of a ``previous_league_id`` chain.

    ``previous_league_id`` is ``None`` when the league states NO predecessor
    (Sleeper's ``"0"`` terminator) -- a fact, distinct from "not observed",
    which is the league being absent from the chain index altogether.
    """

    league_id: str
    previous_league_id: str | None
    season: str | None
    league_type: int | None
    status: str | None
    best_ball: bool | None
    observed_ms: int | None = None

    @classmethod
    def from_league(
        cls, league: Mapping[str, Any] | None, *, observed_ms: int | None = None
    ) -> ChainHop | None:
        """The hop a Sleeper league object states, or ``None`` with no id."""
        if not isinstance(league, Mapping):
            return None
        lid = str(league.get("league_id") or "").strip()
        if not lid:
            return None
        settings = league.get("settings")
        bb: bool | None = None
        if isinstance(settings, Mapping) and settings.get("best_ball") is not None:
            bb = is_best_ball(dict(league))
        season = str(league.get("season") or "").strip() or None
        status = str(league.get("status") or "").strip().lower() or None
        return cls(
            league_id=lid,
            previous_league_id=predecessor_league_id(league),
            season=season,
            league_type=league_type(dict(league)),
            status=status,
            best_ball=bb,
            observed_ms=observed_ms,
        )

    @property
    def is_dynasty(self) -> bool:
        return self.league_type == LEAGUE_TYPE_DYNASTY

    @property
    def is_complete(self) -> bool:
        return self.status == "complete"


def _season_int(season: str | None) -> int | None:
    try:
        return int(str(season).strip()) if season is not None else None
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class LeagueMaturity:
    """Verified completed dynasty seasons for one reading of one league.

    Box-local: ``start_league_id`` is a raw Sleeper id and must never reach a
    committed or public artifact -- :meth:`to_report_dict` omits it.
    """

    reading: str
    start_league_id: str | None
    completed_seasons: int
    state: str
    stop_reason: str
    seasons_walked: int
    flags: tuple[str, ...] = ()

    def meets(self, min_completed: int) -> bool | None:
        """``True`` proven, ``False`` proven not (exact walk), ``None`` unknown."""
        if self.completed_seasons >= int(min_completed):
            return True
        return False if self.state == MATURITY_EXACT else None

    @property
    def cohort(self) -> str:
        if self.stop_reason == STOP_START_NOT_WALKED:
            return COHORT_NOT_WALKED
        if self.meets(MATURITY_PRIMARY_MIN_COMPLETED_SEASONS):
            return COHORT_A
        if self.completed_seasons >= MATURITY_RESEARCH_MIN_COMPLETED_SEASONS:
            return COHORT_B_EXACT if self.state == MATURITY_EXACT else COHORT_B_UNRESOLVED
        return COHORT_BELOW_TWO if self.state == MATURITY_EXACT else COHORT_UNKNOWN_BELOW_TWO

    def to_report_dict(self) -> dict[str, Any]:
        return {
            "reading": self.reading,
            "completedSeasons": self.completed_seasons,
            "state": self.state,
            "stopReason": self.stop_reason,
            "seasonsWalked": self.seasons_walked,
            "flags": list(self.flags),
            "cohort": self.cohort,
        }


def successor_index(chain: Mapping[str, ChainHop]) -> dict[str, list[str]]:
    """``{predecessor_id: [successor ids...]}`` over the observed links."""
    out: dict[str, list[str]] = {}
    for lid in sorted(chain):
        prev = chain[lid].previous_league_id
        if prev:
            out.setdefault(prev, []).append(lid)
    return out


def _newest_descendant(
    start: str,
    chain: Mapping[str, ChainHop],
    successors: Mapping[str, list[str]],
) -> tuple[str, bool]:
    """The newest season-league reachable forward from ``start``; and whether
    a fork (two leagues naming one predecessor) was crossed on the way.  A
    fork follows the newest season, then the lowest id -- deterministic."""
    cur, forked, seen = start, False, {start}
    while True:
        nxt = [s for s in successors.get(cur, ()) if s not in seen]
        if not nxt:
            return cur, forked
        if len(nxt) > 1:
            forked = True
        nxt.sort(key=lambda lid: (-(_season_int(chain[lid].season) or -1), lid))
        cur = nxt[0]
        seen.add(cur)


def resolve_league_maturity(
    league_id: str | None,
    chain: Mapping[str, ChainHop],
    *,
    reading: str = READING_POINT_IN_TIME,
    successors: Mapping[str, list[str]] | None = None,
    max_hops: int = MATURITY_MAX_HOPS,
) -> LeagueMaturity:
    """Verified completed dynasty seasons for ``league_id`` (a Sleeper
    season-league id) over the persisted chain index ``chain``
    (``{league_id: ChainHop}``, e.g. ``ledger.load_league_chain``).

    ``READING_POINT_IN_TIME``: ``league_id`` is the trade's own season-league;
    only its predecessors can count.  ``READING_LEAGUE_LEVEL``: the walk
    starts at the newest known season-league of the same lineage and counts
    that league itself once it is complete.  Pure: no network, no clock.
    """
    if reading not in MATURITY_READINGS:
        raise ValueError(f"unknown maturity reading: {reading!r}")
    lid = str(league_id or "").strip()
    flags: list[str] = []
    if not lid or lid not in chain:
        return LeagueMaturity(
            reading, lid or None, 0, MATURITY_LOWER_BOUND, STOP_START_NOT_WALKED, 0
        )
    start = lid
    if reading == READING_LEAGUE_LEVEL:
        succ = successors if successors is not None else successor_index(chain)
        start, forked = _newest_descendant(lid, chain, succ)
        if forked:
            flags.append(FLAG_FORKED_SUCCESSORS)

    counted: set[int] = set()
    # League-level: the newest KNOWN season-league is not provably the newest
    # one (no forward link exists), and its stored status may be stale.  So
    # the as-of-today count is "at least k" -- never exact, never "proven not".
    lower_bound = reading == READING_LEAGUE_LEVEL
    if lower_bound:
        flags.append(FLAG_SUCCESSOR_UNPROVABLE)
    seen: set[str] = set()
    walked = 0

    def _count(hop: ChainHop, season: int) -> None:
        nonlocal lower_bound
        if not hop.is_complete:
            lower_bound = True
            if FLAG_STATUS_UNVERIFIED not in flags:
                flags.append(FLAG_STATUS_UNVERIFIED)
            return
        if hop.best_ball and FLAG_BEST_BALL_SEASON not in flags:
            flags.append(FLAG_BEST_BALL_SEASON)
        counted.add(season)

    def _done(state_reason: str, exact: bool) -> LeagueMaturity:
        state = MATURITY_EXACT if exact and not lower_bound else MATURITY_LOWER_BOUND
        return LeagueMaturity(
            reading, lid, len(counted), state, state_reason, walked, tuple(sorted(flags))
        )

    cur_hop = chain[start]
    seen.add(start)
    walked = 1
    cur_season = _season_int(cur_hop.season)
    if reading == READING_LEAGUE_LEVEL and cur_hop.is_dynasty and cur_season is not None:
        # The newest season-league counts for the league-level reading only
        # once it is itself complete (the reading is already a lower bound).
        if cur_hop.is_complete:
            _count(cur_hop, cur_season)
    if cur_season is None:
        # Without the start's season no predecessor's order can be verified.
        return _done(STOP_SEASON_UNKNOWN, exact=False)
    while True:
        prev = cur_hop.previous_league_id
        if prev is None:
            return _done(STOP_TERMINATOR, exact=True)
        if prev in seen:
            return _done(STOP_LOOP, exact=False)
        if walked >= max_hops:
            return _done(STOP_CAP, exact=False)
        hop = chain.get(prev)
        if hop is None:
            return _done(STOP_NOT_WALKED, exact=False)
        seen.add(prev)
        walked += 1
        if hop.league_type is None:
            return _done(STOP_TYPE_UNKNOWN, exact=False)
        if not hop.is_dynasty:
            # A redraft / keeper predecessor is not this dynasty's history:
            # the dynasty provably began after it, so the count is exact.
            return _done(STOP_NON_DYNASTY, exact=True)
        season = _season_int(hop.season)
        if season is None:
            return _done(STOP_SEASON_UNKNOWN, exact=False)
        if season > cur_season:
            return _done(STOP_SEASON_ORDER, exact=False)
        if season == cur_season:
            if FLAG_RECREATED_SAME_SEASON not in flags:
                flags.append(FLAG_RECREATED_SAME_SEASON)
        else:
            _count(hop, season)
            cur_season = season
        cur_hop = hop


def lineage_index(chain: Mapping[str, ChainHop]) -> dict[str, str]:
    """``{league_id: lineage_id}`` -- union-find over EVERY observed
    ``(league, previous)`` link, so all seasons of one league share one id
    however the chain was discovered or truncated (a ``chain[-1]`` root
    after a hop cap gives two seasons of one league different roots).

    The id is a stable digest of the component's smallest member id -- not
    the raw id, so it can label aggregate counts.  It changes only when two
    components are discovered to be one (a newly walked link); a consumer
    that persists lineage membership (the holdout reserve) owns the merge
    rule.  Includes predecessor ids the index has not walked yet.
    """
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        root = x
        while parent[root] != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            if rb < ra:
                ra, rb = rb, ra
            parent[rb] = ra

    for lid in sorted(chain):
        find(lid)
        prev = chain[lid].previous_league_id
        if prev:
            union(lid, prev)
    return {
        lid: "lineage:" + hashlib.sha256(find(lid).encode("utf-8")).hexdigest()[:16]
        for lid in sorted(parent)
    }
