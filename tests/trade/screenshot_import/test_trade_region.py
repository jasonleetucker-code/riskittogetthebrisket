"""Trade-region detection on UNCROPPED screenshots (synthetic word boxes).

An ordinary full-page screenshot carries browser chrome, site navigation,
recommendation / insight widgets and ads around the trade.  A pair of side
labels defines the trade region: one container per side, derived from
geometry only; text outside every container is ``ignored`` as
``outside_trade_region`` and is never offered as "needs a side".  Without a
trustworthy region nothing is placed on a side (``trade_region_not_detected``)
and unrecognised page text is filtered rather than dumped into the tray.

Every page is also run at other scales — nothing here may depend on one
screenshot's pixel coordinates.
"""

from __future__ import annotations

import pytest

from src.trade.screenshot_import.layout import (
    build_lines,
    classify_noise,
    detect_layout,
    is_region_boundary,
    is_total_line,
    match_anchor,
)
from src.trade.screenshot_import.ocr import Word
from src.trade.screenshot_import.service import build_extraction

from .conftest import phrase

# The real full-page trade-calculator screenshot's layout (2000 x 1250),
# reduced to word boxes.  Chrome / tab text is neutral placeholder text.
KTC_W, KTC_H = 2000, 1250
KTC_PAGE: tuple[tuple[str, int, int], ...] = (
    ("Tab One", 100, 20),
    ("Tab Two", 400, 20),
    ("example.com/trade-calculator", 220, 80),
    ("Bookmarks Folder", 110, 130),
    ("Choose from dynasty values powered by real trades", 580, 188),
    ("Dynasty Football Trade Calculator", 280, 270),
    ("Superflex", 23, 381),
    ("VALUE SOURCE", 320, 436),
    ("INSIGHTS", 1553, 453),
    ("DYNASTY RESOURCES", 23, 519),
    ("BIGGEST 30 DAY RISER", 1550, 508),
    ("Team 1 gets...", 340, 528),
    ("Team 2 gets...", 969, 528),
    ("Trade Calculator", 55, 565),
    ("Search for a player", 343, 592),
    ("Search for a player", 971, 592),
    ("Dynasty Rankings", 55, 617),
    ("Bryce Young", 1547, 646),
    ("Omarion Hampton", 1762, 646),
    ("League Power", 55, 661),
    ("Jaxson Dart", 342, 661),
    ("QB11 · NYG · 23.4 y.o.", 546, 661),
    ("5542", 765, 661),
    ("De'Von Achane", 970, 661),
    ("RB10 · MIA · 25 y.o.", 1193, 661),
    ("5507", 1393, 661),
    ("QB · CAR · 25.2 y.o.", 1547, 675),
    ("RB · LAC · 23.6 y.o.", 1763, 675),
    ("Trade Database", 55, 720),
    ("1 Total Pieces", 343, 727),
    ("1 Total Pieces", 972, 727),
    ("5,542", 744, 740),
    ("5,507", 1373, 740),
    ("Waiver Database", 55, 769),
    ("HOT IN HAIR", 1668, 807),
    ("Fair Trade", 840, 858),
    ("Copy Trade URL", 690, 948),
    ("Clear Calculator", 940, 948),
    ("Strengthening Scalp Serum", 1570, 945),
    ("HOT IN HAIR", 439, 1065),
    ("Treatment Hair Oil", 909, 1079),
)


def _words(rows, scale: float = 1.0, h: int = 20) -> list[Word]:
    out: list[Word] = []
    for text, x, y in rows:
        out.extend(phrase(text, round(x * scale), round(y * scale), h=max(4, round(h * scale))))
    return out


def _extract(rows, identity_ctx, board, *, width, height, scale: float = 1.0, h: int = 20):
    return build_extraction(
        _words(rows, scale, h),
        width=round(width * scale),
        height=round(height * scale),
        identity_ctx=identity_ctx,
        contract=board,
    )


def _names(side) -> list:
    return [it["boardName"] for it in side["items"]]


