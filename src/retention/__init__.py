"""Retention — the evidence that is destroyed unless something records it.

This package exists for the C1A tranche ``C1-RET-01``…``C1-RET-08``
(``docs/C_SERIES_SCOPE_MANIFEST.md``), whose defining property is that
deferring the work does not postpone it — it *loses* it.  Every day a
rolling window turns over, an overwrite lands, or a timer silently does
not run is a day of evidence no later effort can reconstruct.

**Nothing here may be read by a decision path.**  These stores record
what the platform observed; a value that fed back into the thing it
records would make every measurement taken from it circular.  Same rule
``src/snapshots/board_store.py`` states for the board history, for the
same reason, and it is why this package exposes no valuation surface.

Two stores, split on the B8 public/private boundary rather than on
convenience:

* ``evidence_store`` — ``data/retention/evidence.sqlite``.  League
  scoring cards and Sleeper trending counts.  INTERNAL: not public,
  not committed, but not user-identifying either.
* ``league_events`` — ``data/retention/league_events.sqlite``.  Our own
  leagues' transactions.  PRIVATE: real managers, real rosters, real
  trades.  A separate database file so that "back this up" and
  "publish this" can never be the same gesture by accident.

Both live under ``data/``, which is gitignored, and both are covered by
``deploy/backup/riskit-state-backup.sh``.  Durable does not mean
committed: neither store may be force-added into public Git history.

The full operational record for every retained artifact — primary
store, backup, write owner, read owner, retention, privacy class,
restore/replay method and health signal — is
``docs/retention/RETENTION_REGISTER.md``.
"""

from src.retention.evidence_store import (
    ACCEPT_ANY,
    ACCEPT_BRACKETED,
    ACCEPT_EXACT,
    observe_scoring_card,
    observe_trending_snapshot,
    scoring_card_at,
    scoring_card_observations,
    scoring_card_windows,
    trending_series,
)
from src.retention.league_events import record_transactions, transaction_coverage

__all__ = [
    "ACCEPT_ANY",
    "ACCEPT_BRACKETED",
    "ACCEPT_EXACT",
    "observe_scoring_card",
    "observe_trending_snapshot",
    "record_transactions",
    "scoring_card_at",
    "scoring_card_observations",
    "scoring_card_windows",
    "transaction_coverage",
    "trending_series",
]
