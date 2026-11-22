"""Composed Team Advisor plan (owner directive 2026-11-21, intake DYN10, top-10 item #2).

``GET /api/team/plan`` answers *"what should this team do next?"* as ONE
payload: the team's competitive posture, then a ranked list of next actions
(buy target, sell-high candidate, waiver move, pick action, aging-asset
risk), each carrying the evidence and uncertainty of the owner it came from.
Gated by the owner-held flag ``team_advisor_plan`` (default OFF;
``tests/api/test_team_plan_hold_locked.py``).

This module is a COMPOSER and nothing else
==========================================
Every number in the payload is produced by an existing canonical owner and
passed through verbatim.  This module computes no value, score, threshold,
weight or decision of its own, and it performs no arithmetic on any value it
is handed (``tests/api/test_team_plan.py`` pins that with an AST guard: no
arithmetic operator, no aggregate builtin, no float literal).

=========================  ====================================================
section                    canonical owner consumed (never re-derived)
=========================  ====================================================
posture                    ``src/roster_intel/window.py::competitive_posture``
                           via ``gameplan.league_competitive_postures``
                           (warm-only: the last built league bundle)
team strength / weakness   ``src/roster_intel/strength.py`` / ``weakness.py``
/ age portfolio            / ``age_portfolio.py`` via
                           ``roster_intelligence.get_team_roster_intelligence``
buy targets                ``src/roster_intel/targets.py::rank_target_players``
                           as ``/api/gameplan`` serves it (``targetPlayers``,
                           ``recommended`` only), read warm-only from the
                           gameplan team cache
sell-high candidates       ``src/trade/suggestions.py`` (``sellHigh``), the
                           same path ``/api/trade/suggestions`` runs
waiver moves               ``src/trade/perfect_waivers.py`` (``plan.moves``),
                           read warm-only from the ``/api/waiver/perfect``
                           result cache
aging-asset risk           ``age_portfolio.PositionAgeProfile.is_old_for_league``
                           (the owner's own flag)
draft capital              the ``/api/draft-capital`` owner, read warm-only
                           from its result cache; pick ownership state from
                           the contract's canonical pick fold
roster freshness           ``src/api/roster_freshness.py::roster_age``
trade protections          ``src/trade/constraints.py``, applied only when the
                           requester owns the team (as ``/api/gameplan``)
=========================  ====================================================

Why buy targets come from ``targets.py`` and sell-high from ``suggestions.py``:
``targets.py`` is the canonical "which players are worth pursuing" engine
(two gates: obtainability and independent corroboration), and
``suggestions.py`` is the only owner that names sell-high candidates.  Using
``suggestions.py``'s ``buyLow`` beside the targets engine would put two
answers to one question in one plan.

Ordering (no weights)
=====================
Actions interleave BY KIND in the fixed order :data:`KIND_ORDER` -- the order
the task names them, from the owner directive's list -- taking each owner's
list in that owner's own order: every kind's first item, then every kind's
second item, and so on.  The order is a PRESENTATION order, not a priority:
nothing compares one owner's score with another's, and posture does not
reorder anything.  A posture-aware order would be a new recommendation rule,
which is owner-reserved.

Missing is never zero
=====================
Every section is ``available: true`` with the owner's answer (which may be an
empty list -- a real "nothing cleared this owner's bar") or ``available:
false`` with a stable ``unavailableReason``.  A cold cache, a refused engine,
an unresolved team or a stale roster never reads as "nothing to do".  The
plan asserts ``do_nothing`` only when EVERY owner-backed kind was assessed and
none produced an action; otherwise it is ``incomplete``.

Pure: no I/O, no clock, no globals written.  The route in ``server.py``
resolves every input (warm-only cache reads plus the cheap owners) and hands
them here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import zip_longest
from typing import Any, Mapping, Sequence

__all__ = [
    "FLAG",
    "IN_SCOPE_LEAGUE_KEYS",
    "KIND_ORDER",
    "OWNER_BACKED_KINDS",
    "TEAM_PLAN_CONTRACT_VERSION",
    "OwnerRead",
    "compose_team_plan",
    "out_of_scope_payload",
    "protections_block",
]

TEAM_PLAN_CONTRACT_VERSION = "team-plan/2026-11-22.v1"

#: The owner-held feature flag (default OFF).
FLAG = "team_advisor_plan"

#: Leagues the plan serves.  ``dynasty_main`` only: the owner's 2026-10-18 scope
#: correction puts every other league's private tools out of scope.
IN_SCOPE_LEAGUE_KEYS: frozenset[str] = frozenset({"dynasty_main"})

BUY_TARGET = "buy_target"
SELL_HIGH = "sell_high"
WAIVER_MOVE = "waiver_move"
PICK_ACTION = "pick_action"
AGING_ASSET_RISK = "aging_asset_risk"
DO_NOTHING = "do_nothing"

#: Fixed presentation order of the action kinds (see the module docstring).
KIND_ORDER: tuple[str, ...] = (BUY_TARGET, SELL_HIGH, WAIVER_MOVE, PICK_ACTION, AGING_ASSET_RISK)

#: Kinds an existing owner can actually produce.  ``pick_action`` has no
#: single-team owner (see :func:`_pick_actions_section`), so it is reported
#: as not assessed rather than blocking ``do_nothing`` forever.
OWNER_BACKED_KINDS: tuple[str, ...] = (BUY_TARGET, SELL_HIGH, WAIVER_MOVE, AGING_ASSET_RISK)

POSTURE_OWNER = "src/roster_intel/window.py::competitive_posture"
STRENGTH_OWNER = "src/roster_intel/strength.py"
WEAKNESS_OWNER = "src/roster_intel/weakness.py"
AGE_OWNER = "src/roster_intel/age_portfolio.py"
AGING_OWNER = "src/roster_intel/age_portfolio.py::PositionAgeProfile.is_old_for_league"
TARGETS_OWNER = "src/roster_intel/targets.py::rank_target_players"
SUGGESTIONS_OWNER = "src/trade/suggestions.py::generate_suggestions_from_pool"
WAIVERS_OWNER = "src/trade/perfect_waivers.py::build_perfect_waivers"
DRAFT_CAPITAL_OWNER = "server.py::get_draft_capital (/api/draft-capital)"
PICK_OWNERSHIP_OWNER = "src/identity/picks.py (sleeper.teams[].pickOwnershipState)"
FRESHNESS_OWNER = "src/api/roster_freshness.py::roster_age"
CONSTRAINTS_OWNER = "src/trade/constraints.py"

_SECTION_FOR_KIND = {
    BUY_TARGET: "buyTargets",
    SELL_HIGH: "sellHigh",
    WAIVER_MOVE: "waivers",
    PICK_ACTION: "pickActions",
    AGING_ASSET_RISK: "agingAssets",
}

_ORDERING_RULE = (
    "interleave by kind in kindOrder, keeping each owner's own order: every kind's "
    "first action, then every kind's second, and so on. A presentation order, not a "
    "priority: no owner's score is compared with another's and posture reorders "
    "nothing (a posture-aware order would be a new recommendation rule, which is "
    "owner-reserved)."
)

_HOWTO_TARGETS = (
    "GET /api/gameplan?team=<ownerId> builds and caches this team's targets for the "
    "current league bundle; the plan reads them warm-only and never runs that solve."
)
_HOWTO_WAIVERS = (
    "POST /api/waiver/perfect with this teamOwnerId builds and caches the plan for "
    "two minutes; the plan reads that cache warm-only and never runs the optimizer."
)
_HOWTO_POSTURE = (
    "The league bundle is built after each board publish (trade-analysis warm pass) "
    "and by /api/gameplan; the plan never builds it."
)
_HOWTO_DRAFT_CAPITAL = (
    "GET /api/draft-capital builds and caches the board (the default league's board is "
    "also rebuilt after each publish); the plan reads that cache warm-only."
)

_PICK_ACTIONS_NOTE = (
    "No existing owner turns one team's draft capital or posture into a pick "
    "recommendation: the finder's posture-aware pick generator answers only against a "
    "named counterparty. Defining that rule is an owner decision, so pick actions are "
    "not assessed; draft capital is shown as context."
)

_AGING_REASON = (
    "the age-portfolio owner flags this room as meaningfully older than league peers "
    "(isOldForLeague: value-weighted age at least a year above the league median; "
    "the owner labels the rule PRIOR)"
)


@dataclass(frozen=True)
class OwnerRead:
    """One owner's answer as the route obtained it.

    ``payload`` is the owner's own output, untouched.  ``reason`` set means
    the owner could not answer (a cold cache, a refusal, an error), and the
    section built from it is unavailable with that reason.
    """

    payload: Any = None
    reason: str | None = None
    freshness: str | None = None
    meta: Mapping[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.reason is None and self.payload is not None


def _unavailable(owner: str, reason: str | None, **extra: Any) -> dict[str, Any]:
    return {
        "available": False,
        "unavailableReason": reason or "owner_unavailable",
        "owner": owner,
        **extra,
    }


def _split(
    item: Mapping[str, Any], subject_keys: Sequence[str], uncertainty_keys: Sequence[str]
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """``(subject, evidence, uncertainty)`` from one owner item, verbatim.

    Every field the owner published lands in exactly one of the three; nothing
    is renamed, rounded or rebuilt, so no caveat can be dropped on the way.
    """
    subject = {k: item[k] for k in subject_keys if k in item}
    uncertainty = {k: item[k] for k in uncertainty_keys if k in item}
    taken = {*subject_keys, *uncertainty_keys}
    evidence = {k: v for k, v in item.items() if k not in taken}
    return subject, evidence, uncertainty


def _action(
    kind: str,
    owner: str,
    owner_rank: int,
    *,
    subject: Mapping[str, Any],
    reason: Any,
    evidence: Mapping[str, Any],
    uncertainty: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "kind": kind,
        "owner": owner,
        "ownerRank": owner_rank,
        "subject": dict(subject),
        "reason": reason,
        "evidence": dict(evidence),
        "uncertainty": dict(uncertainty),
    }


# ── Context sections ─────────────────────────────────────────────────


def _posture_section(read: OwnerRead) -> dict[str, Any]:
    if not read.available:
        extra = {"howTo": _HOWTO_POSTURE} if read.reason == "league_bundle_not_warm" else {}
        return _unavailable(POSTURE_OWNER, read.reason, **extra)
    return {
        "available": True,
        "unavailableReason": None,
        "owner": POSTURE_OWNER,
        "bundleFreshness": read.freshness,
        "posture": dict(read.payload),
        "appliedToOrdering": False,
        "note": (
            "context only: posture does not reorder, filter or re-weight any action "
            "(a posture-aware plan would be a new rule, which is owner-reserved)"
        ),
    }


def _block_available(block: Mapping[str, Any]) -> bool:
    """An owner block is available unless it says otherwise -- or is absent."""
    return bool(block) and block.get("available") is not False


def _block_reason(block: Mapping[str, Any]) -> str | None:
    if not block:
        return "owner_returned_no_block"
    if block.get("available") is False:
        return block.get("unavailableReason") or "owner_unavailable"
    return None


def _roster_sections(read: OwnerRead) -> dict[str, dict[str, Any]]:
    """Team Strength, Team Weakness and the age portfolio, verbatim."""
    if not read.available:
        return {
            "teamStrength": _unavailable(STRENGTH_OWNER, read.reason),
            "teamWeakness": _unavailable(WEAKNESS_OWNER, read.reason),
            "agePortfolio": _unavailable(AGE_OWNER, read.reason),
        }
    payload = read.payload
    team = payload.get("team") or {}
    shared = {
        "rosterSource": payload.get("rosterSource"),
        "unpricedVisibility": payload.get("unpricedVisibility"),
    }
    weakness = dict(team.get("weakness") or {})
    age = dict(team.get("agePortfolio") or {})
    return {
        "teamStrength": {
            "available": True,
            "unavailableReason": None,
            "owner": STRENGTH_OWNER,
            "strength": dict(team.get("strength") or {}),
            "teamCount": payload.get("teamCount"),
            "rankPopulation": payload.get("rankPopulation"),
            **shared,
        },
        "teamWeakness": {
            "available": _block_available(weakness),
            "unavailableReason": _block_reason(weakness),
            "owner": WEAKNESS_OWNER,
            "weakness": weakness,
            **shared,
        },
        "agePortfolio": {
            "available": _block_available(age),
            "unavailableReason": _block_reason(age),
            "owner": AGE_OWNER,
            "portfolio": age,
            **shared,
        },
    }


def _draft_capital_section(
    read: OwnerRead, owner_id: str, team_block: Mapping[str, Any] | None
) -> dict[str, Any]:
    """This team's draft-capital rows plus its pick-ownership state."""
    block = team_block or {}
    pick_ownership = {
        "state": block.get("pickOwnershipState"),
        "reason": block.get("pickOwnershipReason"),
        "owner": PICK_OWNERSHIP_OWNER,
    }
    if not read.available:
        extra = {"howTo": _HOWTO_DRAFT_CAPITAL} if read.reason == "draft_capital_not_warm" else {}
        return _unavailable(DRAFT_CAPITAL_OWNER, read.reason, pickOwnership=pick_ownership, **extra)
    payload = read.payload
    if isinstance(payload, Mapping) and payload.get("error"):
        return _unavailable(
            DRAFT_CAPITAL_OWNER, str(payload.get("error")), pickOwnership=pick_ownership
        )

    def _team_row(rows: Any) -> dict[str, Any] | None:
        mine = [
            r
            for r in (rows if isinstance(rows, list) else [])
            if isinstance(r, Mapping) and str(r.get("ownerId") or "") == str(owner_id)
        ]
        # Exactly one row, or none: the owner leaves ``ownerId`` empty on an
        # ambiguous display name, and a guessed row would be another team's.
        return dict(mine[0]) if len(mine) == 1 else None

    upcoming = _team_row(payload.get("teamTotals"))
    all_years = _team_row(payload.get("allYearsTeamTotals"))
    policy = payload.get("budgetPolicy") if isinstance(payload.get("budgetPolicy"), Mapping) else {}
    return {
        "available": True,
        "unavailableReason": None,
        "owner": DRAFT_CAPITAL_OWNER,
        "freshness": read.freshness,
        "upcomingDraftYear": payload.get("upcomingDraftYear"),
        "coveredPickYears": payload.get("coveredPickYears"),
        "teamTotalsState": payload.get("teamTotalsState"),
        "teamTotalsReason": payload.get("teamTotalsReason"),
        "budgetBasis": policy.get("basis"),
        "budgetStatus": policy.get("status"),
        "upcomingClass": upcoming,
        "upcomingClassUnavailableReason": (
            None if upcoming is not None else "team_not_matched_in_draft_capital"
        ),
        "allYears": all_years,
        "allYearsUnavailableReason": (
            None if all_years is not None else "team_not_matched_in_draft_capital"
        ),
        "pickOwnership": pick_ownership,
    }


