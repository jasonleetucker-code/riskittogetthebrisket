"""The seven scoring rules the engine started reading on 2026-07-28.

Found by ``scoring_coverage`` auditing the live dynasty_main card. All
seven were live, nonzero, and contributing zero points:

    bonus_fd_qb / _rb / _wr / _te   13,323 unscored points across 2025
    pass_cmp                         1,762
    rush_att                         1,225
    pass_inc                         (a penalty rule, so it was making
                                      realized points too HIGH)

Effect on 2025 realized points, measured per position: QB +46.3%, RB
+44.4%, WR +33.5%, TE +33.2%.

**The asymmetry is the reason this mattered.** A uniform understatement
is a scale error and mostly harmless to comparisons; a 13-point spread
between position groups biases every relative judgement built on top —
the same failure that inverted the DB-vs-DL scoring tilt when one alias
was fixed and another was not.
"""

from __future__ import annotations

from src.nfl_data.realized_points import compute_weekly_points

_BASE_ROW = {
    "season": 2025,
    "week": 3,
    "attempts": 30,
    "completions": 20,
    "passing_first_downs": 12,
    "rushing_first_downs": 2,
    "receiving_first_downs": 0,
    "carries": 5,
}


def _points(row, scoring, position):
    rp = compute_weekly_points(dict(row), dict(scoring), position=position)
    return rp.fantasy_points if rp else 0.0


def test_first_down_bonus_pays_the_position_rate():
    """14 first downs (12 passing + 2 rushing) at the QB rate."""
    pts = _points(_BASE_ROW, {"bonus_fd_qb": 0.67}, "QB")
    assert pts == 14 * 0.67


def test_first_down_bonus_sums_every_play_type():
    """A position-scoped bonus pays the player for first downs gained by
    ANY means.

    An RB who catches one and runs for one has earned two. Reading only
    ``rushing_first_downs`` would quietly halve pass-catching backs — a
    per-archetype bias inside a single position group.
    """
    row = {
        **_BASE_ROW,
        "passing_first_downs": 0,
        "rushing_first_downs": 6,
        "receiving_first_downs": 4,
    }
    assert _points(row, {"bonus_fd_rb": 1.0}, "RB") == 10.0


def test_the_first_down_bonus_is_keyed_on_position():
    """A WR must not collect the QB's rate, and vice versa."""
    scoring = {"bonus_fd_qb": 0.67, "bonus_fd_wr": 1.0}
    assert _points(_BASE_ROW, scoring, "QB") == 14 * 0.67
    assert _points(_BASE_ROW, scoring, "WR") == 14 * 1.0


def test_positions_without_a_first_down_rule_get_nothing():
    """Defenders and kickers have no ``bonus_fd_*`` key, so the lookup
    must miss rather than fall back to some other position's rate."""
    scoring = {"bonus_fd_qb": 0.67, "bonus_fd_rb": 1.0}
    assert _points(_BASE_ROW, scoring, "LB") == 0.0
    assert _points(_BASE_ROW, scoring, "K") == 0.0


def test_completions_and_carries_score_per_play():
    assert _points(_BASE_ROW, {"pass_cmp": 0.15}, "QB") == 20 * 0.15
    assert _points(_BASE_ROW, {"rush_att": 0.08}, "RB") == 5 * 0.08


def test_incompletions_are_derived_from_attempts_minus_completions():
    """nflverse publishes no incompletion column; Sleeper charges the
    difference. 30 attempts - 20 completions = 10, at -0.22."""
    pts = _points(_BASE_ROW, {"pass_inc": -0.22}, "QB")
    assert abs(pts - (10 * -0.22)) < 1e-9


def test_a_negative_incompletion_count_never_awards_points():
    """The guard on a malformed row.

    ``pass_inc`` is a PENALTY. If completions somehow exceed attempts,
    the naive arithmetic yields a negative count times a negative rate —
    positive points, for throwing incompletions. Clamped instead.
    """
    row = {**_BASE_ROW, "attempts": 5, "completions": 20}
    assert _points(row, {"pass_inc": -0.22}, "QB") == 0.0


def test_a_zero_rate_contributes_nothing():
    """The baseline league zeroes all seven of these. A rule worth
    nothing must not appear in the breakdown or move the total."""
    for key in (
        "bonus_fd_qb",
        "bonus_fd_rb",
        "bonus_fd_wr",
        "bonus_fd_te",
        "pass_cmp",
        "pass_inc",
        "rush_att",
    ):
        assert _points(_BASE_ROW, {key: 0.0}, "QB") == 0.0


def test_each_new_rule_appears_in_the_breakdown():
    """The breakdown is the audit trail. A rule that moves the total
    without a labelled line is unexplainable to a user asking why their
    player scored what they scored.
    """
    rp = compute_weekly_points(
        dict(_BASE_ROW),
        {"bonus_fd_qb": 0.67, "pass_cmp": 0.15, "pass_inc": -0.22, "rush_att": 0.08},
        position="QB",
    )
    labels = {label for label, _, _ in rp.breakdown}
    assert {"First Downs", "Completions", "Incompletions", "Rush Att"} <= labels


def test_the_additions_do_not_disturb_existing_scoring():
    """A row scored under a card containing NONE of the new keys must
    produce exactly what it did before."""
    row = {**_BASE_ROW, "passing_yards": 300, "passing_tds": 2}
    scoring = {"pass_yd": 0.04, "pass_td": 4.0}
    assert _points(row, scoring, "QB") == 300 * 0.04 + 2 * 4.0
