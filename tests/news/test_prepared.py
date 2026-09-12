"""News artifact integration stays offline and proves request/provider isolation."""

from __future__ import annotations

import json
import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.news.base import NewsItem, PlayerMention
from src.news.context import espn_targets, player_meta, player_names
from src.news.prepared import (
    ASSET,
    KEY,
    MODEL_VERSION,
    NewsNotReady,
    PreparedNewsReader,
    load_news,
    refresh_prepared_news,
)
from src.news.service import NewsService
from src.serving.artifacts import ArtifactStore
from src.serving.builder import prepare_generation
from src.serving.serialization import publish_generation

NOW = 1_789_056_000.0


def stamp(epoch=NOW):
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()


def item(ident="one", provider="test", age=0, name="Player One"):
    return NewsItem(
        ident,
        stamp(NOW - age),
        provider,
        provider.title(),
        "info",
        "news",
        f"{name} returns",
        players=[PlayerMention(name=name, ambiguous=name == "CJ Allen")],
        tags=["news"],
        confidence=0.8,
    )


class Provider:
    def __init__(self, name="test", items=None):
        self.name = name
        self.label = name.title()
        self.items = items if items is not None else [item(provider=name)]
        self.error = None
        self.calls = 0

    def fetch(self, **_kwargs):
        self.calls += 1
        if self.error:
            raise self.error
        return self.items


@pytest.fixture
def setup(tmp_path):
    now = [NOW]
    store = ArtifactStore(tmp_path / "private")
    contract = {
        "contractVersion": "test",
        "scrapeTimestamp": stamp(),
        "playerCount": 1,
        "playersArray": [
            {"playerId": "one", "displayName": "Player One", "position": "WR", "team": "GB"}
        ],
        "players": {},
        "sleeper": {"scoringSettings": {"rec": 1}, "teams": []},
    }
    board = prepare_generation(contract, {"players": {}}, {"producedAt": stamp()}, {"ok": True})
    publish_generation(board, store=store)
    provider = Provider()
    service = NewsService([provider], clock=lambda: now[0], cache_ttl_s=1)
    return now, store, provider, service


def publish(store, service, **kwargs):
    return refresh_prepared_news(
        store,
        service,
        player_names=["Player One", "CJ Allen"],
        player_meta={"Player One": {"position": "WR", "team": "GB"}},
        input_generation=store.read_current("canonical-serving", "default").generation_id,
        **kwargs,
    )


def test_exact_types_round_trip_and_public_serialization(setup):
    _, store, provider, service = setup
    provider.items.append(item("two", name="CJ Allen"))
    loaded = load_news(publish(store, service))
    assert type(loaded.items[0]) is NewsItem
    assert type(loaded.items[0].players[0]) is PlayerMention
    assert loaded.items[0].players[0].position == "WR"
    assert loaded.items[1].players[0].ambiguous
    assert loaded.to_dict()["items"][0]["publishedAt"] == stamp()
    assert loaded.to_dict()["items"][0]["confidence"] == 0.8


def test_reader_never_reads_disk_or_calls_providers_on_request(setup, monkeypatch):
    now, store, provider, service = setup
    publish(store, service)
    reader = PreparedNewsReader(store, clock=lambda: now[0])
    assert reader.reload_if_changed()

    def forbidden(*_args):
        raise AssertionError("request performed artifact I/O")

    monkeypatch.setattr(store, "read_current", forbidden)
    monkeypatch.setattr(store, "current_version", forbidden)
    assert len(reader.aggregate(team_names=["Player One"]).items) == 1
    assert reader.aggregate(team_names=["Unrelated"]).items == []
    assert provider.calls == 1


