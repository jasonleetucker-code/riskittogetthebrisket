"""Consensus Edge over the LIVE contract, and its HTTP surface.

The formula lives here and only here. Nothing in ``frontend/`` recomputes a
score, a classification or a confidence — this repository already has a hard
rule against a second ranking engine on the client, and a buy/sell label
computed in two places drifts into two different products.

SHADOW MODE. ``/api/consensus-edge/*`` is registered but every payload carries
``shadow: true`` and ``weightsValidated: false``. The weights are unfitted (see
``score.py``), the 30-day horizon scored only one out-of-sample fold, and Sharp
Flow has no history to validate against at all. The endpoints exist so the
system can be compared against the incumbents on live data — which is the step
that would earn promotion — not because it has earned it.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from src.edge import components as edge_components
from src.edge import history as edge_history
from src.edge import score as edge_score

log = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_NO_CONTRACT = "no_contract"

#: Which live contract field carries the acquisition-market price per asset
#: class. Resolved through ``edge_history.market_anchor_for`` so the panel and
#: the live path can never disagree about what "the market" means.
_MARKET_FIELD = "canonicalSiteValues"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _latest_contract() -> Mapping[str, Any] | None:
    """The loaded contract, or None. Never fabricates one."""
    for module_name in ("server", "__main__"):
        module = sys.modules.get(module_name)
        contract = getattr(module, "latest_contract_data", None)
        if isinstance(contract, Mapping) and contract.get("playersArray"):
            return contract
    return None


def _asset_class(row: Mapping[str, Any]) -> str:
    position = str(row.get("position") or "").strip().upper()
    return "idp" if position in {"DL", "LB", "DB"} else "offense"


def _market_value(row: Mapping[str, Any], asset_class: str) -> tuple[float | None, str]:
    """The acquisition-market price and its source, or (None, reason).

    A missing market price is returned as None so the caller can render
    ``No Market Price``. It must never fall back to the other asset class's
    board: KTC publishes no IDP players, so an offense anchor for a defender is
    not a degraded answer, it is a wrong one.
    """
    anchor = edge_history.market_anchor_for(asset_class)
    site_values = row.get(_MARKET_FIELD) or {}
    if isinstance(site_values, Mapping):
        raw = site_values.get(anchor)
        if isinstance(raw, (int, float)) and raw > 0:
            return float(raw), anchor
    return None, anchor


def _fair_value(row: Mapping[str, Any], anchor: str) -> tuple[float | None, int, list[str]]:
    """Leave-one-out consensus over the row's own per-source values.

    Reads ``sourceRankMeta[key].valueContribution`` — NOT ``canonicalSiteValues``.

    That distinction is not stylistic. For the 17 rank-signal sources
    (``rank_signal_source_keys()``) the ``canonicalSiteValues`` slot holds a
    SYNTHETIC RANK ENCODING of the form ``999900 - rank*100`` — six-digit
    bookkeeping numbers, not prices. Averaging those alongside KTC's native
    0-9999 values produces a "fair value" hundreds of times the market and a
    gap of +6.7 in log space, which is what the first version of this function
    did: every top-of-board name came out a Buy and several large POSITIVE gaps
    were ranked as Sells because the cohort statistics had been poisoned too.

    ``data_contract.rank_signal_source_keys`` documents this trap explicitly and
    records that it has already caused two shipped bugs (trade dispersion CV;
    rankings copy/export, both fixed in PR #530). This was the third.

    ``valueContribution`` is the number that source actually contributed to the
    blend, on the common 0-9999 scale, for value-direct and rank-signal sources
    alike. Returns ``(value, source_count, contributing_sources)``.
    """
    meta = row.get("sourceRankMeta") or {}
    if not isinstance(meta, Mapping):
        return None, 0, []
    from src.edge.panel import MARKET_DERIVED_SOURCES

    contributions: list[float] = []
    used: list[str] = []
    for key, entry in meta.items():
        if key in MARKET_DERIVED_SOURCES:
            continue
        if not isinstance(entry, Mapping):
            continue
        value = entry.get("valueContribution")
        if isinstance(value, (int, float)) and value > 0:
            contributions.append(float(value))
            used.append(str(key))
    if not contributions:
        return None, 0, []
    from src.api.data_contract import count_aware_mean_median_blend

    centre, _mad = count_aware_mean_median_blend(contributions)
    return float(centre), len(contributions), sorted(used)


def sharp_activity_index(window: str = "30d") -> dict[str, dict[str, Any]]:
    """Qualified-cohort activity per asset, keyed by normalized display name.

    Reuses ``sharp.market.market_payload`` rather than re-querying the ledger:
    that function already applies the qualified-cohort filter, the trade-only
    tx-type filter, cross-platform canonicalisation and the person-level
    consensus. A second aggregation here would be a fifth Sleeper-derived
    counting path in this repository and would drift from the Sharp Tracker
    page within a release.

    Returns an EMPTY dict when there is no data, and the caller must treat that
    as "unknown", never as "no sharp traded him".
    """
    try:
        from src.sharp import market as sharp_market

        payload = sharp_market.market_payload(
            window=window, asset_type="player", limit=500, qualification="all"
        )
    except Exception:  # noqa: BLE001 — an optional input must never break the board
        log.exception("consensus edge: sharp activity unavailable")
        return {}

    index: dict[str, dict[str, Any]] = {}
    for asset in payload.get("assets") or []:
        name = str(asset.get("displayName") or "").strip()
        if not name:
            continue
        index[_normalized(name)] = asset
    return index


def _normalized(name: str) -> str:
    from src.utils.name_clean import resolve_canonical_name

    return resolve_canonical_name(name)


def build_player_result(
    row: Mapping[str, Any],
    *,
    cohort_gaps: Mapping[str, Sequence[float]],
    sharp_index: Mapping[str, Mapping[str, Any]] | None = None,
) -> edge_score.EdgeResult | None:
    """One player's Consensus Edge result, or None if he cannot be priced."""
    import math

    name = str(row.get("displayName") or row.get("canonicalName") or "").strip()
    if not name:
        return None
    asset_class = _asset_class(row)
    market_value, anchor = _market_value(row, asset_class)
    fair_value, source_count, _used = _fair_value(row, anchor)

    log_gap: float | None = None
    if market_value and fair_value and market_value > 0 and fair_value > 0:
        from src.edge.panel import LOG_GAP_EPSILON

        log_gap = math.log((fair_value + LOG_GAP_EPSILON) / (market_value + LOG_GAP_EPSILON))

    position = str(row.get("position") or "").strip().upper() or None
    key = edge_components.cohort_key(position, asset_class, market_value or 0.0)

    built: dict[str, edge_components.ComponentScore] = {
        "mispricing": edge_components.mispricing_component(
            log_gap=log_gap,
            cohort_gaps=cohort_gaps.get(key, ()),
            fair_value_source_count=source_count,
            fair_value_dispersion=None,
            market_is_stale=False,
        ),
        "momentum": edge_components.momentum_component(
            trailing_log_change_30d=None,
            trailing_log_change_7d=None,
        ),
        "data_quality": edge_components.data_quality_component(
            market_is_stale=False,
            market_age_days=0,
            fair_value_available=fair_value is not None,
            sharp_available=bool((sharp_index or {}).get(_normalized(name))),
            position_known=position is not None,
        ),
    }
    sharp = (sharp_index or {}).get(_normalized(name))
    if sharp:
        person = sharp.get("personConsensus") or {}
        built["sharp_flow"] = edge_components.sharp_flow_component(
            buys=int(sharp.get("buys") or 0),
            sells=int(sharp.get("sells") or 0),
            unique_managers=int(sharp.get("uniqueManagers") or 0),
            unique_leagues=int(sharp.get("uniqueLeagues") or 0),
            # One person's many leagues are one opinion. ``consensus.py``
            # already measured this; passing it through means a single
            # prolific trader cannot manufacture a confident signal.
            manager_concentration=person.get("networkConcentration"),
        )

    result = edge_score.evaluate(player_key=name, components=built)
    if market_value is None:
        result.warnings.append("no_market_price")
    return result


def build_board() -> dict[str, Any]:
    """Consensus Edge across the whole loaded contract."""
    import math

    contract = _latest_contract()
    if contract is None:
        return {
            "status": STATUS_NO_CONTRACT,
            "shadow": True,
            "generatedAt": _utc_now_iso(),
            "modelVersion": edge_score.MODEL_VERSION,
            "weightsValidated": edge_score.WEIGHTS_VALIDATED,
            "assets": [],
            "note": "No canonical contract is loaded; Consensus Edge has nothing to price.",
        }

    rows = [row for row in contract.get("playersArray") or [] if isinstance(row, Mapping)]

    # Cohort gaps must be computed across the whole board BEFORE any row is
    # scored: a robust z-score is meaningless without its population.
    from src.edge.panel import LOG_GAP_EPSILON

    cohort_gaps: dict[str, list[float]] = {}
    for row in rows:
        asset_class = _asset_class(row)
        market_value, anchor = _market_value(row, asset_class)
        fair_value, _count, _used = _fair_value(row, anchor)
        if not market_value or not fair_value or market_value <= 0 or fair_value <= 0:
            continue
        gap = math.log((fair_value + LOG_GAP_EPSILON) / (market_value + LOG_GAP_EPSILON))
        position = str(row.get("position") or "").strip().upper() or None
        cohort_gaps.setdefault(
            edge_components.cohort_key(position, asset_class, market_value), []
        ).append(gap)

    # Computed ONCE for the whole board: market_payload is a full ledger
    # aggregation and calling it per player would be a thousand of them.
    sharp_index = sharp_activity_index()
    results = [
        result
        for result in (
            build_player_result(row, cohort_gaps=cohort_gaps, sharp_index=sharp_index)
            for row in rows
        )
        if result is not None
    ]
    positions = {
        str(row.get("displayName") or row.get("canonicalName") or ""): str(
            row.get("position") or ""
        ).upper()
        or None
        for row in rows
    }

    buys = edge_score.rank(results, direction="buy", limit=20)
    sells = edge_score.rank(results, direction="sell", limit=20)
    return {
        "status": STATUS_OK,
        # Never omitted. A consumer must be able to tell a shadow score from a
        # promoted one without reading the docs.
        "shadow": True,
        "generatedAt": _utc_now_iso(),
        "modelVersion": edge_score.MODEL_VERSION,
        "weightsValidated": edge_score.WEIGHTS_VALIDATED,
        "counts": {
            "scored": len(results),
            "withSharpActivity": len(sharp_index),
            "qualifyingBuys": len(buys),
            "qualifyingSells": len(sells),
        },
        "topBuys": [item.to_dict() for item in buys],
        "topSells": [item.to_dict() for item in sells],
        "positionLeaders": {
            "buy": {
                position: (result.to_dict() if result else None)
                for position, result in edge_score.position_leaders(
                    results, positions, direction="buy"
                ).items()
            },
            "sell": {
                position: (result.to_dict() if result else None)
                for position, result in edge_score.position_leaders(
                    results, positions, direction="sell"
                ).items()
            },
        },
        "note": (
            "SHADOW MODE. Weights are provisional and unfitted: only the mispricing "
            "component has out-of-sample evidence, Sharp Flow has no history to "
            "validate against, and the 30-day horizon scored a single fold. "
            "Compare against the incumbent signals; do not treat as promoted."
        ),
    }


def health() -> dict[str, Any]:
    """What Consensus Edge can and cannot currently answer."""
    contract = _latest_contract()
    try:
        census = edge_history.coverage(
            [edge_history.OFFENSE_MARKET_ANCHOR, edge_history.IDP_MARKET_ANCHOR]
        )
    except Exception:  # noqa: BLE001
        census = {}
    try:
        from src.intel import ledger

        movements = int(ledger.counts().get("assetMovementCount") or 0)
    except Exception:  # noqa: BLE001
        movements = 0
    return {
        "status": STATUS_OK if contract is not None else STATUS_NO_CONTRACT,
        "shadow": True,
        "generatedAt": _utc_now_iso(),
        "modelVersion": edge_score.MODEL_VERSION,
        "weightsValidated": edge_score.WEIGHTS_VALIDATED,
        "contractLoaded": contract is not None,
        "historyCensus": census,
        "shallowClone": edge_history.is_shallow(),
        "sharpMovements": movements,
        "componentReadiness": {
            "mispricing": "validated_out_of_sample_weak_positive",
            "sharp_flow": "unvalidated_no_history" if not movements else "unvalidated_has_data",
            "momentum": "context_only_never_directional",
            "opportunity_risk": "not_implemented_no_trusted_projection_feed",
        },
    }


def _server_app():
    for module_name in ("server", "__main__"):
        module = sys.modules.get(module_name)
        app = getattr(module, "app", None)
        if app is not None:
            return app
    return None


def _register_http_routes() -> None:
    """Register the shadow endpoints. Idempotent.

    Called explicitly by ``server.py`` rather than relying on this module's
    import side effect — an import-time registration silently does nothing when
    the module is already in ``sys.modules``, which is how the sharp routes once
    404'd in production with nothing logged.
    """
    app = _server_app()
    if app is None:
        return
    existing = {getattr(route, "path", None) for route in getattr(app, "routes", [])}
    if "/api/consensus-edge/top" in existing:
        return

    async def get_top(_request: Request):
        try:
            payload = await run_in_threadpool(build_board)
        except Exception as exc:  # noqa: BLE001
            log.exception("consensus edge board failed")
            return JSONResponse(
                status_code=503,
                content={"error": "consensus_edge_unavailable", "message": str(exc)},
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(content=payload, headers={"Cache-Control": "private, max-age=120"})

    async def get_health(_request: Request):
        try:
            payload = await run_in_threadpool(health)
        except Exception as exc:  # noqa: BLE001
            log.exception("consensus edge health failed")
            return JSONResponse(
                status_code=503,
                content={"error": "consensus_edge_unavailable", "message": str(exc)},
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(content=payload, headers={"Cache-Control": "no-store"})

    async def get_methodology(_request: Request):
        return JSONResponse(
            content={
                "modelVersion": edge_score.MODEL_VERSION,
                "shadow": True,
                "weightsValidated": edge_score.WEIGHTS_VALIDATED,
                "weights": edge_score.PROVISIONAL_WEIGHTS,
                "thresholds": {
                    "strongBuy": edge_score.STRONG_BUY_AT,
                    "buy": edge_score.BUY_AT,
                    "sell": edge_score.SELL_AT,
                    "strongSell": edge_score.STRONG_SELL_AT,
                    "minConfidenceAnyCall": edge_components.MIN_CONFIDENCE_FOR_ANY_CALL,
                    "minConfidenceStrongCall": edge_components.MIN_CONFIDENCE_FOR_STRONG_CALL,
                },
                "classifications": list(edge_score.CLASSIFICATIONS),
                "components": {
                    "mispricing": "Independent (market-excluded) fair value vs the acquisition market. Directional.",
                    "sharp_flow": "Beta-Binomial posterior of qualified-manager buy rate. Directional. UNVALIDATED.",
                    "momentum": "Trailing market movement. CONTEXT ONLY — never contributes to the score.",
                    "data_quality": "Coverage/freshness of the inputs. Can withhold a call.",
                },
                "knownLimitations": [
                    "Weights are provisional and were not fitted out-of-sample.",
                    "Sharp Flow has no historical data and cannot be validated.",
                    "IDP cannot be backtested: the IDP market anchor has 14 days of history.",
                    "The 30-day horizon scored only one out-of-sample fold.",
                    "The target is future MARKET movement, not league-scored production.",
                ],
            },
            headers={"Cache-Control": "private, max-age=300"},
        )

    app.add_api_route(
        "/api/consensus-edge/top", get_top, methods=["GET"], name="get_consensus_edge_top"
    )
    app.add_api_route(
        "/api/consensus-edge/health",
        get_health,
        methods=["GET"],
        name="get_consensus_edge_health",
    )
    app.add_api_route(
        "/api/consensus-edge/methodology",
        get_methodology,
        methods=["GET"],
        name="get_consensus_edge_methodology",
    )


_register_http_routes()
