"""Retention preserves accepted reads, rollback floors, proofs and dependencies."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.serving import artifacts as module
from src.serving.artifacts import (
    ArtifactStore,
    RetentionCapacityError,
    RetentionPolicy,
    RejectedCandidate,
    UnsafeArtifactPath,
)


@pytest.fixture
def store(tmp_path):
    return ArtifactStore(tmp_path, retention_policy=RetentionPolicy(min_free_bytes=0))


def metadata(**extra):
    return {"modelVersion": "test", "inputGenerations": {}, "configHash": "test", **extra}


@pytest.mark.parametrize("dependency", ["board", "explicit", "news"])
def test_candidate_missing_dependency_rejects_before_pointer_change_or_prune(store, dependency):
    asset = "news-serving" if dependency == "news" else "dependent"
    old = store.publish(asset, "main", {"value": b"old"}, metadata())
    pointer = store.root / asset / "main/current.json"
    before = pointer.read_bytes()
    extra = {"inputGenerations": {"canonical" if dependency == "news" else "board": "f" * 64}}
    if dependency == "explicit":
        extra = {
            "artifactReferences": [{"asset": "board", "key": "main", "generationId": "f" * 64}]
        }
    with pytest.raises(RejectedCandidate):
        store.publish(asset, "main", {"value": b"new"}, metadata(**extra))
    assert pointer.read_bytes() == before
    assert store.read_current(asset, "main") == old
    report = store.read_retention_report()
    assert report["candidateDependencyBlocked"] and report["deletedCount"] == 0
    assert not report["capacityBlocked"]


@pytest.mark.parametrize("failure", ["ambiguous", "transitive", "corrupt", "unrelated_corrupt"])
def test_candidate_dependency_closure_fails_closed(store, failure):
    old = store.publish("dependent", "main", {"value": b"old"}, metadata())
    parent = store.publish("board", "main", {"value": b"parent"}, metadata())
    version = parent.generation_id
    if failure == "ambiguous":
        version = "a" * 64
        for key in ("one", "two"):
            store.publish(
                "board", key, {"value": key.encode()}, metadata(logicalGeneration=version)
            )
    elif failure == "transitive":
        # Represent an older accepted artifact created before admission validation.
        candidate, meta = store._candidate(
            "board", "legacy", {"value": b"legacy"}, metadata(inputGenerations={"board": "f" * 64})
        )
        with store._locked():
            parent = store._publish_unlocked(candidate, meta)
        version = parent.generation_id
    elif failure == "corrupt":
        (directory(store, parent) / "files/value").write_bytes(b"corrupt")
    else:
        unrelated = store.publish("other", "main", {"value": b"old"}, metadata())
        (directory(store, unrelated) / "files/value").write_bytes(b"corrupt")
        version = "f" * 64
    pointer = store.root / "dependent/main/current.json"
    before = pointer.read_bytes()
    with pytest.raises(RejectedCandidate):
        store.publish(
            "dependent", "main", {"value": b"new"}, metadata(inputGenerations={"board": version})
        )
    assert pointer.read_bytes() == before
    assert store.read_current("dependent", "main") == old
    report = store.read_retention_report()
    assert report["candidateDependencyBlocked"] and report["deletedCount"] == 0


def test_news_publisher_rejects_captured_parent_pruned_during_provider_work(store):
    from src.news.prepared import refresh_prepared_news
    from src.news.service import NewsService

    class Provider:
        name = "fixture"
        label = "Fixture"

        def fetch(self, **kwargs):
            return []

    now = [datetime.now(timezone.utc).timestamp()]
    service = NewsService([Provider()], clock=lambda: now[0], cache_ttl_s=1)

    def board(value):
        return store.publish("canonical-serving", "default", {"fixture": value}, metadata())

    def news(parent):
        return refresh_prepared_news(
            store, service, player_names=[], player_meta={}, input_generation=parent.generation_id
        )

    old = news(board(b"initial"))
    captured = board(b"captured")
    for value in (b"next1", b"next2", b"next3", b"next4"):
        board(value)
    store.retention(apply=True, now=datetime.now(timezone.utc) + timedelta(hours=72))
    assert not directory(store, captured).exists()
    pointer = store.root / "news-serving/public/current.json"
    before = pointer.read_bytes()
    now[0] += 5
    with pytest.raises(RejectedCandidate):
        news(captured)
    assert pointer.read_bytes() == before
    assert store.read_current("news-serving", "public") == old
    assert store.read_retention_report()["candidateDependencyBlocked"]


@pytest.mark.parametrize("parent_state", ["valid", "missing", "corrupt_pointer", "corrupt_bytes"])
def test_dependent_repair_can_replace_only_its_own_bad_pointer(store, parent_state):
    parent = store.publish("board", "main", {"value": b"parent"}, metadata())
    old = store.publish(
        "dependent",
        "main",
        {"value": b"old"},
        metadata(inputGenerations={"board": parent.generation_id}),
    )
    pointer = store.root / "dependent/main/current.json"
    pointer.write_text("bad JSON", encoding="utf-8")
    version = parent.generation_id
    if parent_state == "missing":
        version = "f" * 64
    elif parent_state == "corrupt_pointer":
        (store.root / "board/main/current.json").write_text("bad JSON", encoding="utf-8")
    elif parent_state == "corrupt_bytes":
        (directory(store, parent) / "files/value").write_bytes(b"bad")
    before = pointer.read_bytes()
    if parent_state == "valid":
        new = store.publish(
            "dependent",
            "main",
            {"value": b"new"},
            metadata(inputGenerations={"board": version}),
        )
        assert store.read_current("dependent", "main") == new
        assert pointer.read_bytes() != before
    else:
        with pytest.raises(RejectedCandidate):
            store.publish(
                "dependent",
                "main",
                {"value": b"new"},
                metadata(inputGenerations={"board": version}),
            )
        assert pointer.read_bytes() == before
    report = store.read_retention_report()
    assert report["blocked"] and report["deletedCount"] == 0
    assert report["candidateDependencyBlocked"] is (parent_state != "valid")
    assert directory(store, old).exists() and directory(store, parent).exists()


@pytest.mark.parametrize(
    "case", ["valid", "physical", "alias", "transitive", "manifest", "capacity"]
)
def test_replacement_quarantine_never_hides_required_dependency(store, case):
    alias = "a" * 64
    parent = store.publish("board", "main", {"value": b"parent"}, metadata(logicalGeneration=alias))
    old = store.publish(
        "dependent",
        "main",
        {"value": b"old"},
        metadata(inputGenerations={"board": parent.generation_id}, logicalGeneration=alias),
    )
    middle = store.publish(
        "middle",
        "main",
        {"value": b"middle"},
        metadata(inputGenerations={"board": old.generation_id}),
    )
    old_path = directory(store, old)
    (old_path / "files/value").write_bytes(b"bad")
    if case == "manifest":
        (old_path / "manifest.json").write_text('{"schemaVersion":1}', encoding="utf-8")
    pointer = store.root / "dependent/main/current.json"
    before = pointer.read_bytes()
    version = {
        "physical": old.generation_id,
        "alias": alias,
        "transitive": middle.generation_id,
    }.get(case, parent.generation_id)
    publisher = (
        store
        if case != "capacity"
        else ArtifactStore(
            store.root, retention_policy=RetentionPolicy(max_bytes=1, min_free_bytes=0)
        )
    )
    if case == "valid":
        accepted = publisher.publish(
            "dependent", "main", {"value": b"new"}, metadata(inputGenerations={"board": version})
        )
        assert store.read_current("dependent", "main") == accepted
    else:
        error = RetentionCapacityError if case == "capacity" else RejectedCandidate
        with pytest.raises(error):
            publisher.publish(
                "dependent",
                "main",
                {"value": b"new"},
                metadata(inputGenerations={"board": version}),
            )
        assert pointer.read_bytes() == before
    report = store.read_retention_report()
    assert report["blocked"] and report["deletedCount"] == 0
    assert (old_path / "files/value").read_bytes() == b"bad"
    assert directory(store, parent).exists() and directory(store, middle).exists()


def test_unknown_quarantined_canonical_alias_refuses_dependent_repair(store):
    parent = store.publish("board", "main", {"value": b"parent"}, metadata())
    old = store.publish(
        "canonical-serving",
        "default",
        {"index.json": b'{"generation":"' + b"a" * 64 + b'"}'},
        metadata(),
    )
    (directory(store, old) / "files/index.json").write_bytes(b"{}")
    pointer = store.root / "canonical-serving/default/current.json"
    before = pointer.read_bytes()
    with pytest.raises(RejectedCandidate):
        store.publish(
            "canonical-serving",
            "default",
            {"value": b"new"},
            metadata(inputGenerations={"board": parent.generation_id}),
        )
    assert pointer.read_bytes() == before
    report = store.read_retention_report()
    assert report["candidateDependencyBlocked"] and report["deletedCount"] == 0


def publish_many(store, monkeypatch, count=6, *, asset="board", key="main", size=1000):
    start = datetime.now(timezone.utc)
    result = []
    for index in range(count):
        monkeypatch.setattr(
            module, "_now", lambda index=index: (start + timedelta(seconds=index)).isoformat()
        )
        result.append(store.publish(asset, key, {"value": bytes([index]) * size}, metadata()))
    return result, start + timedelta(hours=72)


def directory(store, generation):
    return store.root / generation.asset / generation.key / "generations" / generation.generation_id


def test_48_hour_target_and_three_accepted_floor_with_read_only_dry_run(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert store.retention(now=future - timedelta(hours=25))["plannedDeleteCount"] == 0
    preview = store.retention(now=future)
    assert preview["plannedDeleteCount"] == 3 and preview["deletedCount"] == 0
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before
    applied = store.retention(apply=True, now=future)
    assert applied["generationCount"] == 3 and applied["deletedCount"] == 3
    assert all(
        directory(store, item).exists() is (item in generations[-3:]) for item in generations
    )
    assert store.read_current("board", "main").generation_id == generations[-1].generation_id


def test_recent_generations_can_be_released_for_budget_without_breaking_floor(store, monkeypatch):
    generations, _ = publish_many(store, monkeypatch, count=5, size=20000)
    bounded = ArtifactStore(
        store.root, retention_policy=RetentionPolicy(max_bytes=70000, min_free_bytes=0)
    )
    report = bounded.retention(apply=True)
    assert not report["capacityBlocked"]
    assert report["deletedCount"] == 2
    assert report["generationCount"] == 3
    assert report["shortenedRollbackWindow"] is True
    assert module._tree_bytes(store.root) <= 70000
    assert directory(store, generations[-1]).exists()


def test_publish_rejects_capacity_before_pointer_change_and_records_failure(store):
    first = store.publish("board", "main", {"value": b"old"}, metadata())
    pointer = store.root / "board/main/current.json"
    before = pointer.read_bytes()
    bounded = ArtifactStore(
        store.root, retention_policy=RetentionPolicy(max_bytes=1, min_free_bytes=0)
    )
    with pytest.raises(RetentionCapacityError):
        bounded.publish("board", "main", {"value": b"new"}, metadata())
    assert pointer.read_bytes() == before
    assert store.read_current("board", "main") == first
    report = bounded.read_retention_report()
    assert report["capacityFailureCount"] == 1
    assert report["lastCapacityFailureAt"]


def test_publication_automatically_prunes_under_shared_configured_budget(store, monkeypatch):
    generations, _ = publish_many(store, monkeypatch, count=5, size=20000)
    monkeypatch.setenv("RISKIT_SERVING_MAX_BYTES", "70000")
    monkeypatch.setenv("RISKIT_SERVING_MIN_FREE_BYTES", "0")
    bounded = ArtifactStore(store.root)
    accepted = bounded.publish("board", "main", {"value": b"new" * 100}, metadata())
    assert bounded.read_current("board", "main") == accepted
    assert bounded.read_retention_report()["deletedCount"] == 2
    assert bounded.read_retention_report()["shortenedRollbackWindow"]
    assert all(directory(store, generation).exists() for generation in generations[-3:])
    assert bounded._owned_bytes() <= 70000


def test_diagnostic_failure_after_acceptance_does_not_report_rejected_candidate(store, monkeypatch):
    store.publish("board", "main", {"value": b"old"}, metadata())
    monkeypatch.setattr(
        store,
        "_save_retention_report",
        lambda *a, **k: (_ for _ in ()).throw(OSError("report unavailable")),
    )
    accepted = store.publish("board", "main", {"value": b"new"}, metadata())
    assert store.read_current("board", "main") == accepted


@pytest.mark.parametrize("name", ["RISKIT_SERVING_MAX_BYTES", "RISKIT_SERVING_MIN_FREE_BYTES"])
@pytest.mark.parametrize("value", ["-1", "unknown", "1.5"])
def test_invalid_environment_policy_refuses_construction(tmp_path, monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path)


def test_free_space_floor_preserves_existing_source_setting(store, monkeypatch):
    store.publish("board", "main", {"value": b"old"}, metadata())
    monkeypatch.setenv("DISK_SPACE_MIN_MB", "20")
    free = 20 * 1024**2
    monkeypatch.setattr(
        module.shutil, "disk_usage", lambda _: SimpleNamespace(total=1000 * 1024**2, free=free)
    )
    bounded = ArtifactStore(store.root)
    with pytest.raises(RetentionCapacityError):
        bounded.publish("board", "main", {"value": b"new"}, metadata())
    assert bounded.read_retention_report()["minFreeBytes"] == free


def test_pins_and_cross_partition_dependencies_protect_old_generations(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    store.pin("board", "main", generations[0].generation_id, "rollback")
    store.publish(
        "league",
        "one",
        {"view": b"prepared"},
        metadata(inputGenerations={"board": generations[1].generation_id}),
    )
    report = store.retention(apply=True, now=future)
    assert report["deletedCount"] == 1
    assert directory(store, generations[0]).exists()
    assert directory(store, generations[1]).exists()
    store.unpin("rollback")
    assert store.retention(apply=True, now=future)["deletedCount"] == 1
    assert not directory(store, generations[0]).exists()


def test_ownership_proof_keeps_its_historical_canonical_artifact(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch, asset="canonical-serving")
    store.publish(
        "source-ownership",
        "standalone",
        {"receipt.json": json.dumps({"acceptedGeneration": generations[0].generation_id}).encode()},
        metadata(),
    )
    report = store.retention(apply=True, now=future)
    assert not report["blocked"]
    assert directory(store, generations[0]).exists()
    assert report["deletedCount"] == 2


def test_source_receipt_reference_is_protected(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    (store.root / "source-producer-receipt.json").write_text(
        json.dumps({"schemaVersion": 1, "acceptedGeneration": generations[0].generation_id})
    )
    assert store.retention(apply=True, now=future)["deletedCount"] == 2
    assert directory(store, generations[0]).exists()


def test_missing_prepared_news_canonical_dependency_blocks_all_pruning(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch, asset="canonical-serving", key="default")
    store.publish(
        "news-serving",
        "public",
        {"news.json": b"{}"},
        metadata(inputGenerations={"canonical": generations[0].generation_id}),
    )
    # Reversibly simulate external loss of an old canonical directory while
    # current.json still identifies the latest valid board.
    directory(store, generations[0]).rename(store.root / "lost-generation")
    report = store.retention(apply=True, now=future)
    assert report["blocked"] and report["error"] == "CorruptArtifact"
    assert report["deletedCount"] == 0
    assert all(directory(store, item).exists() for item in generations[1:])


def test_external_input_named_canonical_does_not_require_a_local_artifact(store, monkeypatch):
    _, future = publish_many(store, monkeypatch)
    store.publish(
        "external-summary",
        "public",
        {"summary.json": b"{}"},
        metadata(inputGenerations={"canonical": "external-source-version"}),
    )
    report = store.retention(apply=True, now=future)
    assert not report["blocked"] and report["deletedCount"] == 3


def test_explicit_reference_and_unambiguous_logical_generation_are_retained(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    logical = hashlib.sha256(b"board-json").hexdigest()
    aliased = store.publish(
        "canonical-serving",
        "default",
        {"index.json": json.dumps({"generation": logical}).encode()},
        metadata(),
    )
    store.publish(
        "league",
        "main",
        {"value": b"league"},
        metadata(
            inputGenerations={"board": logical},
            artifactReferences=[
                {"asset": "board", "key": "main", "generationId": generations[0].generation_id}
            ],
        ),
    )
    assert not store.retention(apply=True, now=future)["blocked"]
    assert directory(store, aliased).exists()
    assert directory(store, generations[0]).exists()


def test_ambiguous_logical_dependency_fails_closed_without_deletion(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    logical = hashlib.sha256(b"board-json").hexdigest()
    for version in range(2):
        store.publish(
            "canonical-serving",
            "default",
            {"index.json": json.dumps({"generation": logical}).encode()},
            metadata(configHash=str(version)),
        )
    with pytest.raises(RejectedCandidate):
        store.publish(
            "league", "main", {"value": b"league"}, metadata(inputGenerations={"board": logical})
        )
    # Historical invalid state still prevents maintenance deletion.
    candidate, meta = store._candidate(
        "league", "main", {"value": b"league"}, metadata(inputGenerations={"board": logical})
    )
    with store._locked():
        store._publish_unlocked(candidate, meta)
    report = store.retention(apply=True, now=future)
    assert report["blocked"] and report["deletedCount"] == 0
    assert all(directory(store, item).exists() for item in generations)


def test_equivalent_byte_verified_logical_variants_are_conservatively_protected(store, monkeypatch):
    _, future = publish_many(store, monkeypatch)
    raw = b'{"canonical":"same"}'
    logical = hashlib.sha256(raw).hexdigest()
    variants = []
    for version in range(2):
        variants.append(
            store.publish(
                "canonical-serving",
                "default",
                {
                    "index.json": json.dumps({"generation": logical}).encode(),
                    "views/full.json": raw,
                },
                metadata(configHash=str(version)),
            )
        )
    store.publish(
        "league", "main", {"value": b"league"}, metadata(inputGenerations={"board": logical})
    )
    report = store.retention(apply=True, now=future)
    assert not report["blocked"]
    assert all(directory(store, item).exists() for item in variants)


def test_unrelated_labs_and_caches_are_not_budgeted_or_pruned(store, monkeypatch):
    _, future = publish_many(store, monkeypatch)
    before = store._owned_bytes()
    lab = store.root / "lab/node-runtime"
    lab.mkdir(parents=True)
    unrelated = lab / "binary"
    unrelated.write_bytes(b"cache" * 10000)
    (store.root / "unrelated-source-archive").write_bytes(b"archive" * 10000)
    assert store._owned_bytes() == before
    report = store.retention(apply=True, now=future)
    assert not report["blocked"] and report["deletedCount"] == 3
    assert unrelated.exists()


def test_unrecorded_legacy_generations_have_unknown_protected_age(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    (store.root / "board/main/accepted.json").unlink()
    report = store.retention(apply=True, now=future)
    assert report["unknownAcceptanceCount"] == 6
    assert report["oldestRetainedAt"] is None
    assert report["deletedCount"] == 0
    assert all(directory(store, item).exists() for item in generations)


def test_unchanged_refresh_preserves_acceptance_age_and_rollback_transition_renews_it(
    store, monkeypatch
):
    generations, future = publish_many(store, monkeypatch, count=4)
    path = store.root / "board/main/accepted.json"
    accepted = json.loads(path.read_bytes())["generations"]
    last = generations[-1]
    monkeypatch.setattr(module, "_now", lambda: future.isoformat())
    store.publish(last.asset, last.key, last.files, metadata(sourceAsOf=future.isoformat()))
    assert (
        json.loads(path.read_bytes())["generations"][last.generation_id]
        == accepted[last.generation_id]
    )
    old = generations[0]
    store.publish(old.asset, old.key, old.files, metadata())
    assert json.loads(path.read_bytes())["generations"][old.generation_id] == future.isoformat()


def test_impossible_budget_deletes_nothing_even_when_old_candidates_exist(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    bounded = ArtifactStore(
        store.root, retention_policy=RetentionPolicy(max_bytes=1, min_free_bytes=0)
    )
    report = bounded.retention(apply=True, now=future)
    assert report["capacityBlocked"] and report["deletedCount"] == 0
    assert all(directory(store, item).exists() for item in generations)


@pytest.mark.parametrize("damage", ["file", "manifest", "pointer", "pins", "receipt"])
def test_corruption_authorizes_no_deletion(store, monkeypatch, damage):
    generations, future = publish_many(store, monkeypatch)
    path = {
        "file": directory(store, generations[0]) / "files/value",
        "manifest": directory(store, generations[0]) / "manifest.json",
        "pointer": store.root / "board/main/current.json",
        "pins": store.root / "retention-pins.json",
        "receipt": store.root / "source-producer-receipt.json",
    }[damage]
    path.write_bytes(b"broken")
    report = store.retention(apply=True, now=future)
    assert report["blocked"] and report["deletedCount"] == 0
    assert all(directory(store, item).exists() for item in generations)


def test_corrupt_old_generation_can_be_repaired_without_unsafe_pruning(store):
    old = store.publish("proof", "main", {"value": b"old"}, metadata())
    (directory(store, old) / "files/value").write_bytes(b"bad")
    repaired = store.publish("proof", "main", {"value": b"new"}, metadata())
    assert store.read_current("proof", "main") == repaired
    assert directory(store, old).exists()
    assert store.read_retention_report()["blocked"]


def test_reader_and_pruner_share_lease_without_recursive_read_deadlock(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = store._read_generation

    def slow_read(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "_read_generation", slow_read)
    with ThreadPoolExecutor(max_workers=2) as pool:
        read = pool.submit(store.read_current, "board", "main")
        assert entered.wait(5)
        prune = pool.submit(store.retention, apply=True, now=future)
        assert not prune.done()
        release.set()
        captured = read.result(timeout=5)
        assert prune.result(timeout=5)["deletedCount"] == 3
    assert captured.files == generations[-1].files
    store.publish(
        "board",
        "main",
        {"value": b"validator-read"},
        metadata(),
        validator=lambda _: store.read_current("board", "main"),
    )


def test_failed_candidate_publication_keeps_three_previously_accepted_generations(
    store, monkeypatch
):
    generations, _ = publish_many(store, monkeypatch, count=4, size=20000)
    bounded = ArtifactStore(
        store.root,
        retention_policy=RetentionPolicy(max_bytes=100000, min_free_bytes=0, keep_seconds=0),
    )
    original = module.os.replace

    def fail_pointer(source, destination):
        if Path(destination).name == "current.json":
            raise OSError("publication failed")
        return original(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_pointer)
    with pytest.raises(OSError):
        bounded.publish("board", "main", {"value": b"candidate"}, metadata())
    assert store.read_current("board", "main").generation_id == generations[-1].generation_id
    assert all(directory(store, generation).exists() for generation in generations[-3:])


def test_repeated_failed_pointer_writes_never_count_as_accepted_history(store, monkeypatch):
    generations, future = publish_many(store, monkeypatch, count=4)
    original = module.os.replace

    def fail_pointer(source, destination):
        if Path(destination).name == "current.json":
            raise OSError("pointer rejected")
        return original(source, destination)

    monkeypatch.setattr(module.os, "replace", fail_pointer)
    for index in range(4):
        with pytest.raises(OSError):
            store.publish("board", "main", {"value": f"failed-{index}".encode()}, metadata())
    report = store.retention(apply=True, now=future)
    assert report["unknownAcceptanceCount"] == 4
    assert all(directory(store, item).exists() for item in generations[-3:])
    accepted = json.loads((store.root / "board/main/accepted.json").read_bytes())["generations"]
    assert set(accepted) == {item.generation_id for item in generations[-3:]}


def test_old_staging_directory_is_pruned_but_recent_staging_is_retained(store, monkeypatch):
    _, future = publish_many(store, monkeypatch)
    parent = store.root / "board/main/generations"
    old, recent = parent / (".tmp-" + "1" * 32), parent / (".tmp-" + "2" * 32)
    for path in (old, recent):
        path.mkdir()
        (path / "partial").write_bytes(b"unfinished")
    os.utime(recent, (future.timestamp(), future.timestamp()))
    store.retention(apply=True, now=future)
    assert not old.exists() and recent.exists()


def test_symlink_inside_generation_is_never_followed_or_deleted(store, monkeypatch, tmp_path):
    generations, future = publish_many(store, monkeypatch)
    external = tmp_path.parent / (tmp_path.name + "-outside")
    external.mkdir()
    private = external / "keep"
    private.write_bytes(b"keep")
    link = directory(store, generations[0]) / "files/link"
    try:
        link.symlink_to(private)
    except OSError:
        pytest.skip("symlink creation unavailable")
    with pytest.raises(UnsafeArtifactPath):
        store.retention(apply=True, now=future)
    assert private.read_bytes() == b"keep"


def test_bounded_diagnostics_never_scan_generations(store, monkeypatch):
    store.publish("board", "main", {"value": b"value"}, metadata())
    monkeypatch.setattr(
        store, "_inventory", lambda *_: pytest.fail("diagnostics scanned artifacts")
    )
    report = store.read_retention_report()
    assert report["generationCount"] == 1
    assert len(json.dumps(report)) < 65536
    (store.root / "retention-report.json").write_bytes(b"x" * 65537)
    assert store.read_retention_report()["status"] == "unknown"
    for body in (b"[]", b"null"):
        (store.root / "retention-report.json").write_bytes(body)
        assert store.read_retention_report()["status"] == "unknown"


def test_maintenance_cli_defaults_to_dry_run(store, capsys):
    from scripts.prune_serving_artifacts import main

    store.publish("board", "main", {"value": b"value"}, metadata())
    assert main(["--root", str(store.root), "--min-free-bytes", "0"]) == 0
    assert json.loads(capsys.readouterr().out)["dryRun"] is True
    assert (
        main(["--root", str(store.root), "--apply", "--max-bytes", "1", "--min-free-bytes", "0"])
        == 2
    )
    assert json.loads(capsys.readouterr().out)["capacityBlocked"] is True