# ── Action sections ──────────────────────────────────────────────────


def _buy_targets_section(read: OwnerRead) -> dict[str, Any]:
    if not read.available:
        extra = {"howTo": _HOWTO_TARGETS} if read.reason == "gameplan_targets_not_warm" else {}
        return _unavailable(TARGETS_OWNER, read.reason, actions=[], **extra)
    payload = read.payload
    targets = [
        t
        for t in payload.get("targetPlayers") or []
        if isinstance(t, Mapping) and t.get("recommended") is True
    ]
    actions = []
    for owner_rank, target in enumerate(targets, start=1):
        subject, evidence, uncertainty = _split(
            target,
            ("playerId", "name", "position"),
            ("confidence", "marketEdge", "availability"),
        )
        evidence.pop("reason", None)
        actions.append(
            _action(
                BUY_TARGET,
                TARGETS_OWNER,
                owner_rank,
                subject=subject,
                reason=target.get("reason"),
                evidence=evidence,
                uncertainty=uncertainty,
            )
        )
    coverage = payload.get("coverage") if isinstance(payload.get("coverage"), Mapping) else {}
    limitations = (
        payload.get("limitations") if isinstance(payload.get("limitations"), Mapping) else {}
    )
    candidate_policy = coverage.get("candidatePolicy") or {}
    return {
        "available": True,
        "unavailableReason": None,
        "owner": TARGETS_OWNER,
        "freshness": read.freshness,
        "sourceStamp": (payload.get("timing") or {}).get("sourceStamp"),
        "corroborationYield": coverage.get("corroborationYield"),
        "candidatePolicyExhaustive": candidate_policy.get("exhaustive"),
        "marketEdgeUnmeasured": coverage.get("marketEdgeUnmeasured"),
        "limitations": limitations.get("targets"),
        "actions": actions,
    }