def test_retains_failed_provider_across_worker_restart_but_runs_stay_failed(setup):
    now, store, provider, service = setup
    original = load_news(publish(store, service))
    now[0] += 50
    failure = Provider()
    failure.error = RuntimeError("unavailable")
    fresh_process = NewsService([failure], clock=lambda: now[0])
    failed = load_news(publish(store, fresh_process))
    assert failed.items == original.items
    assert failed.retained
    assert failed.generated_at == original.generated_at
    assert failed.last_attempt_at != original.last_attempt_at
    assert failed.last_success_at == original.last_success_at
    assert not any(run.ok for run in failed.provider_runs)
    assert failed.provider_runs[0].count == 0


def test_partial_failure_retains_only_failed_provider_and_empty_success_clears(setup):
    now, store, provider, _ = setup
    other = Provider("other", [item("other", provider="other")])
    service = NewsService([provider, other], clock=lambda: now[0])
    publish(store, service)
    now[0] += 30
    provider.error = RuntimeError("down")
    other.items = []
    result = load_news(publish(store, service))
    assert [row.id for row in result.items] == ["one"]
    assert result.retained and any(run.ok for run in result.provider_runs)
    provider.error = None
    provider.items = []
    cleared = load_news(publish(store, service))
    assert cleared.items == [] and not cleared.retained


def test_missing_is_unknown_and_corruption_keeps_last_valid(setup):
    now, store, _, service = setup
    reader = PreparedNewsReader(store, clock=lambda: now[0])
    assert not reader.reload_if_changed()
    with pytest.raises(NewsNotReady):
        reader.aggregate()
    publish(store, service)
    assert reader.reload_if_changed()
    pointer = store.root / ASSET / KEY / "current.json"
    pointer.write_text("not JSON")
    assert not reader.reload_if_changed()
    assert reader.aggregate().items
    assert reader.aggregate().stale


def test_corruption_recovers_only_after_healthy_refresh(setup):
    now, store, provider, service = setup
    publish(store, service)
    reader = PreparedNewsReader(store, clock=lambda: now[0])
    reader.reload_if_changed()
    pointer = store.root / ASSET / KEY / "current.json"
    pointer.write_text("bad JSON")
    provider.error = RuntimeError("down")
    with pytest.raises(NewsNotReady, match="refresh incomplete"):
        publish(store, service)
    assert not reader.reload_if_changed() and reader.aggregate().items
    provider.error = None
    now[0] += 20
    publish(store, service)
    assert reader.reload_if_changed()
    assert reader.last_error is None and not reader.aggregate().stale


def test_reader_applies_hard_cutoff_without_new_pointer(setup):
    now, store, provider, service = setup
    provider.items = [item(age=7 * 86400 - 30)]
    publish(store, service)
    reader = PreparedNewsReader(store, clock=lambda: now[0])
    reader.reload_if_changed()
    assert reader.aggregate().items
    now[0] += 31
    assert reader.aggregate().items == []
    assert not reader.reload_if_changed()


def test_reader_age_marks_stale_without_lying_about_last_run(setup):
    now, store, _, service = setup
    publish(store, service)
    reader = PreparedNewsReader(store, clock=lambda: now[0])
    reader.reload_if_changed()
    now[0] += 601
    output = reader.aggregate()
    assert output.stale and output.provider_runs[0].ok
    assert output.last_attempt_at == stamp()


def test_failed_or_malformed_candidate_retains_accepted_artifact(setup):
    _, store, provider, service = setup
    accepted = publish(store, service)
    provider.items = [replace(item(), severity="invalid")]
    with pytest.raises(ValueError, match="severity"):
        publish(store, service)
    assert store.read_current(ASSET, KEY).generation_id == accepted.generation_id


def test_unknown_provider_result_is_a_failure_not_empty_success(setup):
    _, store, provider, service = setup
    provider.items = None
    result = load_news(publish(store, service))
    assert not result.provider_runs[0].ok and result.items == []
    assert "TypeError" in result.provider_runs[0].error
    assert result.last_success_at is None and result.stale
    assert store.read_current(ASSET, KEY).manifest["sourceAsOf"]["news"] is None


