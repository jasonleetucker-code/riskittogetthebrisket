"""Dry-run policy report (STAB-7): classification is path-first, protects the
refresh/deploy dispatch state, and never mutates anything."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))

import report_data_policy_migration as rpt  # noqa: E402


def test_scrape_state_and_sleeper_fallback_are_never_moved():
    # Even a path that names a paid vendor stays tracked: deploy dispatch and the
    # source_health freeze key on these commits (CLAUDE.md W31-F001).
    assert rpt.classify("data/scrape_state/dlfSf_last_success", scan=False) == "PROTECTED_STAY"
    assert rpt.classify("data/scrape_state/dlfIdp_dataset.json", scan=False) == "PROTECTED_STAY"
    assert rpt.classify("data/sleeper_last_good.json", scan=False) == "PROTECTED_STAY"


def test_path_classes():
    assert rpt.classify("data/raw/dlf_sf/x.csv", scan=False) == "MOVE_PAID_VENDOR"
    assert rpt.classify("CSVs/site_raw/draftSharksSf.csv", scan=False) == "MOVE_PAID_VENDOR"
    assert rpt.classify("data/raw/fantasypros_sf/x.csv", scan=False) == "MOVE_TERMS_FORBID"
    assert rpt.classify("data/raw/ktc/x.csv", scan=False) == "UNVERIFIED_FREE"
    assert rpt.classify("src/api/data_contract.py", scan=False) == "OTHER_STAY"


def test_owner_id_classes_split_by_where_the_file_lives():
    f = rpt.classify
    assert f("exports/archive/a.zip", scan=False, owner_ids=True) == "MOVE_OWNER_IDS"
    assert f("tests/fixtures/a.zip", scan=False, owner_ids=True) == "FIXTURE_OWNER_IDS"
    assert f("config/leagues/registry.json", scan=False, owner_ids=True) == "REVIEW_CONFIG"
    assert f("exports/archive/a.zip", scan=False, owner_ids=False) == "OTHER_STAY"


def test_report_counts_and_box_loss_without_scanning():
    files = [
        "data/raw/dlf_sf/a.csv",
        "data/raw/fantasypros/b.csv",
        "data/raw/ktc/c.csv",
        "data/scrape_state/dlfSf_last_success",
        "docs/x.md",
    ]
    rep = rpt.build_report(files, scan=False)
    assert rep["wouldMove"]["files"] == 2
    assert rep["boxLossOnResetHardUnlessPreserved"] == 2
    assert rep["protectedOverlap"] == []
    assert rep["classes"]["PROTECTED_STAY"]["files"] == 1
    wider = rpt.build_report(files, scan=False, include_unverified_free=True)
    assert wider["wouldMove"]["files"] == 3


def test_group_of_names_a_directory_not_a_file():
    assert rpt.group_of("data/scrape_state/x.json") == "data/scrape_state/"
    assert rpt.group_of("data/raw/dlf_sf/a.csv") == "data/raw/dlf_sf/"
    assert rpt.group_of("exports/archive/a.zip") == "exports/archive/"
    assert rpt.group_of("README.md") == "(repo root)"


def test_script_cannot_mutate_the_tree():
    src = (REPO / "scripts" / "report_data_policy_migration.py").read_text(encoding="utf-8")
    for needle in ("subprocess", "unlink(", "rmtree", "os.remove", "write_text(", ".write_bytes("):
        assert needle not in src.split('"""', 2)[2], needle
