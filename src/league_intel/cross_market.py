"""Cross-market package valuation (WS-J F-1).

Auditing call sites?  ``grep cross_market`` LIES
────────────────────────────────────────────────
``src/api/data_contract.py`` contains roughly twenty hits for
``is_cross_market`` — an unrelated *source-registry flag* in the
consensus pipeline marking which ranking sources price both offense
and IDP.  It has nothing to do with this module.

CORRECTED 2026-08-18.  This block used to say the honest count of
production importers was **zero**.  That was true when it was written
and is not true now: ``src/roster_intel/packages.py`` imports
``value_package`` / ``compare_packages`` for the Trade Package
Generator, and ``src/api/gameplan.py`` calls
``packages.generate_packages`` from ``GET /api/gameplan?partner=…``.
``src/api/gameplan.py`` separately imports ``DEFAULT_GATE_PCT``.  **A
behaviour change here DOES reach a user**, on that endpoint.

The grep warning above still stands for a different reason: the
``is_cross_market`` hits in ``data_contract.py`` are an unrelated
source-registry flag, so a grep audit over-counts callers of this file
while the stale note under-counted them.  Read the hits.

What has NOT changed: ``src/trade/angle.py`` is still **not rewired**,
and the live defect described below is still live there — see "Which
call site actually matters".

The live defect
───────────────
``src/trade/angle.py::_market_source_for`` routes each PLAYER to the
right board — IDP to ``idpTradeCalc``, everything else to
``ktcSfTep``.  But ``_make_candidate`` then does::

    counter_market_values = [p["market_value"] for p in combo]
    market_sum = sum(counter_market_values)

over a combo that is never constrained to one market.  A mixed
offense/IDP package therefore adds KTC points to IDPTC points, and
``market_gain_pct`` gates candidate visibility on that sum.

What the evidence actually says
───────────────────────────────
Applying ``docs/ORCHESTRATION.md`` §2b — state which side is measured
and which is assumed — because a validation with one assumed side will
look like agreement and mean nothing:

**MEASURED (n=476 paired players, today's board).**  ``ktcSfTep`` and
``idpTradeCalc`` price the same offense players, so the scale relation
is directly observable.  Pooled median ``IDPTC/KTC`` ratio **0.9997**,
Spearman **0.990**.  Per position: QB 1.020, RB 0.994, WR 1.012,
PICK 1.000 — and **TE 0.895**, the one real divergence.

**MEASURED (not assumed).**  IDPTC's IDP values share the scale of its
offense values rather than being normalized separately: its IDP maximum
is **6,444** against an offense maximum of **9,999**.  A
separately-normalized IDP board would top out at its own ceiling.  The
top IDP interleaves at roughly offense rank #29, which is plausible for
a 9-IDP-starter league.

**ASSUMED — and this is the load-bearing assumption.**  That IDPTC's
internal offense↔IDP exchange rate is *correct*, not merely
self-consistent.  Nothing available validates that: there is no ground
truth for what an edge rusher is worth in WR points.  The interleaving
check above establishes coherence, not accuracy.  A defensible package
comparison rests on it, so it is stamped rather than buried —
:data:`SHARED_SCALE_ASSUMPTION`.

Design consequence: prefer exactness over mapping
─────────────────────────────────────────────────
Because IDPTC covers BOTH universes on one scale, the correct primary
strategy is not to build a KTC→IDPTC mapping at all.  It is to evaluate
each package **entirely within a single market** that covers every
asset in it:

* offense-only package → ``ktcSfTep`` (the canonical retail anchor)
* any IDP present → ``idpTradeCalc`` (the only board spanning both)

That is *exact* — no conversion, no fitted parameter, no error term.

Exact ARITHMETIC is not a certain ANSWER
────────────────────────────────────────
The single-market path was originally stamped with ``uncertainty_band =
0.0``, which conflated two different claims.  The arithmetic really is
exact: no conversion happened, so no conversion error exists.  But an
offense+IDP package priced on IDPTC still rests entirely on
:data:`SHARED_SCALE_ASSUMPTION` — that IDPTC's internal offense↔IDP
exchange rate is *correct* and not merely self-consistent.  Stamping a
zero band said the opposite: that the number was beyond doubt.

Concretely, that made the straddle check in :func:`compare_packages`
unreachable for exactly the packages the assumption is load-bearing
for.  A mixed IDPTC package landing at 4.65% against a 5.0% gate came
back ``verdict_certain: True`` — a coin-flip reported as a decision.

So a package containing IDP assets now carries a band sized from the
same measured spread the scalar path uses, applied to the portion of
the total that the assumption prices:

    band = (IDP subtotal) × (_RATIO_P90 − _RATIO_P10)

**MEASURED:** the spread itself (p10 0.886, p90 1.054 over n=476 paired
offense players).  **ASSUMED:** that an offense↔offense disagreement
spread is the right magnitude for an offense↔IDP one.  It is a proxy,
not a measurement of the quantity in question — the offense↔IDP rate
has no ground truth to measure against, which is the whole reason the
assumption exists.  It is the best available sizing and is deliberately
not presented as more than that.  What it buys is that the assumption
now flows through the same materiality machinery as everything else,
instead of being invisible to it.

Suppression keys on PROXIMITY TO THE DECISION BOUNDARY
──────────────────────────────────────────────────────
Two revisions got this wrong before it was right, and the sequence is
worth keeping.

*Revision 1 suppressed on presence* — any package containing an asset
the target board does not price.  Measured, that bucket is entirely
fringe: **all 25 such assets** top out at value 1,004, KTC ranks
~445-477 (Josh Oliver, Carson Wentz, Ray-Ray McCloud).  Among assets
anyone would actually trade (value ≥ 1,500), **100% of mixed packages
resolve on the exact path**.  Withholding a trade because it includes
a 493-point WR removed working functionality.

*Revision 2 suppressed on band-vs-total* — better, but it asked the
question in a place that cannot answer it.  **A package in isolation
has no decision boundary.**  The verdict is a threshold crossing on
``market_gain_pct``, which only exists when two packages are compared.
An 11% band is irrelevant to a package showing a 60% market gain and
decisive for one showing 4% against a 5% gate.

So the materiality decision lives in :func:`compare_packages`, where
the boundary exists.  ``value_package`` measures and *stamps* the
uncertainty; it no longer pretends to adjudicate it.  Package-level
suppression is now reserved for what is genuinely unvaluable — an
asset priced on neither board, or an empty package.

Suppression is always LABELLED, never silent: every withheld result
carries a caller-renderable ``label`` and ``suppressed_reason``, so a
reader can tell "withheld because uncertain" from "data missing".

Which call site actually matters
────────────────────────────────
The counter-side pool in ``angle.py`` is IDP-gated (``include_idp``
defaults False and the frontend never sends it), so counter combos are
offense-only in practice.  **The reachable mixed-market path is the
OFFER side**: ``offer_rows`` is built from user-selected names with no
IDP filter, so ``offer_market_values`` can mix boards today.  Any
rewire must cover that side first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

from src.utils.name_clean import normalize_position as _norm_pos

__all__ = [
    "NORMALIZATION_VERSION",
    "MARKET_KTC",
    "MARKET_IDPTC",
    "SHARED_SCALE_ASSUMPTION",
    "POSITION_SCALE_RATIOS",
    "DEFAULT_GATE_PCT",
    "NormalizationStrategy",
    "AssetValuation",
    "PackageValuation",
    "PackageComparison",
    "compare_packages",
    "value_package",
]

NORMALIZATION_VERSION = "li.crossmarket.2026-07-26.v1"

MARKET_KTC = "ktcSfTep"
MARKET_IDPTC = "idpTradeCalc"
_LEGACY_KTC = "ktc"

SHARED_SCALE_ASSUMPTION = (
    "IDPTC's internal offense<->IDP exchange rate is assumed CORRECT, not merely "
    "self-consistent. Its shared scale is measured (IDP max 6444 vs offense max 9999, "
    "so IDP is not separately normalized); its accuracy is not validatable with "
    "available data."
)

# Measured 2026-07-26 on 476 paired players.  Used ONLY by the
# lower-confidence scalar fallback — the primary path needs no ratio.
# TE is the one material divergence and is the TE-premium question
# (ADR-009), not a scale artifact: ktcSfTep is a TE++ board.
POSITION_SCALE_RATIOS: Mapping[str, float] = {
    "QB": 1.020,
    "RB": 0.994,
    "WR": 1.012,
    "TE": 0.895,
    "PICK": 1.000,
}
_POOLED_SCALE_RATIO = 0.9997

# Measured p10/p90 of the paired ratio (n=476).  CLAUDE.md and
# src/trade/finder.py quote p10 0.888 for the same relation; that is
# n=475 anchored on KTC's 500 rows rather than the paired set, so the
# 0.002 gap is population, not disagreement.  Not worth reconciling —
# it moves the spread by ~1% — but flagged so nobody chases it.
# Used to size the
# uncertainty a conversion introduces, so suppression can be decided on
# whether that uncertainty MATTERS rather than on whether a conversion
# happened at all.  Also reused — as an explicit PROXY, see the module
# docstring — to size the offense<->IDP exchange-rate assumption on the
# exact path.
_RATIO_P10 = 0.886
_RATIO_P90 = 1.054
_RATIO_SPREAD = _RATIO_P90 - _RATIO_P10

DEFAULT_GATE_PCT = 5.0
"""The caller's decision threshold on ``market_gain_pct``, in percent.
Mirrors ``angle.py``'s ``max_market_gain_pct`` default.  Materiality is
judged against DISTANCE FROM THIS BOUNDARY, not against the band in
isolation — see :func:`compare_packages`."""

# The three canonical IDP buckets ``POSITION_ALIASES`` collapses to.
# CLAUDE.md makes ``src/utils/name_clean.py`` the single source of
# truth for position normalization, so this normalizes first and tests
# against the collapsed set rather than re-listing the 14 raw spellings
# (DE/DT/EDGE/NT -> DL, ILB/OLB/MLB -> LB, CB/S/SS/FS -> DB).
#
# That duplicate list is what ``angle.py`` still carries, and this file
# had copied it.  The reasoning matters more than the fix:
#
#   A COPIED position set is one forgotten spelling away from routing
#   an "EDGE" row to a board that prices no defenders.
#
# That is precisely the defect #556 just fixed in ``finder.py``, where
# every IDP asset scored ``ktc_value = None`` and was dropped before
# scoring, so an IDP league silently got offense-only results.  A
# 14-element literal reintroduces it the first time a source emits a
# spelling nobody enumerated.
#
# The merged tree currently holds THREE IDP sets — ``finder.py``
# ``{DL, LB, DB}`` (safe: it normalizes first, and ``Asset.position``
# is built from the normalized value), ``angle.py`` 14 raw spellings,
# and this one.  They agree today only by luck of normalization order.
# ``angle.py`` is still the unrewired live path and still holds the
# raw list; fixing it is WS-J's call when it rewires.
#
# Normalizing handles BOTH already-normalized and raw contract rows, so
# it is strictly safer at either call site.  Parametrized tests cover
# all 14 spellings, including that each still receives the
# offense<->IDP assumption band — a missed spelling would zero that
# band and walk the P1-b defect back in through a side door.
_IDP_POSITIONS = frozenset({"DL", "LB", "DB"})


class NormalizationStrategy(str, Enum):
    """How a package's market total was arrived at."""

    SINGLE_MARKET = "singleMarket"
    """Every asset priced on one board.  Exact — no conversion."""

    SCALAR_FALLBACK = "scalarFallback"
    """A measured per-position ratio converted some assets.  Approximate."""

    SUPPRESSED = "suppressed"
    """No defensible total.  The package must not be ranked."""


