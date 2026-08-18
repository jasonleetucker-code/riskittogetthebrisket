"""The arbitrage finder cannot be imported without its Value Adjustment.

``src/trade/__init__.py`` rebinds ``finder._score_trade`` and
``finder.TradeCandidate.to_dict`` at package-import time
(``finder_value_adjustment.install``).  A monkeypatch is a fragile way
to own behaviour: if any consumer could reach the module without
triggering the package ``__init__``, it would silently score trades on
linear market sums while the trade page shows KTC's package adjustment —
the same class of split as defect #800.

Python's import machinery makes that impossible (importing a submodule
imports its package first), but "impossible today because of how imports
work" is exactly the kind of guarantee that gets removed by a refactor
nobody thought was risky.  These tests state it.

Retiring the monkeypatch in favour of an explicit call inside
``finder.find_trades`` is a larger change than the #800 repair should
carry; it is recorded as follow-up work, and until then this is the
guard.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _run(snippet: str) -> str:
    """Run ``snippet`` in a FRESH interpreter.

    In-process the modules are already imported and patched, so an
    in-process assertion would prove nothing about import order.
    """

    proc = subprocess.run(
        [sys.executable, "-c", snippet],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_importing_the_submodule_directly_still_installs_the_adjustment():
    out = _run(
        "import src.trade.finder as f;"
        "print(getattr(f, '_MARKET_VALUE_ADJUSTMENT_INSTALLED', False))"
    )
    assert out == "True"


def test_importlib_import_module_also_installs_it():
    out = _run(
        "import importlib;"
        "f = importlib.import_module('src.trade.finder');"
        "print(getattr(f, '_MARKET_VALUE_ADJUSTMENT_INSTALLED', False))"
    )
    assert out == "True"


def test_from_import_of_the_scorer_gets_the_patched_one():
    """``from src.trade.finder import _score_trade`` must bind the wrapper."""

    out = _run(
        "from src.trade.finder import _score_trade;"
        "print(hasattr(_score_trade, '__wrapped__'),"
        "      _score_trade.__code__.co_filename.endswith('finder_value_adjustment.py'))"
    )
    # ``functools.wraps`` copies __name__ AND __module__ from the
    # original, so neither identifies the wrapper.  ``__wrapped__`` and
    # the code object's defining file do.
    assert out == "True True"


def test_installing_twice_is_a_no_op():
    """Double-install would wrap the wrapper and adjust the adjustment."""

    out = _run(
        "import src.trade.finder as f;"
        "from src.trade.finder_value_adjustment import install;"
        "before = f._score_trade;"
        "install(f);"
        "print(before is f._score_trade)"
    )
    assert out == "True"
