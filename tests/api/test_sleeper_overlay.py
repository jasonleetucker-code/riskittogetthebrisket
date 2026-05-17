"""Tests for ``src/api/sleeper_overlay.py``.

The overlay is the per-request live Sleeper fetch that powers
``/api/data``'s sleeper block when the loaded contract is stale.
The trade-shape parity covered here is what makes the /trades page
reflect Sleeper activity within ~15 min instead of the next 2h
scrape cadence — the previous overlay returned raw Sleeper
transactions which the frontend's trade-grading couldn't parse.
"""

from __future__ import annotations

import time

import pytest

from src.api import sleeper_overlay


def _recent_ms() -> int:
    """Return a millis timestamp safely inside the default 365-day
    window — used so test trades don't get filtered as ancient."""
    return int(time.time() * 1000) - 30 * 24 * 3600 * 1000  # 30 days ago


@pytest.fixture(autouse=True)
def _clear_overlay_cache():
    """Each test starts with a fresh overlay cache so the in-process
    15-min memo doesn't leak fixtures between cases."""
    sleeper_overlay.invalidate_overlay_cache()
    yield
    sleeper_overlay.invalidate_overlay_cache()


# ── _build_trades_block shape parity ────────────────────────────────────


def _stub_http_responses(mapping):
    """Return a callable suitable for monkeypatching
    ``sleeper_overlay._http_get_json``.  Picks the response by
    LONGEST-matching suffix so a generic prefix like ``/league/L1``
    can't shadow a more specific URL like
    ``/league/L1/transactions/3``.  Unmatched URLs return ``None``
    (the fail-soft signal the real fetcher uses).
    """
    sorted_keys = sorted(mapping.keys(), key=len, reverse=True)

    def _resolve(url: str):
        for suffix in sorted_keys:
            if url.endswith(suffix):
                return mapping[suffix]
        return None

    return _resolve


def test_build_trades_block_emits_processed_sides_shape(monkeypatch):
    """The overlay must emit trades in the same shape the offline
    scraper bakes (``[{leagueId, week, timestamp, sides[]}, ...]``)
    so ``analyzeSleeperTradeHistory`` on the frontend can grade
    them.  This is the load-bearing parity that lets /trades work
    on the overlay path.
    """
    league_id = "L1"
    responses = {
        # League chain root: no previous_league_id → chain stops.
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        # Per-league rosters + users for rid → name + owner_id.
        f"/league/{league_id}/rosters": [
            {"roster_id": 1, "owner_id": "oA"},
            {"roster_id": 2, "owner_id": "oB"},
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        # No drafts → empty draft-slot map → pick labels fall back
        # to "YYYY R{th}" form.
        f"/league/{league_id}/drafts": [],
    }
    # Week 3 has one completed trade between rosters 1 and 2.
    fresh_ms = _recent_ms()
    responses[f"/league/{league_id}/transactions/3"] = [
        {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "status_updated": fresh_ms,
            "roster_ids": [1, 2],
            "adds": {"P-A": 1, "P-B": 2},
            "drops": {"P-A": 2, "P-B": 1},
            "draft_picks": [
                {
                    "season": "2026",
                    "round": 1,
                    "roster_id": 1,
                    "owner_id": 2,
                    "previous_owner_id": 1,
                },
            ],
        },
    ]
    # Other weeks empty.
    for w in range(0, 19):
        if w == 3:
            continue
        responses[f"/league/{league_id}/transactions/{w}"] = []

    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )

    id_to_player = {"P-A": "Player A", "P-B": "Player B"}
    trades = sleeper_overlay._build_trades_block(
        league_id,
        window_days=365,
        id_to_player=id_to_player,
    )

    assert len(trades) == 1
    t = trades[0]
    # Shape: leagueId, week, timestamp, sides[].
    assert t["leagueId"] == league_id
    assert t["week"] == 3
    assert t["timestamp"] == fresh_ms
    assert isinstance(t["sides"], list) and len(t["sides"]) == 2
    # Each side carries team / rosterId / ownerId / got / gave.
    for side in t["sides"]:
        assert set(side.keys()) >= {"team", "rosterId", "ownerId", "got", "gave"}
    by_rid = {s["rosterId"]: s for s in t["sides"]}
    # Roster 1 GOT Player A (resolved from id map) + GAVE Player B
    # + GAVE the 2026 1st pick they originally owned.
    a = by_rid[1]
    assert "Player A" in a["got"]
    assert "Player B" in a["gave"]
    assert any("2026" in label for label in a["gave"])
    # Owner-id stamps come through.
    assert a["ownerId"] == "oA"
    # Roster 2 mirror.
    b = by_rid[2]
    assert "Player B" in b["got"]
    assert "Player A" in b["gave"]
    assert b["ownerId"] == "oB"


