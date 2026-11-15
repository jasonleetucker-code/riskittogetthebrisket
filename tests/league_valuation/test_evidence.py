"""utility_evidence_from_bdvm: explicit states, never a zero for missing."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.league_valuation.contracts import ContractError, UtilityEvidence
from src.league_valuation.evidence import (
    evidence_asset_key,
    quality_for,
    snapshot_freshness,
    utility_evidence_from_bdvm,
)
from tests.league_valuation._builders import NOW, PARAMS, bdvm_entry, payload


def _one(entry, **kw):
    return utility_evidence_from_bdvm(payload([entry], **kw), now=NOW, params=PARAMS)


def test_available_record_carries_signed_points_and_dv():
    ev = _one(bdvm_entry("100", "WR", 512.5, -2.25))["player:100"]
    assert ev.state == "available"
    assert ev.points_over_replacement == -2.25  # signed, not truncated
    assert ev.balanced_dv == 512.5
    assert ev.scope == "OFFENSE" and ev.position == "WR"
    assert ev.projection_families == 3 and ev.quality == 1.0
    assert ev.lineage_ids == ("bdvm_fundamental",)


def test_missing_balanced_strategy_is_unavailable_never_zero():
    ev = _one(bdvm_entry("100", "WR", None, 3.0, strategies={"win_now": 900.0}))["player:100"]
    assert ev.state == "unavailable"
    assert ev.reason == "strategy_missing:balanced"
    assert ev.balanced_dv is None
    assert ev.utility_key is None


def test_non_finite_strategy_value_is_unavailable():
    ev = _one(bdvm_entry("100", "WR", float("nan"), 3.0))["player:100"]
    assert ev.state == "unavailable"


def test_missing_vorg_is_unavailable():
    ev = _one(bdvm_entry("100", "WR", 10.0, None))["player:100"]
    assert ev.state == "unavailable" and ev.reason == "points_over_replacement_missing"


def test_proxy_only_evidence_is_partial_with_quality_zero():
    ev = _one(bdvm_entry("100", "RB", 10.0, 1.0, sources=["reconstructed_baseline"], proxy=True))[
        "player:100"
    ]
    assert ev.state == "partial" and ev.is_proxy and ev.quality == 0.0
    assert ev.reason == "proxy_projection_only"


def test_all_sources_stale_is_stale_with_quality_zero():
    ev = _one(bdvm_entry("100", "RB", 10.0, 1.0, sources=["a", "b"], stale=["a", "b"]))[
        "player:100"
    ]
    assert ev.state == "stale" and ev.quality == 0.0


def test_partially_stale_sources_count_only_fresh_families():
    ev = _one(bdvm_entry("100", "RB", 10.0, 1.0, sources=["a", "b", "c"], stale=["c"]))[
        "player:100"
    ]
    assert ev.state == "available" and ev.projection_families == 2 and ev.quality == 0.7


@pytest.mark.parametrize(
    "as_of,expect",
    [
        ("2026-10-14T06:10:00+00:00", "fresh"),
        ("2026-10-01T00:00:00+00:00", "stale"),
        ("2026-10-25T00:00:00+00:00", "missing"),  # dated after now
        (None, "missing"),
        ("garbage", "missing"),
    ],
)
def test_snapshot_freshness_budget(as_of, expect):
    meta = {"projectionSnapshot": {"asOf": as_of, "asOfUnknown": as_of is None}}
    assert snapshot_freshness(meta, now=NOW, params=PARAMS)[0] == expect


def test_request_time_fallback_asof_is_missing_freshness():
    meta = {"projectionSnapshot": {"asOf": "2026-10-19", "asOfSource": "request_time_fallback"}}
    assert snapshot_freshness(meta, now=NOW, params=PARAMS)[0] == "missing"


def test_stale_snapshot_makes_every_record_stale():
    out = utility_evidence_from_bdvm(
        payload([bdvm_entry("1", "QB", 1.0, 1.0)], as_of=(NOW - timedelta(days=30)).isoformat()),
        now=NOW,
        params=PARAMS,
    )
    assert out["player:1"].state == "stale"


def test_non_ok_payload_yields_no_evidence():
    assert (
        utility_evidence_from_bdvm({"status": "no_projection_snapshot"}, now=NOW, params=PARAMS)
        == {}
    )
    assert utility_evidence_from_bdvm({}, now=NOW, params=PARAMS) == {}


def test_unpriced_players_are_unavailable_with_bdvm_reason():
    pl = payload([], unpriced=[{"name": "Rookie Guy", "reason": "no_projection", "position": "WR"}])
    out = utility_evidence_from_bdvm(pl, now=NOW, params=PARAMS)
    (ev,) = out.values()
    assert ev.state == "unavailable" and ev.reason == "bdvm_unpriced:no_projection"


def test_market_block_is_never_read():
    a = bdvm_entry("1", "QB", 10.0, 1.0)
    b = bdvm_entry("1", "QB", 10.0, 1.0)
    b["market"] = {"marketValue": 9999.0, "gap": -1e9, "marketAdjusted": 0.0}
    assert _one(a)["player:1"] == _one(b)["player:1"]


def test_identity_collision_is_refused():
    out = utility_evidence_from_bdvm(
        payload([bdvm_entry("1", "QB", 10.0, 1.0), bdvm_entry("1", "QB", 20.0, 2.0)]),
        now=NOW,
        params=PARAMS,
    )
    assert out["player:1"].state == "unavailable"
    assert out["player:1"].reason == "identity_collision_in_bdvm_payload"


def test_name_fallback_player_id_is_not_a_platform_id():
    assert evidence_asset_key("12345", "X", "WR") == "player:12345"
    key = evidence_asset_key("john smith", "John Smith", "WR")
    assert key is not None and key.startswith("name:")


def test_idp_scope_and_family():
    ev = _one(bdvm_entry("7", "DE", 1.0, 1.0))
    (e,) = ev.values()
    assert e.scope == "IDP" and e.position == "DL"


def test_quality_map_is_monotone_and_capped():
    qs = [
        quality_for(families=f, is_proxy=False, freshness="fresh", params=PARAMS) for f in range(6)
    ]
    assert qs == sorted(qs) and qs[0] == 0.0 and qs[-1] == 1.0
    assert quality_for(families=3, is_proxy=True, freshness="fresh", params=PARAMS) == 0.0
    assert quality_for(families=3, is_proxy=False, freshness="stale", params=PARAMS) == 0.0


def test_contract_refuses_available_without_numbers():
    with pytest.raises(ContractError):
        UtilityEvidence(
            asset_key="player:1",
            player_id="1",
            position="QB",
            scope="OFFENSE",
            points_over_replacement=None,
            projection_families=2,
            is_proxy=False,
            as_of=None,
            freshness="fresh",
            quality=0.7,
            lineage_ids=(),
            state="available",
            reason=None,
            balanced_dv=1.0,
        )
    with pytest.raises(ContractError):
        UtilityEvidence(
            asset_key="player:1",
            player_id="1",
            position="QB",
            scope="OFFENSE",
            points_over_replacement=None,
            projection_families=0,
            is_proxy=False,
            as_of=None,
            freshness="missing",
            quality=None,
            lineage_ids=(),
            state="unavailable",
            reason="",
        )
