"""Contract tests for detached value-source capture availability probing."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from urllib.error import HTTPError

import pytest

from src.diagnostics import scrape_telemetry as telemetry

SCRIPT = (
    Path(__file__).resolve().parents[2] / "scripts" / "capture_availability_prober.py"
)


@pytest.fixture
def prober():
    spec = importlib.util.spec_from_file_location("capture_availability_prober_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def temp_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(telemetry, "SAMPLES_PATH", tmp_path / "samples.jsonl")
    monkeypatch.setattr(telemetry, "PHASE_PATH", tmp_path / "phase.json")
    return tmp_path


def test_http_5xx_is_recorded_as_the_original_result(prober, monkeypatch):
    class FailingOpener:
        def open(self, _request, timeout):
            assert timeout == 2
            raise HTTPError("https://example.test/api/health", 503, "unavailable", {}, None)

    monkeypatch.setattr(
        prober.urllib.request, "build_opener", lambda *_args: FailingOpener()
    )
    result = prober.probe_once("https://example.test/api/health", 2)

    assert result["http_status"] == 503
    assert result["failure_kind"] == "http_5xx"
    assert result["latency_ms"] >= 0


def test_capture_phase_records_one_probe_then_stops_without_retrying(
    prober, temp_telemetry, monkeypatch
):
    capture_id = "capture-test"
    telemetry.set_phase("value_source_capture", source="KTC", capture_id=capture_id)
    calls = []

    def fake_probe(url, timeout):
        calls.append((url, timeout))
        telemetry.set_phase("source_start", source="KTC")
        return {
            "probe_started_at": "2026-01-01T00:00:00.000Z",
            "probe_finished_at": "2026-01-01T00:00:00.010Z",
            "http_status": None,
            "latency_ms": 10.0,
            "failure_kind": "timeout",
            "error": "TimeoutError: timed out",
        }

    monkeypatch.setattr(prober, "probe_once", fake_probe)
    monkeypatch.setattr(prober, "_resource_snapshot", lambda _pid: {"target_alive": True})
    assert (
        prober.run(
            capture_id=capture_id,
            target_pid=123,
            probe_url="https://example.test/api/health",
            interval=0,
            max_seconds=1,
        )
        == 0
    )

    rows = [json.loads(line) for line in telemetry.EVENTS_PATH.read_text().splitlines()]
    results = [row for row in rows if row["event"] == "capture_probe_result"]
    assert calls == [("https://example.test/api/health", 2.0)]
    assert len(results) == 1
    assert results[0]["capture_id"] == capture_id
    assert results[0]["failure_kind"] == "timeout"
    assert results[0]["http_status"] is None
    assert results[0]["out_of_process"] is True
    assert rows[-1]["event"] == "capture_probe_stopped"
    assert rows[-1]["reason"] == "capture_phase_ended"
