"""Analyze Trade — the ONE canonical decision-synthesis owner (#792 / C7-DESK-01).

Binding design records: ``docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md``
(synthesize by UNIQUE INFORMATION, never by averaging every visible panel),
``docs/trade/ROSTER_CAPACITY_FORCED_DROP_TRADE_ANALYSIS_ADDENDUM_2026-08-14.md``
(#843) and ``docs/OWNER_FEATURE_ADDENDUM_2026-08-29_BEST_BALL_ROSTER_UTILITY.md``
(#1173).  The same packet is meant for ``/trade`` today and the Trade Desk,
counter-offers and saved analyses later — one recommendation contract, never a
formula per consumer.

The packet answers separate questions in separate LENSES
───────────────────────────────────────────────────────
* **market** — what does the market charge?  Canonical asset values, the raw
  package difference, and exact KTC Value Adjustment
  (``src.trade.ktc_va.adjusted_pair_totals``) as its own market lens.  VOTES.
* **roster** — what does THIS roster gain or lose?  #1173 best-ball utility on
  the final legal roster (``rosterUtility``), priced by LEAGUE-SCORED
  PROJECTIONS.  VOTES.  Team Strength (``finalRosterSimulation``) is shown
  inside it as context but does NOT vote: it is a sum of ``rankDerivedValue``,
  the same lineage the market lens already counts.
* **feasibility** — can the trade legally fit, and what must go?  #843 roster
  capacity.  VOTES on what the other two cannot see: dynasty value released by
  a forced cut, or an existing overage resolved.  The cut's WEEKLY-LINEUP cost
  is already inside the roster lens (it is evaluated post-cleanup), so it is
  not counted twice.
* **evidence** — how trustworthy is the rest?  Projection coverage, the
  estimate's own precision, canonical confidence stamps on the traded assets.
  NEVER votes; it sets confidence and fills ``uncertainty``.
* **posture** — #840 Competitive Posture (``src.roster_intel.posture``) for
  both teams, with the marginal change on the final legal roster.  NEVER
  votes: it is derived from playoff odds / lineup strength / age — lineages
  the other lenses already read.  It decides only how two DISAGREEING primary
  lenses are WEIGHED (see "Posture weighting" below).
* **counterpartyFeasibility** — #843 capacity for the OTHER team (forced
  drops it would have to make).  Never votes in this team's verdict: it bears
  on whether they would accept, and their cut is their cost, not ours.
* **currentSeasonEquity** — named UNAVAILABLE with the reason: the playoff
  simulator's trade counterfactual (``playoff_sim.simulate_trade_impact``)
  takes a weekly-mean shift only and is not wired.  Unavailable is not
  neutral and is never read as zero.

Posture weighting (never a vote)
────────────────────────────────
When the market lens (long-horizon canonical value) and the roster lens
(current-season best-ball utility) point in OPPOSITE directions the rule table
says TOO_CLOSE.  A PUSH team weighs the current-season lens; a RETOOL or
REBUILD team weighs the long-horizon lens; HOLD — or any posture at LOW
confidence — leaves TOO_CLOSE.  Posture never moves a verdict when the lenses
agree, never creates a direction when both are neutral, and never acts as a
veto (it only lands on LEAN_MAKE / LEAN_PASS).  Pinned by
``tests/trade/test_analyze_posture_weighting.py``.

Single carrier for a forced drop
────────────────────────────────
The market lens prices the PACKAGE (canonical values + KTC VA) and never the
final roster; the dynasty value a forced cut releases is carried ONLY by the
feasibility lens (``forcedDropReleaseCost``), and the cut's weekly-lineup
cost ONLY by the roster lens (evaluated post-cleanup).  So no forced drop is
subtracted twice.

Use Team Context (#842)
───────────────────────
``simulation["teamContext"]["applied"] is False`` → Asset-Only: the roster,
feasibility and posture lenses are excluded BY MODE (and say so), the
recommendation comes from the market lens alone, and no asset value changes.
One contract with a dimension switched off — not a second formula.  Every
packet carries ``contextEffect``: the Asset-Only recommendation beside the
Team-Context one and WHICH dimension moved it, so the explanation can say what
changed because of team context versus raw value.

No weights
──────────
Directions (favors / opposes / neutral) and each lens's own magnitude bucket
go through an explicit rule table.  The roster lens's neutral band and "large"
multiple are declared PRIORS in ``config/trade/analyze_trade.json``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.trade.ktc_va import adjusted_pair_totals
from src.trade.suggestions import _fairness_label

#: The five product-facing verdicts (plan §C, "Product job").
RECOMMENDATIONS = ("MAKE", "LEAN_MAKE", "TOO_CLOSE", "LEAN_PASS", "PASS")
PACKET_VERSION = "analyze_trade_v3"

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "analyze_trade.json"
_DEFAULTS = {"materialityPpg": 1.0, "largeMultiple": 3.0, "depthNotableLossPpg": 0.5}

#: Lineage tags: two lenses sharing one may not both vote.
LINEAGE_CANONICAL_VALUE = "canonical_value"
LINEAGE_PROJECTION = "league_scored_projection"
LINEAGE_ROSTER_RULES = "league_roster_rules"

#: Dimensions this depth deliberately does not compute, named so "not
#: included" and "computed and found neutral" never look the same.
_UNAVAILABLE_DIMENSIONS = (
    {
        "dimension": "marketCorroboration",
        "reason": "no_backing_ledger",
        "notes": "C4-MTL-01 (real market trades) and C4-MTL-03 (comparable-trade "
        "matching) are ABSENT — there is no independent vendor/comp evidence to synthesize.",
    },
    {
        "dimension": "valueUncertainty",
        "reason": "unaudited_model",
        "notes": "Monte Carlo value-uncertainty bands/correlation have open revalidation "
        "items (docs/trade/TRADE_DECISION_SYNTHESIS_PLAN_2026-08-11.md §A) and are not "
        "folded into this recommendation until that audit closes.",
    },
    {
        "dimension": "currentSeasonEquity",
        "reason": "counterfactual_not_wired",
        "notes": "src.ros.playoff_sim.simulate_trade_impact takes a weekly-mean shift only "
        "and has no production caller; playoff/championship deltas wait for that owner.",
    },
    {
        "dimension": "ownPickSlotCounterfactual",
        "reason": "draft_order_unmodeled",
        "notes": "The league's non-playoff draft-order method (record / Max PF / "
        "consolation) is not modelled, so no projected own-pick slot change is credited.",
    },
)

_STEP = {r: i for i, r in enumerate(RECOMMENDATIONS)}


def _config() -> dict[str, float]:
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        roster = raw.get("rosterUtility") or {}
        return {k: float(roster.get(k, v)) for k, v in _DEFAULTS.items()}
    except (OSError, ValueError, TypeError):
        return dict(_DEFAULTS)


def _direction(value: float, *, epsilon: float = 0.0) -> str:
    if value > epsilon:
        return "favors"
    if value < -epsilon:
        return "opposes"
    return "neutral"


@dataclass
class DimensionResult:
    """One lens: direction / magnitude / detail — never a raw score meant to be
    summed with another lens's raw score."""

    name: str
    available: bool
    direction: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    unavailable_reason: str | None = None
    votes: bool = True
    lineage: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "dimension": self.name,
            "available": self.available,
            "votes": self.votes and self.available,
            "lineage": self.lineage,
        }
        if self.available:
            out["direction"] = self.direction
            out["detail"] = self.detail
        else:
            out["unavailableReason"] = self.unavailable_reason
            if self.detail:
                out["detail"] = self.detail
        return out