_STRATEGY_CONFIDENCE = {
    NormalizationStrategy.SINGLE_MARKET: 0.85,
    NormalizationStrategy.SCALAR_FALLBACK: 0.45,
    NormalizationStrategy.SUPPRESSED: 0.0,
}


@dataclass(frozen=True)
class AssetValuation:
    """One asset's market value, with full provenance."""

    name: str
    position: str
    raw_market_value: float | None
    raw_market_source: str | None
    normalized_market_value: float | None
    normalization_version: str = NORMALIZATION_VERSION
    normalization_confidence: float = 0.0
    converted: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "position": self.position,
            "rawMarketValue": self.raw_market_value,
            "rawMarketSource": self.raw_market_source,
            "normalizedMarketValue": self.normalized_market_value,
            "normalizationVersion": self.normalization_version,
            "normalizationConfidence": self.normalization_confidence,
            "converted": self.converted,
        }


@dataclass
class PackageValuation:
    """A package total that is either defensible or explicitly not."""

    strategy: NormalizationStrategy
    market: str | None
    total: float | None
    assets: list[AssetValuation] = field(default_factory=list)
    normalization_version: str = NORMALIZATION_VERSION
    normalization_confidence: float = 0.0
    uncertainty_band: float = 0.0
    suppressed_reason: str | None = None
    label: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def is_rankable(self) -> bool:
        """False when the package must not be shown as market-fair."""
        return self.strategy is not NormalizationStrategy.SUPPRESSED and self.total is not None

    @property
    def is_mixed_market(self) -> bool:
        return any(_is_idp(a.position) for a in self.assets) and any(
            not _is_idp(a.position) for a in self.assets
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "market": self.market,
            "total": self.total,
            "isRankable": self.is_rankable,
            "isMixedMarket": self.is_mixed_market,
            "normalizationVersion": self.normalization_version,
            "normalizationConfidence": self.normalization_confidence,
            "uncertaintyBand": self.uncertainty_band,
            "suppressedReason": self.suppressed_reason,
            "label": self.label,
            "warnings": list(self.warnings),
            "assets": [a.to_dict() for a in self.assets],
        }


