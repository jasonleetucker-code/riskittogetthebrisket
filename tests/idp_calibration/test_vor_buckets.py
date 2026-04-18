from __future__ import annotations

from src.idp_calibration.buckets import DEFAULT_BUCKETS, bucketize
from src.idp_calibration.stats_adapter import PlayerSeason
from src.idp_calibration.vor import (
    build_universe,
    compute_vor,
    score_universe,
    trim_to_top_n_per_position,
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


def test_trim_to_top_n_keeps_only_top_n_per_position():
    # Mix of DL/LB/DB so the per-position slice is non-trivial.
    universe = []
    for i in range(20):
        universe.append(
            PlayerSeason(
                player_id=f"p{i}",
                name=f"P{i}",
                position=["DL", "LB", "DB"][i % 3],
                games=16,
                stats={"idp_tkl_solo": 50 - i},
            )
        )
    weights = {"idp_tkl_solo": 1.0}
    scored = score_universe(universe, weights, weights)
    trimmed = trim_to_top_n_per_position(scored, 2)
    # Each position should now have at most 2 survivors.
    by_pos = {"DL": 0, "LB": 0, "DB": 0}
    for s in trimmed:
        by_pos[s.position] += 1
    assert all(n <= 2 for n in by_pos.values())
    # Survivors are the highest-scoring per position, not the tail.
    for pos in ("DL", "LB", "DB"):
        pos_scored = [s for s in scored if s.position == pos]
        pos_trim = [s for s in trimmed if s.position == pos]
        pos_scored.sort(key=lambda x: x.points_test, reverse=True)
        assert {s.player_id for s in pos_trim} <= {
            s.player_id for s in pos_scored[:2]
        }


def test_trim_to_top_n_is_noop_when_falsy():
    universe = _universe()[:5]
    weights = {"idp_tkl_solo": 1.0}
    scored = score_universe(universe, weights, weights)
    assert len(trim_to_top_n_per_position(scored, None)) == len(scored)
    assert len(trim_to_top_n_per_position(scored, 0)) == len(scored)


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
