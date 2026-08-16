"""Contract health has two lanes, and CI must be able to tell them apart.

THE INCIDENT THIS PINS
──────────────────────
2026-08-16.  One KTC scrape timed out — 300 s against a 39-run baseline
of ~18.8 s, a transient provider event with this repository's code
byte-identical.  ``validate_api_data_contract`` correctly reported
``ok: False`` on ``partial_run_critical:KTC``.  Then:

* a deterministic unit test asserted ``ok is True`` as a *precondition*,
  so it failed — and because the hard gate runs ``pytest -x``, a provider
  timeout turned every open pull request red and skipped the production
  deploy;
* the check that was SUPPOSED to catch source degradation
  (``scripts/validate_api_contract.py``) had been searching two
  gitignored directories for its payload and silently skipping since the
  day it was written, so the accidental unit-test failure was in fact
  the only thing standing between a source-degraded payload and
  production.

Both halves are repaired, and both halves are pinned here.  Every test
in this module builds its own SYNTHETIC payload: the lane taxonomy is a
statement about our code and must be provable with no live board, no
scrape state and no network.

THE BOUNDARY
────────────
An error is *source-health* iff it can flip purely because an upstream
provider returned less data than usual.  Everything else — schema,
rank invariants, the 1..9999 scale, blend integrity, the pick
completeness census — is *structural*: a statement about what our code
did with whatever payload arrived.
"""

from __future__ import annotations

import pytest

from src.api.data_contract import (
    _is_source_health_error,
    build_api_data_contract,
    validate_api_data_contract,
)


def _healthy_payload() -> dict:
    """A synthetic scrape whose run summary reports a clean run."""
    return {
        "players": {
            "Josh Allen": {
                "_composite": 8500,
                "_rawComposite": 8500,
                "_finalAdjusted": 8400,
                "_canonicalSiteValues": {"ktcSfTep": 8500},
                "_sites": 6,
                "position": "QB",
                "team": "BUF",
            },
            "Ja'Marr Chase": {
                "_composite": 9200,
                "_rawComposite": 9200,
                "_finalAdjusted": 9100,
                "_canonicalSiteValues": {"ktcSfTep": 9200},
                "_sites": 7,
                "position": "WR",
                "team": "CIN",
            },
        },
        "sites": [{"key": "ktcSfTep"}, {"key": "idpTradeCalc"}],
        "maxValues": {"ktcSfTep": 9999},
        "sleeper": {"positions": {"Josh Allen": "QB", "Ja'Marr Chase": "WR"}},
        "settings": {
            "sourceRunSummary": {
                "overallStatus": "ok",
                "partialRun": False,
                "completeSources": ["KTC", "IDPTradeCalc"],
                "partialSources": [],
                "failedSources": [],
                "timedOutSources": [],
            }
        },
    }


def _ktc_timeout_payload() -> dict:
    """The same scrape with KTC timed out — the 2026-08-16 shape."""
    payload = _healthy_payload()
    payload["settings"]["sourceRunSummary"] = {
        "overallStatus": "partial",
        "partialRun": True,
        "completeSources": ["IDPTradeCalc"],
        "partialSources": ["KTC_TradeDB", "KTC_WaiverDB"],
        "failedSources": [],
        "timedOutSources": ["KTC"],
        "sources": {
            "KTC": {
                "source": "KTC",
                "state": "timeout",
                "durationSec": 300.09,
                "error": "KTC timed out after 300s",
                "valueCount": 0,
            }
        },
    }
    return payload


