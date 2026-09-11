"""Canonical parity and live request invariants for prepared serving."""

import asyncio
import copy
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from src.api import rank_history
from src.serving import builder
from src.serving.artifacts import ArtifactStore, CorruptArtifact
from src.serving.league_views import expire_context, prepare_league_views, validate_league_views
from src.serving.projections import BOARD_FIELDS, asset_key, project_board
from src.serving.runtime import AtomicRuntime
from src.serving.serialization import (
    ASSET,
    KEY,
    load_generation,
    publish_generation,
    validate_generation,
)


@pytest.fixture
def board():
    contract = {
        "contractVersion": "test",
        "date": "2026-09-10",
        "scrapeTimestamp": "2026-09-10T12:00:00+00:00",
        "meta": {"leagueKey": "main", "scoringProfile": "same"},
        "playerCount": 2,
        "playersArray": [
            {
                "playerId": "1",
                "displayName": "Player",
                "position": "WR",
                "assetClass": "offense",
                "rankDerivedValue": 1000,
                "canonicalConsensusRank": 1,
                "sourceCount": 2,
                "values": {"displayValue": 1000, "rawComposite": 1131},
                "sourceRankMeta": {"one": {"valueContribution": 900, "appliedWeight": 1}},
                "rankHistory": [{"date": "2026-09-09", "rank": 2}],
                "sourceAudit": {"private": "details"},
            },
            {
                "displayName": "2027 Early 1st",
                "position": "PICK",
                "assetClass": "pick",
                "rankDerivedValue": None,
                "canonicalConsensusRank": None,
                "sourceCount": 0,
            },
        ],
        "players": {},
        "sleeper": {"scoringSettings": {"rec": 1}, "teams": []},
        "sites": [{"key": "one"}],
        "hillCurves": {},
        "methodology": {"version": "one"},
    }
    return builder.prepare_generation(
        contract, {"players": {}}, {"producedAt": contract["scrapeTimestamp"]}, {"ok": True}
    )


def test_projection_preserves_materializer_fields_and_route_envelope(board):
    source = (Path(__file__).resolve().parents[2] / "frontend/lib/dynasty-data.js").read_text(
        encoding="utf-8"
    )
    body = source.split("function _materializePlayerArrayRow", 1)[1].split("\nfunction ", 1)[0]
    reads = set(re.findall(r"\bplayer(?:\?\.)?\.([A-Za-z_]\w*)", body))
    assert len(reads) > 30
    assert reads - {"readModelKey"} <= BOARD_FIELDS
    for name in ("rankings", "trade"):
        payload = board.views[name].payload
        assert len(payload["playersArray"]) == 2
        assert payload["playersArray"][1]["rankDerivedValue"] is None
        assert payload["scrapeTimestamp"] == board.contract["scrapeTimestamp"]
        assert payload["sites"] == board.contract["sites"]
        assert (
            payload["playersArray"][0]["rankHistory"]
            == board.contract["playersArray"][0]["rankHistory"]
        )
    assert (
        board.views["rankings"].payload["playersArray"]
        == board.views["trade"].payload["playersArray"]
    )


@pytest.mark.parametrize("lease_marker", [False, True])
def test_shadow_cache_prime_never_replaces_durable_source_state(
    tmp_path, board, monkeypatch, lease_marker
):
    import server
    from src.serving.artifacts import _publish_lock

    monkeypatch.setenv("RISKIT_SERVING_MODE", "shadow")
    monkeypatch.setenv("RISKIT_SERVING_DIR", str(tmp_path))
    store = ArtifactStore(tmp_path)
    accepted = publish_generation(board, store=store)
    contract = copy.deepcopy(board.contract)
    contract["meta"]["cachePrime"] = True
    cached = builder.prepare_generation(contract, board.raw, board.source, board.health)
    monkeypatch.setattr(builder, "build_generation", lambda *a, **k: cached)
    monkeypatch.setattr(server, "_warm_overlays_in_background", lambda *a: None)
    with _publish_lock(tmp_path / "producer.lock", 0):
        assert (
            server._prime_latest_payload(
                board.raw, data_source=board.source, _source_lease_held=lease_marker
            )
            is cached
        )
        assert store.read_current(ASSET, KEY).generation_id == accepted.generation_id
    assert server.latest_serving_generation is cached


