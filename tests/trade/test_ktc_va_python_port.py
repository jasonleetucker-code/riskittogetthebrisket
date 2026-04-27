"""Python port of KTC's VA algorithm — fixture parity test.

Loads ``scripts/ktc_va_observations.json`` (139 captured KTC trades
with KTC.com's actual displayed VA + recipient side) and asserts the
Python port (:mod:`src.trade.ktc_va`) reproduces them with the same
fidelity as the JS port (verified by ``scripts/test_ktc_va_port.mjs``).

Companion fixture is the single source of truth shared between the JS
and Python implementations — drift in either direction trips here.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from src.trade.ktc_va import ktc_adjust_package, ktc_process_v

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FIXTURE_PATH = _REPO_ROOT / "scripts" / "ktc_va_observations.json"


def _load_observations():
    with _FIXTURE_PATH.open() as f:
        data = json.load(f)
    return data["observations"]


def test_fixture_overall_rms_under_50():
    """Overall RMS error against KTC's actual displayed VAs.

    The JS port scores 27 RMS on this fixture; the Python port should
    match within numerical noise (≤ 50 RMS allows for tiny rounding
    differences in math.pow vs Math.pow).
    """
    obs = _load_observations()
    sq_err = 0.0
    for o in obs:
        a = o.get("team1Values") or []
        b = o.get("team2Values") or []
        observed = (o.get("valueAdjustmentTeam1") or 0) or (o.get("valueAdjustmentTeam2") or 0)
        result = ktc_adjust_package(a, b)
        ported = result.value if result.displayed else 0
        sq_err += (ported - observed) ** 2
    rms = math.sqrt(sq_err / len(obs))
    assert rms < 50, f"RMS error {rms:.1f} exceeds 50 — Python port may have drifted from KTC's algorithm"


def test_fixture_recipient_side_100pct():
    """For every fixture trade where KTC fired a VA, the port picks the same recipient side."""
    obs = _load_observations()
    matched = 0
    fires = 0
    for o in obs:
        a = o.get("team1Values") or []
        b = o.get("team2Values") or []
        va1 = o.get("valueAdjustmentTeam1") or 0
        va2 = o.get("valueAdjustmentTeam2") or 0
        observed_side = 1 if va1 > 0 else (2 if va2 > 0 else 0)
        if observed_side == 0:
            continue
        fires += 1
        result = ktc_adjust_package(a, b)
        if result.displayed and result.side == observed_side:
            matched += 1
    assert matched == fires, f"Recipient-side parity: {matched}/{fires} (every fired VA must pick the right side)"


def test_fixture_suppression_100pct():
    """For every fixture trade where KTC suppressed VA, the port also suppresses."""
    obs = _load_observations()
    matched = 0
    silent = 0
    for o in obs:
        a = o.get("team1Values") or []
        b = o.get("team2Values") or []
        observed = (o.get("valueAdjustmentTeam1") or 0) or (o.get("valueAdjustmentTeam2") or 0)
        if observed > 0:
            continue
        silent += 1
        result = ktc_adjust_package(a, b)
        if not result.displayed or result.value == 0:
            matched += 1
    assert matched == silent, f"Suppression parity: {matched}/{silent} (every KTC-suppressed trade must also suppress in the port)"


def test_users_5v2_trade_returns_4161_to_side2():
    """The user-reported trade that motivated the V13 → port migration.

    5 mid pieces (Bigsby, CRod, Tua, Penix, Pick 1.06) versus 2 studs
    (Pickens, LaPorta TE+).  KTC.com displays +4,161 to side 2.
    V13 fired 0; the native port must reproduce KTC's number.
    """
    result = ktc_adjust_package(
        [4846, 3163, 2819, 2538, 2534],
        [5947, 5049],
    )
    assert result.displayed
    assert result.side == 2
    assert abs(result.value - 4161) <= 5, f"got {result.value}, expected 4161 ± 5"


def test_one_v_one_always_suppressed():
    """KTC's UI gates 1v1 trades off regardless of what adjustPackage computes."""
    result = ktc_adjust_package([9000], [7000])
    assert not result.displayed
    assert result.value == 0


def test_process_v_canonical_inputs():
    """Pin a few outputs of ktc_process_v so a future refactor can't drift the per-piece weights.

    Same expected values as the JS test in __tests__/trade-logic.test.js.
    """
    cases = [
        (9000, 1469, 5),
        (7000, 950, 5),
        (5000, 604, 5),
        (3000, 331, 5),
        (1000, 103, 5),
    ]
    for value, expected, tol in cases:
        got = ktc_process_v(value, 9999, 10041, -1)
        assert abs(got - expected) < tol, f"ktc_process_v({value}) = {got:.2f}, expected {expected} ± {tol}"