# ── Lens 1: market ───────────────────────────────────────────────────────


def _market_lens(simulation: dict[str, Any]) -> DimensionResult:
    """Canonical package values + exact KTC VA.  Calls the owner directly."""
    receiving = simulation.get("receiving") or []
    sending = simulation.get("sending") or []
    sending_values = [a["value"] for a in sending if a.get("value") is not None]
    receiving_values = [a["value"] for a in receiving if a.get("value") is not None]
    if not sending_values and not receiving_values:
        return DimensionResult(
            name="equity",
            available=False,
            unavailable_reason="no_priced_assets_either_side",
            lineage=LINEAGE_CANONICAL_VALUE,
        )
    send_adj, recv_adj, send_va, recv_va = adjusted_pair_totals(sending_values, receiving_values)
    gap = recv_adj - send_adj  # positive = the selected team comes out ahead
    magnitude = _fairness_label(gap)
    # An "even" gap is inside the market's own fairness band: it neither
    # favors nor opposes, whatever its sign.
    direction = "neutral" if magnitude == "even" else _direction(gap)
    return DimensionResult(
        name="equity",
        available=True,
        direction=direction,
        lineage=LINEAGE_CANONICAL_VALUE,
        detail={
            "receivingValue": int(round(sum(receiving_values))),
            "sendingValue": int(round(sum(sending_values))),
            "rawGap": int(round(sum(receiving_values) - sum(sending_values))),
            "vaAdjustedGap": int(round(gap)),
            "magnitude": magnitude,
            "sendingAdjusted": round(send_adj, 1),
            "receivingAdjusted": round(recv_adj, 1),
            "sendingValueAdjustment": round(float(send_va), 1),
            "receivingValueAdjustment": round(float(recv_va), 1),
            "valueAdjustment": "KTC Value Adjustment (exact; src.trade.ktc_va)",
            "unresolvedIn": list(simulation.get("unresolvedIn") or []),
            "unresolvedOut": list(simulation.get("unresolvedOut") or []),
            # Wave A: owned picks this team does not hold are reported by
            # the simulator and left out of ``sending`` -- named here so the
            # explanation can say why they are not counted.
            "notOwnedBySender": [
                {
                    "label": str(c.get("label") or ""),
                    "actualOwnerName": c.get("actualOwnerName"),
                }
                for c in ((simulation.get("ownedPickChecks") or {}).get("notOwnedBySender") or [])
                if isinstance(c, dict)
            ],
            # Generic picks this team sends: priced in ``sendingValue`` but not
            # taken off the roster (no specific owned pick was chosen), so the
            # explanation names them instead of leaving equity and the roster
            # totals an unexplained mismatch.
            "hypotheticalPicksOut": [
                str(x)
                for x in (
                    (simulation.get("ownedPickChecks") or {}).get("hypotheticalPicksOut") or []
                )
            ],
        },
    )


