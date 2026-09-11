"""Diagnostic hooks preserve semantics and do not serialize sensitive arguments."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from scripts.serving_lab_spans import LabSpans


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
