"""The methodology shown to readers IS the calculation, at every season stage.

The Power blend is season-aware: the forward/results split moves from 100%
ROS in the preseason toward the 30/70 target as games accumulate, and
``recent`` carries no weight until its trailing window stops being the whole
season. A description of the late-season target shown in Week 2 would be a
statement about a formula the page is not running.

So the section publishes ``methodology`` built from the exact
``active_weights`` ``_score_state`` scored with, and the page renders it
verbatim (``frontend/__tests__/components/RosPowerSingleRanking.test.jsx``
pins that half). These tests pin, for every supported stage:

* displayed methodology weights == the effective weights used to compute
  Power -- proven by recomputing every row's published score from them;
* displayed component percentages sum to exactly 100, and forward + results
  == 100;
* a 0% component says why (and when it activates), never vanishes.
"""

from __future__ import annotations

import pytest

from src.ros import power_snapshots, power_v2
from tests.ros.test_power_current_season_integrity import (
    _OWNERS_2026,
    _ROS,
    _season,
    _snapshot,
    _week_2026,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    rows = [{"ownerId": oid, "teamRosStrength": v} for oid, v in _ROS.items()]
    monkeypatch.setattr(power_v2, "_load_team_strength_rows", lambda *a, **k: list(rows))
    monkeypatch.setattr(power_snapshots, "ROS_DATA_DIR", tmp_path)
    import src.api.league_registry as league_registry

    monkeypatch.setattr(league_registry, "league_key_for_sleeper_id", lambda _id: "testleague")


def _weeks(n: int) -> dict[int, dict[int, float]]:
    # Vary the order week to week so every component discriminates.
    return {
        wk: _week_2026(wk, overrides={((wk * 5) % 12) + 1: 400.0 + wk}) for wk in range(1, n + 1)
    }


def _in_season(games: int):
    return _snapshot(_season("2026", _OWNERS_2026, _weeks(games), last_scored_leg=games))


def _preseason():
    return _snapshot(_season("2026", _OWNERS_2026, {}, last_scored_leg=0))


def _week1_in_progress():
    live = _week_2026(1, overrides={rid: 0.0 for rid in range(1, 7)})
    return _snapshot(_season("2026", _OWNERS_2026, {1: live}, last_scored_leg=0))


#: (id, snapshot factory, lens)
_STAGES = [
    ("preseason", _preseason, power_v2.LENS_CANONICAL),
    ("week1-in-progress", _week1_in_progress, power_v2.LENS_CANONICAL),
    ("1-game", lambda: _in_season(1), power_v2.LENS_CANONICAL),
    ("2-games", lambda: _in_season(2), power_v2.LENS_CANONICAL),
    ("4-games-window-boundary", lambda: _in_season(4), power_v2.LENS_CANONICAL),
    ("5-games-recent-activates", lambda: _in_season(5), power_v2.LENS_CANONICAL),
    ("8-games", lambda: _in_season(8), power_v2.LENS_CANONICAL),
    ("13-games-late-season", lambda: _in_season(13), power_v2.LENS_CANONICAL),
    ("results-only-lens", lambda: _in_season(8), power_v2.LENS_RESULTS_ONLY),
]


@pytest.fixture(params=_STAGES, ids=[s[0] for s in _STAGES])
def section(request):
    _, factory, lens = request.param
    return power_v2.build_section(factory(), lens=lens)


def _displayed(section: dict) -> dict[str, dict]:
    return {c["key"]: c for c in section["methodology"]["components"]}


class TestDisplayedMethodologyIsTheCalculation:
    def test_every_canonical_component_is_listed_exactly_once(self, section):
        keys = [c["key"] for c in section["methodology"]["components"]]
        assert sorted(keys) == sorted(power_v2.WEIGHTS)

    def test_displayed_weights_equal_the_effective_weights(self, section):
        effective = section["effectiveWeights"]
        for key, comp in _displayed(section).items():
            assert comp["weight"] == pytest.approx(float(effective.get(key, 0.0)), abs=1e-6), key

    def test_the_effective_weights_are_the_ones_the_score_used(self, section):
        """Recompute every published Power score from the displayed weights."""
        weights = {k: c["weight"] for k, c in _displayed(section).items() if c["weight"] > 0}
        checked = 0
        for row in section["currentRanking"]:
            comps = row["components"]
            used = {k: w for k, w in weights.items() if comps.get(k) is not None}
            if set(used) != set(weights):
                continue  # a per-owner renormalisation; covered by weightsApplied below
            assert row["weightsApplied"] == pytest.approx(section["effectiveWeights"])
            total = sum(used.values())
            recomputed = 100.0 * sum(w * comps[k] for k, w in used.items()) / total
            # components are published at 4 dp, the score at 2 dp.
            assert row["powerScore"] == pytest.approx(recomputed, abs=0.02), row["ownerId"]
            checked += 1
        assert checked == 12

    def test_displayed_percentages_sum_to_100(self, section):
        comps = section["methodology"]["components"]
        assert sum(c["displayPct"] for c in comps) == 100
        m = section["methodology"]
        assert m["forwardDisplayPct"] + m["resultsDisplayPct"] == 100

    def test_each_displayed_percentage_is_its_weight_rounded(self, section):
        total = sum(c["weight"] for c in section["methodology"]["components"])
        for c in section["methodology"]["components"]:
            assert abs(c["displayPct"] - 100.0 * c["weight"] / total) < 1.0, c

    def test_a_zero_weight_component_is_explained_not_dropped(self, section):
        for c in section["methodology"]["components"]:
            if c["status"] == "active":
                assert c["weight"] > 0 and c["displayPct"] > 0
            else:
                assert c["weight"] == 0 and c["displayPct"] == 0
                assert c["reason"], c


class TestTheBlendMovesWithTheSeason:
    def test_preseason_is_all_forward_looking(self):
        d = _displayed(power_v2.build_section(_preseason()))
        assert d["team_ros_strength"]["displayPct"] == 100
        for key in ("all_play", "recent", "wl_record"):
            assert d[key]["status"] == "suppressed"

    def test_two_games_is_not_the_late_season_target(self):
        section = power_v2.build_section(_in_season(2))
        m = section["methodology"]
        assert m["forwardDisplayPct"] == 40 and m["resultsDisplayPct"] == 60
        d = _displayed(section)
        assert d["recent"]["status"] == "inactive"
        assert d["recent"]["activatesAfterGames"] == power_v2._RECENT_WINDOW
        assert d["team_vorp"]["status"] == "unavailable"

    def test_recent_activates_after_the_window(self):
        for games, active in ((4, False), (5, True)):
            d = _displayed(power_v2.build_section(_in_season(games)))
            assert (d["recent"]["status"] == "active") is active, games

    def test_the_forward_share_falls_toward_the_target_as_games_accrue(self):
        shares = [
            _displayed(power_v2.build_section(_in_season(g)))["team_ros_strength"]["weight"]
            for g in (1, 2, 4, 8, 13)
        ]
        assert shares == sorted(shares, reverse=True)
        assert shares[-1] == pytest.approx(power_v2.WEIGHTS["team_ros_strength"], abs=0.01)

    def test_results_only_lens_names_why_ros_is_absent(self):
        d = _displayed(power_v2.build_section(_in_season(8), lens=power_v2.LENS_RESULTS_ONLY))
        assert d["team_ros_strength"]["status"] == "excluded_by_lens"


def test_largest_remainder_rounding_never_loses_a_point():
    order = ("a", "b", "c")
    assert power_v2._largest_remainder_percents({"a": 1, "b": 1, "c": 1}, order) == {
        "a": 34,
        "b": 33,
        "c": 33,
    }
    assert power_v2._largest_remainder_percents({"a": 0.0, "b": 0.0, "c": 0.0}, order) == {}
