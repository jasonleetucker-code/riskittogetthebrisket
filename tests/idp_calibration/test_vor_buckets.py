from __future__ import annotations

from src.idp_calibration.buckets import DEFAULT_BUCKETS, bucketize
from src.idp_calibration.stats_adapter import PlayerSeason
from src.idp_calibration.vor import (
    build_universe,
    compute_vor,
    score_universe,
)


def _universe():
    out = []
    for i in range(40):
        out.append(
            PlayerSeason(
                player_id=f"p{i}",
                name=f"Player {i}",
                position="DL",
                games=16,
                stats={"idp_tkl_solo": 40 - i, "idp_sack": max(0, 8 - i / 5)},
            )
        )
    return out


def test_same_universe_rescored_by_both_weight_sets():
    universe = _universe()
    weights_a = {"idp_tkl_solo": 1.0, "idp_sack": 4.0}
    weights_b = {"idp_tkl_solo": 2.0, "idp_sack": 2.0}
    scored = score_universe(universe, weights_a, weights_b)
    # Invariant: every input player appears exactly once under both scorings.
    assert {s.player_id for s in scored} == {p.player_id for p in universe}
    assert len(scored) == len(universe)
    top = max(scored, key=lambda s: s.points_test)
    assert top.points_test != top.points_mine


def test_compute_vor_yields_position_ranks():
    universe = _universe()
    weights_a = {"idp_tkl_solo": 1.0, "idp_sack": 4.0}
    weights_b = {"idp_tkl_solo": 2.0, "idp_sack": 2.0}
    scored = score_universe(universe, weights_a, weights_b)
    rows = compute_vor(scored, {"DL": 10.0}, {"DL": 14.0})
    ranks = sorted({r.rank_test for r in rows})
    assert ranks[0] == 1
    assert ranks[-1] == len(universe)


def test_bucketize_merges_small_buckets_and_reports_merge():
    universe = _universe()[:15]  # only 15 players — tail buckets will be small
    weights = {"idp_tkl_solo": 1.0}
    scored = score_universe(universe, weights, weights)
    rows = compute_vor(scored, {"DL": 5.0}, {"DL": 5.0})
    buckets = bucketize(rows, "DL", buckets=DEFAULT_BUCKETS, min_bucket_size=3)
    merged_labels = [m for b in buckets for m in b.merged_from]
    # With 15 DLs and default buckets, later buckets should merge into earlier ones.
    assert any(merged_labels), "Expected at least one merge"


def test_bucketize_blended_center_equals_mean_plus_median_over_2():
    rows = []
    for i in range(10):
        rows.append(
            type(
                "VorRow",
                (),
                dict(
                    player_id=str(i),
                    name=str(i),
                    position="LB",
                    games=16,
                    points_test=0.0,
                    points_mine=0.0,
                    vor_test=float(i),
                    vor_mine=float(i) + 5,
                    rank_test=i + 1,
                    rank_mine=i + 1,
                ),
            )(),
        )
    buckets = bucketize(rows, "LB", buckets=[(1, 10)], min_bucket_size=3)
    assert len(buckets) == 1
    # mean of 0..9 = 4.5, median = 4.5, blended = 4.5 for vor_test
    assert buckets[0].center_vor_test == 4.5
    assert buckets[0].center_vor_mine == 9.5
