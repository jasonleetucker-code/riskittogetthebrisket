"""build_lines / detect_layout on synthetic word boxes."""

from __future__ import annotations

import pytest

from src.trade.screenshot_import.layout import (
    CONFIDENCE_FLOOR,
    build_lines,
    classify_noise,
    detect_layout,
    is_equalizer_header,
    match_anchor,
)

from .conftest import page

W = 1200


def _texts(lines):
    return [ln.text for ln in lines]


def test_two_column_row_yields_two_segments():
    lines = build_lines(page(("Patrick Mahomes", 60, 100), ("Bijan Robinson", 660, 100)))
    assert _texts(lines) == ["Patrick Mahomes", "Bijan Robinson"]
    assert lines[0].row == lines[1].row


def test_words_of_one_name_stay_together_and_rows_split_by_height():
    lines = build_lines(page(("Jaxon Smith-Njigba WR SEA", 60, 100), ("2027 1st", 60, 160)))
    assert _texts(lines) == ["Jaxon Smith-Njigba WR SEA", "2027 1st"]
    assert lines[0].row != lines[1].row


@pytest.mark.parametrize(
    "text,expected",
    [
        ("You give", (0, 0)),
        ("You get", (0, 1)),
        ("Send", (4, 0)),
        ("Receiving", (5, 1)),
        ("Team A", (6, 0)),
        ("TEAM 2", (7, 1)),
        ("Team 1 gives", (7, 0)),
        ("You give: 7,200", (0, 0)),
        ("Trade away", (8, 0)),
        ("Patrick Mahomes", None),
        ("Get Ready", None),
    ],
)
def test_anchor_matching(text, expected):
    assert match_anchor(text) == expected


@pytest.mark.parametrize(
    "text,reason",
    [
        ("4,512", "value_number"),
        ("+312", "value_number"),
        ("9999", "value_number"),
        ("52%", "percentage"),
        ("+3.1 %", "percentage"),
        ("A+", "grade"),
        ("B-", "grade"),
        ("Total", "label"),
        ("Total: 7,200", "label"),
        ("Value Adjustment", "label"),
        ("Value Adjustment +312", "label"),
        ("Trade Value", "label"),
        ("Win-Win", "label"),
        ("Accept", "label"),
        ("Home", "navigation"),
        ("Log in", "navigation"),
        ("2028 1.05", None),
        ("Patrick Mahomes", None),
    ],
)
def test_noise_classification(text, reason):
    assert classify_noise(text) == reason


def test_equalizer_headers():
    assert is_equalizer_header("Suggested players")
    assert is_equalizer_header("Add to even")
    assert is_equalizer_header("Players to balance")
    assert not is_equalizer_header("Bijan Robinson")


def test_left_right_two_column_with_anchors():
    lines = build_lines(
        page(
            ("You give", 60, 40),
            ("You get", 660, 40),
            ("Patrick Mahomes", 60, 100),
            ("4,512", 460, 100),
            ("2027 1st", 60, 150),
            ("Bijan Robinson", 660, 100),
            ("Quay Walker", 660, 150),
        )
    )
    lay = detect_layout(lines, W)
    assert lay.kind == "two_column" and lay.confidence >= 0.9
    assert [s.label for s in lay.sides] == ["You give", "You get"]
    assert all(s.label_source == "anchor" for s in lay.sides)
    assert _texts(lay.sides[0].lines) == ["Patrick Mahomes", "2027 1st"]
    assert _texts(lay.sides[1].lines) == ["Bijan Robinson", "Quay Walker"]
    assert ("4,512", "value_number") in [(ln.text, r) for ln, r in lay.ignored]


def test_side_a_is_the_left_anchor_even_when_it_is_the_second_slot():
    lines = build_lines(
        page(("You get", 60, 40), ("You give", 660, 40), ("Bijan Robinson", 60, 100))
    )
    lay = detect_layout(lines, W)
    assert [s.label for s in lay.sides] == ["You get", "You give"]


def test_narrow_anchor_row_read_as_one_segment_is_split():
    lines = build_lines(page(("You give You get", 60, 40), ("Bijan Robinson", 60, 100)))
    lay = detect_layout(lines, 400)
    assert len(lay.sides) == 2