def test_no_providers_is_not_observed_empty_success(setup):
    _, store, _, _ = setup
    with pytest.raises(NewsNotReady):
        publish(store, NewsService([]))


def test_in_memory_service_retains_on_expiry_and_filters_age(setup):
    now, _, provider, service = setup
    first = service.aggregate()
    provider.error = RuntimeError("down")
    now[0] += 2
    result = service.aggregate()
    assert result.items == first.items and result.retained
    assert not result.provider_runs[0].ok
    now[0] += 7 * 86400
    assert service.aggregate().items == []


def test_background_reload_swaps_valid_generation_and_stops(setup):
    now, store, provider, service = setup
    publish(store, service)
    reader = PreparedNewsReader(store, clock=lambda: now[0])
    loaded = threading.Event()
    original_reload = reader.reload_if_changed

    def reload():
        if original_reload():
            loaded.set()

    reader.reload_if_changed = reload
    reader.start(interval=0.01)
    try:
        assert loaded.wait(3)
        previous = reader.aggregate()
        loaded.clear()
        provider.items = [item("new")]
        publish(store, service)
        assert loaded.wait(3)
        assert reader.aggregate().items[0].id == "new"
        assert previous.items[0].id == "one"
    finally:
        assert reader.stop()


def test_contract_context_preserves_identity_ambiguity_and_target_rank():
    contract = {
        "playersArray": [
            {
                "displayName": "Player One",
                "position": "WR",
                "team": "gb",
                "playerId": "1",
                "rank": 2,
            },
            {
                "displayName": "Player One",
                "position": "LB",
                "team": "gb",
                "playerId": "2",
                "rank": 1,
            },
        ],
        "sleeper": {"players": {"1": {"espn_id": "11"}, "2": {"espn_id": "22"}}},
    }
    assert player_names(contract) == ["Player One", "Player One"]
    assert player_meta(contract)["Player One"] == {"position": None, "team": None}
    targets = espn_targets(contract)
    assert [target["espnId"] for target in targets] == ["22", "11"]
    assert targets[0]["team"] == "GB"


def test_rejects_schema_and_provider_status_type(setup):
    _, store, _, service = setup
    generation = publish(store, service)
    body = json.loads(generation.files["news.json"])
    body["provider_runs"][0]["ok"] = "true"
    with pytest.raises(ValueError, match="provider run"):
        store.publish(
            ASSET,
            KEY,
            {"news.json": json.dumps(body).encode()},
            {"modelVersion": MODEL_VERSION, "inputGenerations": {}, "configHash": "test"},
            validator=load_news,
        )


@pytest.mark.parametrize("provider_name", ["espn", "pfk", "espn_player", "sleeper"])
def test_malformed_upstream_shapes_are_failed_runs(provider_name):
    from src.news.providers.espn import EspnRssProvider
    from src.news.providers.espn_player import EspnPlayerNewsProvider
    from src.news.providers.pfk import PfkArticlesProvider
    from src.news.providers.sleeper import SleeperTrendingProvider

    providers = {
        "espn": lambda: EspnRssProvider(
            fetcher=lambda _url: b"<html><body>Unavailable</body></html>"
        ),
        "pfk": lambda: PfkArticlesProvider(
            fetcher=lambda _url: b"<html><body>Unavailable</body></html>"
        ),
        "espn_player": lambda: EspnPlayerNewsProvider(
            targets_supplier=lambda: [{"name": "Player One", "espnId": "1"}],
            fetcher=lambda _url: b'{"error":"unavailable"}',
        ),
        "sleeper": SleeperTrendingProvider,
    }
    provider = providers[provider_name]()
    if provider_name == "sleeper":
        provider._get_json = lambda _path: {"error": "unavailable"}
    result = NewsService([provider], clock=lambda: NOW).refresh_snapshot()
    assert result.items == [] and not result.provider_runs[0].ok
    assert result.last_success_at is None


