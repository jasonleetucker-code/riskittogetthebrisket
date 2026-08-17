"""Acquisition history, cost basis and pick lineage — ``C1-ACQ-01..03``.

WHAT THIS ANSWERS
─────────────────
Three questions the platform could not answer at all before this unit:

* **how did this manager come to own this asset, and what did it cost?**
  (``C1-ACQ-01`` — acquisition history / cost basis)
* **who was on this roster on some past date?** (``C1-ACQ-02`` —
  historical roster reconstruction, with fidelity labels)
* **what is the full chain of hands a draft pick has passed through?**
  (``C1-ACQ-03`` / CE-18 — pick lineage and trade trees)

WHY THIS IS A NEW PACKAGE AND NOT AN EXTENSION OF TWO EXISTING ONES
───────────────────────────────────────────────────────────────────
**Not ``src/retention/``.**  That package states its own governing rule
at ``src/retention/__init__.py``: *nothing there may be read by a
decision path*, because a value that fed back into the thing it records
would make every measurement taken from it circular.  A cost-basis
ledger that CE-18 trade trees read IS a decision path.  So retention
stays the raw evidence recorder — its read surface remains
count-only — and this package DERIVES from it, deterministically and
replayably.  The invariant survives verbatim rather than being quietly
widened.

**Not ``src/history/``.**  That owns as-of *market value* observations.
Its ``keys.py`` namespace deliberately excludes league picks (a league
pick is an owned asset; a market pick ref is a priced grade), and its
lanes are about what an asset was WORTH, not who held it.  Ownership
facts are a different quantity in a different privacy class.

**Not a fourth opinion about the same facts.**  Three durable stores
already hold overlapping slices of one Sleeper feed, and none of them
answers the questions above:

===========================================  ==========  =================================
store                                        own league  what it cannot do
===========================================  ==========  =================================
``data/retention/league_events.sqlite``      yes         no asset-level row; count-only reads
``data/intel/ledger.sqlite3``                **no**      members' OTHER leagues; generic pick keys
``data/faab/bid_history_*.json``             yes         waiver adds only; no transaction id
===========================================  ==========  =================================

Draft selections — including realized auction prices — are in none of
them.  This package is the only own-league, asset-grain, all-methods,
lineage-carrying record, and it CONSUMES the others rather than
re-fetching around them.

PRIVACY — READ BEFORE MOVING ANYTHING
─────────────────────────────────────
**PRIVATE**, the same class and the same posture as
``src/retention/league_events.py``: real managers, real rosters, real
trades in our own leagues.  Same directory so one env var redirects
both, separate file so "back this up" and "publish this" can never be
the same gesture by accident.  No ``/api/public/*`` surface may import
this package, and the database is never force-added to git.

SHAPE
─────
``events.py``    normalise raw transactions/draft picks → acquisition events
``store.py``     the three tables + their idempotence rules
``holdings.py``  replay events → holdings and pick lineage (pure derivation)
``basis.py``     cost basis, via ``value_known_before`` and never ``value_as_of``
``roster.py``    roster at a date, with fidelity labels
"""

from __future__ import annotations

from src.acquisition.events import (
    ACQUISITION_METHODS,
    DISPOSAL_METHODS,
    AcquisitionEvent,
    events_from_draft_picks,
    events_from_transaction,
)
from src.acquisition.holdings import derive_holdings, derive_pick_lineage
from src.acquisition.roster import roster_at
from src.acquisition.store import (
    DB_PATH,
    PRIVACY_CLASS,
    SCHEMA_VERSION,
    connect,
    coverage,
    write_events,
)

__all__ = [
    "ACQUISITION_METHODS",
    "DISPOSAL_METHODS",
    "AcquisitionEvent",
    "DB_PATH",
    "PRIVACY_CLASS",
    "SCHEMA_VERSION",
    "connect",
    "coverage",
    "derive_holdings",
    "derive_pick_lineage",
    "events_from_draft_picks",
    "events_from_transaction",
    "roster_at",
    "write_events",
]
