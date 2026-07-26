"""Cross-market package valuation (WS-J F-1).

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
A scalar mapping is offered only as an explicitly lower-confidence
fallback when single-market evaluation is impossible (5% of KTC-priced
assets carry no IDPTC value), and packages that cannot be evaluated
either way are **suppressed, never silently ranked**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping

__all__ = [
    "NORMALIZATION_VERSION",
    "MARKET_KTC",
    "MARKET_IDPTC",
    "SHARED_SCALE_ASSUMPTION",
    "POSITION_SCALE_RATIOS",
    "NormalizationStrategy",
    "AssetValuation",
    "PackageValuation",
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

_IDP_POSITIONS = frozenset(
    {"DL", "DE", "DT", "EDGE", "NT", "LB", "OLB", "ILB", "MLB", "DB", "CB", "S", "SS", "FS"}
)


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
    suppressed_reason: str | None = None
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
            "suppressedReason": self.suppressed_reason,
            "warnings": list(self.warnings),
            "assets": [a.to_dict() for a in self.assets],
        }


def _is_idp(position: str | None) -> bool:
    return str(position or "").strip().upper() in _IDP_POSITIONS


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
    pos = str(position or "").strip().upper()
    if pos in _IDP_POSITIONS:
        return 1.0
    return POSITION_SCALE_RATIOS.get(pos, _POOLED_SCALE_RATIO)


def value_package(
    assets: Iterable[Mapping[str, Any]],
    *,
    allow_scalar_fallback: bool = False,
) -> PackageValuation:
    """Value a package on ONE market, or refuse to value it.

    ``assets`` are contract-shaped rows carrying ``canonicalSiteValues``,
    ``position`` and a display name.

    Strategy order:

    1. **Single market.**  If every asset is priced on one board, total
       there.  Exact.  IDP presence forces ``idpTradeCalc`` because it
       is the only board spanning both universes; a pure-offense package
       uses ``ktcSfTep``.
    2. **Scalar fallback** (opt-in only).  Convert the stragglers with
       the measured per-position ratio.  Approximate, and stamped at
       roughly half the confidence — mixing a converted value into a
       total is precisely what the audit flagged, so it never happens
       silently or by default.
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
            warnings: list[str] = []
            if has_idp:
                warnings.append(SHARED_SCALE_ASSUMPTION)
            return PackageValuation(
                strategy=NormalizationStrategy.SINGLE_MARKET,
                market=market,
                total=sum(v for _, v in priced),
                assets=valuations,
                normalization_confidence=confidence,
                warnings=warnings,
            )

    if not allow_scalar_fallback:
        missing = [
            str(r.get("displayName") or "?") for r in rows if _site_value(r, preferred) is None
        ]
        return PackageValuation(
            strategy=NormalizationStrategy.SUPPRESSED,
            market=None,
            total=None,
            suppressed_reason=(
                f"no single market prices every asset; {len(missing)} unpriced on "
                f"{preferred} (e.g. {', '.join(missing[:3])})"
            ),
        )

    # Scalar fallback — explicitly approximate.
    confidence = _STRATEGY_CONFIDENCE[NormalizationStrategy.SCALAR_FALLBACK]
    valuations = []
    total = 0.0
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
            )
        ratio = _position_ratio(r.get("position"))
        converted_value = other * ratio if preferred == MARKET_IDPTC else other / ratio
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

    return PackageValuation(
        strategy=NormalizationStrategy.SCALAR_FALLBACK,
        market=preferred,
        total=total,
        assets=valuations,
        normalization_confidence=confidence,
        warnings=[
            SHARED_SCALE_ASSUMPTION,
            "scalar conversion applied: median |relative error| 3.0%, p90 11.7% "
            "(measured on 476 paired players)",
        ],
    )
