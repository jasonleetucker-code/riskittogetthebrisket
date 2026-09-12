"""Publication, integrity, privacy and process-crash guarantees for serving files."""

from __future__ import annotations

import json
import multiprocessing
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.serving import (
    ArtifactStore,
    CorruptArtifact,
    MissingArtifact,
    PublishLockTimeout,
    RejectedCandidate,
    UnsafeArtifactPath,
    UnsupportedSchema,
)
from src.serving.artifacts import _publish_lock


def metadata(**changes):
    return {
        "modelVersion": "canonical-v1",
        "inputGenerations": {"raw": "input-1", "scoring": "scoring-1"},
        "configHash": "config-1",
        "sourceAsOf": {"raw": "2026-09-10T12:00:00+00:00"},
        **changes,
    }


def publish(store, body=b'{"player":1}', **changes):
    return store.publish("canonical", "default", {"contract.json": body}, metadata(**changes))


def generation_dir(store, generation):
    return store.root / "canonical" / "default" / "generations" / generation.generation_id


def _holding_process(root, acquired, release):
    path = Path(root) / "canonical" / "default" / "publisher.lock"
    with _publish_lock(path, timeout=5):
        acquired.set()
        release.wait(20)


def test_round_trip_includes_immutable_files_provenance_and_configured_root(tmp_path, monkeypatch):
    monkeypatch.setenv("RISKIT_SERVING_DIR", str(tmp_path / "private"))
    store = ArtifactStore()
    original_metadata = metadata()
    first = store.publish(
        "canonical",
        "default",
        {"contract.json": b'{"players":[]}', "encoded/contract.json.gz": b"compressed"},
        original_metadata,
    )
    original_metadata["inputGenerations"]["raw"] = "mutated-caller"
    loaded = store.read_current("canonical", "default")
    assert first == loaded
    assert loaded.manifest["inputGenerations"]["raw"] == "input-1"
    assert loaded.manifest["schemaVersion"] == 1
    assert loaded.manifest["generatedAt"]
    assert loaded.manifest["observedAt"]
    assert loaded.files["encoded/contract.json.gz"] == b"compressed"
    with pytest.raises(TypeError):
        loaded.files["contract.json"] = b"changed"
    with pytest.raises(TypeError):
        loaded.manifest["inputGenerations"]["raw"] = "changed"


def test_unchanged_generation_updates_freshness_without_rewriting_files(tmp_path):
    store = ArtifactStore(tmp_path)
    first = publish(store, generatedAt="2026-09-10T12:00:00+00:00")
    path = generation_dir(store, first) / "manifest.json"
    previous = (path.read_bytes(), path.stat().st_mtime_ns)
    first_version = store.current_version("canonical", "default")
    later = "2026-09-10T14:00:00+00:00"
    second = publish(store, generatedAt=later, sourceAsOf={"raw": later})
    assert second.generation_id == first.generation_id
    assert second.manifest["generatedAt"] == first.manifest["generatedAt"]
    assert second.manifest["sourceAsOf"] == {"raw": later}
    assert store.read_current("canonical", "default").manifest["sourceAsOf"] == {"raw": later}
    assert (path.read_bytes(), path.stat().st_mtime_ns) == previous
    assert store.current_version("canonical", "default") != first_version
    assert len(list(path.parent.parent.iterdir())) == 1


@pytest.mark.parametrize(
    "changes",
    [
        {"modelVersion": "canonical-v2"},
        {"inputGenerations": {"raw": "input-2", "scoring": "scoring-1"}},
        {"configHash": "config-2"},
        {"scoringFingerprint": "facts-from-requested-league"},
    ],
)
def test_each_semantic_dependency_changes_generation(tmp_path, changes):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    second = publish(store, **changes)
    assert second.generation_id != first.generation_id
    assert store.read_current("canonical", "default") == second
    assert (generation_dir(store, first) / "files" / "contract.json").read_bytes() == first.files[
        "contract.json"
    ]


