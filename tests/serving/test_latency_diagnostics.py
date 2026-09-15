"""Diagnostic driver plumbing only; no performance or canonical-value claims."""

import ast
import asyncio
import copy
import gzip
import hashlib
import itertools
import json
import runpy
import socket
import subprocess
import sys
import threading
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import soak_prepared_serving as lab


PRIVATE = "private-player-league-cookie-path-never-log"
REPO = Path(__file__).resolve().parents[2]


def response(view, generation="fixture-generation-1", *, conditional=False, request_id=1):
    # Real ResponseAudit checks transport identity; this minimal body is not a
    # canonical valuation fixture and does not replace the existing semantic gate.
    raw = json.dumps(
        {
            "payloadView": view,
            "meta": {"readModelGeneration": generation, "leagueKey": PRIVATE},
            "privateFixture": PRIVATE,
        }
    ).encode()
    body = b"" if conditional else gzip.compress(raw, mtime=0)
    return SimpleNamespace(
        status_code=304 if conditional else 200,
        headers={
            "etag": hashlib.sha1(raw).hexdigest(),
            "x-data-generation": generation,
            "x-payload-view": view,
            "x-soak-request-sequence": str(request_id),
            "content-encoding": "gzip",
            "content-length": str(len(body)),
            "set-cookie": PRIVATE,
        },
        body=body,
    )


def args(**changes):
    return SimpleNamespace(
        **{
            "port": 12345,
            "diagnostic_order": "balanced",
            "diagnostic_pacing": "continuous",
            "diagnostic_seed": 73,
            "diagnostic_connection": "reuse",
            "diagnostic_body_read": "whole",
            **changes,
        }
    )


class Clock:
    def __init__(self):
        self.value = 100

    def advance(self, amount):
        self.value += amount

    def __call__(self):
        return self.value


class BodyResponse:
    def __init__(self, clock, *, status=200, body=b"abc", failure=None):
        self.clock, self.status, self.remaining = clock, status, body
        self.will_close = False
        self.reads = []
        self.failure = failure

    def read(self, amount=None):
        self.reads.append(amount)
        self.clock.advance(30 if amount == 1 else 40)
        if self.failure:
            raise self.failure
        body = self.remaining if amount is None else self.remaining[:amount]
        self.remaining = self.remaining[len(body) :]
        return body

    def getheaders(self):
        return [("Content-Type", "application/json"), ("Set-Cookie", PRIVATE)]


class Transport:
    def __init__(self, clock, result, *, failure=None):
        self.clock, self.result, self.failure = clock, result, failure
        self.sequence = 7
        self.establishments = 0
        self.connection_marks = {}
        self.sock = SimpleNamespace(getsockopt=lambda *a: 1)
        self.requested = []

    def request(self, method, path, *, headers):
        self.requested.append((method, path, headers))
        self.clock.advance(10)
        if self.failure == "write":
            raise OSError(PRIVATE)

    def getresponse(self):
        self.clock.advance(20)
        if self.failure == "headers":
            raise TimeoutError(PRIVATE)
        return self.result


def test_balanced_blocks_have_every_permutation_and_equal_request_slots():
    runs = list(itertools.islice(lab.diagnostic_orders("balanced", 73), 48))
    assert runs == list(itertools.islice(lab.diagnostic_orders("balanced", 73), 48))
    assert runs != list(itertools.islice(lab.diagnostic_orders("balanced", 74), 48))
    for block in (0, 1):
        permutations = [order for number, order in runs if number == block]
        assert set(permutations) == set(itertools.permutations(range(4)))
        assert len(permutations) == 24
        slots = Counter(
            (request, slot) for order in permutations for slot, request in enumerate(order)
        )
        assert set(slots.values()) == {6} and len(slots) == 16
    assert list(itertools.islice(lab.diagnostic_orders("original", 1), 3)) == [
        (0, (0, 1, 2, 3)),
        (1, (0, 1, 2, 3)),
        (2, (0, 1, 2, 3)),
    ]


@pytest.mark.parametrize(
    "split,status,body",
    [(False, 200, b"abc"), (True, 200, b"abc"), (True, 304, b""), (True, 200, b"")],
)
def test_response_clocks_are_observed_stage_boundaries(monkeypatch, split, status, body):
    clock = Clock()
    monkeypatch.setattr(lab.time, "perf_counter_ns", clock)
    wire = BodyResponse(clock, status=status, body=body)
    connection = Transport(clock, wire)
    actual, marks = lab.diagnostic_response(
        connection, "/fixture", etag="known-etag", split_body=split
    )
    assert actual.status_code == status and actual.body == body
    assert actual.headers["content-type"] == "application/json"
    assert connection.requested[0][2]["If-None-Match"] == "known-etag"
    assert marks["requestStartNs"] == 100
    assert marks["writeCompleteNs"] == 110
    assert marks["headersAvailableNs"] == 130
    first_attempt = split and status != 304
    assert marks["bodyCompleteNs"] == (200 if first_attempt else 170)
    if split and body:
        assert marks["firstBodyAvailableNs"] == 160
    else:
        assert marks.get("firstBodyAvailableNs") is None
    assert wire.reads == ([1, None] if first_attempt else [None])
    assert marks["bodyBytes"] == len(body)
    assert marks["tcpNoDelay"] == 1 and not marks["newlyConnected"]
    assert PRIVATE not in json.dumps(marks)


def test_connection_marks_distinguish_reestablishment_without_network(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lab.time, "perf_counter_ns", clock)
    calls = []

    def connect(connection):
        calls.append((connection.host, connection.port, connection.timeout))
        clock.advance(5)

    monkeypatch.setattr(lab.http.client.HTTPConnection, "connect", connect)
    connection = lab.DiagnosticConnection(12345, 9)
    connection.connect()
    assert connection.connection_marks == {"connectStartNs": 100, "connectEndNs": 105}
    connection.connect()
    assert connection.establishments == 2 and connection.sequence == 9
    assert connection.connection_marks == {"connectStartNs": 105, "connectEndNs": 110}
    assert calls == [("127.0.0.1", 12345, 5)] * 2


def install_driver(monkeypatch, *, orders=None, fail_at=None, changed=False):
    connections, calls, emitted = [], [], []
    generations = {"rankings": "fixture-generation-1", "trade": "fixture-generation-1"}

    class Connection:
        def __init__(self, port, sequence, **options):
            self.sequence, self.closed = sequence, 0
            self.options = options
            connections.append(self)

        def close(self):
            self.closed += 1

    def exchange(connection, path, *, etag=None, split_body=False):
        view = "trade" if path.endswith("context") else "rankings"
        calls.append((view, etag, connection.sequence))
        if len(calls) == fail_at:
            raise lab.DiagnosticRequestFailure(
                {
                    "requestStartNs": 100,
                    "failureObservedNs": 500,
                    "connectionSequence": connection.sequence,
                },
                "TimeoutError",
            )
        if changed and len(calls) == 3:
            generations[view] = "fixture-generation-2"
        candidate = response(view, generations[view], request_id=len(calls))
        result = response(
            view,
            generations[view],
            conditional=etag == candidate.headers["etag"],
            request_id=len(calls),
        )
        return result, {
            "requestStartNs": 100,
            "bodyCompleteNs": 200,
            "connectionSequence": connection.sequence,
        }

    monkeypatch.setattr(lab, "DiagnosticConnection", Connection)
    monkeypatch.setattr(lab, "diagnostic_response", exchange)
    if orders is not None:
        monkeypatch.setattr(lab, "diagnostic_orders", lambda *a: iter(orders))
    return connections, calls, emitted


def test_seeded_conditionals_work_in_every_balanced_slot(monkeypatch):
    orders = list(itertools.islice(lab.diagnostic_orders("balanced", 73), 24))
    connections, calls, rows = install_driver(monkeypatch, orders=orders)
    lab.diagnostic_reads(args(), threading.Event(), PRIVATE, rows.append)
    assert len(rows) == 96 and len(calls) == 98
    assert [(view, etag) for view, etag, _ in calls[:2]] == [("rankings", None), ("trade", None)]
    counts = Counter((row["route"], row["kind"], row["slot"]) for row in rows)
    assert len(counts) == 16 and set(counts.values()) == {6}
    assert all(row["status"] == (304 if row["kind"] == "conditional" else 200) for row in rows)
    assert not any("failureType" in row for row in rows)
    assert len(connections) == 1 and connections[0].closed == 1
    assert PRIVATE not in json.dumps(rows)


