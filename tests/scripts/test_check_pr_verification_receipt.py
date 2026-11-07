"""CW-53: the PR verification receipt checker."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "check_pr_verification_receipt",
    Path(__file__).resolve().parents[2] / "scripts" / "check_pr_verification_receipt.py",
)
mod = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(mod)

LABELS = [
    "Intended behavior and prohibited behavior",
    "Controlling owner requirement / spec + clause",
    "Live path (route / flag / audience) and canonical owner",
    "Baseline before the change",
    "Independent oracle",
    "Positive / negative / edge / missing / stale cases covered",
    "Regression tests protecting existing behavior",
    "Test commands and outcomes",
    "Remaining unverified behavior and gaps",
    "Production impact and rollback",
    "Independent review and exact-tree validation",
    "State",
]
VALUES = {k: "Concrete evidence for this item." for k in LABELS}
VALUES["State"] = "TESTED_IN_PR (CI run 1)"


def body(overrides=None, drop=(), heading="## Feature verification receipt", fmt="- {l}: {v}"):
    ov = overrides or {}
    lines = [heading, ""]
    for lab in LABELS:
        if lab in drop:
            continue
        lines.append(fmt.format(l=ov.get("label:" + lab, lab), v=ov.get(lab, VALUES[lab])))
    return "Summary\n\n" + "\n".join(lines) + "\n\n## UI impact\n- [ ] none\n"


MAT = ["src/api/x.py"]


def go(b, files=MAT, author="alice"):
    return mod.run(b, files, author)


def test_complete_passes():
    assert go(body())[0] == 0


def test_missing_section_fails():
    code, rep = go("just a summary")
    assert code == 1 and "missing section" in rep


def test_missing_field_fails():
    code, rep = go(body(drop=("Baseline before the change",)))
    assert code == 1 and "Baseline" in rep and "field missing" in rep


def test_empty_field_fails():
    assert go(body({"Test commands and outcomes": ""}))[0] == 1


def test_template_placeholder_fails():
    ph = "Live path (route / flag / audience) and canonical owner"
    code, rep = go(body({ph: "route / flag / audience"}))
    assert code == 1 and "placeholder" in rep


def test_state_placeholder_fails():
    v = "TESTED_IN_PR / MERGED / DEPLOYED / VERIFIED_IN_PRODUCTION (each with evidence; never inferred)"
    assert go(body({"State": v}))[0] == 1


def test_state_must_name_state():
    assert go(body({"State": "looks good"}))[0] == 1


def test_na_without_reason_fails():
    assert go(body({"Baseline before the change": "n/a"}))[0] == 1
    assert go(body({"Baseline before the change": "n/a — "}))[0] == 1


def test_na_with_reason_passes():
    assert go(body({"Baseline before the change": "n/a — new feature, no prior behavior"}))[0] == 0


def test_label_case_and_whitespace_variants():
    b = body(fmt="*  **{l}** :  {v}")
    assert go(b)[0] == 0
    b2 = body(heading="### feature VERIFICATION receipt", fmt="- {l}:{v}")
    assert go(b2)[0] == 0
    b3 = body().replace("Baseline before the change", "BASELINE")
    assert go(b3)[0] == 0


def test_multiline_value():
    b = body().replace(
        "Test commands and outcomes: Concrete evidence for this item.",
        "Test commands and outcomes:\n  pytest tests/x -q\n  12 passed",
    )
    assert go(b)[0] == 0


@pytest.mark.parametrize(
    "files",
    [
        ["docs/a.md", "README.md"],
        ["data/x.json", "exports/latest/a.json", "CSVs/a.csv"],
        ["frontend/__tests__/a.js", "frontend/components/a.test.jsx"],
        ["scripts/research/x.py"],
    ],
)
def test_non_material_exempt(files):
    code, rep = go("", files)
    assert code == 0 and "required" in rep.lower() or "ADVISORY" in rep


def test_docs_only_not_material():
    code, rep = go("", ["docs/a.md"])
    assert code == 0 and "NOT MATERIAL" in rep


def test_tests_only_advisory():
    code, rep = go("", ["tests/api/test_x.py"])
    assert code == 0 and "ADVISORY" in rep


@pytest.mark.parametrize(
    "f",
    [
        "src/a.py",
        "server.py",
        "Dynasty Scraper.py",
        "frontend/app/page.jsx",
        "deploy/x.sh",
        "config/a.json",
        ".github/workflows/a.yml",
        "scripts/a.py",
    ],
)
def test_material_paths(f):
    assert mod.is_material_path(f)
    assert go("", [f])[0] == 1


@pytest.mark.parametrize("a", ["dependabot[bot]", "github-actions[bot]"])
def test_bot_exempt(a):
    code, rep = go("", MAT, a)
    assert code == 0 and "EXEMPT" in rep


def test_mixed_docs_and_code_is_material():
    assert go("", ["docs/a.md", "src/a.py"])[0] == 1


def test_cli_body_file_and_files(tmp_path, capsys):
    bf = tmp_path / "b.md"
    bf.write_text(body())
    ff = tmp_path / "f.txt"
    ff.write_text("src/a.py\n")
    assert mod.main(["--body-file", str(bf), "--files-from", str(ff), "--author", "x"]) == 0
    bf.write_text("nothing")
    assert mod.main(["--body-file", str(bf), "--files-from", str(ff)]) == 1


def test_cli_usage_error(monkeypatch):
    monkeypatch.delenv("GITHUB_EVENT_PATH", raising=False)
    assert mod.main([]) == 2


def test_event_path_and_summary(tmp_path, monkeypatch):
    ev = tmp_path / "ev.json"
    ev.write_text(
        json.dumps(
            {
                "pull_request": {
                    "body": "x",
                    "user": {"login": "dependabot[bot]"},
                    "base": {"sha": "a"},
                    "head": {"sha": "b"},
                }
            }
        )
    )
    ff = tmp_path / "f.txt"
    ff.write_text("src/a.py\n")
    summ = tmp_path / "s.md"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(ev))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summ))
    assert mod.main(["--files-from", str(ff)]) == 0
    assert "EXEMPT" in summ.read_text()
