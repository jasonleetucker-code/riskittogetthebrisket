"""Central Buy/Sell Reconciler (C6-SIG-01) and market-ticker movement (C6-SIG-02).

WHAT THIS OWNS
───────────────
The one place a BUY/SELL/HOLD-class verdict is decided by reconciling
multiple, independently-declared evidence families into a single labelled
output. ``src.signals.reconciler.reconcile_row`` is the entry point.

WHAT THIS REPLACES
───────────────────
``src/news/unified_signal_engine.py`` claimed this role in its own
docstring ("single entry point for every BUY/SELL/HOLD decision emitted
to users") but had zero production callers -- confirmed by grep against
the full import graph before this package was written. It is deleted,
not repaired in place: its confidence model was a single un-externalized
float, predating this codebase's now-canonical axis-based,
``derivedFrom``-documented threshold discipline (``src.api.confidence``).
Its one genuinely reusable idea -- "families that agree collapse to one
composite with bumped confidence; families that disagree stay separate
rather than being averaged into a false neutral" -- is re-implemented
here to that current standard, not ported.

WHAT THIS DOES NOT REPLACE
────────────────────────────
Sixteen other Buy/Sell-style emitters exist in this codebase (catalogued
in ``docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md``). This package wires
exactly three of them as independent evidence FAMILIES (not verdicts to
average): ``board_consensus_gap`` (the existing market-gap stamp on
``/api/data``), ``bdvm_fundamental`` (``src.bdvm.market.buy_hold_sell``),
and ``sharp_transaction`` (``src.sharp.market.market_payload``, read-only
-- nothing here writes to ``src/sharp/``). A fourth slot,
``consensus_edge_composite``, is reserved in the vocabulary and
precedence chain but never fires in v1: Consensus Edge stays flag-off
because its own pre-registered backtest gate failed (ADR-023), and
re-enabling it is not this package's decision to make.

Every other emitter -- the frontend rank-trend rule engine
(``signal-engine.js``) and its Python twin (``terminal.py::_evaluate_signal``),
the arbitrage finder, roster-aware trade suggestions, custom alerts --
keeps running unchanged and unreconciled. Migrating them is out of scope
for this unit; see ``docs/cseries-delivery/CLAUDE_12.md`` for what
follows.

ONE CONCEPT, ONE CANONICAL OWNER
──────────────────────────────────
This package decides SIGNAL confidence (how good is the evidence behind
a BUY/SELL/HOLD verdict). ``src.api.confidence`` decides VALUE confidence
(how good is the evidence behind ``rankDerivedValue``). The two are
deliberately separate canonical owners for deliberately separate
questions, mirroring the same shape (family-head discipline, bottleneck
axes, externalized thresholds) without importing or modifying each
other.
"""

from __future__ import annotations

from src.signals.families import (
    bdvm_fundamental_family,
    board_consensus_gap_family,
    sharp_transaction_family,
)
from src.signals.movement import stamp_movement_windows
from src.signals.reconciler import (
    KNOWN_FAMILIES,
    Direction,
    ReconciledVerdict,
    SignalFamilyEvidence,
    Stance,
    Verdict,
    reconcile_row,
)

__all__ = [
    "KNOWN_FAMILIES",
    "Direction",
    "ReconciledVerdict",
    "SignalFamilyEvidence",
    "Stance",
    "Verdict",
    "bdvm_fundamental_family",
    "board_consensus_gap_family",
    "reconcile_row",
    "sharp_transaction_family",
    "stamp_movement_windows",
]
