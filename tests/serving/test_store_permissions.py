"""Permission-aware layout preserves private defaults and queue ownership."""

import os
import stat

import pytest

from src.serving.artifacts import ArtifactStore, RetentionPolicy, UnsafeArtifactPath
from src.serving.producer_status import (
    claim_source_refresh,
    pending_source_refresh,
    request_source_refresh,
)


def test_private_default_keeps_legacy_queue(tmp_path, monkeypatch):
    monkeypatch.delenv("RISKIT_SERVING_READER_GID", raising=False)
    store = ArtifactStore(tmp_path)
    queued = request_source_refresh(store)
    assert store.reader_gid is None
    assert (tmp_path / "source-refresh.request").exists()
    assert pending_source_refresh(store)["requestId"] == queued["requestId"]
    assert claim_source_refresh(store)["requestId"] == queued["requestId"]


@pytest.mark.parametrize("value", ["", "-1", "group", "1.0"])
def test_invalid_group_configuration_refused(tmp_path, monkeypatch, value):
    monkeypatch.setenv("RISKIT_SERVING_READER_GID", value)
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path)


@pytest.mark.skipif(os.name == "posix", reason="POSIX supports group permissions")
def test_windows_does_not_claim_posix_permissions(tmp_path):
    with pytest.raises(ValueError):
        ArtifactStore(tmp_path, reader_gid=1000)


@pytest.fixture
def group_store(tmp_path):
    if os.name != "posix":
        pytest.skip("Requires actual POSIX mode/group enforcement")
    store = ArtifactStore(
        tmp_path / "store",
        reader_gid=os.getgid(),
        retention_policy=RetentionPolicy(min_free_bytes=0),
    )
    store.provision_access()
    return store


def test_published_and_replaced_files_readable_without_group_write(group_store):
    store = group_store
    metadata = {"modelVersion": "test", "inputGenerations": {}, "configHash": "test"}
    for body in (b"first", b"replacement"):
        generation = store.publish("sample", "main", {"nested/value": body}, metadata)
        assert store.read_current("sample", "main").files["nested/value"] == body
        partition = store.root / "sample/main"
        for path in (
            partition / "current.json",
            partition / "accepted.json",
            partition / "generations" / generation.generation_id / "files/nested/value",
        ):
            assert stat.S_IMODE(path.stat().st_mode) == 0o640
            assert path.stat().st_gid == os.getgid()
        assert stat.S_IMODE(partition.stat().st_mode) == 0o2750


def test_queue_directory_is_writable_but_claim_and_locks_stay_protected(group_store):
    store = group_store
    first = request_source_refresh(store)
    assert request_source_refresh(store)["coalesced"]
    marker = store.request_root / "source-refresh.request"
    assert stat.S_IMODE(marker.stat().st_mode) == 0o660
    assert claim_source_refresh(store)["requestId"] == first["requestId"]
    assert pending_source_refresh(store) is None
    assert stat.S_IMODE((store.root / "source-refresh-claim.json").stat().st_mode) == 0o640
    assert stat.S_IMODE(store.root.stat().st_mode) == 0o2750
    assert stat.S_IMODE(store.request_root.stat().st_mode) == 0o2770
    assert (store.root / "source-request.lock").exists()
    assert not (store.request_root / "source-request.lock").exists()


def test_legacy_queued_obligation_blocks_layout_switch(group_store):
    marker = group_store.root / "source-refresh.request"
    marker.write_text("legacy obligation")
    with pytest.raises(UnsafeArtifactPath):
        request_source_refresh(group_store)
    assert marker.read_text() == "legacy obligation"


def test_provisioning_refuses_broad_existing_root(group_store):
    group_store.root.chmod(0o2770)
    with pytest.raises(UnsafeArtifactPath):
        group_store.provision_access()
    assert stat.S_IMODE(group_store.root.stat().st_mode) == 0o2770


def test_missing_shared_lock_is_not_silently_recreated_by_reader(group_store):
    (group_store.root / "store.lock").unlink()
    with pytest.raises(FileNotFoundError):
        group_store.read_current("sample", "main")
    assert not (group_store.root / "store.lock").exists()


def test_fifo_queue_marker_is_rejected_without_blocking(group_store):
    marker = group_store.request_root / "source-refresh.request"
    os.mkfifo(marker)
    assert pending_source_refresh(group_store) is None
    assert claim_source_refresh(group_store)["outcome"] == "invalid_request"
    assert not marker.exists()


def test_group_layout_requires_setgid_and_rejects_special_bits(group_store):
    group_store.request_root.chmod(0o770)
    with pytest.raises(UnsafeArtifactPath):
        pending_source_refresh(group_store)


def test_coordinator_creates_group_readable_partition(group_store):
    from src.serving.coordinator import prepare_or_reobserve
    from src.serving.input_manifest import InputManifest

    store = group_store
    result = prepare_or_reobserve(
        store=store,
        asset="sample",
        key="main",
        manifest=InputManifest("sample", {"fixture": "same"}, True),
        build=lambda: b"value",
        publish=lambda body, inputs: store.publish(
            "sample",
            "main",
            {"value": body},
            {"modelVersion": "test", "inputGenerations": inputs, "configHash": "test"},
        ),
        validate=lambda generation: generation.files["value"] == b"value",
        source_as_of="2026-09-12T12:00:00+00:00",
    )
    assert result.rebuilt
    assert stat.S_IMODE((store.root / "sample").stat().st_mode) == 0o2750
    assert stat.S_IMODE((store.root / "sample/main").stat().st_mode) == 0o2750


def test_incompatible_existing_partition_is_not_silently_widened(group_store):
    partition = group_store.root / "sample"
    partition.mkdir(mode=0o700)
    with pytest.raises(UnsafeArtifactPath):
        group_store._directory(partition / "main")
    assert stat.S_IMODE(partition.stat().st_mode) & 0o777 == 0o700
