from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from src.serving.artifacts import ArtifactStore
from src.serving.producer import (
    MIRROR_FILES,
    SUPPLEMENTAL_SOURCES,
    source_parity_hash,
    source_receipt_ready,
)
from src.serving.producer_status import RECEIPT_FILE, STATUS_FILE, ProducerJournal


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
