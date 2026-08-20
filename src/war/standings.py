"""Pure standings-credit primitives for `C5-WAR-01`.

Two related concepts, deliberately named and kept separate per
``docs/PLAYER_IMPACT_WAR_MVP_SPEC.md`` §3:

* **H2H credit** — this team's real head-to-head result for the week.
* **Median credit** — whether this team's score beats the league-wide
  median for the week, when the league runs a median game.

Both are pure functions of scores, never of who is on a roster — that
keeps them reusable for both the ACTUAL result and, per §3/§4, a
COUNTERFACTUAL result computed after swapping one player's score for a
replacement-level expectation. The spec is explicit that the
counterfactual median must be **recalculated from the counterfactual
score set**, never held at the actual week's value — every function
here that touches the median takes the full score list as an argument
so a caller cannot accidentally reuse a stale one.

**PRIOR, not verified against live Sleeper behaviour.** Median-game tie
handling and odd/even league-size behaviour are implemented as the
standard statistical median (ties get half-credit, matching Sleeper's
own head-to-head tie convention) because this environment has no
network egress to verify Sleeper's host-specific median-game rules
directly. `docs/GAME_DAY_PROBABILITY_SPEC.md` §3 names this exact
verification as outstanding ("Verify Sleeper/host behavior for ties at
the median and odd/even league sizes rather than guessing") for the
sibling Game Day feature — the same caveat applies here, and is not
resolved by this unit. Do not promote this to a validated methodology
without that verification.
"""

from __future__ import annotations

import statistics
from typing import Sequence

#: Fractional standings credit on a tie — matches
#: `src/public_league/metrics.py`'s existing `winPct = (wins + ties*0.5) / games`
#: convention, so WAR's credit unit agrees with the rest of the codebase's
#: standings math rather than inventing a second tie convention.
TIE_CREDIT = 0.5
WIN_CREDIT = 1.0
LOSS_CREDIT = 0.0


def h2h_credit(my_score: float, opponent_score: float) -> float:
    """This team's standings credit for one head-to-head matchup."""
    if my_score > opponent_score:
        return WIN_CREDIT
    if my_score < opponent_score:
        return LOSS_CREDIT
    return TIE_CREDIT


def median_value(all_scores: Sequence[float]) -> float | None:
    """The league-wide median for one week. ``None`` if there are no
    scores to compute it from — never 0.0, which is a real possible
    median value and must not be confused with "no data"."""
    if not all_scores:
        return None
    return float(statistics.median(all_scores))


def median_credit(my_score: float, all_scores: Sequence[float]) -> float | None:
    """Whether ``my_score`` beats the league median for the week.

    ``all_scores`` must include ``my_score`` itself — the median is a
    property of the whole league's score set for that week, including
    this team. Returns ``None`` (never 0.0/0.5) when the median itself
    is unavailable.
    """
    med = median_value(all_scores)
    if med is None:
        return None
    if my_score > med:
        return WIN_CREDIT
    if my_score < med:
        return LOSS_CREDIT
    return TIE_CREDIT


def standings_credit(
    my_score: float,
    opponent_score: float,
    all_scores: Sequence[float],
    *,
    median_enabled: bool,
) -> float:
    """Total standings-win credit for one team-week: H2H alone, or H2H
    plus the median game when the league runs one.

    ``E[wins] = P(win H2H) + P(beat league median)`` in the spec's own
    notation (§4) becomes, for a single realized/counterfactual score
    (not a probability), the literal sum of the two credits — 0/1/2 with
    ties contributing halves. ``all_scores`` is REQUIRED to include
    ``my_score``, matching :func:`median_credit`.
    """
    credit = h2h_credit(my_score, opponent_score)
    if median_enabled:
        med = median_credit(my_score, all_scores)
        # ``med`` is only ``None`` when ``all_scores`` is empty, which a
        # correct caller never passes (it must include ``my_score``).
        # Guarded rather than asserted so a caller bug degrades to
        # H2H-only credit instead of raising mid-computation.
        if med is not None:
            credit += med
    return credit
