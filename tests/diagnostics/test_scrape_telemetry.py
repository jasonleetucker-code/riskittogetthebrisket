"""Pin the durable telemetry writer's contract.

The whole point of this module is to still have evidence after the
dynasty process is killed, so the properties that matter are: it writes
promptly, it cannot grow without bound, and — above all — it can never
raise into the scrape that calls it.
"""

from __future__ import annotations

import json

import pytest

from src.diagnostics import scrape_telemetry as telemetry


@pytest.fixture
def temp_telemetry(tmp_path, monkeypatch):
    """Redirect every telemetry path into a tmpdir."""
    monkeypatch.setattr(telemetry, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "EVENTS_PATH", tmp_path / "scrape_events.jsonl")
    monkeypatch.setattr(telemetry, "SAMPLES_PATH", tmp_path / "scrape_samples.jsonl")
    monkeypatch.setattr(telemetry, "PHASE_PATH", tmp_path / "scrape_phase.json")
    monkeypatch.delenv("RISKIT_SCRAPE_TELEMETRY", raising=False)
    return tmp_path


def test_record_appends_parseable_jsonl(temp_telemetry):
    telemetry.record("scrape_start_marker", worker_id="run-1", trigger="test")
    telemetry.record("ktc_step", step="goto_start")

    rows = [json.loads(line) for line in telemetry.EVENTS_PATH.read_text().splitlines()]
    assert [r["event"] for r in rows] == ["scrape_start_marker", "ktc_step"]
    assert rows[0]["worker_id"] == "run-1"
    assert rows[1]["step"] == "goto_start"
    assert all(r.get("ts") for r in rows)


def test_written_lines_are_flushed_immediately(temp_telemetry):
    """A buffered line is a lost line when the process is SIGKILLed.

    Reading the file from a separate handle right after the call proves
    the bytes already left the writer.
    """
    telemetry.record("scrape_start_marker")
    assert telemetry.EVENTS_PATH.read_text().strip() != ""


def test_kill_switch_suppresses_all_writes(temp_telemetry, monkeypatch):
    monkeypatch.setenv("RISKIT_SCRAPE_TELEMETRY", "0")
    telemetry.record("scrape_start_marker")
    telemetry.set_phase("browser", source="KTC")
    assert not telemetry.EVENTS_PATH.exists()
    assert not telemetry.PHASE_PATH.exists()


def test_record_never_raises_on_a_serialization_failure(temp_telemetry):
    """Drives the writer's OUTER exception handler specifically.

    Worth stating why this test exists separately from the unwritable-path
    one: that test is satisfied by ``_ensure_dir``'s own OSError guard and
    returns before the write, so it never exercises the outer
    ``except Exception``. Verified by sabotage — making the outer handler
    re-raise left the whole suite green. A circular reference makes
    ``json.dumps`` raise ValueError *past* every inner guard, which is the
    only thing that actually pins the outer one.
    """
    circular: dict = {}
    circular["self"] = circular

    telemetry.record("circular_payload", meta=circular)  # must not raise

    # The bad line is dropped rather than half-written.
    assert telemetry.tail_jsonl(telemetry.EVENTS_PATH, 10) == []


def test_record_never_raises_when_path_is_unwritable(tmp_path, monkeypatch):
    """The critical property: instrumentation must not break the scrape.

    Points the writer at a path whose parent is a FILE, so every mkdir
    and open against it fails.
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    monkeypatch.setattr(telemetry, "DIAGNOSTICS_DIR", blocker / "nested")
    monkeypatch.setattr(telemetry, "EVENTS_PATH", blocker / "nested" / "events.jsonl")
    monkeypatch.setattr(telemetry, "PHASE_PATH", blocker / "nested" / "phase.json")
    monkeypatch.delenv("RISKIT_SCRAPE_TELEMETRY", raising=False)

    telemetry.record("scrape_start_marker")  # must not raise
    telemetry.set_phase("browser")  # must not raise
    assert telemetry.read_phase() == {}


def test_record_never_raises_on_unserializable_payload(temp_telemetry):
    class Exotic:
        def __repr__(self) -> str:
            return "<exotic>"

    telemetry.record("weird", obj=Exotic())
    rows = [json.loads(line) for line in telemetry.EVENTS_PATH.read_text().splitlines()]
    assert rows[0]["obj"] == "<exotic>"


def test_rotation_caps_file_growth(temp_telemetry, monkeypatch):
    monkeypatch.setattr(telemetry, "MAX_BYTES", 200)
    for i in range(80):
        telemetry.record("filler", index=i, padding="x" * 50)

    rotated = telemetry.EVENTS_PATH.with_suffix(telemetry.EVENTS_PATH.suffix + ".1")
    assert rotated.exists(), "expected a rotated generation once the cap was passed"
    assert telemetry.EVENTS_PATH.stat().st_size <= telemetry.MAX_BYTES + 1024


def test_phase_round_trips_for_the_out_of_process_sampler(temp_telemetry):
    telemetry.set_phase("source_start", source="KTC", worker_id="run-9")
    phase = telemetry.read_phase()
    assert phase["phase"] == "source_start"
    assert phase["source"] == "KTC"
    assert phase["worker_id"] == "run-9"


def test_tail_skips_a_torn_final_line(temp_telemetry):
    """A killed writer can leave a half-written line; it must not poison
    the whole read."""
    telemetry.record("good_one")
    with open(telemetry.EVENTS_PATH, "a", encoding="utf-8") as fh:
        fh.write('{"event": "torn", "unterminated": ')

    rows = telemetry.tail_jsonl(telemetry.EVENTS_PATH, 50)
    assert [r["event"] for r in rows] == ["good_one"]


def test_tail_returns_empty_for_missing_file(temp_telemetry):
    assert telemetry.tail_jsonl(temp_telemetry / "nope.jsonl", 10) == []
