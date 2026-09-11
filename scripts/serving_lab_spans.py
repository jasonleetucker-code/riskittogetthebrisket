"""Opt-in local diagnostic spans, installed only by the private serving lab.

No arguments, paths, payload values, identities or exception messages are logged.
Inclusive spans overlap; consumers must not sum nested wall/CPU durations.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import gc
import gzip
import inspect
import json
import queue
import threading
import time
from contextlib import contextmanager
from pathlib import Path

_DUMPS = json.dumps


class LabSpans:
    def __init__(self, path, max_events=500_000):
        self.path = path
        self.phase = contextvars.ContextVar("lab_phase", default="none")
        self.generation = contextvars.ContextVar("lab_generation", default=None)
        self.request_id = contextvars.ContextVar("lab_request", default=None)
        self.depth = contextvars.ContextVar("lab_span_depth", default=0)
        self.loop_thread = threading.get_ident()
        self.active = False
        self.events = queue.Queue(maxsize=4096)
        self.max_events = max_events
        self.emitted = self.dropped = self.sequence = 0
        self.patches = []
        self.pulse_task = None
        self.gc_started = {}
        self.gc_installed = False
        self.writer = threading.Thread(target=self._write, name="lab-span-writer", daemon=True)
        self.writer.start()

    def _write(self):
        with self.path.open("w", encoding="utf-8") as stream:
            while True:
                event = self.events.get()
                if event is None:
                    break
                stream.write(_DUMPS(event) + "\n")
            stream.write(
                _DUMPS(
                    {
                        "event": "collection",
                        "emitted": self.emitted,
                        "dropped": self.dropped,
                        "scope": "diagnostic_only",
                    }
                )
                + "\n"
            )

    def emit(self, event):
        if self.emitted >= self.max_events:
            self.dropped += 1
            return
        try:
            self.events.put_nowait(event)
            self.emitted += 1
        except queue.Full:
            self.dropped += 1

    @contextmanager
    def span(self, stage, phase=None, generation=None):
        phase_token = self.phase.set(phase) if phase else None
        generation_token = self.generation.set(generation) if generation else None
        depth = self.depth.get()
        depth_token = self.depth.set(depth + 1)
        before = time.perf_counter_ns()
        cpu = time.thread_time_ns()
        process_cpu = time.process_time_ns()
        failed = False
        try:
            yield
        except BaseException:
            failed = True
            raise
        finally:
            end = time.perf_counter_ns()
            event = {
                "event": "span",
                "stage": stage,
                "phase": self.phase.get(),
                "startNs": before,
                "endNs": end,
                "wallNs": end - before,
                "threadCpuNs": time.thread_time_ns() - cpu,
                "processCpuNs": time.process_time_ns() - process_cpu,
                "threadId": threading.get_ident(),
                "eventLoopThread": threading.get_ident() == self.loop_thread,
                "servingActive": self.active,
                "depth": depth,
                "requestId": self.request_id.get(),
                "generation": self.generation.get(),
                "failed": failed,
            }
            self.depth.reset(depth_token)
            if phase_token is not None:
                self.phase.reset(phase_token)
            if generation_token is not None:
                self.generation.reset(generation_token)
            self.emit(event)

    def patch(self, owner, name, stage, phase=None, scoped=False):
        original = getattr(owner, name)
        if inspect.iscoroutinefunction(original):

            @functools.wraps(original)
            async def wrapped(*args, **kwargs):
                if scoped and self.phase.get() == "none":
                    return await original(*args, **kwargs)
                with self.span(stage, phase):
                    return await original(*args, **kwargs)
        else:

            @functools.wraps(original)
            def wrapped(*args, **kwargs):
                if scoped and self.phase.get() == "none":
                    return original(*args, **kwargs)
                generation = (
                    getattr(args[0], "generation_id", None)
                    if args and stage in {"canonical.load", "canonical.validate", "canonical.swap"}
                    else None
                )
                if (
                    not isinstance(generation, str)
                    or len(generation) != 64
                    or any(c not in "0123456789abcdef" for c in generation)
                ):
                    generation = None
                with self.span(stage, phase, generation):
                    return original(*args, **kwargs)

        self.patches.append((owner, name, original))
        setattr(owner, name, wrapped)

    def install(self, server):
        from src.serving import artifacts, builder, serialization, league_views, runtime

        for owner, name, stage, phase in (
            (runtime.AtomicRuntime, "reload_if_changed", "canonical.reload", "canonical"),
            (serialization, "load_generation", "canonical.load", "canonical"),
            (serialization, "_validate_generation", "canonical.validate", None),
            (serialization, "project_contract_views", "canonical.projections", None),
            (serialization, "player_index", "canonical.index", None),
            (league_views.LeagueServingReader, "refresh", "league.refresh", "league"),
            (league_views, "load_league_views", "league.load", None),
            (league_views, "validate_league_views", "league.validate", None),
            (league_views, "prepare_league_views", "league.fallback_prepare", None),
            (league_views, "expire_context", "league.expire", None),
            (builder, "prepare_payload", "payload.prepare", None),
            (league_views, "prepare_payload", "payload.prepare", None),
            (server, "_publish_serving_generation", "canonical.swap", None),
            (server, "_get_prepared_read_model", "endpoint.dispatch", "endpoint"),
            (server, "_scoring_identity_error", "endpoint.scoring", None),
            (server, "_serve_prepared_bytes", "endpoint.etag_and_bytes", None),
            (league_views.LeagueServingReader, "capture", "endpoint.capture", None),
            (artifacts.ArtifactStore, "current_version", "artifact.discovery_stat", None),
            (artifacts.ArtifactStore, "read_current", "artifact.copy_generation", None),
            (artifacts, "_check_path", "artifact.path_validation", None),
        ):
            self.patch(owner, name, stage, phase)
        for owner, name, stage in (
            (json, "loads", "decode.json"),
            (json, "dumps", "encode.json"),
            (gzip, "decompress", "decode.gzip"),
            (gzip, "compress", "encode.gzip"),
            (Path, "read_bytes", "file.read"),
            (Path, "stat", "file.stat"),
            (Path, "open", "file.open"),
        ):
            self.patch(owner, name, stage, scoped=True)
        original_lock = artifacts._publish_lock

        @contextmanager
        def measured_lock(*args, **kwargs):
            if self.phase.get() == "none":
                with original_lock(*args, **kwargs):
                    yield
                return
            before = time.perf_counter_ns()
            cpu = time.thread_time_ns()
            with original_lock(*args, **kwargs):
                self.emit(
                    {
                        "event": "lock_wait",
                        "stage": "store.lock",
                        "phase": self.phase.get(),
                        "startNs": before,
                        "endNs": time.perf_counter_ns(),
                        "threadCpuNs": time.thread_time_ns() - cpu,
                        "threadId": threading.get_ident(),
                    }
                )
                with self.span("store.lock.hold"):
                    yield

        self.patches.append((artifacts, "_publish_lock", original_lock))
        artifacts._publish_lock = measured_lock
        gc.callbacks.append(self.gc_callback)
        self.gc_installed = True

    def gc_callback(self, event, info):
        identity = threading.get_ident()
        if event == "start":
            self.gc_started[identity] = time.perf_counter_ns()
        else:
            before = self.gc_started.pop(identity, None)
            if before is not None:
                self.emit(
                    {
                        "event": "gc",
                        "startNs": before,
                        "endNs": time.perf_counter_ns(),
                        "threadId": identity,
                        "eventLoopThread": identity == self.loop_thread,
                        "collected": info["collected"],
                        "generation": info["generation"],
                    }
                )

    async def pulse(self):
        # Windows asyncio may admit timers early by its ~15.6ms clock
        # resolution. A 10ms pulse can spin under HTTP activity and perturb
        # the very workload it observes. Stay above that resolution.
        interval = 0.05
        while True:
            before = time.perf_counter_ns()
            await asyncio.sleep(interval)
            now = time.perf_counter_ns()
            self.emit(
                {
                    "event": "event_loop_delay",
                    "startNs": before,
                    "endNs": now,
                    "delayNs": max(0, now - before - int(interval * 1e9)),
                }
            )

    def begin_serving(self):
        self.active = True
        self.pulse_task = asyncio.create_task(self.pulse())

    async def end_serving(self):
        self.active = False
        if self.pulse_task:
            self.pulse_task.cancel()
            try:
                await self.pulse_task
            except asyncio.CancelledError:
                pass

    @contextmanager
    def request(self, route):
        self.sequence += 1
        request_id = self.sequence
        token = self.request_id.set(request_id)
        before = time.perf_counter_ns()
        try:
            yield request_id
        finally:
            self.emit(
                {
                    "event": "request",
                    "route": route,
                    "requestId": request_id,
                    "startNs": before,
                    "endNs": time.perf_counter_ns(),
                }
            )
            self.request_id.reset(token)

    def close(self):
        if self.gc_installed:
            gc.callbacks.remove(self.gc_callback)
        for owner, name, original in reversed(self.patches):
            setattr(owner, name, original)
        self.events.put(None, timeout=5)
        self.writer.join(timeout=10)
        if self.writer.is_alive():
            raise RuntimeError("diagnostic span writer did not finish")
