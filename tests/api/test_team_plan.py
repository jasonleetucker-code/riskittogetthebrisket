"""The composed Team Advisor plan (``src/api/team_plan.py``) — composition only.

What matters here:

* every action carries its owner's fields VERBATIM (nothing renamed, rounded
  or rebuilt) and the owner it came from;
* the order is the documented kind interleave, each owner's own order kept,
  with no weight, score or threshold of the composer's own;
* every unavailable owner is an explicit section with a reason — never an
  empty list that reads as "nothing to do" — and ``do_nothing`` is asserted
  only when every owner-backed kind was assessed;
* the module performs no arithmetic on anything it is handed (AST guard).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.api import team_plan as tp
from src.api.team_plan import OwnerRead

_REPO = Path(__file__).resolve().parents[2]


# ── Owner payload builders (shapes copied from each owner's to_dict) ──


def _target(pid: str, *, recommended: bool = True, priority: float = 1.0) -> dict:
    return {
        "playerId": pid,
        "name": f"Player {pid}",
        "position": "WR",
        "recommended": recommended,
        "reason": f"corroborated by lineup_fit; adds 2.00 pts ({pid})",
        "signals": ["lineup_fit"],
        "corroborating": ["lineup_fit"],
        "lineupGain": 2.0,
        "marketEdge": None,
        "availability": None,
        "confidence": 0.5,
        "priority": priority,
        "notes": [],
        "modelVersion": "wsj.targets.2026-07-27.v1",
    }


def _gameplan(targets: list[dict]) -> dict:
    return {
        "targetPlayers": targets,
        "coverage": {
            "corroborationYield": {"recommended": 1, "evaluated": len(targets)},
            "candidatePolicy": {"exhaustive": False},
            "marketEdgeUnmeasured": {"reason": "no ROS price"},
        },
        "limitations": {"targets": {"scope": "current season"}},
        "timing": {"sourceStamp": "stamp-1"},
    }


def _suggestion(give: str, receive: str) -> dict:
    return {
        "type": "sell_high",
        "give": [{"name": give, "position": "RB", "displayValue": 5000}],
        "receive": [{"name": receive, "position": "WR", "displayValue": 5100}],
        "giveTotal": 5000,
        "receiveTotal": 5100,
        "gap": 100,
        "fairness": "even",
        "rationale": f"sell {give}",
        "whyThisHelps": "converts surplus",
        "confidence": "medium",
        "strategy": "balanced",
        "rankScore": {"total": 1.0},
    }


def _suggestions(sell: list[dict], *, completed: bool = True, reason: str | None = None) -> dict:
    meta = {"noResultReason": reason} if reason else {}
    if completed:
        meta.update({"assetPoolSize": 150, "boardTopNFilter": 150, "needSource": {"source": "x"}})
    return {"sellHigh": sell, "buyLow": [], "metadata": meta, "warnings": []}


def _move(pid: str) -> dict:
    return {
        "add": {
            "playerId": pid,
            "name": f"FA {pid}",
            "position": "LB",
            "value": 2562.0,
            "bid": {"recommended": None, "confidence": "medium", "balanceState": "unknown"},
        },
        "release": {"kind": "drop", "playerId": "r1", "name": "Rel", "position": "LB"},
        "gain": 967.0,
        "relativeGap": 0.4652,
        "material": True,
        "standsAlone": True,
    }


def _perfect(moves: list[dict]) -> dict:
    return {
        "advisoryOnly": True,
        "plan": {"moves": moves, "addCount": len(moves)},
        "solver": {"status": "optimal", "provenOptimal": True},
        "stopRule": {"stopBandClass": "PRIOR", "nextBestMove": None},
        "budget": {"state": "unknown"},
        "rosterSource": "live_overlay",
        "rostersAsOf": "2026-11-21T10:00:00+00:00",
    }


def _room(pos: str, old: bool) -> dict:
    return {
        "position": pos,
        "value": 9000.0,
        "valueShare": 0.2,
        "valueWeightedAge": 29.5 if old else 24.0,
        "youthScore": 0.3,
        "coverage": {"aged": 3, "total": 3},
        "leagueRank": 1,
        "leaguePercentile": 0.1,
        "leagueMedianAge": 26.0,
        "ageVsLeagueMedian": 3.5 if old else -2.0,
        "isOldForLeague": old,
    }


def _roster_intel(rooms: list[dict], *, age_available: bool = True) -> dict:
    return {
        "teamCount": 4,
        "rankPopulation": "contract_board_priced_players",
        "rosterSource": "canonical_contract",
        "unpricedVisibility": "never zero",
        "team": {
            "strength": {"total": 30000.0, "leagueRank": 2},
            "weakness": {"available": True, "needs": [{"position": "TE", "level": "high"}]},
            "agePortfolio": {
                "available": age_available,
                "unavailableReason": None if age_available else "no_aged_players",
                "youngCoreIndex": 40.0,
                "youngCoreIndexStatus": "PRIOR",
                "valueWeightedCoreAge": 26.4,
                "byPosition": rooms,
            },
        },
    }


def _draft_capital(owner_rows: list[str]) -> dict:
    return {
        "teamTotals": [
            {"team": f"T{i}", "auctionDollars": 100, "rosterId": i, "ownerId": oid}
            for i, oid in enumerate(owner_rows)
        ],
        "allYearsTeamTotals": [
            {"team": f"T{i}", "auctionDollars": 300, "rank": 1, "ownerId": oid}
            for i, oid in enumerate(owner_rows)
        ],
        "teamTotalsState": "available",
        "teamTotalsReason": None,
        "upcomingDraftYear": 2027,
        "coveredPickYears": [2027],
        "budgetPolicy": {"basis": "per_class_pool", "status": "owner_confirmed"},
    }


_FRESH = {"state": "current", "source": "live", "fetchedAt": "x", "ageHours": 1.0}


def _compose(**overrides):
    kwargs = dict(
        league_key="dynasty_main",
        owner_id="o0",
        team_block={"name": "Team o0", "roster_id": 1, "pickOwnershipState": "observed"},
        requester_owns_team=True,
        constraints=None,
        roster_freshness=_FRESH,
        posture=OwnerRead(payload={"label": "PUSH"}, freshness="last_computed"),
        roster_intelligence=OwnerRead(payload=_roster_intel([_room("QB", True)])),
        buy_targets=OwnerRead(payload=_gameplan([_target("t1"), _target("t2")])),
        sell_high=OwnerRead(payload=_suggestions([_suggestion("A", "B")])),
        waivers=OwnerRead(payload=_perfect([_move("w1"), _move("w2"), _move("w3")])),
        draft_capital=OwnerRead(payload=_draft_capital(["o0", "o1"]), freshness="current"),
    )
    kwargs.update(overrides)
    return tp.compose_team_plan(**kwargs)


# ── Ordering ─────────────────────────────────────────────────────────


def test_actions_interleave_by_kind_keeping_each_owners_order():
    plan = _compose()
    kinds = [(a["kind"], a["ownerRank"]) for a in plan["actions"]]
    assert kinds == [
        ("buy_target", 1),
        ("sell_high", 1),
        ("waiver_move", 1),
        ("aging_asset_risk", 1),
        ("buy_target", 2),
        ("waiver_move", 2),
        ("waiver_move", 3),
    ]
    assert [a["rank"] for a in plan["actions"]] == list(range(1, 8))
    assert plan["planState"] == "actions"
    assert plan["ordering"]["kindOrder"] == list(tp.KIND_ORDER)


def test_owner_order_is_kept_even_when_a_field_would_sort_it_differently():
    """The composer never re-sorts an owner's list (no score comparison)."""
    targets = [_target("low", priority=0.1), _target("high", priority=9.0)]
    plan = _compose(buy_targets=OwnerRead(payload=_gameplan(targets)))
    buys = [a["subject"]["playerId"] for a in plan["actions"] if a["kind"] == "buy_target"]
    assert buys == ["low", "high"]


