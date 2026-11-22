"""Read-only census reads on the temporal ledger: which dates, which assets.

``observed_dates`` and ``assets_observed_on`` name what exists; they return
no value.  Pinned: exact-date semantics (no carry-forward, nothing later),
the source filter, corrections, determinism, and that a read never creates
the ledger file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.history import asof, store


def _obs(asset_key: str, day: str, *, source_key: str, value: float, origin: str, at: str | None):
    return {
        "asset_key": asset_key,
        "asset_class": "offense",
        "lane": store.LANE_SOURCE,
        "source_key": source_key,
        "observed_date": day,
        "observed_at": at,
        "observed_at_zone": "utc" if at else None,
        "value": value,
        "rank": None,
        "tier": None,
        "confidence": None,
        "display_name": f"name-{origin}",
        "position": "WR",
        "player_id": asset_key.split(":", 1)[1],
        "scope": None,
        "pipeline_version": None,
        "origin": origin,
    }


@pytest.fixture()
def ledger(tmp_path: Path) -> Path:
    store._reset_setup_cache_for_tests()
    path = tmp_path / "ledger.sqlite"
    rows = [
        _obs("player:1", "2026-08-01", source_key="ktc", value=100, origin="live:server", at=None),
        _obs("player:1", "2026-08-03", source_key="ktc", value=110, origin="live:server", at=None),
        _obs("player:2", "2026-08-03", source_key="idpTradeCalc", value=50, origin="x", at=None),
        # Two rows for one asset on one date: the tie rule picks the known
        # later instant, so its display name is the one reported.
        _obs(
            "player:3",
            "2026-08-03",
            source_key="ktc",
            value=7,
            origin="early",
            at="2026-08-03T01:00:00+00:00",
        ),
        _obs(
            "player:3",
            "2026-08-03",
            source_key="ktc",
            value=8,
            origin="late",
            at="2026-08-03T23:00:00+00:00",
        ),
    ]
    result = store.write_observations(rows, path=path)
    assert result["written"] == len(rows)
    return path


def test_observed_dates_are_ascending_and_filterable(ledger: Path) -> None:
    assert asof.observed_dates(lane=store.LANE_SOURCE, path=ledger) == ["2026-08-01", "2026-08-03"]
    assert asof.observed_dates(lane=store.LANE_SOURCE, source_key="idpTradeCalc", path=ledger) == [
        "2026-08-03"
    ]
    assert asof.observed_dates(lane=store.LANE_CANONICAL, path=ledger) == []


def test_assets_observed_on_is_exact_date_only(ledger: Path) -> None:
    # 2026-08-02: player:1 was seen the day before and the day after; neither counts.
    assert asof.assets_observed_on("2026-08-02", lane=store.LANE_SOURCE, path=ledger) == {}
    on_first = asof.assets_observed_on("2026-08-01", lane=store.LANE_SOURCE, path=ledger)
    assert set(on_first) == {"player:1"}
    ktc = asof.assets_observed_on(
        "2026-08-03", lane=store.LANE_SOURCE, source_key="ktc", path=ledger
    )
    assert set(ktc) == {"player:1", "player:3"}
    assert ktc["player:3"] == {
        "assetClass": "offense",
        "position": "WR",
        "displayName": "name-late",
    }


def test_superseded_observations_do_not_count(ledger: Path) -> None:
    conn = store.connect(ledger)
    try:
        ids = {
            r["display_name"]: r["id"]
            for r in conn.execute(
                "SELECT id, display_name FROM observations WHERE asset_key='player:2'"
            )
        }
    finally:
        conn.close()
    # Supersede player:2's only row with a row dated elsewhere.
    store.write_observations(
        [
            _obs(
                "player:2", "2026-08-05", source_key="idpTradeCalc", value=55, origin="fix", at=None
            )
        ],
        path=ledger,
    )
    conn = store.connect(ledger)
    try:
        new_id = conn.execute(
            "SELECT id FROM observations WHERE asset_key='player:2' AND origin='fix'"
        ).fetchone()["id"]
    finally:
        conn.close()
    store.record_correction(ids["name-x"], new_id, reason="test", path=ledger)
    assert asof.observed_dates(lane=store.LANE_SOURCE, source_key="idpTradeCalc", path=ledger) == [
        "2026-08-05"
    ]
    assert "player:2" not in asof.assets_observed_on(
        "2026-08-03", lane=store.LANE_SOURCE, path=ledger
    )


def test_census_reads_never_create_the_ledger(tmp_path: Path) -> None:
    missing = tmp_path / "absent.sqlite"
    assert asof.observed_dates(lane=store.LANE_SOURCE, path=missing) == []
    assert asof.assets_observed_on("2026-08-01", lane=store.LANE_SOURCE, path=missing) == {}
    assert not missing.exists()
