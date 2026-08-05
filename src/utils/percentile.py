"""THE percentile-rank definition.

One question — "where does this value sit inside this population, on
0-1?" — had four independent answers in the tree, and they disagreed on
both the interior and the edges (audit W30-F007):

===============================  ==========================  ==============
module                           min / max of a 12-population  empty pool
===============================  ==========================  ==============
``src/public_league/power.py``   0.0 / 1.0                    0.5
``src/sharp/score.py``           0.0417 / 0.9583              0.5
``src/ros/power_v2.py``          0.0417 / 0.9583              **0.0**
``src/roster_intel/window.py``   0.0417 / 0.9583              n/a (two
                                                             inline copies)
===============================  ==========================  ==============

Two of those disagreements are defects rather than taste:

* ``power_v2`` returned ``0.0`` for an EMPTY population, so "we could
  not measure this" and "worst team in the league" were the same
  number on a board that ranks teams against each other.
* ``power.py`` divided by ``n - 1`` and subtracted the target from its
  own tie group — a self-EXCLUSIVE rank, which pins the league minimum
  at a literal 0.0 and the maximum at a literal 1.0 whatever the
  spread. Two components of the v1 power score therefore read 0.00 for
  the bottom team every single week, which is a statement about the
  formula and not about the team.

This module is the surviving definition: **self-inclusive midrank**,
``(below + 0.5 * equal) / n``. Self-inclusive because the target is a
member of the population it is being ranked in; midrank because an
all-identical population carries no information and must not read as
universally elite.

The empty-population policy is the caller's, and it is explicit at
every call site. ``percentile_rank`` returns ``None`` when there is
nothing to rank against — absence stays representable, per the
platform rule that a missing input must never resolve to a confident
number. Callers that genuinely need a float pass ``empty=`` and say
what they mean by it (``0.5`` = "unmeasured, treat as league median").

NOT covered by this module, deliberately:

* ``src/api/data_contract.py::_percentile`` and
  ``src/league_comparison/metrics.py::_percentile`` take a fraction and
  return a VALUE (a quantile). Different function, same word.
* ``src/roster_intel/profiles.py::elite_threshold`` selects an actual
  member of the pool by index so the threshold is always reachable.
  That reachability property is the point of it and a percentile rank
  cannot express it.
"""

from __future__ import annotations

from typing import Sequence

__all__ = ["percentile_rank"]


def percentile_rank(
    value: float,
    population: Sequence[float] | None,
    *,
    empty: float | None = None,
) -> float | None:
    """Self-inclusive midrank of ``value`` within ``population``, on 0-1.

    ``(count below + 0.5 * count equal) / count``.

    Returns ``empty`` (``None`` by default) when the population holds no
    numeric values. Non-numeric entries are ignored rather than
    coerced.
    """
    pop = [float(v) for v in (population or []) if isinstance(v, (int, float))]
    if not pop:
        return empty
    try:
        target = float(value)
    except (TypeError, ValueError):
        return empty
    below = sum(1 for v in pop if v < target)
    equal = sum(1 for v in pop if v == target)
    return (below + 0.5 * equal) / len(pop)
