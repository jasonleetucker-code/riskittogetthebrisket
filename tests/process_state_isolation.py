"""Process-wide state a test MODULE must leave as it found it (R-TEST-ISOLATION).

Owner TODO (P3, 2026-09-30, ``docs/OWNER_REQUESTED_TODO.md`` "Test
isolation"): identify any test or fixture that mutates the shared
``server.app``, its route table, or ``sys.modules`` without restoring it.  The
completion row (``docs/completion/families/family_E.json`` R-TEST-ISOLATION)
names the guard: assert ``app.routes`` / ``sys.modules`` are unchanged after
each test module.  ``docs/python-coverage-audit.md`` D-5 is the leak that
motivated it — a registry left behind by one file turned another file's
expected 404 into a 503 whenever the two shared a process.

What is checked, per test module (``tests/conftest.py`` wraps every module):

* ``sys.modules`` — an entry that existed when the module started must still
  be the SAME object when it ends.  Replacing it (``sys.modules["x"] = fake``)
  or removing it (``del sys.modules["server"]`` and re-importing) hands every
  later module a different object from the one already-imported code holds:
  a second ``server`` with a second ``app``, a second registry, a second set
  of module globals.  NEW entries are allowed — lazy imports and the script
  loaders (``importlib.util.module_from_spec`` + ``sys.modules[name] = m``)
  add them legitimately, and deleting a real module would split class
  identity for everything that already imported it.  The exception is a new
  entry that is a stub — not a module at all, or a spec-less module that
  shadows one importable from disk — because it would answer a later
  ``import`` in an unrelated module.  (Spec-less modules that C extensions
  register for themselves, such as ``pyexpat.errors``, are not stubs.)
  A restored submodule is rebound on its parent package too, because a
  re-import rebinds ``pkg.sub`` and ``from pkg import sub`` reads that first.
* ``server.app`` — when ``server`` was imported at the start of the module,
  ``server.app`` must still be the same object (``importlib.reload(server)``
  keeps the module and rebuilds the app), and that app's route table (the
  route OBJECTS, in order), its
  ``dependency_overrides`` and its ``user_middleware`` must be unchanged at
  the end.  The comparison is over ``app.router.routes`` objects, never over
  ``.path``: FastAPI 0.141 keeps an included router as one ``_IncludedRouter``
  entry with no ``.path``, which is the trap #1534 fell into.

A violation is RESTORED first and then reported, the same posture as
``_public_league_process_state`` in ``tests/conftest.py``: the leak stops at
the module boundary whether or not anyone reads the failure.

The same owner TODO asks for a guard against local environments drifting
from CI's pinned FastAPI (#1534 was a 0.135-vs-0.141 difference only CI could
see).  ``web_stack_drift`` answers it and ``tests/conftest.py`` prints the
answer in the pytest header.  It warns rather than fails: CI installs the lock
with hashes, so a failing assertion could only ever fire on a developer's or
agent's machine, where it would block an unrelated local run on an
environment problem instead of naming it.
"""

from __future__ import annotations

import importlib.machinery
import re
import sys
import types
from dataclasses import dataclass, field
from importlib import metadata
from pathlib import Path
from typing import Any

#: The module whose ``app`` is the process-wide FastAPI application.
SERVER_MODULE = "server"

#: The web stack whose behaviour #1534 showed to differ across versions.
WEB_STACK = ("fastapi", "starlette", "pydantic")
CI_LOCK = Path(__file__).resolve().parents[1] / "requirements-dev.lock.txt"


@dataclass
class AppState:
    """What a test module may not leave changed on ``server.app``."""

    app: Any
    routes: list[Any]
    dependency_overrides: dict[Any, Any]
    user_middleware: list[Any]


@dataclass
class Snapshot:
    modules: dict[str, Any]
    app: AppState | None


@dataclass
class Findings:
    replaced: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    stub_added: list[str] = field(default_factory=list)
    app: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.replaced or self.removed or self.stub_added or self.app)

    def lines(self) -> list[str]:
        out: list[str] = []
        if self.replaced:
            out.append("sys.modules entries replaced: " + ", ".join(self.replaced))
        if self.removed:
            out.append("sys.modules entries removed: " + ", ".join(self.removed))
        if self.stub_added:
            out.append(
                "sys.modules stubs (no import spec) left behind: " + ", ".join(self.stub_added)
            )
        out.extend(f"server.app {item}" for item in self.app)
        return out


def _app_state(modules: dict[str, Any]) -> AppState | None:
    server = modules.get(SERVER_MODULE)
    app = getattr(server, "app", None) if server is not None else None
    router = getattr(app, "router", None)
    if app is None or router is None:
        return None
    return AppState(
        app=app,
        routes=list(router.routes),
        dependency_overrides=dict(getattr(app, "dependency_overrides", {}) or {}),
        user_middleware=list(getattr(app, "user_middleware", []) or []),
    )


def take(modules: dict[str, Any] | None = None) -> Snapshot:
    """Snapshot ``sys.modules`` (by object identity) and ``server.app``."""
    current = dict(sys.modules if modules is None else modules)
    return Snapshot(modules=current, app=_app_state(current))


