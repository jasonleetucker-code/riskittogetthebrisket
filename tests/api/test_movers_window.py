"""Window honesty for ``GET /api/movers`` (2026-08-04 audit, H3b/H3c).

``load_history(days=window + 1)`` only TRIMS ``data/rank_history.jsonl``
— it cannot extend it.  The route used to anchor on ``series[0]`` (the
oldest point that happens to be on disk, ~2 days back today) and then
echo the REQUESTED ``window`` back in the response, so ``?window=90``
returned a two-day rank delta labelled 90 days.

Pinned here:

1. A log shallower than the request reports the span it actually
   measured, with the request preserved separately.
2. A log deep enough anchors on the newest point at or before
   ``asOf − window``, not on the oldest point on disk.
3. Equal-delta ties sort deterministically instead of falling through
   to JSONL key order.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import server
from src.api import rank_history


def _iso(d) -> str:
    return d.strftime("%Y-%m-%d")


@pytest.fixture
def movers_env(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_is_authenticated", lambda request: True)
    path = tmp_path / "rank_history.jsonl"
    path.write_text("", encoding="utf-8")
    monkeypatch.setattr(rank_history, "HISTORY_PATH", path)
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": []})
    return path


def _write_history(path, snapshots):
    """``snapshots`` = [(date, {"Name::asset": rank})] — written verbatim."""
    with path.open("w", encoding="utf-8") as f:
        for date, ranks in snapshots:
            f.write(json.dumps({"date": date, "ranks": ranks}) + "\n")


def test_shallow_history_reports_measured_span_not_requested_window(movers_env):
    """A 2-day-deep log asked for 90 days must not answer "window": 90."""
    today = datetime.now(timezone.utc).date()
    _write_history(
        movers_env,
        [
            (_iso(today - timedelta(days=2)), {"Riser::offense": 80}),
            (_iso(today), {"Riser::offense": 30}),
        ],
    )

    with TestClient(server.app) as client:
        body = client.get("/api/movers?window=90&threshold=15").json()

    assert body["window"] == 2  # the span that actually exists on disk
    assert body["windowRequested"] == 90
    assert body["historyDepthDays"] == 2
    assert body["asOf"] == _iso(today)
    riser = next(r for r in body["risers"] if r["name"] == "Riser")
    assert riser["delta"] == 50  # 80 → 30
    assert riser["spanDays"] == 2
    assert riser["rankThenDate"] == _iso(today - timedelta(days=2))
    assert riser["rankNowDate"] == _iso(today)


def test_anchor_resolves_by_date_not_by_oldest_point_on_disk(movers_env):
    """With a gappy log the anchor is the newest point ≤ cutoff.

    Snapshots at 60/30/9/6/3/0 days ago.  ``load_history(days=8)`` trims
    by COUNT, so all six survive and ``series[0]`` is the 60-day-old
    point — the pre-fix anchor, giving ``rankThen = 200`` and a delta of
    160 labelled "7 days".  Anchoring by date picks the 9-days-ago
    snapshot (the newest at or before ``today − 7``): rankThen = 60,
    delta = 60 − 40 = 20 over a real 9-day span.
    """
    today = datetime.now(timezone.utc).date()
    _write_history(
        movers_env,
        [
            (_iso(today - timedelta(days=60)), {"Riser::offense": 200}),
            (_iso(today - timedelta(days=30)), {"Riser::offense": 100}),
            (_iso(today - timedelta(days=9)), {"Riser::offense": 60}),
            (_iso(today - timedelta(days=6)), {"Riser::offense": 50}),
            (_iso(today - timedelta(days=3)), {"Riser::offense": 45}),
            (_iso(today), {"Riser::offense": 40}),
        ],
    )

    with TestClient(server.app) as client:
        body = client.get("/api/movers?window=7&threshold=15").json()

    riser = next(r for r in body["risers"] if r["name"] == "Riser")
    assert riser["rankThen"] == 60
    assert riser["rankNow"] == 40
    assert riser["delta"] == 20
    assert riser["rankThenDate"] == _iso(today - timedelta(days=9))
    assert riser["spanDays"] == 9
    # The nearest usable anchor sits 9 days back, so 9 — not 7 — is the
    # window this answer was actually measured over.
    assert body["windowRequested"] == 7
    assert body["window"] == 9
    assert body["historyDepthDays"] == 60


def test_equal_delta_ties_sort_deterministically(movers_env):
    """Ties used to fall through to ``ranks`` dict insertion order.

    ``Zed`` is stamped first in every snapshot and both players move
    exactly 40 spots with no contract row (so ``valueNow`` is None for
    both) — the only remaining tiebreak is the name.
    """
    today = datetime.now(timezone.utc).date()
    _write_history(
        movers_env,
        [
            (_iso(today - timedelta(days=2)), {"Zed::offense": 90, "Abe::offense": 90}),
            (_iso(today), {"Zed::offense": 50, "Abe::offense": 50}),
        ],
    )

    with TestClient(server.app) as client:
        body = client.get("/api/movers?window=2&threshold=15").json()

    assert [r["name"] for r in body["risers"]] == ["Abe", "Zed"]
    assert {r["delta"] for r in body["risers"]} == {40}


def test_empty_history_reports_zero_measured_window(movers_env):
    with TestClient(server.app) as client:
        body = client.get("/api/movers?window=90").json()

    assert body["window"] == 0
    assert body["windowRequested"] == 90
    assert body["historyDepthDays"] == 0
    assert body["risers"] == []
    assert body["fallers"] == []


def test_history_depth_reports_the_log_not_the_trimmed_slice(movers_env):
    """``historyDepthDays`` must be able to say "the log is DEEPER than
    you asked".

    Adversarial review of the H3 fix (math audit).  The first version
    derived depth from ``history`` — which is
    ``load_history(days=window + 1)``, a COUNT slice — so it equalled
    ``min(true_depth, window)`` by construction and could only ever
    report the window back.  That reads correctly on the live log purely
    because the live log is shallower than any window, which is the same
    accident the whole finding was filed against.

    Here the log spans 60 days and the caller asks for 7.  Depth must
    report 60; the window must still report the 9-day span it actually
    measured.
    """
    today = datetime.now(timezone.utc).date()
    _write_history(
        movers_env,
        [
            (_iso(today - timedelta(days=60)), {"Riser::offense": 200}),
            (_iso(today - timedelta(days=9)), {"Riser::offense": 60}),
            (_iso(today), {"Riser::offense": 40}),
        ],
    )
    with TestClient(server.app) as client:
        body = client.get("/api/movers?window=7&threshold=1").json()

    # Hand-computed: oldest snapshot is 60 days before the newest.
    assert body["historyDepthDays"] == 60
    assert body["windowRequested"] == 7
    # The anchor is still the newest snapshot at or before today−7, i.e.
    # the 9-day-old one — depth and window answer different questions.
    assert body["window"] == 9
