"""D2: the private multi-team decision MATRIX — one named, readable scenario
per axis the build-mode brief lists, each asserting the exact per-team
answer of the ONE engine (``analyze_service.analyze_trade_n``).

``test_multi_team_properties`` proves the spec invariants I1-I20 by seeded
sweeps; this module is the complement a reviewer can read row by row: for each
scenario it states what every team gives and receives, what the package model
makes of it (checked against an independent oracle built from
``fairness_bands`` / ``package_model``, never the engine's own numbers), the
market-fairness state, and the final YES / NO / NO_TOO_CLOSE /
NOT_ENOUGH_EVIDENCE decision in each mode.

| row | axis |
|---|---|
| M01 | 2 teams, even 1-for-1 -> near-tie rule (NO, too close) |
| M02 | 2 teams, lopsided 1-for-1 |
| M03 | uneven packages (raw-even 2-for-1; Value Adjustment decides) |
| M04 | 3 teams, picks only, one class (cycle of 2027 1sts) |
| M05 | multiple same-class assets to one team (two "2027 Round 1") |
| M06 | 4 teams, mixed cycle; no trade-level number |
| M07 | roster constraints (over the cap) never move fairness or Asset-only |
| M08 | missing valuations (unknown, never 0) |
| M09 | league lineup settings never move canonical fairness |
| M10 | rebuilder vs contender (team goal) |
| M11 | Team Context on / off: fairness identical in every mode |
| M12 | fairness vs utility: roster-neutral value kept separate from utility |
| M13 | the final verdict is consistent with fairness in every row |

Everything is the LABELLED synthetic league of ``multi_team_support`` (values
invented for tests).  Team Context's roster lens is the LABELLED stand-in of
``test_multi_team_properties`` unless a row overrides it.  Methodology is
LOCKED (``fairness_bands_v2``, ``geom_q078_v1``, ``trade_decision.decide``):
these tests pin it, they never tune it.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from src.trade import analyze_service as svc
from src.trade import trade_ledger as tl
from src.valuation_math import fairness_bands, package_model
from tests.trade import multi_team_support as mts
from tests.trade.test_multi_team_properties import (  # noqa: F401  (_pinned is an autouse fixture)
    _available_posture,
    _league,
    _pinned,
    _snapshot,
    board_value,
)

KEY = mts.SYNTH_KEY


def _pick(season: int, rnd: int, origin: int) -> str:
    return f"pick:{KEY}:{season}:r{rnd}:o{origin}"


def _leg(aid: str, frm: int, to: int) -> dict[str, Any]:
    return {"id": aid, "from": frm, "to": to}


def _contract(scenario: str = "clean", mutate=None) -> dict[str, Any]:
    c = _league(scenario)
    if mutate is not None:
        mutate(c)
    return c


def _run(
    contract: dict[str, Any],
    teams: list[int],
    legs: list[dict[str, Any]],
    mode: str,
    *,
    scenario: str = "clean",
    goals: dict[int, str] | None = None,
    roster_settings: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if roster_settings is None:
        snap = _snapshot(contract, scenario)
    else:
        snap = tl.build_trade_snapshot(
            contract, league_key=KEY, roster_settings=roster_settings, now=mts.PINNED_NOW
        )
    ledger = tl.validate_ledger(snap, teams=teams, legs=legs, policy=tl.LedgerPolicy())
    kw = {"posture_resolver": _available_posture} if mode == "team_context" else {}
    return svc.analyze_trade_n(
        snap, ledger, mode=mode, counterfactuals=False, team_goals=goals, **kw
    )


def _oracle(contract: dict[str, Any], legs: list[dict[str, Any]], rid: int) -> dict[str, Any]:
    """The team's package answer from the OWNERS, never the engine: its own
    sent and received values (straight off the board), the active package
    model's utilities, and the v2 band."""
    sends = [board_value(contract, x["id"]) for x in legs if x["from"] == rid]
    recvs = [board_value(contract, x["id"]) for x in legs if x["to"] == rid]
    assert None not in sends and None not in recvs, "oracle needs priced legs"
    u_send, u_recv = fairness_bands.package_utilities(sends, recvs)
    gap = u_recv - u_send
    band = fairness_bands.classify_packages(gap, sends, recvs)
    return {"gap": gap, "band": band, "rawSend": sum(sends), "rawRecv": sum(recvs)}


