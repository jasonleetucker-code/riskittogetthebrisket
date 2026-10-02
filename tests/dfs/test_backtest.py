"""Backtest: chronological, pre-lock only, truth revealed after forecasts, realized payouts exact."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.dfs import backtest, pit, store
from src.dfs.contests import Contest, PayoutBand, parse_contest
from src.dfs.imports import apply_projection_csv, parse_draftkings_salaries
from src.dfs.rules import get_ruleset

FIX = Path(__file__).parent / "fixtures"
DK = get_ruleset("draftkings.nfl.classic")
LOCK = datetime(2026, 10, 4, 17, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DFS_DATA_DIR", str(tmp_path))


def test_realized_payouts_rank_against_the_real_field_with_exact_ties_and_our_entries():
    c = Contest(
        name="x",
        platform="draftkings",
        sport="nfl",
        format="classic",
        entry_fee_cents=500,
        tie_rule="split_positions",
        ladder=[PayoutBand(1, 1, 10_000), PayoutBand(2, 2, 2_000), PayoutBand(3, 3, 1_000)],
    )
    field = [(150.0, 1), (120.0, 2), (90.0, 5)]
    out = backtest.realized_payouts(c, field, [160.0, 120.0, None])
    assert out[0] == {"state": "exact", "rank": 1, "tiedWith": 0, "payoutCents": 10_000}
    # 120 ties the two field 120s, below 150 and our 160: ranks 3-5 split ($10 / 3, not whole cents).
    assert out[1]["rank"] == 3 and out[1]["tiedWith"] == 2 and out[1]["state"] == "exact_fraction"
    assert out[2] == {"state": "unscorable"}


def test_unscored_player_makes_a_lineup_unscorable_never_zero():
    assert backtest.realized_lineup_points(["a", "b"], {"a": {"points": 10.0}}, DK) is None


def _setup(owner="o"):
    athletes, _ = parse_draftkings_salaries(
        (FIX / "synthetic_dk_nfl_classic_salaries.csv").read_text(encoding="utf-8")
    )
    apply_projection_csv(
        athletes, (FIX / "synthetic_dk_nfl_classic_projections.csv").read_text(encoding="utf-8")
    )
    body = {"athletes": [a.to_dict() for a in athletes]}
    meta = store.put_snapshot(owner, DK.key, "h" * 64, body)
    snap = store.get_snapshot(owner, meta["id"])
    pit.capture_snapshot(owner, snap)
    return athletes, snap


def test_backtest_uses_only_pre_lock_inputs_even_when_a_perfect_late_source_exists():
    athletes, snap = _setup()
    actual = {a.player_id: 5.0 + (i % 7) * 4.0 for i, a in enumerate(athletes)}
    # A "source" recorded AFTER lock that matches the truth exactly — it must not be used.
    late = LOCK + timedelta(hours=4)
    pit.record(
        "o",
        snap["id"],
        [
            {
                "playerId": pid,
                "kind": "ownership",
                "source": "late_truth",
                "observedAt": late.isoformat(),
                "value": v,
            }
            for pid, v in actual.items()
        ],
        recorded_at=late.isoformat(),
    )
    res = store.put_result(
        "o",
        snap["id"],
        {
            "realized": {pid: {"ownership": v, "points": 10.0} for pid, v in actual.items()},
            "pointsCounts": [(150.0, 3)],
            "unscoredEntries": 0,
        },
    )
    out = backtest.run("o", [{"resultId": res["resultId"]}])
    row = out["perContest"][0]
    ensemble = row["scores"]["ownership.ensemble"]
    assert ensemble["mae"] > 0.5  # the perfect late source was NOT available at lock
    assert "late_truth" not in str(row["scores"].keys())
    assert set(out["summary"]) >= {
        "ownership.structural@prior",
        "ownership.field_implied",
        "ownership.ensemble",
    }
    assert out["summary"]["ownership.ensemble"]["n"] == len(athletes)
    evals = pit.list_evaluations("o", "backtest")
    assert {e["subject"] for e in evals} >= {"ownership.ensemble"} and evals[0]["scope"][
        "windowStart"
    ]


def test_contests_are_replayed_in_lock_order_and_unknown_locks_are_skipped():
    _, snap_a = _setup()
    _, snap_b = _setup()
    early = (LOCK - timedelta(days=7)).isoformat()
    with pit._connect() as conn:  # make B's slate lock a week earlier than A's
        conn.execute(
            "UPDATE dfs_pit_slates SET lock_at=? WHERE snapshot_id=?",
            (pit._utc(early), snap_b["id"]),
        )
    ra = store.put_result(
        "o", snap_a["id"], {"realized": {}, "pointsCounts": [], "unscoredEntries": 0}
    )
    rb = store.put_result(
        "o", snap_b["id"], {"realized": {}, "pointsCounts": [], "unscoredEntries": 0}
    )
    out = backtest.run(
        "o", [{"resultId": ra["resultId"]}, {"resultId": rb["resultId"]}], record=False
    )
    # Snapshot B's inputs were imported AFTER its (rewound) lock, so its as-of view is empty — but it
    # is still replayed FIRST, in lock order.
    assert [r["resultId"] for r in out["perContest"]] == [rb["resultId"], ra["resultId"]]
    _, snap_c = _setup()
    with pit._connect() as conn:
        conn.execute("UPDATE dfs_pit_slates SET lock_at=NULL WHERE snapshot_id=?", (snap_c["id"],))
    rc = store.put_result(
        "o", snap_c["id"], {"realized": {}, "pointsCounts": [], "unscoredEntries": 0}
    )
    out = backtest.run("o", [{"resultId": rc["resultId"]}], record=False)
    assert out["contests"] == 0 and out["skipped"] == [
        {"resultId": rc["resultId"], "reason": "lock_unknown"}
    ]


def test_portfolio_replay_realizes_optimizer_and_baseline_profits_paired():
    athletes, snap = _setup()
    contest = parse_contest(
        {
            "name": "Mini",
            "platform": "draftkings",
            "sport": "nfl",
            "format": "classic",
            "entryFee": "5",
            "capacity": 200,
            "tieRule": "split_positions",
            "payoutText": "1 $300\n2 $100\n3-20 $10",
        }
    )
    crec = store.put_contest("o", None, {"contest": contest.to_dict(), "report": {}})
    realized = {
        a.player_id: {"ownership": 5.0, "points": float(a.projection or 0)} for a in athletes
    }
    res = store.put_result(
        "o",
        snap["id"],
        {
            "realized": realized,
            "pointsCounts": [(200.0, 5), (150.0, 50), (100.0, 144)],
            "unscoredEntries": 0,
        },
    )
    out = backtest.run(
        "o",
        [{"resultId": res["resultId"], "contestId": crec["contestId"]}],
        replay_portfolio=True,
        entries=2,
        sims=150,
        field_sample=200,
        allow_priors=True,
    )
    replay = out["perContest"][0]["replay"]
    assert replay["realizedProfitCents"] is not None and replay["baselineRealized"]
    rp = out["realizedProfitCents"]
    assert (
        rp["optimizer"]["n"] == 1
        and rp["baseline"]["n"] == 1
        and rp["optimizerMinusBaseline"]["n"] == 1
    )
    assert rp["optimizer"]["ci95Cents"] is None  # one contest: no interval, no claim
