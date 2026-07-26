"""Target Position and Target Player engines (WS-J).

Answers the two questions that follow from a roster profile:

* **Which positions are worth attacking?** — :func:`rank_target_positions`
* **Which players are worth pursuing?** — :func:`rank_target_players`

Both consume the roster engine (``marginal``, ``profiles``, ``window``)
and the League Intelligence replacement levels as-is. Nothing here
re-derives lineup value, replacement levels, or window state.

Pure computation: no I/O, no clock, no globals.

──────────────────────────────────────────────────────────────────────
Two gates, and why they are gates rather than score terms
──────────────────────────────────────────────────────────────────────
The temptation in both engines is to build one weighted product and
rank on it. That is wrong in a specific, load-bearing way: a weighted
score lets a large factor **compensate** for a fatal one. Two failures
are not "low score", they are disqualifying, so they are branches.

**Gate 1 — obtainability (positions).** A position is not a target
just because it is your worst. If nothing you could plausibly acquire
would improve the lineup, the correct output is "confirmed weakness,
unfixable", not a recommendation. The engine measures this **exactly**:
it re-solves the optimal lineup with each candidate added and reads the
delta off the solver. A position whose realistic gain is immaterial is
reported with :class:`TargetViability` explaining which way it failed,
and is **excluded from the ranked recommendations**.

Ranking the weakest position by default is how a system recommends
chasing a tight end in a league where every startable tight end is
already rostered.

**Gate 2 — corroboration (players).** Internal-vs-market edge is never
sufficient on its own. Edge is a statement about our own numbers, so an
edge-only recommendation is the model agreeing with itself — and if the
valuation is wrong, edge is *most* confident exactly where it is most
wrong. Every recommended player must carry at least
:data:`MIN_CORROBORATING_SIGNALS` signal that is **not** derived from
our own valuation: measured lineup fit, positional scarcity, external
role data, an independent projection, or availability.

Both gates report *why* they failed, so a caller can render the
distinction between "no target here" and "we could not tell".

──────────────────────────────────────────────────────────────────────
Scope: this is a CURRENT-SEASON engine
──────────────────────────────────────────────────────────────────────
Everything downstream of ``marginal.optimal_score`` is denominated in
``ros_value`` — rest-of-season points. So "upgrade impact" means points
added to *this* season's optimal lineup.

That is the right unit for a contender and an incomplete one for a
rebuild, where the value of an acquisition is mostly its price in two
years. The window distribution is applied as a multiplier
(:func:`win_now_weight`) so rebuild-leaning rosters discount win-now
gains, but a multiplier on a current-season number **cannot** represent
future value, and this module does not pretend otherwise. See
:func:`describe_limitations`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from src.league_intel.replacement import (
    PositionReplacement,
    ScarcityComponents,
    normalize_base_position,
)
from src.roster_intel.marginal import optimal_score
from src.roster_intel.profiles import PositionProfile, RosterProfile
from src.roster_intel.window import COMPETITIVE_STATES, CompetitiveWindow
from src.ros.lineup import RosterPlayer

__all__ = [
    "MIN_CORROBORATING_SIGNALS",
    "MIN_MATERIAL_POINTS",
    "MIN_MATERIAL_SHARE",
    "REALISTIC_CANDIDATE_DEPTH",
    "TARGETS_MODEL_VERSION",
    "PlayerTarget",
    "PositionTarget",
    "TargetViability",
    "ValueSignal",
    "describe_limitations",
    "rank_target_players",
    "rank_target_positions",
    "win_now_weight",
]

TARGETS_MODEL_VERSION = "wsj.targets.2026-07-27.v1"


# ── Tunables ─────────────────────────────────────────────────────────

MIN_MATERIAL_POINTS = 3.0
"""Minimum rest-of-season points an upgrade must add to the optimal
lineup before the position counts as a target.

Not zero, and that matters. The solver will happily report a +0.4 gain
from swapping a bench body, and a strictly-positive test would let
every position pass the gate — turning the gate back into the ranking
it was built to replace. Three points is roughly a third of a starter's
weekly output: below it the recommendation cannot survive the noise in
the underlying ROS values.
"""

MIN_MATERIAL_SHARE = 0.01
"""Second materiality test, relative rather than absolute: the gain must
also be at least this share of the roster's own lineup score.