def test_stacked_mobile_with_anchors():
    lines = build_lines(
        page(
            ("Team A", 40, 40),
            ("Bijan Robinson", 40, 100),
            ("2027 1st", 40, 150),
            ("Team B", 40, 260),
            ("Patrick Mahomes", 40, 320),
        )
    )
    lay = detect_layout(lines, 750)
    assert lay.kind == "stacked"
    assert _texts(lay.sides[0].lines) == ["Bijan Robinson", "2027 1st"]
    assert _texts(lay.sides[1].lines) == ["Patrick Mahomes"]


def test_lines_above_the_anchors_are_outside_the_trade_region():
    # A pair of side labels defines the trade region; text above it is page
    # furniture — ignored with a reason, never guessed onto a side and never
    # offered as "needs a side".
    lines = build_lines(
        page(
            ("Bijan Robinson", 60, 10),
            ("You give", 60, 80),
            ("You get", 660, 80),
            ("Patrick Mahomes", 60, 140),
        )
    )
    lay = detect_layout(lines, W)
    assert lay.unassigned == ()
    assert _texts(lay.sides[0].lines) == ["Patrick Mahomes"]
    assert ("Bijan Robinson", "outside_trade_region") in [(ln.text, r) for ln, r in lay.ignored]


def test_equalizer_region_is_ignored_within_its_side_only():
    lines = build_lines(
        page(
            ("You give", 60, 40),
            ("You get", 660, 40),
            ("Patrick Mahomes", 60, 100),
            ("Bijan Robinson", 660, 100),
            ("Suggested", 660, 200),
            ("Chris Jones", 660, 260),
            ("Quay Walker", 60, 260),
        )
    )
    lay = detect_layout(lines, W)
    assert _texts(lay.sides[0].lines) == ["Patrick Mahomes", "Quay Walker"]
    assert _texts(lay.sides[1].lines) == ["Bijan Robinson"]
    reasons = {ln.text: r for ln, r in lay.ignored}
    assert reasons["Chris Jones"] == "equalizer_region"
    assert reasons["Suggested"] == "equalizer_header"


def test_no_anchors_ambiguous_geometry_is_unassigned_with_low_confidence():
    lines = build_lines(
        page(
            ("Patrick Mahomes", 60, 100),
            ("Bijan Robinson", 300, 160),
            ("Quay Walker", 520, 220),
            ("Jordan Davis", 140, 280),
        )
    )
    lay = detect_layout(lines, W)
    assert lay.confidence < CONFIDENCE_FLOOR
    assert lay.sides == ()
    assert len(lay.unassigned) == 4


def test_no_anchors_single_column_is_unassigned():
    lines = build_lines(page(("Patrick Mahomes", 60, 100), ("Bijan Robinson", 60, 160)))
    lay = detect_layout(lines, W)
    assert lay.kind == "single" and lay.confidence < CONFIDENCE_FLOOR
    assert lay.sides == () and len(lay.unassigned) == 2


def test_no_anchors_clean_columns_are_positional_sides():
    lines = build_lines(
        page(
            ("Patrick Mahomes", 60, 100),
            ("2027 1st", 60, 160),
            ("Bijan Robinson", 700, 100),
            ("Quay Walker", 700, 160),
        )
    )
    lay = detect_layout(lines, W)
    assert lay.kind == "two_column" and CONFIDENCE_FLOOR <= lay.confidence < 0.7
    assert [s.label_source for s in lay.sides] == ["position", "position"]


def test_single_anchor_is_a_single_side():
    lines = build_lines(
        page(("You get", 60, 40), ("Bijan Robinson", 60, 100), ("2027 1st", 60, 150))
    )
    lay = detect_layout(lines, W)
    assert lay.kind == "single" and len(lay.sides) == 1
    assert lay.sides[0].label == "You get"
    assert _texts(lay.sides[0].lines) == ["Bijan Robinson", "2027 1st"]


def test_empty_input():
    assert build_lines([]) == []
    lay = detect_layout([], W)
    assert lay.kind == "unknown" and lay.sides == () and lay.unassigned == ()
