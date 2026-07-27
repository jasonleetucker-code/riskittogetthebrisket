"""Auction power is implemented twice. Nothing kept the two in step.

Backlog defect #8. ``src/api/auction_power.py`` is documented as the
source of truth — ``frontend/app/league/sections/draft-capital.jsx``
says so in a comment — but the numbers a user actually sees come from
``frontend/lib/auction-power.js``, a second implementation with its own
copy of the tuning constants.

The Python side had ``tests/api/test_auction_power.py``. The JS side had
nothing, and no test compared them. Retuning either one alone would
silently change what the board shows while the "source of truth" kept
reporting the old numbers, and every existing test would stay green.

This follows ``tests/api/test_source_registry_parity.py``, which solves
the same shape for the ranking-source registry: parse the JS, diff it
against Python, fail on drift.

WHY CONSTANTS AND NOT OUTPUTS
─────────────────────────────
Executing the JS from pytest would need a node subprocess and a module
shim, and it would test the runner as much as the code. The realistic
drift here is someone tuning a constant on one side — the S-curve shape
is stable and both were transcribed from the same spec. So this pins
the three knobs exactly, and pins the Python invariants separately, so
a shape change on the Python side is caught by behaviour and a value
change on either side is caught by parity.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.api.auction_power import AuctionPowerConstants, effective_auction_power

REPO_ROOT = Path(__file__).resolve().parents[2]
JS = REPO_ROOT / "frontend" / "lib" / "auction-power.js"

#: JS export name -> Python dataclass field.
_PAIRS = {
    "AP_PREMIUM_GAIN": "premium_gain",
    "AP_CURVATURE": "curvature",
    "AP_LEAPFROG_WEIGHT": "leapfrog_weight",
}


def _js_constants() -> dict[str, float]:
    src = JS.read_text(encoding="utf-8")
    found: dict[str, float] = {}
    for name in _PAIRS:
        m = re.search(rf"^export\s+const\s+{name}\s*=\s*([0-9.]+)\s*;", src, re.M)
        if m:
            found[name] = float(m.group(1))
    return found


def test_the_js_file_is_where_we_think_it_is():
    """Guard on the guard.

    Every parity assertion below is a function of this parse. If the
    module moved or the exports were renamed, an empty parse would make
    the comparison vacuous rather than failing — the exact way a parity
    test stops being one.
    """
    assert JS.exists(), f"{JS} is gone; auction power parity is unguarded"
    found = _js_constants()
    missing = set(_PAIRS) - set(found)
    assert not missing, (
        f"could not parse {sorted(missing)} from {JS.name}. Either they were "
        "renamed or the regex is stale — fix the parse, do not delete the test."
    )


@pytest.mark.parametrize("js_name,py_field", sorted(_PAIRS.items()))
def test_constants_match_python(js_name, py_field):
    """The drift this defect is about.

    Retuning one side alone changes what the board shows while the
    documented source of truth still reports the old numbers.
    """
    js = _js_constants()[js_name]
    py = getattr(AuctionPowerConstants(), py_field)
    assert js == pytest.approx(py), (
        f"{js_name}={js} in {JS.name} but {py_field}={py} in "
        "src/api/auction_power.py — the frontend is the one users see, "
        "and the Python file is the one documented as authoritative. "
        "Change both."
    )


# ── Python-side invariants, so a shape change is caught too ──────────


def test_the_lens_is_zero_sum():
    """It is a redistribution of a fixed budget, not an inflation of it.

    A lens that quietly added dollars would make every team look
    stronger and change no relative ordering — invisible in a bar chart
    and wrong in every trade conversation.
    """
    totals = {"A": 180, "B": 120, "C": 100, "D": 60}
    out = effective_auction_power(totals)
    assert sum(out.values()) == sum(totals.values())


def test_every_team_stays_within_the_documented_band():
    """``premium_gain`` promises the multiplier is bounded to
    [1-gain, 1+gain]. That bound is the reason the lens is safe to show
    next to the raw numbers, so it is asserted rather than trusted.

    THE BAND IS A PRE-ROUNDING PROPERTY, and the first draft of this
    test found that out: a team holding $1 came back 0, because
    ``1 * 0.65 = 0.65`` rounds to zero inside the integer zero-sum
    redistribution. That is correct behaviour for a lens that must emit
    whole dollars summing to the real total — not a band violation —
    but it means the guarantee only holds where rounding is not the
    dominant term. Realistic draft capital is tens to hundreds of
    dollars, which is what this asserts over; the sub-$5 case is pinned
    separately below so the boundary is documented rather than lost.
    """
    gain = AuctionPowerConstants().premium_gain
    totals = {"Huge": 400, "Big": 200, "Mid": 100, "Small": 40}
    out = effective_auction_power(totals)
    for team, raw in totals.items():
        ratio = out[team] / raw
        assert (1 - gain) - 0.02 <= ratio <= (1 + gain) + 0.02, (
            f"{team} moved {ratio:.3f}x, outside the +/-{gain} band the " "constant promises"
        )


def test_a_sub_dollar_stack_can_round_to_zero_and_that_is_the_contract():
    """Pinned so nobody 'fixes' it into a non-zero-sum lens.

    The alternative — floor every team at $1 — would emit more dollars
    than the league has, which is the one property
    ``test_the_lens_is_zero_sum`` exists to protect.
    """
    out = effective_auction_power({"Whale": 500, "Minnow": 1})
    assert sum(out.values()) == 501
    assert out["Minnow"] in (0, 1)


def test_a_flat_field_barely_moves():
    """With no spread there is no premium to award. Near-identical
    inputs must come back near-identical, or the lens is inventing a
    hierarchy that the dollars do not support."""
    totals = {"A": 100, "B": 100, "C": 100, "D": 100}
    out = effective_auction_power(totals)
    assert max(out.values()) - min(out.values()) <= 1


def test_the_biggest_stack_is_not_penalised():
    """Directional sanity: the leapfrog term is a bonus for the leader,
    so the largest raw total must not come back below a smaller one."""
    totals = {"Leader": 200, "Second": 150, "Third": 90}
    out = effective_auction_power(totals)
    assert out["Leader"] >= out["Second"] >= out["Third"]


def test_degenerate_inputs_do_not_raise():
    """Empty and all-zero leagues reach this from a cold contract."""
    assert effective_auction_power({}) == {}
    zeroed = effective_auction_power({"A": 0, "B": 0})
    assert sum(zeroed.values()) == 0