def test_shadow_fresh_callback_publishes_inside_source_lease(tmp_path, board, monkeypatch):
    import server
    from src.serving import producer, serialization
    from src.serving.artifacts import PublishLockTimeout, _publish_lock

    monkeypatch.setenv("RISKIT_SERVING_MODE", "shadow")
    monkeypatch.setenv("RISKIT_SERVING_DIR", str(tmp_path))
    monkeypatch.setattr(server, "scrape_run_lock", asyncio.Lock())
    for name in (
        "_reconcile_orphaned_running_state",
        "_mark_scrape_success",
        "_finalize_scrape_run",
        "_warm_overlays_in_background",
    ):
        monkeypatch.setattr(server, name, lambda *a, **k: None)
    monkeypatch.setattr(server, "_start_scrape_run", lambda **k: "fixture")
    monkeypatch.setattr(builder, "build_generation", lambda *a, **k: board)
    monkeypatch.setattr(builder, "record_accepted_generation", lambda *a: None)
    publications = []
    original = serialization.publish_generation

    def publish(candidate):
        with pytest.raises(PublishLockTimeout):
            with _publish_lock(tmp_path / "producer.lock", 0):
                pytest.fail("durable shadow publisher lacked source lease")
        publications.append(original(candidate))

    async def collect(config, previous, *, publish, **kwargs):
        with _publish_lock(config.serving_root / "producer.lock", 0):
            await publish(board.raw, board.source)
        return producer.ProducerResult("success", raw=board.raw)

    monkeypatch.setattr(serialization, "publish_generation", publish)
    monkeypatch.setattr(producer, "run_source_cycle", collect)
    assert asyncio.run(server.run_scraper()) == board.raw
    assert len(publications) == 1
    assert (
        ArtifactStore(tmp_path).read_current(ASSET, KEY).generation_id
        == publications[0].generation_id
    )


def test_legacy_preparation_does_not_pay_for_disabled_read_models(board, monkeypatch):
    monkeypatch.setattr(
        builder, "project_board", lambda *a, **k: pytest.fail("disabled projection built")
    )
    monkeypatch.setattr(
        builder, "player_index", lambda *a: pytest.fail("disabled detail index built")
    )
    legacy = builder.prepare_generation(
        board.contract, board.raw, board.source, board.health, include_read_models=False
    )
    assert set(legacy.views) == {"full", "array", "runtime", "compact", "startup"}
    for name, view in legacy.views.items():
        assert view.raw == board.views[name].raw


def test_projection_rejects_duplicate_identity(board):
    duplicate = {**board.contract, "playersArray": [board.contract["playersArray"][0]] * 2}
    with pytest.raises(ValueError, match="duplicate"):
        project_board(duplicate, "g")


def test_gate_rejects_self_consistent_wrong_values_and_missing_universe(board):
    for mutate in (
        lambda p: p["playersArray"][0].update(rankDerivedValue=9000),
        lambda p: p["playersArray"].pop(),
    ):
        wrong = copy.deepcopy(board.views["rankings"].payload)
        mutate(wrong)
        altered = replace(board, views={**board.views, "rankings": builder.prepare_payload(wrong)})
        with pytest.raises(CorruptArtifact, match="canonical projection"):
            validate_generation(altered)


@pytest.mark.parametrize("view", ["array", "runtime", "startup", "compact"])
def test_legacy_representations_are_bound_to_full_contract(board, view):
    wrong = copy.deepcopy(board.views[view].payload)
    wrong["date"] = "different-generation"
    altered = replace(board, views={**board.views, view: builder.prepare_payload(wrong)})
    with pytest.raises(CorruptArtifact, match="canonical projection"):
        validate_generation(altered)


