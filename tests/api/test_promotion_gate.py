import json
import sys
import unittest
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from pathlib import Path


class PromotionGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = Path(__file__).resolve().parents[2]
        if str(cls.repo_root) not in sys.path:
            sys.path.insert(0, str(cls.repo_root))

        from src.api.data_contract import build_api_data_contract, validate_api_data_contract
        from src.api.promotion_gate import evaluate_promotion_candidate, load_promotion_gate_config, _parse_iso

        cls.build_api_data_contract = staticmethod(build_api_data_contract)
        cls.validate_api_data_contract = staticmethod(validate_api_data_contract)
        cls.evaluate_promotion_candidate = staticmethod(evaluate_promotion_candidate)
        cls.load_promotion_gate_config = staticmethod(load_promotion_gate_config)
        cls.parse_iso = staticmethod(_parse_iso)

        payload_path = cls.repo_root / "tests" / "fixtures" / "runtime_last_good_fixture.json"
        if not payload_path.exists():
            payload_path = cls.repo_root / "data" / "dynasty_data_2026-03-19.json"
        with payload_path.open("r", encoding="utf-8") as f:
            cls.base_payload = json.load(f)

        scrape_ts = cls.parse_iso(cls.base_payload.get("scrapeTimestamp"))
        assert scrape_ts is not None
        cls.eval_now = scrape_ts + timedelta(hours=1)
        cls.cfg = replace(
            cls.load_promotion_gate_config(),
            policy_disagreement_degrade_player_count=999999,
            policy_disagreement_block_player_count=999999,
            policy_disagreement_degrade_source_spike_count=999999,
            policy_disagreement_block_critical_source_spike_count=999999,
            policy_overnight_swing_degrade_count=999999,
            policy_overnight_swing_block_count=999999,
            policy_waivers=[],
        )

    @staticmethod
    def _normalize_source_key(value):
        text = str(value or "").strip().lower()
        if not text:
            return ""
        return "".join(ch for ch in text if ch.isalnum())

    @staticmethod
    def _regression_pass(_repo_root, _cfg):
        return {
            "ok": True,
            "status": "passed",
            "command": "stub",
            "durationSec": 0.01,
            "returnCode": 0,
            "stdoutTail": "stub pass",
            "stderrTail": "",
        }

    def _evaluate(
        self,
        raw_payload,
        contract_payload=None,
        contract_report=None,
        baseline_raw_payload=None,
        baseline_contract_payload=None,
        config=None,
        now=None,
    ):
        contract_payload = contract_payload or self.build_api_data_contract(raw_payload)
        contract_report = contract_report or self.validate_api_data_contract(contract_payload)
        return self.evaluate_promotion_candidate(
            raw_payload=raw_payload,
            contract_payload=contract_payload,
            contract_report=contract_report,
            repo_root=self.repo_root,
            trigger="test",
            source_meta={"type": "test", "path": "fixture"},
            baseline_raw_payload=baseline_raw_payload,
            baseline_contract_payload=baseline_contract_payload,
            config=config or self.cfg,
            now=now or self.eval_now,
            regression_runner=self._regression_pass,
        )

    @staticmethod
    def _sanitize_contract_value_bundles(contract_payload):
        rows = contract_payload.get("playersArray")
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            bundle = row.get("valueBundle")
            if not isinstance(bundle, dict):
                bundle = {}
                row["valueBundle"] = bundle

            fallback_raw = bundle.get("fullValue")
            if fallback_raw is None:
                fallback_raw = row.get("fullValue")
            try:
                fallback = int(fallback_raw)
            except Exception:
                fallback = 1
            fallback = max(1, min(9999, fallback))

            for key in (
                "rawValue",
                "scoringAdjustedValue",
                "scarcityAdjustedValue",
                "bestBallAdjustedValue",
                "fullValue",
            ):
                raw = bundle.get(key)
                try:
                    value = int(raw)
                except Exception:
                    bundle[key] = fallback
                    continue
                if value < 1 or value > 9999:
                    bundle[key] = fallback

    def test_passes_for_known_good_payload(self):
        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)
        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)
        self.assertEqual(result.get("status"), "pass", result)
        self.assertTrue(result["gates"]["requiredSourcePresence"]["ok"])
        self.assertTrue(result["gates"]["sourceFreshness"]["ok"])
        self.assertTrue(result["gates"]["coverageThresholds"]["ok"])
        self.assertTrue(result["gates"]["mergeIntegrity"]["ok"])
        self.assertTrue(result["gates"]["regressionTests"]["ok"])
        self.assertTrue(result["gates"]["formulaSanity"]["ok"])
        self.assertIn("observability", result)
        self.assertIn("operatorReport", result)
        self.assertIn("sourceCoverageByPosition", result["observability"])
        self.assertIn("playerDisagreement", result["observability"])

    def test_formula_sanity_accepts_intentional_quarantine_without_full_value(self):
        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)

        target_row = None
        for row in contract.get("playersArray", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("assetClass") or "").lower() == "pick":
                continue
            bundle = row.get("valueBundle")
            if not isinstance(bundle, dict):
                continue
            target_row = row
            break
        self.assertIsNotNone(target_row, "Expected at least one non-pick player row in fixture.")
        if target_row is None:
            return

        bundle = target_row.get("valueBundle") if isinstance(target_row.get("valueBundle"), dict) else {}
        guardrails = dict(bundle.get("guardrails") or {})
        guardrails["quarantined"] = True
        guardrails["finalAuthorityStatus"] = "quarantined"
        guardrails["quarantineReasons"] = list(guardrails.get("quarantineReasons") or ["position_unresolved"])
        bundle["guardrails"] = guardrails
        bundle["fullValue"] = None
        target_row["valueBundle"] = bundle
        target_row["fullValue"] = None
        target_row["quarantinedFromFinalAuthority"] = True

        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)
        self.assertEqual(result.get("status"), "pass", result)
        formula = result["gates"]["formulaSanity"]
        self.assertTrue(formula.get("ok"), formula)
        self.assertEqual(int(formula.get("invalidValueRows") or 0), 0)
        self.assertGreaterEqual(int(formula.get("intentionalQuarantineRows") or 0), 1)
        self.assertGreaterEqual(int(formula.get("intentionalQuarantineMissingFullValueRows") or 0), 1)

    def test_fails_when_critical_source_missing(self):
        payload = deepcopy(self.base_payload)
        critical_sources = [
            self._normalize_source_key(v)
            for v in (self.cfg.critical_sources or [])
            if self._normalize_source_key(v)
        ]
        self.assertTrue(critical_sources, "Expected at least one configured critical source")
        if not critical_sources:
            return
        target_critical_source = critical_sources[0]
        for row in payload.get("sites", []):
            if not isinstance(row, dict):
                continue
            if self._normalize_source_key(row.get("key")) == target_critical_source:
                row["playerCount"] = 0

        contract = self.build_api_data_contract(payload)
        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)
        self.assertEqual(result.get("status"), "fail", result)
        self.assertFalse(result["gates"]["requiredSourcePresence"]["ok"])
        self.assertIn("required_source_presence_failed", result["summary"]["errors"])
        missing_sources = {
            self._normalize_source_key(v)
            for v in (result["gates"]["requiredSourcePresence"].get("missingSources") or [])
            if self._normalize_source_key(v)
        }
        self.assertIn(target_critical_source, missing_sources)

    def test_fails_when_merge_integrity_exceeds_threshold(self):
        payload = deepcopy(self.base_payload)
        settings = payload.setdefault("settings", {})
        identity = settings.setdefault("identityResolutionDiagnostics", {})
        totals = identity.setdefault("totals", {})
        totals["sourceRows"] = 100
        totals["unmatchedRows"] = 60
        totals["duplicateCanonicalMatches"] = 0
        totals["conflictingPositions"] = 0
        totals["conflictingSourceIdentities"] = 0

        contract = self.build_api_data_contract(payload)
        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)
        self.assertEqual(result.get("status"), "fail", result)
        self.assertFalse(result["gates"]["mergeIntegrity"]["ok"])
        self.assertIn("merge_integrity_failed", result["summary"]["errors"])

    def test_fails_formula_sanity_when_qb_top_value_collapses(self):
        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)
        for row in contract.get("playersArray", []):
            if not isinstance(row, dict) or row.get("position") != "QB":
                continue
            bundle = row.get("valueBundle")
            if not isinstance(bundle, dict):
                continue
            bundle["rawValue"] = 100
            bundle["scoringAdjustedValue"] = 100
            bundle["scarcityAdjustedValue"] = 100
            bundle["bestBallAdjustedValue"] = 100
            bundle["fullValue"] = 100
        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)
        self.assertEqual(result.get("status"), "fail", result)
        self.assertFalse(result["gates"]["formulaSanity"]["ok"])
        self.assertIn("formula_sanity_failed", result["summary"]["errors"])

    def test_observability_flags_coverage_disagreement_and_overnight_swings(self):
        baseline_payload = deepcopy(self.base_payload)
        baseline_contract = self.build_api_data_contract(baseline_payload)

        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)
        rows = contract.get("playersArray") or []

        target_name = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("position") or "").upper() != "QB":
                continue
            canonical = row.get("canonicalSiteValues")
            if not isinstance(canonical, dict):
                continue
            target_name = str(row.get("canonicalName") or "").strip()
            if not target_name:
                continue
            canonical["ktc"] = 850
            canonical["dynastyDaddy"] = 900
            canonical["idpTradeCalc"] = 9800
            bundle = row.get("valueBundle") if isinstance(row.get("valueBundle"), dict) else {}
            if isinstance(bundle, dict):
                prev_full = int(bundle.get("fullValue") or row.get("fullValue") or 2500)
                next_full = min(9999, prev_full + 2500)
                bundle["fullValue"] = next_full
                row["fullValue"] = next_full
            break

        self.assertTrue(target_name, "Fixture should include at least one QB row")

        for row in rows:
            if not isinstance(row, dict):
                continue
            if str(row.get("position") or "").upper() != "QB":
                continue
            canonical = row.get("canonicalSiteValues")
            if not isinstance(canonical, dict):
                continue
            if "yahoo" in canonical:
                canonical["yahoo"] = 0

        report = self.validate_api_data_contract(contract)
        result = self._evaluate(
            payload,
            contract_payload=contract,
            contract_report=report,
            baseline_raw_payload=baseline_payload,
            baseline_contract_payload=baseline_contract,
        )

        flags = result["observability"]["flags"]
        collapse = flags.get("coverageCollapseByPosition") or []
        extremes = flags.get("extremeDisagreementSpikes") or []
        swings = flags.get("unexpectedOvernightSwings") or []
        self.assertTrue(
            any(
                str(row.get("source", "")).lower() == "yahoo"
                and str(row.get("position", "")).upper() == "QB"
                for row in collapse
            ),
            collapse,
        )
        self.assertTrue(any(str(row.get("name")) == target_name for row in extremes), extremes)
        self.assertTrue(any(str(row.get("name")) == target_name for row in swings), swings)

        recommendations = result["observability"]["autoHandlingRecommendations"]
        yahoo_rec = next(
            (row for row in recommendations if str(row.get("source") or "").lower() == "yahoo"),
            None,
        )
        self.assertIsNotNone(yahoo_rec)
        if yahoo_rec is not None:
            self.assertNotEqual(str(yahoo_rec.get("recommendedAction")), "keep")

    def test_observability_recommends_skip_for_missing_source(self):
        payload = deepcopy(self.base_payload)
        for row in payload.get("sites", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("key", "")).lower() == "yahoo":
                row["playerCount"] = 0

        summary = payload.setdefault("settings", {}).setdefault("sourceRunSummary", {})
        source_rows = summary.setdefault("sources", {})
        yahoo_row = source_rows.setdefault("Yahoo", {})
        yahoo_row["enabled"] = True
        yahoo_row["state"] = "failed"
        yahoo_row["error"] = "test_missing_source"

        contract = self.build_api_data_contract(payload)
        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)

        missing_sources = result["observability"]["flags"].get("missingSources") or []
        self.assertIn("yahoo", [str(v).lower() for v in missing_sources])

        recommendations = result["observability"]["autoHandlingRecommendations"]
        yahoo_rec = next(
            (row for row in recommendations if str(row.get("source") or "").lower() == "yahoo"),
            None,
        )
        self.assertIsNotNone(yahoo_rec)
        if yahoo_rec is not None:
            self.assertEqual(str(yahoo_rec.get("recommendedAction")), "skip")
            self.assertEqual(float(yahoo_rec.get("weightMultiplier")), 0.0)

    def test_policy_classifies_required_partial_source_as_degrade(self):
        payload = deepcopy(self.base_payload)
        summary = payload.setdefault("settings", {}).setdefault("sourceRunSummary", {})
        sources = summary.setdefault("sources", {})
        draftsharks = sources.setdefault("DraftSharks", {})
        draftsharks["enabled"] = True
        draftsharks["state"] = "partial"

        contract = self.build_api_data_contract(payload)
        self._sanitize_contract_value_bundles(contract)
        report = self.validate_api_data_contract(contract)
        result = self._evaluate(payload, contract_payload=contract, contract_report=report)
        self.assertEqual(result.get("status"), "pass", result)

        trust_policy = result["gates"].get("trustPolicy") if isinstance(result.get("gates"), dict) else {}
        self.assertEqual(str(trust_policy.get("publishDecision")), "allow_with_degrade")
        degrade_issues = trust_policy.get("degradeIssues") or []
        self.assertTrue(
            any(
                str(issue.get("ruleId")) == "required_source_degraded"
                and str(issue.get("source")) == "draftsharks"
                for issue in degrade_issues
                if isinstance(issue, dict)
            ),
            degrade_issues,
        )

    def test_policy_blocks_severe_disagreement_without_waiver(self):
        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)
        report = self.validate_api_data_contract(contract)
        strict_cfg = replace(
            self.cfg,
            policy_disagreement_block_player_count=1,
            policy_disagreement_block_critical_source_spike_count=1,
            policy_disagreement_degrade_player_count=1,
            policy_disagreement_degrade_source_spike_count=1,
            policy_waivers=[],
        )
        result = self._evaluate(
            payload,
            contract_payload=contract,
            contract_report=report,
            config=strict_cfg,
        )
        self.assertEqual(result.get("status"), "fail", result)
        self.assertIn("trust_policy_failed", result["summary"]["errors"])
        trust_policy = result["gates"].get("trustPolicy") if isinstance(result.get("gates"), dict) else {}
        self.assertEqual(str(trust_policy.get("publishDecision")), "block")
        hard_fail_issues = trust_policy.get("hardFailIssues") or []
        self.assertTrue(
            any(
                str(issue.get("ruleId")) == "severe_disagreement_spike"
                for issue in hard_fail_issues
                if isinstance(issue, dict)
            ),
            hard_fail_issues,
        )

    def test_policy_waiver_allows_blocking_disagreement(self):
        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)
        self._sanitize_contract_value_bundles(contract)
        report = self.validate_api_data_contract(contract)
        waived_cfg = replace(
            self.cfg,
            policy_disagreement_block_player_count=1,
            policy_disagreement_block_critical_source_spike_count=1,
            policy_disagreement_degrade_player_count=1,
            policy_disagreement_degrade_source_spike_count=1,
            policy_waivers=[
                {
                    "ruleId": "severe_disagreement_spike",
                    "scope": "global",
                    "reason": "approved_operator_override_for_test",
                }
            ],
        )
        result = self._evaluate(
            payload,
            contract_payload=contract,
            contract_report=report,
            config=waived_cfg,
        )
        self.assertEqual(result.get("status"), "pass", result)
        trust_policy = result["gates"].get("trustPolicy") if isinstance(result.get("gates"), dict) else {}
        self.assertIn(str(trust_policy.get("publishDecision")), {"allow", "allow_with_warning", "allow_with_degrade"})
        self.assertGreater(int((trust_policy.get("counts") or {}).get("hardFailWaived", 0) or 0), 0)
        waivers = trust_policy.get("waivers") if isinstance(trust_policy.get("waivers"), dict) else {}
        self.assertGreater(len(waivers.get("applied") or []), 0)

    def test_policy_blocks_critical_coverage_collapse(self):
        baseline_payload = deepcopy(self.base_payload)
        baseline_contract = self.build_api_data_contract(baseline_payload)

        payload = deepcopy(self.base_payload)
        contract = self.build_api_data_contract(payload)
        critical_sources = [
            self._normalize_source_key(v)
            for v in (self.cfg.critical_sources or [])
            if self._normalize_source_key(v)
        ]
        self.assertTrue(critical_sources, "Expected at least one configured critical source")
        if not critical_sources:
            return
        target_critical_source = critical_sources[0]
        for row in contract.get("playersArray", []):
            if not isinstance(row, dict):
                continue
            if str(row.get("position") or "").upper() != "QB":
                continue
            canonical = row.get("canonicalSiteValues")
            if not isinstance(canonical, dict):
                continue
            for source_key in list(canonical.keys()):
                if self._normalize_source_key(source_key) == target_critical_source:
                    canonical[source_key] = 0

        report = self.validate_api_data_contract(contract)
        strict_cfg = replace(
            self.cfg,
            policy_critical_coverage_collapse_block_drop_pct=25.0,
            policy_critical_coverage_collapse_block_ratio=0.85,
            policy_waivers=[],
        )
        result = self._evaluate(
            payload,
            contract_payload=contract,
            contract_report=report,
            baseline_raw_payload=baseline_payload,
            baseline_contract_payload=baseline_contract,
            config=strict_cfg,
        )
        self.assertEqual(result.get("status"), "fail", result)
        trust_policy = result["gates"].get("trustPolicy") if isinstance(result.get("gates"), dict) else {}
        self.assertEqual(str(trust_policy.get("publishDecision")), "block")
        hard_fail_issues = trust_policy.get("hardFailIssues") or []
        self.assertTrue(
            any(
                str(issue.get("ruleId")) == "critical_source_coverage_collapse"
                and self._normalize_source_key(issue.get("source")) == target_critical_source
                for issue in hard_fail_issues
                if isinstance(issue, dict)
            ),
            hard_fail_issues,
        )


if __name__ == "__main__":
    unittest.main()
