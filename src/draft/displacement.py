"""Who gets cut to make room for a rookie, and what that costs.

The Perfect Draft optimizer needs one number per roster spot it consumes:
the **Effective Cut Cost** (ECC) of the player who would be released.  This
module produces the ordered ladder of those numbers.

Three decisions here are load-bearing and easy to get wrong if changed:

**1. Cost is measured against replacement, not against zero.**

    ECC(p) = max(0, base(p) - waiverValue(pos)) * scarcityMultiplier(pos)

Releasing a player does not cost you his whole value — it costs you the gap
between him and the best player you could add off waivers at that position.
The symmetric statement is what makes the optimizer work at all: an *empty*
roster spot is not worth zero either, it is worth waiver level, so a rookie's
gain is also measured over replacement (see ``surplusOverReplacement`` in
``frontend/lib/perfect-draft.js``).  Both sides use the same
``waiverValue(pos)`` primitive, so the comparison is symmetric by construction.

Without this, the optimizer is degenerate.  Value-per-dollar rises roughly 30x
from the top of the rookie ladder to the bottom — both the value and the price
come from the same convex Hill curve (``server.py::_rookie_dollars_from_values``)
— so a raw ``max sum(value)`` objective just reads the shape of the price curve
back out and recommends buying thirty $1 dart throws.

**2. An unranked player's ECC is 0, and that is deliberate.**

Players past the board's ``OVERALL_RANK_LIMIT`` carry no ``rankDerivedValue``.
They are, by definition, at or below waiver level, so releasing one genuinely
costs nothing you cannot replace.  We stamp ``valueBasis="assumedWaiver"`` and
surface it, rather than substituting the raw board floor.

That floor is not a value.  Measured on the live board, 19 players sit at
exactly 497 and 19 more at exactly 375, nearly all ``_sites=1`` with no
position — ``src/league_intel/replacement.py`` calls the literal roster tail
"the noisiest number in the league (deep dart throws, and any identity-join
miss lands there)".  Treating those numbers as real costs would let a join miss
on a genuine asset read as a cheap cut.  The ``assumedWaiver`` stamp exists so
the UI can say "unpriced — verify before releasing" instead of quietly ranking
him first.

**3. Droppability is a bipartite matching, not a per-position count.**

``dynasty_main`` starts FLEX x2 and SUPER_FLEX x1.  Cutting your WR3 may be
fine on its own while cutting WR3 *and* RB3 is not, because the flex slots can
absorb one of them but not both.  So a "keep at least N at each position" rule
is wrong in both directions.  Each rung of the ladder is therefore validated by
re-running the real assignment solver
(``src/ros/lineup.py::solve_optimal_assignment``) over the surviving roster.

Building the ladder greedily is nevertheless *exactly* optimal, not a
heuristic.  The sets of players that can fill every starting slot are the
spanning sets of a transversal matroid; the legal cut-sets are precisely the
independent sets of its dual.  Greedy minimum-weight selection is optimal on a
matroid, and minimum-weight independent sets of successive sizes nest — so one
cheapest-first ladder simultaneously gives the optimal cut-set at *every*
cardinality, which is what lets the optimizer treat total displacement cost as
a function of "how many rookies" alone.

Currency discipline (``src/api/gameplan.py`` states this as a repo-wide
tripwire): ``rankDerivedValue`` (0-9999) answers *what is this asset worth* and
is the only scale used for cost arithmetic here.  ``rosValue`` (a 0-100
log-rank index) answers *who starts* and is used only for lineup feasibility.
They are never mixed.  Note also that of the six ``ScarcityComponents`` fields
only the three ``*Scarcity`` ones are dimensionless — ``replacementGap``,
``eliteSeparation`` and ``starterSeparation`` are in ``rosValue`` units and
must never be added to a ``rankDerivedValue``.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from src.league_intel.replacement import ScarcityComponents
from src.ros.lineup import RosterPlayer, solve_optimal_assignment

__all__ = [
    "FEASIBILITY_OBJECTIVE",
    "CutCandidate",
    "RosterAsset",
    "build_cut_ladder",
    "count_free_agents",
    "effective_cut_cost",
    "free_agent_ladder",
    "scarcity_multiplier",
    "waiver_values_by_position",
]

# Ladder length cap.  The optimizer's own bound stops far short of this on any
# real roster (a full 58-man roster yields single-digit useful rungs once cut
# costs are replacement-adjusted), but the ladder is built before the optimizer
# runs, so it needs its own terminator.  When the cap binds we say so in the
# returned notes rather than letting a truncated ladder read as a complete one.
MAX_LADDER_RUNGS = 30

# Multiplier band for how replaceable a position is, taken verbatim from
# ``src/roster_intel/targets.py::_scarcity_multiplier`` so the two engines
# answer "can I just pick one up?" identically.  0.85x when trivially
# replaceable, 1.15x when nothing is available.
_SCARCITY_BASE = 0.85
_SCARCITY_GAIN = 0.30


#: The assignment objective handed to the lineup solver for FEASIBILITY
#: questions — "how many starting slots can the surviving roster fill".
#:
#: Any constant works, and that is the point: ``solve_optimal_assignment`` is
#: a matroid greedy with augmenting paths, which never evicts an assigned
#: player, so it returns a MAXIMUM-CARDINALITY matching whatever the weights
#: are.  Weights decide WHO starts; they cannot decide HOW MANY.
#:
#: ``0.0`` and not ``None`` on purpose: ``None`` is UNKNOWN and the solver
#: excludes it, but a player the board could not price still occupies a body
#: that can legally fill a slot.  Cost arithmetic uses ``board_value``
#: (``rankDerivedValue``) and never this field.
FEASIBILITY_OBJECTIVE = 0.0


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class RosterAsset:
    """One rostered player, as the displacement model sees him."""

    player_id: str
    name: str
    position: str
    #: ``rankDerivedValue``.  ``None`` when the board did not rank this player.
    board_value: float | None
    #: 0-100 log-rank index.  Lineup feasibility ONLY — never cost arithmetic.
    ros_value: float = 0.0
    fantasy_positions: tuple[str, ...] = ()
    injured: bool = False
    bye: bool = False

    def to_lineup_player(self) -> RosterPlayer:
        return RosterPlayer(
            player_id=self.player_id,
            canonical_name=self.name,
            position=self.position,
            ros_value=self.ros_value,
            injured=self.injured,
            bye=self.bye,
            fantasy_positions=self.fantasy_positions,
        )


@dataclass(frozen=True)
class CutCandidate:
    """One rung of the cut ladder."""

    player_id: str
    name: str
    position: str
    #: Effective Cut Cost, in ``rankDerivedValue`` units.
    effective_cut_cost: float
    #: The value the cost was computed from (board value, or the assumed
    #: waiver level for an unranked player).
    base_value: float
    #: ``"board"`` when the player carried a ``rankDerivedValue``,
    #: ``"assumedWaiver"`` when he did not and waiver level stood in.
    value_basis: str
    #: Waiver level at this player's position.
    waiver_value: float
    scarcity_multiplier: float
    #: 1-based position in the ladder; rung 1 is released first.
    rung: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "effectiveCutCost": round(self.effective_cut_cost, 1),
            "baseValue": round(self.base_value, 1),
            "valueBasis": self.value_basis,
            "waiverValue": round(self.waiver_value, 1),
            "scarcityMultiplier": round(self.scarcity_multiplier, 4),
            "rung": self.rung,
            "valueScale": "rankDerivedValue",
        }


@dataclass
class CutLadder:
    """The ordered ladder plus everything a caller needs to read it honestly."""

    rungs: list[CutCandidate] = field(default_factory=list)
    #: Players excluded because releasing them would break the starting lineup.
    undroppable: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: Starter slots the roster could not fill even before any cut.
    unfilled_slots_at_baseline: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "rungs": [r.to_dict() for r in self.rungs],
            "undroppable": self.undroppable,
            "notes": self.notes,
            "unfilledSlotsAtBaseline": self.unfilled_slots_at_baseline,
        }


def scarcity_multiplier(sc: ScarcityComponents | None) -> float:
    """How costly it is to have to replace this position off waivers.

    Uses ``waiver_scarcity`` and only that, for the reason
    ``src/roster_intel/targets.py`` gives: the replacement module keeps its six
    signals separate on purpose ("top-heavy" and "nothing on waivers" call for
    opposite roster moves), so collapsing them here would undo that design.
    Waiver scarcity is the one that answers the question being asked.

    Returns 1.0 (inert) when the signal is missing, so a league with no roster
    snapshot degrades to plain replacement-adjusted values rather than failing.
    """
    if sc is None or sc.waiver_scarcity is None:
        return 1.0
    return _SCARCITY_BASE + _SCARCITY_GAIN * _clamp(float(sc.waiver_scarcity), 0.0, 1.0)


def _available_players(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
) -> list[tuple[float, str]]:
    """``(value, position)`` for every player nobody can have for free.

    A player is available when he is on no roster in the league AND is not in
    ``unavailable_keys`` — which is how rookies in the live auction are kept
    out.  See ``src/draft/rookie_pool.py`` for why that exclusion is not
    cosmetic: on the 2026-08-04 board 5 of the 6 best "free agents" were lots
    in the very auction being optimized.

    Keys are matched case-insensitively against ``playerId`` and all three name
    fields the contract carries (``legacyRef`` / ``canonicalName`` /
    ``displayName``), mirroring ``board_values_from_contract``.
    """
    if not isinstance(contract, Mapping):
        return []
    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        return []

    taken = {str(k).strip().lower() for k in rostered_keys if str(k or "").strip()}
    taken |= {str(k).strip().lower() for k in unavailable_keys if str(k or "").strip()}

    out: list[tuple[float, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        # Picks are not waiver-wire replacements for a roster spot.
        if str(row.get("assetClass") or "").lower() == "pick":
            continue
        pos = str(row.get("position") or "").strip().upper()
        if not pos or pos == "PICK":
            continue
        value = row.get("rankDerivedValue")
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        keys = {
            str(row.get(f) or "").strip().lower()
            for f in ("playerId", "legacyRef", "canonicalName", "displayName")
        }
        keys.discard("")
        if keys & taken:
            continue
        out.append((float(value), pos))
    return out


def waiver_values_by_position(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
) -> dict[str, float]:
    """Best available (unrostered) ``rankDerivedValue`` at each position.

    This is the opportunity cost of a roster spot: what you could put in it
    without spending a draft dollar.  A player rostered by *any* team in the
    league is not available, so ``rostered_keys`` must be the league-wide set,
    not one team's — and neither is a rookie you would have to outbid eleven
    rivals for, which is what ``unavailable_keys`` removes.
    """
    out: dict[str, float] = {}
    for value, pos in _available_players(contract, rostered_keys, unavailable_keys):
        if value > out.get(pos, 0.0):
            out[pos] = value
    return out


def free_agent_ladder(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
    *,
    limit: int = 60,
) -> list[float]:
    """The best ``limit`` freely-available values, highest first.

    ``waiver_values_by_position`` answers "what is the best free player at this
    position"; this answers "what are the best free players, in order".  The
    difference is the whole point of ``W(k)``: a plan that takes *k* roster
    spots does not forgo the best free agent *k* times over — there is only one
    of him.  The second spot forgoes the second-best, and so on down a ladder
    that declines.

    Deliberately position-agnostic.  A roster spot can hold anyone, and this
    model values a roster as the sum of its players' market values throughout
    (the cut side included), so the alternative use of a spot is simply the
    best player still going free.  One consequence is worth knowing rather than
    discovering: on the 2026-08-04 board 13 of the top 20 free agents are tight
    ends, a downstream effect of the TE++ basis this league is scored on.  That
    is what the board says, not a bug here — but it does mean W(k) is largely a
    tight-end ladder for this league.
    """
    values = sorted(
        (v for v, _ in _available_players(contract, rostered_keys, unavailable_keys)),
        reverse=True,
    )
    return values[: max(0, int(limit))]


def count_free_agents(
    contract: Mapping[str, Any] | None,
    rostered_keys: Iterable[str],
    unavailable_keys: Iterable[str] = (),
) -> int:
    """How many players the free-agent universe actually contains.

    Distinct from ``len(free_agent_ladder(...))``, which is capped by ``limit``
    and would otherwise report the cap as if it were the population.
    """
    return len(_available_players(contract, rostered_keys, unavailable_keys))


def _waiver_value_for(position: str, waiver_values: Mapping[str, float]) -> float:
    """Waiver level at a position, with an honest fallback.

    A rostered player with no position (the contract leaves ``position`` empty
    for thin-coverage rows) cannot be matched to a positional waiver level.
    Using 0.0 would make him look maximally expensive to cut, which is the
    opposite of the truth for what is almost always a deep bench body, so we
    fall back to the *cheapest* positional waiver level on the board — the most
    conservative real number available.
    """
    pos = (position or "").strip().upper()
    if pos in waiver_values:
        return float(waiver_values[pos])
    if not waiver_values:
        return 0.0
    return float(min(waiver_values.values()))


def effective_cut_cost(
    asset: RosterAsset,
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, ScarcityComponents] | None = None,
) -> tuple[float, float, str, float, float]:
    """``(ecc, base_value, value_basis, waiver_value, scarcity_mult)``.

    See the module docstring for why the cost is measured over waiver level and
    why an unranked player scores 0.
    """
    waiver = _waiver_value_for(asset.position, waiver_values)
    board = asset.board_value
    if isinstance(board, (int, float)) and board > 0:
        base = float(board)
        basis = "board"
    else:
        # Unranked: at or below waiver level by definition.
        base = waiver
        basis = "assumedWaiver"

    sc = None
    if scarcity:
        sc = scarcity.get((asset.position or "").strip().upper())
    mult = scarcity_multiplier(sc)
    ecc = max(0.0, base - waiver) * mult
    return ecc, base, basis, waiver, mult


def _filled_slot_count(
    pool: Sequence[RosterAsset],
    slots: Sequence[str],
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
) -> int:
    if not slots:
        return 0
    assignment = solve_optimal_assignment(
        [a.to_lineup_player() for a in pool],
        list(slots),
        slot_eligibility=slot_eligibility or None,
    )
    return len(assignment)


def build_cut_ladder(
    roster: Sequence[RosterAsset],
    starter_slots: Sequence[str],
    waiver_values: Mapping[str, float],
    scarcity: Mapping[str, ScarcityComponents] | None = None,
    *,
    slot_eligibility: Mapping[str, Collection[str]] | None = None,
    max_rungs: int = MAX_LADDER_RUNGS,
) -> CutLadder:
    """Cheapest-first ladder of players this team would actually release.

    Each rung is validated against the real lineup solver: a player is only
    admitted if releasing him does not reduce how many starting slots the
    surviving roster can fill.  Comparing against the *baseline* fill count
    rather than against ``len(starter_slots)`` matters — a roster that already
    cannot fill every slot (an injured-out position, a league whose registry
    starters exceed what the team rosters) would otherwise have an empty
    ladder, which would read as "nobody is droppable" when the truth is
    "nothing gets worse".

    ``slot_eligibility`` is the league's CONFIGURED flex rule, forwarded
    verbatim to the canonical solver.  It is threaded, never interpreted —
    ``src/ros/lineup.py`` remains the single owner of what a slot admits, and
    this module holds no eligibility table of its own.  ``None`` (and an empty
    map, which means "nothing configured", not "nothing is eligible") leaves
    the owner on its built-in defaults, so callers that supply nothing are
    unaffected.

    Greedy is exactly optimal here; see the module docstring for the matroid
    argument.  It is also cheap: the cheapest candidate is almost always
    feasible, so this is typically one solver call per rung.
    """
    ladder = CutLadder()
    pool = [a for a in roster if a is not None]
    if not pool:
        ladder.notes.append("roster is empty — no cut ladder")
        return ladder

    slots = [s for s in (starter_slots or []) if s]
    if not slots:
        ladder.notes.append(
            "no starter slots configured for this league — cut ladder built "
            "without a lineup-feasibility guard"
        )

    # Cost every player once; the ordering never changes as the ladder grows,
    # because ECC is a property of the player and his position, not of the set.
    costed: list[tuple[float, str, RosterAsset, float, str, float, float]] = []
    for asset in pool:
        ecc, base, basis, waiver, mult = effective_cut_cost(asset, waiver_values, scarcity)
        costed.append((ecc, asset.name.lower(), asset, base, basis, waiver, mult))
    # Deterministic: equal costs (every ``assumedWaiver`` player scores 0) break
    # by name so the ladder is stable across runs.
    costed.sort(key=lambda t: (t[0], t[1]))

    remaining = list(pool)
    baseline_filled = _filled_slot_count(remaining, slots, slot_eligibility) if slots else 0
    ladder.unfilled_slots_at_baseline = max(0, len(slots) - baseline_filled)
    if ladder.unfilled_slots_at_baseline:
        ladder.notes.append(
            f"roster cannot fill {ladder.unfilled_slots_at_baseline} starting "
            "slot(s) before any cut — ladder measured against that baseline"
        )

    taken: set[str] = set()
    blocked: set[str] = set()
    rung = 0
    while rung < max_rungs:
        progressed = False
        for ecc, _tie, asset, base, basis, waiver, mult in costed:
            if asset.player_id in taken or asset.player_id in blocked:
                continue
            if slots:
                survivors = [a for a in remaining if a.player_id != asset.player_id]
                if _filled_slot_count(survivors, slots, slot_eligibility) < baseline_filled:
                    # Releasing him breaks the lineup — never offer this cut.
                    blocked.add(asset.player_id)
                    ladder.undroppable.append(
                        {
                            "playerId": asset.player_id,
                            "name": asset.name,
                            "position": asset.position,
                            "reason": "required_to_fill_starting_lineup",
                        }
                    )
                    continue
                remaining = survivors
            else:
                remaining = [a for a in remaining if a.player_id != asset.player_id]
            rung += 1
            taken.add(asset.player_id)
            ladder.rungs.append(
                CutCandidate(
                    player_id=asset.player_id,
                    name=asset.name,
                    position=asset.position,
                    effective_cut_cost=ecc,
                    base_value=base,
                    value_basis=basis,
                    waiver_value=waiver,
                    scarcity_multiplier=mult,
                    rung=rung,
                )
            )
            progressed = True
            break
        if not progressed:
            break

    if rung >= max_rungs and len(taken) + len(blocked) < len(pool):
        ladder.notes.append(
            f"cut ladder truncated at {max_rungs} rungs — deeper cuts exist but "
            "are far past any budget-feasible plan"
        )
    return ladder