class TestTheSourceHealthLaneStillFires:
    """Losing the signal was never the goal."""

    def test_a_timed_out_critical_source_is_an_error(self):
        report = validate_api_data_contract(build_api_data_contract(_ktc_timeout_payload()))
        assert report["ok"] is False
        assert report["status"] == "invalid"
        assert any("partial_run_critical:KTC" in e for e in report["errors"])

    def test_it_lands_in_the_source_health_lane_and_only_there(self):
        report = validate_api_data_contract(build_api_data_contract(_ktc_timeout_payload()))
        assert any("partial_run_critical:KTC" in e for e in report["sourceHealthErrors"])
        assert not [e for e in report["structuralErrors"] if "partial_run_critical" in e], report[
            "structuralErrors"
        ]
        assert report["sourceHealthOk"] is False

    def test_the_tolerable_partials_stay_warnings(self):
        """KTC_TradeDB / KTC_WaiverDB are known-partial by policy and must
        not be promoted to errors by this partition."""
        report = validate_api_data_contract(build_api_data_contract(_ktc_timeout_payload()))
        assert any("partial_run_tolerable:KTC_TradeDB" in w for w in report["warnings"])
        assert not [e for e in report["errors"] if "KTC_TradeDB" in e]


class TestTheStructuralLaneIsNotMovedByAnOutage:
    """The property the hard gate actually needs."""

    def test_a_source_outage_produces_no_structural_error(self):
        report = validate_api_data_contract(build_api_data_contract(_ktc_timeout_payload()))
        assert report["structuralErrors"] == [], report["structuralErrors"]
        assert report["structurallyOk"] is True

    def test_the_structural_lane_is_identical_healthy_vs_timed_out(self):
        """The A/B that defines the boundary: the ONLY difference between
        these two payloads is the upstream run summary, so any structural
        difference would mean the lane is measuring the wrong thing."""
        healthy = validate_api_data_contract(build_api_data_contract(_healthy_payload()))
        degraded = validate_api_data_contract(build_api_data_contract(_ktc_timeout_payload()))
        assert healthy["structuralErrors"] == degraded["structuralErrors"]

    def test_a_real_code_defect_still_fails_the_structural_lane(self):
        """…and the structural lane is not vacuous."""
        contract = build_api_data_contract(_ktc_timeout_payload())
        for row in contract["playersArray"]:
            if isinstance(row.get("rankDerivedValue"), (int, float)):
                row["rankDerivedValue"] = 12471  # outside the 1..9999 scale
                break
        report = validate_api_data_contract(contract)
        assert any("canonical_value_out_of_scale" in e for e in report["structuralErrors"])
        # Both conditions are live at once and each is reported in its own
        # lane — a degraded scrape must not mask a code defect.
        assert any("partial_run_critical:KTC" in e for e in report["sourceHealthErrors"])


class TestTheTaxonomyItself:
    @pytest.mark.parametrize(
        "message",
        [
            "partial_run_critical:KTC",
            "source_missing:ktcSfTep",
            "pick_count_below_floor:12:100",
            "pickAnchors missing from payload",
            "pickAnchors is empty",
            "implausibly small IDP pool in playersArray: 3/900 (expected at least 25 ...)",
        ],
    )
    def test_upstream_availability_conditions_are_source_health(self, message):
        assert _is_source_health_error(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "canonical_value_out_of_scale:2 value(s) outside 1..9999 (X.rankDerivedValue=12471)",
            "blend_integrity_violation:1 row(s) hold a value outside ...",
            "pick_value_zero_as_missing:2029 Early 1st",
            "pick_value_not_finite:2029 Mid 2nd",
            "pick_completeness_census:2029 Round 5:missing_or_unpriced",
            "pick_completeness_census:2029 Round 5:no_provenance",
            "missing top-level key: playersArray",
            "#12 Some Player: duplicate rank (also assigned to Other Player)",
            "playersArray[3].values must be object",
        ],
    )
    def test_statements_about_our_code_are_structural(self, message):
        assert _is_source_health_error(message) is False

    def test_the_partition_is_total(self):
        """Every error is in exactly one lane — no error may be dropped by
        a consumer that reads the partition instead of ``errors``."""
        report = validate_api_data_contract(build_api_data_contract(_ktc_timeout_payload()))
        assert sorted(report["sourceHealthErrors"] + report["structuralErrors"]) == sorted(
            report["errors"]
        )