def test_roundtrip_and_hot_reload_never_call_builder(tmp_path, board, monkeypatch):
    store = ArtifactStore(tmp_path)
    first = publish_generation(board, store=store)
    monkeypatch.setattr(
        builder, "build_generation", lambda *a, **k: pytest.fail("read rebuilt board")
    )
    runtime = AtomicRuntime(store, ASSET, KEY, load_generation)
    assert runtime.reload_if_changed()
    old = runtime.current
    assert old.generation_id == board.generation_id
    assert old.artifact_generation_id == first.generation_id
    assert not runtime.reload_if_changed()
    changed = copy.deepcopy(board.contract)
    changed["playersArray"][0]["rankDerivedValue"] = 2000
    second = builder.prepare_generation(changed, board.raw, board.source, board.health)
    publish_generation(second, store=store)
    assert runtime.reload_if_changed()
    assert old.views["rankings"].payload["playersArray"][0]["rankDerivedValue"] == 1000
    assert runtime.current.views["rankings"].payload["playersArray"][0]["rankDerivedValue"] == 2000


def test_rank_history_preview_matches_accepted_append_without_writing(tmp_path, board):
    path = tmp_path / "rank.jsonl"
    preview = rank_history.load_history(path=path, pending_contract=board.contract)
    assert preview and not path.exists()
    rank_history.append_snapshot(board.contract, path=path)
    assert rank_history.load_history(path=path) == preview


def test_failed_candidate_never_records_history(board, monkeypatch):
    for owner, name in (
        (builder._rank_history, "append_snapshot"),
        (builder._source_history, "append_snapshot"),
        (builder._history_record, "record_contract"),
    ):
        monkeypatch.setattr(
            owner, name, lambda *a, **k: pytest.fail("candidate wrote accepted history")
        )
    monkeypatch.setattr(
        builder,
        "prepare_generation",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("encode failed")),
    )
    with pytest.raises(ValueError, match="encode failed"):
        builder.build_generation(
            {},
            {},
            is_fresh_scrape=True,
            build_contract=lambda *a, **k: copy.deepcopy(board.contract),
            validate_contract=lambda *a: {"ok": True},
        )


def test_read_model_endpoint_has_no_provider_or_builder_and_supports_etag(board, monkeypatch):
    import server

    cfg = SimpleNamespace(key="main", scoring_profile="same")
    prepared = prepare_league_views(board, cfg).views["rankings"]
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda request: cfg)
    monkeypatch.setattr(server, "latest_serving_generation", board)
    monkeypatch.setattr(server, "_league_serving_reader", SimpleNamespace(get=lambda *a: prepared))
    monkeypatch.setattr(
        server._sleeper_overlay, "fetch_sleeper_overlay", lambda **k: pytest.fail("provider called")
    )
    monkeypatch.setattr(
        server, "build_api_data_contract", lambda *a, **k: pytest.fail("board rebuilt")
    )
    request = Request(
        {
            "type": "http",
            "query_string": b"",
            "headers": [],
            "method": "GET",
            "path": "/api/read-models/rankings",
        }
    )
    response = asyncio.run(server.get_prepared_rankings(request))
    assert response.status_code == 200 and response.body == prepared.raw
    assert response.headers["cache-control"].startswith("private")
    request = Request({**request.scope, "headers": [(b"if-none-match", prepared.etag.encode())]})
    assert asyncio.run(server.get_prepared_rankings(request)).status_code == 304
    key = asset_key(board.contract["playersArray"][0])
    request = Request(
        {**request.scope, "query_string": f"generation={board.generation_id}".encode()}
    )
    assert asyncio.run(server.get_prepared_player(key, request)).status_code == 200
    request = Request({**request.scope, "query_string": b"generation=old"})
    assert asyncio.run(server.get_prepared_player(key, request)).status_code == 409


def test_partial_and_expired_rosters_are_not_ready(board):
    cfg = SimpleNamespace(key="main", scoring_profile="same")
    bundle = prepare_league_views(board, cfg)
    assert bundle.views["trade"].payload["meta"]["sleeperDataReady"] is False
    now = datetime.now(timezone.utc)
    views = {}
    for name, view in bundle.views.items():
        payload = copy.deepcopy(view.payload)
        payload["meta"].update(
            sleeperDataReady=True, leagueSourceAsOf=(now - timedelta(minutes=31)).isoformat()
        )
        views[name] = builder.prepare_payload(payload)
    stale = expire_context(replace(bundle, views=views), now=now)
    assert stale.views["trade"].payload["sleeper"] is None
    assert stale.views["trade"].payload["meta"]["leagueFreshnessState"] == "stale"
    assert (
        stale.views["rankings"].payload["playersArray"]
        == board.views["rankings"].payload["playersArray"]
    )