def test_only_recommended_targets_become_actions():
    targets = [_target("yes"), _target("no", recommended=False)]
    plan = _compose(buy_targets=OwnerRead(payload=_gameplan(targets)))
    assert [a["subject"]["playerId"] for a in plan["sections"]["buyTargets"]["actions"]] == ["yes"]


def test_posture_does_not_reorder_actions():
    push = _compose(posture=OwnerRead(payload={"label": "PUSH"}))
    rebuild = _compose(posture=OwnerRead(payload={"label": "REBUILD"}))
    strip = lambda p: [(a["kind"], a["ownerRank"]) for a in p["actions"]]  # noqa: E731
    assert strip(push) == strip(rebuild)
    assert push["posture"]["appliedToOrdering"] is False


# ── Verbatim pass-through ────────────────────────────────────────────


def test_buy_target_fields_pass_through_verbatim():
    target = _target("t1")
    plan = _compose(buy_targets=OwnerRead(payload=_gameplan([target])))
    action = plan["sections"]["buyTargets"]["actions"][0]
    assert action["owner"] == tp.TARGETS_OWNER
    assert action["reason"] == target["reason"]
    merged = {**action["subject"], **action["evidence"], **action["uncertainty"]}
    merged["reason"] = action["reason"]
    assert merged == target


