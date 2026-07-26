from __future__ import annotations

import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


_MIN_PLAYERS = 50


def _snapshot_player_count(path: Path) -> int:
    """Players in a dynasty snapshot, or -1 when it can't be read."""
    try:
        with path.open() as fh:
            return len(json.load(fh).get("players") or {})
    except Exception:  # noqa: BLE001 — unreadable/corrupt counts as unusable
        return -1


def _seed_data_cache(repo_root: Path) -> None:
    """Guarantee ``data/`` holds a snapshot the backend can actually serve.

    ``server.py::load_from_disk`` primes the live contract from the
    NEWEST ``data/dynasty_data_*.json``.  On a clean checkout that
    directory is empty, so the server sits with no data until the
    startup scrape completes — which needs external network + scraper
    credentials that CI, sandboxes and offline runs don't have.  The
    repo commits the latest pipeline output under ``exports/latest/``
    (refreshed by scheduled-refresh.yml), so we copy it across.

    A bare "is the directory non-empty?" check is not enough, and that
    gap is what let agents hit an unusable stack:

    * A **failed scrape** can leave a truncated or empty snapshot
      behind.  The old check saw a file, skipped seeding, and the
      backend served an empty board.
    * ``load_from_disk`` takes the newest file by name, so a broken
      newer snapshot shadows a good older one.

    So we validate the file the backend will actually pick and seed
    alongside it when it's unusable.  A healthy local scrape still
    wins — we only intervene when the newest snapshot can't serve.
    """
    data_dir = repo_root / "data"
    existing = sorted(data_dir.glob("dynasty_data_*.json"))
    exports = sorted((repo_root / "exports" / "latest").glob("dynasty_data_*.json"))

    if existing:
        # Mirror load_from_disk's selection: newest by name wins.
        newest = existing[-1]
        count = _snapshot_player_count(newest)
        if count >= _MIN_PLAYERS:
            print(f"[preflight] data/{newest.name} usable ({count} players) — seed skipped")
            return
        print(
            f"[preflight] data/{newest.name} is unusable "
            f"({'unreadable' if count < 0 else f'{count} players'}) — "
            "a failed scrape can leave a truncated snapshot behind; "
            "seeding from the committed export"
        )

    if not exports:
        print(
            "[preflight] ERROR: no committed exports/latest/dynasty_data_*.json "
            "to seed from, and data/ has no usable snapshot.  The suite is "
            "data-driven and cannot run: specs would skip or time out on "
            "missing data instead of catching regressions."
        )
        raise SystemExit(1)

    src = exports[-1]
    count = _snapshot_player_count(src)
    if count < _MIN_PLAYERS:
        print(
            f"[preflight] ERROR: committed {src.name} holds "
            f"{'unreadable content' if count < 0 else f'only {count} players'} "
            f"(need >= {_MIN_PLAYERS}) — cannot seed a usable snapshot."
        )
        raise SystemExit(1)

    data_dir.mkdir(parents=True, exist_ok=True)
    dest = data_dir / src.name
    if existing and dest.exists() and dest.samefile(existing[-1]):
        # The unusable newest snapshot IS this filename — overwrite it.
        pass
    shutil.copy2(src, dest)
    # The seeded file must be the newest by name or load_from_disk will
    # keep choosing the broken one.
    if sorted(data_dir.glob("dynasty_data_*.json"))[-1] != dest:
        newest = sorted(data_dir.glob("dynasty_data_*.json"))[-1]
        quarantine = newest.with_suffix(".json.unusable")
        newest.rename(quarantine)
        print(
            f"[preflight] quarantined unusable newer snapshot "
            f"{newest.name} -> {quarantine.name} so the seeded one is picked"
        )
    print(f"[preflight] seeded data/{dest.name} from committed exports/latest/ ({count} players)")


def _check_node_deps(repo_root: Path) -> None:
    """Fail early, with the lockfile-safe fix, when node deps are missing.

    Two separate installs matter:

    * root ``node_modules`` — the Playwright runner itself.
    * ``frontend/node_modules`` — the webServer builds and serves Next.

    Both are pinned by committed lockfiles, so the correct install is
    ``npm ci``: it installs exactly what the lockfile says and never
    rewrites it.  This matters for agents working under coordination
    rules that forbid touching the lockfile — ``npm install`` may
    rewrite it, ``npm ci`` cannot, so no one needs a lockfile edit to
    get a runnable suite.
    """
    missing = []
    if not (repo_root / "node_modules" / "@playwright" / "test").is_dir():
        missing.append(("root", "npm ci", "the Playwright test runner"))
    if not (repo_root / "frontend" / "node_modules").is_dir():
        missing.append(("frontend", "npm --prefix frontend ci", "the Next.js frontend build"))
    if missing:
        print("[preflight] ERROR: node dependencies are not installed.")
        for where, cmd, what in missing:
            print(f"[preflight]   {where}: missing — needed for {what}")
            print(f"[preflight]     fix: {cmd}")
        print(
            "[preflight] `npm ci` is lockfile-exact and never rewrites "
            "package-lock.json, so it is safe under no-lockfile-edit rules."
        )
        raise SystemExit(1)
    print("[preflight] node dependencies present (runner + frontend)")


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
    _check_node_deps(repo_root)
    print("[preflight] ready for browser regression suite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