# ── Lens 2: roster (#1173) ───────────────────────────────────────────────


def _team_strength_context(frs: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(frs, dict) or frs.get("available", True) is not True:
        return None
    before = (frs.get("strengthBefore") or {}).get("total")
    after = (frs.get("strengthAfter") or {}).get("total")
    if before is None or after is None:
        return None
    return {
        "before": round(float(before), 1),
        "after": round(float(after), 1),
        "delta": round(float(after) - float(before), 1),
        "lineage": LINEAGE_CANONICAL_VALUE,
        "countedAsVote": False,
        "why": "Team Strength sums canonical values over the meaningful core — the same "
        "lineage the market lens already counts, so it explains but does not vote.",
    }


def _roster_lens(simulation: dict[str, Any], cfg: dict[str, float]) -> DimensionResult:
    utility = simulation.get("rosterUtility")
    context = _team_strength_context(simulation.get("finalRosterSimulation"))
    if not isinstance(utility, dict) or utility.get("available") is not True:
        reason = "not_computed"
        if isinstance(utility, dict):
            reason = str(utility.get("unavailableReason") or reason)
        return DimensionResult(
            name="rosterUtility",
            available=False,
            unavailable_reason=reason,
            lineage=LINEAGE_PROJECTION,
            detail={"teamStrength": context} if context else {},
        )
    impact = utility.get("impact") or {}
    raw_ppg = impact.get("ppg")
    if not isinstance(raw_ppg, (int, float)):
        # "available" without a number is a malformed utility, not a zero.
        return DimensionResult(
            name="rosterUtility",
            available=False,
            unavailable_reason="impact_missing",
            lineage=LINEAGE_PROJECTION,
            detail={"teamStrength": context} if context else {},
        )
    ppg = float(raw_ppg)
    stderr = impact.get("standardError")
    # No published precision: the band is the declared PRIOR alone, never a
    # precision of zero invented for the missing figure.
    band = (
        max(cfg["materialityPpg"], 2.0 * float(stderr))
        if isinstance(stderr, (int, float))
        else cfg["materialityPpg"]
    )
    coverage = (utility.get("coverage") or {}).get("state")
    if coverage == "partial":
        # A traded player without a projection: the number is real for the
        # priced players but incomplete for the trade, so the lens ABSTAINS
        # from voting rather than read a partial figure as whole.
        direction = None
        magnitude = "abstain_partial_coverage"
    elif abs(ppg) < band:
        direction, magnitude = "neutral", "within_band"
    else:
        direction = _direction(ppg)
        magnitude = "large" if abs(ppg) >= cfg["largeMultiple"] * band else "modest"
    detail = {
        "unit": utility.get("unit"),
        "ppg": round(ppg, 2),
        "standardError": stderr,
        "ppgBeforeCleanup": impact.get("ppgBeforeCleanup"),
        "neutralBandPpg": round(band, 2),
        "magnitude": magnitude,
        "coverage": utility.get("coverage"),
        "cleanup": utility.get("cleanup"),
        "before": utility.get("before"),
        "after": utility.get("after"),
        "players": utility.get("players"),
        "shape": utility.get("shape"),
        "depth": utility.get("depth"),
        "rosterSpot": utility.get("rosterSpot"),
        "basis": utility.get("basis"),
        "assumptions": utility.get("assumptions"),
        "teamStrength": context,
    }
    if direction is None:
        return DimensionResult(
            name="rosterUtility",
            available=False,
            unavailable_reason="partial_projection_coverage",
            lineage=LINEAGE_PROJECTION,
            detail=detail,
        )
    return DimensionResult(
        name="rosterUtility",
        available=True,
        direction=direction,
        lineage=LINEAGE_PROJECTION,
        detail=detail,
    )


# ── Lens 3: feasibility (#843) ───────────────────────────────────────────


def _feasibility_state(cap: dict[str, Any]) -> str:
    limit = cap.get("rosterLimit")
    if limit is None:
        return "unknown_limit"
    if cap.get("requiresDrops") is None:
        return "uncertain"
    before = cap.get("overLimitBefore")
    after = cap.get("overLimitAfter")
    if not isinstance(before, int) or not isinstance(after, int):
        # A known limit with an unstated overage is not "zero over".
        return "uncertain"
    if before > 0:
        if after == 0:
            return "resolves_overage"
        if after < before:
            return "reduces_overage"
        if after > before:
            return "worsens_overage"
        return "overage_unchanged"
    if cap.get("requiresDrops"):
        return "cut_required"
    if cap.get("openSpotsAfter") == 0:
        return "uses_final_spot"
    return "fits_cleanly"


def _feasibility_lens(simulation: dict[str, Any]) -> DimensionResult:
    cap = simulation.get("rosterCapacity")
    if not isinstance(cap, dict) or cap.get("unavailable"):
        return DimensionResult(
            name="feasibility",
            available=False,
            unavailable_reason="no_team_selected_or_uncomputable"
            if not isinstance(cap, dict)
            else str(cap.get("unavailable")),
            lineage=LINEAGE_ROSTER_RULES,
        )
    state = _feasibility_state(cap)
    drops = cap.get("forcedDrops") or []
    detail = {
        "state": state,
        "rosterLimit": cap.get("rosterLimit"),
        "sizeBefore": cap.get("sizeBefore"),
        "sizeAfter": cap.get("sizeAfter"),
        "openSpotsBefore": cap.get("openSpotsBefore"),
        "openSpotsAfter": cap.get("openSpotsAfter"),
        "overLimitBefore": cap.get("overLimitBefore"),
        "overLimitAfter": cap.get("overLimitAfter"),
        "requiresDrops": cap.get("requiresDrops"),
        "forcedDrops": [
            {
                "playerId": d.get("playerId"),
                "name": d.get("name"),
                "position": d.get("position"),
                "value": d.get("value"),
                "releaseCost": d.get("releaseCost"),
                "acquiredInTrade": d.get("acquiredInTrade"),
            }
            for d in drops
        ],
        "forcedDropReleaseCost": cap.get("forcedDropReleaseCost"),
        "unpricedForcedDrops": cap.get("unpricedForcedDrops"),
        "candidatesTied": bool(cap.get("rungOrderWasTied")),
        "ladderExhausted": bool(cap.get("ladderExhausted")),
        "certainty": cap.get("certainty"),
        "picksOccupySpots": False,
        "notes": list(cap.get("notes") or []),
    }
    if state in ("unknown_limit", "uncertain"):
        return DimensionResult(
            name="feasibility",
            available=False,
            unavailable_reason=state,
            lineage=LINEAGE_ROSTER_RULES,
            detail=detail,
        )
    if state in ("resolves_overage", "reduces_overage"):
        direction = "favors"
    elif state in ("cut_required", "worsens_overage"):
        # The dynasty value a forced release gives away (its weekly-lineup
        # cost is already inside the roster lens).  Releasing only unpriced
        # or zero-cost players is a burden but not a value loss.
        released = cap.get("forcedDropReleaseCost")
        # An unpriced forced drop's value is UNKNOWN, not zero: it is not
        # claimed as a cost (the reasons still name the cut).
        released_value = isinstance(released, (int, float)) and released > 0
        direction = "opposes" if released_value or state == "worsens_overage" else "neutral"
    else:
        direction = "neutral"
    return DimensionResult(
        name="feasibility",
        available=True,
        direction=direction,
        lineage=LINEAGE_ROSTER_RULES,
        detail=detail,
    )


# ── Context: posture (#840) and the other team's capacity (never vote) ──


#: Postures that weigh each primary lens when the two disagree.
_POSTURE_FOLLOWS = {"PUSH": "rosterUtility", "RETOOL": "equity", "REBUILD": "equity"}


def _posture_lens(simulation: dict[str, Any]) -> DimensionResult:
    block = simulation.get("posture")
    if not isinstance(block, dict) or block.get("available") is not True:
        reason = "not_computed"
        if isinstance(block, dict):
            reason = str(block.get("unavailableReason") or reason)
        return DimensionResult(
            name="posture", available=False, unavailable_reason=reason, votes=False
        )
    sel = block.get("selected") or {}
    cp = block.get("counterparty") or {}
    return DimensionResult(
        name="posture",
        available=True,
        direction=None,
        votes=False,
        lineage="playoff_odds+lineup_strength+age",
        detail={
            "selected": {
                "teamName": sel.get("teamName"),
                "posture": sel.get("posture"),
                "confidence": sel.get("confidence"),
                "affinities": sel.get("affinities"),
                "components": sel.get("components"),
                "marginal": sel.get("marginal"),
                "notes": sel.get("notes"),
            },
            "counterparty": (
                {
                    "teamName": cp.get("teamName"),
                    "posture": cp.get("posture"),
                    "confidence": cp.get("confidence"),
                    "affinities": cp.get("affinities"),
                    "marginal": cp.get("marginal"),
                }
                if cp
                else None
            ),
            "timing": block.get("timing"),
            "oddsInput": block.get("oddsInput"),
            "calibration": block.get("calibration"),
            "countedAsVote": False,
            "role": "weights the primary lenses only when they disagree",
        },
    )


def _counterparty_feasibility(simulation: dict[str, Any]) -> DimensionResult:
    cp = simulation.get("counterparty")
    if not isinstance(cp, dict) or cp.get("available") is not True:
        reason = "not_computed"
        if isinstance(cp, dict):
            reason = str(cp.get("unavailableReason") or reason)
        return DimensionResult(
            name="counterpartyFeasibility",
            available=False,
            unavailable_reason=reason,
            votes=False,
            lineage=LINEAGE_ROSTER_RULES,
        )
    inner = _feasibility_lens({"rosterCapacity": cp.get("rosterCapacity")})
    detail = dict(inner.detail or {})
    detail["team"] = cp.get("team")
    detail["role"] = (
        "their roster consequence: bears on whether they would accept; never a vote "
        "in your verdict and never counted as your cost"
    )
    return DimensionResult(
        name="counterpartyFeasibility",
        available=inner.available,
        direction=inner.direction,
        unavailable_reason=inner.unavailable_reason,
        votes=False,
        lineage=LINEAGE_ROSTER_RULES,
        detail=detail,
    )


# ── Lens 4: evidence (never votes) ───────────────────────────────────────


def _evidence_lens(simulation: dict[str, Any], roster: DimensionResult) -> DimensionResult:
    traded = [*(simulation.get("receiving") or []), *(simulation.get("sending") or [])]
    low = [
        {"name": a.get("name"), "confidenceBucket": a.get("confidenceBucket")}
        for a in traded
        if a.get("confidenceBucket") == "low"
    ]
    disagree = [a.get("name") for a in traded if a.get("hasSourceDisagreement") is True]
    unstamped = [a.get("name") for a in traded if a.get("confidenceBucket") is None]
    coverage = (roster.detail or {}).get("coverage") if roster.detail else None
    return DimensionResult(
        name="evidence",
        available=True,
        direction=None,
        votes=False,
        detail={
            "lowConfidenceAssets": low,
            "sourceDisagreementAssets": disagree,
            "unstampedAssets": unstamped,
            "projectionCoverage": coverage,
            "rosterUtilityStandardError": (roster.detail or {}).get("standardError"),
            "note": "Evidence quality sets confidence and the uncertainty list; it is never a "
            "vote, and the canonical value's contributing sources are never re-counted as "
            "independent opinions.",
        },
    )


# ── Synthesis ────────────────────────────────────────────────────────────


def _step(rec: str, delta: int) -> str:
    i = min(max(_STEP[rec] - delta, 0), len(RECOMMENDATIONS) - 1)
    return RECOMMENDATIONS[i]


def _recommend(
    market: DimensionResult,
    roster: DimensionResult,
    feasibility: DimensionResult,
    posture: DimensionResult | None = None,
) -> tuple[str, str, str]:
    """``(recommendation, confidence, basis)`` — the rule table."""
    primaries = [d for d in (market, roster) if d.available]
    if not primaries:
        return "TOO_CLOSE", "LOW", "no_primary_lens"

    if len(primaries) == 1:
        only = primaries[0]
        strong = only.name == "equity" and only.detail.get("magnitude") == "stretch"
        if only.name == "rosterUtility":
            strong = only.detail.get("magnitude") == "large"
        if only.direction == "favors":
            rec = "MAKE" if strong else "LEAN_MAKE"
        elif only.direction == "opposes":
            rec = "PASS" if strong else "LEAN_PASS"
        else:
            rec = "TOO_CLOSE"
        confidence = "MEDIUM" if only.direction != "neutral" else "LOW"
        basis = f"single_lens:{only.name}"
    else:
        dirs = {market.direction, roster.direction}
        basis = "market_and_roster"
        if dirs == {"favors"}:
            rec, confidence = "MAKE", "HIGH"
        elif dirs == {"opposes"}:
            rec, confidence = "PASS", "HIGH"
        elif dirs == {"favors", "neutral"}:
            rec, confidence = "LEAN_MAKE", "MEDIUM"
        elif dirs == {"opposes", "neutral"}:
            rec, confidence = "LEAN_PASS", "MEDIUM"
        elif dirs == {"favors", "opposes"}:
            # The lenses disagree: the market and this roster want different
            # things.  "Depends" is the honest answer; the dissent is shown —
            # unless this team's posture says which horizon it is playing for.
            rec, confidence = "TOO_CLOSE", "MEDIUM"
            weighted = _posture_weighted(market, roster, posture)
            if weighted is not None:
                rec, confidence, tag = weighted
                basis += tag
        else:
            rec, confidence = "TOO_CLOSE", "LOW"

    if feasibility.available and feasibility.direction in ("favors", "opposes"):
        rec = _step(rec, 1 if feasibility.direction == "favors" else -1)
        basis += f"+feasibility:{feasibility.direction}"
    if feasibility.detail.get("ladderExhausted"):
        # No legal cleanup could be found: the trade cannot be recommended as
        # a clean MAKE whatever the value says.
        if _STEP[rec] < _STEP["TOO_CLOSE"]:
            rec = "TOO_CLOSE"
        basis += "+no_legal_cleanup"
    return rec, confidence, basis


def _posture_weighted(
    market: DimensionResult, roster: DimensionResult, posture: DimensionResult | None
) -> tuple[str, str, str] | None:
    """Which disagreeing lens this team's posture weighs, or ``None``.

    Never a vote: it only ever picks the direction ONE of the two existing
    primary lenses already gave, lands on a LEAN (never MAKE / PASS — not a
    veto), and abstains for HOLD or LOW-confidence posture.
    """
    if posture is None or not posture.available:
        return None
    sel = (posture.detail or {}).get("selected") or {}
    label = sel.get("posture")
    conf = sel.get("confidence")
    follow = _POSTURE_FOLLOWS.get(str(label))
    if follow is None or conf not in ("HIGH", "MEDIUM"):
        return None
    lens = roster if follow == "rosterUtility" else market
    rec = "LEAN_MAKE" if lens.direction == "favors" else "LEAN_PASS"
    return rec, "LOW", f"+posture_weighting:{label}->{lens.name}"


def _pct(x: Any) -> str:
    return "—" if x is None else f"{float(x):.0f}%"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _reasons(
    market: DimensionResult,
    roster: DimensionResult,
    feasibility: DimensionResult,
    cfg: dict[str, float],
) -> tuple[list[str], list[str]]:
    reasons_for: list[str] = []
    reasons_against: list[str] = []

    if market.available:
        gap = market.detail["vaAdjustedGap"]
        mag = market.detail["magnitude"]
        if market.direction == "favors":
            reasons_for.append(f"+{gap:,} package value after KTC Value Adjustment ({mag} gap)")
        elif market.direction == "opposes":
            reasons_against.append(
                f"{gap:,} package value against you after KTC Value Adjustment ({mag} gap)"
            )

    detail = roster.detail or {}
    # A roster lens that abstained (a traded player has no projection) gives
    # no roster reasons: its numbers are partial, and a reason built on them
    # would read as complete.  The uncertainty list says why.
    abstained = roster.unavailable_reason == "partial_projection_coverage"
    if detail.get("ppg") is not None and not abstained:
        ppg = detail["ppg"]
        if roster.available and roster.direction == "favors":
            reasons_for.append(f"+{ppg:.1f} expected best-ball points per week in the legal lineup")
        elif roster.available and roster.direction == "opposes":
            reasons_against.append(
                f"{ppg:.1f} expected best-ball points per week in the legal lineup"
            )
        for p in detail.get("players") or []:
            entry = p.get("lineupEntryPctAfter")
            if p.get("role") != "incoming" or not isinstance(entry, (int, float)):
                continue  # unprojected: no lineup-entry claim either way
            if entry >= 50:
                reasons_for.append(
                    f"{p['name']} enters the optimal lineup in "
                    f"{_pct(p['lineupEntryPctAfter'])} of simulated weeks"
                )
            else:
                reasons_against.append(
                    f"{p['name']} would reach the lineup in only "
                    f"{_pct(p['lineupEntryPctAfter'])} of simulated weeks (redundant here)"
                )
        # Only players whose lineup usage was measured: an unprojected player's
        # usage is unknown, not 0%, and never counts toward "rarely used".
        outgoing = [
            p
            for p in detail.get("players") or []
            if p.get("role") == "outgoing" and p.get("lineupEntryPctBefore") is not None
        ]
        if outgoing:
            usage = ", ".join(
                f"{p['name']} {_pct(p.get('lineupEntryPctBefore'))}" for p in outgoing
            )
            line = f"Outgoing lineup usage today: {usage}"
            if all(p["lineupEntryPctBefore"] < 50 for p in outgoing):
                reasons_for.append(line)
            else:
                reasons_against.append(line)
        depth = (detail.get("depth") or {}).get("meanLossDeltaPpg")
        if depth is not None and abs(depth) >= cfg["depthNotableLossPpg"]:
            if depth > 0:
                reasons_against.append(
                    f"Bench insurance declines: a missing starter costs {depth:.1f} more "
                    "points per week"
                )
            else:
                reasons_for.append(
                    f"Bench insurance improves: a missing starter costs {abs(depth):.1f} "
                    "fewer points per week"
                )

    fd = feasibility.detail or {}
    state = fd.get("state")
    # (posture / counterparty reasons are appended by ``_context_reasons``)
    if state == "fits_cleanly":
        spots = fd.get("openSpotsAfter")
        reasons_for.append(
            "Fits without a cut"
            + (f" ({_plural(int(spots), 'open spot')} after)" if spots is not None else "")
        )
    elif state == "uses_final_spot":
        reasons_against.append("Uses your final open roster spot")
    elif state == "resolves_overage":
        reasons_for.append("Brings your roster back under the limit")
    elif state == "reduces_overage":
        reasons_for.append(
            f"Reduces your roster overage ({fd.get('overLimitBefore')} → {fd.get('overLimitAfter')})"
        )
    elif state in ("cut_required", "worsens_overage"):
        names = ", ".join(str(d.get("name")) for d in fd.get("forcedDrops") or [])
        cut = len(fd.get("forcedDrops") or [])
        reasons_against.append(
            f"Roster full — {_plural(cut, 'cut')} required" + (f": likely {names}" if names else "")
        )
    return reasons_for, reasons_against


def _context_reasons(
    posture: DimensionResult,
    counterparty: DimensionResult,
    basis: str,
    market: DimensionResult,
    roster: DimensionResult,
) -> tuple[list[str], list[str]]:
    """Team-context lines that name WHY context mattered, never new votes."""
    reasons_for: list[str] = []
    reasons_against: list[str] = []
    if posture.available:
        sel = (posture.detail or {}).get("selected") or {}
        label = sel.get("posture")
        if "+posture_weighting:" in basis:
            weighed = "current-season lineup impact" if label == "PUSH" else "long-term value"
            line = (
                f"Team direction {label} ({str(sel.get('confidence') or '').lower()} "
                f"confidence): with market and roster split, {weighed} carries the call"
            )
            followed = (
                roster
                if basis.split("+posture_weighting:")[1].split("+")[0].endswith("->rosterUtility")
                else market
            )
            (reasons_for if followed.direction == "favors" else reasons_against).append(line)
        marginal = sel.get("marginal") or {}
        before, after = marginal.get("postureBefore"), marginal.get("postureAfter")
        if marginal.get("available") and before and after and before != after:
            reasons_against.append(
                f"Shifts your team's direction {before} → {after} (lineup-strength basis)"
            )
    if counterparty.available:
        d = counterparty.detail or {}
        team = (d.get("team") or {}).get("name") or "They"
        if d.get("state") in ("cut_required", "worsens_overage"):
            names = ", ".join(str(x.get("name")) for x in d.get("forcedDrops") or [])
            reasons_against.append(
                f"{team} would have to cut {len(d.get('forcedDrops') or [])}"
                + (f" ({names})" if names else "")
                + " to fit this — harder for them to accept"
            )
        elif d.get("state") in ("resolves_overage", "reduces_overage"):
            reasons_for.append(f"{team} gets back toward their roster limit — easier to accept")
    return reasons_for, reasons_against


def _uncertainty(
    market: DimensionResult,
    roster: DimensionResult,
    feasibility: DimensionResult,
    evidence: DimensionResult,
    team_context: bool,
) -> list[str]:
    out: list[str] = []
    if team_context:
        cov = (roster.detail or {}).get("coverage") or {}
        if cov.get("state") == "partial":
            n = len(cov.get("tradedUnprojectedPlayerIds") or [])
            out.append(
                f"No league-scored projection for {n} traded player(s) — the roster lens "
                "abstains rather than count them as zero"
            )
        elif not roster.available and roster.unavailable_reason:
            out.append(f"Roster impact not available ({roster.unavailable_reason})")
        if (feasibility.detail or {}).get("candidatesTied"):
            out.append("Several cut candidates cost about the same; the likely cut is not certain")
        if feasibility.unavailable_reason == "uncertain":
            out.append("Taxi occupancy is unknown, so the forced-cut count is a range")
        cleanup = (roster.detail or {}).get("cleanup") or {}
        if cleanup.get("state") == "uncertain":
            out.append("Roster impact is shown before cleanup because the cut set is uncertain")
    ev = evidence.detail or {}
    if ev.get("lowConfidenceAssets"):
        names = ", ".join(str(a["name"]) for a in ev["lowConfidenceAssets"])
        out.append(f"Low-confidence canonical value for {names}")
    if ev.get("sourceDisagreementAssets"):
        out.append(
            "Sources disagree on " + ", ".join(str(n) for n in ev["sourceDisagreementAssets"])
        )
    unresolved = [
        *((market.detail or {}).get("unresolvedIn") or []),
        *((market.detail or {}).get("unresolvedOut") or []),
    ]
    if unresolved:
        out.append("Not on the board, so not priced: " + ", ".join(unresolved))
    hypothetical = (market.detail or {}).get("hypotheticalPicksOut") or []
    if hypothetical:
        out.append(
            "Counted as sent, but not taken off this roster because no specific "
            "owned pick was chosen: " + ", ".join(hypothetical)
        )
    not_owned = (market.detail or {}).get("notOwnedBySender") or []
    if not_owned:
        out.append(
            "Not held by this team, so not counted as sent: "
            + ", ".join(
                f"{c['label']} (held by {c['actualOwnerName']})"
                if c.get("actualOwnerName")
                else c["label"]
                for c in not_owned
            )
        )
    return out


@dataclass
class AnalyzeTradeResult:
    recommendation: str
    confidence: str
    basis: str
    reasons_for: list[str]
    reasons_against: list[str]
    uncertainty: list[str]
    dimensions: list[DimensionResult]
    unavailable_dimensions: list[dict[str, str]]
    team_context: dict[str, Any]
    context_effect: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        by_name = {d.name: d.to_dict() for d in self.dimensions}
        return {
            "version": PACKET_VERSION,
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "basis": self.basis,
            "teamContext": self.team_context,
            "contextEffect": self.context_effect,
            "reasonsFor": self.reasons_for,
            "reasonsAgainst": self.reasons_against,
            "uncertainty": self.uncertainty,
            "topUncertainty": self.uncertainty[0] if self.uncertainty else None,
            "lenses": {
                "market": by_name.get("equity"),
                "roster": by_name.get("rosterUtility"),
                "feasibility": by_name.get("feasibility"),
                "evidence": by_name.get("evidence"),
                "posture": by_name.get("posture"),
                "counterpartyFeasibility": by_name.get("counterpartyFeasibility"),
            },
            "dimensions": [d.to_dict() for d in self.dimensions],
            "unavailableDimensions": list(self.unavailable_dimensions),
        }


def _excluded_by_mode(name: str, lineage: str) -> DimensionResult:
    return DimensionResult(
        name=name,
        available=False,
        unavailable_reason="asset_only_mode",
        lineage=lineage,
        detail={"note": "not included in Asset-Only analysis"},
    )


def _context_effect(
    market: DimensionResult,
    roster: DimensionResult,
    feasibility: DimensionResult,
    posture: DimensionResult,
    final: str,
    team_context: bool,
) -> dict[str, Any]:
    """The Asset-Only answer beside the Team-Context one, and what moved it.

    Rebuilt by adding ONE context dimension at a time to the market-only rule
    table, so "changed because of team context" names the dimension rather
    than a black box.  OFF mode: both are the same answer by construction.
    """
    off = _excluded_by_mode("rosterUtility", LINEAGE_PROJECTION)
    off_f = _excluded_by_mode("feasibility", LINEAGE_ROSTER_RULES)
    asset_only, _c, _b = _recommend(market, off, off_f)
    if not team_context:
        return {
            "assetOnlyRecommendation": asset_only,
            "teamContextRecommendation": None,
            "changed": False,
            "changedBy": [],
            "note": "Team Context is OFF: this verdict is the Asset-Only Analysis.",
        }
    steps = [
        ("rosterUtility", _recommend(market, roster, off_f)[0]),
        ("feasibility", _recommend(market, roster, feasibility)[0]),
        ("posture", _recommend(market, roster, feasibility, posture)[0]),
    ]
    changed_by: list[dict[str, str]] = []
    prev = asset_only
    for name, rec in steps:
        if rec != prev:
            changed_by.append({"dimension": name, "from": prev, "to": rec})
        prev = rec
    return {
        "assetOnlyRecommendation": asset_only,
        "teamContextRecommendation": final,
        "changed": final != asset_only,
        "changedBy": changed_by,
        "note": (
            "Raw value alone (canonical values + KTC Value Adjustment) gives the "
            "Asset-Only answer; each changedBy step is a team-context dimension."
        ),
    }


def analyze_trade(simulation: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one Analyze Trade packet from a ``simulate_trade`` payload.

    Pure composition over fields the simulation already carries
    (``receiving`` / ``sending`` / ``rosterCapacity`` / ``rosterUtility`` /
    ``finalRosterSimulation`` / ``counterparty`` / ``posture`` /
    ``teamContext``).  Computes no canonical value and calls no engine the
    simulation did not already call.
    """
    cfg = _config()
    team_context_block = dict(simulation.get("teamContext") or {"applied": True, "mode": "team"})
    team_context = team_context_block.get("applied") is not False

    market = _market_lens(simulation)
    if team_context:
        roster = _roster_lens(simulation, cfg)
        feasibility = _feasibility_lens(simulation)
        posture = _posture_lens(simulation)
        counterparty = _counterparty_feasibility(simulation)
    else:
        roster = _excluded_by_mode("rosterUtility", LINEAGE_PROJECTION)
        feasibility = _excluded_by_mode("feasibility", LINEAGE_ROSTER_RULES)
        posture = _excluded_by_mode("posture", "playoff_odds+lineup_strength+age")
        posture.votes = False
        counterparty = _excluded_by_mode("counterpartyFeasibility", LINEAGE_ROSTER_RULES)
        counterparty.votes = False
    evidence = _evidence_lens(simulation, roster)

    recommendation, confidence, basis = _recommend(market, roster, feasibility, posture)
    reasons_for, reasons_against = _reasons(market, roster, feasibility, cfg)
    ctx_for, ctx_against = _context_reasons(posture, counterparty, basis, market, roster)
    reasons_for.extend(ctx_for)
    reasons_against.extend(ctx_against)
    uncertainty = _uncertainty(market, roster, feasibility, evidence, team_context)
    if team_context and posture.available:
        sel = (posture.detail or {}).get("selected") or {}
        if sel.get("confidence") == "LOW":
            uncertainty.append(
                f"Team direction is unclear ({sel.get('posture')}, low confidence) — it is "
                "not used to break a market/roster split"
            )
    if confidence == "HIGH" and uncertainty:
        # Agreement between two lenses does not survive a named gap in the
        # evidence behind them.
        confidence = "MEDIUM"

    team_context_block["applied"] = team_context
    team_context_block["mode"] = "team" if team_context else "asset_only"
    team_context_block.setdefault(
        "label", "Team Context" if team_context else "Asset-Only Analysis"
    )

    return AnalyzeTradeResult(
        recommendation=recommendation,
        confidence=confidence,
        basis=basis,
        reasons_for=reasons_for,
        reasons_against=reasons_against,
        uncertainty=uncertainty,
        dimensions=[market, roster, feasibility, evidence, posture, counterparty],
        unavailable_dimensions=list(_UNAVAILABLE_DIMENSIONS),
        team_context=team_context_block,
        context_effect=_context_effect(
            market, roster, feasibility, posture, recommendation, team_context
        ),
    ).to_dict()
