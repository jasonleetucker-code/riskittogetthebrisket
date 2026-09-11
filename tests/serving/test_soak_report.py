"""Soak reports fail honestly on missing samples, regressions and resource growth."""

import gzip
import hashlib
import json
import sys
import threading
import time
from types import SimpleNamespace

import pytest

from scripts.soak_prepared_serving import (
    ChildLedger,
    RemoteRuntime,
    ResponseAudit,
    http_latency_summary,
    launch,
    percentile,
    publication_evidence,
    resource_observations,
    sampling_evidence,
    summarize,
    TimedEvents,
)


def sample(second, *, rss=100_000_000, handles=100, processes=1):
    return {
        "seconds": second,
        "rssBytes": rss,
        "descriptorCount": handles,
        "processCount": processes,
        "diskBytes": 1000,
    }


def test_missing_baseline_cannot_pass():
    report = summarize([], {"baseline": [], "refresh": []}, 10, [], [], 2000)
    assert not report["passed"]
    assert report["p95Milliseconds"]["baseline"] is None
    assert not report["checks"]["noRemainingObservedChildren"]


def test_latency_regression_fails_without_relaxing_relative_gate():
    rows = [sample(second) for second in range(100)]
    report = summarize(rows, {"baseline": [1] * 100, "refresh": [1.21] * 100}, 10, [], [], 2000)
    assert not report["passed"]
    assert report["checks"]["preparedEndpointP95Below75ms"]
    assert not report["checks"]["refreshDegradationAtMost20Percent"]


def test_post_warmup_growth_and_orphans_fail():
    rows = [sample(second) for second in range(100)]
    rows[-10:] = [sample(second, rss=200_000_000, handles=200) for second in range(90, 100)]
    rows[-1]["processCount"] = 2
    report = summarize(rows, {"baseline": [1], "refresh": [1]}, 10, [], [], 2000)
    assert not report["checks"]["rssGrowthBound"]
    assert not report["checks"]["handlesReturnNearBaseline"]
    assert not report["checks"]["noRemainingObservedChildren"]


def test_percentile_preserves_missing_and_observations():
    assert percentile([]) is None
    assert percentile([1]) == 1
    assert percentile([3, 2, 1]) == 2


def test_exact_75ms_api_target_fails_at_boundary():
    rows = [sample(second) for second in range(100)]
    report = summarize(rows, {"baseline": [75], "refresh": [75]}, 10, [], [], 2000)
    assert not report["checks"]["preparedEndpointP95Below75ms"]


def response(generation="one", *, encoding="gzip"):
    raw = json.dumps(
        {
            "payloadView": "rankings",
            "meta": {"readModelGeneration": generation, "leagueKey": "fixture"},
        }
    ).encode()
    return SimpleNamespace(
        status_code=200,
        body=gzip.compress(raw) if encoding == "gzip" else raw,
        headers={
            "content-encoding": encoding,
            "x-data-generation": generation,
            "x-payload-view": "rankings",
            "etag": hashlib.sha1(raw).hexdigest(),
        },
    )


def test_body_audit_caches_metadata_by_hash_and_stays_bounded():
    audit = ResponseAudit(limit=2)
    first = response()
    audit.check(first, "rankings", "fixture")
    audit.check(first, "rankings", "fixture")
    assert audit.cache_misses == 1
    for generation in ("two", "three"):
        audit.check(response(generation), "rankings", "fixture")
    assert len(audit.cache) == 2
    first.headers["x-data-generation"] = "wrong"
    with pytest.raises(AssertionError, match="body_header_identity_mismatch"):
        audit.check(first, "rankings", "fixture")


def test_conditional_response_cannot_claim_different_generation():
    audit = ResponseAudit()
    first = response()
    conditional = audit.check(first, "rankings", "fixture")
    first.status_code, first.body = 304, b""
    audit.check(first, "rankings", "fixture", conditional)
    first.headers["x-data-generation"] = "two"
    with pytest.raises(AssertionError, match="conditional_generation_mismatch"):
        audit.check(first, "rankings", "fixture", conditional)
    # A canonical transition may correctly answer the old ETag with a new 200.
    audit.check(response("two"), "rankings", "fixture", conditional)


def test_child_ledger_detects_reparenting_without_counting_reused_pid(monkeypatch):
    class Missing(Exception):
        pass

    class Denied(Exception):
        pass

    def child(pid, created):
        return SimpleNamespace(
            pid=pid, create_time=lambda: created, is_running=lambda: True, status=lambda: "running"
        )

    processes = {11: child(11, 100), 12: child(12, 200)}
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            Process=lambda pid: processes[pid],
            NoSuchProcess=Missing,
            AccessDenied=Denied,
            STATUS_ZOMBIE="zombie",
        ),
    )
    ledger = ChildLedger()
    ledger.observe(processes[11])
    ledger.observe(processes[12])
    processes[12] = child(12, 201)
    result = ledger.remaining(SimpleNamespace(children=lambda recursive: []))
    assert result == {
        "observedCount": 2,
        "remainingCount": 1,
        "reparentedCount": 1,
        "unknownCount": 0,
    }
    report = summarize(
        [sample(second) for second in range(100)],
        {"baseline": [1], "refresh": [1]},
        10,
        [],
        [],
        2000,
        children=result,
    )
    assert not report["checks"]["noRemainingObservedChildren"]


