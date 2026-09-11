"""Offline, private-store resource soak; never starts providers or production units.

Uses the actual ArtifactStore, serialization validation, AtomicRuntime and the
server's prepared-byte response function. Auth/network/league routing are tested
separately: this isolates resource contention, not end-to-end API latency.
Install psutil only in an isolated lab environment; it is not a serving dependency.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def percentile(values, fraction=0.95):
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def disable_network():
    import socket

    def reject(*args, **kwargs):
        raise RuntimeError("network disabled in offline serving soak")

    socket.create_connection = reject
    socket.socket.connect = reject
    socket.socket.connect_ex = reject


def store_for(root, budget):
    from src.serving.artifacts import ArtifactStore, RetentionPolicy

    return ArtifactStore(root, retention_policy=RetentionPolicy(max_bytes=budget))


def worker(args):
    from src.serving.artifacts import _plain, _publish_lock
    from src.serving.builder import prepare_generation
    from src.serving.producer_status import claim_source_refresh
    from src.serving.serialization import ASSET, KEY, load_generation, publish_generation

    store = store_for(args.root, args.budget_bytes)
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
    ]
    return subprocess.Popen(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def sample(process, root, started, previous_cpu=None):
    import psutil

    members = [process, *process.children(recursive=True)]
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


def summarize(samples, latencies, baseline_seconds, errors, events, budget):
    baseline = [row for row in samples if baseline_seconds / 2 <= row["seconds"] < baseline_seconds]
    final = samples[-min(120, max(1, len(samples) // 10)) :]
    # Compare idle-parent samples to avoid treating a currently running worker as
    # a leak. Peak tree RSS remains recorded for capacity planning.
    baseline_idle = [row for row in baseline if row["processCount"] == 1]
    final_idle = [row for row in final if row["processCount"] == 1]
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
        "preparedByteResponseWithinWarm1s": warm is not None
        and refresh is not None
        and max(warm, refresh) <= 1000,
        "refreshDegradationAtMost20Percent": warm is not None
        and refresh is not None
        and refresh <= warm * 1.2,
        "rssGrowthBound": before is not None
        and after is not None
        and after - before <= max(before * 0.1, 64 * 1024**2),
        "handlesReturnNearBaseline": handle_before is not None
        and handle_after is not None
        and handle_after <= handle_before + max(10, handle_before * 0.1),
        "noRemainingObservedChildren": bool(samples) and samples[-1]["processCount"] == 1,
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
        "latencyScope": "captured AtomicRuntime generation through server._serve_prepared_bytes; excludes auth, league lookup, HTTP/network",
        "readCounts": {key: len(value) for key, value in latencies.items()},
        "p95Milliseconds": {"baseline": warm, "refresh": refresh},
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
            "Changed input uses a non-value metadata revision; canonical values remain fixed",
            "CPU seconds include currently live processes; completed child totals are unavailable",
            "Observed fixture child cleanup does not prove cleanup of real scraper/browser children or reparented processes",
        ],
    }


def main(args):
    import psutil
    from starlette.requests import Request
    from src.serving.artifacts import RejectedCandidate, RetentionCapacityError, _publish_lock
    from src.serving.builder import prepare_generation
    from src.serving.producer_status import request_league_refresh, request_source_refresh
    from src.serving.runtime import AtomicRuntime
    from src.serving.serialization import ASSET, KEY, load_generation, publish_generation

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
    del candidate, contract, raw
    reload_active = threading.Event()

    def observed_load(artifact):
        reload_active.set()
        try:
            return load_generation(artifact)
        finally:
            reload_active.clear()

    state = AtomicRuntime(store, ASSET, KEY, observed_load)
    assert state.reload_if_changed()
    # Import without lifespan: no embedded scrape, scheduler or server listener.
    os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")
    import server

    stop = threading.Event()
    errors = []
    events = []
    latencies = {"baseline": [], "refresh": [], "postRefreshIdle": []}
    worker_active = threading.Event()
    started = time.monotonic()
    state.start(0.5)

    def read_loop():
        while not stop.wait(0.01):
            try:
                before = time.perf_counter()
                captured = state.current
                view = captured.views["rankings"]
                request = Request(
                    {
                        "type": "http",
                        "headers": [(b"accept-encoding", b"gzip")],
                        "query_string": b"",
                    }
                )
                response = server._serve_prepared_bytes(request, view, captured.generation_id)
                elapsed = (time.perf_counter() - before) * 1000
                phase = (
                    "baseline"
                    if time.monotonic() - started < args.baseline_seconds
                    else (
                        "refresh"
                        if worker_active.is_set()
                        or reload_active.is_set()
                        or state._reload_lock.locked()
                        else "postRefreshIdle"
                    )
                )
                latencies[phase].append(elapsed)
                assert response.status_code == 200 and response.body is view.gzip
                assert response.headers["x-data-generation"] == captured.generation_id
                assert view.payload["meta"]["readModelGeneration"] == captured.generation_id
                conditional = Request(
                    {**request.scope, "headers": [(b"if-none-match", view.etag.encode())]}
                )
                assert (
                    server._serve_prepared_bytes(
                        conditional, view, captured.generation_id
                    ).status_code
                    == 304
                )
            except Exception as exc:
                errors.append(type(exc).__name__)
                stop.set()

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
            try:
                with _publish_lock(store.root / "store.lock", 5):
                    path.write_bytes(b"controlled soak corruption")
                    os.utime(args.root / ASSET / KEY / "current.json", None)
                assert not state.reload_if_changed()
                assert state.last_error and state.current is captured
                events.append({"kind": "corrupt_disk_generation_retained_memory"})
            finally:
                with _publish_lock(store.root / "store.lock", 5):
                    path.write_bytes(original)
                    os.utime(args.root / ASSET / KEY / "current.json", None)
            assert state.reload_if_changed() and state.last_error is None
            state.start(0.5)
            events.append({"kind": "reader_recovered_and_restarted"})
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
            errors.append(f"fault_exercise_{type(exc).__name__}")
        finally:
            if held is not None and held.poll() is None:
                held.terminate()
                held.communicate(timeout=10)
            worker_active.clear()

    sample_file = args.output.with_suffix(".samples.jsonl")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with sample_file.open("w", encoding="utf-8") as stream:
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
                    and elapsed < args.duration_seconds - 125
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
                row = sample(process, args.root, started, previous_cpu)
                samples.append(row)
                stream.write(json.dumps(row) + "\n")
                stream.flush()
                if len(samples) % 60 == 0:
                    print(
                        json.dumps(
                            {
                                "seconds": row["seconds"],
                                "samples": len(samples),
                                "errors": len(errors),
                            }
                        ),
                        flush=True,
                    )
                stop.wait(max(0, 1 - (time.monotonic() - tick)))
    except Exception as exc:
        errors.append(f"driver_{type(exc).__name__}")
    finally:
        observation_seconds = time.monotonic() - started
        observed_sample_count = len(samples)
        stop.set()
        reader.join(timeout=5)
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
        if not state.stop():
            errors.append("reader_stop_timeout")
    samples.append(sample(process, args.root, started, previous_cpu))
    report = summarize(samples, latencies, args.baseline_seconds, errors, events, args.budget_bytes)
    report["inputSha256"] = hashlib.sha256(args.contract.read_bytes()).hexdigest()
    report["rawInputSha256"] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    report["harnessSha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
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
    report["sampleCoverageFraction"] = min(1, observed_sample_count / max(1, observation_seconds))
    report["full60MinuteSoak"] = observation_seconds >= 3600 and args.baseline_seconds >= 600
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
    parser.add_argument("--budget-bytes", type=int, default=512 * 1024**2)
    parser.add_argument("--worker", choices=("changed", "unchanged", "hold", "league"))
    parser.add_argument("--sequence", type=int, default=0)
    parsed = parser.parse_args()
    disable_network()
    if parsed.worker:
        worker(parsed)
    else:
        if parsed.contract is None or parsed.output is None:
            parser.error("--contract and --output are required for the driver")
        if not 0 < parsed.baseline_seconds < parsed.duration_seconds or parsed.refresh_seconds <= 0:
            parser.error("require 0 < baseline < duration and refresh > 0")
        raise SystemExit(main(parsed))
