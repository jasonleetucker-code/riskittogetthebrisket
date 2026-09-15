"""Deterministic timing and drain tests; no provider, sleep or benchmark."""

from types import SimpleNamespace

import pytest

from scripts.soak_observation import (
    AbsoluteSchedule,
    ObservationTiming,
    QuietRecovery,
    ReloadActivity,
    code_provenance,
    maximum_observation_gap,
    observation_duration_summary,
    quiet_observations_ready,
    serving_drain_status,
    valid_durations,
    wholly_within,
)


def test_overrun_uses_latest_due_tick_without_an_extra_full_sleep():
    schedule = AbsoluteSchedule(100, 1)
    assert schedule.started(100)["lateBySeconds"] == 0
    assert schedule.next_delay(101.7) == 0
    assert schedule.started(101.7)["tick"] == 1
    assert schedule.next_delay(101.8) == pytest.approx(0.2)
    assert schedule.started(102)["tick"] == 2


def test_skipped_ticks_are_explicit_and_never_fabricated():
    schedule = AbsoluteSchedule(0, 1)
    assert schedule.next_delay(3.4) == 0
    row = schedule.started(3.4)
    assert row["tick"] == 3
    assert row["missedTicksBefore"] == row["missedTicksTotal"] == 2
    assert schedule.next_delay(3.5) == 0.5
    assert schedule.started(4)["missedTicksBefore"] == 0


def test_stage_timing_separates_cpu_from_wall_and_records_failures():
    state = {"wall": 0, "cpu": 0}
    timing = ObservationTiming(lambda: state["wall"], lambda: state["cpu"])
    try:
        with timing.stage("flush"):
            state.update(wall=20_000_000, cpu=1_000_000)
            raise OSError("injected")
    except OSError:
        pass
    assert timing.snapshot()["flush"] == {"wallMs": 20, "threadCpuMs": 1, "calls": 1}


def step(protocol, now, *, workers=True, reloads=True, token="same", complete=True):
    return protocol.advance(
        now,
        workers_drained=workers,
        reloads_drained=reloads,
        token=token,
        observation_complete=complete,
    )


def test_late_worker_and_reload_extend_exercise_then_full_quiet_tail():
    protocol = QuietRecovery(3600, 120)
    assert protocol.admitting(3599)
    assert not protocol.admitting(3600)
    assert step(protocol, 3600, workers=False) == "drain_workers"
    assert step(protocol, 3620, reloads=False) == "drain_reloads"
    assert step(protocol, 3630) == "quiet"
    assert step(protocol, 3749) == "quiet"
    assert step(protocol, 3750) == "done"
    assert protocol.report()["verifiedQuietSeconds"] == 120


def test_new_activity_at_quiet_119_seconds_resets_continuity():
    protocol = QuietRecovery(300, 120)
    step(protocol, 300)
    assert step(protocol, 419, token="new-generation") == "quiet"
    assert step(protocol, 420, token="new-generation") == "quiet"
    assert step(protocol, 539, token="new-generation") == "done"
    assert protocol.report()["quietResetCount"] == 1


def test_worker_or_unknown_observation_prevents_quiet_completion():
    protocol = QuietRecovery(300, 120)
    step(protocol, 300)
    assert step(protocol, 419, workers=False) == "drain_workers"
    assert step(protocol, 420, complete=False) == "drain_reloads"
    assert step(protocol, 430) == "quiet"
    assert step(protocol, 549) == "quiet"
    assert not protocol.report()["verified"]


def test_pointer_ahead_and_league_behind_are_pending_even_when_locks_idle():
    board = object()
    versions = {("canonical-serving", "default"): (2, 2), ("league-serving", "main"): (3, 3)}
    store = SimpleNamespace(current_version=lambda asset, key: versions[(asset, key)])
    state = SimpleNamespace(current=board, _loaded_version=(1, 1))
    reader = SimpleNamespace(capture=lambda key: (board, object()), _versions={"main": (2, 2)})
    activity = ReloadActivity()
    kwargs = (store, state, reader, [SimpleNamespace(key="main")], activity, lambda: False)
    assert not serving_drain_status(*kwargs)["ready"]
    state._loaded_version = (2, 2)
    assert not serving_drain_status(*kwargs)["ready"]
    reader._versions["main"] = (3, 3)
    first = serving_drain_status(*kwargs)
    assert first["ready"]
    activity.wrap(lambda: None)()
    second = serving_drain_status(*kwargs)
    assert second["ready"] and second["continuityToken"] != first["continuityToken"]


def test_reload_activity_is_balanced_when_loader_raises():
    activity = ReloadActivity()

    @activity.wrap
    def fail():
        assert activity.snapshot()[1] == 1
        raise ValueError("injected")

    try:
        fail()
    except ValueError:
        pass
    assert activity.snapshot() == (2, 0)


@pytest.mark.parametrize("index", range(5))
@pytest.mark.parametrize("value", [float("nan"), float("inf"), 0, -1])
def test_every_duration_must_be_finite_and_positive(index, value):
    values = [300, 60, 30, 120, 300]
    assert valid_durations(*values)
    values[index] = value
    assert not valid_durations(*values)


