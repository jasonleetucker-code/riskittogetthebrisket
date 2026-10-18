"""idp-hampel-n3-v1 (preregistered challenger; default OFF).

docs/valuation/evidence/idp-outlier-n3-2026-10-18/PREREGISTRATION.md.

Unit level: the challenger is the incumbent function with ``min_n = 3``; at
n = 3 it drops an outer vote only on a strongly asymmetric triple above the
1,000-point floor, exactly as PREREGISTRATION §1 states in advance.
Pipeline level (newest complete archived scrape, no network): the flag ships
OFF and OFF is byte-identical; ON changes the drop decision only on IDP rows
with exactly three voters, and leaves every vote, weight and exclusion alone.
"""

from __future__ import annotations

import json

import pytest

from src.api import data_contract as dc
from src.api import feature_flags

FLAG = "idp_hampel_n3_challenger"


def test_flag_ships_off_and_is_declared():
    assert feature_flags._DEFAULTS[FLAG] is False
    assert dc._IDP_HAMPEL_N3_MIN_N == 3
    # Nothing else about the filter is a challenger constant.
    assert dc._HAMPEL_MIN_N == 4
    assert dc._HAMPEL_K == 2.75
    assert dc._HAMPEL_MIN_THRESHOLD == 1000.0


def test_n3_drops_only_a_strongly_asymmetric_triple_above_the_floor():
    # deviations {0, d1, d2}: MAD = min(d1, d2); drop needs d > 2.75 x MAD and > 1000.
    kept, dropped = dc._hampel_filter_per_player(
        [("a", 6444.0), ("b", 6227.0), ("c", 3181.0)], min_n=3
    )
    assert dropped == ["c"] and [k for k, _ in kept] == ["a", "b"]
    # Symmetric triple: neither outer vote exceeds 2.75 x the other's deviation.
    assert (
        dc._hampel_filter_per_player([("a", 3000.0), ("b", 5000.0), ("c", 7000.0)], min_n=3)[1]
        == []
    )
    # Asymmetric but below the 1,000-point floor: never dropped.
    assert (
        dc._hampel_filter_per_player([("a", 900.0), ("b", 880.0), ("c", 100.0)], min_n=3)[1] == []
    )
    # The incumbent minimum leaves every triple alone.
    assert dc._hampel_filter_per_player([("a", 6444.0), ("b", 6227.0), ("c", 3181.0)])[1] == []


# ── full pipeline (archived scrape, no network) ─────────────────────────


@pytest.fixture(scope="module")
def boards():
    from src.api import value_replay as vr
    from tests.archive_fixtures import newest_complete_raw_payload

    payload, _name = newest_complete_raw_payload()
    if payload is None:
        pytest.skip("no complete archived scrape")
    off = vr.build(json.loads(json.dumps(payload)))
    on = vr.build(json.loads(json.dumps(payload)), {"flag": (FLAG, True)})
    return payload, off, on


def _voters(row: dict) -> set[str]:
    meta = row.get("sourceRankMeta") or {}
    return {k for k, m in meta.items() if isinstance(m, dict) and not m.get("excludedReason")}


def test_off_is_byte_identical(boards):
    from src.api import value_replay as vr

    payload, off, _on = boards
    assert feature_flags.is_enabled(FLAG) is False
    again = vr.build(json.loads(json.dumps(payload)), {"flag": (FLAG, False)})
    assert json.dumps(again["playersArray"], sort_keys=True, default=str) == json.dumps(
        off["playersArray"], sort_keys=True, default=str
    )


def test_on_changes_the_drop_decision_only_on_three_voter_idp_rows(boards):
    _payload, off, on = boards
    on_rows = {r["displayName"]: r for r in on["playersArray"]}
    changed = 0
    for row in off["playersArray"]:
        other = on_rows[row["displayName"]]
        a, b = row.get("sourceRankMeta") or {}, other.get("sourceRankMeta") or {}
        assert set(a) == set(b)
        for k in a:
            for field in ("valueContribution", "excludedReason", "rankCoordinatePool"):
                assert a[k].get(field) == b[k].get(field), (row["displayName"], k, field)
        target = row.get("assetClass") == "idp" and len(_voters(row)) == 3
        if not target:
            assert row.get("droppedSources") == other.get("droppedSources"), row["displayName"]
            continue
        if row.get("droppedSources") != other.get("droppedSources"):
            changed += 1
            dropped = set(other.get("droppedSources") or [])
            assert len(dropped) == 1 and dropped <= _voters(other)
    triples = [
        r for r in off["playersArray"] if r.get("assetClass") == "idp" and len(_voters(r)) == 3
    ]
    if not triples:
        pytest.skip("no three-voter IDP row on this archive")
    # Asymmetric IDP triples above the floor exist on every complete board
    # since 2026-10-12, when IDP rows fell to at most three voters.
    assert changed > 0


def test_on_stays_on_scale_and_never_leaves_fewer_than_two_votes(boards):
    _payload, _off, on = boards
    for row in on["playersArray"]:
        dropped = set(row.get("droppedSources") or [])
        if dropped:
            assert len(_voters(row) - dropped) >= 2
        value = row.get("rankDerivedValue")
        if value is not None:
            assert 0 < value <= 9999