Both tests apply because they fail in opposite directions. A flat
points floor is too strict for a weak roster and too lax for a strong
one; a pure share floor lets a tiny gain pass on a tiny roster.
"""

REALISTIC_CANDIDATE_DEPTH = 3
"""How many of a position's best obtainable candidates define the
"realistic" gain.

The gate reads the MEDIAN gain across this many candidates, not the
maximum. Gating on the best available player means every position
justifies itself with "if I acquire the best guy on the market", which
is best-case reasoning wearing a measurement's clothes. Requiring that
several plausible acquisitions all clear the bar is the difference
between a fixable weakness and a lottery ticket.
"""

MIN_CORROBORATING_SIGNALS = 1
"""Non-edge signals a player must carry to be recommended at all.

One, not two, and the reason is honest: with the sources currently
wired, demanding two corroborators would reject nearly everything and
the engine would recommend nothing. One is the weakest gate that still
forbids the failure mode it exists to prevent — a recommendation
resting purely on our own valuation disagreeing with the market.
"""

_WIN_NOW_WEIGHTS: Mapping[str, float] = {
    "championship_contender": 1.00,
    "playoff_contender": 0.85,
    "retool": 0.45,
    "productive_struggle": 0.30,
    "rebuild": 0.15,
}
"""How much a point added to THIS season's lineup is worth per state.

Rebuild is 0.15 rather than 0.0 because a rebuilding roster still
prefers more points to fewer at equal cost — what changes is the price
it should pay, not the sign of the value. It is emphatically not a
claim that this engine prices a rebuild's real objective; see the
module docstring.
"""

_SCARCITY_SIGNAL_PERCENTILE = 0.60
"""Waiver scarcity above this marks a position where replacement is
genuinely hard, which is what makes an asset there worth corroborating."""

_TINY = 1e-9


# ── Outcomes ─────────────────────────────────────────────────────────


class TargetViability(str, Enum):
    """Why a position is or is not a target. Only ``VIABLE`` is ranked."""

    VIABLE = "viable"
    """An obtainable player would add material lineup value."""

    NO_CANDIDATES = "noCandidates"
    """No acquirable players were supplied for this position. This is
    'we could not tell', NOT 'nothing is available' — the distinction
    matters and is never collapsed."""

    NO_OBTAINABLE_UPGRADE = "noObtainableUpgrade"
    """Candidates exist and none of them improve the optimal lineup.
    A confirmed weakness that nobody can fix. Reported, never ranked."""

    IMMATERIAL_GAIN = "immaterialGain"
    """A real but trivial gain — below the materiality floors."""


class ValueSignal(str, Enum):
    """Independent reasons to want a player.

    ``MARKET_EDGE`` is deliberately NOT in
    :data:`CORROBORATING_SIGNALS`: it is derived from our own valuation,
    so it cannot corroborate itself.
    """

    MARKET_EDGE = "marketEdge"
    ROSTER_FIT = "rosterFit"
    SCARCITY = "scarcity"
    ROLE = "role"
    PROJECTION = "projection"
    AVAILABILITY = "availability"


CORROBORATING_SIGNALS = frozenset(
    {
        ValueSignal.ROSTER_FIT,
        ValueSignal.SCARCITY,
        ValueSignal.ROLE,
        ValueSignal.PROJECTION,
        ValueSignal.AVAILABILITY,
    }
)


@dataclass(frozen=True)
class PositionTarget:
    """One position's assessment. ``viability`` decides if it is ranked."""

    position: str
    viability: TargetViability
    reason: str

    #: Median added lineup points across the best obtainable candidates.
    realistic_gain: float = 0.0
    #: Best single candidate's added points. Context only — never gated on.
    best_case_gain: float = 0.0
    candidates_tested: int = 0

    #: Current cost of the weakness, in lineup points.
    severity: float = 0.0
    urgent_need: bool = False
    need_reasons: tuple[str, ...] = ()

    win_now_weight: float = 1.0
    scarcity_multiplier: float = 1.0
    market_efficiency: float | None = None
    confidence: float = 0.0

    #: The ranking quantity. Zero for anything not VIABLE.
    priority: float = 0.0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "position": self.position,
            "viability": self.viability.value,
            "reason": self.reason,
            "realisticGain": round(self.realistic_gain, 3),
            "bestCaseGain": round(self.best_case_gain, 3),
            "candidatesTested": self.candidates_tested,
            "severity": round(self.severity, 3),
            "urgentNeed": self.urgent_need,
            "needReasons": list(self.need_reasons),
            "winNowWeight": round(self.win_now_weight, 4),
            "scarcityMultiplier": round(self.scarcity_multiplier, 4),
            "marketEfficiency": (
                round(self.market_efficiency, 4) if self.market_efficiency is not None else None
            ),
            "confidence": round(self.confidence, 4),
            "priority": round(self.priority, 3),
            "notes": list(self.notes),
            "modelVersion": TARGETS_MODEL_VERSION,
        }


