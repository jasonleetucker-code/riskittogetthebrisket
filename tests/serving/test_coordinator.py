from concurrent.futures import ThreadPoolExecutor

import pytest

from src.serving.artifacts import ArtifactStore
from src.serving.builder import prepare_generation
from src.serving.coordinator import InputChanged, prepare_or_reobserve
from src.serving.input_manifest import InputManifest
from src.serving.serialization import publish_generation

OLD = "2026-09-10T12:00:00+00:00"
NEW = "2026-09-10T12:10:00+00:00"


def execute(
    store, calls, *, identity="same", complete=True, source=OLD, failing=False, verify=None
):
    board = prepare_generation(
        {"playersArray": [{"playerId": identity, "displayName": identity, "position": "WR"}]},
        {},
        {"producedAt": OLD},
        {"ok": True},
    )
    publish_generation(board, store=store)
    manifest = InputManifest(
        "league-serving", {"board": board.generation_id}, complete, verify=verify
    )

    def build():
        calls.append("build")
        if failing:
            raise ValueError("bad candidate")
        return identity.encode()

    def validate(artifact):
        return bool(artifact.files.get("view"))

    def publish(body, inputs):
        artifact = store.publish(
            "league-serving",
            "league",
            {"view": body},
            {
                "modelVersion": "test",
                "configHash": "test",
                "inputGenerations": inputs,
                "sourceAsOf": source,
                "extra": {"nested": ["metadata"]},
            },
            validator=validate,
        )
        calls.append("record")
        return artifact

    return prepare_or_reobserve(
        store=store,
        asset="league-serving",
        key="league",
        manifest=manifest,
        build=build,
        publish=publish,
        validate=validate,
        source_as_of=source,
    )


def test_equal_complete_inputs_reobserve_pointer_without_build_or_history(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    first = execute(store, calls)
    second = execute(store, calls, source=NEW)
    assert first.rebuilt and not second.rebuilt
    assert first.artifact.generation_id == second.artifact.generation_id
    assert second.artifact.manifest["sourceAsOf"] == NEW
    assert first.artifact.manifest["observedAt"] != second.artifact.manifest["observedAt"]
    assert calls == ["build", "record"]


def test_incomplete_inventory_never_skips_even_when_hashes_match(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    execute(store, calls, complete=False)
    assert execute(store, calls, complete=False).rebuilt
    assert calls.count("build") == 2


def test_changed_input_rebuilds_once_and_failure_cannot_accept_fingerprint(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    first = execute(store, calls)
    with pytest.raises(ValueError, match="bad candidate"):
        execute(store, calls, identity="changed", failing=True)
    assert (
        store.read_current("league-serving", "league").generation_id == first.artifact.generation_id
    )
    assert execute(store, calls, identity="changed").rebuilt
    assert not execute(store, calls, identity="changed").rebuilt
    assert calls.count("record") == 2


def test_concurrent_coordinators_build_identical_inputs_once(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: execute(store, calls), range(4)))
    assert sum(result.rebuilt for result in results) == 1
    assert calls == ["build", "record"]


def test_mutated_inputs_reject_candidate_before_acceptance(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    first = execute(store, calls)
    with pytest.raises(InputChanged):
        execute(store, calls, identity="changed", verify=lambda: False)
    assert (
        store.read_current("league-serving", "league").generation_id == first.artifact.generation_id
    )
    assert calls.count("record") == 1


def test_mutated_inputs_cannot_reobserve_pointer(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    execute(store, calls)
    with pytest.raises(InputChanged):
        execute(store, calls, source=NEW, verify=lambda: False)
    assert store.read_current("league-serving", "league").manifest["sourceAsOf"] == OLD
    assert calls == ["build", "record"]


def test_matching_fingerprint_cannot_bypass_domain_validation(tmp_path):
    store, calls = ArtifactStore(tmp_path), []
    first = execute(store, calls)
    manifest = InputManifest(
        "league-serving", {"board": first.artifact.manifest["inputGenerations"]["board"]}, True
    )
    builds = []

    def publish(_candidate, _inputs):
        raise ValueError("replacement validation failed")

    with pytest.raises(ValueError, match="replacement validation failed"):
        prepare_or_reobserve(
            store=store,
            asset="league-serving",
            key="league",
            manifest=manifest,
            build=lambda: builds.append("required") or b"replacement",
            publish=publish,
            validate=lambda _artifact: False,
            source_as_of=NEW,
        )
    assert builds == ["required"]
    assert (
        store.read_current("league-serving", "league").generation_id == first.artifact.generation_id
    )
