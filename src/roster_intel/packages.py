"""Trade Package Generator (WS-J).

Builds concrete, legal, defensible trade packages between our roster and
one opposing roster, and returns a **Pareto frontier** across competing
objectives rather than a single ranked list.

Consumes, never rebuilds:

* ``league_intel.cross_market.value_package`` / ``compare_packages`` —
  package valuation and the boundary-proximity suppression rule. Every
  package is valued **entirely within one market** (offense-only →
  ``ktcSfTep``; anything with IDP → ``idpTradeCalc``), which is exact
  and needs no conversion.
* ``roster_intel.marginal.optimal_score`` — exact lineup re-solve for
  what a package actually does to a starting lineup.
* ``roster_intel.partner.assess_partner`` — how a counterparty is
  likely to receive the offer.

Pure computation: no I/O, no clock, no globals.

──────────────────────────────────────────────────────────────────────
A frontier, not a score
──────────────────────────────────────────────────────────────────────
Packages are judged on four axes that share no unit:

* ``value_efficiency`` — market value retained, from WS-E
* ``roster_improvement`` — lineup points gained, from an exact re-solve
* ``acceptance_plausibility`` — from the partner model
* ``simplicity`` — fewer moving parts

Blending them into one number requires an exchange rate between market
points, lineup points and plausibility. **No such rate exists**, and
inventing one silently encodes a preference as if it were a
measurement. So this module returns the non-dominated set: every
package on the frontier is the best available at *something*, and the
choice between them is the manager's to make. :func:`label_frontier`
names which axis each member wins on, so a caller can present them as
alternatives rather than as a ranking.

──────────────────────────────────────────────────────────────────────
Staged generation, not brute force
──────────────────────────────────────────────────────────────────────
The full combination space over two 30-man rosters is astronomically
larger than the useful part of it. Generation runs in stages, and each
stage only expands what the previous stage proved was **worth**
expanding:

1. 1-for-1 from a pre-filtered seed set.
2. 2-for-1 / 1-for-2, expanding ONLY near-misses — packages that failed
   on value gap but are close enough that one more asset could close
   it. A package that already succeeded is never expanded, because the
   simpler version dominates it by construction.
3. 2-for-2, from stage-2 near-misses only.

Within each stage, cheap filters run before expensive ones: legality,
then market valuation, then the rejection rules, and only then the
exact lineup re-solve. The solve is the expensive step and it never
runs on a package that was already going to be rejected.

──────────────────────────────────────────────────────────────────────
On ``acceptance_plausibility``
──────────────────────────────────────────────────────────────────────
It is inherited from :mod:`roster_intel.partner`, and it carries that
model's limitations unchanged: **we never observe a rejection**, so
this is a plausibility score wearing probability units, not a
calibrated acceptance probability. No output of this module may be
rendered as "manager X will accept this". See
:func:`describe_limitations`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, Sequence

from src.league_intel.cross_market import (
    DEFAULT_GATE_PCT,
    PackageComparison,
    compare_packages,
    value_package,
)
from src.roster_intel.marginal import optimal_score
from src.roster_intel.partner import (
    PartnerInputs,
    RosterSignal,
    TradeShape,
    assess_partner,
)
from src.ros.lineup import RosterPlayer

__all__ = [
    "CORNERSTONE_PREMIUM_PCT",
    "MAX_PACKAGE_ASSETS",
    "NEAR_MISS_PCT",
    "PACKAGES_MODEL_VERSION",
    "PackageCandidate",
    "RejectionReason",
    "TradeAsset",
    "describe_limitations",
    "generate_packages",
    "label_frontier",
    "pareto_frontier",
]

PACKAGES_MODEL_VERSION = "wsj.packages.2026-07-27.v1"


# ── Tunables ─────────────────────────────────────────────────────────

MAX_PACKAGE_ASSETS = 2
"""Most assets from either side in a generated package.

Two, not three, and for a reason beyond combinatorics: each additional
asset multiplies the search AND weakens the result, because a package
that needs three pieces to balance is usually a package whose core
premise does not balance. Three-for-threes are real in dynasty, but
they are negotiated, not generated — a generator proposing them is
almost always laundering a bad core swap behind filler.
"""

NEAR_MISS_PCT = 25.0
"""How far off the value gate a package may be and still be worth
expanding with another asset.

