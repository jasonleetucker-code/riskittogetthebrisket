"""Diagnostic hooks preserve semantics and do not serialize sensitive arguments."""

import asyncio
import json
import queue
from types import SimpleNamespace
from contextlib import contextmanager
import sys
import threading
from pathlib import Path

import pytest

from scripts.serving_lab_spans import LabSpans, adoption_identity


@pytest.mark.parametrize("failure_stage", ["open", "event_write", "footer_write", "flush", "close"])
def test_writer_failure_is_observable_even_without_queue_loss(tmp_path, monkeypatch, failure_stage):
    path = tmp_path / "private-writer-path.jsonl"
    private = "private-writer-error-detail"
    original_open = Path.open
    failed = threading.Event()
    uncaught = []
    monkeypatch.setattr(threading, "excepthook", lambda args: uncaught.append(type(args.exc_value)))

    def fail(stage):
        if failure_stage == stage:
            failed.set()
            raise OSError(private)

    class FaultyStream:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

        def write(self, text):
            fail("footer_write" if json.loads(text)["event"] == "collection" else "event_write")
            return self.stream.write(text)

        def flush(self):
            fail("flush")
            return self.stream.flush()

        def close(self):
            self.stream.close()
            fail("close")

    def faulty_open(owner, *args, **kwargs):
        if owner == path:
            fail("open")
            return FaultyStream(original_open(owner, *args, **kwargs))
        return original_open(owner, *args, **kwargs)

    monkeypatch.setattr(Path, "open", faulty_open)
    trace = LabSpans(path)
    trace.emit({"event": "test"})
    if failure_stage in {"open", "event_write"}:
        assert failed.wait(2), "the injected writer failure did not occur"
    with pytest.raises(RuntimeError, match="diagnostic span writer failed"):
        trace.close()
    report = trace.collection_report()
    assert not report["complete"] and report["writerStopped"] and report["dropped"] == 0
    assert report["writerFailure"] == {"stage": failure_stage, "exceptionClass": "OSError"}
    assert private not in json.dumps(report) and str(path) not in json.dumps(report)
    assert len(json.dumps(report)) < 2048
    assert not uncaught
    with pytest.raises(RuntimeError, match="diagnostic span writer failed"):
        trace.close()


def test_collection_complete_requires_successful_final_writer_boundary(tmp_path):
    path = tmp_path / "collection.jsonl"
    trace = LabSpans(path)
    trace.emit({"event": "test", "ordinal": 1})
    assert trace.collection_report()["complete"] is False
    trace.close()
    report = trace.collection_report()
    assert report == {
        "enabled": True,
        "closed": True,
        "writerStopped": True,
        "footerWritten": True,
        "streamFlushed": True,
        "streamClosed": True,
        "emitted": 1,
        "written": 1,
        "dropped": 0,
        "writerFailure": None,
        "closeFailure": None,
        "complete": True,
    }
    events = read_events(path)
    assert events[0] == {"event": "test", "ordinal": 1}
    assert events[-1]["emitted"] == events[-1]["written"] == 1
    assert events[-1]["completionBoundary"] == "footer_before_flush_and_close"
    assert "complete" not in events[-1], "a footer cannot prove the later file close"
    trace.emit({"event": "late"})
    trace.close()
    assert trace.collection_report() == report
    assert read_events(path) == events


def test_dropped_events_and_disabled_collector_never_claim_final_completeness(tmp_path):
    trace = LabSpans(tmp_path / "loss.jsonl", max_events=1)
    trace.emit({"event": "kept"})
    trace.emit({"event": "dropped"})
    trace.close()  # Counted drops keep their existing nonthrowing close behavior.
    report = trace.collection_report()
    assert report["emitted"] == report["written"] == report["dropped"] == 1
    assert report["footerWritten"] and not report["complete"]
    disabled_path = tmp_path / "disabled.jsonl"
    disabled = LabSpans(disabled_path, collector_enabled=False)
    assert not disabled.collection_report()["complete"]
    disabled.emit({"event": "ignored"})
    disabled.close()
    report = disabled.collection_report()
    assert not report["enabled"] and not report["writerStopped"] and not report["complete"]
    assert report["emitted"] == report["written"] == report["dropped"] == 0
    assert not disabled_path.exists()


@pytest.mark.parametrize("failure", ["stop_signal", "join", "join_timeout"])
def test_writer_shutdown_failures_are_bounded_and_never_complete(tmp_path, monkeypatch, failure):
    trace = LabSpans(tmp_path / "unused.jsonl", collector_enabled=False)
    trace.collector_enabled = True
    trace.footer_written = trace.stream_flushed = trace.stream_closed = True
    observed = []

    class Writer:
        def is_alive(self):
            return True

        def join(self, timeout):
            observed.append(("join", timeout))
            if failure == "join":
                raise RuntimeError("private-join-detail")

    def stop_signal(value, timeout):
        observed.append(("stop", value, timeout))
        if failure == "stop_signal":
            raise queue.Full("private-queue-detail")

    trace.writer = Writer()
    monkeypatch.setattr(trace.events, "put", stop_signal)
    with pytest.raises(RuntimeError, match="^diagnostic span writer failed$"):
        trace.close()
    assert observed == [("stop", None, 5), ("join", 10)]
    report = trace.collection_report()
    assert report["closeFailure"] == {
        "stage": failure,
        "exceptionClass": "Full" if failure == "stop_signal" else "RuntimeError",
    }
    assert not report["complete"] and not report["writerStopped"]
    assert "private-" not in json.dumps(report)


