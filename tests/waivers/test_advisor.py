"""Waiver Advisor (Workstream E) — a composer over the existing waiver owners.

Pins the contract of ``src/waivers/advisor.py``: it consumes Perfect Waivers,
the FAAB engine (through ``find_waiver_targets``), the lineup solver, roster
capacity, droppability and competitive posture, and states every absence
instead of inventing a number.  It never applies the owner-held forced-drop
cost and never runs a second bid formula.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from src.draft.context import contract_teams, match_team
from src.roster_intel.droppability import team_droppability
from src.trade.perfect_waivers import build_perfect_waivers
from src.trade.roster_capacity import build_capacity_context
from src.waivers import advisor as adv

_REPO = Path(__file__).resolve().parents[2]


def _row(pid, name, pos, value, **extra):
    row = {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": "XX",
        "rankDerivedValue": value,
        "sourceCount": 3,
        "assetClass": "offense",
        "confidenceBucket": "medium",
        "confidenceLabel": "Medium",
    }
    row.update(extra)
    return row


_POSITIONS = {
    "Star QB": "QB",
    "Weak TE": "TE",
    "Bench WR": "WR",
    "Deep WR": "WR",
    "Other QB": "QB",
}


def _contract(*, faab=50, roster=None, extra_rows=()):
    roster = roster or ["Star QB", "Weak TE", "Bench WR", "Deep WR", "Ghost"]
    rows = [
        _row("qb1", "Star QB", "QB", 8000),
        _row("te1", "Weak TE", "TE", 900),
        _row("wr1", "Bench WR", "WR", 3000),
        _row("wr2", "Deep WR", "WR", 400),
        _row(
            "fa1",
            "Free TE",
            "TE",
            2600,
            ktcMarket={"value": 2700, "normalizedValue": 2650, "rank": 120, "available": True},
        ),
        _row("fa2", "Free WR", "WR", 2500),
        _row("fa3", "Nobody Knows", "WR", None),
        _row("fa4", "Free LB", "LB", 1800, assetClass="idp"),
        _row("o1", "Other QB", "QB", 7000),
        *extra_rows,
    ]
    return {
        "meta": {"leagueKey": "pw"},
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": ["QB", "TE", "WR", "BN", "BN", "BN"],
            "positions": dict(_POSITIONS),
            "teams": [
                {
                    "ownerId": "me",
                    "name": "Mine",
                    "roster_id": 1,
                    "players": list(roster),
                    "playerIds": [],
                    "faabRemaining": faab,
                },
                {"ownerId": "them", "name": "Theirs", "roster_id": 2, "players": ["Other QB"]},
            ],
        },
    }


def _targets(contract, *, methodology="market_aware", bids=None):
    bids = bids or {}
    out = {"by_position": {}, "bidMethodology": methodology}
    rostered = {n for t in contract["sleeper"]["teams"] for n in t["players"]}
    for row in contract["playersArray"]:
        if row["displayName"] in rostered or not row["rankDerivedValue"]:
            continue
        b = bids.get(row["displayName"], 0)
        market = methodology == "market_aware"
        out["by_position"].setdefault(row["position"], []).append(
            {
                "name": row["displayName"],
                "position": row["position"],
                "consensusValue": row["rankDerivedValue"],
                "isRookie": False,
                "bid": {"aggressive": b + 2, "reasonable": b, "lowball": max(0, b - 2)},
                "clearing": 7 if market else None,
                "clearingLow": 3 if market else None,
                "clearingHigh": 12 if market else None,
                "maxRational": 31 if market else None,
                "objectiveDollars": 40 if market else None,
                "confidence": "medium" if market else None,
            }
        )
    return out


class _StubPosture:
    def to_dict(self):
        return {
            "label": "RETOOL",
            "evidence": "measured",
            "confidence": 0.61,
            "probabilities": {"PUSH": 0.1, "HOLD": 0.2, "RETOOL": 0.6, "REBUILD": 0.1},
            "paramsVersion": "posture_v1_prior",
            "parameterStatus": "PRIOR",
        }


def _assemble(
    contract=None,
    *,
    roster_settings=None,
    methodology="market_aware",
    bids=None,
    postures=None,
    posture_reason="league_bundle_not_warm",
    position="ALL",
    limit=25,
    forced_on=False,
):
    contract = contract or _contract()
    roster_settings = {"rosterSize": 5} if roster_settings is None else roster_settings
    targets = _targets(contract, methodology=methodology, bids=bids)
    plan = build_perfect_waivers(
        contract,
        league_key="pw",
        owner_id="me",
        waiver_targets=targets,
        roster_settings=roster_settings,
    )
    team = match_team(contract_teams(contract), owner_id="me", roster_id=None, team_name=None)
    cap_ctx = build_capacity_context(
        contract,
        "pw",
        team,
        roster_settings=roster_settings or None,
        scarcity_reading=(None, "test: scarcity not supplied"),
    )
    return adv.assemble_waiver_advisor(
        contract,
        league_key="pw",
        owner_id="me",
        waiver_targets=targets,
        perfect_waivers=plan,
        droppability=team_droppability(contract, owner_id="me"),
        capacity_context=cap_ctx,
        scarcity=None,
        scarcity_reason="test: scarcity not supplied",
        postures=postures,
        posture_meta={"bundleFreshness": "current"} if postures else None,
        posture_unavailable_reason=None if postures else posture_reason,
        faab_inputs={"league_budget": 100, "team_count": 2, "starters_per_team": 3},
        forced_drop_selection_enabled=forced_on,
        position=position,
        limit=limit,
    )


def _by_name(out):
    return {c["name"]: c for c in out["candidates"]}


# ── ranking + identity ──────────────────────────────────────────────


def test_candidates_are_the_canonical_board_order_and_serialisable():
    out = _assemble()
    names = [c["name"] for c in out["candidates"]]
    assert names == ["Free TE", "Free WR", "Free LB"]
    values = [c["value"]["rankDerivedValue"] for c in out["candidates"]]
    assert values == sorted(values, reverse=True)
    assert out["advisoryOnly"] is True and out["valueScale"] == "rankDerivedValue"
    assert out["flag"] == "waiver_advisor"
    json.dumps(out)


def test_unpriced_free_agent_is_never_a_candidate_and_never_zero():
    out = _assemble()
    assert "Nobody Knows" not in _by_name(out)
    for c in out["candidates"]:
        assert c["value"]["rankDerivedValue"] > 0


def test_ambiguous_name_is_counted_never_guessed():
    contract = _contract(extra_rows=[_row("fa2b", "Free WR", "WR", 1500)])
    out = _assemble(contract)
    assert "Free WR" not in _by_name(out)
    assert out["census"]["excluded"].get("identity_ambiguous", 0) >= 1


def test_position_filter_uses_the_family_and_limit_is_honoured():
    out = _assemble(position="LB")
    assert [c["name"] for c in out["candidates"]] == ["Free LB"]
    assert out["census"]["matchingFilter"] == 1
    out = _assemble(limit=1)
    assert [c["name"] for c in out["candidates"]] == ["Free TE"]
    assert out["census"]["shown"] == 1 and out["census"]["poolCandidates"] == 3


def test_value_confidence_comes_from_the_row():
    c = _by_name(_assemble())["Free TE"]
    assert c["value"]["confidenceBucket"] == "medium"
    assert c["value"]["confidenceLabel"] == "Medium"
    assert c["playerId"] == "fa1"  # Player File navigation key


# ── plan (Perfect Waivers) ───────────────────────────────────────────


def test_plan_status_comes_from_perfect_waivers():
    out = _assemble()
    te = _by_name(out)["Free TE"]
    assert te["plan"]["status"] == "in_plan"
    assert te["plan"]["release"]["name"] == "Weak TE"
    assert out["plan"]["owner"] == "src/trade/perfect_waivers.py"
    assert out["plan"]["solver"]["provenOptimal"] is True
    statuses = {c["plan"]["status"] for c in out["candidates"]}
    assert statuses <= {"in_plan", "next_best_move", "not_in_plan"}


# ── lineup (exact solver) ─────────────────────────────────────────────


def test_lineup_impact_is_the_exact_solver_on_the_board_objective():
    out = _assemble()
    te = _by_name(out)["Free TE"]["lineup"]
    assert te["state"] == "evaluated"
    assert te["entersOptimalLineup"] is True
    assert te["slot"] == "TE"
    assert [p["name"] for p in te["leavesLineup"]] == ["Weak TE"]
    assert te["startingValueDelta"] == pytest.approx(2600 - 900)
    assert "rankDerivedValue" in te["objective"]
    # A WR below the starting WR does not start and moves nothing.
    wr = _by_name(out)["Free WR"]["lineup"]
    assert wr["entersOptimalLineup"] is False
    assert wr["leavesLineup"] == [] and wr["startingValueDelta"] == 0
    # No LB slot: an LB cannot start in this league.
    assert _by_name(out)["Free LB"]["lineup"]["entersOptimalLineup"] is False


def test_lineup_unavailable_without_slots_is_stated():
    contract = _contract()
    contract["sleeper"]["rosterPositions"] = []
    out = _assemble(contract, roster_settings={"rosterSize": 5, "starters": {}})
    lineup = _by_name(out)["Free TE"]["lineup"]
    assert lineup["state"] == "unavailable"
    assert "entersOptimalLineup" not in lineup


# ── capacity (forced drop, reported not applied) ──────────────────────


def test_full_roster_add_reports_forced_drop_and_never_applies_it():
    out = _assemble()
    for c in out["candidates"]:
        cap = c["capacity"]
        assert cap["application"] == "reported_not_applied"
        assert cap["requiresDrops"] is True
        assert cap["forcedDrops"], c["name"]
        assert cap["forcedDropCost"] is not None
    assert out["forcedDropPolicy"]["selectionEnabled"] is False
    assert out["forcedDropPolicy"]["application"] == "reported_not_applied"


def test_forced_drop_cost_never_reorders_candidates():
    plain = [c["name"] for c in _assemble()["candidates"]]
    flagged = [c["name"] for c in _assemble(forced_on=True)["candidates"]]
    assert plain == flagged
    assert _assemble(forced_on=True)["forcedDropPolicy"]["selectionEnabled"] is True


def test_unknown_cap_is_unknown_never_unlimited():
    out = _assemble(roster_settings={})
    cap = _by_name(out)["Free TE"]["capacity"]
    assert cap["rosterLimit"] is None
    assert cap["requiresDrops"] is None
    assert cap["state"] == "unknown"
    assert cap["forcedDropCost"] is None


def test_open_spot_add_requires_no_drop():
    out = _assemble(
        _contract(roster=["Star QB", "Weak TE", "Deep WR"]), roster_settings={"rosterSize": 4}
    )
    cap = _by_name(out)["Free TE"]["capacity"]
    assert cap["requiresDrops"] is False
    assert cap["forcedDrops"] == []
    assert cap["forcedDropCost"] == 0.0


# ── FAAB (engine numbers, separated) ──────────────────────────────────


def test_market_estimate_is_kept_apart_from_the_max_rational_bid():
    faab = _by_name(_assemble(bids={"Free TE": 5}))["Free TE"]["faab"]
    assert faab["state"] == "market_aware"
    assert faab["recommendedBid"] == 5
    exp = faab["expectedWinningBid"]
    assert exp["state"] == "estimated"
    assert (exp["low"], exp["median"], exp["high"]) == (3, 7, 12)
    assert "NOT this team's maximum offer" in exp["meaning"]
    assert faab["maxRationalBid"] == {
        "state": "available",
        "value": 31,
        "meaning": faab["maxRationalBid"]["meaning"],
    }
    assert faab["basis"] == "faab_engine_standalone_no_drop_side"


def test_ceiling_only_bid_withholds_market_numbers_never_zero():
    out = _assemble(methodology="ceiling_only_estimate", bids={"Free TE": 4})
    faab = _by_name(out)["Free TE"]["faab"]
    assert faab["state"] == "ceiling_only"
    assert faab["expectedWinningBid"]["state"] == "unavailable"
    assert faab["expectedWinningBid"]["median"] is None
    assert faab["maxRationalBid"]["state"] == "unavailable"
    assert faab["maxRationalBid"]["value"] is None
    assert any("ceiling-only" in n for n in out["notes"])


def test_team_faab_context_states_balance_option_value_and_history():
    out = _assemble()
    faab = out["faab"]
    assert faab["state"] == "known" and faab["remaining"] == 50
    assert faab["originalBudget"] == 100
    assert faab["bidHistory"]["state"] == "missing"
    so = faab["seasonOption"]
    assert so["owner"].endswith("season_option_value")
    # The list bids ran with no week: the engine's offseason branch.
    assert so["listBids"]["reason"].startswith("offseason")
    assert so["competitiveStatusUsed"] == "bubble"
    assert faab["crowdEvidence"]["state"] == "evaluated_per_pair_in_bid_desk"


def test_unknown_balance_is_unknown():
    out = _assemble(_contract(faab=None))
    assert out["faab"]["state"] == "unknown"
    assert out["faab"]["remaining"] is None


# ── market reference + replacement ───────────────────────────────────


def test_market_reference_is_the_ktc_benchmark_or_unavailable():
    c = _by_name(_assemble())
    te = c["Free TE"]["marketReference"]
    assert te["state"] == "available" and te["value"] == 2700
    assert te["source"] == "ktc_market_benchmark_non_voting"
    lb = c["Free LB"]["marketReference"]
    assert lb["state"] == "unavailable" and lb["value"] is None
    assert lb["reason"] == "no_ktc_coverage"


def test_replacement_level_comes_from_droppability():
    out = _assemble()
    rep = _by_name(out)["Free TE"]["replacement"]
    levels = out["replacementLevels"]["byPosition"]
    assert rep["waiverLevel"] == round(levels["TE"])
    assert rep["valueOverWaiverLevel"] == round(2600 - levels["TE"])
    # Scarcity not supplied: stated, not a 1.0 pretending to be measured.
    assert rep["scarcityMultiplier"] is None
    assert out["replacementLevels"]["scarcityState"] == "unavailable"


# ── posture (context only) ────────────────────────────────────────────


def test_posture_unavailable_is_named():
    out = _assemble()
    assert out["posture"]["state"] == "unavailable"
    assert out["posture"]["reason"] == "league_bundle_not_warm"
    assert out["posture"]["application"] == "context_only_not_applied_to_bids_or_ranking"


def test_posture_is_context_and_changes_no_number():
    with_p = _assemble(postures={"me": _StubPosture()})
    without = _assemble()
    assert with_p["posture"]["state"] == "available"
    assert with_p["posture"]["label"] == "RETOOL"
    assert with_p["posture"]["bundleFreshness"] == "current"
    assert with_p["candidates"] == without["candidates"]


def test_methodology_dependencies_are_declared():
    ids = {d["id"]: d["state"] for d in _assemble()["methodologyDependencies"]}
    assert ids["forced_drop_activation"] == "owner_held_off"
    assert ids["championship_probability_premium"] == "not_used_sim_uncalibrated"


# ── errors / gate / request parsing ─────────────────────────────────


def test_unknown_team_raises_never_another_teams_answer():
    contract = _contract()
    with pytest.raises(ValueError, match="unknown_team"):
        adv.assemble_waiver_advisor(
            contract,
            league_key="pw",
            owner_id="nobody",
            waiver_targets={},
            perfect_waivers={},
            droppability={},
            capacity_context=None,
            scarcity=None,
            scarcity_reason=None,
            postures=None,
            posture_meta=None,
            posture_unavailable_reason="x",
            faab_inputs={},
            forced_drop_selection_enabled=False,
        )


def test_gate_fails_closed_while_the_flag_is_unregistered(monkeypatch):
    from src.api import feature_flags

    if adv.FLAG not in feature_flags._DEFAULTS:
        assert adv.advisor_enabled() is False
    else:  # once the coordinator registers it, its default must be OFF
        assert feature_flags._DEFAULTS[adv.FLAG] is False
    monkeypatch.setitem(feature_flags._DEFAULTS, adv.FLAG, True)
    feature_flags.reload()
    try:
        assert adv.advisor_enabled() is True
    finally:
        monkeypatch.delitem(feature_flags._DEFAULTS, adv.FLAG, raising=False)
        feature_flags.reload()


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (None, {"teamOwnerId": None, "position": "ALL", "limit": 25}),
        (
            {"teamOwnerId": " 42 ", "position": "lb", "limit": 10},
            {"teamOwnerId": "42", "position": "LB", "limit": 10},
        ),
        ({"position": "K", "limit": "x"}, {"teamOwnerId": None, "position": "ALL", "limit": 25}),
        ({"limit": 5000}, {"teamOwnerId": None, "position": "ALL", "limit": 100}),
        ({"limit": True}, {"teamOwnerId": None, "position": "ALL", "limit": 25}),
    ],
)
def test_parse_advisor_request(body, expected):
    assert adv.parse_advisor_request(body) == expected


# ── end to end through the real owners ───────────────────────────────


def test_compute_runs_the_real_owners_on_one_snapshot():
    contract = _contract()
    inputs = {
        "teams": contract["sleeper"]["teams"],
        "roster_settings": {"rosterSize": 5},
        "league_budget": 100,
        "team_count": 2,
        "starters_per_team": 3,
        "starters": {"QB": 1, "TE": 1, "WR": 1},
        "roster_size": 5,
        "market_priors": None,
    }
    out = adv.compute_waiver_advisor(contract, league_key="pw", owner_id="me", inputs=inputs)
    assert out["faab"]["bidMethodology"] == "market_aware"
    assert out["candidates"], out["census"]
    assert out["posture"]["state"] == "unavailable"  # no bundle for a test league
    assert out["plan"]["available"] is True
    json.dumps(out)


# ── structure: no second owner ───────────────────────────────────────


def test_no_second_bid_formula_or_value_owner():
    src = (_REPO / "src/waivers/advisor.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", "")
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
    }
    # The engine's dollar path is reached only through find_waiver_targets.
    assert "recommend" not in called
    assert "_compute_faab_bid" not in called
    assert "recommend_faab" not in called
    # No feature flag is ever set from here.
    assert "setenv" not in src and "_DEFAULTS[" not in src