A package 200% off is not fixable by adding a bench piece; expanding it
burns search budget on combinations that cannot converge. A package 8%
off might well be. This constant is what makes the staging real rather
than decorative — without it stage 2 would expand everything and the
'staged' generator would be brute force with extra steps.
"""

CORNERSTONE_PREMIUM_PCT = 15.0
"""Market premium required before asking for a cornerstone is a
serious offer rather than a lowball.

Cornerstones do not move at market price. A manager surrenders one for
a clear overpay or not at all, so a package that asks for one at parity
is not a package — it is noise that costs credibility to send.
"""

CORNERSTONE_TOP_N = 3
"""Most assets on a roster that can be cornerstones. A ceiling, not a
definition — see :data:`CORNERSTONE_VALUE_SHARE`."""

CORNERSTONE_VALUE_SHARE = 0.60
"""Share of the roster's most valuable asset an asset must reach before
it counts as a cornerstone.

Rank alone is not enough, and this is not hypothetical: with a
candidate pool of three, a pure top-3 rule makes EVERY asset a
cornerstone — including a 2,200-value bench receiver sitting beside a
9,500 stud — and the premium rule then rejects almost every package
that could be built. "Cornerstone" has to mean genuinely elite relative
to the roster, not merely present in a short list.
"""

_MIN_ROSTER_SIZE = 1
_TINY = 1e-9


class RejectionReason(str, Enum):
    """Why a package was refused. Every rejection is explainable."""

    NONE = "none"

    ILLEGAL_ROSTER = "illegalRoster"
    """The trade leaves a roster outside its legal size, or moves an
    asset a side does not own."""

    WORSENS_CRITICAL_NEED = "worsensCriticalNeed"
    """Takes from a position the partner is already critically short at,
    without sending compensation there."""

    CORNERSTONE_WITHOUT_PREMIUM = "cornerstoneWithoutPremium"
    """Asks for a cornerstone at or near market price."""

    UNVALUABLE = "unvaluable"
    """WS-E could not value the package on a single market."""

    VERDICT_UNCERTAIN = "verdictUncertain"
    """The propagated uncertainty band straddles the decision gate, so
    the comparison is withheld. Boundary-proximity, not presence."""

    DOMINATED = "dominated"
    """A simpler package is at least as good on every axis."""

    DOMINATED_BY_NO_TRADE = "dominatedByNoTrade"
    """Strictly worse than the status quo on both self-interested axes.

    The simplest package of all is no package, and it is always
    available. A trade that loses market value AND loses lineup points
    is dominated by declining to trade, so high acceptance plausibility
    cannot rescue it — plausibility measures how the PARTNER receives
    the offer, and being easy to give away is not a reason to give
    something away."""


@dataclass(frozen=True)
class TradeAsset:
    """One tradeable asset, carrying both representations it needs.

    ``row`` is the contract-shaped row WS-E's ``value_package`` consumes
    (``canonicalSiteValues``, ``position``, ``displayName``).
    ``player`` is the optimizer's view. Both are required: market value
    and lineup value are different questions and neither substitutes for
    the other.
    """

    asset_id: str
    name: str
    position: str
    row: Mapping[str, Any]
    player: RosterPlayer | None = None

    @classmethod
    def from_player(cls, player: RosterPlayer, site_values: Mapping[str, float]) -> TradeAsset:
        return cls(
            asset_id=player.player_id,
            name=player.canonical_name,
            position=player.position,
            row={
                "displayName": player.canonical_name,
                "position": player.position,
                "canonicalSiteValues": dict(site_values),
            },
            player=player,
        )


@dataclass(frozen=True)
class PackageCandidate:
    """One proposed trade, with every axis it is judged on."""

    send: tuple[TradeAsset, ...]
    receive: tuple[TradeAsset, ...]
    stage: int

    accepted: bool = False
    rejection: RejectionReason = RejectionReason.NONE
    rejection_detail: str = ""

    # ── the four frontier axes ──
    value_efficiency: float = 0.0
    roster_improvement: float = 0.0
    acceptance_plausibility: float = 0.0
    simplicity: float = 0.0

    comparison: PackageComparison | None = None
    acceptance_confidence: float = 0.0
    notes: tuple[str, ...] = ()

    @property
    def asset_count(self) -> int:
        return len(self.send) + len(self.receive)

    @property
    def axes(self) -> tuple[float, float, float, float]:
        return (
            self.value_efficiency,
            self.roster_improvement,
            self.acceptance_plausibility,
            self.simplicity,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "send": [{"id": a.asset_id, "name": a.name, "position": a.position} for a in self.send],
            "receive": [
                {"id": a.asset_id, "name": a.name, "position": a.position} for a in self.receive
            ],
            "stage": self.stage,
            "accepted": self.accepted,
            "rejection": self.rejection.value,
            "rejectionDetail": self.rejection_detail,
            "valueEfficiency": round(self.value_efficiency, 4),
            "rosterImprovement": round(self.roster_improvement, 3),
            "acceptancePlausibility": round(self.acceptance_plausibility, 4),
            "acceptanceConfidence": round(self.acceptance_confidence, 4),
            "simplicity": round(self.simplicity, 4),
            "assetCount": self.asset_count,
            "marketGainPct": (
                self.comparison.market_gain_pct if self.comparison is not None else None
            ),
            "verdictCertain": (
                self.comparison.verdict_certain if self.comparison is not None else None
            ),
            "notes": list(self.notes),
            "modelVersion": PACKAGES_MODEL_VERSION,
            "acceptanceCaveat": (
                "acceptancePlausibility is a plausibility score in probability "
                "units, not a calibrated acceptance probability. Rejections are "
                "never observed. Never render as 'they will accept'."
            ),
        }


# ── Pareto machinery ─────────────────────────────────────────────────


def _dominates(a: PackageCandidate, b: PackageCandidate) -> bool:
    """True when ``a`` is at least as good on every axis and strictly
    better on one. Ties on every axis are NOT domination — otherwise
    ordering would decide which of two equivalent packages survives."""
    aa, bb = a.axes, b.axes
    return all(x >= y - _TINY for x, y in zip(aa, bb)) and any(
        x > y + _TINY for x, y in zip(aa, bb)
    )


def pareto_frontier(candidates: Sequence[PackageCandidate]) -> list[PackageCandidate]:
    """Non-dominated packages, i.e. the set of real alternatives.

    A package survives when nothing else is at least as good on market
    efficiency, roster improvement, acceptance plausibility AND
    simplicity simultaneously. Every survivor is the best available at
    something; choosing between them is a preference, not a
    computation, which is exactly why this returns a set.
    """
    live = [c for c in candidates if c.accepted]
    out: list[PackageCandidate] = []
    for cand in live:
        if not any(_dominates(other, cand) for other in live if other is not cand):
            out.append(cand)
    out.sort(key=lambda c: (-c.value_efficiency, c.asset_count, _package_key(c)))
    return out


_AXIS_LABELS = (
    ("valueEfficiency", "best market value"),
    ("rosterImprovement", "biggest lineup upgrade"),
    ("acceptancePlausibility", "most plausible to land"),
    ("simplicity", "simplest structure"),
)


def label_frontier(frontier: Sequence[PackageCandidate]) -> dict[str, Any]:
    """Name which axis each frontier member wins, so a caller can show
    alternatives instead of implying a ranking."""
    if not frontier:
        return {"members": [], "bestBy": {}}
    best_by: dict[str, str] = {}
    for idx, (axis, _label) in enumerate(_AXIS_LABELS):
        winner = max(frontier, key=lambda c, i=idx: (c.axes[i], -c.asset_count))
        best_by[axis] = _package_key(winner)
    return {
        "members": [c.to_dict() for c in frontier],
        "bestBy": best_by,
        "axisLabels": {axis: label for axis, label in _AXIS_LABELS},
        "note": (
            "These are alternatives on a Pareto frontier, not a ranking. No "
            "exchange rate exists between market points, lineup points and "
            "acceptance plausibility, so choosing among them is a preference."
        ),
    }


def _package_key(c: PackageCandidate) -> str:
    """Package identity — DELEGATED, not defined here (V1-36 / C3-PKG-01).

    This module and ``src/trade/finder.py`` both had one of these, and they
    disagreed: this one keys on ``asset_id`` (correct), the finder's keyed on
    display names and so collapsed two assets that share a board row.  Having
    the right answer twice is still two answers, so the identity now has one
    owner in ``src/packages`` and this is its string form for
    the dict keys and stable sorts already built on it.
    """
    from src.packages import package_key  # noqa: PLC0415

    send, receive = package_key(
        [_substrate_view(a) for a in c.send],
        [_substrate_view(a) for a in c.receive],
    )
    return "+".join(send) + "->" + "+".join(receive)


def _substrate_view(asset: TradeAsset):
    """Project a ``TradeAsset`` onto the substrate's asset view."""
    from src.packages import PackageAsset  # noqa: PLC0415

    return PackageAsset(
        asset_id=asset.asset_id,
        name=getattr(asset, "name", "") or asset.asset_id,
        position=getattr(asset, "position", "") or "",
        value=getattr(asset, "market_value", None),
        source=asset,
    )