def _ignored(out) -> dict:
    return {ig["raw"]: ig["reason"] for ig in out["ignored"]}


@pytest.mark.parametrize("scale", [1.0, 0.55, 1.6])
def test_full_page_ktc_layout_reads_exactly_the_trade(scale, identity_ctx, board):
    out = _extract(KTC_PAGE, identity_ctx, board, width=KTC_W, height=KTC_H, scale=scale)
    assert out["layout"] == {"kind": "two_column", "confidence": 0.95}
    assert [s["label"] for s in out["sides"]] == ["Team 1 gets", "Team 2 gets"]
    assert [s["labelSource"] for s in out["sides"]] == ["anchor", "anchor"]
    assert _names(out["sides"][0]) == ["Jaxson Dart"]
    assert _names(out["sides"][1]) == ["De'Von Achane"]
    assert out["unassigned"] == []
    assert out["warnings"] == []
    reasons = _ignored(out)
    # The insights widget's players are page furniture, never assets.
    assert reasons["Bryce Young"] == "outside_trade_region"
    assert reasons["Omarion Hampton"] == "outside_trade_region"
    # Chrome, sidebar navigation and ads too.
    for text in ("Tab One", "Bookmarks Folder", "League Power", "Treatment Hair Oil"):
        assert reasons[text] == "outside_trade_region"
    assert reasons["Search for a player"] == "search_placeholder"
    assert reasons["1 Total Pieces"] == "label"
    assert reasons["Fair Trade"] == "label"
    assert reasons["5,542"] == "value_number"
    # Row metadata is a resolution HINT, not an asset.
    dart = out["sides"][0]["items"][0]
    assert dart["hints"] == {"position": "QB", "team": "NYG"}
    assert out["sides"][1]["items"][0]["hints"] == {"position": "RB", "team": "MIA"}
    # Canonical identity: Sleeper ids from the directory, never the KTC numbers.
    assert dart["sleeperId"] == "12508"
    assert out["sides"][1]["items"][0]["sleeperId"] == "9226"


def test_cropped_trade_area_reads_the_same(identity_ctx, board):
    crop_x, crop_y = 300, 495
    rows = [
        (t, x - crop_x, y - crop_y) for t, x, y in KTC_PAGE if 300 <= x < 1490 and 495 <= y < 790
    ]
    out = _extract(rows, identity_ctx, board, width=1190, height=295)
    assert _names(out["sides"][0]) == ["Jaxson Dart"]
    assert _names(out["sides"][1]) == ["De'Von Achane"]
    assert out["unassigned"] == []


def test_multiple_players_and_future_picks_per_side(identity_ctx, board):
    rows = (
        ("Dashboard", 20, 110),
        ("Chris Jones", 20, 300),  # sidebar "trending" — a real board player
        ("Team A gets...", 290, 194),
        ("Team B gets...", 820, 194),
        ("Patrick Mahomes", 290, 330),
        ("QB · KC · 30 y.o.", 520, 330),
        ("Quay Walker", 290, 390),
        ("2027 Early 1st", 290, 450),
        ("2028 2nd", 290, 510),
        ("Bijan Robinson", 820, 330),
        ("Travis Hunter", 820, 390),
        ("2027 Mid 1st", 820, 450),
        ("2029 3rd", 820, 510),
        ("4 Total Pieces", 290, 580),
        ("4 Total Pieces", 820, 580),
        ("Slightly favors Team A", 650, 650),
        ("Brian Thomas Jr.", 1340, 330),  # insights widget
        ("Josh Allen", 1340, 450),
    )
    out = _extract(rows, identity_ctx, board, width=1600, height=1000)
    assert _names(out["sides"][0]) == [
        "Patrick Mahomes",
        "Quay Walker",
        "2027 Early 1st",
        "2028 Round 2",
    ]
    assert _names(out["sides"][1]) == [
        "Bijan Robinson",
        "Travis Hunter",
        "2027 Mid 1st",
        "2029 Round 3",
    ]
    assert out["unassigned"] == []
    reasons = _ignored(out)
    for name in ("Chris Jones", "Brian Thomas Jr.", "Josh Allen"):
        assert reasons[name] == "outside_trade_region"


