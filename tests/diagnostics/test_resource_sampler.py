"""Pin the out-of-process sampler's contract.

Two properties carry the whole design:

1. It records the *moment the target process dies* — that is the single
   observation nothing inside the dying process can make, and it is what
   distinguishes "dynasty was OOM-killed" from "the whole box wedged
   while dynasty was still alive".
2. It is bounded. A sampler that can outlive its scrape is a process
   leak on a box already short of resources.
"""

from __future__ import annotations

import json
import os

import pytest

from scripts import scrape_resource_sampler as sampler
from src.diagnostics import scrape_telemetry as telemetry


@pytest.fixture
def temp_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(telemetry, "DIAGNOSTICS_DIR", tmp_path)
    monkeypatch.setattr(telemetry, "EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(telemetry, "SAMPLES_PATH", tmp_path / "samples.jsonl")
    monkeypatch.setattr(telemetry, "PHASE_PATH", tmp_path / "phase.json")
    monkeypatch.delenv("RISKIT_SCRAPE_TELEMETRY", raising=False)
    return tmp_path


def _samples(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_sample_carries_every_requested_dimension(temp_telemetry):
    telemetry.set_phase("source_start", source="KTC")
    sample = sampler.build_sample(
        target_pid=os.getpid(), run_id="run-1", prev_cpu=None, prev_tree=None, elapsed=0.0
    )

    # Identity / phase attribution
    assert sample["run_id"] == "run-1"
    assert sample["target_pid"] == os.getpid()
    assert sample["target_alive"] is True
    assert sample["phase"] == "source_start"
    assert sample["phase_source"] == "KTC"
    assert sample["sampler_pid"] == os.getpid()

    # Process-tree split (the app-vs-browser attribution)
    assert sample["app_rss_kb"] > 0
    assert sample["tree_rss_kb"] >= sample["app_rss_kb"]
    assert "chromium_rss_kb" in sample
    assert "chromium_proc_count" in sample

    # System-wide state — the half dynasty itself could never report.
    assert sample["meminfo_kb"]["MemTotal"] > 0
    assert "load1" in sample["loadavg"]
    assert "cpu_total_ticks" in sample


def test_cpu_utilization_needs_two_readings(temp_telemetry):
    """A single /proc/stat reading is cumulative; a rate needs a delta."""
    first = sampler.build_sample(os.getpid(), "r", prev_cpu=None, prev_tree=None, elapsed=0.0)
    assert "cpu_util_pct" not in first

    prev_cpu = {"total": first["cpu_total_ticks"] - 1000, "idle": first["cpu_idle_ticks"] - 400}
    second = sampler.build_sample(os.getpid(), "r", prev_cpu=prev_cpu, prev_tree=None, elapsed=5.0)
    assert 0.0 <= second["cpu_util_pct"] <= 100.0


def test_dead_target_is_reported_not_raised(temp_telemetry):
    sample = sampler.build_sample(0, "run-x", prev_cpu=None, prev_tree=None, elapsed=1.0)
    assert sample["target_alive"] is False
    assert sample["app_rss_kb"] == 0


def test_run_exits_and_marks_the_moment_the_target_vanished(temp_telemetry):
    """The decisive observation: dynasty's PID disappearing."""
    rc = sampler.run(
        target_pid=0,  # never exists
        run_id="run-dead",
        interval=0.01,
        hot_interval=0.01,
        max_seconds=30.0,
        gone_samples_before_exit=3,
    )
    assert rc == 0

    events = [json.loads(line) for line in telemetry.EVENTS_PATH.read_text().splitlines()]
    names = [e["event"] for e in events]
    assert "sampler_started" in names
    assert "target_pid_vanished" in names, "must flag the exact sample where the target died"
    stop = [e for e in events if e["event"] == "sampler_stopped"]
    assert stop and stop[-1]["reason"] == "target_gone"

    rows = _samples(telemetry.SAMPLES_PATH)
    assert len(rows) >= 3
    assert all(r["target_alive"] is False for r in rows)


def test_run_is_bounded_by_max_duration(temp_telemetry):
    """Must stop on its own even while the target stays healthy."""
    rc = sampler.run(
        target_pid=os.getpid(),
        run_id="run-bounded",
        interval=0.01,
        hot_interval=0.01,
        max_seconds=0.2,
        gone_samples_before_exit=1000,
    )
    assert rc == 0
    events = [json.loads(line) for line in telemetry.EVENTS_PATH.read_text().splitlines()]
    stop = [e for e in events if e["event"] == "sampler_stopped"]
    assert stop and stop[-1]["reason"] == "max_duration"


class TestAdaptiveInterval:
    """KTC gets sampled harder — the owner asked for extra attention on
    the phase where every outage has happened."""

    def test_browser_and_ktc_phases_use_the_hot_interval(self):
        assert sampler._interval_for({"phase": "browser"}, 5.0, 2.0) == 2.0
        assert sampler._interval_for({"phase": "source_start"}, 5.0, 2.0) == 2.0
        assert sampler._interval_for({"phase": "other", "source": "KTC"}, 5.0, 2.0) == 2.0

    def test_other_phases_use_the_base_interval(self):
        assert sampler._interval_for({"phase": "bootstrap"}, 5.0, 2.0) == 5.0
        assert sampler._interval_for({}, 5.0, 2.0) == 5.0
