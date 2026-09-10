"""Dependency-aware preparation using only validated accepted artifact manifests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.serving.artifacts import ArtifactError, ArtifactStore, Generation, _mkdir, _publish_lock
from src.serving.input_manifest import InputManifest


class InputChanged(RuntimeError):
    """Inputs changed during preparation; no new fingerprint was accepted."""


@dataclass(frozen=True)
class BuildResult:
    artifact: Generation
    rebuilt: bool
    reason: str


def _plain(value):
    if hasattr(value, "items"):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def prepare_or_reobserve(
    *,
    store: ArtifactStore,
    asset: str,
    key: str,
    manifest: InputManifest,
    build: Callable[[], Any],
    publish: Callable[[Any, dict[str, str]], Generation],
    validate: Callable[[Generation], Any],
    source_as_of: str,
) -> BuildResult:
    """Skip computation only for complete, equal, validated accepted inputs.

    ``publish`` must pass the supplied input_generations to the existing atomic
    publisher and its domain validator. No independent accepted-fingerprint file
    exists, so a failed build cannot poison later rebuild planning.
    """
    if manifest.asset != asset:
        raise ValueError("input manifest belongs to another asset")
    stamp = datetime.fromisoformat(source_as_of.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("source observation requires a qualified timestamp")
    partition = store._partition(asset, key)
    _mkdir(partition)

    def verify_inputs():
        if manifest.verify is not None and not manifest.verify():
            raise InputChanged("producer code changed during preparation")

    with _publish_lock(partition / "coordinator.lock", store.lock_timeout):
        expected = manifest.input_generations
        current = None
        try:
            current = store.read_current(asset, key)
            if validate(current) is False:
                current = None
        except (ArtifactError, ValueError, TypeError, KeyError, OSError):
            current = None
        if (
            manifest.complete
            and current is not None
            and dict(current.manifest.get("inputGenerations", {})) == expected
        ):
            verify_inputs()
            metadata = {
                name: _plain(value)
                for name, value in current.manifest.items()
                if name
                not in {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
            }
            metadata["inputGenerations"] = expected
            metadata["sourceAsOf"] = source_as_of
            artifact = store.publish(asset, key, current.files, metadata, validator=validate)
            return BuildResult(artifact, False, "unchanged complete inputs")
        candidate = build()
        verify_inputs()
        artifact = publish(candidate, expected)
        if dict(artifact.manifest.get("inputGenerations", {})) != expected:
            raise ValueError("publisher did not record the supplied input manifest")
        return BuildResult(
            artifact, True, "changed inputs" if manifest.complete else "incomplete input manifest"
        )
