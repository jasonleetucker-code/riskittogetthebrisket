"""Timing and recovery bookkeeping for the private serving harness only."""

from __future__ import annotations

import functools
import hashlib
import json
import math
import threading
import time
from contextlib import contextmanager


def valid_durations(exercise, baseline, refresh, quiet, drain):
    values = (exercise, baseline, refresh, quiet, drain)
    return all(math.isfinite(value) and value > 0 for value in values) and baseline < exercise


def code_provenance(root, *, diagnostic_spans=False):
    paths = [
        "server.py",
        "scripts/soak_prepared_serving.py",
        "scripts/soak_observation.py",
        "src/serving/serialization.py",
        "src/serving/league_views.py",
        "src/serving/runtime.py",
        "src/serving/artifacts.py",
        "src/serving/builder.py",
        "src/serving/projections.py",
    ]
    if diagnostic_spans:
        paths.append("scripts/serving_lab_spans.py")
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}


def wholly_within(row, bounds):
    """Every measured stage must belong to the selected resource interval."""
    return (
        bounds[0] <= row.get("observationStartedSeconds", row["seconds"])
        and row.get("observationFinishedSeconds", row["seconds"]) <= bounds[1]
    )


def maximum_observation_gap(rows, observation_seconds):
    """Full precision acquisition starts and boundaries, never rounded display time."""
    timestamps = [0, *(row["observationStartedSeconds"] for row in rows), observation_seconds]
    return max((right - left for left, right in zip(timestamps, timestamps[1:])), default=None)


def quiet_observations_ready(rows, first_new, now):
    if (
        not rows
        or not rows[-1].get("resourceObservationComplete", False)
        or now - rows[-1]["observationStartedSeconds"] > 2
    ):
        return False
    if any(not row.get("resourceObservationComplete", False) for row in rows[first_new:]):
        return False
    recent = rows[max(0, first_new - 1) :]
    return all(
        right["observationStartedSeconds"] - left["observationStartedSeconds"] <= 2
        for left, right in zip(recent, recent[1:])
    )


class AbsoluteSchedule:
    """One real observation for the latest due tick; skipped ticks stay missing."""

    def __init__(self, origin, interval=1):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("sample interval must be finite and positive")
        self.origin, self.interval = origin, interval
        self.index = self.missed = self.skipped = 0

    def started(self, actual):
        expected = self.origin + self.index * self.interval
        return {
            "tick": self.index,
            "expectedMonotonicSeconds": expected,
            "actualMonotonicSeconds": actual,
            "lateBySeconds": max(0, actual - expected),
            "missedTicksBefore": self.skipped,
            "missedTicksTotal": self.missed,
        }

    def next_delay(self, now):
        next_index = self.index + 1
        latest_due = math.floor((now - self.origin) / self.interval)
        self.index = max(next_index, latest_due)
        self.skipped = self.index - next_index
        self.missed += self.skipped
        return max(0, self.origin + self.index * self.interval - now)


class ObservationTiming:
    """Nested stage totals are inclusive; do not sum them as elapsed time."""

    def __init__(self, clock=time.perf_counter_ns, cpu=time.thread_time_ns):
        self.clock, self.cpu = clock, cpu
        self.stages = {}

    @contextmanager
    def stage(self, name):
        wall, cpu = self.clock(), self.cpu()
        try:
            yield
        finally:
            total = self.stages.setdefault(name, {"wallMs": 0, "threadCpuMs": 0, "calls": 0})
            total["wallMs"] += (self.clock() - wall) / 1_000_000
            total["threadCpuMs"] += (self.cpu() - cpu) / 1_000_000
            total["calls"] += 1

    def snapshot(self):
        return {name: dict(values) for name, values in self.stages.items()}


