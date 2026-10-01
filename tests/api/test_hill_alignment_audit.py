"""Invariants of the Hill / native-source alignment audit (scripts/hill_alignment_audit.py).

No network: every build here runs with sockets refused and the Sleeper league
context pinned. No assertion depends on which sources answered the last scrape;
real-board tests use the newest COMPLETE archived payload and assert properties
(identities, restorations, populations), never counts.
"""

from __future__ import annotations

import json
import math
import socket

import pytest

from scripts import fit_hill_curve_percentile as fitter
from scripts import hill_alignment_audit as audit
from src.api import data_contract as dc
from src.api import value_replay as vr
from src.canonical.rank_coordinates import curve_for_pool
from tests.archive_fixtures import newest_complete_raw_payload

_PINNED_CONTEXT = {"roster_count": 12, "bonus_rec_te": 0.0, "fetched_from_sleeper": False}


@pytest.fixture(scope="module")
def offline():
    mp = pytest.MonkeyPatch()

    def refuse(*_a, **_k):
        raise OSError("network disabled in test_hill_alignment_audit")

    mp.setattr(socket.socket, "connect", refuse)
    mp.setattr(dc, "_resolve_league_context", lambda *_a, **_k: dict(_PINNED_CONTEXT))
    yield
    mp.undo()


@pytest.fixture(scope="module")
def raw(offline):
    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    return payload


@pytest.fixture(scope="module")
def base(raw):
    return vr.build(raw)


# ── pure helpers ───────────────────────────────────────────────────────────────


def test_bands_cover_every_positive_rank_once():
    assert audit.band_of(1) == "1-50" and audit.band_of(50) == "1-50"
    assert audit.band_of(51) == "51-100" and audit.band_of(400) == "301-400"
    assert audit.band_of(401) == "401+" and audit.band_of(9999) == "401+"
    assert audit.band_of(0) is None and audit.band_of(None) is None
    assert [audit.coverage_band(n) for n in (1, 2, 3, 4, 5, 8, 9)] == [
        "<=2",
        "<=2",
        "3-4",
        "3-4",
        "5-8",
        "5-8",
        "9+",
    ]


def test_dense_ranks_share_ties_and_break_order_by_name_like_phase_1():
    ranks = audit.dense_ranks([("a", 10.0, "Zed"), ("b", 10.0, "Amy"), ("c", 9.0, "Bo")])
    assert ranks == {"b": 1, "a": 1, "c": 3}


def test_vectorized_fit_matches_the_fitter_exactly():
    # A real-shaped board (the fitter's own coordinate) and a curve with noise.
    values = sorted(
        (9999.0 / (1 + ((i / 499) / 0.09) ** 1.2) + (i % 7) * 13 for i in range(150)), reverse=True
    )
    pairs = fitter._percentile_pairs(values)
    c_np, s_np, mse_np = audit.fit_hill(pairs)
    c_py, s_py, mse_py = fitter._fit(pairs)
    assert (round(c_np, 6), round(s_np, 6)) == (round(c_py, 6), round(s_py, 6))
    assert mse_np == pytest.approx(mse_py, rel=1e-9)


def test_scale_map_is_monotone_and_sends_a_points_own_curve_value_to_the_master():
    master = (0.11, 1.11)
    fn = audit.scale_map(0.112, 0.91, master)
    assert fn(9999.0) == 9999.0
    grid = [9000.0, 6000.0, 3000.0, 1500.0, 500.0, 50.0]
    mapped = [fn(v) for v in grid]
    assert mapped == sorted(mapped, reverse=True)
    p = 0.2
    own = 9999.0 / (1 + (p / 0.112) ** 0.91)
    assert fn(own) == pytest.approx(9999.0 / (1 + (p / 0.11) ** 1.11), rel=1e-9)


