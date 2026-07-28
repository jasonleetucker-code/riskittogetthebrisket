"""Unit tests for ``scripts/bdvm_build_baseline.py``.

Pins the two behaviors a weekly prod timer depends on:

1. Carry-forward — a baseline rebuild must never evict real
   (non-proxy) records from the serving snapshot; real records win per
   player and keep their original as_of (staleness handles aging).
2. Same-day rerun — snapshots are immutable and date-stamped, so a
   boot-catch-up or manual rerun is a NO-OP success (exit 0) that
   skips the expensive nflverse fetch entirely, not a red unit blamed
   on upstream data.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "bdvm_build_baseline.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("bdvm_build_baseline", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()

from src.bdvm.projections import ProjectionRecord  # noqa: E402


def _rec(key, *, proxy, source="reconstructedBaseline", as_of="2026-07-20"):
    return ProjectionRecord(
        source=source,
        player_key=key,
        position="LB",
        season=2026,
        as_of=as_of,
        games=16.0,
        fpg=10.0,
        scoring_native=True,
        is_proxy=proxy,
    )


class TestCarryForward(unittest.TestCase):
    def test_real_records_win_per_player_and_keep_their_as_of(self):
        new = [_rec("a", proxy=True, as_of="2026-07-28"), _rec("b", proxy=True, as_of="2026-07-28")]
        prior = [
            _rec("a", proxy=False, source="idpShowProjections", as_of="2026-07-21"),
            _rec("c", proxy=True),  # prior proxies are NOT carried
        ]
        merged, carried = _mod.merge_baseline_over_prior(new, prior)
        self.assertEqual(carried, 1)
        by_key = {(r.player_key, r.source): r for r in merged}
        # a: real record carried, new proxy dropped
        self.assertIn(("a", "idpShowProjections"), by_key)
        self.assertNotIn(("a", "reconstructedBaseline"), by_key)
        self.assertEqual(by_key[("a", "idpShowProjections")].as_of, "2026-07-21")
        # b: fresh proxy kept; c: stale prior proxy gone
        self.assertIn(("b", "reconstructedBaseline"), by_key)
        self.assertNotIn(("c", "reconstructedBaseline"), by_key)

    def test_no_prior_reals_is_passthrough(self):
        new = [_rec("a", proxy=True)]
        merged, carried = _mod.merge_baseline_over_prior(new, [_rec("z", proxy=True)])
        self.assertEqual(carried, 0)
        self.assertEqual([r.player_key for r in merged], ["a"])


class TestSameDayNoOp(unittest.TestCase):
    def _contract(self, tmp: Path) -> Path:
        path = tmp / "dynasty_data_2026-07-28.json"
        path.write_text(json.dumps({"sleeper": {"scoringSettings": {"rec": 1.0}}}))
        return path

    def test_existing_target_short_circuits_before_the_fetch(self):
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            season_dir = tmp / "2026"
            season_dir.mkdir()
            # today's baseline snapshot already exists
            from datetime import datetime, timezone

            today = datetime.now(timezone.utc).date().isoformat()
            (season_dir / f"projections_{today}_baseline.json").write_text("{}")
            fetch = mock.MagicMock(side_effect=AssertionError("fetch must not run"))
            with (
                mock.patch.object(_mod._proj, "SNAPSHOT_DIR", tmp),
                mock.patch.object(_mod, "fetch_and_build_baseline", fetch),
                mock.patch.object(
                    sys,
                    "argv",
                    ["bdvm_build_baseline.py", "--season", "2026"],
                ),
            ):
                rc = _mod.main()
            self.assertEqual(rc, 0)
            fetch.assert_not_called()

    def test_write_race_collision_is_still_success(self):
        import tempfile

        from src.bdvm.projections import ProjectionError

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            contract = self._contract(tmp)
            with (
                mock.patch.object(_mod._proj, "SNAPSHOT_DIR", tmp / "snaps"),
                mock.patch.object(
                    _mod,
                    "fetch_and_build_baseline",
                    return_value=([_rec("a", proxy=True)], {"recordsBuilt": 1}),
                ),
                mock.patch.object(_mod, "latest_snapshot_path", return_value=None),
                mock.patch.object(
                    _mod,
                    "write_snapshot",
                    side_effect=ProjectionError("snapshot already exists (immutable): x"),
                ),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "bdvm_build_baseline.py",
                        "--season",
                        "2026",
                        "--contract",
                        str(contract),
                    ],
                ),
            ):
                rc = _mod.main()
            self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
