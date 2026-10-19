"""Confidence: a LABEL from the weakest axis.  ``isProbability`` is false.

Axes (fixed order, which also breaks bottleneck ties): coverage, margin,
agreement, asset_evidence, mc_precision, predictive_basis, freshness,
overlap_guard.  Nothing averages, so no axis can buy another.

Load-bearing rules:

* **agreement** is capped at MEDIUM whenever the voting groups carry a
  declared partial overlap (``src.evidence_lineage.registry.PARTIAL_OVERLAPS``):
  the market term and the lineup term share current-season production, so
  their agreement is never corroboration -- on EVERY trade where both vote.
* **mc_precision** reads the Monte-Carlo standard error as PRECISION of the
  estimate only; it is never turned into a probability.
* **predictive_basis**: a prior / proxy predictive distribution caps at
  MEDIUM; ``unavailable`` caps at MEDIUM for a verdict the P term decided.
* **overlap_guard**: VA and the lineup term pointing the same way caps at
  MEDIUM (``va_roster_overlap``).
* Competitive posture is context, never an axis.
"""

from __future__ import annotations

from typing import Any, Mapping

from src.trade.decision_engine.contracts import CONFIDENCE_LEVELS, TermResult

AXES = (
    "coverage",
    "margin",
    "agreement",
    "asset_evidence",
    "mc_precision",
    "predictive_basis",
    "freshness",
    "overlap_guard",
)
_RANK = {lvl: i for i, lvl in enumerate(CONFIDENCE_LEVELS)}


def va_relation(asset: Mapping[str, Any], p: TermResult | None) -> str | None:
    """How the package VA relates to the voting lineup term for THIS team.

    ``aligned`` (both point the same way for this team), ``opposed`` (the VA
    consolidation premium points one way and the lineup term the other) or
    ``None`` (no VA, or no voting lineup term).
    """
    if p is None or p.term != "C" or p.direction not in ("favours", "opposes"):
        return None
    recv_va = asset.get("recvVa") if isinstance(asset, Mapping) else None
    send_va = asset.get("sendVa") if isinstance(asset, Mapping) else None
    recv = recv_va if isinstance(recv_va, (int, float)) and not isinstance(recv_va, bool) else None
    send = send_va if isinstance(send_va, (int, float)) and not isinstance(send_va, bool) else None
    if recv is not None and recv > 0:
        va_for_team = True
    elif send is not None and send > 0:
        va_for_team = False
    else:
        return None
    c_for_team = p.direction == "favours"
    return "aligned" if va_for_team == c_for_team else "opposed"


def assess(
    *,
    insufficient: bool,
    raw_verdict: str | None,
    decided_by: str | None,
    a: TermResult,
    p: TermResult | None,
    p_required: bool,
    agreement_cap: str | None,
    asset: Mapping[str, Any],
    asset_detail: Mapping[str, Any],
    freshness: Mapping[str, str],
    params: Mapping[str, Any],
) -> dict[str, Any]:
    axes: dict[str, str] = {}
    why: dict[str, str] = {}

    def put(axis: str, level: str, reason: str) -> None:
        axes[axis], why[axis] = level, reason

    if insufficient:
        put("coverage", "low", "an essential input is not available")
    elif p is None:
        put(
            "coverage",
            "medium" if not p_required else "low",
            "no league-scored roster term votes",
        )
    else:
        put("coverage", "high", "every essential term votes")

    if insufficient or raw_verdict == "TIE":
        put("margin", "low", "no term clears its band" if raw_verdict == "TIE" else "not evaluated")
    else:
        deciding = {"A": [a], "P": [p], "both": [a, p], "strategy": [a, p]}.get(
            decided_by or "", []
        )
        large = any(t is not None and t.magnitude_class == "large" for t in deciding)
        put(
            "margin",
            "high" if large else "medium",
            "deciding margin " + ("large" if large else "modest"),
        )

    if decided_by == "strategy":
        put("agreement", "low", "market and roster terms disagree; the strategy row decided")
    elif agreement_cap is not None:
        put(
            "agreement",
            agreement_cap,
            "market and roster terms share current_season_production; agreement is not corroboration",
        )
    else:
        put("agreement", "high", "one voting family; nothing to corroborate")

    weak = [
        k
        for k in ("lowConfidenceAssets", "unstampedAssets", "sourceDisagreementAssets")
        if asset.get(k)
    ]
    if weak:
        put("asset_evidence", "medium", "traded-asset evidence: " + ", ".join(weak))
    elif asset_detail.get("forcedReleaseBasis") == "lower_bound":
        put("asset_evidence", "medium", "forced-release cost is a lower bound")
    else:
        put("asset_evidence", "high", "traded assets carry no weak-evidence flag")

    c = params["terms"]["C"]
    if p is not None and p.term == "C":
        if p.precision_ok is not True:
            put("mc_precision", "low", "lineup estimate imprecise or precision unknown")
        elif (
            p.mc_standard_error is not None
            and p.band is not None
            and p.mc_standard_error <= p.band * float(c["precisionHighFraction"])
        ):
            put("mc_precision", "high", "lineup estimate precise")
        else:
            put("mc_precision", "medium", "lineup estimate moderately precise")
    else:
        put("mc_precision", "high", "no simulated estimate votes")

    if p is not None and p.term == "C":
        basis = p.predictive_basis
        if basis == "provider_calibrated":
            put("predictive_basis", "high", "provider-calibrated predictive distribution")
        elif basis in ("prior_projection_error", "proxy_dispersion"):
            put("predictive_basis", "medium", f"predictive distribution is {basis}")
        elif decided_by in ("P", "both", "strategy"):
            put(
                "predictive_basis",
                "medium",
                "no predictive distribution behind a roster-decided verdict",
            )
        else:
            put("predictive_basis", "high", "verdict not decided by the roster term")
    else:
        put("predictive_basis", "high", "no predictive term votes")

    states = {k: v for k, v in (freshness or {}).items()}
    if not states:
        put("freshness", "medium", "input freshness not reported")
    elif any(v == "stale" for v in states.values()):
        put(
            "freshness",
            "low",
            "stale: " + ", ".join(sorted(k for k, v in states.items() if v == "stale")),
        )
    elif any(v != "fresh" for v in states.values()):
        put("freshness", "medium", "freshness unknown for some inputs")
    else:
        put("freshness", "high", "every reported input fresh")

    rel = va_relation(asset, p)
    if rel == "aligned":
        put(
            "overlap_guard",
            "medium",
            "va_roster_overlap: package VA and the lineup term point the same way",
        )
    else:
        put("overlap_guard", "high", "no VA / lineup overlap")

    level = min(axes.values(), key=_RANK.__getitem__)
    binding = [k for k in AXES if axes[k] == level]
    return {
        "level": level,
        "bottleneck": binding[0],
        "bottlenecks": binding,
        "axes": axes,
        "why": why,
        "isProbability": False,
        "vaRelation": rel,
    }