def test_build_trades_block_filters_incomplete_trades(monkeypatch):
    """Only ``status == "complete"`` trades are emitted.  Mid-flight
    proposals and rejected trades must not appear on /trades.
    """
    league_id = "L1"
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [{"roster_id": 1, "owner_id": "oA"}],
        f"/league/{league_id}/users": [{"user_id": "oA", "display_name": "A"}],
        f"/league/{league_id}/drafts": [],
    }
    for w in range(0, 19):
        responses[f"/league/{league_id}/transactions/{w}"] = []
    responses[f"/league/{league_id}/transactions/2"] = [
        {
            "transaction_id": "tx-pending",
            "type": "trade",
            "status": "pending",
            "roster_ids": [1],
            "status_updated": 1730000000000,
        },
        {
            "transaction_id": "tx-failed",
            "type": "trade",
            "status": "failed",
            "roster_ids": [1],
            "status_updated": 1730000000000,
        },
    ]
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    trades = sleeper_overlay._build_trades_block(league_id, window_days=365)
    assert trades == []


def test_build_trades_block_filters_outside_window(monkeypatch):
    """Trades older than ``window_days`` are dropped so the rolling
    window stays honest."""
    league_id = "L1"
    very_old_ms = 100_000_000  # Year 1973 — well outside any window.
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [{"roster_id": 1, "owner_id": "oA"}],
        f"/league/{league_id}/users": [{"user_id": "oA", "display_name": "A"}],
        f"/league/{league_id}/drafts": [],
    }
    for w in range(0, 19):
        responses[f"/league/{league_id}/transactions/{w}"] = []
    responses[f"/league/{league_id}/transactions/1"] = [
        {
            "transaction_id": "tx-ancient",
            "type": "trade",
            "status": "complete",
            "status_updated": very_old_ms,
            "roster_ids": [1],
        },
    ]
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    trades = sleeper_overlay._build_trades_block(league_id, window_days=30)
    assert trades == []


def test_build_trades_block_dedupes_across_chain(monkeypatch):
    """When a trade transaction appears in both the current league
    and a previous_league_id along the chain, it must be emitted
    only once (de-duped by transaction_id).
    """
    cur, prev = "L-CUR", "L-PREV"
    base_tx = {
        "transaction_id": "tx-dup",
        "type": "trade",
        "status": "complete",
        "status_updated": _recent_ms(),
        "roster_ids": [1],
    }
    responses = {
        f"/league/{cur}": {"name": "Main", "previous_league_id": prev},
        f"/league/{prev}": {"name": "Old", "previous_league_id": None},
        f"/league/{cur}/rosters": [{"roster_id": 1, "owner_id": "oA"}],
        f"/league/{prev}/rosters": [{"roster_id": 1, "owner_id": "oA"}],
        f"/league/{cur}/users": [{"user_id": "oA", "display_name": "A"}],
        f"/league/{prev}/users": [{"user_id": "oA", "display_name": "A"}],
        f"/league/{cur}/drafts": [],
        f"/league/{prev}/drafts": [],
    }
    for w in range(0, 19):
        responses[f"/league/{cur}/transactions/{w}"] = []
        responses[f"/league/{prev}/transactions/{w}"] = []
    responses[f"/league/{cur}/transactions/4"] = [base_tx]
    responses[f"/league/{prev}/transactions/4"] = [base_tx]
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    trades = sleeper_overlay._build_trades_block(cur, window_days=365)
    assert len(trades) == 1


