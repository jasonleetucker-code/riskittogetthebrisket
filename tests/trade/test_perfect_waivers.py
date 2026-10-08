"""Perfect Waivers (C7-WAIV-01) — the jointly optimal add/drop combination.

What these pin, in the order the manifest's acceptance asks for them:

* **the matching test** — instances where the jointly optimal set differs
  from greedy best-free-agent-first, and a greedy baseline written here
  FAILS them (lineup interaction, budget knapsack);
* **exactness** — the solver equals brute-force enumeration on randomized
  small instances, budget and lineup constraints included;
* **Perfect Draft parity** — where no add changes lineup legality the plan
  is the k-decomposition (best k adds within budget minus the cheapest k
  cuts of the canonical cut ladder);
* capacity / taxi / unknown cap, FAAB budget, protection, unpriced, the stop
  rule, the pairing, and the node-limit label.
"""

from __future__ import annotations

import itertools
import json
import os
import random
import subprocess
import sys
from pathlib import Path

import pytest

from src.draft.displacement import RosterAsset, build_cut_ladder
from src.ros.lineup import RosterPlayer, solve_optimal_assignment
from src.trade.constraints import UNRESOLVED, resolve_constraints
from src.trade import perfect_waivers as pw_module
from src.trade.perfect_waivers import (
    FreeAgentCandidate,
    RosterCandidate,
    build_perfect_waivers,
    materiality_multiplier,
    solve_perfect_waivers,
)

T = 0.15  # config/trade/perfect_waivers.json::stopBand (a declared PRIOR)
RHO = materiality_multiplier(T)


def R(pid, pos, value, locked=None, fp=()):
    return RosterCandidate(
        player_id=pid,
        name=pid,
        position=pos,
        value=value,
        fantasy_positions=tuple(fp),
        locked_reason=locked,
    )


def F(pid, pos, value, bid=0, fp=()):
    return FreeAgentCandidate(
        player_id=pid, name=pid, position=pos, value=value, bid=bid, fantasy_positions=tuple(fp)
    )


def solve(roster, fas, slots, *, open_spots=0, budget=100, node_limit=2000):
    return solve_perfect_waivers(
        roster,
        fas,
        starter_slots=slots,
        open_spots=open_spots,
        budget=budget,
        materiality_ratio=T,
        node_limit=node_limit,
    )


def _fill(players, slots):
    pool = [
        RosterPlayer(
            player_id=p.player_id, canonical_name=p.name, position=p.position, ros_value=0.0
        )
        for p in players
    ]
    return len(solve_optimal_assignment(pool, list(slots)))


def _net(res):
    return sum(fa.value for fa in res.adds) - sum(rc.value for rc in res.drops)


# ── The matching test: greedy best-FA-first fails ───────────────────


def _greedy_best_fa_first(roster, fas, slots, open_spots, budget):
    """The baseline the inventory calls naive: take free agents best-first and
    pair each with the lowest-valued player whose release is legal on the
    CURRENT roster, accepting any positive gain."""
    current = list(roster)
    spent = 0
    net = 0.0
    base = _fill(current, slots)
    for fa in sorted(fas, key=lambda f: -f.value):
        if spent + fa.bid > budget:
            continue
        if open_spots > 0:
            current.append(R(fa.player_id, fa.position, fa.value))
            open_spots -= 1
            spent += fa.bid
            net += fa.value
            continue
        for d in sorted(
            (r for r in current if not r.locked_reason), key=lambda r: (r.value, r.player_id)
        ):
            if _fill([r for r in current if r is not d], slots) < base:
                continue
            if fa.value > d.value:
                current = [r for r in current if r is not d] + [
                    R(fa.player_id, fa.position, fa.value)
                ]
                spent += fa.bid
                net += fa.value - d.value
            break
    return net


def test_lineup_interaction_beats_greedy_best_free_agent_first():
    """The only tight end is weak; a free-agent tight end can replace him, but
    only a plan that sees the ADD can legally release him.  Greedy grabs the
    best free agent (a WR worth barely more than a bench WR) and then cannot
    pair the tight end with anything but an expensive WR."""
    roster = [
        R("qb", "QB", 8000),
        R("te_weak", "TE", 1000),
        R("wr1", "WR", 3000),
        R("wr2", "WR", 2800),
    ]
    fas = [F("wr_fa", "WR", 2900), F("te_fa", "TE", 2500)]
    slots = ["QB", "TE"]
    res = solve(roster, fas, slots)
    assert res.proven_optimal
    assert [a.player_id for a in res.adds] == ["te_fa"]
    assert [d.player_id for d in res.drops] == ["te_weak"]
    assert _net(res) == 1500

    greedy = _greedy_best_fa_first(roster, fas, slots, 0, 100)
    assert greedy == 100  # the WR swap, then stuck
    assert _net(res) > greedy