def _fair(out: dict[str, Any], rid: int) -> dict[str, Any]:
    return out["teams"][rid]["fairness"]


def _decision(out: dict[str, Any], rid: int) -> dict[str, Any]:
    return out["teams"][rid]["analysis"]["decision"]


def _headlines(out: dict[str, Any]) -> dict[int, str]:
    return {rid: t["analysis"]["decision"]["headline"] for rid, t in out["teams"].items()}


def _assert_matches_oracle(out, contract, legs, rid):
    want = _oracle(contract, legs, rid)
    f = _fair(out, rid)
    assert f["gap"] == pytest.approx(want["gap"], abs=0.5), (rid, f, want)
    assert f["level"] == want["band"]["level"], (rid, f, want)
    assert f["relativePct"] == pytest.approx(want["band"]["relativePct"], abs=0.01)
    assert f["state"] == ("FAIR" if want["band"]["level"] == "fair" else "NOT_FAIR")
    # The decision's objective-value evidence is the SAME adjusted gap.
    reasons = {r["component"]: r for r in _decision(out, rid).get("reasons") or []}
    if "objectiveValue" in reasons:
        assert reasons["objectiveValue"]["evidence"]["vaAdjustedGap"] == pytest.approx(
            want["gap"], abs=0.5
        )
    return want


def test_the_matrix_runs_on_the_locked_methodology():
    assert fairness_bands.receipt()["version"] == "fairness_bands_v2"
    assert package_model.active_model_id() == "geom_q078_v1"


# ── M01 / M02: two teams, one asset each ─────────────────────────────────────

M01 = ([1, 3], [_leg("p:103", 1, 3), _leg("p:302", 3, 1)])  # 4000 for 4000
M02 = ([1, 2], [_leg("p:101", 1, 2), _leg("p:202", 2, 1)])  # 6000 for 2000
M03_LEGS = [_leg("p:102", 1, 2), _leg("p:103", 1, 2), _leg("p:201", 2, 1)]  # 3000+4000 for 7000


@pytest.mark.parametrize("mode", svc.MODES)
def test_m01_even_one_for_one_is_fair_and_too_close_to_call(mode):
    c = _contract()
    teams, legs = M01
    out = _run(c, teams, legs, mode)
    for rid in teams:
        want = _assert_matches_oracle(out, c, legs, rid)
        assert want["gap"] == 0
        assert _fair(out, rid)["state"] == "FAIR"
        # The near-tie rule: FAIR is never a YES -- "NO, too close to call".
        assert _decision(out, rid)["headline"] == "NO_TOO_CLOSE"
    assert out["summary"]["fairnessOverall"]["state"] == "FAIR"


@pytest.mark.parametrize("mode", svc.MODES)
def test_m02_lopsided_one_for_one(mode):
    c = _contract()
    teams, legs = M02
    out = _run(c, teams, legs, mode)
    a = _assert_matches_oracle(out, c, legs, 1)
    b = _assert_matches_oracle(out, c, legs, 2)
    assert (a["gap"], b["gap"]) == (-4000, 4000)
    assert _fair(out, 1)["level"] == _fair(out, 2)["level"] == "lopsided"
    assert _headlines(out) == {1: "NO", 2: "YES"}  # the labelled lens agrees with the market here
    assert out["summary"]["fairnessOverall"]["state"] == "NOT_FAIR"


# ── M03: uneven packages — Value Adjustment, not raw sums, decides ──────────


@pytest.mark.parametrize("mode", svc.MODES)
def test_m03_raw_even_two_for_one_favours_the_side_receiving_the_best_piece(mode):
    c = _contract()
    teams, legs = [1, 2], M03_LEGS
    out = _run(c, teams, legs, mode)
    one = _assert_matches_oracle(out, c, legs, 1)
    two = _assert_matches_oracle(out, c, legs, 2)
    assert one["rawSend"] == one["rawRecv"] == 7000
    # geom q = 0.78: U(4000, 3000) = 4000 + 0.78 * 3000 = 6340 < 7000.
    assert one["gap"] == pytest.approx(660) and two["gap"] == pytest.approx(-660)
    assert _fair(out, 1)["state"] == "NOT_FAIR"  # 9.43% > the 9.0% unfair line
    assert _headlines(out) == {1: "YES", 2: "NO"}
    # Raw value is conserved even though the adjusted gaps are what decide.
    assert out["summary"]["conservation"]["balanced"] is True


