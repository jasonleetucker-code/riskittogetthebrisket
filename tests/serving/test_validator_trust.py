"""Production issuer owns serialized validation; caller callbacks cannot replace it."""

import os
import subprocess
import sys

import pytest
from tests.serving import test_league_attestation as league_tests
from src.serving import league_views

from src.serving import attestation, serialization
from src.serving.artifacts import CorruptArtifact, RejectedCandidate
from tests.serving import test_attestation as certificate_tests
from tests.serving import test_serving_pipeline as pipeline_tests

store = certificate_tests.store
board = pipeline_tests.board


def unsigned(board, store):
    artifact = serialization.publish_generation(board, store=store)
    files = {
        name: body for name, body in artifact.files.items() if name != attestation.CERTIFICATE_FILE
    }
    metadata = {
        name: attestation._plain(value)
        for name, value in artifact.manifest.items()
        if name not in {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
    }
    return files, metadata


def test_noop_callback_cannot_certify_wrong_canonical_projection(board, store):
    files, metadata = unsigned(board, store)
    files["views/rankings.json"] = b"{}"
    with pytest.raises((CorruptArtifact, ValueError)):
        attestation.certify(store, "canonical-serving", "default", files, metadata, lambda _: None)


def test_noop_callback_cannot_certify_wrong_scoring_metadata(board, store):
    files, metadata = unsigned(board, store)
    metadata["configHash"] = "incorrect"
    with pytest.raises((CorruptArtifact, ValueError)):
        attestation.certify(store, "canonical-serving", "default", files, metadata, lambda _: True)


@pytest.mark.parametrize("result", [False, "raise"])
def test_extra_validator_may_reject_but_not_replace_authority(board, store, result):
    files, metadata = unsigned(board, store)

    def extra(candidate):
        if result == "raise":
            raise ValueError("extra refusal")
        return False

    with pytest.raises((ValueError, RejectedCandidate)):
        attestation.certify(store, "canonical-serving", "default", files, metadata, extra)


def test_runtime_descriptor_drift_refuses_existing_certificate(board, store, monkeypatch):
    artifact = serialization.publish_generation(board, store=store)
    original = attestation.distribution_version
    monkeypatch.setattr(
        attestation,
        "distribution_version",
        lambda name: "changed" if name == "pydantic" else original(name),
    )
    with pytest.raises(CorruptArtifact, match="runtime changed"):
        attestation.verify_artifact(artifact)


def test_serialized_scope_is_explicit_and_not_raw_build_proof(board, store):
    artifact = serialization.publish_generation(board, store=store)
    claims = attestation.verify_artifact(artifact)
    assert claims["validationScope"] == "serialized-projection-semantics-v2"
    assert claims["rawBuildProvenanceComplete"] is False
    assert claims["runtimeIdentity"]["distributions"]["pydantic"]


cfg = league_tests.cfg
ready_board = league_tests.ready_board


def league_unsigned(ready_board, store, cfg):
    serialization.publish_generation(ready_board, store=store)
    bundle = league_views.prepare_league_views(ready_board, cfg)
    artifact = league_views.publish_league_views(bundle, store=store, board=ready_board, cfg=cfg)
    files = {
        name: body for name, body in artifact.files.items() if name != attestation.CERTIFICATE_FILE
    }
    metadata = {
        name: attestation._plain(value)
        for name, value in artifact.manifest.items()
        if name not in {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
    }
    return files, metadata


def test_league_cannot_certify_without_explicit_context(ready_board, store, cfg):
    files, metadata = league_unsigned(ready_board, store, cfg)
    with pytest.raises(CorruptArtifact, match="explicit context"):
        attestation.certify(store, "league-serving", cfg.key, files, metadata, lambda _: True)


def test_extra_callback_cannot_change_effective_league_context(ready_board, store, cfg):
    files, metadata = league_unsigned(ready_board, store, cfg)

    def mutate(_):
        cfg.scoring_profile = "different"

    with pytest.raises(CorruptArtifact, match="configuration changed"):
        attestation.certify(
            store, "league-serving", cfg.key, files, metadata, mutate, board=ready_board, cfg=cfg
        )


def test_noop_cannot_certify_wrong_final_league_bytes(ready_board, store, cfg):
    files, metadata = league_unsigned(ready_board, store, cfg)
    files["ready/rankings.json"] = b"{}"
    with pytest.raises((CorruptArtifact, ValueError)):
        attestation.certify(
            store,
            "league-serving",
            cfg.key,
            files,
            metadata,
            lambda _: None,
            board=ready_board,
            cfg=cfg,
        )


@pytest.mark.parametrize("configured", [False, True])
def test_optional_runtime_dependencies_only_required_for_enabled_startup(configured):
    env = os.environ.copy()
    env.pop(attestation.PRIVATE_KEY_ENV, None)
    env.pop(attestation.PUBLIC_KEY_ENV, None)
    if configured:
        env[attestation.PUBLIC_KEY_ENV] = "configured-test-pin.pem"
    program = """
import importlib.metadata as metadata
metadata.version = lambda name: (_ for _ in ()).throw(metadata.PackageNotFoundError(name))
from src.serving.artifacts import ArtifactStore
from src.serving import attestation
assert attestation._PROCESS_RUNTIME is None
"""
    result = subprocess.run(
        [sys.executable, "-c", program], env=env, capture_output=True, text=True
    )
    if configured:
        assert result.returncode != 0
        assert "Validator runtime identity unavailable" in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def test_late_enable_requires_restart_in_real_process():
    env = os.environ.copy()
    env.pop(attestation.PRIVATE_KEY_ENV, None)
    env.pop(attestation.PUBLIC_KEY_ENV, None)
    program = """
import os
from src.serving import attestation
os.environ[attestation.PUBLIC_KEY_ENV] = "configured-test-pin.pem"
try:
    attestation.policy_fingerprint()
except attestation.AttestationError as exc:
    assert "not enabled at startup; restart" in str(exc)
else:
    raise AssertionError("late enable unexpectedly accepted")
"""
    result = subprocess.run(
        [sys.executable, "-c", program], env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("mutation", ["modelVersion", "partition"])
def test_league_algorithm_and_partition_identity_cannot_be_relabelled(
    ready_board, store, cfg, mutation
):
    files, metadata = league_unsigned(ready_board, store, cfg)
    key = cfg.key
    if mutation == "modelVersion":
        metadata["modelVersion"] = "different-algorithm"
    else:
        key = "different-league"
    with pytest.raises(CorruptArtifact):
        attestation.certify(
            store,
            "league-serving",
            key,
            files,
            metadata,
            lambda _: None,
            board=ready_board,
            cfg=cfg,
        )


def test_canonical_issuer_refuses_unsupported_partition(board, store):
    files, metadata = unsigned(board, store)
    with pytest.raises(CorruptArtifact):
        attestation.certify(store, "canonical-serving", "unexpected", files, metadata)


def test_league_issuer_refuses_inconsistent_retention_parent(ready_board, store, cfg):
    files, metadata = league_unsigned(ready_board, store, cfg)
    metadata["inputGenerations"]["board"] = "another-canonical-generation"
    with pytest.raises(CorruptArtifact):
        attestation.certify(
            store,
            "league-serving",
            cfg.key,
            files,
            metadata,
            board=ready_board,
            cfg=cfg,
        )