def test_sell_high_and_waiver_fields_pass_through_verbatim():
    s = _suggestion("A", "B")
    m = _move("w1")
    plan = _compose(
        sell_high=OwnerRead(payload=_suggestions([s])),
        waivers=OwnerRead(payload=_perfect([m])),
    )
    sell = plan["sections"]["sellHigh"]["actions"][0]
    assert sell["subject"] == {"give": ["A"], "receive": ["B"]}
    assert sell["uncertainty"] == {"confidence": "medium"}
    rebuilt = {**sell["evidence"], **sell["uncertainty"], "rationale": sell["reason"]}
    assert {**rebuilt, "type": "sell_high"} == s
    wave = plan["sections"]["waivers"]["actions"][0]
    assert wave["evidence"] == m
    assert wave["uncertainty"]["solverProvenOptimal"] is True
    assert wave["uncertainty"]["bidConfidence"] == "medium"
    assert wave["uncertainty"]["stopBandClass"] == "PRIOR"


def test_aging_actions_are_exactly_the_owners_flagged_rooms():
    rooms = [_room("QB", True), _room("RB", False), _room("WR", True)]
    plan = _compose(roster_intelligence=OwnerRead(payload=_roster_intel(rooms)))
    aging = plan["sections"]["agingAssets"]["actions"]
    assert [a["subject"]["position"] for a in aging] == ["QB", "WR"]
    assert aging[0]["evidence"]["ageVsLeagueMedian"] == rooms[0]["ageVsLeagueMedian"]
    assert aging[0]["uncertainty"]["ruleStatus"] == "PRIOR"
    assert aging[0]["owner"] == tp.AGING_OWNER


def test_context_sections_carry_the_owners_blocks():
    plan = _compose()
    assert plan["teamStrength"]["strength"] == {"total": 30000.0, "leagueRank": 2}
    assert plan["teamWeakness"]["weakness"]["needs"][0]["position"] == "TE"
    assert plan["agePortfolio"]["portfolio"]["youngCoreIndexStatus"] == "PRIOR"
    assert plan["posture"]["posture"] == {"label": "PUSH"}
    dc = plan["draftCapital"]
    assert dc["upcomingClass"]["ownerId"] == "o0" and dc["allYears"]["auctionDollars"] == 300
    assert dc["pickOwnership"]["state"] == "observed"


# ── Unavailable states ───────────────────────────────────────────────


@pytest.mark.parametrize(
    ("override", "section", "reason", "has_howto"),
    [
        ("buy_targets", "buyTargets", "gameplan_targets_not_warm", True),
        ("waivers", "waivers", "perfect_waivers_not_warm", True),
        ("sell_high", "sellHigh", "suggestions_error", False),
    ],
)
def test_cold_or_failed_action_owners_are_explicit(override, section, reason, has_howto):
    plan = _compose(**{override: OwnerRead(reason=reason)})
    sec = plan["sections"][section]
    assert sec["available"] is False and sec["unavailableReason"] == reason
    assert sec["actions"] == []
    assert ("howTo" in sec) is has_howto
    assert plan["completeness"]["complete"] is False
    assert any(u["reason"] == reason for u in plan["completeness"]["unassessed"])


@pytest.mark.parametrize("reason", ["league_lineup_unresolved", "all_outgoing_assets_constrained"])
def test_suggestion_refusals_are_unavailable_not_empty(reason):
    payload = _suggestions([], completed=False, reason=reason)
    plan = _compose(sell_high=OwnerRead(payload=payload))
    sec = plan["sections"]["sellHigh"]
    assert sec["available"] is False and sec["unavailableReason"] == reason


def test_a_completed_empty_sell_high_is_a_real_answer():
    payload = _suggestions([], reason="no_need_positions")
    sec = _compose(sell_high=OwnerRead(payload=payload))["sections"]["sellHigh"]
    assert sec["available"] is True and sec["actions"] == []
    assert sec["ownerNoResultReason"] == "no_need_positions"


def test_posture_not_warm_is_explicit():
    plan = _compose(posture=OwnerRead(reason="league_bundle_not_warm"))
    assert plan["posture"]["available"] is False
    assert plan["posture"]["unavailableReason"] == "league_bundle_not_warm"
    assert "howTo" in plan["posture"]