def test_code_provenance_detects_same_size_helper_and_product_rewrites(tmp_path):
    paths = [
        "server.py",
        "scripts/soak_prepared_serving.py",
        "scripts/soak_observation.py",
        "src/serving/serialization.py",
        "src/serving/league_views.py",
        "src/serving/runtime.py",
        "src/serving/artifacts.py",
        "src/serving/attestation.py",
        "src/serving/__init__.py",
        "src/serving/coordinator.py",
        "src/serving/builder.py",
        "src/serving/projections.py",
        "scripts/serving_lab_spans.py",
    ]
    for path in paths:
        file = tmp_path / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text("first", encoding="utf-8")
    before = code_provenance(tmp_path)
    assert "scripts/serving_lab_spans.py" not in before
    assert "scripts/serving_lab_spans.py" in code_provenance(tmp_path, diagnostic_spans=True)
    for name in ("scripts/soak_observation.py", "src/serving/serialization.py"):
        (tmp_path / name).write_text("other", encoding="utf-8")
        assert code_provenance(tmp_path)[name] != before[name]


def test_unrounded_acquisition_gaps_and_boundaries_cannot_hide_missing_time():
    rows = [
        {"observationStartedSeconds": 0, "seconds": 1.8},
        {"observationStartedSeconds": 2.0004, "seconds": 2.1},
    ]
    assert maximum_observation_gap(rows, 3) == 2.0004
    assert maximum_observation_gap(rows, 5) == pytest.approx(2.9996)
    assert maximum_observation_gap([{"observationStartedSeconds": 3}], 4) == 3
    assert not wholly_within(
        {"seconds": 301, "observationStartedSeconds": 299.9, "observationFinishedSeconds": 301},
        (300, 420),
    )


def test_quiet_consumes_every_new_sample_and_detects_transient_unknown():
    def row(second, complete=True):
        return {"observationStartedSeconds": second, "resourceObservationComplete": complete}

    rows = [row(400), row(401, False), row(402)]
    assert not quiet_observations_ready(rows, 1, 402.1)
    assert quiet_observations_ready(rows, 3, 402.1)
    assert not quiet_observations_ready([row(400), row(402.0004)], 1, 402.1)
    assert not quiet_observations_ready(rows, 3, 404.0004)
    assert not quiet_observations_ready([row(400, False)], 1, 400.1)


@pytest.mark.parametrize(
    "condition", ["missing_pointer", "old_capture", "queued_request", "active_load"]
)
def test_drain_requires_existing_caught_up_pointers_and_no_pending_work(condition):
    board = object()
    version = (2, 2)
    store = SimpleNamespace(
        current_version=lambda *_: None if condition == "missing_pointer" else version
    )
    state = SimpleNamespace(current=board, _loaded_version=version)
    reader = SimpleNamespace(
        capture=lambda _: (object() if condition == "old_capture" else board, object()),
        _versions={"main": version},
    )
    activity = SimpleNamespace(snapshot=lambda: (2, int(condition == "active_load")))
    assert not serving_drain_status(
        store,
        state,
        reader,
        [SimpleNamespace(key="main")],
        activity,
        lambda: condition == "queued_request",
    )["ready"]


def duration_summary(rows, **overrides):
    options = {
        "requested_exercise_seconds": 300,
        "elapsed_observation_seconds": 450,
        "requested_quiet_seconds": 125,
        "quiet_report": {"verified": True, "verifiedQuietSeconds": 125},
        "last_http_completion_seconds": 449.25,
    }
    options.update(overrides)
    return observation_duration_summary(rows, **options)


def acquisition(start, end):
    return {"observationStartedSeconds": start, "observationFinishedSeconds": end}


def test_duration_summary_separates_requested_elapsed_observed_and_quiet():
    report = duration_summary([acquisition(0, 0.1), acquisition(449, 449.2)])
    assert report["requestedExerciseSeconds"] == report["cappedElapsedExerciseSeconds"] == 300
    assert report["elapsedObservationSeconds"] == 450
    assert report["resourceObservationTimingState"] == "available"
    assert report["resourceObservationFirstStartSeconds"] == 0
    assert report["resourceObservationLastStartSeconds"] == 449
    assert report["resourceObservationLastEndSeconds"] == 449.2
    assert report["resourceObservationSpanSeconds"] == 449.2
    assert report["resourceObservationTerminalGapSeconds"] == pytest.approx(0.8)
    assert report["lastHttpCompletionSeconds"] == 449.25
    assert report["requestedQuietSeconds"] == report["verifiedQuietSeconds"] == 125
    assert "may contain gaps" in report["observationDurationInterpretation"]
    assert "not observed continuous serving" in report["servingExerciseSecondsMeaning"]
    assert not {"passed", "checks", "full60MinuteSoak", "servingExerciseSeconds"} & report.keys()


