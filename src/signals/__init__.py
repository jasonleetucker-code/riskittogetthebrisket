"""Central Buy/Sell reconciliation (C6-SIG-01).

One owner for the question "what do the platform's Buy/Sell emitters say
about this player, side by side, with every body of evidence counted
once?".  It is a DEDUP / LINEAGE reconciler, deliberately not a scorer:

* :mod:`src.signals.reconciler` — the pure synthesis owner.  Takes
  labelled observations from the existing emitters and publishes them per
  player, collapsing exact duplicates and same-lineage restatements,
  labelling conflicts, and keeping withheld precedence.  It contains no
  numeric blend, no cross-emitter weight and no new label vocabulary.
* :mod:`src.signals.collect` — adapters that read each emitter THROUGH ITS
  OWNER (terminal signal engine, BDVM market layer, Consensus Edge board,
  Sharp market board) and translate the owner's output into observations.
  No emitter's logic is re-derived here.

Record: ``docs/signals/C6_SIG_01_RECONCILER.md``.
"""

from __future__ import annotations
