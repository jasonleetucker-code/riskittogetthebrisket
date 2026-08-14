"""The ROS context-tag classifier has one owner and one mirror — B9b.

WHY THIS FILE EXISTS
────────────────────
The classifier existed three times: ``src/ros/tags.py::tags_for_player``
(the nominal owner, with **no production caller**), and verbatim copies
inside ``PlayerPopup.jsx`` and ``RosTradeFitPanel.jsx`` — which were the
live path.  One of the JS copies carried the comment *"Stays in sync via
the parity test (PR-future)"*.  That parity test was never written, and
triplication is what let W29-F005 survive review three times.

W29-F005: the "Seller cash-out" predicate was
``dynastyValue < rosValue * 0.7``, comparing a 0–9999 dynasty board
value against the 0–100 ROS strength index.  The right-hand side maxes
at 60.8; the board's lowest priced value is 1,134.  The tag could not
fire for any of 1,093 rows and never had.

This file is the parity test that was promised, plus the reachability
assertion the finding asked for: *"Add a unit test asserting the tag
fires on a constructed case, which would have caught this at zero
cost."*
"""

from __future__ import annotations

import pathlib
import re

import pytest

from src.api.thresholds import threshold
from src.ros.tags import ros_percentiles, tags_for_player

REPO = pathlib.Path(__file__).resolve().parents[2]
MIRROR = REPO / "frontend" / "lib" / "ros-index.js"


def _strong() -> float:
    return float(threshold("ROS_STRONG_PERCENTILE"))


class TestEveryTagIsReachable:
    """A tag that cannot fire is a feature that does not exist.

    Nine tags; nine constructed cases.  This is the assertion that was
    missing — the shipped predicate had a zero-row solution set and no
    test noticed for as long as it existed.
    """

    def _tags(self, **kw):
        base = dict(
            canonical_name="Test Player",
            position="WR",
            age=30,
            ros_value=50.0,
            ros_percentile=99.0,
            ros_rank_overall=10,
            dynasty_percentile=50.0,
            volatility_flag=False,
        )
        base.update(kw)
        return tags_for_player(**base)

    def test_seller_cash_out_fires(self):
        """The tag W29-F005 proved was unreachable.

        A 30-year-old WR standing at the 99th percentile for
        rest-of-season and the 50th on the dynasty board: a 49-point gap
        against a 25-point threshold.
        """
        assert "Seller cash-out" in self._tags(ros_percentile=99.0, dynasty_percentile=50.0)

    def test_seller_cash_out_does_not_fire_without_the_gap(self):
        assert "Seller cash-out" not in self._tags(ros_percentile=99.0, dynasty_percentile=95.0)

    def test_seller_cash_out_needs_a_dynasty_standing(self):
        """Missing is not zero.

        An unpriced dynasty row must not read as "worth nothing" and
        therefore maximally underpriced — which is exactly what a
        ``?? 0`` fallback would produce here.
        """
        assert "Seller cash-out" not in self._tags(dynasty_percentile=None)

    def test_win_now_target_fires(self):
        assert "Win-now target" in self._tags()

    def test_contender_upgrade_fires(self):
        assert "Contender upgrade" in self._tags(age=24, ros_percentile=99.0)

    def test_rebuilder_hold_fires(self):
        assert "Rebuilder hold" in self._tags(age=22, ros_percentile=10.0)

    def test_avoid_unless_contending_fires(self):
        assert "Avoid unless contending" in self._tags(ros_rank_overall=400)

    def test_depth_spike_option_fires(self):
        low = float(threshold("ROS_DEPTH_BAND_LOW_PERCENTILE"))
        mid = (low + _strong()) / 2
        assert "Depth spike option" in self._tags(ros_percentile=mid, ros_rank_overall=400)

    def test_best_ball_boost_fires(self):
        assert "Best-ball boost" in self._tags(volatility_flag=True)

    def test_idp_contender_target_fires(self):
        assert "IDP contender target" in self._tags(position="LB", ros_rank_overall=10)

    def test_injury_bye_cover_fires(self):
        assert "Injury/bye cover" in self._tags(age=30, ros_percentile=10.0)


class TestStandingsNotIndexLevels:
    def test_no_tag_without_a_standing(self):
        """Every strength gate is a percentile, and a percentile cannot
        be computed from one player.  Returning nothing is honest;
        falling back to the raw index is the defect being repaired."""
        assert (
            tags_for_player(
                canonical_name="X",
                position="WR",
                age=30,
                ros_value=86.79,
                ros_percentile=None,
            )
            == []
        )

    def test_percentiles_rank_the_whole_pool(self):
        pct = ros_percentiles([10.0, 30.0, 20.0])
        assert pct[1] == 100.0  # best
        assert pct[0] == 0.0  # worst
        assert 0.0 < pct[2] < 100.0

    def test_unranked_rows_are_none_not_zero(self):
        """ "No ROS source ranked this player" is not "worst in the
        league" — a 0.0 percentile would make it one."""
        pct = ros_percentiles([10.0, None, 0, 30.0])
        assert pct[1] is None
        assert pct[2] is None
        assert pct[3] == 100.0

    def test_a_single_ranked_row_does_not_divide_by_zero(self):
        assert ros_percentiles([42.0]) == [100.0]


class TestTheJavaScriptMirrorMatches:
    """Same mechanism as ``tests/api/test_threshold_parity.py``.

    The mirror cannot be imported from Python, so this asserts the two
    things that actually drifted historically: the tag vocabulary and
    the thresholds each gate reads.
    """

    @pytest.fixture(scope="class")
    def mirror(self) -> str:
        if not MIRROR.exists():
            pytest.skip("frontend mirror not present in this checkout")
        return MIRROR.read_text(encoding="utf-8")

    def test_the_mirror_emits_exactly_the_same_tags(self, mirror: str):
        js_tags = set(re.findall(r'tags\.push\("([^"]+)"\)', mirror))
        py_tags = set(
            re.findall(
                r'tags\.append\("([^"]+)"\)',
                (REPO / "src" / "ros" / "tags.py").read_text(encoding="utf-8"),
            )
        )
        assert (
            js_tags == py_tags
        ), f"only in JS: {js_tags - py_tags}; only in Python: {py_tags - js_tags}"

    def test_the_mirror_gates_on_percentiles_not_index_levels(self, mirror: str):
        block = mirror.split("export function tagsForPlayer", 1)[1]
        for name in (
            "ROS_STRONG_PERCENTILE",
            "ROS_ELITE_PERCENTILE",
            "ROS_DEPTH_BAND_LOW_PERCENTILE",
            "ROS_SELLER_PERCENTILE_GAP",
        ):
            assert name in block, f"{name} is not read by the JS classifier"
        assert "rosValue >= 60" not in block
        assert "rosValue >= 80" not in block
        assert "rosValue * 0.7" not in block, "the W29-F005 cross-scale predicate is back"

    def test_the_duplicate_classifiers_are_gone(self):
        for component in ("PlayerPopup.jsx", "RosTradeFitPanel.jsx"):
            path = REPO / "frontend" / "components" / component
            if not path.exists():
                pytest.skip(f"{component} not present")
            src = path.read_text(encoding="utf-8")
            assert "function tagsForPlayer(" not in src, f"{component} re-declares the classifier"
            assert "function _tagsForPlayer(" not in src
            assert "rosValue * 0.7" not in src
