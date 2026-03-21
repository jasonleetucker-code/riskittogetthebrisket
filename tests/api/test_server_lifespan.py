import asyncio
import unittest

import server


class ServerLifespanTests(unittest.TestCase):
    def test_startup_scrape_can_be_disabled_without_scheduling_or_shutdown_error(self):
        original_startup_enabled = server.SCRAPE_STARTUP_ENABLED
        original_scheduler_enabled = server.SCRAPE_SCHEDULER_ENABLED
        original_run_scraper = server.run_scraper
        original_schedule_loop = server.schedule_loop
        original_uptime_watchdog_loop = server.uptime_watchdog_loop

        async def unexpected_run_scraper(*args, **kwargs):
            raise AssertionError("startup scrape should not run when SCRAPE_STARTUP_ENABLED=false")

        async def noop_loop():
            return None

        async def exercise_lifespan():
            async with server.lifespan(server.app):
                await asyncio.sleep(0)

        try:
            server.SCRAPE_STARTUP_ENABLED = False
            server.SCRAPE_SCHEDULER_ENABLED = False
            server.run_scraper = unexpected_run_scraper
            server.schedule_loop = noop_loop
            server.uptime_watchdog_loop = noop_loop
            asyncio.run(exercise_lifespan())
        finally:
            server.SCRAPE_STARTUP_ENABLED = original_startup_enabled
            server.SCRAPE_SCHEDULER_ENABLED = original_scheduler_enabled
            server.run_scraper = original_run_scraper
            server.schedule_loop = original_schedule_loop
            server.uptime_watchdog_loop = original_uptime_watchdog_loop


if __name__ == "__main__":
    unittest.main()
