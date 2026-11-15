"""Batch G — the independent checker agrees with production, and can disagree.

``scripts/check_draft_valuation_independent.py`` re-derives the rookie-auction
curve and the per-class whole dollars from the owner workbook transcription,
the pinned fixtures and the repo-tracked snapshot DATA, importing nothing
from ``src/`` or ``server.py``.  This test:

* proves that structurally (AST: the checker imports only the standard
  library; the one file it loads by path is the stdlib-only Batch A
  transcription);
* runs it, isolated (``python -I``), against a dump of what production
  computes and serves for the golden and for 2027 / 2028 / 2029, and
  requires exact whole-dollar parity — every check PASS;
* mutates the production dump ($1 moved, a half dollar changed, a wrong
  spine, a different record) and requires the checker to FAIL and name it —
  a checker that cannot fail proves nothing.
"""

from __future__ import annotations

import ast
import copy
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CHECKER = REPO / "scripts" / "check_draft_valuation_independent.py"
DUMPER = REPO / "scripts" / "draft_valuation_dump_production.py"
STDLIB = {
    "__future__",
    "argparse",
    "ast",
    "hashlib",
    "importlib",
    "json",
    "math",
    "sys",
    "decimal",
    "fractions",
    "pathlib",
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add((node.module or "").split(".")[0])
    return names


def test_checker_imports_no_production_module():
    assert _imports(CHECKER) <= STDLIB, _imports(CHECKER) - STDLIB
    text = CHECKER.read_text(encoding="utf-8")
    assert "src.draft" not in text and "import server" not in text
    # The only file it loads by path is the Batch A transcription, itself stdlib-only.
    ref = REPO / "tests" / "draft_valuation" / "reference_workbook_formulas.py"
    assert _imports(ref) <= {"__future__", "fractions", "math", "re"}


@pytest.fixture(scope="module")
def dump(tmp_path_factory):
    out = tmp_path_factory.mktemp("prod") / "prod.json"
    done = subprocess.run(
        [sys.executable, str(DUMPER), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(out.read_text("utf-8"))


def _check(tmp_path, payload) -> subprocess.CompletedProcess:
    path = tmp_path / "prod.json"
    path.write_text(json.dumps(payload), "utf-8")
    report = tmp_path / "report.json"
    return subprocess.run(
        [
            sys.executable,
            "-I",
            str(CHECKER),
            "--production",
            str(path),
            "--repo",
            str(REPO),
            "--json",
            str(report),
        ],
        capture_output=True,
        text=True,
    )


def _failures(tmp_path) -> list[str]:
    report = json.loads((tmp_path / "report.json").read_text("utf-8"))
    return [r["check"] for r in report["results"] if r["status"] == "FAIL"]


def test_production_matches_the_independent_derivation_exactly(dump, tmp_path):
    assert sorted(dump["classes"]) == ["2027", "2028", "2029"]
    done = _check(tmp_path, dump)
    assert done.returncode == 0, done.stdout
    report = json.loads((tmp_path / "report.json").read_text("utf-8"))
    assert report["fail"] == 0 and report["pass"] >= 60
    checks = {r["check"] for r in report["results"]}
    for year in (2027, 2028, 2029):
        assert f"{year} production whole dollars = independent (exact)" in checks
        assert f"{year} stored record = independent whole dollars" in checks


def _moved_dollar(d):
    d["classes"]["2028"]["finalWholeDollars"][0] += 1
    d["classes"]["2028"]["finalWholeDollars"][1] -= 1  # still totals $1,200


def _half_dollar(d):
    ref = d["classes"]["2029"]["referenceDollars"]
    ref[5] = str(Decimal(ref[5]) + Decimal("0.5"))


def _wrong_spine(d):
    d["classes"]["2027"]["spineYears"] = [2023, 2024, 2025]


def _other_record(d):
    d["classes"]["2029"]["recordChecksum"] = d["classes"]["2028"]["recordChecksum"]


def _golden(d):
    d["golden"]["finalWholeDollars"][71] += 1


def _last_known_good(d):
    d["classes"]["2027"]["allocationState"] = "last_known_good"


@pytest.mark.parametrize(
    ("mutate", "named"),
    [
        (_moved_dollar, "2028 production whole dollars = independent (exact)"),
        (_half_dollar, "2029 production half-dollar curve = independent (exact)"),
        (_wrong_spine, "2027 spine years = production's served spine"),
        (_other_record, "2029 production serves the stored record"),
        (_golden, "golden: production whole dollars = independent (largest_remainder)"),
        (_last_known_good, "2027 production served state is current"),
    ],
)
def test_checker_fails_and_names_every_mutation(dump, tmp_path, mutate, named):
    payload = copy.deepcopy(dump)
    mutate(payload)
    done = _check(tmp_path, payload)
    assert done.returncode == 1, done.stdout
    assert named in _failures(tmp_path)