# ── Rejection rules ──────────────────────────────────────────────────


def _check_legality(
    send: Sequence[TradeAsset],
    receive: Sequence[TradeAsset],
    our_size: int,
    their_size: int,
    roster_limit: int | None,
) -> tuple[bool, str]:
    """Roster legality. Cheapest check, so it runs first."""
    if not send or not receive:
        return False, "a package must have assets on both sides"
    send_ids = {a.asset_id for a in send}
    recv_ids = {a.asset_id for a in receive}
    if send_ids & recv_ids:
        return False, "the same asset appears on both sides"
    if len(send_ids) != len(send) or len(recv_ids) != len(receive):
        return False, "an asset appears twice on one side"

    our_after = our_size - len(send) + len(receive)
    their_after = their_size - len(receive) + len(send)
    if our_after < _MIN_ROSTER_SIZE or their_after < _MIN_ROSTER_SIZE:
        return False, "trade would empty a roster"
    if roster_limit is not None:
        if our_after > roster_limit:
            return False, f"our roster would hold {our_after} > {roster_limit}"
        if their_after > roster_limit:
            return False, f"their roster would hold {their_after} > {roster_limit}"
    return True, ""


def _check_critical_need(
    send: Sequence[TradeAsset],
    receive: Sequence[TradeAsset],
    their_signal: RosterSignal | None,
) -> tuple[bool, str]:
    """Never strip a position the partner is already critical at.

    Taking a running back from a team whose only real hole is running
    back is not a trade offer, it is an insult with a spreadsheet
    attached. It is allowed only when the same position is replenished
    from our side.

    "Critical" is the partner's LARGEST deficit — deficits are relative
    magnitudes, so a fixed threshold on the engine's units would not
    transfer between rosters.
    """
    if their_signal is None or not their_signal.deficit:
        return True, ""
    peak = max(their_signal.deficit.values())
    if peak <= 0:
        return True, ""
    critical = {pos for pos, mag in their_signal.deficit.items() if mag >= 0.75 * peak}
    taken = {a.position.upper() for a in receive}
    given = {a.position.upper() for a in send}
    stripped = (taken & critical) - given
    if stripped:
        pos = sorted(stripped)[0]
        return False, (
            f"takes {pos} from a partner whose {pos} room is already one of their "
            "most critical needs, with no {pos} sent back as compensation".replace("{pos}", pos)
        )
    return True, ""