def test_budget_knapsack_beats_greedy_best_free_agent_first():
    """Two good claims beat one great claim the budget can only afford alone."""
    roster = [R("qb", "QB", 8000), R("b1", "WR", 1000), R("b2", "WR", 1000)]
    fas = [F("star", "WR", 3000, bid=10), F("a", "WR", 2600, bid=5), F("b", "WR", 2600, bid=5)]
    res = solve(roster, fas, ["QB"], budget=10)
    assert res.proven_optimal
    assert sorted(a.player_id for a in res.adds) == ["a", "b"]
    assert _net(res) == 3200
    assert sum(a.bid for a in res.adds) <= 10
    assert _greedy_best_fa_first(roster, fas, ["QB"], 0, 10) == 2000


# ── Exactness against brute force ───────────────────────────────────


def _brute_force(roster, fas, slots, open_spots, budget):
    """Max of sum V(adds) + rho * sum c(kept roster) over every legal plan."""
    base = _fill(roster, slots)
    droppable = [r for r in roster if not r.locked_reason and r.value]
    best = None
    for na in range(len(fas) + 1):
        for adds in itertools.combinations(fas, na):
            if budget is None and any(a.bid > 0 for a in adds):
                continue
            if budget is not None and sum(a.bid for a in adds) > budget:
                continue
            for nd in range(len(droppable) + 1):
                if na > open_spots + nd:
                    continue
                for drops in itertools.combinations(droppable, nd):
                    kept = [r for r in roster if r not in drops]
                    final = kept + [R(a.player_id, a.position, a.value) for a in adds]
                    if slots and _fill(final, slots) < base:
                        continue
                    obj = sum(a.value for a in adds) + RHO * sum(r.value or 0 for r in kept)
                    if best is None or obj > best:
                        best = obj
    return best


@pytest.mark.parametrize("seed", range(40))
def test_solver_equals_brute_force(seed):
    rng = random.Random(seed)
    positions = ["QB", "RB", "WR", "TE"]
    slot_menu = [["QB", "RB"], ["QB", "WR", "FLEX"], ["RB", "TE", "SUPER_FLEX"], ["TE"]]
    slots = rng.choice(slot_menu)
    roster = []
    for i in range(rng.randint(3, 6)):
        locked = "protected_individual" if rng.random() < 0.15 else None
        value = None if rng.random() < 0.1 else float(rng.randint(200, 4000))
        if value is None:
            locked = "unpriced_value_unknown"
        roster.append(R(f"r{i}", rng.choice(positions), value, locked=locked))
    fas = [
        F(
            f"f{i}",
            rng.choice(positions),
            float(rng.randint(300, 4000)),
            bid=rng.choice([0, 0, 3, 7, 12]),
        )
        for i in range(rng.randint(1, 5))
    ]
    open_spots = rng.choice([0, 0, 1, 2])
    budget = rng.choice([None, 0, 5, 10, 25])
    res = solve(roster, fas, slots, open_spots=open_spots, budget=budget)
    assert res.proven_optimal
    expected = _brute_force(roster, fas, slots, open_spots, budget)
    assert res.objective == pytest.approx(expected, abs=1e-6)
    # The returned plan is itself legal and affordable.
    final = [r for r in roster if r not in res.drops] + [
        R(a.player_id, a.position, a.value) for a in res.adds
    ]
    assert _fill(final, slots) >= _fill(roster, slots)
    assert len(res.adds) <= open_spots + len(res.drops)
    assert sum(a.bid for a in res.adds) <= (budget or 0)
    assert not any(d.locked_reason for d in res.drops)


# ── Perfect Draft parity where no add changes legality ──────────────