def _is_idp(position: str | None) -> bool:
    return _norm_pos(str(position or "")) in _IDP_POSITIONS


def _site_value(row: Mapping[str, Any], key: str) -> float | None:
    sites = row.get("canonicalSiteValues")
    if not isinstance(sites, Mapping):
        return None
    raw = sites.get(key)
    if raw is None and key == MARKET_KTC:
        raw = sites.get(_LEGACY_KTC)
    try:
        v = float(raw)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _position_ratio(position: str | None) -> float:
    # Normalized so a raw "EDGE"/"CB" row takes the IDP branch instead
    # of silently falling through to the pooled offense ratio.
    pos = _norm_pos(str(position or ""))
    if pos in _IDP_POSITIONS:
        return 1.0
    return POSITION_SCALE_RATIOS.get(pos, _POOLED_SCALE_RATIO)


def _shared_scale_band(assets: Iterable[AssetValuation]) -> float:
    """Points of uncertainty carried by the offense<->IDP ASSUMPTION.

    Zero for a package with no IDP assets — there the assumption never
    gets used.  Otherwise the IDP subtotal is the part of the total
    whose placement rests on IDPTC's internal exchange rate being
    right, so that is what the spread is applied to.

    This is NOT a conversion error; no conversion happened on the exact
    path.  It is the assumption's own uncertainty, made visible so
    :func:`compare_packages` can judge whether it reaches the verdict.
    The spread is a measured proxy, not a measurement of this quantity
    — see the module docstring.

    **Known over-correction, stated rather than hidden.**  For a
    PURE-IDP package the exchange rate is a common factor across the
    whole total, so it cancels in a ratio against another pure-IDP
    package — but not against an offense one.  A package cannot see the
    other side of the comparison, so one of those two cases must be
    wrong.  This errs toward the wider band, i.e. toward withholding a
    near-boundary verdict, which matches the module's posture
    everywhere else.  It is also rare in practice: ``angle.py``'s
    counter combos are offense-only today (``include_idp`` defaults
    False).  Moving the sizing into :func:`compare_packages`, where both
    compositions are visible, is the real fix if this starts mattering.
    """
    idp_total = sum(abs(a.normalized_market_value or 0.0) for a in assets if _is_idp(a.position))
    return idp_total * _RATIO_SPREAD if idp_total > 0 else 0.0


