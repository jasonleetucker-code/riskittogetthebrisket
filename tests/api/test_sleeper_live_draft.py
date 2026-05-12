"""Tests for the live Sleeper auction-draft sync helpers in
``src/api/sleeper_overlay.py`` — the polling path that backs
``/api/sleeper/draft/picks``.

These cover the three things that matter:

  1. Draft id auto-discovery picks the right draft when a league
     has multiple (current-season + status precedence).
  2. ``fetch_live_draft_picks`` normalizes Sleeper's raw pick
     shape into the compact contract the frontend hook consumes,
     including the ``metadata.amount`` → ``amount`` coercion
     (Sleeper stamps it as a string).
  3. The ``after_pick_no`` cursor filters correctly so the
     polling client only sees new picks.
"""
from __future__ import annotations

import pytest

from src.api import sleeper_overlay


@pytest.fixture(autouse=True)
def _clear_live_caches():
    """Fresh caches per test so the 60s draft-id memo and 2s picks
    memo don't leak fixtures between cases.
    """
    sleeper_overlay.invalidate_live_draft_cache()
    yield
    sleeper_overlay.invalidate_live_draft_cache()


def _stub_http(mapping):
    """Longest-suffix-match monkeypatch helper, same pattern as the
    overlay tests."""
    sorted_keys = sorted(mapping.keys(), key=len, reverse=True)

    def _resolve(url: str):
        for suffix in sorted_keys:
            if url.endswith(suffix):
                return mapping[suffix]
        return None
    return _resolve


# ── _resolve_active_draft_id ────────────────────────────────────────────


def test_resolve_active_draft_id_prefers_drafting_status(monkeypatch):
    """Of multiple current-season drafts, prefer status=drafting
    over pre_draft over complete."""
    import datetime as _dt
    cur = _dt.datetime.now(_dt.timezone.utc).year
    league_id = "L1"
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({
            f"/league/{league_id}/drafts": [
                {
                    "draft_id": "complete-prior",
                    "season": str(cur),
                    "sport": "nfl",
                    "status": "complete",
                    "start_time": 100,
                },
                {
                    "draft_id": "drafting-now",
                    "season": str(cur),
                    "sport": "nfl",
                    "status": "drafting",
                    "start_time": 200,
                },
                {
                    "draft_id": "pre-draft-soon",
                    "season": str(cur),
                    "sport": "nfl",
                    "status": "pre_draft",
                    "start_time": 300,
                },
            ],
        }),
    )
    assert sleeper_overlay._resolve_active_draft_id(league_id) == "drafting-now"


def test_resolve_active_draft_id_skips_off_season(monkeypatch):
    """Drafts from prior seasons must not be selected even if they
    sit at status complete (the most common stale-data case)."""
    import datetime as _dt
    cur = _dt.datetime.now(_dt.timezone.utc).year
    league_id = "L1"
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({
            f"/league/{league_id}/drafts": [
                {
                    "draft_id": "last-year",
                    "season": str(cur - 1),
                    "sport": "nfl",
                    "status": "complete",
                    "start_time": 50,
                },
            ],
        }),
    )
    assert sleeper_overlay._resolve_active_draft_id(league_id) is None


def test_resolve_active_draft_id_returns_none_on_empty(monkeypatch):
    """An empty /drafts response must return None, not raise — the
    route surfaces this as 404 ``no_active_draft``."""
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({"/league/L1/drafts": []}),
    )
    assert sleeper_overlay._resolve_active_draft_id("L1") is None


# ── _normalize_live_pick ────────────────────────────────────────────────


