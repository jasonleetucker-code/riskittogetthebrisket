"""The arbitrage finder cannot score a package without its Value Adjustment.

Until 2026-08-18 this was true by accident of Python's import machinery:
``src/trade/__init__.py`` monkeypatched ``finder._score_trade`` and
``finder.TradeCandidate.to_dict`` at package-import time, and importing a
submodule imports its package first, so no import path could reach an
unpatched finder.

That guarantee had three problems.  Reading ``finder.py`` told you the finder
summed market values linearly, which it did not.  "Impossible because of how
imports work" is the kind of property a refactor removes silently — the finder
would go on returning trades, scored on a different basis.  And installing
twice wrapped the wrapper, adjusting the adjustment.

``finder._score_trade`` now calls
``finder_value_adjustment.score_with_value_adjustment`` directly.  These tests
pin the PROPERTY (the adjustment is applied, and shows up in the payload) plus
a structural guard that the patching mechanism has not come back.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from src.trade.finder import Asset, TradeCandidate, _score_trade, _score_trade_on_values
from src.trade.ktc_va import ktc_adjust_package

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _asset(name: str, model: int, market: int, position: str = "WR") -> Asset:
    return Asset(
        name=name,
        position=position,
        team="FA",
        model_value=model,
        market_value=market,
        source_count=6,
        market_rank=1,
        market_source="ktcSfTep",
    )


#: A 2-for-1 that clears every one of the scorer's gates AND fires a real
#: Value Adjustment.  Both halves matter: a package with no VA proves nothing
#: about whether the VA is applied, and a package the scorer rejects returns
#: ``None`` before the question is even asked.  The give side's MARKET total
#: must exceed the receive side's (the opponent must strictly win on the
#: retail board) while its MODEL total must not — that gap is the arbitrage
#: this engine exists to find, so model and market cannot be equal here.
def _two_for_one() -> tuple[list[Asset], list[Asset]]:
    give = [_asset("Give A", 3844, 5160), _asset("Give B", 2456, 3440)]
    receive = [_asset("Get", 6200, 6400, "RB")]
    return give, receive


def _one_for_one() -> tuple[list[Asset], list[Asset]]:
    return [_asset("Give", 5000, 6000)], [_asset("Get", 5200, 5400, "RB")]


def _run(snippet: str) -> str:
    """Run ``snippet`` in a FRESH interpreter.

    In-process the modules are already imported, so an in-process assertion
    would prove nothing about import order.
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


# ── The property ─────────────────────────────────────────────────────


def test_the_scorer_applies_the_package_adjustment():
    """A 2-for-1 must be scored on ADJUSTED totals, not on raw sums.

    The consolidation premium is what makes giving two pieces for one better
    player cost more than the arithmetic says, and it is the whole reason this
    module exists.  If the VA ever stops being applied, this is the assertion
    that notices — no import-order archaeology required.
    """
    give, receive = _two_for_one()
    expected = ktc_adjust_package([a.market_value for a in give], [a.market_value for a in receive])
    assert expected.displayed, "fixture chosen so KTC fires a VA — otherwise this proves nothing"

    scored = _score_trade(give, receive)
    unadjusted = _score_trade_on_values(give, receive)

    assert scored is not None
    assert unadjusted is not None
    assert scored.market_value_adjustment == expected.value
    assert scored.market_value_adjustment_side in {"give", "receive"}
    # The two scorers must DISAGREE.  If they agreed, the adjustment did
    # nothing and every assertion above would pass vacuously.
    assert scored.arbitrage_score != unadjusted.arbitrage_score


def test_the_adjustment_never_leaks_into_a_players_market_value():
    """The premium is side-level math applied to a clone, not to the asset."""
    give, receive = _two_for_one()
    original_give = [a.market_value for a in give]
    original_receive = [a.market_value for a in receive]
    scored = _score_trade(give, receive)
    assert scored is not None
    assert scored.market_value_adjustment > 0, "fixture must actually apply a premium"
    assert [a.market_value for a in scored.give] == original_give
    assert [a.market_value for a in scored.receive] == original_receive
    payload = scored.to_dict()
    assert [a["ktcValue"] for a in payload["give"]] == original_give