def test_build_trades_block_uses_draft_slot_when_available(monkeypatch):
    """Draft picks render with ``YYYY R.SS (from Team)`` slot
    suffixes when the league's drafts endpoint exposes
    ``slot_to_roster_id``.  Without slots, the label degrades to
    ``YYYY R{th} (from Team)``.  Both forms resolve through
    ``buildPickLookupCandidates`` on the frontend.

    The slot map lives on the per-draft DETAIL endpoint
    (``/v1/draft/{draft_id}``), not the league's drafts LIST
    endpoint — so this test pins that the detail fetch is wired up.
    """
    league_id = "L1"
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [
            {"roster_id": 1, "owner_id": "oA"},
            {"roster_id": 2, "owner_id": "oB"},
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        # LIST endpoint: drafts metadata, slot_to_roster_id empty.
        f"/league/{league_id}/drafts": [
            {"season": "2026", "draft_id": "D-2026"},
        ],
        # DETAIL endpoint: slot_to_roster_id lives here.
        "/draft/D-2026": {
            "season": "2026",
            "slot_to_roster_id": {"6": 1, "12": 2},
        },
    }
    for w in range(0, 19):
        responses[f"/league/{league_id}/transactions/{w}"] = []
    responses[f"/league/{league_id}/transactions/2"] = [
        {
            "transaction_id": "tx-pick",
            "type": "trade",
            "status": "complete",
            "status_updated": _recent_ms(),
            "roster_ids": [1, 2],
            "adds": {},
            "drops": {},
            "draft_picks": [
                {
                    "season": "2026",
                    "round": 1,
                    "roster_id": 1,
                    "owner_id": 2,
                    "previous_owner_id": 1,
                },
            ],
        },
    ]
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    trades = sleeper_overlay._build_trades_block(league_id, window_days=365)
    assert len(trades) == 1
    sides = trades[0]["sides"]
    # Roster 2 GOT the pick — should see "2026 1.06 (from Team A)".
    by_rid = {s["rosterId"]: s for s in sides}
    label = by_rid[2]["got"][0]
    assert "2026" in label
    assert "1.06" in label
    assert "Team A" in label


def test_build_trades_block_resolves_slot_via_draft_order(monkeypatch):
    """Some leagues author the draft order via ``draft_order``
    (user_id → slot) before ``slot_to_roster_id`` is committed.  The
    overlay must consult both maps and translate user_id → roster_id
    via the rosters' ``owner_id`` column.
    """
    league_id = "L1"
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [
            {"roster_id": 1, "owner_id": "oA"},
            {"roster_id": 2, "owner_id": "oB"},
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        f"/league/{league_id}/drafts": [
            {"season": "2026", "draft_id": "D-2026"},
        ],
        # DETAIL: only draft_order (user_id → slot), no slot_to_roster_id.
        "/draft/D-2026": {
            "season": "2026",
            "draft_order": {"oA": 4, "oB": 8},
        },
    }
    for w in range(0, 19):
        responses[f"/league/{league_id}/transactions/{w}"] = []
    responses[f"/league/{league_id}/transactions/3"] = [
        {
            "transaction_id": "tx-pick-order",
            "type": "trade",
            "status": "complete",
            "status_updated": _recent_ms(),
            "roster_ids": [1, 2],
            "draft_picks": [
                {
                    "season": "2026",
                    "round": 2,
                    "roster_id": 1,
                    "owner_id": 2,
                    "previous_owner_id": 1,
                },
            ],
        },
    ]
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    trades = sleeper_overlay._build_trades_block(league_id, window_days=365)
    assert len(trades) == 1
    by_rid = {s["rosterId"]: s for s in trades[0]["sides"]}
    label = by_rid[2]["got"][0]
    # Slot 4 from draft_order["oA"] → "2026 2.04 (from Team A)".
    assert "2.04" in label, f"expected slot-4 label, got {label!r}"


