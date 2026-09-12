"""Private provider-free generation lifetime experiment; never a product GC policy.

Producer work runs in a separate process. The measured process uses the actual
server aliases, AtomicRuntime and LeagueServingReader. Reports contain sizes,
counts and repository-relative allocation locations, never payload content.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
import tracemalloc
import weakref
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def produce(args):
    from scripts.soak_prepared_serving import disable_network, league_worker, store_for, worker
    from src.serving.builder import prepare_generation
    from src.serving.serialization import publish_generation

    disable_network()
    if args.sequence:
        worker(
            SimpleNamespace(
                root=args.root,
                budget_bytes=args.budget_bytes,
                worker="changed",
                sequence=args.sequence,
            )
        )
        return
    contract = json.loads(args.contract.read_bytes())
    raw = json.loads(args.raw_input.read_bytes())
    store = store_for(args.root, args.budget_bytes)
    board = prepare_generation(
        contract,
        raw,
        {"type": "offline-lifetime", "producedAt": contract.get("scrapeTimestamp")},
        {"ok": True},
    )
    publish_generation(board, store=store)
    league_worker(store)


def publish_next(args, sequence):
    subprocess.run(
        [
            sys.executable,
            __file__,
            "--producer",
            "--sequence",
            str(sequence),
            "--root",
            str(args.root),
            "--contract",
            str(args.contract),
            "--raw-input",
            str(args.raw_input),
            "--budget-bytes",
            str(args.budget_bytes),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def allocation_location(frame):
    path = Path(frame.filename)
    try:
        name = path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        name = path.name
    return f"{name}:{frame.lineno}"


def record_allocator_stats(path, sequence):
    """Capture CPython's own allocator counters; no heap trimming or product GC."""
    if not hasattr(sys, "_debugmallocstats"):
        return False
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"\nSEQUENCE {sequence}\n")
        stream.flush()
        saved = os.dup(2)
        try:
            os.dup2(stream.fileno(), 2)
            sys._debugmallocstats()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
    return True


def count_state(state, reader, server, references):
    from src.serving.runtime import ServingGeneration, PreparedPayload, PreparedBytes
    from src.serving.league_views import LeagueViews

    objects = gc.get_objects()
    counts = {
        "gcTrackedObjects": len(objects),
        "liveServingGenerationCount": 0,
        "liveLeagueBundleCount": 0,
        "livePreparedPayloadCount": 0,
    }
    buffers = {}
    for obj in objects:
        if type(obj) is ServingGeneration:
            counts["liveServingGenerationCount"] += 1
        elif type(obj) is LeagueViews:
            counts["liveLeagueBundleCount"] += 1
        elif type(obj) in (PreparedPayload, PreparedBytes):
            counts["livePreparedPayloadCount"] += 1
            buffers[id(obj.raw)] = len(obj.raw)
            buffers[id(obj.gzip)] = len(obj.gzip)
    counts["serializedBufferCount"] = len(buffers)
    counts["serializedBufferBytes"] = sum(buffers.values())
    roots = [state.current, server.latest_serving_generation]
    roots.extend(pair[0] for pair in reader._current.values())
    counts["rootCanonicalObjectCount"] = len({id(root) for root in roots if root is not None})
    counts["rootGenerationCount"] = len({root.generation_id for root in roots if root is not None})
    counts["acceptedLeaguePairCount"] = len(reader._current)
    counts["supersededCanonicalWeakRefsAlive"] = sum(ref() is not None for ref in references[:-1])
    counts["runtimeVersionSlots"] = int(state._loaded_version is not None)
    counts["leagueVersionSlots"] = len(reader._versions)
    counts["overrideCacheEntries"] = len(server._OVERRIDES_RESPONSE_CACHE)
    counts["draftCacheEntries"] = len(server._DRAFT_CAPITAL_CACHE)
    counts["legacyCacheEntries"] = {
        name: len(getattr(server, name))
        for name in (
            "_OVERLAY_RESPONSE_CACHE",
            "_PUBLIC_CONTRACT_BYTES_CACHE",
            "_OVERRIDES_RESPONSE_CACHE",
            "_DRAFT_CAPITAL_CACHE",
        )
    }
    counts["legacyNameIndexEntries"] = len(server._LIVE_BY_NAME_CACHE.get("value", {}))
    counts["currentPlayerIndexEntries"] = len(state.current.indexes.get("players", {}))
    counts["legacyAliasesMatchCurrent"] = all(
        getattr(server, name) is value
        for name, value in (
            ("latest_contract_data", state.current.contract),
            ("latest_data", state.current.raw),
            ("latest_runtime_data", state.current.views["runtime"].payload),
            ("latest_array_data", state.current.views["array"].payload),
            ("latest_startup_data", state.current.views["startup"].payload),
            ("latest_compact_data", state.current.views["compact"].payload),
        )
    )
    return counts


