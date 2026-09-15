"""Soak reports fail honestly on missing samples, regressions and resource growth."""

import ast
import gzip
import hashlib
import json
import runpy
import sys
import threading
import time
from types import SimpleNamespace
from pathlib import Path

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
from scripts import soak_prepared_serving as soak


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
    intended_web = ledger.remaining(
        SimpleNamespace(children=lambda recursive: []), exclude={(11, 100)}
    )
    assert intended_web["remainingCount"] == 0
    wrong_creation = ledger.remaining(
        SimpleNamespace(children=lambda recursive: []), exclude={(11, 99)}
    )
    assert wrong_creation["remainingCount"] == 1
    undiscovered = ChildLedger().remaining(
        SimpleNamespace(children=lambda recursive: [processes[11]])
    )
    assert undiscovered["remainingCount"] == 1
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
        {"kind": "refresh", "workerKind": "changed", "exitCode": 0, "publishedGeneration": value}
        for value in ("new", "newer")
    ]
    assert not publication_evidence(events, {"old": 1000})
    assert not publication_evidence(events, {"new": 1})
    assert publication_evidence(events, {"new": 1, "newer": 1})
    assert not publication_evidence([], {"old": 1000})


def test_worker_receipts_do_not_replace_or_veto_publication_events():
    receipt = {"kind": "worker_outcome", "workerKind": "changed", "exitCode": 0}
    publication = {**receipt, "kind": "refresh", "publishedGeneration": "new"}
    assert publication_evidence([receipt, publication], {"new": 1})
    assert not publication_evidence([receipt], {"new": 1})
    assert not publication_evidence([{**publication, "kind": "worker_outcome"}], {"new": 1})


@pytest.mark.parametrize("generation", [None, "", "unseen"])
def test_each_successful_changed_publication_requires_a_known_generation(generation):
    event = {"kind": "refresh", "workerKind": "changed", "exitCode": 0}
    valid = {**event, "publishedGeneration": "new"}
    assert not publication_evidence([valid, event], {"new": 1})
    assert not publication_evidence(
        [valid, {**event, "publishedGeneration": generation}], {"new": 1}
    )


def test_failed_or_unchanged_cycles_cannot_supply_changed_publication_evidence():
    event = {
        "kind": "refresh",
        "workerKind": "changed",
        "exitCode": 0,
        "publishedGeneration": "new",
    }
    failed = {**event, "exitCode": 1}
    unchanged = {**event, "workerKind": "unchanged"}
    assert not publication_evidence([failed, unchanged], {"new": 1})
    assert publication_evidence([event, failed, unchanged], {"new": 1})
    rows, latencies, errors, events = complete_soak_report_inputs()
    errors.append("worker_exit_1")
    report = summarize(
        rows, latencies, 10, errors, events, 2000, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY
    )
    assert report["passed"] is False


def test_remote_fault_control_preserves_runtime_none_error_contract(monkeypatch):
    runtime = RemoteRuntime(12345)
    monkeypatch.setattr(runtime, "control", lambda action: {"lastError": False})
    assert runtime.last_error is None
    monkeypatch.setattr(runtime, "control", lambda action: {"lastError": True})
    assert runtime.last_error


def test_resource_samples_continue_while_driver_waits(tmp_path):
    rows, errors, timings = [], [], []
    four_samples = threading.Event()

    def observe():
        if len(rows) >= 3:
            four_samples.set()
        return {"seconds": time.monotonic()}

    path = tmp_path / "samples.jsonl"
    with resource_observations(path, observe, rows, errors, interval=0.01, timings=timings):
        # Represents a driver thread blocked waiting on child startup/store IO.
        assert four_samples.wait(timeout=2)
    assert len(rows) >= 4 and not errors
    assert len(path.read_text().splitlines()) == len(rows)
    assert len(timings) == len(rows)
    assert {"observe", "write", "flush", "progress", "schedule", "iteration"} <= set(
        timings[-1]["stages"]
    )
    assert all(row["actualMonotonicSeconds"] >= row["expectedMonotonicSeconds"] for row in timings)


