"""idp-deep-tail-native-v1 (preregistered challenger; default OFF).

docs/valuation/evidence/idp-deep-tail-native-2026-10-18/PREREGISTRATION.md.

Unit level: the native ladder is non-increasing, interpolates linearly, answers
nothing outside its covered range (never zero, never an extrapolation) and prices
only the 500 < r <= 904 band.  Pipeline level (newest complete archived scrape, no
network): OFF is byte-identical; ON reprices only IDP shared-market rank votes in
the band, stamps every repriced vote, and moves no rank, pool, weight or Hill
constant.
"""

from __future__ import annotations

import json

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.canonical import deep_tail_native as dtn
from src.canonical import player_valuation as pv
from src.canonical import tail_policy

FLAG = "idp_deep_tail_native_challenger"


def test_flag_ships_off_and_band_is_the_preregistered_one():
    assert feature_flags._DEFAULTS[FLAG] is False
    assert dtn.DEEP_TAIL_MIN_RANK_EXCLUSIVE == pv.PERCENTILE_REFERENCE_N == 500
    assert dtn.DEEP_TAIL_MAX_RANK_INCLUSIVE == tail_policy.TAIL_SATURATION_RANK == 904
    assert not dtn.in_deep_band(500) and dtn.in_deep_band(500.5) and dtn.in_deep_band(904)
    assert not dtn.in_deep_band(905)


def test_ladder_is_isotonic_and_interpolates():
    ladder = dtn.build_native_ladder(
        [(500, 1200.0), (600, 900.0), (650, 950.0), (700, 700.0), (700, 500.0), (800, 400.0)]
    )
    assert list(ladder.values) == sorted(ladder.values, reverse=True)
    # 600/650 violate monotonicity and pool to their mean.
    assert ladder.value_at(600) == pytest.approx(925.0)
    assert ladder.value_at(650) == pytest.approx(925.0)
    assert ladder.value_at(700) == pytest.approx(600.0)  # tied ranks averaged
    assert ladder.value_at(750) == pytest.approx(500.0)
    assert ladder.value_at(801) is None  # outside: never zero, never extrapolated
    assert ladder.value_at(499) is None


def test_native_price_only_inside_the_band_and_with_enough_deep_points():
    ladder = dtn.build_native_ladder([(400, 2000.0), (550, 1000.0), (900, 300.0)])
    assert dtn.native_price(ladder, 450) is None  # not in band: incumbent stands
    assert dtn.native_price(ladder, 550) == pytest.approx(1000.0)
    thin = dtn.build_native_ladder([(400, 2000.0), (900, 300.0)])
    assert thin.deep_points == 1 and dtn.native_price(thin, 600) is None
    assert dtn.native_price(dtn.build_native_ladder([]), 600) is None


def test_non_observations_are_ignored():
    ladder = dtn.build_native_ladder([(0, 5.0), (600, 0.0), (650, float("nan")), (700, 10.0)])
    assert ladder.ranks == (700.0,)


# ── full pipeline (archived scrape, no network) ─────────────────────────


@pytest.fixture(scope="module")
def boards():
    from src.api import value_replay as vr
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    off = vr.build(json.loads(json.dumps(payload)))
    on = vr.build(json.loads(json.dumps(payload)), {"flag": (FLAG, True)})
    return payload, off, on


def test_off_is_byte_identical_and_never_builds_a_ladder(boards, monkeypatch):
    from src.api import value_replay as vr

    payload, off, _on = boards

    def _refuse(*_a, **_k):
        raise AssertionError("native ladder built with the flag off")

    monkeypatch.setattr(dc, "_idp_trade_calc_native_points", _refuse)
    again = vr.build(json.loads(json.dumps(payload)), {"flag": (FLAG, False)})
    assert json.dumps(again["playersArray"], sort_keys=True, default=str) == json.dumps(
        off["playersArray"], sort_keys=True, default=str
    )


def test_on_reprices_only_deep_idp_shared_market_rank_votes(boards):
    _payload, off, on = boards
    off_rows = {r["displayName"]: r for r in off["playersArray"]}
    repriced = 0
    for row in on["playersArray"]:
        base = off_rows[row["displayName"]]
        a, b = base.get("sourceRankMeta") or {}, row.get("sourceRankMeta") or {}
        assert set(a) == set(b)
        for k, m in b.items():
            for field in ("effectiveRank", "rankCoordinatePool", "percentile", "excludedReason"):
                assert a[k].get(field) == m.get(field), (row["displayName"], k, field)
            stamp = m.get("deepTailNative")
            if not stamp:
                assert a[k].get("valueContribution") == m.get("valueContribution")
                continue
            repriced += 1
            assert row.get("assetClass") == "idp"
            assert m.get("rankCoordinatePool") == "shared_market"
            assert k not in dc._VALUE_BASED_SOURCES
            assert dtn.in_deep_band(float(m["effectiveRank"]))
            # Stamps are rounded to 2 dp, valueContribution to an integer.
            assert abs(m["valueContribution"] - stamp["nativeValue"]) <= 0.51
            assert abs(a[k]["valueContribution"] - stamp["hillValue"]) <= 0.51
        value = row.get("rankDerivedValue")
        if value is not None:
            assert 0 < value <= 9999
    assert repriced > 0


def test_repriced_votes_preserve_each_sources_order(boards):
    _payload, _off, on = boards
    per_source: dict[str, list[tuple[float, float]]] = {}
    for row in on["playersArray"]:
        for k, m in (row.get("sourceRankMeta") or {}).items():
            if m.get("deepTailNative"):
                per_source.setdefault(k, []).append(
                    (float(m["effectiveRank"]), m["deepTailNative"]["nativeValue"])
                )
    assert per_source
    for k, items in per_source.items():
        items.sort()
        for (r0, v0), (r1, v1) in zip(items, items[1:]):
            assert r1 == r0 or v1 <= v0 + 1e-9, k
