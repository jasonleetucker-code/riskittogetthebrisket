"""Exact producer expiry proof and byte-only, coherent league adoption."""

import copy
import gzip
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from src.serving import attestation, builder, league_views as league
from src.serving.artifacts import ArtifactStore, CorruptArtifact
from src.serving.coordinator import prepare_or_reobserve
from src.serving.input_manifest import InputManifest
from src.serving.runtime import PreparedBytes
from src.serving.serialization import publish_generation
from tests.serving import test_serving_pipeline


board = test_serving_pipeline.board


NOW = datetime(2026, 9, 12, 12, tzinfo=timezone.utc)


@pytest.fixture
def signed_store(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    private, public = tmp_path / "issuer.pem", tmp_path / "verifier.pem"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public.write_bytes(
        key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    monkeypatch.setenv(attestation.PRIVATE_KEY_ENV, str(private))
    monkeypatch.setenv(attestation.PUBLIC_KEY_ENV, str(public))
    # Simulate a separately started, configured signing process in this fixture.
    monkeypatch.setattr(attestation, "_PROCESS_RUNTIME", attestation._runtime_identity())
    return ArtifactStore(tmp_path / "store")


@pytest.fixture
def cfg(monkeypatch):
    # Minimal existing lab configuration is deliberately supported.
    config = SimpleNamespace(key="main", scoring_profile="same")
    monkeypatch.setattr(league.league_registry, "active_leagues", lambda: [config])
    monkeypatch.setattr(league.league_registry, "get_league_roster_settings", lambda key: {})
    return config


@pytest.fixture
def ready_board(board):
    contract = copy.deepcopy(board.contract)
    contract["sleeper"].update(
        teams=[{"rosterId": 1, "players": ["1"]}],
        rosterPositions=["WR", "BN"],
        leagueSettings={"num_teams": 12},
        overlayFetchedAt=NOW.isoformat(),
    )
    contract["meta"]["sleeperDataReady"] = True
    return builder.prepare_generation(
        contract, board.raw, {"producedAt": NOW.isoformat()}, board.health
    )


@pytest.fixture
def clock(monkeypatch):
    current = [NOW]

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return current[0] if tz else current[0].replace(tzinfo=None)

    monkeypatch.setattr(league, "datetime", Clock)
    return current


def publish(board, cfg, store, *, inputs=None):
    publish_generation(board, store=store)
    bundle = league.prepare_league_views(board, cfg)
    artifact = league.publish_league_views(
        bundle, store, board=board, cfg=cfg, input_generations=inputs
    )
    return bundle, artifact


def publication_metadata(artifact):
    claims = json.loads(artifact.files[attestation.CERTIFICATE_FILE])["claims"]["metadata"]
    return {
        **{
            key: claims[key]
            for key in ("modelVersion", "configHash", "inputGenerations", "leagueBinding")
        },
        "sourceAsOf": artifact.manifest["sourceAsOf"],
    }


def byte_board(board):
    return replace(
        board,
        views={
            name: PreparedBytes(view.raw, view.gzip, view.etag, name, view.metadata)
            if name in {"rankings", "trade", "catalog"}
            else view
            for name, view in board.views.items()
        },
    )


def fail_work(*args, **kwargs):
    pytest.fail("web adoption or expiry performed producer semantic/encoding work")


def test_all_eight_views_preserve_ready_stale_unknown_wire_parity(
    ready_board, cfg, signed_store, monkeypatch
):
    original, artifact = publish(ready_board, cfg, signed_store)
    expected = {
        "ready": original,
        "stale": league.expire_context(original, now=NOW + timedelta(minutes=31)),
        "unknown": league.expire_context(original, now=NOW - timedelta(minutes=6)),
    }
    assert len(artifact.files) == 34  # ready raw+gzip, expired gzip only, index, certificate
    monkeypatch.delenv(attestation.PRIVATE_KEY_ENV)
    decoded = []
    original_loads = json.loads

    def loads(body, *args, **kwargs):
        value = original_loads(body, *args, **kwargs)
        # Certificate and small serving index are permitted; payload graphs are not.
        assert "playersArray" not in value and "players" not in value
        decoded.append(value)
        return value

    with monkeypatch.context() as web:
        web.setattr(league.json, "loads", loads)
        web.setattr(league, "prepare_payload", fail_work)
        web.setattr(league, "validate_league_views", fail_work)
        web.setattr(league, "stamp_optimal_lineups", fail_work)
        adopted = league.load_web_league_views(artifact, byte_board(ready_board), cfg)
        for state, now in (
            ("ready", NOW),
            ("stale", NOW + timedelta(minutes=31)),
            ("unknown", NOW - timedelta(minutes=6)),
        ):
            selected = league.expire_context(adopted, now=now)
            for name in league.VIEWS:
                actual, old = selected.views[name], expected[state].views[name]
                assert isinstance(actual, PreparedBytes) and not hasattr(actual, "payload")
                assert actual is adopted.variants[state][name]
                assert (actual.raw, actual.gzip, actual.etag) == (old.raw, old.gzip, old.etag)
                assert actual.payload_view == name and dict(actual.metadata) == old.metadata
                assert gzip.decompress(actual.gzip) == actual.raw
        assert league.expire_context(adopted, now=NOW) is adopted
    assert len(decoded) == 2
    with pytest.raises(TypeError):
        adopted.views["trade"].metadata["sleeperDataReady"] = False


@pytest.mark.parametrize("stamp", [None, "bad", "2026-09-12T12:00:00"])
def test_unknown_age_is_never_signed_as_known(ready_board, cfg, signed_store, stamp):
    publish_generation(ready_board, store=signed_store)
    bundle = league.prepare_league_views(ready_board, cfg)
    context = {**bundle.views["trade"].payload["sleeper"], "overlayFetchedAt": stamp}
    bundle = replace(
        bundle,
        views={
            name: builder.prepare_payload(
                {
                    **view.payload,
                    "sleeper": context,
                    "meta": {**view.metadata, "leagueSourceAsOf": stamp},
                }
            )
            for name, view in bundle.views.items()
        },
    )
    artifact = league.publish_league_views(bundle, signed_store, board=ready_board, cfg=cfg)
    assert artifact.observation["claims"]["sourceAsOf"] is None
    adopted = league.load_web_league_views(artifact, ready_board, cfg)
    selected = league.expire_context(adopted, now=NOW)
    for view in selected.views.values():
        payload = json.loads(view.raw)
        assert payload["sleeper"] is None
        assert payload["meta"]["leagueSourceAsOf"] is None
        assert payload["meta"]["leagueFreshnessState"] == "unknown"
        assert payload["meta"]["sleeperDataReady"] is False
    assert json.loads(adopted.variants["ready"]["trade"].raw)["sleeper"]["overlayFetchedAt"] is None


@pytest.mark.parametrize(
    "state,change",
    [
        ("ready", "value"),
        ("stale", "value"),
        ("unknown", "value"),
        ("stale", "source"),
        ("unknown", "readiness"),
    ],
)
def test_producer_rejects_self_consistent_bad_final_variant(
    ready_board, cfg, signed_store, monkeypatch, state, change
):
    original = league._final_variants

    def altered(bundle):
        final = original(bundle)
        payload = copy.deepcopy(final.variants[state]["rankings"].payload)
        if change == "value":
            payload["playersArray"][0]["rankDerivedValue"] = 9876
        elif change == "source":
            payload["meta"]["sleeperSource"] = "fabricated-source"
        else:
            payload["meta"]["sleeperDataReady"] = True
        variants = {name: dict(views) for name, views in final.variants.items()}
        variants[state]["rankings"] = builder.prepare_payload(payload)
        return replace(final, views=variants["ready"], variants=variants)

    monkeypatch.setattr(league, "_final_variants", altered)
    with pytest.raises(CorruptArtifact):
        publish(ready_board, cfg, signed_store)
    assert not (signed_store.root / league.ASSET / cfg.key / "current.json").exists()


@pytest.mark.parametrize("change", ["bytes", "etag", "parent", "configuration", "unsigned"])
def test_adoption_rejects_tampering_and_wrong_binding(ready_board, cfg, signed_store, change):
    _, accepted = publish(ready_board, cfg, signed_store)
    files = dict(accepted.files)
    metadata = publication_metadata(accepted)
    candidate_board, candidate_cfg = ready_board, cfg
    if change == "bytes":
        files["stale/rankings.gz"] = gzip.compress(b"{}")
    elif change == "etag":
        index = json.loads(files["index.json"])
        index["variants"]["ready"]["rankings"]["etag"] = "forged"
        files["index.json"] = builder.json_bytes(index)
    elif change == "parent":
        candidate_board = replace(ready_board, generation_id="different-parent")
    elif change == "configuration":
        candidate_cfg = SimpleNamespace(**vars(cfg), idp_enabled=True)
    else:
        files.pop(attestation.CERTIFICATE_FILE)
    forged = replace(accepted, files=files)
    if change in {"bytes", "etag", "unsigned"}:
        # Ordinary artifact checksums cannot authorize a rehashed semantic change.
        forged, _ = signed_store._candidate(league.ASSET, cfg.key, files, metadata)
    with pytest.raises(CorruptArtifact):
        league.load_web_league_views(forged, candidate_board, candidate_cfg)


def test_reader_keeps_coherent_lkg_until_matching_parent_then_releases_it(
    ready_board, cfg, signed_store, monkeypatch, clock
):
    publish(ready_board, cfg, signed_store)
    boards = [byte_board(ready_board)]
    reader = league.LeagueServingReader(signed_store, lambda: boards[0], lightweight=True)
    reader.refresh()
    captured = reader.capture(cfg.key)
    changed = copy.deepcopy(ready_board.contract)
    changed["playersArray"][0]["rankDerivedValue"] = 2000
    newer = builder.prepare_generation(
        changed, ready_board.raw, ready_board.source, ready_board.health
    )
    boards[0] = byte_board(newer)
    clock[0] += timedelta(minutes=31)
    with monkeypatch.context() as web:
        web.setattr(league, "prepare_payload", fail_work)
        web.setattr(league, "prepare_league_views", fail_work)
        reader.refresh()
        held = reader.capture(cfg.key)
        assert held[0] is captured[0]
        assert held[1].views["rankings"] is captured[1].variants["stale"]["rankings"]
        assert reader.last_error == "CorruptArtifact"
    publish(newer, cfg, signed_store)
    reader.refresh()
    assert reader.capture(cfg.key)[0] is boards[0]
    assert reader.capture(cfg.key)[1].board_generation == newer.generation_id


def test_corrupt_candidate_retains_accepted_bytes(
    ready_board, cfg, signed_store, monkeypatch, clock
):
    _, artifact = publish(ready_board, cfg, signed_store)
    reader = league.LeagueServingReader(signed_store, lambda: ready_board, lightweight=True)
    reader.refresh()
    original = reader.capture(cfg.key)
    monkeypatch.setattr(signed_store, "current_version", lambda *a: (1, 2))
    monkeypatch.setattr(
        signed_store,
        "read_current",
        lambda *a: replace(artifact, files={**artifact.files, "extra": b"bad"}),
    )
    monkeypatch.setattr(league, "prepare_payload", fail_work)
    reader.refresh()
    assert reader.capture(cfg.key) == original
    assert reader.last_error == "AttestationError"


def test_known_scoring_change_withdraws_old_same_league_capture(
    ready_board, cfg, signed_store, monkeypatch, clock
):
    publish(ready_board, cfg, signed_store)
    reader = league.LeagueServingReader(signed_store, lambda: ready_board, lightweight=True)
    reader.refresh()
    assert reader.capture(cfg.key)
    monkeypatch.setattr(
        league.league_registry, "scoring_fingerprint_for_league", lambda cfg: "changed"
    )
    reader.refresh()
    assert reader.capture(cfg.key) is None
    with pytest.raises(CorruptArtifact, match="scoring changed"):
        publish(ready_board, cfg, signed_store)


def test_cold_byte_only_board_fallback_preserves_full_player_universe(
    ready_board, cfg, signed_store, clock
):
    web_board = byte_board(ready_board)
    reader = league.LeagueServingReader(signed_store, lambda: web_board, lightweight=True)
    reader.refresh()
    held_board, bundle = reader.capture(cfg.key)
    assert held_board is web_board
    canonical = league.prepare_league_views(ready_board, cfg)
    for name in league.VIEWS:
        assert bundle.views[name].raw == canonical.views[name].raw
        assert isinstance(bundle.views[name], PreparedBytes)
    assert len(json.loads(bundle.views["rankings"].raw)["playersArray"]) == 2
    assert reader.last_error == "MissingArtifact"


def test_identical_reobservation_restores_expired_context_without_lineup_rebuild(
    ready_board, cfg, signed_store, monkeypatch, clock
):
    manifest = InputManifest(
        league.ASSET, {"board": ready_board.generation_id, "roster": "same"}, True
    )
    _, first = publish(ready_board, cfg, signed_store, inputs=manifest.input_generations)
    reader = league.LeagueServingReader(signed_store, lambda: ready_board, lightweight=True)
    reader.refresh()
    clock[0] += timedelta(minutes=31)
    reader.refresh()
    old = reader.capture(cfg.key)[1]
    assert old.views["trade"].metadata["sleeperDataReady"] is False
    stamp = clock[0].isoformat()
    monkeypatch.setattr(league, "stamp_optimal_lineups", fail_work)
    result = prepare_or_reobserve(
        store=signed_store,
        asset=league.ASSET,
        key=cfg.key,
        manifest=manifest,
        build=fail_work,
        publish=fail_work,
        validate=lambda artifact: league._validate_final_bundle(
            league.load_league_views(artifact), ready_board, cfg
        ),
        source_as_of=stamp,
        reobserve=lambda artifact, inputs, source: league.reobserve_league_views(
            artifact,
            signed_store,
            board=ready_board,
            cfg=cfg,
            input_generations=inputs,
            source_as_of=source,
        ),
    )
    assert result.rebuilt is False
    assert result.artifact.generation_id != first.generation_id
    assert result.artifact.observation["claims"]["sourceAsOf"] == stamp
    assert attestation.verify_artifact(result.artifact)
    with monkeypatch.context() as web:
        web.setattr(league, "prepare_payload", fail_work)
        reader.refresh()
    adopted = reader.capture(cfg.key)[1]
    for name in league.VIEWS:
        payload = json.loads(adopted.views[name].raw)
        assert payload["sleeper"] == {**ready_board.contract["sleeper"], "overlayFetchedAt": stamp}
        assert payload["meta"]["leagueSourceAsOf"] == stamp
        assert payload["meta"]["sleeperDataReady"] is True
        assert "leagueFreshnessState" not in payload["meta"]
    assert old.views["trade"].metadata["sleeperDataReady"] is False


def test_failed_reobservation_retains_pointer(ready_board, cfg, signed_store):
    manifest = InputManifest(league.ASSET, {"board": ready_board.generation_id}, True)
    _, accepted = publish(ready_board, cfg, signed_store, inputs=manifest.input_generations)

    def failed(*args):
        raise ValueError("injected producer restamp failure")

    with pytest.raises(ValueError, match="restamp failure"):
        prepare_or_reobserve(
            store=signed_store,
            asset=league.ASSET,
            key=cfg.key,
            manifest=manifest,
            build=fail_work,
            publish=fail_work,
            validate=attestation.verify_artifact,
            source_as_of=(NOW + timedelta(minutes=10)).isoformat(),
            reobserve=failed,
        )
    assert signed_store.read_current(league.ASSET, cfg.key).generation_id == accepted.generation_id


@pytest.mark.parametrize("change", ["value", "source", "configuration"])
def test_strict_reader_validates_schema2_expiry_when_attestation_disabled(
    ready_board, cfg, signed_store, monkeypatch, clock, change
):
    _, accepted = publish(ready_board, cfg, signed_store)
    monkeypatch.delenv(attestation.PRIVATE_KEY_ENV)
    monkeypatch.delenv(attestation.PUBLIC_KEY_ENV)
    reader = league.LeagueServingReader(signed_store, lambda: ready_board)
    reader.refresh()
    original = reader.capture(cfg.key)[1]
    assert original.variants is not None
    files = dict(accepted.files)
    metadata = publication_metadata(accepted)
    files.pop(attestation.CERTIFICATE_FILE)
    index = json.loads(files["index.json"])
    payload = json.loads(gzip.decompress(files["stale/rankings.gz"]))
    if change == "value":
        payload["playersArray"][0]["rankDerivedValue"] = 9876
    elif change == "source":
        payload["meta"]["sleeperSource"] = "fabricated-source"
    altered = builder.prepare_payload(payload)
    files["stale/rankings.gz"] = altered.gzip
    index["variants"]["stale"]["rankings"] = {
        "etag": altered.etag,
        "metadata": altered.metadata,
    }
    if change == "configuration":
        index["binding"]["leagueConfiguration"] = "old-configuration"
        metadata["leagueBinding"] = index["binding"]
    files["index.json"] = builder.json_bytes(index)
    signed_store.publish(league.ASSET, cfg.key, files, metadata)
    clock[0] += timedelta(minutes=31)
    reader.refresh()
    actual = reader.capture(cfg.key)[1]
    assert actual.views["rankings"] is original.variants["stale"]["rankings"]
    assert reader.last_error == "CorruptArtifact"
