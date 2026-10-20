"""The research read-only guard (scripts/research_readonly_guard.py).

The guard is a CPython audit hook that can never be removed, so every test runs
it in a fresh interpreter: once installed, the process must be unable to write a
file (outside its own private scratch dir), open SQLite read-write, reach the
network or start a subprocess — and every refusal is recorded.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GUARD = REPO / "scripts" / "research_readonly_guard.py"


def _run(body: str, tmp_path: Path) -> dict:
    code = (
        textwrap.dedent(
            f"""
        import importlib.util, json, os, sys
        spec = importlib.util.spec_from_file_location("g", {str(GUARD)!r})
        g = importlib.util.module_from_spec(spec); spec.loader.exec_module(g)
        scratch = g.install()
        target = {str(tmp_path)!r}
        results = {{}}
        def attempt(name, fn):
            try:
                fn(); results[name] = "allowed"
            except PermissionError:
                results[name] = "refused"
        """
        )
        + textwrap.dedent(body)
        + textwrap.dedent(
            """
        results["_denied"] = len(g.denied())
        results["_bytecode"] = sys.dont_write_bytecode
        print(json.dumps(results))
        """
        )
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_writes_outside_scratch_are_refused(tmp_path):
    existing = tmp_path / "existing.txt"
    existing.write_text("original", encoding="utf-8")
    r = _run(
        """
        attempt("open_w", lambda: open(os.path.join(target, "new.txt"), "w"))
        attempt("open_a", lambda: open(os.path.join(target, "existing.txt"), "a"))
        attempt("open_rplus", lambda: open(os.path.join(target, "existing.txt"), "r+"))
        attempt("os_open_creat", lambda: os.open(os.path.join(target, "x"), os.O_CREAT | os.O_WRONLY))
        attempt("remove", lambda: os.remove(os.path.join(target, "existing.txt")))
        attempt("rename", lambda: os.rename(os.path.join(target, "existing.txt"), os.path.join(target, "y")))
        attempt("mkdir", lambda: os.mkdir(os.path.join(target, "d")))
        attempt("chmod", lambda: os.chmod(os.path.join(target, "existing.txt"), 0o777))
        attempt("read", lambda: open(os.path.join(target, "existing.txt")).read())
        attempt("scratch_write", lambda: open(os.path.join(scratch, "ok.txt"), "w").write("x"))
        """,
        tmp_path,
    )
    for k in (
        "open_w",
        "open_a",
        "open_rplus",
        "os_open_creat",
        "remove",
        "rename",
        "mkdir",
        "chmod",
    ):
        assert r[k] == "refused", k
    assert r["read"] == "allowed"
    assert r["scratch_write"] == "allowed"
    assert r["_denied"] == 8
    assert r["_bytecode"] is True
    assert existing.read_text(encoding="utf-8") == "original"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["existing.txt"]


def test_sqlite_only_read_only(tmp_path):
    import sqlite3

    db = tmp_path / "ledger.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE t (x)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    before = db.read_bytes()
    r = _run(
        f"""
        import sqlite3
        db = {str(db)!r}
        attempt("rw_path", lambda: sqlite3.connect(db))
        attempt("rw_uri", lambda: sqlite3.connect("file:" + db + "?mode=rw", uri=True))
        def ro():
            c = sqlite3.connect("file:" + db + "?mode=ro", uri=True)
            assert c.execute("SELECT x FROM t").fetchone() == (1,)
            try:
                c.execute("INSERT INTO t VALUES (2)")
            except sqlite3.OperationalError:
                results["ro_insert"] = "sqlite_refused"
        attempt("ro", ro)
        attempt("memory", lambda: sqlite3.connect(":memory:"))
        """,
        tmp_path,
    )
    assert r["rw_path"] == "refused" and r["rw_uri"] == "refused"
    assert r["ro"] == "allowed" and r["ro_insert"] == "sqlite_refused"
    assert r["memory"] == "allowed"
    assert db.read_bytes() == before


def test_network_and_subprocess_refused(tmp_path):
    r = _run(
        """
        import socket, subprocess
        attempt("dns", lambda: socket.getaddrinfo("example.com", 443))
        attempt("connect", lambda: socket.create_connection(("127.0.0.1", 9), timeout=1))
        attempt("subprocess", lambda: subprocess.run(["true"]))
        attempt("system", lambda: os.system("true"))
        """,
        tmp_path,
    )
    assert r["dns"] == r["connect"] == r["subprocess"] == r["system"] == "refused"


def test_phase2_box_mode_installs_the_guard_before_app_imports():
    src = (REPO / "scripts" / "package_model_phase2_research.py").read_text(encoding="utf-8")
    guard_at = src.index("GUARD.install()")
    assert guard_at < src.index("sys.path.insert(0, str(REPO))")
    assert guard_at < src.index("_spec.loader.exec_module(P1)")
    assert "import subprocess" not in src.split("def market_ledger_only", 1)[1]


@pytest.mark.parametrize(
    "payload",
    [
        {"deployedCodeSha": "79c32282868f20c3298ae28d5abf9b030c5293fe", "n": 3},
        {"deployedCodeSha": "UNKNOWN"},
    ],
)
def test_aggregate_check_accepts_only_a_real_sha(payload):
    from tests.scripts.test_package_model_phase2_research import P2

    P2.assert_aggregate_only(payload)
    with pytest.raises(ValueError):
        P2.assert_aggregate_only({"deployedCodeSha": "1312006700437352448"})
    with pytest.raises(ValueError):
        P2.assert_aggregate_only({"x": {"rosterId": 3}})
