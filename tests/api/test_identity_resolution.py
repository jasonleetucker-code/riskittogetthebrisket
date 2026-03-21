import importlib.util
import json
import os
import unittest
from pathlib import Path


class IdentityResolutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        repo_root = Path(__file__).resolve().parents[2]
        fixture_path = repo_root / "tests" / "fixtures" / "identity_hard_cases.json"
        with fixture_path.open("r", encoding="utf-8") as f:
            cls.fixture = json.load(f)

        os.environ["DYNASTY_SCRAPER_SKIP_BOOTSTRAP"] = "true"
        scraper_path = repo_root / "Dynasty Scraper.py"
        spec = importlib.util.spec_from_file_location("dynasty_scraper_identity_test", scraper_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        cls.scraper = module

    def test_normalize_cases(self):
        for case in self.fixture.get("normalizeCases", []):
            raw = case["raw"]
            self.assertEqual(self.scraper.clean_name(raw), case["expectedClean"], raw)
            self.assertEqual(self.scraper.normalize_lookup_name(raw), case["expectedNormalized"], raw)

    def test_safe_merge_cases(self):
        for case in self.fixture.get("safeMergeCases", []):
            merged = self.scraper._is_safe_name_merge(case["src"], case["dst"])
            self.assertEqual(bool(merged), bool(case["expected"]), f"{case['src']} -> {case['dst']}")

    def test_best_match_cases(self):
        for case in self.fixture.get("bestMatchCases", []):
            matched = self.scraper.best_match(
                case["target"],
                case["candidates"],
                threshold=float(case.get("threshold", 0.78)),
                match_guard=self.scraper._is_safe_name_merge,
            )
            self.assertEqual(matched, case["expected"], case["target"])


if __name__ == "__main__":
    unittest.main()
