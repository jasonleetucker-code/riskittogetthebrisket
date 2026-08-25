"""The critical-source gate can fire for DLF (audit F-17 / V1-80).

THE DEFECT THIS PINS
────────────────────
``_CRITICAL_PRIMARY_SOURCES`` declares ``"DLF"`` critical, but the name
that reaches the gate is never ``"DLF"``: ``Dynasty Scraper.py``'s
``source_enabled_map`` reads ``SITES.get("DLF")`` and registers the
result under the RUN name ``"DLF_LocalCSV"``, which is what
``sourceRunSummary.failedSources`` carries.  Matched verbatim,
``"DLF_LocalCSV"`` is not in the critical tuple, so a failed DLF run was
emitted as ``partial_run_unknown:DLF_LocalCSV`` — a WARNING — for one of
the four sources the repo declares critical.  Latent today
(``SITES["DLF"] = False``; DLF reaches the board via
``scripts/fetch_dlf.py``), but re-enabling DLF in ``SITES`` looks like a
one-line change and would have shipped with its critical gate disabled.

THE REPAIR
──────────
``critical_primary_for_run_source`` — one derivation rule from run name
to critical primary (exact match, or ``<primary>_<qualifier>``), NOT a
fourth hand-maintained name list; F-17 explicitly rules the latter out
as the defect rather than the fix.

Every test here builds its own SYNTHETIC payload — never the live board,
per the CLAUDE.md rule for hard-gate tests.
"""

from __future__ import annotations

import pytest

from src.api import data_contract
from src.api.data_contract import (
    build_api_data_contract,
    critical_primary_for_run_source,
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
                "completeSources": ["KTC", "IDPTradeCalc", "DLF_LocalCSV"],
                "partialSources": [],
                "failedSources": [],
                "timedOutSources": [],
            }
        },
    }


def _dlf_failed_payload() -> dict:
    """The same scrape with DLF failed — under the SCRAPER'S name for it.

    ``DLF_LocalCSV`` is the exact string ``source_enabled_map`` registers
    for ``SITES["DLF"]``, i.e. the name a real DLF failure arrives under.
    """
    payload = _healthy_payload()
    payload["settings"]["sourceRunSummary"] = {
        "overallStatus": "partial",
        "partialRun": True,
        "completeSources": ["KTC", "IDPTradeCalc"],
        "partialSources": [],
        "failedSources": ["DLF_LocalCSV"],
        "timedOutSources": [],
        "sources": {
            "DLF_LocalCSV": {
                "source": "DLF_LocalCSV",
                "state": "failed",
                "error": "DLF local CSV missing/unreadable",
                "valueCount": 0,
            }
        },
    }
    return payload


class TestTheGateFiresForDlf:
    """The RED half of F-17: before the repair this exact payload
    produced ``partial_run_unknown:DLF_LocalCSV`` — a warning — and
    ``ok: True``."""

    def test_a_failed_dlf_run_is_a_critical_error(self):
        report = validate_api_data_contract(build_api_data_contract(_dlf_failed_payload()))
        assert report["ok"] is False
        assert report["status"] == "invalid"
        assert any("partial_run_critical:DLF_LocalCSV" in e for e in report["errors"])

    def test_it_is_not_downgraded_to_an_unknown_warning(self):
        report = validate_api_data_contract(build_api_data_contract(_dlf_failed_payload()))
        assert not any("partial_run_unknown:DLF_LocalCSV" in w for w in report["warnings"]), report[
            "warnings"
        ]

    def test_it_lands_in_the_source_health_lane_and_only_there(self):
        """A DLF failure is a provider condition, never a structural one —
        the lane split must classify it with the other criticals."""
        report = validate_api_data_contract(build_api_data_contract(_dlf_failed_payload()))
        assert any("partial_run_critical:DLF_LocalCSV" in e for e in report["sourceHealthErrors"])
        assert not [e for e in report["structuralErrors"] if "partial_run_critical" in e], report[
            "structuralErrors"
        ]
        assert report["sourceHealthOk"] is False
        assert report["structurallyOk"] is True

    def test_the_allowlist_still_precedes_the_critical_match(self):
        """Mechanism ordering pin: a recorded allowlist decision wins over
        the critical derivation, exactly as it does for exact names."""
        from unittest import mock

        with mock.patch.object(
            data_contract, "TOLERABLE_PARTIAL_SOURCES", frozenset({"DLF_LocalCSV"})
        ):
            report = validate_api_data_contract(build_api_data_contract(_dlf_failed_payload()))
        assert any("partial_run_tolerable:DLF_LocalCSV" in w for w in report["warnings"])
        assert not [e for e in report["errors"] if "DLF_LocalCSV" in e]


class TestNonCriticalRunNamesStayWarnings:
    """The derivation must not promote sources the repo does not declare
    critical — their primaries are not in the tuple."""

    @pytest.mark.parametrize("run_name", ["DraftSharks_IDP", "FantasyPros_IDP", "Flock"])
    def test_a_failed_non_critical_source_stays_a_warning(self, run_name):
        payload = _healthy_payload()
        payload["settings"]["sourceRunSummary"] = {
            "overallStatus": "partial",
            "partialRun": True,
            "completeSources": ["KTC", "IDPTradeCalc"],
            "partialSources": [],
            "failedSources": [run_name],
            "timedOutSources": [],
        }
        report = validate_api_data_contract(build_api_data_contract(payload))
        assert any(f"partial_run_unknown:{run_name}" in w for w in report["warnings"])
        assert not [e for e in report["errors"] if run_name in e]


class TestTheDerivationRuleItself:
    """One rule, not a name list: run name → critical primary."""

    @pytest.mark.parametrize(
        ("run_name", "primary"),
        [
            ("DLF", "DLF"),
            ("DLF_LocalCSV", "DLF"),
            ("KTC", "KTC"),
            ("KTC_TradeDB", "KTC"),
            ("DynastyNerds", "DynastyNerds"),
            ("IDPTradeCalc", "IDPTradeCalc"),
            ("IDPTradeCalc_Picks", "IDPTradeCalc"),
            # historical bare-prefix sub-endpoint shape, preserved:
            ("IDPTradeCalcPicks", "IDPTradeCalc"),
        ],
    )
    def test_critical_run_names_resolve_to_their_primary(self, run_name, primary):
        assert critical_primary_for_run_source(run_name) == primary

    @pytest.mark.parametrize(
        "run_name",
        [
            "DraftSharks_IDP",
            "FantasyPros_IDP",
            "FantasyCalc",
            "Flock",
            # a primary name as a bare prefix without the ``_`` qualifier
            # separator is a DIFFERENT source, not a qualified run name:
            "DLFX",
            "KTCClone",
            "",
        ],
    )
    def test_everything_else_resolves_to_none(self, run_name):
        assert critical_primary_for_run_source(run_name) is None


class TestTheGateIsValidationOnly:
    """The gate reports; it never reprices.  The ONLY difference between
    these two payloads is the upstream run summary, so every published
    value must be identical."""

    def test_a_dlf_failure_moves_no_value_and_no_rank(self):
        healthy = build_api_data_contract(_healthy_payload())
        degraded = build_api_data_contract(_dlf_failed_payload())
        healthy_rows = {
            r.get("displayName"): (r.get("rankDerivedValue"), r.get("canonicalConsensusRank"))
            for r in healthy["playersArray"]
        }
        degraded_rows = {
            r.get("displayName"): (r.get("rankDerivedValue"), r.get("canonicalConsensusRank"))
            for r in degraded["playersArray"]
        }
        assert healthy_rows == degraded_rows
