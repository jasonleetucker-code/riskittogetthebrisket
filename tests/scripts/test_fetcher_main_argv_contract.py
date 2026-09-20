"""Every fetcher the delegated server source cycle calls must accept ``argv``.

``server.py``'s scrape path refreshes four sources by importing the
fetcher module and calling ``main([...])`` with an explicit argument
list.  Three of the four declared ``main(argv=None)``.  The fourth,
``fetch_idpshow``, declared bare ``main()`` — so the call raised
``TypeError: main() takes 0 positional arguments but 1 was given`` on
EVERY scrape.

That did not fail loudly.  ``server.py:2323`` wraps the call in
``except Exception`` and records a ``idpshow_fetch_exception`` WARNING,
so the in-scrape IDP Show refresh was dead in production while the only
symptom was one warning line in the journal.  It went unnoticed because
the standalone ``dynasty-idpshow-fetch.timer`` runs the same script as a
subprocess and kept the ``idpShow`` freshness stamp looking current —
the broken path and the working path fed the same file.

Observed live 2026-07-30 on the production journal.

Two properties are pinned here, because either one alone is
insufficient:

1. every fetcher's ``main`` accepts a positional ``argv`` — otherwise
   the call raises; and
2. the live ``src.serving.producer`` owner passes a list literal to each — otherwise ``main``
   falls through to ``parse_args(None)``, which reads the *server's*
   ``sys.argv`` under uvicorn and exits on unrecognised flags.

Dropping the argument at the call site would satisfy (1) and silently
break (2), which is why both are asserted.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PY = REPO_ROOT / "server.py"
PRODUCER_PY = REPO_ROOT / "src/serving/producer.py"

# Module name -> the explicit argv list the delegated source owner passes.
FETCHERS: dict[str, str] = {
    "fetch_dynasty_nerds": '["--mirror-data-dir"]',
    "fetch_fantasypros_offense": '["--mirror-data-dir"]',
    "fetch_fantasypros_idp": '["--mirror-data-dir"]',
    "fetch_idpshow": "[]",
}


@pytest.mark.parametrize("module_name", sorted(FETCHERS))
def test_main_accepts_argv(module_name: str) -> None:
    mod = importlib.import_module(f"scripts.{module_name}")
    main = getattr(mod, "main", None)
    assert main is not None, f"scripts/{module_name}.py has no main()"

    sig = inspect.signature(main)
    positional = [
        p
        for p in sig.parameters.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.VAR_POSITIONAL)
    ]
    assert positional, (
        f"scripts/{module_name}.py::main{sig} accepts no positional argument, "
        f"but server.py calls it as main({FETCHERS[module_name]}). That raises "
        "TypeError, which server.py catches and downgrades to a warning — so "
        "the fetch silently stops running. Use main(argv: list[str] | None = None) "
        "and pass argv to parse_args()."
    )


@pytest.mark.parametrize("module_name", sorted(FETCHERS))
def test_argv_is_threaded_into_parse_args(module_name: str) -> None:
    """``parse_args()`` with no argument reads ``sys.argv`` — wrong here.

    Under uvicorn that is the server's own argv, so argparse would exit
    on flags meant for the server rather than the fetcher.
    """
    src = (REPO_ROOT / "scripts" / f"{module_name}.py").read_text(encoding="utf-8")
    bare = re.search(r"parse_args\(\s*\)", src)
    assert bare is None, (
        f"scripts/{module_name}.py calls parse_args() with no argument. "
        "It must be parse_args(argv) so an in-process caller controls the "
        "arguments instead of inheriting the server's sys.argv."
    )


def test_server_delegates_to_the_source_owner() -> None:
    tree = ast.parse(SERVER_PY.read_text(encoding="utf-8"))
    entry = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_scraper"
    )
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "src.serving.producer"
        and any(alias.name == "run_source_cycle" for alias in node.names)
        for node in ast.walk(entry)
    )
    assert any(
        isinstance(node, ast.Await)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "run_source_cycle"
        for node in ast.walk(entry)
    )


@pytest.mark.parametrize("module_name", sorted(FETCHERS))
def test_source_owner_passes_the_expected_list_literal(module_name: str) -> None:
    """Pin the live delegated caller, retaining explicit arguments and mirror policy."""
    tree = ast.parse(PRODUCER_PY.read_text(encoding="utf-8"))
    owner = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_supplemental_sources"
    )
    aliases = [
        alias.asname or alias.name
        for node in ast.walk(owner)
        if isinstance(node, ast.ImportFrom) and node.module == "scripts"
        for alias in node.names
        if alias.name == module_name
    ]
    assert len(aliases) == 1, f"Source owner must import scripts.{module_name}"
    calls = [
        node
        for node in ast.walk(owner)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "main"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == aliases[0]
    ]
    assert len(calls) == 1, f"Source owner must invoke {module_name}.main exactly once"
    call = calls[0]
    assert len(call.args) == 1 and isinstance(
        call.args[0], ast.List
    ), "Explicit argv list required; never inherit server sys.argv"
    assert ast.literal_eval(call.args[0]) == ast.literal_eval(FETCHERS[module_name])
    assert not call.keywords
