"""Independent oracle for the FAAB objective-ceiling math (CW-49).

The expected values come from the SPEC (``docs/faab-model.md`` Stage B/C,
CLAUDE.md "FAAB recommendations"), computed by hand / 50-digit Decimal in
``tests/fixtures/faab_curve_oracle_cases.json`` (each case carries a
``derivation``).  Nothing here calls ``faab_engine._smootherstep`` or copies
its formula to produce an expectation; the engine is only the function under
test.  The small ``_oracle_*`` helpers below restate the spec formulas for the
properties that need many inputs.

Spec constants are pinned from the documentation (2.2 / 0.5 / 6.0) and the
shipped config is asserted equal to them, so a silent recalibration shows up as
a failing oracle rather than as a quietly shifted expectation.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.trade import faab_engine as FE

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "faab_curve_oracle_cases.json"
_DOC = json.loads(FIXTURE.read_text(encoding="utf-8"))
CASES = _DOC["cases"]
V_REPL = float(_DOC["anchors"]["vRepl"])
V_ALLIN = float(_DOC["anchors"]["vAllIn"])
BAND = float(_DOC["anchors"]["band"])

# docs/faab-model.md, "ceilingCurve" table
SPEC_TOE = 2.2
SPEC_SLOPE = 0.5
SPEC_CAP = 6.0
TOL = 1e-12


def _anchors() -> FE.Anchors:
    return FE.Anchors(v_allin=V_ALLIN, v_repl=V_REPL, band=BAND, starter_slots=240)


def _league(budget: int = 100, **kw) -> FE.LeagueContext:
    return FE.LeagueContext(original_budget=budget, in_season=True, current_week=8, **kw)


def _team(remaining=None, **kw) -> FE.TeamContext:
    return FE.TeamContext(faab_remaining=remaining, **kw)


def _oracle_ceiling(value: float) -> tuple[float, float]:
    """Spec Stage C restated (poly via Horner-free expanded form)."""
    s = max(0.0, value - V_REPL) / BAND
    x = min(1.0, s**SPEC_TOE)
    disp = 6 * x**5 - 15 * x**4 + 10 * x**3
    raw = disp if s <= 1 else min(SPEC_CAP, 1 + (s - 1) * SPEC_SLOPE)
    return disp, raw


def test_config_matches_documented_spec_constants():
    cfg = FE.FaabConfig()
    assert cfg.num("ceilingCurve", "toeExponent", -1) == SPEC_TOE
    assert cfg.num("ceilingCurve", "aboveAllinSlope", -1) == SPEC_SLOPE
    assert cfg.num("ceilingCurve", "rawCeilingCap", -1) == SPEC_CAP
    assert cfg.num("dropCost", "dropSurplusWeight", -1) == 1.0


# ── 1. smootherstep on s^gamma ─────────────────────────────────────


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_objective_ceiling_matches_hand_derived_cases(case):
    disp, raw = FE.objective_ceiling(case["value"], _anchors())
    assert disp == pytest.approx(case["expectedDisplayed"], abs=TOL), case["derivation"]
    assert raw == pytest.approx(case["expectedRaw"], abs=TOL), case["derivation"]


def test_endpoints_are_exact():
    assert FE.objective_ceiling(V_REPL, _anchors()) == (0.0, 0.0)
    disp, raw = FE.objective_ceiling(V_ALLIN, _anchors())
    assert disp == pytest.approx(1.0, abs=TOL)
    assert raw == pytest.approx(1.0, abs=TOL)


def test_zero_slope_at_both_ends():
    # Near replacement: c ~ 10 s^6.6, so c/h must be tiny for a small step h.
    h = 1e-3
    lo, _ = FE.objective_ceiling(V_REPL + h * BAND, _anchors())
    assert lo / h < 1e-9
    # Near all-in: 1 - c ~ 10 (2.2 h)^3, so (1-c)/h must be tiny.
    hi, _ = FE.objective_ceiling(V_ALLIN - h * BAND, _anchors())
    assert (1.0 - hi) / h < 1e-3
    # Hand value: 10*(2.2e-3)^3 = 1.0648e-7
    assert (1.0 - hi) == pytest.approx(10 * (2.2 * h) ** 3, rel=0.02)


def test_displayed_curve_is_monotone_and_bounded():
    prev = -1.0
    for i in range(0, 301):
        v = V_REPL + BAND * i / 200.0  # s from 0 to 1.5
        disp, raw = FE.objective_ceiling(v, _anchors())
        assert 0.0 <= disp <= 1.0
        assert disp >= prev - 1e-15
        assert raw >= disp
        prev = disp


@pytest.mark.parametrize("band", [700.0, 1000.0, 1460.0])
def test_curve_depends_on_s_not_absolute_scale(band):
    a = FE.Anchors(v_allin=500 + band, v_repl=500.0, band=band, starter_slots=100)
    for s in (0.2, 0.6, 1.0, 1.7):
        got = FE.objective_ceiling(500.0 + s * band, a)
        want = _oracle_ceiling(V_REPL + s * BAND)
        assert got[0] == pytest.approx(want[0], abs=1e-12)
        assert got[1] == pytest.approx(want[1], abs=1e-12)


# ── 2. surplus and the drop side ───────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [(1800.0, 800.0), (1000.0, 0.0), (999.0, 0.0), (0.0, 0.0), (2000.0, 1000.0)],
)
def test_surplus_floors_at_zero(value, expected):
    assert FE.surplus_over_replacement(value, _anchors()) == expected


def test_drop_below_replacement_is_free_and_above_subtracts():
    league = _league()
    a = _anchors()
    # add surplus 800, drop below replacement (900): drop surplus 0, net 800.
    free = FE.team_ceiling(
        FE.PlayerInput(value=1800, drop_name="X", drop_value=900),
        a,
        league,
        _team(100, open_roster_spots=0),
    )
    assert free["dropSurplus"] == 0.0
    assert free["netSurplus"] == 800.0
    # drop 1500 -> surplus 500; net 800-500 = 300; ceiling = ss((0.3)^2.2)
    paid = FE.team_ceiling(
        FE.PlayerInput(value=1800, drop_name="X", drop_value=1500),
        a,
        league,
        _team(100, open_roster_spots=0, competitive_status="eliminated"),
    )
    assert paid["dropSurplus"] == 500.0
    assert paid["netSurplus"] == 300.0
    want, _ = _oracle_ceiling(1300.0)  # V_repl + net surplus
    assert paid["objectivePct"] == pytest.approx(_oracle_ceiling(1800.0)[0], abs=TOL)
    assert paid["teamCeilingDollars"] == pytest.approx(want * 100, abs=1e-9)
    # drop worth more than the add -> net surplus floors at 0 -> ceiling 0
    over = FE.team_ceiling(
        FE.PlayerInput(value=1200, drop_name="X", drop_value=1900),
        a,
        league,
        _team(100, open_roster_spots=0),
    )
    assert over["netSurplus"] == 0.0
    assert over["teamCeilingDollars"] == 0.0
    # open roster spot: no drop charged even if a drop is named
    opened = FE.team_ceiling(
        FE.PlayerInput(value=1800, drop_name="X", drop_value=1900),
        a,
        league,
        _team(100, open_roster_spots=1),
    )
    assert opened["dropSurplus"] == 0.0
    assert opened["netSurplus"] == 800.0


# ── 3. original budget, team independence ──────────────────────────


@pytest.mark.parametrize("value", [1100.0, 1500.0, 1800.0, 2000.0, 3000.0])
def test_objective_scales_with_original_budget_not_balance(value):
    disp, _ = _oracle_ceiling(value)
    for budget in (100, 250, 1000):
        for remaining in (0, 1, 7, budget // 2, budget, budget * 3):
            out = FE.recommend(
                FE.PlayerInput(value=value, position="WR"),
                _league(budget),
                _team(remaining),
                anchors=_anchors(),
            )
            assert out["objective"]["originalBudget"] == budget
            assert out["objective"]["pctOfOriginalBudget"] == pytest.approx(
                round(100 * disp, 1), abs=1e-9
            )
            assert out["objective"]["dollars"] == int(round(disp * budget))


def test_objective_identical_for_every_team():
    base = None
    for status in ("contender", "bubble", "rebuilder", "eliminated"):
        for need in ("starterHole", "need", "neutral", "surplus"):
            for posture in ("balanced", "aggressive", "conservative"):
                for spots in (0, 3):
                    for remaining in (0, 13, 100):
                        out = FE.recommend(
                            FE.PlayerInput(
                                value=1750, position="RB", drop_name="D", drop_value=1600
                            ),
                            _league(),
                            _team(
                                remaining,
                                competitive_status=status,
                                need_level=need,
                                risk_posture=posture,
                                open_roster_spots=spots,
                            ),
                            anchors=_anchors(),
                        )
                        obj = out["objective"]
                        # drop does not change the OBJECTIVE block (team-independent)
                        base = base or obj
                        assert obj == base


# ── 4. rawCeiling above the all-in line ────────────────────────────


def test_raw_ceiling_grows_then_caps_and_separates_2400_from_9999():
    a = _anchors()
    _, raw_2400 = FE.objective_ceiling(2400, a)
    _, raw_9999 = FE.objective_ceiling(9999, a)
    assert raw_2400 == pytest.approx(1.2, abs=TOL)  # 1 + 0.4*0.5
    assert raw_9999 == pytest.approx(4.9995, abs=TOL)  # 1 + 7.999*0.5
    assert raw_9999 > raw_2400
    # cap binds at s=11 (V=12000) and stays at 6.0
    for v in (12000, 15000, 50000):
        disp, raw = FE.objective_ceiling(v, a)
        assert disp == 1.0
        assert raw == SPEC_CAP
    # team-level raw dollars are raw * ORIGINAL budget (neutral, eliminated => option 1.0)
    t = FE.team_ceiling(
        FE.PlayerInput(value=9999), a, _league(200), _team(50, competitive_status="eliminated")
    )
    assert t["teamRawCeilingDollars"] == pytest.approx(4.9995 * 200, abs=1e-9)
    assert t["objectivePct"] == 1.0
    assert t["objectiveDollars"] == 200.0


# ── 5. recommended bounded by ceiling and balance; $0 is known ─────


@pytest.mark.parametrize("value", [1050.0, 1500.0, 1900.0, 2000.0, 2400.0, 9999.0])
@pytest.mark.parametrize("remaining", [0, 1, 5, 40, 100, 400])
@pytest.mark.parametrize("posture", ["balanced", "aggressive", "conservative"])
def test_recommended_bounded_by_ceiling_and_balance(value, remaining, posture):
    budget = 100
    out = FE.recommend(
        FE.PlayerInput(value=value, position="WR"),
        _league(budget),
        _team(remaining, competitive_status="eliminated", risk_posture=posture),
        anchors=_anchors(),
        rivals=[FE.RivalTeam(owner_id=str(i), faab_remaining=100) for i in range(11)],
    )
    _, raw = _oracle_ceiling(value)
    raw_dollars = raw * budget  # neutral need, option factor 1.0 (eliminated)
    b = out["bids"]
    assert b["recommended"] <= remaining
    assert b["maxRational"] == min(remaining, math.floor(raw_dollars))
    assert 0 <= b["recommended"] <= b["maxRational"]
    assert b["conservative"] <= b["recommended"] <= b["aggressive"] <= b["maxRational"]
    assert out["teamCeilingDollars"] <= remaining


def test_zero_balance_is_known_zero_not_unknown():
    out = FE.recommend(FE.PlayerInput(value=2500), _league(100), _team(0), anchors=_anchors())
    assert out["bids"]["recommended"] == 0
    assert out["bids"]["maxRational"] == 0
    assert out["pctOfRemaining"] is None
    assert out["teamCeilingDollars"] == 0
    assert any("no FAAB left" in w for w in out["warnings"])
    # objective still reports worth: 0 balance must not erase the player's value
    assert out["objective"]["dollars"] == 100
    # contrast: an UNKNOWN balance (None) means the full original budget, never 0
    unknown = FE.recommend(
        FE.PlayerInput(value=2500), _league(100), _team(None), anchors=_anchors()
    )
    assert unknown["bids"]["maxRational"] > 0
