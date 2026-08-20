"""Bridge lifecycle vocabulary.  ONE definition.

A *bridge* is a source (or a source FAMILY) that carries cross-position
information: it says what an IDP is worth against offense, rather than merely
which IDP is better than which other IDP.  A *specialist* answers "who is
better within this domain"; a bridge answers "what is that domain position
worth on the overall market".

These states answer "may this bridge translate right now", which is a
different question from "did we acquire it" (that is
``src.sources.acquisition_state``) and from "is its scale comparable to the
other side's" (that is :data:`COMPARABILITY_STATUSES`).

Why three vocabularies rather than one flattened set: a bridge can be
perfectly acquired, perfectly fresh, and still unusable because its offense
and IDP halves are not the same quantity.  Collapsing that into
``UNAVAILABLE`` would hide the only fact that tells an operator what to fix.
"""

from __future__ import annotations

__all__ = [
    "BRIDGE_STATES",
    "COMPARABILITY_STATUSES",
    "DEPENDENT_SOURCE_FAMILY",
    "DISPROVEN",
    "INSUFFICIENT_COVERAGE",
    "NOT_COMPARABLE",
    "PARTIAL",
    "PENDING",
    "QUALIFIED",
    "STALE",
    "UNAVAILABLE",
    "USABLE_BRIDGE_STATES",
    "VALID",
]


VALID = "VALID"
STALE = "STALE"
PARTIAL = "PARTIAL"
UNAVAILABLE = "UNAVAILABLE"
NOT_COMPARABLE = "NOT_COMPARABLE"
INSUFFICIENT_COVERAGE = "INSUFFICIENT_COVERAGE"
#: This bridge's provider family is already represented by another bridge.
#: Not a fault — a correctness guard.  Two feeds from one vendor are one
#: opinion, and letting both seed a translation would manufacture agreement
#: out of a single source, which is the signal-independence invariant.
DEPENDENT_SOURCE_FAMILY = "DEPENDENT_SOURCE_FAMILY"

BRIDGE_STATES: frozenset[str] = frozenset(
    {
        VALID,
        STALE,
        PARTIAL,
        UNAVAILABLE,
        NOT_COMPARABLE,
        INSUFFICIENT_COVERAGE,
        DEPENDENT_SOURCE_FAMILY,
    }
)

#: Only these may seed a translation.  ``PARTIAL`` is included — a bridge
#: covering DL and LB but not DB still legitimately prices DL and LB, and
#: refusing it entirely would discard evidence to avoid naming a gap.
#: ``STALE`` is excluded: stale rows are real, but a stale bridge asserting a
#: CURRENT cross-position relationship is precisely the false claim.
USABLE_BRIDGE_STATES: frozenset[str] = frozenset({VALID, PARTIAL})


#: Whether a bridge's offense and IDP halves have been shown to be the same
#: quantity.  This is evidence-gated and fails closed: ``PENDING`` never
#: bridges.  A vendor asserting "same engine" is not a proof — scoring
#: variant, format basis and observation time are all ways two halves of one
#: product can fail to be comparable.
QUALIFIED = "QUALIFIED"
DISPROVEN = "DISPROVEN"
PENDING = "PENDING"

COMPARABILITY_STATUSES: frozenset[str] = frozenset({QUALIFIED, DISPROVEN, PENDING})