def value_package(
    assets: Iterable[Mapping[str, Any]],
    *,
    allow_scalar_fallback: bool = True,
) -> PackageValuation:
    """Value a package on ONE market, or refuse to value it.

    ``assets`` are contract-shaped rows carrying ``canonicalSiteValues``,
    ``position`` and a display name.

    Strategy order:

    1. **Single market.**  If every asset is priced on one board, total
       there.  Exact arithmetic.  IDP presence forces ``idpTradeCalc``
       because it is the only board spanning both universes; a
       pure-offense package uses ``ktcSfTep``.  A package containing IDP
       still carries a non-zero ``uncertainty_band`` for the
       offense<->IDP exchange-rate assumption — exactness applies to the
       arithmetic, not to the assumption.
    2. **Scalar fallback.**  Convert the stragglers with the measured
       per-position ratio.  Approximate, stamped at roughly half the
       confidence, and always labelled ``converted`` per asset.  ON by
       default because the measurement says the assets it rescues are
       entirely fringe (see the module docstring): refusing them removed
       working functionality without protecting any real decision.
       Pass ``allow_scalar_fallback=False`` for a strict caller that
       wants exact-or-nothing — the package is then SUPPRESSED with a
       label naming the assets that forced it.
    3. **Suppressed.**  No defensible total; ``is_rankable`` is False
       and the caller must withhold or explicitly label the package.

    Never returns a mixed-market sum without a strategy stamp saying so.
    """
    rows = list(assets)
    if not rows:
        return PackageValuation(
            strategy=NormalizationStrategy.SUPPRESSED,
            market=None,
            total=None,
            suppressed_reason="empty package",
            label="No assets to value",
        )

    has_idp = any(_is_idp(r.get("position")) for r in rows)
    preferred = MARKET_IDPTC if has_idp else MARKET_KTC
    alternate = MARKET_KTC if has_idp else MARKET_IDPTC

    for market in (preferred, alternate):
        priced = [(r, _site_value(r, market)) for r in rows]
        if all(v is not None for _, v in priced):
            # An offense+IDP package can only ever be complete on IDPTC.
            if market == MARKET_KTC and has_idp:
                continue
            confidence = _STRATEGY_CONFIDENCE[NormalizationStrategy.SINGLE_MARKET]
            valuations = [
                AssetValuation(
                    name=str(r.get("displayName") or r.get("canonicalName") or ""),
                    position=str(r.get("position") or "").upper(),
                    raw_market_value=v,
                    raw_market_source=market,
                    normalized_market_value=v,
                    normalization_confidence=confidence,
                    converted=False,
                )
                for r, v in priced
            ]
            total = sum(v for _, v in priced)
            warnings: list[str] = []
            # No conversion happened, so there is no conversion error.
            # There IS assumption error whenever IDP is present, and a
            # zero band would hide it from compare_packages().
            band = _shared_scale_band(valuations)
            if has_idp:
                warnings.append(SHARED_SCALE_ASSUMPTION)
                warnings.append(
                    f"Priced exactly on {market} (no conversion), but the offense<->IDP "
                    f"exchange rate is assumed: 80% band {band:.0f} pts "
                    f"({(band / total if total > 0 else 0.0):.1%} of the total), sized from "
                    "the measured paired-ratio spread as a proxy. Whether it matters "
                    "depends on distance from the verdict boundary — see compare_packages()."
                )
            return PackageValuation(
                strategy=NormalizationStrategy.SINGLE_MARKET,
                market=market,
                total=total,
                assets=valuations,
                normalization_confidence=confidence,
                uncertainty_band=band,
                warnings=warnings,
            )

    if not allow_scalar_fallback:
        unpriced = [
            str(r.get("displayName") or "?") for r in rows if _site_value(r, preferred) is None
        ]
        return PackageValuation(
            strategy=NormalizationStrategy.SUPPRESSED,
            market=None,
            total=None,
            suppressed_reason=(
                f"no single market prices every asset and scalar fallback is disabled; "
                f"{preferred} does not price: {', '.join(unpriced) or 'unknown'}"
            ),
            label=(
                "Cannot be valued on a single market: "
                f"{', '.join(unpriced[:3]) or 'unknown asset'}"
            ),
        )

    # Scalar conversion — on by default for assets the target board does
    # not price.  Suppression is decided AFTER, on whether the
    # conversion's uncertainty could flip the caller's decision.
    confidence = _STRATEGY_CONFIDENCE[NormalizationStrategy.SCALAR_FALLBACK]
    valuations = []
    total = 0.0
    uncertainty = 0.0
    converted_names: list[str] = []
    for r in rows:
        native = _site_value(r, preferred)
        if native is not None:
            valuations.append(
                AssetValuation(
                    name=str(r.get("displayName") or ""),
                    position=str(r.get("position") or "").upper(),
                    raw_market_value=native,
                    raw_market_source=preferred,
                    normalized_market_value=native,
                    normalization_confidence=confidence,
                    converted=False,
                )
            )
            total += native
            continue
        other = _site_value(r, alternate)
        if other is None:
            return PackageValuation(
                strategy=NormalizationStrategy.SUPPRESSED,
                market=None,
                total=None,
                suppressed_reason=(f"{r.get('displayName') or '?'} is priced on neither market"),
                label=f"Not priced by either market: {r.get('displayName') or 'unknown asset'}",
            )
        ratio = _position_ratio(r.get("position"))
        converted_value = other * ratio if preferred == MARKET_IDPTC else other / ratio
        # 80% band this conversion introduces, in package points.
        uncertainty += abs(other) * _RATIO_SPREAD
        converted_names.append(str(r.get("displayName") or "?"))
        valuations.append(
            AssetValuation(
                name=str(r.get("displayName") or ""),
                position=str(r.get("position") or "").upper(),
                raw_market_value=other,
                raw_market_source=alternate,
                normalized_market_value=converted_value,
                normalization_confidence=confidence,
                converted=True,
            )
        )
        total += converted_value

    # Two independent sources of doubt, and they stack: the conversions
    # above, plus the offense<->IDP assumption if any IDP is in here.
    conversion_band = uncertainty
    scale_band = _shared_scale_band(valuations)
    uncertainty = conversion_band + scale_band
    band_share = (uncertainty / total) if total > 0 else 0.0
    return PackageValuation(
        strategy=NormalizationStrategy.SCALAR_FALLBACK,
        market=preferred,
        total=total,
        assets=valuations,
        normalization_confidence=confidence,
        uncertainty_band=uncertainty,
        warnings=[
            SHARED_SCALE_ASSUMPTION,
            f"{len(converted_names)} asset(s) converted with the measured per-position "
            f"ratio; 80% uncertainty band {uncertainty:.0f} pts ({band_share:.1%} of the "
            f"total) = {conversion_band:.0f} conversion + {scale_band:.0f} offense<->IDP "
            "assumption. Whether that matters depends on distance from the verdict "
            "boundary — see compare_packages().",
        ],
    )


