"""Every fitted curve must be bounded outside the range it was fitted on.

PR #604 found the TE++ uplift curve extrapolating without limit: a power
form fitted over KTC base values down to ~480 returned 3.36x at base 100,
against a maximum ever observed of ~2.05. It was capped. Nobody checked
whether the codebase's other fitted curves had the same shape, so this
module is that sweep, kept as a standing check.

**Result of the sweep (2026-07-28).** Four of five were already sound,
and one was not:

===========================  ==========================================
``percentile_to_value``      bounded twice — input clamped to [0, 1],
                             output to the display scale
``rank_to_value``            bounded — rank clamped to >= 1, output to
                             the display scale
``te_premium``               bounded since #604 (floor + ceiling at the
                             observed extremes)
``reception_fit``            bounded — ``MAX_TILT`` 0.25
``scoring_fit``              **UNBOUNDED**, and live
===========================  ==========================================

``scoring_fit`` and ``reception_fit`` are written as siblings — the
second's docstring says its depth probes "mirror
``src.league_intel.scoring_fit`` so the two measurements are judged by
the same standard" — and ``reception_fit`` already carried this exact
clamp for this exact reason: *"so an upstream data fault cannot express
itself as a 3x repricing."* Only one of the two got it, and it was the
one that is not currently enabled.

**Why the existing guard did not cover it.** ``scoring_fit`` rejects a
position whose ratio drifts across depth probes, which is the signature
of *sampling noise*. A corrupted input is not noisy — it is large and
perfectly stable, so it passes cleanly. Measured with one rate parsed
100x too large, the module returned DL 2.899 / LB 0.050 / DB 0.050, a
57x spread, all three marked ``trusted`` at drift 0.0000.

That is the general lesson worth keeping: **a stability check is not a
plausibility check.** They fail on disjoint inputs.
"""

from __future__ import annotations

import pytest

from src.canonical.player_valuation import (
    DISPLAY_SCALE_MAX,
    DISPLAY_SCALE_MIN,
    percentile_to_value,
    rank_to_value,
)
from src.league_intel import reception_fit, scoring_fit
from src.league_intel.scoring_fit import MAX_TILT, measure_positional_scoring_fit


def _week(pid, pos, week, *, solo, sacks):
    return {
        "player_id": pid,
        "player_name": pid,
        "position": pos,
        "season": 2025,
        "week": week,
        "def_tackles_solo": solo,
        "def_tackles_with_assist": 0,
        "def_tackle_assists": 0,
        "def_sacks": sacks,
    }


def _cohort(pos, n, *, solo, sacks, weeks=17):
    return [
        _week(f"{pos}-{i:03d}", pos, w, solo=solo, sacks=sacks)
        for i in range(n)
        for w in range(1, weeks + 1)
    ]


def _three_families():
    return (
        _cohort("DL", 40, solo=3, sacks=2)
        + _cohort("LB", 40, solo=6, sacks=0)
        + _cohort("DB", 40, solo=4, sacks=0)
    )


# ── the curve that was unbounded ──────────────────────────────────────


def test_a_corrupt_scoring_rate_cannot_reprice_idp_by_multiples():
    """THE GUARD, shown firing.

    One rate parsed 100x too large. Pre-fix this returned DL 2.899 and
    LB/DB 0.050 — a 57x spread applied to every IDP asset on the board.
    """
    fit = measure_positional_scoring_fit(
        _three_families(),
        {"idp_tkl_solo": 1.0, "idp_sack": 200.0},
        {"idp_tkl_solo": 1.0, "idp_sack": 2.0},
        season=2025,
    )
    mults = [f.multiplier for f in fit.positions.values()]
    assert mults, "fixture produced no positions"
    for m in mults:
        assert 1.0 - MAX_TILT <= m <= 1.0 + MAX_TILT, f"multiplier {m} escaped the clamp"
    spread = max(mults) / min(mults)
    assert spread < 2.0, f"spread {spread:.2f}x — the clamp is not containing the fault"


def test_the_fault_fixture_really_is_extreme_without_the_clamp():
    """Non-vacuity. If the fixture stopped producing an out-of-range
    ratio, the test above would pass against an unclamped module.
    """
    fit = measure_positional_scoring_fit(
        _three_families(),
        {"idp_tkl_solo": 1.0, "idp_sack": 200.0},
        {"idp_tkl_solo": 1.0, "idp_sack": 2.0},
        season=2025,
    )
    raw = [f.raw_ratio for f in fit.positions.values()]
    assert max(raw) / min(raw) > 10, (
        f"fixture raw spread is only {max(raw) / min(raw):.1f}x — it no longer "
        "exercises the clamp, so the guard above is vacuous"
    )


def test_the_drift_check_does_not_catch_a_corrupt_rate():
    """Documents WHY a second bound was needed.

    A stability check and a plausibility check fail on disjoint inputs.
    A corrupted rate is perfectly stable across depth probes, so every
    position is marked trusted — the drift guard is working correctly
    and is simply answering a different question.
    """
    fit = measure_positional_scoring_fit(
        _three_families(),
        {"idp_tkl_solo": 1.0, "idp_sack": 200.0},
        {"idp_tkl_solo": 1.0, "idp_sack": 2.0},
        season=2025,
    )
    assert all(f.trusted for f in fit.positions.values())
    assert all(f.depth_drift < scoring_fit.MAX_DEPTH_DRIFT for f in fit.positions.values())


