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
* **strategicPosture** — Competitive Posture (#840 / C7-POST-01) from its
  canonical owner (``src.roster_intel.window.competitive_posture``).  CONTEXT,
  NEVER votes: it interprets the same evidence the roster lens and the playoff
  odds already carry, so a vote would count it twice; and the owner decision
  says posture is never a veto.  Excluded by mode under Asset-Only.
* **currentSeasonEquity** — named UNAVAILABLE: the playoff simulator's trade
  counterfactual (``playoff_sim.simulate_trade_impact``) takes a weekly-mean
  shift only and is not wired.  Unavailable is not neutral and is never read
  as zero.

Use Team Context (#842)
───────────────────────
``simulation["teamContext"]["applied"] is False`` → Asset-Only: the roster and
feasibility lenses are excluded BY MODE (and say so), the recommendation comes
from the market lens alone, and no asset value changes.  One contract with a
dimension switched off — not a second formula.

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

#: What each dimension may do to the decision (methodology:
#: ``docs/trade/ANALYZE_TRADE_V3_METHODOLOGY.md``).  Only VOTE dimensions set
#: the direction; a MODIFIER may step the decision or cap confidence on
#: evidence the votes do not carry; CONTEXT explains and never moves it.
ROLE_VOTE = "vote"
ROLE_MODIFIER = "modifier"
ROLE_CONTEXT = "context"

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade" / "analyze_trade.json"
_DEFAULTS = {"materialityPpg": 1.0, "largeMultiple": 3.0, "depthNotableLossPpg": 0.5}

#: Lineage tags: two lenses sharing one may not both vote.
LINEAGE_CANONICAL_VALUE = "canonical_value"
LINEAGE_PROJECTION = "league_scored_projection"
LINEAGE_ROSTER_RULES = "league_roster_rules"
#: Competitive Posture is an INTERPRETATION of evidence other lenses already
#: carry (playoff odds, Team Strength, age-value) — context, never a vote.
LINEAGE_TEAM_STRATEGY = "team_strategy_context"
#: KTC's own published Crowd+Trades price (``src.sources.ktc_market``).  A
#: BENCHMARK of two families that already vote inside canonical value, so it
#: can only corroborate or dispute, never vote.
LINEAGE_MARKET_BENCHMARK = "ktc_market_benchmark"
LINEAGE_COMPLETED_TRADES = "completed_trade_ledger"
LINEAGE_AGE = "canonical_age"
LINEAGE_PICK_OWNERSHIP = "league_pick_ownership"

#: Dimensions this depth deliberately does not compute, named so "not
#: included" and "computed and found neutral" never look the same.
_UNAVAILABLE_DIMENSIONS = (
    {
        "dimension": "currentSeasonEquity",
        "reason": "counterfactual_not_wired",
        "notes": "src.ros.playoff_sim.simulate_trade_impact (paired seeds) is not yet fed "
        "a roster counterfactual for this request; playoff / bye / title deltas are shown "
        "only once that wiring lands, never estimated here.",
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


# ── v3 sections: modifiers and context (#792 Batch 4) ────────────────────
#
# Each reads a field the simulation already carries.  None of them computes a
# canonical value, and none of them votes: a modifier may cap confidence or
# step the decision once on evidence the two votes do not carry; context only
# explains.  Methodology and lineage map:
# ``docs/trade/ANALYZE_TRADE_V3_METHODOLOGY.md``.

_V3_DEFAULTS = {
    "lowConfidenceShareMedium": 0.25,
    "lowConfidenceShareLow": 0.5,
    "benchmarkCoverageMin": 0.5,
    "agingAge": 28.0,
    "agingShareMin": 0.5,
    "titleDeltaMaterialPp": 2.0,
}


def _v3_config() -> dict[str, float]:
    try:
        raw = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
        block = raw.get("decision") or {}
        return {k: float(block.get(k, v)) for k, v in _V3_DEFAULTS.items()}
    except (OSError, ValueError, TypeError):
        return dict(_V3_DEFAULTS)


def _num(x: Any) -> float | None:
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _traded(simulation: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    return [("in", a) for a in simulation.get("receiving") or [] if isinstance(a, dict)] + [
        ("out", a) for a in simulation.get("sending") or [] if isinstance(a, dict)
    ]


def _market_corroboration(simulation: dict[str, Any], equity: DimensionResult) -> DimensionResult:
    """KTC Market benchmark + completed-trade comparables: do they agree with
    the canonical direction?

    Both are DESCENDANTS of evidence canonical value already counts (KTC Crowd
    and KTC Trades vote inside it; comparables are what those markets did), so
    this never votes.  Disagreement lowers confidence and is named; it never
    flips the direction.  BROAD_CONTEXT comparables carry no price authority
    (their owner zeroes it) and are shown only as context.
    """
    priced = [(side, a) for side, a in _traded(simulation) if _num(a.get("value")) is not None]
    total = sum(float(a["value"]) for _, a in priced)
    bench = [(side, a) for side, a in priced if _num(a.get("ktcMarketValue")) is not None]
    covered = sum(float(a["value"]) for _, a in bench)
    coverage = (covered / total) if total > 0 else None
    comps = simulation.get("marketComparables")
    comps_block = comps if isinstance(comps, dict) else None
    lineage = [LINEAGE_MARKET_BENCHMARK, LINEAGE_COMPLETED_TRADES]
    if not bench and not (comps_block and comps_block.get("state") == "ok"):
        return DimensionResult(
            name="marketCorroboration",
            available=False,
            unavailable_reason=(
                "no_market_benchmark_for_traded_assets" if priced else "no_priced_assets"
            ),
            votes=False,
            lineage=LINEAGE_MARKET_BENCHMARK,
            detail={
                "role": ROLE_MODIFIER,
                "lineageAll": lineage,
                "comparables": comps_block
                or {"state": "unavailable", "reason": "comparables_not_wired"},
            },
        )
    recv_b = sum(float(a["ktcMarketValue"]) for side, a in bench if side == "in")
    send_b = sum(float(a["ktcMarketValue"]) for side, a in bench if side == "out")
    bench_gap = recv_b - send_b
    bench_mag = _fairness_label(int(round(bench_gap)))
    bench_dir = "neutral" if bench_mag == "even" else _direction(bench_gap)
    canon_dir = equity.direction if equity.available else None
    if canon_dir is None or bench_dir == "neutral" or canon_dir == "neutral":
        agreement = "inconclusive"
    elif bench_dir == canon_dir:
        agreement = "agrees"
    else:
        agreement = "disagrees"
    comp_dir = (comps_block or {}).get("marketDirection")
    return DimensionResult(
        name="marketCorroboration",
        available=True,
        direction=agreement,
        votes=False,
        lineage=LINEAGE_MARKET_BENCHMARK,
        detail={
            "role": ROLE_MODIFIER,
            "lineageAll": lineage,
            "benchmark": "KTC Market (KTC's published Crowd+Trades) — benchmark only, never a vote",
            "benchmarkReceiving": int(round(recv_b)),
            "benchmarkSending": int(round(send_b)),
            "benchmarkGap": int(round(bench_gap)),
            "benchmarkMagnitude": bench_mag,
            "benchmarkDirection": bench_dir,
            "agreement": agreement,
            "coverage": round(coverage, 3) if coverage is not None else None,
            "assetsWithoutBenchmark": [
                str(a.get("name")) for _, a in priced if _num(a.get("ktcMarketValue")) is None
            ],
            "comparables": comps_block
            or {"state": "unavailable", "reason": "comparables_not_wired"},
            "comparablesDirection": comp_dir,
            "note": "Gap is raw benchmark value (no package adjustment); it corroborates or "
            "disputes the canonical direction and cannot change it.",
        },
    )


def _value_uncertainty(simulation: dict[str, Any], cfg3: dict[str, float]) -> DimensionResult:
    """How sure is the VALUE conclusion?  From the canonical confidence owner's
    per-asset stamps (``src/api/confidence.py``), weighted by traded value.

    Monte Carlo is NOT read: its bands are centred on the same canonical p50,
    so counting it would vote the value twice.
    """
    priced = [a for _, a in _traded(simulation) if _num(a.get("value")) is not None]
    total = sum(float(a["value"]) for a in priced)
    if total <= 0:
        return DimensionResult(
            name="valueUncertainty",
            available=False,
            unavailable_reason="no_priced_assets",
            votes=False,
            lineage=LINEAGE_CANONICAL_VALUE,
            detail={"role": ROLE_MODIFIER},
        )
    low = sum(float(a["value"]) for a in priced if a.get("confidenceBucket") == "low")
    unstamped = sum(float(a["value"]) for a in priced if a.get("confidenceBucket") is None)
    disagree = sum(float(a["value"]) for a in priced if a.get("hasSourceDisagreement") is True)
    low_share = low / total
    unstamped_share = unstamped / total
    if low_share >= cfg3["lowConfidenceShareLow"]:
        cap, cap_reason = "LOW", f"{low_share:.0%} of traded value is low-confidence"
    elif low_share >= cfg3["lowConfidenceShareMedium"]:
        cap, cap_reason = "MEDIUM", f"{low_share:.0%} of traded value is low-confidence"
    elif unstamped_share >= 0.5:
        # An asset with no confidence stamp is UNKNOWN confidence, not high.
        cap, cap_reason = "MEDIUM", f"{unstamped_share:.0%} of traded value has no confidence stamp"
    else:
        cap, cap_reason = None, None
    return DimensionResult(
        name="valueUncertainty",
        available=True,
        direction="context",
        votes=False,
        lineage=LINEAGE_CANONICAL_VALUE,
        detail={
            "role": ROLE_MODIFIER,
            "lowConfidenceValueShare": round(low_share, 3),
            "unstampedValueShare": round(unstamped_share, 3),
            "sourceDisagreementValueShare": round(disagree / total, 3),
            "confidenceCap": cap,
            "confidenceCapReason": cap_reason,
            "monteCarlo": "not counted: centred on the same canonical value",
        },
    )


def _final_roster_section(simulation: dict[str, Any]) -> dict[str, Any] | None:
    """What the FINAL LEGAL roster looks like (``finalRosterSimulation``):
    needs fixed / created, promotions, displacements, cleanup.  Reported, not
    voted — the roster vote is the best-ball utility on this same roster."""
    frs = simulation.get("finalRosterSimulation")
    if not isinstance(frs, dict) or frs.get("available", True) is not True:
        return None

    def _names(rows: Any) -> list[dict[str, Any]]:
        return [
            {
                "name": r.get("canonicalName") or r.get("playerId"),
                "position": r.get("position"),
                "slotBefore": r.get("slotBefore"),
                "slotAfter": r.get("slotAfter"),
            }
            for r in rows or []
            if isinstance(r, dict)
        ]

    def _urgent(w: Any) -> list[str] | None:
        if not isinstance(w, dict):
            return None
        urgent = w.get("urgentPositions")
        return list(urgent) if isinstance(urgent, list) else None

    return {
        "needsFixed": list(frs.get("needsFixed") or []),
        "needsCreated": list(frs.get("needsCreated") or []),
        "weaknessMeasured": isinstance(frs.get("weaknessBefore"), dict)
        and isinstance(frs.get("weaknessAfter"), dict),
        "urgentBefore": _urgent(frs.get("weaknessBefore")),
        "urgentAfter": _urgent(frs.get("weaknessAfter")),
        "promotions": _names(frs.get("promotions")),
        "displacements": _names(frs.get("displacements")),
        "cleanupApplied": [
            {"name": d.get("name"), "position": d.get("position")}
            for d in frs.get("cleanupApplied") or []
            if isinstance(d, dict)
        ],
        "cleanupIsUpperBound": bool(frs.get("cleanupIsUpperBound")),
        "unpricedIncoming": list(frs.get("unpricedIncoming") or []),
    }


def _age_window(simulation: dict[str, Any], cfg3: dict[str, float]) -> DimensionResult:
    """Age / dynasty window, from the canonical age-value owner
    (``roster_intel.age_portfolio``) on the final legal core, plus the ages
    of the traded assets.  CONTEXT: canonical value already prices age, so
    this explains the window effect and never feeds value back."""
    frs = simulation.get("finalRosterSimulation") or {}
    before = frs.get("agePortfolioBefore") if isinstance(frs, dict) else None
    after = frs.get("agePortfolioAfter") if isinstance(frs, dict) else None

    def _vw_age(side: str) -> tuple[float | None, float]:
        rows = [
            a
            for s_, a in _traded(simulation)
            if s_ == side and _num(a.get("age")) is not None and _num(a.get("value")) is not None
        ]
        tot = sum(float(a["value"]) for a in rows)
        if tot <= 0:
            return None, 0.0
        aging = sum(float(a["value"]) for a in rows if float(a["age"]) >= cfg3["agingAge"])
        return sum(float(a["age"]) * float(a["value"]) for a in rows) / tot, aging / tot

    in_age, in_aging = _vw_age("in")
    out_age, out_aging = _vw_age("out")
    have_portfolio = isinstance(before, dict) and isinstance(after, dict)
    if not have_portfolio and in_age is None and out_age is None:
        return DimensionResult(
            name="ageWindow",
            available=False,
            unavailable_reason="no_age_evidence",
            votes=False,
            lineage=LINEAGE_AGE,
            detail={"role": ROLE_CONTEXT},
        )

    def _pick(block: Any, key: str) -> Any:
        return block.get(key) if isinstance(block, dict) else None

    core_b = _num(_pick(before, "valueWeightedCoreAge"))
    core_a = _num(_pick(after, "valueWeightedCoreAge"))
    youth_b = _num(_pick(before, "coreYouthScore"))
    youth_a = _num(_pick(after, "coreYouthScore"))
    return DimensionResult(
        name="ageWindow",
        available=True,
        direction="context",
        votes=False,
        lineage=LINEAGE_AGE,
        detail={
            "role": ROLE_CONTEXT,
            "coreAgeBefore": core_b,
            "coreAgeAfter": core_a,
            "coreAgeDelta": round(core_a - core_b, 2)
            if core_a is not None and core_b is not None
            else None,
            "coreYouthBefore": youth_b,
            "coreYouthAfter": youth_a,
            "incomingValueWeightedAge": round(in_age, 1) if in_age is not None else None,
            "outgoingValueWeightedAge": round(out_age, 1) if out_age is not None else None,
            "incomingAgingValueShare": round(in_aging, 3) if in_age is not None else None,
            "outgoingAgingValueShare": round(out_aging, 3) if out_age is not None else None,
            "agingAge": cfg3["agingAge"],
            "portfolioMeasured": have_portfolio,
            "note": "Canonical value already prices age; this is the window effect, "
            "never fed back into value.",
        },
    )


def _season_equity(simulation: dict[str, Any]) -> DimensionResult:
    """Current-season marginal effect (playoffs / bye / title) from the playoff
    simulator's paired-seed counterfactual.  CONTEXT for the posture fit only:
    its weekly-strength input shares the projection lineage the roster vote
    already carries."""
    block = simulation.get("seasonImpact")
    if not isinstance(block, dict) or block.get("available") is not True:
        reason = (
            str(block.get("unavailableReason") or "not_computed")
            if isinstance(block, dict)
            else "counterfactual_not_wired"
        )
        return DimensionResult(
            name="currentSeasonEquity",
            available=False,
            unavailable_reason=reason,
            votes=False,
            lineage=LINEAGE_PROJECTION,
            detail={"role": ROLE_CONTEXT},
        )
    return DimensionResult(
        name="currentSeasonEquity",
        available=True,
        direction="context",
        votes=False,
        lineage=LINEAGE_PROJECTION,
        detail={"role": ROLE_CONTEXT, **{k: v for k, v in block.items() if k != "available"}},
    )


def _draft_capital(simulation: dict[str, Any]) -> DimensionResult:
    """Future draft capital before → after, from the simulation's own pick
    accounting (Wave A ownership).  Slot projections are shown only when the
    canonical Pick Projector supplied them; otherwise the board grade the pick
    was priced at is all that is claimed."""
    picks = [
        (side, a)
        for side, a in _traded(simulation)
        if a.get("assetClass") == "pick" or str(a.get("pos") or "").upper() == "PICK"
    ]
    checks = simulation.get("ownedPickChecks") or {}
    before = ((simulation.get("before") or {}).get("byPosition") or {}).get("PICK") or {}
    after = ((simulation.get("after") or {}).get("byPosition") or {}).get("PICK") or {}
    not_owned = [
        {"label": c.get("label"), "actualOwnerName": c.get("actualOwnerName")}
        for c in checks.get("notOwnedBySender") or []
        if isinstance(c, dict)
    ]
    hypothetical = list(checks.get("hypotheticalPicksOut") or [])
    if not picks and not not_owned and not hypothetical:
        return DimensionResult(
            name="draftCapital",
            available=False,
            unavailable_reason="no_picks_involved",
            votes=False,
            lineage=LINEAGE_PICK_OWNERSHIP,
            detail={"role": ROLE_CONTEXT},
        )
    projection = simulation.get("pickProjection")
    return DimensionResult(
        name="draftCapital",
        available=True,
        direction="context",
        votes=False,
        lineage=LINEAGE_PICK_OWNERSHIP,
        detail={
            "role": ROLE_CONTEXT,
            "acquired": [
                {
                    "label": a.get("sourceLabel") or a.get("name"),
                    "boardGrade": a.get("name"),
                    "value": a.get("value"),
                }
                for side, a in picks
                if side == "in"
            ],
            "lost": [
                {
                    "label": a.get("sourceLabel") or a.get("name"),
                    "boardGrade": a.get("name"),
                    "value": a.get("value"),
                }
                for side, a in picks
                if side == "out"
            ],
            "pickCountBefore": before.get("count"),
            "pickCountAfter": after.get("count"),
            "pickValueBefore": before.get("value"),
            "pickValueAfter": after.get("value"),
            "notOwnedBySender": not_owned,
            "hypotheticalPicksOut": hypothetical,
            "slotProjection": projection
            if isinstance(projection, dict)
            else {"state": "unvalidated", "reason": "pick_projector_not_consumed"},
            "note": "Picks a team does not own are named, never counted; weakening another "
            "roster helps this team only through picks it actually holds.",
        },
    )


def _posture_label(posture: DimensionResult) -> str | None:
    if not posture.available:
        return None
    label = (posture.detail or {}).get("label")
    return str(label) if label in ("PUSH", "HOLD", "RETOOL", "REBUILD") else None


def _strategic_fit(
    posture: DimensionResult,
    equity: DimensionResult,
    age: DimensionResult,
    season: DimensionResult,
    cfg3: dict[str, float],
) -> tuple[int, str | None]:
    """Preregistered strategic-fit MODIFIER: ``(step, reason)``.

    The posture LABEL alone never moves the decision.  A step needs the label
    AND independent evidence for that label's concern, and is at most one:

    * PUSH, giving up canonical value, season evidence present and no material
      title-odds gain → one step toward PASS;
    * PUSH, giving up at most a "lean" of canonical value for a material,
      significant title-odds gain → one step toward MAKE;
    * REBUILD, buying mostly aging value (incoming aging share at or above the
      PRIOR) without a canonical-value edge → one step toward PASS.
    """
    label = _posture_label(posture)
    if label is None:
        return 0, None
    eq_dir = equity.direction if equity.available else None
    eq_mag = (equity.detail or {}).get("magnitude")
    if label == "PUSH" and season.available:
        title = (season.detail or {}).get("titleDeltaPp")
        sig = (season.detail or {}).get("titleSignificant") is True
        if isinstance(title, (int, float)):
            material = sig and title >= cfg3["titleDeltaMaterialPp"]
            if eq_dir == "opposes" and not material:
                return -1, (
                    "Push posture: gives up canonical value for no material title-odds gain "
                    f"({title:+.1f} pp)"
                )
            if eq_dir == "opposes" and eq_mag == "lean" and material:
                return 1, (f"Push posture: a modest value cost buys {title:+.1f} pp of title odds")
    if label == "REBUILD" and age.available:
        share = (age.detail or {}).get("incomingAgingValueShare")
        if (
            isinstance(share, (int, float))
            and share >= cfg3["agingShareMin"]
            and eq_dir in ("neutral", "opposes")
        ):
            return -1, (
                f"Rebuild posture: {share:.0%} of incoming value is age "
                f"{cfg3['agingAge']:.0f}+ without a value edge"
            )
    return 0, None


# ── Synthesis ────────────────────────────────────────────────────────────


def _step(rec: str, delta: int) -> str:
    i = min(max(_STEP[rec] - delta, 0), len(RECOMMENDATIONS) - 1)
    return RECOMMENDATIONS[i]


def _recommend(
    market: DimensionResult, roster: DimensionResult, feasibility: DimensionResult
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
            # things.  "Depends" is the honest answer; the dissent is shown.
            rec, confidence = "TOO_CLOSE", "MEDIUM"
        else:
            rec, confidence = "TOO_CLOSE", "LOW"
        basis = "market_and_roster"

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


#: Owner of each section's evidence, published as provenance.
_PROVENANCE = {
    "canonicalEquity": "src.api.data_contract (rankDerivedValue) + src.trade.ktc_va",
    "marketCorroboration": "src.sources.ktc_market (benchmark) + src.trade.market_comparables",
    "valueUncertainty": "src.api.confidence (per-asset confidenceBucket)",
    "rosterImpact": "src.roster_intel.best_ball_utility + src.trade.roster_capacity",
    "ageWindow": "src.roster_intel.age_portfolio",
    "currentSeasonEquity": "src.ros.playoff_sim.simulate_trade_impact",
    "competitivePosture": "src.roster_intel.window.competitive_posture",
    "draftCapital": "src.identity.picks (ownership) + board pick grades",
    "feasibility": "src.trade.roster_capacity",
}

_ROLE = {
    "canonicalEquity": ROLE_VOTE,
    "marketCorroboration": ROLE_MODIFIER,
    "valueUncertainty": ROLE_MODIFIER,
    "rosterImpact": ROLE_VOTE,
    "ageWindow": ROLE_CONTEXT,
    "currentSeasonEquity": ROLE_CONTEXT,
    "competitivePosture": ROLE_MODIFIER,
    "draftCapital": ROLE_CONTEXT,
    "feasibility": ROLE_MODIFIER,
}

DECISION_LABELS = {
    "MAKE": "Make the trade",
    "LEAN_MAKE": "Lean make",
    "TOO_CLOSE": "Too close / depends",
    "LEAN_PASS": "Lean pass",
    "PASS": "Pass",
}


def _section(key: str, d: DimensionResult, *, freshness: Any) -> dict[str, Any]:
    """One uniform section: the same fields for every dimension, so "not
    computed", "computed and neutral" and "context only" never look alike."""
    detail = d.detail or {}
    coverage = detail.get("coverage")
    out: dict[str, Any] = {
        "key": key,
        "available": d.available,
        "role": _ROLE[key],
        "lineage": d.lineage,
        "direction": d.direction if d.available else None,
        "magnitude": detail.get("magnitude"),
        "coverage": coverage,
        "freshness": freshness,
        "provenance": _PROVENANCE[key],
        "detail": detail,
    }
    if not d.available:
        out["unavailableReason"] = d.unavailable_reason
    return out


@dataclass
class AnalyzeTradeResult:
    recommendation: str
    confidence: str
    confidence_reasons: list[str]
    basis: str
    reasons_for: list[str]
    reasons_against: list[str]
    uncertainty: list[str]
    dimensions: list[DimensionResult]
    unavailable_dimensions: list[dict[str, str]]
    team_context: dict[str, Any]
    sections: dict[str, Any] = field(default_factory=dict)
    posture_label: str | None = None
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        by_name = {d.name: d.to_dict() for d in self.dimensions}
        return {
            "version": PACKET_VERSION,
            # v3 headline (#792 Batch 4).
            "decision": self.recommendation,
            "decisionLabel": DECISION_LABELS[self.recommendation],
            "confidenceDetail": {"level": self.confidence, "reasons": self.confidence_reasons},
            "competitivePosture": self.posture_label,
            "summary": self.summary,
            "strongestReasonsFor": self.reasons_for[:5],
            "strongestReasonsAgainst": self.reasons_against[:5],
            "keyUncertainty": self.uncertainty[0] if self.uncertainty else None,
            "sections": self.sections,
            # v2 keys, unchanged, for existing consumers.
            "recommendation": self.recommendation,
            "confidence": self.confidence,
            "basis": self.basis,
            "teamContext": self.team_context,
            "reasonsFor": self.reasons_for,
            "reasonsAgainst": self.reasons_against,
            "uncertainty": self.uncertainty,
            "topUncertainty": self.uncertainty[0] if self.uncertainty else None,
            "lenses": {
                "market": by_name.get("equity"),
                "roster": by_name.get("rosterUtility"),
                "feasibility": by_name.get("feasibility"),
                "evidence": by_name.get("evidence"),
                "posture": by_name.get("strategicPosture"),
            },
            "dimensions": [d.to_dict() for d in self.dimensions],
            "unavailableDimensions": list(self.unavailable_dimensions),
        }


def _posture_lens(simulation: dict[str, Any]) -> DimensionResult:
    """Competitive Posture (#840 / C7-POST-01) as CONTEXT, never a vote.

    The owner (``src.roster_intel.window.competitive_posture``) publishes
    PUSH / HOLD / RETOOL / REBUILD as an explained probabilistic
    classification.  Owner decision 2026-09-24: posture is context, never an
    automatic veto, and Analyze Trade weighs the underlying evidence rather
    than the label.  It is derived from the same lineage the roster lens and
    the playoff odds carry, so letting it vote would count that evidence
    twice.  ``votes=False`` makes that structural: ``_recommend`` reads only
    market / roster / feasibility.
    """
    block = simulation.get("competitivePosture")
    if not isinstance(block, dict) or not block.get("available"):
        reason = (block or {}).get("unavailableReason") if isinstance(block, dict) else None
        return DimensionResult(
            name="strategicPosture",
            available=False,
            unavailable_reason=reason or "not_computed",
            votes=False,
            lineage=LINEAGE_TEAM_STRATEGY,
        )
    impact = simulation.get("teamImpact") or {}
    detail = {
        "label": block.get("label"),
        "evidence": block.get("evidence"),
        "probabilities": block.get("probabilities"),
        "confidence": block.get("confidence"),
        "components": block.get("components"),
        "paramsVersion": block.get("paramsVersion"),
        "parameterStatus": block.get("parameterStatus"),
        # How the moving assets line up with the posture (team_impact's window
        # fit, weighted by the posture probabilities).  Reported, not voted.
        "windowFit": impact.get("windowFit"),
        "role": "context_not_vote",
        "notes": block.get("notes") or [],
    }
    return DimensionResult(
        name="strategicPosture",
        available=True,
        direction="context",
        detail=detail,
        votes=False,
        lineage=LINEAGE_TEAM_STRATEGY,
    )


def _excluded_by_mode(name: str, lineage: str) -> DimensionResult:
    return DimensionResult(
        name=name,
        available=False,
        unavailable_reason="asset_only_mode",
        lineage=lineage,
        detail={"note": "not included in Asset-Only analysis"},
    )


def _cap(level: str, cap: str | None) -> str:
    order = ("LOW", "MEDIUM", "HIGH")
    if cap is None:
        return level
    return order[min(order.index(level), order.index(cap))]


def _summary(rec: str, reasons_for: list[str], reasons_against: list[str]) -> str:
    lead = DECISION_LABELS[rec]
    if rec in ("MAKE", "LEAN_MAKE"):
        first = reasons_for[:1] + reasons_against[:1]
    elif rec in ("PASS", "LEAN_PASS"):
        first = reasons_against[:1] + reasons_for[:1]
    else:
        first = reasons_for[:1] + reasons_against[:1]
    return lead + (": " + "; ".join(first) if first else "")


def analyze_trade(simulation: dict[str, Any]) -> dict[str, Any]:
    """Synthesize one Analyze Trade packet from a ``simulate_trade`` payload.

    Pure composition over fields the simulation already carries
    (``receiving`` / ``sending`` / ``rosterCapacity`` / ``rosterUtility`` /
    ``finalRosterSimulation`` / ``teamContext`` / ``competitivePosture`` /
    ``ownedPickChecks`` and, when wired, ``marketComparables`` /
    ``seasonImpact``).  Computes no canonical value and calls no engine the
    simulation did not already call.
    """
    cfg = _config()
    cfg3 = _v3_config()
    team_context_block = simulation.get("teamContext") or {"applied": True, "mode": "team"}
    team_context = team_context_block.get("applied") is not False

    market = _market_lens(simulation)
    if team_context:
        roster = _roster_lens(simulation, cfg)
        feasibility = _feasibility_lens(simulation)
        posture = _posture_lens(simulation)
        age = _age_window(simulation, cfg3)
        season = _season_equity(simulation)
    else:
        roster = _excluded_by_mode("rosterUtility", LINEAGE_PROJECTION)
        feasibility = _excluded_by_mode("feasibility", LINEAGE_ROSTER_RULES)
        posture = _excluded_by_mode("strategicPosture", LINEAGE_TEAM_STRATEGY)
        posture.votes = False
        age = _excluded_by_mode("ageWindow", LINEAGE_AGE)
        age.votes = False
        season = _excluded_by_mode("currentSeasonEquity", LINEAGE_PROJECTION)
        season.votes = False
    evidence = _evidence_lens(simulation, roster)
    corroboration = _market_corroboration(simulation, market)
    value_unc = _value_uncertainty(simulation, cfg3)
    draft = _draft_capital(simulation)

    recommendation, confidence, basis = _recommend(market, roster, feasibility)
    reasons_for, reasons_against = _reasons(market, roster, feasibility, cfg)
    uncertainty = _uncertainty(market, roster, feasibility, evidence, team_context)
    confidence_reasons: list[str] = []

    # Strategic fit (preregistered MODIFIER): label + independent evidence,
    # at most one step.  The label alone never moves anything.
    step, fit_reason = (
        _strategic_fit(posture, market, age, season, cfg3) if team_context else (0, None)
    )
    if step:
        recommendation = _step(recommendation, step)
        basis += f"+strategicFit:{'toward_make' if step > 0 else 'toward_pass'}"
        (reasons_for if step > 0 else reasons_against).append(str(fit_reason))

    if confidence == "HIGH" and uncertainty:
        # Agreement between two lenses does not survive a named gap in the
        # evidence behind them.
        confidence = "MEDIUM"
        confidence_reasons.append("named evidence gaps")

    if (
        corroboration.available
        and corroboration.direction == "disagrees"
        and isinstance((corroboration.detail or {}).get("coverage"), (int, float))
        and corroboration.detail["coverage"] >= cfg3["benchmarkCoverageMin"]
    ):
        confidence = _cap(confidence, "MEDIUM")
        confidence_reasons.append("market benchmark points the other way")
        uncertainty.append(
            "KTC Market benchmark leans the other way "
            f"({corroboration.detail['benchmarkGap']:+,} raw) — shown, not counted"
        )
    vcap = (value_unc.detail or {}).get("confidenceCap") if value_unc.available else None
    if vcap:
        before_cap = confidence
        confidence = _cap(confidence, vcap)
        if confidence != before_cap:
            confidence_reasons.append(str(value_unc.detail["confidenceCapReason"]))
    if not roster.available or not market.available:
        confidence_reasons.append("one primary dimension unavailable")
    if not confidence_reasons:
        confidence_reasons.append("both primary dimensions available and consistent")

    freshness = {"boardAsOf": simulation.get("boardAsOf")}
    roster_section = _section("rosterImpact", roster, freshness=freshness)
    roster_section["finalRoster"] = _final_roster_section(simulation)
    sections = {
        "canonicalEquity": _section("canonicalEquity", market, freshness=freshness),
        "marketCorroboration": _section("marketCorroboration", corroboration, freshness=freshness),
        "valueUncertainty": _section("valueUncertainty", value_unc, freshness=freshness),
        "rosterImpact": roster_section,
        "ageWindow": _section("ageWindow", age, freshness=freshness),
        "currentSeasonEquity": _section("currentSeasonEquity", season, freshness=freshness),
        "competitivePosture": {
            **_section("competitivePosture", posture, freshness=freshness),
            "strategicFit": {"step": step, "reason": fit_reason},
        },
        "draftCapital": _section("draftCapital", draft, freshness=freshness),
        "feasibility": _section("feasibility", feasibility, freshness=freshness),
    }

    return AnalyzeTradeResult(
        recommendation=recommendation,
        confidence=confidence,
        confidence_reasons=confidence_reasons,
        basis=basis,
        reasons_for=reasons_for,
        reasons_against=reasons_against,
        uncertainty=uncertainty,
        dimensions=[market, roster, feasibility, evidence, posture],
        unavailable_dimensions=[
            d
            for d in _UNAVAILABLE_DIMENSIONS
            if not (season.available and d["dimension"] == "currentSeasonEquity")
        ],
        team_context={
            "applied": team_context,
            "mode": "team" if team_context else "asset_only",
        },
        sections=sections,
        posture_label=_posture_label(posture) if team_context else None,
        summary=_summary(recommendation, reasons_for, reasons_against),
    ).to_dict()
