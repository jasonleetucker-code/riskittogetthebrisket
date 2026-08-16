"""Canonical temporal history — ONE owner for as-of asset-value queries.

``src/history/`` is the C1-U4 canonical owner (`C1-HIST-01`/`-02`/`-03`).
It decides, for the whole platform:

* what an asset-history record IS (``store.py`` — immutable, append-only
  observations in ``data/temporal_ledger.sqlite``);
* how an asset is KEYED across time (``keys.py`` — players through the
  C1-U2 identity contract, picks through the C1-U3 market-pick
  namespace; the two namespaces cannot collide);
* what "as of T" MEANS (``asof.py`` — fidelity-labelled, never-future
  lookups with explicit missing reasons and the permanent
  pre-2026-07-14 coverage boundary);
* how history is INGESTED (``record.py`` for the live board,
  ``backfill.py`` for the retained archive, ``migrate.py`` for the
  legacy production stores).

Consumers may not independently interpret the raw stores
(``data/rank_history.jsonl``, ``data/source_value_history.jsonl``,
``data/board_history.sqlite``, ``exports/archive/``); those remain raw
evidence and recording continues where retention rows require it, but
every historical *decision* — snapshot selection, fidelity, missing
semantics, rankChange derivation — routes through this package.
"""

from __future__ import annotations