def _suggestions_refusal(payload: Mapping[str, Any]) -> str | None:
    """The engine's refusal reason, or ``None`` when its generators ran.

    The early returns (lineup unresolved, every outgoing asset constrained, an
    unsatisfiable lock) never run a generator, and only the completed path
    stamps ``assetPoolSize``.  An empty ``sellHigh`` from a completed run is a
    real answer; a refusal is not, and must never read as "nothing to sell".
    """
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), Mapping) else {}
    if "assetPoolSize" in meta:
        return None
    return str(meta.get("noResultReason") or "suggestions_refused")


def _sell_high_section(read: OwnerRead) -> dict[str, Any]:
    if not read.available:
        return _unavailable(SUGGESTIONS_OWNER, read.reason, actions=[])
    payload = read.payload
    refusal = _suggestions_refusal(payload)
    if refusal is not None:
        return _unavailable(
            SUGGESTIONS_OWNER,
            refusal,
            actions=[],
            warnings=list(payload.get("warnings") or []),
        )
    meta = payload.get("metadata") or {}
    actions = []
    for owner_rank, suggestion in enumerate(payload.get("sellHigh") or [], start=1):
        if not isinstance(suggestion, Mapping):
            continue
        subject = {
            "give": [p.get("name") for p in suggestion.get("give") or [] if isinstance(p, Mapping)],
            "receive": [
                p.get("name") for p in suggestion.get("receive") or [] if isinstance(p, Mapping)
            ],
        }
        _s, evidence, uncertainty = _split(suggestion, ("type",), ("confidence",))
        evidence.pop("rationale", None)
        actions.append(
            _action(
                SELL_HIGH,
                SUGGESTIONS_OWNER,
                owner_rank,
                subject=subject,
                reason=suggestion.get("rationale"),
                evidence=evidence,
                uncertainty=uncertainty,
            )
        )
    return {
        "available": True,
        "unavailableReason": None,
        "owner": SUGGESTIONS_OWNER,
        "freshness": read.freshness,
        "ownerNoResultReason": meta.get("noResultReason"),
        "needSource": meta.get("needSource"),
        "boardTopNFilter": meta.get("boardTopNFilter"),
        "rosterUnpriced": meta.get("rosterUnpriced"),
        "constraintsBlockedOutgoing": meta.get("constraintsBlockedOutgoing"),
        "constraintsBlockedReasons": meta.get("constraintsBlockedReasons"),
        "warnings": list(payload.get("warnings") or []),
        "actions": actions,
    }


