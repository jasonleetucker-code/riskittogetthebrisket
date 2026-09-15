from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.serving.artifacts import (
    ArtifactStore,
    PublishLockTimeout,
    RejectedCandidate,
    _publish_lock,
)
from src.serving.producer import (
    MIRROR_FILES,
    SUPPLEMENTAL_SOURCES,
    source_parity_hash,
    source_receipt_ready,
)
from src.serving.producer_status import RECEIPT_FILE, STATUS_FILE, ProducerJournal
from src.serving.producer_status import (
    OWNERSHIP_ASSET,
    OWNERSHIP_KEY,
    OWNERSHIP_MODEL,
    SourceOwnershipError,
    enforce_source_ownership,
)


@pytest.fixture
def receipt(tmp_path):
    store = ArtifactStore(tmp_path / "private")
    timestamp = datetime.now(timezone.utc).isoformat()
    artifact = store.publish(
        "canonical-serving",
        "default",
        {"input.json": b"{}"},
        {
            "modelVersion": "test",
            "inputGenerations": {"sourceCycle": source_parity_hash()},
            "configHash": "test",
            "sourceAsOf": timestamp,
        },
    )
    result = SimpleNamespace(
        outcome="success",
        source={"producedAt": timestamp},
        duration=1.5,
        player_count=300,
        site_count=2,
        total_sites=2,
        source_evidence={
            "mirrors": [{"file": name, "outcome": "copied"} for name in MIRROR_FILES],
            "core": {
                "script": "Dynasty Scraper.py",
                "completed": True,
                "enabledSites": ["KTC", "IDPTradeCalc"],
            },
            "supplemental": [
                {"source": source, "outcome": "success", "exitCode": 0}
                for source, _, _ in SUPPLEMENTAL_SOURCES
            ],
        },
    )
    journal = ProducerJournal(store)
    journal.accepted_generation = artifact.generation_id
    journal.completed(result)
    return store, journal, result


def mutate(store, change):
    path = store.root / RECEIPT_FILE
    value = json.loads(path.read_bytes())
    change(value)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_ready_requires_current_physical_generation_and_source_parity(receipt):
    store, _, _ = receipt
    assert source_receipt_ready(store)
    mutate(store, lambda value: value.update(acceptedGeneration="logical-board-id"))
    assert not source_receipt_ready(store)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(schemaVersion=2),
        lambda value: value.update(outcome="failed"),
        lambda value: value.update(sourceParityHash="old"),
        lambda value: value["sourceParity"].update(mirrorFiles=[]),
        lambda value: value["sourceEvidence"]["core"].update(completed=False),
        lambda value: value["sourceEvidence"]["supplemental"].pop(),
        lambda value: value["sourceEvidence"]["supplemental"][0].update(
            outcome="failed", exitCode=2
        ),
        lambda value: value["sourceEvidence"]["supplemental"][0].update(
            outcome="skipped", reason="session_missing"
        ),
        lambda value: value.update(sourceProducedAt=None),
        lambda value: value.update(completedAt="malformed"),
    ],
)
def test_incomplete_or_mismatched_source_receipt_cannot_authorize_cutover(receipt, change):
    store, _, _ = receipt
    mutate(store, change)
    assert not source_receipt_ready(store)


def test_idpshow_conditional_skip_can_prove_parity(receipt):
    store, _, _ = receipt
    mutate(
        store,
        lambda value: value["sourceEvidence"]["supplemental"][-1].update(
            outcome="skipped", reason="session_missing"
        ),
    )
    assert source_receipt_ready(store)


def test_unmirrored_available_anchor_file_blocks_cutover(receipt):
    store, _, _ = receipt
    mutate(
        store,
        lambda value: value["sourceEvidence"]["mirrors"][0].update(outcome="destination_missing"),
    )
    assert not source_receipt_ready(store)


@pytest.mark.parametrize("field", ["completedAt", "sourceProducedAt"])
@pytest.mark.parametrize("delta", [timedelta(hours=-5), timedelta(minutes=5)])
def test_stale_or_future_clock_evidence_fails_closed(receipt, field, delta):
    store, _, _ = receipt
    mutate(
        store, lambda value: value.update({field: (datetime.now(timezone.utc) + delta).isoformat()})
    )
    assert not source_receipt_ready(store)


