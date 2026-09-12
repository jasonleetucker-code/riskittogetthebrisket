"""Durable prepared bytes. Loading is validation/deserialization, never a build."""

from __future__ import annotations

import gzip
import hashlib
import json

from src.serving.artifacts import ArtifactStore, CorruptArtifact, Generation
from src.serving.builder import json_bytes, project_contract_views
from src.serving.projections import MODEL_VERSION, ReadModelEnvelope, player_index
from src.serving.runtime import PreparedBytes, PreparedPayload, ServingGeneration

ASSET = "canonical-serving"
KEY = "default"
REQUIRED_VIEWS = frozenset(
    {"full", "runtime", "array", "startup", "compact", "rankings", "trade", "catalog"}
)


def validate_generation(candidate: ServingGeneration) -> None:
    _validate_generation(
        candidate, project_contract_views(candidate.contract, candidate.generation_id)
    )


def _validate_generation(candidate: ServingGeneration, projections: dict) -> None:
    if not candidate.health.get("ok") or not candidate.contract.get("playersArray"):
        raise CorruptArtifact("candidate has no valid canonical board")
    if not REQUIRED_VIEWS.issubset(candidate.views):
        raise CorruptArtifact("candidate is missing a required serving view")
    if candidate.contract != candidate.views["full"].payload:
        raise CorruptArtifact("candidate contract and full view disagree")
    if candidate.generation_id != hashlib.sha256(candidate.views["full"].raw).hexdigest():
        raise CorruptArtifact("candidate board identity disagrees with full view")
    for name, view in candidate.views.items():
        # Canonical metadata intentionally contains Python tuples (e.g.
        # deprecations), represented as arrays on the wire. Compare the exact
        # canonical JSON encoding rather than Python container types.
        encoded = json_bytes(view.payload)
        if encoded != view.raw or gzip.decompress(view.gzip) != view.raw:
            raise CorruptArtifact("candidate payload and encoded view disagree")
        if hashlib.sha1(view.raw).hexdigest() != view.etag:
            raise CorruptArtifact("candidate ETag disagrees with encoded view")
        if name in projections and view.raw != (
            encoded if view.payload is projections[name] else json_bytes(projections[name])
        ):
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
        contract = json.loads(artifact.files["views/full.json"])
        # Acceptance already recomputes these pure projections. Keep that graph
        # instead of decoding eight additional graphs and then discarding the
        # recomputed one. Exact persisted bytes still have to match below.
        projections = project_contract_views(contract, index["generation"])
        views = {}
        for name, etag in index["views"].items():
            raw = artifact.files[f"views/{name}.json"]
            views[name] = PreparedPayload(
                projections[name] if name in projections else json.loads(raw),
                raw,
                artifact.files[f"views/{name}.gz"],
                etag,
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
        _validate_generation(candidate, projections)
        if "web" in index and index["web"] != _web_index(candidate):
            raise CorruptArtifact("web metadata or player offsets differ from canonical truth")
        return candidate
    except (ValueError, TypeError, KeyError, OSError) as exc:
        raise CorruptArtifact("invalid prepared serving bundle") from exc


def _web_index(candidate):
    offsets = {id(row): offset for offset, row in enumerate(candidate.contract["playersArray"])}
    return {
        "players": {key: offsets[id(row)] for key, row in player_index(candidate.contract).items()},
        "views": {
            name: {"payloadView": view.payload_view, "meta": view.metadata}
            for name, view in candidate.views.items()
        },
    }


def load_web_generation(artifact: Generation) -> ServingGeneration:
    """Prepared-mode adoption: authenticated bytes, retained domain consumers."""
    from src.serving.attestation import enabled, verify_artifact

    if not enabled():
        return load_generation(artifact)
    verify_artifact(artifact)
    try:
        index = json.loads(artifact.files["index.json"])
        contract = json.loads(artifact.files["views/full.json"])
        if index.get("schemaVersion") != 1 or set(index["views"]) != REQUIRED_VIEWS:
            raise CorruptArtifact("invalid certified serving index")
        if hashlib.sha256(artifact.files["views/full.json"]).hexdigest() != index["generation"]:
            raise CorruptArtifact("certified canonical identity mismatch")
        # Existing domain handlers and legacy globals still consume these five
        # graphs. Runtime/array retain shared canonical rows; page projections
        # have no decoded graph in the web process.
        decoded = {
            "full": contract,
            "runtime": {
                **{k: v for k, v in contract.items() if k != "playersArray"},
                "payloadView": "runtime",
            },
            "array": {
                **{k: v for k, v in contract.items() if k != "players"},
                "payloadView": "array",
            },
        }
        for name in ("startup", "compact"):
            decoded[name] = json.loads(artifact.files[f"views/{name}.json"])
        views = {}
        for name, etag in index["views"].items():
            raw, gz = artifact.files[f"views/{name}.json"], artifact.files[f"views/{name}.gz"]
            info = index["web"]["views"][name]
            views[name] = (
                PreparedPayload(decoded[name], raw, gz, etag)
                if name in decoded
                else PreparedBytes(raw, gz, etag, info["payloadView"], info["meta"])
            )
        players = contract["playersArray"]
        return ServingGeneration(
            index["generation"],
            contract,
            json.loads(artifact.files["input.json"]),
            {
                **index["source"],
                "sourceAsOf": artifact.manifest.get("sourceAsOf"),
                "observedAt": artifact.manifest.get("observedAt"),
            },
            index["health"],
            index["coverage"],
            views,
            indexes={
                "players": {key: players[offset] for key, offset in index["web"]["players"].items()}
            },
            artifact_generation_id=artifact.generation_id,
        )
    except (ValueError, TypeError, KeyError, IndexError, OSError) as exc:
        raise CorruptArtifact("invalid certified canonical bundle") from exc


def validate_serialized_artifact(artifact: Generation) -> ServingGeneration:
    """Issuer-owned projection/byte validation, not raw valuation recomputation."""
    if artifact.asset != ASSET or artifact.key != KEY:
        raise CorruptArtifact("unsupported canonical serving partition")
    loaded = load_generation(artifact)
    expected = hashlib.sha256(
        json_bytes((loaded.contract.get("sleeper") or {}).get("scoringSettings"))
    ).hexdigest()
    if (
        artifact.manifest.get("modelVersion") != MODEL_VERSION
        or artifact.manifest.get("configHash") != expected
    ):
        raise CorruptArtifact("canonical serialized configuration identity differs")
    return loaded


def publish_generation(
    candidate: ServingGeneration,
    *,
    store: ArtifactStore | None = None,
    input_generations: dict | None = None,
) -> Generation:
    from src.serving.attestation import certify, enabled, verify_artifact

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
                **({"web": _web_index(candidate)} if enabled() else {}),
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
    store = store or ArtifactStore()
    files = certify(store, ASSET, KEY, files, metadata)
    return store.publish(
        ASSET,
        KEY,
        files,
        metadata,
        validator=(lambda artifact: verify_artifact(artifact, require_observation=False))
        if enabled()
        else load_generation,
    )
