"""Pin scripts/ci_change_scope.py — the single owner for path-aware CI scoping.

Both `.github/workflows/pr-validation.yml` and the local fast-loop script
(`scripts/tiered_validate.sh`) call `compute_scope`. If this drifts, one of
them silently stops agreeing with the other about what "backend changed"
means, which is exactly the drift the tiered-validation workflow (see
docs/AGENT_OPERATING_SYSTEM.md §3, "Tiered validation workflow") depends on
not happening.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.ci_change_scope import compute_scope


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "-m", "main")
    return repo


def _commit_files(repo: Path, files: dict[str, str], message: str) -> None:
    for rel_path, content in files.items():
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return _init_repo(tmp_path)


def test_frontend_only_change_does_not_flag_python(repo: Path):
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit_files(
        repo,
        {"frontend/components/Foo.jsx": "export default function Foo() {}\n"},
        "frontend change",
    )

    scope = compute_scope(base_ref="main", head_ref="feature", repo_root=str(repo))

    assert scope.frontend is True
    assert scope.python is False
    assert scope.high_risk is False


def test_python_only_change_does_not_flag_frontend(repo: Path):
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit_files(repo, {"src/trade/finder.py": "def foo():\n    return 1\n"}, "backend change")

    scope = compute_scope(base_ref="main", head_ref="feature", repo_root=str(repo))

    assert scope.python is True
    assert scope.frontend is False
    assert scope.high_risk is False


def test_workflow_change_is_high_risk_and_forces_both(repo: Path):
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit_files(
        repo,
        {".github/workflows/pr-validation.yml": "name: PR Validation\n"},
        "workflow change",
    )

    scope = compute_scope(base_ref="main", head_ref="feature", repo_root=str(repo))

    assert scope.high_risk is True
    assert scope.python is True
    assert scope.frontend is True


def test_canonical_owner_change_is_high_risk(repo: Path):
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit_files(repo, {"src/canonical/player_valuation.py": "X = 1\n"}, "canonical change")

    scope = compute_scope(base_ref="main", head_ref="feature", repo_root=str(repo))

    assert scope.high_risk is True
    assert scope.python is True
    assert scope.frontend is True


def test_docs_only_change_flags_neither(repo: Path):
    _git(repo, "checkout", "-q", "-b", "feature")
    _commit_files(repo, {"docs/SOME_NOTE.md": "note\n"}, "docs change")

    scope = compute_scope(base_ref="main", head_ref="feature", repo_root=str(repo))

    assert scope.python is False
    assert scope.frontend is False
    assert scope.high_risk is False


def test_unresolvable_base_ref_fails_safe_to_everything(repo: Path):
    scope = compute_scope(base_ref="origin/does-not-exist", head_ref="main", repo_root=str(repo))

    assert scope.python is True
    assert scope.frontend is True
    assert scope.high_risk is True
    assert scope.fallback_reason is not None


def test_no_diff_at_all_flags_nothing(repo: Path):
    scope = compute_scope(base_ref="main", head_ref="main", repo_root=str(repo))

    assert scope.python is False
    assert scope.frontend is False
    assert scope.high_risk is False
    assert scope.changed_paths == []
