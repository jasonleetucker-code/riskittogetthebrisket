"""Every script a systemd unit runs directly must put the repo root on sys.path.

The units run ``<venv>/bin/python /home/dynasty/trade-calculator/scripts/X.py``.
Run that way, Python puts ``scripts/`` on ``sys.path``, not the repo root, and
``WorkingDirectory=`` does not change that. So a top-level ``from src...``
import only works if the script inserts the repo root first, as
``scripts/fetch_crowd_faab.py`` does. Three units failed every run from at
least 2026-09-01 until 2026-09-24 with ``ModuleNotFoundError: No module named
'src'`` because their scripts did not (depth-charts, injury-feed,
trending-history).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_UNITS = sorted((_REPO / "deploy" / "systemd").glob("*.service*"))
_SCRIPT_IN_EXECSTART = re.compile(r"/scripts/([A-Za-z0-9_]+\.py)\b")


def _unit_scripts() -> list[str]:
    names: set[str] = set()
    for unit in _UNITS:
        for line in unit.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("ExecStart") and "python" in line:
                names.update(_SCRIPT_IN_EXECSTART.findall(line))
    return sorted(names)


def _is_repo_import(node: ast.stmt) -> bool:
    if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
        return node.module.split(".")[0] in ("src", "scripts")
    if isinstance(node, ast.Import):
        return any(a.name.split(".")[0] in ("src", "scripts") for a in node.names)
    return False


def _inserts_path(node: ast.stmt) -> bool:
    """A top-level statement that calls sys.path.insert / sys.path.append (possibly under an if)."""
    for sub in ast.walk(node):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr in ("insert", "append")
            and isinstance(sub.func.value, ast.Attribute)
            and sub.func.value.attr == "path"
            and isinstance(sub.func.value.value, ast.Name)
            and sub.func.value.value.id == "sys"
        ):
            return True
    return False


def test_units_run_scripts_at_all():
    assert _unit_scripts(), "no unit ExecStart runs a scripts/*.py file; the parser drifted"


@pytest.mark.parametrize("name", _unit_scripts())
def test_unit_script_bootstraps_the_repo_root_before_repo_imports(name: str) -> None:
    path = _REPO / "scripts" / name
    assert path.exists(), f"{name} is referenced by a unit but does not exist"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bootstrapped = False
    for node in tree.body:
        if _inserts_path(node):
            bootstrapped = True
        if _is_repo_import(node):
            assert bootstrapped, (
                f"scripts/{name} imports {ast.unparse(node)!r} at top level before any "
                "sys.path insert of the repo root; run as a unit it fails with "
                "ModuleNotFoundError: No module named 'src'"
            )
            return


_FIXED_2026_09_24 = (
    "refresh_depth_charts.py",
    "refresh_injury_feed.py",
    "refresh_sleeper_trending_history.py",
)


@pytest.mark.parametrize("name", _FIXED_2026_09_24)
def test_the_three_failing_unit_scripts_import_the_way_systemd_runs_them(name, tmp_path):
    """Load the script with only scripts/ on sys.path (as `python scripts/X.py` has),
    from an unrelated working directory, without running main()."""
    import os
    import subprocess
    import sys

    script = _REPO / "scripts" / name
    code = (
        "import runpy, sys\n"
        f"sys.path[0] = {str(script.parent)!r}\n"
        f"runpy.run_path({str(script)!r}, run_name='not_main')\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert "No module named 'src'" not in result.stderr, result.stderr[-2000:]
    assert result.returncode == 0, result.stderr[-2000:]