def test_conditional_changed_200_updates_following_conditional_identity(monkeypatch):
    connections, calls, rows = install_driver(
        monkeypatch, orders=[(0, (1, 0, 2, 3)), (1, (1, 0, 2, 3))], changed=True
    )
    lab.diagnostic_reads(args(), threading.Event(), PRIVATE, rows.append)
    assert rows[0]["kind"] == "conditional" and rows[0]["status"] == 200
    assert rows[0]["generation"] == "fixture-generation-2"
    assert rows[4]["kind"] == "conditional" and rows[4]["status"] == 304
    assert calls[2][1] != calls[6][1]
    assert not any("failureType" in row for row in rows)


@pytest.mark.parametrize("mode", ["reuse", "new"])
def test_error_reconnects_and_serializes_only_safe_type(monkeypatch, mode):
    connections, calls, rows = install_driver(monkeypatch, orders=[(0, (1, 0, 2, 3))], fail_at=3)
    lab.diagnostic_reads(args(diagnostic_connection=mode), threading.Event(), PRIVATE, rows.append)
    assert rows[0]["failureType"] == "TimeoutError"
    assert rows[0]["requestStartNs"] == 100 and rows[0]["failureObservedNs"] == 500
    assert "status" not in rows[0]
    assert rows[1]["status"] == 200
    assert calls[2][2] != calls[3][2]
    assert all(connection.closed >= 1 for connection in connections)
    assert PRIVATE not in json.dumps(rows)
    assert not any(key in rows[0] for key in ("body", "headers", "cookie", "path", "message"))


@pytest.mark.parametrize("encoding", [None, "gzip", "identity", PRIVATE, "gzip," + PRIVATE])
def test_actual_diagnostic_rows_allowlist_encoding_even_when_response_audit_fails(
    monkeypatch, encoding
):
    _, calls, rows = install_driver(monkeypatch, orders=[(0, (0,))])
    original = lab.diagnostic_response

    def exchange(*args, **kwargs):
        item, marks = original(*args, **kwargs)
        if len(calls) == 3:
            if encoding is None:
                item.headers.pop("content-encoding")
            else:
                item.headers["content-encoding"] = encoding
            if encoding in {None, "identity"}:
                item.body = gzip.decompress(item.body)
                item.headers["content-length"] = str(len(item.body))
        return item, marks

    monkeypatch.setattr(lab, "diagnostic_response", exchange)
    lab.diagnostic_reads(args(), threading.Event(), PRIVATE, rows.append)
    assert len(rows) == 1
    valid = encoding in {None, "gzip", "identity"}
    assert rows[0]["contentEncoding"] == (
        "absent" if encoding is None else encoding if valid else "other"
    )
    assert ("failureType" not in rows[0]) is valid
    if not valid:
        assert rows[0]["failureType"] == "ValueError"
        assert rows[0]["headerFailure"] == "unsupported_content_encoding"
        assert "generation" not in rows[0]
    assert rows[0]["bodyCompleteNs"] >= rows[0]["requestStartNs"]
    assert PRIVATE not in json.dumps(rows)


@pytest.mark.parametrize("sequence", [None, PRIVATE, "0", "-1", "1.0", " 1", "١", str(2**53)])
def test_actual_diagnostic_rows_refuse_missing_or_invalid_sequence_without_raw_header(
    monkeypatch, sequence
):
    _, calls, rows = install_driver(monkeypatch, orders=[(0, (0,))])
    original = lab.diagnostic_response

    def exchange(*args, **kwargs):
        item, marks = original(*args, **kwargs)
        if len(calls) == 3:
            if sequence is None:
                item.headers.pop("x-soak-request-sequence")
            else:
                item.headers["x-soak-request-sequence"] = sequence
        return item, marks

    monkeypatch.setattr(lab, "diagnostic_response", exchange)
    lab.diagnostic_reads(args(), threading.Event(), PRIVATE, rows.append)
    assert len(rows) == 1 and rows[0]["failureType"] == "ValueError"
    assert rows[0].get("requestId") is None
    assert rows[0]["bodyCompleteNs"] >= rows[0]["requestStartNs"]
    assert PRIVATE not in json.dumps(rows)


@pytest.mark.parametrize("comparable", [True, False])
def test_clock_exchange_intersects_network_delay_bounds(monkeypatch, comparable):
    values, replies = [], []
    for i, (inbound, outbound) in enumerate([(5, 9), (2, 8), (8, 1)] * 4):
        start = 1000 + i * 100
        offset = 500 if comparable or i < 6 else 1500
        values.extend([start, start + inbound + 5 + outbound])
        replies.append(
            {
                "receiveNs": start + inbound + offset,
                "sendNs": start + inbound + 5 + offset,
                "clock": {"name": "fixture"},
            }
        )
    ticks = iter(values)
    monkeypatch.setattr(lab.time, "perf_counter_ns", lambda: next(ticks))

    def control(action):
        assert action == "clock"
        return {"result": replies.pop(0)}

    result = lab.exchange_clocks(SimpleNamespace(control=control))
    assert len(result["exchanges"]) == 12 and not replies
    assert result["comparable"] is comparable
    assert result["offsetLowerNs"] == (499 if comparable else 1499)
    assert result["offsetUpperNs"] == 502
    for row in result["exchanges"]:
        assert row["offsetLowerNs"] == row["serverSendNs"] - row["driverEndNs"]
        assert row["offsetUpperNs"] == row["serverReceiveNs"] - row["driverStartNs"]


def test_same_asgi_application_audits_joined_chunks_and_conditionals():
    calls = []

    async def application(scope, receive, send):
        calls.append(scope)
        assert await receive() == {"type": "http.request", "body": b"", "more_body": False}
        view = "trade" if scope["path"].endswith("context") else "rankings"
        headers = dict(scope["headers"])
        assert headers[b"cookie"] == b"jason_session=offline-soak-fixture"
        actual = response(view, conditional=b"if-none-match" in headers, request_id=len(calls))
        await send(
            {
                "type": "http.response.start",
                "status": actual.status_code,
                "headers": [
                    (key.encode(), value.encode()) for key, value in actual.headers.items()
                ],
            }
        )
        for chunk in (actual.body[:3], actual.body[3:9], actual.body[9:]):
            await send({"type": "http.response.body", "body": chunk, "more_body": True})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=2))
    assert len(calls) == len(result["rows"]) == 8 and result["failures"] == {}
    assert [row["status"] for row in result["rows"]] == [200, 304, 200, 304] * 2
    assert all(row["bodyBytes"] > 0 for row in result["rows"] if row["status"] == 200)
    assert all(row["bodyBytes"] == 0 for row in result["rows"] if row["status"] == 304)
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "sequence,valid",
    [
        (None, True),
        ("1", True),
        (str(2**53 - 1), True),
        (PRIVATE, False),
        ("0", False),
        ("-1", False),
        ("1.0", False),
        ("١", False),
        (str(2**53), False),
    ],
)
def test_actual_asgi_metadata_accepts_only_bounded_numeric_request_sequences(sequence, valid):
    calls = []

    async def application(scope, receive, send):
        calls.append(scope["path"])
        view = "trade" if scope["path"].endswith("context") else "rankings"
        item = response(view, conditional=b"if-none-match" in dict(scope["headers"]))
        if sequence is None:
            item.headers.pop("x-soak-request-sequence")
        else:
            item.headers["x-soak-request-sequence"] = sequence
        await send(
            {
                "type": "http.response.start",
                "status": item.status_code,
                "headers": [(key.encode(), value.encode()) for key, value in item.headers.items()],
            }
        )
        await send({"type": "http.response.body", "body": item.body})

    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=1))
    if valid:
        assert len(result["rows"]) == len(calls) == 4 and not result["failures"]
        assert all(
            row["requestId"] == (None if sequence is None else int(sequence))
            for row in result["rows"]
        )
    else:
        assert len(calls) == 1 and result["rows"] == []
        assert result["failures"] == {"ValueError": 1}
    assert PRIVATE not in json.dumps(result)


def test_asgi_timeout_reports_type_without_exception_details(monkeypatch):
    original_wait_for = asyncio.wait_for

    async def fast_timeout(awaitable, *, timeout):
        assert timeout == 5
        return await original_wait_for(awaitable, timeout=0.001)

    async def application(scope, receive, send):
        await asyncio.Future()

    monkeypatch.setattr(asyncio, "wait_for", fast_timeout)
    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=1))
    assert result["rows"] == [] and result["failures"] == {"TimeoutError": 1}
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "stage,failure_type,end",
    [("write", "OSError", 110), ("headers", "TimeoutError", 130), ("body", "TimeoutError", 160)],
)
def test_failed_response_preserves_only_completed_stage_marks(
    monkeypatch, stage, failure_type, end
):
    clock = Clock()
    monkeypatch.setattr(lab.time, "perf_counter_ns", clock)
    wire = BodyResponse(clock, failure=TimeoutError(PRIVATE) if stage == "body" else None)
    connection = Transport(clock, wire, failure=stage)
    with pytest.raises(lab.DiagnosticRequestFailure) as captured:
        lab.diagnostic_response(connection, "/fixture", split_body=True)
    error = captured.value
    assert error.failure_type == failure_type
    assert error.marks["requestStartNs"] == 100
    assert error.marks["failureObservedNs"] == end
    assert error.marks["connectionSequence"] == 7
    assert ("writeCompleteNs" in error.marks) is (stage != "write")
    assert ("headersAvailableNs" in error.marks) is (stage == "body")
    assert "bodyCompleteNs" not in error.marks and "firstBodyAvailableNs" not in error.marks
    if stage == "body":
        assert error.marks["tcpNoDelay"] == 1 and error.marks["willClose"] is False
    assert PRIVATE not in json.dumps(error.marks)