def _waivers_section(read: OwnerRead) -> dict[str, Any]:
    if not read.available:
        extra = {"howTo": _HOWTO_WAIVERS} if read.reason == "perfect_waivers_not_warm" else {}
        return _unavailable(WAIVERS_OWNER, read.reason, actions=[], **extra)
    payload = read.payload
    plan = payload.get("plan") if isinstance(payload.get("plan"), Mapping) else {}
    moves = plan.get("moves")
    if not isinstance(moves, list):
        return _unavailable(WAIVERS_OWNER, "perfect_waivers_payload_malformed", actions=[])
    solver = payload.get("solver") if isinstance(payload.get("solver"), Mapping) else {}
    stop_rule = payload.get("stopRule") if isinstance(payload.get("stopRule"), Mapping) else {}
    budget = payload.get("budget") if isinstance(payload.get("budget"), Mapping) else {}
    plan_uncertainty = {
        "solverProvenOptimal": solver.get("provenOptimal"),
        "solverStatus": solver.get("status"),
        "stopBandClass": stop_rule.get("stopBandClass"),
        "budgetState": budget.get("state"),
    }
    actions = []
    for owner_rank, move in enumerate(moves, start=1):
        if not isinstance(move, Mapping):
            continue
        add = move.get("add") if isinstance(move.get("add"), Mapping) else {}
        subject = {
            "add": {k: add[k] for k in ("playerId", "name", "position") if k in add},
            "release": move.get("release"),
        }
        bid = add.get("bid") if isinstance(add.get("bid"), Mapping) else {}
        actions.append(
            _action(
                WAIVER_MOVE,
                WAIVERS_OWNER,
                owner_rank,
                subject=subject,
                reason=None,
                evidence=dict(move),
                uncertainty={"bidConfidence": bid.get("confidence"), **plan_uncertainty},
            )
        )
    return {
        "available": True,
        "unavailableReason": None,
        "owner": WAIVERS_OWNER,
        "freshness": read.freshness,
        "advisoryOnly": payload.get("advisoryOnly"),
        "rosterSource": payload.get("rosterSource"),
        "rostersAsOf": payload.get("rostersAsOf"),
        "stopRule": dict(stop_rule),
        "budget": dict(budget),
        "planSummary": {k: v for k, v in plan.items() if k != "moves"},
        "actions": actions,
    }


