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

STATUS — EXPERIMENTAL, NOT CANONICAL (2026-08-14)
─────────────────────────────────────────────────
This methodology was evaluated for promotion to canonical and
**REJECTED** under the owner's outcome-evidence bar.  It may no longer
own a canonical field.  The rejection is recorded in full in
``docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md``; the short form:

* the factor is measured from **current roster state**, not durable
  league structure — ``top`` is the single highest-``rosValue`` player
  rostered today, so one trade or waiver claim moves every player at
  that position;
* its input is a 0-100 **logarithmic rank index** (``rosValue``), which
  is "not points, and not projection-aware", yet it sets a multiplier on
  a 0-9999 dynasty board;
* ``reference_lineup_scarcity = 0.5`` is a bare constant, never derived,
  and it alone decides the sign of every adjustment;
* it is per-position only — 709 live rows carry 7 distinct factors, and
  5 of 8 positions get a pure scalar, which is untestable within
  position by construction;
* it multiplies into a scale whose maximum is the Hill **asymptote**
  (``V(p) = 9999 / (1 + (p/c)^s)``), with no renormalisation, so the
  board leaves its own declared range;
* ``tePremium`` is deliberately ABSENT here with a pinned double-count
  guard, because the anchor is already KTC's TE++ board — but
  ``structuralScarcity`` has no equivalent guard while every offense
  source is already a Superflex board;
* and the evidence needed to validate a replacement does not exist:
  ``board_history`` began accumulating only recently and no artifact
  records league configuration beside a value.

So this module computes a **diagnostic** board.  It writes
``experimentalLeagueAdjustedValue`` / ``…Rank`` / ``…Tier`` and never
``rankDerivedValue``.  Rejection is not a verdict on league-aware
valuation as a goal — it is a verdict on this implementation and on
today's evidence.

The original design note, kept because it explains the shape: every
engine reads exactly one value — ``rankDerivedValue`` on
``playersArray`` rows — so handing them an adjusted contract made them
inherit the lens with no per-engine plumbing.  That is exactly what made
it dangerous: the lens became indistinguishable from canonical truth.

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

#: Where the experimental league-aware numbers live.  Named so no
#: consumer can mistake one for canonical value by reading a field name,
#: and so a grep for the canonical field never lands here.
EXPERIMENTAL_VALUE_FIELD = "experimentalLeagueAdjustedValue"
EXPERIMENTAL_RANK_FIELD = "experimentalLeagueAdjustedRank"
EXPERIMENTAL_TIER_FIELD = "experimentalLeagueAdjustedTier"

#: Canonical fields this module must never write.  Asserted by
#: ``tests/api/test_canonical_value_invariance.py`` rather than trusted:
#: ``values.*`` were measured as exact aliases of ``rankDerivedValue`` on
#: all 1,092 rows of the live contract, so moving one without the others
#: publishes a row that disagrees with itself — which is what the server
#: overlay used to do (it scaled the canonical field and left the aliases
#: at market).
CANONICAL_VALUE_FIELDS = frozenset({"rankDerivedValue", "overall", "finalAdjusted", "displayValue"})

__all__ = [
    "CANONICAL_VALUE_FIELDS",
    "EXPERIMENTAL_RANK_FIELD",
    "EXPERIMENTAL_TIER_FIELD",
    "EXPERIMENTAL_VALUE_FIELD",
    "adjusted_contract",
    "adjusted_rows",
    "row_factor_key",
]


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

    # TWO LISTS, and the split is the whole point.
    #
    # ``scratch`` carries the adjusted number in the canonical slot purely
    # so the existing ranker — which sorts on ``rankDerivedValue`` — can
    # rank the adjusted board without being rewritten.  It never leaves
    # this function.
    #
    # ``out`` is what callers get: the canonical value UNTOUCHED, with the
    # adjusted number under its own unmistakable name.  This overlay was
    # evaluated for promotion to canonical and REJECTED under the
    # outcome-evidence bar (see the module docstring), so it may not own a
    # canonical field.  Writing it into ``rankDerivedValue`` is what let a
    # device-local localStorage setting decide which methodology a user
    # saw, and left no field carrying the canonical number afterwards.
    scratch: list[dict[str, Any]] = []
    out: list[dict[str, Any]] = []
    moved = 0
    for row in rows:
        base = row.get("rankDerivedValue")
        factor = factors.get(row_factor_key(row))
        work = dict(row)
        emit = dict(row)
        if factor and isinstance(base, (int, float)) and not isinstance(base, bool) and base > 0:
            adjusted = int(round(float(base) * float(factor)))
            work["rankDerivedValue"] = adjusted
            emit[EXPERIMENTAL_VALUE_FIELD] = adjusted
            moved += 1
        scratch.append(work)
        out.append(emit)

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
        scratch,
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

    # Carry the experimental ordering across under experimental names.
    # The canonical rank stays whatever the canonical board said, for the
    # same reason the canonical value does.
    for work, emit in zip(scratch, out):
        emit[EXPERIMENTAL_RANK_FIELD] = work.get("canonicalConsensusRank")
        emit[EXPERIMENTAL_TIER_FIELD] = work.get("canonicalTierId")
    return out


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