def test_failed_reconnect_does_not_retain_previous_connect_end(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lab.time, "perf_counter_ns", clock)
    calls = []

    def connect(connection):
        calls.append(True)
        clock.advance(5)
        if len(calls) == 2:
            raise OSError(PRIVATE)

    monkeypatch.setattr(lab.http.client.HTTPConnection, "connect", connect)
    connection = lab.DiagnosticConnection(12345, 3)
    connection.connect()
    with pytest.raises(OSError):
        connection.connect()
    assert connection.connection_marks == {"connectStartNs": 105}
    assert connection.establishments == 1


def test_reused_connection_write_failure_has_no_old_connect_timestamps(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(lab.time, "perf_counter_ns", clock)
    connection = Transport(clock, BodyResponse(clock), failure="write")
    connection.establishments = 1
    connection.connection_marks = {"connectStartNs": 10, "connectEndNs": 20}
    with pytest.raises(lab.DiagnosticRequestFailure) as captured:
        lab.diagnostic_response(connection, "/fixture")
    assert captured.value.marks["connectionEstablishment"] == 1
    assert "connectStartNs" not in captured.value.marks
    assert "connectEndNs" not in captured.value.marks


def test_seed_failure_is_observable_and_closes_reader_without_measured_success(monkeypatch):
    connections, calls, rows = install_driver(monkeypatch, orders=[(0, (1, 0, 2, 3))], fail_at=1)
    with pytest.raises(lab.DiagnosticRequestFailure):
        lab.diagnostic_reads(args(), threading.Event(), PRIVATE, rows.append, cell="fixture-cell")
    assert len(rows) == len(calls) == 1
    assert rows[0] == {
        "route": "rankings",
        "kind": "unconditional",
        "stage": "seed",
        "cell": "fixture-cell",
        "failureType": "TimeoutError",
        "requestStartNs": 100,
        "failureObservedNs": 500,
        "connectionSequence": 1,
    }
    assert connections[0].closed == 1
    assert PRIVATE not in json.dumps(rows)


def test_asgi_application_exception_never_serializes_sensitive_message():
    calls = []

    async def application(scope, receive, send):
        calls.append(scope["path"])
        raise ValueError(PRIVATE)

    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=1))
    assert result["rows"] == [] and result["failures"] == {"ValueError": 1}
    assert len(calls) == 1
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("compressed", [True, False])
def test_remote_control_decodes_metadata_but_http_response_keeps_wire_bytes(
    monkeypatch, compressed
):
    metadata = {
        "result": {
            "scope": "fixture clock \u23f1",
            "rows": [{"route": "rankings", "elapsedMs": 0.25}] * 128,
            "failures": {},
        }
    }
    raw = json.dumps(metadata, ensure_ascii=False).encode("utf-8")
    assert len(raw) > 500  # The real middleware's gzip threshold is crossed.
    wire_body = gzip.compress(raw, mtime=0) if compressed else raw
    connections = []

    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("127.0.0.1", 12345, 90)
            self.body, self.closed, self.requests = wire_body, False, []
            connections.append(self)

        def request(self, method, path, *, headers):
            self.requests.append((method, path, headers))

        def getresponse(self):
            headers = [("Content-Type", "application/json")]
            if compressed:
                headers.append(("Content-Encoding", "gzip"))

            def read():
                body, self.body = self.body, b""
                return body

            return SimpleNamespace(status=200, getheaders=lambda: headers, read=read)

        def close(self):
            self.closed = True

    # The ordinary HTTP helper must preserve compressed bytes for timing/audit.
    probe = Connection("127.0.0.1", 12345, 90)
    received = lab.http_response(probe, "/__soak/asgi", method="POST")
    assert received.body == wire_body
    assert received.headers.get("content-encoding") == ("gzip" if compressed else None)
    monkeypatch.setattr(lab.http.client, "HTTPConnection", Connection)
    assert lab.RemoteRuntime(12345).control("asgi", timeout=90) == metadata
    actual = connections[-1]
    assert actual.closed and actual.body == b""
    assert actual.requests[0][:2] == ("POST", "/__soak/asgi")
    assert actual.requests[0][2]["Accept-Encoding"] == "gzip"


def test_remote_control_closes_connection_when_gzip_decoding_fails(monkeypatch):
    closed = []
    connection = SimpleNamespace(close=lambda: closed.append(True))
    monkeypatch.setattr(lab.http.client, "HTTPConnection", lambda *a, **k: connection)
    monkeypatch.setattr(
        lab,
        "http_response",
        lambda *a, **k: SimpleNamespace(
            status_code=200, headers={"content-encoding": "gzip"}, body=b"not-gzip"
        ),
    )
    with pytest.raises(gzip.BadGzipFile):
        lab.RemoteRuntime(12345).control("asgi")
    assert closed == [True]


@pytest.mark.parametrize("failure", ["incomplete", "length"])
def test_asgi_control_aborts_first_incomplete_or_wrong_length_response(failure):
    calls = []

    async def application(scope, receive, send):
        calls.append(scope["path"])
        actual = response("rankings")
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (key.encode(), value.encode()) for key, value in actual.headers.items()
                ],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": actual.body if failure == "incomplete" else actual.body[:-1],
                "more_body": failure == "incomplete",
            }
        )

    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=2))
    assert len(calls) == 1 and result["rows"] == []
    assert result["failures"] == {"AssertionError": 1}
    assert PRIVATE not in json.dumps(result)


def test_asgi_control_overall_deadline_prevents_another_request(monkeypatch):
    ticks = iter([0.0, 60.0])
    monkeypatch.setattr(lab.time, "perf_counter", lambda: next(ticks))

    async def application(scope, receive, send):
        pytest.fail("ASGI request started after control deadline")

    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=1))
    assert result["rows"] == [] and result["failures"] == {"control_deadline": 1}


def test_asgi_control_last_request_timeout_is_capped_by_remaining_deadline(monkeypatch):
    clock_calls = []
    budgets = []

    def clock():
        clock_calls.append(True)
        return 0.0 if len(clock_calls) == 1 else 59.0

    async def wait_for(awaitable, *, timeout):
        budgets.append(timeout)
        awaitable.close()
        raise TimeoutError(PRIVATE)

    async def application(scope, receive, send):
        pytest.fail("test wait_for should close the unstarted coroutine")

    monkeypatch.setattr(lab.time, "perf_counter", clock)
    monkeypatch.setattr(asyncio, "wait_for", wait_for)
    result = asyncio.run(lab.asgi_control(application, fixture_league_key=PRIVATE, cycles=1))
    assert budgets == [1.0]
    assert result["rows"] == [] and result["failures"] == {"TimeoutError": 1}
    assert PRIVATE not in json.dumps(result)


@pytest.mark.parametrize(
    "options",
    [
        ["--diagnostic-order", "balanced"],
        ["--diagnostic-timeline"],
        ["--diagnostic-spans", "--diagnostic-pacing", "sleep"],
        ["--diagnostic-spans", "--diagnostic-timeline", "--diagnostic-cell-seconds", "nan"],
    ],
)
def test_cli_rejects_unenabled_or_invalid_diagnostics_before_startup(tmp_path, options):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/soak_prepared_serving.py"),
            "--root",
            str(tmp_path / "unused"),
            *options,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert (
        "diagnostic experiments require" in result.stderr
        or "diagnostic cells and repetitions" in result.stderr
    )
    assert result.stdout == "" and not (tmp_path / "unused").exists()


def frozen_scope(path, etag=None, **changes):
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [(b"if-none-match", etag)] if etag is not None else [],
        **changes,
    }


async def asgi_messages(application, scope):
    messages = []

    async def receive():
        return {"type": "http.request", "body": b""}

    async def send(message):
        messages.append(copy.deepcopy(message))

    await application(scope, receive, send)
    return messages


