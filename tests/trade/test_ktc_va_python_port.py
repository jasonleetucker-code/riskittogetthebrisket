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

from src.trade.ktc_va import (
    KtcVAResult,
    _js_round,
    ktc_adjust_package,
    ktc_process_v,
)

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
    assert (
        rms < 50
    ), f"RMS error {rms:.1f} exceeds 50 — Python port may have drifted from KTC's algorithm"


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
    assert (
        matched == fires
    ), f"Recipient-side parity: {matched}/{fires} (every fired VA must pick the right side)"


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
    assert (
        matched == silent
    ), f"Suppression parity: {matched}/{silent} (every KTC-suppressed trade must also suppress in the port)"


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
        assert (
            abs(got - expected) < tol
        ), f"ktc_process_v({value}) = {got:.2f}, expected {expected} ± {tol}"


# ── JS-faithful rounding (one owner, 2026-08-18) ─────────────────────
#
# ``src/trade/market_value_adjustment.py`` used to carry a SECOND port
# of this algorithm.  It rounded with ``floor(x + 0.5)`` (JavaScript
# ``Math.round``, half-up); this module rounded with Python's built-in
# ``round``, which is banker's rounding.  The 139-observation fixture
# above contains no half-integer case, so it never caught the split.
#
# Measured over 40,000 random packages against the JS reference
# (``frontend/lib/trade-logic.js::ktcAdjustPackage``): the retired
# banker's rule published a different value on **75** of them, always
# by 1 point.  ``_js_round`` is now the single rule and the same sweep
# scores **0 / 40,000**.
#
# Each case below is one of those 75.  ``expected`` is the JS answer.

_JS_ROUNDING_BOUNDARY_CASES = [
    ([3751, 4207, 3566, 3426], [9605], (10148, 2)),
    ([1091, 9140], [6791, 5765], (3468, 1)),
    ([2080, 2798, 6381, 8653], [4705, 8620, 7869], (3045, 2)),
    ([2424, 2695, 6705, 945], [8149, 4277], (4418, 2)),
    ([8241], [2316, 2034, 5003], (5233, 1)),
    ([8285], [6053, 7443], (1068, 1)),
]


@pytest.mark.parametrize(("team1", "team2", "expected"), _JS_ROUNDING_BOUNDARY_CASES)
def test_half_integer_boundaries_match_javascript(team1, team2, expected):
    result = ktc_adjust_package(team1, team2)
    assert result.displayed is True
    assert (result.value, result.side) == expected


def test_js_round_is_half_up_not_bankers():
    """The rule itself, stated as a test so it cannot regress quietly."""

    assert _js_round(0.5) == 1  # Python's round() gives 0
    assert _js_round(1.5) == 2
    assert _js_round(2.5) == 3  # Python's round() gives 2
    assert _js_round(-1.5) == -1  # JS Math.round(-1.5) === -1
    assert _js_round(2.4) == 2


# ── One owner ────────────────────────────────────────────────────────


def test_market_value_adjustment_is_a_re_export_not_a_second_port():
    """``market_value_adjustment`` must delegate, never recompute.

    A second Python port is what produced the 75-case divergence above.
    This pins that the compatibility module holds no algorithm of its
    own: the result type is literally the same class, and its answers
    are identical to the owner's on every fixture observation.
    """

    from src.trade import market_value_adjustment as mva

    assert mva.PackageAdjustment is KtcVAResult

    for observation in _load_observations():
        team1 = observation.get("team1Values") or []
        team2 = observation.get("team2Values") or []
        assert mva.ktc_adjust_package(team1, team2) == ktc_adjust_package(team1, team2)

    for team1, team2, _expected in _JS_ROUNDING_BOUNDARY_CASES:
        assert mva.ktc_adjust_package(team1, team2) == ktc_adjust_package(team1, team2)
