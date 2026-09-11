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
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
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


def worker(args):
    from src.serving.artifacts import _plain, _publish_lock
    from src.serving.builder import prepare_generation
    from src.serving.producer_status import claim_source_refresh
    from src.serving.serialization import ASSET, KEY, load_generation, publish_generation

    store = store_for(args.root, args.budget_bytes)
    if args.worker == "web":
        web_worker(args, store)
        return
    if args.worker == "league":
        league_worker(store)
        return
    # Hold the same lease as production source/league owners. A terminated child
    # cannot retain an OS-owned lock. The fixture never invokes external sources.
    with _publish_lock(store.root / "producer.lock", 20):
        if args.worker == "hold":
            (args.root / "worker-ready").write_text("ready", encoding="utf-8")
            time.sleep(120)
            return
        claim_source_refresh(store)
        artifact = store.read_current(ASSET, KEY)
        if args.worker == "unchanged":
            metadata = {
                key: value
                for key, value in _plain(artifact.manifest).items()
                if key
                not in {"schemaVersion", "asset", "key", "generationId", "files", "observedAt"}
            }
            observed = store.publish(
                ASSET, KEY, artifact.files, metadata, validator=load_generation
            )
            assert observed.generation_id == artifact.generation_id
        else:
            current = load_generation(artifact)
            contract = copy.deepcopy(current.contract)
            contract.setdefault("meta", {})["soakSequence"] = args.sequence
            candidate = prepare_generation(contract, current.raw, current.source, current.health)
            publish_generation(candidate, store=store)
        league_worker(store)


def league_worker(store):
    from types import SimpleNamespace
    from src.serving.artifacts import _publish_lock
    from src.serving.league_views import prepare_league_views, publish_league_views
    from src.serving.producer_status import claim_league_refresh
    from src.serving.serialization import ASSET, KEY, load_generation

    with _publish_lock(store.root / "league-producer.lock", 20):
        claim_league_refresh(store)
        board = load_generation(store.read_current(ASSET, KEY))
        meta = board.contract.get("meta") or {}
        cfg = SimpleNamespace(key=meta.get("leagueKey"), scoring_profile=meta.get("scoringProfile"))
        bundle = prepare_league_views(board, cfg)
        publish_league_views(bundle, store, board=board, cfg=cfg)


def launch(args, kind, sequence=0):
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
    if kind == "web" and getattr(args, "diagnostic_spans", False):
        command.append("--diagnostic-spans")
    child = subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        # The long-lived web app may log every request. An unread stderr pipe
        # fills and blocks its event loop, manufacturing availability failures.
        stderr=subprocess.DEVNULL if kind == "web" else subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if hasattr(args, "child_ledger"):
        args.child_ledger.observe_pid(child.pid)
    return child


