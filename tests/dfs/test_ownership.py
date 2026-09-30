"""Ownership: structural baseline, source ensemble, overrides, evaluation — as-of, never leaking."""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dfs import metrics, ownership, pit
from src.dfs.imports import apply_projection_csv, parse_draftkings_salaries
from src.dfs.rules import get_ruleset

FIX = Path(__file__).parent / "fixtures"
DK = get_ruleset("draftkings.nfl.classic")
LOCK = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def _athletes():
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    apply_projection_csv(
        athletes, (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    )
    return athletes


# ── metrics ──────────────────────────────────────────────────────────────


def test_rank_correlation_ties_and_undefined_cases():
    assert metrics.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert metrics.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == -1.0
    assert metrics.spearman([1, 1, 1], [1, 2, 3]) is None  # no variation: undefined, not 0
    assert metrics.spearman([1, 2], [1, 2]) is None


def test_point_metrics_ci_is_seeded_and_small_samples_are_flagged():
    pairs = [(10.0, 8.0), (5.0, 6.0), (20.0, 25.0), (1.0, 1.0), (3.0, 2.0), (15.0, 9.0)]
    a, b = metrics.point_forecast(pairs), metrics.point_forecast(pairs)
    assert a == b and a["n"] == 6 and a["smallSample"] is True
    assert a["mae"] == pytest.approx((2 + 1 + 5 + 0 + 1 + 6) / 6, abs=1e-4)
    assert a["bias"] == pytest.approx((2 - 1 - 5 + 0 + 1 + 6) / 6, abs=1e-4)
    lo, hi = a["maeCi95"]
    assert lo <= a["mae"] <= hi


def test_ownership_scorecard_scores_only_players_present_in_both():
    card = metrics.ownership_scorecard(
        {"a": 10.0, "b": 20.0, "c": 5.0}, {"a": 12.0, "b": 18.0, "z": 3.0}
    )
    assert card["n"] == 2 and card["forecastOnly"] == 1 and card["actualOnly"] == 1


# ── structural baseline ─────────────────────────────────────────────────


def test_structural_totals_caps_and_missing_is_not_zero():
    athletes = _athletes()
    athletes[0].projection = None
    out = ownership.structural_baseline(athletes, DK)
    known = [v for v in out.values() if v is not None]
    assert out[athletes[0].player_id] is None
    # Exact before rounding; each of ~84 values is rounded to 4 dp (<= 0.00005 each).
    assert sum(known) == pytest.approx(100.0 * len(DK.slots), abs=0.005)
    assert max(known) <= 100.0 + 1e-9 and min(known) > 0


def test_structural_is_monotone_in_value_within_a_position():
    athletes = [a for a in _athletes() if a.positions == ["QB"]]
    out = ownership.structural_baseline(athletes, DK, {"bv": 1.5, "bp": 0.0})
    by_value = sorted(athletes, key=lambda a: a.projection / a.salary)
    shares = [out[a.player_id] for a in by_value]
    assert shares == sorted(shares)


def test_fit_recovers_known_parameters_on_synthetic_truth():
    rnd = random.Random(3)
    samples = []
    for _ in range(4):
        athletes = _athletes()
        for a in athletes:
            a.projection = round(a.projection * rnd.uniform(0.7, 1.3), 2)
        truth = ownership.structural_baseline(athletes, DK, {"bv": 2.0, "bp": 0.5})
        samples.append(
            {
                "players": athletes,
                "ruleset": DK.id,
                "actual": {k: v for k, v in truth.items() if v is not None},
            }
        )
    fit = ownership.fit_structural(samples, get_ruleset)
    assert fit["params"] == {"bv": 2.0, "bp": 0.5} and fit["trainingMae"] < 1e-6
    assert "holdout" in fit["note"]


# ── forecast (as-of) ────────────────────────────────────────────────────


def _snapshot(athletes):
    return {
        "id": "snap_1",
        "ruleset": DK.key,
        "contentHash": "h" * 64,
        "createdAt": (LOCK - timedelta(days=2)).isoformat(),
        "body": {"athletes": [a.to_dict() for a in athletes]},
    }


def _own(pid, value, at, source):
    return {
        "playerId": pid,
        "kind": "ownership",
        "source": source,
        "observedAt": at.isoformat(),
        "value": value,
    }


def test_forecast_mixes_sources_baseline_and_overrides_with_labels_and_no_leakage():
    athletes = _athletes()
    snap = _snapshot(athletes)
    pit.capture_snapshot("o", snap)
    a, b, c, d = (x.player_id for x in athletes[:4])
    t = LOCK - timedelta(hours=3)
    pit.record(
        "o",
        "snap_1",
        [_own(a, 30.0, t, "srcA"), _own(a, 20.0, t, "srcB"), _own(b, 12.0, t, "srcA")],
        recorded_at=t.isoformat(),
    )
    # Stale: published two days before T.
    old = LOCK - timedelta(days=2)
    pit.record("o", "snap_1", [_own(d, 44.0, old, "srcOld")], recorded_at=old.isoformat())
    # Recorded after T: must not be visible at T.
    late = LOCK - timedelta(minutes=10)
    pit.record("o", "snap_1", [_own(c, 99.0, t, "srcA")], recorded_at=late.isoformat())
    fc = ownership.forecast("o", snap, DK, LOCK - timedelta(hours=1), overrides={b: 7.5})
    rows = fc["players"]
    assert rows[a] == {"ownership": 25.0, "method": "ensemble", "sources": ["srcA", "srcB"]}
    assert rows[b] == {"ownership": 7.5, "method": "owner_override"}
    assert rows[c]["method"] == "structural_baseline"  # the late value was not held at T
    assert rows[d]["method"] == "structural_baseline" and fc["staleSources"] == ["srcOld"]
    assert (
        fc["models"]["ownership.ensemble"]["weights"]["srcA"]["basis"]
        == "equal_insufficient_evidence"
    )
    with pytest.raises(pit.PitError):
        ownership.forecast("o", snap, DK, LOCK + timedelta(minutes=1))


def test_ensemble_weights_become_inverse_error_only_with_enough_evidence():
    pit.record_evaluation("o", "ownership", "srcA", {}, 80, {"mae": 2.0}, {})
    pit.record_evaluation("o", "ownership", "srcB", {}, 40, {"mae": 4.0}, {})
    w = ownership.source_weights("o", ["srcA", "srcB"])
    assert {v["basis"] for v in w.values()} == {"equal_insufficient_evidence"}  # srcB too thin
    pit.record_evaluation("o", "ownership", "srcB", {}, 40, {"mae": 4.0}, {})
    w = ownership.source_weights("o", ["srcA", "srcB"])
    assert w["srcA"]["weight"] == pytest.approx(2 / 3) and w["srcA"]["basis"] == "inverse_mae"


def test_evaluation_against_results_stores_scoped_scorecards_per_component():
    athletes = _athletes()
    snap = _snapshot(athletes)
    pit.capture_snapshot("o", snap)
    t = LOCK - timedelta(hours=3)
    pit.record(
        "o",
        "snap_1",
        [_own(x.player_id, 10.0, t, "srcA") for x in athletes[:20]],
        recorded_at=t.isoformat(),
    )
    realized = {
        x.player_id: {"ownership": 8.0 + i % 5, "points": 10.0} for i, x in enumerate(athletes)
    }
    out = ownership.evaluate_against_results("o", snap, DK, realized)
    assert (
        out["state"] == "evaluated"
        and out["scope"]["sport"] == "nfl"
        and out["scope"]["slateSize"] == "2-4"
    )
    assert out["sources"]["srcA"]["n"] == 20
    assert out["structuralBaseline"]["n"] == len(athletes)
    subjects = {e["subject"] for e in pit.list_evaluations("o", "ownership")}
    assert subjects == {"srcA", "model:ownership.structural@prior", "model:ownership.ensemble"}
