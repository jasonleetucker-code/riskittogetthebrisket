"""Imputing first downs onto a projected stat line.

Realized scoring reads first downs from nflverse columns and is exact.
Projections have no such columns — no source publishes them — so a
projected line scored through the same engine silently contributes zero
first-down points under a card that pays 1.00 each.

Measured on realistic season lines under this league's card: 30.5%
understated for a QB, 22.5% RB, 23.6% WR, 24.6% TE. Uneven, so it does
not cancel from a relative comparison; and *mixed*, because BDVM's proxy
rows are scored from realized stats that DO carry the columns.

The tests that matter are the refusals. An imputer that fires when it
should not is worse than one that never fires at all, because the number
it produces looks exactly like a measurement.
"""

from __future__ import annotations

import pytest

from src.nfl_data.first_down_rate import (
    FIRST_DOWNS_PER_YARD,
    FIRST_DOWN_COLUMNS,
    FIT_R_SQUARED,
    MIN_YARDS_TO_IMPUTE,
    fit_first_downs_per_yard,
    imputed_first_down_column,
    supplies_first_downs,
    with_imputed_first_downs,
)
from src.nfl_data.realized_points import _FIRST_DOWN_COLUMNS as SCORER_COLUMNS


# ── the refusals ────────────────────────────────────────────────────────


def test_a_line_that_already_has_first_downs_is_left_alone():
    """THE DOUBLE-COUNT GUARD, and it is structural rather than a rule.

    A source that supplies first downs is authoritative. Adding an
    estimate on top would roughly double every receiver's bonus, and the
    result would look like an ordinary number.
    """
    line = {"receiving_yards": 1200.0, "receiving_first_downs": 55.0}
    out, imputed = with_imputed_first_downs(line, "WR")
    assert imputed is False
    assert out["receiving_first_downs"] == 55.0


def test_a_present_but_zero_column_still_counts_as_supplied():
    """A source emitting the column with 0 is telling us he had none.
    Overwriting that with an estimate discards real information."""
    line = {"receiving_yards": 400.0, "receiving_first_downs": 0.0}
    out, imputed = with_imputed_first_downs(line, "WR")
    assert imputed is False
    assert out["receiving_first_downs"] == 0.0


def test_an_unmeasured_position_gets_nothing_rather_than_a_league_average():
    """Only four positions were fitted. A kicker or a linebacker must not
    receive a rate measured on receivers."""
    for pos in ("K", "DEF", "LB", "DB", "", None, "PICK"):
        out, imputed = with_imputed_first_downs({"rushing_yards": 400.0}, pos)
        assert imputed is False
        assert not supplies_first_downs(out)


def test_a_negligible_yardage_line_is_not_extrapolated_onto():
    """The fit's population was 200+ yard players. Projecting a fraction
    of a first down onto a 0.5-yard line claims precision the
    measurement does not have."""
    out, imputed = with_imputed_first_downs({"receiving_yards": MIN_YARDS_TO_IMPUTE / 2}, "WR")
    assert imputed is False


def test_an_empty_line_imputes_nothing():
    assert with_imputed_first_downs(None, "WR") == ({}, False)
    assert with_imputed_first_downs({}, "WR") == ({}, False)


def test_the_callers_line_is_never_mutated():
    line = {"receiving_yards": 1200.0}
    with_imputed_first_downs(line, "WR")
    assert line == {"receiving_yards": 1200.0}


# ── the imputation itself ───────────────────────────────────────────────


def test_it_fires_on_a_projection_shaped_line_and_says_so():
    out, imputed = with_imputed_first_downs({"receiving_yards": 1000.0}, "WR")
    assert imputed is True
    assert out["receiving_first_downs"] == pytest.approx(1000.0 * FIRST_DOWNS_PER_YARD["WR"])


def test_yards_from_every_phase_count():
    """A back's first downs come from carries AND catches."""
    out, _ = with_imputed_first_downs({"rushing_yards": 900.0, "receiving_yards": 400.0}, "RB")
    assert out["rushing_first_downs"] == pytest.approx(1300.0 * FIRST_DOWNS_PER_YARD["RB"])