def web_worker(args, store):
    """Real local app/HTTP stack with only the producer lifespan replaced."""
    from contextlib import asynccontextmanager
    import uvicorn
    from starlette.concurrency import run_in_threadpool
    from src.api import league_registry
    from src.serving.league_views import LeagueServingReader
    from src.serving.runtime import AtomicRuntime
    from src.serving.serialization import ASSET, KEY, load_generation

    os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")
    import server

    tracer = None
    if getattr(args, "diagnostic_spans", False):
        from scripts.serving_lab_spans import LabSpans
        from src.serving import serialization

        tracer = LabSpans(args.root.with_name(args.root.name + ".spans.jsonl"))
        tracer.install(server)
        load_generation = serialization.load_generation

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
    leagues = LeagueServingReader(store, lambda: server.latest_serving_generation)
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

    @server.app.middleware("http")
    async def observe_reload(request, call_next):
        active = state._reload_lock.locked() or leagues._refresh_lock.locked()
        if tracer and request.url.path in {
            "/api/read-models/rankings",
            "/api/read-models/trade/context",
        }:
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

    @server.app.api_route("/__soak/{action}", methods=["GET", "POST"])
    async def control(action: str):
        result = None
        if action == "stop":
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

    config = uvicorn.Config(
        server.app, host="127.0.0.1", port=args.port, access_log=False, log_level="warning"
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
            return json.loads(response.body)
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


def http_latency_summary(series):
    p95 = {key: percentile(values) for key, values in series.items()}
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
    return {
        "p95MillisecondsByReadSeries": p95,
        "baselineComparisons": comparisons,
        "checks": {
            "requiredHttpReadSeriesObserved": all(p95.get(key) is not None for key in required),
            "eachHttpReadSeriesP95Below75ms": bool(p95)
            and all(value is not None and value < 75 for value in p95.values()),
            "eachRefreshReadSeriesWithin20Percent": bool(comparisons)
            and all(
                p95.get(baseline) is not None and p95[key] <= p95[baseline] * 1.2
                for key, baseline in comparisons.items()
            ),
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
        if event.get("workerKind") == "changed" and event.get("exitCode") == 0
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
    warm = percentile(latencies["baseline"])
    refresh = percentile(latencies["refresh"])
    checks = {
        "noIncorrectResponsesOrUnexpectedFailures": not errors,
        "preparedEndpointP95Below75ms": warm is not None
        and refresh is not None
        and max(warm, refresh) < 75,
        "refreshDegradationAtMost20Percent": warm is not None
        and refresh is not None
        and refresh <= warm * 1.2,
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
        "p95Milliseconds": {key: percentile(values) for key, values in latencies.items()},
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


def main(args):
    import psutil
    from src.serving.artifacts import RejectedCandidate, RetentionCapacityError, _publish_lock
    from src.serving.builder import prepare_generation
    from src.serving.producer_status import request_league_refresh, request_source_refresh
    from src.serving.serialization import ASSET, KEY, load_generation, publish_generation

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
                        elapsed = (time.perf_counter() - before) * 1000
                        phase = (
                            "baseline"
                            if time.monotonic() - started < args.baseline_seconds
                            else (
                                "refresh"
                                if overlapping
                                or worker_active.is_set()
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
            except RejectedCandidate:
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
            try:
                pressure.publish(
                    ASSET,
                    KEY,
                    accepted.files,
                    {
                        "modelVersion": accepted.manifest["modelVersion"],
                        "inputGenerations": {"soak": "pressure"},
                        "configHash": accepted.manifest["configHash"],
                    },
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
            held.communicate(timeout=10)
            with _publish_lock(store.root / "producer.lock", 2):
                assert pending_source_refresh(store)["requestId"] == source_request["requestId"]
                assert pending_league_refresh(store)["requestId"] == league_request["requestId"]
                events.append({"kind": "terminated_worker_lease_reacquired_with_queued_requests"})
            fault_stage = "restart_worker_acknowledge_requests"
            resumed = launch(args, "unchanged")
            try:
                resumed.communicate(timeout=60)
                assert resumed.returncode == 0
            finally:
                if resumed.poll() is None:
                    resumed.terminate()
                    resumed.communicate(timeout=10)
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
                held.communicate(timeout=10)
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
                    child.communicate(timeout=10)
                    if child.returncode != 0:
                        errors.append(f"worker_exit_{child.returncode}")
                    events.append(
                        {
                            "kind": "refresh",
                            "sequence": sequence,
                            "exitCode": child.returncode,
                            "workerKind": "unchanged" if sequence % 3 == 0 else "changed",
                            "publishedGeneration": json.loads(
                                store.read_current(ASSET, KEY).files["index.json"]
                            )["generation"]
                            if child.returncode == 0
                            else None,
                        }
                    )
                    child = None
                if league_child is not None and league_child.poll() is not None:
                    league_child.communicate(timeout=10)
                    if league_child.returncode != 0:
                        errors.append(f"league_worker_exit_{league_child.returncode}")
                    events.append({"kind": "league_refresh", "exitCode": league_child.returncode})
                    league_child = None
                if (
                    child is None
                    and league_child is None
                    and (fault_thread is None or not fault_thread.is_alive())
                ):
                    worker_active.clear()
                if (
                    elapsed >= next_refresh
                    and child is None
                    and league_child is None
                    and (fault_thread is None or not fault_thread.is_alive())
                    and recovery.admitting(time.monotonic() - started)
                ):
                    sequence += 1
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
            request_stream.close()
        if child is not None:
            if child.poll() is None:
                child.terminate()
            child.communicate(timeout=10)
        if league_child is not None:
            if league_child.poll() is None:
                league_child.terminate()
            league_child.communicate(timeout=10)
        if fault_thread is not None:
            fault_thread.join(timeout=45)
            if fault_thread.is_alive():
                errors.append("fault_thread_stop_timeout")
        try:
            if not state.stop():
                errors.append("reader_stop_timeout")
        except Exception:
            errors.append("web_control_stop_failed")
        try:
            state.control("shutdown")
            web_child.communicate(timeout=10)
        except Exception:
            errors.append("web_graceful_shutdown_failed")
            web_child.terminate()
            web_child.communicate(timeout=10)
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
    )
    report["responseCounts"] = dict(response_counts)
    http_report = http_latency_summary(read_series)
    report.update({key: value for key, value in http_report.items() if key != "checks"})
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
    parser.add_argument("--worker", choices=("changed", "unchanged", "hold", "league", "web"))
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Fixture HTTP loopback port; driver chooses a free port by default",
    )
    parser.add_argument("--sequence", type=int, default=0)
    parser.add_argument(
        "--diagnostic-spans",
        action="store_true",
        help="Local attribution only; never acceptance timing",
    )
    parsed = parser.parse_args()
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