def measure(args):
    import psutil
    from scripts.soak_prepared_serving import disable_network, store_for
    from src.api import league_registry
    from src.serving.runtime import AtomicRuntime
    from src.serving.league_views import LeagueServingReader
    from src.serving.serialization import ASSET, KEY, load_web_generation as load_generation
    from src.serving.attestation import enabled as attestation_enabled

    if args.root.exists():
        raise ValueError("Use a new private store; existing evidence is never modified")
    publish_next(args, 0)
    os.environ.setdefault("ALLOW_DEFAULT_LOGIN_DEV", "1")
    import server

    disable_network()
    process = psutil.Process()
    store = store_for(args.root, args.budget_bytes)
    state = AtomicRuntime(
        store, ASSET, KEY, load_generation, on_publish=server._publish_serving_generation
    )
    reader = LeagueServingReader(store, lambda: state.current, lightweight=attestation_enabled())
    server._league_serving_reader = reader
    references = []
    if args.trace_frames:
        tracemalloc.start(args.trace_frames)
    baseline_snapshot = None
    phase_observations = []

    def allocation_phase(name, operation):
        def run(*values, **keywords):
            blocks = sys.getallocatedblocks()
            live_before = tracemalloc.get_traced_memory()[0] if args.trace_frames else None
            collections = sum(item["collections"] for item in gc.get_stats())
            if args.trace_frames:
                tracemalloc.reset_peak()
            cpu, wall = time.thread_time(), time.perf_counter()
            try:
                return operation(*values, **keywords)
            finally:
                live, peak = tracemalloc.get_traced_memory() if args.trace_frames else (None, None)
                phase_observations.append(
                    {
                        "phase": name,
                        "wallSeconds": time.perf_counter() - wall,
                        "threadCpuSeconds": time.thread_time() - cpu,
                        "netAllocatedBlocks": sys.getallocatedblocks() - blocks,
                        "liveBytesBefore": live_before,
                        "liveBytesAfter": live,
                        "peakBytesAboveStart": peak - live_before if peak is not None else None,
                        "gcCollections": sum(item["collections"] for item in gc.get_stats())
                        - collections,
                    }
                )

        return run

    state.build = allocation_phase("canonical.adoption", state.build)
    reader.refresh = allocation_phase("league.adoption_and_expiry", reader.refresh)
    started = time.perf_counter()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.with_suffix(".samples.jsonl").open("w", encoding="utf-8") as stream:
        for sequence in range(args.cycles + 1):
            phase_observations.clear()
            if sequence:
                publish_next(args, sequence)
            if args.trace_frames:
                tracemalloc.reset_peak()
            before = time.perf_counter()
            assert state.reload_if_changed(), state.last_error
            meta = state.current.contract.get("meta") or {}
            cfg = SimpleNamespace(
                key=meta.get("leagueKey"), scoring_profile=meta.get("scoringProfile")
            )
            league_registry.active_leagues = lambda: [cfg]
            reader.refresh()
            assert reader.capture(cfg.key)[0] is state.current
            references.append(weakref.ref(state.current))
            # Older weakrefs were already observed dead after their successor
            # adopted. Do not let diagnostic history itself pin allocator arenas.
            references[:] = references[-2:]
            load_seconds = time.perf_counter() - before
            row = {
                "sequence": sequence,
                "seconds": time.perf_counter() - started,
                "loadAndAdoptSeconds": load_seconds,
                "rssBeforeDiagnosticGcBytes": process.memory_info().rss,
                "retainedBaselineSnapshotPresent": baseline_snapshot is not None,
                "allocationPhases": list(phase_observations),
            }
            row.update(count_state(state, reader, server, references))
            row["diagnosticGcCollected"] = gc.collect() if sequence % args.gc_every == 0 else None
            row["rssAfterDiagnosticGcBytes"] = process.memory_info().rss
            row["tracemallocCurrentBytes"], row["tracemallocPeakBytes"] = (
                tracemalloc.get_traced_memory() if args.trace_frames else (None, None)
            )
            row["tracemallocBookkeepingBytes"] = (
                tracemalloc.get_tracemalloc_memory() if args.trace_frames else None
            )
            row["topAllocationDeltasFromInitial"] = []
            if args.trace_frames:
                snapshot = tracemalloc.take_snapshot()
                if baseline_snapshot is None:
                    baseline_snapshot = snapshot
                row["topAllocationDeltasFromInitial"] = [
                    {
                        "bytesDelta": stat.size_diff,
                        "countDelta": stat.count_diff,
                        "traceback": [allocation_location(frame) for frame in stat.traceback],
                    }
                    for stat in snapshot.compare_to(baseline_snapshot, "traceback")[:10]
                ]
                del snapshot
            row["allocatorStatsRecorded"] = record_allocator_stats(
                args.output.with_suffix(".allocator.txt"), sequence
            )
            stream.write(json.dumps(row) + "\n")
            stream.flush()
            print(
                json.dumps(
                    {
                        key: row[key]
                        for key in (
                            "sequence",
                            "loadAndAdoptSeconds",
                            "rssAfterDiagnosticGcBytes",
                            "tracemallocCurrentBytes",
                            "liveServingGenerationCount",
                            "supersededCanonicalWeakRefsAlive",
                        )
                    }
                ),
                flush=True,
            )
    report = {
        "scope": "Diagnostic, not acceptance timing: optional tracemalloc/snapshots, object enumeration, allocator counters and periodic explicit GC perturb RSS and CPU. Producers are separate processes; no providers/browser/HTTP.",
        "inputSha256": hashlib.sha256(args.contract.read_bytes()).hexdigest(),
        "traceFrames": args.trace_frames,
        "diagnosticGcEvery": args.gc_every,
        "reportRowsRetainedDuringMeasurement": False,
        "weakReferenceHistoryLimit": 2,
        "allocationPhaseScope": "Diagnostic only: net blocks/live bytes and traced peak above phase start, not total allocation traffic; tracing peaks reset per phase; GC collection counts are process-wide.",
        "rows": [
            json.loads(line)
            for line in args.output.with_suffix(".samples.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--raw-input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--trace-frames", type=int, default=3)
    parser.add_argument("--gc-every", type=int, default=3)
    parser.add_argument("--budget-bytes", type=int, default=536870912)
    parser.add_argument("--producer", action="store_true")
    parser.add_argument("--sequence", type=int, default=0)
    args = parser.parse_args()
    if args.producer:
        produce(args)
    else:
        if not args.output or args.cycles < 1 or args.gc_every < 1 or args.trace_frames < 0:
            parser.error("output, positive cycles/gc-every and nonnegative trace-frames required")
        measure(args)
