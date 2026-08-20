"""Guards against accidental "fixes" that would undo deliberate v1 scope
decisions (C6-SIG-01).

Unlike ``test_reconciler.py`` / ``test_families.py`` / ``test_movement.py``
(which pin what the reconciler DOES), this file pins what it deliberately
does NOT do yet — the RED-first discipline applied to scope itself, the
same idea ``tests/api/test_signal_engine_parity.py`` already uses for the
terminal.py / signal-engine.js pair.
"""

from __future__ import annotations

from pathlib import Path

from src.api.terminal import _evaluate_signal
from src.signals.families import board_consensus_gap_family
from src.signals.reconciler import Stance, reconcile_row

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_reconciler_is_allowed_to_diverge_from_terminal_evaluate_signal():
    """A board-descended trend/technical read (terminal.py) and a
    retail-vs-consensus gap read (this reconciler) are DIFFERENT
    questions about the same player, and are deliberately not wired
    together in this unit -- see docs/lane4/C6_SIG_01_RECONCILER.md §"What
    a reconciliation unit has to decide".  If a future change makes them
    always agree without a decomposition unit actually landing, that is
    very likely accidental (the two are answering different questions on
    purpose) and this test is meant to make that change fail loudly
    rather than pass silently.

    Constructed scenario: sustained 7d/30d downtrend (terminal.py fires
    SELL) on a player whose retail market currently prices him ABOVE
    consensus by a material margin (this reconciler's board_consensus_gap
    family leans BUY -- "buy low from a retail-first partner" per
    _compute_market_gap's own docstring). Both readings are legitimate;
    they are not required to agree.
    """
    terminal_ctx = {
        "trend7": -6,
        "trend30": -4,
        "volatility": {"label": "normal", "mad": 1.0},
        "value": 5000,
        "rankChange": -6,
        "alertCount": 0,
        "negativeImpactCount": 0,
        "positiveImpactCount": 0,
    }
    terminal_result = _evaluate_signal(terminal_ctx)
    terminal_signals = {f["signal"] for f in terminal_result.get("fired") or []}
    assert "SELL" in terminal_signals or terminal_result.get("primary", {}).get("signal") == "SELL"

    gap_evidence = board_consensus_gap_family(
        {"marketGapDirection": "consensus_premium", "marketGapValueRatio": 0.25}
    )
    assert gap_evidence is not None
    reconciler_result = reconcile_row(families=[gap_evidence])

    # The point of this test: SELL (terminal) and a BUY-leaning verdict
    # (this reconciler) coexisting on the same player is EXPECTED, not a
    # bug -- assert the reconciler's verdict is BUY-side, deliberately
    # the opposite of terminal's SELL, so nobody mistakes silence here
    # for "we checked and they always agree."
    assert reconciler_result.verdict in (Stance.BUY, Stance.STRONG_BUY, Stance.STASH)


def test_unified_signal_engine_stays_deleted():
    """Structural guard against accidental resurrection of the module
    this unit retired for claiming sole BUY/SELL/HOLD ownership with
    zero production callers (docs/lane4/LANE4_SIGNAL_EMITTER_INVENTORY.md
    §2). If this file reappears, ONE CONCEPT ONE CANONICAL OWNER is
    violated again -- two modules both plausibly claiming the reconciler
    role."""
    assert not (REPO_ROOT / "src" / "news" / "unified_signal_engine.py").exists()
