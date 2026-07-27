"""Guard the BDVM reference fixture (docs/research/bdvm-v1/reference/).

The reference is the acceptance fixture for the production package: any
accidental edit to it must fail CI.  ``run_examples.py`` is executed
unchanged and its output compared token-for-token against the committed
``examples_output.txt`` (whitespace-normalized — column padding is not
semantic; every number is).
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_DIR = REPO_ROOT / "docs" / "research" / "bdvm-v1" / "reference"


class TestReferenceFixture(unittest.TestCase):
    def test_reference_files_present(self):
        for name in (
            "dynasty_engine.py",
            "run_examples.py",
            "examples_output.txt",
            "schema.sql",
            "league_config.example.json",
            "player_payload.example.json",
            "README.md",
        ):
            self.assertTrue((REFERENCE_DIR / name).exists(), f"missing reference file {name}")

    def test_run_examples_reproduces_committed_output(self):
        result = subprocess.run(
            [sys.executable, "run_examples.py"],
            cwd=REFERENCE_DIR,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        self.assertEqual(result.returncode, 0, f"reference run failed: {result.stderr[:2000]}")
        actual = result.stdout.split()
        expected = (REFERENCE_DIR / "examples_output.txt").read_text(encoding="utf-8").split()
        self.assertEqual(len(actual), len(expected), "token count drifted from golden output")
        mismatches = [(i, e, a) for i, (e, a) in enumerate(zip(expected, actual)) if e != a]
        self.assertEqual(
            mismatches[:10], [], f"{len(mismatches)} token mismatches vs golden output"
        )

    def test_reference_is_not_importable_from_src(self):
        """No production module may IMPORT the reference implementation.

        Docstring mentions are fine; import statements or file loads of
        the frozen fixture are not.
        """
        import re

        patterns = (
            re.compile(r"^\s*(import|from)\s+dynasty_engine\b", re.MULTILINE),
            re.compile(r"spec_from_file_location\([^)]*dynasty_engine", re.DOTALL),
            re.compile(r"reference[/\\]dynasty_engine\.py"),
        )
        hits = []
        for py in (REPO_ROOT / "src").rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="replace")
            if any(p.search(text) for p in patterns):
                hits.append(str(py))
        self.assertEqual(hits, [], "production code imports the frozen reference fixture")


if __name__ == "__main__":
    unittest.main()
