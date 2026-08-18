"""#802 — joining the play-by-play supplement into realized points.

The producer (:mod:`src.nfl_data.pbp_weekly`) is validated against the
league host in ``test_pbp_weekly.py``. This file is about the SEAM: what
``compute_weekly_points`` does with the supplement, and — the part that
matters more — what it does without one.

The failure this closes is not "the number was wrong". It is that the
number was *presented as complete* while ten configured rules had no
source. On ``dynasty_main``'s card that is about two thirds of every
receiver's reception points. So the seam has three states, not two, and
they are asserted separately:

* supplement absent      → those rules are UNKNOWN, reported in ``unscored``
* supplement present, {} → the player recorded none, which is a real zero
* supplement present     → scored

Host-native rows take no supplement at all: Sleeper publishes these keys
itself, so merging a derived copy would pay several of them twice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.nfl_data.realized_points import (
    PBP_SUPPLEMENT_KEYS,
    PBP_SUPPLEMENT_ROW_KEY,
    compute_cumulative_points,
    compute_weekly_points,
)
from src.nfl_data.scoring_coverage import Coverage, audit_scoring_settings

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIVE_CARDS = json.loads((FIXTURES / "live_scoring_cards_2026-07-28.json").read_text("utf-8"))
DYNASTY_MAIN = LIVE_CARDS["dynasty_main"]


def _row(**kw):
    row = {"season": 2025, "week": 4, "position": "WR", "player_id": "00-a"}
    row.update(kw)
    return row


# ── The three states ─────────────────────────────────────────────────


def test_without_a_supplement_the_pbp_rules_are_reported_unknown():
    card = {"rec": 0.08, "rec_0_4": 0.25, "rec_40p": 2.0, "st_ff": 4.4, "pass_yd": 0.04}
    rp = compute_weekly_points(_row(receptions=5, receiving_yards=60), card, position="WR")

    assert dict(rp.unscored) == {"rec_0_4": 0.25, "rec_40p": 2.0, "st_ff": 4.4}
    assert rp.to_dict()["fantasyPointsComplete"] is False


def test_a_rule_the_card_pays_nothing_for_is_not_reported_unknown():
    """A rate of zero cannot cost anything, so naming it would be noise —
    the same reason ``audit_scoring_settings`` skips zero-rated keys."""
    card = {"rec": 0.08, "rec_0_4": 0.0, "st_ff": 4.4}
    rp = compute_weekly_points(_row(receptions=5), card, position="WR")
    assert dict(rp.unscored) == {"st_ff": 4.4}


def test_a_consulted_supplement_with_no_events_is_a_real_zero():
    """This is the distinction the whole seam exists for. An empty
    supplement means play-by-play WAS read and this player recorded none
    of these events — which scores zero honestly, and must not be
    reported as missing evidence."""
    card = {"rec": 0.08, "rec_0_4": 0.25, "st_ff": 4.4}
    row = _row(receptions=5, **{PBP_SUPPLEMENT_ROW_KEY: {}})
    rp = compute_weekly_points(row, card, position="WR")

    assert rp.unscored == ()
    assert rp.to_dict()["fantasyPointsComplete"] is True
    assert rp.to_dict()["unscored"] == []
    assert rp.fantasy_points == pytest.approx(0.4)


def test_a_supplement_is_scored_by_the_canonical_scorer():
    card = {"rec": 0.08, "rec_0_4": 0.25, "rec_10_19": 0.75, "st_tkl_solo": 1.38}
    row = _row(
        receptions=5,
        **{PBP_SUPPLEMENT_ROW_KEY: {"rec_0_4": 2, "rec_10_19": 3, "st_tkl_solo": 1}},
    )
    rp = compute_weekly_points(row, card, position="WR")

    assert rp.unscored == ()
    assert rp.fantasy_points == pytest.approx(5 * 0.08 + 2 * 0.25 + 3 * 0.75 + 1.38)
    labels = {label for (label, _stat, _pts) in rp.breakdown}
    assert {"Rec 0-4 yd", "Rec 10-19 yd", "ST Solo Tkl"} <= labels


# ── Guards ───────────────────────────────────────────────────────────


def test_the_supplement_cannot_overwrite_a_stat_the_weekly_feed_owns():
    """An allow-list, not a merge. ``kr_yd`` / ``pr_yd`` / ``st_td`` are on
    the weekly feed and are scored from it; letting the supplement write
    them — or ``rec``, or ``pass_yd`` — would give one number a second
    silent owner, and the two would disagree the first time a play was
    re-charted."""
    card = {"rec": 1.0, "kr_yd": 0.04, "rec_0_4": 0.25}
    row = _row(
        receptions=3,
        kickoff_return_yards=25,
        **{PBP_SUPPLEMENT_ROW_KEY: {"rec": 99, "kr_yd": 9999, "rec_0_4": 1}},
    )
    rp = compute_weekly_points(row, card, position="WR")
    assert rp.fantasy_points == pytest.approx(3 * 1.0 + 25 * 0.04 + 0.25)


def test_a_host_native_row_refuses_a_supplement():
    """The host publishes all ten keys itself. Silently resolving the
    combination would pay several of them twice; refusing says so."""
    row = {
        "season": 2025,
        "week": 4,
        "player_id_sleeper": "4046",
        "rec": 3,
        "rec_0_4": 1,
        PBP_SUPPLEMENT_ROW_KEY: {"rec_0_4": 1},
    }
    with pytest.raises(ValueError, match="double-count"):
        compute_weekly_points(row, {"rec": 1.0, "rec_0_4": 0.25}, position="WR", source="sleeper")


def test_a_malformed_supplement_is_ignored_rather_than_trusted():
    card = {"rec": 0.08, "rec_0_4": 0.25}
    row = _row(receptions=5, **{PBP_SUPPLEMENT_ROW_KEY: {"rec_0_4": "not a number"}})
    rp = compute_weekly_points(row, card, position="WR")
    assert rp.fantasy_points == pytest.approx(0.4)


# ── Aggregation ──────────────────────────────────────────────────────


def test_one_unavailable_week_makes_the_season_total_a_lower_bound():
    """The union, not a sum. A rule missing in one week of seventeen still
    means the season total is understated, and that has to survive the
    roll-up or the caller sees a complete-looking number."""
    card = {"rec": 0.08, "rec_0_4": 0.25}
    rows = [
        _row(week=1, receptions=4, **{PBP_SUPPLEMENT_ROW_KEY: {"rec_0_4": 2}}),
        _row(week=2, receptions=4),
    ]
    out = compute_cumulative_points(rows, card, position="WR")

    assert out["totalPointsComplete"] is False
    assert out["unscored"] == [{"key": "rec_0_4", "rate": 0.25}]


def test_a_fully_supplemented_season_reports_complete():
    card = {"rec": 0.08, "rec_0_4": 0.25}
    rows = [_row(week=w, receptions=4, **{PBP_SUPPLEMENT_ROW_KEY: {"rec_0_4": 1}}) for w in (1, 2)]
    out = compute_cumulative_points(rows, card, position="WR")
    assert out["totalPointsComplete"] is True
    assert out["unscored"] == []


# ── Coverage, on the real card ───────────────────────────────────────


def test_the_live_card_has_no_unscorable_rule_left_once_the_join_is_made():
    """The measurable claim. Before this change ten configured nonzero
    rules on ``dynasty_main`` were UNSCORABLE; the supplement is the only
    thing standing between that and complete coverage, so the two audits
    are asserted against each other rather than against a hand-written
    expectation."""
    without = audit_scoring_settings(DYNASTY_MAIN, pbp_supplement=False)
    with_join = audit_scoring_settings(DYNASTY_MAIN, pbp_supplement=True)

    assert set(without[Coverage.UNSCORABLE]) == set(PBP_SUPPLEMENT_KEYS)
    assert with_join[Coverage.UNSCORABLE] == {}
    assert with_join[Coverage.GAP] == {}
    assert set(with_join[Coverage.SCORED]) == set(without[Coverage.SCORED]) | PBP_SUPPLEMENT_KEYS


def test_coverage_still_defaults_to_the_bare_nflverse_path():
    """Coverage is a property of the engine AND its inputs. Answering as
    though the supplement were present when the caller does not join it
    is the same overstatement this whole unit exists to remove."""
    assert set(audit_scoring_settings(DYNASTY_MAIN)[Coverage.UNSCORABLE]) == set(
        PBP_SUPPLEMENT_KEYS
    )
