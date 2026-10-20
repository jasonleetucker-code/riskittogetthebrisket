"""Current-season competitive outcome (title probability) — explicitly unavailable.

The question: how does a trade move each team's probability of winning this
season's title?  The only simulator that could answer it,
:mod:`src.ros.playoff_sim`, runs its pre-simulation on the ``rosValue`` index,
not on league-scored points per game.  A lineup delta measured in league-scored
ppg (``src.bestball``) cannot be pushed through a simulator whose basis is a
different quantity without inventing a conversion, and the decision on moving
that simulator to a points basis is Owner Decision 11 (in review).

So this module answers ``unavailable`` for every team, always, with the reason
named — it never fabricates a number, and its contract
(:class:`src.bestball.contracts.CompetitiveOutcome`) refuses to carry one in an
``unavailable`` state.  When the basis question is resolved, this function gains
a real path behind a flag; until then a consumer reads the reason, not a zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.bestball.contracts import CompetitiveOutcome

__all__ = ["BASIS_MISMATCH_REASON", "championship_delta"]

BASIS_MISMATCH_REASON = (
    "basis_mismatch: playoff presim on rosValue index; owner decision 11 pending"
)
_BASIS = "src.ros.playoff_sim (rosValue presim) — not consumed"


def championship_delta(
    owner_ids: Sequence[str],
    lineup_deltas: Mapping[str, Any],
    *,
    snapshot: Mapping | None = None,
) -> dict[str, CompetitiveOutcome]:
    """``{owner_id: CompetitiveOutcome}`` — every entry ``unavailable``.

    ``lineup_deltas`` and ``snapshot`` are accepted so the signature is stable
    for the later real path; neither is read today.
    """
    del lineup_deltas, snapshot  # accepted for signature stability; not read
    return {
        str(oid): CompetitiveOutcome(
            owner_id=str(oid),
            title_prob_before=None,
            title_prob_after=None,
            delta=None,
            ci_low=None,
            ci_high=None,
            horizon="current_season",
            basis=_BASIS,
            state="unavailable",
            reason=BASIS_MISMATCH_REASON,
        )
        for oid in owner_ids
    }
