"""Analyst intelligence — the claim schema and stance taxonomy.

This package is the **gating artifact** for podcast / YouTube / analyst
ingestion, and deliberately nothing more.  The owner's sequencing is that the
claim is defined before anything starts storing claims, because the questions
that matter — *is this dynasty?  did he say that or did we infer it?  is this
the same take as last week's?* — are not recoverable from a row that was
written without their answers.

What is here:

* ``stance``  the §4.16 vocabulary, and the structural guarantee that
  STASH cannot merge into conviction BUY.
* ``claim``   what one take IS: attribution, provenance, game type, side,
  conditions, thesis lineage, and the supersession/dedupe rules.

**Nothing consumes this yet, and that is the intended state**, not an
oversight.  Said plainly because this repo already carries
``src/news/unified_signal_engine.py``, which describes itself as "single
entry point for every BUY/SELL/HOLD decision" and is imported by nothing in
production — a module that claims to be wired is worse than one that says it
is not.

Not here, on purpose:

* **no ingestion** — no feed reader, no transcript fetch, no extraction;
* **no scoring or weighting** — how far a stance moves a recommendation is
  evidence-gated;
* **no freshness constants** — §4.19 makes decay take-type, event and season
  aware, which is a set of inputs rather than a number.  ``TakeType`` names
  the vocabulary a decay policy would key on and stops there;
* **no IDP Guru, and The Run stays paused** — both are explicit owner
  decisions to wait, and a schema is not a reason to revisit them.

Owner spec: ``docs/OWNER_FEATURE_SPEC_RECONCILIATION_2026-08-13.md`` §4.16,
§4.19, §4.20.  Tracked as **T-NEW-10** in
``docs/OWNER_REQUESTED_TODO_SPEC_INDEX.md``.  Full record:
``docs/analyst/CLAIM_SCHEMA.md``.
"""

from src.analyst.claim import (
    AnalystClaim,
    AssetSide,
    Condition,
    GameType,
    Provenance,
    SourceRef,
    TakeType,
    claim_from_label,
    dynasty_claims,
    independent_claims,
)
from src.analyst.stance import (
    ConvictionClass,
    Direction,
    SourceLabel,
    Stance,
    StanceTally,
    conviction_class,
    direction,
    is_speculative,
    requires_condition,
    stance_for_label,
    tally,
)

__all__ = [
    "AnalystClaim",
    "AssetSide",
    "Condition",
    "ConvictionClass",
    "Direction",
    "GameType",
    "Provenance",
    "SourceLabel",
    "SourceRef",
    "Stance",
    "StanceTally",
    "TakeType",
    "claim_from_label",
    "conviction_class",
    "direction",
    "dynasty_claims",
    "independent_claims",
    "is_speculative",
    "requires_condition",
    "stance_for_label",
    "tally",
]