def test_roster_intelligence_unavailable_makes_every_dependent_section_unavailable():
    plan = _compose(roster_intelligence=OwnerRead(reason="team_not_in_contract"))
    for key in ("teamStrength", "teamWeakness", "agePortfolio"):
        assert plan[key]["available"] is False
        assert plan[key]["unavailableReason"] == "team_not_in_contract"
    assert plan["sections"]["agingAssets"]["available"] is False


def test_age_portfolio_owner_unavailable_is_carried():
    intel = _roster_intel([], age_available=False)
    plan = _compose(roster_intelligence=OwnerRead(payload=intel))
    assert plan["sections"]["agingAssets"]["unavailableReason"] == "no_aged_players"


@pytest.mark.parametrize(
    ("read", "reason"),
    [
        (OwnerRead(reason="draft_capital_not_warm"), "draft_capital_not_warm"),
        (OwnerRead(payload={"error": "pick_ownership_unavailable"}), "pick_ownership_unavailable"),
    ],
)
def test_draft_capital_unavailable_states(read, reason):
    dc = _compose(draft_capital=read)["draftCapital"]
    assert dc["available"] is False and dc["unavailableReason"] == reason
    assert dc["pickOwnership"]["state"] == "observed"


def test_an_ambiguous_or_missing_draft_capital_row_is_never_guessed():
    for owners in (["o1", "o2"], ["o0", "o0"]):
        dc = _compose(draft_capital=OwnerRead(payload=_draft_capital(owners)))["draftCapital"]
        assert dc["available"] is True
        assert dc["upcomingClass"] is None
        assert dc["upcomingClassUnavailableReason"] == "team_not_matched_in_draft_capital"


def test_pick_actions_are_reported_not_assessable():
    plan = _compose()
    sec = plan["sections"]["pickActions"]
    assert sec["available"] is False
    assert sec["unavailableReason"] == "no_canonical_pick_action_owner"
    assert plan["completeness"]["notAssessable"][0]["kind"] == "pick_action"


def test_stale_rosters_are_surfaced():
    stale = {"state": "stale", "source": "last_good", "fetchedAt": "x", "ageHours": 30.0}
    plan = _compose(roster_freshness=stale)
    assert plan["rosterFreshness"]["state"] == "stale"
    assert any("rosters are stale" in w for w in plan["warnings"])


# ── do nothing vs incomplete ─────────────────────────────────────────


def _empty_answers(**overrides):
    base = dict(
        buy_targets=OwnerRead(payload=_gameplan([_target("x", recommended=False)])),
        sell_high=OwnerRead(payload=_suggestions([], reason="no_need_positions")),
        waivers=OwnerRead(payload=_perfect([])),
        roster_intelligence=OwnerRead(payload=_roster_intel([_room("QB", False)])),
    )
    base.update(overrides)
    return base


def test_do_nothing_only_when_every_owner_backed_kind_was_assessed():
    plan = _compose(**_empty_answers())
    assert plan["planState"] == "do_nothing"
    assert [a["kind"] for a in plan["actions"]] == ["do_nothing"]
    action = plan["actions"][0]
    assert action["rank"] == 1
    assert set(action["evidence"]) == set(tp.OWNER_BACKED_KINDS)
    assert action["evidence"]["sell_high"]["ownerNoResultReason"] == "no_need_positions"
    assert action["uncertainty"]["notAssessed"][0]["kind"] == "pick_action"
    assert plan["completeness"]["complete"] is True


def test_empty_answers_with_a_cold_owner_are_incomplete_not_do_nothing():
    plan = _compose(**_empty_answers(waivers=OwnerRead(reason="perfect_waivers_not_warm")))
    assert plan["planState"] == "incomplete"
    assert plan["actions"] == []
    assert plan["completeness"]["unassessed"] == [
        {"kind": "waiver_move", "reason": "perfect_waivers_not_warm"}
    ]
    assert any("unknown, not 'nothing to do'" in w for w in plan["warnings"])


# ── Protections never leak ───────────────────────────────────────────


def test_protections_block_never_carries_a_list():
    from src.trade.constraints import resolve_constraints

    c = resolve_constraints(persistent={"untouchables": ["Secret Star"], "nflTeams": ["MIN"]})
    owned = tp.protections_block(True, c)
    assert owned["applied"] is True and owned["active"] is True
    other = tp.protections_block(False, c)
    assert other == {
        "applied": False,
        "reason": "requester_does_not_own_team",
        "owner": tp.CONSTRAINTS_OWNER,
    }
    for block in (owned, other):
        assert "Secret Star" not in json.dumps(block) and "MIN" not in json.dumps(block)