def test_normalize_live_pick_coerces_string_amount():
    """Sleeper stamps ``metadata.amount`` as a STRING for auction
    picks ("$23" or "23").  Normalizer must coerce to int."""
    row = sleeper_overlay._normalize_live_pick({
        "pick_no": 5,
        "player_id": "4046",
        "picked_by": "user-123",
        "roster_id": 7,
        "round": 1,
        "picked_at": 1715000000,
        "metadata": {"amount": "$23"},
    })
    assert row == {
        "pickNo": 5,
        "playerId": "4046",
        "amount": 23,
        "ownerId": "user-123",
        "rosterId": 7,
        "round": 1,
        "pickedAt": 1715000000,
    }


def test_normalize_live_pick_handles_snake_draft_no_amount():
    """Snake-draft picks have no ``metadata.amount`` — must default
    to 0 rather than failing the row."""
    row = sleeper_overlay._normalize_live_pick({
        "pick_no": 1,
        "player_id": "4046",
        "picked_by": "user-123",
        "roster_id": 1,
        "round": 1,
        "metadata": {},
    })
    assert row is not None
    assert row["amount"] == 0


def test_normalize_live_pick_skips_malformed():
    """Missing pick_no or player_id → return None (the row is
    dropped from the stream rather than poisoning the cursor)."""
    assert sleeper_overlay._normalize_live_pick({"player_id": "x"}) is None
    assert sleeper_overlay._normalize_live_pick({"pick_no": 1}) is None
    assert sleeper_overlay._normalize_live_pick({"pick_no": 0, "player_id": "x"}) is None


def test_normalize_live_pick_blank_picked_by():
    """Commish picks / co-managers can have empty picked_by — must
    produce an empty ownerId string (not None) so the JSON response
    has a consistent type."""
    row = sleeper_overlay._normalize_live_pick({
        "pick_no": 5,
        "player_id": "4046",
        "picked_by": None,
        "roster_id": 7,
        "metadata": {"amount": "10"},
    })
    assert row["ownerId"] == ""
    assert row["rosterId"] == 7


# ── fetch_live_draft_picks ──────────────────────────────────────────────


def _fixture_picks_response():
    """Two-pick auction-draft fixture in raw Sleeper shape."""
    return [
        {
            "pick_no": 1,
            "player_id": "4046",
            "picked_by": "user-A",
            "roster_id": 1,
            "round": 1,
            "metadata": {"amount": "23"},
        },
        {
            "pick_no": 2,
            "player_id": "5021",
            "picked_by": "user-B",
            "roster_id": 2,
            "round": 1,
            "metadata": {"amount": "$12"},
        },
    ]


def _fixture_drafts_response():
    import datetime as _dt
    cur = _dt.datetime.now(_dt.timezone.utc).year
    return [
        {
            "draft_id": "D1",
            "season": str(cur),
            "sport": "nfl",
            "status": "drafting",
            "start_time": 200,
        },
    ]


def test_fetch_live_draft_picks_full_snapshot(monkeypatch):
    """First poll with cursor=0 returns every pick, status from the
    draft meta endpoint, and a monotonic latestPickNo."""
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({
            "/league/L1/drafts": _fixture_drafts_response(),
            "/draft/D1": {"status": "drafting"},
            "/draft/D1/picks": _fixture_picks_response(),
        }),
    )
    snap = sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=0)
    assert snap is not None
    assert snap["draftId"] == "D1"
    assert snap["status"] == "drafting"
    assert snap["latestPickNo"] == 2
    assert len(snap["picks"]) == 2
    # First pick exactly matches the auction shape the frontend expects.
    assert snap["picks"][0]["playerId"] == "4046"
    assert snap["picks"][0]["amount"] == 23
    assert snap["picks"][0]["ownerId"] == "user-A"
    # Second pick has $-prefixed amount in the fixture — coerced.
    assert snap["picks"][1]["amount"] == 12