@pytest.mark.parametrize("path", ["/api/read-models/rankings", "/api/read-models/trade/context"])
def test_frozen_owner_replays_exact_200_and_matching_304_separately(path):
    calls = []
    etag = b'"captured-etag"'
    body = gzip.compress(PRIVATE.encode(), mtime=0)

    async def application(scope, receive, send):
        calls.append(scope)
        conditional = dict(scope["headers"]).get(b"if-none-match") == etag
        await send(
            {
                "type": "http.response.start",
                "status": 304 if conditional else 200,
                "headers": [
                    (b"etag", etag),
                    (b"content-encoding", b"gzip"),
                    (b"vary", b"Cookie"),
                    (b"vary", b"Accept-Encoding"),
                ],
            }
        )
        chunks = [b""] if conditional else [body[:3], b"", body[3:]]
        for index, chunk in enumerate(chunks):
            await send(
                {"type": "http.response.body", "body": chunk, "more_body": index < len(chunks) - 1}
            )

    frozen = lab.FrozenResponses(application)

    async def exercise():
        first = await asgi_messages(frozen, frozen_scope(path))
        assert await asgi_messages(frozen, frozen_scope(path)) == first
        conditional = await asgi_messages(frozen, frozen_scope(path, etag))
        assert await asgi_messages(frozen, frozen_scope(path, etag)) == conditional
        assert await asgi_messages(frozen, frozen_scope(path, b'"other-etag"')) == first
        assert b"".join(row.get("body", b"") for row in first) == body
        assert conditional[0]["status"] == 304
        assert b"".join(row.get("body", b"") for row in conditional) == b""

    asyncio.run(exercise())
    assert len(calls) == 2 and set(frozen.cache) == {(path, 200), (path, 304)}


@pytest.mark.parametrize(
    "scope",
    [
        {"type": "lifespan"},
        frozen_scope("/api/read-models/rankings", method="POST"),
        frozen_scope("/api/read-models/rankings", method="HEAD"),
        frozen_scope("/__soak/clock"),
        frozen_scope("/api/read-models/players/catalog"),
    ],
)
def test_frozen_owner_forwards_other_surfaces_unchanged(scope):
    calls = []
    result = object()

    async def application(actual_scope, actual_receive, actual_send):
        calls.append((actual_scope, actual_receive, actual_send))
        return result

    async def receive():
        return {}

    async def send(message):
        pass

    frozen = lab.FrozenResponses(application)
    assert asyncio.run(frozen(scope, receive, send)) is result
    assert calls == [(scope, receive, send)] and frozen.cache == {}


@pytest.mark.parametrize(
    "failure",
    [
        "bytes",
        "chunks",
        "partial",
        "missing-start",
        "duplicate-start",
        "after-final",
        "application-error",
    ],
)
def test_frozen_owner_never_caches_oversize_partial_or_failed_responses(failure):
    start = {"type": "http.response.start", "status": 200, "headers": [(b"etag", b"e")]}

    async def application(scope, receive, send):
        if failure != "missing-start":
            await send(start)
        if failure == "duplicate-start":
            await send(start)
        if failure == "chunks":
            for _ in range(256):
                await send({"type": "http.response.body", "body": b"", "more_body": True})
        await send(
            {
                "type": "http.response.body",
                "body": b"x" * (2 * 1024**2 + 1) if failure == "bytes" else b"x",
                "more_body": failure == "partial",
            }
        )
        if failure == "after-final":
            await send({"type": "http.response.body", "body": b"later"})
        if failure == "application-error":
            raise OSError(PRIVATE)

    frozen = lab.FrozenResponses(application)
    with pytest.raises((AssertionError, OSError)):
        asyncio.run(asgi_messages(frozen, frozen_scope("/api/read-models/rankings")))
    assert frozen.cache == {}


def test_frozen_owner_accepts_exact_byte_and_message_budget():
    body = b"x" * (2 * 1024**2)

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"etag", b"e")]})
        for i in range(255):
            await send(
                {
                    "type": "http.response.body",
                    "body": body if i == 0 else b"",
                    "more_body": i < 254,
                }
            )

    frozen = lab.FrozenResponses(application)
    asyncio.run(asgi_messages(frozen, frozen_scope("/api/read-models/rankings")))
    cached = frozen.cache[("/api/read-models/rankings", 200)]
    assert len(cached) == 256
    assert sum(len(message.get("body", b"")) for message in cached) == 2 * 1024**2


def test_frozen_owner_does_not_cache_after_downstream_send_failure():
    problem = OSError(PRIVATE)

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": [(b"etag", b"e")]})
        await send({"type": "http.response.body", "body": b"x", "more_body": False})

    async def receive():
        return {}

    async def send(message):
        if message["type"] == "http.response.body":
            raise problem

    frozen = lab.FrozenResponses(application)
    with pytest.raises(OSError) as captured:
        asyncio.run(frozen(frozen_scope("/api/read-models/rankings"), receive, send))
    assert captured.value is problem and frozen.cache == {}


def test_socket_recorder_delegates_original_buffer_sizes_closure_and_error(monkeypatch):
    wall, cpu = Clock(), Clock()
    monkeypatch.setattr(lab.time, "perf_counter_ns", wall)
    monkeypatch.setattr(lab.time, "thread_time_ns", cpu)
    original_buffer = memoryview(bytearray(32))
    problem = OSError(PRIVATE)
    calls, closed = [], []

    class Sock:
        def recv_into(self, buffer, *args):
            assert buffer is original_buffer
            calls.append(args)
            wall.advance(50)
            cpu.advance(7)
            if len(calls) == 3:
                raise problem
            buffer[:3] = b"abc"
            return 3

        def close(self):
            closed.append(True)

    connection = SimpleNamespace(socket_reads=[], socket_reads_dropped=0)
    recorder = lab.RecordingSocketReads(Sock(), connection)
    assert recorder.recv_into(original_buffer, 3, socket.MSG_PEEK) == 3
    assert recorder.recv_into(original_buffer, 0) == 3
    with pytest.raises(OSError) as failure:
        recorder.recv_into(original_buffer)
    assert failure.value is problem
    recorder.close()
    assert calls == [(3, socket.MSG_PEEK), (0,), ()] and closed == [True]
    assert connection.socket_reads == [
        {"startNs": 100, "endNs": 150, "threadCpuNs": 7, "requestedBytes": 3, "receivedBytes": 3},
        {"startNs": 150, "endNs": 200, "threadCpuNs": 7, "requestedBytes": 32, "receivedBytes": 3},
        {
            "startNs": 200,
            "endNs": 250,
            "threadCpuNs": 7,
            "requestedBytes": 32,
            "receivedBytes": None,
        },
    ]
    assert PRIVATE not in json.dumps(connection.socket_reads)


def test_socket_recorder_bounds_records_and_counts_every_drop():
    calls = []

    def recv_into(buffer, *args):
        calls.append(True)
        return 0

    connection = SimpleNamespace(socket_reads=[], socket_reads_dropped=0)
    recorder = lab.RecordingSocketReads(SimpleNamespace(recv_into=recv_into), connection)
    for _ in range(259):
        assert recorder.recv_into(bytearray(8)) == 0
    assert len(calls) == 259
    assert len(connection.socket_reads) == 256 and connection.socket_reads_dropped == 3
    assert all(row["receivedBytes"] == 0 for row in connection.socket_reads)


@pytest.mark.parametrize("enabled", [False, True])
def test_driver_preserves_socket_read_optin_across_reconnect(monkeypatch, enabled):
    connections, calls, rows = install_driver(monkeypatch, orders=[(0, (1, 0, 2, 3))], fail_at=3)
    lab.diagnostic_reads(
        args(diagnostic_socket_reads=enabled), threading.Event(), PRIVATE, rows.append
    )
    assert len(connections) == 2
    assert all(
        connection.options == ({"socket_reads": True} if enabled else {})
        for connection in connections
    )
    assert rows[0]["failureType"] == "TimeoutError" and rows[1]["status"] == 200


def test_socket_record_drops_make_the_measured_request_fail(monkeypatch):
    connections, calls, rows = install_driver(monkeypatch, orders=[(0, (1, 0, 2, 3))])
    original = lab.diagnostic_response

    def exchange(*args, **kwargs):
        result, marks = original(*args, **kwargs)
        return result, {**marks, "socketReadsDropped": 1 if len(calls) == 3 else 0}

    monkeypatch.setattr(lab, "diagnostic_response", exchange)
    lab.diagnostic_reads(
        args(diagnostic_socket_reads=True), threading.Event(), PRIVATE, rows.append
    )
    assert rows[0]["failureType"] == "AssertionError" and rows[0]["socketReadsDropped"] == 1
    assert "status" not in rows[0] and rows[1]["status"] == 200
    assert len(connections) == 2


