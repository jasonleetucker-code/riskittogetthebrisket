"""The percentile tail policy — one owner, deferred to by all four clamps.

Serving, fitting and holdout scoring each held their own ``p <= 1.0``
clamp. Four independent statements of one rule is how serving and
training come to disagree about a coordinate, which is what audit finding
W30-F008 was; W30-F023 is the same shape one layer down. This module is
the single place that answers "where does the tail saturate", so the
answer cannot differ between them.

The policy
----------

A rank's percentile coordinate is ``p = (rank − 1) / (reference_n − 1)``.
It saturates once the rank passes :data:`TAIL_SATURATION_RANK`, not once
``p`` passes 1.0.

Stated as a coordinate ceiling::

    p_max = (TAIL_SATURATION_RANK − 1) / (reference_n − 1)

Note what this deliberately does NOT do: it does not change ``c``, ``s``
or ``PERCENTILE_REFERENCE_N``. The Hill in rank form is

    V(r) = 9999 / (1 + ((r − 1) / M)^s),   M = c · (N − 1)

so the rank-space midpoint ``M`` is the invariant (B1.2), and ``N`` is a
coordinate *unit* rather than a model parameter. Raising the ceiling and
re-expressing the curve in a universe ``N' = TAIL_SATURATION_RANK`` with
``c' = c · (N − 1) / (N' − 1)`` are the *same function* — verified at
every rank on all three masters in
``docs/master-site-audit/evidence/W30/b4_candidate_measure.py``. The
ceiling formulation is the one implemented because it touches no
committed constant, so a tail change cannot smuggle in a refit. Changing
``N`` on its own would move ``M`` and genuinely reshape the curve, which
is why B4 was told not to start there.

Why 903
-------

Measured, not chosen for roundness. It is the deepest rank ANY source
publishes, recorded independently of this work at
``src/api/source_history.py:352-353`` and pinned by
``tests/api/test_source_history_rank_encodings.py``.

Three depths were candidates and the differences are not cosmetic:

* **500** (the old boundary) collapses 421 of 5,146 rank-Hill
  observations on the B4 pin, touching 254 board rows — every one of
  them served.
* **800** (``OVERALL_RANK_LIMIT``) is the wrong domain. Board rank and
  source coordinate are different things: ``idpShow`` reaches effective
  rank 877 on rows the board publishes, so saturating at the board limit
  would still collapse genuine evidence.
* **877** (deepest rank-Hill rank on the pin) has no headroom and would
  re-saturate the 878..899 band that ``idpTradeCalc`` publishes — a band
  reachable through the value-direct *fallback* branch, which is live
  code carrying no live traffic today.

903 covers the entire published domain and invents nothing beyond it: a
rank past it has never been observed from any source, so the curve stops
resolving there rather than stating a value no evidence supports.

Status: the boundary is NOT applied
------------------------------------

:data:`TAIL_SATURATION_RANK` ships as ``None`` — pre-B4 behaviour, to the
integer, on every row. What this module delivers today is the *single
owner*: four independent transcriptions of one rule became one, so
serving, fitting and holdout scoring can no longer disagree about where
the tail is. That is a W30-F008-class repair on its own and it is
behaviour-preserving.

The value repair is one constant away and is deliberately not taken.
Measured on the B4 pin, setting it to 903 makes the B3 market corridor
clamp four rows carrying five or more sources and three rows in the top
third of the IDP board — both of which B3's own repair criteria state it
must not do — and flips three clamps to direction ``up`` for the first
time. The mechanism is the two B3 residuals that were explicitly left
open: the anchor is itself one of the row's voters (#794), and the band
is the board's own P90 drift so removing the saturation inflation
narrows it from ~0.63 to ~0.46 and tightens the corridor onto rows it
never targeted (#795).

So the tail policy and the corridor are not separable on this board, and
B4's scope forbids reopening B3. Full evidence and the decision are in
``docs/master-site-audit/evidence/W30/B4_TAIL_DECISION.md``.
"""

from __future__ import annotations

#: The deepest rank the coordinate resolves. Ranks past it share the
#: curve's tail value.
#:
#: ``None`` means "saturate at the caller's own reference population",
#: which is the pre-B4 behaviour exactly — and is what ships today.
#:
#: **This is deliberately still None.** The measured repair is 903 and the
#: evidence supports it, but landing it is BLOCKED: it drives the B3
#: market corridor onto rows B3's own repair criteria forbid it to touch,
#: through the two residuals that were explicitly left open (#794 anchor/
#: voter circularity, #795 systemic-drift self-widening). Setting this to
#: 903 is the entire production change, and it must not be made until that
#: dependency is decided. See
#: ``docs/master-site-audit/evidence/W30/B4_TAIL_DECISION.md``.
TAIL_SATURATION_RANK: int | None = None


def max_percentile(reference_n: int) -> float:
    """The largest coordinate the tail policy allows for ``reference_n``.

    With a boundary set, it is expressed relative to the caller's own
    reference population so it keeps meaning *rank*
    ``TAIL_SATURATION_RANK`` whatever coordinate unit is in play. A fixed
    coordinate constant would silently become a different rank the moment
    a caller declared a different universe — the class of drift this
    module exists to prevent.

    With ``None`` it is 1.0, i.e. the caller's own reference population
    is the boundary. That is what every one of the four clamps did
    independently before this module existed.
    """
    n = int(reference_n)
    if n < 2:
        return 0.0
    if TAIL_SATURATION_RANK is None:
        return 1.0
    return (float(TAIL_SATURATION_RANK) - 1.0) / float(n - 1)


def clamp_percentile(percentile: float, *, reference_n: int) -> float:
    """Apply the tail policy to an already-computed coordinate.

    The single answer to "is this coordinate past the tail". Every clamp
    site calls this instead of writing ``min(1.0, p)`` of its own.
    """
    return max(0.0, min(max_percentile(reference_n), float(percentile)))