#: The multipliers this module actually produced against the live 2025
#: feed and both real scoring cards, 2026-07-28. The bound has to leave
#: these untouched or it is flattening signal rather than catching
#: faults.
_MEASURED_LIVE_MULTIPLIERS = {"DB": 0.9971, "DL": 1.0421, "LB": 0.9608}


def test_the_bound_leaves_the_real_measured_tilt_untouched():
    """It must not touch normal operation.

    Asserted against the REAL measured multipliers rather than a
    synthetic cohort. A first version of this test used a fixture with a
    2x rate difference on a single stat and called it "realistic"; it
    produced DL 0.724 and tripped the clamp, which says the fixture was
    extreme, not that the bound is wrong. The live spread is 0.9608 to
    1.0421 — six times inside the bound.
    """
    for pos, mult in _MEASURED_LIVE_MULTIPLIERS.items():
        assert 1.0 - MAX_TILT < mult < 1.0 + MAX_TILT, pos
        headroom = min(abs(mult - (1.0 - MAX_TILT)), abs((1.0 + MAX_TILT) - mult))
        assert headroom > 0.15, (
            f"{pos} at {mult} sits only {headroom:.3f} from the clamp — the "
            "bound is close enough to real data to be flattening signal"
        )


def test_a_mild_tilt_passes_through_unclamped():
    """The synthetic control: a small genuine difference survives intact."""
    fit = measure_positional_scoring_fit(
        _three_families(),
        {"idp_tkl_solo": 1.0, "idp_sack": 2.0},
        {"idp_tkl_solo": 1.0, "idp_sack": 2.2},
        season=2025,
    )
    for f in fit.positions.values():
        assert 1.0 - MAX_TILT < f.multiplier < 1.0 + MAX_TILT
        assert f.multiplier != pytest.approx(1.0 - MAX_TILT), "clamped a mild tilt"
        assert f.multiplier != pytest.approx(1.0 + MAX_TILT), "clamped a mild tilt"


def test_both_sibling_fits_are_bounded_at_all():
    """The asymmetry that let one go unbounded is what this pins shut.

    An earlier version asserted the two bounds were EQUAL. That was a
    proxy for the real property and it was wrong: the bounds should
    track each measurement's own spread, and those differ. IDP
    positional multipliers span 0.96-1.04 against a 0.25 bound, while
    per-player reception tilt spans 0.765-1.098 and needed 0.35 to stop
    the clamp shaping the result. Equality would have forced one of them
    to be wrong for its data.

    What must hold is that each exists and each is sane.
    """
    for mod in (scoring_fit, reception_fit):
        bound = getattr(mod, "MAX_TILT", None)
        assert bound is not None, f"{mod.__name__} has no MAX_TILT"
        assert 0.0 < bound < 1.0, (
            f"{mod.__name__}.MAX_TILT={bound} — a bound at or above 1.0 permits "
            "a player's value to be zeroed or doubled, which is not a backstop"
        )


def test_each_bound_clears_its_own_measured_data():
    """The principle the equality check was reaching for.

    A bound must not bind on real data — that is the difference between
    a fault backstop and a silent shaper. Each module records its own
    measured extremes next to its constant; this asserts the bound sits
    outside them with room.
    """
    # scoring_fit: measured IDP multipliers, 2026-07-28.
    for observed in (0.9608, 1.0421):
        assert 1.0 - scoring_fit.MAX_TILT < observed < 1.0 + scoring_fit.MAX_TILT

    # reception_fit: measured per-player tilt over 199 receivers, 2025.
    for observed in (0.765, 1.098):
        assert 1.0 - reception_fit.MAX_TILT < observed < 1.0 + reception_fit.MAX_TILT


# ── the curves the sweep found already sound ──────────────────────────


@pytest.mark.parametrize(
    "percentile", [-1e9, -1.0, -0.001, 0.0, 0.5, 1.0, 1.001, 2.0, 1e9, float("inf")]
)
def test_percentile_to_value_is_bounded_for_any_input(percentile):
    v = percentile_to_value(percentile)
    assert DISPLAY_SCALE_MIN <= v <= DISPLAY_SCALE_MAX


@pytest.mark.parametrize("rank", [-1e9, -1, 0, 1, 250, 500, 5000, 10**9])
def test_rank_to_value_is_bounded_for_any_input(rank):
    v = rank_to_value(rank)
    assert 0 <= v <= DISPLAY_SCALE_MAX


def test_percentile_to_value_is_monotone_non_increasing():
    """A value curve that rose with percentile would be a sign error,
    and the bounds tests above would not notice."""
    prev = percentile_to_value(0.0)
    for i in range(1, 101):
        cur = percentile_to_value(i / 100.0)
        assert cur <= prev, f"value rose at p={i / 100.0}"
        prev = cur


def test_te_premium_is_bounded_below_its_fitted_range():
    """The original #604 defect, kept as a regression.

    The power form read 3.36x at base value 100 against a maximum
    observed uplift of ~2.05.
    """
    from src.league_intel import te_premium

    ceiling = te_premium._FALLBACK_CEILING
    for base in (1.0, 10.0, 100.0, 480.0, 5000.0, 9999.0):
        got = te_premium.convert_te_value(base, from_basis="base", to_basis="tepp")
        assert (
            got <= base * ceiling * 1.001
        ), f"base {base} converted to {got}, above the observed uplift ceiling"