@pytest.mark.parametrize("enabled", [False, True])
def test_socket_read_optin_keeps_actual_http_bytes_and_resets_each_request(enabled):
    # Local TCP fixture only: exercises CPython HTTPResponse/SocketIO buffering,
    # including closing through the proxy. It starts no application or provider.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.settimeout(2)
    listener.bind(("127.0.0.1", 0))
    listener.listen(1)
    errors, wire_lengths = [], []
    expected = [response("rankings"), response("rankings", conditional=True)]

    def serve():
        try:
            peer, _ = listener.accept()
            with peer:
                peer.settimeout(2)
                for item in expected:
                    request = b""
                    while b"\r\n\r\n" not in request:
                        block = peer.recv(8192)
                        assert block, "fixture request ended early"
                        request += block
                    status = b"200 OK" if item.status_code == 200 else b"304 Not Modified"
                    headers = b"".join(
                        key.encode() + b": " + value.encode() + b"\r\n"
                        for key, value in item.headers.items()
                    )
                    wire = b"HTTP/1.1 " + status + b"\r\n" + headers + b"\r\n" + item.body
                    wire_lengths.append(len(wire))
                    peer.sendall(wire)
        except Exception as exc:
            errors.append(type(exc).__name__)

    worker = threading.Thread(target=serve, daemon=True)
    worker.start()
    connection = lab.DiagnosticConnection(listener.getsockname()[1], 1, socket_reads=enabled)
    if not enabled:
        assert connection.response_class is lab.http.client.HTTPResponse
    try:
        first, first_marks = lab.diagnostic_response(connection, "/api/read-models/rankings")
        snapshot = copy.deepcopy(first_marks)
        second, second_marks = lab.diagnostic_response(
            connection, "/api/read-models/rankings", etag=first.headers["etag"]
        )
        assert first.body == expected[0].body and second.body == b""
        assert (first.status_code, second.status_code) == (200, 304)
        assert first_marks == snapshot
        if enabled:
            for marks, length in zip((first_marks, second_marks), wire_lengths):
                assert marks["socketReads"] and marks["socketReadsDropped"] == 0
                assert sum(row["receivedBytes"] for row in marks["socketReads"]) == length
                assert all(row["requestedBytes"] > 0 for row in marks["socketReads"])
                assert PRIVATE not in json.dumps(marks)
            assert first_marks["socketReads"] is not second_marks["socketReads"]
        else:
            assert "socketReads" not in first_marks and "socketReads" not in second_marks
    finally:
        connection.close()
        listener.close()
        worker.join(timeout=3)
    assert not worker.is_alive() and errors == []


@pytest.mark.parametrize(
    "options,error",
    [
        (["--diagnostic-socket-reads"], "diagnostic experiments require"),
        (["--diagnostic-response-owner", "frozen"], "diagnostic experiments require"),
        (
            [
                "--diagnostic-spans",
                "--diagnostic-timeline",
                "--diagnostic-response-owner",
                "frozen",
            ],
            "frozen responses require",
        ),
        (
            [
                "--diagnostic-spans",
                "--diagnostic-timeline",
                "--diagnostic-response-owner",
                "frozen",
                "--diagnostic-quiet",
                "factorial",
            ],
            "frozen responses require",
        ),
    ],
)
def test_new_control_options_require_explicit_allowed_diagnostic_context(tmp_path, options, error):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/soak_prepared_serving.py"),
            "--root",
            str(tmp_path / "unused"),
            *options,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2 and error in result.stderr
    assert result.stdout == "" and not (tmp_path / "unused").exists()


@pytest.mark.parametrize("status", [200, 304])
def test_quiet_reload_header_changes_only_header_without_mutating_source(status):
    chunks = [b"compressed-prefix", b"", b"compressed-suffix"] if status == 200 else [b""]
    start = {
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-encoding", b"gzip"),
            (b"X-Soak-Reload-Active", b"1"),
            (b"etag", b'"same-etag"'),
            (b"x-soak-reload-active", b"9"),
            (b"vary", b"Cookie"),
            (b"vary", b"Accept-Encoding"),
            (b"content-length", str(sum(map(len, chunks))).encode()),
        ],
        "trailers": False,
    }
    bodies = [
        {"type": "http.response.body", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    before = copy.deepcopy([start, *bodies])
    sent, calls = [], []
    scope = frozen_scope("/api/read-models/rankings")
    request = {"type": "http.request", "body": PRIVATE.encode()}
    sentinel = object()

    async def receive():
        return request

    async def send(message):
        sent.append(message)

    async def application(actual_scope, actual_receive, actual_send):
        calls.append((actual_scope, actual_receive))
        assert await actual_receive() is request
        for message in (start, *bodies):
            await actual_send(message)
        return sentinel

    result = asyncio.run(lab.quiet_reload_header(application)(scope, receive, send))
    assert result is sentinel and calls == [(scope, receive)]
    assert [start, *bodies] == before
    assert sent[0] == {
        **start,
        "headers": [
            (key, value)
            for key, value in start["headers"]
            if key.lower() != b"x-soak-reload-active"
        ]
        + [(b"x-soak-reload-active", b"0")],
    }
    assert sent[0] is not start and sent[0]["headers"] is not start["headers"]
    assert len(sent) == len(bodies) + 1
    assert all(actual is original for actual, original in zip(sent[1:], bodies))


def test_quiet_reload_header_forwards_lifespan_calls_and_messages():
    scope = {"type": "lifespan", "asgi": {"version": "3.0"}}
    messages = [{"type": "lifespan.startup.complete"}, {"type": "lifespan.shutdown.complete"}]
    sent = []
    sentinel = object()

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        sent.append(message)

    async def application(actual_scope, actual_receive, actual_send):
        assert actual_scope is scope and actual_receive is receive
        assert await actual_receive() == {"type": "lifespan.startup"}
        for message in messages:
            await actual_send(message)
        return sentinel

    assert asyncio.run(lab.quiet_reload_header(application)(scope, receive, send)) is sentinel
    assert len(sent) == 2 and all(actual is original for actual, original in zip(sent, messages))


@pytest.mark.parametrize("origin", ["application", "send"])
def test_quiet_reload_header_preserves_error_identity_without_completing_response(origin):
    problem = OSError(PRIVATE)
    sent = []

    async def receive():
        return {}

    async def send(message):
        sent.append(message)
        if message["type"] == "http.response.body":
            raise problem

    async def application(scope, receive, send):
        if origin == "application":
            raise problem
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"partial", "more_body": True})
        pytest.fail("send failure was swallowed")

    with pytest.raises(OSError) as captured:
        asyncio.run(lab.quiet_reload_header(application)(frozen_scope("/fixture"), receive, send))
    assert captured.value is problem
    assert len(sent) == (0 if origin == "application" else 2)
    assert not any(message.get("more_body") is False for message in sent)


def test_reload_observer_cli_defaults_to_on_without_starting_worker(monkeypatch, tmp_path):
    class Parsed(Exception):
        pass

    original = lab.argparse.ArgumentParser.parse_args

    def capture(parser, *args, **kwargs):
        raise Parsed(original(parser, *args, **kwargs))

    monkeypatch.setattr(lab.argparse.ArgumentParser, "parse_args", capture)
    monkeypatch.setattr(
        sys, "argv", ["soak_prepared_serving.py", "--root", str(tmp_path / "unused")]
    )
    monkeypatch.setattr(sys, "path", list(sys.path))
    with pytest.raises(Parsed) as captured:
        runpy.run_path(str(REPO / "scripts/soak_prepared_serving.py"), run_name="__main__")
    assert captured.value.args[0].diagnostic_reload_observer == "on"
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    "kind,setting,expected",
    [("web", None, False), ("web", "on", False), ("web", "off", True), ("changed", "off", False)],
)
def test_launch_forwards_reload_observer_override_only_to_diagnostic_web_child(
    monkeypatch, tmp_path, kind, setting, expected
):
    captured = []
    child = SimpleNamespace(pid=123)

    def popen(command, **kwargs):
        # Do not retain the inherited process environment in test diagnostics.
        kwargs.pop("env", None)
        captured.append(command)
        return child

    options = SimpleNamespace(
        root=tmp_path,
        budget_bytes=1024,
        port=12345,
        diagnostic_spans=True,
        diagnostic_timeline=True,
    )
    if setting is not None:
        options.diagnostic_reload_observer = setting
    monkeypatch.setattr(lab.subprocess, "Popen", popen)
    assert lab.launch(options, kind, sequence=7) is child
    assert len(captured) == 1
    command = captured[0]
    assert ("--diagnostic-reload-observer" in command) is expected
    if expected:
        assert command[command.index("--diagnostic-reload-observer") + 1] == "off"
        assert "--diagnostic-spans" in command and "--diagnostic-timeline" in command