@pytest.mark.parametrize("age", [None, -1, 0, True, float("inf"), float("nan"), "1"])
def test_invalid_age_limit_fails_closed(receipt, age):
    store, _, _ = receipt
    assert not source_receipt_ready(store, max_age_seconds=age)


def test_missing_or_malformed_receipt_is_not_ready(tmp_path):
    store = ArtifactStore(tmp_path)
    assert not source_receipt_ready(store)
    (tmp_path / RECEIPT_FILE).write_text("[", encoding="utf-8")
    assert not source_receipt_ready(store)


def test_new_publication_invalidates_old_receipt(receipt):
    store, _, result = receipt
    store.publish(
        "canonical-serving",
        "default",
        {"input.json": b'{"new":true}'},
        {
            "modelVersion": "test",
            "inputGenerations": {"sourceCycle": source_parity_hash()},
            "configHash": "test",
            "sourceAsOf": result.source["producedAt"],
        },
    )
    assert not source_receipt_ready(store)


def test_failed_cycle_does_not_write_new_success_receipt(receipt):
    store, journal, result = receipt
    before = (store.root / RECEIPT_FILE).read_bytes()
    result.outcome = "failed"
    journal.completed(result)
    assert (store.root / RECEIPT_FILE).read_bytes() == before
    assert json.loads((store.root / STATUS_FILE).read_bytes())["outcome"] == "failed"


def test_private_status_is_bounded_and_excludes_provider_payload(receipt):
    store, journal, _ = receipt
    for index in range(205):
        journal.event(
            f"source_event_{index}", message="private cookie secret", payload={"roster": "private"}
        )
    status = json.loads((store.root / STATUS_FILE).read_bytes())
    assert len(status["events"]) == 200
    assert status["events"][0]["event"] == "source_event_5"
    assert "private cookie" not in json.dumps(status)
    assert "roster" not in json.dumps(status)
    assert not list(store.root.glob("*.tmp"))


def _advance_clock(monkeypatch, hours):
    from src.serving import producer_status

    later = datetime.now(timezone.utc) + timedelta(hours=hours)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return later if tz else later.replace(tzinfo=None)

    monkeypatch.setattr(producer_status, "datetime", Clock)


def test_attested_restart_survives_stale_source_without_faking_freshness(receipt, monkeypatch):
    store, _, _ = receipt
    before = (store.root / RECEIPT_FILE).read_bytes()
    enforce_source_ownership(store)
    proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    _advance_clock(monkeypatch, 5)
    assert not source_receipt_ready(store)
    enforce_source_ownership(store)
    assert store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY).generation_id == proof.generation_id
    assert (store.root / RECEIPT_FILE).read_bytes() == before
    assert not source_receipt_ready(store)


def test_attested_restart_allows_new_accepted_generation(receipt):
    store, _, result = receipt
    enforce_source_ownership(store)
    store.publish(
        "canonical-serving",
        "default",
        {"input.json": b'{"later":true}'},
        {
            "modelVersion": "test",
            "inputGenerations": {"sourceCycle": source_parity_hash()},
            "configHash": "test",
            "sourceAsOf": result.source["producedAt"],
        },
    )
    assert not source_receipt_ready(store)
    enforce_source_ownership(store)


def test_first_cutover_cannot_attest_a_stale_receipt(receipt, monkeypatch):
    store, _, _ = receipt
    _advance_clock(monkeypatch, 5)
    with pytest.raises(SourceOwnershipError, match="healthy current"):
        enforce_source_ownership(store)
    assert not (store.root / OWNERSHIP_ASSET).exists()


def test_first_cutover_cannot_attest_receipt_for_another_current_generation(receipt):
    store, _, result = receipt
    store.publish(
        "canonical-serving",
        "default",
        {"input.json": b'{"later":true}'},
        {
            "modelVersion": "test",
            "inputGenerations": {"sourceCycle": source_parity_hash()},
            "configHash": "test",
            "sourceAsOf": result.source["producedAt"],
        },
    )
    with pytest.raises(SourceOwnershipError, match="healthy current"):
        enforce_source_ownership(store)


def test_absent_proof_and_missing_receipt_refuse_unknown_ownership(tmp_path):
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(ArtifactStore(tmp_path))


def test_corrupt_ownership_proof_cannot_fall_back_to_stale_receipt(receipt, monkeypatch):
    store, _, _ = receipt
    enforce_source_ownership(store)
    proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    path = (
        store.root
        / OWNERSHIP_ASSET
        / OWNERSHIP_KEY
        / "generations"
        / proof.generation_id
        / "files"
        / "receipt.json"
    )
    path.write_bytes(b"{}")
    _advance_clock(monkeypatch, 5)
    assert not source_receipt_ready(store)
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store)


