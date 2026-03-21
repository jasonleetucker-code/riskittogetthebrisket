import asyncio
import json
import time
import unittest
from pathlib import Path

import server
from src.api.data_contract import build_api_data_contract


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "trade_scoring_matrix_cases.json"


class _DummyJsonRequest:
    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


class TradeScoringMatrixTests(unittest.TestCase):
    def setUp(self):
        self._prev_contract = server.latest_contract_data
        self.contract = self._build_contract_fixture()
        server.latest_contract_data = self.contract
        with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
            fixture_payload = json.load(fh)
        self.matrix_cases = list(fixture_payload.get("cases") or [])

    def tearDown(self):
        server.latest_contract_data = self._prev_contract

    @staticmethod
    def _build_contract_fixture():
        raw_payload = {
            "sites": [
                {"key": "ktc"},
                {"key": "fantasyCalc"},
                {"key": "idpTradeCalc"},
            ],
            "maxValues": {
                "ktc": 10000,
                "fantasyCalc": 10000,
                "idpTradeCalc": 10000,
            },
            "players": {
                "Alpha QB": {
                    "_sites": 3,
                    "_rawComposite": 5000,
                    "_scoringAdjusted": 5400,
                    "_scarcityAdjusted": 5600,
                    "_bestBallAdjusted": 5680,
                    "_finalAdjusted": 6100,
                    "_marketConfidence": 0.83,
                    "_canonicalSiteValues": {"ktc": 5050, "fantasyCalc": 4980, "idpTradeCalc": None},
                },
                "Beta LB": {
                    "_sites": 3,
                    "_rawComposite": 4100,
                    "_scoringAdjusted": 4250,
                    "_scarcityAdjusted": 4380,
                    "_bestBallAdjusted": 4480,
                    "_finalAdjusted": 4525,
                    "_marketConfidence": 0.74,
                    "_canonicalSiteValues": {"ktc": 4150, "fantasyCalc": 4050, "idpTradeCalc": 4300},
                    "_isRookie": True,
                },
                "Gamma TE": {
                    "_sites": 3,
                    "_rawComposite": 4625,
                    "_scoringAdjusted": 5600,
                    "_scarcityAdjusted": 5480,
                    "_bestBallAdjusted": 5555,
                    "_finalAdjusted": 5280,
                    "_marketConfidence": 0.79,
                    "_canonicalSiteValues": {"ktc": 4700, "fantasyCalc": 4550, "idpTradeCalc": None},
                },
                "Delta WR": {
                    "_sites": 3,
                    "_rawComposite": 4550,
                    "_scoringAdjusted": 4700,
                    "_scarcityAdjusted": 4760,
                    "_bestBallAdjusted": 4850,
                    "_finalAdjusted": 4800,
                    "_marketConfidence": 0.78,
                    "_canonicalSiteValues": {"ktc": 4600, "fantasyCalc": 4520, "idpTradeCalc": None},
                },
                "Epsilon RB": {
                    "_sites": 3,
                    "_rawComposite": 4700,
                    "_scoringAdjusted": 4880,
                    "_scarcityAdjusted": 4920,
                    "_bestBallAdjusted": 4990,
                    "_finalAdjusted": 5000,
                    "_marketConfidence": 0.77,
                    "_canonicalSiteValues": {"ktc": 4780, "fantasyCalc": 4660, "idpTradeCalc": None},
                },
                "Rookie WR": {
                    "_sites": 2,
                    "_rawComposite": 3200,
                    "_scoringAdjusted": 3390,
                    "_scarcityAdjusted": 3510,
                    "_bestBallAdjusted": 3580,
                    "_finalAdjusted": 3600,
                    "_marketConfidence": 0.69,
                    "_canonicalSiteValues": {"ktc": 3350, "fantasyCalc": 3150, "idpTradeCalc": None},
                    "_isRookie": True,
                },
                "2026 Pick 1.01": {
                    "_sites": 3,
                    "_rawComposite": 7000,
                    "_scoringAdjusted": 7000,
                    "_scarcityAdjusted": 7000,
                    "_bestBallAdjusted": 7000,
                    "_finalAdjusted": 7000,
                    "_marketConfidence": 0.66,
                    "_canonicalSiteValues": {"ktc": 7000, "fantasyCalc": 6900, "idpTradeCalc": None},
                },
                "2026 Pick 2.06": {
                    "_sites": 3,
                    "_rawComposite": 4200,
                    "_scoringAdjusted": 4200,
                    "_scarcityAdjusted": 4200,
                    "_bestBallAdjusted": 4200,
                    "_finalAdjusted": 4200,
                    "_marketConfidence": 0.63,
                    "_canonicalSiteValues": {"ktc": 4200, "fantasyCalc": 4100, "idpTradeCalc": None},
                },
                "2027 Pick 1.11": {
                    "_sites": 3,
                    "_rawComposite": 3300,
                    "_scoringAdjusted": 3300,
                    "_scarcityAdjusted": 3300,
                    "_bestBallAdjusted": 3300,
                    "_finalAdjusted": 3300,
                    "_marketConfidence": 0.61,
                    "_canonicalSiteValues": {"ktc": 3300, "fantasyCalc": 3210, "idpTradeCalc": None},
                },
                # No position mapping on purpose so this row is quarantined from final authority.
                "Mystery Asset": {
                    "_sites": 2,
                    "_rawComposite": 3900,
                    "_scoringAdjusted": 4000,
                    "_scarcityAdjusted": 4100,
                    "_bestBallAdjusted": 4200,
                    "_finalAdjusted": 4300,
                    "_marketConfidence": 0.73,
                    "_canonicalSiteValues": {"ktc": 3950, "fantasyCalc": 3850, "idpTradeCalc": None},
                },
            },
            "sleeper": {
                "positions": {
                    "Alpha QB": "QB",
                    "Beta LB": "LB",
                    "Gamma TE": "TE",
                    "Delta WR": "WR",
                    "Epsilon RB": "RB",
                    "Rookie WR": "WR",
                    "2026 Pick 1.01": "PICK",
                    "2026 Pick 2.06": "PICK",
                    "2027 Pick 1.11": "PICK",
                }
            },
        }
        return build_api_data_contract(raw_payload)

    def _score(self, payload):
        response = asyncio.run(server.score_trade(_DummyJsonRequest(payload)))
        self.assertEqual(response.status_code, 200, response.body.decode("utf-8"))
        return json.loads(response.body.decode("utf-8"))

    @staticmethod
    def _resolved_lookup(side_payload):
        out = {}
        for row in side_payload.get("resolvedEntries", []):
            key = str(row.get("canonicalName") or row.get("name") or row.get("label") or "").strip()
            if key:
                out[key] = row
        return out

    def _assert_matrix_case(self, case_payload):
        request_payload = case_payload["request"]
        expected = case_payload.get("expect", {})
        result = self._score(request_payload)
        self.assertEqual(str(result.get("authority")), "backend_trade_scoring_v1", case_payload["id"])

        expected_summary = expected.get("summary") or {}
        summary = result.get("summary") or {}
        for key, val in expected_summary.items():
            self.assertEqual(int(summary.get(key) or 0), int(val), f"{case_payload['id']}: summary.{key}")

        side_resolution = expected.get("sideResolution") or {}
        for side, counts in side_resolution.items():
            resolution = (result.get("sides", {}).get(side, {}) or {}).get("resolution", {}) or {}
            for key, val in (counts or {}).items():
                self.assertEqual(int(resolution.get(key) or 0), int(val), f"{case_payload['id']}: {side}.{key}")

        for side in expected.get("weightedTotalsPositiveSides") or []:
            weighted = float((result.get("sides", {}).get(side, {}) or {}).get("weightedTotal") or 0)
            self.assertGreater(weighted, 0.0, f"{case_payload['id']}: {side} weightedTotal should be positive")

        for expected_row in expected.get("requireResolved") or []:
            side = str(expected_row.get("side") or "")
            side_payload = result.get("sides", {}).get(side, {}) or {}
            resolved = self._resolved_lookup(side_payload)
            row_key = str(expected_row.get("canonicalName") or expected_row.get("name") or "").strip()
            self.assertIn(row_key, resolved, f"{case_payload['id']}: missing resolved row {row_key}")
            row = resolved[row_key]

            if "resolutionPrefix" in expected_row:
                self.assertTrue(
                    str(row.get("resolution") or "").startswith(str(expected_row["resolutionPrefix"])),
                    f"{case_payload['id']}: {row_key} resolution prefix",
                )
            if "resolution" in expected_row:
                self.assertEqual(str(row.get("resolution") or ""), str(expected_row["resolution"]))
            if "assetClass" in expected_row:
                self.assertEqual(str(row.get("assetClass") or "").lower(), str(expected_row["assetClass"]).lower())
            if "value" in expected_row:
                self.assertEqual(int(row.get("value") or 0), int(expected_row["value"]))
            if "source" in expected_row:
                self.assertEqual(str(row.get("source") or ""), str(expected_row["source"]))

        for expected_unresolved in expected.get("requireUnresolvedReasons") or []:
            side = str(expected_unresolved.get("side") or "")
            unresolved = (result.get("sides", {}).get(side, {}) or {}).get("unresolvedEntries", []) or []
            reasons = {str(row.get("reason") or "") for row in unresolved}
            self.assertIn(
                str(expected_unresolved.get("reason") or ""),
                reasons,
                f"{case_payload['id']}: unresolved reason missing on side {side}",
            )

    def test_trade_scoring_matrix_fixture_cases(self):
        self.assertGreater(len(self.matrix_cases), 0, "matrix fixture must include cases")
        for case_payload in self.matrix_cases:
            with self.subTest(case=case_payload.get("id")):
                self._assert_matrix_case(case_payload)

    def test_best_ball_toggle_changes_package_totals_for_same_inputs(self):
        payload_base = {
            "valueBasis": "full",
            "alpha": 1.7,
            "sides": {
                "A": [
                    {"label": "Gamma TE", "fallbackValue": 1},
                    {"label": "Delta WR", "fallbackValue": 1},
                    {"label": "Rookie WR", "fallbackValue": 1},
                ],
                "B": [
                    {"label": "Epsilon RB", "fallbackValue": 1},
                ],
                "C": [],
            },
        }
        best_ball_on = self._score({**payload_base, "bestBallMode": True})
        best_ball_off = self._score({**payload_base, "bestBallMode": False})

        side_a_on = float(best_ball_on["sides"]["A"]["weightedTotal"] or 0)
        side_a_off = float(best_ball_off["sides"]["A"]["weightedTotal"] or 0)
        self.assertNotEqual(
            round(side_a_on, 3),
            round(side_a_off, 3),
            "best-ball mode toggle should change package totals for depth package",
        )

    def test_stress_large_packages_and_rapid_repeat_calls(self):
        side_a = [{"label": "Alpha QB", "fallbackValue": 1}] * 12
        side_a += [{"label": "2026 Pick 1.01", "fallbackValue": 1}] * 6
        side_a += [{"label": "Unknown Manual A", "fallbackValue": 1500, "manualOverride": True, "pos": "WR"}] * 2

        side_b = [{"label": "Beta LB", "fallbackValue": 1}] * 10
        side_b += [{"label": "Rookie WR", "fallbackValue": 1}] * 8
        side_b += [{"label": "2026 Pick 2.06", "fallbackValue": 1}] * 2

        side_c = [{"label": "Epsilon RB", "fallbackValue": 1}] * 8
        side_c += [{"label": "Unknown With Fallback C", "fallbackValue": 1300, "pos": "RB"}] * 3
        side_c += [{"label": "Mystery Asset", "fallbackValue": 3900}] * 2

        payload = {
            "valueBasis": "full",
            "alpha": 1.95,
            "bestBallMode": True,
            "sides": {"A": side_a, "B": side_b, "C": side_c},
        }

        start = time.perf_counter()
        latest = None
        for _ in range(20):
            latest = self._score(payload)
        elapsed = time.perf_counter() - start

        self.assertIsNotNone(latest)
        self.assertLess(elapsed, 12.0, "stress loop should remain deterministic and fast enough for CI")
        self.assertGreater(float(latest["sides"]["A"]["weightedTotal"] or 0), 0)
        self.assertGreater(float(latest["sides"]["B"]["weightedTotal"] or 0), 0)
        self.assertGreater(float(latest["sides"]["C"]["weightedTotal"] or 0), 0)
        summary = latest.get("summary") or {}
        self.assertGreaterEqual(int(summary.get("fallbackUsed") or 0), 2)
        self.assertGreaterEqual(int(summary.get("quarantinedExcluded") or 0), 1)


if __name__ == "__main__":
    unittest.main()