@pytest.mark.parametrize(
    "options,error",
    [
        (["--diagnostic-reload-observer", "off"], "diagnostic experiments require"),
        (
            ["--diagnostic-spans", "--diagnostic-reload-observer", "off"],
            "diagnostic experiments require",
        ),
        (
            ["--diagnostic-spans", "--diagnostic-timeline", "--diagnostic-reload-observer", "off"],
            "reload observer control requires",
        ),
        (
            [
                "--diagnostic-spans",
                "--diagnostic-timeline",
                "--diagnostic-reload-observer",
                "off",
                "--diagnostic-quiet",
                "factorial",
            ],
            "reload observer control requires",
        ),
        (
            [
                "--diagnostic-spans",
                "--diagnostic-timeline",
                "--diagnostic-reload-observer",
                "off",
                "--diagnostic-quiet",
                "control",
                "--diagnostic-cell-seconds",
                "nan",
            ],
            "diagnostic cells and repetitions",
        ),
        (
            [
                "--diagnostic-spans",
                "--diagnostic-timeline",
                "--diagnostic-reload-observer",
                "off",
                "--worker",
                "web",
                "--diagnostic-cell-seconds",
                "nan",
            ],
            "diagnostic cells and repetitions",
        ),
    ],
)
def test_reload_observer_cli_enforces_optin_and_control_context_before_startup(
    tmp_path, options, error
):
    # Allowed contexts deliberately stop at the subsequent finite-duration gate,
    # proving authorization parsing without starting the driver or web child.
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/soak_prepared_serving.py"),
            "--root",
            str(tmp_path / "unused"),
            *options,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2 and error in result.stderr
    assert result.stdout == "" and not (tmp_path / "unused").exists()


@pytest.mark.parametrize(
    "options,error",
    [
        (["--diagnostic-transport"], "diagnostic experiments require"),
        (
            ["--diagnostic-spans", "--diagnostic-timeline", "--diagnostic-transport"],
            "transport observations require",
        ),
        (
            [
                "--diagnostic-spans",
                "--diagnostic-timeline",
                "--diagnostic-transport",
                "--diagnostic-quiet",
                "factorial",
            ],
            "transport observations require",
        ),
    ],
)
def test_transport_control_cannot_enter_default_or_refresh_execution(tmp_path, options, error):
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/soak_prepared_serving.py"),
            "--root",
            str(tmp_path / "unused"),
            *options,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2 and error in result.stderr
    assert not (tmp_path / "unused").exists()


def nested_driver_function(name, namespace):
    tree = ast.parse(Path(lab.__file__).read_text(encoding="utf-8"))
    function = next(
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<driver-seam>", "exec"), namespace)
    return namespace[name]


def test_natural_driver_preserves_immediate_pairs_without_seed_or_cross_cycle_etag(monkeypatch):
    connections, calls, rows = install_driver(
        monkeypatch, orders=[(0, (0, 1, 2, 3)), (1, (0, 1, 2, 3))]
    )
    phase = nested_driver_function(
        "diagnostic_phase",
        {
            "time": SimpleNamespace(monotonic=lambda: 100),
            "started": 0,
            "args": SimpleNamespace(baseline_seconds=60),
        },
    )
    activity = iter([True, False] * 8)
    lab.diagnostic_reads(
        args(diagnostic_case="natural-transitions", diagnostic_order="original"),
        threading.Event(),
        PRIVATE,
        rows.append,
        phase=phase,
        worker_state=lambda: next(activity),
    )
    assert len(calls) == len(rows) == 8
    assert [row["status"] for row in rows] == [200, 304, 200, 304] * 2
    assert [etag for _, etag, _ in calls[::2]] == [None] * 4
    assert all(row["phase"] == "refresh" for row in rows)
    assert all(
        row["workerActiveBefore"] is True and row["workerActiveAfter"] is False for row in rows
    )
    assert all(row["completionObservedMonotonicSeconds"] > 0 for row in rows)
    assert len(connections) == 1 and connections[0].closed == 1


@pytest.mark.parametrize(
    "before,after,reload,elapsed,expected",
    [
        (False, False, False, 59, "baseline"),
        (True, False, False, 60, "refresh"),
        (False, True, False, 60, "refresh"),
        (False, False, True, 60, "refresh"),
        (False, False, False, 60, "postRefreshIdle"),
    ],
)
def test_actual_diagnostic_phase_uses_both_request_boundaries(
    before, after, reload, elapsed, expected
):
    phase = nested_driver_function(
        "diagnostic_phase",
        {
            "time": SimpleNamespace(monotonic=lambda: elapsed),
            "started": 0,
            "args": SimpleNamespace(baseline_seconds=60),
        },
    )
    assert (
        phase(
            SimpleNamespace(headers={"x-soak-reload-active": "1" if reload else "0"}), before, after
        )
        == expected
    )


@pytest.mark.parametrize(
    "changed_board,changed_bytes", [(False, False), (False, True), (True, True)]
)
def test_adoption_tokens_distinguish_same_board_byte_change_without_exposing_identity(
    changed_board, changed_bytes
):
    from scripts.serving_lab_spans import adoption_identity

    old_etag, old_board = "a" * 40, "b" * 64
    new_etag = "c" * 40 if changed_bytes else old_etag
    new_board = "d" * 64 if changed_board else old_board
    tokens = lab.diagnostic_request_tokens(
        (old_etag, old_board),
        SimpleNamespace(
            headers={
                "etag": '"' + new_etag + '"',
                "x-data-generation": new_board,
                "set-cookie": PRIVATE,
            }
        ),
    )
    assert tokens["requestedEtagToken"] == adoption_identity(old_etag)
    assert tokens["returnedEtagToken"] == adoption_identity(new_etag)
    assert tokens["conditionalRepresentationChanged"] is changed_bytes
    assert tokens["conditionalCanonicalChanged"] is changed_board
    serialized = json.dumps(tokens)
    assert PRIVATE not in serialized and old_etag not in serialized and old_board not in serialized


@pytest.mark.parametrize("failed", [False, True])
def test_actual_diagnostic_emit_excludes_raw_identity_and_keeps_completion(failed):
    emitted = []
    namespace = {
        "diagnostic_output": SimpleNamespace(emit=emitted.append),
        "last_http_completion": [None],
        "started": 100,
        "read_error_counts": Counter(),
        "response_counts": Counter(),
        "latencies": {"refresh": []},
        "read_series": {},
        "observed_generations": Counter(),
    }
    emit = nested_driver_function("diagnostic_emit", namespace)
    row = {
        "generation": PRIVATE,
        "completionObservedMonotonicSeconds": 102.125,
        "phase": "refresh",
        "route": "rankings",
        "kind": "conditional",
        "status": 200,
        "elapsedMs": 3,
    }
    if failed:
        row["failureType"] = "TimeoutError"
    emit(row)
    assert PRIVATE not in json.dumps(emitted)
    assert row["generation"] == PRIVATE  # Do not mutate the input audit result.
    assert namespace["last_http_completion"] == [2.125]
    assert namespace["latencies"]["refresh"] == ([] if failed else [3])
    assert namespace["read_error_counts"]["TimeoutError"] == int(failed)


@pytest.mark.parametrize("failure", [False, True])
def test_actual_natural_finally_attempts_closing_clock_and_closes_output(failure):
    tree = ast.parse(Path(lab.__file__).read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    closing = next(
        node
        for node in ast.walk(main)
        if isinstance(node, ast.If)
        and ast.unparse(node.test) == "diagnostic_output"
        and any(
            isinstance(child, ast.Assign)
            and ast.unparse(child.targets[0]) == "diagnostic_clock_end"
            for child in ast.walk(node)
        )
    )
    calls, errors = [], []

    def exchange(state):
        calls.append("clock")
        if failure:
            raise TimeoutError(PRIVATE)
        return {"comparable": True}

    namespace = {
        "diagnostic_output": SimpleNamespace(
            close=lambda: calls.append("close"),
            collection_report=lambda: {"complete": True, "dropped": 0},
        ),
        "diagnostic_clock_end": None,
        "exchange_clocks": exchange,
        "state": object(),
        "errors": errors,
    }
    exec(compile(ast.Module(body=[closing], type_ignores=[]), "<closing-clock>", "exec"), namespace)
    assert calls == ["clock", "close"]
    assert errors == (["diagnostic_closing_clock_TimeoutError"] if failure else [])
    assert namespace["diagnostic_clock_end"] == (None if failure else {"comparable": True})
    assert PRIVATE not in json.dumps(errors)


@pytest.mark.parametrize("failure", ["writer", "web", "collection", "web_nonzero", "healthy"])
def test_actual_quiet_finally_preserves_failed_report_after_cleanup_failure(
    monkeypatch, tmp_path, failure
):
    calls = []

    class Web:
        returncode = None
        killed = False

        def poll(self):
            return self.returncode

        def communicate(self, **kwargs):
            calls.append("web_communicate")
            if failure == "web" and not self.killed:
                raise subprocess.TimeoutExpired("fixture", kwargs["timeout"])
            self.returncode = -9 if self.killed else 3 if failure == "web_nonzero" else 0

        def terminate(self):
            calls.append("web_terminate")

        def kill(self):
            calls.append("web_kill")
            self.killed = True
            self.returncode = -9

    def close():
        calls.append("output_close")
        if failure == "writer":
            raise RuntimeError(PRIVATE)

    contract, raw_path = tmp_path / "contract.json", tmp_path / "raw.json"
    contract.write_text("{}")
    raw_path.write_text("{}")
    options = args(
        root=tmp_path / "store",
        contract=contract,
        output=tmp_path / "failed-quiet.json",
        diagnostic_collector="off",
        diagnostic_asgi=False,
        child_ledger=SimpleNamespace(remaining=lambda *a: {"remainingCount": 0, "unknownCount": 0}),
    )
    tree = ast.parse(Path(lab.__file__).read_text(encoding="utf-8"))
    controller = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "diagnostic_quiet_run"
    )
    finalization = next(
        node
        for node in controller.body
        if isinstance(node, ast.Try)
        and any(
            isinstance(item, ast.Call) and ast.unparse(item.func) == "monitor_stop.set"
            for item in ast.walk(ast.Module(body=node.finalbody, type_ignores=[]))
        )
    )
    extracted = ast.parse("def run_finalization():\n    pass\n").body[0]
    extracted.body = [
        ast.Try(body=[ast.Pass()], handlers=[], orelse=[], finalbody=finalization.finalbody),
        *controller.body[controller.body.index(finalization) + 1 :],
    ]
    web = Web()
    namespace = {
        **vars(lab),
        "monitor_stop": SimpleNamespace(set=lambda: calls.append("monitor_stop")),
        "watcher": SimpleNamespace(
            ident=1,
            join=lambda **k: calls.append("watcher_join"),
            is_alive=lambda: False,
        ),
        "web_child": web,
        "state": SimpleNamespace(
            stop=lambda: calls.append("reader_stop") or True,
            control=lambda *a: calls.append("web_shutdown"),
        ),
        "output": SimpleNamespace(
            close=close,
            dropped=0,
            collection_report=lambda: {
                "complete": failure not in {"writer", "collection"},
                "dropped": 0,
            },
        ),
        "errors": [],
        "checks": [
            {"atNs": 0, "valid": True},
            {"atNs": 1_000_000_000, "valid": True},
        ],
        "cells": [],
        "clock_start": {"comparable": True},
        "clock_end": {"comparable": True},
        "quiet_start": 0,
        "quiet_end": 1_000_000_000,
        "provenance": {},
        "code_provenance": lambda *a, **k: {},
        "args": options,
        "raw_path": raw_path,
        "process": object(),
        "read_failures": Counter(),
        "socket_reads_dropped": 0,
    }
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[extracted], type_ignores=[])),
            "<quiet-finally-report>",
            "exec",
        ),
        namespace,
    )
    assert namespace["run_finalization"]() == (0 if failure == "healthy" else 1)
    report = json.loads(options.output.read_text())
    assert bool(report["errors"]) is (failure != "healthy")
    assert report["officialAcceptance"] is False
    assert web.poll() is not None
    assert {"monitor_stop", "watcher_join", "reader_stop", "output_close"} <= set(calls)
    if failure == "web":
        assert "web_kill" in calls
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize(
    "footer,complete",
    [
        ({"event": "collection", "dropped": 0, "adoption": {"complete": True}}, True),
        ({"event": "collection", "dropped": 1, "adoption": {"complete": True}}, False),
        ({"event": "collection", "dropped": 0, "adoption": {"complete": False}}, False),
        ({"event": "collection", "dropped": 0}, False),
        ({"event": "span", "dropped": 0}, False),
    ],
)
def test_adoption_collection_footer_requires_lossless_complete_evidence(tmp_path, footer, complete):
    root = tmp_path / "store"
    footer = {
        "emitted": 3,
        "written": 3,
        "completionBoundary": "footer_before_flush_and_close",
        **footer,
    }
    root.with_name(root.name + ".spans.jsonl").write_text(json.dumps(footer) + "\n")
    assert (
        lab.diagnostic_collection_summary(
            args(root=root, diagnostic_collector="on", diagnostic_adoption=True), web_exit_code=0
        )["complete"]
        is complete
    )
    assert lab.diagnostic_collection_summary(
        args(root=root, diagnostic_collector="off", diagnostic_adoption=True)
    ) == {"enabled": False, "complete": None}


