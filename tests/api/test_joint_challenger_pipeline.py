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
    with vr._flag("joint_sparse_limited_evidence", True):
        on = vr.build(raw, {"flag": ("joint_outlier_sparse_challenger", True)})
    return off, on


def _rows(contract):
    return {r["canonicalName"]: r for r in contract["playersArray"] if r.get("canonicalName")}


def _family(key):
    return dc.correlation_group_for(key)


def test_flags_default_off_and_off_never_calls_the_challenger(boards, monkeypatch):
    from src.api import feature_flags

    assert feature_flags.is_enabled("joint_outlier_sparse_challenger") is False
    assert feature_flags.is_enabled("joint_sparse_limited_evidence") is False
    off, _on = boards

    def _refuse(*_a, **_k):
        raise AssertionError("challenger filter called with the flag off")

    monkeypatch.setattr(dc, "_joint_robust_filter", _refuse)
    payload, _name = newest_complete_raw_payload()
    again = vr.build(json.loads(json.dumps(payload)))
    key = lambda c: [  # noqa: E731
        (r.get("displayName"), r.get("rankDerivedValue"), r.get("canonicalConsensusRank"))
        for r in c["playersArray"]
    ]
    assert key(again) == key(off)
    assert not any("limitedEvidence" in r or "jointFilterReasons" in r for r in off["playersArray"])


def test_the_filter_receives_capped_evidence_weights(monkeypatch):
    # The weights the pipeline hands the filter are the row's freshness x health x
    # coverage weights AFTER the family cap -- the published appliedWeight stamps.
    seen = []
    real = dc._joint_robust_filter

    def spy(obs, weights, families, **kw):
        seen.append((dict(obs), dict(weights), dict(families)))
        return real(obs, weights, families, **kw)

    monkeypatch.setattr(dc, "_joint_robust_filter", spy)
    payload, _name = newest_complete_raw_payload()
    built = vr.build(
        json.loads(json.dumps(payload)), {"flag": ("joint_outlier_sparse_challenger", True)}
    )
    assert seen
    # Match each filter call to its row by the observations themselves.
    by_values = {}
    for row in built["playersArray"]:
        meta = row.get("sourceRankMeta") or {}
        if not row.get("droppedSources") and len(meta) >= 4:
            sig = tuple(sorted((k, m.get("valueContribution")) for k, m in meta.items()))
            by_values.setdefault(sig, []).append(meta)
    checked = 0
    for obs, weights, families in seen:
        sig = tuple(sorted((k, int(round(v))) for k, v in obs.items()))
        matches = by_values.get(sig) or []
        if len(matches) != 1:
            continue
        meta = matches[0]
        for k, w in weights.items():
            stamped = meta[k].get("appliedWeight")
            if isinstance(stamped, (int, float)):
                assert abs(round(w, 4) - stamped) < 1e-3, k
                checked += 1
        groups = {}
        for k in weights:
            groups.setdefault(families[k], 0.0)
            groups[families[k]] += weights[k]
        assert all(total <= 1.0 + 1e-9 for total in groups.values())
    assert checked > 0


def test_challenger_never_applies_the_value_haircut(boards):
    _off, on = boards
    assert not any(r.get("singleSourceValuePenaltyApplied") for r in on["playersArray"])


def test_every_former_haircut_row_is_stamped_limited_evidence(boards):
    off, on = boards
    on_rows = _rows(on)
    haircut = [n for n, r in _rows(off).items() if r.get("singleSourceValuePenaltyApplied")]
    assert haircut, "archive should exercise the single-family path"
    assert any("limitedEvidence" in r for r in on["playersArray"])
    for name in haircut:
        row = on_rows.get(name)
        if row is None:
            continue
        assert row.get("limitedEvidence", {}).get("presentFamilies", 2) <= 1, name


def test_the_filter_never_manufactures_a_single_family_row(boards):
    _off, on = boards
    assert any(r.get("droppedSources") for r in on["playersArray"])
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
        assert dc._CANONICAL_VALUE_MIN <= value <= 9999, row.get("canonicalName")


def test_ranked_values_stay_inside_their_own_contribution_hull(boards):
    # Removing the haircut must not create a blend-integrity violation.
    _off, on = boards
    assert not any(r.get("blendIntegrityViolation") for r in on["playersArray"])
