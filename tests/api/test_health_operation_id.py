"""OpenAPI operationIds are deterministic and unique (audit W00-F005).

``/api/health`` was one ``api_route(methods=["GET", "HEAD"])``.  FastAPI
derives a route's operationId from ``list(route.methods)[0]`` — the first
element of a SET of strings, whose iteration order follows PYTHONHASHSEED —
so the published id flipped between ``get_health_api_health_get`` and
``get_health_api_health_head`` from one process to the next (measured:
seeds 0-2 vs seed 3), and the GET and HEAD operations shared that one id
("Duplicate Operation ID" UserWarning on every schema build).

Uses ``app.openapi()`` rather than ``app.routes``: the routes view differs
across FastAPI versions (local vs CI), the published schema does not.
"""

from __future__ import annotations

from collections import Counter

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import server


def _operations() -> list[tuple[str, str, str]]:
    spec = server.app.openapi()
    return [
        (path, method, op.get("operationId"))
        for path, item in spec["paths"].items()
        for method, op in item.items()
        if isinstance(op, dict) and "operationId" in op
    ]


def test_every_operation_id_is_unique():
    counts = Counter(op_id for _p, _m, op_id in _operations())
    dupes = {op_id: n for op_id, n in counts.items() if n > 1}
    assert not dupes, f"duplicate OpenAPI operationIds: {dupes}"


def test_no_route_derives_its_id_from_set_order():
    """A multi-method APIRoute gets ONE id from an arbitrary member of its
    method set.  Register one route per method instead."""
    multi = sorted(
        (r.path, sorted(r.methods))
        for r in server.app.router.routes
        if isinstance(r, APIRoute) and len(r.methods) > 1
    )
    assert multi == [], f"multi-method routes (operationId depends on hash order): {multi}"


def test_health_get_and_head_have_stable_distinct_ids():
    ops = {(p, m): op_id for p, m, op_id in _operations()}
    assert ops[("/api/health", "get")] == "get_health_api_health_get"
    assert ops[("/api/health", "head")] == "head_health_api_health_head"


def test_head_still_answers_like_get():
    client = TestClient(server.app)
    get = client.get("/api/health")
    head = client.head("/api/health")
    assert head.status_code == get.status_code
    assert head.headers.get("content-type") == get.headers.get("content-type")
    assert head.content == b""
