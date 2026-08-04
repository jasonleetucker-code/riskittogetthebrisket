"""Who is in this rookie auction.

One definition, two consumers.  ``server._our_rookie_pool`` shapes these rows
into the ``/api/draft-capital`` payload; ``src/draft/context.py`` needs the same
set for the opposite reason — to EXCLUDE it from the free-agent pool.

Why that exclusion matters, measured on the 2026-08-04 board: of the 145
players the league leaves unrostered, **7 are in the top-72 rookie auction, and
5 of them occupy the top five free-agent slots**.  Without this the model told
you not to pay for a rookie tight end because Marlin Klein was available for
free — while Marlin Klein was himself lot number one.  A player you have to bid
for is not the free alternative to bidding.

Undrafted rookies do become genuine free agents once the auction ends.  During
the auction they are not, and every question this module serves is a
during-the-auction question.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

__all__ = [
    "DEFAULT_POOL_SIZE",
    "auction_rookie_keys",
    "select_rookie_rows",
]

#: Matches ``server._KTC_TOTAL_PICKS`` — the number of slots in this league's
#: rookie draft, and therefore the size of the board /draft renders.
DEFAULT_POOL_SIZE = 72

#: Every field a contract row can be identified by, mirroring
#: ``board_values_from_contract`` and ``waiver_values_by_position``.
_KEY_FIELDS = ("playerId", "legacyRef", "canonicalName", "displayName")


def _row_value(row: Mapping[str, Any]) -> float | None:
    """``rankDerivedValue``, falling back to ``values.overall``.

    The fallback matches ``_our_rookie_pool`` exactly; the two must agree on
    which rows qualify or the exclusion set would not cover the board.
    """
    val = row.get("rankDerivedValue")
    if val is None:
        vals = row.get("values")
        val = vals.get("overall") if isinstance(vals, Mapping) else None
    if not isinstance(val, (int, float)):
        return None
    return float(val) if float(val) > 0 else None


def select_rookie_rows(
    contract: Mapping[str, Any] | None,
    top_n: int = DEFAULT_POOL_SIZE,
) -> list[Mapping[str, Any]]:
    """The auction board: top-N rookie rows by value, highest first.

    Filters to ``rookie`` rows that carry a Sleeper ``playerId``, which is what
    drops college / undrafted entries a ranking source lists but no league can
    roster.
    """
    if not isinstance(contract, Mapping):
        return []
    rows = contract.get("playersArray")
    if not isinstance(rows, list):
        return []

    scored: list[tuple[float, Mapping[str, Any]]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        if not row.get("rookie") or not row.get("playerId"):
            continue
        value = _row_value(row)
        if value is None:
            continue
        if not str(row.get("canonicalName") or row.get("displayName") or "").strip():
            continue
        scored.append((value, row))

    scored.sort(key=lambda pair: -pair[0])
    return [row for _, row in scored[: max(0, int(top_n))]]


def auction_rookie_keys(
    contract: Mapping[str, Any] | None,
    top_n: int = DEFAULT_POOL_SIZE,
) -> set[str]:
    """Lower-cased identity keys for every rookie in the auction.

    Shaped to be intersected with the same key set
    ``waiver_values_by_position`` builds per row, so a rookie is excluded
    whichever field the two sides happen to match on.
    """
    keys: set[str] = set()
    for row in select_rookie_rows(contract, top_n):
        for field in _KEY_FIELDS:
            key = str(row.get(field) or "").strip().lower()
            if key:
                keys.add(key)
    return keys