@dataclass(frozen=True)
class PlayerTarget:
    """One candidate player's assessment."""

    player_id: str
    name: str
    position: str
    recommended: bool
    reason: str

    signals: tuple[ValueSignal, ...] = ()
    corroborating: tuple[ValueSignal, ...] = ()

    lineup_gain: float = 0.0
    market_edge: float | None = None
    availability: float | None = None
    confidence: float = 0.0
    priority: float = 0.0
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "playerId": self.player_id,
            "name": self.name,
            "position": self.position,
            "recommended": self.recommended,
            "reason": self.reason,
            "signals": [s.value for s in self.signals],
            "corroborating": [s.value for s in self.corroborating],
            "lineupGain": round(self.lineup_gain, 3),
            "marketEdge": (round(self.market_edge, 4) if self.market_edge is not None else None),
            "availability": (
                round(self.availability, 4) if self.availability is not None else None
            ),
            "confidence": round(self.confidence, 4),
            "priority": round(self.priority, 3),
            "notes": list(self.notes),
            "modelVersion": TARGETS_MODEL_VERSION,
        }


# ── helpers ──────────────────────────────────────────────────────────


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return 0.5 * (ordered[mid - 1] + ordered[mid])


def win_now_weight(window: CompetitiveWindow | None) -> float:
    """Expected value of a point added to this season's lineup.

    Consumes the full five-state distribution rather than
    ``most_likely``. A roster split 45/40 between retool and rebuild is
    a different decision from one sitting at 85% retool, and collapsing
    to the argmax throws away exactly that difference — which is the
    reason the roster engine reports probabilities in the first place.
    """
    if window is None:
        return 1.0
    total = 0.0
    mass = 0.0
    for state in COMPETITIVE_STATES:
        p = float(window.probabilities.get(state, 0.0))
        if p <= 0:
            continue
        total += p * _WIN_NOW_WEIGHTS.get(state, 0.5)
        mass += p
    if mass <= _TINY:
        return 1.0
    return total / mass


def _scarcity_multiplier(sc: ScarcityComponents | None) -> tuple[float, str | None]:
    """How durable an upgrade at this position is.

    Uses ``waiver_scarcity`` specifically, and only that. The
    replacement module keeps its six signals separate on purpose —
    "top-heavy" and "nothing on waivers" call for opposite moves — so
    collapsing them here would undo that design. Waiver scarcity is the
    one that answers the question this engine is asking: if I do not
    trade for this, can I just pick one up?
    """
    if sc is None or sc.waiver_scarcity is None:
        return 1.0, "no scarcity data — position scarcity multiplier inert"
    # 0.85x when trivially replaceable, 1.15x when nothing is available.
    return 0.85 + 0.30 * _clamp(float(sc.waiver_scarcity), 0.0, 1.0), None


def _position_severity(profile: PositionProfile | None) -> float:
    """Current cost of the weakness, in lineup points.

    Fragility × the group's contribution: a position that collapses when
    one player is absent is expensive whether or not it looks thin by
    headcount. Unfilled slots are already reflected in the marginal
    solve, so they are not added again here.
    """
    if profile is None:
        return 0.0
    return max(0.0, float(profile.fragility)) * max(0.0, float(profile.marginal_points))


# ── Target Position engine ───────────────────────────────────────────