def test_missing_footer_is_failure_even_when_writer_exits_normally(tmp_path, monkeypatch):
    monkeypatch.setattr(LabSpans, "_write", lambda self: None)
    trace = LabSpans(tmp_path / "absent.jsonl")
    with pytest.raises(RuntimeError, match="diagnostic span writer failed"):
        trace.close()
    report = trace.collection_report()
    assert report["writerStopped"] and not report["footerWritten"] and not report["complete"]
    assert report["closeFailure"] == {"stage": "missing_footer", "exceptionClass": "RuntimeError"}


def test_unserializable_event_fails_collection_without_exposing_object(tmp_path):
    trace = LabSpans(tmp_path / "bad-event.jsonl")
    trace.emit({"event": "test", "unsupported": object()})
    with pytest.raises(RuntimeError, match="diagnostic span writer failed"):
        trace.close()
    report = trace.collection_report()
    assert report["writerFailure"] == {"stage": "event_write", "exceptionClass": "TypeError"}
    assert report["written"] == 0 and report["emitted"] == 1 and not report["complete"]


def test_failure_class_names_are_allowlisted_and_hooks_restore(tmp_path, monkeypatch):
    class PrivateClassName(Exception):
        pass

    def fail_open(*args, **kwargs):
        raise PrivateClassName("private-exception-content")

    def work():
        return 7

    monkeypatch.setattr(Path, "open", fail_open)
    owner = SimpleNamespace(work=work)
    trace = LabSpans(tmp_path / "no-file.jsonl")
    trace.patch(owner, "work", "test.work", "canonical")
    assert owner.work() == 7
    with pytest.raises(RuntimeError, match="^diagnostic span writer failed$"):
        trace.close()
    assert owner.work is work
    report = trace.collection_report()
    assert report["writerFailure"] == {"stage": "open", "exceptionClass": "OtherException"}
    assert "PrivateClassName" not in json.dumps(report)


def test_span_preserves_return_failure_and_restores_without_private_values(tmp_path):
    secret = "private-fixture-content-that-must-not-appear"

    def work(value):
        if value == secret:
            raise ValueError(secret)
        return value + 1

    owner = SimpleNamespace(work=work)
    path = tmp_path / "spans.jsonl"
    trace = LabSpans(path)
    trace.patch(owner, "work", "test.work", "canonical")
    assert owner.work(3) == 4
    with pytest.raises(ValueError, match=secret):
        owner.work(secret)
    assert trace.phase.get() == "none" and trace.depth.get() == 0
    trace.close()
    assert owner.work is work
    body = path.read_text()
    assert secret not in body
    events = [json.loads(line) for line in body.splitlines()]
    assert [e["failed"] for e in events if e["event"] == "span"] == [False, True]
    assert all(e["endNs"] >= e["startNs"] for e in events if e["event"] == "span")


def test_async_request_context_and_bounded_drops(tmp_path):
    async def work():
        await asyncio.sleep(0)
        return 5

    owner = SimpleNamespace(work=work)
    path = tmp_path / "spans.jsonl"
    trace = LabSpans(path, max_events=3)
    trace.patch(owner, "work", "endpoint.dispatch", "endpoint")

    async def invoke():
        with trace.request("rankings") as request_id:
            assert await owner.work() == 5
            assert trace.request_id.get() == request_id
        assert trace.request_id.get() is None

    asyncio.run(invoke())
    for _ in range(5):
        trace.emit({"event": "test"})
    trace.close()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert rows[0]["requestId"] == rows[1]["requestId"] == 1
    assert rows[-1]["emitted"] == 3 and rows[-1]["dropped"] == 4


def read_events(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


@pytest.mark.parametrize("status", [200, 304])
def test_asgi_stream_correlates_through_final_send_without_payload_or_headers(tmp_path, status):
    path = tmp_path / "timeline.jsonl"
    trace = LabSpans(path, timeline_only=True)
    private = b"private-player-and-league-content"
    sent = []

    async def app(scope, receive, send):
        assert scope["query_string"] == private
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"etag", private), (b"set-cookie", private)],
            }
        )
        if status == 200:
            # Copying the context into streaming tasks must retain one ID.
            async def stream():
                await asyncio.sleep(0)
                await send({"type": "http.response.body", "body": private, "more_body": True})
                await asyncio.sleep(0)
                await send({"type": "http.response.body", "body": b"!"})

            await asyncio.create_task(stream())
        else:
            await send({"type": "http.response.body", "body": b""})

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        assert trace.request_id.get() == 1
        await asyncio.sleep(0)
        assert trace.request_id.get() == 1
        sent.append(message)

    wrapped = trace.wrap_app(app)

    async def invoke():
        await wrapped(
            {
                "type": "http",
                "path": "/api/read-models/rankings",
                "query_string": private,
                "headers": [(b"cookie", private)],
            },
            receive,
            send,
        )
        assert trace.request_id.get() is None and trace.request_state.get() is None

    asyncio.run(invoke())
    trace.close()
    assert private.decode() not in path.read_text()
    assert (b"etag", private) in sent[0]["headers"]
    assert (b"x-soak-request-sequence", b"1") in sent[0]["headers"]
    timeline = [row for row in read_events(path) if row["event"] == "timeline"]
    assert {row["requestId"] for row in timeline} == {1}
    assert {row["route"] for row in timeline} == {"rankings"}
    assert [row["timestampNs"] for row in timeline] == sorted(
        row["timestampNs"] for row in timeline
    )
    assert timeline[-1]["stage"] == "asgi.complete"
    assert timeline[-1]["responseComplete"] and timeline[-1]["outcome"] == "returned"
    assert timeline[-1]["responseBytes"] == (len(private) + 1 if status == 200 else 0)
    assert any(row["stage"] == "asgi.response.first_body.begin" for row in timeline) == (
        status == 200
    )
    clock = read_events(path)[0]
    assert clock["event"] == "clock_metadata" and clock["monotonic"]
    assert clock["perfCounterBeforeNs"] <= clock["perfCounterAfterNs"]


