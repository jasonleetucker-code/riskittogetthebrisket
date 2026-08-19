"""THE canonical lineup / slot-assignment owner (C2-U1).

Two concepts live here, deliberately distinct, because conflating them
is what produced five competing implementations:

**(A) League slot RULES** — which slots a league starts, and which
player positions are legal in each.  ``resolve_starter_slots`` (the
truth ladder), ``flatten_starter_slots``, ``normalize_slot``,
``lineup_position``, ``slot_eligible_positions``,
``player_eligible_for_slot``, ``slot_demand``.

**(B) ASSIGNMENT** — which player occupies which legal slot.
``solve_optimal_assignment`` / ``assign_lineup``.  Exact, never greedy.

Everything else in the codebase CONSUMES these.  Nothing re-derives
them — not a Python module, not a frontend library.  See §"one owner"
below and ``tests/lineup/test_single_owner.py``, which enforces it
structurally rather than by convention.

Missing is never zero (B)
─────────────────────────
``ros_value`` is ``float | None``.  ``0.0`` is a REAL objective value:
that player is assignable and contributes nothing.  ``None`` is an
UNKNOWN objective: that player is **not assignable**, is reported in
``LineupAssignment.unpriced_ids``, and the slot they would have filled
is reported unfilled.  Neither is silently the other.

This matters more than it looks.  The retired coercion
``float(player.ros_value or 0.0)`` produced the same SCORE either way —
so nothing that only summed values could ever have caught it — while
reporting a slot as filled by a player nobody can price, and dividing
``health_availability_score`` by a starter count that included them.

Given a roster + per-player ROS values + the league's roster_settings,
return the highest-scoring eligible lineup plus a residual "depth"
score for the bench — best-ball-aware.

    starting_lineup_score = Σ ros_value over the OPTIMAL eligible lineup
    bb_depth_score        = Σ ros_value over the next ``DEPTH_BENCH_LIMIT``
                            players, decayed by position (best-ball
                            spike-week premium for WR/RB/TE).

Exactness (LI-3, ADR-004)
─────────────────────────
The lineup fill is an **exact** maximum-weight assignment, not a
heuristic.  It was previously a slot-ordered greedy ("walk slots
most-restrictive-first, take the best eligible unused player"), which
is optimal only while the slot eligibility sets form a *laminar*
family (each pair nested or disjoint).  That happens to hold for this
league's slots today (QB ⊂ SUPER_FLEX; RB/WR/TE ⊂ FLEX ⊂ SUPER_FLEX;
DL/LB/DB ⊂ IDP_FLEX; K disjoint) — so the old code produced correct
answers by an unstated precondition nobody was enforcing.  A single
non-laminar slot (a WR/TE-only flex beside the RB/WR/TE FLEX, a
QB/RB-only slot, a two-family IDP flex) breaks it *silently*: no
error, just a quietly suboptimal lineup.

``optimize_lineup`` now solves the assignment exactly via weight-
descending matroid greedy with augmenting paths (Kuhn's algorithm on
the bipartite player↔slot graph).  Because slot eligibility defines a
transversal matroid and each player's weight is slot-independent,
processing players in descending weight and augmenting when possible
yields a provably maximum-weight assignment for ANY eligibility
structure — laminar or not.  Cost is O(P·S·E), trivial at roster
scale (≤60 players × ≤25 slots), and it is dependency-free.
``tests/league_intel/test_lineup_exactness.py`` pins equivalence with
brute force and includes the non-laminar case the old greedy failed.

Slot eligibility map mirrors Sleeper's roster_positions naming:

    QB, RB, WR, TE, FLEX (RB/WR/TE), SUPER_FLEX (QB/RB/WR/TE),
    DL, LB, DB, IDP_FLEX (DL/LB/DB), DEF (team defense, ignored), K, BN

One owner (C2-U1)
─────────────────
Retired into this module, with the reason each was wrong measured
against Sleeper's OWN awarded lineups
(``tests/league_intel/fixtures/golden_bestball_lineups.json`` — 10 real
2025 team-weeks; the exact solver here reproduces the host on 10/10):

* ``src/trade/team_impact.py::project_starters`` — slot-ordered greedy.
  **0/10**, short 333.66 pts.  Four independent faults: ``_FILL_ORDER``
  named no ``K`` or ``DEF`` so those slots never filled (15-16 of 17
  slots occupied); ``_BASE_POSITIONS`` dropped kickers from the pool
  outright; no ``fantasy_positions``, so hybrids were locked out of half
  their legal slots; and it filled ``SFLEX`` *before* ``FLEX``, i.e.
  least-restrictive first, which is backwards even for a greedy.
* ``frontend/lib/starter-slots.js::fillLineup`` — two-pass greedy.
  **5/10**, short 50.14 pts, which decomposes into **34.01 pts** of
  eligibility blindness and **16.13 pts** the ALGORITHM loses when it is
  handed this module's own eligibility.  That residue is why the repair
  is "the server assigns and the client renders", not "port the tables
  to JavaScript": correct data does not rescue a greedy.
* ``src/bdvm/roster.py::_quick_starter_fpg`` — per-group greedy, already
  self-described as "heuristic display number only".

And four independent re-derivations of the even-split slot-demand
approximation (``_flex_share``, ``_starter_requirements``,
``starter_slot_counts``, and this module's own ``_slot_demand``) are
now one declared :func:`slot_demand` contract — see its docstring for
why the even split is kept but LABELLED rather than blessed.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Collection, Iterable, Mapping, Sequence

# Per-position eligibility for flex slots.  Order encodes priority when
# the optimizer has a choice (more-restricted slot fills first).
_FLEX_ELIGIBLE = {"RB", "WR", "TE"}
_SUPER_FLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}
_IDP_FLEX_ELIGIBLE = {"DL", "DE", "DT", "EDGE", "LB", "DB", "S", "CB"}
_IDP_FAMILIES = {
    "DL": {"DL", "DE", "DT", "EDGE"},
    "LB": {"LB"},
    "DB": {"DB", "S", "CB"},
}

# Player position → the token a lineup slot is named in.  Defensive
# players resolve to their FAMILY, kept distinct, because a league that
# starts 3 DL + 3 LB + 3 DB does not start "9 defenders": collapsing
# them makes every defensive slot match every defender, and a roster
# stacked at one IDP position then "starts" players the league has no
# slot for.
#
# Widened past ``_IDP_FAMILIES`` on purpose.  Those sets answer "is this
# position legal in that slot" and are Sleeper-faithful; this answers
# "which slot family is this player", and must also absorb the roster
# spellings the scrapers emit (NT, OLB/ILB/MLB, FS/SS).
#
# ``MLB`` was missing until 2026-08-19 and that was a real eligibility
# defect, not a naming one: an MLB-listed player resolved to a family
# called "MLB", which matches no slot, so a genuine linebacker could not
# fill LB or IDP_FLEX at all.  Zero of 660 rostered players carry the
# spelling today, which is why nothing caught it.  The two are
# reconciled in :func:`lineup_position`, which is the single definition.
_LINEUP_FAMILY: dict[str, str] = {}
for _fam, _members in (
    ("DL", ("DL", "DE", "DT", "EDGE", "NT")),
    ("LB", ("LB", "OLB", "ILB", "MLB")),
    ("DB", ("DB", "CB", "S", "FS", "SS")),
    ("K", ("K", "PK", "P")),
):
    for _m in _members:
        _LINEUP_FAMILY[_m] = _fam
del _fam, _members, _m

# Slots that are not part of a starting lineup.
NON_LINEUP_SLOTS: frozenset[str] = frozenset({"BN", "IR", "TAXI"})

#: Canonical position order — a lineup card reads QB, RB, WR, TE, ...
#: Eligibility is a SET (order is meaningless to the solver), but several
#: consumers need a stable SEQUENCE for display and for their own
#: contracts.  Sorting alphabetically instead puts TE before WR, which is
#: nobody's lineup card, so the order is declared once here.
POSITION_ORDER: tuple[str, ...] = (
    "QB", "RB", "WR", "TE", "K", "DEF",
    "DL", "DE", "DT", "EDGE", "NT", "LB", "OLB", "ILB", "DB", "CB", "S", "FS", "SS",
)  # fmt: skip
_POSITION_RANK = {pos: i for i, pos in enumerate(POSITION_ORDER)}


def ordered_positions(positions: Iterable[str]) -> tuple[str, ...]:
    """``positions`` in canonical lineup-card order; unknowns last, then
    alphabetical so the result is always deterministic."""
    return tuple(
        sorted(
            {str(p).strip().upper() for p in positions if str(p).strip()},
            key=lambda p: (_POSITION_RANK.get(p, len(_POSITION_RANK)), p),
        )
    )


# Best-ball depth: how many bench rows to count.  Beyond this, a
# player's spike-week contribution is too marginal to credit at the
# team level.
DEPTH_BENCH_LIMIT = 8

# Position decay for depth contribution — first bench WR/RB/TE counts
# fully, second counts 70%, third counts 49%, etc.  QBs and IDP get a
# slightly steeper decay because their backup-week spikes are rarer.
_DEPTH_DECAY = {
    "QB": 0.55,
    "RB": 0.65,
    "WR": 0.65,
    "TE": 0.55,
    "DL": 0.55,
    "LB": 0.55,
    "DB": 0.55,
}
_DEFAULT_DECAY = 0.50


@dataclass(frozen=True)
class RosterPlayer:
    """Roster entry for the optimizer.  Immutable so the order doesn't matter.

    ``fantasy_positions`` mirrors Sleeper's per-player
    ``fantasy_positions`` list — the field the host itself uses for
    slot eligibility.  It is frequently WIDER than ``position``: a
    pass-rushing linebacker ships as ``position="DL"`` with
    ``fantasy_positions=["DL", "LB"]`` and is legal in either slot.
    Empty (the default) means "fall back to ``position``", so existing
    callers keep working unchanged.
    """

    player_id: str
    canonical_name: str
    position: str
    #: The objective.  ``0.0`` is a REAL value — that player is
    #: assignable and contributes nothing.  ``None`` is an UNKNOWN
    #: objective — that player is NOT assignable and is reported in
    #: ``LineupAssignment.unpriced_ids``.  Never conflate them; see the
    #: module docstring for what the retired ``or 0.0`` coercion hid.
    ros_value: float | None
    confidence: float = 1.0
    injured: bool = False
    bye: bool = False
    fantasy_positions: tuple[str, ...] = ()

    def eligible_positions(self) -> tuple[str, ...]:
        """Every position this player may be slotted at."""
        if self.fantasy_positions:
            merged = {p.strip().upper() for p in self.fantasy_positions if p and p.strip()}
            if self.position:
                merged.add(self.position.strip().upper())
            return tuple(sorted(merged))
        return (self.position.strip().upper(),) if self.position else ()


def roster_player_from_row(row: Mapping[str, Any]) -> RosterPlayer:
    """THE roster-row → :class:`RosterPlayer` adapter.

    Two byte-identical copies of this existed —
    ``league_intel.replacement._to_roster_players`` and
    ``roster_intel.marginal.to_roster_players`` — the second documenting
    that it "mirrors" the first "deliberately: the two modules must
    agree on how a roster row becomes an optimizer input, or their
    numbers stop being comparable".  Agreement maintained by hand is the
    thing ONE CONCEPT, ONE CANONICAL OWNER exists to replace; both now
    delegate here, so they agree structurally.

    **``rosValue`` missing is UNKNOWN, not 0.0.**  Both copies wrote
    ``float(row.get("rosValue") or 0.0)`` — the exact coercion C2-U1
    retired from this module, reintroduced at the adapter, where it
    would hand the solver a real, assignable, worthless player instead
    of an unpriced one.  An explicitly supplied ``0`` still passes
    through as the real value it is.

    Measured before changing: on the live path this is a no-op, because
    ``ros/team_strength.py`` already writes every unmatched row with
    ``ros_value=0.0`` (a deliberate coercion its own comment names) —
    so the snapshot these adapters read carries no ``None`` to preserve.
    That is worth knowing rather than assuming — the honest-missing
    state is lost UPSTREAM of here, so ``LineupAssignment.unpriced_ids``
    is empty by construction on the snapshot path however correct this
    function is.  (Corrected 2026-08-19: this said the writer DROPPED
    those rows.  It coerces them.)  Callers that assemble rows themselves (and can carry
    an unpriced player) get the honest behaviour.
    """
    raw = row.get("rosValue")
    return RosterPlayer(
        player_id=str(row.get("playerId") or row.get("canonicalName") or ""),
        canonical_name=str(row.get("canonicalName") or row.get("name") or ""),
        position=str(row.get("position") or "").upper(),
        ros_value=None if raw is None else float(raw),
        confidence=float(row.get("confidence") or 0.0),
        injured=bool(row.get("injured")),
        bye=bool(row.get("bye")),
        fantasy_positions=tuple(str(fp).upper() for fp in (row.get("fantasyPositions") or ())),
    )


def roster_players_from_rows(rows: Iterable[Mapping[str, Any]]) -> list[RosterPlayer]:
    """:func:`roster_player_from_row` over a sequence."""
    return [roster_player_from_row(r) for r in rows]


@dataclass
class LineupSolution:
    """Structured optimizer output for serialization + UI."""

    starting_lineup_score: float
    starting_lineup: list[dict[str, Any]]
    bench_depth_score: float
    bench_depth: list[dict[str, Any]]
    positional_coverage_score: float
    health_availability_score: float
    unfilled_slots: list[str]


#: Slot alias → canonical slot name.  THE alias table.
#:
#: Two tables existed and they DISAGREED, which is the reason this one
#: is written out rather than left implicit:
#:
#: * ``WRRB_FLEX`` (a WR/RB flex) normalized to ``FLEX`` here, and
#:   ``FLEX`` accepts a TE — so a slot that must not take a tight end
#:   would have taken one.  It is now its own slot.
#: * ``WRT`` meant WR/TE in ``frontend/lib/starter-slots.js`` and
#:   WR/RB/TE in ``src/scoring/replacement_level.py``.  Resolved to
#:   WR/RB/TE: "W/R/T" is the long-standing fantasy spelling of the
#:   full offensive flex (Yahoo's name for what Sleeper calls ``FLEX``),
#:   which is also what the two-of-three agreement says.
#: * ``DL_LB`` / ``DB_LB`` / ``DL_DB`` were all mapped to "every
#:   defender" by the frontend.  Their names say otherwise, and a
#:   two-family flex is exactly the NON-LAMINAR case a greedy fills
#:   wrongly, so they are declared precisely.  Neither live league runs
#:   one; this is the table being right rather than lucky.
_SLOT_ALIASES: dict[str, str] = {
    "SUPERFLEX": "SUPER_FLEX",
    "SFLEX": "SUPER_FLEX",
    "OP": "SUPER_FLEX",
    "Q_FLEX": "SUPER_FLEX",
    "QB_RB_WR_TE": "SUPER_FLEX",
    "WRT": "FLEX",
    "WRRBTE": "FLEX",
    "WRRB_FLEX": "WR_RB_FLEX",
    "RB_WR_FLEX": "WR_RB_FLEX",
    "RBWR_FLEX": "WR_RB_FLEX",
    "FLEX_WRRB": "WR_RB_FLEX",
    "WR_TE_FLEX": "REC_FLEX",
    "WRTE_FLEX": "REC_FLEX",
    "IDP_FL": "IDP_FLEX",
    "IDPFLX": "IDP_FLEX",
    "DEF_FLEX": "IDP_FLEX",
    "PK": "K",
}

#: Canonical flex slot → the positions it accepts.  IDP entries are
#: expanded through :data:`_IDP_FAMILIES` so every spelling of a family
#: resolves; the family TOKENS are what :func:`slot_demand` keys on.
_FLEX_SLOT_ELIGIBILITY: dict[str, frozenset[str]] = {
    "FLEX": frozenset(_FLEX_ELIGIBLE),
    "SUPER_FLEX": frozenset(_SUPER_FLEX_ELIGIBLE),
    "WR_RB_FLEX": frozenset({"RB", "WR"}),
    "REC_FLEX": frozenset({"WR", "TE"}),
    "IDP_FLEX": frozenset(_IDP_FLEX_ELIGIBLE),
    "DL_LB": frozenset(_IDP_FAMILIES["DL"] | _IDP_FAMILIES["LB"]),
    "DB_LB": frozenset(_IDP_FAMILIES["DB"] | _IDP_FAMILIES["LB"]),
    "DL_DB": frozenset(_IDP_FAMILIES["DL"] | _IDP_FAMILIES["DB"]),
}

#: Which base positions each flex slot's DEMAND is attributed to.  The
#: family token, never every spelling — see :func:`slot_demand`.
_FLEX_SLOT_DEMAND_KEYS: dict[str, tuple[str, ...]] = {
    "FLEX": ("RB", "WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
    "WR_RB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("TE", "WR"),
    "IDP_FLEX": ("DB", "DL", "LB"),
    "DL_LB": ("DL", "LB"),
    "DB_LB": ("DB", "LB"),
    "DL_DB": ("DB", "DL"),
}


def _normalize_slot_name(slot: str) -> str:
    s = (slot or "").strip().upper()
    return _SLOT_ALIASES.get(s, s)


#: Public name.  Slot aliasing has exactly one definition in the tree.
normalize_slot = _normalize_slot_name


def lineup_position(position: str) -> str:
    """A player position resolved to the token that fills a lineup slot.

    THE single position vocabulary for lineup purposes.  Offense passes
    through unchanged so a K slot still matches a kicker and a DEF slot a
    team defense; defenders resolve to DL / LB / DB, kept distinct.

    Existed only as ``frontend/lib/starter-slots.js::lineupPosition``
    before C2-U1.  That asymmetry is precisely why the frontend had to
    keep an optimizer: the server could not name a player in the
    vocabulary its own slots are written in, so it could not hand the
    client an assignment to render.
    """
    p = (position or "").strip().upper()
    return _LINEUP_FAMILY.get(p, p)


def slot_eligible_positions(slot: str) -> frozenset[str]:
    """Every player position legal in ``slot``.

    The declared eligibility table.  Consumers read it; nobody keeps a
    second copy (``_DEFAULT_FLEX_ELIGIBLE``, ``FLEX_POOLS``,
    ``_FLEX_SLOTS`` and friends all routed here in C2-U1).
    """
    norm = _normalize_slot_name(slot)
    flex = _FLEX_SLOT_ELIGIBILITY.get(norm)
    if flex is not None:
        return flex
    if norm in _IDP_FAMILIES:
        return frozenset(_IDP_FAMILIES[norm])
    return frozenset({norm}) if norm else frozenset()


def starter_slots_from_roster_positions(roster_positions: Sequence[str] | None) -> list[str]:
    """The lineup slots in a Sleeper ``roster_positions`` array.

    Bench / IR / taxi rows are not lineup slots.  Returns ``[]`` for an
    absent or empty array — the caller decides what that means, which is
    the distinction :func:`resolve_starter_slots` makes explicit.
    """
    if not roster_positions:
        return []
    return [
        _normalize_slot_name(str(p))
        for p in roster_positions
        if str(p).strip().upper() not in NON_LINEUP_SLOTS
    ]


def flatten_starter_slots(starters: dict[str, Any] | None) -> list[str]:
    """Expand ``{"QB": 1, "RB": 2, ...}`` → ``["QB", "RB", "RB", ...]``.

    THE canonical starter-slot flattener (LI-8).  Two byte-identical
    copies previously existed — ``src/ros/scrape.py::_flatten_starter_slots``
    and ``src/ros/playoff_sim.py::_load_starter_slots`` — each with its
    own private ``{"SFLEX": "SUPER_FLEX"}`` alias map, so a slot-name
    alias added to one silently diverged from the other.  ADR-007
    flagged the duplication; this is the single implementation, and it
    routes through ``_normalize_slot_name`` so slot aliasing has exactly
    one definition in the codebase.

    Slots with a non-integer or non-positive count are skipped.  Order
    follows the mapping's iteration order; callers that need a stable
    order should pass an ordered mapping (the registry JSON preserves
    document order through ``json.load``).
    """
    if not starters:
        return []
    out: list[str] = []
    for slot, count in starters.items():
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        out.extend([_normalize_slot_name(str(slot))] * n)
    return out


def resolve_starter_slots(
    *,
    roster_positions: Sequence[str] | None = None,
    roster_settings: dict[str, Any] | None = None,
) -> tuple[list[str], str | None]:
    """THE starter-slot truth ladder: live host → registry → refuse.

    Returns ``(slots, source)`` where ``source`` is
    ``"sleeper_roster_positions"``, ``"registry_starters"``, or ``None``
    when neither rung answered.

    **``None`` is a refusal, not a default lineup.**  Three consumers had
    written this ladder separately (``src/bdvm/league_config.py``,
    ``frontend/lib/starter-slots.js``, and the implicit version inside
    ``load_league_starter_slots``) and they disagreed on that exact
    point: a silent offense-only default undercounted an IDP league by
    twelve slots without saying so.

    An EMPTY ``roster_positions`` falls through to the registry rather
    than being served as "this league starts nobody" — /rosters gets
    teams and the lineup from two different Sleeper endpoints and only
    the lineup call sits in a bare except, so teams-present /
    lineup-empty is a reachable state.
    """
    slots = starter_slots_from_roster_positions(roster_positions)
    if slots:
        return slots, "sleeper_roster_positions"
    starters = (roster_settings or {}).get("starters")
    slots = flatten_starter_slots(starters if isinstance(starters, dict) else None)
    if slots:
        return slots, "registry_starters"
    return [], None


@dataclass(frozen=True)
class SlotDemand:
    """How many of each position a league's lineup demands.

    Three DISTINCT quantities, kept named and separate rather than
    averaged into one number, because they answer different questions
    and the tree already contained a measured disagreement about which
    one is meant:

    ``dedicated``
        Only slots that name a position.  Flex slots are deliberately
        NOT attributed to anyone.  This is
        ``roster_intel/profiles._required_slots``'s answer, and it is the
        honest one when you must not assume who fills a flex.

    ``flex_capacity``
        Flex slot instances, reported as themselves.  Nothing is
        invented about who takes them.

    ``even_split``
        Every flex slot split evenly across its eligible positions.  An
        **approximation**, flagged as one by
        :attr:`even_split_is_approximation`.  It is kept because four
        modules independently needed a single per-position number and
        each re-derived this same rule — but it is not truth: LI-5
        measured SUPER_FLEX going to a QB in 9 of 12 live rosters, not
        the 1-in-4 an even split assumes, so QB demand is off by ~40%.

    ``flex_priority``
        Every flex slot allocated WHOLE to one position, round-robin
        down :data:`FLEX_PRIORITY_ORDER`.  A different approximation
        with a different bias: a superflex slot becomes a whole QB —
        which is the reason the format is called superflex, and closer
        to what LI-5 measured than a quarter of one.  Integer-valued, so
        it answers "how many startable bodies", not "what fraction of a
        slot".

    Who actually fills a flex is ENDOGENOUS.  The measured answer is
    ``src/league_intel/replacement.py::measure_endogenous_starters``,
    which runs the exact solver over real rosters.  Reach for that when
    the number decides something; reach for an approximation only when a
    coarse sizing constant is genuinely enough, and say which one.
    """

    dedicated: dict[str, float] = field(default_factory=dict)
    flex_capacity: dict[str, int] = field(default_factory=dict)
    even_split: dict[str, float] = field(default_factory=dict)
    flex_priority: dict[str, int] = field(default_factory=dict)
    even_split_is_approximation: bool = True


#: Which position a flex slot goes to first when it is allocated whole.
#: QB leads because a SUPER_FLEX slot is a QB slot in all but name.
FLEX_PRIORITY_ORDER: tuple[str, ...] = ("QB", "RB", "WR", "TE", "DL", "LB", "DB")


def slot_demand(
    slots: Iterable[str],
    *,
    eligibility_overrides: Mapping[str, Collection[str]] | None = None,
) -> SlotDemand:
    """Per-position demand implied by a flat slot list.  See
    :class:`SlotDemand` — read which field you want before using one.

    ``eligibility_overrides`` carries a league's CONFIGURED flex
    eligibility (``flexEligible`` / ``idpFlexEligible`` in the registry),
    for the same reason :func:`solve_optimal_assignment` accepts it.
    """
    overrides = {
        _normalize_slot_name(str(k)): ordered_positions(v)
        for k, v in (eligibility_overrides or {}).items()
    }
    dedicated: dict[str, float] = {}
    flex_capacity: dict[str, int] = {}
    even: dict[str, float] = {}
    priority: dict[str, int] = {}
    # Round-robin cursors, one per flex slot NAME, so two FLEX slots
    # spread across RB then WR rather than doubling up on RB.
    cursors: dict[str, int] = {}
    for raw in slots:
        slot = _normalize_slot_name(str(raw))
        if not slot or slot in NON_LINEUP_SLOTS or slot == "DEF":
            continue
        # Demand is keyed by the FAMILY token a slot is named in — the
        # same vocabulary :func:`lineup_position` resolves a player to,
        # and the one ``_positional_coverage`` counts bodies against.
        # NOT by the eligibility set: a dedicated ``DL`` slot demands one
        # DL, it does not demand a quarter each of DL/DE/DT/EDGE, and
        # splitting it that way would leave the numerator and denominator
        # of every coverage ratio in different vocabularies.
        demand_keys = _FLEX_SLOT_DEMAND_KEYS.get(slot)
        if demand_keys is not None:
            flex_capacity[slot] = flex_capacity.get(slot, 0) + 1
            eligible = list(overrides.get(slot) or demand_keys)
        else:
            dedicated[slot] = dedicated.get(slot, 0.0) + 1.0
            priority[slot] = priority.get(slot, 0) + 1
            eligible = [slot]
        if not eligible:
            continue
        share = 1.0 / len(eligible)
        for pos in eligible:
            even[pos] = even.get(pos, 0.0) + share
        if demand_keys is not None:
            ranked = [p for p in FLEX_PRIORITY_ORDER if p in eligible] or list(eligible)
            cursor = cursors.get(slot, 0)
            cursors[slot] = cursor + 1
            winner = ranked[cursor % len(ranked)]
            priority[winner] = priority.get(winner, 0) + 1
    return SlotDemand(
        dedicated=dedicated,
        flex_capacity=flex_capacity,
        even_split=even,
        flex_priority=priority,
    )


def configured_slot_eligibility(
    roster_settings: Mapping[str, Any] | None,
) -> dict[str, tuple[str, ...]]:
    """A league's CONFIGURED flex eligibility, in THIS module's vocabulary.

    Sleeper lets a league decide what its flex slots accept, and the
    registry records that as ``flexEligible`` / ``sflexEligible`` /
    ``idpFlexEligible``.  Every consumer that solves or measures a lineup
    needs the same map, and until now each built its own: ``bdvm``'s keys
    it ``"SFLEX"`` (`league_config.py`), ``trade/suggestions.py`` builds a
    two-entry variant.  Neither is an owner of slot rules; this module is
    (see the "one owner" note above), so the resolver belongs here.

    Returns ONLY the slots the league actually configures.  An absent or
    empty list means "not configured", and the DECLARED default applies —
    which is different from an empty eligibility set, and the difference
    matters: an empty set would make the slot unfillable rather than
    ordinary.

    Keys come back normalized (``SFLEX`` → ``SUPER_FLEX``) and positions
    in canonical lineup-card order, so the result can be handed straight
    to :func:`solve_optimal_assignment` or :func:`slot_demand`.
    """
    if not isinstance(roster_settings, Mapping):
        return {}
    out: dict[str, tuple[str, ...]] = {}
    for key, slot in (
        ("flexEligible", "FLEX"),
        ("sflexEligible", "SUPER_FLEX"),
        ("idpFlexEligible", "IDP_FLEX"),
    ):
        raw = roster_settings.get(key)
        if not isinstance(raw, (list, tuple)):
            continue
        positions = ordered_positions(lineup_position(str(x)) for x in raw if str(x or "").strip())
        if positions:
            out[_normalize_slot_name(slot)] = positions
    return out


def load_league_starter_slots(league_key: str | None = None) -> list[str]:
    """Flat starter-slot list for a league, read from the registry.

    Returns ``[]`` when no league config resolves or it carries no
    starters — callers degrade rather than raise (the playoff sim falls
    back to its empirical model, team-strength logs and skips).
    """
    try:
        from src.api.league_registry import (  # noqa: PLC0415
            get_default_league,
            get_league_by_key,
        )

        cfg = get_league_by_key(league_key) if league_key else get_default_league()
        if cfg is None or not cfg.roster_settings:
            return []
        return flatten_starter_slots(cfg.roster_settings.get("starters"))
    except Exception:  # noqa: BLE001 — registry problems must not break callers
        return []


def _eligible_for_slot(slot: str, position: str) -> bool:
    """Is a player of this position legal in this slot?

    Decided on the raw token OR its resolved FAMILY, because those are
    two spellings of one fact and the tables that hold them are not the
    same size.  ``_SLOT_ELIGIBLE`` is Sleeper-faithful (``LB`` means
    ``LB``); ``_LINEUP_FAMILY`` is deliberately wider, absorbing the
    spellings the scrapers actually emit (``NT``, ``OLB``/``ILB``/``MLB``,
    ``FS``/``SS``).

    Testing only the raw token left every one of those six spellings
    eligible for **nothing** — they resolved to a correct family and then
    matched no slot, so a genuine linebacker listed as ``MLB`` could not
    start at LB, at IDP_FLEX, or anywhere else.  Measured 2026-08-19:
    ``NT``, ``OLB``, ``ILB``, ``MLB``, ``FS`` and ``SS`` all False for
    DL/LB/DB/IDP_FLEX alike.  Zero of 660 rostered players carry one
    today, which is why nothing caught it.

    Strictly a widening: an ``or`` cannot make an eligible player
    ineligible, so no lineup that solved before can change except by
    gaining a candidate that was always legal.
    """
    token = (position or "").strip().upper()
    if not token:
        return False
    eligible = slot_eligible_positions(slot)
    return token in eligible or lineup_position(token) in eligible


def _player_eligible_for_slot(slot: str, player: RosterPlayer) -> bool:
    """Slot eligibility over ALL of a player's fantasy positions.

    Sleeper evaluates eligibility against ``fantasy_positions``, so a
    DL/LB hybrid legally fills either an LB or a DL slot.  Checking
    only ``position`` (as this module used to) silently benches the
    better lineup — confirmed against real Sleeper best-ball weeks in
    ``tests/league_intel/test_lineup_exactness.py``.
    """
    return any(_eligible_for_slot(slot, pos) for pos in player.eligible_positions())


#: Public name.  THE eligibility predicate — consumers call this instead
#: of keeping a slot→positions table of their own.
player_eligible_for_slot = _player_eligible_for_slot


def _objective(player: RosterPlayer) -> float | None:
    """The assignment objective, or ``None`` when it is UNKNOWN.

    Discounts ``ros_value`` when the player is injured / on bye.  Returns
    ``None`` — never ``0.0`` — when no value was supplied, so an
    unpriceable player cannot silently win a slot.  ``0.0`` supplied
    explicitly is a real value and passes through as one.
    """
    if player.ros_value is None:
        return None
    base = max(0.0, float(player.ros_value))
    if player.injured:
        base *= 0.4
    elif player.bye:
        base *= 0.0
    return base


def _value_with_health_penalty(player: RosterPlayer) -> float:
    """Numeric objective for arithmetic, with UNKNOWN read as 0.0.

    Only for callers that have ALREADY excluded unpriced players (the
    solver does, before it ever sorts).  ``_objective`` is the honest
    form; this exists so the arithmetic below is not littered with
    ``or 0.0`` — the very coercion this unit retired.
    """
    value = _objective(player)
    return 0.0 if value is None else value


def _eligibility_predicate(
    slot_eligibility: Mapping[str, Collection[str]] | None,
):
    """The eligibility test for one solve.

    ``slot_eligibility`` overrides the DECLARED table for named slots
    only, and exists because Sleeper lets a league CONFIGURE what its
    flex accepts (``flexEligible`` / ``sflexEligible`` /
    ``idpFlexEligible`` in the registry, which
    ``src/bdvm/league_config.py`` already reads).  Slots it does not
    name keep the declared table.

    It is not a seam for inventing a private vocabulary: what it carries
    is the LEAGUE's own rule, and a consumer passing anything else is
    reintroducing the second eligibility table this unit deleted.
    """
    if not slot_eligibility:
        return _player_eligible_for_slot

    overrides = {
        _normalize_slot_name(str(k)): frozenset(str(p).strip().upper() for p in v if str(p).strip())
        for k, v in slot_eligibility.items()
    }

    def _predicate(slot: str, player: RosterPlayer) -> bool:
        allowed = overrides.get(_normalize_slot_name(slot))
        if allowed is None:
            return _player_eligible_for_slot(slot, player)
        return any(pos in allowed for pos in player.eligible_positions())

    return _predicate


def solve_optimal_assignment(
    pool: list[RosterPlayer],
    slots: list[str],
    *,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
) -> dict[int, RosterPlayer]:
    """Exact maximum-weight player→slot assignment.

    Returns ``{slot_index: player}`` maximizing Σ adjusted value over
    assigned players, subject to each player filling at most one slot
    and each slot holding at most one eligible player.

    Algorithm: matroid greedy with augmenting paths.  Slot eligibility
    defines a transversal matroid and each player's weight is the same
    whichever slot they fill, so processing players in descending
    weight and admitting a player whenever an augmenting path to a
    free slot exists is provably optimal — for any eligibility
    structure, laminar or not.  (Admitting a player may reshuffle
    already-assigned players between slots; it never evicts one,
    which is exactly why the exchange argument holds.)

    Deterministic: players are ordered by ``(-value, player_id)`` and
    augmenting paths explore slots in index order, so equal-value ties
    resolve the same way on every run.

    Players whose objective is UNKNOWN (``ros_value is None``) are not
    candidates — an unpriceable player must not win a slot a priced one
    could fill.  Use :func:`assign_lineup` to see which they were; this
    function returns only the assignment.
    """
    is_eligible = _eligibility_predicate(slot_eligibility)
    ordered = sorted(
        (p for p in pool if _objective(p) is not None),
        key=lambda p: (-_value_with_health_penalty(p), p.player_id),
    )
    eligible_slots: list[list[int]] = [
        [i for i, slot in enumerate(slots) if is_eligible(slot, p)] for p in ordered
    ]
    # slot index -> index into `ordered`
    slot_owner: dict[int, int] = {}

    def _augment(player_idx: int, seen: set[int]) -> bool:
        for slot_idx in eligible_slots[player_idx]:
            if slot_idx in seen:
                continue
            seen.add(slot_idx)
            owner = slot_owner.get(slot_idx)
            if owner is None or _augment(owner, seen):
                slot_owner[slot_idx] = player_idx
                return True
        return False

    seen_ids: set[str] = set()
    for idx, player in enumerate(ordered):
        # Guard against a roster carrying the same player twice — the
        # matching would otherwise happily start them in two slots.
        if player.player_id in seen_ids:
            continue
        seen_ids.add(player.player_id)
        _augment(idx, set())

    assignment = {slot_idx: ordered[p_idx] for slot_idx, p_idx in slot_owner.items()}
    return _canonicalize_slots(assignment, slots, is_eligible)


@dataclass(frozen=True)
class LineupAssignment:
    """The canonical answer to "who starts where", plus what we could not
    answer and why.

    ``slots`` is the slot list this was solved against, so a consumer can
    render slot-ordered without re-deriving the order.  ``assignments``
    is ``{slot_index: player}``.
    """

    slots: tuple[str, ...]
    assignments: dict[int, RosterPlayer]
    unpriced_ids: frozenset[str]
    duplicate_ids: frozenset[str]

    @property
    def starter_ids(self) -> set[str]:
        return {p.player_id for p in self.assignments.values()}

    @property
    def score(self) -> float:
        return float(sum(_value_with_health_penalty(p) for p in self.assignments.values()))

    @property
    def unfilled_slots(self) -> list[str]:
        return [s for i, s in enumerate(self.slots) if i not in self.assignments]

    def bench_ids(self, pool: Iterable[RosterPlayer]) -> set[str]:
        """Everyone rostered who did not start AND whom we could price.

        Unpriced players are in neither the starters nor the bench: "we
        have no read on this player" is a third state, and folding it
        into the bench is the same missing-is-zero error one layer up.
        """
        started = self.starter_ids
        return {
            p.player_id
            for p in pool
            if p.player_id not in started and p.player_id not in self.unpriced_ids
        }


def assign_lineup(
    pool: Iterable[RosterPlayer],
    slots: Sequence[str],
    *,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
) -> LineupAssignment:
    """THE public lineup-assignment entry point.

    Exact maximum-weight assignment (see
    :func:`solve_optimal_assignment`) plus the honest reporting the bare
    dict cannot carry: which players had no objective, which were
    duplicates, and which slots are unfilled.
    """
    pool_list = list(pool)
    slot_list = [_normalize_slot_name(str(s)) for s in slots]
    unpriced = frozenset(p.player_id for p in pool_list if _objective(p) is None)
    seen: set[str] = set()
    duplicates: set[str] = set()
    for p in pool_list:
        if p.player_id in seen:
            duplicates.add(p.player_id)
        seen.add(p.player_id)
    return LineupAssignment(
        slots=tuple(slot_list),
        assignments=solve_optimal_assignment(
            pool_list, slot_list, slot_eligibility=slot_eligibility
        ),
        unpriced_ids=unpriced,
        duplicate_ids=frozenset(duplicates),
    )


def _canonicalize_slots(
    assignment: dict[int, RosterPlayer],
    slots: list[str],
    is_eligible=_player_eligible_for_slot,
) -> dict[int, RosterPlayer]:
    """Pick a canonical representative among equally-optimal lineups.

    A maximum-weight assignment is rarely unique: a WR worth the same
    in the WR slot and the FLEX slot can sit in either without changing
    the score.  Which one the matching happens to return is an artifact
    of augmenting-path order, and it leaks into the UI ("why is my WR1
    listed as my FLEX?").

    Callers expect the intuitive labelling: higher-value players in the
    more restrictive slots, which is the order ``slots`` is already
    sorted in.  This pass repeatedly (a) slides a player into an
    earlier empty slot they are eligible for, and (b) swaps two
    assigned players when the earlier slot holds the lower value and
    both are cross-eligible.  Both moves keep the multiset of started
    players — and therefore the total — identical, so optimality is
    preserved by construction.
    """
    changed = True
    while changed:
        changed = False
        for i in range(len(slots)):
            for j in range(i + 1, len(slots)):
                here, there = assignment.get(i), assignment.get(j)
                if there is None:
                    continue
                if here is None:
                    if is_eligible(slots[i], there):
                        assignment[i] = there
                        del assignment[j]
                        changed = True
                    continue
                if _value_with_health_penalty(here) >= _value_with_health_penalty(there):
                    continue
                if is_eligible(slots[i], there) and is_eligible(slots[j], here):
                    assignment[i], assignment[j] = there, here
                    changed = True
    return assignment


def optimize_lineup(
    roster: Iterable[RosterPlayer],
    *,
    starter_slots: Iterable[str],
) -> LineupSolution:
    """Exact best-projected lineup over the configured starter slots.

    The starting lineup is a true maximum-weight assignment (see
    ``solve_optimal_assignment`` and the module docstring); slots are
    reported in restrictiveness order for stable output.

    Returns:
        LineupSolution with starting_lineup_score = Σ best lineup, plus
        the bench_depth contribution + positional_coverage +
        health_availability sub-scores ready to feed
        ``team_ros_strength``'s composite formula.
    """
    roster_list = list(roster)
    # Deterministic for equal values: without the id tiebreak the BENCH
    # order (and so the decayed depth score) depended on input order,
    # while the starting lineup did not — a permutation-invariance hole
    # in the wrapper rather than in the solver.
    pool = sorted(
        roster_list,
        key=lambda p: (-_value_with_health_penalty(p), p.player_id),
    )
    used: set[str] = set()
    slot_order = sorted(
        [_normalize_slot_name(s) for s in starter_slots],
        key=_slot_priority,
    )

    solution = assign_lineup(pool, slot_order)
    assignment = solution.assignments
    # Unpriced players are neither started nor benched — see
    # ``LineupAssignment.bench_ids``.  Counting them as bench depth would
    # credit a team for players nobody can price.
    pool = [p for p in pool if p.player_id not in solution.unpriced_ids]

    starting_total = 0.0
    starting_rows: list[dict[str, Any]] = []
    unfilled: list[str] = []

    for slot_idx, slot in enumerate(slot_order):
        pick = assignment.get(slot_idx)
        if pick is None:
            unfilled.append(slot)
            continue
        used.add(pick.player_id)
        adj_value = _value_with_health_penalty(pick)
        starting_total += adj_value
        starting_rows.append(
            {
                "slot": slot,
                "playerId": pick.player_id,
                "canonicalName": pick.canonical_name,
                "position": pick.position,
                "rosValue": round(float(pick.ros_value), 2),
                "adjustedValue": round(adj_value, 2),
                "confidence": round(float(pick.confidence), 3),
                "flagged": "injured" if pick.injured else ("bye" if pick.bye else None),
            }
        )

    # Bench contribution — best-ball spike-week credit.
    bench: list[RosterPlayer] = [p for p in pool if p.player_id not in used]
    bench_total = 0.0
    bench_rows: list[dict[str, Any]] = []
    by_pos_seen: dict[str, int] = {}
    for player in bench:
        if len(bench_rows) >= DEPTH_BENCH_LIMIT:
            break
        decay_per_player = _DEPTH_DECAY.get(player.position.upper(), _DEFAULT_DECAY)
        seen = by_pos_seen.get(player.position.upper(), 0)
        # First bench player at a position counts fully; second decays
        # by `decay_per_player`; third by decay^2; etc.
        depth_factor = decay_per_player**seen
        adj_value = _value_with_health_penalty(player) * depth_factor
        bench_total += adj_value
        bench_rows.append(
            {
                "playerId": player.player_id,
                "canonicalName": player.canonical_name,
                "position": player.position,
                "rosValue": round(float(player.ros_value), 2),
                "depthFactor": round(depth_factor, 3),
                "depthContribution": round(adj_value, 2),
            }
        )
        by_pos_seen[player.position.upper()] = seen + 1

    # Positional coverage — penalize teams missing bodies where the
    # league actually starts them.  Slot-derived (LI-5): covers K and
    # IDP, and weights each position by its starter demand.
    coverage_score = _positional_coverage(roster, slot_order)

    # Health availability — share of starters not flagged injured/bye.
    healthy_starters = sum(1 for r in starting_rows if not r.get("flagged"))
    health_score = healthy_starters / len(starting_rows) * 100 if starting_rows else 0.0

    return LineupSolution(
        starting_lineup_score=round(starting_total, 2),
        starting_lineup=starting_rows,
        bench_depth_score=round(bench_total, 2),
        bench_depth=bench_rows,
        positional_coverage_score=round(coverage_score, 2),
        health_availability_score=round(health_score, 2),
        unfilled_slots=unfilled,
    )


# Restrictive slots fill before flexible ones so we don't burn a SF
# pick on a WR who could've slotted FLEX.
def _slot_priority(slot: str) -> tuple[int, str]:
    if slot == "SUPER_FLEX":
        return (3, slot)
    if slot in {"FLEX", "IDP_FLEX"}:
        return (2, slot)
    return (0, slot)


# How much depth a league wants beyond its raw starter demand, as a
# multiplier on demand.  1.5 == "your starters plus a half-line of
# cover".  Chosen to reproduce the long-standing offense targets it
# replaces (QB 2, RB 4, TE ~3) while extending to K and IDP.
_COVERAGE_DEPTH_MULTIPLIER = 1.5


def _slot_demand(slots: Iterable[str]) -> dict[str, float]:
    """The even-split demand approximation, for coverage sizing only.

    Delegates to :func:`slot_demand` — the ONE declared contract — rather
    than re-deriving the split.  Byte-for-byte the same numbers it always
    produced; see :class:`SlotDemand` for why the approximation is kept
    but labelled, and for the measured answer when it must be right.
    """
    return dict(slot_demand(slots).even_split)


def _positional_coverage(
    roster: Iterable[RosterPlayer],
    starter_slots: Iterable[str] | None = None,
) -> float:
    """0-100 score for "does this roster have bodies where the league
    starts them".

    Derived from the league's ACTUAL slots rather than a hardcoded
    offense-only table.  The previous implementation scored depth at
    QB/RB/WR/TE only, with fixed targets — in a league that starts a
    kicker and nine IDP, a roster with zero linebackers still scored a
    perfect 100.  In practice it returned exactly 100.00 for all 12
    teams, contributing a constant 5 points to every composite and
    discriminating nothing.

    Counting is eligibility-aware: a DL/LB hybrid counts toward both
    DL and LB cover, matching how the lineup optimizer may deploy them.
    Positions are weighted by demand, so a 3-DB league weights DB three
    times as heavily as a 1-QB slot.

    ``starter_slots`` is optional for backwards compatibility; without
    it the league's demand is unknown and the score falls back to the
    historical offense-only table.
    """
    if starter_slots is None:
        counts: dict[str, int] = {}
        for p in roster:
            counts[p.position.upper()] = counts.get(p.position.upper(), 0) + 1
        legacy_targets = {"QB": 2, "RB": 4, "WR": 5, "TE": 2}
        pts = 0.0
        for pos, target in legacy_targets.items():
            pts += min(1.0, counts.get(pos, 0) / target) * (100.0 / len(legacy_targets))
        return pts

    demand = _slot_demand(starter_slots)
    if not demand:
        return 0.0

    roster_list = list(roster)
    total_weight = 0.0
    earned = 0.0
    for pos, need in demand.items():
        target = max(1.0, need * _COVERAGE_DEPTH_MULTIPLIER)
        have = sum(1 for p in roster_list if _player_eligible_for_slot(pos, p))
        earned += min(1.0, have / target) * need
        total_weight += need
    return (earned / total_weight) * 100.0 if total_weight else 0.0
