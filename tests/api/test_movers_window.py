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


def _league(key: str, sleeper_id: str) -> dict:
    return {
        "key": key,
        "displayName": key.title(),
        "sleeperLeagueId": sleeper_id,
        "scoringProfile": "superflex_tep15_ppr1",
        "active": True,
        "rosterSettings": {"teamCount": 12, "rosterSize": 30, "starters": {"QB": 1, "RB": 2}},
    }


@pytest.fixture
def movers_env(tmp_path, monkeypatch):
    """A one-league-loaded server.

    Movers resolve the requested league and follow the board's
    scoring-identity gate (LI1842-DEFECT-03), exactly as ``/api/data`` does:
    that needs a registry, and a served contract stamped with the league it
    was built for (an unstamped one is unproven and refused).  ``alpha`` is
    the default and the loaded league; ``beta`` is registered but has no
    scoring snapshot, so its scoring is unproven.
    """
    from src.api import league_registry

    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "defaultLeagueKey": "alpha",
                "leagues": [_league("alpha", "L-ALPHA"), _league("beta", "L-BETA")],
            }
        ),
        encoding="utf-8",
    )
    with monkeypatch.context() as m:
        m.setenv("LEAGUE_REGISTRY_PATH", str(registry))
        m.setenv("LEAGUE_SCORING_SNAPSHOT_DIR", str(tmp_path / "cards"))
        league_registry.reload_registry()
        m.setattr(server, "_is_authenticated", lambda request: True)
        path = tmp_path / "rank_history.jsonl"
        path.write_text("", encoding="utf-8")
        m.setattr(rank_history, "HISTORY_PATH", path)
        m.setattr(
            server,
            "latest_contract_data",
            {"meta": {"leagueKey": "alpha"}, "playersArray": []},
        )
        yield path
    league_registry.reload_registry()


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


# ── league scoping (LI1842-DEFECT-03) ───────────────────────────────────────


def _two_day_riser(path) -> None:
    today = datetime.now(timezone.utc).date()
    _write_history(
        path,
        [
            (_iso(today - timedelta(days=2)), {"Riser::offense": 80}),
            (_iso(today), {"Riser::offense": 30}),
        ],
    )


def test_the_loaded_leagues_own_request_is_served_unchanged(movers_env):
    """The explicit key of the league the board was built for, and the
    implicit default, both answer 200 with the same movers."""
    _two_day_riser(movers_env)
    with TestClient(server.app) as client:
        implicit = client.get("/api/movers?window=2&threshold=15")
        explicit = client.get("/api/movers?window=2&threshold=15&leagueKey=alpha")
    assert implicit.status_code == explicit.status_code == 200
    assert implicit.json() == explicit.json()
    assert [r["name"] for r in implicit.json()["risers"]] == ["Riser"]


def test_a_league_whose_scoring_is_unproven_gets_the_boards_503_not_its_movers(movers_env):
    """``/api/data`` refuses the loaded board for ``beta`` (no scoring snapshot,
    so identity is unproven); the movers ARE that board's rank movement and
    must not be served under ``beta``'s name."""
    _two_day_riser(movers_env)
    with TestClient(server.app) as client:
        board = client.get("/api/data?leagueKey=beta")
        movers = client.get("/api/movers?window=2&threshold=15&leagueKey=beta")
    assert board.status_code == 503
    assert movers.status_code == 503
    body = movers.json()
    assert body["error"] == "data_not_ready"
    assert body["leagueKey"] == "beta"
    assert "risers" not in body and "fallers" not in body


def test_an_unknown_league_key_is_a_400_like_every_league_route(movers_env):
    _two_day_riser(movers_env)
    with TestClient(server.app) as client:
        res = client.get("/api/movers?window=2&threshold=15&leagueKey=not_a_league")
    assert res.status_code == 400
    assert res.json()["error"] == "unknown_league"
