"""The L0 syntax-compile step must not fail a PR for deleting a Python file.

``scripts/ci_change_scope.py --paths-only`` deliberately reports DELETED paths
(they matter for risk classification), and the fast gate passed them straight
to ``py_compile``. PR #1705 deleted ``src/news/unified_signal_engine.py`` and
L0 failed with ``[Errno 2] No such file or directory``. This runs the real
workflow step against a stubbed change scope that lists a deleted file.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_STEP = "Syntax-compile changed Python files"


def _step_script() -> str:
    workflow = yaml.safe_load((REPO / ".github" / "workflows" / "fast-gate.yml").read_text("utf-8"))
    for job in workflow["jobs"].values():
        for step in job.get("steps", []):
            if step.get("name") == _STEP:
                return step["run"]
    raise AssertionError(f"step {_STEP!r} not found")


def _bash() -> str:
    found = shutil.which("bash")
    if not found:
        pytest.skip("bash is not available")
    return found


def _run_step(tmp_path: Path, changed: list[str], body: str) -> subprocess.CompletedProcess:
    stub = tmp_path / "scripts" / "ci_change_scope.py"
    stub.parent.mkdir(parents=True)
    stub.write_text("print(" + repr("\n".join(changed)) + ")\n", encoding="utf-8")
    (tmp_path / "present.py").write_text(body, encoding="utf-8")
    return subprocess.run(
        [_bash(), "-c", _step_script()],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_a_deleted_python_file_is_not_compiled(tmp_path):
    proc = _run_step(tmp_path, ["present.py", "deleted_module.py"], "x = 1\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "present.py" in proc.stdout
    assert "deleted_module.py" not in proc.stdout


def test_a_present_file_with_a_syntax_error_still_fails(tmp_path):
    proc = _run_step(tmp_path, ["present.py", "deleted_module.py"], "def broken(:\n")
    assert proc.returncode != 0


def test_only_deleted_files_means_nothing_to_compile(tmp_path):
    proc = _run_step(tmp_path, ["deleted_module.py"], "x = 1\n")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "No changed Python files to compile." in proc.stdout


def test_the_local_l0_applies_the_same_rule():
    text = (REPO / "scripts" / "tiered_validate.sh").read_text("utf-8")
    assert 'if [[ -f "$f" ]]; then PY_FILES+=("$f"); fi' in text
