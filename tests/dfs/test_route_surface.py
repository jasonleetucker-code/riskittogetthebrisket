"""The DFS API surface, pinned: an edit that drops (or adds) an endpoint must be deliberate.

Added after a refactor silently deleted two endpoints (``/evaluations`` and the
Daily Fantasy Fuel pull) that sat between the lines it replaced; only one of
them had an API test.  Changing the surface means changing this list.
"""

from __future__ import annotations

from src.dfs import api

EXPECTED = {
    "GET /api/dfs/auto/slates",
    "POST /api/dfs/auto/slates/select",
    "GET /api/dfs/builds",
    "GET /api/dfs/builds/{build_id}",
    "GET /api/dfs/builds/{build_id}/export",
    "GET /api/dfs/capabilities",
    "GET /api/dfs/contests",
    "GET /api/dfs/contests/{contest_id}",
    "GET /api/dfs/evaluations",
    "GET /api/dfs/jobs/{job_id}",
    "GET /api/dfs/presets",
    "GET /api/dfs/provider-slates",
    "GET /api/dfs/providers",
    "GET /api/dfs/results/{result_id}",
    "GET /api/dfs/slates/{snapshot_id}",
    "POST /api/dfs/backtest",
    "POST /api/dfs/builds",
    "POST /api/dfs/builds/{build_id}/export-entries",
    "POST /api/dfs/contests",
    "POST /api/dfs/contests/validate",
    "POST /api/dfs/contests/{contest_id}/entry-cap",
    "POST /api/dfs/entries/parse",
    "POST /api/dfs/jobs",
    "POST /api/dfs/late-swap",
    "POST /api/dfs/late-swap/export",
    "POST /api/dfs/ownership/forecast",
    "POST /api/dfs/portfolio",
    "POST /api/dfs/provider-slates/import",
    "POST /api/dfs/results",
    "POST /api/dfs/simulate",
    "POST /api/dfs/slates",
    "POST /api/dfs/slates/detect",
    "POST /api/dfs/sources/dailyfantasyfuel/pull",
}


def test_dfs_route_surface_is_exactly_the_expected_set():
    actual = {f"{m} {r.path}" for r in api.router.routes for m in r.methods if m != "HEAD"}
    assert actual == EXPECTED, {
        "missing": sorted(EXPECTED - actual),
        "unexpected": sorted(actual - EXPECTED),
    }
