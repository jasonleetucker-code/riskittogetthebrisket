"""Offline, private-store resource soak; never starts providers or production units.

Uses actual ArtifactStore, AtomicRuntime, LeagueServingReader and prepared
rankings/trade endpoints over loopback HTTP, including app middleware and a
synthetic auth session. League selection and application lifespan are fixtures.
Install psutil only in an isolated lab environment; it is not a serving dependency.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import http.client
import itertools
import json
import math
import os
import platform
import random
import socket
import statistics
import subprocess
import sys
import threading
import time
import uuid
from collections import Counter, OrderedDict
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


def percentile(values, fraction=0.95):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


@contextmanager
def prevent_automatic_sleep():
    """Keep this Windows measurement awake, without changing saved power policy."""
    if os.name != "nt":
        yield
        return
    import ctypes

    execution_state = ctypes.windll.kernel32.SetThreadExecutionState
    execution_state.argtypes = [ctypes.c_uint]
    execution_state.restype = ctypes.c_uint
    if not execution_state(0x80000001):  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
        raise OSError("Could not request temporary automatic-sleep prevention")
    try:
        yield
    finally:
        execution_state(0x80000000)


class TimedEvents(list):
    def __init__(self, started):
        super().__init__()
        self.started = started

    def append(self, event):
        super().append({**event, "seconds": round(time.monotonic() - self.started, 3)})


@contextmanager
def resource_observations(
    path, observe, rows, errors, interval=1, progress=None, *, timings=None, timed_observe=False
):
    """Sample outside driver publication/child-start waits; never fill missed ticks."""
    done = threading.Event()

    def collect():
        try:
            with path.open("w", encoding="utf-8") as stream:
                schedule = AbsoluteSchedule(time.monotonic(), interval)
                while not done.is_set():
                    timing = ObservationTiming()
                    actual = time.monotonic()
                    driver_cpu = time.process_time_ns()
                    observation = schedule.started(actual)
                    try:
                        with timing.stage("iteration"):
                            with timing.stage("observe"):
                                row = observe(timing) if timed_observe else observe()
                            rows.append(row)
                            with timing.stage("write"):
                                stream.write(json.dumps(row) + "\n")
                            with timing.stage("flush"):
                                stream.flush()
                            with timing.stage("progress"):
                                if len(rows) % 60 == 0:
                                    print(
                                        json.dumps(
                                            {
                                                "seconds": row["seconds"],
                                                "samples": len(rows),
                                                "errors": len(errors),
                                                **(progress() if progress else {}),
                                            }
                                        ),
                                        flush=True,
                                    )
                    finally:
                        # Keep completed IO/flush timings in memory; serialize
                        # this small diagnostic ledger after observation ends.
                        # No second synchronous log write is hidden per tick.
                        observation.update(
                            finishedMonotonicSeconds=time.monotonic(),
                            driverProcessCpuMs=(time.process_time_ns() - driver_cpu) / 1_000_000,
                            stages=timing.snapshot(),
                        )
                        if timings is not None:
                            timings.append(observation)
                    with timing.stage("schedule"):
                        delay = schedule.next_delay(time.monotonic())
                    observation["stages"] = timing.snapshot()
                    observation["requestedWaitSeconds"] = delay
                    observation["missedTicksAfter"] = schedule.skipped
                    done.wait(delay)
        except Exception as exc:
            errors.append(f"sampling_{type(exc).__name__}")

    thread = threading.Thread(target=collect, name="soak-resources", daemon=True)
    thread.start()
    try:
        yield
    finally:
        done.set()
        thread.join(timeout=5)
        if thread.is_alive():
            errors.append("resource_sampler_stop_timeout")


def disable_network(loopback_port=None):
    import socket

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex

    def guard(original):
        def connect(sock, address):
            if (
                loopback_port is not None
                and isinstance(address, tuple)
                and address[:2] == ("127.0.0.1", loopback_port)
            ):
                return original(sock, address)
            raise RuntimeError("external network disabled in offline serving soak")

        return connect

    socket.socket.connect = guard(original_connect)
    socket.socket.connect_ex = guard(original_connect_ex)


def store_for(root, budget):
    from src.serving.artifacts import ArtifactStore, RetentionPolicy

    return ArtifactStore(root, retention_policy=RetentionPolicy(max_bytes=budget))


WORKER_RECEIPT_PREFIX = "SOAK_WORKER_OUTCOME_V1 "
WORKER_RECEIPT_LIMIT = 8192
WORKER_RECEIPT_COUNT_LIMIT = 1024
WORKER_STAGES = frozenset(
    {
        "initialize",
        "source_admission",
        "source_claim",
        "canonical_read",
        "canonical_deserialize",
        "canonical_prepare",
        "canonical_publish",
        "canonical_identity_check",
        "league_admission",
        "league_claim",
        "league_board_read",
        "league_prepare",
        "league_publish",
        "league_deferred_queue",
        "complete",
    }
)
_worker_evidence_lock = threading.Lock()


def _safe_worker_class(value):
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 80
        and value.isascii()
        and all(char.isalnum() or char == "_" for char in value)
    )


def _worker_identity(value):
    return (
        isinstance(value, str)
        and len(value) in (32, 40, 64)
        and all(char in "0123456789abcdef" for char in value)
    )


def validate_worker_receipt(record, *, attempt_id, kind, sequence):
    """Strict private-safe terminal protocol; never retain arbitrary stderr fields."""
    required = {
        "schemaVersion",
        "attemptId",
        "workerKind",
        "sequence",
        "outcome",
        "stage",
        "exceptionClass",
        "errno",
        "winerror",
        "canonicalAccepted",
        "acceptedPhysicalGeneration",
        "leagueOutcome",
    }
    if not isinstance(record, dict) or set(record) != required:
        raise ValueError("worker_receipt_schema")
    if (
        type(record["schemaVersion"]) is not int
        or record["schemaVersion"] != 1
        or record["attemptId"] != attempt_id
        or not _worker_identity(attempt_id)
        or record["workerKind"] != kind
        or kind not in {"changed", "unchanged", "league", "hold"}
        or type(record["sequence"]) is not int
        or record["sequence"] != sequence
        or record["outcome"] not in {"success", "failed"}
        or record["stage"] not in WORKER_STAGES
        or type(record["canonicalAccepted"]) is not bool
        or record["leagueOutcome"] not in {"not_started", "running", "success", "failed", "busy"}
        or (
            record["acceptedPhysicalGeneration"] is not None
            and not _worker_identity(record["acceptedPhysicalGeneration"])
        )
        or (record["canonicalAccepted"] != (record["acceptedPhysicalGeneration"] is not None))
        or any(
            record[name] is not None
            and (type(record[name]) is not int or not -(2**31) <= record[name] <= 2**32 - 1)
            for name in ("errno", "winerror")
        )
    ):
        raise ValueError("worker_receipt_identity")
    if record["outcome"] == "success":
        if (
            record["stage"] != "complete"
            or record["exceptionClass"] is not None
            or (kind in {"changed", "unchanged"} and not record["canonicalAccepted"])
            or (kind == "league" and record["leagueOutcome"] != "success")
            or (
                kind in {"changed", "unchanged"}
                and record["leagueOutcome"] not in {"success", "busy"}
            )
        ):
            raise ValueError("worker_receipt_outcome")
    elif not _safe_worker_class(record["exceptionClass"]):
        raise ValueError("worker_receipt_exception")
    return record


class WorkerEvidenceSink:
    """Bounded run-local output; refuse any preexisting sidecar, count in O(1)."""

    def __init__(self, path):
        self.path = path
        self.count = 0
        self.failed = False
        self.lock = threading.Lock()
        with path.open("xb"):
            pass

    def append(self, encoded):
        with self.lock:
            if self.failed or self.count >= WORKER_RECEIPT_COUNT_LIMIT:
                raise ValueError("worker_evidence_count_limit")
            try:
                with self.path.open("ab") as output:
                    output.write(encoded)
                    output.flush()
                self.count += 1
            except OSError:
                self.failed = True
                raise


def worker_evidence_sink(args):
    with _worker_evidence_lock:
        if not hasattr(args, "_worker_evidence_sink"):
            args._worker_evidence_sink = WorkerEvidenceSink(
                args.root.with_name(args.root.name + ".workers.jsonl")
            )
        return args._worker_evidence_sink


class WorkerReceiptCapture:
    """One bounded stderr reader per child; raw log text is discarded immediately."""

    def __init__(self, child, args, kind, sequence, attempt_id):
        self.child = child
        self.kind, self.sequence, self.attempt_id = kind, sequence, attempt_id
        self.sink = worker_evidence_sink(args)
        self.record = None
        self.invalid = False
        self.stderr_bytes = 0
        self.receipt_framing_bytes = 0
        self.final = None
        self.started = time.monotonic()
        self.thread = threading.Thread(target=self._drain, name="soak-worker-outcome", daemon=True)
        self.thread.start()

    def _drain(self):
        try:
            stream = self.child.stderr
            skipping = False
            while True:
                line = stream.readline(WORKER_RECEIPT_LIMIT + 1)
                if not line:
                    break
                self.stderr_bytes += len(line)
                oversized = len(line) > WORKER_RECEIPT_LIMIT
                if not skipping and line.startswith(WORKER_RECEIPT_PREFIX.encode("ascii")):
                    if oversized or not line.endswith(b"\n") or self.record is not None:
                        self.invalid = True
                    else:
                        try:
                            self.record = validate_worker_receipt(
                                json.loads(line[len(WORKER_RECEIPT_PREFIX) :]),
                                attempt_id=self.attempt_id,
                                kind=self.kind,
                                sequence=self.sequence,
                            )
                            self.receipt_framing_bytes = len(line)
                        except (ValueError, TypeError, UnicodeError):
                            self.invalid = True
                skipping = not line.endswith(b"\n")
        except Exception:  # noqa: BLE001 — report bounded protocol failure, never stderr text
            self.invalid = True
        finally:
            stream = getattr(self.child, "stderr", None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:  # noqa: BLE001 — retain failure, never exception text
                    self.invalid = True

    def finish(self, *, timeout=10, intentional_termination=False):
        if self.final is not None:
            return self.final
        self.child.wait(timeout=timeout)
        self.thread.join(timeout=timeout)
        problem = None
        if self.thread.is_alive():
            problem = "worker_receipt_drain_timeout"
        elif self.invalid:
            problem = "worker_receipt_invalid"
        elif self.record is None and not intentional_termination:
            problem = "worker_receipt_missing"
        elif self.record is not None and (
            (self.record["outcome"] == "success") != (self.child.returncode == 0)
        ):
            problem = "worker_receipt_exit_mismatch"
        observed_bytes = self.stderr_bytes
        framing_bytes = self.receipt_framing_bytes if not problem else 0
        result = {
            "attemptId": self.attempt_id,
            "workerKind": self.kind,
            "sequence": self.sequence,
            "exitCode": self.child.returncode,
            "lifecycleSeconds": time.monotonic() - self.started,
            "lifecycleScope": "post_spawn_capture_to_parent_finalize",
            "stderrBytesObserved": observed_bytes,
            "validReceiptFramingBytes": framing_bytes,
            "stderrBytesDiscarded": observed_bytes - framing_bytes,
            "intentionalTermination": intentional_termination,
            "receiptError": problem,
            "receipt": self.record if not problem else None,
        }
        encoded = (json.dumps(result, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            if len(encoded) > WORKER_RECEIPT_LIMIT:
                raise ValueError("worker_evidence_record_limit")
            self.sink.append(encoded)
        except (OSError, ValueError):
            result["receiptError"] = "worker_evidence_write_failed"
        self.final = result
        return result


def finish_worker(child, *, timeout=10, intentional_termination=False, events=None, errors=None):
    if intentional_termination and child._soak_receipt.kind != "hold":
        raise ValueError("only the queued-request hold fault may omit a terminal receipt")
    result = child._soak_receipt.finish(
        timeout=timeout, intentional_termination=intentional_termination
    )
    if result["receiptError"] and errors is not None:
        errors.append(result["receiptError"])
    if events is not None:
        events.append({"kind": "worker_outcome", **result})
    return result


def cleanup_worker(child, *, label, events, errors, timeout=10):
    """Bounded cleanup; retain failures and keep the sole receipt drain owner."""
    if child is None:
        return None
    for action in ("terminate", "kill"):
        try:
            if child.poll() is None:
                getattr(child, action)()
        except Exception as exc:
            errors.append(f"{label}_cleanup_{action}_{type(exc).__name__}")
        try:
            result = finish_worker(child, timeout=timeout, events=events, errors=errors)
            if result["exitCode"] != 0:
                errors.append(f"{label}_cleanup_exit_nonzero")
            return result
        except Exception as exc:
            errors.append(f"{label}_cleanup_finalize_{action}_{type(exc).__name__}")
    # wait() can fail before finish() reaches its join. Still attempt the existing
    # reader's bounded join; never introduce a second stderr/communicate reader.
    try:
        capture = child._soak_receipt
        capture.thread.join(timeout=timeout)
        if capture.thread.is_alive():
            errors.append(f"{label}_cleanup_receipt_drain_timeout")
    except Exception as exc:
        errors.append(f"{label}_cleanup_receipt_join_{type(exc).__name__}")
    return None


def cleanup_web(state, child, errors, *, timeout=10):
    """A failed graceful stop stays failed even when bounded fallback reaps it."""
    for action in ("shutdown", "terminate", "kill"):
        try:
            if action == "shutdown":
                state.control("shutdown")
            elif child.poll() is None:
                getattr(child, action)()
            child.communicate(timeout=timeout)
            return_code = child.poll()
            if return_code is None:
                errors.append(f"web_cleanup_{action}_not_exited")
                continue
            if return_code != 0:
                errors.append("web_cleanup_exit_nonzero")
            return return_code
        except Exception as exc:
            errors.append(f"web_cleanup_{action}_{type(exc).__name__}")


class DeferredLeagueFollowup:
    """One pending convergence task, never a retry policy for failed work."""

    def __init__(self, now):
        self.deadline = now + 90
        self.attempts = 0
        self.target_version = None
        self.superseded_while_running = False
        self.failure = None

    def worker_finished(self, canonical_version):
        self.superseded_while_running = canonical_version != self.target_version

    def action(self, now, *, companions_drained, cycle_failed, canonical_version, drain_ready):
        if cycle_failed:
            self.failure = "league_followup_blocked_by_worker_failure"
            return "failed"
        if now >= self.deadline:
            self.failure = "league_followup_deadline"
            return "failed"
        if canonical_version is None:
            self.failure = "league_followup_missing_canonical"
            return "failed"
        if not companions_drained:
            return "wait"
        if self.attempts and drain_ready:
            return "complete"
        if self.attempts == 0 or (self.attempts == 1 and self.superseded_while_running):
            self.attempts += 1
            self.target_version = canonical_version
            self.superseded_while_running = False
            return "launch"
        return "wait"


def worker(args):
    if args.worker == "web":
        return web_worker(args, store_for(args.root, args.budget_bytes))
    record = {
        "schemaVersion": 1,
        "attemptId": getattr(args, "attempt_id", None) or uuid.uuid4().hex,
        "workerKind": args.worker,
        "sequence": args.sequence,
        "outcome": "failed",
        "stage": "initialize",
        "exceptionClass": None,
        "errno": None,
        "winerror": None,
        "canonicalAccepted": False,
        "acceptedPhysicalGeneration": None,
        "leagueOutcome": "not_started",
    }
    try:
        _worker(args, record)
        record.update(outcome="success", stage="complete")
    except BaseException as exc:
        record["exceptionClass"] = (
            type(exc).__name__ if _safe_worker_class(type(exc).__name__) else "OtherException"
        )
        for name in ("errno", "winerror"):
            value = getattr(exc, name, None)
            record[name] = value if type(value) is int and -(2**31) <= value <= 2**32 - 1 else None
        if record["leagueOutcome"] == "running":
            record["leagueOutcome"] = "failed"
        raise SystemExit(1) from None
    finally:
        sys.stderr.write(WORKER_RECEIPT_PREFIX + json.dumps(record, separators=(",", ":")) + "\n")
        sys.stderr.flush()


def _worker(args, record):
    from src.serving.artifacts import _plain, _publish_lock
    from src.serving.builder import prepare_generation
    from src.serving.producer_status import claim_source_refresh
    from src.serving.serialization import ASSET, KEY, load_generation, publish_generation

    store = store_for(args.root, args.budget_bytes)
    if args.worker == "league":
        league_worker(store, record)
        return
    # Hold the same lease as production source/league owners. A terminated child
    # cannot retain an OS-owned lock. The fixture never invokes external sources.
    record["stage"] = "source_admission"
    with _publish_lock(store.root / "producer.lock", 20):
        if args.worker == "hold":
            (args.root / "worker-ready").write_text("ready", encoding="utf-8")
            time.sleep(120)
            return
        record["stage"] = "source_claim"
        claim_source_refresh(store)
        record["stage"] = "canonical_read"
        artifact = store.read_current(ASSET, KEY)
        if args.worker == "unchanged":
            metadata = {
                key: value
                for key, value in _plain(artifact.manifest).items()
                if key
                not in {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
            }
            record["stage"] = "canonical_publish"
            observed = store.publish(
                ASSET, KEY, artifact.files, metadata, validator=load_generation
            )
            record.update(canonicalAccepted=True, acceptedPhysicalGeneration=observed.generation_id)
            record["stage"] = "canonical_identity_check"
            assert observed.generation_id == artifact.generation_id
        else:
            record["stage"] = "canonical_deserialize"
            current = load_generation(artifact)
            record["stage"] = "canonical_prepare"
            contract = copy.deepcopy(current.contract)
            contract.setdefault("meta", {})["soakSequence"] = args.sequence
            candidate = prepare_generation(contract, current.raw, current.source, current.health)
            record["stage"] = "canonical_publish"
            accepted = publish_generation(candidate, store=store)
            record.update(canonicalAccepted=True, acceptedPhysicalGeneration=accepted.generation_id)
        if not league_worker(store, record, lease_wait_seconds=0, allow_busy=True):
            from src.serving.producer_status import request_league_refresh

            record["stage"] = "league_deferred_queue"
            request_league_refresh(store, "soak_followup")


def league_worker(store, record=None, *, lease_wait_seconds=20, allow_busy=False):
    from types import SimpleNamespace
    from src.serving.artifacts import _publish_lock, PublishLockTimeout
    from src.serving.league_views import prepare_league_views, publish_league_views
    from src.serving.producer_status import claim_league_refresh
    from src.serving.serialization import ASSET, KEY, load_generation

    record = record if record is not None else {}
    record.update(stage="league_admission", leagueOutcome="running")
    admitted = False
    try:
        with _publish_lock(store.root / "league-producer.lock", lease_wait_seconds):
            admitted = True
            record["stage"] = "league_claim"
            claim_league_refresh(store)
            record["stage"] = "league_board_read"
            board = load_generation(store.read_current(ASSET, KEY))
            meta = board.contract.get("meta") or {}
            cfg = SimpleNamespace(
                key=meta.get("leagueKey"), scoring_profile=meta.get("scoringProfile")
            )
            record["stage"] = "league_prepare"
            bundle = prepare_league_views(board, cfg)
            record["stage"] = "league_publish"
            publish_league_views(bundle, store, board=board, cfg=cfg)
            record["leagueOutcome"] = "success"
            return True
    except PublishLockTimeout:
        if admitted or not allow_busy:
            raise
        record["leagueOutcome"] = "busy"
        return False


def launch(args, kind, sequence=0):
    attempt_id = uuid.uuid4().hex
    if kind != "web":
        worker_evidence_sink(args)
    child_env = os.environ.copy()
    if kind == "web":
        child_env.pop("RISKIT_SERVING_ATTESTATION_PRIVATE_KEY", None)
    command = [
        sys.executable,
        __file__,
        "--root",
        str(args.root),
        "--worker",
        kind,
        "--sequence",
        str(sequence),
        "--budget-bytes",
        str(args.budget_bytes),
        "--port",
        str(args.port),
    ]
    if kind != "web":
        command.extend(["--attempt-id", attempt_id])
    if kind == "web" and getattr(args, "diagnostic_spans", False):
        command.append("--diagnostic-spans")
        if getattr(args, "diagnostic_timeline", False):
            command.append("--diagnostic-timeline")
        if getattr(args, "diagnostic_collector", "on") == "off":
            command.extend(["--diagnostic-collector", "off"])
        if getattr(args, "diagnostic_response_owner", "app") == "frozen":
            command.extend(["--diagnostic-response-owner", "frozen"])
        if getattr(args, "diagnostic_reload_observer", "on") == "off":
            command.extend(["--diagnostic-reload-observer", "off"])
        if getattr(args, "diagnostic_transport", False):
            command.append("--diagnostic-transport")
        if getattr(args, "diagnostic_adoption", False):
            command.append("--diagnostic-adoption")
    child = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        # The long-lived web app may log every request. An unread stderr pipe
        # fills and blocks its event loop, manufacturing availability failures.
        stderr=subprocess.DEVNULL if kind == "web" else subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        env=child_env,
    )
    try:
        if hasattr(args, "child_ledger"):
            args.child_ledger.observe_pid(child.pid)
        if kind != "web":
            child._soak_receipt = WorkerReceiptCapture(child, args, kind, sequence, attempt_id)
    except BaseException:
        # A setup failure must not orphan a child before the caller receives it.
        if child.poll() is None:
            child.terminate()
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=10)
        finally:
            if child.stderr is not None:
                child.stderr.close()
        raise
    return child


def web_worker(args, store):
    """Real local app/HTTP stack with only the producer lifespan replaced."""
    from contextlib import asynccontextmanager
    import uvicorn
    from starlette.concurrency import run_in_threadpool
    from src.api import league_registry
    from src.serving.league_views import LeagueServingReader
    from src.serving.runtime import AtomicRuntime
    from src.serving.serialization import ASSET, KEY, load_web_generation as load_generation
    from src.serving.attestation import enabled as attestation_enabled

    os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")
    import server

    tracer = None
    if getattr(args, "diagnostic_spans", False):
        from scripts.serving_lab_spans import LabSpans
        from src.serving import serialization

        tracer = LabSpans(
            args.root.with_name(args.root.name + ".spans.jsonl"),
            max_events=15_000_000,
            timeline_only=getattr(args, "diagnostic_timeline", False),
            collector_enabled=getattr(args, "diagnostic_collector", "on") != "off",
            adoption_timeline=getattr(args, "diagnostic_adoption", False),
        )
        tracer.install(server)
        if getattr(args, "diagnostic_transport", False):
            tracer.install_transport(args.web_loop)
        load_generation = serialization.load_web_generation

    # Acceptance instrumentation is counters/clocks only. Track meaningful
    # loads and encoding, not each unchanged 1s/2s polling call, so an entirely
    # idle polling loop does not manufacture refresh activity.
    from src.serving import league_views
    from src.serving.producer_status import pending_league_refresh, pending_source_refresh

    reload_activity = ReloadActivity()
    store.read_current = reload_activity.wrap(store.read_current)
    load_generation = reload_activity.wrap(load_generation)
    for name in (
        "load_league_views",
        "load_web_league_views",
        "validate_league_views",
        "prepare_league_views",
        "prepare_payload",
    ):
        setattr(league_views, name, reload_activity.wrap(getattr(league_views, name)))
    state = AtomicRuntime(
        store, ASSET, KEY, load_generation, on_publish=server._publish_serving_generation
    )
    assert state.reload_if_changed()
    meta = state.current.contract.get("meta") or {}
    cfg = SimpleNamespace(key=meta.get("leagueKey"), scoring_profile=meta.get("scoringProfile"))
    assert cfg.key, "recorded fixture requires a league identity"
    league_registry.active_leagues = lambda: [cfg]
    server._resolve_league_for_request = lambda request: cfg
    server.auth_sessions["offline-soak-fixture"] = {
        "username": "offline-soak-fixture",
        "_last_touch_epoch": time.time() + 86400,
    }
    leagues = LeagueServingReader(
        store, lambda: server.latest_serving_generation, lightweight=attestation_enabled()
    )
    server._league_serving_reader = leagues

    @asynccontextmanager
    async def fixture_lifespan(app):
        leagues.refresh()
        state.start()
        leagues.start()
        if tracer:
            tracer.begin_serving()
        (args.root / "web-ready").write_text("ready", encoding="utf-8")
        try:
            yield
        finally:
            state.stop()
            leagues.stop()
            if tracer:
                await tracer.end_serving()

    server.app.router.lifespan_context = fixture_lifespan

    async def observe_reload(request, call_next):
        active = state._reload_lock.locked() or leagues._refresh_lock.locked()
        if (
            tracer
            and not getattr(args, "diagnostic_timeline", False)
            and request.url.path
            in {
                "/api/read-models/rankings",
                "/api/read-models/trade/context",
            }
        ):
            route = "rankings" if request.url.path.endswith("rankings") else "trade"
            with tracer.request(route) as request_id:
                response = await call_next(request)
                response.headers["X-Soak-Request-Sequence"] = str(request_id)
        else:
            response = await call_next(request)
        response.headers["X-Soak-Reload-Active"] = str(
            int(active or state._reload_lock.locked() or leagues._refresh_lock.locked())
        )
        return response

    if getattr(args, "diagnostic_reload_observer", "on") != "off":
        server.app.middleware("http")(observe_reload)

    @server.app.api_route("/__soak/{action}", methods=["GET", "POST"])
    async def control(action: str):
        result = None
        if action == "clock" and getattr(args, "diagnostic_timeline", False):
            result = {"receiveNs": time.perf_counter_ns(), "clock": clock_metadata()}
            if getattr(args, "diagnostic_transport", False):
                result["transport"] = tracer.transport_report()
            if getattr(args, "diagnostic_adoption", False):
                result["adoption"] = tracer.adoption_report()
            result["sendNs"] = time.perf_counter_ns()
        elif action == "asgi" and getattr(args, "diagnostic_timeline", False):
            result = await asgi_control(application, fixture_league_key=cfg.key)
        elif action == "stop":
            result = await run_in_threadpool(state.stop)
        elif action == "reload":
            result = await run_in_threadpool(state.reload_if_changed)
        elif action == "start":
            state.start()
        elif action == "shutdown":
            web_server.should_exit = True
        elif action == "drain":
            result = await run_in_threadpool(
                serving_drain_status,
                store,
                state,
                leagues,
                [cfg],
                reload_activity,
                lambda: pending_source_refresh(store) or pending_league_refresh(store),
            )
        elif action != "state":
            raise ValueError("unknown fixture control")
        return {
            "generation": state.current.generation_id,
            "lastError": bool(state.last_error),
            "result": result,
        }

    response_application = server.app
    if getattr(args, "diagnostic_reload_observer", "on") == "off":
        response_application = quiet_reload_header(response_application)
    if getattr(args, "diagnostic_response_owner", "app") == "frozen":
        response_application = FrozenResponses(response_application)
    application = (
        tracer.wrap_app(response_application)
        if tracer and getattr(args, "diagnostic_timeline", False)
        else response_application
    )
    config = uvicorn.Config(
        application, host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
    )
    web_server = uvicorn.Server(config)
    try:
        args.web_loop.run_until_complete(web_server.serve())
    finally:
        args.web_loop.close()
        if tracer:
            tracer.close()


def http_response(connection, path, *, etag=None, method="GET"):
    headers = {"Accept-Encoding": "gzip", "Cookie": "jason_session=offline-soak-fixture"}
    if etag:
        headers["If-None-Match"] = etag
    connection.request(method, path, headers=headers)
    response = connection.getresponse()
    return SimpleNamespace(
        status_code=response.status,
        headers={key.lower(): value for key, value in response.getheaders()},
        body=response.read(),
    )


class RemoteRuntime:
    """Fault controls act on the same web-child runtime serving measured reads."""

    def __init__(self, port):
        self.port = port

    def control(self, action, *, timeout=30):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            response = http_response(connection, "/__soak/" + action, method="POST")
            assert response.status_code == 200
            body = (
                gzip.decompress(response.body)
                if response.headers.get("content-encoding") == "gzip"
                else response.body
            )
            return json.loads(body)
        finally:
            connection.close()

    @property
    def current(self):
        return self.control("state")["generation"]

    @property
    def last_error(self):
        return "recorded_error" if self.control("state")["lastError"] else None

    def stop(self):
        return self.control("stop")["result"]

    def reload_if_changed(self):
        return self.control("reload")["result"]

    def start(self, interval=1):
        self.control("start")


class ChildLedger:
    """Remember observed process identities, including children later reparented."""

    def __init__(self):
        self.identities = set()
        self.lock = threading.Lock()

    def observe_pid(self, pid):
        import psutil

        try:
            self.observe(psutil.Process(pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def observe(self, process):
        import psutil

        try:
            identity = (process.pid, process.create_time())
            with self.lock:
                self.identities.add(identity)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def remaining(self, parent, *, exclude=()):
        import psutil

        visible_processes = parent.children(recursive=True)
        visible = {child.pid for child in visible_processes}
        discovered = set()
        remaining = reparented = unknown = 0
        for child in visible_processes:
            try:
                discovered.add((child.pid, child.create_time()))
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                unknown += 1
        with self.lock:
            self.identities.update(discovered)
            identities = tuple(self.identities - set(exclude))
        for pid, created in identities:
            try:
                process = psutil.Process(pid)
                if process.create_time() != created or not process.is_running():
                    continue  # PID reuse is not the observed child.
                if process.status() == psutil.STATUS_ZOMBIE:
                    continue
                remaining += 1
                reparented += pid not in visible
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                unknown += 1
        return {
            "observedCount": len(identities),
            "remainingCount": remaining,
            "reparentedCount": reparented,
            "unknownCount": unknown,
        }


class ResponseAudit:
    """Hash-cache parsed identity metadata; never retain entire decoded bodies."""

    def __init__(self, limit=64):
        self.cache = OrderedDict()
        self.limit = limit
        self.cache_misses = 0

    def check(self, response, view, league_key, conditional=None):
        generation = response.headers.get("x-data-generation")
        etag = response.headers.get("etag")
        assert generation and etag, "missing_response_identity"
        assert response.headers.get("x-payload-view") == view, "wrong_response_view"
        if response.status_code == 304:
            assert conditional == (etag, generation), "conditional_generation_mismatch"
            assert not response.body, "conditional_body_present"
            return etag, generation
        assert response.status_code == 200, "unexpected_status"
        digest = hashlib.sha256(response.body).hexdigest()
        key = (digest, response.headers.get("content-encoding"))
        identity = self.cache.get(key)
        if identity is None:
            raw = gzip.decompress(response.body) if key[1] == "gzip" else response.body
            payload = json.loads(raw)
            meta = payload.get("meta") or {}
            identity = (
                meta.get("readModelGeneration"),
                meta.get("leagueKey"),
                payload.get("payloadView"),
                hashlib.sha1(raw).hexdigest(),
            )
            self.cache[key] = identity
            self.cache_misses += 1
            if len(self.cache) > self.limit:
                self.cache.popitem(last=False)
        else:
            self.cache.move_to_end(key)
        assert identity == (generation, league_key, view, etag), "body_header_identity_mismatch"
        return etag, generation


LEGACY_LATENCY_POLICY = "legacy-relative-v1"
LOCAL_HYBRID_LATENCY_POLICY = "local-prepared-hybrid-v1"
LATENCY_POLICIES = (LEGACY_LATENCY_POLICY, LOCAL_HYBRID_LATENCY_POLICY)


def _valid_latency(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def evaluate_refresh_latency(baseline, refresh, *, policy=LEGACY_LATENCY_POLICY):
    """Evaluate recorded p95s; the campaign policy never changes observations."""
    if policy not in LATENCY_POLICIES:
        raise ValueError("unknown local latency policy")
    valid = _valid_latency(baseline) and _valid_latency(refresh)
    delta = refresh - baseline if valid else None
    relative = (refresh / baseline - 1) * 100 if valid and baseline > 0 else None
    ceiling = valid and refresh < 75
    legacy_relative = valid and refresh <= baseline * 1.2
    relative_branch = legacy_relative if valid and baseline > 0 else None
    absolute_branch = valid and delta <= 15 and refresh <= 25
    secondary = (
        legacy_relative
        if policy == LEGACY_LATENCY_POLICY
        else relative_branch is True or absolute_branch
    )
    return {
        "policy": policy,
        "observationsValid": valid,
        "baselineMilliseconds": baseline,
        "refreshMilliseconds": refresh,
        "absoluteMilliseconds": delta,
        "relativePercent": relative,
        "absoluteCeilingPass": ceiling,
        "relativeBranchPass": relative_branch,
        "absoluteBranchPass": absolute_branch,
        "legacyRelativePass": legacy_relative,
        "passed": ceiling and secondary,
    }


def http_latency_summary(series, *, latency_policy=LEGACY_LATENCY_POLICY):
    if latency_policy not in LATENCY_POLICIES:
        raise ValueError("unknown local latency policy")
    valid_series = {
        key: bool(values) and all(_valid_latency(value) for value in values)
        for key, values in series.items()
    }
    p95 = {key: percentile(values) if valid_series[key] else None for key, values in series.items()}
    required = {
        f"{view}:{phase}:{kind}:{status}"
        for view in ("rankings", "trade")
        for phase in ("baseline", "refresh", "postRefreshIdle")
        for kind, status in (("unconditional", 200), ("conditional", 304))
    }
    comparisons = {}
    for key in p95:
        view, phase, kind, status = key.split(":")
        if phase != "refresh":
            continue
        baseline = f"{view}:baseline:{kind}:{status}"
        if status == "200" and p95.get(baseline) is None:
            # A valid generation transition can turn a conditional hit into a
            # full-body 200. Compare it with that route's normal full-body cost.
            baseline = f"{view}:baseline:unconditional:200"
        comparisons[key] = baseline
    evaluations = {
        key: evaluate_refresh_latency(p95.get(baseline), p95[key], policy=latency_policy)
        for key, baseline in comparisons.items()
    }
    legacy_relative = bool(evaluations) and all(
        evaluation["legacyRelativePass"] for evaluation in evaluations.values()
    )
    policy_check = (
        {"eachRefreshReadSeriesWithin20Percent": legacy_relative}
        if latency_policy == LEGACY_LATENCY_POLICY
        else {
            "eachRefreshReadSeriesPassLatencyPolicy": bool(evaluations)
            and all(evaluation["passed"] for evaluation in evaluations.values())
        }
    )
    return {
        "latencyPolicy": latency_policy,
        "refreshLatencyEvaluations": evaluations,
        "legacyLatencyChecks": {"eachRefreshReadSeriesWithin20Percent": legacy_relative},
        "p95MillisecondsByReadSeries": p95,
        "p99MillisecondsByReadSeries": {
            key: percentile(values, 0.99) if valid_series[key] else None
            for key, values in series.items()
        },
        "sampleCountsByReadSeries": {key: len(values) for key, values in series.items()},
        "p99SufficientByReadSeries": {
            key: valid_series[key] and len(values) >= 1000 for key, values in series.items()
        },
        "invalidLatencyObservationCountsByReadSeries": {
            key: sum(not _valid_latency(value) for value in values)
            for key, values in series.items()
        },
        "refreshP95Deltas": {
            key: {
                "baselineMilliseconds": p95.get(baseline),
                "refreshMilliseconds": p95[key],
                "absoluteMilliseconds": p95[key] - p95[baseline],
                "relativePercent": (p95[key] / p95[baseline] - 1) * 100 if p95[baseline] else None,
            }
            for key, baseline in comparisons.items()
            if p95.get(baseline) is not None and p95[key] is not None
        },
        "baselineComparisons": comparisons,
        "checks": {
            "httpLatencyObservationsValid": bool(series) and all(valid_series.values()),
            "requiredHttpReadSeriesObserved": all(p95.get(key) is not None for key in required),
            "eachHttpReadSeriesP95Below75ms": bool(p95)
            and all(_valid_latency(value) and value < 75 for value in p95.values()),
            **policy_check,
        },
    }


def sampling_evidence(count, seconds, max_gap):
    return {
        "observationCoverageAtLeast99Percent": seconds > 0 and count / seconds >= 0.99,
        "observationSampleGapsAtMost2Seconds": max_gap is not None and max_gap <= 2,
    }


def publication_evidence(events, observed):
    changed = [
        event.get("publishedGeneration")
        for event in events
        if event.get("kind") == "refresh"
        and event.get("workerKind") == "changed"
        and event.get("exitCode") == 0
    ]
    return bool(changed) and all(generation and generation in observed for generation in changed)


def sample(
    process, root, started, previous_cpu=None, child_ledger=None, web_identity=None, *, timing=None
):
    import psutil

    timing = timing or ObservationTiming()
    observation_started = time.monotonic()
    with timing.stage("tree"):
        members = [process, *process.children(recursive=True)]
    web_ids = set()
    web_observed = False
    with timing.stage("webTree"):
        if web_identity is not None:
            try:
                web_pid, web_created = web_identity
                web_process = psutil.Process(web_pid)
                if web_process.create_time() == web_created:
                    web_ids = {web_pid, *(p.pid for p in web_process.children(recursive=True))}
                    web_observed = web_ids <= {member.pid for member in members}
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    driver_rss = driver_handles = web_rss = web_handles = 0
    with timing.stage("ledger"):
        if child_ledger is not None:
            for member in members[1:]:
                child_ledger.observe(member)
    rss = peak = handles = 0
    cpu = 0.0
    cpu_delta = 0.0
    driver_cpu_delta = web_cpu_delta = 0.0
    alive = 0
    unknown = 0
    for member in members:
        try:
            with timing.stage("member"):
                with timing.stage("memberMemory"):
                    memory = member.memory_info()
                rss += memory.rss
                peak += getattr(memory, "peak_wset", memory.rss)
                with timing.stage("memberHandles"):
                    descriptors = member.num_handles() if os.name == "nt" else member.num_fds()
                handles += descriptors
                if member.pid == process.pid:
                    driver_rss = memory.rss
                    driver_handles = descriptors
                if member.pid in web_ids:
                    web_rss += memory.rss
                    web_handles += descriptors
                with timing.stage("memberCpu"):
                    times = member.cpu_times()
                cpu += times.user + times.system
                if previous_cpu is not None:
                    prior = previous_cpu.get(member.pid)
                    current = times.user + times.system
                    delta = max(0, current - prior) if prior is not None else 0
                    cpu_delta += delta
                    driver_cpu_delta += delta if member.pid == process.pid else 0
                    web_cpu_delta += delta if member.pid in web_ids else 0
                    previous_cpu[member.pid] = current
                alive += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            unknown += 1
            if member.pid in web_ids:
                web_observed = False
            continue
    # Lab root only, never source archives or unrelated caches.
    disk = 0
    with timing.stage("disk"):
        for path in root.rglob("*"):
            try:
                if path.is_file():
                    disk += path.stat().st_size
            except FileNotFoundError:
                # A publisher may rename its temporary file during this observation.
                continue
    with timing.stage("hostCpu"):
        host_cpu = psutil.cpu_percent()
    observation_finished = time.monotonic()
    return {
        "seconds": round(observation_finished - started, 3),
        "observationStartedSeconds": observation_started - started,
        "observationFinishedSeconds": observation_finished - started,
        "resourceObservationComplete": unknown == 0 and (web_identity is None or web_observed),
        "unknownProcessObservationCount": unknown,
        "rssBytes": rss,
        "driverRssBytes": driver_rss,
        "driverDescriptorCount": driver_handles,
        "webRssBytes": web_rss if web_observed else None,
        "webDescriptorCount": web_handles if web_observed else None,
        "webResourceObservationComplete": web_observed,
        "peakRssBytes": peak,
        "cpuSecondsLiveProcesses": cpu,
        "cpuSecondsSincePreviousSample": cpu_delta,
        "driverCpuSecondsSincePreviousSample": driver_cpu_delta,
        "webCpuSecondsSincePreviousSample": web_cpu_delta if web_observed else None,
        "hostCpuPercent": host_cpu,
        "processCount": alive,
        "descriptorCount": handles,
        "diskBytes": disk,
    }


def summarize(
    samples,
    latencies,
    baseline_seconds,
    errors,
    events,
    budget,
    *,
    children=None,
    idle_process_count=1,
    quiet_bounds=None,
    latency_policy=LEGACY_LATENCY_POLICY,
):
    baseline = [row for row in samples if baseline_seconds / 2 <= row["seconds"] < baseline_seconds]
    final = (
        [row for row in samples if wholly_within(row, quiet_bounds)]
        if quiet_bounds is not None
        else samples[-min(120, max(1, len(samples) // 10)) :]
    )
    # Compare idle-parent samples to avoid treating a currently running worker as
    # a leak. Peak tree RSS remains recorded for capacity planning.
    baseline_idle = [row for row in baseline if row["processCount"] == idle_process_count]
    final_idle = [row for row in final if row["processCount"] == idle_process_count]
    before = statistics.median(row["rssBytes"] for row in baseline_idle) if baseline_idle else None
    after = statistics.median(row["rssBytes"] for row in final_idle) if final_idle else None
    handle_before = (
        statistics.median(row["descriptorCount"] for row in baseline_idle)
        if baseline_idle
        else None
    )
    handle_after = (
        statistics.median(row["descriptorCount"] for row in final_idle) if final_idle else None
    )
    valid_series = {
        key: bool(values) and all(_valid_latency(value) for value in values)
        for key, values in latencies.items()
    }
    p95 = {
        key: percentile(values) if valid_series[key] else None for key, values in latencies.items()
    }
    warm = p95.get("baseline")
    refresh = p95.get("refresh")
    evaluation = evaluate_refresh_latency(warm, refresh, policy=latency_policy)
    policy_check = (
        {"refreshDegradationAtMost20Percent": evaluation["legacyRelativePass"]}
        if latency_policy == LEGACY_LATENCY_POLICY
        else {"refreshLatencyPolicyPass": evaluation["passed"]}
    )
    checks = {
        "noIncorrectResponsesOrUnexpectedFailures": not errors,
        "pooledLatencyObservationsValid": bool(latencies) and all(valid_series.values()),
        "preparedEndpointP95Below75ms": evaluation["observationsValid"] and max(warm, refresh) < 75,
        **policy_check,
        "rssGrowthBound": before is not None
        and after is not None
        and after - before <= max(before * 0.1, 64 * 1024**2),
        "handlesReturnNearBaseline": handle_before is not None
        and handle_after is not None
        and handle_after <= handle_before + max(10, handle_before * 0.1),
        "noRemainingObservedChildren": bool(samples)
        and samples[-1]["processCount"] == 1
        and (children is None or not (children["remainingCount"] or children["unknownCount"])),
        "diskWithinBudget": bool(samples) and samples[-1]["diskBytes"] <= budget,
        "faultScenariosObserved": {
            "rejected_candidate_kept_pointer",
            "corrupt_disk_generation_retained_memory",
            "reader_recovered_and_restarted",
            "capacity_exhaustion_kept_pointer",
            "terminated_worker_lease_reacquired_with_queued_requests",
            "restarted_worker_acknowledged_preserved_requests",
        }
        <= {event["kind"] for event in events},
        "changedAndUnchangedRefreshObserved": {"changed", "unchanged"}
        <= {event.get("workerKind") for event in events if event.get("exitCode") == 0},
    }
    return {
        "latencyPolicy": latency_policy,
        "pooledRefreshLatencyEvaluation": evaluation,
        "legacyLatencyChecks": {
            "refreshDegradationAtMost20Percent": evaluation["legacyRelativePass"]
        },
        "checks": checks,
        "passed": all(checks.values()),
        "durationSeconds": samples[-1]["seconds"] if samples else 0,
        "baselineSeconds": baseline_seconds,
        "sampleCount": len(samples),
        "sampleIntervalTargetSeconds": 1,
        "maxSampleGapSeconds": max(
            (right["seconds"] - left["seconds"] for left, right in zip(samples, samples[1:])),
            default=None,
        ),
        "descriptorKind": "Windows handles" if os.name == "nt" else "Linux file descriptors",
        "latencyScope": "loopback HTTP through real app middleware, synthetic auth session, prepared rankings/trade endpoints and LeagueServingReader; fixed fixture league selection; excludes response audit",
        "readCounts": {key: len(value) for key, value in latencies.items()},
        "p95Milliseconds": p95,
        "invalidLatencyObservationCounts": {
            key: sum(not _valid_latency(value) for value in values)
            for key, values in latencies.items()
        },
        "observedChildren": children,
        "rssBaselineBytes": before,
        "rssFinalBytes": after,
        "peakProcessTreeRssBytes": max((row["rssBytes"] for row in samples), default=None),
        "handlesBaseline": handle_before,
        "handlesFinal": handle_after,
        "maxProcesses": max((row["processCount"] for row in samples), default=None),
        "budgetBytes": budget,
        "diskFinalBytes": samples[-1]["diskBytes"] if samples else None,
        "errors": errors[:20],
        "events": events,
        "limitations": [
            "Private recorded board replay; no external providers",
            "No deployed API or Linux/systemd proof",
            "Separate loopback web child uses fixture lifespan and auth session; login, session persistence and external network latency are excluded",
            "Changed input uses a non-value metadata revision; canonical values remain fixed",
            "CPU seconds include currently live processes; completed child totals are unavailable",
            "PID/create-time ledger detects surviving observed descendants after reparenting; unobserved short-lived descendants and real scraper/browser cleanup are unproven",
        ],
    }


DIAGNOSTIC_REQUESTS = (
    ("rankings", "/api/read-models/rankings", "unconditional"),
    ("rankings", "/api/read-models/rankings", "conditional"),
    ("trade", "/api/read-models/trade/context", "unconditional"),
    ("trade", "/api/read-models/trade/context", "conditional"),
)


def clock_metadata():
    return {
        name: {
            "implementation": time.get_clock_info(name).implementation,
            "resolutionSeconds": time.get_clock_info(name).resolution,
            "monotonic": time.get_clock_info(name).monotonic,
        }
        for name in ("perf_counter", "monotonic", "thread_time")
    }


def diagnostic_orders(order, seed):
    """All 24 permutations per complete block; incomplete blocks stay visible."""
    rng = random.Random(seed)
    block = 0
    while True:
        permutations = (
            list(itertools.permutations(range(4))) if order == "balanced" else [(0, 1, 2, 3)]
        )
        rng.shuffle(permutations)
        for permutation in permutations:
            yield block, permutation
        block += 1


def quiet_reload_header(application):
    """Quiet-only control retaining wire metadata without BaseHTTPMiddleware.

    Independent drain/continuity checks remain authoritative. The fixed header
    is not a refresh observation and this adapter cannot run in acceptance.
    """

    async def wrapped(scope, receive, send):
        async def send_with_header(message):
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-soak-reload-active"
                ]
                message = {**message, "headers": headers + [(b"x-soak-reload-active", b"0")]}
            await send(message)

        return await application(scope, receive, send_with_header)

    return wrapped


class FrozenResponses:
    """Lab-only application-owner control; preserve captured headers/chunks exactly.

    The first 200/304 for each route still traverses the initialized app and is
    audited by the driver. Later quiet requests bypass only that application.
    This is deliberately ineligible for refresh or official acceptance.
    """

    def __init__(self, application):
        self.application = application
        self.cache = {}

    async def __call__(self, scope, receive, send):
        paths = {path for _, path, _ in DIAGNOSTIC_REQUESTS}
        path = scope.get("path")
        if scope.get("type") != "http" or scope.get("method") != "GET" or path not in paths:
            return await self.application(scope, receive, send)
        headers = dict(scope.get("headers", []))
        initial = self.cache.get((path, 200))
        etag = dict(initial[0]["headers"]).get(b"etag") if initial else None
        conditional = etag is not None and headers.get(b"if-none-match") == etag
        key = (path, 304 if conditional else 200)
        if key in self.cache:
            for message in self.cache[key]:
                await send(dict(message))
            return
        captured = []
        total = 0
        complete = False

        async def capture(message):
            nonlocal total, complete
            if message["type"] == "http.response.start":
                assert not captured, "frozen_control_duplicate_start"
                assert message["status"] == key[1], "frozen_control_status_mismatch"
                captured.append({**message, "headers": list(message.get("headers", []))})
            elif message["type"] == "http.response.body":
                assert captured and not complete, "frozen_control_body_order"
                total += len(message.get("body", b""))
                assert total <= 2 * 1024 * 1024, "frozen_control_body_budget"
                assert len(captured) < 256, "frozen_control_chunk_budget"
                captured.append(dict(message))
                complete = not message.get("more_body", False)
            await send(message)

        await self.application(scope, receive, capture)
        assert complete, "frozen_control_incomplete_body"
        self.cache[key] = tuple(captured)


class RecordingSocketReads:
    """Delegate the original SocketIO recv sizes; record no buffer contents."""

    def __init__(self, sock, connection):
        self.sock = sock
        self.connection = connection

    def __getattr__(self, name):
        return getattr(self.sock, name)

    def recv_into(self, buffer, *args):
        before = time.perf_counter_ns()
        cpu_before = time.thread_time_ns()
        count = None
        try:
            count = self.sock.recv_into(buffer, *args)
            return count
        finally:
            event = {
                "startNs": before,
                "endNs": time.perf_counter_ns(),
                "threadCpuNs": time.thread_time_ns() - cpu_before,
                "requestedBytes": args[0] if args and args[0] else len(buffer),
                "receivedBytes": count,
            }
            if len(self.connection.socket_reads) < 256:
                self.connection.socket_reads.append(event)
            else:
                self.connection.socket_reads_dropped += 1


class DiagnosticConnection(http.client.HTTPConnection):
    def __init__(self, port, sequence, *, socket_reads=False):
        super().__init__("127.0.0.1", port, timeout=5)
        self.sequence = sequence
        self.establishments = 0
        self.connection_marks = {}
        self.socket_reads_enabled = socket_reads
        self.socket_reads = []
        self.socket_reads_dropped = 0
        if socket_reads:

            def response_class(sock, *args, **kwargs):
                response = http.client.HTTPResponse(sock, *args, **kwargs)
                response.fp.raw._sock = RecordingSocketReads(response.fp.raw._sock, self)
                return response

            self.response_class = response_class

    def connect(self):
        self.connection_marks = {"connectStartNs": time.perf_counter_ns()}
        super().connect()
        self.connection_marks["connectEndNs"] = time.perf_counter_ns()
        self.establishments += 1


class DiagnosticRequestFailure(Exception):
    def __init__(self, marks, failure_type):
        super().__init__(failure_type)
        self.marks = marks
        self.failure_type = failure_type


def diagnostic_response(connection, path, *, etag=None, split_body=False):
    """Buffer availability boundaries only; never call them packet arrival."""
    marks = {
        "requestStartNs": time.perf_counter_ns(),
        "connectionSequence": connection.sequence,
        "connectionEstablishment": connection.establishments,
    }
    before_establishments = connection.establishments
    if getattr(connection, "socket_reads_enabled", False):
        connection.socket_reads = []
        connection.socket_reads_dropped = 0

    def socket_marks():
        if getattr(connection, "socket_reads_enabled", False):
            marks.update(
                socketReads=connection.socket_reads,
                socketReadsDropped=connection.socket_reads_dropped,
            )

    headers = {"Accept-Encoding": "gzip", "Cookie": "jason_session=offline-soak-fixture"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        connection.request("GET", path, headers=headers)
        marks["writeCompleteNs"] = time.perf_counter_ns()
        response = connection.getresponse()
        marks["headersAvailableNs"] = time.perf_counter_ns()
        tcp_nodelay = (
            connection.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
            if connection.sock
            else None
        )
        marks.update(status=response.status, tcpNoDelay=tcp_nodelay, willClose=response.will_close)
        first = b""
        if split_body and response.status != 304:
            first = response.read(1)
            if first:
                marks["firstBodyAvailableNs"] = time.perf_counter_ns()
        body = first + response.read()
        marks["bodyCompleteNs"] = time.perf_counter_ns()
        socket_marks()
        marks.update(
            connectionSequence=connection.sequence,
            connectionEstablishment=connection.establishments,
            newlyConnected=connection.establishments != before_establishments,
            tcpNoDelay=tcp_nodelay,
            willClose=response.will_close,
            bodyBytes=len(body),
            splitBody=split_body,
        )
        if marks["newlyConnected"]:
            marks.update(connection.connection_marks)
        return SimpleNamespace(
            status_code=response.status,
            headers={key.lower(): value for key, value in response.getheaders()},
            body=body,
        ), marks
    except Exception as exc:
        socket_marks()
        marks["failureObservedNs"] = time.perf_counter_ns()
        marks["connectionEstablishment"] = connection.establishments
        if connection.connection_marks.get("connectStartNs", -1) >= marks["requestStartNs"]:
            marks.update(connection.connection_marks)
        raise DiagnosticRequestFailure(marks, type(exc).__name__) from None


def exchange_clocks(state):
    exchanges = []
    for _ in range(12):
        start = time.perf_counter_ns()
        result = state.control("clock")["result"]
        end = time.perf_counter_ns()
        exchanges.append(
            {
                "driverStartNs": start,
                "serverReceiveNs": result["receiveNs"],
                "serverSendNs": result["sendNs"],
                "driverEndNs": end,
                # Server clock minus driver clock. Network delay is nonnegative.
                "offsetLowerNs": result["sendNs"] - end,
                "offsetUpperNs": result["receiveNs"] - start,
            }
        )
    lower = max(row["offsetLowerNs"] for row in exchanges)
    upper = min(row["offsetUpperNs"] for row in exchanges)
    return {
        "exchanges": exchanges,
        "offsetLowerNs": lower,
        "offsetUpperNs": upper,
        "comparable": lower <= upper,
        "driverClock": clock_metadata(),
        "serverClock": result["clock"],
        "transport": result.get("transport"),
        "adoption": result.get("adoption"),
    }


def diagnostic_request_sequence(value):
    """Return an absent or bounded JSON-safe numeric counter, never header text."""
    if value is None:
        return None
    if (
        isinstance(value, str)
        and 1 <= len(value) <= 16
        and value.isascii()
        and value.isdecimal()
        and 0 < int(value) <= 2**53 - 1
    ):
        return int(value)
    raise ValueError("invalid_diagnostic_request_sequence")


def diagnostic_content_encoding(value):
    """Unsupported header values are represented only by a fixed failure enum."""
    return "absent" if value is None else value if value in ("gzip", "identity") else "other"


async def asgi_control(application, *, fixture_league_key, cycles=1024):
    """Same initialized middleware/auth/answers; no TCP or real backpressure."""
    import asyncio

    audit = ResponseAudit()
    previous = {}
    measurements = []
    failures = Counter()
    deadline = time.perf_counter() + 60
    for cycle in range(cycles):
        for view, path, kind in DIAGNOSTIC_REQUESTS:
            if time.perf_counter() >= deadline:
                failures["control_deadline"] += 1
                return {
                    "scope": "bounded same-app ASGI control",
                    "rows": measurements,
                    "failures": dict(failures),
                }
            captured = {"status": None, "headers": {}, "chunks": [], "complete": False}
            requested = False
            never = asyncio.Event()
            headers = [
                (b"accept-encoding", b"gzip"),
                (b"cookie", b"jason_session=offline-soak-fixture"),
            ]
            if kind == "conditional" and view in previous:
                headers.append((b"if-none-match", previous[view][0].encode("ascii")))
            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.3"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode("ascii"),
                "query_string": b"",
                "root_path": "",
                "headers": headers,
                "client": ("127.0.0.1", 1),
                "server": ("127.0.0.1", 80),
            }

            async def receive():
                nonlocal requested
                if not requested:
                    requested = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await never.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.start":
                    captured["status"] = message["status"]
                    captured["headers"] = {
                        k.decode("latin1").lower(): v.decode("latin1")
                        for k, v in message.get("headers", [])
                    }
                elif message["type"] == "http.response.body":
                    captured["chunks"].append(message.get("body", b""))
                    captured["complete"] = not message.get("more_body", False)

            before = time.perf_counter_ns()
            try:
                await asyncio.wait_for(
                    application(scope, receive, send),
                    timeout=max(0.001, min(5, deadline - time.perf_counter())),
                )
                end = time.perf_counter_ns()
                response = SimpleNamespace(
                    status_code=captured["status"],
                    headers=captured["headers"],
                    body=b"".join(captured["chunks"]),
                )
                assert captured["complete"], "incomplete_asgi_body"
                if response.status_code == 200 and "content-length" in response.headers:
                    assert int(response.headers["content-length"]) == len(
                        response.body
                    ), "body_length_mismatch"
                previous[view] = audit.check(
                    response,
                    view,
                    fixture_league_key,
                    previous.get(view) if kind == "conditional" else None,
                )
                measurements.append(
                    {
                        "route": view,
                        "kind": kind,
                        "status": response.status_code,
                        "elapsedMs": (end - before) / 1e6,
                        "bodyBytes": len(response.body),
                        "requestId": diagnostic_request_sequence(
                            response.headers.get("x-soak-request-sequence")
                        ),
                    }
                )
            except Exception as exc:
                failures[type(exc).__name__] += 1
                return {
                    "scope": "bounded same-app ASGI control",
                    "rows": measurements,
                    "failures": dict(failures),
                }
    return {
        "scope": "same app, synthetic auth/league, no TCP or real send backpressure",
        "rows": measurements,
        "failures": dict(failures),
    }


def diagnostic_request_tokens(expected, response):
    from scripts.serving_lab_spans import adoption_identity

    def etag_token(value):
        return adoption_identity(value.strip('"') if isinstance(value, str) else None)

    requested = etag_token(expected[0]) if expected else None
    returned = etag_token(response.headers.get("etag"))
    old_board = adoption_identity(expected[1]) if expected else None
    new_board = adoption_identity(response.headers.get("x-data-generation"))
    return {
        "requestedEtagToken": requested,
        "returnedEtagToken": returned,
        "requestedCanonicalToken": old_board,
        "returnedCanonicalToken": new_board,
        "conditionalRepresentationChanged": bool(expected and requested != returned),
        "conditionalCanonicalChanged": bool(expected and old_board != new_board),
    }


def diagnostic_collection_summary(args, *, web_exit_code=None):
    if args.diagnostic_collector != "on":
        return {"enabled": False, "complete": None}
    path = args.root.with_name(args.root.name + ".spans.jsonl")
    try:
        with path.open("rb") as stream:
            stream.seek(max(0, path.stat().st_size - 16384))
            footer = json.loads(stream.read(16384).splitlines()[-1])
        valid = (
            footer.get("event") == "collection"
            and type(footer.get("dropped")) is int
            and footer["dropped"] == 0
            and type(footer.get("written")) is int
            and type(footer.get("emitted")) is int
            and footer["written"] == footer["emitted"] >= 0
            and footer.get("completionBoundary") == "footer_before_flush_and_close"
        )
        if getattr(args, "diagnostic_adoption", False):
            valid = valid and footer.get("adoption", {}).get("complete") is True
        return {
            "enabled": True,
            "complete": valid and type(web_exit_code) is int and web_exit_code == 0,
            "footerCompleteBeforeFlushAndClose": valid,
            "completionBoundary": "valid_footer_plus_known_zero_web_exit_after_close",
            "webExitCode": web_exit_code if type(web_exit_code) is int else None,
            "footer": footer,
        }
    except (OSError, ValueError, IndexError, AttributeError):
        return {"enabled": True, "complete": False, "error": "collection_unavailable"}


def diagnostic_reads(
    args,
    stop,
    fixture_league_key,
    emit,
    *,
    order=None,
    pacing=None,
    phase=None,
    cell=None,
    worker_state=None,
):
    """Alternate diagnostic driver inside the existing lab; never acceptance."""
    audit = ResponseAudit()
    previous = {}
    connection_sequence = 1
    connection_options = (
        {"socket_reads": True} if getattr(args, "diagnostic_socket_reads", False) else {}
    )
    connection = DiagnosticConnection(args.port, connection_sequence, **connection_options)
    order = order or args.diagnostic_order
    pacing = pacing or args.diagnostic_pacing
    natural = getattr(args, "diagnostic_case", None) == "natural-transitions"
    try:
        # Seed conditionals outside measured blocks, so any slot may run first.
        for view, path, _ in () if natural else (DIAGNOSTIC_REQUESTS[0], DIAGNOSTIC_REQUESTS[2]):
            try:
                response, _ = diagnostic_response(connection, path)
                previous[view] = audit.check(response, view, fixture_league_key, None)
            except Exception as exc:
                emit(
                    {
                        "route": view,
                        "kind": "unconditional",
                        "stage": "seed",
                        "cell": cell,
                        "failureType": getattr(exc, "failure_type", type(exc).__name__),
                        **getattr(exc, "marks", {}),
                    }
                )
                raise
        for block, permutation in diagnostic_orders(order, args.diagnostic_seed):
            if stop.is_set():
                break
            if natural:
                previous = {}
            pacing_start = time.perf_counter_ns()
            if pacing == "event":
                if stop.wait(0.01):
                    break
            elif pacing == "sleep":
                time.sleep(0.01)
            pacing_end = time.perf_counter_ns()
            for slot, request_index in enumerate(permutation):
                if stop.is_set():
                    break
                view, path, kind = DIAGNOSTIC_REQUESTS[request_index]
                row = {
                    "route": view,
                    "kind": kind,
                    "slot": slot,
                    "block": block,
                    "order": order,
                    "pacing": pacing,
                    "cell": cell,
                    "pacingStartNs": pacing_start,
                    "pacingEndNs": pacing_end,
                }
                try:
                    if args.diagnostic_connection == "new":
                        connection.close()
                        connection_sequence += 1
                        connection = DiagnosticConnection(
                            args.port, connection_sequence, **connection_options
                        )
                    expected = previous.get(view) if kind == "conditional" else None
                    if kind == "conditional" and expected is None:
                        continue
                    active_before = bool(worker_state()) if worker_state else False
                    response, marks = diagnostic_response(
                        connection,
                        path,
                        etag=expected[0] if expected else None,
                        split_body=args.diagnostic_body_read == "split",
                    )
                    completed_monotonic = time.monotonic()
                    active_after = bool(worker_state()) if worker_state else False
                    row.update(marks)
                    row.update(
                        workerActiveBefore=active_before,
                        workerActiveAfter=active_after,
                        reloadActive=response.headers.get("x-soak-reload-active") == "1",
                        completionObservedMonotonicSeconds=completed_monotonic,
                    )
                    assert not marks.get("socketReadsDropped"), "socket_trace_capacity"
                    row["status"] = response.status_code
                    row["elapsedMs"] = (marks["bodyCompleteNs"] - marks["requestStartNs"]) / 1e6
                    row["phase"] = (
                        (
                            phase(response, active_before, active_after)
                            if worker_state
                            else phase(response)
                        )
                        if phase
                        else ("warmup" if cell == "warmup" else "verifiedQuiet")
                    )
                    row["requestId"] = diagnostic_request_sequence(
                        response.headers.get("x-soak-request-sequence")
                    )
                    if row["requestId"] is None:
                        raise ValueError("missing_diagnostic_request_sequence")
                    row["contentEncoding"] = diagnostic_content_encoding(
                        response.headers.get("content-encoding")
                    )
                    if row["contentEncoding"] == "other":
                        row["headerFailure"] = "unsupported_content_encoding"
                        raise ValueError("unsupported_content_encoding")
                    row["contentLength"] = (
                        int(response.headers["content-length"])
                        if "content-length" in response.headers
                        else None
                    )
                    previous[view] = audit.check(response, view, fixture_league_key, expected)
                    row["generation"] = previous[view][1]
                    if getattr(args, "diagnostic_adoption", False):
                        row.update(diagnostic_request_tokens(expected, response))
                except Exception as exc:
                    row.update(getattr(exc, "marks", {}))
                    row["failureType"] = getattr(exc, "failure_type", type(exc).__name__)
                    connection.close()
                    connection_sequence += 1
                    connection = DiagnosticConnection(
                        args.port, connection_sequence, **connection_options
                    )
                emit(row)
    finally:
        connection.close()


def diagnostic_quiet_run(args, state, web_child, fixture_league_key, raw_path, provenance):
    """Quiet experiment controller reusing this lab's initialized web/store/drain."""
    from scripts.serving_lab_spans import LabSpans
    import psutil

    output = LabSpans(args.output.with_suffix(".requests.jsonl"), max_events=5_000_000)
    monitor_stop = threading.Event()
    checks = []
    errors = []
    cells = []
    read_failures = Counter()
    socket_reads_dropped = 0
    process = psutil.Process()
    initial_children = {(p.pid, p.create_time()) for p in process.children(recursive=True)}
    expected_token = None

    def emit(row):
        nonlocal socket_reads_dropped
        output.emit(row)
        socket_reads_dropped += row.get("socketReadsDropped", 0)
        if "failureType" in row:
            read_failures[row["failureType"]] += 1

    def monitor():
        nonlocal expected_token
        while not monitor_stop.is_set():
            now = time.perf_counter_ns()
            try:
                drain = state.control("drain", timeout=5)["result"]
                children = {(p.pid, p.create_time()) for p in process.children(recursive=True)}
                valid = drain["ready"] and children <= initial_children
                token = drain["continuityToken"]
                if expected_token is None and valid:
                    expected_token = token
                valid = valid and token == expected_token
                checks.append({"atNs": now, "endNs": time.perf_counter_ns(), "valid": valid})
            except Exception as exc:
                checks.append(
                    {
                        "atNs": now,
                        "endNs": time.perf_counter_ns(),
                        "valid": False,
                        "failureType": type(exc).__name__,
                    }
                )
            monitor_stop.wait(1)

    def cell_run(order, pacing, seconds, name):
        stopped = threading.Event()
        failure = []

        def read():
            try:
                diagnostic_reads(
                    args,
                    stopped,
                    fixture_league_key,
                    emit,
                    order=order,
                    pacing=pacing,
                    cell=name,
                )
            except Exception as exc:
                failure.append(type(exc).__name__)

        reader = threading.Thread(target=read, daemon=True, name="diagnostic-reads")
        start = time.perf_counter_ns()
        reader.start()
        stopped.wait(seconds)
        stopped.set()
        reader.join(timeout=6)
        if reader.is_alive() or failure:
            errors.append({"cell": name, "failures": failure, "readerAlive": reader.is_alive()})
        cells.append(
            {
                "cell": name,
                "order": order,
                "pacing": pacing,
                "startNs": start,
                "endNs": time.perf_counter_ns(),
            }
        )

    watcher = threading.Thread(target=monitor, daemon=True, name="diagnostic-quiet")
    try:
        clock_start = exchange_clocks(state)
        cell_run("original", "event", 30, "warmup")
        watcher.start()
        deadline = time.perf_counter() + args.quiet_seconds + 30
        while True:
            if checks and not all(r["valid"] for r in checks):
                raise RuntimeError("initial quiet verification failed")
            if len(checks) >= 2:
                quiet_start = checks[0]["endNs"]
                quiet_end = checks[-1]["atNs"]
                if (quiet_end - quiet_start) / 1e9 >= args.quiet_seconds:
                    break
            if time.perf_counter() > deadline:
                raise RuntimeError("initial quiet observation timeout")
            monitor_stop.wait(0.05)
        rng = random.Random(args.diagnostic_seed)
        for repetition in range(args.diagnostic_repetitions):
            orderings = (
                ["original", "balanced"]
                if args.diagnostic_quiet == "factorial"
                else [args.diagnostic_order]
            )
            pacings = (
                ["event", "continuous", "sleep"]
                if args.diagnostic_quiet == "factorial"
                else [args.diagnostic_pacing]
            )
            schedule = list(itertools.product(orderings, pacings))
            rng.shuffle(schedule)
            for index, (order, pacing) in enumerate(schedule):
                cell_run(order, pacing, args.diagnostic_cell_seconds, f"r{repetition}-c{index}")
        clock_end = exchange_clocks(state)
        if getattr(args, "diagnostic_transport", False):
            transport_report = clock_end.get("transport") or {}
            if not transport_report.get("complete") or not all(
                transport_report.get(key, 0) > 0
                for key in ("watchedWrites", "watchedWriteBytes", "completionDeliveries")
            ):
                errors.append({"transportObservationIncomplete": True})
        asgi = []
        if args.diagnostic_asgi:
            for _ in range(3):
                result = state.control("asgi", timeout=90)["result"]
                asgi.append(result)
                if result["failures"]:
                    errors.append({"asgiFailures": result["failures"]})
        args.output.with_suffix(".asgi.json").write_text(json.dumps(asgi), encoding="utf-8")
        tail_end = time.perf_counter_ns()
        tail_deadline = time.perf_counter() + 10
        while not checks or checks[-1]["atNs"] < tail_end:
            if time.perf_counter() > tail_deadline:
                raise RuntimeError("final quiet observation timeout")
            monitor_stop.wait(0.05)
    except Exception as exc:
        errors.append({"driverFailure": type(exc).__name__})
        clock_start = locals().get("clock_start")
        clock_end = locals().get("clock_end")
        quiet_start = locals().get("quiet_start")
        quiet_end = locals().get("quiet_end")
    finally:
        monitor_stop.set()
        if watcher.ident is not None:
            watcher.join(timeout=6)
        try:
            state.stop()
        except Exception as exc:
            errors.append({"readerStopFailure": type(exc).__name__})
        web_exit_code = cleanup_web(state, web_child, errors)
        try:
            output.close()
        except Exception as exc:
            errors.append({"driverCollectionCloseFailure": type(exc).__name__})
        try:
            driver_collection = output.collection_report()
            if driver_collection.get("complete") is not True:
                errors.append({"driverCollectionIncomplete": True})
        except Exception as exc:
            errors.append({"driverCollectionReportFailure": type(exc).__name__})
            driver_collection = {"complete": False}
    gaps = [(right["atNs"] - left["atNs"]) / 1e9 for left, right in zip(checks, checks[1:])]
    if type(web_exit_code) is not int or web_exit_code != 0:
        errors.append({"webExitUnsuccessfulOrUnknown": True})
    server_collection = diagnostic_collection_summary(args, web_exit_code=web_exit_code)
    if args.diagnostic_collector == "on" and server_collection["complete"] is not True:
        errors.append({"serverCollectionIncomplete": True})
    report = {
        "diagnosticOnly": True,
        "officialAcceptance": False,
        "cells": cells,
        "errors": errors,
        "clockStart": clock_start,
        "clockEnd": clock_end,
        "inputSha256": hashlib.sha256(args.contract.read_bytes()).hexdigest(),
        "rawInputSha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "quietStartNs": quiet_start,
        "quietEndNs": quiet_end,
        "quietChecks": checks,
        "allQuietChecksValid": bool(checks) and all(r["valid"] for r in checks),
        "maxQuietCheckGapSeconds": max(gaps, default=None),
        "codeProvenance": {
            "startup": provenance,
            "end": code_provenance(Path(__file__).resolve().parents[1], diagnostic_spans=True),
        },
        "remainingChildren": args.child_ledger.remaining(process),
        "requestEventsDropped": output.dropped,
        "driverCollection": driver_collection,
        "readFailures": dict(read_failures),
        "socketReadsDropped": socket_reads_dropped,
        "serverCollection": server_collection,
        "webExitCode": web_exit_code,
        "controls": {
            "collector": args.diagnostic_collector,
            "bodyRead": args.diagnostic_body_read,
            "connection": args.diagnostic_connection,
            "asgi": args.diagnostic_asgi,
            "responseOwner": getattr(args, "diagnostic_response_owner", "app"),
            "socketReads": getattr(args, "diagnostic_socket_reads", False),
            "reloadObserver": getattr(args, "diagnostic_reload_observer", "on"),
            "transport": getattr(args, "diagnostic_transport", False),
        },
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: v
                for k, v in report.items()
                if k not in {"quietChecks", "codeProvenance", "clockStart", "clockEnd"}
            }
        ),
        flush=True,
    )
    return (
        0
        if not errors
        and not read_failures
        and report["allQuietChecksValid"]
        and max(gaps, default=999) <= 2
        and output.dropped == 0
        and driver_collection.get("complete") is True
        and report["codeProvenance"]["startup"] == report["codeProvenance"]["end"]
        and clock_start
        and clock_start["comparable"]
        and clock_end
        and clock_end["comparable"]
        and report["remainingChildren"]["remainingCount"] == 0
        and report["remainingChildren"]["unknownCount"] == 0
        else 1
    )


