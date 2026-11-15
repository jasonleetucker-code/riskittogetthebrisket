"""Bitemporal ``knowledge_cutoff`` on the instant-strict as-of reads.

``value_known_before`` / ``batch_known_before`` bound VALID time (when a value
was observed).  Without a knowledge bound they read the ledger's CURRENT
knowledge of that past, so a correction or backfill recorded today leaks into a
historical evaluation.  ``knowledge_cutoff`` also bounds TRANSACTION time
(``recorded_at``).  These tests pin:

* a correction recorded AFTER the cutoff is ignored with the flag and applied
  without it;
* a correction recorded at or before the cutoff is applied either way;
* an observation recorded after the cutoff is invisible with the flag;
* an unprovable ``recorded_at`` is not known at the cutoff (conservative);
* the default path is byte-identical (same result as before, no extra keys);
* the HISTORY_FLOOR refusal and naive-datetime refusal are unchanged.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest

from src.history import asof, store

T_QUERY = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
RECORDED_EARLY = "2026-08-02T00:00:00+00:00"
CUTOFF = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
RECORDED_LATE = "2026-09-15T00:00:00+00:00"


@pytest.fixture
def ledger(tmp_path):
    store._reset_setup_cache_for_tests()
    return tmp_path / "ledger.sqlite"


def _write(path, key, day, value, *, at, recorded_at, origin="test"):
    res = store.write_observations(
        [
            {
                "asset_key": key,
                "asset_class": "offense",
                "lane": store.LANE_CANONICAL,
                "source_key": "",
                "observed_date": day,
                "observed_at": at,
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


def _correct(path, monkeypatch, superseded, superseding, *, recorded_at):
    monkeypatch.setattr(store, "utc_now_iso", lambda: recorded_at)
    store.record_correction(superseded, superseding, "test correction", path=path)
    monkeypatch.undo()


@pytest.fixture
def corrected_late(ledger, monkeypatch):
    """A 4000 observation (recorded early) corrected to 4500 by a row and a
    correction both recorded AFTER the cutoff."""
    orig = _write(
        ledger,
        "player:1",
        "2026-08-01",
        4000,
        at="2026-08-01T12:00:00+00:00",
        recorded_at=RECORDED_EARLY,
    )
    fixed = _write(
        ledger,
        "player:1",
        "2026-08-01",
        4500,
        at="2026-08-01T12:00:00+00:00",
        recorded_at=RECORDED_LATE,
        origin="correction",
    )
    _correct(ledger, monkeypatch, orig, fixed, recorded_at=RECORDED_LATE)
    return ledger


def test_correction_after_cutoff_is_ignored_with_flag_and_applied_without(corrected_late):
    default = asof.value_known_before("player:1", T_QUERY, path=corrected_late)
    assert default["value"] == 4500  # today's knowledge: the correction applies
    bounded = asof.value_known_before(
        "player:1", T_QUERY, path=corrected_late, knowledge_cutoff=CUTOFF
    )
    assert bounded["value"] == 4000  # what was known at the cutoff
    assert bounded["fidelity"] == asof.FIDELITY_NEAREST_PRIOR
    assert bounded["knowledgeCutoff"] == CUTOFF.isoformat()
    assert bounded["provenance"]["recordedAt"] == RECORDED_EARLY


def test_correction_at_or_before_cutoff_applies_either_way(ledger, monkeypatch):
    orig = _write(
        ledger,
        "player:1",
        "2026-08-01",
        4000,
        at="2026-08-01T12:00:00+00:00",
        recorded_at=RECORDED_EARLY,
    )
    fixed = _write(
        ledger,
        "player:1",
        "2026-08-01",
        4500,
        at="2026-08-01T12:00:00+00:00",
        recorded_at="2026-08-05T00:00:00+00:00",
        origin="correction",
    )
    _correct(ledger, monkeypatch, orig, fixed, recorded_at=CUTOFF.isoformat())
    for kwargs in ({}, {"knowledge_cutoff": CUTOFF}):
        assert asof.value_known_before("player:1", T_QUERY, path=ledger, **kwargs)["value"] == 4500


def test_observation_recorded_after_cutoff_is_invisible(ledger):
    _write(
        ledger,
        "player:1",
        "2026-08-01",
        4000,
        at="2026-08-01T12:00:00+00:00",
        recorded_at=RECORDED_EARLY,
    )
    # A later-dated observation BACKFILLED after the cutoff.
    _write(
        ledger,
        "player:1",
        "2026-08-15",
        7000,
        at="2026-08-15T12:00:00+00:00",
        recorded_at=RECORDED_LATE,
    )
    assert asof.value_known_before("player:1", T_QUERY, path=ledger)["value"] == 7000
    bounded = asof.value_known_before("player:1", T_QUERY, path=ledger, knowledge_cutoff=CUTOFF)
    assert bounded["value"] == 4000
    assert bounded["observedDate"] == "2026-08-01"


def test_only_late_recorded_evidence_is_unavailable_not_zero(ledger):
    _write(
        ledger,
        "player:1",
        "2026-08-01",
        4000,
        at="2026-08-01T12:00:00+00:00",
        recorded_at=RECORDED_LATE,
    )
    bounded = asof.value_known_before("player:1", T_QUERY, path=ledger, knowledge_cutoff=CUTOFF)
    assert bounded["fidelity"] == asof.FIDELITY_UNAVAILABLE
    assert bounded["missingReason"] == asof.REASON_NO_PRIOR
    assert bounded["value"] is None


def test_unprovable_recorded_at_is_not_known_at_the_cutoff(ledger):
    _write(
        ledger,
        "player:1",
        "2026-08-01",
        4000,
        at="2026-08-01T12:00:00+00:00",
        recorded_at="2026-08-02",  # date-only: no proven instant
    )
    assert asof.value_known_before("player:1", T_QUERY, path=ledger)["value"] == 4000
    bounded = asof.value_known_before("player:1", T_QUERY, path=ledger, knowledge_cutoff=CUTOFF)
    assert bounded["value"] is None


def test_batch_matches_single_reads_under_the_cutoff(corrected_late):
    _write(
        corrected_late,
        "player:2",
        "2026-08-03",
        3000,
        at="2026-08-03T12:00:00+00:00",
        recorded_at="2026-08-04T00:00:00+00:00",
    )
    reqs = [("player:1", T_QUERY), ("player:2", T_QUERY), ("player:1", T_QUERY)]
    out = asof.batch_known_before(reqs, path=corrected_late, knowledge_cutoff=CUTOFF)
    assert [r["value"] for r in out["results"]] == [4000, 3000, 4000]
    assert out["knowledgeCutoff"] == CUTOFF.isoformat()
    for (key, inst), r in zip(reqs, out["results"]):
        single = asof.value_known_before(key, inst, path=corrected_late, knowledge_cutoff=CUTOFF)
        assert r == single
    default = asof.batch_known_before(reqs, path=corrected_late)
    assert [r["value"] for r in default["results"]] == [4500, 3000, 4500]


def test_default_path_shape_is_unchanged(corrected_late):
    single = asof.value_known_before("player:1", T_QUERY, path=corrected_late)
    explicit_none = asof.value_known_before(
        "player:1", T_QUERY, path=corrected_late, knowledge_cutoff=None
    )
    assert single == explicit_none
    assert "knowledgeCutoff" not in single
    batch = asof.batch_known_before([("player:1", T_QUERY)], path=corrected_late)
    assert "knowledgeCutoff" not in batch
    assert "knowledgeCutoff" not in batch["results"][0]
    assert batch["results"][0] == single


def test_history_floor_refusal_unchanged(corrected_late):
    before = datetime(2026, 7, 1, tzinfo=timezone.utc)
    for kwargs in ({}, {"knowledge_cutoff": CUTOFF}):
        r = asof.value_known_before("player:1", before, path=corrected_late, **kwargs)
        assert r["missingReason"] == asof.REASON_BEFORE_BOUNDARY
        b = asof.batch_known_before([("player:1", before)], path=corrected_late, **kwargs)
        assert b["results"][0]["missingReason"] == asof.REASON_BEFORE_BOUNDARY


def test_naive_cutoff_is_refused(corrected_late):
    with pytest.raises(store.ObservationError):
        asof.value_known_before(
            "player:1", T_QUERY, path=corrected_late, knowledge_cutoff=datetime(2026, 8, 10)
        )
    with pytest.raises(store.ObservationError):
        asof.batch_known_before(
            [("player:1", T_QUERY)], path=corrected_late, knowledge_cutoff=datetime(2026, 8, 10)
        )


def test_max_age_still_applies_under_the_cutoff(corrected_late):
    r = asof.value_known_before(
        "player:1", T_QUERY, path=corrected_late, knowledge_cutoff=CUTOFF, max_age_days=5
    )
    assert r["missingReason"] == asof.REASON_OUTSIDE_MAX_AGE
    assert r["nearestPriorDate"] == "2026-08-01"
    assert r["nearestPriorDistanceDays"] == 19
