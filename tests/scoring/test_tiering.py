"""Tests for src.scoring.tiering.  Pins the pool-normalized-gap tier
walk, the fallback behavior when SD is zero, the grid-search fitter,
and drift detection."""

from __future__ import annotations

import json

from src.scoring import tiering


def _mk_rows(values_by_pos):
    rows = []
    for pos, vals in values_by_pos.items():
        for i, v in enumerate(vals):
            rows.append({"name": f"{pos}_{i}", "pos": pos, "rankDerivedValue": v})
    return rows


def test_single_player_position_becomes_tier_1():
    rows = _mk_rows({"QB": [9000.0]})
    tiers = tiering.detect_tiers(rows)
    assert tiers[0].tier_id == 1


def test_uniform_values_all_one_tier():
    """When every player has identical value, pooled SD is 0 →
    everyone in tier 1 (not everyone in their own tier)."""
    rows = _mk_rows({"QB": [9000.0, 9000.0, 9000.0, 9000.0]})
    tiers = tiering.detect_tiers(rows)
    tier_ids = {t.tier_id for t in tiers}
    assert tier_ids == {1}


def test_wide_value_gaps_produce_multiple_tiers():
    """Very spread-out values → multiple tiers."""
    rows = _mk_rows({"QB": [9800.0, 9000.0, 7000.0, 4000.0, 1000.0]})
    tiers = tiering.detect_tiers(rows, thresholds={"QB": 0.3})
    max_tier = max(t.tier_id for t in tiers)
    assert max_tier >= 2, f"expected >=2 tiers, got {max_tier}"


def test_lower_threshold_yields_more_tiers():
    rows = _mk_rows({"WR": [9800, 9400, 8800, 7900, 6500, 5000, 3500, 2000]})
    loose = tiering.detect_tiers(rows, thresholds={"WR": 0.5})
    tight = tiering.detect_tiers(rows, thresholds={"WR": 0.1})
    loose_count = max(t.tier_id for t in loose)
    tight_count = max(t.tier_id for t in tight)
    assert tight_count >= loose_count


def test_stamp_tiers_is_non_destructive():
    rows = _mk_rows({"RB": [9800, 9000, 5000]})
    before_snapshot = [dict(r) for r in rows]
    out = tiering.stamp_tiers_on_players(rows)
    # input unchanged
    assert rows == before_snapshot
    # output has tierId
    assert all("tierId" in r for r in out)
    # input order preserved
    assert [r["name"] for r in out] == [r["name"] for r in rows]


def test_stamp_tiers_stays_aligned_when_detect_drops_rows():
    """``detect_tiers`` DROPS rows it can't tier (non-dicts, and dicts
    with no position).  ``stamp_tiers_on_players`` used to zip the
    returned entries against ``rows`` BY INDEX, so any drop shifted the
    whole mapping and every later row inherited some other row's tier.

    Here the QB pool is [9000, 1000]: pool SD is 4000, the gap is
    8000, so the second QB's normalized gap is 2.0 — well past the
    0.35 QB threshold — and the two land in tiers 1 and 2.  With a
    non-dict at index 0 and a position-less row in the middle, the old
    index zip handed QB_0 the SECOND entry's tier and left QB_1
    unstamped.
    """
    qb0 = {"name": "QB_0", "pos": "QB", "rankDerivedValue": 9000}
    no_pos = {"name": "no_pos", "rankDerivedValue": 5000}
    qb1 = {"name": "QB_1", "pos": "QB", "rankDerivedValue": 1000}
    rows = [None, qb0, no_pos, qb1]

    out = tiering.stamp_tiers_on_players(rows)

    assert out[0] is None  # non-dicts pass through untouched
    by_name = {r["name"]: r for r in out if isinstance(r, dict)}
    assert by_name["QB_0"]["tierId"] == 1
    assert by_name["QB_1"]["tierId"] == 2
    # A row detect_tiers refused to tier must not be stamped at all.
    assert "tierId" not in by_name["no_pos"]


