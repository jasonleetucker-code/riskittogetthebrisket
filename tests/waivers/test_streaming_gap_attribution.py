"""Gap-attribution diagnostics and the point-in-time helpers (research only)."""

from __future__ import annotations

from datetime import timedelta

from src.waivers import streaming_backtest as sb
from src.waivers import streaming_gap_attribution as ga
from src.waivers import streaming_point_in_time as pit
from tests.waivers.test_streaming_backtest import T0, _data, _hand_ctx


def _ab(key):
    return next(a for a in ga.ABLATIONS if a.key == key)


def test_base_ablation_is_exactly_baseline_7():
    ctx = _hand_ctx(
        roster_values={"r1": 900.0, "r2": 800.0, "r3": 100.0},
        pool_values={"f1": 300.0, "f2": 50.0},
        projection={"r1": 10.0, "r2": 8.0, "r3": 2.0, "f1": 12.0, "f2": 3.0, "f3": 1.0},
    )
    base = ga.AblatedOptimizerPolicy(ablation=_ab("base"))
    assert base.decide(ctx) == sb.DynastySafeOptimizerPolicy().decide(ctx)
    assert _ab("base").work_limit is None  # reproduces the preregistered cell


def test_unpriced_release_is_a_labelled_diagnostic_only():
    ctx = _hand_ctx(
        roster_values={"r1": 900.0, "r2": 800.0},  # r3 has NO known value
        pool_values={"f1": 300.0},
        projection={"r1": 10.0, "r2": 8.0, "r3": 0.5, "f1": 30.0},
    )
    assert sb.DynastySafeOptimizerPolicy().decide(ctx) == []
    relaxed = ga.AblatedOptimizerPolicy(ablation=_ab("unpriced_releasable"))
    assert relaxed.decide(ctx) == [sb.Swap("r3", "f1", 0.0)]


def test_protection_off_releases_a_priced_player_above_the_line():
    ctx = _hand_ctx(
        roster_values={"r1": 900.0, "r2": 800.0, "r3": 700.0},
        pool_values={"f1": 300.0},
        projection={"r1": 10.0, "r2": 8.0, "r3": 2.0, "f1": 30.0},
    )
    assert sb.DynastySafeOptimizerPolicy().decide(ctx) == []
    off = ga.AblatedOptimizerPolicy(ablation=_ab("dynasty_protection_off"))
    swaps = off.decide(ctx)
    assert len(swaps) == 1 and swaps[0].add_id == "f1"


def test_oracle_and_combined_rows_are_flagged_hindsight():
    flagged = {a.key for a in ga.ABLATIONS if a.hindsight}
    assert flagged == {"projection_oracle", "all_plus_oracle"}
    assert all(a.projection == "oracle" for a in ga.ABLATIONS if a.hindsight)


def test_open_spots_default_keeps_every_preregistered_baseline_one_for_one():
    class PureAdd:
        name = "pure_add"

        def decide(self, ctx):
            return [sb.Swap("", "d3", 0.0)]

    data = _data()
    strict = sb.simulate_policy(data, 1, 0, PureAdd(), [], max_swaps=3, masked=True)
    assert all(r.adds == () and r.rejected_swaps == 1 for r in strict)
    room = sb.simulate_policy(data, 1, 0, PureAdd(), [], max_swaps=3, masked=True, open_spots=1)
    assert room[0].adds == ("d3",) and room[0].drops == ()
    assert "d3" in room[0].idp_set


def test_timestamp_classification_never_treats_a_revision_as_a_forecast():
    cutoff = T0
    assert pit.classify_projection_timestamp(T0 - timedelta(hours=1), cutoff) == pit.PRE_KICKOFF
    assert pit.classify_projection_timestamp(T0 + timedelta(hours=1), cutoff) == pit.POST_KICKOFF
    assert pit.classify_projection_timestamp(T0, cutoff) == pit.POST_KICKOFF
    assert pit.classify_projection_timestamp(None, cutoff) == pit.UNSTAMPED
    assert pit.classify_projection_timestamp("2026-09-01T00:00:00", cutoff) == pit.UNSTAMPED
    assert pit.classify_projection_timestamp("garbage", cutoff) == pit.UNSTAMPED


def test_candidate_universe_is_the_backtest_pool():
    data = _data()
    assert pit.candidate_universe(data, 1, 2, {"d1"}) == sb.available_pool(
        data, 1, 2, {"d1"}, masked=True
    )
    ctx = pit.decision_context_for(data, 1, 2, {"d1", "l1"})
    assert ctx.week == 2 and ctx.cutoff_utc == data.cutoffs[2]
    assert all(w < 2 for hist in ctx.realized_before.values() for w in hist)


def test_projection_error_rows_keep_did_not_play_separate_from_zero():
    proj = {
        w: {
            "d1": sb.Projection(4.0, (T0 + timedelta(days=10)).isoformat()),
            "d3": sb.Projection(3.0, None),
        }
        for w in (1, 2, 3, 4)
    }
    pts = {w: {"d1": 5.0} for w in (1, 2, 3, 4)}
    data = _data(points=pts, projections=proj)
    rows = pit.projection_error_rows(data, {"d1": {"team": "AAA", "years_exp": 0}})
    d3 = [r for r in rows if r.player_id == "d3"]
    assert d3 and all(r.realized is None and r.late_inactive for r in d3)
    d1 = [r for r in rows if r.player_id == "d1"]
    assert d1[0].first_appearance and not d1[1].first_appearance
    assert all(r.rookie is True for r in d1)
    assert d1[0].timestamp_class == pit.POST_KICKOFF  # revised after week 1 kicked off
    assert d1[-1].timestamp_class == pit.PRE_KICKOFF
    assert pit.error_summary([1.0, -1.0])["bias"] == 0.0
