"""BDVM reuse must follow the evidence and the scoring actually consumed."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import pytest

from src.api import bdvm_api as api
from src.bdvm import actuals, context_store, schedule
from src.nfl_data import cache, ingest, pbp_weekly


@pytest.fixture(autouse=True)
def isolated_inputs(tmp_path, monkeypatch):
    api.reset_cache()
    monkeypatch.setattr(cache, "_default_cache_dir", lambda: tmp_path / "nfl")
    monkeypatch.setattr(context_store, "SNAPSHOT_DIR", tmp_path / "context")
    monkeypatch.setattr(pbp_weekly, "default_pbp_weekly_dir", lambda: tmp_path / "pbp")
    monkeypatch.setattr(actuals, "current_nfl_season", lambda: 2026)
    monkeypatch.setattr(api, "nfl_projection_season", lambda: 2026)
    monkeypatch.setattr(api, "_today", lambda: "2026-09-10")
    yield
    api.reset_cache()


def _contract(rec=1.0):
    return {"generatedAt": "fixed", "sleeper": {"scoringSettings": {"rec": rec}}}


def test_actuals_do_not_reuse_another_scoring_card():
    def scored(scoring, **kwargs):
        assert kwargs["cache_only"] is True
        return 2, {"receiver": [(1, 10 * scoring["rec"])]}

    with mock.patch.object(actuals, "fetch_current_season_actuals", side_effect=scored) as run:
        assert api._actuals_for(_contract(1))[1]["receiver"] == [(1, 10)]
        assert api._actuals_for(_contract(0.5))[1]["receiver"] == [(1, 5)]
        api._actuals_for(_contract(0.5))
    assert run.call_count == 2


def test_actuals_reload_after_same_day_input_refresh():
    key = ingest.cache_key("weekly_stats", [2026])
    cache.put(key, [{"points": 10}])

    def scored(scoring, **kwargs):
        rows = cache.get(key, ttl_seconds=1000)
        return 2, {"receiver": [(1, rows[0]["points"])]}

    with mock.patch.object(actuals, "fetch_current_season_actuals", side_effect=scored):
        assert api._actuals_for(_contract())[1]["receiver"] == [(1, 10)]
        cache.put(key, [{"points": 123}])
        assert api._actuals_for(_contract())[1]["receiver"] == [(1, 123)]


def test_context_missing_then_created_then_replaced_is_reloaded():
    path = context_store.snapshot_path(2026)
    with mock.patch.object(context_store, "load_snapshot", return_value=None) as load:
        assert api._context_for(2026) == {}
        path.parent.mkdir(parents=True)
        path.write_text("first generation")
        load.return_value = {"player": "first"}
        assert api._context_for(2026) == {"player": "first"}
        path.write_text("second, changed generation")
        load.return_value = {"player": "second"}
        assert api._context_for(2026) == {"player": "second"}
        assert load.call_count == 3


def test_schedule_reloads_when_local_artifact_changes():
    key = ingest.cache_key("schedules", [2026])
    cache.put(key, [{"week": 1}])
    with mock.patch.object(schedule, "fetch_team_weeks", return_value={"BUF": [1]}) as load:
        assert api._schedule_for(2026) == {"BUF": [1]}
        cache.put(key, [{"week": 1}, {"week": 2}])
        load.return_value = {"BUF": [1, 2]}
        assert api._schedule_for(2026) == {"BUF": [1, 2]}
        assert load.call_count == 2
        assert all(call.kwargs["cache_only"] for call in load.call_args_list)


@pytest.mark.parametrize("changed", ["context", "schedule", "weekly", "pbp", "projection"])
def test_values_invalidate_when_auxiliary_artifact_changes(tmp_path, changed):
    projection = tmp_path / "projection.json"
    projection.write_text("projection")
    context = context_store.snapshot_path(2026)
    context.parent.mkdir(parents=True)
    context.write_text("generation one")
    cache.put(ingest.cache_key("schedules", [2026]), [{"week": 1}])
    cache.put(ingest.cache_key("weekly_stats", [2026]), [{"week": 1}])
    pbp = pbp_weekly.pbp_weekly_path(2026)
    pbp.parent.mkdir(parents=True)
    pbp.write_text("PBP generation one")
    contract = _contract()
    with (
        mock.patch.object(api, "latest_snapshot_path", return_value=projection),
        mock.patch.object(api, "_actuals_for", return_value=(2, {})),
        mock.patch.object(api, "_context_for", return_value={}),
        mock.patch.object(api, "_schedule_for", return_value={}),
        mock.patch.object(api, "run_valuation", return_value={"status": "ok"}) as run,
    ):
        api.get_bdvm_values(contract, "test")
        api.get_bdvm_values(contract, "test")
        assert run.call_count == 1
        if changed in ("context", "pbp", "projection"):
            {"context": context, "pbp": pbp, "projection": projection}[changed].write_text(
                "generation two is new"
            )
        else:
            feed = "schedules" if changed == "schedule" else "weekly_stats"
            cache.put(ingest.cache_key(feed, [2026]), [{"week": 1}, {"week": 2}])
        api.get_bdvm_values(contract, "test")
        assert run.call_count == 2


def test_concurrent_values_build_once_and_failed_build_can_retry():
    contract = _contract()
    barrier = threading.Barrier(6)

    def build(*args, **kwargs):
        time.sleep(0.05)
        return {"status": "ok"}

    def request():
        barrier.wait(timeout=5)
        return api.get_bdvm_values(contract, "test")

    with (
        mock.patch.object(api, "latest_snapshot_path", return_value=None),
        mock.patch.object(api, "_context_for", return_value={}),
        mock.patch.object(api, "_schedule_for", return_value={}),
        mock.patch.object(api, "run_valuation", side_effect=build) as run,
        ThreadPoolExecutor(max_workers=6) as pool,
    ):
        outputs = list(pool.map(lambda _: request(), range(6)))
        assert run.call_count == 1
        assert all(output == outputs[0] for output in outputs)
        api.reset_cache()
        run.side_effect = RuntimeError("failed build")
        with pytest.raises(RuntimeError, match="failed build"):
            api.get_bdvm_values(contract, "test")
        run.side_effect = build
        assert api.get_bdvm_values(contract, "test") == {"status": "ok"}


def test_auxiliary_caches_are_bounded():
    with mock.patch.object(actuals, "fetch_current_season_actuals", return_value=(2, {})):
        for rec in range(40):
            api._actuals_for(_contract(rec))
    assert len(api._actuals_cache) <= 16


def test_failed_actuals_read_is_retried_and_report_uses_season_not_week(tmp_path):
    projection = tmp_path / "projection.json"
    projection.write_text("projection")
    contract = _contract()
    with (
        mock.patch.object(api, "latest_snapshot_path", return_value=projection),
        mock.patch.object(api, "_context_for", return_value={}),
        mock.patch.object(api, "_schedule_for", return_value={}),
        mock.patch.object(
            actuals, "fetch_current_season_actuals", side_effect=[OSError("busy"), (2, {})]
        ) as load,
        mock.patch.object(api, "run_valuation", side_effect=lambda *a, **k: {"meta": {}}) as run,
        mock.patch.object(api, "_auxiliary_input_report", return_value={}) as report,
    ):
        api.get_bdvm_values(contract, "test")
        api.get_bdvm_values(contract, "test")
        api.get_bdvm_values(contract, "test")
        assert load.call_count == 2
        assert run.call_count == 2
        assert all(call.args == (2026, 2026) for call in report.call_args_list)
