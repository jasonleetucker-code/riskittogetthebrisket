"""Pins for the per-module process-state guard (R-TEST-ISOLATION).

The guard lives in ``tests/process_state_isolation.py`` and is wired as a
module-scoped autouse fixture in ``tests/conftest.py``.  A guard that cannot
fail proves nothing, so each rule is exercised against a fake ``sys.modules``
and a real FastAPI app, and one subprocess run proves the wired fixture fails
a module that leaks.
"""

from __future__ import annotations

import ast
import importlib.machinery
import re
import subprocess
import sys
import textwrap
import types
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import APIRouter, FastAPI
from starlette.middleware.gzip import GZipMiddleware

from tests import process_state_isolation as guard

REPO_ROOT = Path(__file__).resolve().parents[1]


def _real_module(name: str) -> types.ModuleType:
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    return module


def _fake_server() -> tuple[dict, FastAPI]:
    app = FastAPI()

    @app.get("/kept")
    def kept() -> dict:
        return {}

    server = _real_module(guard.SERVER_MODULE)
    server.app = app
    return {guard.SERVER_MODULE: server, "colorsys": _real_module("colorsys")}, app


def test_a_clean_module_reports_nothing_and_changes_nothing():
    modules, app = _fake_server()
    before = guard.take(modules)
    routes = list(app.router.routes)

    findings = guard.check_and_restore(before, modules)

    assert not findings and findings.lines() == []
    assert list(app.router.routes) == routes


def test_a_replaced_entry_is_reported_and_the_original_put_back():
    modules, _ = _fake_server()
    original = modules["colorsys"]
    before = guard.take(modules)
    modules["colorsys"] = MagicMock()

    findings = guard.check_and_restore(before, modules)

    assert findings.replaced == ["colorsys"]
    assert modules["colorsys"] is original


def test_a_removed_entry_is_reported_and_restored():
    """``del sys.modules["server"]`` then re-import is a second server."""
    modules, _ = _fake_server()
    original = modules[guard.SERVER_MODULE]
    before = guard.take(modules)
    del modules[guard.SERVER_MODULE]
    modules[guard.SERVER_MODULE + "_other"] = _real_module("unrelated")

    findings = guard.check_and_restore(before, modules)

    assert findings.removed == [guard.SERVER_MODULE]
    assert modules[guard.SERVER_MODULE] is original


def test_a_reimported_submodule_is_rebound_on_its_parent_package():
    """``del sys.modules["pkg.sub"]`` + re-import rebinds ``pkg.sub``, and
    ``from pkg import sub`` reads the attribute first."""
    modules, _ = _fake_server()
    parent, child = _real_module("pkg"), _real_module("pkg.sub")
    parent.sub = child
    modules.update({"pkg": parent, "pkg.sub": child})
    before = guard.take(modules)
    second = _real_module("pkg.sub")
    modules["pkg.sub"] = second
    parent.sub = second

    findings = guard.check_and_restore(before, modules)

    assert findings.replaced == ["pkg.sub"]
    assert modules["pkg.sub"] is child and parent.sub is child


def test_a_reloaded_server_app_is_reported_and_put_back():
    """``importlib.reload(server)`` keeps the module object, so only the
    ``app`` identity shows that every route now hangs off a second app."""
    modules, app = _fake_server()
    before = guard.take(modules)
    modules[guard.SERVER_MODULE].app = FastAPI()

    findings = guard.check_and_restore(before, modules)

    assert findings.app and "different FastAPI app" in findings.app[0]
    assert modules[guard.SERVER_MODULE].app is app


def test_a_new_real_module_is_allowed_and_kept():
    """Lazy imports and script loaders add real modules; removing one would
    split class identity for everything that already imported it."""
    modules, _ = _fake_server()
    before = guard.take(modules)
    loaded = _real_module("fetch_some_script")
    modules["fetch_some_script"] = loaded

    findings = guard.check_and_restore(before, modules)

    assert not findings
    assert modules["fetch_some_script"] is loaded


def test_a_new_stub_is_reported_and_removed():
    """A non-module, or a spec-less module shadowing an importable one."""
    modules, _ = _fake_server()
    before = guard.take(modules)
    modules["wave"] = types.ModuleType("wave")  # stdlib, importable from disk
    modules["mocked_dep"] = MagicMock()

    findings = guard.check_and_restore(before, modules)

    assert findings.stub_added == ["mocked_dep", "wave"]
    assert "wave" not in modules and "mocked_dep" not in modules


def test_spec_less_modules_a_c_extension_registers_are_not_stubs():
    """``pyexpat`` adds ``pyexpat.errors`` / ``pyexpat.model`` and Cython adds
    ``cython_runtime`` without specs the first time a test imports them."""
    import pyexpat

    modules, _ = _fake_server()
    before = guard.take(modules)
    modules["pyexpat"] = pyexpat
    modules["pyexpat.errors"] = pyexpat.errors
    modules["cython_runtime"] = types.ModuleType("cython_runtime")

    assert not guard.check_and_restore(before, modules)
    assert modules["pyexpat.errors"] is pyexpat.errors


def test_ignored_names_are_neither_reported_nor_restored():
    modules, _ = _fake_server()
    before = guard.take(modules)
    replacement = MagicMock()
    modules["colorsys"] = replacement

    findings = guard.check_and_restore(before, modules, ignore=frozenset({"colorsys"}))

    assert not findings
    assert modules["colorsys"] is replacement