def rank_target_positions(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    *,
    profile: RosterProfile | None = None,
    candidates: Mapping[str, Sequence[RosterPlayer]] | None = None,
    window: CompetitiveWindow | None = None,
    scarcity: Mapping[str, ScarcityComponents] | None = None,
    replacement: Mapping[str, PositionReplacement] | None = None,
    market_prices: Mapping[str, float] | None = None,
    candidate_depth: int = REALISTIC_CANDIDATE_DEPTH,
) -> list[PositionTarget]:
    """Rank positions worth attacking. Non-viable positions are returned
    too, unranked, so a caller can show a confirmed-but-unfixable
    weakness instead of silently omitting it.

    Args:
        pool: our roster, eligibility-enriched.
        slots: the league's flattened starter slots.
        profile: roster engine output. Supplies severity and need
            context; absent ⇒ severity reads zero and confidence drops.
        candidates: ``{position: [acquirable players]}``. **This is what
            makes the obtainability gate real.** Absent for a position ⇒
            :attr:`TargetViability.NO_CANDIDATES` — "we could not tell",
            never "nothing available".
        window: five-state competitive window; scales win-now value.
        scarcity: per-position scarcity components.
        replacement: league replacement levels, for market efficiency.
        market_prices: ``{position: typical acquisition cost}`` in the
            same units as player value. Absent ⇒ efficiency unreported.
        candidate_depth: how many top candidates define the realistic
            gain.

    Returns:
        Viable targets first, ranked by ``priority`` descending, then
        non-viable positions ordered by severity so the biggest
        unfixable weakness is still visible.
    """
    pool_list = list(pool)
    slots_list = list(slots)
    base_score = optimal_score(pool_list, slots_list)
    cands = candidates or {}
    ww = win_now_weight(window)

    positions = set(cands)
    if profile is not None:
        positions |= set(profile.positions)
    positions = {normalize_base_position(p) for p in positions if p}

    out: list[PositionTarget] = []
    for pos in sorted(positions):
        pprof = profile.positions.get(pos) if profile else None
        severity = _position_severity(pprof)
        scar_mult, scar_note = _scarcity_multiplier((scarcity or {}).get(pos))
        notes: list[str] = []
        if scar_note:
            notes.append(scar_note)

        pos_candidates = [c for c in (cands.get(pos) or []) if c is not None]

        # ── the obtainability gate ───────────────────────────────────
        if not pos_candidates:
            out.append(
                PositionTarget(
                    position=pos,
                    viability=TargetViability.NO_CANDIDATES,
                    reason=(
                        "no acquirable candidates supplied for this position, so "
                        "obtainable upgrade value is unknown — this is 'not "
                        "measured', not 'nothing available'"
                    ),
                    severity=severity,
                    urgent_need=bool(pprof.urgent_need) if pprof else False,
                    need_reasons=tuple(pprof.need_reasons) if pprof else (),
                    win_now_weight=ww,
                    scarcity_multiplier=scar_mult,
                    notes=tuple(notes),
                )
            )
            continue

        # Exact re-solve per candidate: what does adding them do to the
        # optimal lineup? This is measured, not inferred from value.
        gains = [
            (optimal_score([*pool_list, cand], slots_list) - base_score, cand)
            for cand in pos_candidates
        ]
        gains.sort(key=lambda g: (-g[0], g[1].player_id))
        best_case = gains[0][0] if gains else 0.0
        top = [g for g, _ in gains[: max(1, int(candidate_depth))]]
        realistic = _median(top)

        material_floor = max(MIN_MATERIAL_POINTS, MIN_MATERIAL_SHARE * base_score)
        if best_case <= _TINY:
            out.append(
                PositionTarget(
                    position=pos,
                    viability=TargetViability.NO_OBTAINABLE_UPGRADE,
                    reason=(
                        f"tested {len(gains)} obtainable candidates; none improves "
                        "the optimal lineup. A confirmed weakness that cannot "
                        "currently be fixed is not a target"
                    ),
                    realistic_gain=realistic,
                    best_case_gain=best_case,
                    candidates_tested=len(gains),
                    severity=severity,
                    urgent_need=bool(pprof.urgent_need) if pprof else False,
                    need_reasons=tuple(pprof.need_reasons) if pprof else (),
                    win_now_weight=ww,
                    scarcity_multiplier=scar_mult,
                    notes=tuple(notes),
                )
            )
            continue

        if realistic < material_floor:
            out.append(
                PositionTarget(
                    position=pos,
                    viability=TargetViability.IMMATERIAL_GAIN,
                    reason=(
                        f"realistic gain {realistic:.2f} pts is below the "
                        f"materiality floor {material_floor:.2f} "
                        f"(max({MIN_MATERIAL_POINTS}, "
                        f"{MIN_MATERIAL_SHARE:.0%} of lineup score)); best single "
                        f"candidate would add {best_case:.2f}"
                    ),
                    realistic_gain=realistic,
                    best_case_gain=best_case,
                    candidates_tested=len(gains),
                    severity=severity,
                    urgent_need=bool(pprof.urgent_need) if pprof else False,
                    need_reasons=tuple(pprof.need_reasons) if pprof else (),
                    win_now_weight=ww,
                    scarcity_multiplier=scar_mult,
                    notes=tuple(notes),
                )
            )
            continue

        # ── market efficiency (reported, bounded, never a gate) ──────
        efficiency: float | None = None
        eff_mult = 1.0
        price = (market_prices or {}).get(pos)
        rep = (replacement or {}).get(pos)
        if price is not None and price > 0:
            starter = rep.value("starter") if rep else None
            if starter:
                efficiency = float(starter) / float(price)
                eff_mult = _clamp(0.80 + 0.40 * _clamp(efficiency, 0.0, 2.0) / 2.0, 0.80, 1.20)
            else:
                notes.append(
                    "market price supplied but no starter replacement level — "
                    "market efficiency not computable"
                )
        else:
            notes.append("no market price for this position — efficiency unreported")

        # ── confidence ───────────────────────────────────────────────
        # Tracks how much of the input set was actually supplied. Same
        # rule as the partner model: a defaulted input is an abstention
        # and must cost confidence rather than pass silently.
        supplied = sum(
            1
            for present in (
                profile is not None,
                window is not None,
                (scarcity or {}).get(pos) is not None,
                efficiency is not None,
            )
            if present
        )
        confidence = _clamp(0.40 + 0.15 * supplied, 0.0, 1.0)
        if len(gains) < candidate_depth:
            confidence *= 0.85
            notes.append(
                f"only {len(gains)} candidates tested (< {candidate_depth}); the "
                "realistic gain rests on a thin sample"
            )

        priority = realistic * ww * scar_mult * eff_mult * confidence

        out.append(
            PositionTarget(
                position=pos,
                viability=TargetViability.VIABLE,
                reason=(
                    f"{len(gains)} candidates tested; a realistic acquisition adds "
                    f"{realistic:.2f} pts to the optimal lineup"
                ),
                realistic_gain=realistic,
                best_case_gain=best_case,
                candidates_tested=len(gains),
                severity=severity,
                urgent_need=bool(pprof.urgent_need) if pprof else False,
                need_reasons=tuple(pprof.need_reasons) if pprof else (),
                win_now_weight=ww,
                scarcity_multiplier=scar_mult,
                market_efficiency=efficiency,
                confidence=confidence,
                priority=priority,
                notes=tuple(notes),
            )
        )

    viable = [t for t in out if t.viability is TargetViability.VIABLE]
    rest = [t for t in out if t.viability is not TargetViability.VIABLE]
    viable.sort(key=lambda t: (-t.priority, t.position))
    rest.sort(key=lambda t: (-t.severity, t.position))
    return viable + rest


