"""MD-108 / W10-F004: population-safe vendor rookie-price comparison (vc_v1).

Every expected number is hand-computed from the rule in
``src/draft/vendor_comparison.py`` (pair the vendor's order over the common
rookies with OUR dollars over those same rookies, sorted descending), never read
back from the implementation.
"""

from __future__ import annotations

import copy

import pytest

import server
from src.draft import vendor_comparison as vc


def _pool(n, vendor_raw, key="ktcRaw", stale=None):
    """Rookies R00.. ; ``vendor_raw(i)`` -> raw value or None."""
    pool = []
    for i in range(n):
        row = {"name": f"R{i:02d}", "ktcRaw": None, "idpRaw": None, "staleVendors": []}
        row[key] = vendor_raw(i)
        if stale and i in stale:
            row["staleVendors"] = ["ktc" if key == "ktcRaw" else "idpTradeCalc"]
        pool.append(row)
    return pool


def _ours(n):
    # 72 - i for rookie i (rank order = index order), hand-summable.
    return [float(72 - i) for i in range(n)]


def _agree(i):
    return 9000.0 - 100.0 * i


def test_partial_list_that_agrees_with_us_shows_exactly_zero_gap():
    # The W10-F004 repro: KTC lists the first 45 of 72 and orders them as we do.
    pool = _pool(72, lambda i: _agree(i) if i < 45 else None)
    ours = _ours(72)
    out, r = vc.compare_vendor(pool, ours, "ktc")
    assert r["state"] == vc.STATE_COMPARABLE and r["covered"] == 45 and r["common"] == 45
    assert len(out) == 45
    for i in range(45):
        assert out[f"r{i:02d}"] == ours[i]


def test_vendor_total_is_our_total_over_the_common_rookies_not_the_whole_budget():
    pool = _pool(72, lambda i: _agree(i) if i < 45 else None)
    out, _ = vc.compare_vendor(pool, _ours(72), "ktc")
    # sum(72..28) = (72 + 28) * 45 / 2 = 2250 - NOT the full 72*73/2 = 2628
    assert sum(out.values()) == 2250.0


def test_omitting_middle_rookies_does_not_change_the_agreement():
    omitted = set(range(10, 30))
    pool = _pool(72, lambda i: None if i in omitted else _agree(i))
    ours = _ours(72)
    out, r = vc.compare_vendor(pool, ours, "ktc")
    assert r["common"] == 52
    for i in range(72):
        if i in omitted:
            assert f"r{i:02d}" not in out
        else:
            assert out[f"r{i:02d}"] == ours[i]


def test_order_swap_moves_dollars_between_the_swapped_rookies_only():
    # 12 rookies, ours 12..1.  Vendor puts R01 above R00.
    def raw(i):
        return {0: 8000.0, 1: 9000.0}.get(i, 7000.0 - 100.0 * i)

    pool = _pool(12, raw)
    ours = [float(12 - i) for i in range(12)]
    out, _ = vc.compare_vendor(pool, ours, "ktc")
    assert out["r01"] == 12.0  # vendor's #1 gets our #1 dollar (ours R01 = 11)
    assert out["r00"] == 11.0  # vendor's #2 gets our #2 dollar (ours R00 = 12)
    assert all(out[f"r{i:02d}"] == ours[i] for i in range(2, 12))
    assert sum(out.values()) == sum(ours) == 78.0


def test_tied_vendor_values_share_the_mean_of_their_slots():
    # Same-round style tie: R00 and R01 identical -> (12 + 11) / 2 each.
    pool = _pool(12, lambda i: 9000.0 if i < 2 else 5000.0 - 100.0 * i)
    out, _ = vc.compare_vendor(pool, [float(12 - i) for i in range(12)], "ktc")
    assert out["r00"] == out["r01"] == 11.5
    assert out["r02"] == 10.0


def test_a_vendor_with_no_observations_is_explicit_not_zero():
    pool = _pool(72, lambda i: None)
    out, r = vc.compare_vendor(pool, _ours(72), "ktc")
    assert out == {}
    assert r["state"] == vc.STATE_NO_OBSERVATIONS and r["reason"] == "vendor_lists_no_rookies"


def test_non_positive_vendor_values_are_not_observations():
    pool = _pool(72, lambda i: 0.0 if i % 2 else -5.0)
    _, r = vc.compare_vendor(pool, _ours(72), "ktc")
    assert r["listed"] == 0


@pytest.mark.parametrize(
    "n_pool,n_cover,state",
    [
        (72, 11, vc.STATE_INSUFFICIENT),  # below the 12-rookie floor
        (72, 35, vc.STATE_INSUFFICIENT),  # 35/72 < 0.5
        (72, 36, vc.STATE_COMPARABLE),  # 36/72 == 0.5 passes
        (24, 12, vc.STATE_COMPARABLE),  # exactly both floors
    ],
)
def test_incomplete_populations_hit_the_declared_floors(n_pool, n_cover, state):
    pool = _pool(n_pool, lambda i: _agree(i) if i < n_cover else None)
    out, r = vc.compare_vendor(pool, _ours(n_pool), "ktc")
    assert r["state"] == state
    assert bool(out) == (state == vc.STATE_COMPARABLE)


def test_stale_observations_are_excluded_and_counted():
    stale = {0, 1, 2}
    pool = _pool(24, lambda i: _agree(i) if i < 15 else None, stale=stale)
    out, r = vc.compare_vendor(pool, _ours(24), "ktc")
    assert r["listed"] == 15 and r["staleObservations"] == 3 and r["covered"] == 12
    assert r["state"] == vc.STATE_COMPARABLE
    assert not {"r00", "r01", "r02"} & set(out)
    # Dollars are the ones OUR ladder gave the 12 fresh rookies R03..R14: the
    # stale rookies' dollars do not leak into the vendor's pool.
    assert sum(out.values()) == sum(float(72 - i) for i in range(3, 15))


