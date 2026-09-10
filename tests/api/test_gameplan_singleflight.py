"""Concurrent gameplan requests share identical solves, not unrelated leagues."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest import mock

import pytest

from src.api import gameplan


@pytest.fixture(autouse=True)
def reset_cache():
    gameplan.invalidate_cache()
    yield
    gameplan.invalidate_cache()


def test_same_generation_solves_once_under_concurrent_requests():
    inputs = SimpleNamespace(source_stamp="generation-one")
    start = threading.Barrier(6)
    bundle = object()

    def build(_):
        time.sleep(0.05)
        return bundle

    def request(_):
        start.wait(timeout=5)
        return gameplan.get_league_bundle("league", "profile", {})

    with (
        mock.patch.object(gameplan, "load_league_inputs", return_value=inputs),
        mock.patch.object(gameplan, "build_league_bundle", side_effect=build) as solve,
        ThreadPoolExecutor(max_workers=6) as pool,
    ):
        outputs = list(pool.map(request, range(6)))
        assert solve.call_count == 1
        assert all(result is bundle for result, _ in outputs)
        assert sum(not hit for _, hit in outputs) == 1
        inputs.source_stamp = "generation-two"
        assert gameplan.get_league_bundle("league", "profile", {}) == (bundle, False)
        assert solve.call_count == 2


def test_unrelated_leagues_can_build_concurrently_and_failures_retry():
    both_building = threading.Barrier(2)

    def inputs(league, *_):
        return SimpleNamespace(source_stamp=league)

    def build(value):
        both_building.wait(timeout=5)
        return value.source_stamp

    with (
        mock.patch.object(gameplan, "load_league_inputs", side_effect=inputs),
        mock.patch.object(gameplan, "build_league_bundle", side_effect=build) as solve,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        outputs = list(
            pool.map(lambda league: gameplan.get_league_bundle(league, "p", {}), ["a", "b"])
        )
        assert outputs == [("a", False), ("b", False)]
        solve.side_effect = RuntimeError("solver failed")
        with pytest.raises(RuntimeError, match="solver failed"):
            gameplan.get_league_bundle("c", "p", {})
        solve.side_effect = lambda value: value.source_stamp
        assert gameplan.get_league_bundle("c", "p", {}) == ("c", False)