def _check_cornerstone(
    receive: Sequence[TradeAsset],
    cornerstones: frozenset[str],
    comparison: PackageComparison | None,
) -> tuple[bool, str]:
    """Asking for a cornerstone requires a real premium.

    ``market_gain_pct`` is OUR gain, so a genuine overpay to them is a
    NEGATIVE gain of at least the premium.
    """
    asked = {a.asset_id for a in receive} & cornerstones
    if not asked:
        return True, ""
    if comparison is None or comparison.market_gain_pct is None:
        return False, "asks for a cornerstone but the package could not be priced"
    if comparison.market_gain_pct > -CORNERSTONE_PREMIUM_PCT:
        return False, (
            f"asks for a cornerstone while our side gains "
            f"{comparison.market_gain_pct:+.1f}%; a cornerstone moves only for a "
            f"clear overpay (at least {CORNERSTONE_PREMIUM_PCT:.0f}% in their favour)"
        )
    return True, ""


# ── Generation ───────────────────────────────────────────────────────


def _evaluate(
    send: tuple[TradeAsset, ...],
    receive: tuple[TradeAsset, ...],
    stage: int,
    *,
    our_pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    base_lineup: float,
    our_size: int,
    their_size: int,
    roster_limit: int | None,
    their_signal: RosterSignal | None,
    our_signal: RosterSignal | None,
    cornerstones: frozenset[str],
    gate_pct: float,
    partner_owner_id: str,
    allow_scalar_fallback: bool,
) -> PackageCandidate:
    """Run one candidate through the pipeline, cheapest check first."""
    notes: list[str] = []

    def _reject(reason: RejectionReason, detail: str) -> PackageCandidate:
        return PackageCandidate(
            send=send,
            receive=receive,
            stage=stage,
            accepted=False,
            rejection=reason,
            rejection_detail=detail,
            notes=tuple(notes),
        )

    # 1 ── legality (cheapest)
    ok, detail = _check_legality(send, receive, our_size, their_size, roster_limit)
    if not ok:
        return _reject(RejectionReason.ILLEGAL_ROSTER, detail)

    # 2 ── critical-need protection (dict lookups)
    ok, detail = _check_critical_need(send, receive, their_signal)
    if not ok:
        return _reject(RejectionReason.WORSENS_CRITICAL_NEED, detail)

    # 3 ── market valuation, entirely within one market (WS-E)
    out_val = value_package([a.row for a in send], allow_scalar_fallback=allow_scalar_fallback)
    in_val = value_package([a.row for a in receive], allow_scalar_fallback=allow_scalar_fallback)
    if not out_val.is_rankable or not in_val.is_rankable:
        blocked = out_val if not out_val.is_rankable else in_val
        return _reject(
            RejectionReason.UNVALUABLE,
            blocked.suppressed_reason or "package could not be valued on one market",
        )

    # ``compare_packages`` treats the first argument as the side we
    # GAIN. We receive ``in_val``, so it is the counter side.
    comparison = compare_packages(in_val, out_val, gate_pct=gate_pct)
    if comparison.market_gain_pct is None:
        return _reject(
            RejectionReason.UNVALUABLE,
            comparison.suppressed_reason or "no comparable market totals",
        )
    if not comparison.verdict_certain:
        # Boundary proximity, NOT presence of a conversion.
        return PackageCandidate(
            send=send,
            receive=receive,
            stage=stage,
            accepted=False,
            rejection=RejectionReason.VERDICT_UNCERTAIN,
            rejection_detail=comparison.suppressed_reason or "verdict uncertain",
            comparison=comparison,
            notes=tuple(notes),
        )

    # 4 ── cornerstone premium
    ok, detail = _check_cornerstone(receive, cornerstones, comparison)
    if not ok:
        return _reject(RejectionReason.CORNERSTONE_WITHOUT_PREMIUM, detail)

    # 5 ── exact lineup re-solve (EXPENSIVE — survivors only)
    sent_ids = {a.asset_id for a in send}
    after = [p for p in our_pool if p.player_id not in sent_ids]
    after.extend(a.player for a in receive if a.player is not None)
    roster_improvement = optimal_score(after, slots) - base_lineup

    # 6 ── acceptance plausibility (never a claim about a decision)
    shape = TradeShape(
        send_positions=_position_counts(send),
        receive_positions=_position_counts(receive),
        market_value_sent=out_val.total,
        market_value_received=in_val.total,
        markets_mixed=(out_val.market != in_val.market),
    )
    assessment = assess_partner(
        PartnerInputs(
            owner_id=partner_owner_id,
            our_roster=our_signal,
            their_roster=their_signal,
            shape=shape,
        )
    )
    if shape.markets_mixed:
        notes.append("sides priced on different markets; fairness suppressed per audit F-1")

    gain = comparison.market_gain_pct

    # The null trade is always on the table, costs nothing, and is
    # simpler than anything else. A package that is strictly worse than
    # it on both axes we care about is dominated before it is ranked.
    if gain < 0 and roster_improvement < 0:
        return PackageCandidate(
            send=send,
            receive=receive,
            stage=stage,
            accepted=False,
            rejection=RejectionReason.DOMINATED_BY_NO_TRADE,
            rejection_detail=(
                f"loses {abs(gain):.1f}% of market value AND "
                f"{abs(roster_improvement):.1f} lineup points; declining to "
                "trade is strictly better on both"
            ),
            value_efficiency=gain,
            roster_improvement=roster_improvement,
            comparison=comparison,
            notes=tuple(notes),
        )

    return PackageCandidate(
        send=send,
        receive=receive,
        stage=stage,
        accepted=True,
        value_efficiency=gain,
        roster_improvement=roster_improvement,
        acceptance_plausibility=assessment.trade_acceptance_estimate,
        acceptance_confidence=assessment.acceptance_confidence,
        simplicity=1.0 / float(len(send) + len(receive)),
        comparison=comparison,
        notes=tuple(notes),
    )


