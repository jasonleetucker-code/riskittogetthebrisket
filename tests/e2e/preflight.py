from __future__ import annotations

import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


def _seed_data_cache(repo_root: Path) -> None:
    """Seed ``data/`` from the committed export snapshot when empty.

    ``server.py::load_from_disk`` primes the live contract from the
    newest ``data/dynasty_data_*.json``.  On a clean checkout that
    directory has no snapshot, so the server would sit empty until the
    startup scrape completes — which requires external network +
    scraper credentials that CI and offline runs don't have.  The
    repo DOES commit the latest pipeline output under
    ``exports/latest/`` (refreshed by scheduled-refresh.yml), so we
    copy it across once.  Never overwrites: a fresher local scrape
    always wins.
    """
    data_dir = repo_root / "data"
    if sorted(data_dir.glob("dynasty_data_*.json")):
        print("[preflight] data/ already has a dynasty snapshot — seed skipped")
        return
    exports = sorted((repo_root / "exports" / "latest").glob("dynasty_data_*.json"))
    if not exports:
        print(
            "[preflight] WARNING: no committed exports/latest/dynasty_data_*.json "
            "to seed from — browser tests will fail until a scrape completes"
        )
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    src = exports[-1]
    shutil.copy2(src, data_dir / src.name)
    print(f"[preflight] seeded data/{src.name} from committed exports/latest/")


def _check_frontend_deps(repo_root: Path) -> None:
    """Fail early with a clear message if frontend deps are missing.

    The Playwright webServer boots Next.js from ``frontend/`` — a bare
    checkout without ``npm install`` there produces a confusing
    build-time failure minutes into the run.  Catch it up front.
    """
    if not (repo_root / "frontend" / "node_modules").is_dir():
        print(
            "[preflight] ERROR: frontend/node_modules missing — run "
            "`npm install` inside frontend/ first (the E2E webServer "
            "builds and serves the Next.js frontend)"
        )
        raise SystemExit(1)
    print("[preflight] frontend dependencies present")


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
    _seed_data_cache(repo_root)
    _check_frontend_deps(repo_root)
    print("[preflight] ready for browser regression suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
