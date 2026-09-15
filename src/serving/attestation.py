"""Opt-in producer certification; readers pin an external Ed25519 public key.

The private signing key belongs to the standalone producer. Merely storing a
public key beside an artifact never grants trust. Filesystem/account separation
of these keys is an operator responsibility, not a property this module proves.
Unsigned deployments retain their existing full-validation path.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sys
import zlib
from importlib.metadata import version as distribution_version
from datetime import datetime
from pathlib import Path

from src.serving.artifacts import CorruptArtifact, RejectedCandidate, _identity, _json_bytes, _plain

PUBLIC_KEY_ENV = "RISKIT_SERVING_ATTESTATION_PUBLIC_KEY"
PRIVATE_KEY_ENV = "RISKIT_SERVING_ATTESTATION_PRIVATE_KEY"
CERTIFICATE_FILE = "validation.json"
ATTESTED_ASSETS = frozenset({"canonical-serving", "league-serving"})
_REPO = Path(__file__).resolve().parents[2]
# Required entrypoints plus every source module and acquisition script below.
# This is a conservative code closure, not runtime/effective-config certification.
_POLICY_FILES = (
    "server.py",
    "Dynasty Scraper.py",
    "scripts/run_source_producer.py",
    "scripts/refresh_league_serving.py",
    "scripts/refresh_prepared_news.py",
    "src/serving/__init__.py",
)
_VOLATILE = frozenset({"generatedAt", "sourceAsOf", "observedAt"})


class AttestationError(CorruptArtifact):
    """Missing, mismatched or invalid producer evidence."""


def enabled() -> bool:
    public = bool(os.getenv(PUBLIC_KEY_ENV, "").strip())
    if not public and os.getenv(PRIVATE_KEY_ENV, "").strip():
        raise AttestationError("Signing requires an externally pinned public key")
    return public


def _policy_inventory():
    """Enumerate anew: additions/deletions and same-mtime edits are policy drift."""
    root = _REPO.resolve(strict=True)
    names = set(_POLICY_FILES)
    for directory in (root / "src", root / "scripts"):
        if directory.is_symlink() or directory.is_junction() or not directory.is_dir():
            raise AttestationError("Validation policy directory is unavailable")
        for parent, dirs, files in os.walk(directory, followlinks=False, onerror=_walk_error):
            for name in dirs:
                if (Path(parent) / name).is_symlink() or (Path(parent) / name).is_junction():
                    raise AttestationError("Validation policy contains a linked directory")
            for name in files:
                if name.endswith(".py") and (
                    directory.name == "src" or name.startswith("fetch_") or name == "__init__.py"
                ):
                    names.add((Path(parent) / name).relative_to(root).as_posix())
    for name in sorted(names):
        path = root / name
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root):
            raise AttestationError("Validation policy file is unavailable or unsafe")
        yield name, path


def _walk_error(error):
    raise error


def _disk_policy_fingerprint() -> str:
    try:
        files = {}
        for name, path in _policy_inventory():
            with path.open("rb") as stream:
                files[name] = hashlib.file_digest(stream, "sha256").hexdigest()
    except OSError as exc:
        raise AttestationError("Validation policy implementation is unavailable") from exc
    return hashlib.sha256(_json_bytes({"version": 2, "files": files})).hexdigest()


def policy_fingerprint() -> str:
    """Refuse in-place code drift from the policy pinned at package startup."""
    if enabled() and _PROCESS_RUNTIME is None:
        raise AttestationError("Attestation was not enabled at startup; restart the process")
    if _PROCESS_RUNTIME is not None and _runtime_identity() != _PROCESS_RUNTIME:
        raise AttestationError("Validator runtime changed; restart the process")
    if _disk_policy_fingerprint() != _PROCESS_POLICY:
        raise AttestationError("Validation policy changed on disk; restart the process")
    return _PROCESS_POLICY


def _key_bytes(variable):
    configured = os.getenv(variable, "").strip()
    if not configured:
        raise AttestationError("Configured attestation key is unavailable")
    try:
        with Path(configured).open("rb") as stream:
            body = stream.read(16385)
        if len(body) > 16384:
            raise ValueError("oversized key")
        return body
    except (OSError, ValueError) as exc:
        raise AttestationError("Configured attestation key is unreadable") from exc


def _public_key():
    from cryptography.hazmat.primitives.serialization import load_pem_public_key
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    try:
        key = load_pem_public_key(_key_bytes(PUBLIC_KEY_ENV))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("wrong key algorithm")
        return key
    except (ValueError, TypeError) as exc:
        raise AttestationError("Pinned public key must be PEM Ed25519") from exc


def validate_key_locations(store, *, require_private=False):
    variables = (PUBLIC_KEY_ENV, PRIVATE_KEY_ENV) if require_private else (PUBLIC_KEY_ENV,)
    for variable in variables:
        configured = os.getenv(variable, "").strip()
        if not configured:
            raise AttestationError("Producer signing key configuration is incomplete")
        if Path(configured).resolve().is_relative_to(store.root.resolve()):
            raise AttestationError("Attestation keys must be outside the artifact store")


def _private_key(store):
    from cryptography.hazmat.primitives.serialization import (
        load_pem_private_key,
        Encoding,
        PublicFormat,
    )
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    validate_key_locations(store, require_private=True)
    try:
        key = load_pem_private_key(_key_bytes(PRIVATE_KEY_ENV), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("wrong key algorithm")
        actual = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        expected = _public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        if actual != expected:
            raise AttestationError("Producer signing key does not match the pinned public key")
        return key
    except (ValueError, TypeError) as exc:
        raise AttestationError("Producer key must be unencrypted PEM Ed25519") from exc


def _signed(claims, key):
    return {
        "claims": claims,
        "signature": base64.b64encode(key.sign(_json_bytes(claims))).decode("ascii"),
    }


def _verified(envelope, purpose):
    from cryptography.exceptions import InvalidSignature

    try:
        envelope = _plain(envelope)
        if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
            raise ValueError("invalid envelope")
        claims = envelope["claims"]
        if (
            not isinstance(claims, dict)
            or claims.get("schemaVersion") != 1
            or claims.get("purpose") != purpose
        ):
            raise ValueError("invalid signed schema")
        signature = base64.b64decode(envelope["signature"], validate=True)
        if len(signature) != 64:
            raise ValueError("invalid signature length")
        _public_key().verify(signature, _json_bytes(claims))
        return claims
    except (ValueError, TypeError, KeyError, binascii.Error, InvalidSignature) as exc:
        raise AttestationError("Invalid producer attestation") from exc


def _inventory(files):
    return {
        name: {"size": len(body), "sha256": hashlib.sha256(body).hexdigest()}
        for name, body in sorted(files.items())
        if name != CERTIFICATE_FILE
    }


def _immutable_metadata(manifest):
    return {
        name: _plain(value)
        for name, value in manifest.items()
        if name not in _VOLATILE | {"generationId", "files"}
    }


def _runtime_identity():
    """Observed validator runtime versions; not exhaustive native artifact provenance."""
    try:
        return {
            "scope": "serialized-validator-runtime-versions-v1",
            "implementation": sys.implementation.name,
            "version": sys.version,
            "cacheTag": sys.implementation.cache_tag,
            "platform": sys.platform,
            "zlib": zlib.ZLIB_RUNTIME_VERSION,
            "distributions": {
                name: distribution_version(name)
                for name in ("pydantic", "pydantic_core", "cryptography")
            },
        }
    except Exception as exc:
        raise AttestationError("Validator runtime identity unavailable") from exc


def _validation_context(asset, metadata):
    if asset not in ATTESTED_ASSETS:
        raise AttestationError("Unsupported serialized validation owner")
    return {
        "modelVersion": metadata.get("modelVersion"),
        "configHash": metadata.get("configHash"),
        "leagueBinding": _plain(metadata.get("leagueBinding"))
        if asset == "league-serving"
        else None,
    }


def _validate_serialized(candidate, board, cfg):
    if candidate.asset == "canonical-serving":
        from src.serving.serialization import validate_serialized_artifact

        validate_serialized_artifact(candidate)
    elif candidate.asset == "league-serving":
        from src.serving.league_views import validate_serialized_artifact

        validate_serialized_artifact(candidate, board, cfg)
    else:
        raise AttestationError("Unsupported serialized validation owner")


def _current_context(candidate, board, cfg):
    context = _validation_context(candidate.asset, candidate.manifest)
    if candidate.asset == "league-serving":
        from src.serving.league_views import _binding

        if board is None or cfg is None:
            raise AttestationError("League certification requires explicit context")
        if _binding(board, cfg) != context["leagueBinding"]:
            raise AttestationError("League effective configuration changed during certification")
    return context


def _claims(candidate, policy):
    inventory = _inventory(candidate.files)
    metadata = _immutable_metadata(candidate.manifest)
    return {
        "schemaVersion": 1,
        "purpose": "serving-artifact",
        "validationComplete": True,
        "validationScope": "serialized-projection-semantics-v2",
        "rawBuildProvenanceComplete": False,
        "validatorId": candidate.asset + ":strict-serialized-v2",
        "validationContext": _validation_context(candidate.asset, metadata),
        "runtimeIdentity": _runtime_identity(),
        "policyFingerprint": policy,
        "asset": candidate.asset,
        "key": candidate.key,
        "unsignedGenerationId": _identity({**metadata, "files": inventory}),
        "files": inventory,
        "metadata": metadata,
    }


def certify(store, asset, key, files, metadata, validator=None, *, board=None, cfg=None):
    """Validate exact unsigned bytes before certifying; never certify a boolean alone."""
    if not enabled():
        return dict(files)
    if validator is not None and not callable(validator):
        raise AttestationError("Certification requires the full serialized validator")
    unsigned = {name: body for name, body in files.items() if name != CERTIFICATE_FILE}
    candidate, _ = store._candidate(asset, key, unsigned, metadata)
    policy = policy_fingerprint()
    context = _current_context(candidate, board, cfg)
    runtime = _runtime_identity()
    _validate_serialized(candidate, board, cfg)
    if validator is not None and validator(candidate) is False:
        raise RejectedCandidate("Full validation rejected certification")
    if context != _current_context(candidate, board, cfg) or runtime != _runtime_identity():
        raise AttestationError("Validation context/runtime changed during certification")
    if policy != policy_fingerprint():
        raise AttestationError("Validation implementation changed during certification")
    certificate = _signed(_claims(candidate, policy), _private_key(store))
    return {**candidate.files, CERTIFICATE_FILE: _json_bytes(certificate)}


def _timestamp(value, *, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str):
        raise AttestationError("Signed observation timestamp must be qualified")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError("unqualified timestamp")
    except ValueError as exc:
        raise AttestationError("Signed observation timestamp must be qualified") from exc


def observation_signer(store, *, source_as_of):
    """Resolve producer authority before publication/pruning, never in the web reader."""
    _timestamp(source_as_of, optional=True)
    private = _private_key(store)
    policy = policy_fingerprint()

    def sign(asset, key, pointer):
        _timestamp(pointer.get("observedAt"))
        return _signed(
            {
                "schemaVersion": 1,
                "purpose": "serving-observation",
                "asset": asset,
                "key": key,
                "generationId": pointer["generationId"],
                "manifestSha256": pointer["manifestSha256"],
                "sourceAsOf": pointer.get("sourceAsOf"),
                "observedAt": pointer["observedAt"],
                "policyFingerprint": policy,
            },
            private,
        )

    return sign


def verify_artifact(artifact, require_observation=True):
    """Verify content-bound proof using external authority; no semantic recomputation."""
    if not enabled():
        raise AttestationError("An external pinned public key is required")
    try:
        certificate = artifact.files[CERTIFICATE_FILE]
        if len(certificate) > 1024 * 1024:
            raise ValueError("oversized certificate")
        claims = _verified(json.loads(certificate), "serving-artifact")
        expected_claims = _claims(artifact, policy_fingerprint())
        if claims != expected_claims:
            raise AttestationError("Certificate does not bind this artifact and validation policy")
        # Store normally proves this already; retain the check for direct callers
        # and forged in-memory Generation objects used by corruption regressions.
        all_files = {
            **expected_claims["files"],
            CERTIFICATE_FILE: {
                "size": len(certificate),
                "sha256": hashlib.sha256(certificate).hexdigest(),
            },
        }
        if (
            _plain(artifact.manifest.get("files")) != all_files
            or _identity(_plain(artifact.manifest)) != artifact.generation_id
            or artifact.manifest.get("asset") != artifact.asset
            or artifact.manifest.get("key") != artifact.key
        ):
            raise AttestationError("Artifact physical identity does not match its certified files")
        if require_observation:
            verify_observation(artifact, policy=claims["policyFingerprint"])
        return claims
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise AttestationError("Invalid certified serving artifact") from exc


def verify_observation(artifact, *, policy=None):
    """No unsigned pointer timestamp is exposed as verified source freshness."""
    if not enabled() or CERTIFICATE_FILE not in artifact.files:
        raise AttestationError("A certified artifact and pinned public key are required")
    observation = _verified(artifact.observation, "serving-observation")
    _timestamp(observation.get("sourceAsOf"), optional=True)
    _timestamp(observation.get("observedAt"))
    expected = {
        "schemaVersion": 1,
        "purpose": "serving-observation",
        "asset": artifact.asset,
        "key": artifact.key,
        "generationId": artifact.generation_id,
        "manifestSha256": artifact.manifest_sha256,
        "sourceAsOf": artifact.manifest.get("sourceAsOf"),
        "observedAt": artifact.manifest.get("observedAt"),
        "policyFingerprint": policy or policy_fingerprint(),
    }
    if not artifact.manifest_sha256 or observation != expected:
        raise AttestationError("Signed observation does not match the selected artifact")
    return observation


# src.serving.__init__ imports this before builder/serialization/league modules.
# A long-lived producer may not relabel already imported code after deployment.
_PROCESS_RUNTIME = _runtime_identity() if enabled() else None
_PROCESS_POLICY = _disk_policy_fingerprint()
