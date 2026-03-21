import json
import math
import os
import sys
import unittest
from pathlib import Path
from typing import Any


Z_FLOOR = -2.0
Z_CEILING = 4.0

CONFIDENCE_TOLERANCE_BY_STABILITY = {
    "stable": 0.01,
    "moderate": 0.02,
    "unstable": 0.04,
}


def _to_num(v: Any) -> float | None:
    try:
        n = float(v)
    except Exception:
        return None
    if not math.isfinite(n):
        return None
    return n


def _latest_payload_path(repo_root: Path) -> Path:
    candidates = sorted(repo_root.glob("data/dynasty_data_*.json"))
    if not candidates:
        raise FileNotFoundError("No data/dynasty_data_*.json files found.")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _normalize_site_value(
    *,
    site_key: str,
    canonical_value: float,
    site_stats: dict[str, Any],
    max_values: dict[str, Any],
) -> float:
    stat = site_stats.get(site_key)
    if isinstance(stat, dict):
        mean = _to_num(stat.get("mean"))
        stdev = _to_num(stat.get("stdev"))
        if mean is not None and stdev is not None and stdev > 0:
            z = (float(canonical_value) - float(mean)) / float(stdev)
            return max(0.0, min(1.0, (z - Z_FLOOR) / (Z_CEILING - Z_FLOOR)))
    mx = _to_num(max_values.get(site_key))
    if mx is None or mx <= 0:
        mx = 9999.0
    return max(0.0, min(1.0, float(canonical_value) / float(mx)))


def _source_spread(canonical_sites: dict[str, Any]) -> float:
    vals = []
    for site_val in canonical_sites.values():
        n = _to_num(site_val)
        if n is None or n <= 0:
            continue
        vals.append(float(n))
    if not vals:
        return 1.0
    return float(max(vals) / max(1.0, min(vals)))


def _normalize_source_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return "".join(ch for ch in text if ch.isalnum())


class ValuePipelineGoldenRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._prev_mike_clay_enabled = os.environ.get("MIKE_CLAY_ENABLED")
        os.environ["MIKE_CLAY_ENABLED"] = "0"

        cls.repo_root = Path(__file__).resolve().parents[2]
        if str(cls.repo_root) not in sys.path:
            sys.path.insert(0, str(cls.repo_root))

        from src.api.data_contract import build_api_data_contract, validate_api_data_contract
        from src.api.promotion_gate import load_promotion_gate_config

        cls.build_api_data_contract = staticmethod(build_api_data_contract)
        cls.validate_api_data_contract = staticmethod(validate_api_data_contract)
        cls.load_promotion_gate_config = staticmethod(load_promotion_gate_config)

        fixture_dir = cls.repo_root / "tests" / "fixtures"
        with (fixture_dir / "value_pipeline_golden_input.json").open("r", encoding="utf-8") as f:
            cls.golden_input = json.load(f)
        with (fixture_dir / "value_pipeline_golden.json").open("r", encoding="utf-8") as f:
            cls.golden_spec = json.load(f)

        cls.golden_contract = cls.build_api_data_contract(cls.golden_input)
        rows = cls.golden_contract.get("playersArray") or []
        cls.rows_by_name = {
            str(row.get("canonicalName")): row
            for row in rows
            if isinstance(row, dict) and row.get("canonicalName")
        }

        players_map = cls.golden_contract.get("players")
        cls.players_map = players_map if isinstance(players_map, dict) else {}

        site_stats = cls.golden_input.get("siteStats")
        cls.site_stats = site_stats if isinstance(site_stats, dict) else {}
        max_values = cls.golden_input.get("maxValues")
        cls.max_values = max_values if isinstance(max_values, dict) else {}
        cls.promotion_cfg = cls.load_promotion_gate_config()

    @classmethod
    def tearDownClass(cls):
        if cls._prev_mike_clay_enabled is None:
            os.environ.pop("MIKE_CLAY_ENABLED", None)
        else:
            os.environ["MIKE_CLAY_ENABLED"] = cls._prev_mike_clay_enabled

    def _assert_int_band(self, *, label: str, actual: int, lo: int, hi: int):
        self.assertGreaterEqual(actual, int(lo), f"{label}: {actual} < {lo}")
        self.assertLessEqual(actual, int(hi), f"{label}: {actual} > {hi}")

    def test_contract_is_valid(self):
        validation = self.validate_api_data_contract(self.golden_contract)
        self.assertTrue(validation.get("ok"), f"Contract validation failed: {validation}")

    def test_golden_case_regression(self):
        cases = self.golden_spec.get("cases") or []
        self.assertEqual(len(cases), 14, "Expected 14 curated golden cases")

        for case in cases:
            case_id = str(case["id"])
            expected = case["expected"]
            name = str(case["canonicalName"])
            row = self.rows_by_name.get(name)
            self.assertIsNotNone(row, f"{case_id}: missing player row for {name}")
            if row is None:
                continue

            merge_expected = expected["mergeIdentity"]
            self.assertEqual(row.get("canonicalName"), merge_expected.get("canonicalName"), case_id)
            self.assertEqual(row.get("position"), merge_expected.get("position"), case_id)
            self.assertEqual(row.get("playerId"), merge_expected.get("playerId"), case_id)
            self.assertEqual(row.get("assetClass"), merge_expected.get("assetClass"), case_id)

            canonical_sites = row.get("canonicalSiteValues")
            self.assertIsInstance(canonical_sites, dict, f"{case_id}: canonicalSiteValues missing")
            if not isinstance(canonical_sites, dict):
                continue

            source_expected = expected["sourcePresence"]
            required_sites = source_expected.get("requiredSites") or []
            present_sites = sorted(
                [
                    str(sk)
                    for sk, sv in canonical_sites.items()
                    if _to_num(sv) is not None and float(_to_num(sv)) > 0
                ]
            )

            for site_key in required_sites:
                n = _to_num(canonical_sites.get(site_key))
                self.assertTrue(n is not None and n > 0, f"{case_id}: missing required source {site_key}")

            self.assertEqual(
                present_sites,
                sorted(source_expected.get("presentSitesExpected") or []),
                f"{case_id}: present source list drifted",
            )

            source_count = int(row.get("sourceCount") or 0)
            self.assertGreaterEqual(
                source_count,
                int(source_expected.get("minSourceCount") or 0),
                f"{case_id}: sourceCount below minimum",
            )
            max_count = source_expected.get("maxSourceCount")
            if max_count is not None:
                self.assertLessEqual(source_count, int(max_count), f"{case_id}: sourceCount above maximum")

            normalized = expected["normalizedValues"]["bands"]
            for site_key, band in normalized.items():
                site_val = _to_num(canonical_sites.get(site_key))
                self.assertIsNotNone(site_val, f"{case_id}: expected normalized site missing: {site_key}")
                if site_val is None:
                    continue
                self.assertGreater(site_val, 0, f"{case_id}: expected site non-positive: {site_key}")
                norm = _normalize_site_value(
                    site_key=site_key,
                    canonical_value=float(site_val),
                    site_stats=self.site_stats,
                    max_values=self.max_values,
                )
                self.assertGreaterEqual(norm + 1e-9, float(band["min"]), f"{case_id}: norm low for {site_key}")
                self.assertLessEqual(norm - 1e-9, float(band["max"]), f"{case_id}: norm high for {site_key}")

            bundle = row.get("valueBundle") or {}
            self.assertIsInstance(bundle, dict, f"{case_id}: valueBundle missing")
            if not isinstance(bundle, dict):
                continue

            full_value = int(bundle.get("fullValue") or 0)
            raw_value = int(bundle.get("rawValue") or 0)
            self._assert_int_band(
                label=f"{case_id}: fullValue",
                actual=full_value,
                lo=int(expected["finalAdjustedValueBand"]["min"]),
                hi=int(expected["finalAdjustedValueBand"]["max"]),
            )
            self._assert_int_band(
                label=f"{case_id}: rawValue",
                actual=raw_value,
                lo=int(expected["rawValueBand"]["min"]),
                hi=int(expected["rawValueBand"]["max"]),
            )

            source_cov = bundle.get("sourceCoverage") or {}
            self.assertIsInstance(source_cov, dict, f"{case_id}: sourceCoverage missing")
            if isinstance(source_cov, dict):
                self.assertEqual(
                    int(source_cov.get("count") or 0),
                    int(expected["coverageAndConfidence"]["sourceCoverageCount"]),
                    f"{case_id}: sourceCoverage.count drifted",
                )

            confidence = float(bundle.get("confidence") or 0.0)
            expected_conf = float(expected["coverageAndConfidence"]["confidence"])
            tol = float(
                CONFIDENCE_TOLERANCE_BY_STABILITY.get(
                    str(case.get("stability") or "moderate"),
                    0.02,
                )
            )
            self.assertLessEqual(
                abs(confidence - expected_conf),
                tol,
                f"{case_id}: confidence drifted {confidence} vs {expected_conf}",
            )

            spread = round(_source_spread(canonical_sites), 4)
            self.assertEqual(
                spread,
                float(expected["coverageAndConfidence"]["sourceSpread"]),
                f"{case_id}: source spread drifted",
            )

            self.assertEqual(bool(row.get("rookie")), bool(expected["rookieExpected"]), case_id)

            injury_proxy = expected.get("injuryProxy")
            if isinstance(injury_proxy, dict):
                field = str(injury_proxy.get("field") or "").strip()
                player_map = self.players_map.get(name)
                self.assertIsInstance(player_map, dict, f"{case_id}: players map missing {name}")
                if isinstance(player_map, dict) and field:
                    self.assertEqual(
                        bool(player_map.get(field)),
                        bool(injury_proxy.get("expected")),
                        f"{case_id}: injury proxy mismatch for {field}",
                    )

            conflict = expected.get("sourceConflict")
            if isinstance(conflict, dict):
                self.assertGreaterEqual(
                    spread,
                    float(conflict.get("spreadMin") or 0.0),
                    f"{case_id}: conflict spread floor missed",
                )

    def test_latest_payload_required_sources_present(self):
        latest_payload_path = _latest_payload_path(self.repo_root)
        with latest_payload_path.open("r", encoding="utf-8") as f:
            latest_payload = json.load(f)
        latest_contract = self.build_api_data_contract(latest_payload)
        latest_rows = latest_contract.get("playersArray") or []
        latest_by_name = {
            str(row.get("canonicalName")): row
            for row in latest_rows
            if isinstance(row, dict) and row.get("canonicalName")
        }

        failures: list[str] = []
        policy_required = {
            _normalize_source_key(v)
            for v in (self.promotion_cfg.required_sources or [])
            if _normalize_source_key(v)
        }
        for case in self.golden_spec.get("cases") or []:
            case_id = str(case["id"])
            name = str(case["canonicalName"])
            source_expected = case["expected"]["sourcePresence"]
            required_sites = [str(v) for v in (source_expected.get("requiredSites") or [])]
            active_required_sites = [
                site
                for site in required_sites
                if _normalize_source_key(site) in policy_required
            ]
            min_count = int(source_expected.get("minSourceCount") or 0)
            removed_required_site_count = max(0, len(required_sites) - len(active_required_sites))
            effective_min_count = max(0, min_count - removed_required_site_count)

            row = latest_by_name.get(name)
            if not isinstance(row, dict):
                failures.append(f"{case_id}: missing player in latest payload ({name})")
                continue
            canonical_sites = row.get("canonicalSiteValues")
            if not isinstance(canonical_sites, dict):
                failures.append(f"{case_id}: missing canonicalSiteValues in latest payload ({name})")
                continue

            missing_sites = []
            for site_key in active_required_sites:
                n = _to_num(canonical_sites.get(site_key))
                if n is None or n <= 0:
                    missing_sites.append(str(site_key))
            if missing_sites:
                failures.append(
                    f"{case_id}: missing required sources in latest payload ({name}): {', '.join(missing_sites)}"
                )

            source_count = int(row.get("sourceCount") or 0)
            if source_count < effective_min_count:
                failures.append(
                    f"{case_id}: sourceCount {source_count} below minimum {effective_min_count} in latest payload ({name})"
                )

        self.assertFalse(failures, "Latest payload source-presence regressions:\n" + "\n".join(failures))


if __name__ == "__main__":
    unittest.main()
