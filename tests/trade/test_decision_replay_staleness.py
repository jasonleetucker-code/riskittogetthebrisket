"""Opt-in leakage guards on the asset-only trade replay.

Default behaviour is documented, not changed: a nearest-prior value of ANY age
prices an asset.  With ``max_age_days`` an old value is refused and the asset is
reported unpriced with its distance and fidelity; with ``knowledge_cutoff`` a
correction recorded after the cutoff does not leak into the replay.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.history import store
from src.trade import decision_replay as dr

AT = datetime(2026, 10, 15, tzinfo=timezone.utc)


def _write(path, key, day, value, *, recorded_at=None, origin="test"):
    # Recorded an hour after the scrape unless a test says otherwise.
    recorded_at = recorded_at or f"{day}T13:00:00+00:00"
    res = store.write_observations(
        [
            {
                "asset_key": key,
                "asset_class": "offense",
                "lane": store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": day,
                "observed_at": f"{day}T12:00:00+00:00",
                "value": value,
                "origin": origin,
            }
        ],
        path=path,
        recorded_at=recorded_at,
    )
    assert res["written"] == 1, res
    conn = sqlite3.connect(str(path))
    try:
        return conn.execute("SELECT MAX(id) FROM observations").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def ledger(tmp_path):
    path = tmp_path / "ledger.sqlite"
    store._reset_setup_cache_for_tests()
    _write(path, "player:1", "2026-10-14", 6000)  # fresh
    _write(path, "player:2", "2026-07-20", 5000)  # last seen ~3 months before AT
    return path


SEND = [{"name": "Stale", "assetKey": "player:2"}]
RECV = [{"name": "Fresh", "assetKey": "player:1"}]


def test_default_prices_a_months_old_value(ledger):
    """Today's behaviour, documented: no freshness budget is applied."""
    out = dr.replay_asset_only(SEND, RECV, AT, ledger_path=ledger)
    stale = next(a for a in out["assets"] if a["assetKey"] == "player:2")
    assert stale["fidelity"] == "nearest-prior"
    assert stale["observedDate"] == "2026-07-20"
    assert stale["missingReason"] is None
    assert out["decision"]["headline"] == "YES"
    assert "leakageGuards" not in out
    assert set(stale) == {"side", "name", "assetKey", "fidelity", "observedDate", "missingReason"}


def test_max_age_refuses_the_stale_value_and_names_it(ledger):
    out = dr.replay_asset_only(SEND, RECV, AT, ledger_path=ledger, max_age_days=30)
    stale = next(a for a in out["assets"] if a["assetKey"] == "player:2")
    fresh = next(a for a in out["assets"] if a["assetKey"] == "player:1")
    assert stale["fidelity"] == "unavailable"
    assert stale["missingReason"] == "outside_max_age"
    assert stale["observedDate"] is None
    assert stale["nearestPriorDate"] == "2026-07-20"
    assert stale["nearestPriorDistanceDays"] == 87
    assert fresh["fidelity"] == "nearest-prior" and fresh["distanceDays"] == 1
    # Unpriced, never zero: the owner's missing-evidence headline.
    assert out["decision"]["headline"] == "NOT_ENOUGH_EVIDENCE"
    assert "unpriced_assets" in {g["code"] for g in out["decision"]["missingEvidence"]}
    assert out["leakageGuards"] == {"maxAgeDays": 30, "knowledgeCutoff": None}


def test_generous_budget_keeps_the_default_decision(ledger):
    default = dr.replay_asset_only(SEND, RECV, AT, ledger_path=ledger)
    budget = dr.replay_asset_only(SEND, RECV, AT, ledger_path=ledger, max_age_days=365)
    assert budget["decision"] == default["decision"]


def test_explicit_none_is_byte_identical_to_default(ledger):
    default = dr.replay_asset_only(SEND, RECV, AT, ledger_path=ledger)
    explicit = dr.replay_asset_only(
        SEND, RECV, AT, ledger_path=ledger, max_age_days=None, knowledge_cutoff=None
    )
    assert explicit == default


def test_negative_budget_is_refused(ledger):
    with pytest.raises(ValueError):
        dr.replay_asset_only(SEND, RECV, AT, ledger_path=ledger, max_age_days=-1)


def test_knowledge_cutoff_keeps_a_later_correction_out(ledger, monkeypatch):
    orig = _write(ledger, "player:3", "2026-10-10", 7000)
    fixed = _write(
        ledger,
        "player:3",
        "2026-10-10",
        4000,
        recorded_at="2026-10-18T00:00:00+00:00",
        origin="correction",
    )
    monkeypatch.setattr(store, "utc_now_iso", lambda: "2026-10-18T00:00:00+00:00")
    store.record_correction(orig, fixed, "late correction", path=ledger)
    monkeypatch.undo()
    send = [{"name": "Corrected", "assetKey": "player:3"}]
    default = dr.replay_asset_only(send, RECV, AT, ledger_path=ledger)
    bounded = dr.replay_asset_only(send, RECV, AT, ledger_path=ledger, knowledge_cutoff=AT)
    # 6000 in: today's ledger says 4000 out (YES); at AT it said 7000 out (NO).
    assert default["decision"]["headline"] == "YES"
    assert bounded["decision"]["headline"] == "NO"
    assert bounded["leakageGuards"]["knowledgeCutoff"] == AT.isoformat()
