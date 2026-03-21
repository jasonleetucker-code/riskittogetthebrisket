import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path

import server
from src.api.raw_fallback_health import scan_raw_fallback_health


class _DummyRequest:
    def __init__(self, query_params: dict[str, str] | None = None):
        self.query_params = query_params or {}


class FrontendRawFallbackHealthTests(unittest.TestCase):
    def _write(self, path: Path, content: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_scan_reports_skipped_invalid_files_and_selected_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)
            data_dir = base_dir / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            invalid = self._write(data_dir / "dynasty_data_2026-03-20.json", '{"players": ')
            valid = self._write(
                base_dir / "dynasty_data_2026-03-19.json",
                json.dumps({"players": {"A": {}}, "generatedAt": "2026-03-19T12:00:00Z"}),
            )
            os.utime(valid, (1_742_382_400, 1_742_382_400))
            os.utime(invalid, (1_742_468_800, 1_742_468_800))

            payload, skipped_paths = scan_raw_fallback_health(
                base_dir,
                data_dir,
                checked_at="2026-03-20T15:00:00+00:00",
            )

            self.assertEqual(payload["status"], "warning")
            self.assertEqual(payload["selected_source"], "dynasty_data_2026-03-19.json")
            self.assertEqual(payload["selected_source_type"], "json")
            self.assertEqual(payload["skipped_file_count"], 1)
            self.assertEqual(payload["skipped_files"][0]["file"], "data/dynasty_data_2026-03-20.json")
            self.assertEqual(len(skipped_paths), 1)
            self.assertEqual(skipped_paths[0].name, "dynasty_data_2026-03-20.json")

    def test_status_and_health_surface_frontend_raw_fallback_summary(self):
        prev_base_dir = server.BASE_DIR
        prev_data_dir = server.DATA_DIR
        prev_contract = server.latest_contract_data
        prev_scrape_status = dict(server.scrape_status)
        prev_contract_health = dict(server.contract_health)
        prev_frontend_runtime = dict(server.frontend_runtime_status)
        prev_raw_cache = server._frontend_raw_fallback_health_cache
        prev_raw_cache_at = server._frontend_raw_fallback_health_cache_at
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base_dir = Path(tmpdir)
                data_dir = base_dir / "data"
                data_dir.mkdir(parents=True, exist_ok=True)
                invalid = self._write(data_dir / "dynasty_data_2026-03-20.json", '{"players": ')
                valid = self._write(
                    base_dir / "dynasty_data_2026-03-19.json",
                    json.dumps({"players": {"A": {}}, "generatedAt": "2026-03-19T12:00:00Z"}),
                )
                os.utime(valid, (1_742_382_400, 1_742_382_400))
                os.utime(invalid, (1_742_468_800, 1_742_468_800))

                server.BASE_DIR = base_dir
                server.DATA_DIR = data_dir
                server._frontend_raw_fallback_health_cache = None
                server._frontend_raw_fallback_health_cache_at = 0.0
                server.latest_contract_data = {"playerCount": 12, "date": "2026-03-20"}
                server.contract_health.update({"ok": True, "status": "healthy", "errors": [], "warnings": []})
                now_iso = server._utc_now_iso()
                server.scrape_status.update(
                    {
                        "running": False,
                        "is_running": False,
                        "stalled": False,
                        "last_scrape": now_iso,
                        "last_error": None,
                        "error": None,
                    }
                )
                server.frontend_runtime_status.update({"configured": "next", "active": "next", "reason": "test"})

                status_response = asyncio.run(server.get_status(_DummyRequest()))
                status_payload = json.loads(status_response.body.decode("utf-8"))
                raw_fallback = status_payload["frontend_runtime"]["raw_fallback_health"]
                self.assertEqual(raw_fallback["status"], "warning")
                self.assertEqual(raw_fallback["selected_source"], "dynasty_data_2026-03-19.json")
                self.assertEqual(raw_fallback["skipped_file_count"], 1)
                self.assertEqual(raw_fallback["skipped_files"][0]["file"], "data/dynasty_data_2026-03-20.json")

                health_response = asyncio.run(server.get_health())
                self.assertEqual(health_response.status_code, 200)
                health_payload = json.loads(health_response.body.decode("utf-8"))
                self.assertEqual(health_payload["frontend_raw_fallback"]["status"], "warning")
                self.assertEqual(health_payload["frontend_raw_fallback"]["skipped_file_count"], 1)
                self.assertIn("frontend_raw_fallback_skipped_files", health_payload["warnings"])
        finally:
            server.BASE_DIR = prev_base_dir
            server.DATA_DIR = prev_data_dir
            server.latest_contract_data = prev_contract
            server.scrape_status.update(prev_scrape_status)
            server.contract_health.update(prev_contract_health)
            server.frontend_runtime_status.update(prev_frontend_runtime)
            server._frontend_raw_fallback_health_cache = prev_raw_cache
            server._frontend_raw_fallback_health_cache_at = prev_raw_cache_at


if __name__ == "__main__":
    unittest.main()
