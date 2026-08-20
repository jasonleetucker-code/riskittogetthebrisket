"""Trade-engine package.

This module used to MONKEYPATCH the arbitrage finder at import time —
``finder_value_adjustment.install(finder)`` rebound ``finder._score_trade`` and
``finder.TradeCandidate.to_dict`` so every caller got KTC's package Value
Adjustment.  It is gone: ``src/trade/finder.py`` calls those helpers directly,
so the behaviour is visible in the file that has it and cannot be lost by a
refactor that changes import order.  See ``finder_value_adjustment`` for the
full reasoning and ``tests/trade/test_finder_va_is_not_bypassable.py`` for the
guard.

Deliberately empty otherwise.  A package ``__init__`` that changes a sibling
module's behaviour is action at a distance, and this one is where that pattern
lived.
"""
