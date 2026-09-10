"""Durable prepared bytes. Loading is validation/deserialization, never a build."""

from __future__ import annotations

import gzip
import hashlib
import json

from src.serving.artifacts import ArtifactStore, CorruptArtifact, Generation
from src.serving.builder import json_bytes, project_contract_views
from src.serving.projections import MODEL_VERSION, ReadModelEnvelope, player_index
from src.serving.runtime import PreparedPayload, ServingGeneration

ASSET = "canonical-serving"
KEY = "default"
REQUIRED_VIEWS = frozenset(
    {"full", "runtime", "array", "startup", "compact", "rankings", "trade", "catalog"}
)


def validate_generation(candidate: ServingGeneration) -> None:
    if not candidate.health.get("ok") or not candidate.contract.get("playersArray"):
        raise CorruptArtifact("candidate has no valid canonical board")
    if not REQUIRED_VIEWS.issubset(candidate.views):
        raise CorruptArtifact("candidate is missing a required serving view")
    if candidate.contract != candidate.views["full"].payload:
        raise CorruptArtifact("candidate contract and full view disagree")
    if candidate.generation_id != hashlib.sha256(candidate.views["full"].raw).hexdigest():
        raise CorruptArtifact("candidate board identity disagrees with full view")
    projections = project_contract_views(candidate.contract, candidate.generation_id)
    for name, view in candidate.views.items():
        # Canonical metadata intentionally contains Python tuples (e.g.
        # deprecations), represented as arrays on the wire. Compare the exact
        # canonical JSON encoding rather than Python container types.
        if json_bytes(view.payload) != view.raw or gzip.decompress(view.gzip) != view.raw:
            raise CorruptArtifact("candidate payload and encoded view disagree")
        if hashlib.sha1(view.raw).hexdigest() != view.etag:
            raise CorruptArtifact("candidate ETag disagrees with encoded view")
        if name in projections and view.raw != json_bytes(projections[name]):
            raise CorruptArtifact("candidate view differs from canonical projection")
        if name in {"rankings", "trade", "catalog"}:
            ReadModelEnvelope.model_validate(view.payload)
            if view.payload["meta"].get("readModelGeneration") != candidate.generation_id:
                raise CorruptArtifact("candidate read model generation disagrees")


def load_generation(artifact: Generation) -> ServingGeneration:
    """Called on the reload thread only; immutable bytes were checksum-verified."""
    try:
        index = json.loads(artifact.files["index.json"])
        if index.get("schemaVersion") != 1:
            raise CorruptArtifact("unsupported serving index schema")
        views = {}
        for name, etag in index["views"].items():
            raw = artifact.files[f"views/{name}.json"]
            views[name] = PreparedPayload(
                json.loads(raw), raw, artifact.files[f"views/{name}.gz"], etag
            )
        candidate = ServingGeneration(
            index["generation"],
            views["full"].payload,
            json.loads(artifact.files["input.json"]),
            {
                **index["source"],
                "sourceAsOf": artifact.manifest.get("sourceAsOf"),
                "observedAt": artifact.manifest.get("observedAt"),
            },
            index["health"],
            index["coverage"],
            views,
            indexes={"players": player_index(views["full"].payload)},
            artifact_generation_id=artifact.generation_id,
        )
        validate_generation(candidate)
        return candidate
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise CorruptArtifact("invalid prepared serving bundle") from exc


def publish_generation(
    candidate: ServingGeneration,
    *,
    store: ArtifactStore | None = None,
    input_generations: dict | None = None,
) -> Generation:
    validate_generation(candidate)
    files = {
        "index.json": json_bytes(
            {
                "schemaVersion": 1,
                "generation": candidate.generation_id,
                "source": candidate.source,
                "health": candidate.health,
                "coverage": candidate.coverage,
                "views": {name: view.etag for name, view in candidate.views.items()},
            }
        ),
        "input.json": json_bytes(candidate.raw),
    }
    for name, view in candidate.views.items():
        files[f"views/{name}.json"] = view.raw
        files[f"views/{name}.gz"] = view.gzip
    metadata = {
        "modelVersion": MODEL_VERSION,
        "inputGenerations": input_generations
        or {"canonicalInput": hashlib.sha256(files["input.json"]).hexdigest()},
        "configHash": hashlib.sha256(
            json_bytes((candidate.contract.get("sleeper") or {}).get("scoringSettings"))
        ).hexdigest(),
        "sourceAsOf": candidate.source.get("producedAt")
        or candidate.raw.get("scrapeTimestamp")
        or None,
    }
    return (store or ArtifactStore()).publish(
        ASSET,
        KEY,
        files,
        metadata,
        validator=load_generation,
    )