def test_mapped_csv_keeps_rows_order_and_identity(tmp_path):
    src = tmp_path / "src.csv"
    src.write_text("name,value,rank\nA,9000,1\nB,4500,2\nC,,\nD,100,4\n", encoding="utf-8")
    ident = tmp_path / "ident.csv"
    assert audit.write_mapped_csv(src, ident, lambda v: v) == 3
    vals = [r for r in ident.read_text(encoding="utf-8").splitlines()[1:]]
    assert [v.split(",")[0] for v in vals] == ["A", "B", "C", "D"]
    assert vals[2] == "C,,"  # a missing value stays missing, never becomes 0
    out = tmp_path / "half.csv"
    audit.write_mapped_csv(src, out, lambda v: v / 2)
    nums = [
        float(x.split(",")[1])
        for x in out.read_text(encoding="utf-8").splitlines()[1:]
        if x.split(",")[1]
    ]
    assert nums == sorted(nums, reverse=True)


def test_board_impact_matches_the_hill_board_guard(tmp_path):
    import sys

    def contract(vals):
        rows = []
        for i, v in enumerate(vals):
            rows.append(
                {"displayName": f"p{i}", "rankDerivedValue": v, "canonicalConsensusRank": None}
            )
        ranked = sorted(rows, key=lambda r: -r["rankDerivedValue"])
        for i, r in enumerate(ranked):
            r["canonicalConsensusRank"] = i + 1
        return {"playersArray": rows}

    before = contract([9000 - 40 * i for i in range(130)])
    after = contract([9000 - 40 * i + (37 if i % 5 == 0 else -11) * (i % 9) for i in range(130)])
    policy = json.loads(audit.POLICY_PATH.read_text(encoding="utf-8"))
    ours = audit.board_impact(before, after, policy["boardImpact"])

    def capture(c):
        return {"rows": {r["displayName"]: r for r in c["playersArray"]}}

    (tmp_path / "b.json").write_text(json.dumps(capture(before)), encoding="utf-8")
    (tmp_path / "a.json").write_text(json.dumps(capture(after)), encoding="utf-8")
    argv = sys.argv
    sys.argv = [
        "hill_board_guard",
        str(tmp_path / "b.json"),
        str(tmp_path / "a.json"),
        "--policy",
        str(audit.POLICY_PATH),
        "--out",
        str(tmp_path / "o.json"),
    ]
    try:
        audit.guard.main()
    finally:
        sys.argv = argv
    theirs = json.loads((tmp_path / "o.json").read_text(encoding="utf-8"))
    assert ours["gates"] == theirs["gates"]
    for key in ("medianAbsPctValueChange", "p90AbsPctValueChange", "top25Overlap", "top100Overlap"):
        assert ours["metrics"][key] == pytest.approx(theirs["metrics"][key])


def test_vendor_ratio_is_one_for_a_board_that_is_exactly_the_master():
    curve = curve_for_pool("offense")
    values = [float(audit.hill_value(r, curve)) for r in range(1, 451)]
    ratios = audit._vendor_ratio_by_band(values, curve)
    assert set(ratios) == set(audit.VERDICT_BANDS)
    assert all(abs(v - 1.0) < 0.002 for v in ratios.values())
    assert audit._days_between("20260923", "20260930") == 7


# ── the corrected counterfactual (erratum to the 2026-09-30 replay) ─────────────


def test_idptc_cannot_be_re_expressed_through_the_value_set():
    with pytest.raises(ValueError):
        vr.native_values_as_ranks_spec(("ktcCrowdSfTep", "idpTradeCalc"))


def test_emptying_the_value_set_decodes_idptc_values_as_ranks(raw, base):
    """Characterizes the artifact: the old patch put every IDPTC row near rank 9,900."""
    old = vr.build(raw, {"patch": ("_VALUE_BASED_SOURCES", frozenset())})
    ranks = [
        r["sourceRankMeta"]["idpTradeCalc"]["effectiveRank"]
        for r in old["playersArray"]
        if "idpTradeCalc" in (r.get("sourceRankMeta") or {})
    ]
    assert ranks and min(ranks) > 5000
    assert vr.native_vs_hill(base, old).get("idpTradeCalc", {}).get("notComparableRankMoved")


