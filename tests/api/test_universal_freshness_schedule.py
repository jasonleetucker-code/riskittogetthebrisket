"""The owner's freshness schedule on a real board (owner directive 2026-10-19 §9).

Built from the newest complete archived scrape (``tests/archive_fixtures``)
with this checkout's dataset state.  Invariants only — never a count or a
health status of the live board, which depend on which sources answered the
last scrape:

* every vote's freshness factor is a schedule step, and no vote rests on
  evidence older than 30 whole days;
* a fresh, healthy, full-coverage vote carries its full base weight times
  the provider-family adjustment, nothing else;
* every registered source has exactly one voting-status entry, and the
  statuses agree with what the rows actually did;
* flag off restores the v1 curve (no v2 fields anywhere).
"""

from __future__ import annotations

import os

import pytest

from src.api import data_contract as dc
from src.api import feature_flags
from src.api.source_weighting_explain import source_table
from src.sources.voting_status import ACTIVE_STATUSES
from tests.archive_fixtures import newest_complete_raw_payload

STEPS = (1.0, 0.75, 0.5, 0.25)
FLAG_ENV = "RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2"
_cache: dict[str, dict] = {}


def _build(v2: bool) -> dict:
    key = "on" if v2 else "off"
    if key not in _cache:
        raw, _archive = newest_complete_raw_payload()
        if raw is None:
            pytest.skip("no complete archived scrape to build a contract from")
        prior = os.environ.get(FLAG_ENV)
        os.environ[FLAG_ENV] = "1" if v2 else "0"
        feature_flags.reload()
        try:
            _cache[key] = dc.build_api_data_contract(raw)
        finally:
            if prior is None:
                os.environ.pop(FLAG_ENV, None)
            else:
                os.environ[FLAG_ENV] = prior
            feature_flags.reload()
    return _cache[key]


def _votes(contract: dict):
    for row in contract.get("playersArray") or []:
        for key, m in (row.get("sourceRankMeta") or {}).items():
            w = m.get("appliedWeight")
            if (
                isinstance(w, (int, float))
                and w > 0
                and m.get("contributedToBlend") is not False
                and not m.get("hampelDropped")
            ):
                yield row, key, m


def _requires_weighting(contract: dict) -> None:
    sw = contract.get("sourceWeighting") or {}
    if not sw.get("applied"):
        pytest.skip("this board carries no applied freshness weighting")


def test_every_vote_is_on_a_schedule_step_and_within_thirty_days():
    contract = _build(True)
    _requires_weighting(contract)
    assert contract["sourceWeighting"]["curve"] == "STEP_V2"
    seen = 0
    for row, key, m in _votes(contract):
        seen += 1
        fresh = m.get("freshness", 1.0)
        assert any(abs(fresh - s) < 1e-9 for s in STEPS), (row.get("displayName"), key, fresh)
        age = m.get("freshnessAgeHours")
        if age is not None:
            assert int(age // 24) <= 30, (row.get("displayName"), key, age)
    assert seen > 0


def test_fresh_healthy_votes_carry_their_full_base_weight():
    contract = _build(True)
    _requires_weighting(contract)
    status = {e["key"]: e for e in contract["sourceVotingStatus"]["sources"]}
    for row, key, m in _votes(contract):
        factors = status[key]["weightFactors"]
        if (
            m.get("freshness", 1.0) == 1.0
            and factors["health"] == 1.0
            and factors["coverage"] == 1.0
        ):
            base = float(m.get("baseWeight", m.get("weight", 1.0)) or 1.0)
            fam = float(m.get("familyAdjustment", 1.0) or 1.0)
            assert m["appliedWeight"] == pytest.approx(base * fam, abs=1e-3), (
                row.get("displayName"),
                key,
            )


def test_voting_status_covers_every_registered_source_and_matches_the_rows():
    contract = _build(True)
    block = contract["sourceVotingStatus"]
    keys = [str(s["key"]) for s in dc._RANKING_SOURCES]
    assert [e["key"] for e in block["sources"]] == keys
    voted = {key for _row, key, _m in _votes(contract)}
    for e in block["sources"]:
        assert e["voting"] == (e["key"] in voted), e["key"]
        if e["voting"]:
            assert e["status"] in ACTIVE_STATUSES, e
            if block["freshnessApplied"]:
                assert (e["daysSinceUpdate"] or 0) <= 30 or e["rowLevelClock"], e
        else:
            assert e["status"] not in ACTIVE_STATUSES, e
            assert e["reason"] and e["restoreRequirement"], e
        assert e["statusLabel"] == block["statusLabels"][e["status"]]


def test_status_payload_is_served_by_the_source_health_endpoint_shape():
    contract = _build(True)
    table = source_table(contract)
    assert table["votingStatus"] is contract["sourceVotingStatus"]


def test_flag_off_is_the_v1_curve():
    contract = _build(False)
    sw = contract.get("sourceWeighting") or {}
    if not sw:
        pytest.skip("this board carries no source weighting")
    assert sw["curve"] != "STEP_V2"
    for entry in (sw.get("sources") or {}).values():
        assert "freshnessSchedule" not in entry
        for sub in (entry.get("subsets") or {}).values():
            assert "clockBasis" not in sub
    assert contract["sourceVotingStatus"]["freshnessSchedule"] == "v1_cadence_curve"
