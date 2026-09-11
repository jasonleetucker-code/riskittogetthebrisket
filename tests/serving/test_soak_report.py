"""Soak reports fail honestly on missing samples, regressions and resource growth."""

from scripts.soak_prepared_serving import percentile, summarize


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
    assert report["checks"]["preparedByteResponseWithinWarm1s"]
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
