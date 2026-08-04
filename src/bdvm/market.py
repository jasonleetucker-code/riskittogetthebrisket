"""Market comparison layer — runs strictly AFTER the fundamental model.

Isolation contract (Phase-5 gate, enforced by the function signatures
here and pinned by tests):

* the fundamental engine (``engine.py``) has no market inputs;
* every function in this module takes a *completed* fundamental
  valuation and never mutates it;
* the market may inform ``market_adjusted`` outputs only — separately
  labeled, stored beside (never over) the fundamental value.

Market sources come from the live contract's ``canonicalSiteValues``.
ONLY value-signal sources may be read as market prices: the Phase-0
audit established that rank-signal sources store a synthetic encoding
(``999900 − rank×100``) in that dict, so treating them as values would
be garbage arithmetic.  v1 anchors: ``ktcSfTep`` (offense + picks) and
``idpTradeCalc`` (IDP) — directly comparable per the 2026-07-26
cross-market study (median value ratio 1.000, both top out at 9999).

Raw KTC and raw IDPTC numbers for DIFFERENT assets are never summed
without a normalization tag: ``MarketView.normalization_version``
records the mapping under which any cross-market comparison happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.bdvm.params import ParamSet

# Value-signal market sources with their market-type tags (§8.1).
VALUE_MARKET_SOURCES: dict[str, str] = {
    "ktcSfTep": "crowd",
    "ktc": "crowd",
    "idpTradeCalc": "crowd",
}
NORMALIZATION_VERSION = "ktc-idptc-peer-v1"  # 2026-07-26 study: ratio ~1.000

_IDP_GROUPS = frozenset({"DL", "LB", "DB"})


class MarketIsolationError(RuntimeError):
    """Raised when market code is asked to run before fundamentals exist."""


# Liquidity to use for the alpha SCALE when dispersion was never
# measured.  This is the params' own ``clip_lo`` — the least-liquid end
# of the band — resolved at call time rather than hardcoded here.
#
# Why the floor and not a "typical" value: alpha = gap x liquidity, and
# alpha drives the reachable BUY / SELL / STRONG_SELL signals.  Scaling
# an unmeasured row by the floor SHRINKS its alpha toward zero, so a row
# we know nothing about is harder to trigger a signal on, never easier.
# The previous default did the opposite — see ``_dispersion_for_row``.
_UNMEASURED_LIQUIDITY_USES_CLIP_LO = True


@dataclass(frozen=True)
class MarketView:
    """One asset's market picture, on the shared 0-10000 scale.

    ``dispersion`` and ``liquidity`` are ``None`` when the row carries no
    dispersion measurement.  They are deliberately NOT defaulted to a
    number: absent, zero and unmeasured are three different things, and
    collapsing them is how the defect in ``_dispersion_for_row`` stayed
    invisible.
    """

    market_value: float | None
    market_source: str | None
    market_type: str | None
    dispersion: float | None  # 0-1 cross-source disagreement; None = unmeasured
    liquidity: float | None  # None = unmeasured, NOT "zero liquidity"
    normalization_version: str = NORMALIZATION_VERSION


def market_view_for_row(
    contract_row: Mapping[str, Any],
    group: str,
    params: ParamSet,
) -> MarketView:
    """Extract the market anchor for one contract row.

    Offense + picks anchor on KTC SF-TEP; IDP anchors on IDPTradeCalc.
    A missing anchor yields ``market_value=None`` — gap/alpha are then
    omitted entirely rather than fabricated (§9.5).
    """
    site_values = contract_row.get("canonicalSiteValues") or {}
    if group in _IDP_GROUPS:
        source_order = ("idpTradeCalc",)
    else:
        source_order = ("ktcSfTep", "ktc")
    value: float | None = None
    source: str | None = None
    for key in source_order:
        raw = site_values.get(key)
        if raw is None:
            continue
        try:
            value = float(raw)
            source = key
            break
        except (TypeError, ValueError):
            continue

    dispersion = _dispersion_for_row(contract_row)
    liq_cfg = params["market"]["liquidity"]
    # Dispersion SUBTRACTS from liquidity (audit M7, landed on main
    # 2026-08-04).  Cross-source disagreement about a price makes an
    # asset harder to transact, not easier, and must move the same
    # direction as its effect on ``tau_market`` below.  The additive
    # form meant one number read as "liquid" here and "unreliable"
    # there.
    #
    # ``None`` when dispersion was never measured — see
    # ``_dispersion_for_row``.  Not a number: absent, zero and
    # unmeasured are three different things.
    liquidity: float | None = None
    if dispersion is not None:
        liquidity = min(
            float(liq_cfg["clip_hi"]),
            max(
                float(liq_cfg["clip_lo"]),
                float(liq_cfg["base"]) - float(liq_cfg["dispersion_coeff"]) * dispersion,
            ),
        )
    return MarketView(
        market_value=value,
        market_source=source,
        market_type=VALUE_MARKET_SOURCES.get(source or "", None),
        dispersion=dispersion,
        liquidity=liquidity,
    )


def _dispersion_for_row(row: Mapping[str, Any]) -> float | None:
    """Cross-source disagreement for one row, or ``None`` if unmeasured.

    ONE field, deliberately.  Until 2026-08-04 this read
    ``marketDispersionCV``, fell back to ``sourceRankPercentileSpread``,
    and otherwise returned a hardcoded ``0.20`` — three incommensurable
    numbers poured into the one slot the liquidity and precision params
    were calibrated against.

    Measured on the pinned 2026-07-30 contract:

    * The two fields are different STATISTICS.  On the 684 rows carrying
      both, ``sourceRankPercentileSpread`` is a median **4.03x** larger
      than ``marketDispersionCV`` (p10 1.46x, p90 8.61x).  A coefficient
      of variation and a percentile spread are not interchangeable.
    * ``0.20`` sits near the **maximum** of the real CV scale (observed
      max 0.263, median 0.0215).  So "we could not measure this" was
      being read as "this asset is maximally dispersed".

    WHAT THE FIX IS, AND WHAT IT IS NOT
    ===================================
    The scale substitution is the durable half: a percentile spread is
    not a coefficient of variation, and feeding one where the params
    were calibrated for the other silently reprices every row that
    lacks a CV.  Under the current SUBTRACT form that shows up as
    liquidity 0.845 for a median-spread row against 0.966 for a
    median-CV row — same asset, different statistic, different answer.

    The hardcoded ``0.20`` is the other half: it invents a measurement.
    Its DIRECTION of harm depends on the liquidity formula, and that
    formula changed under this fix.  Measured on the pinned 2026-07-30
    contract under the current ``clip(1.0 - 1.6 x d, 0.2, 1.0)``:

        typical measured CV 0.0215  ->  liquidity 0.966
        percentile-spread   0.0968  ->  liquidity 0.845
        hardcoded           0.20    ->  liquidity 0.680

    So today an unmeasured row is scored LESS liquid than a typical
    measured one, not more.  Under the previous ADDITIVE form
    (``0.35 + 1.6 x d``) the same constant did the opposite — it put
    unmeasured rows at 0.68 against a measured median of 0.384, making
    absence the strongest liquidity signal on the board.  That is the
    point worth keeping: a fabricated input's harm flips sign with a
    formula change nobody re-derived it against, which is exactly why
    it must not be fabricated at all.

    KNOWN, SEPARATELY: the ``strong_buy_min_liquidity`` gate of 0.5 is
    currently DECORATIVE for measured rows.  The worst observable CV
    (0.263) still yields 0.579, so no measured row can fail it — 833 of
    833 clear.  Fixing that is a threshold-calibration question, logged
    rather than silently re-tuned here.

    Returning ``None`` keeps unmeasured distinguishable downstream.  It
    is NOT 0.0: zero dispersion means "every source agrees", which is
    the strongest possible statement about a row and the exact opposite
    of knowing nothing.
    """
    v = row.get("marketDispersionCV")
    if v is None:
        return None
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return None


def market_comparison(
    fundamental_trade_values: Mapping[str, float],
    view: MarketView,
    params: ParamSet,
    *,
    is_idp: bool,
    is_rookie: bool,
    small_sample: float = 0.0,
) -> dict[str, Any]:
    """Gap / alpha / market-adjusted outputs for one completed valuation.

    ``fundamental_trade_values`` MUST already be computed — this
    function cannot run first, and it never writes into them.
    """
    if not fundamental_trade_values:
        raise MarketIsolationError(
            "market_comparison called before fundamental values were computed"
        )
    fund_balanced = float(fundamental_trade_values.get("balanced", 0.0))
    mcfg = params["market"]

    # Unmeasured dispersion stays visible as None in the payload rather
    # than being rendered as a number a reader would trust.
    liq_cfg = mcfg["liquidity"]
    liquidity_measured = view.liquidity is not None
    # For the alpha SCALE only, an unmeasured row is treated as the
    # least-liquid end of the band.  This shrinks its alpha toward zero
    # (harder to trigger any signal), where the old hardcoded 0.20
    # inflated it.  BUY/SELL keep working for these rows — "degrade,
    # never fail" — while the liquidity GATE below fails closed.
    effective_liquidity = float(view.liquidity) if liquidity_measured else float(liq_cfg["clip_lo"])

    out: dict[str, Any] = {
        "marketValue": None,
        "marketSource": view.market_source,
        "marketType": view.market_type,
        "marketDispersion": round(view.dispersion, 4) if view.dispersion is not None else None,
        "liquidity": round(view.liquidity, 4) if liquidity_measured else None,
        "liquidityMeasured": liquidity_measured,
        "normalizationVersion": view.normalization_version,
        "gap": None,
        "alpha": None,
        "marketAdjusted": None,
        "tradeClearing": None,
        "blendWeightModel": None,
    }
    if view.market_value is None:
        return out

    market_tv = float(view.market_value)
    gap = fund_balanced - market_tv
    alpha = gap * effective_liquidity

    # Bayesian-style precision blend weight (reference §5.10).
    tau_market = 1.0
    if is_idp:
        tau_market *= float(mcfg["tau_market_idp_mult"])
    if is_rookie:
        tau_market *= float(mcfg["tau_market_rookie_mult"])
    # Unmeasured dispersion contributes no adjustment here.  Inventing a
    # disagreement that was never observed would move the model/market
    # blend weight on the strength of missing data.
    if view.dispersion is not None:
        tau_market *= 1.0 - float(mcfg["tau_market_dispersion_mult"]) * view.dispersion
    tau_model = float(mcfg["tau_model"]) * (
        1.0 - float(mcfg["tau_model_small_sample_mult"]) * small_sample
    )
    w_model = tau_model / max(1e-9, tau_model + tau_market)

    lam_display = float(mcfg["lambda_market_display"])
    lam_clearing = float(mcfg["lambda_market_clearing"])
    out.update(
        {
            "marketValue": market_tv,
            "gap": round(gap, 1),
            "alpha": round(alpha, 1),
            # MA = FUND + λ·(MARKET − FUND); fundamental itself is λ=0.
            "marketAdjusted": round(fund_balanced + lam_display * (market_tv - fund_balanced), 1),
            "tradeClearing": round(fund_balanced + lam_clearing * (market_tv - fund_balanced), 1),
            "blendWeightModel": round(w_model, 4),
        }
    )
    return out


def buy_hold_sell(
    market_out: Mapping[str, Any],
    params: ParamSet,
    *,
    gap_persisted_days: int | None = None,
    p_collapse_1y: float | None = None,
) -> dict[str, Any]:
    """Signal policy (§8.4).  Magnitude-ordered; explains itself.

    Two rules the ladder is built on, both of which it violated before
    the 2026-08-04 audit:

    * **Every state has a magnitude floor, and the ladder is walked by
      magnitude.**  The collapse probability ESCALATES a sell that
      already clears the sell bar; it does not create one.  It used to
      be tested first, on ``alpha < 0`` alone, so a one-point negative
      gap fired the loudest signal in the model.
    * **``gap_persisted_days`` is an optional strengthener, not a
      precondition.**  Nothing in the platform stores gap history, so no
      caller can supply it — and requiring it made STRONG_BUY (a state
      ``ACTIONABLE_BDVM_SIGNALS`` alerts on) unreachable, with
      ``strong_buy_alpha`` and ``strong_buy_min_liquidity`` inert.  With
      no history the strong-buy bar is magnitude + liquidity, symmetric
      with STRONG_SELL's magnitude bar; a caller that DOES have history
      still gets the momentum guard.
    """
    alpha = market_out.get("alpha")
    if alpha is None:
        return {"signal": "NO_MARKET", "reason": "no market anchor for this asset"}
    th = params["market"]["signal_thresholds"]
    # A liquidity-gated signal requires a MEASURED liquidity.  Explicit
    # rather than relying on ``None -> 0.0`` happening to fall below the
    # threshold: that coincidence reverses silently if the threshold
    # ever moves below the clip floor, and "unmeasured" must fail this
    # gate on purpose rather than by arithmetic accident.
    liquidity_measured = bool(
        market_out.get("liquidityMeasured", market_out.get("liquidity") is not None)
    )
    raw_liquidity = market_out.get("liquidity")
    liquidity = float(raw_liquidity) if raw_liquidity is not None else 0.0
    persisted = gap_persisted_days is None or gap_persisted_days >= int(th["gap_persistence_days"])
    if alpha > float(th["buy_alpha"]):
        if not persisted:
            return {
                "signal": "HOLD",
                "reason": "positive gap but not yet persistent (momentum guard)",
            }
        if (
            alpha > float(th["strong_buy_alpha"])
            and liquidity_measured
            and liquidity > float(th["strong_buy_min_liquidity"])
        ):
            return {"signal": "STRONG_BUY", "reason": f"alpha {alpha:+.0f}, liquid market"}
        return {"signal": "BUY", "reason": f"alpha {alpha:+.0f}"}
    if alpha < float(th["sell_alpha"]):
        if alpha < float(th["strong_sell_alpha"]):
            return {"signal": "STRONG_SELL", "reason": f"alpha {alpha:+.0f}"}
        if p_collapse_1y is not None and p_collapse_1y > 0.5:
            return {
                "signal": "STRONG_SELL",
                "reason": f"alpha {alpha:+.0f} and collapse probability {p_collapse_1y:.0%}",
            }
        return {"signal": "SELL", "reason": f"alpha {alpha:+.0f}"}
    return {"signal": "HOLD", "reason": f"alpha {alpha:+.0f} inside hold band"}