def test_file_and_metadata_order_do_not_change_identity(tmp_path):
    store = ArtifactStore(tmp_path)
    files = {"b.json": b"b", "a.json": b"a"}
    first = store.publish("canonical", "default", files, metadata())
    second = store.publish(
        "canonical",
        "default",
        dict(reversed(list(files.items()))),
        metadata(inputGenerations={"scoring": "scoring-1", "raw": "input-1"}),
    )
    assert first.generation_id == second.generation_id


@pytest.mark.parametrize("raises", [True, False])
def test_rejected_candidate_leaves_current_bytes_and_freshness_untouched(tmp_path, raises):
    store = ArtifactStore(tmp_path)
    previous = publish(store)
    pointer = tmp_path / "canonical" / "default" / "current.json"
    previous_pointer = pointer.read_bytes()

    def reject(candidate):
        assert candidate.files["contract.json"] == b"bad"
        if raises:
            raise ValueError("domain validation failed")
        return False

    with pytest.raises(ValueError if raises else RejectedCandidate):
        store.publish("canonical", "default", {"contract.json": b"bad"}, metadata(), reject)
    assert store.read_current("canonical", "default") == previous
    assert pointer.read_bytes() == previous_pointer
    assert len(list(pointer.parent.joinpath("generations").iterdir())) == 1


def test_missing_and_corrupted_are_distinct(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(MissingArtifact):
        store.read_current("canonical", "default")
    with pytest.raises(MissingArtifact):
        store.current_version("canonical", "default")
    generation = publish(store)
    (generation_dir(store, generation) / "files" / "contract.json").unlink()
    with pytest.raises(CorruptArtifact):
        store.read_current("canonical", "default")


@pytest.mark.parametrize("target", ["file", "manifest", "pointer"])
def test_corruption_is_rejected_instead_of_becoming_last_good(tmp_path, target):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    directory = generation_dir(store, first)
    path = {
        "file": directory / "files" / "contract.json",
        "manifest": directory / "manifest.json",
        "pointer": tmp_path / "canonical" / "default" / "current.json",
    }[target]
    if target == "file":
        path.write_bytes(b'{"player":9}')  # Same length; checksum must catch it.
    elif target == "manifest":
        manifest = json.loads(path.read_bytes())
        manifest["sourceAsOf"] = {"raw": "forged"}  # Excluded from generation identity.
        path.write_text(json.dumps(manifest))
    else:
        path.write_bytes(b"truncated{")
    with pytest.raises(CorruptArtifact):
        store.read_current("canonical", "default")


@pytest.mark.parametrize("target", ["manifest", "pointer"])
def test_unknown_schema_is_explicit(tmp_path, target):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    path = (
        generation_dir(store, first) / "manifest.json"
        if target == "manifest"
        else tmp_path / "canonical" / "default" / "current.json"
    )
    content = json.loads(path.read_bytes())
    content["schemaVersion"] = 999
    path.write_text(json.dumps(content))
    with pytest.raises(UnsupportedSchema):
        store.read_current("canonical", "default")


@pytest.mark.parametrize("target", ["file", "manifest"])
def test_republishing_a_corrupted_generation_cannot_refresh_its_freshness(tmp_path, target):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    pointer = tmp_path / "canonical" / "default" / "current.json"
    original_pointer = pointer.read_bytes()
    if target == "file":
        (generation_dir(store, first) / "files" / "contract.json").write_bytes(b"corrupt")
    else:
        path = generation_dir(store, first) / "manifest.json"
        content = json.loads(path.read_bytes())
        content["generatedAt"] = "corrupt timestamp excluded from identity"
        path.write_text(json.dumps(content))
    with pytest.raises(CorruptArtifact):
        publish(store, sourceAsOf="later")
    assert pointer.read_bytes() == original_pointer


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "x\\y", "a/../b", "", "a//b", "NUL", "x."]
)
def test_untrusted_names_cannot_escape_storage(tmp_path, name):
    store = ArtifactStore(tmp_path)
    with pytest.raises(UnsafeArtifactPath):
        store.publish(name, "default", {"contract.json": b"x"}, metadata())
    with pytest.raises(UnsafeArtifactPath):
        store.publish("canonical", "default", {name: b"x"}, metadata())
    assert list(tmp_path.iterdir()) == []