# ── Target Player engine ─────────────────────────────────────────────


def rank_target_players(
    pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    candidates: Sequence[RosterPlayer],
    *,
    market_values: Mapping[str, float] | None = None,
    scarcity: Mapping[str, ScarcityComponents] | None = None,
    role_scores: Mapping[str, float] | None = None,
    projection_scores: Mapping[str, float] | None = None,
    availability: Mapping[str, float] | None = None,
    min_corroborating: int = MIN_CORROBORATING_SIGNALS,
) -> list[PlayerTarget]:
    """Rank individual players worth pursuing.

    **A player is never recommended on internal-vs-market edge alone.**
    Edge is computed from our own valuation, so an edge-only case is the
    model agreeing with itself; where the valuation is wrong, edge is
    most confident exactly where it is most wrong. Each candidate must
    carry at least ``min_corroborating`` signal from
    :data:`CORROBORATING_SIGNALS`, all of which come from somewhere
    other than our price.

    Args:
        pool: our roster.
        slots: the league's starter slots.
        candidates: players who might be acquired.
        market_values: ``{player_id: market price}``. Drives the edge
            signal only — never sufficient by itself.
        scarcity: per-position scarcity components.
        role_scores: ``{player_id: 0-1}`` external usage/role evidence
            (snap share, target share, depth chart) — independent of our
            valuation, which is what makes it corroborating.
        projection_scores: ``{player_id: 0-1}`` independent projection
            percentile.
        availability: ``{player_id: 0-1}`` how obtainable they are —
            e.g. from ``partner.assess_partner``, or their owner's
            surplus at that position.
        min_corroborating: the gate. Lowering it to 0 disables the
            corroboration requirement and is not supported.

    Returns:
        Recommended players first by ``priority`` descending, then
        rejected candidates with the reason they failed the gate.
    """
    pool_list = list(pool)
    slots_list = list(slots)
    base_score = optimal_score(pool_list, slots_list)
    material_floor = max(MIN_MATERIAL_POINTS, MIN_MATERIAL_SHARE * base_score)

    out: list[PlayerTarget] = []
    for cand in candidates:
        if cand is None:
            continue
        pos = normalize_base_position(cand.position)
        notes: list[str] = []
        signals: list[ValueSignal] = []

        # ── measured lineup fit (exact re-solve) ─────────────────────
        gain = optimal_score([*pool_list, cand], slots_list) - base_score
        if gain >= material_floor:
            signals.append(ValueSignal.ROSTER_FIT)

        # ── market edge — necessary for value, never sufficient ──────
        edge: float | None = None
        price = (market_values or {}).get(cand.player_id)
        if price is not None and price > 0:
            edge = (float(cand.ros_value) - float(price)) / float(price)
            if edge > 0:
                signals.append(ValueSignal.MARKET_EDGE)
        else:
            notes.append("no market value supplied — edge unmeasured")

        # ── corroborators ────────────────────────────────────────────
        sc = (scarcity or {}).get(pos)
        if sc is not None and sc.waiver_scarcity is not None:
            if float(sc.waiver_scarcity) >= _SCARCITY_SIGNAL_PERCENTILE:
                signals.append(ValueSignal.SCARCITY)

        role = (role_scores or {}).get(cand.player_id)
        if role is not None and float(role) >= 0.6:
            signals.append(ValueSignal.ROLE)

        proj = (projection_scores or {}).get(cand.player_id)
        if proj is not None and float(proj) >= 0.6:
            signals.append(ValueSignal.PROJECTION)

        avail = (availability or {}).get(cand.player_id)
        if avail is not None and float(avail) >= 0.5:
            signals.append(ValueSignal.AVAILABILITY)

        corroborating = tuple(s for s in signals if s in CORROBORATING_SIGNALS)

        # ── the corroboration gate ───────────────────────────────────
        if len(corroborating) < min_corroborating:
            if ValueSignal.MARKET_EDGE in signals:
                reason = (
                    f"market edge {edge:+.1%} is the only signal; a recommendation "
                    "resting solely on our own valuation disagreeing with the "
                    "market is the model agreeing with itself. Needs at least "
                    f"{min_corroborating} independent signal (roster fit, "
                    "scarcity, role, projection or availability)"
                )
            else:
                reason = (
                    "no admissible value signal: the player neither improves the "
                    "optimal lineup nor carries scarcity, role, projection or "
                    "availability evidence"
                )
            out.append(
                PlayerTarget(
                    player_id=cand.player_id,
                    name=cand.canonical_name,
                    position=pos,
                    recommended=False,
                    reason=reason,
                    signals=tuple(signals),
                    corroborating=corroborating,
                    lineup_gain=gain,
                    market_edge=edge,
                    availability=avail,
                    notes=tuple(notes),
                )
            )
            continue

        # ── priority for gated-in players ────────────────────────────
        # Anchored on measured lineup gain, because that is the only
        # component denominated in points. Edge and availability adjust
        # it within bounds; neither can manufacture a target on its own,
        # which the gate above has already guaranteed.
        scar_mult, _ = _scarcity_multiplier(sc)
        edge_mult = 1.0 + _clamp(edge or 0.0, -0.5, 0.5) * 0.4
        avail_mult = 0.7 + 0.6 * _clamp(avail if avail is not None else 0.5, 0.0, 1.0)
        confidence = _clamp(0.35 + 0.15 * len(corroborating), 0.0, 1.0)

        # A corroborated player with no measured lineup gain is still a
        # legitimate target (scarcity/role cases), so the anchor floors
        # at a fraction of the materiality bar rather than zero.
        anchor = max(gain, 0.25 * material_floor)
        priority = anchor * scar_mult * edge_mult * avail_mult * confidence

        out.append(
            PlayerTarget(
                player_id=cand.player_id,
                name=cand.canonical_name,
                position=pos,
                recommended=True,
                reason=(
                    "corroborated by "
                    + ", ".join(s.value for s in corroborating)
                    + (f"; adds {gain:.2f} pts to the optimal lineup" if gain > 0 else "")
                ),
                signals=tuple(signals),
                corroborating=corroborating,
                lineup_gain=gain,
                market_edge=edge,
                availability=avail,
                confidence=confidence,
                priority=priority,
                notes=tuple(notes),
            )
        )

    rec = [t for t in out if t.recommended]
    rej = [t for t in out if not t.recommended]
    rec.sort(key=lambda t: (-t.priority, t.player_id))
    rej.sort(key=lambda t: (-t.lineup_gain, t.player_id))
    return rec + rej