# ── M04 / M05: picks, and several assets of one class ───────────────────────

M04_LEGS = [
    _leg(_pick(2027, 1, 1), 1, 2),
    _leg(_pick(2027, 1, 2), 2, 3),
    _leg(_pick(2027, 1, 3), 3, 1),
]


@pytest.mark.parametrize("mode", svc.MODES)
def test_m04_three_team_cycle_of_same_class_picks_is_fair_for_everyone(mode):
    c = _contract()
    teams = [1, 2, 3]
    out = _run(c, teams, M04_LEGS, mode)
    for rid in teams:
        _assert_matches_oracle(out, c, M04_LEGS, rid)
        assert _fair(out, rid)["state"] == "FAIR"
        assert _decision(out, rid)["headline"] == "NO_TOO_CLOSE"
    assert out["summary"]["fairnessOverall"]["state"] == "FAIR"


def _team_one_holds_team_twos_first(c: dict[str, Any]) -> None:
    teams = {t["roster_id"]: t for t in c["sleeper"]["teams"]}
    moved = next(d for d in teams[2]["pickDetails"] if d["season"] == 2027 and d["round"] == 1)
    teams[2]["pickDetails"].remove(moved)
    teams[2]["picks"] = [d["label"] for d in teams[2]["pickDetails"]]
    moved["ownerRosterId"] = 1
    teams[1]["pickDetails"].append(moved)
    teams[1]["picks"] = [d["label"] for d in teams[1]["pickDetails"]]


M05_LEGS = [
    _leg(_pick(2027, 1, 1), 1, 4),
    _leg(_pick(2027, 1, 2), 1, 4),  # the same "2027 Round 1" label, another origin
    _leg("p:401", 4, 1),
]


@pytest.mark.parametrize("mode", svc.MODES)
def test_m05_two_same_label_picks_are_two_assets_each_priced_once(mode):
    c = _contract(mutate=_team_one_holds_team_twos_first)
    out = _run(c, [1, 4], M05_LEGS, mode)
    four = _assert_matches_oracle(out, c, M05_LEGS, 4)
    assert four["rawRecv"] == 7200  # 3600 + 3600 -- never collapsed by label
    received = sorted(x["assetId"] for x in out["teams"][4]["receives"])
    assert received == sorted([_pick(2027, 1, 1), _pick(2027, 1, 2)])
    _assert_matches_oracle(out, c, M05_LEGS, 1)
    assert out["summary"]["conservation"]["balanced"] is True


# ── M06: four teams ──────────────────────────────────────────────────────────

M06_LEGS = [
    _leg("p:103", 1, 2),  # 4000
    _leg("p:203", 2, 3),  # 5000
    _leg("p:302", 3, 4),  # 4000
    _leg("p:401", 4, 1),  # 8000
]


@pytest.mark.parametrize("mode", svc.MODES)
def test_m06_four_team_cycle_each_team_on_its_own_package(mode):
    c = _contract()
    teams = [1, 2, 3, 4]
    out = _run(c, teams, M06_LEGS, mode)
    gaps = {rid: _assert_matches_oracle(out, c, M06_LEGS, rid)["gap"] for rid in teams}
    assert gaps == {1: 4000, 2: -1000, 3: 1000, 4: -4000}
    # Kleene AND over the teams; no trade-level gap, VA or utility is published.
    assert out["summary"]["fairnessOverall"]["state"] == "NOT_FAIR"
    blob = json.dumps(out["summary"], default=str)
    for forbidden in ('"gap"', "valueAdjustment", '"utility"'):
        assert forbidden not in blob


# ── M07: roster constraints ──────────────────────────────────────────────────


#: Team 3 (5 players) takes two for one into a 5-man cap (``over_cap``).
M07 = ([1, 3], [_leg("p:102", 1, 3), _leg("p:103", 1, 3), _leg("p:302", 3, 1)])