def test_fresh_roster_repairs_readiness_and_rejects_wrong_canonical_values(board, monkeypatch):
    from src.serving import league_views

    cfg = SimpleNamespace(key="main", scoring_profile="same")
    overlay = {
        "teams": [{"roster_id": 1}],
        "overlayFetchedAt": datetime.now(timezone.utc).isoformat(),
        "leagueConfig": {
            "scoringSettings": {"rec": 1},
            "rosterPositions": ["WR"],
            "leagueSettings": {"num_teams": 2},
        },
    }
    monkeypatch.setattr(league_views, "stamp_optimal_lineups", lambda *a, **k: None)
    bundle = prepare_league_views(board, cfg, overlay)
    assert bundle.views["trade"].payload["meta"]["sleeperDataReady"] is True
    validate_league_views(bundle, board, cfg)
    wrong = copy.deepcopy(bundle.views["rankings"].payload)
    wrong["playersArray"][0]["rankDerivedValue"] = 9000
    corrupted = replace(bundle, views={**bundle.views, "rankings": builder.prepare_payload(wrong)})
    with pytest.raises(CorruptArtifact, match="canonical projection"):
        validate_league_views(corrupted, board, cfg)


def test_prepared_news_route_does_no_provider_or_contract_scan(tmp_path, monkeypatch):
    import server
    from src.news.prepared import PreparedNewsReader
    from src.news.service import AggregatedNews

    reader = PreparedNewsReader(ArtifactStore(tmp_path))
    # An accepted empty feed is different from an absent snapshot.
    reader._current = AggregatedNews(
        items=[], providers_used=[], last_attempt_at=datetime.now(timezone.utc).isoformat()
    )
    monkeypatch.setenv("RISKIT_SERVING_MODE", "prepared")
    monkeypatch.setattr(server, "_prepared_news_reader", reader)
    monkeypatch.setattr(
        server, "build_default_service", lambda **k: pytest.fail("provider created")
    )
    monkeypatch.setattr(server, "_live_player_names", lambda: pytest.fail("request scanned board"))
    request = Request(
        {"type": "http", "query_string": b"", "headers": [], "method": "GET", "path": "/api/news"}
    )
    assert asyncio.run(server.get_news(request)).status_code == 200
    reader._current = None
    assert asyncio.run(server.get_news(request)).status_code == 503


def test_live_league_refresh_reobserves_without_rebuilding_and_invalidates_roster(
    tmp_path, board, monkeypatch
):
    from src.serving import league_views
    from src.api.league_registry import LeagueConfig

    store = ArtifactStore(tmp_path)
    publish_generation(board, store=store)
    cfg = LeagueConfig("main", "Main", "league-1", "same", {}, False)
    overlay = {
        "teams": [{"roster_id": 1, "playerIds": ["1"]}],
        "overlayFetchedAt": datetime.now(timezone.utc).isoformat(),
        "leagueConfig": {
            "scoringSettings": {"rec": 1},
            "rosterPositions": ["WR"],
            "leagueSettings": {"num_teams": 2},
        },
    }
    calls = []
    monkeypatch.setattr(league_views.league_registry, "active_leagues", lambda: [cfg])
    monkeypatch.setattr(league_views.league_registry, "refresh_scoring_snapshot", lambda cfg: None)
    monkeypatch.setattr(league_views.league_registry, "get_league_roster_settings", lambda key: {})
    monkeypatch.setattr(league_views.sleeper_overlay, "fetch_sleeper_overlay", lambda **k: overlay)
    monkeypatch.setattr(
        league_views, "stamp_optimal_lineups", lambda *a, **k: calls.append("solve")
    )
    assert league_views.refresh_league_serving(store)["published"] == ["main"]
    first = store.read_current(league_views.ASSET, "main")
    overlay["overlayFetchedAt"] = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    assert league_views.refresh_league_serving(store)["reobserved"] == ["main"]
    second = store.read_current(league_views.ASSET, "main")
    assert first.generation_id == second.generation_id
    assert first.files == second.files
    assert (
        league_views.load_league_views(second).views["trade"].payload["sleeper"]["overlayFetchedAt"]
        == overlay["overlayFetchedAt"]
    )
    assert calls == ["solve"]
    overlay["teams"][0]["playerIds"] = []
    assert league_views.refresh_league_serving(store)["reobserved"] == []
    assert calls == ["solve", "solve"]


