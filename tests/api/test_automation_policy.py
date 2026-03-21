import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone

import server


class AutomationPolicyTests(unittest.TestCase):
    def test_scrape_delay_policy_applies_backoff_and_cap(self):
        original = {
            "SCRAPE_INTERVAL_HOURS": server.SCRAPE_INTERVAL_HOURS,
            "SCRAPE_FAILURE_BACKOFF_MINUTES": server.SCRAPE_FAILURE_BACKOFF_MINUTES,
            "SCRAPE_MAX_BACKOFF_HOURS": server.SCRAPE_MAX_BACKOFF_HOURS,
            "SCRAPE_INTERVAL_JITTER_MINUTES": server.SCRAPE_INTERVAL_JITTER_MINUTES,
        }
        try:
            server.SCRAPE_INTERVAL_HOURS = 4.0
            server.SCRAPE_FAILURE_BACKOFF_MINUTES = 60
            server.SCRAPE_MAX_BACKOFF_HOURS = 12.0
            server.SCRAPE_INTERVAL_JITTER_MINUTES = 0

            base = server._compute_scrape_delay_seconds(failure_count=0, include_jitter=False)
            self.assertEqual(base, 4 * 3600)

            one_failure = server._compute_scrape_delay_seconds(failure_count=1, include_jitter=False)
            self.assertEqual(one_failure, 5 * 3600)

            # 20 failures would imply 24h+ without capping, but policy caps at 12h.
            capped = server._compute_scrape_delay_seconds(failure_count=20, include_jitter=False)
            self.assertEqual(capped, 12 * 3600)
        finally:
            server.SCRAPE_INTERVAL_HOURS = original["SCRAPE_INTERVAL_HOURS"]
            server.SCRAPE_FAILURE_BACKOFF_MINUTES = original["SCRAPE_FAILURE_BACKOFF_MINUTES"]
            server.SCRAPE_MAX_BACKOFF_HOURS = original["SCRAPE_MAX_BACKOFF_HOURS"]
            server.SCRAPE_INTERVAL_JITTER_MINUTES = original["SCRAPE_INTERVAL_JITTER_MINUTES"]

    def test_health_degrades_when_scrape_age_exceeds_policy(self):
        prev_scrape_status = dict(server.scrape_status)
        prev_contract = dict(server.contract_health)
        prev_gate = dict(server.promotion_gate_state)
        prev_threshold = server.MAX_HEALTHY_SCRAPE_AGE_HOURS

        try:
            server.MAX_HEALTHY_SCRAPE_AGE_HOURS = 2.0
            old_scrape = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
            server.scrape_status.update(
                {
                    "running": False,
                    "stalled": False,
                    "error": None,
                    "last_scrape": old_scrape,
                    "last_heartbeat": datetime.now(timezone.utc).isoformat(),
                }
            )
            server.contract_health.update({"ok": True})
            server.promotion_gate_state.update(
                {
                    "lastStatus": "pass",
                    "lastSuccessAt": datetime.now(timezone.utc).isoformat(),
                    "lastFailureAt": None,
                    "lastFailureSummary": "",
                }
            )

            response = asyncio.run(server.get_health())
            payload = json.loads(response.body.decode("utf-8"))
            self.assertEqual(response.status_code, 503)
            self.assertTrue(bool(payload.get("scrape_age_exceeded")))
        finally:
            server.scrape_status.update(prev_scrape_status)
            server.contract_health.update(prev_contract)
            server.promotion_gate_state.update(prev_gate)
            server.MAX_HEALTHY_SCRAPE_AGE_HOURS = prev_threshold


if __name__ == "__main__":
    unittest.main()
