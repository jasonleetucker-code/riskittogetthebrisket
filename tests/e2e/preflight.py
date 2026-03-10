from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path


def _compile_python(repo_root: Path) -> None:
    targets = [
        repo_root / "server.py",
        repo_root / "Dynasty Scraper.py",
    ]
    for target in targets:
        py_compile.compile(str(target), doraise=True)
    print("[preflight] Python compile checks passed")


def _run_contract_validation(repo_root: Path) -> None:
    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "validate_api_contract.py"),
        "--repo",
        str(repo_root),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, check=False)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)
    print("[preflight] API contract validation passed")


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    _compile_python(repo_root)
    _run_contract_validation(repo_root)
    print("[preflight] ready for browser regression suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