# ── Where the materiality decision actually belongs ───────────────────


@dataclass
class PackageComparison:
    """A counter-vs-offer verdict, plus whether uncertainty could flip it.

    The verdict is a THRESHOLD CROSSING on ``market_gain_pct``, so
    conversion uncertainty only matters relative to the distance from
    that threshold.  A 60% gain is untouched by an 11% band; a 4% gain
    against a 5% gate is decided by it.
    """

    counter: PackageValuation
    offer: PackageValuation
    market_gain_pct: float | None
    gate_pct: float
    gain_low_pct: float | None = None
    gain_high_pct: float | None = None
    passes_gate: bool | None = None
    verdict_certain: bool = False
    suppressed_reason: str | None = None
    label: str | None = None

    @property
    def is_rankable(self) -> bool:
        return self.market_gain_pct is not None and self.verdict_certain

    def to_dict(self) -> dict[str, Any]:
        return {
            "marketGainPct": self.market_gain_pct,
            "gainLowPct": self.gain_low_pct,
            "gainHighPct": self.gain_high_pct,
            "gatePct": self.gate_pct,
            "passesGate": self.passes_gate,
            "verdictCertain": self.verdict_certain,
            "isRankable": self.is_rankable,
            "suppressedReason": self.suppressed_reason,
            "label": self.label,
            "counter": self.counter.to_dict(),
            "offer": self.offer.to_dict(),
        }