def test_pool_normalized_gap_is_named_for_what_it_computes():
    """The statistic is |tier mean − candidate| ÷ the POPULATION SD of
    the whole position pool.  That is not Cohen's d (which divides by
    the pooled SD of the two groups being compared), and calling it
    that in the code invited someone to "fix" the denominator.

    Pinned by name so the rename can't silently revert.
    """
    assert not hasattr(tiering, "_cohens_d")
    # 9000 vs 5000 against a pool SD of 2000 → 2.0.
    assert tiering._pool_normalized_gap(9000.0, 5000.0, 2000.0) == 2.0  # noqa: SLF001
    # Zero / negative SD is the cold-start guard, not a division.
    assert tiering._pool_normalized_gap(9000.0, 5000.0, 0.0) == 0.0  # noqa: SLF001


def test_each_position_tiers_start_at_1():
    """A new position always re-starts at tier 1 — tiers don't
    span positions."""
    rows = _mk_rows({"QB": [9800, 8000], "RB": [9900, 7000]})
    tiers = tiering.detect_tiers(rows)
    qb_tiers = {t.tier_id for t in tiers if t.position == "QB"}
    rb_tiers = {t.tier_id for t in tiers if t.position == "RB"}
    assert 1 in qb_tiers
    assert 1 in rb_tiers


def test_load_thresholds_from_config(tmp_path):
    cfg = tmp_path / "t.json"
    cfg.write_text(json.dumps({"thresholds": {"QB": 0.5, "RB": 0.15}}), encoding="utf-8")
    t = tiering.load_thresholds(cfg)
    assert t["QB"] == 0.5
    assert t["RB"] == 0.15
    # Unspecified positions fall back to defaults.
    assert t["WR"] == 0.22


def test_load_thresholds_accepts_flat_shape(tmp_path):
    cfg = tmp_path / "t.json"
    cfg.write_text(json.dumps({"QB": 0.4}), encoding="utf-8")
    t = tiering.load_thresholds(cfg)
    assert t["QB"] == 0.4


def test_load_thresholds_missing_returns_defaults(tmp_path):
    t = tiering.load_thresholds(tmp_path / "absent.json")
    assert t["QB"] == 0.35  # default


def test_load_thresholds_malformed_returns_defaults(tmp_path):
    cfg = tmp_path / "bad.json"
    cfg.write_text("{not valid", encoding="utf-8")
    t = tiering.load_thresholds(cfg)
    assert t["QB"] == 0.35


def test_grid_search_fits_something_reasonable():
    """With 30 QBs spread in value, the fitter should land on a
    threshold that produces 4–6 tiers."""
    import random

    random.seed(42)
    vals = sorted([random.gauss(5000, 2000) for _ in range(30)], reverse=True)
    rows = [
        {"name": f"QB_{i}", "pos": "QB", "rankDerivedValue": max(100, v)}
        for i, v in enumerate(vals)
    ]
    fit = tiering.fit_thresholds_grid_search(rows)
    assert "QB" in fit
    # Verify the fit actually produces in-range tier counts.
    tiers = tiering.detect_tiers(rows, thresholds=fit)
    count = max(t.tier_id for t in tiers)
    assert 4 <= count <= 6, f"fit produced {count} tiers, expected 4–6"


def test_drift_detection_under_tolerance_is_clean():
    old = {"QB": 0.30, "RB": 0.22}
    new = {"QB": 0.32, "RB": 0.23}  # ~6% and ~4.5% drift
    d = tiering.detect_threshold_drift(old, new, tolerance_pct=0.15)
    assert d["hasDrift"] is False


def test_drift_detection_over_tolerance_flags():
    old = {"QB": 0.30, "RB": 0.22}
    new = {"QB": 0.50, "RB": 0.22}  # 66% drift
    d = tiering.detect_threshold_drift(old, new, tolerance_pct=0.15)
    assert d["hasDrift"] is True
    assert d["maxDriftPct"] >= 0.15


def test_drift_detection_handles_new_position():
    """Adding a position that didn't exist before shouldn't crash —
    the drift entry for it is None."""
    old = {"QB": 0.30}
    new = {"QB": 0.30, "LB": 0.30}
    d = tiering.detect_threshold_drift(old, new)
    assert d["positions"]["LB"] is None
