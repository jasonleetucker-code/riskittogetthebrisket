"""Pin how server.py is wired to the telemetry owner.

The instrumentation sits on the scrape's critical path, so the property
that matters most is negative: with the sink broken, disabled, or absent,
``_record_scrape_event`` must still behave exactly as it did before.
"""

from __future__ import annotations

import json

import pytest

import server
from src.diagnostics import proc_probe
from src.diagnostics import scrape_telemetry as telemetry


@pytest.fixture
def temp_telemetry(tmp_path, monkeypatch):
    monkeypatch.setitem(server.scrape_status, "run_events", [])
    monkeypatch.setattr(telemetry, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(telemetry, "SAMPLES_PATH", tmp_path / "samples.jsonl")
    monkeypatch.setattr(telemetry, "PHASE_PATH", tmp_path / "phase.json")
    monkeypatch.delenv("RISKIT_SCRAPE_TELEMETRY", raising=False)
    return tmp_path


def test_scrape_events_reach_the_durable_sink(temp_telemetry):
    server._record_scrape_event("scrape_started", message="trigger=test", trigger="test")

    rows = [json.loads(line) for line in telemetry.EVENTS_PATH.read_text().splitlines()]
    assert rows[-1]["event"] == "scrape_started"
    assert rows[-1]["message"] == "trigger=test"
    assert rows[-1]["meta"]["trigger"] == "test"


def test_in_memory_run_events_still_populated(temp_telemetry):
    """The durable sink is a MIRROR — it must not replace the existing
    in-memory ring buffer that /api/status serves."""
    before = len(server.scrape_status.get("run_events") or [])
    server._record_scrape_event("phase_start", message="mirrored")
    after = server.scrape_status.get("run_events") or []
    assert len(after) == before + 1
    assert after[-1]["event"] == "phase_start"


def test_record_scrape_event_survives_a_broken_sink(tmp_path, monkeypatch):
    """Instrumentation must never be able to break a scrape."""
    blocker = tmp_path / "file-not-dir"
    blocker.write_text("x")
    monkeypatch.setattr(telemetry, "DIAGNOSTICS_DIR", blocker / "nested")
    monkeypatch.setattr(telemetry, "EVENTS_PATH", blocker / "nested" / "events.jsonl")
    monkeypatch.setattr(telemetry, "PHASE_PATH", blocker / "nested" / "phase.json")

    server._record_scrape_event("phase_start", message="still fine")
    assert (server.scrape_status.get("run_events") or [])[-1]["event"] == "phase_start"


def test_record_scrape_event_survives_the_kill_switch(temp_telemetry, monkeypatch):
    monkeypatch.setenv("RISKIT_SCRAPE_TELEMETRY", "0")
    server._record_scrape_event("phase_start", message="switched off")
    assert not telemetry.EVENTS_PATH.exists()
    assert (server.scrape_status.get("run_events") or [])[-1]["event"] == "phase_start"


def test_progress_update_publishes_phase_for_the_sampler(temp_telemetry):
    server._update_scrape_progress(step="source_start", source="KTC", event=None)
    phase = telemetry.read_phase()
    assert phase["phase"] == "source_start"
    assert phase["source"] == "KTC"


class TestProcHelperDelegation:
    """server.py must not keep a second copy of the /proc walk.

    The sampler cannot import server.py (it has to outlive it), so the
    primitives live in src/diagnostics/proc_probe.py and server.py is an
    adapter. If someone re-inlines them here, the two copies drift and
    the reaper and the sampler stop agreeing about what a Chromium
    process is — with the reaper being the one that sends SIGKILL.
    """

    def test_server_delegates_to_the_shared_owner(self):
        assert server._collect_descendant_pids is proc_probe.collect_descendant_pids
        assert server._looks_like_playwright_chromium is proc_probe.looks_like_playwright_chromium

    def test_reaper_still_finds_and_skips_a_non_chromium_child(self):
        """The reaper's safety property: it only kills what the predicate
        accepts. A plain python child must survive a reap sweep."""
        import subprocess
        import sys
        import time

        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            deadline = time.time() + 5
            while time.time() < deadline and child.poll() is None:
                if child.pid in server._collect_descendant_pids(__import__("os").getpid()):
                    break
                time.sleep(0.05)

            killed = server._reap_orphan_browsers()
            assert killed == 0, "a non-Chromium child must never be reaped"
            assert child.poll() is None, "reaper killed an unrelated process"
        finally:
            child.kill()
            child.wait(timeout=5)