def test_build_trades_block_uses_tier_label_for_future_year_picks(monkeypatch):
    """Picks for ``current_year + 1`` and beyond render as tier-bucketed
    labels (``"YYYY Mid 1st"``) instead of slot-specific (``"YYYY 1.06"``).
    The rankings board only carries tier-bucketed pick rows for years
    past the upcoming draft, so a slot-specific label would miss the
    row entirely on /trades and produce a $0 valuation — exactly the
    bug this whole code path is fixing.
    """
    import datetime as _dt

    league_id = "L1"
    next_year = _dt.datetime.now(_dt.timezone.utc).year + 1
    # 12-team league so the Early/Mid/Late thirds (per_tier=4) match
    # the realistic boundaries: slots 1-4 Early, 5-8 Mid, 9-12 Late.
    rosters = [{"roster_id": i + 1, "owner_id": f"o{i + 1}"} for i in range(12)]
    users = [{"user_id": f"o{i + 1}", "display_name": f"Team {i + 1}"} for i in range(12)]
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": rosters,
        f"/league/{league_id}/users": users,
        f"/league/{league_id}/drafts": [
            {"season": str(next_year), "draft_id": f"D-{next_year}"},
        ],
        f"/draft/D-{next_year}": {
            "season": str(next_year),
            # Slot known — but next-year picks should still get a
            # tier label because the board doesn't carry slot rows
            # for years past the imminent draft.
            "slot_to_roster_id": {"3": 1},
        },
    }
    for w in range(0, 19):
        responses[f"/league/{league_id}/transactions/{w}"] = []
    responses[f"/league/{league_id}/transactions/4"] = [
        {
            "transaction_id": "tx-future",
            "type": "trade",
            "status": "complete",
            "status_updated": _recent_ms(),
            "roster_ids": [1, 2],
            "draft_picks": [
                {
                    "season": str(next_year),
                    "round": 1,
                    "roster_id": 1,
                    "owner_id": 2,
                    "previous_owner_id": 1,
                },
            ],
        },
    ]
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    trades = sleeper_overlay._build_trades_block(league_id, window_days=365)
    assert len(trades) == 1
    by_rid = {s["rosterId"]: s for s in trades[0]["sides"]}
    label = by_rid[2]["got"][0]
    # Slot 3 in a 12-team league → "Early" tier; round 1 → "1st".
    # Final shape: "{next_year} Early 1st (from Team A)".
    assert str(next_year) in label
    assert "Early" in label
    assert "1st" in label
    assert "1.03" not in label, f"future-year label must not be slot-specific: {label!r}"


# ── _build_waivers_block shape parity ───────────────────────────────────


def test_build_waivers_block_emits_waiver_and_free_agent(monkeypatch):
    """Sister to the trades parity test.  Both ``waiver`` and
    ``free_agent`` complete transactions are surfaced; player IDs
    resolve through ``id_to_player``; FAAB bid lifts from
    ``settings.waiver_bid``."""
    league_id = "L1"
    fresh_ms = _recent_ms()
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [
            {"roster_id": 1, "owner_id": "oA"},
            {"roster_id": 2, "owner_id": "oB"},
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        f"/league/{league_id}/drafts": [],
    }
    responses[f"/league/{league_id}/transactions/5"] = [
        {
            "transaction_id": "wv-1",
            "type": "waiver",
            "status": "complete",
            "status_updated": fresh_ms,
            "roster_ids": [1],
            "adds": {"P-A": 1},
            "drops": {"P-Z": 1},
            "settings": {"waiver_bid": 22},
        },
        {
            "transaction_id": "fa-1",
            "type": "free_agent",
            "status": "complete",
            "status_updated": fresh_ms,
            "roster_ids": [2],
            "adds": {"P-B": 2},
            "drops": {},
            "settings": {},
        },
        # A trade should NOT appear in the waiver block.
        {
            "transaction_id": "tx-1",
            "type": "trade",
            "status": "complete",
            "status_updated": fresh_ms,
            "roster_ids": [1, 2],
            "adds": {"P-A": 1},
            "drops": {"P-A": 2},
        },
    ]
    for w in range(0, 19):
        if w == 5:
            continue
        responses[f"/league/{league_id}/transactions/{w}"] = []

    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )

    id_map = {"P-A": "Player A", "P-B": "Player B", "P-Z": "Player Z"}
    waivers = sleeper_overlay._build_waivers_block(
        league_id,
        window_days=365,
        id_to_player=id_map,
    )
    assert len(waivers) == 2
    by_id = {w["transactionId"]: w for w in waivers}
    wv = by_id["wv-1"]
    assert wv["type"] == "waiver"
    assert wv["faabBid"] == 22
    assert wv["added"] == ["Player A"]
    assert wv["dropped"] == ["Player Z"]
    assert wv["rosterId"] == 1
    assert wv["ownerId"] == "oA"
    assert wv["week"] == 5

    fa = by_id["fa-1"]
    assert fa["type"] == "free_agent"
    assert fa["faabBid"] == 0  # FA tx don't carry a bid
    assert fa["added"] == ["Player B"]
    assert fa["dropped"] == []
    assert fa["rosterId"] == 2
    assert fa["ownerId"] == "oB"