def _aging_section(roster: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
    age = roster["agePortfolio"]
    if not age["available"]:
        return _unavailable(AGING_OWNER, age.get("unavailableReason"), actions=[])
    portfolio = age.get("portfolio") or {}
    rooms = [
        r
        for r in portfolio.get("byPosition") or []
        if isinstance(r, Mapping) and r.get("isOldForLeague") is True
    ]
    actions = []
    for owner_rank, room in enumerate(rooms, start=1):
        subject, evidence, uncertainty = _split(room, ("position",), ("coverage",))
        evidence.pop("isOldForLeague", None)
        uncertainty["ruleStatus"] = "PRIOR"
        uncertainty["youngCoreIndexStatus"] = portfolio.get("youngCoreIndexStatus")
        actions.append(
            _action(
                AGING_ASSET_RISK,
                AGING_OWNER,
                owner_rank,
                subject=subject,
                reason=_AGING_REASON,
                evidence=evidence,
                uncertainty=uncertainty,
            )
        )
    return {
        "available": True,
        "unavailableReason": None,
        "owner": AGING_OWNER,
        "valueWeightedCoreAge": portfolio.get("valueWeightedCoreAge"),
        "youngCoreIndex": portfolio.get("youngCoreIndex"),
        "youngCoreIndexStatus": portfolio.get("youngCoreIndexStatus"),
        "actions": actions,
    }


def _pick_actions_section() -> dict[str, Any]:
    return _unavailable(
        "none (no single-team pick-action owner exists)",
        "no_canonical_pick_action_owner",
        actions=[],
        note=_PICK_ACTIONS_NOTE,
    )


# ── Composition ──────────────────────────────────────────────────────


def _interleave(sections: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Round-robin over :data:`KIND_ORDER`, each owner's order kept."""
    lanes = [list(sections[_SECTION_FOR_KIND[kind]].get("actions") or []) for kind in KIND_ORDER]
    return [action for tier in zip_longest(*lanes) for action in tier if action is not None]


def _do_nothing_action(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    return _action(
        DO_NOTHING,
        "src/api/team_plan.py (composition only)",
        1,
        subject={},
        reason=(
            "no candidate cleared any assessed owner's own bar; nothing here is a new "
            "threshold, it is the conjunction of the owners' empty answers"
        ),
        evidence={
            kind: {
                "owner": sections[_SECTION_FOR_KIND[kind]].get("owner"),
                "ownerNoResultReason": sections[_SECTION_FOR_KIND[kind]].get("ownerNoResultReason"),
            }
            for kind in OWNER_BACKED_KINDS
        },
        uncertainty={
            "notAssessed": [
                {"kind": PICK_ACTION, "reason": sections["pickActions"]["unavailableReason"]}
            ]
        },
    )


def protections_block(requester_owns_team: bool, constraints: Any | None) -> dict[str, Any]:
    """Whether the requester's trade protections bound this plan, and why.

    Never the protection LIST: a plan for another manager's team must not
    reveal anyone's protections, and the requester can read their own on
    ``/api/user/trade-protections``.
    """
    if not requester_owns_team:
        return {
            "applied": False,
            "reason": "requester_does_not_own_team",
            "owner": CONSTRAINTS_OWNER,
        }
    if constraints is None:
        return {"applied": False, "reason": "constraints_not_resolved", "owner": CONSTRAINTS_OWNER}
    return {
        "applied": True,
        "reason": None,
        "active": bool(getattr(constraints, "active", False)),
        "resolutionFailed": bool(getattr(constraints, "resolution_failed", False)),
        "owner": CONSTRAINTS_OWNER,
    }


def compose_team_plan(
    *,
    league_key: str,
    owner_id: str,
    team_block: Mapping[str, Any] | None,
    requester_owns_team: bool,
    constraints: Any | None,
    roster_freshness: Mapping[str, Any],
    posture: OwnerRead,
    roster_intelligence: OwnerRead,
    buy_targets: OwnerRead,
    sell_high: OwnerRead,
    waivers: OwnerRead,
    draft_capital: OwnerRead,
) -> dict[str, Any]:
    """Compose one team's plan from the owners' answers.  Computes nothing."""
    block = team_block or {}
    roster = _roster_sections(roster_intelligence)
    sections = {
        "buyTargets": _buy_targets_section(buy_targets),
        "sellHigh": _sell_high_section(sell_high),
        "waivers": _waivers_section(waivers),
        "pickActions": _pick_actions_section(),
        "agingAssets": _aging_section(roster),
    }
    merged = _interleave(sections)
    unassessed = [
        {"kind": kind, "reason": sections[_SECTION_FOR_KIND[kind]]["unavailableReason"]}
        for kind in OWNER_BACKED_KINDS
        if not sections[_SECTION_FOR_KIND[kind]]["available"]
    ]
    if merged:
        plan_state = "actions"
    elif not unassessed:
        plan_state = DO_NOTHING
        merged = [_do_nothing_action(sections)]
    else:
        plan_state = "incomplete"
    actions = [{"rank": rank, **action} for rank, action in enumerate(merged, start=1)]

    warnings: list[str] = []
    state = roster_freshness.get("state")
    if state != "current":
        warnings.append(
            f"rosters are {state}: every roster-derived section describes the snapshot "
            "named in rosterFreshness, not necessarily today's rosters"
        )
    if unassessed:
        warnings.append(
            "not every action kind could be assessed (see completeness.unassessed); "
            "an absent action of those kinds is unknown, not 'nothing to do'"
        )

    return {
        "contractVersion": TEAM_PLAN_CONTRACT_VERSION,
        "flag": FLAG,
        "available": True,
        "leagueKey": league_key,
        "team": {
            "ownerId": str(owner_id),
            "teamName": str(block.get("name") or block.get("sleeperTeamName") or ""),
            "rosterId": block.get("roster_id", block.get("rosterId")),
        },
        "requesterOwnsTeam": bool(requester_owns_team),
        "advisoryOnly": True,
        "isVerdict": False,
        "rosterFreshness": {**dict(roster_freshness), "owner": FRESHNESS_OWNER},
        "posture": _posture_section(posture),
        **roster,
        "draftCapital": _draft_capital_section(draft_capital, owner_id, team_block),
        "sections": sections,
        "actions": actions,
        "planState": plan_state,
        "completeness": {
            "complete": not unassessed,
            "assessedKinds": [
                kind
                for kind in OWNER_BACKED_KINDS
                if sections[_SECTION_FOR_KIND[kind]]["available"]
            ],
            "unassessed": unassessed,
            "notAssessable": [
                {"kind": PICK_ACTION, "reason": sections["pickActions"]["unavailableReason"]}
            ],
        },
        "ordering": {"kindOrder": list(KIND_ORDER), "rule": _ORDERING_RULE},
        "protections": protections_block(requester_owns_team, constraints),
        "warnings": warnings,
    }


def out_of_scope_payload(league_key: str) -> dict[str, Any]:
    """The explicit answer for a league the plan does not serve."""
    return {
        "contractVersion": TEAM_PLAN_CONTRACT_VERSION,
        "flag": FLAG,
        "available": False,
        "unavailableReason": "league_not_in_scope",
        "leagueKey": league_key,
        "inScopeLeagues": sorted(IN_SCOPE_LEAGUE_KEYS),
        "note": (
            "The team plan serves dynasty_main only (owner scope correction 2026-10-18); "
            "no plan is computed for any other league."
        ),
    }
