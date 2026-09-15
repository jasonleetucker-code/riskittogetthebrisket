import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from src.serving.artifacts import ArtifactStore, _publish_lock
from src.serving.producer_status import (
    CLAIM_FILE,
    REQUEST_FILE,
    STATUS_FILE,
    ProducerJournal,
    claim_source_refresh,
    pending_source_refresh,
    request_source_refresh,
)
from src.serving.producer import source_parity_contract, source_parity_hash


def test_request_is_queued_and_coalesced_without_touching_running_status(tmp_path):
    store = ArtifactStore(tmp_path)
    (tmp_path / STATUS_FILE).write_text('{"outcome":"running"}', encoding="utf-8")
    first = request_source_refresh(store)
    second = request_source_refresh(store)
    assert first["outcome"] == "queued"
    assert first["requestId"] == second["requestId"]
    assert second["coalesced"] is True
    assert json.loads((tmp_path / STATUS_FILE).read_bytes()) == {"outcome": "running"}
    assert len((tmp_path / REQUEST_FILE).read_bytes()) < 4096


def test_concurrent_requests_have_one_pending_identity(tmp_path):
    store = ArtifactStore(tmp_path)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: request_source_refresh(store), range(12)))
    assert len({result["requestId"] for result in results}) == 1
    assert sum(not result["coalesced"] for result in results) == 1


def test_journal_claims_inside_admitted_cycle_and_later_request_survives(tmp_path):
    store = ArtifactStore(tmp_path)
    request = request_source_refresh(store)
    journal = ProducerJournal(store)
    with _publish_lock(tmp_path / "producer.lock", 0):
        journal.event(
            "producer_started",
            sourceParity=source_parity_contract(),
            sourceParityHash=source_parity_hash(),
        )
        assert pending_source_refresh(store) is None
        assert journal.state["refreshRequest"]["requestId"] == request["requestId"]
        second = request_source_refresh(store)
        journal.event("producer_finished")
    assert pending_source_refresh(store)["requestId"] == second["requestId"]
    assert json.loads((tmp_path / CLAIM_FILE).read_bytes())["outcome"] == "claimed"


def test_malformed_or_oversized_marker_is_acknowledged_without_payload(tmp_path):
    store = ArtifactStore(tmp_path)
    (tmp_path / REQUEST_FILE).write_text("private" * 1000, encoding="utf-8")
    assert pending_source_refresh(store) is None
    with _publish_lock(tmp_path / "producer.lock", 0):
        claim = claim_source_refresh(store)
    assert claim["outcome"] == "invalid_request"
    assert "private" not in json.dumps(claim)
    assert not (tmp_path / REQUEST_FILE).exists()


@pytest.mark.parametrize("trigger", ["", "a" * 41, "cookie=private", "../bad", None])
def test_trigger_is_only_bounded_operational_label(tmp_path, trigger):
    with pytest.raises(ValueError):
        request_source_refresh(ArtifactStore(tmp_path), trigger)
    assert not (tmp_path / REQUEST_FILE).exists()


def test_path_unit_uses_same_service_with_bounded_lease_wait():
    root = Path(__file__).resolve().parents[2] / "deploy/systemd"
    path = (root / "dynasty-source-producer.path.template").read_text(encoding="utf-8")
    service = (root / "dynasty-source-producer.service.template").read_text(encoding="utf-8")
    assert "PathExists=__SERVING_DIR__/source-refresh.request" in path
    assert "Unit=__SERVICE_NAME__-source-producer.service" in path
    assert "--lease-wait-seconds 9000" in service
    assert "TimeoutStartSec=18000" in service
