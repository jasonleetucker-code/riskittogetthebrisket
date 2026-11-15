#!/usr/bin/env python3
"""Low-value-asset research — candidate treatments (owner directive 2026-10-20).

RESEARCH ONLY.  ``geom_q078_v1`` (q = 0.78) stays the production package model.
Nothing here is imported by served code.  Every candidate is a pure function of
side value vectors (plus, for the replacement-anchored variants, each asset's
position), evaluated in-process by the shadow harnesses.

The three approaches the owner asked to compare:

* **A — canonical value curve.**  The low end of the canonical 1–9999 scale is
  too high *as a player value*.  Shadow form: remap EVERY asset (the top piece
  and 1-for-1 trades included) through a smooth currency curve, then apply the
  incumbent geometric package model.  A real fix would live in the value
  pipeline and move rankings too; this shadow only shows its trade effect.
* **B — trade-currency adjustment.**  Low-end assets are valued correctly as
  holdings, but as *extra* pieces in a package they buy less than their value.
  Shadow form ("top-full currency"): one piece per side counts in full, every
  other piece counts at its currency value, geometric by rank.  1-for-1 trades
  are untouched.
* **C — informational only.**  No number changes; a disclosure fires when the
  B treatment would have changed the verdict.

The currency curve is ``g(v; c) = v^2 / (v + c)``: increasing, ``g(0) = 0``,
``g(v) ≈ v − c`` for ``v ≫ c`` and ``≈ v^2 / c`` for ``v ≪ c``.  It is smooth —
no threshold, no cliff — and ``g(v) <= v`` always.  ``c`` is an anchor:

* ``market`` — the Phase 3 market level (2,000).  The owner's caution applies:
  this is a comparator, not an assumption;
* ``replacement`` — the league's own replacement value at the asset's position
  (``dynasty_main`` waiver / replacement levels), so a starting-calibre IDP
  valued 1,500 keeps most of its credit while a never-start WR at 1,500 does not.
  That is the "usable depth vs expendable filler" distinction without a single
  global threshold.

B's form is ``U(S) = max_j [ v_j + OWA_q( g(v_k; c_k) : k != j ) ]``: the max over
which piece is "the" full-credit piece keeps it continuous and monotone even
when ``c`` differs by position.  Properties (pinned by
``tests/scripts/test_low_value_asset_treatments.py``): adding a positive asset
never hurts; raising a value never hurts; order-invariant; swapping sides
negates the gap; 1-for-1 is raw (B); an added piece adds at most its own value;
continuous.  It is NOT positively homogeneous (``c`` is a level on the fixed
canonical scale) — reported, not hidden.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

Q = 0.78
MARKET_LEVEL = 2000.0


def g(v: float, c: float) -> float:
    """Smooth currency credit of a piece worth ``v`` against anchor ``c``."""
    if v <= 0:
        return 0.0
    if c <= 0:
        return float(v)
    return v * v / (v + c)


def owa(vals: Sequence[float], q: float = Q) -> float:
    """Incumbent geometric package utility on any values (descending)."""
    return sum(v * q**i for i, v in enumerate(sorted((x for x in vals if x > 0), reverse=True)))


Piece = tuple[float, float]  # (canonical value, anchor c for this piece)


def u_incumbent(side: Sequence[Piece], q: float = Q) -> float:
    return owa([v for v, _c in side], q)


def u_curve(side: Sequence[Piece], q: float = Q) -> float:
    """Approach A (shadow): every asset remapped through g, then the incumbent shape."""
    return owa([g(v, c) for v, c in side], q)


def u_currency(side: Sequence[Piece], q: float = Q) -> float:
    """Approach B (shadow): one full-credit piece, every other piece at currency value."""
    pieces = [(v, c) for v, c in side if v > 0]
    if not pieces:
        return 0.0
    best = 0.0
    for j, (vj, _cj) in enumerate(pieces):
        rest = [g(v, c) for k, (v, c) in enumerate(pieces) if k != j]
        best = max(best, vj + owa(rest, q))
    return best


TREATMENTS: dict[str, dict] = {
    "GEOM_78": {"u": u_incumbent, "approach": "incumbent", "anchor": None},
    "A_curve_market": {"u": u_curve, "approach": "A", "anchor": "market"},
    "A_curve_replacement": {"u": u_curve, "approach": "A", "anchor": "replacement"},
    "B_currency_market": {"u": u_currency, "approach": "B", "anchor": "market"},
    "B_currency_replacement": {"u": u_currency, "approach": "B", "anchor": "replacement"},
}


def anchor_for(treatment: str, position: str | None, replacement_by_pos: dict[str, float]) -> float:
    """The ``c`` a piece carries under a treatment.  Unknown position under the
    replacement anchor falls back to the league-wide replacement level (key
    ``"*"``), never to 0 (which would silently mean "no discount")."""
    kind = TREATMENTS[treatment]["anchor"]
    if kind is None:
        return 0.0
    if kind == "market":
        return MARKET_LEVEL
    if position and position in replacement_by_pos:
        return replacement_by_pos[position]
    return replacement_by_pos["*"]


def gap(
    treatment: str,
    side_a: Sequence[tuple[float, str | None]],
    side_b: Sequence[tuple[float, str | None]],
    replacement_by_pos: dict[str, float] | None = None,
) -> float:
    """Signed utility gap A − B under a treatment; sides are (value, position)."""
    rep = replacement_by_pos or {"*": MARKET_LEVEL}
    u: Callable = TREATMENTS[treatment]["u"]
    pa = [(v, anchor_for(treatment, p, rep)) for v, p in side_a]
    pb = [(v, anchor_for(treatment, p, rep)) for v, p in side_b]
    return u(pa) - u(pb)