class ReloadActivity:
    """Track meaningful artifact loads/encoding, excluding unchanged stat polls."""

    def __init__(self):
        self._lock = threading.Lock()
        self._epoch = self._active = 0

    def snapshot(self):
        with self._lock:
            return self._epoch, self._active

    def wrap(self, function):
        @functools.wraps(function)
        def tracked(*args, **kwargs):
            with self._lock:
                self._epoch += 1
                self._active += 1
            try:
                return function(*args, **kwargs)
            finally:
                with self._lock:
                    self._epoch += 1
                    self._active -= 1

        return tracked


def serving_drain_status(store, state, reader, configs, activity, pending_requests):
    """Off-event-loop, bounded pointer checks; never load or validate artifacts."""
    before = activity.snapshot()
    board = state.current
    canonical_version = store.current_version("canonical-serving", "default")
    canonical_ready = (
        board is not None
        and canonical_version is not None
        and state._loaded_version == canonical_version
    )
    versions = []
    leagues_ready = True
    for cfg in configs:
        version = store.current_version("league-serving", cfg.key)
        captured = reader.capture(cfg.key)
        ready = (
            captured is not None
            and version is not None
            and captured[0] is board
            and reader._versions.get(cfg.key) == version
        )
        leagues_ready = leagues_ready and ready
        versions.append((cfg.key, version))
    pending = bool(pending_requests())
    after = activity.snapshot()
    stable = before == after and after[1] == 0 and state.current is board
    token = hashlib.sha256(
        json.dumps((canonical_version, versions, after[0]), sort_keys=True).encode()
    ).hexdigest()
    return {
        "ready": canonical_ready and leagues_ready and stable and not pending,
        "canonicalCaughtUp": canonical_ready,
        "leaguesCaughtUp": leagues_ready,
        "reloadActive": after[1] != 0,
        "requestsPending": pending,
        "continuityToken": token,
    }


class QuietRecovery:
    """Exercise first; then drain and measure an uninterrupted recovery tail."""

    def __init__(self, exercise_seconds, quiet_seconds):
        if not all(
            math.isfinite(value) and value > 0 for value in (exercise_seconds, quiet_seconds)
        ):
            raise ValueError("exercise and quiet durations must be finite and positive")
        self.exercise_seconds, self.quiet_seconds = exercise_seconds, quiet_seconds
        self.phase = "exercise"
        self.admission_closed_at = None
        self.quiet_started_at = None
        self.completed_at = None
        self.resets = 0
        self._token = None

    def admitting(self, elapsed):
        return self.phase == "exercise" and elapsed < self.exercise_seconds

    def advance(
        self, elapsed, *, workers_drained, reloads_drained, token, observation_complete=True
    ):
        if self.phase == "done":
            return self.phase
        if elapsed < self.exercise_seconds:
            return self.phase
        if self.admission_closed_at is None:
            self.admission_closed_at = elapsed
        if not workers_drained:
            phase = "drain_workers"
        elif not reloads_drained or not observation_complete or token is None:
            phase = "drain_reloads"
        else:
            phase = "quiet"
        changed = self._token is not None and token != self._token
        if self.quiet_started_at is not None and (phase != "quiet" or changed):
            self.resets += 1
            self.quiet_started_at = None
        self.phase = phase
        if phase == "quiet":
            if self.quiet_started_at is None:
                self.quiet_started_at = elapsed
            self._token = token
            if elapsed - self.quiet_started_at >= self.quiet_seconds:
                self.phase = "done"
                self.completed_at = elapsed
        return self.phase

    def report(self):
        duration = (
            self.completed_at - self.quiet_started_at
            if self.completed_at is not None and self.quiet_started_at is not None
            else 0
        )
        return {
            "phase": self.phase,
            "exerciseRequiredSeconds": self.exercise_seconds,
            "admissionClosedAtSeconds": self.admission_closed_at,
            "quietStartSeconds": self.quiet_started_at,
            "quietEndSeconds": self.completed_at,
            "verifiedQuietSeconds": duration,
            "quietResetCount": self.resets,
            "verified": self.phase == "done" and duration >= self.quiet_seconds,
        }
