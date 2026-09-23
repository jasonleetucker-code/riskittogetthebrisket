"""KTC signals — which KTC number is a model INPUT and which is the market BENCHMARK.

One owner for a distinction the rest of the codebase must not re-derive.

KeepTradeCut publishes three dynasty value modes on the same player object
(captured verbatim by :mod:`src.sources.ktc_value_sources`):

* **Crowd** (``ktcCrowdSfTep``) — expressed dynasty-community valuation.
* **Trades** (``ktcTradesSfTep``) — revealed trade-market behaviour.
* **Crowd+Trades** (``ktcCrowdTradesSfTep``) — KTC's own published blend of
  the two.  We never reconstruct it; KTC publishes it.

Owner directive 2026-09-23 (``docs/sources/SOURCE_FRESHNESS_WEIGHTING.md``):

* Crowd and Trades are two SEPARATE model inputs (two voters, two B10
  families, base weight 1.0 each).
* Crowd+Trades is **KTC Market** — the benchmark our model value is
  compared against.  It is NOT a model input.  Registering it beside Crowd
  and Trades would count the same KTC information twice (it is derived
  from them), so it is structurally excluded from the ranking registry.
* KTC Market contains no non-KTC source.  Ever.  Averaging a republisher
  (Fantasy Navigator), IDPTC, DLF or anything else into the "market" side
  would destroy what a market comparison means.

This module is pure: it imports nothing from the ranking pipeline, so every
consumer (pipeline, trade engines, BDVM, Consensus Edge, history, frontend
mirrors) can depend on it without an import cycle.
"""

from __future__ import annotations

import math
from typing import Any, Mapping

# ── Source keys ──────────────────────────────────────────────────────────
KTC_CROWD_KEY = "ktcCrowdSfTep"
KTC_TRADES_KEY = "ktcTradesSfTep"
KTC_MARKET_KEY = "ktcCrowdTradesSfTep"

#: The two KTC signals that vote in OUR model, in registry precedence order.
KTC_MODEL_INPUT_KEYS: tuple[str, str] = (KTC_CROWD_KEY, KTC_TRADES_KEY)

#: Pre-2026-09-08 KTC boards.  Both are Crowd-only captures.  Readable ONLY as
#: the historical stand-in for the market on as-of replays that predate the
#: three-mode capture — never a live fallback, never a vote.
KTC_HISTORICAL_MARKET_KEYS: tuple[str, str] = ("ktcSfTep", "ktc")

#: Every KTC-family key a CSV may carry.  Used for TE-basis exemption (KTC's
#: TE++ board is the basis the board is anchored on) and provenance.
KTC_ALL_KEYS: frozenset[str] = frozenset(
    {KTC_CROWD_KEY, KTC_TRADES_KEY, KTC_MARKET_KEY, *KTC_HISTORICAL_MARKET_KEYS}
)

#: The benchmark is DERIVED from the model inputs.  Anything that asks "remove
#: the market's influence from the board" (Consensus Edge's leave-one-out
#: board) must remove both inputs it is derived from.
KTC_MARKET_DERIVED_FROM: tuple[str, str] = KTC_MODEL_INPUT_KEYS

#: KTC's native scale tops out at exactly 9999.  A published value above it is
#: a scrape glitch, not a price.
KTC_DECLARED_MAX: float = 9999.0

#: Board scale ceiling (the Hill asymptote every canonical value lives under).
BOARD_SCALE_MAX: float = 9999.0

MARKET_DEFINITION = "ktc_published_crowd_trades"
MARKET_UNAVAILABLE_NO_COVERAGE = "no_ktc_coverage"
MARKET_UNAVAILABLE_OUT_OF_RANGE = "ktc_value_out_of_declared_range"

# Direction vocabulary for ``marketGapDirection`` — kept for consumer
# compatibility.  "retail" now means KTC Market; "consensus" means OUR model.
MARKET_PREMIUM = "retail_premium"
MODEL_PREMIUM = "consensus_premium"
NO_GAP = "none"


