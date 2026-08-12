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
``docs/master-site-audit/evidence/W30/b4_candidate_measure.py``, and
re-verified against the applied boundary in ``b4f_measure.py
--equivalence`` (max head deviation **0** at every rank 1..500 on all
three routed masters, while ranks 501..904 go from one distinct value to
395 / 327 / 271). The
ceiling formulation is the one implemented because it touches no
committed constant, so a tail change cannot smuggle in a refit. Changing
``N`` on its own would move ``M`` and genuinely reshape the curve, which
is why B4 was told not to start there.

Why 904
-------

Measured, and **not** the 903 an earlier round of this work selected.

The boundary answers one question: how deep does source evidence
actually go? Ranks past it share the curve's tail value, because
resolving them would state a number no observation supports.

Three depths were candidates and the differences are not cosmetic:

* **500** (the old boundary) collapses 421 of 5,143 rank-Hill
  observations on the B4-final pin, touching 254 board rows — every one
  of them served, 34.3% of the served board.
* **800** (``OVERALL_RANK_LIMIT``) is the wrong domain. Board rank and
  source coordinate are different things: ``idpShow`` reaches effective
  rank 876 on rows the board publishes, so saturating at the board limit
  would still collapse genuine evidence.
* **882** (deepest rank-Hill rank ever observed) would re-saturate the
  band above it that ``idpTradeCalc`` publishes — reachable through the
  value-direct *fallback* branch, which is live code carrying no live
  traffic today. Three conditions route a value-direct source to the
  curve (source suppressed, value outside its declared range, value
  missing or non-positive), so the boundary has to cover value-direct
  ranks too.

**903 was refuted by measurement.** It had no executable definition
anywhere in the tree — the only occurrences were a comment at
``src/api/source_history.py:353`` and prose in a test docstring, and that
test's actual guard uses 2000. Replaying the 17 compatible historical
days with current code (``b4f_historical.py``) shows the deepest observed
effective rank is **904**, from ``idpTradeCalc`` on 2026-07-28. The
distribution across those days is 784, 785, 898 x5, 899, 900 x5, 901 x2,
903, 904 — so the quantity moves with source coverage and a single
board cannot decide it. 903 would have re-saturated a rank the evidence
has actually seen.

904 is the deepest rank observed across all retained evidence. It carries
no invented headroom: one rank further would already be a number no
observation supports, which is the same objection that rules out
unbounded extrapolation.

Known residual, stated rather than papered over: because the boundary is
the observed maximum, a future board on which a source reaches 905 will
saturate at 904. That is a far smaller defect than W30-F023 (which
collapses everything past 500) and it is the honest position — the
alternative is inventing a margin. ``b4f_historical.py --depths`` re-runs
the measurement when that question needs revisiting.

Status: APPLIED
---------------

:data:`TAIL_SATURATION_RANK` is ``904``. The former blocker is gone —
see the constant's own note.
"""

from __future__ import annotations

#: The deepest rank the coordinate resolves. Ranks past it share the
#: curve's tail value.
#:
#: ``None`` would mean "saturate at the caller's own reference
#: population", which is the pre-B4 behaviour and is what shipped until
#: this constant was set.
#:
#: **Former blocker, now resolved — kept because the history explains the
#: shape of the repair, not because it still applies.** Between
#: 2026-08-11 and #799 this constant was pinned at ``None`` even though
#: the repair was one assignment away: activating it drove the B3 market
#: corridor onto rows B3's own repair criteria forbade it to touch,
#: through the two residuals left open as #794 (the corridor's anchor was
#: itself one of the row's voters) and #795 (its band was the board's own
#: P90 drift, so removing the saturation inflation narrowed the band and
#: tightened the corridor onto rows it never targeted).
#:
#: PR #799 (merge ``52d48b6e5``) removed the market corridor outright and
#: replaced it with blend-integrity detection, which changes no value.
#: #794, #795 and #796 are resolved; there is no corridor for a tail
#: change to disturb, and the detector is silent under both tail policies
#: on the current board. The dependency is gone, not waived.
#:
#: #804 / W02-F019 (correlated-source anomalies) is a DIFFERENT problem —
#: several sources being wrong together — and does not touch the
#: percentile coordinate. It does not block this.
#:
#: Evidence for the value 904 is in the module docstring above and in
#: ``docs/master-site-audit/evidence/W30/B4F_TAIL_FINAL.md``. The
#: superseded blocked experiment is preserved unchanged at
#: ``docs/master-site-audit/evidence/W30/B4_TAIL_DECISION.md``.
TAIL_SATURATION_RANK: int | None = 904


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