def test_the_payload_publishes_raw_and_adjusted_totals():
    give, receive = _two_for_one()
    payload = _score_trade(give, receive).to_dict()
    for key in (
        "rawGiveKtcTotal",
        "rawReceiveKtcTotal",
        "adjustedGiveKtcTotal",
        "adjustedReceiveKtcTotal",
        "marketValueAdjustment",
        "marketValueAdjustmentSide",
        "marketValueAdjustmentApplied",
    ):
        assert key in payload, f"{key} missing from the finder payload"
    assert payload["rawGiveKtcTotal"] == sum(a.market_value for a in give)
    assert payload["rawReceiveKtcTotal"] == sum(a.market_value for a in receive)
    assert payload["marketValueAdjustmentApplied"] is True


def test_a_one_for_one_is_scored_without_an_adjustment():
    """KTC suppresses VA on 1-v-1, so the finder must too."""
    give, receive = _one_for_one()
    scored = _score_trade(give, receive)
    assert scored is not None
    assert scored.market_value_adjustment == 0
    assert scored.market_value_adjustment_side is None
    assert scored.to_dict()["marketValueAdjustmentApplied"] is False


def test_every_import_path_reaches_the_adjusting_scorer():
    """No import order yields a finder that scores linearly."""
    for snippet in (
        "import src.trade.finder as f; print(f._score_trade.__module__)",
        "import importlib; print(importlib.import_module('src.trade.finder')._score_trade.__module__)",
        "from src.trade.finder import _score_trade; print(_score_trade.__module__)",
    ):
        assert _run(snippet) == "src.trade.finder"


# ── The structural guard ─────────────────────────────────────────────


def test_the_package_init_does_not_patch_anything():
    """``src/trade/__init__.py`` must stay inert.

    A package ``__init__`` that rebinds a sibling module's attributes is
    action at a distance, and this one is where that pattern lived.  Parsed
    rather than grepped, so a comment quoting the old code cannot trip it —
    the mistake that made two earlier guards in this repo decorative.
    """
    tree = ast.parse((_REPO_ROOT / "src" / "trade" / "__init__.py").read_text())
    executable = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
        )  # the module docstring
    ]
    assert executable == [], (
        "src/trade/__init__.py has executable statements again — it must not "
        f"install, patch or import for side effects (found {len(executable)})"
    )


def test_no_module_installs_a_patch_over_the_finder():
    """``install(finder)`` is retired; nothing may reintroduce it."""
    import src.trade.finder as finder
    import src.trade.finder_value_adjustment as fva

    assert not hasattr(fva, "install")
    assert not hasattr(finder, "_MARKET_VALUE_ADJUSTMENT_INSTALLED")
    # ``functools.wraps`` copies __name__ AND __module__, so neither
    # identifies a wrapper.  ``__wrapped__`` does.
    assert not hasattr(finder._score_trade, "__wrapped__")
    assert not hasattr(TradeCandidate.to_dict, "__wrapped__")
    assert finder._score_trade.__code__.co_filename.endswith("finder.py")
    assert TradeCandidate.to_dict.__code__.co_filename.endswith("finder.py")


@pytest.mark.parametrize("generator", ["_generate_1for1", "_generate_2for1", "_generate_1for2"])
def test_every_generator_routes_through_the_adjusting_scorer(generator):
    """Parsed, not grepped: each shape generator must call ``_score_trade``.

    A generator calling ``_score_trade_on_values`` directly would produce
    linearly-scored candidates that look identical in the payload.
    """
    source = (_REPO_ROOT / "src" / "trade" / "finder.py").read_text()
    tree = ast.parse(source)
    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == generator
    )
    called = {
        node.func.id
        for node in ast.walk(func)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_score_trade" in called
    assert "_score_trade_on_values" not in called