def test_matches_the_k_decomposition_when_lineup_is_not_in_play():
    """A deep roster: every cut is legal with or without the adds, so the
    plan must equal Perfect Draft's framing — best k adds within budget minus
    the cheapest (k − open) rungs of the canonical cut ladder."""
    roster = [R("qb", "QB", 9000), R("qb2", "QB", 7000)] + [
        R(f"w{i}", "WR", float(v)) for i, v in enumerate([400, 900, 1300, 1700, 2600, 5000])
    ]
    fas = [
        F("a", "WR", 3100, bid=30),
        F("b", "WR", 2400, bid=10),
        F("c", "WR", 2000, bid=0),
        F("d", "WR", 1500, bid=0),
        F("e", "WR", 1450, bid=20),
    ]
    slots = ["QB", "WR"]
    open_spots, budget = 1, 35
    assets = [
        RosterAsset(player_id=r.player_id, name=r.name, position=r.position, board_value=r.value)
        for r in roster
    ]
    ladder = build_cut_ladder(assets, slots, {})
    costs = sorted(rung.base_value for rung in ladder.rungs)
    best = 0.0  # objective delta over doing nothing, under rho
    for k in range(len(fas) + 1):
        cuts = max(0, k - open_spots)
        if cuts > len(costs):
            break
        add_best = max(
            (
                sum(f.value for f in combo)
                for combo in itertools.combinations(fas, k)
                if sum(f.bid for f in combo) <= budget
            ),
            default=None,
        )
        if add_best is None:
            continue
        best = max(best, add_best - RHO * sum(costs[:cuts]))
    res = solve(roster, fas, slots, open_spots=open_spots, budget=budget)
    baseline = RHO * sum(r.value for r in roster)
    assert res.objective - baseline == pytest.approx(best)


# ── Stop rule ───────────────────────────────────────────────────────


def test_immaterial_swap_is_not_proposed_and_the_stop_is_explained():
    """2100 vs 2000 is a 4.9% gap — inside the agreement ratio — so the plan
    stops, and names that swap as the next move it declined."""
    roster = [R("qb", "QB", 8000), R("wr", "WR", 2000)]
    res = solve(roster, [F("fa", "WR", 2100)], ["QB"])
    assert res.adds == [] and res.drops == []
    assert res.next_move is not None
    assert res.next_move["reason"] == "within_uncertainty"
    assert res.next_move["relativeGap"] == pytest.approx(100 / 2050)


def test_material_swap_is_proposed():
    roster = [R("qb", "QB", 8000), R("wr", "WR", 2000)]
    res = solve(roster, [F("fa", "WR", 2400)], ["QB"])  # 18.2% gap
    assert [a.player_id for a in res.adds] == ["fa"]
    assert res.pairs[0]["material"] is True
    assert res.pairs[0]["relativeGap"] > T


def test_threshold_is_the_algebraic_form_of_the_relative_gap():
    for v, c in [(2300, 2000), (2400, 2000), (1000, 860), (1000, 861)]:
        material = v > RHO * c
        gap = (v - c) / ((v + c) / 2)
        assert material == (gap > T)


def test_open_spot_add_is_always_material_and_next_move_says_no_positive_move():
    roster = [R("qb", "QB", 8000)]
    res = solve(roster, [F("fa", "WR", 600)], ["QB"], open_spots=1)
    assert [a.player_id for a in res.adds] == ["fa"]
    assert res.pairs[0]["releaseKind"] == "openSpot"
    assert res.open_spots_used == 1


# ── Pairing: each claim stands alone ────────────────────────────────


def test_pairs_are_the_legal_matching_not_lowest_value_for_everything():
    roster = [
        R("qb", "QB", 8000),
        R("te_weak", "TE", 900),
        R("wr_low", "WR", 300),
        R("wr", "WR", 4000),
    ]
    fas = [F("te_fa", "TE", 2600), F("wr_fa", "WR", 2500)]
    res = solve(roster, fas, ["QB", "TE"])
    assert {a.player_id for a in res.adds} == {"te_fa", "wr_fa"}
    assert {d.player_id for d in res.drops} == {"te_weak", "wr_low"}
    by_add = {p["add"].split(":", 2)[2]: p["release"].split(":", 2)[2] for p in res.pairs}
    # The TE add must carry the TE release: if the TE claim fails, keeping
    # te_weak keeps the lineup legal; pairing it with wr_low would not.
    assert by_add["te_fa"] == "te_weak"
    assert all(p["standsAlone"] for p in res.pairs)
    assert all(p["material"] for p in res.pairs)