def espn_provider(clock, failures):
    from src.news.providers.espn_player import EspnPlayerNewsProvider

    def fetch(url):
        ident = "1" if "playerId=1&" in url else "2"
        if ident in failures:
            raise RuntimeError("upstream unavailable")
        return json.dumps(
            {
                "feed": [
                    {
                        "id": ident,
                        "headline": f"Player {ident} returns",
                        "published": stamp(),
                        "story": "News",
                    }
                ]
            }
        ).encode()

    return EspnPlayerNewsProvider(
        targets_supplier=lambda: [{"name": f"Player {i}", "espnId": str(i)} for i in (1, 2)],
        fetcher=fetch,
        clock=lambda: clock[0],
        player_ttl_s=60,
    )


def test_warm_espn_failure_retains_items_without_minting_success(setup):
    now, store, _, _ = setup
    failures = set()
    provider = espn_provider(now, failures)
    service = NewsService([provider], clock=lambda: now[0])
    first = load_news(publish(store, service))
    now[0] += 61
    failures.update({"1", "2"})
    result = load_news(publish(store, service))
    assert result.items == first.items
    run = result.provider_runs[0]
    assert not run.ok and run.attempted_count == run.failed_count == 2
    assert run.retained and result.retained and result.stale
    assert result.last_success_at == first.last_success_at
    assert result.to_dict()["providerRuns"][0]["failedCount"] == 2


def test_espn_partial_attempt_success_and_fresh_cache_are_distinct(setup):
    now, store, _, _ = setup
    failures = set()
    service = NewsService([espn_provider(now, failures)], clock=lambda: now[0])
    first = load_news(publish(store, service))
    now[0] += 10
    cached = load_news(publish(store, service))
    assert cached.provider_runs[0].ok and cached.provider_runs[0].attempted_count == 0
    assert cached.last_success_at == first.last_success_at
    now[0] += 61
    failures.add("1")
    partial = load_news(publish(store, service))
    run = partial.provider_runs[0]
    assert run.ok and run.attempted_count == 2 and run.failed_count == 1
    assert run.retained and partial.retained
    assert partial.last_success_at != first.last_success_at


def test_valid_empty_feeds_remain_successful():
    from src.news.providers.espn import EspnRssProvider
    from src.news.providers.espn_player import EspnPlayerNewsProvider
    from src.news.providers.pfk import PfkArticlesProvider

    for provider in [
        EspnRssProvider(fetcher=lambda _url: b"<rss><channel/></rss>"),
        PfkArticlesProvider(fetcher=lambda _url: b"<urlset/>"),
        EspnPlayerNewsProvider(
            targets_supplier=lambda: [{"name": "Player One", "espnId": "1"}],
            fetcher=lambda _url: b'{"feed":[]}',
        ),
    ]:
        result = NewsService([provider], clock=lambda: NOW).refresh_snapshot()
        assert result.provider_runs[0].ok and result.items == []
        assert result.last_success_at == stamp()


def test_watch_worker_reuses_providers_between_cycles(setup, monkeypatch):
    from scripts import refresh_prepared_news as cli

    _, store, provider, service = setup
    monkeypatch.setattr(cli, "ArtifactStore", lambda _root: store)
    constructed = []

    def build(**kwargs):
        constructed.append(kwargs)
        return service

    monkeypatch.setattr(cli, "build_default_service", build)
    stop = threading.Event()
    waits = []

    def wait(delay):
        waits.append(delay)
        if len(waits) == 1:
            provider.error = RuntimeError("down")
        else:
            stop.set()

    stop.wait = wait
    monkeypatch.setattr(cli.threading, "Event", lambda: stop)
    monkeypatch.setattr(cli.signal, "signal", lambda *_args: None)
    assert cli.main(["--watch"]) == 0
    assert len(constructed) == 1 and provider.calls == 2
    assert waits == [600, 15]
    assert load_news(store.read_current(ASSET, KEY)).retained
