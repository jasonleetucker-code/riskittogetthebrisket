"""``scripts.faab_heat_backtest`` — descriptive-only trending-velocity
backtest. Every test seeds the real capture path so the join logic is
exercised against the actual contracts, not a stub.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from scripts.faab_heat_backtest import MIN_SAMPLE_FOR_CORRELATION, _created_at_ms, build_report
from src.retention import evidence_store

T0 = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    evidence_store._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "evidence.sqlite"
    yield path
    evidence_store._reset_setup_cache_for_tests()


def _observe(db, *, at: datetime, counts: dict[str, int]) -> None:
    evidence_store.observe_trending_snapshot(
        {"fetchedAt": at.isoformat(), "counts": counts, "lookbackHours": 24}, path=db
    )


def _claim(player_id: str, *, bid_pct: float, created_at_s: int) -> dict:
    return {"playerId": player_id, "bid": 5, "bidPct": bid_pct, "createdAt": created_at_s}


def _payload(claims: list[dict]) -> dict:
    return {"schemaVersion": 1, "seasons": [{"season": "2026", "adds": claims}]}


# ── _created_at_ms: the temporal-integrity guard ────────────────────────


def test_zero_created_at_is_treated_as_unknown_never_epoch():
    assert _created_at_ms(0) is None


def test_negative_created_at_is_treated_as_unknown():
    assert _created_at_ms(-5) is None


def test_none_created_at_is_treated_as_unknown():
    assert _created_at_ms(None) is None


def test_a_plausible_seconds_value_is_normalized_to_milliseconds():
    seconds = int(T0.timestamp())
    assert _created_at_ms(seconds) == seconds * 1000


def test_an_already_millisecond_value_passes_through():
    ms = int(T0.timestamp() * 1000)
    assert _created_at_ms(ms) == ms


# ── build_report ─────────────────────────────────────────────────────


def test_empty_bid_history_reports_zero_claims_not_an_error(db):
    report = build_report(_payload([]), path=db)

    assert report["totalClaims"] == 0
    for entry in report["windows"].values():
        assert entry["status"] == "insufficient_sample"


def test_a_claim_with_zero_created_at_is_excluded_and_counted(db):
    _observe(db, at=T0, counts={"4034": 100})
    claims = [_claim("4034", bid_pct=10.0, created_at_s=0)]

    report = build_report(_payload(claims), path=db)

    assert report["totalClaims"] == 1
    assert report["undatedClaimsExcluded"] == 1


def test_a_claim_whose_player_has_no_trending_observations_is_not_joined(db):
    # No observations recorded at all -- the claim exists but contributes
    # no (velocity, bidPct) pair to any window.
    claims = [_claim("9999", bid_pct=10.0, created_at_s=int(T0.timestamp()))]

    report = build_report(_payload(claims), path=db)

    assert report["totalClaims"] == 1
    assert report["undatedClaimsExcluded"] == 0
    for entry in report["windows"].values():
        assert entry["sampleSize"] == 0


def test_below_minimum_sample_reports_insufficient_sample_not_a_number(db):
    _observe(db, at=T0 - timedelta(hours=6), counts={"4034": 10})
    _observe(db, at=T0, counts={"4034": 20})
    claims = [_claim("4034", bid_pct=15.0, created_at_s=int(T0.timestamp()))]

    report = build_report(_payload(claims), windows_hours=(6,), path=db)

    entry = report["windows"]["6h"]
    assert entry["sampleSize"] == 1
    assert entry["status"] == "insufficient_sample"
    assert entry["correlation"] is None


def test_crossing_the_sample_threshold_reports_a_correlation(db):
    claims = []
    for i in range(MIN_SAMPLE_FOR_CORRELATION):
        pid = str(4000 + i)
        instant = T0 + timedelta(minutes=i)
        _observe(db, at=instant - timedelta(hours=6), counts={pid: 10})
        _observe(db, at=instant, counts={pid: 10 + i})
        claims.append(_claim(pid, bid_pct=float(i), created_at_s=int(instant.timestamp())))

    report = build_report(_payload(claims), windows_hours=(6,), path=db)

    entry = report["windows"]["6h"]
    assert entry["sampleSize"] == MIN_SAMPLE_FOR_CORRELATION
    assert entry["status"] == "descriptive_only"
    assert entry["correlation"] is not None
    # Constructed as a perfect linear relationship (delta == bidPct == i).
    assert entry["correlation"] == pytest.approx(1.0, abs=1e-6)


def test_a_claim_missing_bid_pct_is_skipped_not_crashed(db):
    _observe(db, at=T0, counts={"4034": 100})
    claims = [{"playerId": "4034", "bid": 5, "bidPct": None, "createdAt": int(T0.timestamp())}]

    report = build_report(_payload(claims), path=db)

    assert report["totalClaims"] == 1
    for entry in report["windows"].values():
        assert entry["sampleSize"] == 0
