"""Sleeper league-mate intelligence ("Sharp Tracker", Phase 5).

Crawls the pool of league members (the active league's managers) across
ALL of their other Sleeper leagues via the public, unauthenticated
Sleeper API, aggregates per-asset buy/sell activity over rolling
windows, and persists a snapshot the ``/api/intel/*`` endpoints serve.

Modules:
    crawler.py   — budgeted, resumable Sleeper crawl (leagues, rosters,
                   incremental transactions)
    aggregate.py — read-time per-asset window aggregation + trend score
    store.py     — atomic snapshot persistence under ``data/intel/``
    service.py   — crawl→merge→store orchestration with a process lock
"""

from __future__ import annotations