@pytest.mark.parametrize("failure", ["app", "send", "timeout"])
def test_asgi_failure_and_timeout_keep_partial_timeline_and_clear_context(tmp_path, failure):
    trace = LabSpans(tmp_path / "timeline.jsonl", timeline_only=True)

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        if failure == "app":
            raise ValueError("private-exception-content")
        if failure == "timeout":
            await asyncio.Event().wait()
        await send({"type": "http.response.body", "body": b"private-body"})

    async def send(message):
        if failure == "send" and message["type"] == "http.response.body":
            raise OSError("private-network-error")

    async def receive():
        return {"type": "http.request", "body": b""}

    wrapped = trace.wrap_app(app)

    async def invoke():
        with pytest.raises((ValueError, OSError, TimeoutError)):
            await asyncio.wait_for(
                wrapped({"type": "http", "path": "/api/read-models/trade/context"}, receive, send),
                timeout=0.01,
            )
        assert trace.request_id.get() is None and trace.request_state.get() is None

    asyncio.run(invoke())
    trace.close()
    assert "private-" not in trace.path.read_text()
    final = [row for row in read_events(trace.path) if row.get("stage") == "asgi.complete"][-1]
    assert final["outcome"] == ("cancelled" if failure == "timeout" else "failed")
    assert not final["responseComplete"] and final["responseBytes"] == 0


@pytest.fixture
def fake_transport_runtime(monkeypatch):
    class Future:
        def __init__(self, size, *, done=False):
            self.size, self.ready = size, done
            self.callbacks = []
            self.error = None

        def done(self):
            return self.ready

        def result(self):
            if self.error:
                raise self.error
            assert self.ready
            return self.size

        def add_done_callback(self, callback):
            self.callbacks.append(callback)

        def finish(self, error=None):
            self.ready, self.error = True, error
            for callback in list(self.callbacks):
                callback(self)

    class Proactor:
        def __init__(self):
            self.calls, self.futures = [], []
            self.immediate = False
            self.error = None

        def send(self, sock, data, *args, **kwargs):
            self.calls.append((sock, data, args, kwargs))
            if self.error:
                raise self.error
            future = Future(len(data), done=self.immediate)
            self.futures.append(future)
            return future

    class Sock:
        def __init__(self):
            self.options = []

        def getsockopt(self, level, option):
            self.options.append((level, option))
            return 1

    class Base:
        def write(self, data):
            self.writes.append(data)
            if self.error:
                raise self.error
            if self._write_fut is None:
                self._loop_writing(data=bytes(data))
            else:
                self._buffer.extend(bytes(data))
            return "original-write-result"

        def _loop_writing(self, f=None, data=None):
            self.callback_calls.append(f)
            if f is not None:
                f.result()
            self._write_fut = None
            if data is None:
                data = self._buffer
                self._buffer = bytearray()
            if data:
                self._write_fut = self._loop._proactor.send(self._sock, data)
                self._write_fut.add_done_callback(self._loop_writing)
            return "original-completion-result"

    class Transport(Base):
        def __init__(self, loop):
            self._loop, self._sock = loop, Sock()
            self._buffer, self._write_fut = bytearray(), None
            self.writes, self.callback_calls = [], []
            self.error = None

        def get_write_buffer_size(self):
            return len(self._buffer) + (self._write_fut.size if self._write_fut else 0)

    module = SimpleNamespace(_ProactorSocketTransport=Transport)
    monkeypatch.setitem(sys.modules, "asyncio.proactor_events", module)
    loop = SimpleNamespace(_proactor=Proactor())
    return SimpleNamespace(loop=loop, Transport=Transport, Proactor=Proactor)


@contextmanager
def watched_request(trace):
    with trace.request("rankings") as request:
        token = trace.request_state.set({"route": "rankings", "responseClass": "unknown"})
        try:
            yield request
        finally:
            trace.request_state.reset(token)