# ── Protection, unpriced, capacity, budget ──────────────────────────


def test_protected_player_is_never_dropped():
    roster = [
        R("qb", "QB", 8000),
        R("fav", "WR", 300, locked="protected_individual"),
        R("wr", "WR", 1500),
    ]
    res = solve(roster, [F("fa1", "WR", 3000), F("fa2", "WR", 2900)], ["QB"])
    assert "fav" not in {d.player_id for d in res.drops}
    assert [d.player_id for d in res.drops] == ["wr"]


def test_unpriced_roster_player_is_never_dropped():
    roster = [R("qb", "QB", 8000), R("ghost", "WR", None, locked="unpriced_value_unknown")]
    res = solve(roster, [F("fa", "WR", 5000)], ["QB"])
    assert res.drops == [] and res.adds == []


def test_no_open_spots_means_no_pure_adds():
    roster = [R("qb", "QB", 8000), R("wr", "WR", 9000)]
    res = solve(roster, [F("fa", "WR", 3000)], ["QB"], open_spots=0)
    assert res.adds == []


def test_budget_is_respected_and_unknown_budget_withholds_paid_claims():
    roster = [R("qb", "QB", 8000), R("b1", "WR", 500), R("b2", "WR", 500)]
    fas = [F("paid", "WR", 4000, bid=40), F("free", "WR", 2000, bid=0)]
    res = solve(roster, fas, ["QB"], budget=39)
    assert [a.player_id for a in res.adds] == ["free"]
    res = solve(roster, fas, ["QB"], budget=40)
    assert {a.player_id for a in res.adds} == {"paid", "free"}
    res = solve(roster, fas, ["QB"], budget=None)
    assert [a.player_id for a in res.adds] == ["free"]
    assert any("FAAB balance unknown" in n for n in res.notes)


def test_node_limit_is_labelled_never_presented_as_optimal():
    roster = [R("qb", "QB", 8000)] + [R(f"b{i}", "WR", 300 + i) for i in range(6)]
    fas = [F(f"f{i}", "WR", 3000 - 37 * i, bid=7 + (i * 5) % 11) for i in range(8)]
    res = solve(roster, fas, ["QB"], budget=20, node_limit=0)
    if res.status == "optimal":
        pytest.skip("root relaxation was already budget-feasible")
    assert res.status == "node_limit"
    assert res.proven_optimal is False
    assert res.upper_bound >= res.objective
    assert any("NOT proven optimal" in n for n in res.notes)


# ── The payload builder over a contract ─────────────────────────────


def _row(pid, name, pos, value, *, team="XX", sources=3):
    return {
        "playerId": pid,
        "displayName": name,
        "canonicalName": name,
        "legacyRef": name,
        "position": pos,
        "team": team,
        "rankDerivedValue": value,
        "sourceCount": sources,
        "assetClass": "offense",
    }