@pytest.mark.parametrize("scale", [1.0, 0.5])
def test_mobile_stacked_with_widgets_below_the_trade(scale, identity_ctx, board):
    rows = (
        ("9:41", 40, 20),
        ("Trade Calculator", 40, 115),
        ("Team 1 gets...", 60, 282),
        ("Search for a player", 60, 392),
        ("Kenneth Walker III RB KC", 60, 480),
        ("2027 Late 1st", 60, 600),
        ("2 Total Pieces", 60, 720),
        ("Team 2 gets...", 60, 842),
        ("Josh Hines-Allen", 60, 1040),
        ("Marvin Harrison Jr.", 60, 1160),
        ("2026 1.05", 60, 1280),
        ("3 Total Pieces", 60, 1400),
        ("Fair Trade", 420, 1502),
        ("Trending players", 60, 1640),
        ("Bijan Robinson", 60, 1710),
        ("Patrick Mahomes", 60, 1780),
    )
    out = _extract(rows, identity_ctx, board, width=1080, height=2200, scale=scale, h=40)
    assert out["layout"]["kind"] == "stacked"
    assert [s["label"] for s in out["sides"]] == ["Team 1 gets", "Team 2 gets"]
    assert _names(out["sides"][0]) == ["Kenneth Walker III", "2027 Late 1st"]
    assert _names(out["sides"][1]) == ["Josh Hines-Allen", "Marvin Harrison Jr.", "2026 Pick 1.05"]
    assert out["unassigned"] == []
    reasons = _ignored(out)
    assert reasons["Bijan Robinson"] == "outside_trade_region"
    assert reasons["Patrick Mahomes"] == "outside_trade_region"


def test_centred_side_labels_still_contain_their_left_aligned_lists(identity_ctx, board):
    rows = (
        ("You give", 260, 40),
        ("You get", 860, 40),
        ("Patrick Mahomes", 60, 120),
        ("2027 1st", 60, 180),
        ("Bijan Robinson", 660, 120),
        ("Quay Walker", 660, 180),
    )
    out = _extract(rows, identity_ctx, board, width=1200, height=400)
    assert _names(out["sides"][0]) == ["Patrick Mahomes", "2027 Round 1"]
    assert _names(out["sides"][1]) == ["Bijan Robinson", "Quay Walker"]


def test_one_side_label_never_invents_the_other_side(identity_ctx, board):
    rows = (
        ("TradeLab", 20, 18),
        ("You give", 80, 133),
        ("Patrick Mahomes", 80, 220),
        ("2027 1st", 80, 290),
        ("Bijan Robinson", 640, 220),  # the other side's list, its label unread
        ("Brian Thomas Jr.", 1140, 170),  # an insights widget
    )
    out = _extract(rows, identity_ctx, board, width=1400, height=760)
    assert out["layout"]["kind"] == "single"
    assert [s["label"] for s in out["sides"]] == ["You give"]
    assert _names(out["sides"][0]) == ["Patrick Mahomes", "2027 Round 1"]
    # Not pulled onto "You give", not given a positional "Side B" either.
    assert sorted(it["boardName"] for it in out["unassigned"]) == [
        "Bijan Robinson",
        "Brian Thomas Jr.",
    ]
    assert "missing_side" in out["warnings"]