def test_transport_fifo_coalescing_and_late_native_completion_preserve_delegation(
    tmp_path, fake_transport_runtime
):
    runtime = fake_transport_runtime
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    assert trace.install_transport(runtime.loop)["available"]
    transport = runtime.Transport(runtime.loop)
    body = b"private-first-header"
    with watched_request(trace) as first:
        assert transport.write(body) == "original-write-result"
        transport.write(b"abc")
    with watched_request(trace) as second:
        transport.write(b"defg")
    transport.write(b"!")  # Control bytes can share a send, but are never guessed to be watched.
    assert runtime.loop._proactor.calls[0][1] is body
    future = runtime.loop._proactor.futures[0]
    assert len(future.callbacks) == 1  # Observer adds no completion callback.
    assert trace.request_id.get() is None
    future.finish()
    coalesced = runtime.loop._proactor.futures[1]
    assert len(coalesced.callbacks) == 1
    coalesced.finish()
    report = trace.transport_report()
    assert report["complete"] and report["mixedSendCount"] == 1
    assert report["watchedWriteBytes"] == report["watchedCompletedBytes"] == len(body) + 7
    assert report["pendingSendCount"] == report["queuedWatchedBytes"] == 0
    assert report["tcpNoDelayTrue"] == 1
    trace.close()
    assert "write" not in vars(runtime.Transport) and "_loop_writing" not in vars(runtime.Transport)
    assert "send" not in vars(runtime.loop._proactor)
    assert "private-" not in trace.path.read_text()
    events = [row for row in read_events(trace.path) if row["event"] == "transport"]
    complete = [row for row in events if row["stage"] == "proactor.completion.delivery"]
    assert complete[0]["ranges"] == [{"bytes": len(body), "requestId": first}]
    assert complete[1]["ranges"] == [
        {"bytes": 3, "requestId": first},
        {"bytes": 4, "requestId": second},
        {"bytes": 1, "requestId": None},
    ]
    assert all(row["timestampNs"] > 0 and row["threadCpuNs"] > 0 for row in events)


def test_transport_immediate_done_is_distinct_from_native_completion_delivery(
    tmp_path, fake_transport_runtime
):
    runtime = fake_transport_runtime
    runtime.loop._proactor.immediate = True
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    trace.install_transport(runtime.loop)
    transport = runtime.Transport(runtime.loop)
    with watched_request(trace):
        transport.write(b"abcd")
    before = trace.transport_report()
    assert before["doneAtReturnCount"] == 1 and before["completionDeliveries"] == 0
    assert not before["complete"] and before["pendingWatchedBytes"] == 4
    runtime.loop._proactor.futures[0].finish()
    assert trace.transport_report()["complete"]
    trace.close()


def test_transport_counts_memoryview_bytes_and_rejects_partial_completion(
    tmp_path, fake_transport_runtime
):
    runtime = fake_transport_runtime
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    trace.install_transport(runtime.loop)
    transport = runtime.Transport(runtime.loop)
    data = memoryview(b"abcdefgh").cast("I")
    with watched_request(trace):
        transport.write(data)
    assert transport.writes[0] is data
    assert trace.transport_report()["watchedWriteBytes"] == data.nbytes == 8
    future = runtime.loop._proactor.futures[0]
    future.size = 4
    future.finish()
    report = trace.transport_report()
    assert not report["complete"] and not report["byteConservation"]
    assert report["completionFailures"] == 1 and report["uncompletedWatchedBytes"] == 4
    trace.close()


def test_transport_overcount_is_not_conservation_even_when_no_bytes_remain(
    tmp_path, fake_transport_runtime
):
    runtime = fake_transport_runtime
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    trace.install_transport(runtime.loop)
    transport = runtime.Transport(runtime.loop)
    with watched_request(trace):
        transport.write(b"abc")
    runtime.loop._proactor.futures[0].finish()
    assert trace.transport_report()["complete"]
    trace.transport_observer.counts["watchedSubmittedBytes"] += 1
    report = trace.transport_report()
    assert not report["complete"] and not report["byteConservation"]
    assert report["overcountWatchedBytes"] == 1 and report["uncompletedWatchedBytes"] == 0
    trace.close()


@pytest.mark.parametrize("stage", ["write", "send", "completion"])
def test_transport_errors_remain_original_errors_and_fail_diagnostic_completeness(
    tmp_path, fake_transport_runtime, stage
):
    runtime = fake_transport_runtime
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    trace.install_transport(runtime.loop)
    transport = runtime.Transport(runtime.loop)
    error = OSError("private-error-detail")
    if stage == "write":
        transport.error = error
    elif stage == "send":
        runtime.loop._proactor.error = error
    with watched_request(trace):
        if stage == "completion":
            transport.write(b"abc")
        else:
            with pytest.raises(OSError) as raised:
                transport.write(b"abc")
            assert raised.value is error
    if stage == "completion":
        with pytest.raises(OSError) as raised:
            runtime.loop._proactor.futures[0].finish(error)
        assert raised.value is error
    report = trace.transport_report()
    assert not report["complete"] and report[f"{stage}Failures"] == 1
    trace.close()
    assert "private-" not in trace.path.read_text()


def test_transport_close_restores_and_pending_callback_does_not_emit(
    tmp_path, fake_transport_runtime
):
    runtime = fake_transport_runtime
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    trace.install_transport(runtime.loop)
    transport = runtime.Transport(runtime.loop)
    with watched_request(trace):
        transport.write(b"abc")
    trace.close()
    final = trace.path.read_bytes()
    runtime.loop._proactor.futures[0].finish()
    assert trace.path.read_bytes() == final
    assert trace.transport_report()["abandonedWatchedBytes"] == 3
    assert not trace.transport_report()["complete"]


