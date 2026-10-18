"""rank-space-hampel-per-vote-v1 (preregistered FOLLOW-UP challenger; default OFF).

docs/valuation/evidence/rank-space-hampel-per-vote-2026-10-17/PREREGISTRATION.md.
Unit level: the per-vote inverse round-trips exactly for every curve family the
pipeline prices with (OFFENSE / IDP / shared-market GLOBAL masters, TE basis and
flat transforms, value-direct votes); a vote with no coordinate is never zero and
never dropped; on a single-curve row the decision is the original challenger's.
Pipeline level (newest complete archived scrape, no network): the flag ships OFF
and OFF never calls the challenger; ON hands the filter each vote's own forward
map, leaves every pre-filter vote, weight and family untouched, and stays on the
canonical scale.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.canonical import player_valuation as pv
from src.canonical.rank_coordinates import (
    RANK_POOL_IDP,
    RANK_POOL_OFFENSE,
    RANK_POOL_SHARED_MARKET,
    curve_for_pool,
)

OFFENSE = curve_for_pool(RANK_POOL_OFFENSE)
IDP = curve_for_pool(RANK_POOL_IDP)
GLOBAL = curve_for_pool(RANK_POOL_SHARED_MARKET)
CURVES = {"offense": OFFENSE, "idp": IDP, "shared_market": GLOBAL}
TE_TRANSFORMS = {
    "none": (None, None),
    "basis": (dc.PER_VOTE_TE_BASIS, ("base", "tepp")),
    "flat_native_1.10": (dc.PER_VOTE_TE_FLAT, 1.10),
    "flat_non_tep_1.15": (dc.PER_VOTE_TE_FLAT, 1.15),
}
GRID = [0.0005, 0.002, 0.01, 0.03, 0.08, 0.2, 0.45, 0.8, 1.0, 1.4]


def _fmap(curve, te=(None, None)):
    return (curve[0], curve[1], *te)


# ── the inverse ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("curve_name", sorted(CURVES))
@pytest.mark.parametrize("te_name", sorted(TE_TRANSFORMS))
@pytest.mark.parametrize("u", GRID)
def test_inverse_round_trips_exactly_per_curve_family(curve_name, te_name, u):
    fmap = _fmap(CURVES[curve_name], TE_TRANSFORMS[te_name])
    v = dc._per_vote_forward(u, fmap)
    # abs_tol 1e-6 (percentile units): a top tight end's lift sits ~1e-8 below
    # the 9,999 ceiling, where float64 resolves ln((9999 - v) / span) to ~1e-4
    # relative -- conditioning, not an inverse error, and four orders of
    # magnitude below any MAD the filter compares against.
    assert math.isclose(dc._per_vote_inverse(v, fmap), u, rel_tol=1e-7, abs_tol=1e-6)
    # ...and the other way round, on the vote scale.
    assert math.isclose(dc._per_vote_forward(dc._per_vote_inverse(v, fmap), fmap), v, rel_tol=1e-9)


def test_forward_map_is_the_pipelines_own_composition():
    """F = T ∘ H is exactly what the blend loop applies: the Hill curve, then
    ``convert_te_value`` (or the flat multiplier), then the soft ceiling."""
    from src.league_intel.te_premium import convert_te_value

    for curve in CURVES.values():
        for p in GRID:
            h = 9999.0 / (1.0 + (p / curve[0]) ** curve[1])
            assert dc._per_vote_forward(p, _fmap(curve)) == pytest.approx(h, rel=1e-12)
            basis = dc._te_lift_under_ceiling(
                convert_te_value(h, from_basis="base", to_basis="tepp")
            )
            assert dc._per_vote_forward(p, _fmap(curve, TE_TRANSFORMS["basis"])) == basis
            flat = dc._te_lift_under_ceiling(h * 1.10)
            assert dc._per_vote_forward(p, _fmap(curve, TE_TRANSFORMS["flat_native_1.10"])) == flat


def test_te_lift_is_inverted_above_the_knee():
    for lifted in (9000.0, 9900.0, 9950.0, 10500.0, 11000.0):
        out = dc._te_lift_under_ceiling(lifted)
        assert dc._te_lift_inverse(out) == pytest.approx(lifted, rel=1e-9)
    # The largest reachable lift (9999 x the uplift floor) lands ~2e-8 below the
    # ceiling; float64 conditioning there bounds the round trip to ~0.01 points.
    assert dc._te_lift_inverse(dc._te_lift_under_ceiling(12093.0)) == pytest.approx(
        12093.0, abs=0.05
    )
    assert dc._te_lift_inverse(9999.0) == math.inf  # outside the map's range


@pytest.mark.parametrize("curve_name", sorted(CURVES))
@pytest.mark.parametrize("p", [0.004, 0.02, 0.1, 0.3, 0.7])
def test_integer_rounded_rank_votes_recover_their_percentile_within_rounding(curve_name, p):
    """A rank vote is ``percentile_to_value`` (an integer); the inverse recovers
    the percentile it came from up to that rounding -- bounded by half a point
    over the curve's local slope."""
    c, s = CURVES[curve_name]
    v = float(pv.percentile_to_value(p, midpoint=c, slope=s))
    u = dc._per_vote_inverse(v, _fmap((c, s)))
    slope = abs(
        dc._per_vote_forward(p * 1.0001, _fmap((c, s))) - dc._per_vote_forward(p, _fmap((c, s)))
    )
    slope /= p * 0.0001
    assert abs(u - p) <= 0.5 / slope * 1.01 + 1e-12