def test_an_added_route_is_reported_and_the_table_restored_by_identity():
    modules, app = _fake_server()
    before = guard.take(modules)
    original = list(app.router.routes)
    app.openapi()

    @app.get("/leaked")
    def leaked() -> dict:
        return {}

    findings = guard.check_and_restore(before, modules)

    assert findings.app and "route table changed" in findings.app[0]
    assert list(app.router.routes) == original
    assert all(a is b for a, b in zip(app.router.routes, original))
    # The cached schema described the leaked route; it must be regenerated.
    assert app.openapi_schema is None
    assert "/leaked" not in app.openapi()["paths"]


def test_an_included_router_is_seen_although_it_has_no_path():
    """FastAPI 0.141 keeps an included router as one wrapper entry without
    ``.path`` (#1534); a path walk misses it, an identity compare does not."""
    modules, app = _fake_server()
    before = guard.take(modules)
    router = APIRouter()

    @router.get("/included")
    def included() -> dict:
        return {}

    app.include_router(router)

    findings = guard.check_and_restore(before, modules)

    assert findings.app
    assert len(app.router.routes) == len(before.app.routes)


def test_dependency_overrides_and_middleware_are_reported_and_restored():
    modules, app = _fake_server()

    def dep() -> int:
        return 1

    app.dependency_overrides[dep] = lambda: 2
    before = guard.take(modules)
    app.dependency_overrides.clear()
    app.dependency_overrides[dep] = lambda: 3
    app.add_middleware(GZipMiddleware)

    findings = guard.check_and_restore(before, modules)

    assert "dependency_overrides changed" in findings.app
    assert "user_middleware changed" in findings.app
    assert app.dependency_overrides[dep]() == 2
    assert app.user_middleware == before.app.user_middleware
    assert app.middleware_stack is None


def test_no_server_imported_means_no_app_check():
    modules = {"colorsys": _real_module("colorsys")}
    before = guard.take(modules)
    assert before.app is None
    modules[guard.SERVER_MODULE] = _real_module(guard.SERVER_MODULE)

    assert not guard.check_and_restore(before, modules)


def test_the_conftest_wires_the_guard_module_scoped_and_autouse():
    tree = ast.parse((REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_state_is_restored":
            (decorator,) = node.decorator_list
            keywords = {kw.arg: ast.literal_eval(kw.value) for kw in decorator.keywords}
            assert keywords == {"autouse": True, "scope": "module"}
            body = ast.unparse(node)
            assert "check_and_restore(before)" in body and "pytest.fail(" in body
            return
    raise AssertionError("tests/conftest.py no longer defines _process_state_is_restored")


def test_the_wired_fixture_fails_a_module_that_leaks(tmp_path):
    """End to end: the real conftest, loaded as a plugin, fails a leaking
    module at teardown and restores the entry before the next module runs."""
    (tmp_path / "test_a_leaks.py").write_text(
        textwrap.dedent(
            """
            import colorsys
            import sys

            def test_replaces_a_module():
                sys.modules["colorsys"] = object()
            """
        ),
        encoding="utf-8",
    )
    (tmp_path / "test_b_runs_after.py").write_text(
        textwrap.dedent(
            """
            import sys
            import types

            def test_sees_the_real_module_again():
                assert isinstance(sys.modules["colorsys"], types.ModuleType)
            """
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            "-p",
            "no:cacheprovider",
            "-q",
            "--rootdir",
            str(tmp_path),
            str(tmp_path / "test_a_leaks.py"),
            str(tmp_path / "test_b_runs_after.py"),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=600,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1, output
    assert "left process-wide state changed" in output, output
    assert "sys.modules entries replaced: colorsys" in output, output
    assert re.search(r"2 passed, 1 error", output), output


_LOCK = """\
fastapi==0.141.1 \\
    --hash=sha256:aaa
pydantic==2.13.5 \\
    --hash=sha256:bbb
starlette==1.7.0 \\
    --hash=sha256:ccc
"""


def test_the_lock_parser_reads_hashed_pins():
    assert guard.locked_versions(_LOCK) == {
        "fastapi": "0.141.1",
        "starlette": "1.7.0",
        "pydantic": "2.13.5",
    }


def test_web_stack_drift_names_every_mismatch_and_treats_unknown_as_drift():
    matching = {"fastapi": "0.141.1", "starlette": "1.7.0", "pydantic": "2.13.5"}
    assert guard.web_stack_drift(matching, _LOCK) == {}
    # The #1534 shape: a local FastAPI older than CI's.
    drifted = dict(matching, fastapi="0.135.4", pydantic=None)
    assert guard.web_stack_drift(drifted, _LOCK) == {
        "fastapi": ("0.135.4", "0.141.1"),
        "pydantic": (None, "2.13.5"),
    }
    # An unreadable lock proves nothing matches.
    assert set(guard.web_stack_drift(matching, "")) == set(guard.WEB_STACK)


def test_the_real_lock_pins_the_whole_web_stack():
    locked = guard.locked_versions(guard.CI_LOCK.read_text(encoding="utf-8"))
    assert all(locked.values()), locked


def test_the_pytest_header_reports_web_stack_drift():
    tree = ast.parse((REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"))
    hooks = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "pytest_report_header"
    ]
    assert hooks, "tests/conftest.py no longer reports web-stack drift in the header"
    assert "web_stack_drift()" in ast.unparse(hooks[0])
