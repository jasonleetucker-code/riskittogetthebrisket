"""``src.trade.faab_heat_metrics.trending_velocity`` — a C4-FAAB-01
prerequisite. Every test seeds the real capture path
(``src.retention.evidence_store.observe_trending_snapshot``) rather than
poking a private schema, so these tests exercise the actual read/write
contract the eventual backtest will depend on.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.retention import evidence_store
from src.trade.faab_heat_metrics import (
    REASON_NO_CURRENT_OBSERVATION,
    REASON_NO_PAST_OBSERVATION,
    trending_velocity,
)

PLAYER = "4034"
T0 = datetime(2026, 8, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(tmp_path):
    evidence_store._reset_setup_cache_for_tests()
    path = tmp_path / "retention" / "evidence.sqlite"
    yield path
    evidence_store._reset_setup_cache_for_tests()


def _observe(db, *, at: datetime, counts: dict[str, int], lookback_hours: int = 24) -> None:
    evidence_store.observe_trending_snapshot(
        {"fetchedAt": at.isoformat(), "counts": counts, "lookbackHours": lookback_hours},
        path=db,
    )


def _ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_no_observations_at_all_reports_every_window_unavailable(db):
    result = trending_velocity(PLAYER, _ms(T0), path=db)

    assert result["current"] is None
    for window in result["windows"].values():
        assert window["deltaCount"] is None
        assert window["reason"] == REASON_NO_CURRENT_OBSERVATION


def test_observations_only_after_as_of_are_ignored_not_used(db):
    # An observation recorded AFTER the instant being asked about must never
    # be treated as "current" -- that would be a lookahead leak.
    _observe(db, at=T0 + timedelta(hours=1), counts={PLAYER: 500})

    result = trending_velocity(PLAYER, _ms(T0), path=db)

    assert result["current"] is None


def test_a_window_with_no_qualifying_past_observation_is_explicit(db):
    _observe(db, at=T0, counts={PLAYER: 100})

    result = trending_velocity(PLAYER, _ms(T0), windows_hours=(6,), path=db)

    assert result["current"]["count"] == 100
    assert result["windows"]["6h"]["deltaCount"] is None
    assert result["windows"]["6h"]["reason"] == REASON_NO_PAST_OBSERVATION


def test_a_real_delta_is_computed_when_both_anchors_resolve(db):
    _observe(db, at=T0 - timedelta(hours=6), counts={PLAYER: 40})
    _observe(db, at=T0, counts={PLAYER: 100})

    result = trending_velocity(PLAYER, _ms(T0), windows_hours=(6,), path=db)

    assert result["windows"]["6h"]["deltaCount"] == 60
    assert result["windows"]["6h"]["pastCount"] == 40


def test_a_narrow_window_reuses_the_nearest_prior_observation_and_says_so(db):
    # Only a 48h-old observation is available. Consistent with this repo's
    # own established precedent (src.history.asof's nearest-prior lookups,
    # and src/retention's explicit "no gap threshold" design -- a magic
    # cutoff would stand in for a cadence guarantee that doesn't exist),
    # the 6h window still resolves via nearest-prior rather than refusing --
    # but it must be labelled nearest-prior, and the actual anchor exposed,
    # so a caller can see this is not a true 6h reading.
    _observe(db, at=T0 - timedelta(hours=48), counts={PLAYER: 10})
    _observe(db, at=T0, counts={PLAYER: 90})

    result = trending_velocity(PLAYER, _ms(T0), windows_hours=(6, 48), path=db)

    assert result["windows"]["6h"]["deltaCount"] == 80
    assert result["windows"]["6h"]["fidelity"] == "nearest-prior"
    assert result["windows"]["48h"]["deltaCount"] == 80
    assert result["windows"]["48h"]["fidelity"] == "exact"


def test_multiple_windows_each_resolve_independently(db):
    _observe(db, at=T0 - timedelta(hours=48), counts={PLAYER: 5})
    _observe(db, at=T0 - timedelta(hours=24), counts={PLAYER: 20})
    _observe(db, at=T0 - timedelta(hours=12), counts={PLAYER: 50})
    _observe(db, at=T0 - timedelta(hours=6), counts={PLAYER: 70})
    _observe(db, at=T0, counts={PLAYER: 100})

    result = trending_velocity(PLAYER, _ms(T0), path=db)

    assert result["windows"]["6h"]["deltaCount"] == 30
    assert result["windows"]["12h"]["deltaCount"] == 50
    assert result["windows"]["24h"]["deltaCount"] == 80
    assert result["windows"]["48h"]["deltaCount"] == 95


def test_an_observation_exactly_at_the_window_boundary_is_used(db):
    _observe(db, at=T0 - timedelta(hours=6), counts={PLAYER: 33})
    _observe(db, at=T0, counts={PLAYER: 50})

    result = trending_velocity(PLAYER, _ms(T0), windows_hours=(6,), path=db)

    assert result["windows"]["6h"]["deltaCount"] == 17
    assert result["windows"]["6h"]["fidelity"] == "exact"


def test_duplicate_observed_at_rows_do_not_double_count(db):
    # observe_trending_snapshot's own write-layer dedup should mean a second
    # write of the identical fetch changes nothing; verified at the read
    # layer too, for defense in depth.
    _observe(db, at=T0, counts={PLAYER: 100})
    _observe(db, at=T0, counts={PLAYER: 100})

    result = trending_velocity(PLAYER, _ms(T0), windows_hours=(1,), path=db)

    assert result["current"]["count"] == 100


def test_a_zero_trending_count_is_a_real_observation_not_a_missing_one(db):
    _observe(db, at=T0, counts={PLAYER: 0})

    result = trending_velocity(PLAYER, _ms(T0), path=db)

    assert result["current"] is not None
    assert result["current"]["count"] == 0


def test_unknown_player_reports_unavailable_not_an_error(db):
    _observe(db, at=T0, counts={"9999": 100})

    result = trending_velocity(PLAYER, _ms(T0), path=db)

    assert result["current"] is None


def test_empty_player_id_reports_unavailable_not_an_error(db):
    result = trending_velocity("", _ms(T0), path=db)

    assert result["current"] is None
    assert result["playerId"] == ""