def _position_counts(assets: Sequence[TradeAsset]) -> dict[str, float]:
    out: dict[str, float] = {}
    for a in assets:
        pos = a.position.upper()
        out[pos] = out.get(pos, 0.0) + 1.0
    return out


def _is_near_miss(cand: PackageCandidate, gate_pct: float) -> bool:
    """Worth spending another asset on?

    Only packages that failed on VALUE and failed by a closeable margin.
    A structural rejection (illegal, critical need, cornerstone) is not
    fixed by adding filler, so expanding it wastes the budget the
    staging exists to protect.
    """
    if cand.accepted:
        # Already works — the simpler version dominates any expansion.
        return False
    if cand.rejection in {
        RejectionReason.ILLEGAL_ROSTER,
        RejectionReason.WORSENS_CRITICAL_NEED,
        RejectionReason.UNVALUABLE,
    }:
        return False
    if cand.comparison is None or cand.comparison.market_gain_pct is None:
        return False
    return abs(cand.comparison.market_gain_pct - gate_pct) <= NEAR_MISS_PCT


def generate_packages(
    our_pool: Sequence[RosterPlayer],
    slots: Sequence[str],
    *,
    our_assets: Sequence[TradeAsset],
    their_assets: Sequence[TradeAsset],
    their_full_roster: Sequence[TradeAsset] | None = None,
    partner_owner_id: str = "partner",
    our_signal: RosterSignal | None = None,
    their_signal: RosterSignal | None = None,
    roster_limit: int | None = None,
    gate_pct: float = DEFAULT_GATE_PCT,
    max_assets_per_side: int = MAX_PACKAGE_ASSETS,
    max_candidates_per_stage: int = 400,
    allow_scalar_fallback: bool = False,
    constraints: Any | None = None,
) -> dict[str, Any]:
    """Generate, filter and return a Pareto frontier of trade packages.

    Args:
        our_pool: our full roster, for the lineup re-solve.
        slots: the league's flattened starter slots.
        our_assets: what we are willing to send. Pre-filtering this to
            genuine surplus is the caller's job and is the single
            biggest lever on both quality and cost.
        their_assets: what we would want from them.
        our_signal / their_signal: roster engine output, via
            ``RosterSignal.from_engine``. ``their_signal`` powers the
            critical-need rejection; absent, that rule cannot fire and
            says so.
        roster_limit: league roster size cap, for the legality rule.
        gate_pct: the market-gain decision threshold handed to WS-E.
        max_assets_per_side: hard cap per side.
        max_candidates_per_stage: search budget. Exceeding it truncates
            and stamps a note rather than silently returning a partial
            frontier as though it were complete.
        constraints: C3-CON-01 recommendation constraints (persistent
            protection + temporary LOCK/EXCLUDE). Applied to ``our_assets``
            BEFORE stage 1 — never a post-hoc filter of an already-built
            frontier, per the spec's "applied during generation, before
            scoring" rule — through the same owner every other generator
            surface consumes (``src.trade.constraints``), not a page-local
            copy. Only the OUTGOING side is constrained: a protected player
            stays a valid incoming target. ``None`` (the default) generates
            exactly as before — every existing caller is unaffected.

    Returns:
        ``{"frontier": [...], "bestBy": {...}, "rejected": [...],
        "stages": [...], "truncated": bool, "constraintsBlockedOutgoing": int,
        "constraintsBlockedReasons": [...]}``
    """
    from src.trade.constraints import partition_sendable  # noqa: PLC0415

    # ``partition_sendable`` is a no-op when ``constraints`` is None or
    # inactive (src/trade/constraints.py:306-320), so this line changes
    # nothing for the one production caller today (src/api/gameplan.py),
    # which passes no constraints argument.
    our_assets, blocked_outgoing = partition_sendable(our_assets, constraints)

    base_lineup = optimal_score(our_pool, slots)
    our_size = len(our_pool)
    their_size = max(len(their_assets), 1)

    # Cornerstones come from their FULL roster when we have it. Deriving
    # them from ``their_assets`` — the filtered list of players we want —
    # is wrong: if we only ask about their two best players, both look
    # elite relative to that list and the premium rule refuses every
    # package. Falling back is supported but stamped.
    cornerstone_pool = their_full_roster if their_full_roster else their_assets
    cornerstones = _identify_cornerstones(cornerstone_pool)

    evaluated: list[PackageCandidate] = []
    stage_report: list[dict[str, Any]] = []
    truncated = False

    def _run(
        pairs: Iterable[tuple[tuple[TradeAsset, ...], tuple[TradeAsset, ...]]],
        stage: int,
    ) -> list[PackageCandidate]:
        nonlocal truncated
        out: list[PackageCandidate] = []
        for send, receive in pairs:
            if len(out) >= max_candidates_per_stage:
                truncated = True
                break
            out.append(
                _evaluate(
                    send,
                    receive,
                    stage,
                    our_pool=our_pool,
                    slots=slots,
                    base_lineup=base_lineup,
                    our_size=our_size,
                    their_size=their_size,
                    roster_limit=roster_limit,
                    their_signal=their_signal,
                    our_signal=our_signal,
                    cornerstones=cornerstones,
                    gate_pct=gate_pct,
                    partner_owner_id=partner_owner_id,
                    allow_scalar_fallback=allow_scalar_fallback,
                )
            )
        return out

    # ── Stage 1: 1-for-1 ─────────────────────────────────────────────
    stage1 = _run((((o,), (t,)) for o in our_assets for t in their_assets), 1)
    evaluated.extend(stage1)
    stage_report.append(
        {"stage": 1, "evaluated": len(stage1), "accepted": sum(c.accepted for c in stage1)}
    )

    # ── Stage 2: expand ONLY near-misses ─────────────────────────────
    near = [c for c in stage1 if _is_near_miss(c, gate_pct)]
    stage2: list[PackageCandidate] = []
    if max_assets_per_side >= 2 and near:
        pairs: list[tuple[tuple[TradeAsset, ...], tuple[TradeAsset, ...]]] = []
        for cand in near:
            base_send, base_recv = cand.send, cand.receive
            gain = cand.comparison.market_gain_pct if cand.comparison else 0.0
            if gain > gate_pct:
                # We are gaining too much: add to OUR side to balance.
                for extra in our_assets:
                    if extra.asset_id not in {a.asset_id for a in base_send}:
                        pairs.append(((*base_send, extra), base_recv))
            else:
                # We are giving too much: ask for more back.
                for extra in their_assets:
                    if extra.asset_id not in {a.asset_id for a in base_recv}:
                        pairs.append((base_send, (*base_recv, extra)))
        stage2 = _run(pairs, 2)
        evaluated.extend(stage2)
    stage_report.append(
        {
            "stage": 2,
            "expandedFrom": len(near),
            "evaluated": len(stage2),
            "accepted": sum(c.accepted for c in stage2),
        }
    )

    # ── Stage 3: 2-for-2, from stage-2 near-misses only ──────────────
    near2 = [c for c in stage2 if _is_near_miss(c, gate_pct)]
    stage3: list[PackageCandidate] = []
    if max_assets_per_side >= 2 and near2:
        pairs = []
        for cand in near2:
            if len(cand.send) == 1:
                for extra in our_assets:
                    if extra.asset_id not in {a.asset_id for a in cand.send}:
                        pairs.append(((*cand.send, extra), cand.receive))
            elif len(cand.receive) == 1:
                for extra in their_assets:
                    if extra.asset_id not in {a.asset_id for a in cand.receive}:
                        pairs.append((cand.send, (*cand.receive, extra)))
        stage3 = _run(pairs, 3)
        evaluated.extend(stage3)
    stage_report.append(
        {
            "stage": 3,
            "expandedFrom": len(near2),
            "evaluated": len(stage3),
            "accepted": sum(c.accepted for c in stage3),
        }
    )

    # ── Domination: a simpler package that is no worse wins ──────────
    frontier = pareto_frontier(evaluated)
    frontier_keys = {_package_key(c) for c in frontier}
    dominated = [
        PackageCandidate(
            send=c.send,
            receive=c.receive,
            stage=c.stage,
            accepted=False,
            rejection=RejectionReason.DOMINATED,
            rejection_detail=(
                "another package is at least as good on market value, lineup "
                "improvement, acceptance plausibility and simplicity"
            ),
            value_efficiency=c.value_efficiency,
            roster_improvement=c.roster_improvement,
            acceptance_plausibility=c.acceptance_plausibility,
            acceptance_confidence=c.acceptance_confidence,
            simplicity=c.simplicity,
            comparison=c.comparison,
            notes=c.notes,
        )
        for c in evaluated
        if c.accepted and _package_key(c) not in frontier_keys
    ]

    rejected = [c for c in evaluated if not c.accepted] + dominated
    labelled = label_frontier(frontier)

    notes: list[str] = []
    if their_signal is None:
        notes.append(
            "no partner roster signal supplied — the critical-need rejection "
            "rule could not fire; packages are not screened against their needs"
        )
    if not their_full_roster:
        notes.append(
            "cornerstones inferred from the requested assets rather than the "
            "partner's full roster; if that list is already their best players, "
            "the cornerstone rule is stricter than intended. Pass "
            "their_full_roster to measure it properly"
        )
    if truncated:
        notes.append(
            f"search truncated at {max_candidates_per_stage} candidates in at "
            "least one stage; the frontier is valid for what was explored but "
            "is not exhaustive"
        )

    return {
        **labelled,
        "frontier": [c.to_dict() for c in frontier],
        "rejected": [c.to_dict() for c in rejected],
        "stages": stage_report,
        "truncated": truncated,
        "evaluatedTotal": len(evaluated),
        "notes": notes,
        "modelVersion": PACKAGES_MODEL_VERSION,
        # Naming matches src/trade/finder.py's C3-CON-01 wiring for
        # cross-generator consistency: a COUNT (not the blocked list itself,
        # which would leak protected-player identities into a package
        # response) plus the distinct reasons.
        "constraintsBlockedOutgoing": len(blocked_outgoing),
        "constraintsBlockedReasons": sorted({reason for _, reason in blocked_outgoing}),
    }


