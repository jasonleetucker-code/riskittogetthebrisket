"""The ONE canonical trade decision (TC-C, owner decisions 1-5, 2026-10-18).

Every top-line answer to "should I make this trade?" -- **YES — MAKE THE
TRADE**, **NO — DO NOT MAKE THE TRADE**, **NO — TOO CLOSE** or **NOT ENOUGH
EVIDENCE** -- is produced here and nowhere else.  ``analyze_trade`` builds the
evidence (its lenses read the canonical owners: the package model, the
best-ball roster utility, roster capacity, competitive posture, the
confidence stamps) and hands it to :func:`decide`; the frontend renders the
result verbatim (the ``buildRows`` materializer rule).  No other module may
emit a top-line decision (pinned by ``tests/trade/test_trade_decision_owner.py``).
The retired ``teamImpact.verdict`` (owner decision 5) does not come back here
in any form: this module does not read ``teamImpact``.

The decision is computed in four steps, never by a weighted sum:

1. **Strategy** (owner decision 2).  The user's explicit ``teamGoal`` wins and
   is echoed back.  Otherwise it is inferred from the canonical Competitive
   Posture (``src.roster_intel.window.competitive_posture``): PUSH (contender)
   → WIN_NOW; RETOOL → BALANCED; REBUILD (rebuilder) → LONG_TERM; HOLD
   (uncertain) → BALANCED (owner decisions, 2026-10-18).  RETOOL stays its own
   classification -- it is never reported as a rebuilder.  A posture that is
   not available at all is UNKNOWN, not BALANCED.
2. **Execution gate.**  No legal roster cleanup exists → NO.
3. **Evidence gates** (owner decision 1).  NOT ENOUGH EVIDENCE when material
   information is missing: an unpriced / off-board / quarantined / stale
   traded asset, a pick the sender does not hold, unknown pick ownership, an
   unknown roster, roster limit or posture, an unpriced forced cut, or (for
   WIN_NOW / BALANCED in season) a traded player without a projection.  Every
   missing item is named.
4. **Components and a goal-keyed rule table.**  Objective value (component A:
   the adjusted package gap net of releases the trade forces, classified by
   the ONE fairness-band owner) and roster benefit (component B: the best-ball
   utility lens) each give favours / neutral / opposes plus modest / large in
   their OWN units; the strategy only chooses which one decides when they
   disagree.  A near tie with complete evidence is **NO — TOO CLOSE**.

Confidence is a label (HIGH / MEDIUM / LOW) from the weakest of five axes --
never a probability.  This module computes no value, calls no engine, writes
nothing and executes nothing: a recommendation is never an action.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from src.valuation_math import fairness_bands, package_model

DECISION_VERSION = "trade_decision_v2"

#: The four top-line answers and their user-facing text.  This dict is the
#: only place these strings exist in the backend.
HEADLINE_TEXT = {
    "YES": "YES — MAKE THE TRADE",
    "NO": "NO — DO NOT MAKE THE TRADE",
    "NO_TOO_CLOSE": "NO — TOO CLOSE",
    "NOT_ENOUGH_EVIDENCE": "NOT ENOUGH EVIDENCE",
}
NOT_ENOUGH_EVIDENCE_SUBTEXT = "A reliable recommendation cannot be made yet."

GOALS = ("WIN_NOW", "BALANCED", "LONG_TERM")
GOAL_LABELS = {"WIN_NOW": "Win now", "BALANCED": "Balanced", "LONG_TERM": "Long-term value"}
#: Owner decisions (2026-10-18, final): contender (PUSH) → win now; RETOOL →
#: BALANCED; rebuilder (REBUILD) → long-term; uncertain (HOLD) → balanced.
#: RETOOL keeps its own classification and is never relabelled a rebuilder: a
#: retooling roster weighs current competitiveness AND long-term value, so it
#: must not automatically prefer future value over meaningful current
#: production.  (This supersedes the audit §7.2 C proposal RETOOL → REBUILD.)
POSTURE_TO_GOAL = {
    "PUSH": "WIN_NOW",
    "HOLD": "BALANCED",
    "RETOOL": "BALANCED",
    "REBUILD": "LONG_TERM",
}
#: How each classification is named to the user (RETOOL is never "rebuilder").
POSTURE_WORDS = {
    "PUSH": "contender (PUSH)",
    "HOLD": "uncertain (HOLD)",
    "RETOOL": "retooling (RETOOL)",
    "REBUILD": "rebuilder (REBUILD)",
}

#: The five-level graded detail (the v2 ``recommendation``), kept as ``leaning``.
RECOMMENDATIONS = ("MAKE", "LEAN_MAKE", "TOO_CLOSE", "LEAN_PASS", "PASS")
_STEP = {r: i for i, r in enumerate(RECOMMENDATIONS)}

#: Roster-utility states that mean "no current-season roster effect exists to
#: measure" (offseason), as opposed to "we failed to measure it".
_ROSTER_NOT_APPLICABLE = {"season_unresolved", "no_remaining_fantasy_weeks"}

_LEVELS = ("LOW", "MEDIUM", "HIGH")


# ── The graded leaning (moved here from analyze_trade: one owner) ──────────


def _step(rec: str, delta: int) -> str:
    i = min(max(_STEP[rec] - delta, 0), len(RECOMMENDATIONS) - 1)
    return RECOMMENDATIONS[i]


def leaning(market: Any, roster: Any, feasibility: Any) -> tuple[str, str, str]:
    """``(leaning, confidence, basis)`` -- the five-level rule table that was
    the v2 ``recommendation``.  It is the graded DETAIL under the headline,
    never a second headline."""
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
            rec, confidence = "TOO_CLOSE", "MEDIUM"
        else:
            rec, confidence = "TOO_CLOSE", "LOW"
        basis = "market_and_roster"

    if feasibility.available and feasibility.direction in ("favors", "opposes"):
        rec = _step(rec, 1 if feasibility.direction == "favors" else -1)
        basis += f"+feasibility:{feasibility.direction}"
    if feasibility.detail.get("ladderExhausted"):
        if _STEP[rec] < _STEP["TOO_CLOSE"]:
            rec = "TOO_CLOSE"
        basis += "+no_legal_cleanup"
    return rec, confidence, basis


# ── Strategy (owner decision 2) ────────────────────────────────────────────


def normalize_goal(raw: Any) -> str | None:
    """A requested goal, or ``None`` for "infer it".  Accepts the canonical
    keys and a few spellings; anything else is ``None`` (reported as invalid)."""
    if not isinstance(raw, str):
        return None
    key = raw.strip().upper().replace("-", "_").replace(" ", "_")
    aliases = {
        "WINNOW": "WIN_NOW",
        "CONTEND": "WIN_NOW",
        "REBUILD": "LONG_TERM",
        "LONGTERM": "LONG_TERM",
    }
    key = aliases.get(key, key)
    return key if key in GOALS else None


def resolve_strategy(posture: Any, team_goal: Any, team_context: bool) -> dict[str, Any]:
    requested = team_goal if isinstance(team_goal, str) and team_goal.strip() else None
    chosen = normalize_goal(requested)
    out: dict[str, Any] = {
        "requested": requested,
        "requestedValid": None if requested is None else chosen is not None,
        "options": [{"value": g, "label": GOAL_LABELS[g]} for g in GOALS],
        "postureMap": dict(POSTURE_TO_GOAL),
    }
    label = (posture.detail or {}).get("label") if posture.available else None
    out["inferredClassification"] = label
    inferred = POSTURE_TO_GOAL.get(label) if label else None
    out["inferredStrategy"] = inferred
    if not team_context:
        return {
            **out,
            "used": None,
            "label": None,
            "source": "asset_only",
            "reasoning": "Asset-only analysis: no strategy is used.",
        }
    if chosen is not None:
        why = f"You chose {GOAL_LABELS[chosen].lower()}"
        if label:
            would = GOAL_LABELS[inferred].lower() if inferred else "no strategy"
            why += f"; your competitive posture is {POSTURE_WORDS.get(label, label)}, which would infer {would}"
        return {
            **out,
            "used": chosen,
            "label": GOAL_LABELS[chosen],
            "source": "user",
            "reasoning": why + ".",
        }
    if inferred is None:
        return {
            **out,
            "used": None,
            "label": None,
            "source": "posture_unknown",
            "reasoning": "Your competitive posture is unknown, so no strategy can be inferred.",
        }
    if (posture.detail or {}).get("evidence") != "measured":
        return {
            **out,
            "used": inferred,
            "label": GOAL_LABELS[inferred],
            "source": "posture_no_evidence",
            "reasoning": "Your competitive posture has no measured evidence (HOLD), so the "
            "strategy is balanced.",
        }
    return {
        **out,
        "used": inferred,
        "label": GOAL_LABELS[inferred],
        "source": "posture",
        "reasoning": f"Your competitive posture is {POSTURE_WORDS.get(label, label)}, so the "
        f"strategy is {GOAL_LABELS[inferred].lower()}.",
    }


def _posture_block(posture: Any, team_context: bool) -> dict[str, Any]:
    if not team_context:
        return {"available": False, "reason": "asset_only_mode"}
    if not posture.available:
        return {"available": False, "reason": posture.unavailable_reason}
    d = posture.detail or {}
    return {
        "available": True,
        "label": d.get("label"),
        "evidence": d.get("evidence"),
        "probabilities": d.get("probabilities"),
        "confidence": d.get("confidence"),
        "paramsVersion": d.get("paramsVersion"),
        "role": "selects_strategy_never_votes",
    }


# ── Evidence gates (owner decision 1) ──────────────────────────────────────


def _missing(code: str, text: str, **evidence: Any) -> dict[str, Any]:
    return {"code": code, "text": text, "evidence": evidence}


def _traded(simulation: dict[str, Any]) -> list[dict[str, Any]]:
    return [*(simulation.get("receiving") or []), *(simulation.get("sending") or [])]


def asset_is_priced(asset: Any) -> bool:
    """MISSING IS NEVER ZERO: a resolved asset whose canonical value is absent
    or not positive is UNPRICED, never an asset worth 0.  The one definition
    the market lens and the evidence gates both use."""
    v = asset.get("value") if isinstance(asset, dict) else None
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0


def asset_evidence_codes(asset: Any) -> tuple[str, ...]:
    """The evidence-gate codes ONE resolved traded asset raises, in gate order:
    ``unpriced_assets`` (no positive canonical value), ``quarantined_values``
    (the pipeline's own quarantine verdict) and ``stale_values`` (the
    confidence owner's freshness axis reads ``low``).  Read, never computed."""
    if not isinstance(asset, dict):
        return ()
    codes: list[str] = []
    if not asset_is_priced(asset):
        codes.append("unpriced_assets")
    if asset.get("quarantined") is True:
        codes.append("quarantined_values")
    if asset.get("valueFreshness") == "low":
        codes.append("stale_values")
    return tuple(codes)


def _evidence_gaps(
    simulation: dict[str, Any],
    market: Any,
    roster: Any,
    feasibility: Any,
    strategy: dict[str, Any],
    team_context: bool,
) -> list[dict[str, Any]]:
    gaps: list[dict[str, Any]] = []
    md = market.detail or {}
    if not market.available:
        gaps.append(
            _missing("no_priced_assets", "No traded asset has a canonical value on either side.")
        )
    off_board = [*(md.get("unresolvedIn") or []), *(md.get("unresolvedOut") or [])]
    off_board += [
        n
        for n in (*(simulation.get("unresolvedIn") or []), *(simulation.get("unresolvedOut") or []))
        if n not in off_board
    ]
    if off_board:
        gaps.append(
            _missing(
                "off_board_assets",
                "Not on the board, so not priced: " + ", ".join(map(str, off_board)),
                assets=off_board,
            )
        )
    unpriced = [*(md.get("unpricedIn") or []), *(md.get("unpricedOut") or [])]
    if unpriced:
        gaps.append(
            _missing(
                "unpriced_assets",
                "On the board but unpriced (unknown, not worth 0): " + ", ".join(unpriced),
                assets=unpriced,
            )
        )
    unheld = md.get("notOwnedBySender") or []
    if unheld:
        gaps.append(
            _missing(
                "unheld_assets",
                "Your team does not hold: "
                + ", ".join(
                    f"{c.get('label')} (held by {c['actualOwnerName']})"
                    if c.get("actualOwnerName")
                    else str(c.get("label"))
                    for c in unheld
                ),
                assets=[c.get("label") for c in unheld],
            )
        )
    po = simulation.get("pickOwnership")
    has_picks = any(a.get("assetClass") == "pick" for a in _traded(simulation))
    if isinstance(po, dict) and po.get("state") == "unavailable" and has_picks:
        gaps.append(
            _missing(
                "pick_ownership_unknown",
                "This team's draft-pick ownership is unknown, so the picks in this trade "
                "cannot be checked.",
                reason=po.get("reason"),
            )
        )
    quarantined = [
        a.get("name")
        for a in _traded(simulation)
        if "quarantined_values" in asset_evidence_codes(a)
    ]
    if quarantined:
        gaps.append(
            _missing(
                "quarantined_values",
                "Value withheld as untrustworthy (quarantined): "
                + ", ".join(map(str, quarantined)),
                assets=quarantined,
            )
        )
    stale = [
        a.get("name") for a in _traded(simulation) if "stale_values" in asset_evidence_codes(a)
    ]
    if stale:
        gaps.append(
            _missing(
                "stale_values",
                "Value rests mostly on stale sources: " + ", ".join(map(str, stale)),
                assets=stale,
            )
        )
    if not team_context:
        return gaps

    if strategy.get("source") == "posture_unknown":
        gaps.append(
            _missing(
                "posture_unknown",
                "Your team's competitive posture is unknown, so the strategy cannot be inferred "
                "(choose one to continue).",
                strategySource=strategy.get("source"),
            )
        )
    goal = strategy.get("used")
    if not roster.available:
        reason = roster.unavailable_reason
        if reason == "partial_projection_coverage":
            if goal in ("WIN_NOW", "BALANCED"):
                ids = ((roster.detail or {}).get("coverage") or {}).get(
                    "tradedUnprojectedPlayerIds"
                ) or []
                gaps.append(
                    _missing(
                        "unprojected_players",
                        f"No league-scored projection for {len(ids)} traded player(s), and a "
                        f"{GOAL_LABELS[goal].lower()} decision needs the roster effect.",
                        playerIds=list(ids),
                    )
                )
        elif reason not in _ROSTER_NOT_APPLICABLE:
            gaps.append(
                _missing(
                    "roster_unknown",
                    f"The roster effect could not be measured ({reason}).",
                    reason=reason,
                )
            )
    fd = feasibility.detail or {}
    if not feasibility.available:
        reason = feasibility.unavailable_reason
        grows = (
            isinstance(fd.get("sizeAfter"), int)
            and isinstance(fd.get("sizeBefore"), int)
            and fd["sizeAfter"] > fd["sizeBefore"]
        )
        if reason not in ("unknown_limit", "uncertain") or grows:
            gaps.append(
                _missing(
                    "roster_limit_unknown",
                    f"Whether the trade fits your roster is unknown ({reason}).",
                    reason=reason,
                )
            )
    unpriced_drops = fd.get("unpricedForcedDrops")
    if isinstance(unpriced_drops, int) and unpriced_drops > 0:
        gaps.append(
            _missing(
                "forced_drop_unpriced",
                f"{unpriced_drops} forced cut(s) have no value, so the cost of the cut is unknown.",
                count=unpriced_drops,
            )
        )
    return gaps


# ── Components ─────────────────────────────────────────────────────────────


def _objective_value(market: Any, feasibility: Any) -> dict[str, Any]:
    """Component A: the adjusted package gap, net of the dynasty value released
    by cuts this trade ADDS (charged once here; their lineup effect is in B)."""
    md = market.detail or {}
    gap = float(md["vaAdjustedGap"])
    larger = max(float(md["sendingAdjusted"]), float(md["receivingAdjusted"]))
    fd = feasibility.detail or {}
    release = fd.get("forcedDropReleaseCost")
    charged = None
    if "forcedDropCharge" in fd:
        # Flag ``forced_drop_cheapest_legal``: the ONE charge the roster-capacity
        # owner publishes (``roster_capacity.forced_drop_cost``) — the same
        # number the Trade Finder ranks on.  Marginal to the trade, unpriced
        # drops charged, an acquired release already netted out of the package.
        # Absent when the flag is OFF, so the incumbent branch below is
        # unchanged.
        c = fd.get("forcedDropCharge")
        if (
            feasibility.available
            and isinstance(c, (int, float))
            and not isinstance(c, bool)
            and c > 0
        ):
            charged = float(c)
    elif (
        feasibility.available
        and fd.get("state") == "cut_required"
        and fd.get("overLimitBefore") == 0
        and isinstance(release, (int, float))
        and not isinstance(release, bool)
        and release > 0
    ):
        charged = float(release)
    net = gap - charged if charged is not None else gap
    band = fairness_bands.classify(net, larger)
    if band["level"] == "fair":
        direction, magnitude = "neutral", None
    else:
        direction = "favors" if net > 0 else "opposes"
        magnitude = "modest" if band["level"] == "slight" else "large"
    return {
        "evaluated": True,
        "direction": direction,
        "magnitude": magnitude,
        "unit": "canonical value points (adjusted package)",
        "vaAdjustedGap": int(round(gap)),
        "forcedReleaseCost": None if charged is None else int(round(charged)),
        "netGap": int(round(net)),
        "largerAdjustedSide": int(round(larger)),
        "band": band,
        "kind": "independent",
    }


def _roster_benefit(roster: Any, goal: str | None, team_context: bool) -> dict[str, Any]:
    d = roster.detail or {}
    if not team_context:
        return {"evaluated": False, "state": "excluded_by_mode", "kind": "independent"}
    if not roster.available:
        reason = roster.unavailable_reason
        state = (
            "not_applicable"
            if reason in _ROSTER_NOT_APPLICABLE
            or (reason == "partial_projection_coverage" and goal == "LONG_TERM")
            else "unavailable"
        )
        return {"evaluated": False, "state": state, "reason": reason, "kind": "independent"}
    magnitude = d.get("magnitude")
    return {
        "evaluated": True,
        "state": "evaluated",
        "direction": roster.direction,
        "magnitude": magnitude if magnitude in ("modest", "large") else None,
        "unit": d.get("unit"),
        "ppg": d.get("ppg"),
        "standardError": d.get("standardError"),
        "neutralBandPpg": d.get("neutralBandPpg"),
        "kind": "independent",
    }


def _rule(a: dict[str, Any], b: dict[str, Any], goal: str | None) -> tuple[str, str]:
    """``(headline, deciding)`` -- the goal-keyed lexicographic table (audit
    §7.3, owner decision 1: a near tie reads NO — TOO CLOSE).  No weights."""
    da = a["direction"]
    if not b.get("evaluated"):
        if da == "favors":
            return "YES", "objectiveValue"
        if da == "opposes":
            return "NO", "objectiveValue"
        return "NO_TOO_CLOSE", "objectiveValue"
    db = b["direction"]
    a_large = a.get("magnitude") == "large"
    b_large = b.get("magnitude") == "large"
    if da == db == "favors":
        return "YES", "both"
    if da == db == "opposes":
        return "NO", "both"
    if da == db == "neutral":
        return "NO_TOO_CLOSE", "both"
    if da == "favors" and db == "neutral":
        return "YES", "objectiveValue"
    if da == "neutral" and db == "favors":
        if goal == "LONG_TERM" and not b_large:
            return "NO_TOO_CLOSE", "strategy"
        return "YES", "rosterBenefit"
    if da == "opposes" and db == "neutral":
        return "NO", "objectiveValue"
    if da == "neutral" and db == "opposes":
        return "NO", "rosterBenefit"
    if da == "favors" and db == "opposes":
        # Value up, lineup down.
        if goal == "LONG_TERM":
            return "YES", "strategy"
        return ("YES", "strategy") if (a_large and not b_large) else ("NO", "strategy")
    # da == "opposes" and db == "favors": value down, lineup up.
    if goal == "WIN_NOW":
        # A contender takes a large lineup gain over package value.
        return ("YES", "strategy") if b_large else ("NO", "strategy")
    if goal == "BALANCED":
        # Weighs both, symmetric with the case above (owner decision RETOOL ->
        # BALANCED: meaningful current production is not automatically traded
        # away for future value, nor the reverse).
        return ("YES", "strategy") if (b_large and not a_large) else ("NO", "strategy")
    return "NO", "strategy"


# ── Reasons ────────────────────────────────────────────────────────────────


def _signed(n: Any) -> str:
    return f"{int(n):+,}"


def _reasons(
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
    feasibility: Any,
    strategy: dict[str, Any],
    posture: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if a is not None:
        band = a["band"]
        rel = band.get("relativePct")
        text = (
            f"{_signed(a['netGap'])} package value for you after Value Adjustment"
            + (
                f" and the forced cut ({_signed(-a['forcedReleaseCost'])})"
                if a["forcedReleaseCost"]
                else ""
            )
            + (
                f" — {rel:.1f}% of the larger package, {band['label']} band"
                if rel is not None
                else ""
            )
        )
        out.append(
            {
                "component": "objectiveValue",
                "stance": {"favors": "for", "opposes": "against"}.get(a["direction"], "neutral"),
                "kind": "independent",
                "text": text,
                "evidence": {
                    k: a[k]
                    for k in ("vaAdjustedGap", "forcedReleaseCost", "netGap", "largerAdjustedSide")
                }
                | {"band": band},
            }
        )
    if b is not None and b.get("evaluated"):
        ppg = b.get("ppg")
        out.append(
            {
                "component": "rosterBenefit",
                "stance": {"favors": "for", "opposes": "against"}.get(b["direction"], "neutral"),
                "kind": "independent",
                "text": (
                    f"{ppg:+.1f} expected best-ball points per week in your legal lineup"
                    if isinstance(ppg, (int, float))
                    else "Roster effect measured"
                ),
                "evidence": {
                    k: b.get(k) for k in ("ppg", "standardError", "neutralBandPpg", "magnitude")
                },
            }
        )
    fd = feasibility.detail or {}
    state = fd.get("state")
    if feasibility.available and state:
        names = [str(d.get("name")) for d in fd.get("forcedDrops") or []]
        text = {
            "fits_cleanly": "Fits your roster without a cut",
            "uses_final_spot": "Uses your final open roster spot",
            "resolves_overage": "Brings your roster back under the limit",
            "reduces_overage": "Reduces your roster overage",
            "cut_required": "Roster full — cut required"
            + (f": likely {', '.join(names)}" if names else ""),
            "worsens_overage": "Worsens an existing roster overage",
            "overage_unchanged": "Leaves an existing roster overage unchanged",
        }.get(state, state)
        out.append(
            {
                "component": "feasibility",
                "stance": "against"
                if feasibility.direction == "opposes"
                else "for"
                if feasibility.direction == "favors"
                else "neutral",
                "kind": "contextual",
                "text": text,
                "evidence": {
                    "state": state,
                    "forcedDrops": names,
                    "forcedDropReleaseCost": fd.get("forcedDropReleaseCost"),
                },
            }
        )
    if strategy.get("used"):
        src = strategy["source"]
        out.append(
            {
                "component": "strategy",
                "stance": "context",
                "kind": "contextual",
                "text": f"Strategy: {strategy['label']}. {strategy.get('reasoning') or ''}".strip(),
                "evidence": {
                    "used": strategy["used"],
                    "source": src,
                    "inferredClassification": strategy.get("inferredClassification"),
                    "inferredStrategy": strategy.get("inferredStrategy"),
                    "postureProbabilities": posture.get("probabilities"),
                },
            }
        )
    return out


# ── Confidence (a label, never a probability) ──────────────────────────────


def _confidence(
    headline: str,
    deciding: str,
    a: dict[str, Any],
    b: dict[str, Any],
    strategy: dict[str, Any],
    evidence: Any,
    uncertainty: list[str],
    team_context: bool,
) -> dict[str, Any]:
    axes: dict[str, str] = {}
    why: dict[str, str] = {}
    # coverage: is every component this strategy needs evaluated?
    if not team_context:
        axes["coverage"], why["coverage"] = "MEDIUM", "asset-only: roster and fit not considered"
    elif not b.get("evaluated"):
        axes["coverage"], why["coverage"] = "MEDIUM", "no current-season roster effect to measure"
    elif strategy.get("source") == "posture_no_evidence":
        axes["coverage"], why["coverage"] = "MEDIUM", "strategy defaulted: posture has no evidence"
    else:
        axes["coverage"], why["coverage"] = "HIGH", "every component evaluated"
    # margin: how far the deciding component is from its neutral band
    mags = [c.get("magnitude") for c in (a, b) if c.get("evaluated")]
    if headline == "NO_TOO_CLOSE":
        axes["margin"], why["margin"] = "MEDIUM", "a near tie"
    elif deciding == "objectiveValue":
        axes["margin"] = "HIGH" if a.get("magnitude") == "large" else "MEDIUM"
        why["margin"] = f"package gap {a['band']['label']}"
    elif deciding == "rosterBenefit":
        axes["margin"] = "HIGH" if b.get("magnitude") == "large" else "MEDIUM"
        why["margin"] = f"roster effect {b.get('magnitude')}"
    else:
        axes["margin"] = "HIGH" if "large" in mags else "MEDIUM"
        why["margin"] = "deciding margin"
    # agreement: did the strategy have to overrule an opposing component?
    if deciding == "strategy":
        axes["agreement"], why["agreement"] = (
            "LOW",
            "value and roster disagree; your strategy decided",
        )
    else:
        axes["agreement"], why["agreement"] = "HIGH", "no component opposes the answer"
    # asset evidence: the canonical confidence stamps of the traded assets
    ev = evidence.detail or {}
    if ev.get("lowConfidenceAssets") or ev.get("unstampedAssets"):
        axes["assetEvidence"], why["assetEvidence"] = (
            "MEDIUM",
            "a traded asset has low or no confidence stamp",
        )
    elif ev.get("sourceDisagreementAssets"):
        axes["assetEvidence"], why["assetEvidence"] = "MEDIUM", "sources disagree on a traded asset"
    else:
        axes["assetEvidence"], why["assetEvidence"] = "HIGH", "traded assets well evidenced"
    # precision: the roster estimate's own simulation error
    se, band = b.get("standardError"), b.get("neutralBandPpg")
    if (
        b.get("evaluated")
        and isinstance(se, (int, float))
        and isinstance(band, (int, float))
        and band > 0
    ):
        if se < band / 3:
            axes["precision"], why["precision"] = "HIGH", "roster estimate precise"
        elif se < band / 2:
            axes["precision"], why["precision"] = "MEDIUM", "roster estimate moderately precise"
        else:
            axes["precision"], why["precision"] = "LOW", "roster estimate imprecise"
    else:
        axes["precision"], why["precision"] = "HIGH", "no simulated estimate involved"
    if uncertainty and axes["coverage"] == "HIGH":
        axes["coverage"], why["coverage"] = "MEDIUM", uncertainty[0]
    level = min(axes.values(), key=_LEVELS.index)
    binding = [k for k, v in axes.items() if v == level]
    if level == "HIGH":
        statement = "High confidence — every axis is high."
    else:
        statement = f"{level.capitalize()} confidence — limited by " + "; ".join(
            f"{k}: {why[k]}" for k in binding
        )
    return {
        "level": level,
        "bottleneck": binding,
        "axes": axes,
        "statement": statement,
        "isProbability": False,
    }


# ── What would change it (computed here, never in the frontend) ───────────

#: Search grid for the smallest hypothetical asset that flips the answer:
#: canonical values 25..9,975 in steps of 25.  The rule table is monotone in
#: incoming value (pinned by test), so the first flip on the grid is the
#: smallest one to within one step.
_FLIP_STEP = 25
_FLIP_MAX = 9975


def _priced_values(assets: list[dict[str, Any]]) -> list[float]:
    out = []
    for a in assets or []:
        v = a.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out.append(float(v))
    return out


def _a_from_values(send: list[float], recv: list[float], release: float | None) -> dict[str, Any]:
    """Component A recomputed for a hypothetical package -- the SAME owners as
    the market lens (the active package model, then the fairness bands)."""
    send_adj, recv_adj, _, _ = package_model.adjusted_pair_totals(send, recv)
    gap = recv_adj - send_adj
    # ``None`` = no cut is charged (not an unknown cost: an unpriced cut is an
    # evidence gate upstream and never reaches this search).
    net = gap - release if release is not None else gap
    band = fairness_bands.classify(net, max(send_adj, recv_adj))
    if band["level"] == "fair":
        return {"evaluated": True, "direction": "neutral", "magnitude": None, "band": band}
    return {
        "evaluated": True,
        "direction": "favors" if net > 0 else "opposes",
        "magnitude": "modest" if band["level"] == "slight" else "large",
        "band": band,
    }


def _what_would_change(
    simulation: dict[str, Any],
    headline: str,
    a: dict[str, Any],
    b: dict[str, Any],
    goal: str | None,
    strategy: dict[str, Any],
) -> list[dict[str, Any]]:
    """The smallest changes that flip the answer, each found by RE-RUNNING the
    decision on perturbed inputs -- never by subtracting a raw value from an
    adjusted gap (a new piece re-runs the package model from scratch)."""
    out: list[dict[str, Any]] = []
    send = _priced_values(simulation.get("sending") or [])
    recv = _priced_values(simulation.get("receiving") or [])
    release = a.get("forcedReleaseCost")

    def run(a2: dict[str, Any], b2: dict[str, Any], g: str | None) -> str:
        return _rule(a2, b2, g)[0]

    # 1. Price: one more asset on either side.
    side = "receive" if headline in ("NO", "NO_TOO_CLOSE") else "send"
    for v in range(_FLIP_STEP, _FLIP_MAX + 1, _FLIP_STEP):
        s2, r2 = (send, [*recv, float(v)]) if side == "receive" else ([*send, float(v)], recv)
        flipped = run(_a_from_values(s2, r2, release), b, goal)
        if flipped != headline:
            out.append(
                {
                    "kind": "price",
                    "text": (
                        f"If you also received an asset worth about {v:,}, the answer would be "
                        f"{HEADLINE_TEXT[flipped]}"
                        if side == "receive"
                        else f"If you also had to send an asset worth about {v:,}, the answer "
                        f"would be {HEADLINE_TEXT[flipped]}"
                    ),
                    "flipsTo": flipped,
                    "evidence": {"side": side, "assetValue": v, "searchStep": _FLIP_STEP},
                }
            )
            break
    else:
        out.append(
            {
                "kind": "price",
                "text": "No single added asset (up to 9,975) changes the answer",
                "flipsTo": None,
                "evidence": {"side": side, "searchedUpTo": _FLIP_MAX},
            }
        )
    # 2. Strategy: only when it is in use.
    if goal is not None:
        for g in GOALS:
            if g == goal:
                continue
            flipped = run(a, b, g)
            if flipped != headline:
                out.append(
                    {
                        "kind": "strategy",
                        "text": f"If your strategy were {GOAL_LABELS[g].lower()}, the answer "
                        f"would be {HEADLINE_TEXT[flipped]}",
                        "flipsTo": flipped,
                        "evidence": {
                            "strategy": g,
                            "current": goal,
                            "source": strategy.get("source"),
                        },
                    }
                )
    # 3. Roster effect: if it were neutral instead.
    if b.get("evaluated") and b.get("direction") != "neutral":
        flipped = run(a, {**b, "direction": "neutral", "magnitude": None}, goal)
        if flipped != headline:
            out.append(
                {
                    "kind": "roster",
                    "text": f"If the trade did not change your lineup, the answer would be "
                    f"{HEADLINE_TEXT[flipped]}",
                    "flipsTo": flipped,
                    "evidence": {"rosterPpg": b.get("ppg")},
                }
            )
    # 4. The forced cut: if it were avoided.
    if release:
        flipped = run(_a_from_values(send, recv, None), b, goal)
        if flipped != headline:
            out.append(
                {
                    "kind": "forced_cut",
                    "text": f"If the forced cut could be avoided, the answer would be "
                    f"{HEADLINE_TEXT[flipped]}",
                    "flipsTo": flipped,
                    "evidence": {"forcedReleaseCost": release},
                }
            )
    return out


# ── Per-dimension coverage record (audit §7.5) ────────────────────────────

DIMENSIONS = (
    "asset_value",
    "immediate_improvement",
    "long_term",
    "roster_construction",
    "market_evidence",
    "competitive_strategy",
    "risk",
    "feasibility",
    "opportunity_cost",
    "league_constraints",
)


def _cov(
    dimension: str,
    state: str,
    *,
    kind: str,
    lineage: str | None,
    component: str | None,
    role: str,
    evidence: Any = None,
    freshness: str = "unknown",
    applicability: str = "exact",
    applicability_reason: str | None = None,
    uncertainty: dict[str, Any] | None = None,
    contribution: dict[str, Any] | None = None,
    exclusion: str | None = None,
    owner: str,
) -> dict[str, Any]:
    return {
        "dimension": dimension,
        "state": state,
        "evidenceKind": kind,
        "lineage": lineage,
        "component": component,
        "role": role,
        "evidence": evidence if state in ("evaluated", "partial") else None,
        "freshness": freshness,
        "applicability": {"state": applicability, "reason": applicability_reason},
        "uncertainty": uncertainty or {"kind": "unknown", "value": None},
        "contribution": contribution or {"direction": None, "magnitude": None, "unit": None},
        "exclusionReason": exclusion,
        "owner": owner,
    }


def _coverage(
    simulation: dict[str, Any],
    *,
    market: Any,
    roster: Any,
    feasibility: Any,
    evidence: Any,
    posture: Any,
    comparables: Any,
    a: dict[str, Any] | None,
    b: dict[str, Any] | None,
    strategy: dict[str, Any],
    team_context: bool,
) -> list[dict[str, Any]]:
    """One record per required dimension, always all ten, so "not evaluated"
    and "evaluated and neutral" can never look the same."""
    traded = _traded(simulation)
    fresh = [x.get("valueFreshness") for x in traded if x.get("valueFreshness")]
    asset_fresh = (
        "stale" if "low" in fresh else "fresh" if fresh and len(fresh) == len(traded) else "unknown"
    )
    md = market.detail or {}
    rd = roster.detail or {}
    fd = feasibility.detail or {}
    ev = evidence.detail or {}
    excluded = None if team_context else "asset_only_mode"
    recs = [
        _cov(
            "asset_value",
            "evaluated" if market.available else "unavailable",
            kind="independent",
            lineage="canonical_value",
            component="objectiveValue",
            role="decides",
            evidence={
                k: md.get(k)
                for k in ("vaAdjustedGap", "rawGap", "sendingAdjusted", "receivingAdjusted", "band")
            },
            freshness=asset_fresh,
            uncertainty={
                "kind": "confidence_bucket",
                "value": len(ev.get("lowConfidenceAssets") or []),
            },
            contribution=None
            if a is None
            else {
                "direction": a["direction"],
                "magnitude": a["magnitude"],
                "unit": "canonical value",
            },
            exclusion=None if market.available else market.unavailable_reason,
            owner="src/trade/analyze_trade.py::equity_verdict + src/valuation_math",
        ),
    ]
    if not team_context:
        r_state = "excluded_by_mode"
    elif roster.available:
        r_state = "evaluated"
    elif b is not None and b.get("state") == "not_applicable":
        r_state = "not_applicable"
    else:
        r_state = "unavailable"
    recs.append(
        _cov(
            "immediate_improvement",
            r_state,
            kind="independent",
            lineage="league_scored_projection",
            component="rosterBenefit",
            role="decides",
            evidence={
                k: rd.get(k) for k in ("ppg", "standardError", "neutralBandPpg", "magnitude")
            },
            freshness="fresh" if roster.available else "unknown",
            uncertainty={"kind": "monte_carlo_se", "value": rd.get("standardError")},
            contribution=None
            if not (b and b.get("evaluated"))
            else {
                "direction": b["direction"],
                "magnitude": b["magnitude"],
                "unit": "best-ball ppg",
            },
            exclusion=excluded or (None if roster.available else roster.unavailable_reason),
            owner="src/roster_intel/best_ball_utility.py",
        )
    )
    recs.append(
        _cov(
            "long_term",
            "partial" if market.available else "unavailable",
            kind="correlated",
            lineage="canonical_value",
            component="objectiveValue",
            role="explain_only",
            evidence={"via": "canonical dynasty value (long-horizon) inside asset_value"},
            applicability="approximate",
            applicability_reason="no roster-level long-term quantity is wired; counted once, via asset value",
            exclusion=None,
            owner="src/trade/analyze_trade.py",
        )
    )
    recs.append(
        _cov(
            "roster_construction",
            "excluded_by_mode"
            if not team_context
            else ("evaluated" if feasibility.available else "unavailable"),
            kind="contextual",
            lineage="league_roster_rules",
            component="objectiveValue",
            role="gate",
            evidence={
                k: fd.get(k)
                for k in (
                    "state",
                    "forcedDropReleaseCost",
                    "ladderExhausted",
                    "unpricedForcedDrops",
                )
            },
            uncertainty={"kind": "none", "value": None},
            contribution={
                "direction": "opposes" if (a or {}).get("forcedReleaseCost") else "context",
                "magnitude": None,
                "unit": "release cost charged once to asset value",
            },
            exclusion=excluded
            or (None if feasibility.available else feasibility.unavailable_reason),
            owner="src/trade/roster_capacity.py",
        )
    )
    cd = getattr(comparables, "detail", None) or {}
    recs.append(
        _cov(
            "market_evidence",
            "evaluated" if comparables is not None and comparables.available else "unavailable",
            kind="correlated",
            lineage="real_trade_ledger",
            component=None,
            role="explain_only",
            evidence={
                "comparableTrades": len(cd.get("comparableTrades") or []),
                "candidates": cd.get("candidates"),
            },
            exclusion=None
            if comparables is not None and comparables.available
            else getattr(comparables, "unavailable_reason", "not_computed"),
            owner="src/trade/comparable_trades.py",
        )
    )
    pd = posture.detail or {}
    recs.append(
        _cov(
            "competitive_strategy",
            "excluded_by_mode"
            if not team_context
            else ("evaluated" if posture.available else "unavailable"),
            kind="contextual",
            lineage="team_strategy_context",
            component=None,
            role="tiebreak",
            evidence={
                "postureLabel": pd.get("label"),
                "strategyUsed": strategy.get("used"),
                "strategySource": strategy.get("source"),
            },
            uncertainty={"kind": "range", "value": pd.get("confidence")},
            exclusion=excluded or (None if posture.available else posture.unavailable_reason),
            owner="src/roster_intel/window.py::competitive_posture",
        )
    )
    recs.append(
        _cov(
            "risk",
            "evaluated",
            kind="explanatory",
            lineage=None,
            component=None,
            role="confidence_only",
            evidence={
                "lowConfidenceAssets": len(ev.get("lowConfidenceAssets") or []),
                "sourceDisagreementAssets": len(ev.get("sourceDisagreementAssets") or []),
                "unstampedAssets": len(ev.get("unstampedAssets") or []),
            },
            owner="src/api/confidence.py (stamps) via the evidence lens",
        )
    )
    po = (
        simulation.get("pickOwnership")
        if isinstance(simulation.get("pickOwnership"), dict)
        else None
    )
    recs.append(
        _cov(
            "feasibility",
            "evaluated" if market.available else "unavailable",
            kind="contextual",
            lineage="ownership_records",
            component=None,
            role="gate",
            evidence={
                "notOwnedBySender": len(md.get("notOwnedBySender") or []),
                "pickOwnership": (po or {}).get("state", "observed"),
                "counterpartyAcceptance": "not_evaluated",
            },
            applicability="approximate",
            applicability_reason="counterparty acceptance is not evaluated",
            owner="src/identity/picks.py + src/api/trade_simulator.py",
        )
    )
    recs.append(
        _cov(
            "opportunity_cost",
            "unavailable",
            kind="independent",
            lineage=None,
            component=None,
            role="explain_only",
            exclusion="not_wired",
            owner="(none: best-alternative comparison is not wired)",
        )
    )
    recs.append(
        _cov(
            "league_constraints",
            "excluded_by_mode"
            if not team_context
            else ("partial" if feasibility.available else "unavailable"),
            kind="contextual",
            lineage="league_roster_rules",
            component=None,
            role="gate",
            evidence={"rosterLimit": fd.get("rosterLimit")},
            applicability="approximate",
            applicability_reason="roster limit only; trade deadline and saved LOCK / EXCLUDE are not applied",
            exclusion=excluded,
            owner="src/trade/roster_capacity.py",
        )
    )
    assert tuple(r["dimension"] for r in recs) == DIMENSIONS
    return recs


# ── Decision receipt (audit §7.7) ──────────────────────────────────────────


def _receipt(
    simulation: dict[str, Any],
    *,
    market: Any,
    roster: Any,
    posture: Any,
    team_goal: Any,
    team_context: bool,
    provenance: dict[str, Any] | None,
    strategy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Everything needed to reproduce this decision.  The request hash covers
    the trade as priced (names, values, owned-pick checks), the team, the
    goal and the mode; ``provenance`` carries what only the caller knows (the
    board stamp, the scoring fingerprint)."""
    md = market.detail or {}

    def side(xs: list[dict[str, Any]]) -> list[list[Any]]:
        return sorted([[str(a.get("name")), a.get("value")] for a in xs or []], key=str)

    request = {
        "team": (simulation.get("team") or {}).get("name")
        if isinstance(simulation.get("team"), dict)
        else None,
        "receiving": side(simulation.get("receiving") or []),
        "sending": side(simulation.get("sending") or []),
        "notOwnedBySender": md.get("notOwnedBySender") or [],
        "teamGoal": team_goal,
        "teamContext": team_context,
    }
    digest = hashlib.sha256(
        json.dumps(request, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    prov = dict(provenance or {})
    return {
        "decisionVersion": DECISION_VERSION,
        "requestHash": digest,
        "bands": fairness_bands.receipt()["version"],
        "packageModel": md.get("packageModel"),
        "postureParamsVersion": (posture.detail or {}).get("paramsVersion")
        if posture.available
        else None,
        "projectionBasis": (roster.detail or {}).get("basis") if roster.available else None,
        "boardStamp": prov.get("boardStamp"),
        "scoringFingerprint": prov.get("scoringFingerprint"),
        "analyzeConfig": prov.get("analyzeConfig"),
        # The inferred classification, the strategy used and why (owner
        # decision 2026-10-18: shown in the recommendation AND the receipt).
        "strategy": {
            k: (strategy or {}).get(k)
            for k in (
                "inferredClassification",
                "inferredStrategy",
                "requested",
                "used",
                "source",
                "reasoning",
            )
        },
    }


# ── The decision ───────────────────────────────────────────────────────────


def decide(
    simulation: dict[str, Any],
    *,
    market: Any,
    roster: Any,
    feasibility: Any,
    evidence: Any,
    posture: Any,
    team_context: bool,
    team_goal: Any = None,
    uncertainty: list[str] | None = None,
    leaning_result: tuple[str, str, str] | None = None,
    comparables: Any = None,
    provenance: dict[str, Any] | None = None,
    counterfactuals: bool = True,
) -> dict[str, Any]:
    """The one top-line decision for one analyzed trade (pure).

    ``counterfactuals=False`` skips the "what would change it" search on the
    decided path (``whatWouldChange`` is then ``[]``).  The search runs AFTER
    the headline, leaning and confidence are fixed, so skipping it cannot
    change any of them; it is a linear scan whose run time grows with the
    gap, so a caller that must not leak the gap through latency (the public
    Brisket Trade Advisor) turns it off.
    """
    strategy = resolve_strategy(posture, team_goal, team_context)
    posture_block = _posture_block(posture, team_context)
    lean = leaning_result or leaning(market, roster, feasibility)
    base = {
        "version": DECISION_VERSION,
        "strategy": strategy,
        "posture": posture_block,
        "bands": fairness_bands.receipt(),
        "leaning": lean[0],
        "recommendationOnly": True,
        "executes": False,
        "receipt": _receipt(
            simulation,
            market=market,
            roster=roster,
            posture=posture,
            team_goal=team_goal,
            team_context=team_context,
            provenance=provenance,
            strategy=strategy,
        ),
    }

    def _cover(a: dict[str, Any] | None, b: dict[str, Any] | None) -> list[dict[str, Any]]:
        return _coverage(
            simulation,
            market=market,
            roster=roster,
            feasibility=feasibility,
            evidence=evidence,
            posture=posture,
            comparables=comparables,
            a=a,
            b=b,
            strategy=strategy,
            team_context=team_context,
        )

    def _out(headline: str, **rest: Any) -> dict[str, Any]:
        out = {
            **base,
            "headline": headline,
            "headlineText": HEADLINE_TEXT[headline],
            "subtext": NOT_ENOUGH_EVIDENCE_SUBTEXT if headline == "NOT_ENOUGH_EVIDENCE" else None,
            **rest,
        }
        return out

    # 2. Execution gate: a fact, not an evidence gap.
    if (feasibility.detail or {}).get("ladderExhausted") and team_context:
        gate = {
            "component": "feasibility",
            "stance": "against",
            "kind": "gate",
            "text": "No legal roster cleanup exists for this trade",
            "evidence": {"ladderExhausted": True},
        }
        return _out(
            "NO",
            deciding="executionGate",
            primaryReason=gate,
            reasons=[gate],
            missingEvidence=[],
            components={},
            mainCounterargument=None,
            whatWouldChange=[
                {
                    "kind": "feasibility",
                    "text": "A legal roster cleanup (a cut or a smaller package) is required first",
                    "flipsTo": None,
                    "evidence": {"ladderExhausted": True},
                }
            ],
            coverage=_cover(None, None),
            confidence={
                "level": "HIGH",
                "bottleneck": [],
                "axes": {},
                "statement": "High confidence — the trade cannot be executed as built.",
                "isProbability": False,
            },
        )

    # 3. Evidence gates.
    gaps = _evidence_gaps(simulation, market, roster, feasibility, strategy, team_context)
    if gaps:
        return _out(
            "NOT_ENOUGH_EVIDENCE",
            deciding="evidenceGate",
            primaryReason={
                "component": "evidence",
                "stance": "neutral",
                "kind": "gate",
                "text": gaps[0]["text"],
                "evidence": gaps[0]["evidence"],
            },
            reasons=[],
            missingEvidence=gaps,
            components={},
            mainCounterargument=None,
            # Each gap, resolved, is what would let a decision be made; which
            # answer it would produce cannot be known without the evidence.
            whatWouldChange=[
                {
                    "kind": "evidence",
                    "text": f"Resolve: {g['text']}",
                    "flipsTo": None,
                    "evidence": {"code": g["code"]},
                }
                for g in gaps
            ],
            coverage=_cover(None, None),
            confidence={
                "level": None,
                "bottleneck": ["evidence"],
                "axes": {},
                "statement": "No confidence is stated: material information is missing.",
                "isProbability": False,
            },
        )

    # 4. Components and the goal-keyed table.
    goal = strategy.get("used")
    a = _objective_value(market, feasibility)
    b = _roster_benefit(roster, goal, team_context)
    headline, deciding = _rule(a, b, goal)
    reasons = _reasons(a, b, feasibility, strategy, posture_block)
    by_component = {r["component"]: r for r in reasons}
    if deciding in ("objectiveValue", "rosterBenefit"):
        primary = by_component.get(deciding)
    elif deciding == "strategy":
        primary = by_component.get("strategy")
    else:  # "both"
        primary = by_component.get("objectiveValue")
    want = {"YES": "against", "NO": "for"}.get(headline)
    counter = next(
        (r for r in reasons if want and r["stance"] == want and r["kind"] == "independent"),
        None,
    ) or next((r for r in reasons if want and r["stance"] == want), None)
    confidence = _confidence(
        headline, deciding, a, b, strategy, evidence, list(uncertainty or []), team_context
    )
    return _out(
        headline,
        deciding=deciding,
        primaryReason=primary,
        reasons=reasons,
        missingEvidence=[],
        components={"objectiveValue": a, "rosterBenefit": b},
        mainCounterargument=counter,
        whatWouldChange=(
            _what_would_change(simulation, headline, a, b, goal, strategy)
            if counterfactuals
            else []
        ),
        coverage=_cover(a, b),
        confidence=confidence,
    )


# ── Public categories (Brisket Trade Advisor; design §3) ──────────────────
#
# The public advisor shows one of five recommendation categories and never a
# number.  The categories are a MAPPING of this module's own decision — no new
# threshold, no new band, no second engine.  "Strong" means the value band is
# unfair or lopsided in the matching direction (``_objective_value``'s
# ``magnitude == "large"``) AND the headline and graded leaning agree — the
# same strong cut the 3-4-team mapping uses (band unfair/lopsided), so strong
# means one thing at every team count.  Copy lives here and only here.

PUBLIC_CATEGORIES = (
    "STRONGLY_FAVORABLE",
    "FAVORABLE",
    "APPROXIMATELY_EVEN",
    "UNFAVORABLE",
    "STRONGLY_UNFAVORABLE",
    "UNAVAILABLE",
)

PUBLIC_CATEGORY_TEXT: dict[str, dict[str, str]] = {
    "STRONGLY_FAVORABLE": {
        "recommendation": "ACCEPT",
        "headline": "ACCEPT — STRONG TRADE FOR YOUR TEAM",
        "message": "Our analysis strongly favors your side of this trade.",
    },
    "FAVORABLE": {
        "recommendation": "ACCEPT",
        "headline": "ACCEPT — GOOD TRADE FOR YOUR TEAM",
        "message": "Our analysis indicates this trade benefits your team.",
    },
    "APPROXIMATELY_EVEN": {
        "recommendation": "FAIR",
        "headline": "FAIR TRADE — YOUR DECISION",
        "message": "Our analysis considers this a relatively balanced exchange.",
    },
    "UNFAVORABLE": {
        "recommendation": "DECLINE",
        "headline": "DECLINE — NOT RECOMMENDED",
        "message": "Our analysis indicates this trade does not favor your team.",
    },
    "STRONGLY_UNFAVORABLE": {
        "recommendation": "DECLINE",
        "headline": "DECLINE — STRONGLY NOT RECOMMENDED",
        "message": "Our analysis strongly favors the assets your team would give up.",
    },
    "UNAVAILABLE": {
        "recommendation": "NONE",
        "headline": "NO RECOMMENDATION",
        "message": "This trade can't be evaluated reliably right now.",
    },
}

#: The execution gate's own copy (UNFAVORABLE with reason ``roster_limit``).
PUBLIC_ROSTER_LIMIT_TEXT: dict[str, str] = {
    "recommendation": "DECLINE",
    "headline": "DECLINE — YOUR ROSTER CAN'T FIT THIS TRADE",
    "message": "Your team couldn't complete this trade under the roster limit.",
}

#: The ONLY reason codes the public surface may expose.  Anything else is
#: ``None`` with the generic UNAVAILABLE copy (posture, projection, staleness
#: and quarantine causes are deliberately collapsed).
PUBLIC_REASON_TEXT: dict[str, str] = {
    "asset_not_evaluable": "One or more assets in this trade can't be evaluated right now.",
    "ownership_unverifiable": "We couldn't confirm who owns every asset in this trade.",
    "multi_team_unsupported": (
        "Recommendations for trades with more than two teams aren't available yet."
    ),
    "roster_limit": PUBLIC_ROSTER_LIMIT_TEXT["message"],
}

#: Evidence-gate code -> public reason code.  Codes absent here (and any code
#: added to the gates later) map to ``None``: unknown fails closed.
_PUBLIC_GAP_REASON = {
    "no_priced_assets": "asset_not_evaluable",
    "off_board_assets": "asset_not_evaluable",
    "unpriced_assets": "asset_not_evaluable",
    "unheld_assets": "ownership_unverifiable",
    "pick_ownership_unknown": "ownership_unverifiable",
}


def public_category_from_decision(decision: Any) -> str:
    """The public category for one 2-team :func:`decide` result (design §3).

    | headline | condition | category |
    |---|---|---|
    | NOT_ENOUGH_EVIDENCE | — | UNAVAILABLE |
    | YES | A favours, A large, leaning MAKE | STRONGLY_FAVORABLE |
    | YES | otherwise | FAVORABLE |
    | NO_TOO_CLOSE | — | APPROXIMATELY_EVEN |
    | NO | execution gate | UNFAVORABLE (reason ``roster_limit``) |
    | NO | A opposes, A large, leaning PASS | STRONGLY_UNFAVORABLE |
    | NO | otherwise | UNFAVORABLE |

    ``A`` is ``components.objectiveValue``.  Anything malformed or unknown is
    UNAVAILABLE — a confident category is never invented.
    """
    if not isinstance(decision, dict):
        return "UNAVAILABLE"
    headline = decision.get("headline")
    if headline == "NOT_ENOUGH_EVIDENCE":
        return "UNAVAILABLE"
    if headline == "NO_TOO_CLOSE":
        return "APPROXIMATELY_EVEN"
    if headline not in ("YES", "NO"):
        return "UNAVAILABLE"
    if headline == "NO" and decision.get("deciding") == "executionGate":
        return "UNFAVORABLE"
    comps = decision.get("components")
    a = comps.get("objectiveValue") if isinstance(comps, dict) else None
    a = a if isinstance(a, dict) else {}
    large = a.get("magnitude") == "large"
    lean = decision.get("leaning")
    if headline == "YES":
        if a.get("direction") == "favors" and large and lean == "MAKE":
            return "STRONGLY_FAVORABLE"
        return "FAVORABLE"
    if a.get("direction") == "opposes" and large and lean == "PASS":
        return "STRONGLY_UNFAVORABLE"
    return "UNFAVORABLE"


def public_category_from_net_band(band: Any, net: Any) -> str:
    """The public category for one side's fairness band (the 3-4-team path).

    fair → APPROXIMATELY_EVEN; slight → FAVORABLE / UNFAVORABLE by the sign of
    ``net``; unfair or lopsided → STRONGLY_* by sign.  ``band`` is a
    ``fairness_bands.classify`` result (or its ``level``).  Unknown → UNAVAILABLE.
    """
    level = band.get("level") if isinstance(band, dict) else band
    if not isinstance(net, (int, float)) or isinstance(net, bool):
        return "UNAVAILABLE"
    if level == "fair":
        return "APPROXIMATELY_EVEN"
    if level not in ("slight", "unfair", "lopsided") or net == 0:
        return "UNAVAILABLE"
    if level == "slight":
        return "FAVORABLE" if net > 0 else "UNFAVORABLE"
    return "STRONGLY_FAVORABLE" if net > 0 else "STRONGLY_UNFAVORABLE"


def public_reason_code(decision: Any) -> str | None:
    """The one public reason code for a decision, or ``None``.

    ``roster_limit`` for the execution gate.  For NOT_ENOUGH_EVIDENCE, the
    FIRST gap decides (gates run asset checks before team-context checks, so
    a trade with an unevaluable asset reads the same whatever the team's
    posture).  A first gap outside the public list — or any code this
    function does not know — is ``None``: fail closed.
    """
    if not isinstance(decision, dict):
        return None
    if decision.get("headline") == "NO" and decision.get("deciding") == "executionGate":
        return "roster_limit"
    if decision.get("headline") != "NOT_ENOUGH_EVIDENCE":
        return None
    gaps = decision.get("missingEvidence")
    if not isinstance(gaps, list) or not gaps or not isinstance(gaps[0], dict):
        return None
    return _PUBLIC_GAP_REASON.get(str(gaps[0].get("code") or ""))


def public_text(category: str, reason_code: str | None = None) -> dict[str, str]:
    """``{recommendation, headline, message}`` for a public category (copy)."""
    if category == "UNFAVORABLE" and reason_code == "roster_limit":
        return dict(PUBLIC_ROSTER_LIMIT_TEXT)
    return dict(PUBLIC_CATEGORY_TEXT.get(category) or PUBLIC_CATEGORY_TEXT["UNAVAILABLE"])
