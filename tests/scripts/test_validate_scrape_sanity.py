"""Unit tests for the pre-commit scrape sanity gate (roadmap 1.4).

Exercises the pure ``evaluate()`` decision function — no git / IO.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "validate_scrape_sanity",
    Path(__file__).resolve().parents[2] / "scripts" / "validate_scrape_sanity.py",
)
vss = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(vss)


def _csv(rows: list[str], header: str = "name,value") -> str:
    return "\n".join([header, *rows]) + "\n"


class EvaluateTests(unittest.TestCase):
    def test_healthy_value_csv_ok(self) -> None:
        cur = _csv([f"Player {i},{100 + i}" for i in range(200)])
        prev = _csv([f"Player {i},{100 + i}" for i in range(205)])
        level, _ = vss.evaluate("ktc", cur, prev)
        self.assertEqual(level, "ok")

    def test_rank_only_csv_ok(self) -> None:
        # name,Rank,position,team — value column is NOT last; the
        # any-numeric-signal check must still see the rank.
        rows = [f"Player {i},{i + 1},QB,BUF" for i in range(120)]
        cur = _csv(rows, header="name,Rank,position,team")
        level, msg = vss.evaluate("fantasyProsSf", cur, None)
        self.assertEqual(level, "ok", msg)

    def test_below_min_lines_errors(self) -> None:
        cur = _csv([f"P{i},{i+1}" for i in range(20)])  # 20 rows, ktc needs 100
        level, msg = vss.evaluate("ktc", cur, None)
        self.assertEqual(level, "error")
        self.assertIn("required", msg)

    def test_all_zero_no_signal_errors(self) -> None:
        rows = [f"Player {i},0" for i in range(150)]
        cur = _csv(rows)
        level, msg = vss.evaluate("ktc", cur, None)
        self.assertEqual(level, "error")
        self.assertIn("no numeric signal", msg)

    def test_empty_values_no_signal_errors(self) -> None:
        rows = [f"Player {i},,," for i in range(60)]
        cur = _csv(rows, header="name,a,b,c")
        level, _ = vss.evaluate("dynastyNerdsSfTep", cur, None)
        self.assertEqual(level, "error")

    def test_row_collapse_over_50pct_errors(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(400)])
        cur = _csv([f"P{i},{i+1}" for i in range(150)])  # 37.5% of prior
        level, msg = vss.evaluate("otcffbSf", cur, prev)
        self.assertEqual(level, "error")
        self.assertIn("collapsed", msg)

    def test_row_drop_30_to_50pct_warns(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(400)])
        cur = _csv([f"P{i},{i+1}" for i in range(240)])  # 60% of prior
        level, msg = vss.evaluate("otcffbSf", cur, prev)
        self.assertEqual(level, "warn")
        self.assertIn("dropped", msg)

    def test_minor_drift_ok(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(400)])
        cur = _csv([f"P{i},{i+1}" for i in range(395)])
        level, _ = vss.evaluate("otcffbSf", cur, prev)
        self.assertEqual(level, "ok")

    def test_exempt_source_skips_collapse(self) -> None:
        prev = _csv([f"P{i},{i+1}" for i in range(900)])
        cur = _csv([f"P{i},{i+1}" for i in range(5)])  # huge collapse
        level, _ = vss.evaluate("draftSharksRosSf", cur, prev)
        self.assertEqual(level, "ok")  # ROS is allowlisted

    def test_unreadable_current_errors(self) -> None:
        level, msg = vss.evaluate("ktc", None, None)
        self.assertEqual(level, "error")
        self.assertIn("unreadable", msg)

    def test_new_file_no_prev_only_min_check(self) -> None:
        cur = _csv([f"P{i},{i+1}" for i in range(120)])
        level, _ = vss.evaluate("ktc", cur, None)
        self.assertEqual(level, "ok")


_PICKS_HEADER = "asset,year,round,slot,overall,value"
_PICK_ROWS = [f"2026 1.{i:02d} ({i}),2026,1,{i},{i},{700 - 10 * i}.0000" for i in range(1, 61)]


class AuditSidecarTests(unittest.TestCase):
    """``dlfValuesSfTepPicks`` is an audit-only sidecar, not a source.

    Incident (#1552): DLF dropped its 2026 slot picks on 2026-09-30, the
    prod timer pushed a header-only sidecar to main, and the floor turned
    every scheduled refresh red — blocking 29 healthy sources' commit and
    the Hill dispatch while the file it "guarded" was already on main.
    """

    def test_header_only_sidecar_warns_every_run_even_when_unchanged(self) -> None:
        # In scheduled-refresh the box-pushed file equals HEAD, so cur == prev;
        # empty must still surface as a (non-blocking) warning, never "OK".
        cur = _csv([], header=_PICKS_HEADER)
        level, msg = vss.evaluate("dlfValuesSfTepPicks", cur, cur)
        self.assertEqual(level, "warn", msg)
        self.assertIn("0 data rows", msg)
        self.assertNotIn("OK", msg)

    def test_header_only_sidecar_with_no_prior_warns(self) -> None:
        level, _ = vss.evaluate("dlfValuesSfTepPicks", _csv([], header=_PICKS_HEADER), None)
        self.assertEqual(level, "warn")

    def test_sidecar_partial_drop_warns(self) -> None:
        prev = _csv(_PICK_ROWS, header=_PICKS_HEADER)
        cur = _csv(_PICK_ROWS[:20], header=_PICKS_HEADER)
        level, msg = vss.evaluate("dlfValuesSfTepPicks", cur, prev)
        self.assertEqual(level, "warn")
        self.assertIn("60 -> 20", msg)

    def test_empty_sidecar_is_non_blocking_in_main(self) -> None:
        """main() exits 0 and emits a ``::warning`` for an empty sidecar."""
        import contextlib
        import io
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            site_raw = repo / "CSVs" / "site_raw"
            site_raw.mkdir(parents=True)
            (site_raw / "dlfValuesSfTepPicks.csv").write_text(
                _PICKS_HEADER + "\n", encoding="utf-8"
            )
            fake_script = repo / "scripts" / "validate_scrape_sanity.py"
            out = io.StringIO()
            with (
                mock.patch.object(vss, "__file__", str(fake_script)),
                mock.patch.object(vss, "_git_show", return_value=_PICKS_HEADER + "\n"),
                contextlib.redirect_stdout(out),
            ):
                code = vss.main()
        self.assertEqual(code, 0, out.getvalue())
        self.assertIn("::warning title=Scrape sanity::dlfValuesSfTepPicks", out.getvalue())

    def test_sidecar_drop_is_reported_not_blocking(self) -> None:
        prev = _csv(_PICK_ROWS, header=_PICKS_HEADER)
        cur = _csv([], header=_PICKS_HEADER)
        level, msg = vss.evaluate("dlfValuesSfTepPicks", cur, prev)
        self.assertEqual(level, "warn")
        self.assertIn("60 -> 0", msg)

    def test_sidecar_with_rows_but_no_signal_still_errors(self) -> None:
        cur = _csv([f"2026 1.{i:02d},,,,," for i in range(1, 30)], header=_PICKS_HEADER)
        level, msg = vss.evaluate("dlfValuesSfTepPicks", cur, None)
        self.assertEqual(level, "error")
        self.assertIn("no numeric signal", msg)

    def test_healthy_sidecar_ok(self) -> None:
        cur = _csv(_PICK_ROWS, header=_PICKS_HEADER)
        level, msg = vss.evaluate("dlfValuesSfTepPicks", cur, cur)
        self.assertEqual(level, "ok", msg)

    def test_parent_values_board_keeps_every_check(self) -> None:
        self.assertNotIn("dlfValuesSfTep", vss.AUDIT_SIDECARS)
        level, _ = vss.evaluate("dlfValuesSfTep", _csv([], header="name,pos,team,value"), None)
        self.assertEqual(level, "error")
        prev = _csv([f"P{i},WR,BUF,{900 - i}" for i in range(320)], header="name,pos,team,value")
        cur = _csv([f"P{i},WR,BUF,{900 - i}" for i in range(100)], header="name,pos,team,value")
        level, _ = vss.evaluate("dlfValuesSfTep", cur, prev)
        self.assertEqual(level, "error")

    def test_sidecars_are_never_registered_sources(self) -> None:
        """The exemption is only sound while the sidecar is not a source.

        What this ENFORCES: the sidecar is neither a key nor a path in
        ``data_contract._SOURCE_CSV_PATHS``, nor a key (or any string field)
        of ``_RANKING_SOURCES`` — the registries every voting source must be
        in — and no literal mention of it exists in ``src/``, ``server.py``
        or the scraper.  It does NOT inspect ``scripts/`` (audit tooling,
        which may legitimately read it) or prove the absence of a
        dynamically-built filename; the directory-enumeration guard below
        covers the loader-by-glob route.
        """
        from src.api import data_contract as dc

        repo = Path(__file__).resolve().parents[2]
        for key in vss.AUDIT_SIDECARS:
            self.assertNotIn(key, dc._SOURCE_CSV_PATHS)
            for src_key, spec in dc._SOURCE_CSV_PATHS.items():
                path = spec if isinstance(spec, str) else str((spec or {}).get("path", ""))
                self.assertNotIn(key, path, f"_SOURCE_CSV_PATHS[{src_key!r}] reads {key}")
            for entry in dc._RANKING_SOURCES:
                self.assertNotEqual(entry.get("key"), key)
                strings = [v for v in entry.values() if isinstance(v, str)]
                self.assertFalse(
                    any(key in v for v in strings), f"_RANKING_SOURCES entry {entry.get('key')!r}"
                )

            consumers = [repo / "server.py", repo / "Dynasty Scraper.py"]
            consumers += sorted((repo / "src").rglob("*.py"))
            hits = [
                str(p.relative_to(repo))
                for p in consumers
                if key in p.read_text(encoding="utf-8", errors="replace")
            ]
            self.assertEqual(hits, [], f"{key} is read by {hits}; it is a source now")

    # ``src/`` modules allowed to ENUMERATE a directory while mentioning
    # ``site_raw``.  Each entry must not turn a file it finds into model input.
    _SITE_RAW_ENUMERATORS_ALLOWED = {
        # Provenance pins: sha256 of every CSV's bytes; never parses a value.
        "src/api/value_replay.py",
        # Source census: indexes site_raw CSV NAMES inside export-archive zips
        # (presence dates only); never parses a value.
        "src/sources/source_census.py",
    }

    def test_no_src_module_loads_site_raw_by_enumeration(self) -> None:
        """A glob/listdir loader over ``CSVs/site_raw`` would pick the sidecar
        up as a source without ever naming it.  Any ``src/`` module that both
        mentions ``site_raw`` and enumerates a directory must be reviewed onto
        the allowlist above (file-level check: conservative, may over-flag)."""
        import re

        repo = Path(__file__).resolve().parents[2]
        enumerate_re = re.compile(
            r"\.r?glob\(|\bglob\.i?glob\(|\biterdir\(|\blistdir\(|\bscandir\(|\bos\.walk\("
        )
        flagged = set()
        for p in sorted((repo / "src").rglob("*.py")):
            text = p.read_text(encoding="utf-8", errors="replace")
            if "site_raw" in text and enumerate_re.search(text):
                flagged.add(p.relative_to(repo).as_posix())
        self.assertEqual(flagged - self._SITE_RAW_ENUMERATORS_ALLOWED, set())

    def test_sidecars_are_declared_non_voting(self) -> None:
        import sys

        repo = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(repo / "scripts"))
        try:
            import source_inventory
        finally:
            sys.path.remove(str(repo / "scripts"))
        self.assertLessEqual(vss.AUDIT_SIDECARS, set(source_inventory.KNOWN_NON_VOTING_REASONS))

    def test_sidecar_is_the_dlf_fetchers_audit_output(self) -> None:
        repo = Path(__file__).resolve().parents[2]
        fetcher = (repo / "scripts" / "fetch_dlf.py").read_text(encoding="utf-8")
        self.assertIn('"picks_out": "CSVs/site_raw/dlfValuesSfTepPicks.csv"', fetcher)


if __name__ == "__main__":
    unittest.main()