def test_every_position_lands_near_one_first_down_per_twenty_yards():
    """The headline fact, and a tripwire on a bad refit.

    All four fitted positions sit between 19.6 and 21.2 yards per first
    down. A refit that moved one of them outside 18-23 has found
    something the game changed, or a broken join — either way a human
    should look before it ships.
    """
    for pos, rate in FIRST_DOWNS_PER_YARD.items():
        assert 18.0 <= 1.0 / rate <= 23.0, f"{pos} drifted to {1.0 / rate:.1f} yards per FD"


def test_the_shipped_fit_quality_is_recorded_and_high():
    """R^2 ships with the rate because a caller deciding whether to trust
    an imputed value needs to know a QB's is near-deterministic and a
    TE's is merely good."""
    assert set(FIT_R_SQUARED) == set(FIRST_DOWNS_PER_YARD)
    assert all(r >= 0.85 for r in FIT_R_SQUARED.values())
    assert FIT_R_SQUARED["QB"] > FIT_R_SQUARED["TE"]


def test_the_target_column_is_one_the_scorer_actually_reads():
    """A silent divergence from ``realized_points`` would write the
    estimate into a column nothing sums — imputing nothing, while
    reporting that it imputed."""
    assert set(FIRST_DOWN_COLUMNS) == set(SCORER_COLUMNS)
    for pos in FIRST_DOWNS_PER_YARD:
        assert imputed_first_down_column(pos) in SCORER_COLUMNS


# ── the fitter ──────────────────────────────────────────────────────────


def _weekly(player_id, pos, season, yards, first_downs, weeks=17):
    return [
        {
            "player_id": player_id,
            "position": pos,
            "season": season,
            "season_type": "REG",
            "receiving_yards": yards / weeks,
            "receiving_first_downs": first_downs / weeks,
        }
        for _ in range(weeks)
    ]


def test_the_fitter_recovers_a_planted_rate():
    rows = []
    for i in range(40):
        yards = 300.0 + i * 40
        rows += _weekly(f"p{i}", "WR", 2025, yards, yards * 0.05)
    out = fit_first_downs_per_yard(rows)
    assert out["rates"]["WR"] == pytest.approx(0.05, abs=1e-4)
    assert out["r2"]["WR"] > 0.99
    assert out["n"]["WR"] == 40


def test_the_fit_goes_through_the_origin():
    """Zero yards must mean zero first downs.

    A fitted intercept on 200+ yard players measured +1.2 for WRs and
    +4.2 for TEs — free first downs for a player projected for almost
    nothing. Planting data with a large positive intercept and asserting
    the fitted rate does NOT absorb it pins the shape.
    """
    rows = []
    for i in range(40):
        yards = 300.0 + i * 40
        rows += _weekly(f"p{i}", "WR", 2025, yards, 20.0 + yards * 0.05)
    out = fit_first_downs_per_yard(rows)
    # With an intercept the rate would come back ~0.05; through the
    # origin the +20 is spread across yards and inflates it.
    assert out["rates"]["WR"] > 0.055
    assert out["r2"]["WR"] < 0.99, "an intercept-shaped fit would still look perfect"


def test_thin_positions_are_omitted_rather_than_fitted_on_nothing():
    rows = []
    for i in range(5):
        rows += _weekly(f"p{i}", "TE", 2025, 500.0, 25.0)
    assert "TE" not in fit_first_downs_per_yard(rows)["rates"]


def test_low_yardage_players_are_excluded_from_the_fit():
    rows = []
    for i in range(40):
        rows += _weekly(f"p{i}", "WR", 2025, 50.0, 3.0)
    assert fit_first_downs_per_yard(rows)["rates"] == {}


def test_postseason_rows_are_excluded_by_default():
    rows = []
    for i in range(40):
        yards = 300.0 + i * 40
        rows += _weekly(f"p{i}", "WR", 2025, yards, yards * 0.05)
    post = [dict(r, season_type="POST", receiving_first_downs=0.0) for r in rows]
    assert fit_first_downs_per_yard(rows + post)["rates"]["WR"] == pytest.approx(0.05, abs=1e-4)