def test_m07_over_the_cap_reports_the_release_but_never_moves_fairness_or_asset_only():
    teams, legs = M07
    clean = _contract()
    capped = _contract("over_cap")
    for mode in ("asset_only", "market_fairness"):
        a = _run(clean, teams, legs, mode)
        b = _run(capped, teams, legs, mode, scenario="over_cap")
        for rid in teams:
            assert _fair(a, rid) == _fair(b, rid)
            assert _decision(a, rid)["headline"] == _decision(b, rid)["headline"]
    ctx = _run(capped, teams, legs, "team_context", scenario="over_cap")
    cap = ctx["teams"][3]["simulation"]["rosterCapacity"]
    assert cap["overLimitAfter"] == 1, cap
    assert len(cap["forcedDrops"]) == 1, "a receiving team over the cap must be told who goes"
    assert _fair(ctx, 3) == _fair(_run(clean, teams, legs, "team_context"), 3)


# ── M08: missing valuations ──────────────────────────────────────────────────

M08 = ([1, 2], [_leg("p:105", 1, 2), _leg("p:202", 2, 1)])  # 105 has no board value


@pytest.mark.parametrize("mode", svc.MODES)
def test_m08_an_unpriced_asset_is_unknown_for_both_teams_never_zero(mode):
    c = _contract()
    teams, legs = M08
    assert board_value(c, "p:105") is None
    out = _run(c, teams, legs, mode)
    for rid in teams:
        f = _fair(out, rid)
        assert (f["state"], f["reasonCode"]) == ("UNABLE", "asset_not_evaluable")
        assert f.get("gap") is None and f.get("relativePct") is None
        d = _decision(out, rid)
        assert d["headline"] == "NOT_ENOUGH_EVIDENCE"
        assert "unpriced_assets" in [g["code"] for g in d["missingEvidence"]]
    leg = next(x for x in out["teams"][1]["gives"] if x["assetId"] == "p:105")
    assert leg.get("value") is None  # MISSING IS NEVER ZERO
    assert out["summary"]["fairnessOverall"]["state"] == "UNABLE"


# ── M09: league lineup settings ──────────────────────────────────────────────


@pytest.mark.parametrize("mode", ("asset_only", "market_fairness"))
def test_m09_league_lineup_settings_never_move_canonical_fairness(mode):
    """Scoring controls rankings; the league key controls context.  A
    different starting lineup (here superflex) changes what Team Context
    measures, never the canonical package values fairness reads."""
    c = _contract()
    teams, legs = M02
    base = _run(c, teams, legs, mode)
    sf = {
        **mts.SYNTH_SETTINGS,
        "starters": {"QB": 1, "RB": 2, "WR": 3, "FLEX": 2, "SUPER_FLEX": 1},
    }
    other = _run(c, teams, legs, mode, roster_settings=sf)
    for rid in teams:
        assert _fair(base, rid) == _fair(other, rid)
        assert _decision(base, rid)["headline"] == _decision(other, rid)["headline"]


# ── M10 / M12: team goals, and utility vs fairness ───────────────────────────


def _losing_lineup(context, capacity, *, incoming_players=(), outgoing_players=(), **_unused):
    """LABELLED roster lens: every trade costs this team 3 best-ball points a
    week, whatever the market says -- invented to make utility disagree."""
    return {
        "available": True,
        "unit": "LABELLED synthetic best-ball points per week",
        "impact": {"ppg": -3.0, "standardError": 0.2},
        "coverage": {"state": "full", "tradedUnprojectedPlayerIds": []},
        "players": [],
        "depth": {"meanLossDeltaPpg": None},
        "cleanup": {"state": "none", "forcedDropIds": [], "candidatesTied": False},
    }


