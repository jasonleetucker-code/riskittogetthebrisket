"""Hierarchical trade decision engine v3 -- a SHADOW challenger.

Pure library in batch 1: nothing in production imports it (pinned by
``tests/trade/decision_engine/test_isolation.py``).  The served top-line
decision remains ``src/trade/trade_decision.decide``.  Entry points:
:func:`src.trade.decision_engine.engine.evaluate_team` and
:func:`src.trade.decision_engine.engine.evaluate_two_sided`.
"""

from __future__ import annotations