def test_no_side_labels_falls_back_without_dumping_the_page(identity_ctx, board):
    rows = (
        ("Dashboard", 20, 40),
        ("League Power Rankings", 20, 90),
        ("Weekly Trade Ideas", 300, 40),
        ("Patrick Mahomes", 300, 160),
        ("Hot Summer Deals", 700, 220),
        ("Bijan Robinson", 1000, 300),
        ("Exclusive Member Pricing", 420, 420),
        ("Byron Young", 560, 560),  # two on the board: the person chooses
    )
    out = _extract(rows, identity_ctx, board, width=1400, height=760)
    assert out["sides"] == []
    assert "trade_region_not_detected" in out["warnings"]
    assert "low_layout_confidence" in out["warnings"]
    raws = [it["raw"] for it in out["unassigned"]]
    assert raws == ["Patrick Mahomes", "Bijan Robinson", "Byron Young"]
    assert out["unassigned"][2]["status"] == "needs_confirmation"  # never auto-picked
    reasons = _ignored(out)
    for text in ("Hot Summer Deals", "Exclusive Member Pricing", "Weekly Trade Ideas"):
        assert reasons[text] == "unrecognized_text"


def test_ocr_errors_inside_the_region_stay_visible_and_unguessed(identity_ctx, board):
    rows = (
        ("Team 1 gets...", 60, 40),
        ("Team 2 gets...", 660, 40),
        ("Patrick Mahomez", 60, 120),  # surname OCR typo: refused, never repaired
        ("Byron Young", 60, 180),  # ambiguous: two on the board
        ("Bijan Robinson", 660, 120),
        ("Total", 60, 300),
    )
    out = _extract(rows, identity_ctx, board, width=1200, height=400)
    a = out["sides"][0]["items"]
    assert [it["status"] for it in a] == ["unresolved", "needs_confirmation"]
    assert a[0]["boardName"] is None and a[1]["boardName"] is None
    assert _names(out["sides"][1]) == ["Bijan Robinson"]


def test_two_screenshots_of_one_trade_are_read_independently(identity_ctx, board):
    top = (
        ("Team 1 gets...", 60, 40),
        ("Team 2 gets...", 660, 40),
        ("Patrick Mahomes", 60, 120),
        ("Quay Walker", 60, 180),
        ("Bijan Robinson", 660, 120),
    )
    bottom = (
        ("Quay Walker", 60, 20),
        ("2027 1st", 60, 80),
        ("Travis Hunter", 660, 20),
        ("2 Total Pieces", 60, 160),
        ("Josh Allen", 1100, 20),
    )
    first = _extract(top, identity_ctx, board, width=1200, height=260)
    second = _extract(bottom, identity_ctx, board, width=1200, height=260)
    assert _names(first["sides"][0]) == ["Patrick Mahomes", "Quay Walker"]
    assert _names(first["sides"][1]) == ["Bijan Robinson"]
    # The scrolled continuation has no labels: nothing is placed on a side
    # (the person places it, or the merge tray offers it) — and the overlap
    # with the first image is left to the client's documented seam merge.
    assert second["sides"] == []
    assert "trade_region_not_detected" in second["warnings"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1 Total Pieces", True),
        ("Total: 7,200", True),
        ("Totals", True),
        ("5 total assets", True),
        ("Total Recall", False),
        ("Patrick Mahomes", False),
    ],
)
def test_total_lines(text, expected):
    assert is_total_line(text) is expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Fair Trade", True),
        ("Slightly favors Team A", True),
        ("Copy Trade URL", True),
        ("Clear Calculator", True),
        ("Accept", True),
        ("1 Total Pieces", True),
        ("Jaxson Dart", False),
        ("Search for a player", False),
        ("Suggested", False),  # equalizer headers keep their own handling
    ],
)
def test_region_boundaries(text, expected):
    assert is_region_boundary(text) is expected


def test_search_placeholder_and_platform_labels():
    assert classify_noise("Search for a player") == "search_placeholder"
    assert classify_noise("1 Total Pieces") == "label"
    assert match_anchor("Team 1 gets...") == match_anchor("Team 1 gets")
    assert match_anchor("Giving") is not None and match_anchor("Getting") is not None


def test_layout_uses_no_fixed_pixel_coordinates():
    # The same page at two resolutions yields the same assignment.
    def assign(scale):
        lines = build_lines(_words(KTC_PAGE, scale))
        lay = detect_layout(lines, round(KTC_W * scale))
        return [[ln.text for ln in s.lines] for s in lay.sides]

    assert assign(0.5) == assign(1.0) == assign(2.0)
