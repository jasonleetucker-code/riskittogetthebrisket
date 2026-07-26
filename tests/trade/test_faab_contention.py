"""Tests for ``src/trade/faab_contention.py`` — the FAAB v2 rival-bid
estimator.

Pins the sealed-auction math factor by factor:

    exp_bid = min(base × agg × need_f × intel_f, base × 2.5) × 1.15
    exp_bid = min(exp_bid, opponent.faabRemaining)
    clearing = topRival + 1

plus the defensive intel-snapshot reader (plain JSON, no
``src.intel`` import) and the ``staleInputs`` freshness helper.
No live network anywhere.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from src.trade.faab_contention import (
    AGG_MIN_WINNING_BIDS,
    INTEL_PLAYER_FACTOR,
    INTEL_POSITION_FACTOR,
    SAFETY_MARGIN,
    STACK_CAP_MULT,
    aggression_factor,
    build_intel_index,
    estimate_rival_bids,
    intel_factor,
    load_intel_snapshot,
    need_level_for,
    stale_inputs,
)
from src.trade.suggestions import PlayerAsset


# ── Fixtures ───────────────────────────────────────────────────


def _asset(name: str, position: str, value: int = 3000) -> PlayerAsset:
    return PlayerAsset(
        name=name,
        position=position,
        display_value=value,
        calibrated_value=value,
        source_count=3,
    )


def _team(owner_id: str, players: list[str], faab: int | None = 100) -> dict:
    return {
        "ownerId": owner_id,
        "name": f"Team {owner_id}",
        "players": players,
        "faabRemaining": faab,
    }


# A pool where "WR Needy" rosters have too few WRs and "WR Loaded"
# rosters have starters + 2 depth pieces (surplus per analyze_roster).
_WR_NAMES = [f"Wr Guy {i}" for i in range(1, 9)]
_POOL = [_asset(n, "WR") for n in _WR_NAMES] + [
    _asset("Qb Guy", "QB"),
    _asset("Rb Guy", "RB"),
]


# ── aggression_factor ──────────────────────────────────────────


def test_aggression_ratio_and_clamp():
    # avg 20 vs median 10 → ratio 2.0 (at the upper clamp).
    agg, low = aggression_factor({"avgBid": 20.0, "winningCount": 5}, 10.0)
    assert agg == 2.0
    assert low is False
    # avg 50 vs median 10 → ratio 5 → clamped to 2.0.
    agg, _ = aggression_factor({"avgBid": 50.0, "winningCount": 5}, 10.0)
    assert agg == 2.0
    # avg 2 vs median 10 → 0.2 → clamped to 0.5.
    agg, _ = aggression_factor({"avgBid": 2.0, "winningCount": 5}, 10.0)
    assert agg == 0.5


def test_aggression_low_sample_defaults_neutral():
    """winningCount below the floor ⇒ 1.0 + lowSample flag —
    winning-bid selection bias means thin histories are noise."""
    agg, low = aggression_factor({"avgBid": 40.0, "winningCount": AGG_MIN_WINNING_BIDS - 1}, 10.0)
    assert agg == 1.0
    assert low is True
    # Missing entry entirely → same neutral default.
    agg, low = aggression_factor(None, 10.0)
    assert (agg, low) == (1.0, True)
    # No league median → can't normalize → neutral.
    agg, low = aggression_factor({"avgBid": 40.0, "winningCount": 9}, None)
    assert (agg, low) == (1.0, True)


# ── need_level_for ─────────────────────────────────────────────


def test_need_level_classification():
    # 1 WR rostered (< 4 starters needed) → need.
    assert need_level_for([_WR_NAMES[0]], "WR", _POOL) == "need"
    # 6 WRs → 4 starters + 2 depth → surplus.
    assert need_level_for(_WR_NAMES[:6], "WR", _POOL) == "surplus"
    # Position with no starter-needs mapping → neutral.
    assert need_level_for([_WR_NAMES[0]], "K", _POOL) == "neutral"
    # No roster info → neutral.
    assert need_level_for([], "WR", _POOL) == "neutral"


# ── intel index + factor ───────────────────────────────────────


def _intel_snapshot(events: list[dict]) -> dict:
    return {"version": 1, "generatedAt": "2026-07-25T00:00:00+00:00", "events": events}


def test_intel_player_level_beats_position_level():
    now_ms = 1_800_000_000_000
    snap = _intel_snapshot(
        [
            {"ownerId": "o1", "assetId": "p9", "action": "add", "ts": now_ms - 1000},
            {"ownerId": "o2", "assetId": "p7", "action": "add", "ts": now_ms - 1000},
        ]
    )
    idx = build_intel_index(snap, id_to_position={"p9": "WR", "p7": "WR"}, now_ms=now_ms)
    # o1 added THIS player → player-level 1.25.
    assert intel_factor(idx, "o1", "p9", "WR") == (INTEL_PLAYER_FACTOR, "player")
    # o2 added a different WR → position-level 1.10.
    assert intel_factor(idx, "o2", "p9", "WR") == (INTEL_POSITION_FACTOR, "position")
    # o3 has no events → none.
    assert intel_factor(idx, "o3", "p9", "WR") == (1.0, "none")


def test_intel_index_ignores_old_drops_and_picks():
    now_ms = 1_800_000_000_000
    snap = _intel_snapshot(
        [
            # Too old — outside the recency window.
            {"ownerId": "o1", "assetId": "p1", "action": "add", "ts": 1},
            # Drops are not buy signals.
            {"ownerId": "o1", "assetId": "p2", "action": "drop", "ts": now_ms - 1000},
            # Picks don't hit the waiver wire.
            {
                "ownerId": "o1",
                "assetId": "pick:2027:1",
                "assetType": "pick",
                "action": "add",
                "ts": now_ms - 1000,
            },
        ]
    )
    idx = build_intel_index(snap, id_to_position={}, now_ms=now_ms)
    assert idx == {}


def test_missing_intel_defaults_to_one():
    assert intel_factor(None, "o1", "p9", "WR") == (1.0, "none")
    assert intel_factor({}, "o1", "p9", "WR") == (1.0, "none")


# ── load_intel_snapshot (defensive read) ───────────────────────


def test_load_intel_snapshot_missing_file(tmp_path):
    assert load_intel_snapshot(tmp_path / "nope.json") is None


def test_load_intel_snapshot_corrupt_file(tmp_path):
    p = tmp_path / "snapshot.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_intel_snapshot(p) is None
    # Valid JSON but not an object → also None.
    p.write_text("[1, 2]", encoding="utf-8")
    assert load_intel_snapshot(p) is None


def test_load_intel_snapshot_roundtrip(tmp_path):
    p = tmp_path / "snapshot.json"
    p.write_text(json.dumps(_intel_snapshot([])), encoding="utf-8")
    snap = load_intel_snapshot(p)
    assert isinstance(snap, dict)
    assert snap["generatedAt"] == "2026-07-25T00:00:00+00:00"


# ── estimate_rival_bids ────────────────────────────────────────


def test_clearing_is_top_rival_plus_one():
    out = estimate_rival_bids(
        base_bid=10,
        add_position="WR",
        opponents=[
            _team("o1", [_WR_NAMES[0]]),  # need → 1.0
            _team("o2", _WR_NAMES[:6]),  # surplus → 0.25
        ],
        asset_pool=_POOL,
        team_aggression={},
        league_median_winning_bid=10.0,
    )
    # o1: 10 × 1.0(agg lowSample) × 1.0(need) × 1.0 → ×1.15 = 11.5 → 12
    # o2: 10 × 1.0 × 0.25 → 2.875 → 3
    per = {r["ownerId"]: r for r in out["perOpponent"]}
    assert per["o1"]["expBid"] == 12
    assert per["o2"]["expBid"] == 3
    assert per["o1"]["needLevel"] == "need"
    assert per["o2"]["needLevel"] == "surplus"
    assert per["o1"]["lowSample"] is True
    assert out["topRival"] == 12
    assert out["clearing"] == 13
    assert out["estimateOnly"] is True


def test_aggression_raises_rival_estimate():
    out = estimate_rival_bids(
        base_bid=10,
        add_position="WR",
        opponents=[_team("o1", [_WR_NAMES[0]])],
        asset_pool=_POOL,
        team_aggression={"o1": {"avgBid": 20.0, "winningCount": 5}},
        league_median_winning_bid=10.0,
    )
    # 10 × 2.0 × 1.0 × 1.0 = 20 → ×1.15 = 23.
    row = out["perOpponent"][0]
    assert row["aggression"] == 2.0
    assert row["lowSample"] is False
    assert row["expBid"] == 23


def test_stack_cap_limits_multiplier_pileup():
    """agg 2.0 × need 1.0 × intel 1.25 = 2.5 — exactly the stack
    cap; the expected bid can never exceed base × 2.5 × 1.15."""
    now_ms = 1_800_000_000_000
    idx = build_intel_index(
        _intel_snapshot([{"ownerId": "o1", "assetId": "p9", "action": "add", "ts": now_ms - 1000}]),
        id_to_position={"p9": "WR"},
        now_ms=now_ms,
    )
    out = estimate_rival_bids(
        base_bid=20,
        add_position="WR",
        add_player_id="p9",
        opponents=[_team("o1", [_WR_NAMES[0]], faab=1000)],
        asset_pool=_POOL,
        team_aggression={"o1": {"avgBid": 90.0, "winningCount": 8}},  # ratio 9 → clamp 2.0
        league_median_winning_bid=10.0,
        intel_index=idx,
        intel_available=True,
    )
    row = out["perOpponent"][0]
    assert row["intelLevel"] == "player"
    hard_max = round(20 * STACK_CAP_MULT * SAFETY_MARGIN)
    assert row["expBid"] == hard_max  # 20 × 2.5 × 1.15 = 57.5 → 58
    assert row["expBid"] <= hard_max


def test_rival_capped_by_faab_remaining():
    out = estimate_rival_bids(
        base_bid=30,
        add_position="WR",
        opponents=[_team("o1", [_WR_NAMES[0]], faab=8)],
        asset_pool=_POOL,
        team_aggression={},
        league_median_winning_bid=10.0,
    )
    row = out["perOpponent"][0]
    assert row["expBid"] == 8
    assert row["capped"] is True
    assert out["clearing"] == 9


def test_unknown_balance_rival_excluded_from_clearing():
    """A rival with no visible faabRemaining is unverifiable — their
    row is reported (flagged ``balanceUnknown``) but must never drive
    ``topRival``/``clearing`` upward."""
    out = estimate_rival_bids(
        base_bid=30,
        add_position="WR",
        opponents=[
            _team("o1", [_WR_NAMES[0]], faab=10),  # verifiable, capped at $10
            _team("o2", [_WR_NAMES[1]], faab=None),  # balance unknown
        ],
        asset_pool=_POOL,
        team_aggression={},
        league_median_winning_bid=10.0,
    )
    per = {r["ownerId"]: r for r in out["perOpponent"]}
    assert per["o1"]["balanceUnknown"] is False
    assert per["o2"]["balanceUnknown"] is True
    assert per["o2"]["expBid"] > per["o1"]["expBid"]  # bigger raw estimate...
    assert out["topRival"] == per["o1"]["expBid"]  # ...but excluded
    assert out["clearing"] == per["o1"]["expBid"] + 1
    assert any("no visible FAAB balance" in n for n in out["notes"])


def test_all_broke_rivals_clear_at_one_dollar():
    out = estimate_rival_bids(
        base_bid=30,
        add_position="WR",
        opponents=[
            _team("o1", [_WR_NAMES[0]], faab=0),
            _team("o2", [_WR_NAMES[1]], faab=0),
        ],
        asset_pool=_POOL,
        team_aggression={},
        league_median_winning_bid=10.0,
    )
    assert out["topRival"] == 0
    assert out["clearing"] == 1
    assert all(r["expBid"] == 0 for r in out["perOpponent"])


def test_missing_intel_snapshot_adds_note():
    out = estimate_rival_bids(
        base_bid=10,
        add_position="WR",
        opponents=[_team("o1", [_WR_NAMES[0]])],
        asset_pool=_POOL,
        team_aggression={},
        league_median_winning_bid=10.0,
        intel_index=None,
        intel_available=False,
    )
    assert any("Intel snapshot missing" in n for n in out["notes"])
    assert out["perOpponent"][0]["intelLevel"] == "none"


def test_selection_bias_note_always_present():
    out = estimate_rival_bids(
        base_bid=10,
        add_position="WR",
        opponents=[],
        asset_pool=_POOL,
    )
    assert any("selection bias" in n for n in out["notes"])


def test_zero_base_bid_returns_token_clearing():
    out = estimate_rival_bids(
        base_bid=0,
        add_position="WR",
        opponents=[_team("o1", [_WR_NAMES[0]])],
        asset_pool=_POOL,
    )
    assert out["topRival"] == 0
    assert out["clearing"] == 1
    assert out["perOpponent"] == []


# ── stale_inputs ───────────────────────────────────────────────


def test_stale_inputs_flags_missing_and_old():
    now = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)
    fresh = now.isoformat()
    old = (now - timedelta(days=30)).isoformat()
    stale = stale_inputs(
        {
            "rosters": fresh,
            "leagueAnalytics": old,
            "trending": None,
            "intel": fresh,
        },
        now=now.timestamp(),
    )
    assert "rosters" not in stale
    assert "intel" not in stale
    assert "leagueAnalytics" in stale
    assert "trending" in stale


def test_stale_inputs_ignores_unknown_keys():
    stale = stale_inputs({"someOtherThing": None})
    assert stale == []
