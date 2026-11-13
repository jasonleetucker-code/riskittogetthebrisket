"""``python server.py`` executes server.py's module body ONCE (WA-17).

The systemd unit starts the backend with ``python server.py``, which runs the
file as ``__main__``; ``uvicorn.run("server:app")`` then imported it again as
``server``.  Every module-level load ran twice and the ``__main__`` copy was
never served: measured 2026-11-12, the unused copy held its own 44 MiB
public-league snapshot (``Loaded persisted public_league snapshot`` was
logged twice per start).

This runs the real entrypoint in a subprocess with a stub ``uvicorn`` that
resolves its target the way uvicorn does (``importlib.import_module``) and
reports what it found instead of serving.  On the previous entrypoint it
reports ``main_has_app: true`` and ``main_has_body_state: true``.  Importing
server.py writes nothing (verified when this test was written), and the stub
never starts the lifespan, so no scrape, timer or network call runs.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

_STUB = """
import importlib, json, sys

def run(target, **kw):
    module_name, attr = target.split(":")
    served = importlib.import_module(module_name)
    main = sys.modules["__main__"]
    print("UVICORN_STUB " + json.dumps({
        "served_module": served.__name__,
        "served_file": getattr(served, "__file__", None),
        "main_is_served": main is served,
        "main_has_app": hasattr(main, "app"),
        "main_has_body_state": hasattr(main, "_public_league_cache"),
        "served_has_app": hasattr(served, attr),
        "host": kw.get("host"),
        "reload": kw.get("reload"),
    }))
"""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX subprocess environment")
def test_python_server_py_executes_the_module_once(tmp_path):
    stub = tmp_path / "stub" / "uvicorn"
    stub.mkdir(parents=True)
    (stub / "__init__.py").write_text(_STUB, encoding="utf-8")
    env = {
        **os.environ,
        "PYTHONPATH": str(stub.parent),
        "ALLOW_DEFAULT_LOGIN_DEV": "1",
        "UPTIME_CHECK_ENABLED": "false",
    }
    env.pop("RISKIT_BIND_HOST", None)
    res = subprocess.run(
        [sys.executable, str(ROOT / "server.py")],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert res.returncode == 0, res.stderr[-4000:]
    lines = [ln for ln in res.stdout.splitlines() if ln.startswith("UVICORN_STUB ")]
    assert len(lines) == 1, res.stdout[-4000:]
    seen = json.loads(lines[0][len("UVICORN_STUB ") :])
    assert seen["served_module"] == "server"
    assert Path(seen["served_file"]).resolve() == (ROOT / "server.py").resolve()
    assert seen["served_has_app"] is True
    # The script copy stops at the guard: no app, no module-level state.
    assert seen["main_has_app"] is False
    assert seen["main_has_body_state"] is False
    assert seen["main_is_served"] is False
    # What it serves did not change.
    assert seen["host"] == "127.0.0.1"
    assert seen["reload"] is False
    # One load of the persisted snapshot per start, not two.
    assert (res.stdout + res.stderr).count("Loaded persisted public_league snapshot") <= 1


def test_importing_server_does_not_run_the_entrypoint():
    """``import server`` (tests, scripts, chase_upside_mcp) must not serve."""
    import server  # noqa: PLC0415

    assert server.__name__ == "server"
    assert callable(server.main)