@pytest.mark.parametrize("exit_code", [0, 3, None, False, 0.0, "0"])
def test_real_writer_footer_requires_independently_known_integer_zero_web_exit(tmp_path, exit_code):
    from scripts.serving_lab_spans import LabSpans

    root = tmp_path / "store"
    trace = LabSpans(root.with_name(root.name + ".spans.jsonl"))
    trace.emit({"event": "fixture"})
    trace.close()
    assert trace.collection_report()["complete"] is True
    report = lab.diagnostic_collection_summary(
        args(root=root, diagnostic_collector="on"), web_exit_code=exit_code
    )
    assert report["footerCompleteBeforeFlushAndClose"] is True
    assert report["complete"] is (type(exit_code) is int and exit_code == 0)
    assert report["webExitCode"] == (exit_code if type(exit_code) is int else None)
    assert report["completionBoundary"] == "valid_footer_plus_known_zero_web_exit_after_close"


@pytest.mark.parametrize(
    "mutation",
    [
        {"written": 2},
        {"emitted": -1, "written": -1},
        {"emitted": True, "written": True},
        {"dropped": False},
        {"dropped": 1},
        {"completionBoundary": "unproven_boundary"},
    ],
)
def test_zero_web_exit_cannot_qualify_missing_or_false_footer_conservation(tmp_path, mutation):
    root = tmp_path / "store"
    footer = {
        "event": "collection",
        "emitted": 3,
        "written": 3,
        "dropped": 0,
        "completionBoundary": "footer_before_flush_and_close",
        **mutation,
    }
    root.with_name(root.name + ".spans.jsonl").write_text(json.dumps(footer) + "\n")
    report = lab.diagnostic_collection_summary(
        args(root=root, diagnostic_collector="on"), web_exit_code=0
    )
    assert not report["complete"] and not report["footerCompleteBeforeFlushAndClose"]


def stale_control_fixture(
    monkeypatch,
    tmp_path,
    *,
    corrupt_wire=None,
    fail_first=False,
    close_fails=False,
    remaining=0,
    unknown=0,
    web_exit_code=0,
    collector="off",
):
    from src.serving import producer_status

    # This controller fixture supplies ledger outcomes, not OS resource samples.
    # Keep its identity seam explicit without requiring the optional lab psutil.
    process_identity = object()
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=lambda: process_identity))
    generation = [0]
    exchanges, clocks, queued = [], [], []

    def close():
        exchanges.append({"closed": True})
        if close_fails:
            raise OSError(PRIVATE)

    connection = SimpleNamespace(close=close)
    monkeypatch.setattr(
        lab.threading,
        "Event",
        lambda: SimpleNamespace(
            wait=lambda seconds: exchanges.append({"pacingSeconds": seconds}) or False
        ),
    )
    monkeypatch.setattr(lab, "DiagnosticConnection", lambda *a: connection)
    monkeypatch.setattr(lab, "store_for", lambda *a: SimpleNamespace(root=tmp_path / "store"))
    monkeypatch.setattr(lab, "code_provenance", lambda *a, **k: {})
    monkeypatch.setattr(
        producer_status, "request_source_refresh", lambda *a: queued.append("source")
    )
    monkeypatch.setattr(
        producer_status, "request_league_refresh", lambda *a: queued.append("league")
    )

    def launch(options, kind, revision):
        generation[0] = revision
        return SimpleNamespace(poll=lambda: 0)

    monkeypatch.setattr(lab, "launch", launch)
    monkeypatch.setattr(
        lab,
        "finish_worker",
        lambda *a, **k: {
            "exitCode": 0,
            "receiptError": None,
            "receipt": {"leagueOutcome": "success"},
        },
    )

    def exchange_clock(state):
        clocks.append("clock")
        return {"comparable": True}

    monkeypatch.setattr(lab, "exchange_clocks", exchange_clock)

    def exchange(connection, path, *, etag=None, **kwargs):
        if fail_first:
            raise TimeoutError(PRIVATE)
        view = "trade" if path.endswith("context") else "rankings"
        candidate = response(view, f"{generation[0]:064x}")
        current_conditional = etag == candidate.headers["etag"]
        item = response(view, f"{generation[0]:064x}", conditional=current_conditional)
        if generation[0] and etag and not current_conditional and corrupt_wire:
            raw = gzip.decompress(item.body)
            if corrupt_wire == "gzip":
                item.body = gzip.compress(
                    raw, mtime=1
                )  # Same decoded body/ETag, different wire bytes.
            elif corrupt_wire == "encoding":
                item.body = raw
                item.headers["content-encoding"] = "identity"
            elif corrupt_wire == "length":
                item.headers["content-length"] = str(len(item.body) + 1)
            if corrupt_wire != "length":
                item.headers["content-length"] = str(len(item.body))
        exchanges.append(
            {
                "revision": generation[0],
                "route": view,
                "requested": etag,
                "status": item.status_code,
                "bodyBytes": len(item.body),
            }
        )
        return item, {"requestStartNs": 100, "bodyCompleteNs": 200}

    monkeypatch.setattr(lab, "diagnostic_response", exchange)
    contract, raw = tmp_path / "contract.json", tmp_path / "raw.json"
    contract.write_text("{}")
    raw.write_text("{}")
    options = args(
        root=tmp_path / "store",
        budget_bytes=1024,
        contract=contract,
        output=tmp_path / "report.json",
        diagnostic_collector="off",
        diagnostic_adoption=True,
        child_ledger=SimpleNamespace(
            remaining=lambda *a: {"remainingCount": remaining, "unknownCount": unknown}
        ),
    )
    options.diagnostic_collector = collector
    if collector == "on":
        options.root.with_name(options.root.name + ".spans.jsonl").write_text(
            json.dumps(
                {
                    "event": "collection",
                    "emitted": 3,
                    "written": 3,
                    "dropped": 0,
                    "completionBoundary": "footer_before_flush_and_close",
                    "adoption": {"complete": True},
                }
            )
            + "\n"
        )
        monkeypatch.setattr(
            lab,
            "exchange_clocks",
            lambda state: clocks.append("clock")
            or {"comparable": True, "adoption": {"complete": True}},
        )
    state = SimpleNamespace(control=lambda *a, **k: {"result": {"ready": True}})
    web = SimpleNamespace(
        communicate=lambda **k: None,
        poll=lambda: web_exit_code,
        terminate=lambda: None,
        kill=lambda: None,
    )
    result = lab.diagnostic_stale_etag_run(options, state, web, PRIVATE, raw, {})
    return result, json.loads(options.output.read_text()), exchanges, clocks, queued


