"""Vendor rookie-price COMPARISON layer (MD-108 / W10-F004, version vc_v1).

Scope: this module only builds the comparison a vendor board can honestly
support against OUR canonical rookie-auction dollars.  It never produces or
changes a canonical dollar (``src/draft/rookie_auction/*`` owns those) and never
touches ``rankDerivedValue``.

The defect it replaces (``server._vendor_dollars_for_rookies``): each vendor's
partial rookie list was stretched over the whole $1,200.  KTC lists 45 of 72
rookies, IDP Trade Calculator 63-70; a vendor that agrees with our board on every
rookie it covers still showed a "vendor overrates" gap because 45 rows shared the
dollars our board spreads over 72.

RULE (``intersection_budget_reallocation``).  Let C be the rookies that BOTH the
vendor observes (fresh, positive value) AND our canonical ladder prices.  The
vendor's comparable dollar for a rookie in C is the dollar our own ladder gives
the rookie standing at the SAME rank inside C by the vendor's order:

    sort C by vendor value desc; sort the same players' OUR dollars desc;
    pair them position by position (tied vendor values share the mean of their
    positions).

Properties (all tested against hand-computed cases):
  * the vendor's total over C equals OUR total over C exactly, so population
    size cannot create a price advantage - omitting rookies removes them from
    both sides;
  * a vendor that orders C exactly as we do has a gap of exactly 0;
  * the gap measures ORDER disagreement only.  Vendor magnitude is not
    re-priced (the vendor's raw value is untouched and travels separately).

The number is DERIVED, never a vendor quote: ``quoteKind`` says so.  Where the
comparison is not defensible the state is explicit and the dollar is ``None`` -
never ``0`` and never a stretched curve.  Thresholds are declared PRIORS.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

COMPARISON_VERSION = "vc_v1"
METHOD = "intersection_budget_reallocation"
QUOTE_KIND = "derived_comparison_not_a_vendor_quote"

# PRIORS (declared, not fitted): below either floor the common population is too
# small for a rank reallocation to mean anything.
MIN_COMMON_ROOKIES = 12
MIN_COVERAGE_SHARE = 0.5

STATE_COMPARABLE = "comparable"
STATE_NO_OBSERVATIONS = "no_vendor_observations"
STATE_INSUFFICIENT = "insufficient_coverage"
STATE_OURS_UNAVAILABLE = "our_dollars_unavailable"
STATE_AMBIGUOUS = "ambiguous_identity"

# vendor id -> pool key / provider.  KTC Crowd+Trades is KTC's own published
# market (one provider); IDPTC is a second provider.  They are never merged, and
# a vendor is one provider however many boards it publishes.
VENDORS: dict[str, dict[str, str]] = {
    "ktc": {"rawKey": "ktcRaw", "provider": "KeepTradeCut", "source": "ktcCrowdTradesSfTep"},
    "idpTradeCalc": {
        "rawKey": "idpRaw",
        "provider": "IDP Trade Calculator",
        "source": "idpTradeCalc",
    },
}


def _name_key(row: Mapping[str, Any]) -> str:
    return str(row.get("name") or "").strip().lower()


def compare_vendor(
    pool: Sequence[Mapping[str, Any]],
    our_dollars: Sequence[float | None] | None,
    vendor: str,
) -> tuple[dict[str, float], dict[str, Any]]:
    """Return ``(comparable_dollar_by_lower_name, receipt)`` for one vendor.

    ``pool`` rows carry ``name``, the vendor raw key and optional
    ``staleVendors`` (vendor ids whose observation is past its freshness budget);
    ``our_dollars`` is index-aligned with ``pool`` and holds OUR canonical ladder
    dollars (``None`` for a rookie it did not price).
    """
    spec = VENDORS[vendor]
    raw_key = spec["rawKey"]
    receipt: dict[str, Any] = {
        "vendor": vendor,
        "provider": spec["provider"],
        "source": spec["source"],
        "version": COMPARISON_VERSION,
        "method": METHOD,
        "quoteKind": QUOTE_KIND,
        "poolSize": len(pool),
        "listed": 0,
        "staleObservations": 0,
        "covered": 0,
        "common": 0,
        "coverageShare": None,
        "state": STATE_NO_OBSERVATIONS,
        "reason": None,
        "minCommonRookies": MIN_COMMON_ROOKIES,
        "minCoverageShare": MIN_COVERAGE_SHARE,
    }
    names = [_name_key(r) for r in pool]
    if len(set(names)) != len(names) or "" in names:
        receipt.update(state=STATE_AMBIGUOUS, reason="duplicate_or_blank_rookie_names")
        return {}, receipt

    listed: list[int] = []
    fresh: list[int] = []
    for i, r in enumerate(pool):
        v = r.get(raw_key)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            listed.append(i)
            if vendor in (r.get("staleVendors") or ()):
                continue
            fresh.append(i)
    receipt["listed"] = len(listed)
    receipt["staleObservations"] = len(listed) - len(fresh)
    receipt["covered"] = len(fresh)
    if not fresh:
        receipt["reason"] = "stale" if listed else "vendor_lists_no_rookies"
        return {}, receipt

    ours = list(our_dollars) if our_dollars is not None else []
    common = [
        i for i in fresh if i < len(ours) and isinstance(ours[i], (int, float)) and ours[i] >= 0
    ]
    receipt["common"] = len(common)
    receipt["coverageShare"] = round(len(common) / len(pool), 4) if pool else None
    if not common:
        receipt.update(state=STATE_OURS_UNAVAILABLE, reason="canonical_ladder_priced_no_common")
        return {}, receipt
    if len(common) < MIN_COMMON_ROOKIES or len(common) / len(pool) < MIN_COVERAGE_SHARE:
        receipt.update(state=STATE_INSUFFICIENT, reason="common_population_below_floor")
        return {}, receipt

    by_vendor = sorted(common, key=lambda i: -float(pool[i][raw_key]))
    our_sorted = sorted((float(ours[i]) for i in common), reverse=True)
    out: dict[str, float] = {}
    pos = 0
    while pos < len(by_vendor):
        end = pos
        v0 = float(pool[by_vendor[pos]][raw_key])
        while end + 1 < len(by_vendor) and float(pool[by_vendor[end + 1]][raw_key]) == v0:
            end += 1
        share = sum(our_sorted[pos : end + 1]) / (end - pos + 1)  # ties share the mean
        for k in range(pos, end + 1):
            out[names[by_vendor[k]]] = share
        pos = end + 1
    receipt.update(state=STATE_COMPARABLE, reason=None)
    return out, receipt


def compare_all_vendors(
    pool: Sequence[Mapping[str, Any]],
    our_dollars: Sequence[float | None] | None,
) -> tuple[dict[str, dict[str, float]], dict[str, Any]]:
    """Run every vendor; return ``(by_vendor_by_name, block)`` for the payload."""
    dollars: dict[str, dict[str, float]] = {}
    receipts: dict[str, Any] = {}
    for vendor in VENDORS:
        d, r = compare_vendor(pool, our_dollars, vendor)
        dollars[vendor] = d
        receipts[vendor] = r
    return dollars, {
        "version": COMPARISON_VERSION,
        "method": METHOD,
        "quoteKind": QUOTE_KIND,
        "vendors": receipts,
    }