def test_resource_observation_failure_preserves_stage_evidence(tmp_path):
    failed = threading.Event()
    rows, errors, timings = [], [], []

    def observe(timing):
        with timing.stage("tree"):
            failed.set()
            raise OSError("injected")

    with resource_observations(
        tmp_path / "samples.jsonl", observe, rows, errors, timings=timings, timed_observe=True
    ):
        assert failed.wait(timeout=2)
    assert not rows and errors == ["sampling_OSError"]
    assert "tree" in timings[0]["stages"] and "observe" in timings[0]["stages"]


def test_recovery_resource_median_uses_verified_quiet_bounds_not_arbitrary_tail():
    rows = [
        sample(second, rss=300_000_000 if 80 <= second < 100 else 100_000_000)
        for second in range(140)
    ]
    report = summarize(
        rows, {"baseline": [1], "refresh": [1]}, 10, [], [], 2000, quiet_bounds=(80, 99)
    )
    assert report["rssFinalBytes"] == 300_000_000
    assert not report["checks"]["rssGrowthBound"]
    missing = summarize(
        rows,
        {"baseline": [1], "refresh": [1]},
        10,
        [],
        [],
        2000,
        quiet_bounds=(float("inf"), -float("inf")),
    )
    assert missing["rssFinalBytes"] is None
    assert not missing["checks"]["rssGrowthBound"]


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


def test_latency_policy_names_and_default_preserve_legacy_selection():
    assert soak.LEGACY_LATENCY_POLICY == "legacy-relative-v1"
    assert soak.LOCAL_HYBRID_LATENCY_POLICY == "local-prepared-hybrid-v1"
    actual = soak.evaluate_refresh_latency(1, 16)
    assert actual["policy"] == soak.LEGACY_LATENCY_POLICY
    assert actual["legacyRelativePass"] is False and actual["passed"] is False
    assert set(actual) == {
        "policy",
        "observationsValid",
        "baselineMilliseconds",
        "refreshMilliseconds",
        "absoluteMilliseconds",
        "relativePercent",
        "absoluteCeilingPass",
        "relativeBranchPass",
        "absoluteBranchPass",
        "legacyRelativePass",
        "passed",
    }


@pytest.mark.parametrize(
    "baseline,refresh,relative,absolute,ceiling,passed",
    [
        (50, 60, True, False, True, True),  # Relative branch alone, exactly 20%.
        (50, 60.000001, False, False, True, False),
        (1, 16, False, True, True, True),  # Absolute delta exactly 15 ms.
        (1, 16.000001, False, False, True, False),
        (20, 25, False, True, True, True),  # Refresh exactly 25 ms, delta 5 ms.
        (20, 25.000001, False, False, True, False),
        (10, 25, False, True, True, True),  # Both absolute thresholds at once.
        (1, 30, False, False, True, False),
        (10, 11, True, True, True, True),
        (50, 40, True, False, True, True),
        (70, 74.999999, True, False, True, True),
        (70, 75, True, False, False, False),  # 75 ms is a strict ceiling.
        (70, 75.000001, True, False, False, False),
        (100, 50, True, False, True, True),  # Global baseline ceiling is separate.
    ],
)
def test_hybrid_latency_formula_exact_boundaries(
    baseline, refresh, relative, absolute, ceiling, passed
):
    result = soak.evaluate_refresh_latency(
        baseline, refresh, policy=soak.LOCAL_HYBRID_LATENCY_POLICY
    )
    assert result["policy"] == soak.LOCAL_HYBRID_LATENCY_POLICY
    assert result["observationsValid"] is True
    assert result["baselineMilliseconds"] == baseline
    assert result["refreshMilliseconds"] == refresh
    assert result["absoluteMilliseconds"] == pytest.approx(refresh - baseline)
    assert result["relativePercent"] == pytest.approx((refresh - baseline) / baseline * 100)
    assert result["relativeBranchPass"] is relative
    assert result["absoluteBranchPass"] is absolute
    assert result["absoluteCeilingPass"] is ceiling
    assert result["legacyRelativePass"] is relative
    assert result["passed"] is passed