def test_transport_disabled_unsupported_and_other_loop_or_control_are_not_watched(
    tmp_path, fake_transport_runtime
):
    runtime = fake_transport_runtime
    disabled = LabSpans(tmp_path / "absent", collector_enabled=False)
    assert disabled.install_transport(runtime.loop)["reason"] == "collector_disabled"
    assert "write" not in vars(runtime.Transport)
    disabled.close()
    unsupported = LabSpans(tmp_path / "unsupported")
    assert unsupported.install_transport(SimpleNamespace())["reason"] == "unsupported_loop"
    unsupported.close()
    trace = LabSpans(tmp_path / "transport.jsonl", timeline_only=True)
    trace.install_transport(runtime.loop)
    control = runtime.Transport(runtime.loop)
    control.write(b"private-control")
    other_loop = SimpleNamespace(_proactor=runtime.Proactor())
    other = runtime.Transport(other_loop)
    with watched_request(trace):
        other.write(b"private-other-loop")
    assert trace.transport_report()["watchedWrites"] == 0
    assert trace.transport_report()["complete"]
    trace.close()
    assert not any(row["event"] == "transport" for row in read_events(trace.path))


@pytest.mark.parametrize("limit", ["segments", "pending", "events"])
def test_transport_bounded_loss_invalidates_observation(tmp_path, fake_transport_runtime, limit):
    runtime = fake_transport_runtime
    trace = LabSpans(
        tmp_path / "transport.jsonl",
        timeline_only=True,
        max_events=3 if limit == "events" else 500_000,
    )
    trace.install_transport(runtime.loop)
    observer = trace.transport_observer
    if limit == "segments":
        observer.MAX_SEGMENTS = 1
    if limit == "pending":
        observer.MAX_PENDING = 0
    transport = runtime.Transport(runtime.loop)
    with watched_request(trace):
        transport.write(b"a")
        transport.write(b"b")
    with watched_request(trace):
        transport.write(b"c")
    runtime.loop._proactor.futures[0].finish()
    runtime.loop._proactor.futures[1].finish()
    report = trace.transport_report()
    assert not report["complete"]
    if limit == "events":
        assert report["eventDrops"] > 0
    else:
        assert report["metadataDropped"] > 0 and report["missingCorrelationBytes"] > 0
    trace.close()


def test_route_allowlist_and_concurrent_ids_do_not_collect_private_paths(tmp_path):
    trace = LabSpans(tmp_path / "timeline.jsonl", timeline_only=True)
    messages = []

    async def app(scope, receive, send):
        await asyncio.sleep(0)
        await send({"type": "http.response.start", "status": 304, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    wrapped = trace.wrap_app(app)

    async def invoke():
        await asyncio.gather(
            *(
                wrapped({"type": "http", "path": route}, receive, send)
                for route in [
                    "/api/read-models/rankings",
                    "/api/read-models/trade/context",
                    "/private-player-name",
                ]
            )
        )

    asyncio.run(invoke())
    trace.close()
    arrivals = [row for row in read_events(trace.path) if row.get("stage") == "asgi.arrival"]
    assert len(arrivals) == 2 and len({row["requestId"] for row in arrivals}) == 2
    assert "private-player-name" not in trace.path.read_text()
    headers = [m["headers"] for m in messages if m["type"] == "http.response.start"]
    assert sum(any(k == b"x-soak-request-sequence" for k, _ in row) for row in headers) == 2


def test_disabled_collector_has_no_file_writer_or_rows_but_preserves_asgi_response(tmp_path):
    trace = LabSpans(tmp_path / "absent.jsonl", timeline_only=True, collector_enabled=False)
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"unchanged"})

    async def send(message):
        messages.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    asyncio.run(
        trace.wrap_app(app)({"type": "http", "path": "/api/read-models/rankings"}, receive, send)
    )
    trace.close()
    assert trace.writer is None and not trace.path.exists()
    assert trace.emitted == trace.dropped == 0
    assert messages[-1]["body"] == b"unchanged"
    assert (b"x-soak-request-sequence", b"1") in messages[0]["headers"]


def test_timeline_install_measures_response_construction_without_deep_patches(tmp_path):
    import gc
    from pathlib import Path
    from starlette.responses import Response

    trace = LabSpans(tmp_path / "timeline.jsonl", timeline_only=True)
    server = SimpleNamespace(Response=Response)

    def serve(*args):
        return server.Response(b"private-body", headers={"ETag": "private-etag"})

    async def handler(*args):
        return server._serve_prepared_bytes()

    server._serve_prepared_bytes = serve
    server._get_prepared_read_model = handler
    server._scoring_identity_error = lambda *args: None
    original_loads, original_open = json.loads, Path.open
    gc_callbacks = list(gc.callbacks)
    trace.install(server)
    assert json.loads is original_loads and Path.open is original_open
    assert gc.callbacks == gc_callbacks

    async def app(scope, receive, send):
        response = await server._get_prepared_read_model()
        await response(scope, receive, send)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        return None

    async def invoke():
        trace.begin_serving()
        assert trace.pulse_task is None
        await trace.wrap_app(app)(
            {"type": "http", "path": "/api/read-models/rankings"}, receive, send
        )
        await trace.end_serving()

    asyncio.run(invoke())
    trace.close()
    assert server.Response is Response and server._get_prepared_read_model is handler
    rows = read_events(trace.path)
    spans = {row["stage"] for row in rows if row["event"] == "span"}
    assert spans == {"endpoint.dispatch", "endpoint.etag_and_bytes", "endpoint.response_construct"}
    constructed = [row for row in rows if row.get("stage") == "response.created"]
    assert len(constructed) == 1 and constructed[0]["responseClass"] == "Response"
    assert "private-" not in trace.path.read_text()


