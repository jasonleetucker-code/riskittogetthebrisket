"""Which coordinate pool an effective rank lives in, and its master curve.

The blend converts a source's *effective rank* to a value through a
scope-level master Hill curve.  Picking the curve is only well-defined
once you know **what population the rank counts within** — rank 120 of
the combined offense+IDP market and rank 120 of the IDP slice are
different quantities, and the two masters were fit on those different
populations precisely because of that.

This module owns that question.  It exists because the answer used to be
inferred from the source's REGISTRY DECLARATION rather than from what the
pipeline actually did to the rank::

    if src_def["is_cross_market"]:            → GLOBAL master
    elif src_def["scope"] == "overall_idp":   → IDP master
    else:                                     → OFFENSE master

Three registered sources declare ``needs_shared_market_translation``, and
the pipeline crosswalks their native IDP-only ordinal onto the backbone's
shared offense+IDP ladder *before* the curve is applied.  Their effective
rank is a shared-market rank; the declaration still said "IDP scope", so
it was priced on the IDP slice master (W02-F001).  The IDP rookie ladder
reaches the same wrong curve by a second route — Phase 1d translates a
within-class rookie rank through ``idpTradeCalc``'s ranks, which are also
shared-market — so this is a translation problem, not an IDP-source
problem.

The rule this module encodes, in one line:

    **A translation moves a rank INTO the coordinate pool of the ladder
    it was translated through.  The curve follows the pool.**

That makes the pool a property of a specific (row, source) rank, not of a
source, which matters: when the backbone is unavailable the crosswalk
returns the raw rank with ``TRANSLATION_FALLBACK`` and the rank is still
IDP-local.  Routing it through GLOBAL because "the source is normally
translated" would be the same class of error in the other direction.

What this module deliberately does NOT do:

* It does not change any master's constants.  Promotion and apply are
  human-gated through ``src/model_registry`` (ADR-008,
  ``docs/roster-trade-intelligence/DECISIONS.md``).
* It does not route the ROOKIE master.  That master is fit by the weekly
  refit and is not routed today (``_build_hill_curves_block`` stamps
  ``routed: False``); a rookie rank whose ladder translation was skipped
  keeps its source's native pool, which is the pre-existing behaviour and
  is tracked separately as ``scale_integrity_lost``.
* It does not decide reference N.  ``rank_to_percentile`` owns the
  coordinate; this owns which curve reads that coordinate.
"""

from __future__ import annotations

from typing import Any

from src.canonical.idp_backbone import (
    SOURCE_SCOPE_OVERALL_IDP,
    SOURCE_SCOPE_POSITION_IDP,
)
from src.canonical.player_valuation import (
    HILL_GLOBAL_PERCENTILE_C,
    HILL_GLOBAL_PERCENTILE_S,
    HILL_PERCENTILE_C,
    HILL_PERCENTILE_S,
    IDP_HILL_PERCENTILE_C,
    IDP_HILL_PERCENTILE_S,
)

# ── The pools ──────────────────────────────────────────────────────────
#
# One token per population a rank can be counted within.  These are the
# populations the three routed masters were fit against, which is why
# there are exactly three.

#: Combined offense + IDP ranks — the backbone's shared market, the
#: cross-market sources' native scale, and where a successful
#: shared-market crosswalk lands.  Priced by the GLOBAL master.
RANK_POOL_SHARED_MARKET = "shared_market"

#: Offense (+ picks) ranks.  Priced by the OFFENSE master.
RANK_POOL_OFFENSE = "offense"

#: IDP-only ranks — a source's native defensive ordinal, or a positional
#: list lifted onto the backbone's overall-IDP ladder.  Priced by the IDP
#: master.
RANK_POOL_IDP = "idp"

VALID_RANK_POOLS = frozenset(
    {
        RANK_POOL_SHARED_MARKET,
        RANK_POOL_OFFENSE,
        RANK_POOL_IDP,
    }
)

_CURVE_BY_POOL: dict[str, tuple[float, float]] = {
    RANK_POOL_SHARED_MARKET: (HILL_GLOBAL_PERCENTILE_C, HILL_GLOBAL_PERCENTILE_S),
    RANK_POOL_OFFENSE: (HILL_PERCENTILE_C, HILL_PERCENTILE_S),
    RANK_POOL_IDP: (IDP_HILL_PERCENTILE_C, IDP_HILL_PERCENTILE_S),
}

#: Human label per pool, for evidence tables and diagnostics.
CURVE_LABEL_BY_POOL: dict[str, str] = {
    RANK_POOL_SHARED_MARKET: "GLOBAL",
    RANK_POOL_OFFENSE: "OFFENSE",
    RANK_POOL_IDP: "IDP",
}


class RankCoordinateError(ValueError):
    """An effective rank was handed to the curve with no known pool."""


def native_pool_for_source(src_def: dict[str, Any]) -> str:
    """The pool a source's ranks are in BEFORE any translation.

    This is the only place a registry field decides a pool, and it is
    describing the source's own data rather than naming the source:
    ``is_cross_market`` is the registry's declaration that this source
    prices offense and IDP on one scale, which is exactly what
    "shared market" means.

    Positional IDP lists report a within-position ordinal, which is not
    an IDP-overall rank either — but the ladder that lifts them
    (``IdpBackbone.ladder_for``) is numbered over IDP entries only, so
    both the translated and the untranslated case belong to the IDP
    family and take the IDP master.
    """
    if src_def.get("is_cross_market"):
        return RANK_POOL_SHARED_MARKET
    scope = str(src_def.get("scope") or "")
    if scope in (SOURCE_SCOPE_OVERALL_IDP, SOURCE_SCOPE_POSITION_IDP):
        return RANK_POOL_IDP
    return RANK_POOL_OFFENSE


def curve_for_pool(pool: str) -> tuple[float, float]:
    """``(c, s)`` for the master that prices ranks counted in ``pool``.

    Raises rather than defaulting.  A silent default here is how a rank
    with unknown provenance gets a plausible-looking value: the caller
    always knows which pool it established, so an unknown token means the
    provenance was lost, not that a fallback is wanted.
    """
    try:
        return _CURVE_BY_POOL[pool]
    except KeyError:
        raise RankCoordinateError(
            f"unknown rank coordinate pool {pool!r}; expected one of " f"{sorted(VALID_RANK_POOLS)}"
        ) from None


def curve_label_for_pool(pool: str) -> str:
    return CURVE_LABEL_BY_POOL.get(pool, "UNKNOWN")
