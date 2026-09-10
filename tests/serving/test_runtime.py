"""Hot reload must never expose half a generation or discard accepted state."""

from __future__ import annotations

import gzip
import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from src.serving import ArtifactStore, RejectedCandidate
from src.serving.runtime import AtomicRuntime, PreparedPayload, ServingGeneration


def publish(store, value=1, **metadata):
    return store.publish(
        "canonical",
        "default",
        {"contract.json": json.dumps({"value": value}).encode()},
        {
            "modelVersion": "model-v1",
            "configHash": "scoring-v1",
            "inputGenerations": {"raw": str(value)},
            "sourceAsOf": "2026-09-10T12:00:00+00:00",
            **metadata,
        },
    )


def build(artifact):
    raw = artifact.files["contract.json"]
    contract = json.loads(raw)
    view = PreparedPayload(contract, raw, gzip.compress(raw), hashlib.sha256(raw).hexdigest())
    return ServingGeneration(
        generation_id=artifact.generation_id,
        contract=contract,
        raw=dict(contract),
        source={"sourceAsOf": artifact.manifest["sourceAsOf"]},
        health={"ok": True},
        coverage={"value": contract["value"]},
        views={"full": view, "rankings": view},
    )


def runtime(store, builder=build, validator=None):
    return AtomicRuntime(store, "canonical", "default", builder, validator)


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), "background consumer did not reach expected state"


def test_unchanged_pointer_skips_loading_and_rebuilding_large_files(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)
    publish(store)
    state = runtime(store)
    assert state.reload_if_changed()
    captured = state.current

    def unexpected(*args):
        raise AssertionError("unchanged pointer must not read the artifact")

    monkeypatch.setattr(store, "read_current", unexpected)
    assert not state.reload_if_changed()
    assert state.current is captured
    assert state.last_error is None
    assert captured.views["full"].raw == gzip.decompress(captured.views["full"].gzip)
    with pytest.raises(TypeError):
        captured.views["other"] = captured.views["full"]


def test_unchanged_computation_identity_still_refreshes_source_stamps(tmp_path):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    state = runtime(store)
    assert state.reload_if_changed()
    old = state.current
    second = publish(store, sourceAsOf="2026-09-10T14:00:00+00:00")
    assert second.generation_id == first.generation_id
    assert state.reload_if_changed()
    assert state.current.generation_id == old.generation_id
    assert state.current.source["sourceAsOf"] == "2026-09-10T14:00:00+00:00"
    assert old.source["sourceAsOf"] == "2026-09-10T12:00:00+00:00"


def test_corrupt_artifact_and_missing_pointer_retain_last_good(tmp_path):
    store = ArtifactStore(tmp_path)
    state = runtime(store)
    assert not state.reload_if_changed()
    assert state.current is None
    assert state.last_error.startswith("MissingArtifact:")
    first = publish(store)
    assert state.reload_if_changed()
    good = state.current
    second = publish(store, 2)
    directory = tmp_path / "canonical" / "default" / "generations" / second.generation_id
    (directory / "files" / "contract.json").write_bytes(b"broken")
    assert not state.reload_if_changed()
    assert state.current is good
    assert state.current.generation_id == first.generation_id
    assert state.last_error.startswith("CorruptArtifact:")
    (tmp_path / "canonical" / "default" / "current.json").unlink()
    assert not state.reload_if_changed()
    assert state.current is good


@pytest.mark.parametrize("raises", [True, False])
def test_failed_validation_never_replaces_active_generation(tmp_path, raises):
    store = ArtifactStore(tmp_path)

    def validate(candidate):
        if candidate.contract["value"] == 2:
            if raises:
                raise ValueError("bad board")
            return False

    first = publish(store)
    state = runtime(store, validator=validate)
    assert state.reload_if_changed()
    good = state.current
    second = publish(store, 2)
    assert not state.reload_if_changed()
    assert state.current is good
    assert state.current.generation_id == first.generation_id
    with pytest.raises(ValueError if raises else RejectedCandidate):
        state.publish(build(second))
    assert state.current is good
    publish(store, 3)
    assert state.reload_if_changed()
    assert state.current.contract["value"] == 3
    assert state.last_error is None


