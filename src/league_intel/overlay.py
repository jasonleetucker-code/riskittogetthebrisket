"""Apply this league's valuation factors to a board, once, for everyone.

Why this module exists
──────────────────────
``/api/valuation/league-adjusted`` publishes *factors* and the client
multiplies them onto the board it already holds.  That works for
``/rankings``, where the client owns the rendering.  It does nothing for
the engines — trade suggestions, the arbitrage finder, angles, waivers,
the terminal, the simulator — because they run **server-side** off
``latest_contract_data`` and never see the overlay at all.

The result until now: a user who switched the board to league-adjusted
saw adjusted rankings and then got trade advice priced on the market
board.  Two boards, one session, no indication which was which.  That is
the inconsistency this closes.

The whole trick is that every engine reads exactly one value —
``rankDerivedValue`` on ``playersArray`` rows.  So none of them need to
know this feature exists: hand them a contract whose rows are already
adjusted and they inherit it.  No per-engine plumbing, no second value
concept to keep in sync.

What this is NOT
────────────────
Not a second ranking engine.  ``compact_ranks_and_tiers`` — the same
function the pipeline and :mod:`src.league_intel.publish` use — does the
re-rank, so the "no frontend ranking engine, and no parallel backend one
either" rule holds by construction rather than by discipline.

Not a write path.  ``latest_contract_data`` is a shared mutable module
global read by every other in-flight request; mutating a row in place
would reprice the market board for everyone.  Everything here copies.

Not league-shareable.  The factors come from one league's rosters
(``lineupScarcity``), so an adjusted contract is valid for exactly the
league it was built for.  Callers must resolve the league first — see
``server.py::_valuation_scoped_contract``.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

_LOGGER = logging.getLogger(__name__)

__all__ = ["adjusted_contract", "adjusted_rows", "row_factor_key"]


def row_factor_key(row: Mapping[str, Any]) -> str:
    """The name a factor is keyed by.

    Must stay identical to :func:`src.league_intel.publish._row_key`.
    A silent divergence here would not raise — it would just make the
    overlay apply to nobody, and the engines would quietly serve the
    market board under an adjusted label.
    """
    return str(row.get("displayName") or row.get("canonicalName") or "").strip()


def adjusted_rows(
    rows: Sequence[Mapping[str, Any]],
    factors: Mapping[str, float] | None,
) -> list[dict[str, Any]] | None:
    """Board rows with factors applied and ranks recomputed.

    Returns ``None`` when the adjustment produces an incoherent board —
    the caller is expected to fall back to the market board and say so.
    Serving an incoherent board is worse than serving none: engines
    would rank assets against values that contradict their own ranks.

    ``None`` factors, empty factors and an empty board all return
    ``None`` too, for the same reason: "nothing to apply" and "applied
    nothing" must not be distinguishable by the caller, since both mean
    the market board is what should be served.
    """
    if not rows or not factors:
        return None

    from src.api.data_contract import (  # noqa: PLC0415 - heavy import graph
        assert_ranking_coherence,
        compact_ranks_and_tiers,
        current_rookie_draft_year,
    )

    copies: list[dict[str, Any]] = []
    moved = 0
    for row in rows:
        copy = dict(row)
        base = copy.get("rankDerivedValue")
        factor = factors.get(row_factor_key(row))
        if factor and isinstance(base, (int, float)) and base > 0:
            copy["rankDerivedValue"] = int(round(float(base) * float(factor)))
            moved += 1
        copies.append(copy)

    if not moved:
        return None

    # ``copy_rows=False`` ON OUR OWN COPIES, deliberately.
    #
    # ``compact_ranks_and_tiers`` RETURNS only the rows it ranked — it
    # drops every row without a prior rank and every current-year slot
    # pick (whose rank it clears by design, because a slot pick is a
    # proxy for the corresponding rookie and must not consume a rank).
    # Returning that subset as "the board" measured 740 of 1093 rows on
    # the live contract: 113 picks including every 2026 pick, plus 240
    # unpriced players.  Under the adjusted lens the trade calculator
    # would simply not have had any 2026 picks in it.
    #
    # The ranker mutates in place, so ranking our copies without a
    # second copy leaves every row — ranked, unranked and slot-pick
    # alike — carrying the correct rank while the row list stays whole.
    ranked = compact_ranks_and_tiers(
        copies,
        anchor_year=current_rookie_draft_year(),
        copy_rows=False,
    )
    errors = assert_ranking_coherence(ranked)
    if errors:
        _LOGGER.warning(
            "league-adjusted board incoherent (%d errors); callers should serve market",
            len(errors),
        )
        return None
    return copies


def adjusted_contract(
    contract: Mapping[str, Any] | None,
    factors: Mapping[str, float] | None,
) -> dict[str, Any] | None:
    """A contract whose ``playersArray`` is this league's adjusted board.

    Shallow copy: every block the adjustment does not touch (``sleeper``,
    ``sources``, ``methodology``, ``poolAudit``) is shared with the
    original by reference, which is what makes this cheap enough to do
    per request.  Only ``playersArray`` and its rows are new objects.

    The legacy ``players`` dict is deliberately left alone.  Engines read
    values from ``playersArray``; the dict is consulted only for
    metadata like ``_yearsExp``.  Rewriting it would double the copy
    cost to keep a field nothing values-related reads.
    """
    if not contract:
        return None
    rows = adjusted_rows(contract.get("playersArray") or [], factors)
    if rows is None:
        return None
    out = dict(contract)
    out["playersArray"] = rows
    return out