def _replace_proof(store, change, *, model_version=OWNERSHIP_MODEL):
    proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    payload = json.loads(proof.files["receipt.json"])
    change(payload)
    files = {"receipt.json": json.dumps(payload).encode()}
    metadata = {
        "modelVersion": model_version,
        "inputGenerations": {"sourceCycle": source_parity_hash()},
        "configHash": source_parity_hash(),
        "sourceAsOf": payload["sourceProducedAt"],
    }
    if payload.get("acceptedGeneration") == "unverified":
        # Admission rejects this now; seed only the explicitly historical bad
        # state to retain the independent downstream ownership-reader test.
        with pytest.raises(RejectedCandidate):
            store.publish(OWNERSHIP_ASSET, OWNERSHIP_KEY, files, metadata)
        candidate, meta = store._candidate(OWNERSHIP_ASSET, OWNERSHIP_KEY, files, metadata)
        with store._locked():
            return store._publish_unlocked(candidate, meta)
    return store.publish(OWNERSHIP_ASSET, OWNERSHIP_KEY, files, metadata)


@pytest.mark.parametrize(
    "change",
    [
        lambda proof: proof.update(schemaVersion=2),
        lambda proof: proof.update(acceptedGeneration="unverified"),
        lambda proof: proof["sourceEvidence"]["core"].update(completed=False),
        lambda proof: proof["sourceEvidence"]["supplemental"][0].update(
            outcome="failed", exitCode=1
        ),
        lambda proof: proof["sourceEvidence"]["mirrors"].pop(),
        lambda proof: proof.update(
            completedAt=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        ),
    ],
)
def test_checksum_valid_but_invalid_ownership_evidence_is_rejected(receipt, change):
    store, _, _ = receipt
    enforce_source_ownership(store)
    _replace_proof(store, change)
    (store.root / RECEIPT_FILE).unlink()
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store)


def test_unknown_ownership_model_is_rejected(receipt):
    store, _, _ = receipt
    enforce_source_ownership(store)
    _replace_proof(store, lambda _proof: None, model_version="future-model")
    (store.root / RECEIPT_FILE).unlink()
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store)


def test_source_code_drift_invalidates_durable_ownership(receipt, monkeypatch):
    from src.serving import producer

    store, _, _ = receipt
    enforce_source_ownership(store)
    contract = producer.source_parity_contract()
    changed = {**contract, "coreScriptDigest": "changed-script"}
    monkeypatch.setattr(producer, "source_parity_contract", lambda: changed)
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store)


def test_source_policy_renewal_requires_new_exact_healthy_current_receipt(receipt, monkeypatch):
    from src.serving import producer

    store, _, result = receipt
    enforce_source_ownership(store)
    old_proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    policy = {**producer.source_parity_contract(), "coreScriptDigest": "new-authorized-source-code"}
    monkeypatch.setattr(producer, "source_parity_contract", lambda: policy)
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store)
    timestamp = datetime.now(timezone.utc).isoformat()
    current = store.publish(
        "canonical-serving",
        "default",
        {"input.json": b'{"newPolicy":true}'},
        {
            "modelVersion": "test",
            "inputGenerations": {"sourceCycle": source_parity_hash()},
            "configHash": "test",
            "sourceAsOf": timestamp,
        },
    )
    journal = ProducerJournal(store)
    journal.accepted_generation = current.generation_id
    result.source = {"producedAt": timestamp}
    journal.completed(result)
    assert source_receipt_ready(store)
    enforce_source_ownership(store)
    proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    assert proof.generation_id != old_proof.generation_id
    assert json.loads(proof.files["receipt.json"])["sourceParity"] == policy
    assert proof.manifest["inputGenerations"]["sourceCycle"] == source_parity_hash()


def test_healthy_current_receipt_can_repair_corrupt_immutable_proof(receipt):
    store, _, _ = receipt
    enforce_source_ownership(store)
    before = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    path = (
        store.root
        / OWNERSHIP_ASSET
        / OWNERSHIP_KEY
        / "generations"
        / before.generation_id
        / "files"
        / "receipt.json"
    )
    path.write_bytes(b"{}")
    assert source_receipt_ready(store)
    enforce_source_ownership(store)
    after = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
    assert after.generation_id != before.generation_id
    assert path.read_bytes() == b"{}", "renewal must not rewrite an immutable generation"
    report = store.read_retention_report()
    assert report["blocked"] and report["deletedCount"] == 0
    assert not report["candidateDependencyBlocked"]