def test_build_waivers_block_filters_incomplete_status(monkeypatch):
    """Pending waiver bids that haven't run yet must NOT appear in
    the overlay — only ``status == complete`` claims surface."""
    league_id = "L1"
    fresh_ms = _recent_ms()
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [{"roster_id": 1, "owner_id": "oA"}],
        f"/league/{league_id}/users": [{"user_id": "oA", "display_name": "A"}],
        f"/league/{league_id}/drafts": [],
    }
    responses[f"/league/{league_id}/transactions/4"] = [
        {
            "transaction_id": "p-1",
            "type": "waiver",
            "status": "pending",
            "status_updated": fresh_ms,
            "roster_ids": [1],
            "adds": {"X": 1},
            "settings": {"waiver_bid": 5},
        },
    ]
    for w in range(0, 19):
        if w == 4:
            continue
        responses[f"/league/{league_id}/transactions/{w}"] = []
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    waivers = sleeper_overlay._build_waivers_block(league_id)
    assert waivers == []


def test_build_waivers_block_dedupes_across_chain(monkeypatch):
    """A waiver tx that appears in both the current league and a
    previous_league_id (chain replay) must only be counted once."""
    cur, prev = "L1", "L0"
    fresh_ms = _recent_ms()
    common_tx = {
        "transaction_id": "wv-shared",
        "type": "waiver",
        "status": "complete",
        "status_updated": fresh_ms,
        "roster_ids": [1],
        "adds": {"X": 1},
        "settings": {"waiver_bid": 7},
    }
    responses = {
        f"/league/{cur}": {"name": "Main", "previous_league_id": prev},
        f"/league/{prev}": {"name": "Old", "previous_league_id": None},
    }
    for lid in (cur, prev):
        responses[f"/league/{lid}/rosters"] = [{"roster_id": 1, "owner_id": "oA"}]
        responses[f"/league/{lid}/users"] = [{"user_id": "oA", "display_name": "A"}]
        responses[f"/league/{lid}/drafts"] = []
        for w in range(0, 19):
            responses[f"/league/{lid}/transactions/{w}"] = [common_tx] if w == 2 else []
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    waivers = sleeper_overlay._build_waivers_block(cur)
    assert len(waivers) == 1
    assert waivers[0]["transactionId"] == "wv-shared"


def test_build_waivers_block_filters_outside_window(monkeypatch):
    """Old waiver claims past ``window_days`` are dropped.  Mirrors
    the trade-block window-bound test."""
    league_id = "L1"
    ancient_ms = int(time.time() * 1000) - 400 * 24 * 3600 * 1000
    responses = {
        f"/league/{league_id}": {"name": "Main", "previous_league_id": None},
        f"/league/{league_id}/rosters": [{"roster_id": 1, "owner_id": "oA"}],
        f"/league/{league_id}/users": [{"user_id": "oA", "display_name": "A"}],
        f"/league/{league_id}/drafts": [],
    }
    responses[f"/league/{league_id}/transactions/1"] = [
        {
            "transaction_id": "old-1",
            "type": "waiver",
            "status": "complete",
            "status_updated": ancient_ms,
            "roster_ids": [1],
            "adds": {"X": 1},
            "settings": {"waiver_bid": 1},
        },
    ]
    for w in range(0, 19):
        if w == 1:
            continue
        responses[f"/league/{league_id}/transactions/{w}"] = []
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    waivers = sleeper_overlay._build_waivers_block(league_id, window_days=30)
    assert waivers == []


# ── _build_teams_block FAAB fields ──────────────────────────────────────