def test_fetch_live_draft_picks_cursor_filters(monkeypatch):
    """``after_pick_no`` filters server-side from the cached full
    snapshot.  Picks at or below the cursor are excluded."""
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({
            "/league/L1/drafts": _fixture_drafts_response(),
            "/draft/D1": {"status": "drafting"},
            "/draft/D1/picks": _fixture_picks_response(),
        }),
    )
    snap = sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=1)
    assert len(snap["picks"]) == 1
    assert snap["picks"][0]["pickNo"] == 2
    # latestPickNo is the full-snapshot max, not cursor-filtered.
    assert snap["latestPickNo"] == 2


def test_fetch_live_draft_picks_no_active_draft(monkeypatch):
    """When the league has no current-season draft, return None
    so the route can 404 cleanly."""
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({"/league/L1/drafts": []}),
    )
    assert sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=0) is None


def test_fetch_live_draft_picks_complete_status(monkeypatch):
    """A completed draft still serves its picks (useful for replay /
    review) and the status flag drives the frontend's auto-stop."""
    import datetime as _dt
    cur = _dt.datetime.now(_dt.timezone.utc).year
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({
            "/league/L1/drafts": [{
                "draft_id": "D1",
                "season": str(cur),
                "sport": "nfl",
                "status": "complete",
                "start_time": 100,
            }],
            "/draft/D1": {"status": "complete"},
            "/draft/D1/picks": _fixture_picks_response(),
        }),
    )
    snap = sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=0)
    assert snap["status"] == "complete"
    assert len(snap["picks"]) == 2


def test_fetch_live_draft_picks_cache_isolation(monkeypatch):
    """The live-draft 2s cache must be separate from the 15-minute
    overlay cache.  Specifically: invalidating the LIVE cache must
    not also wipe the team-overlay cache, and vice versa.  Earlier
    designs sharing a single dict caused the live polling loop to
    flush the overlay every 2s, which DDoS'd the team-overlay
    rebuild on every page load."""
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http({
            "/league/L1/drafts": _fixture_drafts_response(),
            "/draft/D1": {"status": "drafting"},
            "/draft/D1/picks": _fixture_picks_response(),
        }),
    )
    # Seed both caches.
    sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=0)
    # Manually seed an overlay cache entry to prove isolation.
    with sleeper_overlay._CACHE_LOCK:
        sleeper_overlay._CACHE["L1"] = {
            "payload": {"sentinel": True},
            "_cached_at": 9_999_999_999.0,
        }
    sleeper_overlay.invalidate_live_draft_cache("L1")
    with sleeper_overlay._CACHE_LOCK:
        assert "L1" in sleeper_overlay._CACHE  # overlay cache preserved
        assert "L1" not in sleeper_overlay._DRAFT_ID_CACHE  # live cache cleared


def test_fetch_live_draft_picks_caches_full_list_not_delta(monkeypatch):
    """A burst of polls with different cursors must reuse the same
    cached snapshot — Sleeper is hit at most once per
    ``_DRAFT_PICKS_CACHE_TTL_SEC`` regardless of cursor variance.
    This is the load-bearing safety property: 10 tabs polling at
    2.5s each must NOT result in 4 Sleeper round-trips per second.
    """
    call_count = {"n": 0}
    real_responses = {
        "/league/L1/drafts": _fixture_drafts_response(),
        "/draft/D1": {"status": "drafting"},
        "/draft/D1/picks": _fixture_picks_response(),
    }
    sorted_keys = sorted(real_responses.keys(), key=len, reverse=True)

    def _counting_fetch(url):
        call_count["n"] += 1
        for suffix in sorted_keys:
            if url.endswith(suffix):
                return real_responses[suffix]
        return None

    monkeypatch.setattr(sleeper_overlay, "_http_get_json", _counting_fetch)
    sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=0)
    calls_after_first = call_count["n"]
    # Second + third polls with different cursors must hit the cache.
    sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=1)
    sleeper_overlay.fetch_live_draft_picks("L1", after_pick_no=0)
    assert call_count["n"] == calls_after_first, (
        f"Expected cached polls to make 0 new HTTP calls; saw "
        f"{call_count['n'] - calls_after_first}."
    )