def test_m10_rebuilder_and_contender_answer_differently_on_the_same_facts(monkeypatch):
    from src.trade import roster_capacity

    monkeypatch.setattr(roster_capacity, "evaluate_final_roster_utility", _losing_lineup)
    c = _contract()
    teams, legs = M02  # team 2 gains +4000 of package value and loses 3 ppg
    contender = _run(c, teams, legs, "team_context", goals={2: "WIN_NOW"})
    rebuilder = _run(c, teams, legs, "team_context", goals={2: "REBUILD"})
    assert _decision(contender, 2)["headline"] == "NO"
    assert _decision(rebuilder, 2)["headline"] == "YES"
    for out, used in ((contender, "WIN_NOW"), (rebuilder, "LONG_TERM")):
        strategy = next(r for r in _decision(out, 2)["reasons"] if r["component"] == "strategy")
        assert strategy["evidence"]["used"] == used
        assert strategy["evidence"]["source"] == "user"
    # The goal is context, never a fairness input.
    assert _fair(contender, 2) == _fair(rebuilder, 2)
    assert _fair(contender, 2)["gap"] == 4000


def test_m12_roster_neutral_value_stays_separate_from_team_utility(monkeypatch):
    from src.trade import roster_capacity

    monkeypatch.setattr(roster_capacity, "evaluate_final_roster_utility", _losing_lineup)
    c = _contract()
    teams, legs = M02
    out = _run(c, teams, legs, "team_context")
    d2 = _decision(out, 2)
    reasons = {r["component"]: r for r in d2["reasons"]}
    # The headline value is the market's +4000 ...
    assert reasons["objectiveValue"]["stance"] == "for"
    assert reasons["objectiveValue"]["evidence"]["vaAdjustedGap"] == 4000
    # ... the utility is the roster lens's -3 ppg, named separately ...
    assert reasons["rosterBenefit"]["stance"] == "against"
    assert reasons["rosterBenefit"]["evidence"]["ppg"] == -3.0
    # ... and a balanced team declines without the value being restated.
    assert d2["headline"] == "NO"
    assert _fair(out, 2)["state"] == "NOT_FAIR" and _fair(out, 2)["gap"] == 4000
    asset_only = _run(c, teams, legs, "asset_only")
    assert _decision(asset_only, 2)["headline"] == "YES"
    assert _fair(asset_only, 2) == _fair(out, 2)


# ── M11 / M13: across every row ──────────────────────────────────────────────

ROWS = {
    "M01": ("clean", None, *M01),
    "M02": ("clean", None, *M02),
    "M03": ("clean", None, [1, 2], M03_LEGS),
    "M04": ("clean", None, [1, 2, 3], M04_LEGS),
    "M05": ("clean", _team_one_holds_team_twos_first, [1, 4], M05_LEGS),
    "M06": ("clean", None, [1, 2, 3, 4], M06_LEGS),
    "M07": ("over_cap", None, *M07),
    "M08": ("clean", None, *M08),
}


@pytest.mark.parametrize("row", list(ROWS))
def test_m11_team_context_on_or_off_never_moves_fairness(row):
    scenario, mutate, teams, legs = ROWS[row]
    c = _contract(scenario, mutate)
    outs = [_run(copy.deepcopy(c), teams, legs, m, scenario=scenario) for m in svc.MODES]
    for rid in teams:
        first = _fair(outs[0], rid)
        assert all(_fair(o, rid) == first for o in outs[1:]), (row, rid)
    overall = {o["summary"]["fairnessOverall"]["state"] for o in outs}
    assert len(overall) == 1, (row, overall)


@pytest.mark.parametrize("row", list(ROWS))
@pytest.mark.parametrize("mode", svc.MODES)
def test_m13_the_final_verdict_is_consistent_with_market_fairness(row, mode):
    """FAIR -> never YES (the near-tie rule answers NO_TOO_CLOSE in the
    asset-only modes); UNABLE -> NOT_ENOUGH_EVIDENCE, never YES; NOT_FAIR ->
    never "too close"."""
    scenario, mutate, teams, legs = ROWS[row]
    out = _run(_contract(scenario, mutate), teams, legs, mode, scenario=scenario)
    for rid in teams:
        state = _fair(out, rid)["state"]
        headline = _decision(out, rid)["headline"]
        if state == "UNABLE":
            assert headline == "NOT_ENOUGH_EVIDENCE", (row, rid)
        elif state == "FAIR":
            allowed = ("NO_TOO_CLOSE",) if mode != "team_context" else ("NO_TOO_CLOSE", "NO")
            assert headline in allowed, (row, rid, headline)
        else:
            assert headline in ("YES", "NO"), (row, rid, headline)