@pytest.fixture
def adoption_trace(tmp_path):
    traces = []

    def create(**kwargs):
        trace = LabSpans(
            tmp_path / f"adoption-{len(traces)}.jsonl",
            timeline_only=True,
            adoption_timeline=True,
            **kwargs,
        )
        traces.append(trace)
        return trace

    yield create
    for trace in reversed(traces):
        trace.close()


def adoption_board(letter):
    from src.serving.runtime import ServingGeneration

    return ServingGeneration(
        letter * 64, {}, {}, {}, {}, {}, {}, artifact_generation_id=letter * 64
    )


def adoption_bundle(board, letter):
    from src.serving.league_views import LeagueViews
    from src.serving.runtime import PreparedBytes

    views = {
        name: PreparedBytes(
            b"private-uncompressed",
            b"private-compressed",
            letter * 40,
            name,
            {
                "sleeperDataReady": True,
                "leagueKey": "private-league-key",
                "leagueSourceAsOf": "private-source-time",
            },
        )
        for name in ("rankings", "trade")
    }
    return LeagueViews(board.generation_id, "private-league-key", views)


def adoption_server():
    from starlette.responses import Response

    return SimpleNamespace(
        Response=Response,
        _get_prepared_read_model=lambda *args: None,
        _scoring_identity_error=lambda *args: None,
        _serve_prepared_bytes=lambda *args: None,
        _publish_serving_generation=lambda *args: None,
        latest_serving_generation=None,
    )


@pytest.mark.parametrize(
    "value",
    [None, True, 42, "private-person", "A" * 64, "g" * 64, "a" * 39, "a" * 65, b"a" * 64, [], {}],
)
def test_adoption_identity_rejects_non_content_identifiers(value):
    assert adoption_identity(value) is None


@pytest.mark.parametrize("length", [40, 64])
def test_adoption_identity_is_bounded_deterministic_and_not_raw(length):
    import hashlib

    value = "a" * length
    expected = hashlib.sha256(b"serving-lab-identity-v1\0" + value.encode("ascii")).hexdigest()
    assert adoption_identity(value) == expected != value
    assert len(expected) == 64


def test_adoption_install_is_opt_in_and_does_not_enable_deep_patches(adoption_trace):
    from pathlib import Path
    from src.serving import runtime, league_views, serialization

    original = [
        runtime.AtomicRuntime.reload_if_changed,
        runtime.AtomicRuntime._install,
        league_views.LeagueServingReader._refresh,
        serialization.load_web_generation,
    ]
    deep = [json.loads, Path.open, list(__import__("gc").callbacks)]
    disabled = adoption_trace(collector_enabled=False)
    disabled.install(adoption_server())
    assert original == [
        runtime.AtomicRuntime.reload_if_changed,
        runtime.AtomicRuntime._install,
        league_views.LeagueServingReader._refresh,
        serialization.load_web_generation,
    ]
    assert not disabled.path.exists() and not disabled.adoption_report()["complete"]
    trace = adoption_trace()
    trace.install(adoption_server())
    assert all(
        before is not after
        for before, after in zip(
            original,
            [
                runtime.AtomicRuntime.reload_if_changed,
                runtime.AtomicRuntime._install,
                league_views.LeagueServingReader._refresh,
                serialization.load_web_generation,
            ],
        )
    )
    assert deep == [json.loads, Path.open, list(__import__("gc").callbacks)]
    trace.close()
    assert original == [
        runtime.AtomicRuntime.reload_if_changed,
        runtime.AtomicRuntime._install,
        league_views.LeagueServingReader._refresh,
        serialization.load_web_generation,
    ]


def test_adoption_runtime_records_install_noop_and_caught_failure_as_different_states(
    adoption_trace,
):
    from src.serving.runtime import AtomicRuntime

    board = adoption_board("a")
    version = [1]
    store = SimpleNamespace(
        current_version=lambda *args: version[0],
        read_current=lambda *args: SimpleNamespace(generation_id=board.generation_id),
    )

    def build(artifact):
        if version[0] == 2:
            raise ValueError("private-rejected-candidate")
        return board

    runtime = AtomicRuntime(store, "fixture", "private-key", build)
    trace = adoption_trace()
    trace.install(adoption_server())
    assert runtime.reload_if_changed() is True
    assert runtime.current is board
    assert runtime.reload_if_changed() is False
    version[0] = 2
    assert runtime.reload_if_changed() is False and runtime.current is board
    trace.close()
    rows = [r for r in read_events(trace.path) if r.get("event") == "adoption"]
    reloads = [r for r in rows if r["stage"] == "canonical.reload"]
    assert [r["resultBoolean"] for r in reloads] == [True, False, False]
    assert [r["after"]["errorPresent"] for r in reloads] == [False, False, True]
    assert all(r["returned"] for r in reloads)  # A swallowed failure is not an exception return.
    assert reloads[0]["before"]["accepted"]["boardToken"] is None
    assert reloads[0]["after"]["accepted"]["boardToken"] == adoption_identity(board.generation_id)
    installs = [r for r in rows if r["stage"] == "canonical.install"]
    assert len(installs) == 1 and installs[0]["inputSnapshot"] == installs[0]["after"]["accepted"]
    assert all(r["endNs"] >= r["startNs"] and r["threadCpuNs"] >= 0 for r in rows)
    assert all(r["boundary"] == "wrapper_bracket_not_pointer_assignment" for r in rows)
    assert (
        "private-" not in trace.path.read_text()
        and board.generation_id not in trace.path.read_text()
    )


