"""Shadow isolation: nothing live imports ``src.ros_calibration``.

The only permitted importer is the research study script.  The package imports
only an allow-listed set of read-only owners — never feature flags, the server,
the data contract, or any writer of ``data/ros``.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "src" / "ros_calibration"
ALLOWED_IMPORTERS = {"scripts/ros_scale_calibration_study.py"}
ALLOWED_SRC_IMPORTS = {
    "src.ros.lineup": {"lineup_position"},
    "src.league_intel.replacement": {"compute_replacement_levels", "normalize_base_position"},
    "src.ros_calibration": None,
}


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            yield node.module, {a.name for a in node.names}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, set()


def _is_pkg(module: str) -> bool:
    return module == "src.ros_calibration" or module.startswith("src.ros_calibration.")


def test_no_live_module_imports_the_package():
    offenders = []
    roots = [REPO / "src", REPO / "scripts", REPO / "deploy"]
    files = [p for root in roots if root.exists() for p in root.rglob("*.py")]
    files.append(REPO / "server.py")
    for path in files:
        if PACKAGE in path.parents:
            continue
        rel = path.relative_to(REPO).as_posix()
        for module, names in _imports(path):
            if _is_pkg(module) or (module == "src" and "ros_calibration" in names):
                if rel not in ALLOWED_IMPORTERS:
                    offenders.append(rel)
    assert offenders == []


def test_frontend_never_references_the_package():
    hits = []
    fe = REPO / "frontend"
    for ext in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for path in fe.rglob(ext):
            if "node_modules" in path.parts or ".next" in path.parts:
                continue
            if "ros_calibration" in path.read_text(encoding="utf-8", errors="ignore"):
                hits.append(str(path))
    assert hits == []


def test_package_imports_only_allow_listed_owners():
    bad = []
    for path in PACKAGE.rglob("*.py"):
        for module, names in _imports(path):
            if not module.startswith("src"):
                continue
            if _is_pkg(module):
                continue
            allowed = ALLOWED_SRC_IMPORTS.get(module, "missing")
            if allowed == "missing" or (allowed is not None and not names <= allowed):
                bad.append((path.name, module, sorted(names)))
    assert bad == []


def test_package_never_writes_files():
    for path in PACKAGE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for forbidden in ("write_text", "write_bytes", "open(", "json.dump"):
            assert forbidden not in text, (path.name, forbidden)
