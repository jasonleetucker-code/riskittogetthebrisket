"""Resolved losing waiver bids improve owner-tendency prediction safely.

Sleeper does not expose another manager's pending blind bid before the
waiver run.  After processing, however, a failed waiver transaction can
carry the submitted ``settings.waiver_bid``.  That is useful evidence of
willingness to spend, but it is NOT a clearing price.

These tests pin the separation:

* completed wins continue to own the market-clearing distribution;
* completed + failed waiver claims own the manager-tendency sample;
* pending claims never enter history;
* legacy v1 rows without status metadata remain completed wins.
"""

from __future__ import annotations

import pytest

from src.trade import faab_history


def _league(budget=100):
    return {
        "settings": {"num_teams": 12, "waiver_budget": budget},
        "season": "2026",
        "previous_league_id": None,
    }


def _tx(*, bid, status="complete", tx_type="waiver", player="p1", roster_id=1):
    return {
        "transaction_id": f"{status}-{tx_type}-{player}-{bid}",
        "type": tx_type,
        "status": status,
        "settings": {"waiver_bid": bid},
        "adds": {player: roster_id},
        "roster_ids": [roster_id],
        "status_updated": 1_700_000_000,
    }


def _install(monkeypatch, transactions):
    rosters = [
        {"roster_id": 1, "owner_id": "owner-a"},
        {"roster_id": 2, "owner_id": "owner-b"},
    ]

    def fake_get(url: str):
        if "/transactions/" in url:
            week = int(url.rsplit("/", 1)[-1])
            return transactions if week == 1 else []
        if url.endswith("/rosters"):
            return rosters
        return _league()

    monkeypatch.setattr(faab_history, "_get", fake_get)


def _row(pct, *, owner, status="complete", tx_type="waiver", week=1):
    return {
        "bidPct": float(pct),
        "ownerId": owner,
        "status": status,
        "type": tx_type,
        "week": week,
    }


def test_fetch_keeps_resolved_failed_waiver_bids_but_not_pending_or_failed_free_agents(monkeypatch):
    _install(
        monkeypatch,
        [
            _tx(bid=18, status="complete", tx_type="waiver", player="won", roster_id=1),
            _tx(bid=31, status="failed", tx_type="waiver", player="lost", roster_id=2),
            _tx(bid=44, status="pending", tx_type="waiver", player="secret", roster_id=2),
            _tx(bid=12, status="failed", tx_type="free_agent", player="fa-fail", roster_id=2),
        ],
    )

    out = faab_history.fetch_bid_history("L1")
    rows = out["seasons"][0]["adds"]

    assert {(r["playerId"], r["status"], r["bid"]) for r in rows} == {
        ("won", "complete", 18),
        ("lost", "failed", 31),
    }
    assert out["schemaVersion"] == 2
    assert out["totalAdds"] == 1, "legacy totalAdds must still mean completed acquisitions"
    assert out["totalBidAttempts"] == 2
    assert out["totalFailedWaiverBids"] == 1
    assert next(r for r in rows if r["playerId"] == "lost")["ownerId"] == "owner-b"


def test_losing_bids_expand_owner_sample_without_polluting_clearing_prices():
    payload = {
        "schemaVersion": 2,
        "seasons": [
            {
                "season": "2026",
                "adds": [
                    _row(10, owner="a", status="complete"),
                    _row(20, owner="b", status="complete"),
                    _row(90, owner="a", status="failed"),
                    _row(80, owner="a", status="failed"),
                ],
            }
        ],
    }

    priors = faab_history.summarize_bid_history(payload)

    # Clearing-price statistics are wins only: [10, 20].
    assert priors.sample_size == 2
    assert priors.median_pct == pytest.approx(15.0)
    assert priors.mean_pct == pytest.approx(15.0)
    assert priors.max_pct == pytest.approx(20.0)

    # Manager tendency sees all resolved blind waiver attempts.
    assert priors.bid_attempt_sample_size == 4
    assert priors.failed_bid_sample_size == 2
    assert priors.owner_attempt_sample["a"] == 3
    assert priors.owner_sample["a"] == 1
    assert priors.owner_attempt_aggression["a"] > 1.0


def test_owner_aggression_prefers_three_resolved_attempts_over_one_winning_bid():
    payload = {
        "schemaVersion": 2,
        "seasons": [
            {
                "season": "2026",
                "adds": [
                    _row(10, owner="a", status="complete"),
                    _row(20, owner="a", status="failed"),
                    _row(30, owner="a", status="failed"),
                    _row(0, owner="b", status="complete"),
                    _row(0, owner="b", status="failed"),
                    _row(0, owner="b", status="failed"),
                ],
            }
        ],
    }

    priors = faab_history.summarize_bid_history(payload)
    factor, low_sample = faab_history.owner_aggression_factor(priors, "a", min_sample=3)

    # Attempt means: owner A = 20, owner B = 0, league = 10 => 2.0x.
    # The old wins-only path would have seen just one A win and returned
    # neutral/low-sample instead.
    assert factor == pytest.approx(2.0)
    assert low_sample is False


def test_v1_rows_without_status_keep_the_legacy_winning_bid_behavior():
    payload = {
        "schemaVersion": 1,
        "seasons": [
            {
                "season": "2025",
                "adds": [
                    {"bidPct": 5.0, "ownerId": "a", "type": "waiver", "week": 1},
                    {"bidPct": 10.0, "ownerId": "a", "type": "waiver", "week": 2},
                    {"bidPct": 15.0, "ownerId": "a", "type": "waiver", "week": 3},
                    {"bidPct": 10.0, "ownerId": "b", "type": "waiver", "week": 1},
                ],
            }
        ],
    }

    priors = faab_history.summarize_bid_history(payload)
    assert priors.sample_size == 4
    assert priors.bid_attempt_sample_size == 4
    assert priors.failed_bid_sample_size == 0
    factor, low_sample = faab_history.owner_aggression_factor(priors, "a", min_sample=3)
    assert low_sample is False
    assert factor == pytest.approx(priors.owner_attempt_aggression["a"])