def _positive(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(out) or out <= 0:
        return None
    return out


def market_raw_value(sites: Mapping[str, Any] | None) -> float | None:
    """KTC's published Crowd+Trades value for one row, or None.

    None means KTC did not price this asset (or priced it outside KTC's own
    declared scale).  It never means zero.
    """
    if not isinstance(sites, Mapping):
        return None
    raw = _positive(sites.get(KTC_MARKET_KEY))
    if raw is None or raw > KTC_DECLARED_MAX:
        return None
    return raw


def market_raw_value_as_of(
    sites: Mapping[str, Any] | None, *, allow_historical: bool = False
) -> tuple[float | None, str | None]:
    """``(value, source_key)`` — the live market, or a historical stand-in.

    ``allow_historical`` is for as-of replays of boards captured before KTC's
    three-mode split existed.  The live path must pass False: a missing
    Crowd+Trades value today is missing, not a Crowd value.
    """
    live = market_raw_value(sites)
    if live is not None:
        return live, KTC_MARKET_KEY
    if allow_historical and isinstance(sites, Mapping):
        for key in KTC_HISTORICAL_MARKET_KEYS:
            raw = _positive(sites.get(key))
            if raw is not None and raw <= KTC_DECLARED_MAX:
                return raw, key
    return None, None


def compute_market_gap(
    model_value: float | None, market_normalized: float | None
) -> tuple[str, float | None]:
    """Relative gap between OUR model value and KTC Market, in value space.

    Returns ``(direction, ratio)``: ``ratio = |market − model| / mean(both)``
    (the same symmetric normalisation ``marketGapValueRatio`` has always
    used).  ``retail_premium`` → KTC Market prices the asset above our model
    (sell-high candidate); ``consensus_premium`` → our model prices it above
    KTC Market (buy-low candidate).  Either side missing → ``("none", None)``:
    an unmeasurable gap is not a zero gap.
    """
    model = _positive(model_value)
    market = _positive(market_normalized)
    if model is None or market is None:
        return NO_GAP, None
    scale = (model + market) / 2.0
    ratio = (market - model) / scale
    if ratio > 0:
        return MARKET_PREMIUM, float(abs(ratio))
    if ratio < 0:
        return MODEL_PREMIUM, float(abs(ratio))
    return NO_GAP, 0.0


def model_vs_market(
    model_value: float | None, market_block: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Our model value against KTC Market — absolute, percent and normalized.

    * ``absoluteDifference`` = model − KTC's published value (native units).
    * ``percentDifference``  = that difference ÷ KTC's published value.
    * ``normalizedDifference`` = model − market on the board's 0-9999 scale
      (KTC's value re-expressed with its own top asset at 9999 — the same
      encoding KTC votes arrive in).
    Any missing side yields None for every field, never 0.
    """
    block = market_block if isinstance(market_block, Mapping) else {}
    model = _positive(model_value)
    raw = _positive(block.get("value"))
    norm = _positive(block.get("normalizedValue"))
    out: dict[str, Any] = {
        "modelValue": model,
        "marketValue": raw,
        "marketNormalizedValue": norm,
        "absoluteDifference": None,
        "percentDifference": None,
        "normalizedDifference": None,
        "direction": NO_GAP,
        "valueRatio": None,
    }
    if model is None:
        return out
    if raw is not None:
        out["absoluteDifference"] = round(model - raw, 1)
        out["percentDifference"] = round((model - raw) / raw, 4)
    if norm is not None:
        out["normalizedDifference"] = round(model - norm, 1)
    direction, ratio = compute_market_gap(model, norm)
    out["direction"] = direction
    out["valueRatio"] = None if ratio is None else round(ratio, 4)
    return out


def build_market_blocks(
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """Stamp the canonical per-row ``ktcMarket`` block on every row.

    Normalization uses the market board's OWN maximum across the rows that
    carry it (``raw / market_max × 9999``) — the identical encoding a
    value-direct KTC vote uses — so ``normalizedValue`` is comparable to
    ``rankDerivedValue``.  Rank is KTC Market's own ordering by published
    value (ties broken by name for determinism).

    Rows KTC does not price receive an explicit unavailable block rather
    than no block, so "no KTC Market for this asset" is distinguishable from
    "the block was never computed".  Returns a small board-level summary.
    """
    priced: list[tuple[float, str, dict[str, Any]]] = []
    for row in rows:
        sites = row.get("canonicalSiteValues")
        raw = market_raw_value(sites)
        if raw is not None:
            name = str(row.get("displayName") or row.get("canonicalName") or "")
            priced.append((raw, name, row))
    market_max = max((p[0] for p in priced), default=0.0)
    priced.sort(key=lambda t: (-t[0], t[1]))
    rank_by_id = {id(row): i + 1 for i, (_raw, _name, row) in enumerate(priced)}

    for row in rows:
        sites = row.get("canonicalSiteValues")
        sites = sites if isinstance(sites, Mapping) else {}
        raw = market_raw_value(sites)
        # Compact on purpose: this block rides on every row of every
        # override delta.  The two KTC components are already on the row in
        # ``canonicalSiteValues`` (``ktcCrowdSfTep`` / ``ktcTradesSfTep``);
        # ``player_market_explain`` reads them from there.
        if raw is None:
            reason = (
                MARKET_UNAVAILABLE_OUT_OF_RANGE
                if _positive(sites.get(KTC_MARKET_KEY)) is not None
                else MARKET_UNAVAILABLE_NO_COVERAGE
            )
            row["ktcMarket"] = {"value": None, "available": False, "reason": reason}
            continue
        norm = raw / market_max * BOARD_SCALE_MAX if market_max > 0 else None
        row["ktcMarket"] = {
            "value": raw,
            "normalizedValue": None if norm is None else round(norm, 1),
            "rank": rank_by_id.get(id(row)),
            "available": True,
        }
    return {
        "sourceKey": KTC_MARKET_KEY,
        "definition": MARKET_DEFINITION,
        "derivedFrom": list(KTC_MARKET_DERIVED_FROM),
        "isModelInput": False,
        "pricedRows": len(priced),
        "boardMax": market_max or None,
    }


def ktc_market_for_row(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """The canonical KTC Market block for a row.

    Reads the stamped ``ktcMarket`` block when present (the contract path).
    For bare rows that never went through the pipeline, derives the raw
    value only — ``normalizedValue`` stays None because normalization needs
    the whole board.
    """
    if not isinstance(row, Mapping):
        return {"value": None, "normalizedValue": None, "available": False}
    stamped = row.get("ktcMarket")
    if isinstance(stamped, Mapping):
        return dict(stamped)
    sites = row.get("canonicalSiteValues")
    raw = market_raw_value(sites if isinstance(sites, Mapping) else None)
    return {
        "value": raw,
        "normalizedValue": None,
        "rank": None,
        "available": raw is not None,
        "reason": None if raw is not None else MARKET_UNAVAILABLE_NO_COVERAGE,
    }
