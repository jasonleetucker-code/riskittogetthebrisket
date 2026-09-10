import asyncio
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.api import telemetry


def test_browser_metric_rejects_private_paths_and_unbounded_values():
    valid = dict(name="LCP", value=123, id="nav-1", route="/rankings")
    telemetry.WebVital(**valid)
    for extra in (
        {"route": "/players/private-id"},
        {"value": float("nan")},
        {"query": "secret"},
        {"value": -1},
    ):
        with pytest.raises(ValidationError):
            telemetry.WebVital(**{**valid, **extra})


def test_aggregation_has_no_user_or_navigation_identity():
    telemetry.reset()
    for ident in ("one", "two"):
        telemetry.record_vital(telemetry.WebVital(name="INP", value=10, id=ident, route="/trade"))
    report = telemetry.snapshot()
    assert len(report["series"]) == 1
    assert report["series"][0]["count"] == 2
    assert "one" not in json.dumps(report)


def test_middleware_streams_and_does_not_label_raw_urls():
    telemetry.reset()
    messages = []

    async def app(scope, receive, send):
        await send({"type": "http.response.start", "status": 404, "headers": []})
        await send({"type": "http.response.body", "body": b"abc", "more_body": True})
        await send({"type": "http.response.body", "body": b"def"})

    async def capture(message):
        messages.append(message)

    asyncio.run(
        telemetry.PerformanceMiddleware(app)(
            {"type": "http", "method": "GET", "path": "/secret-user-123", "headers": []},
            None,
            capture,
        )
    )
    assert len(messages) == 3
    headers = dict(messages[0]["headers"])
    assert b"server-timing" in headers and len(headers[b"x-trace-id"]) == 32
    report = telemetry.snapshot()
    assert report["series"][0]["bytes"] == 6
    assert "secret-user" not in json.dumps(report)


def test_counter_memory_is_bounded():
    telemetry.reset()
    for i in range(telemetry._MAX_SERIES + 10):
        telemetry.cache_event(str(i), True)
    assert len(telemetry.snapshot()["series"]) == telemetry._MAX_SERIES


def test_every_frontend_route_template_is_accepted():
    source = (Path(__file__).resolve().parents[2] / "frontend/lib/web-vitals-report.js").read_text()
    routes = set(re.findall(r'"(/[A-Za-z0-9_\[\]/-]*)"', source))
    assert len(routes) > 20
    assert routes <= telemetry._PAGE_ROUTES


def test_cls_buckets_distinguish_good_from_poor_layout_shift():
    telemetry.reset()
    for value in (0.01, 0.2, 0.4):
        telemetry.record_vital(
            telemetry.WebVital(name="CLS", value=value, id="test", route="/trade")
        )
    metric = telemetry.snapshot()["series"][0]
    assert metric["unit"] == "score"
    assert sum(value > 0 for value in metric["buckets"]) == 3