def test_adoption_league_same_board_new_representation_and_lkg_error_are_visible(adoption_trace):
    board = adoption_board("a")
    original, updated = adoption_bundle(board, "b"), adoption_bundle(board, "c")

    class Reader:
        def __init__(self):
            self._current = {"private-league-key": (board, original)}
            self.last_error = None

        def refresh(self, fail=False):
            if fail:
                self.last_error = "private-load-failure"
            else:
                self._current = {"private-league-key": (board, updated)}

    reader = Reader()
    trace = adoption_trace()
    trace.patch(Reader, "refresh", "league.adopt", "league")
    assert reader.refresh() is None
    assert reader.refresh(fail=True) is None
    trace.close()
    rows = [r for r in read_events(trace.path) if r.get("event") == "adoption"]
    before, after = rows[0]["before"]["accepted"][0], rows[0]["after"]["accepted"][0]
    assert before["board"] == after["board"]
    assert (
        before["bundle"]["views"]["rankings"]["etagToken"]
        != after["bundle"]["views"]["rankings"]["etagToken"]
    )
    assert rows[1]["before"]["accepted"] == rows[1]["after"]["accepted"]
    assert rows[1]["after"]["errorPresent"] and rows[1]["returned"]
    assert "private-" not in trace.path.read_text()


@pytest.mark.parametrize("status", [200, 304])
def test_adoption_endpoint_identity_stays_with_captured_bytes_through_send(
    adoption_trace, monkeypatch, status
):
    from src.serving.league_views import LeagueServingReader

    board = adoption_board("a")
    bundle = adoption_bundle(board, "b")
    newer = adoption_bundle(adoption_board("c"), "d")
    reader = LeagueServingReader(None, lambda: board)
    reader._current = {"private-league-key": (board, bundle)}
    server = adoption_server()
    trace = adoption_trace()
    sent = []

    def serve(request, prepared, generation):
        return server.Response(
            prepared.gzip if status == 200 else b"",
            status_code=status,
            headers={"ETag": prepared.etag, "X-Data-Generation": generation},
        )

    async def handler(request, view):
        captured = reader.capture("private-league-key")
        reader._current = {"private-league-key": (adoption_board("c"), newer)}
        return server._serve_prepared_bytes(
            request, captured[1].views[view], captured[0].generation_id
        )

    server._serve_prepared_bytes, server._get_prepared_read_model = serve, handler
    trace.install(server)

    def forbidden(*args, **kwargs):
        raise AssertionError("diagnostics must not decode or perform file I/O")

    async def app(scope, receive, send):
        response = await server._get_prepared_read_model(object(), "rankings")
        await response(scope, receive, send)

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        await asyncio.sleep(0)
        sent.append(message)

    with monkeypatch.context() as patch:
        patch.setattr(json, "loads", forbidden)
        patch.setattr(__import__("gzip"), "decompress", forbidden)
        patch.setattr(__import__("pathlib").Path, "read_bytes", forbidden)
        asyncio.run(
            trace.wrap_app(app)(
                {
                    "type": "http",
                    "path": "/api/read-models/rankings",
                    "headers": [(b"cookie", b"private-cookie")],
                },
                receive,
                send,
            )
        )
    trace.close()
    rows = read_events(trace.path)
    capture = next(
        r for r in rows if r.get("event") == "adoption" and r["stage"] == "endpoint.capture"
    )
    selected = next(
        r for r in rows if r.get("event") == "adoption" and r["stage"] == "endpoint.etag_and_bytes"
    )
    assert (
        capture["resultSnapshot"]["board"]["boardToken"]
        == selected["selected"]["boardToken"]
        == adoption_identity(board.generation_id)
    )
    assert selected["selected"]["prepared"]["etagToken"] == adoption_identity("b" * 40)
    assert selected["selected"]["prepared"]["gzipBytes"] == len(b"private-compressed")
    assert selected["responseStatus"] == status
    complete = next(r for r in rows if r.get("stage") == "asgi.complete")
    assert capture["requestId"] == selected["requestId"] == complete["requestId"] == 1
    assert complete["responseComplete"] and complete["responseBytes"] == (
        len(b"private-compressed") if status == 200 else 0
    )
    assert sent[-1]["body"] == (b"private-compressed" if status == 200 else b"")
    assert not any(value in trace.path.read_text() for value in ("private-", "a" * 64, "b" * 40))
    assert trace.adoption_report()["complete"]


