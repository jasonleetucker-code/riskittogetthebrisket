"""Current-main #1338: equal inputs share work; changed facts never share answers."""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
from threading import Barrier, Event, Lock, Timer

import pytest

from src.api import gameplan


@pytest.fixture(autouse=True)
def clear_cache():
    gameplan.invalidate_cache()
    yield
    gameplan.invalidate_cache()


@pytest.fixture
def facts(tmp_path, monkeypatch):
    rows = [
        {
            "ownerId": "one",
            "teamName": "One",
            "fullRoster": [
                {
                    "playerId": "p1",
                    "canonicalName": "Player One",
                    "position": "QB",
                    "rosValue": 80.0,
                }
            ],
        }
    ]
    slots = ["QB"]
    snapshot = tmp_path / "roster.json"
    snapshot.write_text("fixed")
    sim = tmp_path / "sim.json"
    sim.write_text('{"playoffOdds": [{"ownerId": "one", "championshipOdds": 0.5}]}')
    monkeypatch.setattr(gameplan, "load_or_compute_team_strength", lambda key: deepcopy(rows))
    monkeypatch.setattr(gameplan, "load_league_starter_slots", lambda key: list(slots))
    monkeypatch.setattr(gameplan, "_team_strength_stamp_path", lambda key: snapshot)
    monkeypatch.setattr(gameplan, "_sim_playoff_path", lambda key: sim)
    contract = {
        "scrapeTimestamp": "fixed",
        "playersArray": [{"playerId": "p1", "age": 25, "canonicalSiteValues": {"test": 100}}],
    }
    return rows, slots, contract


def test_concurrent_identical_misses_build_once(facts, monkeypatch):
    inputs = gameplan.load_league_inputs("one", "profile", facts[2])
    arrivals = Barrier(6)
    entered = Event()
    release = Event()
    lock = Lock()
    calls = []

    def load(*args):
        arrivals.wait(timeout=5)
        return inputs

    real_build = gameplan.build_league_bundle

    def build(value):
        with lock:
            calls.append(value.source_stamp)
        entered.set()
        assert release.wait(5)
        return real_build(value)

    monkeypatch.setattr(gameplan, "load_league_inputs", load)
    monkeypatch.setattr(gameplan, "build_league_bundle", build)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(gameplan.get_league_bundle, "one", "profile", {}) for _ in range(6)]
        assert entered.wait(5)
        # Synchronize cold callers before releasing the real solve. No latency SLO.
        timer = Timer(0.1, release.set)
        timer.start()
        try:
            results = [f.result(timeout=10) for f in futures]
        finally:
            release.set()
            timer.join()
    assert len(calls) == 1
    assert len({id(bundle) for bundle, _ in results}) == 1
    assert sum(not cached for _, cached in results) == 1


@pytest.mark.parametrize("dimension", ["roster", "slots", "age", "value"])
def test_same_observation_stamp_changed_facts_rebuild(facts, dimension):
    rows, slots, contract = facts
    first, _ = gameplan.get_league_bundle("one", "profile", contract)
    if dimension == "roster":
        rows[0]["fullRoster"][0]["rosValue"] = 60
    elif dimension == "slots":
        slots.append("QB")
    elif dimension == "age":
        contract["playersArray"][0]["age"] = 31
    else:
        contract["playersArray"][0]["canonicalSiteValues"]["test"] = 200
    second, cached = gameplan.get_league_bundle("one", "profile", contract)
    assert not cached
    assert second.inputs.source_stamp != first.inputs.source_stamp
    assert second.inputs == gameplan.load_league_inputs("one", "profile", contract)


def test_distinct_leagues_can_build_concurrently(facts, monkeypatch):
    inputs = gameplan.load_league_inputs("one", "profile", facts[2])
    rendezvous = Barrier(2)
    real_build = gameplan.build_league_bundle
    monkeypatch.setattr(
        gameplan, "load_league_inputs", lambda key, *args: replace(inputs, league_key=key)
    )

    def build(value):
        rendezvous.wait(timeout=5)
        return real_build(value)

    monkeypatch.setattr(gameplan, "build_league_bundle", build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(gameplan.get_league_bundle, key, "profile", {}) for key in ("one", "two")
        ]
        results = [f.result(timeout=10) for f in futures]
    assert {b.inputs.league_key for b, _ in results} == {"one", "two"}


