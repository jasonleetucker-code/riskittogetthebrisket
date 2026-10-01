"""Position-scoped reception bonuses are an EXACT mapping, not a derivation.

Sleeper's ``bonus_rec_rb`` / ``bonus_rec_wr`` / ``bonus_rec_te`` pay a
per-reception rate scoped by the receiver's position.  Every projection
source BDVM consumes already publishes ``receptions`` and the record
carries the position, so the rule is fully supplied by an existing field.

Before this change only ``bonus_rec_te`` was emitted by the normalizer, so
dynasty_main's live 2026 card (``bonus_rec_wr: 0.02``) scored a silent
zero for every wide receiver — and NOT as a reported ``unscoredKeys``
entry, because ``unscored`` only tracks the play-by-play rules.  The
engine coverage probe classified it ``GAP`` (the scoring census surfaced
it as the only MAPPING_ERROR on either live card).
"""

from __future__ import annotations

import pytest

from src.bdvm.scoring import score_stat_line_per_game_detailed
from src.nfl_data.realized_points import compute_weekly_points
from src.nfl_data.scoring_coverage import Coverage, classify

LINE = {"receptions": 6.0, "receiving_yards": 70.0}
BASE = {"rec": 1.0, "rec_yd": 0.1}


@pytest.mark.parametrize(
    "position,key", [("WR", "bonus_rec_wr"), ("RB", "bonus_rec_rb"), ("TE", "bonus_rec_te")]
)
def test_bonus_pays_its_own_position_per_reception(position, key):
    base, _ = score_stat_line_per_game_detailed(LINE, BASE, position=position)
    with_bonus, unscored = score_stat_line_per_game_detailed(
        LINE, {**BASE, key: 0.5}, position=position
    )
    assert with_bonus == pytest.approx(base + 0.5 * 6.0)
    assert unscored == ()


@pytest.mark.parametrize(
    "position,foreign",
    [
        ("WR", ("bonus_rec_rb", "bonus_rec_te")),
        ("RB", ("bonus_rec_wr", "bonus_rec_te")),
        ("TE", ("bonus_rec_wr", "bonus_rec_rb")),
        ("QB", ("bonus_rec_wr", "bonus_rec_rb", "bonus_rec_te")),
    ],
)
def test_bonus_never_pays_another_position(position, foreign):
    base, _ = score_stat_line_per_game_detailed(LINE, BASE, position=position)
    card = {**BASE, **{k: 0.5 for k in foreign}}
    scored, _ = score_stat_line_per_game_detailed(LINE, card, position=position)
    assert scored == pytest.approx(base)


def test_live_dynasty_main_wr_bonus_rate_is_paid():
    """The live card's 0.02/reception on a 6-catch WR line."""
    card = {**BASE, "bonus_rec_wr": 0.02}
    rp = compute_weekly_points(
        {"season": 2025, "week": 1, "receptions": 6, "receiving_yards": 70},
        card,
        position="WR",
    )
    assert rp is not None
    assert rp.fantasy_points == pytest.approx(6.0 + 7.0 + 0.12)


def test_no_double_count_with_te_bonus():
    """A TE under a card carrying all three rates is paid the TE rate once."""
    card = {**BASE, "bonus_rec_te": 0.5, "bonus_rec_wr": 0.25, "bonus_rec_rb": 0.1}
    scored, _ = score_stat_line_per_game_detailed(LINE, card, position="TE")
    base, _ = score_stat_line_per_game_detailed(LINE, BASE, position="TE")
    assert scored == pytest.approx(base + 3.0)


@pytest.mark.parametrize("key", ["bonus_rec_wr", "bonus_rec_rb", "bonus_rec_te"])
def test_engine_probe_classifies_every_reception_bonus_scored(key):
    assert classify(key) is Coverage.SCORED


# --------------------------------------------------------------------------
# Host verification — Sleeper's own awarded points, not our assumption
# --------------------------------------------------------------------------

#: Observed 2026-10-01 from the PUBLIC Sleeper API for dynasty_main (live card
#: ``rec`` 0.1, ``bonus_rec_wr`` 0.02), 2026 week 1.  ``host`` is the league's
#: ``players_points``; ``without`` is the host's own stat line rescored by the
#: golden-validated exact scorer with ``bonus_rec_wr`` zeroed.  Numbers only.
#: Full run (401 WR player-weeks, 291 joined to nflverse):
#: docs/research/bdvm-v1/scoring-census-2026-10-01/host_verification.json.
HOST_OBSERVATIONS = (
    # (receptions, host players_points, host line rescored WITHOUT the rule)
    (5, 22.55, 22.45),
    (5, 13.65, 13.55),
    (6, 14.37, 14.25),
    (8, 31.66, 31.50),
    (8, 37.26, 37.10),
)
HOST_TOLERANCE = 0.011  # the host publishes two decimals (same as W18 R4)


@pytest.mark.parametrize("receptions,host,without", HOST_OBSERVATIONS)
def test_engine_reproduces_the_host_awarded_wr_reception_bonus(receptions, host, without):
    """The host DOES pay ``bonus_rec_wr`` per reception: dropping the rule
    misses its points, and this mapping (receptions x rate, from the nflverse
    row) reproduces exactly the part the rule contributes."""
    host_bonus = host - without
    assert host_bonus > HOST_TOLERANCE  # without the rule, the host total is missed
    rp = compute_weekly_points(
        {"season": 2026, "week": 1, "receptions": receptions},
        {"bonus_rec_wr": 0.02},
        position="WR",
    )
    assert rp is not None
    assert rp.fantasy_points == pytest.approx(host_bonus, abs=HOST_TOLERANCE)


@pytest.mark.parametrize("key", ["bonus_rec_rb", "bonus_fd_rb"])
def test_fullback_is_not_paid_the_rb_bonus(key):
    """Sleeper's stat feed carries neither ``bonus_rec_rb`` nor ``bonus_fd_rb``
    on an FB's line (host_verification.json ``fbReceptionLines``), so a raw
    ``FB`` earns no RB-scoped bonus here.  (The BDVM baseline/actuals remap
    FB -> RB first — a documented divergence, see realized_points.)"""
    row = {
        "season": 2026,
        "week": 2,
        "receptions": 2,
        "receiving_yards": 27,
        "receiving_first_downs": 1,
        "receiving_tds": 0,
    }
    plain = compute_weekly_points(row, {"rec": 1.0}, position="FB")
    paid = compute_weekly_points(row, {"rec": 1.0, key: 0.5}, position="FB")
    assert plain is not None and paid is not None
    assert paid.fantasy_points == pytest.approx(plain.fantasy_points)
