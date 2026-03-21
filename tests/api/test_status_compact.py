import asyncio
import json
import unittest

import server


class _DummyRequest:
    def __init__(self, query_params: dict[str, str] | None = None):
        self.query_params = query_params or {}


class StatusCompactTests(unittest.TestCase):
    def test_compact_status_shape(self):
        prev_contract = server.latest_contract_data
        prev_scrape_status = dict(server.scrape_status)
        try:
            server.latest_contract_data = {"playerCount": 321, "date": "2026-03-19"}
            server.scrape_status.update(
                {
                    "running": True,
                    "is_running": True,
                    "stalled": False,
                    "next_scrape": "2026-03-19T15:00:00+00:00",
                    "error": None,
                    "last_error": None,
                }
            )
            response = asyncio.run(server.get_status(_DummyRequest({"compact": "1"})))
            payload = json.loads(response.body.decode("utf-8"))

            self.assertEqual(payload["player_count"], 321)
            self.assertEqual(payload["data_date"], "2026-03-19")
            self.assertIsInstance(payload["is_running"], bool)
            self.assertIsInstance(payload["running"], bool)
            self.assertIn("status_summary", payload)

            self.assertNotIn("source_health", payload)
            self.assertNotIn("promotion_gate", payload)
            self.assertNotIn("architecture", payload)
        finally:
            server.latest_contract_data = prev_contract
            server.scrape_status.update(prev_scrape_status)

    def test_truthy_query_parser(self):
        self.assertTrue(server._is_truthy_query_value("1"))
        self.assertTrue(server._is_truthy_query_value("true"))
        self.assertTrue(server._is_truthy_query_value("YES"))
        self.assertFalse(server._is_truthy_query_value("0"))
        self.assertFalse(server._is_truthy_query_value("false"))
        self.assertFalse(server._is_truthy_query_value(None))

    def test_full_status_exposes_offseason_clay_gate_summary(self):
        prev_contract = server.latest_contract_data
        prev_scrape_status = dict(server.scrape_status)
        try:
            server.latest_contract_data = {
                "playerCount": 321,
                "date": "2026-03-19",
                "valueAuthority": {
                    "offseasonClay": {
                        "enabled": True,
                        "importDataReady": True,
                        "seasonalGatingActive": True,
                        "seasonalGatingConfigured": True,
                        "seasonalGatingReason": "active",
                        "cutoverWindow": {
                            "policy": "explicit_yearly_window",
                            "guideYear": 2026,
                            "offseasonStartDate": "2026-01-15",
                            "week1StartDate": "2026-09-10",
                            "week1EndDate": "2026-09-14",
                        },
                    }
                },
            }
            server.scrape_status.update({"running": False, "is_running": False, "stalled": False})
            response = asyncio.run(server.get_status(_DummyRequest()))
            payload = json.loads(response.body.decode("utf-8"))
            clay = (
                payload.get("contract", {})
                .get("value_authority", {})
                .get("offseasonClay", {})
            )
            self.assertTrue(clay.get("enabled"))
            self.assertTrue(clay.get("importDataReady"))
            self.assertTrue(clay.get("seasonalGatingConfigured"))
            self.assertEqual(clay.get("cutoverWindow", {}).get("policy"), "explicit_yearly_window")
            self.assertEqual(clay.get("cutoverWindow", {}).get("guideYear"), 2026)
        finally:
            server.latest_contract_data = prev_contract
            server.scrape_status.update(prev_scrape_status)


if __name__ == "__main__":
    unittest.main()
