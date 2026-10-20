"""Test builders for the decision engine: packet-shaped layers, no I/O."""

from __future__ import annotations

from typing import Any

from src.trade.decision_engine.contracts import TeamLayers
from src.valuation_math import package_model

GEOM = package_model.GEOM_Q078_V1
FRESH = {"asset": "fresh", "lineup": "fresh", "posture": "fresh"}


def asset_layer(
    send: list[float],
    recv: list[float],
    *,
    forced: float | None = 0.0,
    forced_state: str | None = None,
    gates: tuple[str, ...] = (),
    model: str = GEOM,
    **extra: Any,
) -> dict[str, Any]:
    send_adj, recv_adj, send_va, recv_va = package_model.adjusted_pair_totals(
        send, recv, model_id=model
    )
    state = forced_state or ("none" if forced == 0 else "exact")
    return {
        "state": "available",
        "reason": None,
        "sendValues": list(send),
        "recvValues": list(recv),
        "sendRaw": float(sum(send)),
        "recvRaw": float(sum(recv)),
        "sendAdjusted": send_adj,
        "recvAdjusted": recv_adj,
        "sendVa": send_va,
        "recvVa": recv_va,
        "vaGap": recv_adj - send_adj,
        "packageModel": {"id": model, "configState": "ACTIVE"},
        "gateCodes": list(gates),
        "forcedDropCost": forced,
        "forcedDropCostBasis": {"state": state},
        **extra,
    }


def lineup_layer(
    delta: float | None,
    *,
    se: float | None = 0.1,
    psd: float | None = None,
    basis: str = "unavailable",
    state: str = "available",
    reason: str | None = None,
    coverage: str = "full",
    before: float = 140.0,
) -> dict[str, Any]:
    return {
        "ownerId": "x",
        "beforePpg": before if delta is not None else None,
        "afterPpg": before + delta if delta is not None else None,
        "deltaPpg": delta,
        "mcStandardError": se,
        "predictiveSd": psd,
        "predictiveBasis": basis,
        "downsideQ10": None,
        "depthBefore": 3.2 if delta is not None else None,
        "depthAfter": 3.0 if delta is not None else None,
        "coverage": coverage,
        "vacatedSpotBackfill": [],
        "state": state,
        "reason": reason,
    }


def unavailable(reason: str = "provider_not_merged_batch1") -> dict[str, Any]:
    return {"state": "unavailable", "reason": reason}


def layers(
    team_id: str = "team-a",
    *,
    strategy: str | None = "WIN_NOW",
    source: str = "user",
    asset: dict[str, Any] | None = None,
    lineup: dict[str, Any] | None = None,
    title: dict[str, Any] | None = None,
    horizon: dict[str, Any] | None = None,
    roster_known: bool | None = True,
    roster_limit_known: bool | None = True,
    freshness: dict[str, str] | None = None,
    posture_label: str | None = None,
) -> TeamLayers:
    return TeamLayers(
        team_id=team_id,
        strategy=strategy,
        strategy_source=source,  # type: ignore[arg-type]
        posture_label=posture_label,
        posture_probabilities=None,
        asset=asset if asset is not None else asset_layer([5000.0], [5000.0]),
        lineup=lineup if lineup is not None else lineup_layer(0.0),
        title=title if title is not None else unavailable("basis_mismatch"),
        horizon=horizon if horizon is not None else unavailable("not_built"),
        roster_known=roster_known,
        roster_limit_known=roster_limit_known,
        freshness=dict(FRESH if freshness is None else freshness),
    )