@pytest.mark.parametrize(
    "invalid", [None, float("nan"), float("inf"), -float("inf"), -1, True, False, "1"]
)
@pytest.mark.parametrize("side", ["baseline", "refresh"])
def test_invalid_observations_cannot_pass_either_latency_policy(invalid, side):
    baseline, refresh = (invalid, 1) if side == "baseline" else (1, invalid)
    for policy in (soak.LEGACY_LATENCY_POLICY, soak.LOCAL_HYBRID_LATENCY_POLICY):
        result = soak.evaluate_refresh_latency(baseline, refresh, policy=policy)
        assert result["observationsValid"] is False
        assert result["passed"] is False
        assert not result["absoluteCeilingPass"] and not result["legacyRelativePass"]


@pytest.mark.parametrize(
    "refresh,absolute", [(0, True), (1, True), (15, True), (15.000001, False), (75, False)]
)
def test_zero_baseline_keeps_relative_unavailable_and_absolute_evaluable(refresh, absolute):
    hybrid = soak.evaluate_refresh_latency(0, refresh, policy=soak.LOCAL_HYBRID_LATENCY_POLICY)
    legacy = soak.evaluate_refresh_latency(0, refresh)
    assert hybrid["observationsValid"] is True
    assert hybrid["relativePercent"] is None and hybrid["relativeBranchPass"] is None
    assert hybrid["absoluteBranchPass"] is absolute and hybrid["passed"] is absolute
    assert legacy["relativePercent"] is None and legacy["relativeBranchPass"] is None
    assert legacy["legacyRelativePass"] is (refresh == 0)
    assert legacy["passed"] is (refresh == 0)


def test_unknown_policy_cannot_silently_select_an_acceptance_rule():
    with pytest.raises(ValueError):
        soak.evaluate_refresh_latency(1, 1, policy="unapproved-policy")
    with pytest.raises(ValueError):
        http_latency_summary({}, latency_policy="unapproved-policy")


def complete_soak_report_inputs():
    events = [
        {"kind": name}
        for name in (
            "rejected_candidate_kept_pointer",
            "corrupt_disk_generation_retained_memory",
            "reader_recovered_and_restarted",
            "capacity_exhaustion_kept_pointer",
            "terminated_worker_lease_reacquired_with_queued_requests",
            "restarted_worker_acknowledged_preserved_requests",
        )
    ]
    events.extend(
        {"kind": "refresh_finished", "workerKind": kind, "exitCode": 0}
        for kind in ("changed", "unchanged")
    )
    return (
        [sample(second) for second in range(100)],
        {"baseline": [1] * 100, "refresh": [16] * 100},
        [],
        events,
    )


def test_pooled_policy_selection_keeps_legacy_failure_informational_under_hybrid():
    rows, latencies, errors, events = complete_soak_report_inputs()
    legacy = summarize(rows, latencies, 10, errors, events, 2000)
    explicit = summarize(
        rows, latencies, 10, errors, events, 2000, latency_policy=soak.LEGACY_LATENCY_POLICY
    )
    hybrid = summarize(
        rows, latencies, 10, errors, events, 2000, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY
    )
    assert legacy["checks"] == explicit["checks"] and legacy["passed"] == explicit["passed"]
    assert legacy["latencyPolicy"] == soak.LEGACY_LATENCY_POLICY
    assert hybrid["latencyPolicy"] == soak.LOCAL_HYBRID_LATENCY_POLICY
    assert legacy["checks"]["refreshDegradationAtMost20Percent"] is False
    assert "refreshDegradationAtMost20Percent" not in hybrid["checks"]
    assert hybrid["checks"]["refreshLatencyPolicyPass"] is True
    assert hybrid["legacyLatencyChecks"]["refreshDegradationAtMost20Percent"] is False
    assert legacy["passed"] is False and hybrid["passed"] is True
    assert legacy["p95Milliseconds"] == hybrid["p95Milliseconds"] == {"baseline": 1, "refresh": 16}
    assert hybrid["pooledRefreshLatencyEvaluation"] == soak.evaluate_refresh_latency(
        1, 16, policy=soak.LOCAL_HYBRID_LATENCY_POLICY
    )