def test_corrected_patch_keeps_idptc_value_direct_and_ktc_on_its_own_rank(raw, base):
    c2 = vr.build(raw, vr.native_values_as_ranks_spec())
    before = {r["displayName"]: r for r in base["playersArray"]}
    checked = 0
    for row in c2["playersArray"]:
        meta = row.get("sourceRankMeta") or {}
        old = before[row["displayName"]].get("sourceRankMeta") or {}
        if "idpTradeCalc" in meta:
            assert meta["idpTradeCalc"]["effectiveRank"] == old["idpTradeCalc"]["effectiveRank"]
            assert meta["idpTradeCalc"].get("valueContributionPath") == old["idpTradeCalc"].get(
                "valueContributionPath"
            )
        for key in audit.KTC_KEYS:
            m = meta.get(key)
            if (
                not m
                or row.get("position") == "TE"
                or m.get("valueContributionPath") != "rank_hill"
            ):
                continue
            expected = audit.hill_value(m["effectiveRank"], curve_for_pool(m["rankCoordinatePool"]))
            assert abs(m["valueContribution"] - expected) <= 1
            checked += 1
    assert checked > 0
    assert dc._VALUE_BASED_SOURCES >= {"ktcCrowdSfTep", "ktcTradesSfTep", "idpTradeCalc"}


# ── diagnostic seams restore and are exact at identity ─────────────────────────


def test_identity_csv_override_and_incumbent_threshold_change_nothing(raw, base, tmp_path):
    paths = {}
    for key in audit.KTC_KEYS:
        dst = tmp_path / f"{key}.csv"
        audit.write_mapped_csv(audit.CSV_DIR / f"{key}.csv", dst, lambda v: v)
        paths[key] = dst
    before = (dict(dc._SOURCE_CSV_PATHS), dc._hampel_filter_per_player)
    same_csv = vr.build(raw, vr.csv_override_spec(paths))
    same_floor = vr.build(raw, vr.hampel_threshold_spec(dc._HAMPEL_MIN_THRESHOLD))
    assert vr.board_diff(base, same_csv)["rowsChanged"] == 0
    assert vr.board_hash(same_floor) == vr.board_hash(base)
    assert (dict(dc._SOURCE_CSV_PATHS), dc._hampel_filter_per_player) == before


def test_a_lower_floor_can_only_exclude_more(raw, base):
    lower = vr.build(raw, vr.hampel_threshold_spec(500.0))
    assert (
        audit.hampel_census(lower)["observationsExcluded"]
        >= audit.hampel_census(base)["observationsExcluded"]
    )


# ── population / scale decomposition ───────────────────────────────────────────


def test_scale_population_decomposition_is_an_identity(base):
    obs = audit.scale_population_observations(base, audit.vendor_player_values())
    offense = [o for o in obs if o["assetClass"] == "offense" and o.get("ratioPop")]
    assert offense
    for o in offense:
        assert o["ratioLive"] == pytest.approx(o["ratioPop"] * o["populationFactor"], rel=1e-9)
        if o["source"] in audit.KTC_KEYS:
            # Removing picks from the pool can only move a player UP.
            assert o["popRank"] <= o["liveRank"]
    picks = [o for o in obs if o["assetClass"] == "pick"]
    assert all(not o["comparable"] and o.get("ratioPop") is None for o in picks)
    assert all(
        o["circular"] for o in obs if o["source"] == "idpTradeCalc" and o["assetClass"] == "idp"
    )


