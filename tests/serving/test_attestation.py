"""External producer authority binds exact bytes, metadata and observations."""

import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from src.serving import attestation
from src.serving.artifacts import ArtifactStore, RejectedCandidate


@pytest.fixture
def store(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    private = tmp_path / "producer.pem"
    public = tmp_path / "public.pem"
    private.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    public.write_bytes(
        key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
    )
    monkeypatch.setenv(attestation.PUBLIC_KEY_ENV, str(public))
    monkeypatch.setenv(attestation.PRIVATE_KEY_ENV, str(private))
    return ArtifactStore(tmp_path / "store")


def metadata(**changes):
    return {
        "modelVersion": "test-v1",
        "configHash": "factual-scoring",
        # Certificate-unit fixture inputs are external synthetic provenance,
        # not a claim that a local canonical parent artifact exists.
        "inputGenerations": {"fixtureSource": "canonical-board", "roster": "roster-1"},
        "sourceAsOf": "2026-09-12T12:00:00+00:00",
        **changes,
    }


def files():
    raw = b'{"generation":"board-1","scoring":"factual-scoring","value":23}'
    return {
        "full.json": raw,
        "projection.json": raw,
        "projection.gz": gzip.compress(raw, mtime=0),
        "index.json": json.dumps({"etag": hashlib.sha1(raw).hexdigest()}).encode(),
    }


def strict(candidate):
    assert attestation.CERTIFICATE_FILE not in candidate.files
    full = json.loads(candidate.files["full.json"])
    projection = json.loads(candidate.files["projection.json"])
    if full != projection or full["value"] != 23:
        raise ValueError("canonical semantic mismatch")
    if gzip.decompress(candidate.files["projection.gz"]) != candidate.files["projection.json"]:
        raise ValueError("gzip mismatch")
    if (
        json.loads(candidate.files["index.json"])["etag"]
        != hashlib.sha1(candidate.files["projection.json"]).hexdigest()
    ):
        raise ValueError("etag mismatch")


def certified(store, *, meta=None):
    meta = meta or metadata()
    return attestation.certify(store, "canonical-serving", "default", files(), meta, strict)


def publish(store, *, meta=None):
    meta = meta or metadata()
    return store.publish("canonical-serving", "default", certified(store, meta=meta), meta)


def test_exact_unsigned_candidate_is_validated_before_certification(store):
    observed = []

    def validate(candidate):
        strict(candidate)
        observed.append(candidate)

    original = files()
    output = attestation.certify(
        store, "canonical-serving", "default", original, metadata(), validate
    )
    assert len(observed) == 1 and dict(observed[0].files) == original
    assert attestation.CERTIFICATE_FILE not in original
    candidate, _ = store._candidate("canonical-serving", "default", output, metadata())
    claims = attestation.verify_artifact(candidate, require_observation=False)
    assert claims["validationComplete"] is True
    assert claims["unsignedGenerationId"] == observed[0].generation_id
    assert candidate.generation_id != claims["unsignedGenerationId"]
    with pytest.raises(attestation.AttestationError):
        attestation.verify_artifact(candidate)


@pytest.mark.parametrize("reject", [False, "exception", "semantic"])
def test_rejected_full_validation_never_mints_certificate_or_publishes(store, reject):
    def validate(candidate):
        if reject == "exception":
            raise ValueError("injected full validator failure")
        if reject == "semantic":
            strict(candidate)
        return False

    original = files()
    if reject == "semantic":
        wrong = original["full.json"].replace(b"23", b"99")
        original.update(
            {
                "full.json": wrong,
                "projection.json": wrong,
                "projection.gz": gzip.compress(wrong),
                "index.json": json.dumps({"etag": hashlib.sha1(wrong).hexdigest()}).encode(),
            }
        )
    with pytest.raises((RejectedCandidate, ValueError)):
        attestation.certify(store, "canonical-serving", "default", original, metadata(), validate)
    assert not store.root.exists()


@pytest.mark.parametrize(
    "change", ["json", "gzip", "etag", "generation", "scoring", "inputs", "partition", "extra_file"]
)
def test_unsigned_rehash_of_tampered_content_or_identity_is_not_authority(store, change):
    contents = certified(store)
    meta = metadata()
    key = "default"
    if change == "json":
        contents["projection.json"] = contents["projection.json"].replace(b"23", b"99")
    elif change == "gzip":
        contents["projection.gz"] = gzip.compress(b"wrong")
    elif change == "etag":
        contents["index.json"] = b'{"etag":"forged"}'
    elif change == "generation":
        contents["full.json"] = contents["full.json"].replace(b"board-1", b"board-2")
    elif change == "scoring":
        meta["configHash"] = "different-scoring"
    elif change == "inputs":
        meta["inputGenerations"] = {"board": "another-parent"}
    elif change == "partition":
        key = "another-league"
    else:
        contents["unvalidated.json"] = b"{}"
    # Attacker can rewrite every unsigned checksum, manifest and physical id.
    forged, _ = store._candidate("canonical-serving", key, contents, meta)
    with pytest.raises(attestation.AttestationError):
        attestation.verify_artifact(forged, require_observation=False)


def test_artifact_supplied_key_and_forged_certificate_are_never_trusted(store):
    contents = certified(store)
    certificate = json.loads(contents[attestation.CERTIFICATE_FILE])
    attacker = Ed25519PrivateKey.generate()
    body = attestation._json_bytes(certificate["claims"])
    certificate["signature"] = base64.b64encode(attacker.sign(body)).decode()
    contents[attestation.CERTIFICATE_FILE] = attestation._json_bytes(certificate)
    forged, _ = store._candidate("canonical-serving", "default", contents, metadata())
    with pytest.raises(attestation.AttestationError):
        attestation.verify_artifact(forged, require_observation=False)


def test_signed_noop_keeps_content_identity_and_renews_observation(store, monkeypatch):
    monkeypatch.setattr("src.serving.artifacts._now", lambda: "2026-09-12T12:00:00+00:00")
    first = publish(store)
    certificate = first.files[attestation.CERTIFICATE_FILE]
    later = metadata(
        sourceAsOf="2026-09-12T12:10:00+00:00", generatedAt="2026-09-12T12:10:00+00:00"
    )
    monkeypatch.setattr("src.serving.artifacts._now", lambda: "2026-09-12T12:10:00+00:00")
    second = publish(store, meta=later)
    assert first.generation_id == second.generation_id
    assert first.files == second.files and second.files[attestation.CERTIFICATE_FILE] == certificate
    assert first.observation != second.observation
    assert second.manifest_sha256 == first.manifest_sha256
    assert attestation.verify_artifact(store.read_current("canonical-serving", "default"))
    with pytest.raises(TypeError):
        second.observation["claims"]["sourceAsOf"] = "forged"


@pytest.mark.parametrize(
    "change",
    [
        "sourceAsOf",
        "observedAt",
        "signed_claim",
        "signature",
        "missing",
        "physical_id",
        "manifest_hash",
    ],
)
def test_pointer_tamper_never_exposes_forged_freshness(store, change):
    accepted = publish(store)
    path = store.root / "canonical-serving/default/current.json"
    pointer = json.loads(path.read_bytes())
    if change in {"sourceAsOf", "observedAt"}:
        pointer[change] = "2099-01-01T00:00:00+00:00"
    elif change == "signed_claim":
        pointer["observation"]["claims"]["sourceAsOf"] = "2099-01-01T00:00:00+00:00"
    elif change == "signature":
        pointer["observation"]["signature"] = base64.b64encode(b"x" * 64).decode()
    elif change == "missing":
        pointer.pop("observation")
    else:
        altered = (
            replace(accepted, manifest_sha256="f" * 64)
            if change == "manifest_hash"
            else replace(accepted, key="wrong")
        )
        with pytest.raises(attestation.AttestationError):
            attestation.verify_artifact(altered)
        return
    path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(attestation.AttestationError):
        store.read_current("canonical-serving", "default")


def test_public_only_reader_cannot_sign_or_renew(store, monkeypatch):
    accepted = publish(store)
    path = store.root / "canonical-serving/default/current.json"
    original = path.read_bytes()
    monkeypatch.delenv(attestation.PRIVATE_KEY_ENV)
    assert attestation.verify_artifact(store.read_current("canonical-serving", "default"))
    with pytest.raises(attestation.AttestationError):
        certified(store)
    with pytest.raises(attestation.AttestationError):
        store.publish("canonical-serving", "default", accepted.files, metadata())
    assert path.read_bytes() == original


def test_signed_observation_cannot_be_replayed_onto_another_certified_generation(store):
    first = publish(store)
    second = publish(store, meta=metadata(inputGenerations={"fixtureSource": "another-parent"}))
    assert first.generation_id != second.generation_id
    with pytest.raises(attestation.AttestationError, match="observation"):
        attestation.verify_artifact(replace(second, observation=first.observation))


def test_lightweight_verifier_cannot_replace_unsigned_full_validation(store):
    with pytest.raises(attestation.AttestationError):
        attestation.certify(
            store,
            "canonical-serving",
            "default",
            files(),
            metadata(),
            lambda candidate: attestation.verify_artifact(candidate, require_observation=False),
        )
    assert not store.root.exists()


def test_public_only_reader_cannot_pin_an_artifact_owned_key(store, monkeypatch):
    publish(store)
    inside = store.root / "public.pem"
    inside.write_bytes(Path(os.environ[attestation.PUBLIC_KEY_ENV]).read_bytes())
    monkeypatch.delenv(attestation.PRIVATE_KEY_ENV)
    monkeypatch.setenv(attestation.PUBLIC_KEY_ENV, str(inside))
    with pytest.raises(attestation.AttestationError, match="outside"):
        store.read_current("canonical-serving", "default")


def test_configured_target_cannot_publish_without_certificate(store):
    with pytest.raises(attestation.AttestationError):
        store.publish("canonical-serving", "default", files(), metadata())
    assert not store.root.exists()


@pytest.mark.parametrize("stamp", ["bad", "2026-09-12T12:00:00", {}, 4])
def test_malformed_signed_source_age_is_rejected_before_publication(store, stamp):
    with pytest.raises(attestation.AttestationError):
        publish(store, meta=metadata(sourceAsOf=stamp))
    assert not store.root.exists()


def test_unknown_source_age_remains_explicitly_unknown(store):
    accepted = publish(store, meta=metadata(sourceAsOf=None))
    assert attestation.verify_artifact(accepted)
    assert accepted.observation["claims"]["sourceAsOf"] is None


def test_policy_disk_drift_requires_restart_before_signing_or_verifying(store, monkeypatch):
    accepted = publish(store)
    monkeypatch.setattr(attestation, "_disk_policy_fingerprint", lambda: "changed-after-import")
    with pytest.raises(attestation.AttestationError, match="restart"):
        certified(store)
    with pytest.raises(attestation.AttestationError, match="restart"):
        attestation.verify_artifact(accepted)


def test_projection_season_dependency_drift_refuses_signing_and_verification(
    store, tmp_path, monkeypatch
):
    dependency = "src/bdvm/actuals.py"
    replica = tmp_path / "policy"
    for name in {*attestation._POLICY_FILES, dependency}:
        target = replica / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((attestation._REPO / name).read_bytes())
    monkeypatch.setattr(attestation, "_REPO", replica)
    before = attestation._disk_policy_fingerprint()
    monkeypatch.setattr(attestation, "_PROCESS_POLICY", before)
    accepted = publish(store)
    target = replica / dependency
    original = target.read_bytes()
    stamp = target.stat()
    # Change the directly executed season boundary, preserving size and mtime.
    changed = original.replace(b"d.month == 1 else d.year", b"d.month == 2 else d.year")
    assert changed != original and len(changed) == len(original)
    target.write_bytes(changed)
    os.utime(target, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    assert target.stat().st_size == stamp.st_size
    assert target.stat().st_mtime_ns == stamp.st_mtime_ns
    assert attestation._disk_policy_fingerprint() != before
    with pytest.raises(attestation.AttestationError, match="restart"):
        certified(store)
    with pytest.raises(attestation.AttestationError, match="restart"):
        attestation.verify_artifact(accepted)
    # A fresh process pins new code, but old certificates still bind old policy.
    monkeypatch.setattr(attestation, "_PROCESS_POLICY", attestation._disk_policy_fingerprint())
    with pytest.raises(attestation.AttestationError, match="does not bind"):
        attestation.verify_artifact(accepted)
    assert attestation.verify_artifact(publish(store))


@pytest.mark.parametrize(
    "dependency",
    [
        "server.py",
        "src/canonical/player_valuation.py",
        "src/api/confidence.py",
        "src/identity/picks.py",
        "src/utils/name_clean.py",
        "src/canonical/idp_backbone.py",
        "src/league_intel/te_premium.py",
    ],
)
def test_actual_semantic_dependency_content_drift_invalidates_policy(
    tmp_path, monkeypatch, dependency
):
    assert dependency in attestation._POLICY_FILES
    # Copy the real policy inventory; never mutate a concurrently used source.
    replica = tmp_path / "policy"
    for name in attestation._POLICY_FILES:
        copied = replica / name
        copied.parent.mkdir(parents=True, exist_ok=True)
        copied.write_bytes((attestation._REPO / name).read_bytes())
    monkeypatch.setattr(attestation, "_REPO", replica)
    before = attestation._disk_policy_fingerprint()
    monkeypatch.setattr(attestation, "_PROCESS_POLICY", before)
    assert attestation.policy_fingerprint() == before
    target = replica / dependency
    original = target.read_bytes()
    original_stat = target.stat()
    # Same size and modification time still cannot hide a rule/code rewrite.
    target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    os.utime(target, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert target.stat().st_size == original_stat.st_size
    assert target.stat().st_mtime_ns == original_stat.st_mtime_ns
    assert attestation._disk_policy_fingerprint() != before
    with pytest.raises(attestation.AttestationError, match="restart"):
        attestation.policy_fingerprint()


@pytest.mark.parametrize("damage", ["missing", "signature", "sourceAsOf"])
def test_fresh_authorized_noop_repairs_observation_without_resetting_acceptance_age(
    store, monkeypatch, damage
):
    monkeypatch.setattr("src.serving.artifacts._now", lambda: "2026-09-12T12:00:00+00:00")
    first = publish(store)
    partition = store._partition("canonical-serving", "default")
    pointer_path = partition / "current.json"
    accepted_before = (partition / "accepted.json").read_bytes()
    manifest_path = partition / "generations" / first.generation_id / "manifest.json"
    manifest_before = manifest_path.read_bytes()
    pointer = json.loads(pointer_path.read_bytes())
    if damage == "missing":
        pointer.pop("observation")
    elif damage == "signature":
        pointer["observation"]["signature"] = base64.b64encode(b"x" * 64).decode()
    else:
        pointer["sourceAsOf"] = "2026-09-12T13:00:00+00:00"
    pointer_path.write_text(json.dumps(pointer), encoding="utf-8")
    with pytest.raises(attestation.AttestationError):
        store.read_current("canonical-serving", "default")
    monkeypatch.setattr("src.serving.artifacts._now", lambda: "2026-09-12T12:10:00+00:00")
    repaired = publish(store, meta=metadata(sourceAsOf="2026-09-12T12:10:00+00:00"))
    assert repaired.generation_id == first.generation_id
    assert repaired.files == first.files
    assert manifest_path.read_bytes() == manifest_before
    assert (partition / "accepted.json").read_bytes() == accepted_before
    assert repaired.observation != first.observation
    assert attestation.verify_artifact(repaired)
    assert repaired == store.read_current("canonical-serving", "default")


def test_unsigned_default_preserves_full_validator_and_has_no_observation(tmp_path, monkeypatch):
    monkeypatch.delenv(attestation.PUBLIC_KEY_ENV, raising=False)
    monkeypatch.delenv(attestation.PRIVATE_KEY_ENV, raising=False)
    store = ArtifactStore(tmp_path / "store")
    contents = attestation.certify(
        store, "canonical-serving", "default", files(), metadata(), strict
    )
    assert contents == files() and attestation.CERTIFICATE_FILE not in contents
    checked = []

    def validate(candidate):
        strict(candidate)
        checked.append(True)

    accepted = store.publish(
        "canonical-serving", "default", contents, metadata(), validator=validate
    )
    assert checked == [True] and accepted.observation is None
    assert accepted == store.read_current("canonical-serving", "default")
    with pytest.raises(attestation.AttestationError):
        attestation.verify_artifact(accepted)