@pytest.mark.parametrize("fault", ["rss", "handles", "children", "disk", "errors", "events"])
def test_latency_selector_does_not_change_resource_or_correctness_checks(fault):
    rows, latencies, errors, events = complete_soak_report_inputs()
    if fault == "rss":
        for row in rows[-10:]:
            row["rssBytes"] = 200_000_000
    elif fault == "handles":
        for row in rows[-10:]:
            row["descriptorCount"] = 200
    elif fault == "children":
        rows[-1]["processCount"] = 2
    elif fault == "disk":
        rows[-1]["diskBytes"] = 2001
    elif fault == "errors":
        errors.append("synthetic_response_failure")
    else:
        events.clear()
    legacy = summarize(rows, latencies, 10, errors, events, 2000)
    hybrid = summarize(
        rows, latencies, 10, errors, events, 2000, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY
    )
    resource_checks = set(legacy["checks"]) - {
        "preparedEndpointP95Below75ms",
        "refreshDegradationAtMost20Percent",
    }
    assert {key: legacy["checks"][key] for key in resource_checks} == {
        key: hybrid["checks"][key] for key in resource_checks
    }
    assert not all(hybrid["checks"][key] for key in resource_checks)
    assert legacy["passed"] is False and hybrid["passed"] is False
    for key in (
        "rssBaselineBytes",
        "rssFinalBytes",
        "peakProcessTreeRssBytes",
        "handlesBaseline",
        "handlesFinal",
        "maxProcesses",
        "budgetBytes",
        "diskFinalBytes",
    ):
        assert legacy[key] == hybrid[key]


def test_hybrid_keeps_report_wide_strict_75ms_ceiling_and_missing_observation_failure():
    rows, _, errors, events = complete_soak_report_inputs()
    for baseline, refresh in (
        (75, 50),
        (1, 75),
        (None, 1),
        (1, None),
        (float("inf"), 1),
        (1, float("inf")),
    ):
        latencies = {
            "baseline": [] if baseline is None else [baseline],
            "refresh": [] if refresh is None else [refresh],
        }
        report = summarize(
            rows,
            latencies,
            10,
            errors,
            events,
            2000,
            latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY,
        )
        assert report["passed"] is False
        assert report["checks"]["preparedEndpointP95Below75ms"] is False


def test_http_hybrid_uses_changed_conditional_200_body_baseline_and_legacy_information():
    series = http_series()
    key = "rankings:refresh:conditional:200"
    series["rankings:baseline:unconditional:200"] = [10]
    series["rankings:baseline:conditional:304"] = [2]
    series[key] = [25]
    legacy = http_latency_summary(series)
    explicit_legacy = http_latency_summary(series, latency_policy=soak.LEGACY_LATENCY_POLICY)
    hybrid = http_latency_summary(series, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY)
    assert legacy["latencyPolicy"] == soak.LEGACY_LATENCY_POLICY
    assert legacy["checks"] == explicit_legacy["checks"]
    assert hybrid["latencyPolicy"] == soak.LOCAL_HYBRID_LATENCY_POLICY
    assert hybrid["baselineComparisons"][key] == "rankings:baseline:unconditional:200"
    evaluation = hybrid["refreshLatencyEvaluations"][key]
    assert evaluation["baselineMilliseconds"] == 10
    assert evaluation["absoluteMilliseconds"] == 15
    assert evaluation["relativePercent"] == 150
    assert evaluation["passed"] is True
    assert all(hybrid["checks"].values())
    assert "eachRefreshReadSeriesWithin20Percent" not in hybrid["checks"]
    assert hybrid["checks"]["eachRefreshReadSeriesPassLatencyPolicy"] is True
    assert hybrid["legacyLatencyChecks"]["eachRefreshReadSeriesWithin20Percent"] is False
    assert legacy["checks"]["eachRefreshReadSeriesWithin20Percent"] is False
    assert legacy["p95MillisecondsByReadSeries"] == hybrid["p95MillisecondsByReadSeries"]


