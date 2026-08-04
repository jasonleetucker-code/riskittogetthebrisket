"""Every fetcher ``server.py`` calls in-scrape must accept ``argv``.

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
2. ``server.py`` passes a list literal to each — otherwise ``main``
   falls through to ``parse_args(None)``, which reads the *server's*
   ``sys.argv`` under uvicorn and exits on unrecognised flags.

Dropping the argument at the call site would satisfy (1) and silently
break (2), which is why both are asserted.
"""

from __future__ import annotations

import importlib
import inspect
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_PY = REPO_ROOT / "server.py"

# Module name -> the argv list server.py passes it.
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


@pytest.mark.parametrize("module_name", sorted(FETCHERS))
def test_server_passes_a_list_literal(module_name: str) -> None:
    """The call site must keep passing an explicit list.

    A future edit to ``main()`` alone cannot restore correctness if the
    caller stops passing argv, so the contract is pinned from both ends.
    """
    src = SERVER_PY.read_text(encoding="utf-8")
    # server.py imports these as `from scripts import X as _alias`.
    alias = re.search(
        rf"from scripts import {re.escape(module_name)} as (\w+)",
        src,
    )
    assert alias, f"server.py no longer imports scripts.{module_name}"
    call = re.search(rf"{re.escape(alias.group(1))}\.main\(\s*\[", src)
    assert call, (
        f"server.py calls {alias.group(1)}.main() without a list literal. "
        "Pass an explicit argv list so the fetcher does not parse the "
        "server's sys.argv."
    )