def test_durable_ownership_does_not_replace_current_board_validation(receipt, monkeypatch):
    store, _, _ = receipt
    enforce_source_ownership(store)
    original = store.read_current

    def read(asset, key):
        assert asset == OWNERSHIP_ASSET, "ownership must not impersonate board validation"
        return original(asset, key)

    monkeypatch.setattr(store, "read_current", read)
    enforce_source_ownership(store)


def test_bootstrap_persists_proof_before_releasing_source_lease(receipt, monkeypatch):
    store, _, _ = receipt
    original = store.publish
    checked = []

    def publish(*args, **kwargs):
        with pytest.raises(PublishLockTimeout):
            with _publish_lock(store.root / "producer.lock", 0):
                pytest.fail("source lease released before ownership publication")
        checked.append(True)
        return original(*args, **kwargs)

    monkeypatch.setattr(store, "publish", publish)
    enforce_source_ownership(store)
    assert checked == [True]
    with _publish_lock(store.root / "producer.lock", 0):
        proof = store.read_current(OWNERSHIP_ASSET, OWNERSHIP_KEY)
        assert json.loads(proof.files["receipt.json"])["acceptedGeneration"] == (
            store.read_current("canonical-serving", "default").generation_id
        )


def test_bootstrap_busy_refuses_without_writing_proof_or_receipt(receipt):
    store, _, _ = receipt
    before = (store.root / RECEIPT_FILE).read_bytes()
    with _publish_lock(store.root / "producer.lock", 0):
        with pytest.raises(SourceOwnershipError, match="acquire the source lease"):
            enforce_source_ownership(store, lease_wait_seconds=0)
    assert not (store.root / OWNERSHIP_ASSET).exists()
    assert (store.root / RECEIPT_FILE).read_bytes() == before


def test_bootstrap_checks_current_generation_after_lease_admission(receipt, monkeypatch):
    from src.serving import producer_status

    store, _, result = receipt
    waiting = threading.Event()
    original = producer_status._publish_lock

    def observed_lock(path, timeout):
        waiting.set()
        return original(path, timeout)

    monkeypatch.setattr(producer_status, "_publish_lock", observed_lock)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with _publish_lock(store.root / "producer.lock", 0):
            future = pool.submit(enforce_source_ownership, store)
            assert waiting.wait(1)
            store.publish(
                "canonical-serving",
                "default",
                {"input.json": b'{"newer":true}'},
                {
                    "modelVersion": "test",
                    "inputGenerations": {"sourceCycle": source_parity_hash()},
                    "configHash": "test",
                    "sourceAsOf": result.source["producedAt"],
                },
            )
        with pytest.raises(SourceOwnershipError, match="healthy current"):
            future.result(timeout=3)
    assert not (store.root / OWNERSHIP_ASSET).exists()


def test_attested_stale_restart_does_not_wait_for_active_source_cycle(receipt, monkeypatch):
    store, _, _ = receipt
    enforce_source_ownership(store)
    _advance_clock(monkeypatch, 5)
    with _publish_lock(store.root / "producer.lock", 0):
        enforce_source_ownership(store, lease_wait_seconds=0)
    assert not source_receipt_ready(store)


def test_bootstrap_publication_failure_releases_lease_and_cannot_attest(receipt, monkeypatch):
    store, _, _ = receipt
    original = store.publish

    def fail(*_args, **_kwargs):
        raise OSError("proof disk write failed")

    monkeypatch.setattr(store, "publish", fail)
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store)
    assert not (store.root / OWNERSHIP_ASSET).exists()
    with _publish_lock(store.root / "producer.lock", 0):
        assert source_receipt_ready(store)
    monkeypatch.setattr(store, "publish", original)
    enforce_source_ownership(store)


@pytest.mark.parametrize("wait", [None, -1, 31, True, float("inf"), float("nan"), "1"])
def test_bootstrap_lease_wait_is_bounded(receipt, wait):
    store, _, _ = receipt
    with pytest.raises(SourceOwnershipError):
        enforce_source_ownership(store, lease_wait_seconds=wait)
    assert not (store.root / OWNERSHIP_ASSET).exists()
