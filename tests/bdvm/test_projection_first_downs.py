"""BDVM scores a projected line as if it were a realized one — except
projections have no first-down columns.

BDVM deliberately reuses ``compute_weekly_points`` so a league config
that scores history correctly scores projections identically. That is
the right design and it has one leak: the scorer reads first downs from
``*_first_downs`` columns, and no projection source publishes them.

Under this league's card (1.00 per first down for RB/WR/TE, 0.67 QB) a
projected line scored as-is loses 22-30% of a player's points. Two
things make that worse than a scale error:

* it is **uneven** — 1.44x for a QB against 1.29x for a back — so it
  survives a relative comparison, which is all BDVM produces;
* it is **mixed** — the reconstructed baseline scores REAL weekly rows,
  which DO have the columns, so within one snapshot a Clay-covered
  player sits ~24% below an otherwise identical proxy player.

The second is the one that would have been hardest to spot: nothing
errors, and both numbers look ordinary.
"""

from __future__ import annotations

import pytest

from src.bdvm.projections import ProjectionRecord
from src.bdvm.scoring import score_stat_line_per_game
from src.nfl_data.first_down_rate import FIRST_DOWNS_PER_YARD

# This league's real shape, trimmed to what these lines exercise.
CARD = {
    "pass_yd": 0.04,
    "pass_td": 6.0,
    "pass_int": -4.0,
    "rush_yd": 0.1,
    "rush_td": 6.0,
    "rec": 0.08,
    "rec_yd": 0.1,
    "rec_td": 6.0,
    "bonus_fd_qb": 0.67,
    "bonus_fd_rb": 1.0,
    "bonus_fd_wr": 1.0,
    "bonus_fd_te": 1.0,
}

# The exact vocabulary src/bdvm/clay_projections.py emits — no first downs.
CLAY_SHAPED = {
    "QB": {
        "attempts": 560,
        "completions": 370,
        "passing_yards": 4200,
        "passing_tds": 30,
        "interceptions": 11,
        "carries": 60,
        "rushing_yards": 320,
        "rushing_tds": 3,
    },
    "RB": {
        "carries": 260,
        "rushing_yards": 1150,
        "rushing_tds": 9,
        "receptions": 52,
        "receiving_yards": 400,
        "receiving_tds": 2,
    },
    "WR": {"receptions": 95, "receiving_yards": 1250, "receiving_tds": 8},
    "TE": {"receptions": 78, "receiving_yards": 820, "receiving_tds": 6},
}


def _score(pos, *, impute):
    return score_stat_line_per_game(CLAY_SHAPED[pos], CARD, position=pos, impute_first_downs=impute)


# ── the gap is real, and it is uneven ───────────────────────────────────


def test_scoring_a_projection_without_the_imputation_loses_real_points():
    """Non-vacuity for everything below: the gap must actually exist on
    a source-shaped line, or the fix is fixing nothing."""
    for pos in CLAY_SHAPED:
        off, on = _score(pos, impute=False), _score(pos, impute=True)
        assert on > off, f"{pos} scored identically with and without first downs"
        assert (on - off) / on > 0.15, f"{pos} gap is only {(on - off) / on:.1%}"


def test_the_gap_is_uneven_across_positions_so_it_does_not_cancel():
    """THE REASON THIS MATTERS.

    BDVM produces relative value. A uniform scale error would wash out
    of every comparison it makes; this one does not — a QB is inflated
    substantially more than a back, which reprices superflex's central
    question.
    """
    inflation = {pos: _score(pos, impute=True) / _score(pos, impute=False) for pos in CLAY_SHAPED}
    assert (
        inflation["QB"] > inflation["RB"] * 1.05
    ), f"expected the QB gap to exceed the RB gap materially, got {inflation}"


def test_a_proxy_row_and_a_real_source_row_now_agree():
    """The mixed-snapshot failure, in one assertion.

    A proxy row is scored from realized weekly stats, which DO carry
    first downs; a real-source row is scored from a projection that does
    not. Same player, same production, two numbers ~24% apart inside one
    snapshot — and nothing anywhere says which is which.
    """
    pos = "WR"
    realized_shaped = dict(
        CLAY_SHAPED[pos],
        receiving_first_downs=CLAY_SHAPED[pos]["receiving_yards"] * FIRST_DOWNS_PER_YARD[pos],
    )
    proxy = score_stat_line_per_game(realized_shaped, CARD, position=pos)
    real_source = _score(pos, impute=True)
    assert real_source == pytest.approx(proxy, rel=1e-9)

    # And the divergence it closes was large.
    unfixed = _score(pos, impute=False)
    assert (proxy - unfixed) / proxy > 0.20


# ── the default stays off ───────────────────────────────────────────────


def test_the_scorer_does_not_impute_unless_asked():
    """Explicit at the call site, so the behaviour change stays visible
    in the diff forever rather than becoming an invisible default."""
    assert score_stat_line_per_game(CLAY_SHAPED["WR"], CARD, position="WR") == pytest.approx(
        _score("WR", impute=False)
    )


def test_a_league_that_does_not_pay_first_downs_is_unaffected():
    """No gate needed — the scorer multiplies by a rate of 0.0. Asserted
    so nobody adds one, and so a future refactor that starts adding raw
    counts somewhere gets caught."""
    no_fd = {k: v for k, v in CARD.items() if not k.startswith("bonus_fd_")}
    for pos in CLAY_SHAPED:
        off = score_stat_line_per_game(CLAY_SHAPED[pos], no_fd, position=pos)
        on = score_stat_line_per_game(
            CLAY_SHAPED[pos], no_fd, position=pos, impute_first_downs=True
        )
        assert on == pytest.approx(off)


# ── the projection record ───────────────────────────────────────────────


def test_the_projection_path_imputes_and_the_fact_is_inspectable():
    proj = ProjectionRecord(
        player_key="wr1",
        position="WR",
        source="clayProjections",
        season=2026,
        as_of="2026-07-28T00:00:00+00:00",
        stat_line=CLAY_SHAPED["WR"],
        stat_basis="season",
        games=17.0,
    )
    fpg, native = proj.resolve_fpg(CARD)
    assert native is True
    assert proj.first_downs_imputed is True
    assert fpg == pytest.approx(_score("WR", impute=True) / 17.0)


def test_a_source_that_supplies_first_downs_is_reported_as_not_imputed():
    proj = ProjectionRecord(
        player_key="wr2",
        position="WR",
        source="manualCsv",
        season=2026,
        as_of="2026-07-28T00:00:00+00:00",
        stat_line=dict(CLAY_SHAPED["WR"], receiving_first_downs=55.0),
        stat_basis="season",
        games=17.0,
    )
    assert proj.first_downs_imputed is False


def test_a_points_only_projection_reports_no_imputation():
    """``fpg``/``fpts`` projections never touch the stat-line path, so
    claiming an imputation for them would be a lie about provenance."""
    proj = ProjectionRecord(
        player_key="wr3",
        position="WR",
        source="someSource",
        season=2026,
        as_of="2026-07-28T00:00:00+00:00",
        fpg=14.2,
        games=17.0,
    )
    assert proj.first_downs_imputed is False