def _identify_cornerstones(assets: Sequence[TradeAsset]) -> frozenset[str]:
    """Which assets are genuinely elite for this roster.

    Both conditions required: inside the top ``CORNERSTONE_TOP_N`` AND
    worth at least ``CORNERSTONE_VALUE_SHARE`` of the roster's best
    asset. Rank alone would make every asset a cornerstone whenever the
    candidate pool is small, which turns the premium rule from a
    safeguard into a blanket refusal.
    """
    ranked = sorted(assets, key=lambda a: (-_market_hint(a), a.asset_id))
    if not ranked:
        return frozenset()
    top_value = _market_hint(ranked[0])
    if top_value <= 0:
        return frozenset()
    floor = CORNERSTONE_VALUE_SHARE * top_value
    return frozenset(a.asset_id for a in ranked[:CORNERSTONE_TOP_N] if _market_hint(a) >= floor)


def _market_hint(asset: TradeAsset) -> float:
    """Rough value for cornerstone identification only.

    Deliberately NOT used for any package total — those go through
    ``value_package`` so the single-market rule is never bypassed.
    """
    sites = asset.row.get("canonicalSiteValues")
    if not isinstance(sites, Mapping):
        return 0.0
    vals = [float(v) for v in sites.values() if isinstance(v, (int, float)) and v > 0]
    return max(vals) if vals else 0.0


