"""``scripts/classify_deploy_delta.py`` -- DATA_ONLY only when the code tree is identical.

Audit-remediation Task 3 (owner directive 2026-11-18), SHADOW MODE: the
classifier decides nothing in production, but its rule is the one an activated
data-only path would trust, so every fail-closed branch is pinned here on real
git repositories built in a temp directory (no network, no live board).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from scripts import classify_deploy_delta as cdd

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class Repo:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True)
        self.git("init", "-q", "-b", "main")

    def git(self, *args: str) -> str:
        out = subprocess.run(
            ["git", "-C", str(self.root), *args],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **_GIT_ENV},
        )
        return out.stdout.strip()

    def write(self, rel: str, content: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def commit(self, message: str = "c") -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "--allow-empty", "-m", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    r = Repo(tmp_path / "repo")
    r.write("src/app.py", "VALUE = 1\n")
    r.write("server.py", "import src.app\n")
    r.write("config/weights/w.json", '{"w": 1}\n')
    r.write("data/scrape_state/ktc_last_success", "1763460000\n")
    r.write("exports/latest/dynasty_data_2026-11-18.json", '{"players": {}}\n')
    r.write("CSVs/site_raw/ktc.csv", "name,value\na,1\n")
    r.write("docs/notes.md", "prose\n")
    return r


def _classify(repo: Repo, base: str, target: str) -> dict:
    return cdd.classify(repo.root, base, target, base_source="test")


# ── the five cases the task names ──────────────────────────────────────────


def test_a_one_byte_code_change_is_code(repo: Repo):
    base = repo.commit("base")
    repo.write("src/app.py", "VALUE = 2\n")  # one byte differs
    target = repo.commit("one byte")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert "code_paths_changed" in receipt["reasons"]
    assert [c["path"] for c in receipt["codePaths"]] == ["src/app.py"]
    assert receipt["codeTreeDigest"]["base"] != receipt["codeTreeDigest"]["target"]


def test_a_pure_data_change_is_data_only(repo: Repo):
    base = repo.commit("base")
    repo.write("data/scrape_state/ktc_last_success", "1763467200\n")
    repo.write("CSVs/site_raw/ktc.csv", "name,value\na,2\n")
    repo.write("data/ros/new_output.json", "{}\n")
    (repo.root / "exports" / "latest" / "dynasty_data_2026-11-18.json").unlink()
    repo.write("exports/latest/dynasty_data_2026-11-19.json", "{}\n")
    target = repo.commit("automated data refresh")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.DATA_ONLY, receipt["reasons"]
    assert receipt["reasons"] == ["code_tree_identical"]
    assert receipt["baseIsAncestor"] is True
    assert receipt["codeTreeDigest"]["base"] == receipt["codeTreeDigest"]["target"]
    assert receipt["dataTreeDigest"]["base"] != receipt["dataTreeDigest"]["target"]
    assert receipt["changed"] == {"total": 5, "code": 0, "data": 5}  # 2 M, 2 A, 1 D
    assert set(receipt["dataPathRoots"]) == {"CSVs/", "data/", "exports/"}


def test_an_unknown_new_top_level_path_is_code(repo: Repo):
    base = repo.commit("base")
    repo.write("newroot/payload.json", "{}\n")  # a .json, but nobody classified newroot/
    target = repo.commit("new root")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["codePaths"] == [
        {
            "path": "newroot/payload.json",
            "status": "A",
            "class": "code",
            "reason": "outside_data_roots",
        }
    ]


@pytest.mark.parametrize(
    "rel",
    [
        "config/weights/w.json",
        "config/model_registry/hill_autopilot_runs.jsonl",
        "config/model_registry/hill_scope_masters.json",
        "config/draft_valuation/promotion_pointers/2027.json",
    ],
)
def test_a_config_file_is_code(repo: Repo, rel: str):
    base = repo.commit("base")
    repo.write(rel, '{"changed": true}\n')
    target = repo.commit("config")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["codePaths"][0]["path"] == rel


@pytest.mark.parametrize(
    ("base_value", "reason"),
    [("", "base_unknown"), ("abc123", "base_invalid"), ("0" * 40, "base_unavailable")],
)
def test_a_missing_base_is_code(repo: Repo, base_value: str, reason: str):
    repo.commit("base")
    repo.write("data/scrape_state/ktc_last_success", "2\n")
    target = repo.commit("data only")
    receipt = _classify(repo, base_value, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["reasons"] == [reason]


# ── the other fail-closed branches ─────────────────────────────────────────


def test_a_missing_target_is_code(repo: Repo):
    base = repo.commit("base")
    receipt = _classify(repo, base, "f" * 40)
    assert receipt["classification"] == cdd.CODE
    assert receipt["reasons"] == ["target_unavailable"]


def test_a_rollback_of_data_alone_is_still_code(repo: Repo):
    older = repo.commit("base")
    repo.write("data/scrape_state/ktc_last_success", "3\n")
    newer = repo.commit("data")
    # Production is at `newer`; deploying `older` moves it backwards.
    receipt = _classify(repo, newer, older)
    assert receipt["classification"] == cdd.CODE
    assert receipt["reasons"] == ["base_not_ancestor"]
    assert receipt["baseIsAncestor"] is False


def test_a_diverged_target_is_code(repo: Repo):
    root = repo.commit("base")
    repo.write("data/a.json", "1\n")
    side = repo.commit("side")
    repo.git("checkout", "-q", "-b", "other", root)
    repo.write("data/b.json", "2\n")
    other = repo.commit("other")
    receipt = _classify(repo, side, other)
    assert receipt["classification"] == cdd.CODE
    assert "base_not_ancestor" in receipt["reasons"]


def test_a_redeploy_of_the_same_commit_is_data_only(repo: Repo):
    sha = repo.commit("base")
    receipt = _classify(repo, sha, sha)
    assert receipt["classification"] == cdd.DATA_ONLY
    assert receipt["changed"] == {"total": 0, "code": 0, "data": 0}


def test_a_data_file_turned_executable_is_code(repo: Repo):
    base = repo.commit("base")
    (repo.root / "data/scrape_state/ktc_last_success").chmod(0o755)
    target = repo.commit("chmod")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["codePaths"][0]["reason"] == "non_regular_mode:100755"


def test_a_symlink_under_a_data_root_is_code(repo: Repo):
    base = repo.commit("base")
    os.symlink("../src/app.py", repo.root / "data" / "link.json")
    target = repo.commit("symlink")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["codePaths"][0]["reason"] == "non_regular_mode:120000"


def test_python_under_a_data_root_is_code(repo: Repo):
    base = repo.commit("base")
    repo.write("data/helper.py", "import os\n")
    target = repo.commit("py in data")
    assert _classify(repo, base, target)["classification"] == cdd.CODE


def test_the_one_reviewed_js_export_is_data(repo: Repo):
    base = repo.commit("base")
    repo.write("exports/latest/dynasty_data.js", "window.DYNASTY_DATA = {};\n")
    target = repo.commit("export")
    assert _classify(repo, base, target)["classification"] == cdd.DATA_ONLY


def test_a_docs_change_is_code(repo: Repo):
    base = repo.commit("base")
    repo.write("docs/notes.md", "more prose\n")
    target = repo.commit("docs")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["codePathGroups"] == {"docs/": 1}


def test_a_mixed_delta_lists_only_the_code_paths(repo: Repo):
    base = repo.commit("base")
    repo.write("data/scrape_state/ktc_last_success", "9\n")
    repo.write("tests/test_new.py", "def test_x():\n    pass\n")
    target = repo.commit("mixed")
    receipt = _classify(repo, base, target)
    assert receipt["classification"] == cdd.CODE
    assert receipt["changed"] == {"total": 2, "code": 1, "data": 1}
    assert receipt["codePathGroups"] == {"tests/": 1}


# ── the entry rule, without git ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "mode", "expected"),
    [
        ("data/scrape_state/ktc_last_success", "100644", "data"),
        ("exports/narratives/2026/week_01.json", "100644", "data"),
        ("CSVs/Draft Data.xlsx", "100644", "data"),
        ("exports/latest/dynasty_data.js", "100644", "data"),
        ("data/raw/README.md", "100644", "data"),
        ("Data/x.json", "100644", "code"),  # case-sensitive roots
        ("datax/x.json", "100644", "code"),
        ("data", "100644", "code"),
        ("data/x.json", "100755", "code"),
        ("data/x.json", "120000", "code"),
        ("data/sub", "160000", "code"),
        ("data/x.PY", "100644", "code"),
        ("data/x.yml", "100644", "code"),
        ("data/model.pkl", "100644", "code"),
        ("exports/latest/model.PICKLE", "100644", "code"),
        ("data/ros/model.joblib", "100644", "code"),
        ("data/model.dill", "100644", "code"),
        ("data/model.pt", "100644", "code"),
        ("data/arr.npy", "100644", "data"),  # numpy refuses pickled objects by default
        ("data/arr.npz", "100644", "data"),
        ("data/t.parquet", "100644", "data"),
        ("data/.gitattributes", "100644", "code"),
        ("exports/conftest.py", "100644", "code"),
        ("exports/other.js", "100644", "code"),
        ("data/../src/app.py", "100644", "code"),
        ("data//x.json", "100644", "code"),
        ("src/api/data_contract.py", "100644", "code"),
        ("server.py", "100644", "code"),
        ("Dynasty Scraper.py", "100644", "code"),
        ("frontend/package-lock.json", "100644", "code"),
        ("requirements.lock.txt", "100644", "code"),
        ("pyproject.toml", "100644", "code"),
        ("tests/fixtures/board.json", "100644", "code"),
        (".github/workflows/deploy.yml", "100644", "code"),
        ("deploy/deploy.sh", "100755", "code"),
        ("config/sources/freshness_v1.json", "100644", "code"),
    ],
)
def test_classify_entry(path: str, mode: str, expected: str):
    assert cdd.classify_entry(path, mode)[0] == expected


def test_every_data_exception_sits_under_a_data_root_and_needs_the_exception():
    for path, reason in cdd.DATA_EXCEPTIONS.items():
        assert reason.strip()
        assert any(path.startswith(root) for root in cdd.DATA_ROOTS)
        suffix = Path(path).suffix.lower()
        assert suffix in cdd.CODE_SUFFIXES, f"{path} would be data without the exception"


def test_the_receipt_carries_the_rules_and_their_digest(repo: Repo):
    sha = repo.commit("base")
    receipt = _classify(repo, sha, sha)
    assert receipt["rules"] == cdd.rules_document()
    assert receipt["rulesDigest"] == cdd.rules_digest()
    assert set(receipt["rules"]["dataRoots"]) == {"CSVs/", "data/", "exports/"}


def test_cli_writes_the_receipt_and_the_step_output(repo: Repo, tmp_path: Path, monkeypatch):
    base = repo.commit("base")
    repo.write("CSVs/site_raw/ktc.csv", "name,value\na,3\n")
    target = repo.commit("data")
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    receipt_path = tmp_path / "r" / "classification.json"
    rc = cdd.main(
        [
            "--repo",
            str(repo.root),
            "--base",
            base,
            "--target",
            target,
            "--receipt",
            str(receipt_path),
        ]
    )
    assert rc == 0
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["classification"] == cdd.DATA_ONLY
    assert out.read_text(encoding="utf-8") == "classification=DATA_ONLY\n"


def test_cli_answers_code_rather_than_failing_on_an_unknown_base(repo: Repo, tmp_path, monkeypatch):
    target = repo.commit("base")
    out = tmp_path / "gh_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    assert cdd.main(["--repo", str(repo.root), "--base", "", "--target", target]) == 0
    assert out.read_text(encoding="utf-8") == "classification=CODE\n"