def test_one_bad_http_series_cannot_be_hidden_by_pooled_hybrid_success():
    series = {key: [1] * 1000 for key in http_series()}
    bad = "trade:refresh:conditional:304"
    series[bad] = [26]
    pooled = [value for key, values in series.items() if ":refresh:" in key for value in values]
    assert percentile(pooled) == 1
    assert (
        soak.evaluate_refresh_latency(
            1, percentile(pooled), policy=soak.LOCAL_HYBRID_LATENCY_POLICY
        )["passed"]
        is True
    )
    report = http_latency_summary(series, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY)
    assert report["checks"]["eachHttpReadSeriesP95Below75ms"] is True
    assert report["checks"]["eachRefreshReadSeriesPassLatencyPolicy"] is False
    assert report["refreshLatencyEvaluations"][bad]["passed"] is False


@pytest.mark.parametrize("failed_route", [False, True])
def test_live_report_merge_keeps_legacy_informational_and_failed_series_authoritative(failed_route):
    rows, latencies, errors, events = complete_soak_report_inputs()
    report = summarize(
        rows, latencies, 10, errors, events, 2000, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY
    )
    assert report["passed"] is True
    series = {key: [16 if ":refresh:" in key else 1] * 1000 for key in http_series()}
    if failed_route:
        series["trade:refresh:conditional:304"] = [26]
    # Execute the driver's actual merge and final decision without starting its
    # workers, app or sampling loop. Helper-only tests cannot catch a later merge
    # accidentally treating informational legacy failures as acceptance checks.
    source = ast.parse(Path(soak.__file__).read_text(encoding="utf-8"))
    main = next(
        node for node in source.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    start = next(
        index
        for index, node in enumerate(main.body)
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "http_report"
    )
    end = next(
        index
        for index, node in enumerate(main.body[start:], start)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and ast.unparse(node.value.func) == "report['checks'].update"
        and [ast.unparse(argument) for argument in node.value.args] == ["http_report['checks']"]
    )
    final = next(
        node
        for node in main.body[end + 1 :]
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "report['passed']"
    )
    namespace = {
        "report": report,
        "read_series": series,
        "http_latency_summary": http_latency_summary,
        "args": SimpleNamespace(latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY),
    }
    exec(
        compile(
            ast.Module(body=[*main.body[start : end + 1], final], type_ignores=[]),
            "<live-latency-report-merge>",
            "exec",
        ),
        namespace,
    )
    assert report["legacyLatencyChecks"] == {
        "refreshDegradationAtMost20Percent": False,
        "eachRefreshReadSeriesWithin20Percent": False,
    }
    assert not set(report["legacyLatencyChecks"]) & set(report["checks"])
    assert report["checks"]["refreshLatencyPolicyPass"] is True
    assert report["checks"]["eachRefreshReadSeriesPassLatencyPolicy"] is not failed_route
    assert report["passed"] is not failed_route


def test_http_missing_comparison_fails_and_zero_baseline_uses_absolute_branch():
    series = http_series()
    key = "trade:refresh:conditional:304"
    series["trade:baseline:conditional:304"] = []
    missing = http_latency_summary(series, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY)
    assert missing["checks"]["eachRefreshReadSeriesPassLatencyPolicy"] is False
    assert missing["refreshLatencyEvaluations"][key]["observationsValid"] is False
    series["trade:baseline:conditional:304"] = [0]
    series[key] = [15]
    report = http_latency_summary(series, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY)
    assert report["checks"]["eachRefreshReadSeriesPassLatencyPolicy"] is True
    assert report["refreshLatencyEvaluations"][key]["relativePercent"] is None


@pytest.mark.parametrize("count,sufficient", [(0, False), (999, False), (1000, True), (1001, True)])
def test_p99_sample_sufficiency_labels_never_replace_raw_p99(count, sufficient):
    key = "rankings:baseline:unconditional:200"
    series = http_series()
    series[key] = list(range(count))
    for policy in (soak.LEGACY_LATENCY_POLICY, soak.LOCAL_HYBRID_LATENCY_POLICY):
        report = http_latency_summary(series, latency_policy=policy)
        assert report["p99SufficientByReadSeries"][key] is sufficient
        assert report["p99MillisecondsByReadSeries"][key] == percentile(series[key], 0.99)
        assert report["sampleCountsByReadSeries"][key] == count


@pytest.mark.parametrize(
    "invalid", [None, float("nan"), float("inf"), -float("inf"), -1, True, False, "invalid"]
)
def test_invalid_raw_observation_cannot_be_masked_by_an_ordinary_percentile(invalid):
    rows, latencies, errors, events = complete_soak_report_inputs()
    latencies["refresh"] = [1] * 1000 + [invalid]
    series = http_series()
    series["trade:refresh:conditional:304"] = [1] * 1000 + [invalid]
    for policy in (soak.LEGACY_LATENCY_POLICY, soak.LOCAL_HYBRID_LATENCY_POLICY):
        pooled = summarize(rows, latencies, 10, errors, events, 2000, latency_policy=policy)
        individual = http_latency_summary(series, latency_policy=policy)
        assert pooled["checks"]["pooledLatencyObservationsValid"] is False
        assert pooled["passed"] is False
        assert individual["checks"]["httpLatencyObservationsValid"] is False
        assert not all(individual["checks"].values())
        assert pooled["readCounts"]["refresh"] == 1001
        assert individual["sampleCountsByReadSeries"]["trade:refresh:conditional:304"] == 1001
        assert pooled["invalidLatencyObservationCounts"]["refresh"] == 1
        assert (
            individual["invalidLatencyObservationCountsByReadSeries"][
                "trade:refresh:conditional:304"
            ]
            == 1
        )
        assert pooled["p95Milliseconds"]["refresh"] is None
        assert individual["p99MillisecondsByReadSeries"]["trade:refresh:conditional:304"] is None


@pytest.mark.parametrize("missing", list(http_series()))
def test_hybrid_cannot_pass_without_each_required_route_phase_and_status(missing):
    series = http_series()
    del series[missing]
    report = http_latency_summary(series, latency_policy=soak.LOCAL_HYBRID_LATENCY_POLICY)
    assert report["checks"]["requiredHttpReadSeriesObserved"] is False
    assert not all(report["checks"].values())


@pytest.mark.parametrize("explicit", [None, "local-prepared-hybrid-v1", "unapproved-policy"])
def test_latency_cli_default_explicit_hybrid_and_unknown_rejection_without_startup(
    monkeypatch, tmp_path, capsys, explicit
):
    class Parsed(Exception):
        pass

    original = soak.argparse.ArgumentParser.parse_args

    def capture(parser, *args, **kwargs):
        raise Parsed(original(parser, *args, **kwargs))

    arguments = ["soak_prepared_serving.py", "--root", str(tmp_path / "unused")]
    if explicit is not None:
        arguments.extend(["--latency-policy", explicit])
    monkeypatch.setattr(soak.argparse.ArgumentParser, "parse_args", capture)
    monkeypatch.setattr(sys, "argv", arguments)
    monkeypatch.setattr(sys, "path", list(sys.path))
    script = Path(__file__).resolve().parents[2] / "scripts/soak_prepared_serving.py"
    if explicit == "unapproved-policy":
        with pytest.raises(SystemExit) as rejected:
            runpy.run_path(str(script), run_name="__main__")
        assert rejected.value.code == 2
        error = capsys.readouterr().err
        assert "--latency-policy" in error and "invalid choice" in error
    else:
        with pytest.raises(Parsed) as captured:
            runpy.run_path(str(script), run_name="__main__")
        parsed = captured.value.args[0]
        assert parsed.latency_policy == (explicit or soak.LEGACY_LATENCY_POLICY)
        assert parsed.diagnostic_spans is False and parsed.diagnostic_timeline is False
        assert parsed.diagnostic_socket_reads is False
        assert (
            parsed.diagnostic_response_owner == "app" and parsed.diagnostic_reload_observer == "on"
        )
    assert not (tmp_path / "unused").exists()