def test_case_collisions_are_rejected_on_every_platform(tmp_path):
    with pytest.raises(UnsafeArtifactPath):
        ArtifactStore(tmp_path).publish(
            "canonical", "default", {"a.json": b"a", "A.json": b"b"}, metadata()
        )


@pytest.mark.parametrize("location", ["root", "partition", "file", "pointer"])
def test_symlink_escape_is_rejected(tmp_path, location):
    outside = tmp_path / "outside"
    outside.mkdir()
    store = ArtifactStore(tmp_path / "private")
    first = publish(store)
    if location == "root":
        link = tmp_path / "linked-root"
        target = store.root
    elif location == "partition":
        link = store.root / "canonical" / "other"
        target = outside
    elif location == "pointer":
        link = store.root / "canonical" / "default" / "current.json"
        target = outside / "current.json"
        target.write_bytes(link.read_bytes())
        link.unlink()
    else:
        link = generation_dir(store, first) / "files" / "contract.json"
        target = outside / "contract.json"
        target.write_bytes(link.read_bytes())
        link.unlink()
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"OS does not grant symlink creation: {exc}")
    with pytest.raises(UnsafeArtifactPath):
        if location == "root":
            ArtifactStore(link)
        elif location == "partition":
            store.publish("canonical", "other", {"x": b"x"}, metadata())
        else:
            store.read_current("canonical", "default")


def test_failed_pointer_replace_retains_current_and_cleans_only_own_temp(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    original_replace = os.replace

    def fail_pointer(source, destination):
        if Path(destination).name == "current.json":
            raise OSError("simulated interrupted publication")
        return original_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_pointer)
    with pytest.raises(OSError, match="interrupted"):
        publish(store, body=b"candidate")
    assert store.read_current("canonical", "default") == first
    partition = tmp_path / "canonical" / "default"
    assert list(partition.glob(".current-*.tmp")) == []
    assert list(partition.joinpath("generations").glob(".tmp-*")) == []


def test_concurrent_readers_capture_complete_generations(tmp_path):
    store = ArtifactStore(tmp_path)
    publish(store)

    def write(number):
        value = str(number).encode()
        store.publish("canonical", "default", {"left": value, "right": value}, metadata())

    def read():
        for _ in range(20):
            captured = store.read_current("canonical", "default")
            if "left" in captured.files:
                assert captured.files["left"] == captured.files["right"]

    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = [pool.submit(write, number) for number in range(8)]
        pending.extend(pool.submit(read) for _ in range(3))
        for future in pending:
            future.result()


def test_process_lock_timeout_and_crash_release(tmp_path):
    store = ArtifactStore(tmp_path, lock_timeout=0.1)
    first = publish(store)
    context = multiprocessing.get_context("spawn")
    acquired = context.Event()
    release = context.Event()
    process = context.Process(target=_holding_process, args=(str(tmp_path), acquired, release))
    process.start()
    try:
        assert acquired.wait(10), "child did not acquire publication lock"
        with pytest.raises(PublishLockTimeout):
            publish(store, body=b"waiting")
        assert store.read_current("canonical", "default") == first
        process.terminate()
        process.join(timeout=10)
        assert not process.is_alive()
        later = publish(store, body=b"after crash")
        assert store.read_current("canonical", "default") == later
    finally:
        if process.is_alive():
            process.terminate()
            process.join(timeout=10)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits do not represent Windows ACLs")
def test_new_artifacts_are_private_to_service_user(tmp_path):
    store = ArtifactStore(tmp_path / "private")
    first = publish(store)
    assert store.root.stat().st_mode & 0o077 == 0
    assert (generation_dir(store, first) / "files" / "contract.json").stat().st_mode & 0o077 == 0