def test_all_stale_is_labelled_stale_not_missing():
    pool = _pool(24, lambda i: _agree(i), stale=set(range(24)))
    out, r = vc.compare_vendor(pool, _ours(24), "ktc")
    assert out == {} and r["reason"] == "stale" and r["state"] == vc.STATE_NO_OBSERVATIONS


def test_rookies_we_did_not_price_are_not_in_the_common_population():
    ours = _ours(24)
    for i in (3, 4, 5):
        ours[i] = None
    pool = _pool(24, lambda i: _agree(i))
    out, r = vc.compare_vendor(pool, ours, "ktc")
    assert r["covered"] == 24 and r["common"] == 21
    assert not {"r03", "r04", "r05"} & set(out)
    assert sum(out.values()) == sum(o for o in ours if o is not None)


def test_no_canonical_dollars_at_all_is_an_explicit_state():
    pool = _pool(24, lambda i: _agree(i))
    for ours in (None, [None] * 24):
        out, r = vc.compare_vendor(pool, ours, "ktc")
        assert out == {} and r["state"] == vc.STATE_OURS_UNAVAILABLE


def test_duplicate_or_blank_identity_refuses_the_comparison():
    pool = _pool(24, lambda i: _agree(i))
    pool[5]["name"] = "r04"  # case-insensitive collision with R04
    out, r = vc.compare_vendor(pool, _ours(24), "ktc")
    assert out == {} and r["state"] == vc.STATE_AMBIGUOUS
    pool[5]["name"] = " "
    assert vc.compare_vendor(pool, _ours(24), "ktc")[1]["state"] == vc.STATE_AMBIGUOUS


def test_conflicting_providers_are_compared_separately_never_merged():
    # KTC orders R00>R01>...; IDPTC reverses the first 12.  12 rookies, ours 12..1.
    pool = []
    for i in range(12):
        pool.append(
            {
                "name": f"R{i:02d}",
                "ktcRaw": 9000.0 - 100.0 * i,
                "idpRaw": 5000.0 + 100.0 * i,
                "staleVendors": [],
            }
        )
    ours = [float(12 - i) for i in range(12)]
    by_vendor, block = vc.compare_all_vendors(pool, ours)
    assert by_vendor["ktc"]["r00"] == 12.0 and by_vendor["ktc"]["r11"] == 1.0
    assert by_vendor["idpTradeCalc"]["r00"] == 1.0 and by_vendor["idpTradeCalc"]["r11"] == 12.0
    provs = {v["provider"] for v in block["vendors"].values()}
    assert provs == {"KeepTradeCut", "IDP Trade Calculator"}  # two providers, no blend


def test_identical_values_from_two_vendors_do_not_become_a_third_number():
    pool = [
        {"name": f"R{i:02d}", "ktcRaw": 9000.0 - i, "idpRaw": 9000.0 - i, "staleVendors": []}
        for i in range(12)
    ]
    by_vendor, block = vc.compare_all_vendors(pool, _ours(12))
    assert by_vendor["ktc"] == by_vendor["idpTradeCalc"]
    assert set(block["vendors"]) == {"ktc", "idpTradeCalc"}


def test_every_figure_is_labelled_derived_and_versioned():
    _, block = vc.compare_all_vendors(_pool(12, _agree), _ours(12))
    assert block["version"] == "vc_v1"
    assert block["quoteKind"] == "derived_comparison_not_a_vendor_quote"
    for r in block["vendors"].values():
        assert r["quoteKind"] == "derived_comparison_not_a_vendor_quote"
        assert r["method"] == "intersection_budget_reallocation"


def test_inputs_are_never_mutated():
    pool = _pool(24, _agree)
    ours = _ours(24)
    before = (copy.deepcopy(pool), list(ours))
    vc.compare_all_vendors(pool, ours)
    assert (pool, ours) == before


def test_layer_does_not_import_the_canonical_curve_or_server():
    src = open(vc.__file__, encoding="utf-8").read()
    assert "rookie_auction" not in src.replace("src/draft/rookie_auction", "")
    assert "import server" not in src


# ------------------------------------------------------------------ server wiring


def _row(name, value, ktc, idp, excluded=()):
    return {
        "canonicalName": name,
        "displayName": name,
        "position": "WR",
        "playerId": name.lower(),
        "rookie": True,
        "rankDerivedValue": value,
        "assetClass": "offense",
        "canonicalSiteValues": {"ktcCrowdTradesSfTep": ktc, "idpTradeCalc": idp},
        "freshnessExcludedSources": list(excluded),
    }


def test_pool_marks_stale_vendors_from_row_freshness_exclusions(monkeypatch):
    rows = [
        _row("A", 9000, 8000, 7000, excluded=["idpTradeCalc"]),
        _row("B", 8000, 7000, 6000, excluded=["ktcCrowdSfTep"]),  # only one KTC board
        _row("C", 7000, 6000, 5000, excluded=["ktcCrowdSfTep", "ktcTradesSfTep"]),
    ]
    monkeypatch.setattr(server, "latest_contract_data", {"playersArray": rows}, raising=False)
    pool = {r["name"]: r for r in server._our_rookie_pool(top_n=10)}
    assert pool["A"]["staleVendors"] == ["idpTradeCalc"]
    assert pool["B"]["staleVendors"] == []
    assert pool["C"]["staleVendors"] == ["ktc"]