def test_build_teams_block_includes_faab_fields(monkeypatch):
    """Each team dict carries ``faabBudget`` (league-level),
    ``faabUsed`` (per-roster), and computed ``faabRemaining``.
    """
    league_id = "L1"
    responses = {
        f"/league/{league_id}": {
            "name": "Main",
            "previous_league_id": None,
            "settings": {"waiver_budget": 200},
        },
        f"/league/{league_id}/rosters": [
            {
                "roster_id": 1,
                "owner_id": "oA",
                "players": ["P-1"],
                "settings": {"waiver_budget_used": 45},
            },
            {
                "roster_id": 2,
                "owner_id": "oB",
                "players": ["P-2"],
                "settings": {"waiver_budget_used": 200},
            },
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        f"/league/{league_id}/traded_picks": [],
    }
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    teams = sleeper_overlay._build_teams_block(
        league_id, id_to_player={"P-1": "P One", "P-2": "P Two"}
    )
    assert teams is not None
    by_owner = {t["ownerId"]: t for t in teams}
    a = by_owner["oA"]
    assert a["faabBudget"] == 200
    assert a["faabUsed"] == 45
    assert a["faabRemaining"] == 155
    b = by_owner["oB"]
    assert b["faabBudget"] == 200
    assert b["faabUsed"] == 200
    assert b["faabRemaining"] == 0  # exact-spent rosters floor at 0


def test_build_teams_block_faab_falls_back_when_missing(monkeypatch):
    """Sleeper doesn't always populate ``settings.waiver_budget`` (older
    leagues, dev fixtures).  When either piece is absent the team
    dict still emits the keys with explicit ``None`` so the frontend
    can render ``"—"`` instead of crashing on missing fields."""
    league_id = "L1"
    responses = {
        f"/league/{league_id}": {
            "name": "Main",
            "previous_league_id": None,
            "settings": {},  # no waiver_budget
        },
        f"/league/{league_id}/rosters": [
            {
                "roster_id": 1,
                "owner_id": "oA",
                "players": [],
                "settings": {"waiver_budget_used": 12},
            },
            {
                "roster_id": 2,
                "owner_id": "oB",
                "players": [],
                "settings": {},  # no waiver_budget_used
            },
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
            {"user_id": "oB", "display_name": "Team B"},
        ],
        f"/league/{league_id}/traded_picks": [],
    }
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    teams = sleeper_overlay._build_teams_block(league_id, id_to_player={})
    assert teams is not None
    by_owner = {t["ownerId"]: t for t in teams}
    a = by_owner["oA"]
    # Budget missing → faabRemaining stays None even though faabUsed is known.
    assert a["faabBudget"] is None
    assert a["faabUsed"] == 12
    assert a["faabRemaining"] is None
    b = by_owner["oB"]
    assert b["faabBudget"] is None
    assert b["faabUsed"] is None
    assert b["faabRemaining"] is None


# ── fetch_sleeper_overlay end-to-end ───────────────────────────────────


def test_fetch_sleeper_overlay_includes_waivers_and_meta(monkeypatch):
    """End-to-end: ``fetch_sleeper_overlay`` must surface both the
    new ``waivers`` array and ``meta.waiverCount`` alongside the
    existing trades data."""
    league_id = "L1"
    fresh_ms = _recent_ms()
    responses = {
        f"/league/{league_id}": {
            "name": "Main",
            "previous_league_id": None,
            "settings": {"waiver_budget": 100},
        },
        f"/league/{league_id}/rosters": [
            {
                "roster_id": 1,
                "owner_id": "oA",
                "players": [],
                "settings": {"waiver_budget_used": 10},
            },
        ],
        f"/league/{league_id}/users": [
            {"user_id": "oA", "display_name": "Team A"},
        ],
        f"/league/{league_id}/drafts": [],
        f"/league/{league_id}/traded_picks": [],
    }
    responses[f"/league/{league_id}/transactions/3"] = [
        {
            "transaction_id": "wv-1",
            "type": "waiver",
            "status": "complete",
            "status_updated": fresh_ms,
            "roster_ids": [1],
            "adds": {"P": 1},
            "settings": {"waiver_bid": 5},
        },
    ]
    for w in range(0, 19):
        if w == 3:
            continue
        responses[f"/league/{league_id}/transactions/{w}"] = []
    monkeypatch.setattr(
        sleeper_overlay,
        "_http_get_json",
        _stub_http_responses(responses),
    )
    payload = sleeper_overlay.fetch_sleeper_overlay(
        sleeper_league_id=league_id,
        id_to_player={"P": "Picked"},
        force_refresh=True,
    )
    assert payload is not None
    assert "waivers" in payload
    assert isinstance(payload["waivers"], list)
    assert len(payload["waivers"]) == 1
    assert payload["meta"]["waiverCount"] == 1
    assert payload["meta"]["tradeCount"] == 0
    # FAAB fields lifted into teams block too.
    assert payload["teams"][0]["faabRemaining"] == 90
