"""Unit tests for ``scripts/backfill_rank_history.py``.

We don't invoke ``build_api_data_contract`` directly here — a real
contract build pulls the full pipeline and isn't what this script
is responsible for.  Instead we inject a pass-through
``build_contract`` so the test can stuff a pre-built contract into
each synthetic zip and verify the iteration / dedup / dry-run
plumbing around it.
"""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "backfill_rank_history.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("backfill_rank_history", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


_mod = _load_module()


def _contract(rank_by_name: dict[str, int], asset_class: str = "offense") -> dict[str, Any]:
    return {
        "playersArray": [
            {
                "canonicalName": name,
                "displayName": name,
                "canonicalConsensusRank": rank,
                "assetClass": asset_class,
            }
            for name, rank in rank_by_name.items()
        ]
    }


def _write_zip(path: Path, *, date: str, payload: dict[str, Any]) -> None:
    """Write a synthetic archive with the same member layout the real
    scraper produces — ``manifest.json`` plus
    ``dynasty_data_<DATE>.json`` — so the script's zip-reader path is
    exercised end-to-end."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "manifest.json",
            json.dumps({"date": date, "files": [f"dynasty_data_{date}.json"]}),
        )
        z.writestr(f"dynasty_data_{date}.json", json.dumps(payload))


def _passthrough(raw: dict[str, Any]) -> dict[str, Any]:
    """Injected ``build_contract`` that returns the raw payload
    unchanged — our synthetic raw already carries a ``playersArray``."""
    return raw


class TestBackfillThreeSnapshots(unittest.TestCase):
    def test_writes_three_entries_in_date_order(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            # Three synthetic archives, intentionally created out of
            # date order and with differing HHMMSS timestamps so the
            # test exercises sort + filename parsing rather than
            # relying on filesystem-iteration order.
            _write_zip(
                archive / "dynasty_export_20260310_120000.zip",
                date="2026-03-10",
                payload=_contract({"Alice": 1, "Bob": 2}),
            )
            _write_zip(
                archive / "dynasty_export_20260308_090000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 2, "Bob": 1}),
            )
            _write_zip(
                archive / "dynasty_export_20260309_110000.zip",
                date="2026-03-09",
                payload=_contract({"Alice": 1, "Bob": 3}),
            )

            results = _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            self.assertEqual(len(results), 3)
            self.assertTrue(all(r["appended"] for r in results))
            self.assertEqual(
                [r["date"] for r in results],
                ["2026-03-08", "2026-03-09", "2026-03-10"],
            )

            # JSONL: exactly three entries, in chronological order.
            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            parsed = [json.loads(line) for line in lines]
            self.assertEqual(
                [e["date"] for e in parsed],
                ["2026-03-08", "2026-03-09", "2026-03-10"],
            )
            # Rank maps carry the composite ``name::assetClass`` key
            # the snapshot path actually stores — so each synthetic
            # player lands under ``Alice::offense`` / ``Bob::offense``.
            self.assertEqual(
                parsed[0]["ranks"],
                {"Alice::offense": 2, "Bob::offense": 1},
            )
            self.assertEqual(
                parsed[2]["ranks"],
                {"Alice::offense": 1, "Bob::offense": 2},
            )

    def test_is_idempotent_across_reruns(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            _write_zip(
                archive / "dynasty_export_20260308_090000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 1}),
            )
            _write_zip(
                archive / "dynasty_export_20260309_090000.zip",
                date="2026-03-09",
                payload=_contract({"Alice": 1}),
            )
            _write_zip(
                archive / "dynasty_export_20260310_090000.zip",
                date="2026-03-10",
                payload=_contract({"Alice": 1}),
            )

            # First run lays down three entries.
            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_passthrough,
                out=io.StringIO(),
            )
            # Second run must be a no-growth fixed point — per-date
            # dedup inside ``append_snapshot`` rewrites the entry
            # rather than appending a fourth.
            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 3)
            self.assertEqual(
                [json.loads(line)["date"] for line in lines],
                ["2026-03-08", "2026-03-09", "2026-03-10"],
            )


class TestBackfillDrySelection(unittest.TestCase):
    def test_dry_run_does_not_write(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            _write_zip(
                archive / "dynasty_export_20260308_090000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 1}),
            )

            buf = io.StringIO()
            results = _mod.backfill(
                archive_dir=archive,
                history_path=history,
                dry_run=True,
                build_contract=_passthrough,
                out=buf,
            )

            self.assertFalse(history.exists())
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0]["appended"])
            self.assertEqual(results[0]["rows"], 1)
            self.assertIn("DRY RUN", buf.getvalue())
            self.assertIn("WOULD", buf.getvalue())

    def test_picks_latest_timestamp_per_date(self) -> None:
        # Same day, two scrapes — the later one's ranks must win,
        # matching what ``append_snapshot``'s per-date dedup would
        # produce if we blindly processed both.
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            _write_zip(
                archive / "dynasty_export_20260308_020000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 9, "Bob": 9}),
            )
            _write_zip(
                archive / "dynasty_export_20260308_220000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 1, "Bob": 2}),
            )

            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["date"], "2026-03-08")
            self.assertEqual(
                entry["ranks"],
                {"Alice::offense": 1, "Bob::offense": 2},
            )

    def test_since_filter_skips_earlier_snapshots(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            for date in ("2026-03-08", "2026-03-09", "2026-03-10"):
                ymd = date.replace("-", "")
                _write_zip(
                    archive / f"dynasty_export_{ymd}_090000.zip",
                    date=date,
                    payload=_contract({"Alice": 1}),
                )

            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                since="2026-03-09",
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                [json.loads(line)["date"] for line in lines],
                ["2026-03-09", "2026-03-10"],
            )

    def test_max_snapshots_cap(self) -> None:
        # With a cap of 2 and three archives, only the two most
        # recent dates survive the trim — same retention policy the
        # production path enforces.
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            for date in ("2026-03-08", "2026-03-09", "2026-03-10"):
                ymd = date.replace("-", "")
                _write_zip(
                    archive / f"dynasty_export_{ymd}_090000.zip",
                    date=date,
                    payload=_contract({"Alice": 1}),
                )

            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                max_snapshots=2,
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 2)
            self.assertEqual(
                [json.loads(line)["date"] for line in lines],
                ["2026-03-09", "2026-03-10"],
            )


class TestCorruptLatestFallback(unittest.TestCase):
    """Regression coverage for Codex PR #223 round 1.

    The original selector kept only the highest-HHMMSS archive per
    date before any validation — so if that latest upload was
    corrupt or crashed build_contract, the entire day was dropped
    even when earlier same-day archives were fine.  The selector
    now returns all candidates per date and the loop walks them
    newest-first until one succeeds.
    """

    def test_corrupt_latest_falls_back_to_earlier_same_day(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            archive.mkdir()
            history = tmpdir / "rank_history.jsonl"

            # Earlier valid bundle.
            _write_zip(
                archive / "dynasty_export_20260308_020000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 1, "Bob": 2}),
            )
            # Latest is corrupt — pre-fix this would drop the day.
            (archive / "dynasty_export_20260308_220000.zip").write_bytes(b"not a zip")

            results = _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            # The valid-earlier bundle wrote a snapshot.
            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            entry = json.loads(lines[0])
            self.assertEqual(entry["date"], "2026-03-08")
            self.assertEqual(
                entry["ranks"],
                {"Alice::offense": 1, "Bob::offense": 2},
            )
            # The corrupt candidate should not be surfaced as a
            # failure — we found a good one for that day.  Any
            # results reported must be for successful appends only.
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]["appended"])

    def test_build_error_on_latest_falls_back_to_earlier(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            _write_zip(
                archive / "dynasty_export_20260308_020000.zip",
                date="2026-03-08",
                payload={"flavour": "good", "playersArray": [
                    {"canonicalName": "Alice", "canonicalConsensusRank": 1, "assetClass": "offense"},
                ]},
            )
            _write_zip(
                archive / "dynasty_export_20260308_220000.zip",
                date="2026-03-08",
                payload={"flavour": "bad"},
            )

            # Builder that rejects the "bad" payload but accepts
            # the "good" one — simulates a targeted build failure
            # on the latest upload only.
            def _picky_build(raw):
                if raw.get("flavour") == "bad":
                    raise RuntimeError("simulated build error")
                return raw

            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_picky_build,
                out=io.StringIO(),
            )

            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(
                json.loads(lines[0])["ranks"],
                {"Alice::offense": 1},
            )


class TestSinceAgainstManifestDate(unittest.TestCase):
    """Regression coverage for Codex PR #223 round 1.

    Pre-fix, ``--since`` was evaluated against the filename date
    before the manifest was read — so an archive whose filename
    said 2026-03-08 but whose manifest said 2026-03-09 was
    incorrectly skipped by ``--since 2026-03-09``, even though the
    manifest date is what ``append_snapshot`` actually writes.
    """

    def test_since_uses_manifest_date_not_filename_date(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            history = tmpdir / "rank_history.jsonl"

            # Filename says 2026-03-08 but manifest authoritatively
            # says 2026-03-09 — simulates a UTC-midnight-crossing
            # scrape or a clock skew.
            _write_zip(
                archive / "dynasty_export_20260308_235959.zip",
                date="2026-03-09",
                payload=_contract({"Alice": 1}),
            )

            _mod.backfill(
                archive_dir=archive,
                history_path=history,
                since="2026-03-09",
                build_contract=_passthrough,
                out=io.StringIO(),
            )

            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["date"], "2026-03-09")


class TestArchiveZipLoader(unittest.TestCase):
    def test_unreadable_zip_is_reported_not_fatal(self) -> None:
        with TemporaryDirectory() as tmp:
            tmpdir = Path(tmp)
            archive = tmpdir / "archive"
            archive.mkdir()
            history = tmpdir / "rank_history.jsonl"

            # One good, one corrupt.
            _write_zip(
                archive / "dynasty_export_20260308_090000.zip",
                date="2026-03-08",
                payload=_contract({"Alice": 1}),
            )
            (archive / "dynasty_export_20260309_090000.zip").write_bytes(b"not a zip")

            buf = io.StringIO()
            results = _mod.backfill(
                archive_dir=archive,
                history_path=history,
                build_contract=_passthrough,
                out=buf,
            )

            self.assertEqual(len(results), 2)
            statuses = [r.get("skipped") for r in results]
            self.assertIn("unreadable", statuses)
            # The good snapshot still landed.
            lines = history.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(lines), 1)
            self.assertEqual(json.loads(lines[0])["date"], "2026-03-08")


if __name__ == "__main__":
    unittest.main()
