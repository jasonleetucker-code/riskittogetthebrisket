"""Guards for scripts/fetch_dynasty_nerds.py.

Covers the schema probe (DR_DATA missing SFLEXTEP) and row-count floor
added as part of the source-monitoring hardening pass.
"""
from __future__ import annotations

import json
import unittest

from scripts import fetch_dynasty_nerds as dn


def _wrap_html(data_obj: dict) -> str:
    """Wrap a Python dict into a minimal DR_DATA HTML fragment."""
    return f"<html><body><script>DR_DATA = {json.dumps(data_obj)};</script></body></html>"


class TestExtractDrDataSchemaProbe(unittest.TestCase):
    def test_valid_payload_returns_dict(self):
        html = _wrap_html({"SFLEXTEP": [], "_meta": {}})
        out = dn._extract_dr_data(html)
        self.assertIn("SFLEXTEP", out)

    def test_missing_sflextep_raises_schema_error(self):
        """DR_DATA missing the SFLEXTEP key triggers DynastyNerdsSchemaError."""
        html = _wrap_html({"PPR": [], "SFLEX": [], "_meta": {}})
        with self.assertRaises(dn.DynastyNerdsSchemaError):
            dn._extract_dr_data(html)

    def test_missing_sflextep_logs_available_keys(self):
        """Schema error message lists the keys that WERE present."""
        html = _wrap_html({"PPR": [], "SFLEX": [], "_meta": {}})
        try:
            dn._extract_dr_data(html)
        except dn.DynastyNerdsSchemaError as exc:
            msg = str(exc)
            self.assertIn("SFLEXTEP", msg)
            self.assertTrue(
                any(k in msg for k in ("PPR", "SFLEX", "_meta")),
                f"Expected available keys in error message, got {msg}",
            )
        else:
            self.fail("Expected DynastyNerdsSchemaError")


class TestMainExitCodes(unittest.TestCase):
    def test_main_exits_2_on_missing_sflextep(self):
        """main() returns exit code 2 when DR_DATA missing SFLEXTEP."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "dn.html"
            html_path.write_text(
                _wrap_html({"PPR": [], "_meta": {}}), encoding="utf-8"
            )
            dest_path = Path(tmpdir) / "out.csv"
            rc = dn.main(
                [
                    "--from-file",
                    str(html_path),
                    "--dest",
                    str(dest_path),
                ]
            )
        self.assertEqual(
            rc,
            2,
            f"Expected exit code 2 for schema regression, got {rc}",
        )

    def test_main_exits_2_on_low_row_count(self):
        """main() returns exit code 2 when SFLEXTEP has too few rows."""
        import tempfile
        from pathlib import Path

        # Build a DR_DATA blob with only 5 valid rows (well below 230).
        tiny_sflextep = [
            {
                "firstName": f"First{i}",
                "lastName": f"Last{i}",
                "rank": i + 1,
                "value": 100 - i,
                "sleeperId": str(1000 + i),
                "pos": "RB",
                "team": "NFL",
            }
            for i in range(5)
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            html_path = Path(tmpdir) / "dn.html"
            html_path.write_text(
                _wrap_html({"SFLEXTEP": tiny_sflextep, "_meta": {}}),
                encoding="utf-8",
            )
            dest_path = Path(tmpdir) / "out.csv"
            rc = dn.main(
                [
                    "--from-file",
                    str(html_path),
                    "--dest",
                    str(dest_path),
                ]
            )
        self.assertEqual(
            rc,
            2,
            f"Expected exit code 2 for low row count, got {rc}",
        )


if __name__ == "__main__":
    unittest.main()