@pytest.mark.parametrize("outcome", ["success", "blocked", "failed"])
def test_web_scrape_adapter_preserves_completion_status(board, monkeypatch, outcome):
    import server
    from src.serving import producer

    calls = []
    monkeypatch.setenv("RISKIT_SERVING_MODE", "legacy")
    monkeypatch.setattr(server, "latest_serving_generation", board)
    monkeypatch.setattr(server, "scrape_run_lock", asyncio.Lock())
    monkeypatch.setattr(server, "_reconcile_orphaned_running_state", lambda: None)
    monkeypatch.setattr(server, "_start_scrape_run", lambda **k: "worker")
    monkeypatch.setattr(server, "_finalize_scrape_run", lambda worker: calls.append("finalized"))
    for name in ("success", "blocked", "failure"):
        monkeypatch.setattr(
            server, "_mark_scrape_" + name, lambda *a, name=name: calls.append(name)
        )

    async def cycle(config, previous, **kwargs):
        assert previous() is board.raw
        return producer.ProducerResult(outcome, board.raw, reason="example")

    monkeypatch.setattr(producer, "run_source_cycle", cycle)
    asyncio.run(server.run_scraper())
    assert calls == ["failure" if outcome == "failed" else outcome, "finalized"]


def test_prepared_lifespan_reloads_without_scraping_or_rebuilding(tmp_path, board, monkeypatch):
    import server
    from src.api import session_store, startup_validation
    from src.serving import producer_status

    store = ArtifactStore(tmp_path)
    publish_generation(board, store=store)
    monkeypatch.setenv("RISKIT_SERVING_MODE", "prepared")
    monkeypatch.setenv("RISKIT_SERVING_DIR", str(tmp_path))
    for name, value in vars(server).copy().items():
        if name.startswith("latest_"):
            monkeypatch.setattr(server, name, value)
    monkeypatch.setattr(server._league_registry, "active_leagues", lambda: [])
    monkeypatch.setattr(startup_validation, "run_all", lambda: [])
    monkeypatch.setattr(session_store, "hydrate", lambda **k: {})
    monkeypatch.setattr(server, "_warmup_public_snapshot", lambda: None)
    monkeypatch.setattr(server, "run_scraper", lambda *a, **k: pytest.fail("web started producer"))
    monkeypatch.setattr(
        server, "_prime_latest_payload", lambda *a, **k: pytest.fail("web rebuilt board")
    )
    verified = []
    monkeypatch.setattr(
        producer_status, "enforce_source_ownership", lambda store: verified.append(1)
    )
    changed = copy.deepcopy(board.contract)
    changed["playersArray"][0]["rankDerivedValue"] = 2000
    next_board = builder.prepare_generation(changed, board.raw, board.source, board.health)

    async def run():
        async with server.lifespan(server.app):
            assert server.latest_serving_generation.generation_id == board.generation_id
            await asyncio.to_thread(publish_generation, next_board, store=store)
            await asyncio.to_thread(server._serving_runtime.reload_if_changed)
            assert server.latest_serving_generation.generation_id == next_board.generation_id
            assert server.latest_contract_data["playersArray"][0]["rankDerivedValue"] == 2000
        assert server._serving_runtime is None
        assert server._prepared_news_reader is None
        assert server._producer_status_reader is None

    asyncio.run(run())
    assert verified == [1]


