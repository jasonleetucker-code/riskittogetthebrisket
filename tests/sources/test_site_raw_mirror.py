"""V1-89: DraftSharks must be OBSERVABLE by the existing content-age scan.

THE DEFECT.  ``scripts/check_source_health.measure_content_staleness``
reads one evidence lane — the tracked ``exports/archive/*.zip`` bundles —
and those bundles carried exactly three ``site_raw`` CSVs (``ktc``,
``ktcSfTep``, ``idpTradeCalc``), because the export path is assembled
from ``Dynasty Scraper.py``'s own ``FULL_DATA``.  Every source acquired
by a standalone fetcher writes straight into ``CSVs/site_raw/`` and so
never entered an archive at all.

Measured 2026-08-25: substituting 8-day-old DraftSharks CSVs into the
tree while leaving the fetch stamps current produced a health verdict
byte-identical to the healthy run.  The detector was never wrong — it
was never given the bytes.

WHAT THESE TESTS PIN.  Not "a mirror function exists".  The property:
frozen DraftSharks content with a fresh fetch timestamp must reach
``content-stale`` through the EXISTING detector and the EXISTING
vocabulary, and must return to current when the vendor publishes again —
with ``idpTradeCalc``'s behaviour unchanged either way.
"""

from __future__ import annotations

import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.check_source_health import measure_content_staleness
from src.sources.site_raw_mirror import MIRRORED_SITE_RAW_CSVS, mirror_site_raw_csvs

REPO_ROOT = Path(__file__).resolve().parents[2]

_DRAFTSHARKS_FILES = (
    "draftSharksSf.csv",
    "draftSharksIdp.csv",
    "draftSharksRosSf.csv",
    "draftSharksRosIdp.csv",
)

# 12 archive stamps a day apart. Long enough to cross the 14-day default
# budget when combined with a frozen payload, short enough to stay fast.
_STAMPS = [f"202608{day:02d}_120000" for day in range(1, 25)]


def _archive(root: Path, stamp: str, members: dict[str, bytes]) -> None:
    out = root / "exports" / "archive"
    out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out / f"dynasty_export_{stamp}.zip", "w") as zf:
        for name, blob in members.items():
            zf.writestr(f"site_raw/{name}", blob)


def _board(marker: str) -> bytes:
    return f"Rank,Team,Player\n1,,Player {marker}\n".encode()


class TestTheMirrorListTracksRealConsumers(unittest.TestCase):
    """A file may only be mirrored because live code reads it.

    Without this the tuple degrades into a wishlist: a name could be
    archived for months after its consumer was deleted, and the archive
    would keep reporting a source nothing votes on.
    """

    def test_every_mirrored_name_is_read_by_live_code(self) -> None:
        contract = (REPO_ROOT / "src" / "api" / "data_contract.py").read_text(encoding="utf-8")
        ros_adapter = (REPO_ROOT / "src" / "ros" / "sources" / "draftsharks_ros.py").read_text(
            encoding="utf-8"
        )
        haystack = contract + ros_adapter
        for name in MIRRORED_SITE_RAW_CSVS:
            with self.subTest(name=name):
                self.assertIn(
                    name,
                    haystack,
                    f"{name} is mirrored into the archive but no consumer reads it",
                )

    def test_the_four_draftsharks_files_are_covered(self) -> None:
        for name in _DRAFTSHARKS_FILES:
            self.assertIn(name, MIRRORED_SITE_RAW_CSVS)

    def test_the_export_path_actually_calls_the_owner(self) -> None:
        """A correct helper nothing invokes changes no archive."""
        scraper = (REPO_ROOT / "Dynasty Scraper.py").read_text(encoding="utf-8")
        self.assertIn("site_raw_mirror", scraper)
        self.assertIn("_mirror_site_raw_csvs(", scraper)
        self.assertIn("siteRawMirrored", scraper)


class TestMirrorSemantics(unittest.TestCase):
    def _tree(self, tmp: Path, files: dict[str, bytes]) -> Path:
        src = tmp / "CSVs" / "site_raw"
        src.mkdir(parents=True)
        for name, blob in files.items():
            (src / name).write_bytes(blob)
        return tmp / "exports" / "latest" / "site_raw"

    def test_files_are_copied_byte_for_byte(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            payload = "Rank,Team,Player,Fantasy Position\n1,,Só Meoné Jr.,QB\n".encode()
            dest = self._tree(tmp, {"draftSharksSf.csv": payload})
            outcomes = mirror_site_raw_csvs(repo_root=tmp, site_raw_dir=dest)
            self.assertEqual(outcomes["draftSharksSf.csv"], "mirrored")
            self.assertEqual((dest / "draftSharksSf.csv").read_bytes(), payload)

    def test_a_missing_source_is_absent_not_an_empty_placeholder(self) -> None:
        """An empty placeholder would make a never-acquired source read
        as perfectly byte-stable — the exact failure being repaired."""
        with TemporaryDirectory() as td:
            tmp = Path(td)
            dest = self._tree(tmp, {})
            outcomes = mirror_site_raw_csvs(repo_root=tmp, site_raw_dir=dest)
            self.assertEqual(set(outcomes.values()), {"missing_source"})
            self.assertEqual(list(dest.glob("*.csv")), [])

    def test_a_name_the_scraper_produced_is_never_overwritten(self) -> None:
        with TemporaryDirectory() as td:
            tmp = Path(td)
            dest = self._tree(tmp, {"draftSharksSf.csv": b"vendor\n"})
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "draftSharksSf.csv").write_bytes(b"scraper-owned\n")
            outcomes = mirror_site_raw_csvs(
                repo_root=tmp,
                site_raw_dir=dest,
                produced_this_run={"draftSharksSf.csv"},
            )
            self.assertEqual(outcomes["draftSharksSf.csv"], "skipped_scraper_owns")
            self.assertEqual((dest / "draftSharksSf.csv").read_bytes(), b"scraper-owned\n")


