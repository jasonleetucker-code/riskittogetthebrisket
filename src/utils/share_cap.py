"""Bound any one contributor's share of a weighted total.

One implementation, because two would drift. ``src/consensus_edge`` has
capped per-manager and per-league concentration since ADR-011;
``src/sharp`` did not cap at all, so one manager active in ten leagues
contributed ten observations to the Sharp Tracker board and
``breadth_factor = m/(m+3)`` saturated too fast to push back. Both now
call this.

It lives in ``src/utils`` rather than in either caller because the
dependency has to point somewhere neutral: ``consensus_edge`` is a
feature package and must not be imported by ``src/sharp``, while
``sharp_flow`` deliberately imports nothing from ``src/sharp`` so it can
be reasoned about without a database. This module imports nothing at
all — it is arithmetic over ``{group: weight}``.
"""

from __future__ import annotations

# Enough passes to converge for any realistic input. Each pass either
# caps a group or returns, and capping the largest offender can push a
# second group over the line, so this iterates rather than scaling once.
_MAX_PASSES = 32


def apply_share_cap(
    weights_by_group: dict[str, float],
    max_share: float,
) -> dict[str, float]:
    """Scale groups down until none exceeds ``max_share`` of the total.

    Capping SHARES rather than counts is what makes this scale-free: ten
    managers each contributing 10% are untouched, while one manager
    contributing 80% is cut to the cap no matter how many observations
    that represents.

    A ``max_share`` outside ``(0, 1)`` is a no-op — 0 would erase every
    group and 1 or more can never bind, so neither is a cap and neither
    should silently behave like one.

    Returns a new mapping; the input is not modified.
    """
    if max_share <= 0 or max_share >= 1 or not weights_by_group:
        return dict(weights_by_group)

    capped = dict(weights_by_group)
    for _ in range(_MAX_PASSES):
        total = sum(capped.values())
        if total <= 0:
            return capped
        over = {k: v for k, v in capped.items() if v / total > max_share + 1e-12}
        if not over:
            return capped
        # Cap the single largest offender per pass, then re-evaluate: the
        # total moves, so capping them all at once would over-correct.
        worst = max(over, key=lambda k: capped[k])
        others = total - capped[worst]
        if others <= 0:
            return capped
        # Solve capped[worst] / (capped[worst] + others) == max_share
        capped[worst] = others * max_share / (1.0 - max_share)
    return capped