def test_failed_build_can_retry(facts, monkeypatch):
    real_build = gameplan.build_league_bundle
    calls = 0

    def build(inputs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("controlled failure")
        return real_build(inputs)

    monkeypatch.setattr(gameplan, "build_league_bundle", build)
    with pytest.raises(ValueError, match="controlled failure"):
        gameplan.get_league_bundle("one", "profile", facts[2])
    bundle, cached = gameplan.get_league_bundle("one", "profile", facts[2])
    assert not cached
    assert bundle.inputs.league_key == "one"
    assert calls == 2


def test_invalidation_during_team_build_does_not_repopulate(facts, monkeypatch):
    entered, release = Event(), Event()
    real_build = gameplan.build_gameplan

    def build(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(gameplan, "build_gameplan", build)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(gameplan.get_team_gameplan, "one", "profile", facts[2], "one")
        assert entered.wait(5)
        gameplan.invalidate_cache("one")
        release.set()
        future.result(timeout=10)
    assert not gameplan._TEAM_CACHE


def test_roster_capacity_is_captured_in_cache_identity(facts, monkeypatch):
    capacity = [25]
    monkeypatch.setattr(gameplan, "_roster_limit", lambda key: capacity[0])
    first, _ = gameplan.get_league_bundle("one", "profile", facts[2])
    capacity[0] = 30
    second, cached = gameplan.get_league_bundle("one", "profile", facts[2])
    assert not cached
    assert first.inputs.source_stamp != second.inputs.source_stamp
    assert first.inputs.roster_limit == 25
    assert second.inputs.roster_limit == 30


def test_concurrent_team_misses_share_derivation(facts, monkeypatch):
    real_bundle = gameplan.get_league_bundle
    gameplan.get_league_bundle("one", "profile", facts[2])
    arrivals = Barrier(4)
    entered, release = Event(), Event()
    calls = []
    real_build = gameplan.build_gameplan

    def bundle(*args):
        answer = real_bundle(*args)
        arrivals.wait(timeout=5)
        return answer

    def build(*args, **kwargs):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(gameplan, "get_league_bundle", bundle)
    monkeypatch.setattr(gameplan, "build_gameplan", build)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(gameplan.get_team_gameplan, "one", "profile", facts[2], "one")
            for _ in range(4)
        ]
        assert entered.wait(5)
        timer = Timer(0.1, release.set)
        timer.start()
        try:
            answers = [f.result(timeout=10) for f in futures]
        finally:
            release.set()
            timer.join()
    assert len(calls) == 1
    assert sum(not a["timing"]["teamBuildCached"] for a in answers) == 1
    assert all(a["timing"]["leagueBuildCached"] for a in answers)


def test_invalidated_bundle_build_is_not_joined_or_published(facts, monkeypatch):
    entered, release = Event(), Event()
    real_build = gameplan.build_league_bundle
    calls = []

    def build(inputs):
        calls.append(1)
        if len(calls) == 1:
            entered.set()
            assert release.wait(5)
        return real_build(inputs)

    monkeypatch.setattr(gameplan, "build_league_bundle", build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(gameplan.get_league_bundle, "one", "profile", facts[2])
        assert entered.wait(5)
        gameplan.invalidate_cache("one")
        try:
            second = pool.submit(gameplan.get_league_bundle, "one", "profile", facts[2]).result(5)
        finally:
            release.set()
        first.result(5)
    assert len(calls) == 2
    assert gameplan.get_league_bundle("one", "profile", facts[2]) == (second[0], True)


def test_changed_inputs_during_old_build_do_not_restore_old_cache(facts, monkeypatch):
    entered, release = Event(), Event()
    real_build = gameplan.build_league_bundle

    def build(inputs):
        if inputs.player_meta["p1"]["age"] == 25:
            entered.set()
            assert release.wait(5)
        return real_build(inputs)

    monkeypatch.setattr(gameplan, "build_league_bundle", build)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(gameplan.get_league_bundle, "one", "profile", deepcopy(facts[2]))
        assert entered.wait(5)
        changed = deepcopy(facts[2])
        changed["playersArray"][0]["age"] = 30
        try:
            second = pool.submit(gameplan.get_league_bundle, "one", "profile", changed).result(5)
        finally:
            release.set()
        old = first.result(5)[0]
    assert old.inputs.player_meta["p1"]["age"] == 25
    assert second[0].inputs.player_meta["p1"]["age"] == 30
    assert gameplan.get_league_bundle("one", "profile", changed) == (second[0], True)


def test_followers_share_failure_and_later_request_retries(facts, monkeypatch):
    inputs = gameplan.load_league_inputs("one", "profile", facts[2])
    arrivals = Barrier(4)
    entered, release = Event(), Event()
    calls = []

    def load(*args):
        arrivals.wait(timeout=5)
        return inputs

    def build(value):
        calls.append(1)
        entered.set()
        assert release.wait(5)
        raise ValueError("controlled shared failure")

    real_build = gameplan.build_league_bundle
    monkeypatch.setattr(gameplan, "load_league_inputs", load)
    monkeypatch.setattr(gameplan, "build_league_bundle", build)
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(gameplan.get_league_bundle, "one", "profile", {}) for _ in range(4)]
        assert entered.wait(5)
        timer = Timer(0.1, release.set)
        timer.start()
        try:
            for future in futures:
                with pytest.raises(ValueError, match="controlled shared failure"):
                    future.result(5)
        finally:
            release.set()
            timer.join()
    assert len(calls) == 1
    monkeypatch.setattr(gameplan, "load_league_inputs", lambda *args: inputs)
    monkeypatch.setattr(gameplan, "build_league_bundle", real_build)
    assert gameplan.get_league_bundle("one", "profile", {})[1] is False


def test_package_builder_uses_captured_capacity(facts, monkeypatch):
    capacity = [25]
    monkeypatch.setattr(gameplan, "_roster_limit", lambda key: capacity[0])
    bundle, _ = gameplan.get_league_bundle("one", "profile", facts[2])
    capacity[0] = 30
    observed = []

    def packages(*args, **kwargs):
        observed.append(kwargs)
        return {}

    monkeypatch.setattr(gameplan._packages, "generate_packages", packages)
    gameplan._build_packages(bundle, "one", "one")
    assert observed[0]["roster_limit"] == 25