def test_value_direct_votes_map_through_their_own_pool_curve():
    """raw / site_max x 9999 has no rank curve; it maps to the percentile its
    source's own pool curve implies (KTC: OFFENSE; IDPTC: shared market,
    TEP-native flat 1.10 on TE rows)."""
    v = 7321.0 / 9999.0 * 9999.0
    for curve in (OFFENSE, GLOBAL):
        u = dc._per_vote_inverse(v, _fmap(curve))
        assert math.isclose(dc._hill_inverse(v, *curve), u, rel_tol=1e-12)
    te = _fmap(GLOBAL, TE_TRANSFORMS["flat_native_1.10"])
    lifted = dc._te_lift_under_ceiling(v * 1.10)
    assert dc._per_vote_inverse(lifted, te) == pytest.approx(dc._hill_inverse(v, *GLOBAL), rel=1e-9)


# ── missing is never zero ───────────────────────────────────────────────


def test_a_vote_without_a_coordinate_is_never_zero_and_never_dropped():
    assert dc._per_vote_inverse(5000.0, None) == math.inf
    assert dc._per_vote_inverse(0.0, _fmap(OFFENSE)) == math.inf
    assert dc._per_vote_inverse(-3.0, _fmap(OFFENSE)) == math.inf
    pairs = [("a", 6000.0), ("b", 6050.0), ("c", 5980.0), ("d", 6020.0), ("x", 100.0)]
    maps = {k: _fmap(OFFENSE) for k in "abcd"}  # "x" has no recorded forward map
    res = dc.rank_space_per_vote_assessment(pairs, maps)
    assert "x" not in res["dropped"]
    assert res["thresholds"]["x"] is None
    # median / MAD are over the four coordinated votes only
    finite = sorted(dc._per_vote_inverse(v, maps[k]) for k, v in pairs if k in maps)
    assert res["median"] == pytest.approx((finite[1] + finite[2]) / 2)


def test_too_few_coordinates_stand_the_filter_down():
    pairs = [("a", 6000.0), ("b", 6050.0), ("c", 1000.0), ("d", 6020.0)]
    maps = {"a": _fmap(OFFENSE), "b": _fmap(OFFENSE), "c": _fmap(OFFENSE)}
    assert dc._hampel_filter_rank_space_per_vote(pairs, forward_maps=maps) == (pairs, [])


# ── guards and equivalence with the original challenger ─────────────────


def test_guards_match_the_incumbent():
    maps = {k: _fmap(OFFENSE) for k in "abcd"}
    three = [("a", 5000.0), ("b", 5100.0), ("c", 9000.0)]
    assert dc._hampel_filter_rank_space_per_vote(three, forward_maps=maps) == (three, [])
    same = [(k, 4000.0) for k in "abcd"]
    assert dc._hampel_filter_rank_space_per_vote(same, forward_maps=maps)[1] == []
    lopsided = [("a", 9000.0), ("b", 1000.0), ("c", 1100.0), ("d", 1050.0)]
    kept, _ = dc._hampel_filter_rank_space_per_vote(lopsided, forward_maps=maps)
    assert len(kept) >= 2


@pytest.mark.parametrize("curve_name", sorted(CURVES))
def test_single_curve_rows_decide_exactly_as_the_original_challenger(curve_name):
    """With one curve and no TE transform the per-vote floor IS the original
    challenger's floor formula, so every decision coincides."""
    curve = CURVES[curve_name]
    rng = random.Random(2027)
    for _ in range(400):
        n = rng.randint(4, 9)
        centre = rng.uniform(300, 9800)
        pairs = [
            (f"s{i}", max(5.0, min(9998.0, centre * math.exp(rng.gauss(0, 0.18)))))
            for i in range(n)
        ]
        maps = {k: _fmap(curve) for k, _ in pairs}
        mine = dc._hampel_filter_rank_space_per_vote(pairs, forward_maps=maps)
        theirs = dc._hampel_filter_rank_space(pairs, curve=curve)
        assert sorted(mine[1]) == sorted(theirs[1])


def test_each_vote_is_read_in_its_own_coordinate():
    """The same vote values judged per vote (shared-market curve, as the
    pipeline priced them) and per row (the IDP master the original challenger
    used) are different coordinates -- the discrepancy this follow-up tests."""
    pairs = [("a", 3000.0), ("b", 3100.0), ("c", 2950.0), ("d", 3050.0), ("e", 1500.0)]
    per_vote = dc.rank_space_per_vote_assessment(pairs, {k: _fmap(GLOBAL) for k, _ in pairs})
    assert per_vote["coords"]["a"] == pytest.approx(dc._hill_inverse(3000.0, *GLOBAL))
    assert per_vote["coords"]["a"] != pytest.approx(dc._hill_inverse(3000.0, *IDP))


