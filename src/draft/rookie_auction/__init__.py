"""Rookie-auction pick valuation — the draft-valuation automation workstream.

``curve``
    The owner-approved ``Draft Data`` spreadsheet formula, reproduced exactly
    (Batch A).  Pure; turns 72 rookie-value inputs plus three completed-class
    dollar curves into 72 pick dollars summing to the class's $1,200 pool.
``snapshots``
    Immutable, checksummed inputs: the frozen owner-approved provisional
    rookie values and the completed-class historical curves the spine is
    built from (Batch B/C).

Each rookie draft class is its own independent $1,200 pool (owner decision
2026-10-18).  Package Value Adjustment never applies to these dollars.  Plan
and status: ``docs/draft/DRAFT_VALUATION_WORKSTREAM.md``.
"""
