"""Cadence-relative freshness (owner directive 2026-09-23 + required revision).

freshness = curve(age / E), E = the source's own expected interval.  There is
no universal absolute grace floor: a fast source loses authority quickly
after a few missed cycles, a slow source is not punished for being slow.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest

from src.sources import freshness as fr
from src.sources.dataset_integrity import parse_board
from src.sources.dataset_state import observe

NOW = datetime(2026, 9, 23, 18, 0, tzinfo=timezone.utc)
CFG = fr.load_config()


def f(age_hours: float, expected_hours: float) -> float:
    return fr.freshness_from_ratio(age_hours / expected_hours, "C4")


class TestTheCurve:
    @pytest.mark.parametrize(
        "r, expected",
        [
            (0.5, 1.0),
            (1.0, 1.0),
            (1.25, 0.966),
            (1.5, 0.891),
            (2.0, 0.707),
            (3.0, 0.397),
            (4.0, 0.210),
            (6.0, 0.056),
            (8.0, 0.014),
        ],
    )
    def test_documented_ratio_table(self, r, expected):
        assert fr.freshness_from_ratio(r, "C4") == pytest.approx(expected, abs=0.001)

    def test_monotone_and_smooth(self):
        prev = 1.0
        for i in range(0, 1000):
            r = i / 100.0
            v = fr.freshness_from_ratio(r, "C4")
            assert v <= prev + 1e-12
            assert prev - v < 0.02  # no cliff between adjacent 0.01 steps
            prev = v

    def test_no_kink_at_one_interval(self):
        left = (fr.freshness_from_ratio(1.0) - fr.freshness_from_ratio(0.999)) / 0.001
        right = (fr.freshness_from_ratio(1.001) - fr.freshness_from_ratio(1.0)) / 0.001
        assert abs(left) < 1e-6 and abs(right) < 0.01

    def test_every_candidate_is_implemented_and_bounded(self):
        for name in ("C1", "C2", "C3", "C4"):
            for r in (0, 0.5, 1, 2, 4, 8, 20):
                v = fr.freshness_from_ratio(r, name)
                assert 0.0 <= v <= 1.0 and math.isfinite(v)


class TestCadenceRelative:
    def test_fast_source_e12h(self):
        assert f(12, 12) == 1.0
        assert f(24, 12) == pytest.approx(0.707, abs=0.001)
        assert f(36, 12) == pytest.approx(0.397, abs=0.001)
        assert f(48, 12) == pytest.approx(0.210, abs=0.001)
        assert f(72, 12) == pytest.approx(0.056, abs=0.001)
        assert f(96, 12) < CFG.quarantine_below  # quarantined

    def test_medium_source_e3d(self):
        e = 72
        assert f(72, e) == 1.0
        assert f(144, e) == pytest.approx(0.707, abs=0.001)
        assert f(216, e) == pytest.approx(0.397, abs=0.001)
        assert f(288, e) == pytest.approx(0.210, abs=0.001)
        assert f(432, e) == pytest.approx(0.056, abs=0.001)

    def test_weekly_source_e7d(self):
        e = 168
        assert f(168, e) == 1.0
        assert f(336, e) == pytest.approx(0.707, abs=0.001)
        assert f(504, e) == pytest.approx(0.397, abs=0.001)
        assert f(672, e) == pytest.approx(0.210, abs=0.001)
        assert f(1008, e) == pytest.approx(0.056, abs=0.001)

    def test_slow_monthly_source_e35d(self):
        e = 35 * 24
        assert f(7 * 24, e) == 1.0
        assert f(21 * 24, e) == 1.0
        assert f(35 * 24, e) == 1.0
        assert f(45 * 24, e) == pytest.approx(0.957, abs=0.002)
        assert f(70 * 24, e) == pytest.approx(0.707, abs=0.001)
        assert f(105 * 24, e) == pytest.approx(0.397, abs=0.001)

    def test_same_absolute_age_means_different_things(self):
        # 72 hours: seriously stale for a 12-hour source, normal for a weekly one.
        assert f(72, 12) < 0.1
        assert f(72, 168) == 1.0


def _history(times, rows_changed=50, total=100):
    return [
        {
            "at": t.isoformat().replace("+00:00", "Z"),
            "rowsChanged": rows_changed,
            "rowsTotal": total,
            "broad": rows_changed >= 5,
        }
        for t in times
    ]


class TestExpectedCadence:
    SEED = fr.SourceCadence(seed_hours=72, min_hours=12, max_hours=240)

    def test_learned_from_closed_broad_intervals(self):
        times = [NOW - timedelta(days=d) for d in (30, 25, 20, 15, 10, 5)]
        e, source, observed = fr.expected_interval_hours(_history(times), NOW, self.SEED, CFG)
        assert source == fr.CADENCE_LEARNED_PHASE or source == fr.CADENCE_LEARNED_ANY
        assert e == pytest.approx(120.0)

    def test_outage_cannot_redefine_normal(self):
        # Five 5-day intervals, then a 60-day outage that has now ENDED.
        times = [NOW - timedelta(days=d) for d in (90, 85, 80, 75, 70, 10)]
        e, _, observed = fr.expected_interval_hours(_history(times), NOW, self.SEED, CFG)
        assert observed is not None
        assert e <= self.SEED.max_hours  # clamp holds even if the p75 moved

    def test_the_open_gap_is_never_in_the_sample(self):
        times = [NOW - timedelta(days=d) for d in (60, 55, 50, 45, 40, 35)]
        intervals = fr.broad_intervals_hours(_history(times), NOW, CFG)
        assert all(h == pytest.approx(120.0) for h, _ in intervals)

    def test_too_few_intervals_falls_back_to_the_seed(self):
        times = [NOW - timedelta(days=3)]
        e, source, _ = fr.expected_interval_hours(_history(times), NOW, self.SEED, CFG)
        assert source == fr.CADENCE_SEED and e == 72

    def test_minimum_is_per_source_not_universal(self):
        fast = fr.SourceCadence(seed_hours=12, min_hours=12, max_hours=48)
        times = [NOW - timedelta(hours=h) for h in (30, 24, 18, 12, 6, 1)]
        e, _, observed = fr.expected_interval_hours(_history(times), NOW, fast, CFG)
        assert observed == pytest.approx(6.0)
        assert e == 12.0


def _state_with(clock_days_ago: float, *, events_days_ago=(), subset="players", rows=None):
    history = _history([NOW - timedelta(days=d) for d in events_days_ago])
    at = (NOW - timedelta(days=clock_days_ago)).isoformat().replace("+00:00", "Z")
    return {
        "subsets": {
            subset: {
                "changeHistory": history,
                "lastAnyMeaningfulChangeAt": at,
                "lastBroadDatasetChangeAt": at,
                "rowCount": 100,
                "rowCountHistory": [100],
                "rowChangedAt": rows or {},
            }
        },
        "health": {"state": "HEALTHY", "errors": []},
        "upstream": {},
    }


class TestSourceLevel:
    def test_stale_source_loses_weight_fresh_source_keeps_it(self):
        fresh = fr.assess_source("idpTradeCalc", _state_with(1), as_of=NOW, cfg=CFG)
        stale = fr.assess_source("idpTradeCalc", _state_with(30), as_of=NOW, cfg=CFG)
        assert fresh.subsets["players"].freshness == 1.0
        assert stale.subsets["players"].freshness < 0.1

    def test_recovers_automatically_after_a_genuine_update(self):
        stale = fr.assess_source("idpShowCombined", _state_with(35), as_of=NOW, cfg=CFG)
        assert stale.subsets["players"].freshness < 0.2
        refreshed = fr.assess_source("idpShowCombined", _state_with(0.5), as_of=NOW, cfg=CFG)
        assert refreshed.subsets["players"].freshness == 1.0

    def test_idptc_and_idp_show_go_stale_independently(self):
        a = fr.assess_source("idpTradeCalc", _state_with(2), as_of=NOW, cfg=CFG)
        b = fr.assess_source("idpShowCombined", _state_with(34), as_of=NOW, cfg=CFG)
        assert a.subsets["players"].freshness == 1.0
        assert b.subsets["players"].freshness < 0.2

    def test_different_expected_cadences_are_supported(self):
        assert (
            CFG.cadence_for("ktcCrowdSfTep").seed_hours != CFG.cadence_for("yahooBoone").seed_hours
        )

    def test_picks_are_judged_on_their_own_clock(self):
        state = _state_with(2)
        pick_state = _state_with(26, subset="picks")
        state["subsets"]["picks"] = pick_state["subsets"]["picks"]
        sw = fr.assess_source("idpTradeCalc", state, as_of=NOW, cfg=CFG)
        assert sw.factor_for_row(is_pick=False, row_key=None)[0] == 1.0
        assert sw.factor_for_row(is_pick=True, row_key=None)[0] < 0.2

    def test_unmeasured_source_is_neutral_and_says_so(self):
        sw = fr.assess_source("brandNew", None, as_of=NOW, cfg=CFG)
        assert sw.measured is False
        assert sw.factor_for_row(is_pick=False, row_key="x") == (1.0, None)

    def test_deterministic_for_a_fixed_as_of(self):
        a = fr.assess_source("dlfSf", _state_with(9), as_of=NOW, cfg=CFG).to_dict()
        b = fr.assess_source("dlfSf", _state_with(9), as_of=NOW, cfg=CFG).to_dict()
        assert a == b

    def test_past_as_of_never_sees_future_changes(self):
        state = _state_with(1, events_days_ago=(40, 30, 20, 10, 1))
        past = NOW - timedelta(days=15)
        sw = fr.assess_source("dlfSf", state, as_of=past, cfg=CFG)
        clock = sw.subsets["players"].clock_at
        assert clock is not None and clock <= past


class TestPublicationStyle:
    def test_snapshot(self):
        hist = [{"broad": True, "rowsChanged": 80, "rowsTotal": 100}] * 6
        assert fr.classify_style(hist, CFG)[0] == fr.STYLE_SNAPSHOT

    def test_incremental(self):
        hist = [{"broad": False, "rowsChanged": 1, "rowsTotal": 100}] * 6
        assert fr.classify_style(hist, CFG)[0] == fr.STYLE_INCREMENTAL

    def test_batch(self):
        hist = [
            {"broad": i % 2 == 0, "rowsChanged": 40 if i % 2 == 0 else 2, "rowsTotal": 100}
            for i in range(6)
        ]
        assert fr.classify_style(hist, CFG)[0] == fr.STYLE_BATCH

    def test_unknown_is_flagged_and_conservative(self):
        style, evidence = fr.classify_style(
            [{"broad": True, "rowsChanged": 90, "rowsTotal": 100}], CFG
        )
        assert style == fr.STYLE_UNKNOWN and evidence["events"] == 1

    def test_snapshot_refreshes_the_whole_source(self):
        state = _state_with(0.2, events_days_ago=(5, 4, 3, 2, 1, 0.2))
        sw = fr.assess_source("ktcCrowdSfTep", state, as_of=NOW, cfg=CFG)
        assert sw.subsets["players"].style == fr.STYLE_SNAPSHOT
        assert sw.factor_for_row(is_pick=False, row_key="anyone")[0] == 1.0

    def test_incremental_one_player_update_does_not_refresh_untouched_players(self):
        touched = (NOW - timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        hist = [
            {
                "at": (NOW - timedelta(days=d)).isoformat(),
                "broad": False,
                "rowsChanged": 1,
                "rowsTotal": 100,
            }
            for d in (5, 4, 3, 2, 1)
        ]
        state = _state_with(30, rows={"player a": touched})
        state["subsets"]["players"]["changeHistory"] = hist
        sw = fr.assess_source("dlfIdp", state, as_of=NOW, cfg=CFG)
        assert sw.subsets["players"].style == fr.STYLE_INCREMENTAL
        assert sw.factor_for_row(is_pick=False, row_key="player a")[0] == 1.0
        assert sw.factor_for_row(is_pick=False, row_key="player b")[0] < 0.5

    def test_batch_broad_refresh_ages_rows_from_the_batch(self):
        state = _state_with(1, events_days_ago=(12, 11, 8, 6, 3, 1))
        state["subsets"]["players"]["changeHistory"][1]["broad"] = False
        state["subsets"]["players"]["rowChangedAt"] = {
            "old": (NOW - timedelta(days=40)).isoformat()
        }
        sw = fr.assess_source("idpTradeCalc", state, as_of=NOW, cfg=CFG)
        # The broad batch a day ago refreshed the row even though the row
        # itself last changed 40 days ago.
        assert sw.factor_for_row(is_pick=False, row_key="old")[0] == 1.0

    def test_explicit_upstream_timestamp_is_the_clock(self):
        import dataclasses

        cfg = dataclasses.replace(
            CFG,
            sources={
                **CFG.sources,
                "idpShowCombined": fr.SourceCadence(168, 72, 336, style=fr.STYLE_EXPLICIT),
            },
        )
        state = _state_with(1)
        state["upstream"] = {"publishedAt": (NOW - timedelta(days=35)).isoformat()}
        sw = fr.assess_source("idpShowCombined", state, as_of=NOW, cfg=cfg)
        assert sw.subsets["players"].clock == "upstreamPublishedAt"
        assert sw.subsets["players"].freshness < 0.2


def test_state_file_round_trip_through_the_real_owner():
    """End to end: dataset_state → freshness, with no hand-built state."""
    t0 = NOW - timedelta(days=20)
    board = "name,value\n" + "".join(f"P{i},{1000 + i}\n" for i in range(50))
    state = observe(None, source_key="x", board=parse_board(board), observed_at=t0)
    sw = fr.assess_source("x", state, as_of=NOW, cfg=CFG)
    assert sw.subsets["players"].age_hours == pytest.approx(480.0)
    assert sw.subsets["players"].cadence_source == fr.CADENCE_SEED
