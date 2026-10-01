"""Full-pipeline tests for the joint outlier/sparse challenger (#1555 Batch 2 Unit C).

Built from the newest complete archived scrape (no live board, no network), once
with ``joint_outlier_sparse_challenger`` off (the incumbent) and once on. The
assertions are invariants, never counts over the live board.
"""

from __future__ import annotations

import json

import pytest

from src.api import data_contract as dc
from src.api import value_replay as vr
from tests.archive_fixtures import newest_complete_raw_payload


@pytest.fixture(scope="module")
def boards():
    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    raw = json.loads(json.dumps(payload))
    off = vr.build(raw)
    on = vr.build(raw, {"flag": ("joint_outlier_sparse_challenger", True)})
    return off, on


def _rows(contract):
    return {r["canonicalName"]: r for r in contract["playersArray"] if r.get("canonicalName")}


def _family(key):
    return dc.correlation_group_for(key)


def test_flag_defaults_off_and_off_is_the_incumbent(boards):
    from src.api import feature_flags

    assert feature_flags.is_enabled("joint_outlier_sparse_challenger") is False
    off, _on = boards
    rows = off["playersArray"]
    assert not any("limitedEvidence" in r or "jointFilterReasons" in r for r in rows)


def test_challenger_never_applies_the_value_haircut(boards):
    _off, on = boards
    assert not any(r.get("singleSourceValuePenaltyApplied") for r in on["playersArray"])


def test_every_former_haircut_row_is_stamped_limited_evidence(boards):
    off, on = boards
    on_rows = _rows(on)
    haircut = [n for n, r in _rows(off).items() if r.get("singleSourceValuePenaltyApplied")]
    if not haircut:
        pytest.skip("archive has no single-family row")
    for name in haircut:
        row = on_rows.get(name)
        if row is None:
            continue
        assert row.get("limitedEvidence", {}).get("presentFamilies", 2) <= 1, name


def test_the_filter_never_manufactures_a_single_family_row(boards):
    _off, on = boards
    for row in on["playersArray"]:
        dropped = row.get("droppedSources") or []
        if not dropped:
            continue
        audit = row.get("sourceRanks") or {}
        present = {_family(k) for k in audit}
        surviving = {_family(k) for k in audit if k not in dropped}
        if len(present) >= 2:
            assert len(surviving) >= 2, row.get("canonicalName")


def test_challenger_values_stay_on_the_canonical_scale(boards):
    _off, on = boards
    for row in on["playersArray"]:
        value = row.get("rankDerivedValue")
        if value is None:
            continue
        assert 0 <= value <= 9999, row.get("canonicalName")


def test_ranked_values_stay_inside_their_own_contribution_hull(boards):
    # Removing the haircut must not create a blend-integrity violation.
    _off, on = boards
    assert not any(r.get("blendIntegrityViolation") for r in on["playersArray"])