def diagnostic_stale_etag_run(args, state, web_child, fixture_league_key, raw_path, provenance):
    """Three real publications; paired stale-A/full-B bodies after B adoption."""
    import psutil

    from src.serving.producer_status import request_source_refresh, request_league_refresh

    started = time.monotonic()
    harness_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    store = store_for(args.root, args.budget_bytes)
    audit = ResponseAudit()
    rows, outcomes, errors = [], [], []
    connection = DiagnosticConnection(args.port, 1)
    child = None
    clock_start = clock_end = None
    accepted = 0
    controls = (
        ("rankings", "/api/read-models/rankings"),
        ("trade", "/api/read-models/trade/context"),
    )
    previous = {}
    current_conditionals = []
    pacing = threading.Event()

    def wire_evidence(response):
        # Only fixed enums, hashes and numeric sizes leave the private response.
        encoding = response.headers.get("content-encoding")
        length = response.headers.get("content-length")
        if (
            encoding != "gzip"
            or not isinstance(length, str)
            or not length.isascii()
            or not length.isdecimal()
        ):
            raise AssertionError("stale_etag_wire_metadata_invalid")
        if int(length) != len(response.body):
            raise AssertionError("stale_etag_wire_length_mismatch")
        return {
            "bodySha256": hashlib.sha256(response.body).hexdigest(),
            "bodyBytes": len(response.body),
            "contentLength": int(length),
            "contentEncoding": encoding,
        }

    try:
        clock_start = exchange_clocks(state)
        for view, path in controls:
            response, _ = diagnostic_response(connection, path)
            previous[view] = audit.check(response, view, fixture_league_key)
        for revision in range(1, 4):
            request_source_refresh(store, "stale_etag_control")
            request_league_refresh(store, "stale_etag_control")
            child = launch(args, "changed", revision)
            outcome = finish_worker(child, timeout=90)
            outcomes.append(outcome)
            if outcome["receiptError"] or outcome["exitCode"] != 0:
                raise RuntimeError("stale_etag_publication_failed")
            if outcome["receipt"]["leagueOutcome"] != "success":
                raise RuntimeError("stale_etag_league_not_completed")
            child = None
            deadline = time.monotonic() + 90
            while not state.control("drain", timeout=5)["result"]["ready"]:
                if time.monotonic() >= deadline:
                    raise TimeoutError("stale_etag_adoption_timeout")
                time.sleep(0.1)
            current, current_wire = {}, {}
            for view, path in controls:
                response, _ = diagnostic_response(connection, path)
                current[view] = audit.check(response, view, fixture_league_key)
                current_wire[view] = wire_evidence(response)
                if current[view][1] == previous[view][1] or current[view][0] == previous[view][0]:
                    raise AssertionError("stale_etag_requires_changed_identity")
                conditional, marks = diagnostic_response(connection, path, etag=current[view][0])
                observed = audit.check(conditional, view, fixture_league_key, current[view])
                if conditional.status_code != 304 or conditional.body or observed != current[view]:
                    raise AssertionError("current_etag_requires_empty_304")
                current_conditionals.append(
                    {
                        "revision": revision,
                        "route": view,
                        "status": conditional.status_code,
                        "bodyBytes": len(conditional.body),
                        "requestId": int(conditional.headers["x-soak-request-sequence"]),
                        **diagnostic_request_tokens(current[view], conditional),
                        **marks,
                    }
                )
            accepted += 1
            for cycle in range(10):
                # Same event wait as the original read loop: once before the
                # block containing both routes, not between requests of a pair.
                pacing.wait(0.01)
                for view, path in controls:
                    kinds = (
                        ("unconditional", "staleConditional")
                        if cycle % 2 == 0
                        else ("staleConditional", "unconditional")
                    )
                    for pair_slot, kind in enumerate(kinds):
                        expected = previous[view] if kind == "staleConditional" else None
                        response, marks = diagnostic_response(
                            connection, path, etag=expected[0] if expected else None
                        )
                        observed = audit.check(response, view, fixture_league_key, expected)
                        if response.status_code != 200 or observed != current[view]:
                            raise AssertionError("stale_etag_pair_not_same_current_body")
                        wire = wire_evidence(response)
                        if wire != current_wire[view]:
                            raise AssertionError("stale_etag_pair_wire_mismatch")
                        rows.append(
                            {
                                "revision": revision,
                                "cycle": cycle,
                                "route": view,
                                "kind": kind,
                                "pairSlot": pair_slot,
                                "status": response.status_code,
                                **wire,
                                "requestId": int(response.headers["x-soak-request-sequence"]),
                                **diagnostic_request_tokens(expected, response),
                                "workerActiveBefore": False,
                                "workerActiveAfter": False,
                                "reloadActive": response.headers.get("x-soak-reload-active") == "1",
                                "elapsedMs": (marks["bodyCompleteNs"] - marks["requestStartNs"])
                                / 1e6,
                                **marks,
                            }
                        )
            previous = current
        clock_end = exchange_clocks(state)
    except Exception as exc:
        errors.append(type(exc).__name__)
    finally:
        try:
            connection.close()
        except Exception as exc:
            errors.append(f"connection_close_{type(exc).__name__}")
        if child is not None:
            outcome = cleanup_worker(child, label="source", events=None, errors=errors)
            if outcome is not None and outcome not in outcomes:
                outcomes.append(outcome)
        if clock_end is None:
            try:
                clock_end = exchange_clocks(state)
            except Exception as exc:
                errors.append(f"closing_clock_{type(exc).__name__}")
        web_exit_code = cleanup_web(state, web_child, errors)
    try:
        remaining_children = args.child_ledger.remaining(psutil.Process())
    except Exception as exc:
        errors.append(f"child_observation_{type(exc).__name__}")
        remaining_children = {
            "observedCount": 0,
            "remainingCount": 0,
            "reparentedCount": 0,
            "unknownCount": 1,
        }
    collector_enabled = args.diagnostic_collector == "on"
    adoption = (clock_end or {}).get("adoption") or {}
    collection = diagnostic_collection_summary(args, web_exit_code=web_exit_code)
    checks = {
        "threeChangedPublications": accepted == 3,
        "tenPairedCyclesPerRoutePerPublication": len(rows) == 120,
        "allPairedResponses200": bool(rows) and all(row["status"] == 200 for row in rows),
        "exactWirePairs": len(rows) == 120
        and all(
            all(
                left[key] == right[key]
                for key in ("bodySha256", "bodyBytes", "contentLength", "contentEncoding")
            )
            for left, right in zip(rows[::2], rows[1::2])
        ),
        "currentB304WithoutBodyPerRoutePerPublication": len(current_conditionals) == 6
        and all(row["status"] == 304 and row["bodyBytes"] == 0 for row in current_conditionals),
        "noControlFailures": not errors,
        "noRemainingObservedChildren": remaining_children["remainingCount"] == 0
        and remaining_children["unknownCount"] == 0,
        "clockBoundsAvailable": bool(
            clock_start and clock_start["comparable"] and clock_end and clock_end["comparable"]
        ),
        "collectorEvidenceCompleteWhenEnabled": not collector_enabled
        or adoption.get("complete") is True,
        "finalCollectorCompleteWhenEnabled": not collector_enabled
        or collection["complete"] is True,
        "harnessUnchanged": hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == harness_sha,
        "productAndHelpersUnchanged": code_provenance(
            Path(__file__).resolve().parents[1], diagnostic_spans=True
        )
        == provenance,
    }
    report = {
        "diagnosticCase": "stale-etag",
        "acceptanceClaim": False,
        "diagnosticComplete": all(checks.values()),
        "checks": checks,
        "errors": errors,
        "collector": args.diagnostic_collector,
        "collectorOffRepeatRequired": True,
        "serverCollection": collection,
        "webExitCode": web_exit_code,
        "acceptedBGenerations": accepted,
        "pairedCyclesPerRoute": 10,
        "alternatingPairOrder": True,
        "eventPacingSeconds": 0.01,
        "eventPacingScope": "once before each cycle containing both route pairs, matching the original read-loop block; control probes are separate",
        "remainingChildren": remaining_children,
        "childObservationScope": "visible descendants and previously observed PID/create-time identities; unobserved already-reparented descendants cannot be proven absent",
        "rows": rows,
        "currentBConditionals": current_conditionals,
        "workerOutcomes": outcomes,
        "clockStart": clock_start,
        "clockEnd": clock_end,
        "elapsedSeconds": time.monotonic() - started,
        "harnessSha256": harness_sha,
        "inputSha256": hashlib.sha256(args.contract.read_bytes()).hexdigest(),
        "rawInputSha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "scope": "same initialized fixture web app; no source/league work during pairs; app-to-driver timings, not field acceptance",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps({"diagnosticCase": "stale-etag", "checks": checks, "errors": errors}), flush=True
    )
    return 0 if report["diagnosticComplete"] else 1


