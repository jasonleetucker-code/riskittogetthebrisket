"""Tracked-data exposure guard (Task 8, owner directive 2026-11-18).

The repository is PUBLIC.  While the owner decides what to do about the data it
already publishes (docs/security/DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md),
this test stops the exposure GROWING: a NEW tracked file that carries
owner/user-id-like fields, or that is a paid-vendor board, fails unless it is
covered by ``config/security/tracked_data_exposure_baseline.txt``.

It changes nothing about what the pipelines publish.  The baseline lists
existing offenders by path (no values) plus the directories the refresh
republishes continuously; shrinking it is always fine.
"""

from __future__ import annotations

import io
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import pytest  # noqa: E402

import audit_tracked_data_exposure as guard  # noqa: E402

OWNER_FIELD = '"owner_id": "123456789012345678"'


@pytest.mark.livedata
def test_no_new_tracked_file_grows_the_exposure():
    """Advisory (livedata lane): reads the LIVE tracked tree, which scheduled refreshes
    change without a PR.  The blocking check is the diff-scoped PR step."""
    exact, prefixes = guard.load_baseline()
    assert prefixes, "baseline file missing or empty"
    offenders = []
    for rel in guard.tracked_files():
        if not guard.in_scope(rel) or guard.baselined(rel, exact, prefixes):
            continue
        reasons = guard.guard_findings(rel)
        if reasons:
            offenders.append(f"  {rel}: {'; '.join(reasons)}")
    assert not offenders, (
        "new tracked files publish owner-id-like fields or paid-vendor data in a "
        "PUBLIC repository.  Keep them box-local / untracked, or get the owner decision "
        "in docs/security/DATA_EXPOSURE_DECISION_BRIEF_2026-11-18.md before adding them to "
        "config/security/tracked_data_exposure_baseline.txt:\n" + "\n".join(offenders[:20])
    )


def test_baseline_is_paths_only_and_wellformed():
    for line in (guard.BASELINE_PATH).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        assert line.startswith(("path: ", "prefix: ")), line
        assert not guard.LONG_NUMERIC_RE.search(line), "baseline must not carry id-like numbers"


def test_paid_vendor_path_detection():
    assert guard.is_paid_vendor_data_path("CSVs/site_raw/dlfSf.csv") == "Dynasty League Football"
    assert guard.is_paid_vendor_data_path("data/raw/draftsharks/x.json") == "Draft Sharks"
    assert guard.is_paid_vendor_data_path("CSVs/site_raw/idpShow.csv") == "The IDP Show"
    assert guard.is_paid_vendor_data_path("data/raw/footballguys_sf/x.csv") == "Footballguys"
    assert guard.is_paid_vendor_data_path("CSVs/site_raw/ktc.csv") is None
    assert guard.is_paid_vendor_data_path("CSVs/site_raw/fantasyCalc.csv") is None
    assert guard.is_paid_vendor_data_path("docs/dlf_notes.csv") is None  # outside data prefixes
    assert guard.is_paid_vendor_data_path("CSVs/site_raw/dlfSf.txt") is None


def test_owner_id_detection_counts_without_values(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "REPO", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "teams.json").write_text("{" + OWNER_FIELD + "}", encoding="utf-8")
    (tmp_path / "data" / "clean.json").write_text('{"player": "x", "value": 12}', encoding="utf-8")
    (tmp_path / "data" / "short.json").write_text('{"owner_id": "42"}', encoding="utf-8")
    reasons = guard.guard_findings("data/teams.json")
    assert reasons and "count=1" in reasons[0]
    assert "123456789012345678" not in " ".join(reasons)
    assert guard.guard_findings("data/clean.json") == []
    assert guard.guard_findings("data/short.json") == []  # not id-like


def test_zip_members_scanned(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "REPO", tmp_path)
    (tmp_path / "exports").mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("dynasty_data.json", "{" + OWNER_FIELD + "}")
        zf.writestr("site_raw/dlfSf.csv", "name,rank\nA,1\n")
    (tmp_path / "exports" / "new.zip").write_bytes(buf.getvalue())
    reasons = guard.guard_findings("exports/new.zip")
    assert any("owner/user-id" in r for r in reasons)
    assert any("paid-vendor members" in r for r in reasons)


def test_baseline_coverage_rules(tmp_path):
    base = tmp_path / "b.txt"
    base.write_text("prefix: data/raw/\npath: CSVs/a.csv\n# c\n", encoding="utf-8")
    exact, prefixes = guard.load_baseline(base)
    assert guard.baselined("data/raw/dlf_sf/new.csv", exact, prefixes)
    assert guard.baselined("CSVs/a.csv", exact, prefixes)
    assert not guard.baselined("CSVs/b.csv", exact, prefixes)
    assert not guard.baselined("data/other/x.csv", exact, prefixes)


def _git(cwd, *args):
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "PATH": __import__("os").environ["PATH"],
            "HOME": str(cwd),
        },
    )


def test_changed_since_diff_mode(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    (repo / "data" / "raw" / "dlf_sf").mkdir(parents=True)
    (repo / "CSVs" / "site_raw").mkdir(parents=True)
    (repo / "CSVs" / "site_raw" / "dlfSf.csv").write_text("a\n", encoding="utf-8")
    (repo / "data" / "raw" / "dlf_sf" / "old.csv").write_text("a\n", encoding="utf-8")
    (repo / "README").write_text("x", encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text("prefix: data/raw/\npath: CSVs/site_raw/dlfSf.csv\n", encoding="utf-8")
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    monkeypatch.setattr(guard, "REPO", repo)

    # modify a baselined file + refresh-style new file under a baselined prefix: passes
    (repo / "CSVs" / "site_raw" / "dlfSf.csv").write_text("b\n", encoding="utf-8")
    (repo / "data" / "raw" / "dlf_sf" / "new.csv").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "refresh-style")
    assert guard.check_changed_since("main", base) == []

    # add an offender outside the baseline: fails, and no value is echoed
    (repo / "data" / "teams.json").write_text("{" + OWNER_FIELD + "}", encoding="utf-8")
    (repo / "CSVs" / "site_raw" / "draftSharksSf.csv").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "offenders")
    found = guard.check_changed_since("main", base)
    assert len(found) == 2
    assert any(f.startswith("data/teams.json") for f in found)
    assert any("Draft Sharks" in f for f in found)
    assert "123456789012345678" not in " ".join(found)


