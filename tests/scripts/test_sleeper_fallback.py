"""Behavioral tests for the Sleeper cached-fallback helpers (roadmap 1.5).

``Dynasty Scraper.py`` does import-time network work, so — like the
rest of the suite — we do NOT import it.  Instead we ast-extract just
the three pure filesystem helpers and exec them in isolation against a
tmp dir.  This exercises the real shipped code path.
"""
from __future__ import annotations

import ast
import json
import os
import time
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SCRAPER = _REPO / "Dynasty Scraper.py"
_TARGETS = {"_save_sleeper_snapshot", "_load_sleeper_snapshot", "_stamp_sleeper_success"}


def _load_helpers(cache_path: str, stamp_path: str) -> dict:
    tree = ast.parse(_SCRAPER.read_text(encoding="utf-8"))
    src_parts: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in _TARGETS:
            src_parts.append(ast.get_source_segment(_SCRAPER.read_text(encoding="utf-8"), node))
    assert len(src_parts) == len(_TARGETS), f"missing helpers: found {len(src_parts)}"
    ns: dict = {"os": os, "json": json, "time": time}
    exec(compile("\n\n".join(src_parts), "<sleeper_helpers>", "exec"), ns)
    # Helpers read these module globals at call time.
    ns["_SLEEPER_CACHE_PATH"] = cache_path
    ns["_SLEEPER_STAMP_PATH"] = stamp_path
    return ns


class SleeperFallbackHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self.tmp = tempfile.mkdtemp()
        self.cache = os.path.join(self.tmp, "data", "sleeper_last_good.json")
        self.stamp = os.path.join(self.tmp, "data", "scrape_state", "sleeper_last_success")
        self.h = _load_helpers(self.cache, self.stamp)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_save_then_load_roundtrip(self) -> None:
        rd = {"leagueId": "L1", "teams": [{"id": 1}], "trades": [{"tx": "a"}]}
        self.h["_save_sleeper_snapshot"](rd)
        loaded, age = self.h["_load_sleeper_snapshot"]()
        self.assertEqual(loaded, rd)
        self.assertIsNotNone(age)
        self.assertLess(age, 1.0)  # just saved → < 1h old

    def test_load_missing_returns_none(self) -> None:
        loaded, age = self.h["_load_sleeper_snapshot"]()
        self.assertIsNone(loaded)
        self.assertIsNone(age)

    def test_load_corrupt_returns_none(self) -> None:
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        with open(self.cache, "w") as f:
            f.write("{ not json")
        self.assertEqual(self.h["_load_sleeper_snapshot"](), (None, None))

    def test_load_empty_rosterdata_returns_none(self) -> None:
        os.makedirs(os.path.dirname(self.cache), exist_ok=True)
        with open(self.cache, "w") as f:
            json.dump({"savedAt": time.time(), "rosterData": {}}, f)
        self.assertEqual(self.h["_load_sleeper_snapshot"](), (None, None))

    def test_stamp_writes_epoch(self) -> None:
        self.h["_stamp_sleeper_success"]()
        self.assertTrue(os.path.exists(self.stamp))
        val = float(Path(self.stamp).read_text().strip())
        self.assertLess(abs(time.time() - val), 5.0)

    def test_save_is_best_effort_no_raise(self) -> None:
        # Point the cache at an unwritable location → must not raise.
        bad = _load_helpers("/proc/cannot/write/here.json", self.stamp)
        try:
            bad["_save_sleeper_snapshot"]({"a": 1})  # should swallow OSError
        except Exception as e:  # noqa: BLE001
            self.fail(f"_save_sleeper_snapshot must be best-effort, raised {e}")


if __name__ == "__main__":
    unittest.main()