def test_adoption_snapshot_errors_and_caps_preserve_original_results(adoption_trace):
    board, bundle = adoption_board("a"), adoption_bundle(adoption_board("a"), "b")

    class Reader:
        def __init__(self):
            self._current = {str(n): (board, bundle) for n in range(33)}
            self.last_error = None

        def refresh(self):
            return "private-original-result"

    trace = adoption_trace()
    trace.patch(Reader, "refresh", "league.adopt", "league")
    assert Reader().refresh() == "private-original-result"
    trace.close()
    row = next(r for r in read_events(trace.path) if r.get("event") == "adoption")
    assert row["before"]["captureCount"] == 33 and len(row["before"]["accepted"]) == 32
    assert trace.adoption_report()["snapshotDrops"] > 0 and not trace.adoption_report()["complete"]
    assert "private-" not in trace.path.read_text()

    broken = adoption_trace()
    broken.patch(Reader, "refresh", "league.adopt", "league")
    reader = Reader()
    reader._current = None
    assert reader.refresh() == "private-original-result"
    broken.close()
    assert broken.adoption_report()["observationErrors"] > 0
    assert not broken.adoption_report()["complete"]


def test_adoption_failure_retains_partial_bracket_and_original_exception(adoption_trace):
    error = OSError("private-exception")
    owner = SimpleNamespace(work=lambda: None)

    def fail():
        raise error

    owner.work = fail
    trace = adoption_trace(max_events=3)
    trace.patch(owner, "work", "canonical.load", "canonical")
    with pytest.raises(OSError) as raised:
        owner.work()
    assert raised.value is error
    for _ in range(5):
        trace.emit({"event": "test"})
    trace.close()
    row = next(r for r in read_events(trace.path) if r.get("event") == "adoption")
    assert not row["returned"] and row["resultSnapshot"] is None
    assert row["endNs"] >= row["startNs"]
    assert trace.adoption_report()["eventDrops"] > 0 and not trace.adoption_report()["complete"]
    assert "private-" not in trace.path.read_text()


@pytest.mark.parametrize("value", ["1", "0", 1, None])
def test_adoption_option_requires_explicit_boolean_before_starting_collector(tmp_path, value):
    with pytest.raises(ValueError, match="must be a boolean"):
        LabSpans(tmp_path / "absent", adoption_timeline=value)
    assert not (tmp_path / "absent").exists()


def test_adoption_load_links_physical_input_to_result_without_retaining_input(adoption_trace):
    board = adoption_board("a")
    artifact = SimpleNamespace(generation_id="e" * 64, files={"private-path": b"private-body"})
    owner = SimpleNamespace(load=lambda value: board)
    trace = adoption_trace()
    trace.patch(owner, "load", "canonical.web_load", "canonical")
    assert owner.load(artifact) is board
    trace.close()
    row = next(r for r in read_events(trace.path) if r.get("event") == "adoption")
    assert row["inputSnapshot"] == {"artifactToken": adoption_identity("e" * 64)}
    assert row["resultSnapshot"]["boardToken"] == adoption_identity("a" * 64)
    assert row["before"] is None and row["after"] is None  # Loading is not adoption.
    assert not any(value in trace.path.read_text() for value in ("private-", "a" * 64, "e" * 64))


def test_adoption_expiry_snapshot_is_copied_and_reports_selection_not_install(adoption_trace):
    board = adoption_board("a")
    ready = adoption_bundle(board, "b")
    metadata = {
        "sleeperDataReady": False,
        "leagueFreshnessState": "stale",
        "leagueKey": "private-league",
        "leagueSourceAsOf": "private-time",
    }
    stale_view = SimpleNamespace(
        etag="c" * 40,
        raw=b"private-raw",
        gzip=b"private-gzip",
        payload_view="rankings",
        metadata=metadata,
    )
    stale = SimpleNamespace(
        board_generation=board.generation_id, views={"rankings": stale_view, "trade": stale_view}
    )
    owner = SimpleNamespace(expire=lambda bundle: stale)
    trace = adoption_trace()
    trace.patch(owner, "expire", "league.expire", "league")
    assert owner.expire(ready) is stale
    metadata["leagueFreshnessState"] = "unknown"
    stale_view.etag = "d" * 40
    trace.close()
    row = next(r for r in read_events(trace.path) if r.get("event") == "adoption")
    selected = row["resultSnapshot"]["views"]["rankings"]
    assert selected["freshnessState"] == "stale" and selected["sleeperDataReady"] is False
    assert selected["etagToken"] == adoption_identity("c" * 40)
    assert "accepted" not in row["before"] and "selected" in row["before"]
    assert "private-" not in trace.path.read_text()


def test_adoption_async_cancellation_preserves_exception_and_request_context(adoption_trace):
    trace = adoption_trace()
    entered = asyncio.Event()

    async def wait_forever():
        entered.set()
        await asyncio.Event().wait()

    owner = SimpleNamespace(capture=wait_forever)
    trace.patch(owner, "capture", "endpoint.capture", "endpoint")

    async def invoke():
        with trace.request("rankings") as request_id:
            task = asyncio.create_task(owner.capture())
            await entered.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert trace.request_id.get() == request_id
        assert trace.request_id.get() is None

    asyncio.run(invoke())
    trace.close()
    row = next(r for r in read_events(trace.path) if r.get("event") == "adoption")
    assert row["requestId"] == 1 and not row["returned"] and row["resultSnapshot"] is None
    assert row["endNs"] >= row["startNs"]
