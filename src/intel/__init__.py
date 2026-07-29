"""Sleeper league-mate intelligence — the INSIDER TRADING product.

Crawls the pool of league members (the active league's managers) across
ALL of their other Sleeper leagues via the public, unauthenticated
Sleeper API, and serves league-scoped trade leads at
``/league/insider-trading`` via the ``/api/intel/*`` endpoints.

**This is not Sharp Tracker.**  This package used to say it was, and
that was the single largest defect in the feature: the cohort here is
"every manager in your league", with no skill filter of any kind, while
Sharp Tracker means a *qualified* cohort of proven managers drawn from
every league we observe.  One product was shipped under both names, so
neither existed.  Sharp Tracker now lives in ``src/sharp/`` and is
deliberately NOT league-scoped.  See ``docs/intel/AUDIT.md``.

The two products share the ingestion layer below and nothing above it.

Modules:
    crawler.py       — budgeted, resumable Sleeper crawl (leagues,
                       rosters, incremental transactions)
    league_filter.py — dynasty/keeper admission (redraft and best-ball
                       trade behaviour inverts a dynasty signal)
    ledger.py        — normalized SQLite store: transactions, asset
                       movements, users, leagues.  SHARED with Sharp
                       Tracker; owns history and all window queries
    signals.py       — window-safe metrics (volume, breadth, velocity,
                       confidence).  SHARED.  Replaced ``trend_score``
    ingest.py        — snapshot → ledger bridge + migration
    aggregate.py     — legacy read-time aggregation (being retired in
                       favour of ledger queries)
    store.py         — atomic snapshot persistence under ``data/intel/``
    service.py       — crawl→merge→store orchestration with a lock
"""

from __future__ import annotations