def test_interrupted_full_run_never_describes_capped_elapsed_as_observed_hour():
    report = duration_summary(
        [acquisition(0, 0.125), acquisition(2999, 2999.719)],
        requested_exercise_seconds=3600,
        elapsed_observation_seconds=5657.719,
        quiet_report={"verified": False, "verifiedQuietSeconds": 0},
        last_http_completion_seconds=3000.016,
    )
    assert report["cappedElapsedExerciseSeconds"] == 3600
    assert report["elapsedObservationSeconds"] == 5657.719
    assert report["resourceObservationSpanSeconds"] == 2999.719
    assert report["resourceObservationLastStartSeconds"] == 2999
    assert report["resourceObservationTerminalGapSeconds"] == pytest.approx(2658)
    assert report["lastHttpCompletionSeconds"] == 3000.016
    assert report["verifiedQuietSeconds"] == 0


def test_internal_suspension_span_does_not_change_gap_or_quiet_gates():
    rows = [acquisition(0, 0.1), acquisition(100, 100.1), acquisition(400, 400.1)]
    before = maximum_observation_gap(rows, 401)
    report = duration_summary(
        rows,
        elapsed_observation_seconds=401,
        quiet_report={"verified": False, "verifiedQuietSeconds": 125},
    )
    assert report["resourceObservationSpanSeconds"] == 400.1
    assert report["verifiedQuietSeconds"] == 0
    assert maximum_observation_gap(rows, 401) == before == 300


def test_missing_resource_or_http_observations_stay_unavailable():
    report = duration_summary([], last_http_completion_seconds=None)
    assert report["resourceObservationTimingState"] == "missing"
    for key in (
        "resourceObservationFirstStartSeconds",
        "resourceObservationLastStartSeconds",
        "resourceObservationLastEndSeconds",
        "resourceObservationSpanSeconds",
        "resourceObservationTerminalGapSeconds",
        "lastHttpCompletionSeconds",
    ):
        assert report[key] is None


@pytest.mark.parametrize(
    "rows",
    [
        [{}],
        [None],
        [acquisition(float("nan"), 1)],
        [acquisition(0, float("inf"))],
        [acquisition(True, 1)],
        [acquisition(-1, 1)],
        [acquisition(2, 1)],
        [acquisition(0, 451)],
        [acquisition(2, 3), acquisition(1, 2)],
        [acquisition(0, 2), acquisition(1, 3)],
    ],
)
def test_invalid_acquisition_bounds_are_not_silently_filtered(rows):
    report = duration_summary(rows)
    assert report["resourceObservationTimingState"] == "invalid"
    assert report["resourceObservationSpanSeconds"] is None
    assert report["resourceObservationTerminalGapSeconds"] is None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, "300"])
def test_invalid_http_completion_stays_unavailable(value):
    assert (
        duration_summary([], last_http_completion_seconds=value)["lastHttpCompletionSeconds"]
        is None
    )


def test_post_cleanup_row_cannot_extend_selected_observation_boundaries():
    rows = [acquisition(0, 0.1), acquisition(449, 449.2)]
    observation_count = len(rows)
    rows.append(acquisition(452, 452.1))
    report = duration_summary(rows[:observation_count])
    assert report["resourceObservationLastEndSeconds"] == 449.2
    assert report["elapsedObservationSeconds"] == 450
    assert duration_summary(rows)["resourceObservationTimingState"] == "invalid"


def test_http_completion_after_observation_stop_keeps_its_actual_boundary():
    # An in-flight response may finish while the driver joins its read thread.
    report = duration_summary([], last_http_completion_seconds=450.25)
    assert report["lastHttpCompletionSeconds"] == 450.25
    assert report["elapsedObservationSeconds"] == 450


@pytest.mark.parametrize(
    "key,value",
    [
        ("requested_exercise_seconds", 0),
        ("requested_exercise_seconds", float("inf")),
        ("requested_quiet_seconds", -1),
        ("requested_quiet_seconds", True),
        ("elapsed_observation_seconds", float("nan")),
        ("elapsed_observation_seconds", -1),
    ],
)
def test_invalid_requested_or_elapsed_duration_is_rejected(key, value):
    with pytest.raises(ValueError, match=key):
        duration_summary([], **{key: value})


def test_zero_elapsed_does_not_fabricate_an_observation():
    report = duration_summary([], elapsed_observation_seconds=0)
    assert report["elapsedObservationSeconds"] == report["cappedElapsedExerciseSeconds"] == 0
    assert report["resourceObservationSpanSeconds"] is None


def test_suspension_during_quiet_requires_a_fresh_complete_tail():
    protocol = QuietRecovery(300, 125)
    step(protocol, 300)
    step(protocol, 419)
    rows = [{"observationStartedSeconds": 419, "resourceObservationComplete": True}]
    complete = quiet_observations_ready(rows, len(rows), 600)
    assert not complete
    assert step(protocol, 600, complete=complete) == "drain_reloads"
    assert protocol.report()["verifiedQuietSeconds"] == 0
    assert step(protocol, 601) == "quiet"
    assert step(protocol, 725) == "quiet"
    assert step(protocol, 726) == "done"
    assert protocol.report()["verifiedQuietSeconds"] == 125
    assert protocol.report()["quietResetCount"] == 1
