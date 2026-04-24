#!/usr/bin/env python3
"""Preflight environment check.

Fails loud when the Python environment is missing a dependency the
runtime or test suite needs.  Run before ``pytest`` (CI + local) so a
missing dep surfaces as a clear actionable error instead of a cryptic
``ModuleNotFoundError`` mid-test.

Usage:

    python scripts/check_env.py              # runtime + dev deps
    python scripts/check_env.py --runtime    # runtime only

Exit codes:
    0  — all imports succeeded
    1  — at least one import failed (see stderr)
"""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Iterable


# Third-party modules the server + scrapers import unconditionally
# (or inside functions that must succeed in production).  Listed as
# import names, not distribution names, so ``beautifulsoup4`` appears
# as ``bs4`` and ``curl_cffi`` keeps its underscore.
RUNTIME_MODULES: tuple[str, ...] = (
    "fastapi",
    "fastapi.testclient",  # importable even without httpx
    "uvicorn",
    "requests",
    "playwright.async_api",
    "openpyxl",
    "curl_cffi",
    "bs4",
    # ``anthropic`` is optional at runtime (server.py wraps the import
    # in try/except) but production should still have it installed
    # so the chat endpoint is not silently disabled.
    "anthropic",
)

# Extra modules only the test suite needs.  ``fastapi.testclient.TestClient``
# requires ``httpx`` at *call* time (not import time), so the test env
# must have httpx even though ``import fastapi.testclient`` works without it.
DEV_MODULES: tuple[str, ...] = (
    "pytest",
    "httpx",
)


def _try_import(module: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module)
    except Exception as exc:  # noqa: BLE001 — surface every failure mode
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def _check(modules: Iterable[str], label: str) -> list[str]:
    failures: list[str] = []
    print(f"[check_env] {label}:")
    for mod in modules:
        ok, err = _try_import(mod)
        if ok:
            print(f"  OK   {mod}")
        else:
            print(f"  FAIL {mod}  ({err})", file=sys.stderr)
            failures.append(mod)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        action="store_true",
        help="Only check runtime modules (skip test-only modules).",
    )
    args = parser.parse_args()

    print(f"[check_env] python={sys.version.split()[0]} executable={sys.executable}")

    failures = _check(RUNTIME_MODULES, "runtime modules")
    if not args.runtime:
        failures += _check(DEV_MODULES, "dev / test modules")

    if failures:
        print(
            "\n[check_env] Missing modules: "
            + ", ".join(failures)
            + "\n[check_env] Run `make setup` (or `scripts/setup.sh`) to install"
            " every declared dep, then re-run this check.",
            file=sys.stderr,
        )
        return 1

    print("[check_env] All required modules importable.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
