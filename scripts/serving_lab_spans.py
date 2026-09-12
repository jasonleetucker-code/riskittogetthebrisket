"""Opt-in local diagnostic spans, installed only by the private serving lab.

No arguments, paths, payload values, raw identities or exception messages are logged.
Adoption mode records only hashed content identities and existing byte metadata.
Inclusive spans overlap; consumers must not sum nested wall/CPU durations.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import gc
import gzip
import hashlib
import inspect
import json
import queue
import socket
import threading
import time
import weakref
from collections import deque
from collections.abc import Mapping
from contextlib import contextmanager
from itertools import islice
from pathlib import Path

_DUMPS = json.dumps
_ROUTES = {
    "/api/read-models/rankings": "rankings",
    "/api/read-models/trade/context": "trade",
}
_RESPONSE_CLASSES = frozenset(
    {
        "Response",
        "JSONResponse",
        "StreamingResponse",
        "PlainTextResponse",
        "HTMLResponse",
        "FileResponse",
        "RedirectResponse",
    }
)
_ADOPTION_STAGES = frozenset(
    {
        "canonical.reload",
        "canonical.load",
        "canonical.web_load",
        "canonical.install",
        "canonical.swap",
        "league.refresh",
        "league.adopt",
        "league.load",
        "league.web_load",
        "league.expire",
        "endpoint.capture",
        "endpoint.etag_and_bytes",
    }
)
_SNAPSHOT_LIMIT = 32


def _collection_failure(stage, error):
    # Exception subclasses can have arbitrary names. Never retain their text,
    # arguments, paths, traceback or an unbounded class name in diagnostic output.
    kind = next(
        (
            owner.__name__
            for owner in (OSError, ValueError, TypeError, RuntimeError, queue.Full)
            if isinstance(error, owner)
        ),
        "OtherException",
    )
    return {"stage": stage, "exceptionClass": kind}


def adoption_identity(value):
    """A bounded, cross-process token for a known content identity, never arbitrary text."""
    if (
        type(value) is not str
        or len(value) not in {40, 64}
        or any(char not in "0123456789abcdef" for char in value)
    ):
        return None
    return hashlib.sha256(b"serving-lab-identity-v1\0" + value.encode("ascii")).hexdigest()


def _board_snapshot(board):
    return {
        "boardToken": adoption_identity(getattr(board, "generation_id", None)),
        "artifactToken": adoption_identity(getattr(board, "artifact_generation_id", None)),
    }


def _prepared_snapshot(prepared):
    # These are existing byte carriers and tiny metadata mappings. Do not read
    # .payload, decode either body, hash the body, or fetch another artifact.
    meta = getattr(prepared, "metadata", None)
    meta = meta if isinstance(meta, Mapping) else {}
    ready = meta.get("sleeperDataReady")
    freshness = meta.get("leagueFreshnessState")
    view = getattr(prepared, "payload_view", None)
    raw, compressed = getattr(prepared, "raw", None), getattr(prepared, "gzip", None)
    return {
        "etagToken": adoption_identity(getattr(prepared, "etag", None)),
        "view": view if view in {"rankings", "trade"} else "other",
        "rawBytes": len(raw) if type(raw) is bytes else None,
        "gzipBytes": len(compressed) if type(compressed) is bytes else None,
        "sleeperDataReady": ready if type(ready) is bool else None,
        "freshnessState": freshness if freshness in {"stale", "unknown"} else None,
    }


def _bundle_snapshot(bundle):
    views = getattr(bundle, "views", {})
    return {
        "boardToken": adoption_identity(getattr(bundle, "board_generation", None)),
        "views": {name: _prepared_snapshot(views.get(name)) for name in ("rankings", "trade")},
    }


def _capture_snapshot(captured):
    if not isinstance(captured, tuple) or len(captured) != 2:
        return None
    return {"board": _board_snapshot(captured[0]), "bundle": _bundle_snapshot(captured[1])}


class LabSpans:
    def __init__(
        self,
        path,
        max_events=500_000,
        *,
        timeline_only=False,
        collector_enabled=True,
        adoption_timeline=False,
    ):
        if type(max_events) is not int or max_events < 1:
            raise ValueError("max_events must be a positive integer")
        if type(adoption_timeline) is not bool:
            raise ValueError("adoption_timeline must be a boolean")
        self.path = Path(path)
        self.timeline_only = timeline_only
        self.collector_enabled = collector_enabled
        self.adoption_timeline = adoption_timeline
        self.adoption_errors = self.adoption_snapshot_drops = 0
        self.server = None
        self.phase = contextvars.ContextVar("lab_phase", default="none")
        self.generation = contextvars.ContextVar("lab_generation", default=None)
        self.request_id = contextvars.ContextVar("lab_request", default=None)
        # A shared per-request object also survives task-copying middleware.
        self.request_state = contextvars.ContextVar("lab_request_state", default=None)
        self.depth = contextvars.ContextVar("lab_span_depth", default=0)
        self.loop_thread = threading.get_ident()
        self.active = False
        self.events = queue.Queue(maxsize=4096)
        self.max_events = max_events
        self.emitted = self.dropped = self.sequence = 0
        self.collection_lock = threading.Lock()
        self.closed = False
        self.clock_emitted = False
        self.patches = []
        self.pulse_task = None
        self.gc_started = {}
        self.gc_installed = False
        self.transport_observer = None
        self.writer = None
        self.written = 0
        self.footer_written = self.stream_flushed = self.stream_closed = False
        self.writer_failure = self.close_failure = None
        if collector_enabled:
            self.writer = threading.Thread(target=self._write, name="lab-span-writer", daemon=True)
            self.writer.start()

    def _write(self):
        stream = None
        stage = "open"
        try:
            stream = self.path.open("w", encoding="utf-8")
            while True:
                event = self.events.get()
                if event is None:
                    break
                stage = "event_write"
                stream.write(_DUMPS(event) + "\n")
                self.written += 1
            stage = "footer_write"
            stream.write(
                _DUMPS(
                    {
                        "event": "collection",
                        "emitted": self.emitted,
                        "written": self.written,
                        "dropped": self.dropped,
                        "scope": "diagnostic_only",
                        "completionBoundary": "footer_before_flush_and_close",
                        "transport": self.transport_report(),
                        **({"adoption": self.adoption_report()} if self.adoption_timeline else {}),
                    }
                )
                + "\n"
            )
            self.footer_written = True
            stage = "flush"
            stream.flush()
            self.stream_flushed = True
        except BaseException as error:
            self.writer_failure = _collection_failure(stage, error)
        finally:
            if stream is not None:
                try:
                    stream.close()
                    self.stream_closed = True
                except BaseException as error:
                    if self.writer_failure is None:
                        self.writer_failure = _collection_failure("close", error)

    def collection_report(self):
        """Final in-process writer evidence; an on-disk footer alone is not this proof."""
        stopped = self.writer is not None and not self.writer.is_alive()
        complete = bool(
            self.collector_enabled
            and self.closed
            and stopped
            and self.footer_written
            and self.stream_flushed
            and self.stream_closed
            and self.written == self.emitted
            and not (self.dropped or self.writer_failure or self.close_failure)
        )
        return {
            "enabled": self.collector_enabled,
            "closed": self.closed,
            "writerStopped": stopped,
            "footerWritten": self.footer_written,
            "streamFlushed": self.stream_flushed,
            "streamClosed": self.stream_closed,
            "emitted": self.emitted,
            "written": self.written,
            "dropped": self.dropped,
            "writerFailure": self.writer_failure,
            "closeFailure": self.close_failure,
            "complete": complete,
        }

    def emit(self, event):
        if not self.collector_enabled or self.closed:
            return
        with self.collection_lock:
            if self.closed:
                return
            if self.emitted >= self.max_events:
                self.dropped += 1
                return
            try:
                self.events.put_nowait(event)
                self.emitted += 1
            except queue.Full:
                self.dropped += 1

    def _clock_metadata(self):
        if self.clock_emitted or not self.collector_enabled:
            return
        self.clock_emitted = True
        before = time.perf_counter_ns()
        utc_ns = time.time_ns()
        after = time.perf_counter_ns()
        info = time.get_clock_info("perf_counter")
        self.emit(
            {
                "event": "clock_metadata",
                "perfCounterBeforeNs": before,
                "utcNs": utc_ns,
                "perfCounterAfterNs": after,
                "clock": "perf_counter_ns",
                "resolutionSeconds": info.resolution,
                "implementation": info.implementation,
                "monotonic": info.monotonic,
                "adjustable": info.adjustable,
                "timelineOnly": self.timeline_only,
                **({"adoptionTimeline": True} if self.adoption_timeline else {}),
                "scope": "diagnostic_only",
                "sendBoundary": "await_asgi_send_return",
            }
        )

    def _timeline(self, stage, **fields):
        if self.collector_enabled:
            state = self.request_state.get() or {}
            self.emit(
                {
                    "event": "timeline",
                    "stage": stage,
                    "timestampNs": time.perf_counter_ns(),
                    "threadCpuNs": time.thread_time_ns(),
                    "threadId": threading.get_ident(),
                    "requestId": self.request_id.get(),
                    "route": state.get("route"),
                    **fields,
                }
            )

    def _response_metadata(self, response):
        state = self.request_state.get()
        if state is None:
            return
        if state["responseClass"] != "unknown":
            return
        name = type(response).__name__
        state["responseClass"] = name if name in _RESPONSE_CLASSES else "Other"
        self._timeline("response.created", responseClass=state["responseClass"])

    def adoption_report(self):
        return {
            "enabled": self.adoption_timeline,
            "observationErrors": self.adoption_errors,
            "snapshotDrops": self.adoption_snapshot_drops,
            "snapshotLimit": _SNAPSHOT_LIMIT,
            "eventDrops": self.dropped,
            "complete": self.adoption_timeline
            and self.collector_enabled
            and not (self.adoption_errors or self.adoption_snapshot_drops or self.dropped),
            "boundary": "wrapper_bracket_not_pointer_assignment",
        }

    def _adoption_state(self, stage, args):
        owner = args[0] if args else None
        if stage in {"canonical.reload", "canonical.install"}:
            return {
                "accepted": _board_snapshot(getattr(owner, "_current", None)),
                "errorPresent": bool(getattr(owner, "_last_error", None)),
            }
        if stage == "canonical.swap":
            return {
                "accepted": _board_snapshot(getattr(self.server, "latest_serving_generation", None))
            }
        if stage in {"league.refresh", "league.adopt"}:
            captures = getattr(owner, "_current", {})
            count = len(captures)
            with self.collection_lock:
                self.adoption_snapshot_drops += max(0, count - _SNAPSHOT_LIMIT)
            return {
                "accepted": [
                    _capture_snapshot(item) for item in islice(captures.values(), _SNAPSHOT_LIMIT)
                ],
                "captureCount": count,
                "errorPresent": bool(getattr(owner, "last_error", None)),
            }
        if stage == "league.expire":
            return {"selected": _bundle_snapshot(owner)}
        return None

    def _adoption_result(self, stage, result):
        if stage == "endpoint.capture":
            return _capture_snapshot(result)
        if stage in {"canonical.load", "canonical.web_load"}:
            return _board_snapshot(result)
        if stage in {"league.load", "league.web_load", "league.expire"}:
            return _bundle_snapshot(result)
        return None

    @contextmanager
    def _observe_adoption(self, stage, args):
        if (
            not self.adoption_timeline
            or not self.collector_enabled
            or stage not in _ADOPTION_STAGES
        ):
            yield None
            return

        # Metadata inspection must never change the wrapped return or exception.
        def inspect_safely(callback):
            try:
                return callback()
            except Exception:
                with self.collection_lock:
                    self.adoption_errors += 1
                return None

        before = inspect_safely(lambda: self._adoption_state(stage, args))
        input_snapshot = None
        if stage in {"canonical.load", "canonical.web_load", "league.load", "league.web_load"}:
            input_snapshot = (
                inspect_safely(
                    lambda: {
                        "artifactToken": adoption_identity(getattr(args[0], "generation_id", None))
                    }
                )
                if args
                else None
            )
        elif stage == "canonical.install" and len(args) > 1:
            input_snapshot = inspect_safely(lambda: _board_snapshot(args[1]))
        selected = None
        if stage == "endpoint.etag_and_bytes" and len(args) >= 3:
            selected = inspect_safely(
                lambda: {
                    "boardToken": adoption_identity(args[2]),
                    "prepared": _prepared_snapshot(args[1]),
                }
            )
        holder = {"returned": False, "result": None}
        started, cpu = time.perf_counter_ns(), time.thread_time_ns()
        try:
            yield holder
        finally:
            ended, cpu_end = time.perf_counter_ns(), time.thread_time_ns()
            result = holder["result"]
            state = self.request_state.get() or {}
            status = (
                inspect_safely(lambda: getattr(result, "status_code", None))
                if (stage == "endpoint.etag_and_bytes" and holder["returned"])
                else None
            )
            self.emit(
                {
                    "event": "adoption",
                    "stage": stage,
                    "phase": stage.split(".", 1)[0],
                    "boundary": "wrapper_bracket_not_pointer_assignment",
                    "startNs": started,
                    "endNs": ended,
                    "wallNs": ended - started,
                    "threadCpuNs": cpu_end - cpu,
                    "threadId": threading.get_ident(),
                    "eventLoopThread": threading.get_ident() == self.loop_thread,
                    "requestId": self.request_id.get(),
                    "route": state.get("route"),
                    "before": before,
                    "after": inspect_safely(lambda: self._adoption_state(stage, args)),
                    "inputSnapshot": input_snapshot,
                    "returned": holder["returned"],
                    "resultBoolean": result if type(result) is bool else None,
                    "resultSnapshot": inspect_safely(lambda: self._adoption_result(stage, result))
                    if holder["returned"]
                    else None,
                    "selected": selected,
                    "responseStatus": status
                    if type(status) is int and 100 <= status <= 599
                    else None,
                }
            )

    def wrap_app(self, app):
        """Observe ASGI send returns, not TCP acknowledgement or client receipt."""
        self._clock_metadata()

        async def observed(scope, receive, send):
            route = _ROUTES.get(scope.get("path")) if scope.get("type") == "http" else None
            if route is None:
                return await app(scope, receive, send)
            with self.collection_lock:
                self.sequence += 1
                request_id = self.sequence
            request_token = self.request_id.set(request_id)
            phase_token = self.phase.set("endpoint")
            state = {"route": route, "status": None, "responseBytes": 0, "responseClass": "unknown"}
            state_token = self.request_state.set(state)
            self._timeline("asgi.arrival")
            complete = False
            first_body = False
            outcome = "returned"

            async def observed_send(message):
                nonlocal complete, first_body
                kind = message.get("type")
                if kind == "http.response.start":
                    state["status"] = message.get("status")
                    headers = list(message.get("headers", []))
                    # Copy only the outgoing collection and append an opaque ID.
                    headers = [
                        (k, v) for k, v in headers if k.lower() != b"x-soak-request-sequence"
                    ]
                    headers.append((b"x-soak-request-sequence", str(request_id).encode("ascii")))
                    message = {**message, "headers": headers}
                    self._timeline(
                        "asgi.response.start.begin",
                        status=state["status"],
                        responseClass=state["responseClass"],
                    )
                    sent = False
                    try:
                        await send(message)
                        sent = True
                    finally:
                        self._timeline("asgi.response.start.end", status=state["status"], sent=sent)
                elif kind == "http.response.body":
                    size = len(message.get("body", b""))
                    final = not message.get("more_body", False)
                    initial = size > 0 and not first_body
                    if initial:
                        first_body = True
                        self._timeline("asgi.response.first_body.begin")
                    self._timeline("asgi.response.body.begin", bodyBytes=size, final=final)
                    sent = False
                    try:
                        await send(message)
                        sent = True
                        state["responseBytes"] += size
                        complete = final
                    finally:
                        self._timeline(
                            "asgi.response.body.end", bodyBytes=size, final=final, sent=sent
                        )
                        if initial:
                            self._timeline("asgi.response.first_body.end", sent=sent)
                    if final:
                        self._timeline(
                            "asgi.response.complete",
                            status=state["status"],
                            responseBytes=state["responseBytes"],
                            responseClass=state["responseClass"],
                        )
                else:
                    await send(message)

            try:
                return await app(scope, receive, observed_send)
            except asyncio.CancelledError:
                outcome = "cancelled"
                raise
            except BaseException:
                outcome = "failed"
                raise
            finally:
                self._timeline(
                    "asgi.complete",
                    outcome=outcome,
                    responseComplete=complete,
                    responseBytes=state["responseBytes"],
                    status=state["status"],
                    responseClass=state["responseClass"],
                )
                self.request_state.reset(state_token)
                self.phase.reset(phase_token)
                self.request_id.reset(request_token)

        return observed

    def install_transport(self, loop):
        """Windows lab only; preserve native write/send/completion callback order."""
        if self.transport_observer is None:
            self.transport_observer = _TransportObserver(self, loop)
        return self.transport_report()

    def transport_report(self):
        if self.transport_observer is None:
            return {"available": False, "reason": "not_installed", "complete": False}
        return self.transport_observer.report()

    @contextmanager
    def span(self, stage, phase=None, generation=None):
        if not self.collector_enabled:
            yield
            return
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
                with self._observe_adoption(stage, args) as observation:
                    with self.span(stage, phase):
                        result = await original(*args, **kwargs)
                        if stage == "endpoint.dispatch":
                            self._response_metadata(result)
                        if observation is not None:
                            observation.update(returned=True, result=result)
                        return result
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
                if self.adoption_timeline:
                    generation = adoption_identity(generation)
                with self._observe_adoption(stage, args) as observation:
                    with self.span(stage, phase, generation):
                        result = original(*args, **kwargs)
                        if stage == "endpoint.etag_and_bytes":
                            self._response_metadata(result)
                        if observation is not None:
                            observation.update(returned=True, result=result)
                        return result

        self.patches.append((owner, name, original))
        setattr(owner, name, wrapped)

    def install(self, server):
        from src.serving import artifacts, builder, serialization, league_views, runtime

        if not self.collector_enabled:
            return

        self.server = server

        for owner, name, stage, phase in (
            (runtime.AtomicRuntime, "reload_if_changed", "canonical.reload", "canonical"),
            (serialization, "load_generation", "canonical.load", "canonical"),
            (serialization, "load_web_generation", "canonical.web_load", "canonical"),
            (serialization, "_validate_generation", "canonical.validate", None),
            (serialization, "project_contract_views", "canonical.projections", None),
            (serialization, "player_index", "canonical.index", None),
            (league_views.LeagueServingReader, "refresh", "league.refresh", "league"),
            (league_views, "load_league_views", "league.load", None),
            (league_views, "load_web_league_views", "league.web_load", None),
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
            if (
                not self.timeline_only
                or stage.startswith("endpoint.")
                or self.adoption_timeline
                and stage in _ADOPTION_STAGES
            ):
                self.patch(
                    owner,
                    name,
                    stage,
                    phase,
                    scoped=self.timeline_only and stage.startswith("endpoint."),
                )
        if self.adoption_timeline:
            self.patch(runtime.AtomicRuntime, "_install", "canonical.install", "canonical")
            self.patch(league_views.LeagueServingReader, "_refresh", "league.adopt", "league")
        original_response = server.Response

        @functools.wraps(original_response)
        def measured_response(*args, **kwargs):
            if self.request_id.get() is None:
                return original_response(*args, **kwargs)
            with self.span("endpoint.response_construct"):
                response = original_response(*args, **kwargs)
            self._response_metadata(response)
            return response

        self.patches.append((server, "Response", original_response))
        server.Response = measured_response
        if self.timeline_only:
            return
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
        if self.collector_enabled and not self.timeline_only:
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
        with self.collection_lock:
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
                    "route": route if route in {"rankings", "trade"} else "other",
                    "requestId": request_id,
                    "startNs": before,
                    "endNs": time.perf_counter_ns(),
                }
            )
            self.request_id.reset(token)

    def close(self):
        if self.closed:
            if self.writer_failure or self.close_failure:
                raise RuntimeError("diagnostic span writer failed")
            return
        if self.gc_installed:
            gc.callbacks.remove(self.gc_callback)
        if self.transport_observer:
            self.transport_observer.close()
        for owner, name, original in reversed(self.patches):
            setattr(owner, name, original)
        self.server = None
        # Publish the closed flag under the enqueue lock, so no accepted event
        # can be placed behind the writer's sentinel.
        with self.collection_lock:
            self.closed = True
        if self.writer:
            if self.writer.is_alive():
                try:
                    self.events.put(None, timeout=5)
                except Exception as error:
                    self.close_failure = _collection_failure("stop_signal", error)
            try:
                self.writer.join(timeout=10)
                if self.writer.is_alive():
                    self.close_failure = self.close_failure or _collection_failure(
                        "join_timeout", RuntimeError()
                    )
            except Exception as error:
                self.close_failure = self.close_failure or _collection_failure("join", error)
            if not self.footer_written and not (self.writer_failure or self.close_failure):
                self.close_failure = _collection_failure("missing_footer", RuntimeError())
            if self.writer_failure or self.close_failure:
                raise RuntimeError("diagnostic span writer failed")


class _TransportObserver:
    """Bounded byte provenance; no buffers, sockets, or futures are retained strongly."""

    MAX_TRANSPORTS = 64
    MAX_SEGMENTS = 128
    MAX_PENDING = 256

    def __init__(self, trace, loop):
        self.trace, self.loop = trace, loop
        self.available = False
        self.reason = "collector_disabled" if not trace.collector_enabled else "unsupported_loop"
        self.closed = False
        self.states = weakref.WeakKeyDictionary()
        self.sockets = weakref.WeakKeyDictionary()
        self.pending = weakref.WeakKeyDictionary()
        self.restorers = []
        self.write_sequence = self.send_sequence = 0
        self.counts = dict.fromkeys(
            (
                "watchedWrites",
                "watchedWriteBytes",
                "watchedSubmittedBytes",
                "watchedCompletedBytes",
                "mixedSendCount",
                "missingCorrelationBytes",
                "metadataDropped",
                "observerErrors",
                "writeFailures",
                "sendFailures",
                "completionFailures",
                "doneAtReturnCount",
                "completionDeliveries",
                "tcpNoDelayTrue",
                "tcpNoDelayFalse",
                "tcpNoDelayUnknown",
                "abandonedWatchedBytes",
            ),
            0,
        )
        if not trace.collector_enabled:
            return
        try:
            from asyncio.proactor_events import _ProactorSocketTransport

            proactor = loop._proactor
            original_send = proactor.send
            original_write = _ProactorSocketTransport.write
            original_completion = _ProactorSocketTransport._loop_writing
        except (ImportError, AttributeError):
            return

        def write(transport, data):
            if self.closed or getattr(transport, "_loop", None) is not loop:
                return original_write(transport, data)
            request = trace.request_id.get() if trace.request_state.get() is not None else None
            state = self._state(transport, request)
            if state is None:
                return original_write(transport, data)
            size = self._byte_size(data)
            self.write_sequence += 1
            sequence = self.write_sequence
            if request is not None:
                self.counts["watchedWrites"] += 1
                self.counts["watchedWriteBytes"] += size
                self._emit(
                    "transport.write.enter",
                    requestId=request,
                    writeSequence=sequence,
                    bytes=size,
                    bufferBytes=self._buffer_size(transport),
                )
            # Enqueue before write: an idle transport calls proactor.send inside it.
            if size:
                self._append(state, size, request)
            failed = False
            try:
                return original_write(transport, data)
            except BaseException:
                failed = True
                if request is not None:
                    self.counts["writeFailures"] += 1
                raise
            finally:
                if request is not None:
                    self._emit(
                        "transport.write.return",
                        requestId=request,
                        writeSequence=sequence,
                        bytes=size,
                        bufferBytes=self._buffer_size(transport),
                        failed=failed,
                    )

        def send(sock, data, *args, **kwargs):
            if self.closed:
                return original_send(sock, data, *args, **kwargs)
            try:
                state = self.sockets.get(sock)
            except TypeError:
                state = None
            if state is None:
                # Other loop operations and unobserved control traffic are out of scope.
                return original_send(sock, data, *args, **kwargs)
            size = self._byte_size(data)
            ranges = self._consume(state, size)
            watched = sum(size for size, request in ranges if request is not None)
            if not watched:
                return original_send(sock, data, *args, **kwargs)
            self.send_sequence += 1
            sequence = self.send_sequence
            ids = {request for _, request in ranges}
            if len(ids) > 1:
                self.counts["mixedSendCount"] += 1
            details = {
                "sendSequence": sequence,
                "bytes": size,
                "ranges": [{"bytes": size, "requestId": request} for size, request in ranges],
                "attribution": "mixed" if len(ids) > 1 else "single",
            }
            self._emit("proactor.send.submit", **details)
            self.counts["watchedSubmittedBytes"] += watched
            try:
                future = original_send(sock, data, *args, **kwargs)
            except BaseException:
                self.counts["sendFailures"] += 1
                self._emit("proactor.send.return", **details, failed=True)
                raise
            try:
                already_done = future.done()
                self.counts["doneAtReturnCount"] += int(already_done)
                self._emit("proactor.send.return", **details, failed=False, futureDone=already_done)
                if len(self.pending) >= self.MAX_PENDING:
                    self.counts["metadataDropped"] += 1
                    self.counts["missingCorrelationBytes"] += watched
                else:
                    self.pending[future] = (details, ranges, watched)
            except Exception:
                self.counts["observerErrors"] += 1
                self.counts["missingCorrelationBytes"] += watched
            return future

        def completion(transport, f=None, data=None):
            if not self.closed and getattr(transport, "_loop", None) is loop and f is not None:
                try:
                    self._complete(f)
                except Exception:
                    self.counts["observerErrors"] += 1
            # This is the native registered callback. Do not add or reorder callbacks.
            return original_completion(transport, f, data)

        try:
            self._patch(_ProactorSocketTransport, "write", write)
            self._patch(_ProactorSocketTransport, "_loop_writing", completion)
            self._patch(proactor, "send", send)
        except (AttributeError, TypeError):
            for restore in reversed(self.restorers):
                restore()
            self.restorers.clear()
            self.reason = "patch_unavailable"
            return
        self.available = True
        self.reason = "installed"

    def _patch(self, owner, name, replacement):
        owned = name in vars(owner)
        original = vars(owner).get(name)
        setattr(owner, name, replacement)

        def restore():
            if owned:
                setattr(owner, name, original)
            else:
                delattr(owner, name)

        self.restorers.append(restore)

    def _emit(self, stage, **fields):
        self.trace.emit(
            {
                "event": "transport",
                "stage": stage,
                "timestampNs": time.perf_counter_ns(),
                "threadCpuNs": time.thread_time_ns(),
                **fields,
            }
        )

    @staticmethod
    def _byte_size(data):
        return (
            data.nbytes
            if isinstance(data, memoryview)
            else len(data)
            if isinstance(data, (bytes, bytearray))
            else 0
        )

    def _buffer_size(self, transport):
        try:
            return transport.get_write_buffer_size()
        except Exception:
            self.counts["observerErrors"] += 1
            return None

    def _state(self, transport, request):
        try:
            state = self.states.get(transport)
            if state is not None or request is None:
                return state
            if len(self.states) >= self.MAX_TRANSPORTS:
                self.counts["metadataDropped"] += 1
                self.counts["observerErrors"] += 1
                return None
            # Existing unsent control bytes precede the first observed request.
            buffered = getattr(transport, "_buffer", None)
            state = {"queue": deque(), "poisoned": False}
            if buffered:
                state["queue"].append((len(buffered), None))
            self.states[transport] = state
            self.sockets[transport._sock] = state
            try:
                enabled = transport._sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
                name = (
                    "tcpNoDelayTrue"
                    if enabled == 1
                    else "tcpNoDelayFalse"
                    if enabled == 0
                    else "tcpNoDelayUnknown"
                )
            except Exception:
                name = "tcpNoDelayUnknown"
            self.counts[name] += 1
            self._emit(
                "transport.socket_option",
                requestId=request,
                tcpNoDelay=True
                if name == "tcpNoDelayTrue"
                else False
                if name == "tcpNoDelayFalse"
                else None,
            )
            return state
        except (AttributeError, TypeError):
            self.counts["observerErrors"] += 1
            return None

    def _append(self, state, size, request):
        queue = state["queue"]
        if state["poisoned"] or len(queue) >= self.MAX_SEGMENTS:
            lost = sum(count for count, owner in queue if owner is not None)
            self.counts["missingCorrelationBytes"] += lost + (size if request is not None else 0)
            self.counts["metadataDropped"] += 1
            total = sum(count for count, _ in queue) + size
            queue.clear()
            queue.append((total, None))
            state["poisoned"] = True
        elif queue and queue[-1][1] == request:
            previous, _ = queue.pop()
            queue.append((previous + size, request))
        else:
            queue.append((size, request))

    def _consume(self, state, size):
        ranges = []
        queue = state["queue"]
        while size and queue:
            count, request = queue.popleft()
            used = min(size, count)
            ranges.append((used, request))
            if count > used:
                queue.appendleft((count - used, request))
            size -= used
        if size:
            # Never infer an owner from the current context for unexplained bytes.
            ranges.append((size, None))
            if any(request is not None for _, request in ranges):
                self.counts["missingCorrelationBytes"] += size
        return ranges

    def _complete(self, future):
        entered = time.perf_counter_ns()
        cpu = time.thread_time_ns()
        pending = self.pending.pop(future, None)
        if pending is None:
            return
        details, ranges, watched = pending
        self.counts["completionDeliveries"] += 1
        failed = False
        try:
            completed = future.result()
            if type(completed) is not int or not 0 <= completed <= details["bytes"]:
                self.counts["observerErrors"] += 1
                completed = None
            else:
                remaining = completed
                for count, request in ranges:
                    used = min(count, remaining)
                    if request is not None:
                        self.counts["watchedCompletedBytes"] += used
                    remaining -= used
                if completed != details["bytes"]:
                    self.counts["completionFailures"] += 1
        except BaseException:
            failed = True
            completed = None
            self.counts["completionFailures"] += 1
        self._emit(
            "proactor.completion.delivery",
            **details,
            failed=failed,
            completedBytes=completed,
            completionBoundary="native_loop_writing_callback_entry",
            timestampNs=entered,
            threadCpuNs=cpu,
        )

    def report(self):
        queued = sum(count for state in self.states.values() for count, _ in state["queue"])
        watched_queued = sum(
            count
            for state in self.states.values()
            for count, owner in state["queue"]
            if owner is not None
        )
        pending = sum(details["bytes"] for details, _, _ in self.pending.values())
        watched_pending = sum(watched for _, _, watched in self.pending.values())
        written = self.counts["watchedWriteBytes"]
        submitted = self.counts["watchedSubmittedBytes"]
        completed = self.counts["watchedCompletedBytes"]
        uncompleted = max(0, written - completed)
        conserved = written == submitted == completed
        failed = any(
            self.counts[key]
            for key in (
                "missingCorrelationBytes",
                "metadataDropped",
                "observerErrors",
                "writeFailures",
                "sendFailures",
                "completionFailures",
                "abandonedWatchedBytes",
            )
        )
        return {
            "available": self.available,
            "reason": self.reason,
            **self.counts,
            "pendingSendCount": len(self.pending),
            "pendingSendBytes": pending,
            "pendingWatchedBytes": watched_pending,
            "queuedWriteBytes": queued,
            "queuedWatchedBytes": watched_queued,
            "eventDrops": self.trace.dropped,
            "uncompletedWatchedBytes": uncompleted,
            "byteConservation": conserved,
            "overcountWatchedBytes": max(0, completed - written, submitted - written),
            "complete": self.available
            and not failed
            and conserved
            and not uncompleted
            and not watched_pending
            and not watched_queued
            and not self.trace.dropped,
            "completionBoundary": "native_loop_writing_callback_entry",
            "physicalCompletionObserved": False,
            "peerReceiptObserved": False,
            "limits": {
                "transports": self.MAX_TRANSPORTS,
                "segmentsPerTransport": self.MAX_SEGMENTS,
                "pendingSends": self.MAX_PENDING,
            },
        }

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.counts["abandonedWatchedBytes"] += (
            self.report()["pendingWatchedBytes"] + self.report()["queuedWatchedBytes"]
        )
        for restore in reversed(self.restorers):
            restore()
        self.restorers.clear()
        self.pending.clear()
        self.states.clear()
        self.sockets.clear()