def test_mislabeled_candidate_does_not_claim_artifact_loaded(tmp_path):
    store = ArtifactStore(tmp_path)
    publish(store)
    state = runtime(store, builder=lambda artifact: replace(build(artifact), generation_id="wrong"))
    assert not state.reload_if_changed()
    assert state.current is None
    assert "does not match" in state.last_error


def test_transient_builder_failure_recovers_without_another_pointer_change(tmp_path):
    store = ArtifactStore(tmp_path)
    first = publish(store)
    unavailable = True

    def temporarily_unavailable(artifact):
        if unavailable:
            raise OSError("temporary local dependency failure")
        return build(artifact)

    state = runtime(store, builder=temporarily_unavailable)
    assert not state.reload_if_changed()
    assert state.current is None
    assert state.last_error.startswith("OSError:")
    unavailable = False
    assert state.reload_if_changed()
    assert state.current.generation_id == first.generation_id
    assert state.last_error is None


def test_slow_reload_preserves_captured_request_and_coalesces_other_reloaders(tmp_path):
    store = ArtifactStore(tmp_path)
    publish(store)
    entered = threading.Event()
    release = threading.Event()

    def slow_builder(artifact):
        candidate = build(artifact)
        if candidate.contract["value"] == 2:
            entered.set()
            assert release.wait(5)
        return candidate

    state = runtime(store, builder=slow_builder)
    assert state.reload_if_changed()
    captured = state.current
    publish(store, 2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = pool.submit(state.reload_if_changed)
        try:
            assert entered.wait(5)
            assert not state.reload_if_changed()
            assert state.current is captured
        finally:
            release.set()
        assert pending.result()
    current = state.current
    assert captured.contract["value"] == 1
    assert json.loads(captured.views["full"].raw)["value"] == 1
    assert current.contract["value"] == 2
    assert current.coverage["value"] == 2
    assert json.loads(current.views["full"].raw)["value"] == 2


def test_superseded_in_flight_generation_cannot_replace_current(tmp_path):
    store = ArtifactStore(tmp_path)
    publish(store)

    def superseded_builder(artifact):
        candidate = build(artifact)
        if candidate.contract["value"] == 2:
            publish(store, 3)
        return candidate

    state = runtime(store, builder=superseded_builder)
    assert state.reload_if_changed()
    publish(store, 2)
    assert not state.reload_if_changed()
    assert state.current.contract["value"] == 1
    assert state.reload_if_changed()
    assert state.current.contract["value"] == 3


def test_background_reload_advances_without_restart_and_stops_cleanly(tmp_path):
    store = ArtifactStore(tmp_path)
    state = runtime(store)
    state.start(interval=0.01)
    state.start(interval=0.01)  # Idempotent, no second consumer.
    try:
        first = publish(store)
        wait_until(lambda: state.current is not None)
        captured = state.current
        second = publish(store, 2)
        wait_until(lambda: state.current.generation_id == second.generation_id)
        assert captured.generation_id == first.generation_id
        assert captured.contract["value"] == 1
        assert state.last_error is None
    finally:
        assert state.stop(timeout=5)


def test_stop_during_slow_build_does_not_publish_after_shutdown(tmp_path):
    store = ArtifactStore(tmp_path)
    publish(store)
    entered = threading.Event()
    release = threading.Event()

    def slow_builder(artifact):
        entered.set()
        assert release.wait(5)
        return build(artifact)

    state = runtime(store, builder=slow_builder)
    state.start(interval=0.01)
    try:
        assert entered.wait(5)
        assert not state.stop(timeout=0.01)
        with pytest.raises(RuntimeError, match="still stopping"):
            state.start()
    finally:
        release.set()
        assert state.stop(timeout=5)
    assert state.current is None


@pytest.mark.parametrize("interval", [0, -1, float("inf"), float("nan")])
def test_invalid_poll_interval_is_rejected(tmp_path, interval):
    with pytest.raises(ValueError):
        runtime(ArtifactStore(tmp_path)).start(interval)
