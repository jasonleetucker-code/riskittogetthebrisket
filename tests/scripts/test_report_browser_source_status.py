"""``scripts/report_browser_source_status.py`` is signal only.

2026-10-25: every browser-driven fetcher in the Scheduled Data Refresh produced
nothing for five runs, last-good CSVs were restored, and every run concluded
``success``.  The reporter turns "a browser source was kept, not rewritten" into
a job-summary block and one annotation.  It must never become a new failure mode,
and it must not misread the manifest, which says something different for the
scraper's own CSVs than for the standalone DraftSharks fetchers.

Hermetic: temp directories, ``os.utime`` for mtimes, no network, no repo state.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from scripts import report_browser_source_status as rbs

# Mtimes in seconds: marker < "after" so the comparison is never a filesystem tie.
BEFORE = 1_700_000_000
MARKER = 1_700_000_100
AFTER = 1_700_000_200

SCRAPER_OWNED = [s for s in rbs.BROWSER_SOURCES if s.scraper_owned]
STANDALONE = [s for s in rbs.BROWSER_SOURCES if not s.scraper_owned]


def _touch(path: Path, mtime: int, text: str = "name,value\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def _world(
    tmp_path: Path,
    *,
    mtimes: dict[str, int] | None = None,
    default: int = AFTER,
    manifest_preserved: list[str] | None = None,
    manifest_mtime: int = AFTER,
    missing: tuple[str, ...] = (),
) -> dict[str, Path]:
    """Lay out CSVs, a marker and (optionally) a manifest the way the refresh does."""
    csv_dir = tmp_path / "CSVs" / "site_raw"
    for source in rbs.BROWSER_SOURCES:
        if source.csv in missing:
            continue
        _touch(csv_dir / source.csv, (mtimes or {}).get(source.csv, default))
    marker = _touch(tmp_path / "scrape_start.marker", MARKER, "")
    manifest = tmp_path / "manifest.json"
    if manifest_preserved is not None:
        manifest.write_text(json.dumps({"siteRawPreserved": manifest_preserved}), encoding="utf-8")
        os.utime(manifest, (manifest_mtime, manifest_mtime))
    return {
        "csv_dir": csv_dir,
        "marker": marker,
        "manifest": manifest,
        "summary": tmp_path / "s.md",
    }


def _run(paths: dict[str, Path], capsys) -> tuple[int, str, str]:
    rc = rbs.main(
        [
            "--marker",
            str(paths["marker"]),
            "--csv-dir",
            str(paths["csv_dir"]),
            "--manifest",
            str(paths["manifest"]),
            "--summary",
            str(paths["summary"]),
        ]
    )
    out = capsys.readouterr().out
    summary = paths["summary"].read_text(encoding="utf-8") if paths["summary"].exists() else ""
    return rc, out, summary


def test_the_source_list_is_one_well_formed_table():
    csvs = [s.csv for s in rbs.BROWSER_SOURCES]
    assert len(csvs) == len(set(csvs)), "a CSV is listed twice"
    assert len({s.name for s in rbs.BROWSER_SOURCES}) == len(rbs.BROWSER_SOURCES)
    assert {s.csv for s in SCRAPER_OWNED} == {
        "ktc.csv",
        "ktcSfTep.csv",
        "ktcCrowdSfTep.csv",
        "ktcTradesSfTep.csv",
        "ktcCrowdTradesSfTep.csv",
        "idpTradeCalc.csv",
    }
    assert {s.csv for s in STANDALONE} == {
        "draftSharksSf.csv",
        "draftSharksIdp.csv",
        "draftSharksRosSf.csv",
        "draftSharksRosIdp.csv",
    }


def test_a_healthy_run_is_quiet(tmp_path, capsys):
    # The manifest of a HEALTHY run still lists the DraftSharks CSVs as preserved
    # (the scraper never produces them), so it must not flag them.
    paths = _world(
        tmp_path,
        manifest_preserved=[s.csv for s in STANDALONE],
    )
    rc, out, summary = _run(paths, capsys)
    assert rc == 0
    assert "::warning" not in out
    assert f"All {len(rbs.BROWSER_SOURCES)} browser-dependent source CSVs were rewritten" in summary
    assert "| " not in summary.split("rewritten", 1)[1], "no table when nothing was kept"


def test_a_scraper_restore_is_caught_even_though_its_mtime_is_current(tmp_path, capsys):
    # Audit Z-2: the restore pass rewrites last-good with open(dest, "wb"), so the
    # mtime is NEW.  Only the manifest tells the truth.
    paths = _world(tmp_path, manifest_preserved=["idpTradeCalc.csv", "ktc.csv"])
    rc, out, summary = _run(paths, capsys)
    assert rc == 0
    warnings = [ln for ln in out.splitlines() if ln.startswith("::warning")]
    assert len(warnings) == 1
    assert warnings[0].startswith("::warning title=Browser sources preserved::")
    assert f"2 of {len(rbs.BROWSER_SOURCES)}" in warnings[0]
    assert "ktc" in warnings[0] and "idpTradeCalc" in warnings[0]
    assert (
        "| idpTradeCalc | idpTradeCalc.csv | Dynasty Scraper.py | " + rbs.REASON_RESTORED in summary
    )
    assert rbs.REASON_RESTORED in summary


def test_no_chromium_means_every_browser_csv_is_reported(tmp_path, capsys):
    # The 2026-10-25 shape: nothing rewrote anything.  Scraper-owned CSVs sit at
    # checkout mtimes, the manifest is last run's (older than the marker), and the
    # standalone fetchers wrote nothing.
    paths = _world(tmp_path, default=BEFORE, manifest_preserved=[], manifest_mtime=BEFORE)
    rc, out, summary = _run(paths, capsys)
    assert rc == 0
    total = len(rbs.BROWSER_SOURCES)
    assert out.count("::warning title=Browser sources preserved::") == 1
    assert f"{total} of {total}" in out
    for source in rbs.BROWSER_SOURCES:
        assert source.name in out
        assert f"| {source.name} | {source.csv} |" in summary
    assert rbs.REASON_NOT_REWRITTEN in summary
    assert "Manifest evidence: `stale`" in summary


def test_a_stale_manifest_is_never_evidence(tmp_path):
    marker_ns = MARKER * 1_000_000_000
    paths = _world(tmp_path, manifest_preserved=["ktc.csv"], manifest_mtime=BEFORE)
    manifest = rbs.read_manifest(paths["manifest"], marker_ns)
    assert manifest.state == "stale"
    assert manifest.preserved == frozenset()


def test_the_manifest_is_not_evidence_for_standalone_fetchers(tmp_path, capsys):
    paths = _world(tmp_path, manifest_preserved=["draftSharksSf.csv", "draftSharksRosIdp.csv"])
    rc, out, _ = _run(paths, capsys)
    assert rc == 0
    assert "::warning" not in out


def test_a_standalone_fetcher_that_wrote_nothing_is_reported_by_mtime(tmp_path, capsys):
    paths = _world(
        tmp_path,
        mtimes={"draftSharksSf.csv": BEFORE, "draftSharksRosSf.csv": BEFORE},
        manifest_preserved=[],
    )
    rc, out, summary = _run(paths, capsys)
    assert rc == 0
    assert "2 of" in out
    assert "draftSharksSf" in out and "draftSharksRosSf" in out
    assert "draftSharksIdp" not in out and "draftSharksRosIdp" not in out
    assert "| draftSharksSf | draftSharksSf.csv | scripts/fetch_draftsharks.py |" in summary
    assert (
        "| draftSharksRosSf | draftSharksRosSf.csv | scripts/fetch_draftsharks_ros.py |" in summary
    )


def test_an_equal_mtime_is_not_newer(tmp_path, capsys):
    # bash ``-nt`` is strictly newer; the reporter must agree with stamp_if_present.
    paths = _world(tmp_path, mtimes={"ktc.csv": MARKER}, manifest_preserved=[])
    _, out, _ = _run(paths, capsys)
    assert "1 of" in out and "ktc" in out


def test_a_missing_csv_is_reported_as_missing_not_as_rewritten(tmp_path, capsys):
    paths = _world(tmp_path, manifest_preserved=[], missing=("draftSharksIdp.csv",))
    _, out, summary = _run(paths, capsys)
    assert "1 of" in out and "draftSharksIdp" in out
    assert "| draftSharksIdp | draftSharksIdp.csv |" in summary
    assert rbs.REASON_MISSING in summary


@pytest.mark.parametrize("body", ["{not json", "[]", '{"siteRawPreserved": 7}'])
def test_an_unusable_manifest_falls_back_to_mtime_and_says_so(tmp_path, capsys, body):
    paths = _world(tmp_path, manifest_preserved=[])
    paths["manifest"].write_text(body, encoding="utf-8")
    os.utime(paths["manifest"], (AFTER, AFTER))
    rc, out, summary = _run(paths, capsys)
    assert rc == 0
    assert "::warning title=Browser sources preserved::" not in out
    assert "Manifest evidence: `unreadable`" in summary


def test_an_absent_manifest_falls_back_to_mtime_and_says_so(tmp_path, capsys):
    paths = _world(tmp_path)
    _, out, summary = _run(paths, capsys)
    assert "::warning" not in out
    assert "Manifest evidence: `absent`" in summary


def test_a_missing_marker_makes_no_claim_and_still_exits_zero(tmp_path, capsys):
    paths = _world(tmp_path)
    paths["marker"].unlink()
    rc, out, summary = _run(paths, capsys)
    assert rc == 0
    assert out.startswith("::notice title=Browser sources not assessed::")
    assert "::warning" not in out
    assert summary == "", "no summary block is better than a false 'all rewritten'"


def test_the_reporter_cannot_fail_the_step(tmp_path, capsys, monkeypatch):
    paths = _world(tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(rbs, "find_kept", boom)
    rc, out, _ = _run(paths, capsys)
    assert rc == 0
    assert "::warning title=Browser source report failed::RuntimeError: disk on fire" in out


def test_summary_defaults_to_github_step_summary(tmp_path, capsys, monkeypatch):
    paths = _world(tmp_path, manifest_preserved=[])
    target = tmp_path / "gh_summary.md"
    target.write_text("# earlier step\n", encoding="utf-8")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(target))
    rc = rbs.main(
        [
            "--marker",
            str(paths["marker"]),
            "--csv-dir",
            str(paths["csv_dir"]),
            "--manifest",
            str(paths["manifest"]),
        ]
    )
    capsys.readouterr()
    assert rc == 0
    text = target.read_text(encoding="utf-8")
    assert text.startswith("# earlier step\n"), "must append, never truncate"
    assert "### Browser-driven sources" in text


def test_the_reporter_writes_no_csv_and_no_stamp(tmp_path, capsys):
    paths = _world(tmp_path, default=BEFORE, manifest_preserved=[], manifest_mtime=BEFORE)
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths["csv_dir"].iterdir()}
    _run(paths, capsys)
    after = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths["csv_dir"].iterdir()}
    assert before == after
    assert not (tmp_path / "data").exists()