def describe_limitations() -> dict[str, Any]:
    """Machine-readable limitations of both target engines.

    Asserted by tests so it cannot drift from behaviour.
    """
    return {
        "modelVersion": TARGETS_MODEL_VERSION,
        "canSupport": [
            "Ranking positions by measured, obtainable upgrade value — the "
            "gain is read off an exact lineup re-solve, not inferred from "
            "player value.",
            "Distinguishing a fixable weakness from a confirmed weakness "
            "nobody can fix, and from one we simply have no market data for.",
            "Rejecting players whose only case is that our valuation " "disagrees with the market.",
            "Explaining, per position and per player, which signal drove the " "recommendation.",
        ],
        "cannotSupport": [
            "Multi-year or rebuild value. Everything is denominated in "
            "rest-of-season points, so a rebuild's real objective — what an "
            "asset is worth in two years — is not represented. The win-now "
            "weight discounts current-season gains; it does not price the "
            "future.",
            "Any claim about what a trade will COST. The engines rank what is "
            "worth wanting, not what it takes to get it.",
            "Availability in any measured sense unless the caller supplies "
            "it; absent that, the availability signal simply does not fire.",
            "Positions with no supplied candidates — reported as "
            "'not measured', never as 'nothing available'.",
            "Cross-market (offense + IDP) comparison, which inherits audit "
            "F-1's missing normalization.",
        ],
        "keyAssumptions": {
            "materialityFloorPoints": MIN_MATERIAL_POINTS,
            "materialityFloorShare": MIN_MATERIAL_SHARE,
            "materialityFloorIsMeasured": False,
            "materialityFloorNote": (
                "Assumed, not fitted. Chosen so a bench-body swap cannot clear "
                "the gate; no calibration data exists to tune it against."
            ),
            "realisticCandidateDepth": REALISTIC_CANDIDATE_DEPTH,
            "realisticGainIsMedianNotMax": True,
            "minCorroboratingSignals": MIN_CORROBORATING_SIGNALS,
            "winNowWeights": dict(_WIN_NOW_WEIGHTS),
            "winNowWeightsAreMeasured": False,
        },
        "whatWouldUnlockMore": [
            "A dynasty/multi-year value scale alongside ros_value, which "
            "would let the engine price rebuild targets rather than "
            "discounting win-now ones.",
            "Measured acquisition costs, turning 'worth wanting' into " "'worth paying for'.",
            "External role data (snap share, target share, depth chart) — the "
            "corroborating signal most often missing today.",
        ],
    }