def _contract(*, faab=50, roster=None):
    roster = roster or ["Star QB", "Weak TE", "Bench WR", "Deep WR", "Ghost"]
    rows = [
        _row("qb1", "Star QB", "QB", 8000),
        _row("te1", "Weak TE", "TE", 900),
        _row("wr1", "Bench WR", "WR", 3000),
        _row("wr2", "Deep WR", "WR", 400),
        _row("fa1", "Free TE", "TE", 2600),
        _row("fa2", "Free WR", "WR", 2500),
        _row("fa3", "Nobody Knows", "WR", None),
        _row("o1", "Other QB", "QB", 7000),
    ]
    return {
        "meta": {"leagueKey": "pw"},
        "playersArray": rows,
        "sleeper": {
            "rosterPositions": ["QB", "TE", "BN", "BN", "BN", "BN"],
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


def _targets(contract, bids=None):
    bids = bids or {}
    out = {"by_position": {}, "bidMethodology": "market_aware"}
    rostered = {n for t in contract["sleeper"]["teams"] for n in t["players"]}
    for row in contract["playersArray"]:
        if row["displayName"] in rostered or not row["rankDerivedValue"]:
            continue
        b = bids.get(row["displayName"], 0)
        out["by_position"].setdefault(row["position"], []).append(
            {
                "name": row["displayName"],
                "position": row["position"],
                "consensusValue": row["rankDerivedValue"],
                "bid": {"aggressive": b, "reasonable": b, "lowball": b},
                "clearing": 0,
                "maxRational": b,
                "confidence": "medium",
            }
        )
    return out


def _build(contract, *, roster_settings=None, constraints=None, bids=None):
    return build_perfect_waivers(
        contract,
        league_key="pw",
        owner_id="me",
        waiver_targets=_targets(contract, bids),
        constraints=constraints,
        roster_settings=roster_settings if roster_settings is not None else {"rosterSize": 5},
    )


def test_payload_plans_the_matching_and_reports_unpriced():
    out = _build(_contract())
    plan = out["plan"]
    moves = {m["add"]["name"]: m["release"].get("name") for m in plan["moves"]}
    assert moves["Free TE"] == "Weak TE"
    assert plan["netValueGain"] > 0
    assert out["advisoryOnly"] is True
    assert out["solver"]["provenOptimal"] is True
    # Ghost did not join the board: unpriced, never dropped.
    assert "Ghost" in {r["name"] for r in out["unpriced"]["rosterPlayers"]}
    assert "Ghost" not in {m["release"].get("name") for m in plan["moves"]}
    # An unpriced free agent is reported, never valued at zero.
    assert out["unpriced"]["freeAgents"] >= 1
    assert "Nobody Knows" in out["unpriced"]["freeAgentSample"]
    assert out["stopRule"]["source"] == "config/trade/perfect_waivers.json::stopBand"
    assert out["stopRule"]["stopBandClass"] == "PRIOR"
    json.dumps(out)  # serialisable as-is


def test_payload_protected_player_never_dropped():
    contract = _contract()
    cons = resolve_constraints(contract=contract, persistent={"untouchables": ["Weak TE"]})
    out = _build(contract, constraints=cons)
    released = {m["release"].get("name") for m in out["plan"]["moves"]}
    assert "Weak TE" not in released
    assert {r["name"] for r in out["constraints"]["protectedOnRoster"]} == {"Weak TE"}


def test_payload_unresolved_constraints_propose_no_drop():
    out = _build(_contract(), constraints=UNRESOLVED)
    assert out["plan"]["dropCount"] == 0
    assert out["constraints"]["resolutionFailed"] is True


def test_payload_unknown_cap_makes_no_capacity_claim():
    out = _build(_contract(roster=["Star QB", "Weak TE", "Deep WR"]), roster_settings={})
    assert out["capacity"]["state"] == "unknown"
    assert out["capacity"]["rosterLimit"] is None
    # No open spot is assumed: every add carries a drop.
    assert out["plan"]["openSpotsUsed"] == 0
    assert all(m["release"]["kind"] == "drop" for m in out["plan"]["moves"])


def test_payload_open_spot_from_known_cap():
    out = _build(
        _contract(roster=["Star QB", "Weak TE", "Deep WR"]), roster_settings={"rosterSize": 4}
    )
    assert out["capacity"]["openSpotsPlanned"] == 1
    assert out["plan"]["openSpotsUsed"] == 1


def test_payload_taxi_unknown_is_partial_and_conservative():
    out = _build(
        _contract(roster=["Star QB", "Weak TE", "Deep WR"]),
        roster_settings={"rosterSize": 4, "taxiSize": 2},
    )
    assert out["capacity"]["state"] == "partial"
    assert out["capacity"]["openSpotsPlanned"] == 1  # the fewest possible
    assert any("taxi occupancy is unknown" in n for n in out["notes"])


def test_payload_budget_known_and_unknown():
    contract = _contract(faab=10)
    out = _build(contract, bids={"Free TE": 20, "Free WR": 5})
    assert out["budget"]["state"] == "known"
    assert out["plan"]["totalRecommendedBid"] <= 10
    assert "Free TE" not in {m["add"]["name"] for m in out["plan"]["moves"]}

    contract = _contract(faab=None)
    out = _build(contract, bids={"Free TE": 20, "Free WR": 0})
    assert out["budget"]["state"] == "unknown"
    assert out["budget"]["balance"] is None
    assert out["plan"]["totalRecommendedBid"] == 0


def test_payload_unknown_team_raises():
    with pytest.raises(ValueError, match="unknown_team"):
        build_perfect_waivers(
            _contract(), league_key="pw", owner_id="nobody", waiver_targets={}, roster_settings={}
        )


# ── R2: the stop band is this feature's own declared PRIOR ──────────


REPO = Path(__file__).resolve().parents[2]


def test_stop_band_is_read_from_the_features_own_config():
    doc = json.loads((REPO / "config/trade/perfect_waivers.json").read_text(encoding="utf-8"))
    assert doc["stopBandClass"] == "PRIOR"
    assert "not calibrated" in doc["stopBandRationale"]
    assert pw_module.load_stop_band() == doc["stopBand"]
    # Not the confidence gate: the module never reads it.
    src = (REPO / "src/trade/perfect_waivers.py").read_text(encoding="utf-8")
    assert "gate_parameter" not in src


def test_stop_band_value_reaches_the_plan(monkeypatch, tmp_path):
    cfg = tmp_path / "pw.json"
    cfg.write_text(json.dumps({"stopBand": 0.5, "stopBandClass": "PRIOR"}), encoding="utf-8")
    monkeypatch.setattr(pw_module, "_CONFIG_PATH", cfg)
    out = _build(_contract())
    assert out["stopRule"]["agreementRatio"] == 0.5
    assert out["stopRule"]["swapMultiplier"] == pytest.approx(materiality_multiplier(0.5))


@pytest.mark.parametrize(
    "content",
    [None, "{not json", json.dumps({"stopBandClass": "PRIOR"}), json.dumps({"stopBand": 0.15})],
)
def test_missing_or_undeclared_stop_band_refuses(monkeypatch, tmp_path, content):
    cfg = tmp_path / "pw.json"
    if content is not None:
        cfg.write_text(content, encoding="utf-8")
    monkeypatch.setattr(pw_module, "_CONFIG_PATH", cfg)
    with pytest.raises(pw_module.PerfectWaiversConfigError):
        _build(_contract())


# ── R3: pairs are legal in BOTH directions, deterministically ───────


def test_pair_must_also_be_legal_when_only_this_claim_wins():
    """Fail-on-old: the previous pairing checked only "this claim alone
    fails" and paired the QB add with the WR release.  If only the QB claim
    wins, the roster loses a FLEX-capable body — a QB cannot play FLEX — and
    fills one slot fewer.  The WR release must ride with a TE add."""
    roster = [
        R("r0", "WR", 2197),
        R("r1", "QB", 3059, locked="protected_individual"),
        R("r2", "WR", 2418),
        R("r3", "TE", 3646, locked="protected_individual"),
    ]
    fas = [
        F("f0", "TE", 4163),
        F("f1", "RB", 3168),
        F("f2", "RB", 2007),
        F("f3", "WR", 2793),
        F("f4", "QB", 4498),
        F("f5", "TE", 4119),
    ]
    res = solve(roster, fas, ["QB", "WR", "FLEX", "FLEX"], open_spots=2)
    by_release = {p["release"]: p["add"].split(":", 2)[2] for p in res.pairs}
    assert by_release["r:0:r0"] in {"f0", "f5"}, by_release
    assert all(p["failsAloneLegal"] and p["winsAloneLegal"] for p in res.pairs)


@pytest.mark.parametrize("seed", range(150))
def test_a_both_directions_pairing_exists_and_is_returned(seed):
    """Brute force: for the plan returned, a bijection legal in both
    directions exists (strong base orderability), and the solver returns one."""
    rng = random.Random(1000 + seed)
    positions = ["QB", "RB", "WR", "TE"]
    slots = rng.choice(
        [["QB", "WR", "FLEX"], ["QB", "WR", "FLEX", "FLEX"], ["RB", "TE", "SUPER_FLEX"]]
    )
    roster = [
        R(
            f"r{i}",
            rng.choice(positions),
            float(rng.randint(200, 4000)),
            locked="protected_individual" if rng.random() < 0.2 else None,
        )
        for i in range(rng.randint(3, 6))
    ]
    fas = [
        F(f"f{i}", rng.choice(positions), float(rng.randint(300, 4500)))
        for i in range(rng.randint(1, 5))
    ]
    res = solve(roster, fas, slots, open_spots=rng.choice([0, 1, 2]))
    if not res.pairs:
        return
    base = _fill(roster, slots)
    adds = list(res.adds)
    releases = list(res.drops) + [None] * res.open_spots_used

    def fails_alone(a, d):
        kept = [r for r in roster if r not in res.drops or r is d]
        others = [x for x in adds if x is not a]
        return _fill(kept + [R(x.player_id, x.position, x.value) for x in others], slots) >= base

    def wins_alone(a, d):
        kept = [r for r in roster if r is not d]
        return _fill(kept + [R(a.player_id, a.position, a.value)], slots) >= base

    exists = any(
        all(fails_alone(a, d) and wins_alone(a, d) for a, d in zip(adds, perm))
        for perm in itertools.permutations(releases)
    )
    assert exists
    assert all(p["standsAlone"] for p in res.pairs)


def _repro_case():
    """Reviewer's repro: QB/WR/FLEX, the WR the only droppable player, the RBs
    protected; the plan adds three QBs and a TE."""
    roster = [
        R("wr", "WR", 300),
        R("rb1", "RB", 3000, locked="protected_individual"),
        R("rb2", "RB", 2800, locked="protected_individual"),
    ]
    fas = [F("qb1", "QB", 4000), F("qb2", "QB", 3900), F("qb3", "QB", 3800), F("te", "TE", 3500)]
    return roster, fas, ["QB", "WR", "FLEX"], 3


def test_reviewer_repro_pairs_are_legal_both_ways():
    roster, fas, slots, open_spots = _repro_case()
    res = solve(roster, fas, slots, open_spots=open_spots)
    assert sorted(a.player_id for a in res.adds) == ["qb1", "qb2", "qb3", "te"]
    assert [d.player_id for d in res.drops] == ["wr"]
    assert all(p["standsAlone"] for p in res.pairs)


_SUBPROCESS = (
    "import json, sys\n"
    "sys.path.insert(0, ROOT)\n"
    "from tests.trade.test_perfect_waivers import _repro_case, solve\n"
    "roster, fas, slots, open_spots = _repro_case()\n"
    "res = solve(roster, fas, slots, open_spots=open_spots)\n"
    "print(json.dumps([[p['add'], p['release']] for p in res.pairs]))\n"
)


def test_pairing_does_not_depend_on_pythonhashseed():
    outputs = set()
    for seed in ("0", "1", "2", "3", "12345"):
        env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONUTF8="1")
        proc = subprocess.run(
            [sys.executable, "-c", f"ROOT = {str(REPO)!r}\n" + _SUBPROCESS],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(REPO),
            timeout=120,
            check=True,
        )
        outputs.add(proc.stdout.strip().splitlines()[-1])
    assert len(outputs) == 1, outputs


# ── F4 / F5: identity join and the waiver pool's own filters ────────


def test_fa_join_requires_name_and_position():
    contract = _contract()
    # A same-named DIFFERENT player at another position sits first on the board.
    contract["playersArray"].insert(0, _row("dup1", "Free TE", "LB", 9000))
    out = _build(contract)
    by_pos = {
        m["add"]["position"]: m["add"]["playerId"]
        for m in out["plan"]["moves"]
        if m["add"]["name"] == "Free TE"
    }
    # Each candidate joins to the board row with ITS position — never to
    # whichever same-named row came first.
    assert by_pos["TE"] == "fa1"
    assert by_pos.get("LB", "dup1") == "dup1"


def test_fa_join_with_two_same_name_same_position_players_is_ambiguous():
    contract = _contract()
    contract["playersArray"].append(_row("fa1b", "Free TE", "TE", 1000))
    out = _build(contract)
    assert "Free TE" not in {m["add"]["name"] for m in out["plan"]["moves"]}
    # The pool emits one candidate per board row; both are refused.
    assert out["freeAgentExclusions"]["planJoin"]["identity_ambiguous"] == 2
    assert out["freeAgentExclusions"]["identityAmbiguous"] == ["Free TE"]


def test_waiver_pool_filters_are_disclosed_by_reason():
    contract = _contract()
    contract["playersArray"] += [
        _row("lo", "Low Guy", "WR", 300),
        _row("one", "One Source", "WR", 2000, sources=1),
        _row("k1", "Kicker", "K", 900),
    ]
    out = _build(contract)
    pool = out["freeAgentExclusions"]["waiverPool"]
    assert pool["below_min_value"] == 1
    assert pool["single_source"] == 1
    assert pool["kicker_def_excluded"] == 1
    assert pool["unpriced"] >= 1


def test_partial_baseline_fill_is_disclosed():
    roster, fas, slots, open_spots = _repro_case()
    res = solve(roster, fas, slots, open_spots=open_spots)
    assert res.baseline_fill < len(slots)
    assert any("not necessarily the same slots" in n for n in res.notes)
