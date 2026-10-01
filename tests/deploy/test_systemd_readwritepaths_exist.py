"""A sandboxed unit's ReadWritePaths must exist when the unit starts.

systemd bind-mounts every ReadWritePaths entry while setting up the unit's
mount namespace; a path that does not exist yet fails the unit with
status=226/NAMESPACE before the program runs -- so a collector that creates its
own store on first run can never create it.  Observed on production
2026-10-01 for dynasty-signals-fetch (``data/sources/signals``).

Rule: under the app checkout, a ReadWritePaths entry must be the checkout or
its always-present ``data/`` directory; anything else must be optional
(``-`` prefix).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ALWAYS_PRESENT = {"__APP_DIR__", "__APP_DIR__/data"}


def _entries():
    for unit in sorted((ROOT / "deploy" / "systemd").glob("*.service.template")):
        for line in unit.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ReadWritePaths="):
                for path in line.split("=", 1)[1].split():
                    yield unit.name, path


def test_app_dir_write_paths_exist_at_start():
    offenders = [
        (unit, path)
        for unit, path in _entries()
        if path.startswith("__APP_DIR__") and path not in ALWAYS_PRESENT
    ]
    assert offenders == [], offenders


def test_signals_fetch_can_create_its_own_store():
    entries = [p for u, p in _entries() if u == "dynasty-signals-fetch.service.template"]
    assert entries == ["__APP_DIR__/data"]