def test_web_child_idle_baseline_is_separate_from_worker_overlap():
    rows = [sample(second, processes=2) for second in range(100)]
    rows.append(sample(100, processes=1))
    report = summarize(
        rows,
        {"baseline": [1], "refresh": [1], "postRefreshIdle": [7]},
        10,
        [],
        [],
        2000,
        idle_process_count=2,
    )
    assert report["rssBaselineBytes"] == 100_000_000
    assert report["checks"]["rssGrowthBound"]
    assert report["p95Milliseconds"]["postRefreshIdle"] == 7


def test_long_lived_web_logging_cannot_block_on_an_unread_pipe(monkeypatch, tmp_path):
    import subprocess

    captured = {}

    def popen(command, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(pid=1)

    monkeypatch.setattr(subprocess, "Popen", popen)
    launch(SimpleNamespace(root=tmp_path, budget_bytes=1000, port=12345), "web")
    assert captured["stderr"] == subprocess.DEVNULL


def http_series():
    return {
        f"{view}:{phase}:{kind}:{status}": [1] * 10
        for view in ("rankings", "trade")
        for phase in ("baseline", "refresh", "postRefreshIdle")
        for kind, status in (("unconditional", 200), ("conditional", 304))
    }


def test_http_gates_cannot_hide_one_route_or_quiet_tail_in_pooled_samples():
    series = http_series()
    series["trade:postRefreshIdle:unconditional:200"] = [75]
    assert not http_latency_summary(series)["checks"]["eachHttpReadSeriesP95Below75ms"]
    series = http_series()
    series["trade:refresh:conditional:304"] = [1.21]
    assert not http_latency_summary(series)["checks"]["eachRefreshReadSeriesWithin20Percent"]


def test_missing_quiet_coverage_is_incomplete_and_transition_200_uses_body_baseline():
    series = http_series()
    del series["rankings:postRefreshIdle:conditional:304"]
    assert not http_latency_summary(series)["checks"]["requiredHttpReadSeriesObserved"]
    series = http_series()
    series["rankings:refresh:conditional:200"] = [1.1]
    report = http_latency_summary(series)
    assert all(report["checks"].values())
    assert (
        report["baselineComparisons"]["rankings:refresh:conditional:200"]
        == "rankings:baseline:unconditional:200"
    )


def test_sampling_coverage_and_gap_limits_are_required():
    assert all(sampling_evidence(990, 1000, 2).values())
    assert not all(sampling_evidence(989, 1000, 2).values())
    assert not all(sampling_evidence(1000, 1000, 2.01).values())


def test_changed_publication_requires_actual_http_adoption():
    events = [
        {"workerKind": "changed", "exitCode": 0, "publishedGeneration": "new"},
        {"workerKind": "changed", "exitCode": 0, "publishedGeneration": "newer"},
    ]
    assert not publication_evidence(events, {"old": 1000})
    assert not publication_evidence(events, {"new": 1})
    assert publication_evidence(events, {"new": 1, "newer": 1})
    assert not publication_evidence([], {"old": 1000})


def test_remote_fault_control_preserves_runtime_none_error_contract(monkeypatch):
    runtime = RemoteRuntime(12345)
    monkeypatch.setattr(runtime, "control", lambda action: {"lastError": False})
    assert runtime.last_error is None
    monkeypatch.setattr(runtime, "control", lambda action: {"lastError": True})
    assert runtime.last_error


def test_resource_samples_continue_while_driver_waits(tmp_path):
    rows, errors = [], []
    four_samples = threading.Event()

    def observe():
        if len(rows) >= 3:
            four_samples.set()
        return {"seconds": time.monotonic()}

    path = tmp_path / "samples.jsonl"
    with resource_observations(path, observe, rows, errors, interval=0.01):
        # Represents a driver thread blocked waiting on child startup/store IO.
        assert four_samples.wait(timeout=2)
    assert len(rows) >= 4 and not errors
    assert len(path.read_text().splitlines()) == len(rows)


def test_fault_events_have_elapsed_time_without_payload_content():
    events = TimedEvents(time.monotonic())
    events.append({"kind": "capacity_exhaustion_kept_pointer"})
    assert events[0]["seconds"] >= 0
    assert set(events[0]) == {"kind", "seconds"}


def test_web_resource_identity_must_match_and_missing_is_not_zero(monkeypatch, tmp_path):
    from scripts import soak_prepared_serving as soak

    def process(pid, rss, handles):
        return SimpleNamespace(
            pid=pid,
            create_time=lambda: 42,
            children=lambda recursive: [],
            memory_info=lambda: SimpleNamespace(rss=rss),
            num_handles=lambda: handles,
            num_fds=lambda: handles,
            cpu_times=lambda: SimpleNamespace(user=0, system=0),
        )

    parent, web = process(1, 100, 2), process(2, 200, 4)
    parent.children = lambda recursive: [web]
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        SimpleNamespace(
            Process=lambda pid: web,
            NoSuchProcess=RuntimeError,
            AccessDenied=PermissionError,
            cpu_percent=lambda: 0,
        ),
    )
    observed = soak.sample(parent, tmp_path, time.monotonic(), web_identity=(2, 42))
    assert observed["rssBytes"] == 300
    assert observed["webRssBytes"] == 200
    assert observed["driverDescriptorCount"] == 2
    missing = soak.sample(parent, tmp_path, time.monotonic(), web_identity=(2, 41))
    assert missing["webRssBytes"] is None
    assert not missing["webResourceObservationComplete"]