def compare_packages(
    counter: PackageValuation,
    offer: PackageValuation,
    *,
    gate_pct: float = DEFAULT_GATE_PCT,
) -> PackageComparison:
    """Decide whether a counter/offer verdict survives its uncertainty.

    ``gate_pct`` is the caller's decision threshold — ``angle.py``
    defaults ``max_market_gain_pct`` to 5.0.  The comparison propagates
    each side's ``uncertainty_band`` into a range on ``market_gain_pct``;
    if that range straddles the gate the verdict is **not certain** and
    the package is withheld with a renderable label.  Otherwise it is
    rankable, however wide the band, because it cannot change the
    answer.

    The band covers BOTH kinds of doubt — scalar conversion error and
    the offense<->IDP exchange-rate assumption — so an exactly-summed
    mixed package reaches this check like any other.  Only a genuinely
    assumption-free comparison (offense-only, both sides on KTC) carries
    a zero band and is certain by construction.
    """
    if not counter.is_rankable or not offer.is_rankable:
        blocked = counter if not counter.is_rankable else offer
        return PackageComparison(
            counter=counter,
            offer=offer,
            market_gain_pct=None,
            gate_pct=gate_pct,
            suppressed_reason=blocked.suppressed_reason or "package could not be valued",
            label=blocked.label or "Cannot be valued on a single market",
        )

    c_total, o_total = counter.total or 0.0, offer.total or 0.0
    if o_total <= 0:
        return PackageComparison(
            counter=counter,
            offer=offer,
            market_gain_pct=None,
            gate_pct=gate_pct,
            suppressed_reason="offer side has no positive market total",
            label="Offer side has no market value",
        )

    gain = 100.0 * (c_total - o_total) / o_total
    # Worst/best case: push each side's band in the direction that most
    # moves the gain.
    c_lo, c_hi = c_total - counter.uncertainty_band, c_total + counter.uncertainty_band
    o_lo, o_hi = o_total - offer.uncertainty_band, o_total + offer.uncertainty_band
    gain_low = 100.0 * (c_lo - o_hi) / o_hi if o_hi > 0 else gain
    gain_high = 100.0 * (c_hi - o_lo) / o_lo if o_lo > 0 else gain

    passes = gain <= gate_pct
    straddles = gain_low <= gate_pct <= gain_high
    # The band guard keeps a zero-band comparison certain even when the
    # gain lands exactly ON the gate: with no conversion and no
    # cross-universe assumption there is nothing for it to be uncertain
    # about.  It is NOT a shortcut for "single market" — a mixed
    # single-market package has a non-zero band and falls through here.
    if straddles and (counter.uncertainty_band > 0 or offer.uncertainty_band > 0):
        return PackageComparison(
            counter=counter,
            offer=offer,
            market_gain_pct=gain,
            gate_pct=gate_pct,
            gain_low_pct=gain_low,
            gain_high_pct=gain_high,
            passes_gate=passes,
            verdict_certain=False,
            suppressed_reason=(
                f"market gain {gain:.1f}% sits within the cross-market uncertainty band "
                f"[{gain_low:.1f}%, {gain_high:.1f}%] of the {gate_pct:.1f}% gate"
            ),
            label="Withheld: too close to call under cross-market uncertainty",
        )

    return PackageComparison(
        counter=counter,
        offer=offer,
        market_gain_pct=gain,
        gate_pct=gate_pct,
        gain_low_pct=gain_low,
        gain_high_pct=gain_high,
        passes_gate=passes,
        verdict_certain=True,
    )
