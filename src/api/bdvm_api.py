"""API adapter for the BDVM fundamental valuation engine.

Thin, cached bridge between ``server.py`` and ``src/bdvm``.  The heavy
lifting (projection consensus, replacement solve, per-player paths)
runs in a threadpool from the route; results are cached per (contract
build, league, param set, snapshot, surplus mode) so repeat requests
are free until the board or the projections change.

Player context (nflverse id map + career loads) and the season schedule
are fetched lazily, cached per season in-process, and degrade to None —
a network failure narrows the output (no ROS block, contract-only ages)
instead of breaking the board.

READ-ONLY with respect to the live contract: BDVM never mutates
``latest_contract_data`` and never writes into ``rankDerivedValue``.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Mapping

from src.api import league_registry as _league_registry
from src.bdvm.params import ParamSet, load_param_set
from src.bdvm.projections import latest_snapshot_path
from src.bdvm.roster import analyze_rosters, scan_double_positive_trades
from src.bdvm.service import run_valuation

_LOGGER = logging.getLogger(__name__)

_lock = threading.Lock()
# Small LRU, not a single slot: the roster/trades path always computes
# with the default surplus mode while /api/bdvm/values may carry a
# non-default one — a single-entry cache would make those two keys
# evict each other on every alternation, turning each request into a
# cold multi-second engine run.
_VALUES_CACHE_MAX = 4
_values_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()

_aux_lock = threading.Lock()
_context_cache: dict[int, Mapping[str, Any]] = {}
_schedule_cache: dict[int, Mapping[str, Any] | None] = {}


def _registry_settings_for(league_key: str) -> tuple[Mapping[str, Any] | None, bool, str]:
    try:
        cfg = _league_registry.get_league_by_key(league_key)
    except Exception:
        cfg = None
    if cfg is None:
        return None, True, ""
    return cfg.roster_settings, bool(cfg.idp_enabled), str(cfg.scoring_profile or "")


def _context_for(season: int) -> Mapping[str, Any]:
    with _aux_lock:
        if season in _context_cache:
            return _context_cache[season]
    try:
        from src.bdvm.context import fetch_and_build_context  # noqa: PLC0415

        ctx = fetch_and_build_context(season)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm: context unavailable: %s", exc)
        ctx = {}
    with _aux_lock:
        _context_cache[season] = ctx
    return ctx


def _schedule_for(season: int) -> Mapping[str, Any] | None:
    with _aux_lock:
        if season in _schedule_cache:
            return _schedule_cache[season]
    try:
        from src.bdvm.schedule import fetch_team_weeks  # noqa: PLC0415

        sched = fetch_team_weeks(season) or None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm: schedule unavailable: %s", exc)
        sched = None
    with _aux_lock:
        _schedule_cache[season] = sched
    return sched


def get_bdvm_values(
    contract: Mapping[str, Any],
    league_key: str,
    *,
    surplus_mode: str = "option",
    params: ParamSet | None = None,
) -> dict[str, Any]:
    """Compute (or serve cached) BDVM values for one league."""
    params = params or load_param_set()
    season = int(contract.get("currentDraftYear") or 0)
    snapshot = latest_snapshot_path(season) if season else None
    key = (
        id(contract),
        contract.get("generatedAt"),
        league_key,
        params.param_set_id,
        str(snapshot) if snapshot else None,
        surplus_mode,
    )
    with _lock:
        cached = _values_cache.get(key)
        if cached is not None:
            _values_cache.move_to_end(key)
            return cached

    roster_settings, idp_enabled, scoring_profile = _registry_settings_for(league_key)
    context = _context_for(season) if season else {}
    schedule_weeks = _schedule_for(season) if season else None
    payload = run_valuation(
        contract,
        league_key=league_key,
        params=params,
        registry_roster_settings=roster_settings,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        surplus_mode=surplus_mode,
        context=context,
        schedule_weeks=schedule_weeks,
    )
    with _lock:
        _values_cache[key] = payload
        _values_cache.move_to_end(key)
        while len(_values_cache) > _VALUES_CACHE_MAX:
            _values_cache.popitem(last=False)
    return payload


def get_bdvm_roster(
    contract: Mapping[str, Any],
    league_key: str,
    *,
    params: ParamSet | None = None,
) -> dict[str, Any]:
    """Per-roster BDVM aggregates for the league's Sleeper teams."""
    params = params or load_param_set()
    values = get_bdvm_values(contract, league_key, params=params)
    if values.get("status") != "ok":
        return {"status": values.get("status"), "rosters": [], "message": values.get("message")}
    league_meta = {k: values["meta"].get(k) for k in ("configHash",)}
    # starters/flex come from the same league config the valuation used
    from src.bdvm.league_config import from_contract  # noqa: PLC0415

    roster_settings, idp_enabled, scoring_profile = _registry_settings_for(league_key)
    waiver_cfg = params["replacement"]
    cfg = from_contract(
        contract,
        league_key=league_key,
        registry_roster_settings=roster_settings,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        waiver_buffer=waiver_cfg["waiver_buffer"],
        default_buffer=float(waiver_cfg["default_buffer"]),
    )
    analysis = analyze_rosters(values, contract, params, league_cfg_meta=cfg.to_meta())
    analysis["status"] = "ok"
    analysis["meta"] = {
        **analysis.get("meta", {}),
        **league_meta,
        "valuationAsOf": values["meta"].get("asOf"),
    }
    return analysis


def get_bdvm_trades(
    contract: Mapping[str, Any],
    league_key: str,
    *,
    team: str | None = None,
    params: ParamSet | None = None,
) -> dict[str, Any]:
    """Double-positive trade scan over the league's rosters."""
    params = params or load_param_set()
    analysis = get_bdvm_roster(contract, league_key, params=params)
    if analysis.get("status") != "ok":
        return {"status": analysis.get("status"), "trades": [], "message": analysis.get("message")}
    scan = scan_double_positive_trades(analysis, params, team=team)
    scan["status"] = "ok" if "error" not in scan else "error"
    return scan


def reset_cache() -> None:
    """Test hook."""
    with _lock:
        _values_cache.clear()
    with _aux_lock:
        _context_cache.clear()
        _schedule_cache.clear()