# ── registration ────────────────────────────────────────────────────────


def test_flag_ships_off_and_is_declared():
    assert feature_flags._DEFAULTS["rank_space_hampel_per_vote_challenger"] is False
    assert feature_flags._DEFAULTS["rank_space_hampel_challenger"] is False


# ── full pipeline (archived scrape, no network) ─────────────────────────


@pytest.fixture(scope="module")
def boards():
    from src.api import value_replay as vr
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    off = vr.build(json.loads(json.dumps(payload)))
    on = vr.build(
        json.loads(json.dumps(payload)), {"flag": ("rank_space_hampel_per_vote_challenger", True)}
    )
    return payload, off, on


def test_off_is_byte_identical_and_never_calls_the_challenger(boards, monkeypatch):
    from src.api import value_replay as vr

    payload, off, _on = boards
    assert feature_flags.is_enabled("rank_space_hampel_per_vote_challenger") is False

    def _refuse(*_a, **_k):
        raise AssertionError("per-vote challenger called with the flag off")

    monkeypatch.setattr(dc, "_hampel_filter_rank_space_per_vote", _refuse)
    again = vr.build(json.loads(json.dumps(payload)))
    assert json.dumps(again["playersArray"], sort_keys=True, default=str) == json.dumps(
        off["playersArray"], sort_keys=True, default=str
    )


def test_on_hands_the_filter_each_votes_own_forward_map(boards, monkeypatch):
    from src.api import value_replay as vr
    from src.robust_filter_shadow.record import per_vote_forward_maps

    payload, _off, on = boards
    seen = []
    real = dc._hampel_filter_rank_space_per_vote

    def spy(pairs, *, forward_maps, **kw):
        seen.append((list(pairs), dict(forward_maps)))
        return real(pairs, forward_maps=forward_maps, **kw)

    monkeypatch.setattr(dc, "_hampel_filter_rank_space_per_vote", spy)
    vr.build(
        json.loads(json.dumps(payload)), {"flag": ("rank_space_hampel_per_vote_challenger", True)}
    )
    assert seen
    by_sig = {}
    for row in on["playersArray"]:
        meta = row.get("sourceRankMeta") or {}
        voting = {
            k: m.get("valueContribution") for k, m in meta.items() if not m.get("excludedReason")
        }
        by_sig.setdefault(tuple(sorted(voting.items())), []).append(row)
    checked = te_checked = 0
    for pairs, maps in seen:
        assert {k for k, _ in pairs} == set(maps), "every voting source carries a forward map"
        rows = by_sig.get(tuple(sorted((k, int(round(v))) for k, v in pairs))) or []
        if len(rows) != 1:
            continue
        stamped = per_vote_forward_maps(rows[0])
        for k, fmap in maps.items():
            assert fmap[:2] == stamped[k][:2], k  # the curve that priced the vote
            assert fmap[2] == stamped[k][2], k  # the TE transform it applied
            if fmap[2] == dc.PER_VOTE_TE_FLAT:
                assert fmap[3] == pytest.approx(stamped[k][3], abs=1e-4)
            elif fmap[2] is not None:
                assert fmap[3] == stamped[k][3]
                te_checked += 1
            checked += 1
    assert checked > 0 and te_checked > 0


def test_on_leaves_votes_weights_and_families_untouched(boards):
    """The challenger decides only which votes drop: every pre-filter vote, its
    freshness/health weight, its exclusion and its family are the incumbent's."""
    _payload, off, on = boards
    on_rows = {r["displayName"]: r for r in on["playersArray"]}
    for row in off["playersArray"]:
        other = on_rows[row["displayName"]]
        a, b = row.get("sourceRankMeta") or {}, other.get("sourceRankMeta") or {}
        assert set(a) == set(b)
        for k in a:
            for field in ("valueContribution", "excludedReason", "freshness", "rankCoordinatePool"):
                assert a[k].get(field) == b[k].get(field), (row["displayName"], k, field)
            assert dc.correlation_group_for(k) == dc.correlation_group_for(k)
        dropped = set(other.get("droppedSources") or [])
        voting = {k for k, m in b.items() if not m.get("excludedReason")}
        assert dropped <= voting, "only a voting observation can be dropped"
        if row.get("assetClass") == "pick":
            assert not dropped


def test_on_never_manufactures_a_single_family_row_and_stays_on_scale(boards):
    _payload, _off, on = boards
    assert any(r.get("droppedSources") for r in on["playersArray"])
    for row in on["playersArray"]:
        meta = row.get("sourceRankMeta") or {}
        voting = [k for k, m in meta.items() if not m.get("excludedReason")]
        dropped = set(row.get("droppedSources") or [])
        if dropped:
            assert len([k for k in voting if k not in dropped]) >= 2
        value = row.get("rankDerivedValue")
        if value is not None:
            assert 0 < value <= 9999