@pytest.mark.parametrize("other_league", [True, False])
def test_prepared_manual_refresh_queues_correct_producer_without_inline_provider(
    tmp_path, monkeypatch, other_league
):
    import server
    from fastapi import BackgroundTasks
    from src.serving.producer_status import pending_source_refresh, pending_league_refresh

    monkeypatch.setenv("RISKIT_SERVING_MODE", "prepared")
    monkeypatch.setenv("RISKIT_SERVING_DIR", str(tmp_path))
    cfg = SimpleNamespace(key="other" if other_league else "main")
    monkeypatch.setattr(server, "_require_admin_session", lambda request: {})
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda request: cfg)
    monkeypatch.setattr(
        server._league_registry, "get_default_league", lambda: SimpleNamespace(key="main")
    )
    monkeypatch.setattr(
        server._sleeper_overlay, "fetch_sleeper_overlay", lambda **k: pytest.fail("provider called")
    )
    request = Request(
        {
            "type": "http",
            "query_string": b"",
            "headers": [],
            "method": "POST",
            "path": "/api/scrape",
        }
    )
    tasks = BackgroundTasks()
    first = asyncio.run(server.trigger_scrape(request, tasks))
    second = asyncio.run(server.trigger_scrape(request, tasks))
    assert first.status_code == second.status_code == 202
    assert not tasks.tasks
    store = ArtifactStore(tmp_path)
    assert bool(pending_league_refresh(store)) is other_league
    assert bool(pending_source_refresh(store)) is not other_league


def test_league_reader_clears_recovered_error(tmp_path, board, monkeypatch):
    from src.serving import league_views

    cfg = SimpleNamespace(key="main", scoring_profile="same")
    store = ArtifactStore(tmp_path)
    reader = league_views.LeagueServingReader(store, lambda: board)
    monkeypatch.setattr(league_views.league_registry, "active_leagues", lambda: [cfg])
    reader.refresh()
    assert reader.last_error == "MissingArtifact"
    league_views.publish_league_views(prepare_league_views(board, cfg), store, board=board, cfg=cfg)
    reader.refresh()
    assert reader.last_error is None


def test_failed_prime_retains_accepted_objects_and_history(board, monkeypatch):
    import server

    monkeypatch.setattr(server, "latest_serving_generation", board)
    monkeypatch.setattr(server, "latest_contract_data", board.contract)
    monkeypatch.setattr(server, "latest_data", board.raw)
    monkeypatch.setattr(
        server,
        "build_api_data_contract",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("rejected")),
    )
    assert server._prime_latest_payload({"players": {"new": {}}}, is_fresh_scrape=True) is None
    assert server.latest_serving_generation is board
    assert server.latest_contract_data is board.contract
    assert server.latest_data is board.raw


def test_prepared_legacy_array_read_never_calls_overlay(board, monkeypatch):
    import server

    cfg = SimpleNamespace(key="main", scoring_profile="same")
    bundle = prepare_league_views(board, cfg)
    monkeypatch.setenv("RISKIT_SERVING_MODE", "prepared")
    monkeypatch.setattr(server, "latest_serving_generation", board)
    monkeypatch.setattr(server, "_resolve_league_for_request", lambda request: cfg)
    monkeypatch.setattr(
        server, "_league_serving_reader", SimpleNamespace(get=lambda g, k, v: bundle.views[v])
    )
    monkeypatch.setattr(
        server._sleeper_overlay, "fetch_sleeper_overlay", lambda **k: pytest.fail("provider called")
    )
    request = Request(
        {
            "type": "http",
            "query_string": b"view=array",
            "headers": [],
            "method": "GET",
            "path": "/api/data",
        }
    )
    response = asyncio.run(server.get_data(request))
    assert response.status_code == 200
    assert response.body == bundle.views["array"].raw


def test_overlay_prepare_single_flight_includes_conditional_get(monkeypatch):
    import server

    server._OVERLAY_RESPONSE_CACHE.clear()
    server._OVERLAY_ENCODE_LOCKS.clear()
    calls = []

    def prepare():
        calls.append(1)
        return {"sleeper": {"teams": [{"optimalLineup": {"ready": True}}]}}

    request = Request({"type": "http", "headers": [], "method": "GET", "path": "/api/data"})

    async def run():
        responses = await asyncio.gather(
            *[
                server._serialize_overlaid_response(
                    request, {}, {}, ("test",), "one", prepare=prepare
                )
                for _ in range(6)
            ]
        )
        etag = responses[0].headers["etag"]
        conditional = Request({**request.scope, "headers": [(b"if-none-match", etag.encode())]})
        assert (
            await server._serialize_overlaid_response(
                conditional, {}, {}, ("test",), "one", prepare=prepare
            )
        ).status_code == 304
        assert len(calls) == 1
        await server._serialize_overlaid_response(
            request, {}, {}, ("test",), "two", prepare=prepare
        )
        assert len(calls) == 2

    asyncio.run(run())
