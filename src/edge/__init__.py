"""Consensus Edge — the authoritative buy/sell evaluation.

Deliberately a separate package from ``src/intel`` (Insider Trading) and
``src/sharp`` (Sharp Tracker).  Those answer "who in my league wants this
player" and "what is the qualified cohort doing".  Consensus Edge answers a
third question — "is this asset mispriced, and does independent evidence
agree" — and it CONSUMES the other two rather than replacing them.

The package is built foundation-first and in this order, because each layer
is worthless without the one under it:

    history.py    reconstruct as-of source snapshots from git history, so a
                  model can be validated against the past instead of asserted
    panel.py      join those snapshots into an immutable as-of feature panel
                  with future-outcome labels
    components.py the individual, separately-visible scores
    score.py      the composite Consensus Edge Score + confidence + conflict

Nothing in this package may write a production weight that has not been
validated against the panel.  A provisional weight is allowed only while it
is labelled provisional and the model is in shadow mode.
"""

from __future__ import annotations