def test_stale_etag_control_requires_current_b_304_with_no_body(monkeypatch, tmp_path):
    result, report, exchanges, clocks, queued = stale_control_fixture(monkeypatch, tmp_path)
    assert result == 0 and report["diagnosticComplete"] is True
    assert report["acceptedBGenerations"] == 3 and len(report["rows"]) == 120
    current = [row for row in exchanges if row.get("revision", 0) > 0 and row.get("status") == 304]
    assert {(row["revision"], row["route"]) for row in current} == {
        (revision, route) for revision in range(1, 4) for route in ("rankings", "trade")
    }
    assert all(row["bodyBytes"] == 0 for row in current)
    assert len(clocks) == 2 and queued == ["source", "league"] * 3
    assert report["acceptanceClaim"] is False


def test_stale_etag_control_retains_event_pacing_for_each_four_request_cycle(monkeypatch, tmp_path):
    result, _, exchanges, _, _ = stale_control_fixture(monkeypatch, tmp_path)
    assert result == 0
    assert [row["pacingSeconds"] for row in exchanges if "pacingSeconds" in row] == [0.01] * 30


@pytest.mark.parametrize("remaining,unknown", [(1, 0), (0, 1)])
def test_stale_etag_observed_children_or_unknown_identity_veto_completion(
    monkeypatch, tmp_path, remaining, unknown
):
    result, report, _, _, _ = stale_control_fixture(
        monkeypatch, tmp_path, remaining=remaining, unknown=unknown
    )
    assert result == 1 and report["diagnosticComplete"] is False
    assert report["checks"]["noRemainingObservedChildren"] is False
    assert report["remainingChildren"] == {"remainingCount": remaining, "unknownCount": unknown}


@pytest.mark.parametrize("web_exit_code", [0, 3, None])
def test_actual_stale_controller_requires_known_zero_web_exit_after_valid_footer(
    monkeypatch, tmp_path, web_exit_code
):
    result, report, _, _, _ = stale_control_fixture(
        monkeypatch, tmp_path, web_exit_code=web_exit_code, collector="on"
    )
    assert report["serverCollection"]["footerCompleteBeforeFlushAndClose"] is True
    assert report["serverCollection"]["complete"] is (web_exit_code == 0)
    assert report["webExitCode"] == web_exit_code
    assert result == (0 if web_exit_code == 0 else 1)
    assert report["diagnosticComplete"] is (web_exit_code == 0)


def test_stale_etag_connection_close_failure_preserves_report_and_web_cleanup(
    monkeypatch, tmp_path
):
    result, report, exchanges, clocks, _ = stale_control_fixture(
        monkeypatch, tmp_path, close_fails=True
    )
    assert result == 1 and report["diagnosticComplete"] is False and report["errors"]
    assert len(clocks) == 2 and exchanges[-1] == {"closed": True}
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize("corrupt_wire", ["gzip", "encoding", "length"])
def test_stale_etag_paired_200_requires_identical_wire_body_encoding_and_length(
    monkeypatch, tmp_path, corrupt_wire
):
    result, report, _, clocks, _ = stale_control_fixture(
        monkeypatch, tmp_path, corrupt_wire=corrupt_wire
    )
    assert result == 1 and report["diagnosticComplete"] is False
    assert report["errors"] and len(clocks) == 2
    assert report["acceptanceClaim"] is False
    assert PRIVATE not in json.dumps(report)


def test_stale_etag_failure_still_captures_closing_clock_and_sanitizes_error(monkeypatch, tmp_path):
    result, report, exchanges, clocks, _ = stale_control_fixture(
        monkeypatch, tmp_path, fail_first=True
    )
    assert result == 1 and report["errors"] == ["TimeoutError"]
    assert len(clocks) == 2 and exchanges == [{"closed": True}]
    assert report["clockEnd"] == {"comparable": True}
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize(
    "change",
    [
        [],
        ["--duration-seconds", "899"],
        ["--baseline-seconds", "59"],
        ["--refresh-seconds", "29"],
        ["--quiet-seconds", "124"],
        ["--drain-timeout-seconds", "299"],
        ["--diagnostic-order", "balanced"],
        ["--diagnostic-pacing", "continuous"],
        ["--diagnostic-connection", "new"],
        ["--diagnostic-body-read", "split"],
    ],
)
def test_natural_transition_cli_rejects_changed_protocol_before_startup(tmp_path, change):
    options = [
        "--diagnostic-spans",
        "--diagnostic-timeline",
        "--diagnostic-case",
        "natural-transitions",
        "--duration-seconds",
        "900",
        "--baseline-seconds",
        "60",
    ]
    if change:
        options += ["--diagnostic-adoption", *change]
    result = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts/soak_prepared_serving.py"),
            "--root",
            str(tmp_path / "unused"),
            *options,
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 2
    assert ("natural transitions require" if change else "adoption cases require") in result.stderr
    assert not (tmp_path / "unused").exists()


@pytest.mark.parametrize("missing", [None, "coverage", "gap", "quiet"])
def test_full_duration_qualification_is_not_all_gate_acceptance(missing):
    tree = ast.parse(Path(lab.__file__).read_text(encoding="utf-8"))
    main = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    qualification = next(
        node
        for node in main.body
        if isinstance(node, ast.Assign)
        and ast.unparse(node.targets[0]) == "report['full60MinuteSoak']"
    )
    final_pass = next(
        node
        for node in main.body
        if isinstance(node, ast.Assign) and ast.unparse(node.targets[0]) == "report['passed']"
    )
    gap = 3 if missing == "gap" else 1
    report = {
        "servingExerciseSeconds": 3600,
        "maxObservationSampleGapSeconds": gap,
        "checks": {
            "completeResourceCoverageAtLeast99Percent": missing != "coverage",
            "noIncorrectResponsesOrUnexpectedFailures": False,
            **lab.sampling_evidence(3600, 3600, gap),
        },
    }
    namespace = {
        "args": SimpleNamespace(diagnostic_spans=False, baseline_seconds=600, quiet_seconds=125),
        "report": report,
        "quiet_report": {"verified": missing != "quiet"},
        "observed_sample_count": 3600,
        "observation_seconds": 3600,
        "sampling_evidence": lab.sampling_evidence,
    }
    exec(
        compile(
            ast.Module(body=[qualification, final_pass], type_ignores=[]),
            "<duration-qualification>",
            "exec",
        ),
        namespace,
    )
    assert report["full60MinuteSoak"] is (missing is None)
    assert (
        report["passed"] is False
    )  # A full-duration qualifier cannot hide a failed response gate.
