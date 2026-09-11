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
def resource_observations(path, observe, rows, errors, interval=1, progress=None):
    """Sample outside driver publication/child-start waits; never fill missed ticks."""
    done = threading.Event()

    def collect():
        try:
            with path.open("w", encoding="utf-8") as stream:
                deadline = time.monotonic()
                while not done.is_set():
                    row = observe()
                    rows.append(row)
                    stream.write(json.dumps(row) + "\n")
                    stream.flush()
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
                    deadline += interval
                    now = time.monotonic()
                    if deadline < now:
                        deadline = now + interval
                    done.wait(max(0, deadline - now))
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
        (args.root / "web-ready").write_text("ready", encoding="utf-8")
        try:
            yield
        finally:
            state.stop()
            leagues.stop()

    server.app.router.lifespan_context = fixture_lifespan

    @server.app.middleware("http")
    async def observe_reload(request, call_next):
        active = state._reload_lock.locked()
        response = await call_next(request)
        response.headers["X-Soak-Reload-Active"] = str(int(active or state._reload_lock.locked()))
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

    def control(self, action):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
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

    def remaining(self, parent):
        import psutil

        visible = {child.pid for child in parent.children(recursive=True)}
        with self.lock:
            identities = tuple(self.identities)
        remaining = reparented = unknown = 0
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


def sample(process, root, started, previous_cpu=None, child_ledger=None):
    import psutil

    members = [process, *process.children(recursive=True)]
    if child_ledger is not None:
        for member in members[1:]:
            child_ledger.observe(member)
    rss = peak = handles = 0
    cpu = 0.0
    cpu_delta = 0.0
    alive = 0
    for member in members:
        try:
            memory = member.memory_info()
            rss += memory.rss
            peak += getattr(memory, "peak_wset", memory.rss)
            handles += member.num_handles() if os.name == "nt" else member.num_fds()
            times = member.cpu_times()
            cpu += times.user + times.system
            if previous_cpu is not None:
                prior = previous_cpu.get(member.pid)
                current = times.user + times.system
                if prior is not None:
                    cpu_delta += max(0, current - prior)
                previous_cpu[member.pid] = current
            alive += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    # Lab root only, never source archives or unrelated caches.
    disk = 0
    for path in root.rglob("*"):
        try:
            if path.is_file():
                disk += path.stat().st_size
        except FileNotFoundError:
            # A publisher may rename its temporary file during this observation.
            continue
    return {
        "seconds": round(time.monotonic() - started, 3),
        "rssBytes": rss,
        "peakRssBytes": peak,
        "cpuSecondsLiveProcesses": cpu,
        "cpuSecondsSincePreviousSample": cpu_delta,
        "hostCpuPercent": psutil.cpu_percent(),
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
):
    baseline = [row for row in samples if baseline_seconds / 2 <= row["seconds"] < baseline_seconds]
    final = samples[-min(120, max(1, len(samples) // 10)) :]
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
    baseline_process_count = 1 + len(psutil.Process().children(recursive=True))

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
            lambda: sample(process, args.root, started, previous_cpu, args.child_ledger),
            samples,
            errors,
            progress=lambda: {"httpErrors": sum(read_error_counts.values())},
        ):
            while time.monotonic() - started < args.duration_seconds and not stop.is_set():
                tick = time.monotonic()
                elapsed = tick - started
                if child is not None and child.poll() is not None:
                    _, stderr = child.communicate()
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
                    league_child.communicate()
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
                    and elapsed < args.duration_seconds - args.quiet_seconds
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
                ):
                    fault_thread = threading.Thread(
                        target=exercise_faults, name="soak-faults", daemon=True
                    )
                    fault_thread.start()
                if web_child.poll() is not None:
                    errors.append("fatal_web_child_exit")
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
    samples.append(sample(process, args.root, started, previous_cpu, args.child_ledger))
    if read_error_counts:
        errors.append("unexpected_read_failures")
    report = summarize(
        samples,
        latencies,
        args.baseline_seconds,
        errors,
        events,
        args.budget_bytes,
        children=args.child_ledger.remaining(process),
        idle_process_count=baseline_process_count,
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
    report["checks"]["harnessUnchangedDuringRun"] = (
        harness_sha == hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    )
    report["environment"] = {
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "psutil": psutil.__version__,
        "hostMemoryBytes": psutil.virtual_memory().total,
        "logicalCpus": psutil.cpu_count(),
    }
    report["retention"] = store.retention(apply=False)
    report["readObservationSeconds"] = observation_seconds
    report["observedSampleCountBeforeCleanup"] = observed_sample_count
    report["maxObservationSampleGapSeconds"] = max(
        (
            right["seconds"] - left["seconds"]
            for left, right in zip(
                samples[:observed_sample_count], samples[1:observed_sample_count]
            )
        ),
        default=None,
    )
    report["sampleCoverageFraction"] = min(1, observed_sample_count / max(1, observation_seconds))
    report["checks"].update(
        sampling_evidence(
            observed_sample_count, observation_seconds, report["maxObservationSampleGapSeconds"]
        )
    )
    report["samplingRequirements"] = {"minimumCoverageFraction": 0.99, "maximumGapSeconds": 2}
    report["quietSeconds"] = args.quiet_seconds
    report["full60MinuteSoak"] = (
        observation_seconds >= 3600
        and args.baseline_seconds >= 600
        and args.quiet_seconds >= 120
        and all(
            sampling_evidence(
                observed_sample_count, observation_seconds, report["maxObservationSampleGapSeconds"]
            ).values()
        )
    )
    report["passed"] = all(report["checks"].values())
    latency_file = args.output.with_suffix(".latencies.json")
    latency_file.write_text(json.dumps(read_series) + "\n", encoding="utf-8")
    report["latencyObservationsFile"] = latency_file.name
    report["timestampedHttpObservationsFile"] = request_file.name
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
        help="Final no-launch window; short functional smoke may override",
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
        if (
            not 0 < parsed.baseline_seconds < parsed.duration_seconds
            or parsed.refresh_seconds <= 0
            or not 0 < parsed.quiet_seconds < parsed.duration_seconds
        ):
            parser.error("require 0 < baseline < duration and refresh > 0")
        with prevent_automatic_sleep():
            raise SystemExit(main(parsed))