# ── review fixes: renames/copies, fail-closed on unscannable files ──────────
def test_diff_mode_catches_a_renamed_offender(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "old_teams.json").write_text("{" + OWNER_FIELD + "}", encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text("path: data/old_teams.json\n", encoding="utf-8")
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    monkeypatch.setattr(guard, "REPO", repo)
    _git(repo, "mv", "data/old_teams.json", "data/new_teams.json")
    _git(repo, "commit", "-q", "-am", "rename")
    assert guard.changed_files("main") == ["data/new_teams.json"]
    found = guard.check_changed_since("main", base)
    assert len(found) == 1 and found[0].startswith("data/new_teams.json")


def test_diff_mode_copy_is_caught_too(tmp_path, monkeypatch):
    repo = tmp_path / "r"
    (repo / "data").mkdir(parents=True)
    (repo / "data" / "old_teams.json").write_text("{" + OWNER_FIELD + "}", encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text("path: data/old_teams.json\n", encoding="utf-8")
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    monkeypatch.setattr(guard, "REPO", repo)
    (repo / "data" / "copy.json").write_text("{" + OWNER_FIELD + "}", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "copy")
    assert len(guard.check_changed_since("main", base)) == 1


def test_unscannable_files_are_findings_in_diff_mode_only(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "REPO", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "bad.zip").write_bytes(b"this is not a zip")
    (tmp_path / "data" / "big.json").write_text('{"a": 1}' * 50, encoding="utf-8")
    (tmp_path / "data" / "ok.json").write_text('{"a": 1}', encoding="utf-8")
    monkeypatch.setattr(guard, "MAX_SCAN_BYTES", 100)

    corrupt = guard.guard_findings("data/bad.zip", fail_closed=True)
    assert any("could not be scanned" in r and "BadZipFile" in r for r in corrupt)
    big = guard.guard_findings("data/big.json", fail_closed=True)
    assert any("could not be scanned" in r and "scan cap" in r for r in big)
    assert guard.guard_findings("data/ok.json", fail_closed=True) == []
    # report / baseline mode keeps the old behaviour (counts only, no finding)
    assert guard.guard_findings("data/bad.zip") == []
    assert guard.guard_findings("data/big.json") == []


def test_oserror_on_read_is_a_finding_without_leaking_content(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "REPO", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "x.json").write_text("{" + OWNER_FIELD + "}", encoding="utf-8")

    def boom(self):
        raise PermissionError("secret path detail 123456789012345678")

    monkeypatch.setattr(Path, "read_bytes", boom)
    reasons = guard.guard_findings("data/x.json", fail_closed=True)
    assert any("unreadable (PermissionError)" in r for r in reasons)
    assert "123456789012345678" not in " ".join(reasons)


def test_oversized_zip_member_is_a_finding(tmp_path, monkeypatch):
    monkeypatch.setattr(guard, "REPO", tmp_path)
    (tmp_path / "exports").mkdir()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.json", "x" * 5000)
    (tmp_path / "exports" / "z.zip").write_bytes(buf.getvalue())
    # cap below the member (5000) but above the compressed archive
    monkeypatch.setattr(guard, "MAX_SCAN_BYTES", 1000)
    reasons = guard.guard_findings("exports/z.zip", fail_closed=True)
    assert any("zip member larger" in r for r in reasons)


def test_new_paid_vendor_directory_under_a_baselined_prefix_is_a_finding(tmp_path, monkeypatch):
    """Closes the documented gap: the rotating prefixes acknowledge dated files in
    EXISTING vendor directories, but a paid-vendor feed in a directory that did not
    exist at the merge base is a new publication, not a refresh."""
    repo = tmp_path / "r"
    (repo / "data" / "raw" / "dlf_sf").mkdir(parents=True)
    (repo / "data" / "raw" / "dlf_sf" / "old.csv").write_text("a\n", encoding="utf-8")
    (repo / "README").write_text("x", encoding="utf-8")
    base = tmp_path / "baseline.txt"
    base.write_text("prefix: data/raw/\n", encoding="utf-8")
    _git(repo.parent, "init", "-q", "-b", "main", str(repo))
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    monkeypatch.setattr(guard, "REPO", repo)

    # refresh-style: new dated file in an existing vendor directory -> still fine
    (repo / "data" / "raw" / "dlf_sf" / "new.csv").write_text("b\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "refresh")
    assert guard.check_changed_since("main", base) == []

    # a NEW paid vendor directory under the same prefix -> finding; a free one is not
    (repo / "data" / "raw" / "footballguys_sf").mkdir()
    (repo / "data" / "raw" / "footballguys_sf" / "a.csv").write_text("a\n", encoding="utf-8")
    (repo / "data" / "raw" / "ktc_new").mkdir()
    (repo / "data" / "raw" / "ktc_new" / "a.csv").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "new vendor")
    found = guard.check_changed_since("main", base)
    assert len(found) == 1
    assert found[0].startswith("data/raw/footballguys_sf/a.csv")
    assert "NEW directory" in found[0] and "Footballguys" in found[0]