def main(args):
    import psutil
    from src.serving.artifacts import RejectedCandidate, RetentionCapacityError, _publish_lock
    from src.serving.builder import prepare_generation
    from src.serving.producer_status import request_league_refresh, request_source_refresh
    from src.serving.serialization import ASSET, KEY, load_generation, publish_generation
    from src.serving.attestation import AttestationError, enabled as attestation_enabled

    harness_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    repo_root = Path(__file__).resolve().parents[1]
    provenance_start = code_provenance(
        repo_root, diagnostic_spans=getattr(args, "diagnostic_spans", False)
    )
    if args.root.exists():
        raise ValueError("Soak requires a new private root; existing stores are never modified")
    args.root.mkdir(parents=True)
    store = store_for(args.root, args.budget_bytes)
    contract = json.loads(args.contract.read_bytes())
    raw_path = args.raw_input or args.contract.with_name("raw-input.json")
    raw = json.loads(raw_path.read_bytes())
    source = {"type": "offline-soak", "producedAt": contract.get("scrapeTimestamp")}
    candidate = prepare_generation(contract, raw, source, {"ok": True})
    publish_generation(candidate, store=store)
    fixture_league_key = (contract.get("meta") or {}).get("leagueKey")
    league_worker(store)
    del candidate, contract, raw
    args.child_ledger = ChildLedger()
    web_child = launch(args, "web")
    deadline = time.monotonic() + 90
    while (
        not (args.root / "web-ready").exists()
        and web_child.poll() is None
        and time.monotonic() < deadline
    ):
        time.sleep(0.05)
    if not (args.root / "web-ready").exists():
        web_child.terminate()
        web_child.communicate(timeout=10)
        raise RuntimeError("fixture web child failed to become ready")
    state = RemoteRuntime(args.port)
    if getattr(args, "diagnostic_case", None) == "stale-etag":
        return diagnostic_stale_etag_run(
            args, state, web_child, fixture_league_key, raw_path, provenance_start
        )
    if getattr(args, "diagnostic_quiet", None):
        return diagnostic_quiet_run(
            args, state, web_child, fixture_league_key, raw_path, provenance_start
        )
    # Include the whole intentionally running web tree (Windows Python may use
    # launcher descendants), captured before any source/league workers start.
    baseline_children = psutil.Process().children(recursive=True)
    baseline_process_count = 1 + len(baseline_children)
    web_tree_identities = {(member.pid, member.create_time()) for member in baseline_children}
    web_identity = (web_child.pid, psutil.Process(web_child.pid).create_time())

    started = time.monotonic()
    stop = threading.Event()
    errors = []
    events = TimedEvents(started)
    latencies = {"baseline": [], "refresh": [], "postRefreshIdle": []}
    worker_active = threading.Event()
    response_counts = Counter()
    read_series = {}
    observed_generations = Counter()
    last_http_completion = [None]
    read_error_counts = Counter()
    audit = ResponseAudit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    request_file = args.output.with_suffix(".requests.jsonl")
    request_stream = request_file.open("w", encoding="utf-8")

    def read_loop():
        connection = http.client.HTTPConnection("127.0.0.1", args.port, timeout=5)
        while not stop.wait(0.01):
            for view, path in (
                ("rankings", "/api/read-models/rankings"),
                ("trade", "/api/read-models/trade/context"),
            ):
                conditional = None
                for request_kind in ("unconditional", "conditional"):
                    if stop.is_set():
                        break
                    if request_kind == "conditional" and conditional is None:
                        continue
                    try:
                        before = time.perf_counter()
                        overlapping = worker_active.is_set()
                        response = http_response(
                            connection, path, etag=conditional[0] if conditional else None
                        )
                        last_http_completion[0] = time.monotonic() - started
                        active_after = worker_active.is_set()
                        elapsed = (time.perf_counter() - before) * 1000
                        phase = (
                            "baseline"
                            if time.monotonic() - started < args.baseline_seconds
                            else (
                                "refresh"
                                if overlapping
                                or active_after
                                or response.headers.get("x-soak-reload-active") == "1"
                                else "postRefreshIdle"
                            )
                        )
                        response_counts[
                            f"{view}:{phase}:{request_kind}:{response.status_code}"
                        ] += 1
                        observation = {
                            "seconds": round(time.monotonic() - started, 3),
                            "route": view,
                            "phase": phase,
                            "kind": request_kind,
                            "status": response.status_code,
                            "elapsedMs": elapsed,
                            "workerActiveBefore": overlapping,
                            "workerActiveAfter": active_after,
                            "reloadActive": response.headers.get("x-soak-reload-active") == "1",
                        }
                        if getattr(args, "diagnostic_spans", False):
                            observation["requestId"] = int(
                                response.headers["x-soak-request-sequence"]
                            )
                        if response.status_code not in (200, 304):
                            try:
                                reason = json.loads(response.body).get("error")
                            except (ValueError, AttributeError):
                                reason = None
                            observation["reason"] = (
                                "data_not_ready" if reason == "data_not_ready" else "other"
                            )
                        request_stream.write(json.dumps(observation) + "\n")
                        if response.status_code not in (200, 304):
                            read_error_counts[f"{view}:http_{response.status_code}"] += 1
                            continue
                        latencies[phase].append(elapsed)
                        read_series.setdefault(
                            f"{view}:{phase}:{request_kind}:{response.status_code}", []
                        ).append(elapsed)
                        conditional = audit.check(response, view, fixture_league_key, conditional)
                        observed_generations[conditional[1]] += 1
                    except Exception as exc:
                        read_error_counts[f"{view}:{type(exc).__name__}"] += 1
                        request_stream.write(
                            json.dumps(
                                {
                                    "seconds": round(time.monotonic() - started, 3),
                                    "route": view,
                                    "kind": request_kind,
                                    "failureType": type(exc).__name__,
                                }
                            )
                            + "\n"
                        )
                        if len(errors) < 20:
                            errors.append(f"read_{view}_{type(exc).__name__}")
                        connection.close()
                        connection = http.client.HTTPConnection("127.0.0.1", args.port, timeout=5)
        connection.close()
        request_stream.flush()

    diagnostic_clock_start = None
    diagnostic_clock_end = None
    diagnostic_output = None
    diagnostic_collection = None
    if getattr(args, "diagnostic_timeline", False):
        from scripts.serving_lab_spans import LabSpans

        diagnostic_clock_start = exchange_clocks(state)
        diagnostic_output = LabSpans(
            args.output.with_suffix(".timeline.jsonl"), max_events=5_000_000
        )

        def diagnostic_phase(response, active_before=False, active_after=False):
            if time.monotonic() - started < args.baseline_seconds:
                return "baseline"
            if active_before or active_after or response.headers.get("x-soak-reload-active") == "1":
                return "refresh"
            return "postRefreshIdle"

        def diagnostic_emit(row):
            diagnostic_output.emit(
                {key: value for key, value in row.items() if key != "generation"}
            )
            if row.get("completionObservedMonotonicSeconds") is not None:
                last_http_completion[0] = row["completionObservedMonotonicSeconds"] - started
            if "failureType" in row:
                read_error_counts[row["failureType"]] += 1
                return
            phase = row["phase"]
            key = f"{row['route']}:{phase}:{row['kind']}:{row['status']}"
            response_counts[key] += 1
            latencies[phase].append(row["elapsedMs"])
            read_series.setdefault(key, []).append(row["elapsedMs"])
            observed_generations[row["generation"]] += 1

        def read_diagnostics():
            try:
                diagnostic_reads(
                    args,
                    stop,
                    fixture_league_key,
                    diagnostic_emit,
                    phase=diagnostic_phase,
                    worker_state=worker_active.is_set,
                )
            except Exception as exc:
                read_error_counts[type(exc).__name__] += 1

        read_loop = read_diagnostics

    reader = threading.Thread(target=read_loop, name="soak-reads", daemon=True)
    reader.start()
    process = psutil.Process()
    previous_cpu = {}
    samples = []
    sampler_timings = []
    recovery = QuietRecovery(args.duration_seconds, args.quiet_seconds)
    quiet_checks = []
    last_quiet_check = None
    last_quiet_sample_index = None
    child = None
    league_child = None
    pending_followup = None
    followup_failed = False
    cycle_worker_failed = False
    sequence = 0
    next_refresh = args.baseline_seconds + 1
    fault_thread = None

    def exercise_faults():
        held = None
        fault_stage = "reject_candidate"
        try:
            accepted = store.read_current(ASSET, KEY)
            try:
                store.publish(
                    ASSET,
                    KEY,
                    {"invalid": b"bad"},
                    {"modelVersion": "soak", "inputGenerations": {}, "configHash": "soak"},
                    validator=lambda _: False,
                )
                errors.append("corrupt_candidate_accepted")
            except (RejectedCandidate, AttestationError):
                assert store.read_current(ASSET, KEY).generation_id == accepted.generation_id
                events.append({"kind": "rejected_candidate_kept_pointer"})
            fault_stage = "stop_reader_for_corruption"
            assert state.stop(), "reader did not stop for controlled corruption"
            captured = state.current
            path = (
                args.root
                / ASSET
                / KEY
                / "generations"
                / accepted.generation_id
                / "files"
                / "views"
                / "rankings.json"
            )
            original = path.read_bytes()
            fault_stage = "retain_memory_on_corrupt_disk"
            try:
                with _publish_lock(store.root / "store.lock", 5):
                    path.write_bytes(b"controlled soak corruption")
                    os.utime(args.root / ASSET / KEY / "current.json", None)
                assert not state.reload_if_changed()
                assert state.last_error and state.current == captured
                events.append({"kind": "corrupt_disk_generation_retained_memory"})
            finally:
                with _publish_lock(store.root / "store.lock", 5):
                    path.write_bytes(original)
                    os.utime(args.root / ASSET / KEY / "current.json", None)
            fault_stage = "recover_and_restart_reader"
            assert state.reload_if_changed() and state.last_error is None
            state.start(0.5)
            events.append({"kind": "reader_recovered_and_restarted"})
            fault_stage = "capacity_exhaustion"
            pressure = store_for(args.root, 1)
            # In certified mode pressure must use a valid signed candidate;
            # changing signed inputs would test tamper refusal before capacity.
            from src.serving.artifacts import _plain

            pressure_metadata = (
                {
                    key: value
                    for key, value in _plain(accepted.manifest).items()
                    if key
                    not in {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
                }
                if attestation_enabled()
                else {
                    "modelVersion": accepted.manifest["modelVersion"],
                    "inputGenerations": {"soak": "pressure"},
                    "configHash": accepted.manifest["configHash"],
                }
            )
            try:
                pressure.publish(
                    ASSET,
                    KEY,
                    accepted.files,
                    pressure_metadata,
                    validator=load_generation,
                )
                errors.append("capacity_exhaustion_accepted")
            except RetentionCapacityError:
                assert store.read_current(ASSET, KEY).generation_id == accepted.generation_id
                events.append({"kind": "capacity_exhaustion_kept_pointer"})
            worker_active.set()
            fault_stage = "terminate_worker_with_queued_requests"
            held = launch(args, "hold")
            ready = args.root / "worker-ready"
            deadline = time.monotonic() + 30
            while not ready.exists() and held.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert ready.exists(), "worker never acquired source lease"
            from src.serving.producer_status import pending_source_refresh, pending_league_refresh

            source_request = request_source_refresh(store, "soak")
            league_request = request_league_refresh(store, "soak")
            held.terminate()
            finish_worker(held, intentional_termination=True, events=events, errors=errors)
            with _publish_lock(store.root / "producer.lock", 2):
                assert pending_source_refresh(store)["requestId"] == source_request["requestId"]
                assert pending_league_refresh(store)["requestId"] == league_request["requestId"]
                events.append({"kind": "terminated_worker_lease_reacquired_with_queued_requests"})
            fault_stage = "restart_worker_acknowledge_requests"
            resumed = launch(args, "unchanged")
            try:
                resumed_outcome = finish_worker(resumed, timeout=60, events=events, errors=errors)
                assert resumed_outcome["receiptError"] is None
                assert resumed.returncode == 0
            finally:
                if resumed.poll() is None:
                    resumed.terminate()
                    finish_worker(resumed, events=events, errors=errors)
            assert pending_source_refresh(store) is None and pending_league_refresh(store) is None
            events.append(
                {
                    "kind": "restarted_worker_acknowledged_preserved_requests",
                    "workerKind": "unchanged",
                    "exitCode": 0,
                }
            )
        except Exception as exc:
            errors.append(f"fault_{fault_stage}_{type(exc).__name__}")
        finally:
            if held is not None and held.poll() is None:
                held.terminate()
                finish_worker(held, intentional_termination=True, events=events, errors=errors)
            worker_active.clear()

    sample_file = args.output.with_suffix(".samples.jsonl")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with resource_observations(
            sample_file,
            lambda timing: sample(
                process,
                args.root,
                started,
                previous_cpu,
                args.child_ledger,
                web_identity,
                timing=timing,
            ),
            samples,
            errors,
            progress=lambda: {"httpErrors": sum(read_error_counts.values())},
            timings=sampler_timings,
            timed_observe=True,
        ):
            while recovery.phase != "done" and not stop.is_set():
                tick = time.monotonic()
                elapsed = tick - started
                if child is not None and child.poll() is not None:
                    outcome = finish_worker(child, events=events, errors=errors)
                    cycle_worker_failed |= (
                        child.returncode != 0 or outcome["receiptError"] is not None
                    )
                    if child.returncode != 0:
                        errors.append(f"worker_exit_{child.returncode}")
                    if (
                        child.returncode == 0
                        and outcome["receiptError"] is None
                        and outcome["receipt"]["leagueOutcome"] == "busy"
                    ):
                        pending_followup = DeferredLeagueFollowup(time.monotonic())
                        events.append(
                            {"kind": "league_followup", "phase": "queued", "sequence": sequence}
                        )
                    events.append(
                        {
                            "kind": "refresh",
                            "sequence": sequence,
                            "exitCode": child.returncode,
                            "workerKind": "unchanged" if sequence % 3 == 0 else "changed",
                            "attemptId": outcome["attemptId"],
                            "workerOutcome": outcome["receipt"],
                            "publishedGeneration": json.loads(
                                store.read_current(ASSET, KEY).files["index.json"]
                            )["generation"]
                            if child.returncode == 0 and outcome["receiptError"] is None
                            else None,
                        }
                    )
                    child = None
                if league_child is not None and league_child.poll() is not None:
                    outcome = finish_worker(league_child, events=events, errors=errors)
                    if pending_followup is not None and pending_followup.attempts:
                        pending_followup.worker_finished(store.current_version(ASSET, KEY))
                    cycle_worker_failed |= (
                        league_child.returncode != 0 or outcome["receiptError"] is not None
                    )
                    if league_child.returncode != 0:
                        errors.append(f"league_worker_exit_{league_child.returncode}")
                    events.append(
                        {
                            "kind": "league_refresh",
                            "exitCode": league_child.returncode,
                            "attemptId": outcome["attemptId"],
                            "sequence": outcome["sequence"],
                            "workerOutcome": outcome["receipt"],
                        }
                    )
                    league_child = None
                if pending_followup is not None:
                    companions_drained = child is None and league_child is None
                    drain_ready = False
                    if companions_drained and pending_followup.attempts and not cycle_worker_failed:
                        drain_ready = state.control("drain", timeout=5)["result"]["ready"]
                    action = pending_followup.action(
                        time.monotonic(),
                        companions_drained=companions_drained,
                        cycle_failed=cycle_worker_failed,
                        canonical_version=store.current_version(ASSET, KEY),
                        drain_ready=drain_ready,
                    )
                    if action == "launch":
                        request_league_refresh(store, "soak_followup")
                        league_child = launch(args, "league", sequence)
                        events.append(
                            {
                                "kind": "league_followup",
                                "phase": "launched",
                                "attempt": pending_followup.attempts,
                                "sequence": sequence,
                            }
                        )
                    elif action in {"complete", "failed"}:
                        events.append(
                            {
                                "kind": "league_followup",
                                "phase": action,
                                "attempts": pending_followup.attempts,
                                "sequence": sequence,
                            }
                        )
                        if action == "failed":
                            followup_failed = True
                            errors.append(pending_followup.failure)
                        pending_followup = None
                if (
                    child is None
                    and league_child is None
                    and pending_followup is None
                    and (fault_thread is None or not fault_thread.is_alive())
                ):
                    worker_active.clear()
                if (
                    elapsed >= next_refresh
                    and child is None
                    and league_child is None
                    and pending_followup is None
                    and not followup_failed
                    and (fault_thread is None or not fault_thread.is_alive())
                    and recovery.admitting(time.monotonic() - started)
                ):
                    sequence += 1
                    cycle_worker_failed = False
                    request_source_refresh(store, "soak")
                    request_league_refresh(store, "soak")
                    worker_active.set()
                    child = launch(args, "unchanged" if sequence % 3 == 0 else "changed", sequence)
                    league_child = launch(args, "league", sequence)
                    next_refresh = elapsed + args.refresh_seconds
                if (
                    elapsed >= args.baseline_seconds
                    and child is None
                    and league_child is None
                    and pending_followup is None
                    and not followup_failed
                    and fault_thread is None
                    and recovery.admitting(time.monotonic() - started)
                ):
                    fault_thread = threading.Thread(
                        target=exercise_faults, name="soak-faults", daemon=True
                    )
                    fault_thread.start()
                if web_child.poll() is not None:
                    errors.append("fatal_web_child_exit")
                    break
                elapsed = time.monotonic() - started
                if elapsed >= args.duration_seconds:
                    # No more work is admitted. Wait for natural worker exit,
                    # then prove that both independent readers consumed their
                    # latest pointers, before starting the full quiet interval.
                    drain_timing = ObservationTiming()
                    with drain_timing.stage("workerLedger"):
                        remaining = args.child_ledger.remaining(
                            process, exclude=web_tree_identities
                        )
                    workers_drained = (
                        child is None
                        and league_child is None
                        and pending_followup is None
                        and (fault_thread is None or not fault_thread.is_alive())
                        and remaining["remainingCount"] == 0
                        and remaining["unknownCount"] == 0
                    )
                    drain = {"ready": False, "continuityToken": None}
                    if workers_drained:
                        try:
                            with drain_timing.stage("readerDrainControl"):
                                drain = state.control("drain", timeout=5)["result"]
                        except Exception as exc:
                            drain["failureType"] = type(exc).__name__
                    now = time.monotonic() - started
                    current_sample_count = len(samples)
                    first_new = (
                        last_quiet_sample_index
                        if last_quiet_sample_index is not None
                        else max(0, current_sample_count - 1)
                    )
                    observation_complete = quiet_observations_ready(
                        samples[:current_sample_count], first_new, now
                    ) and (last_quiet_check is None or now - last_quiet_check <= 2)
                    last_quiet_sample_index = current_sample_count
                    last_quiet_check = now
                    previous_phase = recovery.phase
                    recovery.advance(
                        now,
                        workers_drained=workers_drained,
                        reloads_drained=drain["ready"],
                        token=drain["continuityToken"],
                        observation_complete=observation_complete,
                    )
                    quiet_checks.append(
                        {
                            "seconds": now,
                            "phase": recovery.phase,
                            "workers": remaining,
                            "observationComplete": observation_complete,
                            "reader": drain,
                            "stages": drain_timing.snapshot(),
                        }
                    )
                    if recovery.phase != previous_phase:
                        events.append({"kind": "recovery_phase", "phase": recovery.phase})
                    if (
                        recovery.phase != "done"
                        and now
                        >= args.duration_seconds + args.drain_timeout_seconds + args.quiet_seconds
                    ):
                        errors.append("quiet_drain_timeout")
                        break
                    if recovery.phase == "done":
                        break
                stop.wait(max(0, 1 - (time.monotonic() - tick)))
    except Exception as exc:
        errors.append(f"driver_{type(exc).__name__}")
    finally:
        observation_seconds = time.monotonic() - started
        observed_sample_count = len(samples)
        stop.set()
        reader.join(timeout=6)
        if reader.is_alive():
            errors.append("http_read_thread_stop_timeout")
        else:
            try:
                request_stream.close()
            except Exception as exc:
                errors.append(f"request_stream_close_{type(exc).__name__}")
        if diagnostic_output:
            try:
                diagnostic_clock_end = exchange_clocks(state)
            except Exception as exc:
                errors.append(f"diagnostic_closing_clock_{type(exc).__name__}")
            try:
                diagnostic_output.close()
            except Exception as exc:
                errors.append(f"diagnostic_output_close_{type(exc).__name__}")
            try:
                diagnostic_collection = diagnostic_output.collection_report()
                if diagnostic_collection.get("complete") is not True:
                    errors.append("diagnostic_driver_collection_incomplete")
            except Exception as exc:
                errors.append(f"diagnostic_collection_report_{type(exc).__name__}")
                diagnostic_collection = {"complete": False}
        cleanup_worker(child, label="source", events=events, errors=errors)
        cleanup_worker(league_child, label="league", events=events, errors=errors)
        if fault_thread is not None:
            fault_thread.join(timeout=45)
            if fault_thread.is_alive():
                errors.append("fault_thread_stop_timeout")
        try:
            if not state.stop():
                errors.append("reader_stop_timeout")
        except Exception:
            errors.append("web_control_stop_failed")
        web_exit_code = cleanup_web(state, web_child, errors)
    samples.append(
        sample(process, args.root, started, previous_cpu, args.child_ledger, web_identity)
    )
    if read_error_counts:
        errors.append("unexpected_read_failures")
    quiet_report = recovery.report()
    quiet_bounds = (
        (quiet_report["quietStartSeconds"], quiet_report["quietEndSeconds"])
        if quiet_report["verified"]
        else (math.inf, -math.inf)
    )
    report = summarize(
        samples,
        latencies,
        args.baseline_seconds,
        errors,
        events,
        args.budget_bytes,
        children=args.child_ledger.remaining(process),
        idle_process_count=baseline_process_count,
        quiet_bounds=quiet_bounds,
        latency_policy=args.latency_policy,
    )
    report["responseCounts"] = dict(response_counts)
    report["webAdoptionMode"] = "producer-attested" if attestation_enabled() else "full-validation"
    http_report = http_latency_summary(read_series, latency_policy=args.latency_policy)
    report.update(
        {
            key: value
            for key, value in http_report.items()
            if key not in {"checks", "legacyLatencyChecks"}
        }
    )
    report["legacyLatencyChecks"].update(http_report["legacyLatencyChecks"])
    report["checks"].update(http_report["checks"])
    report["observedHttpGenerations"] = dict(observed_generations)
    report["checks"]["changedPublicationsObservedByHttp"] = publication_evidence(
        events, observed_generations
    )
    report["readErrorCounts"] = dict(read_error_counts)
    report["responseAuditCacheMisses"] = audit.cache_misses
    report["responseAuditCacheLimit"] = audit.limit
    report["idleProcessCount"] = baseline_process_count
    report["inputSha256"] = hashlib.sha256(args.contract.read_bytes()).hexdigest()
    report["rawInputSha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    report["harnessSha256"] = harness_sha
    report["diagnosticSpansEnabled"] = getattr(args, "diagnostic_spans", False)
    report["workerOutcomesFile"] = args.root.with_name(args.root.name + ".workers.jsonl").name
    report["webExitCode"] = web_exit_code
    report["workerOutcomeLimits"] = {
        "records": WORKER_RECEIPT_COUNT_LIMIT,
        "bytesPerRecord": WORKER_RECEIPT_LIMIT,
    }
    report["workerStderrAccounting"] = (
        "observed equals validReceiptFramingBytes plus discarded bytes; valid framing is the sole "
        "validated newline-terminated receipt including prefix/newline after protocol and exit checks; "
        "all other bytes, including every frame of an invalid stream, are discarded"
    )
    report["leagueFollowupPolicy"] = {
        "sourceAdmissionWaitSeconds": 0,
        "standaloneAdmissionWaitSeconds": 20,
        "controlDeadlineSeconds": 90,
        "maximumAttempts": 2,
        "secondAttemptRequiresNewCanonical": True,
        "globalDrainTimeoutSeconds": args.drain_timeout_seconds,
    }
    report["checks"]["deferredLeagueFollowupsConverged"] = (
        pending_followup is None and not followup_failed
    )
    if diagnostic_output:
        report["diagnosticClockStart"] = diagnostic_clock_start
        report["diagnosticClockEnd"] = diagnostic_clock_end
        report["diagnosticRequestsDropped"] = diagnostic_output.dropped
        report["driverCollection"] = diagnostic_collection
        report["diagnosticOrder"] = args.diagnostic_order
        report["diagnosticPacing"] = args.diagnostic_pacing
        report["diagnosticCollector"] = args.diagnostic_collector
        report["diagnosticCase"] = getattr(args, "diagnostic_case", None)
        report["diagnosticAdoption"] = getattr(args, "diagnostic_adoption", False)
        report["diagnosticRequiredRunSequence"] = (
            ["on", "off", "on"]
            if getattr(args, "diagnostic_case", None) == "natural-transitions"
            else None
        )
        report["diagnosticRequestComparison"] = (
            "conditional versus immediately preceding same-route unconditional in this cycle"
            if getattr(args, "diagnostic_case", None) == "natural-transitions"
            else "configured diagnostic order"
        )
        report["serverCollection"] = diagnostic_collection_summary(
            args, web_exit_code=web_exit_code
        )
        report["checks"]["diagnosticDriverCollectionLossless"] = (
            diagnostic_output.dropped == 0
            and diagnostic_collection is not None
            and diagnostic_collection.get("complete") is True
        )
        report["checks"]["diagnosticClockBoundsAvailable"] = bool(
            diagnostic_clock_start
            and diagnostic_clock_start["comparable"]
            and diagnostic_clock_end
            and diagnostic_clock_end["comparable"]
        )
        report["checks"]["diagnosticServerCollectionLosslessWhenEnabled"] = (
            args.diagnostic_collector != "on" or report["serverCollection"]["complete"] is True
        )
    report["requestClockOriginSeconds"] = started
    report["checks"]["harnessUnchangedDuringRun"] = (
        harness_sha == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
    provenance_end = code_provenance(
        repo_root, diagnostic_spans=getattr(args, "diagnostic_spans", False)
    )
    report["codeProvenance"] = {"startup": provenance_start, "end": provenance_end}
    report["checks"]["productAndHelperCodeUnchangedDuringRun"] = provenance_start == provenance_end
    report["environment"] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "psutil": psutil.__version__,
        "hostMemoryBytes": psutil.virtual_memory().total,
        "logicalCpus": psutil.cpu_count(),
    }
    report["retention"] = store.retention(apply=False)
    report["readObservationSeconds"] = observation_seconds
    report["servingExerciseSeconds"] = min(observation_seconds, args.duration_seconds)
    report["quietRecovery"] = quiet_report
    report.update(
        observation_duration_summary(
            samples[:observed_sample_count],
            requested_exercise_seconds=args.duration_seconds,
            elapsed_observation_seconds=observation_seconds,
            requested_quiet_seconds=args.quiet_seconds,
            quiet_report=quiet_report,
            last_http_completion_seconds=last_http_completion[0],
        )
    )
    report["checks"]["verifiedWorkerAndReloadFreeQuietRecovery"] = quiet_report["verified"]
    baseline_resources = [
        row
        for row in samples[:observed_sample_count]
        if args.baseline_seconds / 2 <= row["seconds"] < args.baseline_seconds
        and row["processCount"] == baseline_process_count
    ]
    final_resources = [
        row
        for row in samples[:observed_sample_count]
        if wholly_within(row, quiet_bounds) and row["processCount"] == baseline_process_count
    ]
    report["resourceOwnership"] = {
        "scope": "Attribution only; aggregate RSS/handle gates remain unchanged",
        "webMissingObservationCount": sum(
            not row.get("webResourceObservationComplete", False)
            for row in samples[:observed_sample_count]
        ),
        "baseline": {
            key: statistics.median(row[key] for row in baseline_resources)
            if baseline_resources and all(row.get(key) is not None for row in baseline_resources)
            else None
            for key in (
                "driverRssBytes",
                "webRssBytes",
                "driverDescriptorCount",
                "webDescriptorCount",
            )
        },
        "final": {
            key: statistics.median(row[key] for row in final_resources)
            if final_resources and all(row.get(key) is not None for row in final_resources)
            else None
            for key in (
                "driverRssBytes",
                "webRssBytes",
                "driverDescriptorCount",
                "webDescriptorCount",
            )
        },
    }
    report["observedSampleCountBeforeCleanup"] = observed_sample_count
    report["maxObservationSampleGapSeconds"] = maximum_observation_gap(
        samples[:observed_sample_count], observation_seconds
    )
    report["sampleCoverageFraction"] = min(1, observed_sample_count / max(1, observation_seconds))
    complete_sample_count = sum(
        row.get("resourceObservationComplete", False) for row in samples[:observed_sample_count]
    )
    report["completeResourceSampleCount"] = complete_sample_count
    report["completeResourceCoverageFraction"] = min(
        1, complete_sample_count / max(1, observation_seconds)
    )
    report["checks"]["completeResourceCoverageAtLeast99Percent"] = (
        report["completeResourceCoverageFraction"] >= 0.99
    )
    report["checks"].update(
        sampling_evidence(
            observed_sample_count, observation_seconds, report["maxObservationSampleGapSeconds"]
        )
    )
    report["samplingRequirements"] = {"minimumCoverageFraction": 0.99, "maximumGapSeconds": 2}
    report["quietSeconds"] = args.quiet_seconds
    report["full60MinuteSoak"] = (
        not getattr(args, "diagnostic_spans", False)
        and report["servingExerciseSeconds"] >= 3600
        and args.baseline_seconds >= 600
        and args.quiet_seconds >= 120
        and quiet_report["verified"]
        and report["checks"]["completeResourceCoverageAtLeast99Percent"]
        and all(
            sampling_evidence(
                observed_sample_count, observation_seconds, report["maxObservationSampleGapSeconds"]
            ).values()
        )
    )
    report["full60MinuteSoakMeaning"] = (
        "Structural duration, baseline, verified quiet and sampling qualification only; "
        "full release requires full60MinuteSoak and passed both true"
    )
    report["checks"]["uninstrumentedAcceptance"] = not getattr(args, "diagnostic_spans", False)
    report["passed"] = all(report["checks"].values())
    latency_file = args.output.with_suffix(".latencies.json")
    latency_file.write_text(json.dumps(read_series) + "\n", encoding="utf-8")
    report["latencyObservationsFile"] = latency_file.name
    report["timestampedHttpObservationsFile"] = request_file.name
    sampler_file = args.output.with_suffix(".sampler.jsonl")
    sampler_file.write_text(
        "".join(json.dumps(row) + "\n" for row in sampler_timings), encoding="utf-8"
    )
    quiet_file = args.output.with_suffix(".quiet.jsonl")
    quiet_file.write_text("".join(json.dumps(row) + "\n" for row in quiet_checks), encoding="utf-8")
    report["samplerObservationsFile"] = sampler_file.name
    report["quietObservationsFile"] = quiet_file.name
    report["samplerTiming"] = {
        "scope": "Inclusive wall/thread CPU stage clocks; driver process CPU overlaps request/audit work; completed timings serialized after observation",
        "observationCount": len(sampler_timings),
        "missedTicks": sum(row.get("missedTicksAfter", 0) for row in sampler_timings),
        "maxLateBySeconds": max((row["lateBySeconds"] for row in sampler_timings), default=None),
        "stageMaxWallMs": {
            name: max(row["stages"].get(name, {}).get("wallMs", 0) for row in sampler_timings)
            for name in sorted({name for row in sampler_timings for name in row["stages"]})
        },
    }
    report["automaticSleepPrevention"] = (
        "temporary Windows system request" if os.name == "nt" else "not configured"
    )
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--contract", type=Path)
    parser.add_argument(
        "--raw-input",
        type=Path,
        help="Defaults to raw-input.json beside the exported full contract",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--duration-seconds", type=float, default=3600)
    parser.add_argument("--baseline-seconds", type=float, default=600)
    parser.add_argument("--refresh-seconds", type=float, default=30)
    parser.add_argument(
        "--quiet-seconds",
        type=float,
        default=125,
        help="Required continuous worker/reload-free tail after the exercise duration",
    )
    parser.add_argument(
        "--drain-timeout-seconds",
        type=float,
        default=300,
        help="Maximum extra drain/reset allowance beyond exercise plus required quiet",
    )
    parser.add_argument("--budget-bytes", type=int, default=512 * 1024**2)
    parser.add_argument(
        "--latency-policy",
        choices=LATENCY_POLICIES,
        default=LEGACY_LATENCY_POLICY,
        help="Acceptance evaluation only; local-prepared-hybrid-v1 requires campaign owner authorization",
    )
    parser.add_argument("--worker", choices=("changed", "unchanged", "hold", "league", "web"))
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Fixture HTTP loopback port; driver chooses a free port by default",
    )
    parser.add_argument("--sequence", type=int, default=0)
    parser.add_argument("--attempt-id", help=argparse.SUPPRESS)
    parser.add_argument(
        "--diagnostic-spans",
        action="store_true",
        help="Local attribution only; never acceptance timing",
    )
    parser.add_argument("--diagnostic-timeline", action="store_true")
    parser.add_argument("--diagnostic-adoption", action="store_true")
    parser.add_argument("--diagnostic-case", choices=("natural-transitions", "stale-etag"))
    parser.add_argument("--diagnostic-quiet", choices=("factorial", "control"))
    parser.add_argument("--diagnostic-order", choices=("original", "balanced"), default="original")
    parser.add_argument(
        "--diagnostic-pacing", choices=("event", "continuous", "sleep"), default="event"
    )
    parser.add_argument("--diagnostic-collector", choices=("on", "off"), default="on")
    parser.add_argument("--diagnostic-body-read", choices=("whole", "split"), default="whole")
    parser.add_argument("--diagnostic-connection", choices=("reuse", "new"), default="reuse")
    parser.add_argument("--diagnostic-seed", type=int, default=20260911)
    parser.add_argument("--diagnostic-cell-seconds", type=float, default=60)
    parser.add_argument("--diagnostic-repetitions", type=int, default=3)
    parser.add_argument("--diagnostic-asgi", action="store_true")
    parser.add_argument("--diagnostic-response-owner", choices=("app", "frozen"), default="app")
    parser.add_argument("--diagnostic-socket-reads", action="store_true")
    parser.add_argument("--diagnostic-reload-observer", choices=("on", "off"), default="on")
    parser.add_argument("--diagnostic-transport", action="store_true")
    parsed = parser.parse_args()
    diagnostic_options = any(
        arg.startswith("--diagnostic-") and arg != "--diagnostic-spans" for arg in sys.argv[1:]
    )
    if diagnostic_options and not (parsed.diagnostic_spans and parsed.diagnostic_timeline):
        parser.error("diagnostic experiments require --diagnostic-spans --diagnostic-timeline")
    if parsed.diagnostic_case:
        if not parsed.diagnostic_adoption or parsed.diagnostic_quiet:
            parser.error(
                "adoption cases require --diagnostic-adoption and cannot combine with quiet controls"
            )
        if parsed.diagnostic_case == "natural-transitions" and (
            parsed.diagnostic_order != "original"
            or parsed.diagnostic_pacing != "event"
            or parsed.diagnostic_connection != "reuse"
            or parsed.diagnostic_body_read != "whole"
            or parsed.duration_seconds != 900
            or parsed.baseline_seconds != 60
            or parsed.refresh_seconds != 30
            or parsed.quiet_seconds != 125
            or parsed.drain_timeout_seconds != 300
        ):
            parser.error(
                "natural transitions require900s/60s/30s/125s/300s and original/event/reuse/whole request protocol"
            )
    if parsed.diagnostic_response_owner == "frozen" and not (
        parsed.worker == "web" or parsed.diagnostic_quiet == "control"
    ):
        parser.error("frozen responses require a quiet diagnostic control")
    if parsed.diagnostic_reload_observer == "off" and not (
        parsed.worker == "web" or parsed.diagnostic_quiet == "control"
    ):
        parser.error("reload observer control requires a quiet diagnostic control")
    if parsed.diagnostic_transport and not (
        parsed.worker == "web" or parsed.diagnostic_quiet == "control"
    ):
        parser.error("transport observations require a quiet diagnostic control")
    if (
        not math.isfinite(parsed.diagnostic_cell_seconds)
        or parsed.diagnostic_cell_seconds <= 0
        or parsed.diagnostic_repetitions <= 0
    ):
        parser.error("diagnostic cells and repetitions must be positive and finite")
    if not parsed.port:
        import socket

        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            parsed.port = reservation.getsockname()[1]
    if parsed.worker == "web":
        import asyncio

        # Windows' event-loop self-pipe creates a private socketpair. Construct
        # it before the strict network guard; providers are not imported yet.
        parsed.web_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(parsed.web_loop)
    disable_network(parsed.port)
    if parsed.worker:
        worker(parsed)
    else:
        if parsed.contract is None or parsed.output is None:
            parser.error("--contract and --output are required for the driver")
        if not valid_durations(
            parsed.duration_seconds,
            parsed.baseline_seconds,
            parsed.refresh_seconds,
            parsed.quiet_seconds,
            parsed.drain_timeout_seconds,
        ):
            parser.error("require finite positive durations and baseline < exercise duration")
        with prevent_automatic_sleep():
            raise SystemExit(main(parsed))