def test_disagreement_ranks_are_counted_over_the_same_rows(raw, base):
    loo = vr.build(raw, {"disable": list(audit.KTC_KEYS)})
    d = audit.loo_disagreement(base, loo, "ktcCrowdSfTep")
    assert d["rows"] > 0
    # Same population on both sides => the rank ratios' geometric mean sits near 1
    # unless the source genuinely reorders; it can never be driven by coverage.
    medians = [v["median"] for v in d["rankRatioByBand"].values() if v.get("n")]
    assert all(math.isfinite(m) and m > 0 for m in medians)
    rookie = next(s["key"] for s in dc._RANKING_SOURCES if s.get("needs_rookie_translation"))
    assert audit.loo_disagreement(base, base, rookie)["status"] == "non_comparable_rookie_only_list"


# ── post-hoc c3 (added at review) ──────────────────────────────────────────────


def test_c3_prices_ktc_players_by_players_only_rank_and_keeps_picks_value_direct(raw, base):
    seams = (dc._partition_value_source_ranges, dc._apply_pick_year_discount_to_blend)
    with audit.ktc_players_rank_hill_patch() as stats:
        c3 = vr.build(raw)
    # Both seams restored, the patch fired, and every rewrite was undone.
    assert (dc._partition_value_source_ranges, dc._apply_pick_year_discount_to_blend) == seams
    assert stats["partitionCalls"] == 1
    assert all(n > 0 for n in stats["rowsRewritten"].values())
    assert stats["restored"] == sum(stats["rowsRewritten"].values())
    check = audit.c3_contribution_check(base, c3)
    assert check["ok"], check
    for key in audit.KTC_KEYS:
        assert check[key]["playerRowsMatchHillPlayersOnlyRank"] > 0
        assert check[key]["pickRowsUnchanged"] > 0
    # A different board from c2 (players-only rank, picks value-direct) ...
    c2 = vr.build(raw, vr.native_values_as_ranks_spec())
    assert vr.board_hash(c3) != vr.board_hash(c2)
    # ... and outside the patch the incumbent is untouched.
    assert vr.board_hash(vr.build(raw)) == vr.board_hash(base)


def test_c3_vote_is_never_below_hill_at_the_live_rank(raw):
    with audit.ktc_players_rank_hill_patch():
        c3 = vr.build(raw)
    off = curve_for_pool("offense")
    checked = 0
    for row in c3["playersArray"]:
        if row.get("assetClass") != "offense":
            continue
        for key in audit.KTC_KEYS:
            m = (row.get("sourceRankMeta") or {}).get(key)
            if not m or m.get("valueContributionPath") != "value_direct":
                continue
            # Removing picks can only move a player UP, and Hill decreases in rank.
            assert m["valueContribution"] >= audit.hill_value(m["effectiveRank"], off) - 1
            checked += 1
    assert checked > 0


# ── DLF native values (added at review) ────────────────────────────────────────


def test_dlf_join_probe_stamps_dlf_values_without_moving_the_board(raw, base):
    if not (audit.REPO_ROOT / audit.DLF_VALUES_CSV_REL).exists():
        pytest.skip("no DLF Values CSV")
    before = dict(dc._SOURCE_CSV_PATHS)
    probe = vr.build(raw, audit.dlf_join_probe_spec())
    assert dict(dc._SOURCE_CSV_PATHS) == before
    assert audit.DLF_VALUES not in {s.get("key") for s in dc._RANKING_SOURCES}
    stamped = [
        r
        for r in probe["playersArray"]
        if (r.get("canonicalSiteValues") or {}).get(audit.DLF_VALUES)
    ]
    assert stamped and all(r.get("assetClass") == "offense" for r in stamped)
    assert vr.board_hash(probe) == vr.board_hash(base)


def test_dlf_family_voters_are_the_dlf_rank_family():
    voters = audit.dlf_family_voters()
    assert "dlfSf" in voters and audit.DLF_VALUES not in voters


def test_post_hoc_additions_are_not_part_of_the_predeclaration():
    assert "c3_ktc_players_rank_hill" not in audit.DECLARATION["candidates"]
    assert "c3_ktc_players_rank_hill" in audit.POST_HOC_ADDITIONS["candidates"]
