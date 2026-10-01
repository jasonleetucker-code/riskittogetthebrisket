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
