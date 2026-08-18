"""Which positions get IDP scoring rules applied — and who owns that answer.

``SAF`` is the spelling the 2025 unified nflverse release uses for a safety.
It was in **neither** ``POSITION_ALIASES`` — which CLAUDE.md names the single
source of truth for position families — nor
``realized_points._IDP_POSITIONS``.

The consequence in the scoring engine is a silent zero of the exact kind this
package has now hit four times (``idp_pass_def``, ``idp_qb_hit``,
``def_tackles``, and this): ``_is_idp_position("SAF")`` returned False, so the
whole IDP block was skipped and every safety scored a well-formed 0.000 with no
reason and no flag.  Measured on the real 2025 REG feed against the live
``dynasty_main`` card: **1,429 player-weeks, 10,842.88 points never awarded**,
about 7.59 per affected player-week — starting safeties scoring roughly nothing.
Talanoa Hufanga alone lost 222.70.

Two consumers had already found this and patched it *locally*
(``league_comparison.scoring_engine._canonical_position``, whose comment says it
"was in neither POSITION_ALIASES nor this table", and
``bdvm.context.TRUE_POSITION_MAP``), which is why it did not surface in their
output — and is exactly why a third private copy in the scoring engine kept the
bug.  A position table that is not derived from the owner is a second owner.

Position-scoped understatement is also a *relative* bias, not merely a
magnitude error: crushing the DB group against DL and LB tilts every
comparison between them, the same argument the module header of
``scoring_coverage`` makes about partial corrections.
"""

from __future__ import annotations

import pytest

from src.nfl_data.realized_points import _IDP_POSITIONS, _is_idp_position, compute_weekly_points
from src.utils.name_clean import POSITION_ALIASES, normalize_position

#: A defensive line the engine must score identically however the feed spells
#: the player's position.
SAFETY_LINE = {
    "season": 2025,
    "week": 5,
    "def_tackles_solo": 6,
    "def_tackles_with_assist": 2,
    "def_tackle_assists": 3,
    "def_pass_defended": 2,
    "def_interceptions": 1,
    "def_interception_yards": 22,
}

CARD = {
    "idp_tkl_solo": 1.33,
    "idp_tkl_ast": 0.71,
    "idp_pd": 5.32,
    "idp_int": 4.25,
    "idp_int_ret_yd": 0.111,
}


def test_the_alias_owner_knows_the_feeds_safety_spelling():
    """CLAUDE.md makes POSITION_ALIASES the single source of truth. A spelling
    the live feed uses on 1,423 player-weeks belongs in it, not in three
    private workarounds."""
    assert POSITION_ALIASES.get("SAF") == "DB"
    assert normalize_position("SAF") == "DB"


@pytest.mark.parametrize("spelling", ["SAF", "S", "FS", "SS", "DB", "CB"])
def test_every_secondary_spelling_is_idp_scoring_eligible(spelling):
    assert _is_idp_position(spelling), f"{spelling} is a defensive back and must score IDP rules"


def test_a_safety_scores_the_same_however_the_feed_spells_him():
    """The defect, stated as the invariant it broke."""
    as_saf = compute_weekly_points({**SAFETY_LINE, "position": "SAF"}, CARD, position="SAF")
    as_s = compute_weekly_points({**SAFETY_LINE, "position": "S"}, CARD, position="S")
    assert as_saf.fantasy_points == as_s.fantasy_points
    assert as_saf.fantasy_points > 0, "a safety with 9 tackles, 2 PD and a pick scored nothing"


def test_a_safety_is_not_scored_as_zero():
    """The specific production symptom: well-formed 0.000, no reason, no flag."""
    rp = compute_weekly_points({**SAFETY_LINE, "position": "SAF"}, CARD, position="SAF")
    assert rp.fantasy_points == pytest.approx(
        6 * 1.33 + 2 * 1.33 + 3 * 0.71 + 2 * 5.32 + 4.25 + 22 * 0.111, abs=1e-6
    )


def test_idp_positions_is_derived_from_the_alias_owner():
    """Structural guard: the next spelling added to the owner must be scored
    automatically.  A hand-maintained mirror of the owner drifts from it —
    that is what produced this defect and the three local workarounds."""
    expected = {raw for raw, fam in POSITION_ALIASES.items() if fam in {"DL", "LB", "DB"}}
    assert (
        _IDP_POSITIONS == expected
    ), "the IDP-eligible set must be derived from POSITION_ALIASES, not restated"


def test_offensive_players_are_still_not_scored_by_idp_rules():
    """A WR credited with a tackle after a turnover is not IDP production the
    league pays under idp_* rules — he occupies no IDP slot.  317 WR rows
    recorded defensive events in 2025 and none of them may score here."""
    for pos in ("WR", "RB", "TE", "QB", "K", "OT"):
        assert not _is_idp_position(pos)
        rp = compute_weekly_points({**SAFETY_LINE, "position": pos}, CARD, position=pos)
        assert rp.fantasy_points == 0.0, f"{pos} scored IDP rules"
