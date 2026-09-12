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
from datetime import datetime
from pathlib import Path

from src.serving.artifacts import CorruptArtifact, RejectedCandidate, _identity, _json_bytes, _plain

PUBLIC_KEY_ENV = "RISKIT_SERVING_ATTESTATION_PUBLIC_KEY"
PRIVATE_KEY_ENV = "RISKIT_SERVING_ATTESTATION_PRIVATE_KEY"
CERTIFICATE_FILE = "validation.json"
ATTESTED_ASSETS = frozenset({"canonical-serving", "league-serving"})
_REPO = Path(__file__).resolve().parents[2]
_POLICY_FILES = (
    "server.py",
    "src/serving/__init__.py",
    "src/serving/attestation.py",
    "src/serving/artifacts.py",
    "src/serving/runtime.py",
    "src/serving/serialization.py",
    "src/serving/league_views.py",
    "src/serving/builder.py",
    "src/serving/projections.py",
    "src/serving/coordinator.py",
    "src/serving/input_manifest.py",
    "src/api/compact_view.py",
    "src/api/data_contract.py",
    "src/api/sleeper_overlay.py",
    "src/api/league_registry.py",
    "src/bdvm/actuals.py",
    "src/data_models/contracts.py",
    "src/league_comparison/sleeper_scoring.py",
    "src/ros/lineup.py",
    "src/canonical/player_valuation.py",
    "src/canonical/tail_policy.py",
    "src/api/confidence.py",
    "src/picks/site_pick_map.py",
    "src/identity/picks.py",
    "src/utils/name_clean.py",
    "src/canonical/idp_backbone.py",
    "src/canonical/rank_coordinates.py",
    "src/bridges/assess.py",
    "src/bridges/states.py",
    "src/bridges/ladder.py",
    "src/bridges/registry.py",
    "src/bridges/descriptor.py",
    "src/utils/config_loader.py",
    "src/sources/acquisition_state.py",
    "src/identity/resolution.py",
    "src/identity/name_primitives.py",
    "src/sources/ktc_value_sources.py",
    "src/api/feature_flags.py",
    "src/league_intel/te_premium.py",
    "src/model_registry/__init__.py",
    "src/model_registry/versioning.py",
)
_VOLATILE = frozenset({"generatedAt", "sourceAsOf", "observedAt"})


class AttestationError(CorruptArtifact):
    """Missing, mismatched or invalid producer evidence."""


def enabled() -> bool:
    public = bool(os.getenv(PUBLIC_KEY_ENV, "").strip())
    if not public and os.getenv(PRIVATE_KEY_ENV, "").strip():
        raise AttestationError("Signing requires an externally pinned public key")
    return public


def _disk_policy_fingerprint() -> str:
    try:
        files = {
            name: hashlib.sha256((_REPO / name).read_bytes()).hexdigest() for name in _POLICY_FILES
        }
    except OSError as exc:
        raise AttestationError("Validation policy implementation is unavailable") from exc
    return hashlib.sha256(_json_bytes({"version": 1, "files": files})).hexdigest()


def policy_fingerprint() -> str:
    """Refuse in-place code drift from the policy pinned at package startup."""
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


def _claims(candidate, policy):
    inventory = _inventory(candidate.files)
    metadata = _immutable_metadata(candidate.manifest)
    return {
        "schemaVersion": 1,
        "purpose": "serving-artifact",
        "validationComplete": True,
        "policyFingerprint": policy,
        "asset": candidate.asset,
        "key": candidate.key,
        "unsignedGenerationId": _identity({**metadata, "files": inventory}),
        "files": inventory,
        "metadata": metadata,
    }


def certify(store, asset, key, files, metadata, validator):
    """Validate exact unsigned bytes before certifying; never certify a boolean alone."""
    if not enabled():
        return dict(files)
    if not callable(validator):
        raise AttestationError("Certification requires the full serialized validator")
    unsigned = {name: body for name, body in files.items() if name != CERTIFICATE_FILE}
    candidate, _ = store._candidate(asset, key, unsigned, metadata)
    policy = policy_fingerprint()
    if validator(candidate) is False:
        raise RejectedCandidate("Full validation rejected certification")
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
_PROCESS_POLICY = _disk_policy_fingerprint()
