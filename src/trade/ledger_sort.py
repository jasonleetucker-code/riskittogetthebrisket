"""Time-ordering for ledger-derived rows, without fabricating a missing
timestamp.

Every ledger materializer under this package (``waiver_ledger``,
``market_trade_ledger``, ``comparable_trades``) needs to sort rows that
may or may not carry a known ``occurredAtMs``. The obvious idiom —
``occurred_at_ms or 0`` as a sort-key fallback — is exactly the
"missing resolves to a fabricated number" anti-pattern
``scripts/check_decision_coercions.py`` exists to block: a timestamp
nobody recorded is not the Unix epoch.

Both key functions below never invent a magnitude for the missing case.
Python tuple comparison is lexicographic and evaluates left to right,
stopping at the first element where two keys differ (found via ``==``);
element 1 here (``is not None`` / ``is None``) partitions every row into
an absolute "known" vs "unknown" group, so element 2 is only ever
compared between two rows already in the SAME group — within the known
group it is always a real integer (or its negation, for descending
order: negating a real, known value is a legitimate transform for sort
direction, not fabrication), and within the unknown group it is
``None`` for every row, so the comparison resolves via equality and
falls through to the tiebreaker without ever evaluating ``None <`` an
int or inventing a timestamp. Missing therefore stays missing all the
way through the sort, not merely in the published row.
"""

from __future__ import annotations

from typing import Any


def oldest_first_key(occurred_at_ms: int | None, tiebreak: Any) -> tuple:
    """Undated rows lead, mirroring ``acquisition.store.read_events``'s
    own convention (they cannot be ordered against dated ones, so the
    conservative reading treats them as the earliest baseline); dated
    rows follow, oldest first. ``tiebreak`` breaks ties within either
    group (typically ``sourceRef``)."""
    return (occurred_at_ms is not None, occurred_at_ms, tiebreak)


def newest_first_key(occurred_at_ms: int | None) -> tuple:
    """Dated rows lead, newest first; undated rows trail — recency is
    what makes a market-ledger row useful to read first."""
    return (
        occurred_at_ms is None,
        -occurred_at_ms if occurred_at_ms is not None else None,
    )
