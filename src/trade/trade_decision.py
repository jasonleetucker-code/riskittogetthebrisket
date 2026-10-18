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
   → WIN_NOW; RETOOL / REBUILD (rebuilder) → LONG_TERM; HOLD (uncertain) →
   BALANCED.  A posture that is not available at all is UNKNOWN, not BALANCED.
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

from typing import Any

from src.valuation_math import fairness_bands

DECISION_VERSION = "trade_decision_v1"

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
#: Owner decision 2: contender → win now, rebuilder → long-term, uncertain →
#: balanced.  RETOOL is a struggling roster building around its core, so it is
#: a rebuilder here (the mapping proposed in the decision-engine audit §7.2 C).
POSTURE_TO_GOAL = {
    "PUSH": "WIN_NOW",
    "HOLD": "BALANCED",
    "RETOOL": "LONG_TERM",
    "REBUILD": "LONG_TERM",
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
    if not team_context:
        return {**out, "used": None, "label": None, "source": "asset_only"}
    if chosen is not None:
        return {**out, "used": chosen, "label": GOAL_LABELS[chosen], "source": "user"}
    if not posture.available:
        return {**out, "used": None, "label": None, "source": "posture_unknown"}
    label = (posture.detail or {}).get("label")
    goal = POSTURE_TO_GOAL.get(label)
    if goal is None:
        return {**out, "used": None, "label": None, "source": "posture_unknown"}
    measured = (posture.detail or {}).get("evidence") == "measured"
    return {
        **out,
        "used": goal,
        "label": GOAL_LABELS[goal],
        "source": "posture" if measured else "posture_no_evidence",
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
    quarantined = [a.get("name") for a in _traded(simulation) if a.get("quarantined") is True]
    if quarantined:
        gaps.append(
            _missing(
                "quarantined_values",
                "Value withheld as untrustworthy (quarantined): "
                + ", ".join(map(str, quarantined)),
                assets=quarantined,
            )
        )
    stale = [a.get("name") for a in _traded(simulation) if a.get("valueFreshness") == "low"]
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
    if (
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
        if goal == "LONG_TERM":
            return "YES", "strategy"
        return ("YES", "strategy") if (a_large and not b_large) else ("NO", "strategy")
    # da == "opposes" and db == "favors"
    if goal == "WIN_NOW" and b_large and not a_large:
        return "YES", "strategy"
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
        why = {
            "user": "you chose it",
            "posture": f"inferred from competitive posture {posture.get('label')}",
            "posture_no_evidence": "posture has no measured evidence, so balanced",
        }.get(src, src)
        out.append(
            {
                "component": "strategy",
                "stance": "context",
                "kind": "contextual",
                "text": f"Strategy: {strategy['label']} ({why})",
                "evidence": {
                    "used": strategy["used"],
                    "source": src,
                    "postureLabel": posture.get("label"),
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
) -> dict[str, Any]:
    """The one top-line decision for one analyzed trade (pure)."""
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
    }

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
        confidence=confidence,
    )
