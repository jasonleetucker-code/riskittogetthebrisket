"""I12 (Python half): the multi-team package-math parity fixture is exactly
what the Python owners produce, and the N-team engine agrees with it.

The JavaScript half reads the same file:
``frontend/__tests__/multi-team-package-parity.test.js``.
"""

from __future__ import annotations

import json

import pytest

from tests.trade import multi_team_parity_cases as gen


def test_fixture_is_current_against_the_python_owners():
    assert gen.OUT.exists(), "run python -m tests.trade.multi_team_parity_cases"
    assert gen.OUT.read_text(encoding="utf-8") == gen.serialize(gen.build()), (
        "multi_team_trade_parity_cases.json is stale; regenerate with "
        "python -m tests.trade.multi_team_parity_cases"
    )


def test_fixture_covers_the_shapes_the_spec_names():
    data = json.loads(gen.OUT.read_text(encoding="utf-8"))
    assert data["model"] == "geom_q078_v1"
    ids = {c["id"] for c in data["cases"]}
    for required in ("i14_one_to_many", "three_team_cycle_one_for_one", "four_team_cycle_mixed"):
        assert required in ids
    teams = [t for c in data["cases"] for t in c["teams"].values()]
    assert any(not t["receives"] for t in teams), "an empty-side team is required"
    assert any(t["expected"]["level"] == "fair" for t in teams)
    assert any(t["expected"]["sendVA"] > 0 or t["expected"]["recvVA"] > 0 for t in teams)


def test_i14_numbers_match_the_spec():
    data = json.loads(gen.OUT.read_text(encoding="utf-8"))
    case = next(c for c in data["cases"] if c["id"] == "i14_one_to_many")
    a, b, c = (case["teams"][k]["expected"] for k in "ABC")
    assert (round(a["gap"]), a["larger"], a["relativePct"], a["level"]) == (
        610,
        9610,
        6.35,
        "slight",
    )
    assert (round(b["gap"]), b["level"]) == (-1000, "unfair")
    assert (round(c["gap"]), c["level"]) == (500, "unfair")


def test_cycle_of_one_for_ones_sums_to_zero():
    data = json.loads(gen.OUT.read_text(encoding="utf-8"))
    case = next(c for c in data["cases"] if c["id"] == "three_team_cycle_one_for_one")
    assert sum(t["expected"]["gap"] for t in case["teams"].values()) == 0


@pytest.mark.parametrize("case_id", ["i14_one_to_many", "four_team_cycle_mixed"])
def test_engine_reproduces_the_fixture_on_a_synthetic_board(case_id):
    """The N-team engine's per-team market numbers equal the fixture's, so
    the engine and the browser mirror share one package rule."""
    from src.trade import analyze_service as svc
    from src.trade import trade_ledger as tl
    from tests.trade import multi_team_support as mts

    _cid, _desc, routes = next(t for t in gen.TRADES if t[0] == case_id)
    names = sorted({*routes, *(to for legs in routes.values() for _v, to in legs)})
    rid = {n: i + 1 for i, n in enumerate(names)}
    contract = mts.synthetic_league()
    rows = []
    teams = contract["sleeper"]["teams"]
    for t in teams:
        t["players"], t["playerIds"] = [], []
    legs = []
    for n, out in routes.items():
        for k, (value, to) in enumerate(out):
            pid = f"{rid[n]}{k:02d}"
            rows.append(
                {
                    "playerId": pid,
                    "displayName": f"P{pid}",
                    "canonicalName": f"P{pid}",
                    "assetClass": "offense",
                    "position": "WR",
                    "pos": "WR",
                    "rankDerivedValue": value,
                    "values": {"full": value},
                }
            )
            teams[rid[n] - 1]["players"].append(f"P{pid}")
            teams[rid[n] - 1]["playerIds"].append(pid)
            legs.append({"id": f"p:{pid}", "from": rid[n], "to": rid[to]})
    contract["playersArray"] = rows
    snap = mts.synthetic_snapshot(contract)
    ledger = tl.validate_ledger(
        snap, teams=sorted(rid.values()), legs=legs, policy=tl.LedgerPolicy()
    )
    out = svc.analyze_trade_n(snap, ledger, mode="market_fairness", counterfactuals=False)
    data = json.loads(gen.OUT.read_text(encoding="utf-8"))
    case = next(c for c in data["cases"] if c["id"] == case_id)
    for n in names:
        expected = case["teams"][n]["expected"]
        md = out["teams"][rid[n]]["analysis"]["lenses"]["market"]["detail"]
        assert md["vaAdjustedGap"] == int(round(expected["gap"]))
        assert md["band"]["level"] == expected["level"]
        assert md["sendingAdjusted"] == round(expected["sendAdj"], 1)
        assert md["receivingAdjusted"] == round(expected["recvAdj"], 1)