def _is_stub(name: str, value: Any, live: dict[str, Any]) -> bool:
    """A new ``sys.modules`` entry that would answer a later ``import`` falsely.

    Anything that is not a module at all (a ``MagicMock``, ``object()``) is a
    stub.  A real-looking module with no import spec is a stub only when it
    SHADOWS something importable from disk: C extensions legitimately
    register spec-less modules (``pyexpat.errors``, ``cython_runtime``) the
    first time a test imports them, and those must not read as leaks.
    """
    if not isinstance(value, types.ModuleType):
        return True
    if getattr(value, "__spec__", None) is not None:
        return False
    parent_name, _, child = name.rpartition(".")
    search_path = None
    if parent_name:
        search_path = getattr(live.get(parent_name), "__path__", None)
        if search_path is None:
            return False
    try:
        return importlib.machinery.PathFinder.find_spec(child or name, search_path) is not None
    except (ImportError, ValueError, OSError):
        return False


def check_and_restore(
    before: Snapshot,
    modules: dict[str, Any] | None = None,
    *,
    ignore: frozenset[str] = frozenset(),
) -> Findings:
    """Compare the live state with ``before``, put ``before`` back, report.

    ``modules`` defaults to ``sys.modules`` and is mutated in place.  Names in
    ``ignore`` are neither reported nor restored.
    """
    live = sys.modules if modules is None else modules
    findings = Findings()

    restored: list[tuple[str, Any, Any]] = []
    for name, original in before.modules.items():
        if name in ignore:
            continue
        if name not in live:
            findings.removed.append(name)
            restored.append((name, original, None))
            live[name] = original
        elif live[name] is not original:
            findings.replaced.append(name)
            restored.append((name, original, live[name]))
            live[name] = original
    # A re-import also rebinds the submodule on its parent package, and
    # ``from pkg import sub`` reads that attribute first: restoring only
    # ``sys.modules`` would leave ``pkg.sub`` pointing at the second copy.
    for name, original, replacement in restored:
        parent_name, _, child = name.rpartition(".")
        parent = live.get(parent_name) if parent_name else None
        if parent is None:
            continue
        current = getattr(parent, child, None)
        if current is not original and (current is replacement or replacement is None):
            try:
                setattr(parent, child, original)
            except (AttributeError, TypeError):
                pass
    for name in [n for n in live if n not in before.modules and n not in ignore]:
        if _is_stub(name, live[name], live):
            findings.stub_added.append(name)
            del live[name]

    state = before.app
    if state is not None:
        app = state.app
        server = live.get(SERVER_MODULE)
        if server is not None and getattr(server, "app", None) is not app:
            # ``importlib.reload(server)`` keeps the module object and
            # rebuilds every global, so only the ``app`` identity shows it.
            findings.app.append("object replaced (server.app is a different FastAPI app)")
            server.app = app
        routes = app.router.routes
        if list(routes) != state.routes:
            findings.app.append(
                f"route table changed ({len(state.routes)} -> {len(routes)} entries)"
            )
            routes[:] = state.routes
            # A cached schema describes the routes it was generated from.
            app.openapi_schema = None
        overrides = app.dependency_overrides
        if dict(overrides) != state.dependency_overrides:
            findings.app.append("dependency_overrides changed")
            overrides.clear()
            overrides.update(state.dependency_overrides)
        middleware = app.user_middleware
        if list(middleware) != state.user_middleware:
            findings.app.append("user_middleware changed")
            middleware[:] = state.user_middleware
            # Starlette rebuilds the stack from ``user_middleware`` when unset.
            app.middleware_stack = None

    findings.replaced.sort()
    findings.removed.sort()
    findings.stub_added.sort()
    return findings


def locked_versions(lock_text: str, packages: tuple[str, ...] = WEB_STACK) -> dict[str, str | None]:
    """``{package: pinned version}`` from a ``pip-compile --generate-hashes`` lock."""
    out: dict[str, str | None] = {}
    for package in packages:
        match = re.search(rf"^{re.escape(package)}==([^\s\\]+)", lock_text, re.MULTILINE)
        out[package] = match.group(1) if match else None
    return out


def web_stack_drift(
    installed: dict[str, str | None] | None = None,
    lock_text: str | None = None,
) -> dict[str, tuple[str | None, str | None]]:
    """``{package: (installed, locked)}`` for every web-stack package that differs.

    An unreadable lock or an uninstalled package is drift too (``None`` on
    that side): unknown is not "matches".
    """
    if lock_text is None:
        try:
            lock_text = CI_LOCK.read_text(encoding="utf-8")
        except OSError:
            lock_text = ""
    locked = locked_versions(lock_text)
    if installed is None:
        installed = {}
        for package in WEB_STACK:
            try:
                installed[package] = metadata.version(package)
            except metadata.PackageNotFoundError:
                installed[package] = None
    return {
        package: (installed.get(package), locked[package])
        for package in WEB_STACK
        if installed.get(package) is None or installed.get(package) != locked[package]
    }