def describe_limitations() -> dict[str, Any]:
    """Machine-readable limitations. Asserted by tests."""
    return {
        "modelVersion": PACKAGES_MODEL_VERSION,
        "canSupport": [
            "Generating legal, single-market-valued trade packages between two specific rosters.",
            "Presenting a Pareto frontier of genuine alternatives rather than a "
            "single blended ranking.",
            "Explaining, per package, exactly why it was rejected.",
            "Withholding a comparison whose verdict its own uncertainty could "
            "flip — on proximity to the decision boundary, not on the presence "
            "of a conversion.",
        ],
        "cannotSupport": [
            "Any claim that a manager will accept a package. "
            "acceptancePlausibility inherits the partner model's limitation: "
            "rejections are never observed, so it is a plausibility score in "
            "probability units and not a calibrated probability.",
            "Exhaustive search. Generation is staged and budgeted; the frontier "
            "is valid for what was explored, not proven globally optimal.",
            "Packages beyond the configured asset cap — a deal needing three "
            "pieces per side to balance is negotiated, not generated.",
            "Multi-year or rebuild framing: lineup improvement is "
            "rest-of-season, inheriting the target engine's scope.",
            "Any ranking ACROSS the frontier. No exchange rate exists between "
            "market points, lineup points and plausibility; a caller that "
            "collapses the frontier to one pick is expressing a preference.",
        ],
        "keyAssumptions": {
            "maxPackageAssets": MAX_PACKAGE_ASSETS,
            "nearMissPct": NEAR_MISS_PCT,
            "cornerstonePremiumPct": CORNERSTONE_PREMIUM_PCT,
            "cornerstoneTopN": CORNERSTONE_TOP_N,
            "thresholdsAreMeasured": False,
            "thresholdsNote": (
                "All four are assumed, not fitted. No dataset of accepted vs "
                "rejected offers exists to calibrate them against — the same "
                "gap that makes the acceptance estimate uncalibratable."
            ),
        },
        "whatWouldUnlockMore": [
            "A record of DECLINED offers, which would calibrate both the "
            "acceptance estimate and the cornerstone premium.",
            "Measured roster-limit and lineup-legality rules per league, so "
            "the legality check can go beyond size bounds.",
        ],
    }
