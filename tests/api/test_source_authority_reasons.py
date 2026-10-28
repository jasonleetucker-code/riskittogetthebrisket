"""Per-source weight-below-base reasons (``sourceAuthorityReasons``).

A row whose evidence is degraded must be able to say WHY, source by source:
stale since a date, withheld, family-capped, rejected as an outlier, or held
from voting by an owner policy.  The field is a diagnostic built from stamps
the blend already wrote; it decides nothing.

Two layers:

* unit tests of ``_source_authority_reasons`` on synthetic stamps (every
  reason code, and the "full authority is absent" rule);
* invariants on a real board built from the newest complete archive — never a
  count of the live board: every source the row's ``retainedAuthority``
  counts below full strength is named, every named stale date agrees with the
  row's own freshness stamp, and a policy-held source is named only when it
  observed the row.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from src.api import data_contract as dc
from tests.archive_fixtures import newest_complete_raw_payload

AS_OF = datetime(2026, 10, 28, 9, 2, 26, tzinfo=timezone.utc)


@dataclass
class _Sub:
    as_of: datetime
    clock_is_baseline: bool = False
    clock_at: datetime | None = None


@dataclass
class _SW:
    measured: bool = True
    health_factor: float = 1.0
    coverage_factor: float = 1.0

    def subset_for(self, is_pick: bool) -> _Sub:
        return _Sub(AS_OF)


def _reasons(meta, sw=None, *, applied=True, held=()):
    return dc._source_authority_reasons(
        meta,
        is_pick=False,
        source_weighting=sw if sw is not None else {k: _SW() for k in meta},
        freshness_applied=applied,
        held_observed=held,
    )


class TestReasonCodes:
    def test_full_authority_source_is_absent(self):
        assert _reasons({"a": {"appliedWeight": 1.0, "weight": 1.0}}) == {}

    def test_stale_voter_names_factor_and_content_date(self):
        # 1302.5 h before the as-of is 2026-09-04 (FantasyPros IDP's stated clock).
        out = _reasons({"fp": {"freshness": 0.21, "freshnessAgeHours": 1302.5}})
        assert out == {"fp": "stale=0.21@2026-09-04"}

    def test_withheld_for_staleness_names_date(self):
        meta = {
            "show": {
                "freshness": 0.0,
                "freshnessAgeHours": 1671.2,
                "contributedToBlend": False,
                "appliedWeight": 0.0,
            }
        }
        assert _reasons(meta) == {"show": "withheld:stale@2026-08-19"}

    def test_withheld_for_health(self):
        meta = {"x": {"contributedToBlend": False, "appliedWeight": 0.0}}
        assert _reasons(meta) == {"x": "withheld:health"}

    def test_health_and_coverage_factors(self):
        out = _reasons({"x": {}}, {"x": _SW(health_factor=0.5, coverage_factor=0.8)})
        assert out == {"x": "health=0.5,coverage=0.8"}

    def test_family_cap_and_stale_combine(self):
        meta = {"d": {"freshness": 0.5, "freshnessAgeHours": 24.0, "familyAdjustment": 0.5}}
        assert _reasons(meta) == {"d": "stale=0.5@2026-10-27,family_cap=0.5"}

    def test_outlier_and_superseded(self):
        meta = {"o": {"hampelDropped": True}, "s": {"supersededBy": "o"}}
        assert _reasons(meta) == {"o": "outlier_dropped", "s": "superseded:o"}

    def test_freshness_rollback_reports_no_stale_reduction(self):
        # RISKIT_FEATURE_SOURCE_FRESHNESS_WEIGHTING=0: the factor is stamped
        # for diagnostics but did not reduce the vote, so it is not a reason.
        meta = {"fp": {"freshness": 0.21, "freshnessAgeHours": 1302.5}}
        assert _reasons(meta, applied=False) == {}

    def test_unmeasured_source_has_no_date(self):
        meta = {"x": {"freshness": 0.4, "freshnessAgeHours": 10.0}}
        assert _reasons(meta, {}) == {"x": "stale=0.4"}

    def test_baseline_clock_is_never_shown_as_a_content_date(self):
        # The source's only clock is our first fetch: no content date is known.
        base = AS_OF - timedelta(hours=100.0)

        class _BaselineSW(_SW):
            def subset_for(self, is_pick):
                return _Sub(AS_OF, clock_is_baseline=True, clock_at=base)

        stale = {"n": {"freshness": 0.5, "freshnessAgeHours": 100.0}}
        assert _reasons(stale, {"n": _BaselineSW()}) == {"n": "stale=0.5@unverified_clock"}
        withheld = {
            "n": {"freshness": 0.0, "freshnessAgeHours": 100.0, "contributedToBlend": False}
        }
        assert _reasons(withheld, {"n": _BaselineSW()}) == {"n": "withheld:stale@unverified_clock"}
        # A row whose own clock moved past the baseline keeps its real date.
        moved = {"n": {"freshness": 0.5, "freshnessAgeHours": 24.0}}
        assert _reasons(moved, {"n": _BaselineSW()}) == {"n": "stale=0.5@2026-10-27"}

    def test_policy_held_source_is_named(self):
        assert _reasons({}, held=["dlfIdp"]) == {"dlfIdp": "held:owner_policy"}


@pytest.fixture(scope="module")
def board() -> dict:
    raw, _name = newest_complete_raw_payload()
    if raw is None:
        pytest.skip("no complete archived scrape to build a contract from")
    return dc.build_api_data_contract(copy.deepcopy(raw))


def _blended(board):
    return [r for r in board.get("playersArray") or [] if "sourceAuthorityReasons" in r]


def test_every_reduced_source_is_named(board):
    rows = _blended(board)
    # Every row that went through the blend carries the field (``{}`` when
    # nothing was reduced) — its absence is never "nothing to explain".
    blended = [r for r in board.get("playersArray") or [] if r.get("sourceRankMeta")]
    assert len(rows) >= len(blended) > 0
    for row in rows:
        reasons = row["sourceAuthorityReasons"]
        assert isinstance(reasons, dict)
        for key, m in (row.get("sourceRankMeta") or {}).items():
            reduced = (
                m.get("contributedToBlend") is False
                or m.get("hampelDropped")
                or (isinstance(m.get("familyAdjustment"), float) and m["familyAdjustment"] < 1.0)
                or (
                    (board.get("sourceWeighting") or {}).get("applied")
                    and isinstance(m.get("freshness"), (int, float))
                    and m["freshness"] < 1.0
                )
            )
            if reduced:
                assert key in reasons, (row.get("displayName"), key, m)


def test_reduced_authority_row_always_has_a_reason(board):
    """The direction that matters: a row below full authority can always say
    why.  (The converse does not hold, by design: a withheld member of a
    provider family whose other member votes at full strength leaves the
    family-capped denominator — and so ``retainedAuthority`` — at 1.0, while
    the withheld member is still named.)"""
    for row in _blended(board):
        ra = row.get("retainedAuthority")
        if isinstance(ra, (int, float)) and ra < 1.0:
            weight_reasons = [
                v
                for v in row["sourceAuthorityReasons"].values()
                if v.startswith(("stale", "withheld", "health", "coverage"))
            ]
            assert weight_reasons, (row.get("displayName"), ra, row["sourceAuthorityReasons"])


def test_held_source_named_only_when_it_observed_the_row(board):
    for row in _blended(board):
        site = row.get("canonicalSiteValues") or {}
        for key, code in row["sourceAuthorityReasons"].items():
            if code == dc.SOURCE_AUTHORITY_HELD_POLICY:
                assert site.get(key) is not None, (row.get("displayName"), key)
                assert key not in (row.get("sourceRankMeta") or {}), (row.get("displayName"), key)


def test_field_mirrors_to_legacy_dict_and_delta(board):
    assert "sourceAuthorityReasons" in dc._TRUST_MIRROR_FIELDS
    assert "sourceAuthorityReasons" in dc._DELTA_PLAYER_FIELDS
