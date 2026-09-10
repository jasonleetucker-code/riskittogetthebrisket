import json
from datetime import datetime, timedelta, timezone

import pytest

from src.serving.artifacts import ArtifactStore, _publish_lock
from src.serving.producer_status import STATUS_FILE, request_source_refresh
from src.serving.status import ProducerStatusReader


def test_status_observes_real_lease_and_never_reads_during_snapshot(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / STATUS_FILE).write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "outcome": "running",
                "progress": {"step": "scrape"},
                "providerMessage": "private payload must not be forwarded",
            }
        )
    )
    reader = ProducerStatusReader(store)
    request_source_refresh(store)
    with _publish_lock(store.root / "producer.lock", 0):
        reader.refresh()
        assert reader.snapshot()["running"] is True
    reader.refresh()
    assert reader.snapshot()["status_summary"] == "interrupted"
    assert reader.snapshot()["pendingRefresh"]["outcome"] == "queued"
    assert "private payload" not in json.dumps(reader.snapshot())
    monkeypatch.setattr(
        type(tmp_path), "open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read"))
    )
    assert reader.snapshot()["running"] is False


def test_corrupt_status_marks_observation_unknown_without_claiming_a_live_owner(tmp_path):
    reader = ProducerStatusReader(ArtifactStore(tmp_path))
    (tmp_path / STATUS_FILE).write_text("broken")
    reader.refresh()
    assert reader.snapshot()["status_summary"] == "unknown"
    assert reader.last_error == "JSONDecodeError"


@pytest.mark.parametrize("bad", [{"progress": ["invalid"]}, {"runs": {"wrong": 1}}])
def test_status_shape_failure_recovers_on_the_next_observation(tmp_path, bad):
    path = tmp_path / STATUS_FILE
    path.write_text(json.dumps({"schemaVersion": 1, "outcome": "running", **bad}))
    reader = ProducerStatusReader(ArtifactStore(tmp_path))
    reader.refresh()
    assert reader.snapshot()["status_summary"] == "unknown"
    path.write_text(json.dumps({"schemaVersion": 1, "outcome": "success"}))
    reader.refresh()
    assert reader.snapshot()["status_summary"] == "success"
    assert reader.last_error is None


def test_persisted_run_rate_counts_blocked_as_failure_and_alerts_once(tmp_path):
    now = datetime.now(timezone.utc)
    payload = {
        "schemaVersion": 1,
        "outcome": "blocked",
        "finishedAt": now.isoformat(),
        "runs": [
            {"outcome": "success", "timestamp": now.isoformat(), "duration": 2},
            {"outcome": "blocked", "timestamp": now.isoformat(), "duration": 3},
            {"outcome": "failed", "timestamp": (now - timedelta(days=2)).isoformat()},
        ],
    }
    (tmp_path / STATUS_FILE).write_text(json.dumps(payload))
    alerts = []
    reader = ProducerStatusReader(ArtifactStore(tmp_path), alert=lambda *a: alerts.append(a))
    reader.refresh()
    reader.refresh()
    assert reader.snapshot()["scrape_success_rate_24h"] == {
        "total": 2,
        "success": 1,
        "failure": 1,
        "rate": 0.5,
    }
    assert len(alerts) == 1