class TestFrozenContentReachesContentStale(unittest.TestCase):
    """The headline control, and it is deliberately non-vacuous.

    Every archive below is stamped later than the last, i.e. the fetch
    kept succeeding throughout — which is the state that used to read as
    healthy.  Only the BYTES decide.
    """

    def _lane(self, root: Path, *, freeze_draftsharks: bool) -> None:
        """Build the archive lane THROUGH the real mirror, not around it.

        Writing archive members directly would test the detector against
        a hand-made bundle and leave the repair itself unexercised — the
        DraftSharks rows would be there because the test put them there.
        Here each run stages the vendor CSVs where a fetcher writes them
        and lets ``mirror_site_raw_csvs`` decide what reaches the bundle,
        so emptying the mirror list turns these tests RED.
        """
        for i, stamp in enumerate(_STAMPS):
            run = root / "runs" / stamp
            vendor = run / "CSVs" / "site_raw"
            vendor.mkdir(parents=True)
            for name in _DRAFTSHARKS_FILES:
                (vendor / name).write_bytes(
                    _board(f"{name}-frozen" if freeze_draftsharks else f"{name}-{i}")
                )

            bundle = run / "exports" / "latest" / "site_raw"
            bundle.mkdir(parents=True)
            # What Dynasty Scraper.py's own FULL_DATA pass writes.
            (bundle / "idpTradeCalc.csv").write_bytes(_board("idptc-constant"))
            (bundle / "ktc.csv").write_bytes(_board(f"ktc-{i}"))
            mirror_site_raw_csvs(
                repo_root=run,
                site_raw_dir=bundle,
                produced_this_run={"idpTradeCalc.csv", "ktc.csv"},
            )

            _archive(
                root,
                stamp,
                {f.name: f.read_bytes() for f in sorted(bundle.glob("*.csv"))},
            )

    def test_frozen_draftsharks_becomes_content_stale(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            self._lane(root, freeze_draftsharks=True)
            result = measure_content_staleness(root)
            for name in _DRAFTSHARKS_FILES:
                key = name[: -len(".csv")]
                with self.subTest(source=key):
                    self.assertIn(
                        key,
                        result,
                        f"{key} is still invisible to the content-age scan",
                    )
                    days = result[key]["daysSinceChange"]
                    self.assertIsNotNone(days, "unknown must not read as fresh")
                    self.assertGreater(
                        days,
                        14,
                        f"{key} frozen across the whole lane but reported {days}d",
                    )

    def test_a_publishing_vendor_does_not_false_alert(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            self._lane(root, freeze_draftsharks=False)
            result = measure_content_staleness(root)
            for name in _DRAFTSHARKS_FILES:
                key = name[: -len(".csv")]
                with self.subTest(source=key):
                    self.assertEqual(result[key]["daysSinceChange"], 0)

    def test_content_age_resets_when_the_vendor_publishes_again(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td)
            self._lane(root, freeze_draftsharks=True)
            stale = measure_content_staleness(root)["draftSharksSf"]["daysSinceChange"]
            self.assertGreater(stale, 14)

            run = root / "runs" / "20260826_120000"
            vendor = run / "CSVs" / "site_raw"
            vendor.mkdir(parents=True)
            for name in _DRAFTSHARKS_FILES:
                (vendor / name).write_bytes(_board(f"{name}-fresh"))
            bundle = run / "exports" / "latest" / "site_raw"
            bundle.mkdir(parents=True)
            (bundle / "idpTradeCalc.csv").write_bytes(_board("idptc-constant"))
            (bundle / "ktc.csv").write_bytes(_board("ktc-new"))
            mirror_site_raw_csvs(
                repo_root=run,
                site_raw_dir=bundle,
                produced_this_run={"idpTradeCalc.csv", "ktc.csv"},
            )
            _archive(
                root,
                "20260826_120000",
                {f.name: f.read_bytes() for f in sorted(bundle.glob("*.csv"))},
            )
            after = measure_content_staleness(root)
            self.assertEqual(after["draftSharksSf"]["daysSinceChange"], 0)

    def test_idptradecalc_behaviour_is_unchanged_by_the_mirror(self) -> None:
        """The repair must not perturb the source the lane already
        watched: idpTradeCalc is frozen in both lanes and must report
        frozen in both, with the same number."""
        with TemporaryDirectory() as td_a, TemporaryDirectory() as td_b:
            a, b = Path(td_a), Path(td_b)
            self._lane(a, freeze_draftsharks=True)
            self._lane(b, freeze_draftsharks=False)
            days_a = measure_content_staleness(a)["idpTradeCalc"]["daysSinceChange"]
            days_b = measure_content_staleness(b)["idpTradeCalc"]["daysSinceChange"]
            self.assertEqual(days_a, days_b)
            self.assertGreater(days_a, 14)


if __name__ == "__main__":
    unittest.main()