def test_out_of_scope_payload_is_explicit():
    body = tp.out_of_scope_payload("dynasty_new")
    assert body["available"] is False
    assert body["unavailableReason"] == "league_not_in_scope"
    assert body["inScopeLeagues"] == ["dynasty_main"]


def test_inputs_are_not_mutated():
    gameplan = _gameplan([_target("t1")])
    intel = _roster_intel([_room("QB", True)])
    before = json.dumps([gameplan, intel], sort_keys=True)
    _compose(
        buy_targets=OwnerRead(payload=gameplan),
        roster_intelligence=OwnerRead(payload=intel),
    )
    assert json.dumps([gameplan, intel], sort_keys=True) == before


# ── The composer computes nothing (AST guard) ────────────────────────

_AGGREGATES = {"sum", "min", "max", "round", "abs", "pow", "divmod", "float", "int"}


def _arithmetic_offenders(source: str) -> list[str]:
    """Arithmetic, aggregates, float literals and numeric imports in ``source``."""
    tree = ast.parse(source)
    # ``X | None`` in a type annotation is a BinOp too; annotations are not
    # values, so their subtrees are exempt (and only theirs).
    annotation_nodes: set[int] = set()
    for node in ast.walk(tree):
        annotations = []
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            every = [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]
            annotations = [a.annotation for a in every if a is not None and a.annotation]
            annotations.append(node.returns)
        elif isinstance(node, ast.AnnAssign):
            annotations = [node.annotation]
        for ann in annotations:
            if ann is not None:
                annotation_nodes.update(id(n) for n in ast.walk(ann))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if id(node) in annotation_nodes:
            continue
        if isinstance(node, (ast.BinOp, ast.AugAssign)):
            offenders.append(f"arithmetic at line {node.lineno}")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            offenders.append(f"unary arithmetic at line {node.lineno}")
        elif isinstance(node, ast.Constant) and isinstance(node.value, float):
            offenders.append(f"float literal at line {node.lineno}")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in _AGGREGATES:
                offenders.append(f"{node.func.id}() at line {node.lineno}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
            if any(n.split(".")[0] in {"math", "statistics", "numpy", "decimal"} for n in names):
                offenders.append(f"numeric import at line {node.lineno}")
    return offenders


def test_the_composer_performs_no_value_arithmetic():
    """No arithmetic operator, no aggregate builtin, no float literal and no
    numeric library anywhere in the composer: every number it publishes is an
    owner's, carried through.  (Integer literals are allowed for the 1-based
    ``enumerate`` start and the exactly-one-row test.)"""
    source = (_REPO / "src/api/team_plan.py").read_text(encoding="utf-8")
    offenders = _arithmetic_offenders(source)
    assert not offenders, offenders


@pytest.mark.parametrize(
    "snippet",
    [
        "x = a + b",
        "x = a * 0.5",
        "x += 1",
        "x = -a",
        "x = sum(v)",
        "x = max(a, b)",
        "x = 0.25",
        "import math",
        "from statistics import median",
    ],
)
def test_the_arithmetic_guard_catches_what_it_claims(snippet):
    assert _arithmetic_offenders(snippet)


def test_the_arithmetic_guard_exempts_only_annotations():
    assert _arithmetic_offenders("def f(a: int | None) -> str | None:\n    return None") == []
    assert _arithmetic_offenders("x: int | None = None") == []
    assert _arithmetic_offenders("y = a | b")


def test_the_composer_reads_no_global_state():
    """Pure: no I/O, no clock, no module state written."""
    source = (_REPO / "src/api/team_plan.py").read_text(encoding="utf-8")
    for forbidden in ("open(", "time.", "datetime", "global ", "requests", "urllib"):
        assert forbidden not in source, forbidden


def test_an_absent_owner_block_is_unavailable_not_assumed_present():
    intel = _roster_intel([_room("QB", True)])
    del intel["team"]["weakness"]
    intel["team"]["agePortfolio"] = {"available": False}
    plan = _compose(roster_intelligence=OwnerRead(payload=intel))
    assert plan["teamWeakness"]["available"] is False
    assert plan["teamWeakness"]["unavailableReason"] == "owner_returned_no_block"
    assert plan["agePortfolio"]["unavailableReason"] == "owner_unavailable"
    assert plan["sections"]["agingAssets"]["available"] is False
