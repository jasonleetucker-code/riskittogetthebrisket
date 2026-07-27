"""API adapter for the BDVM fundamental valuation engine.

Thin, cached bridge between ``server.py`` and ``src/bdvm/service.py``.
The heavy lifting (projection consensus, replacement solve, per-player
paths) runs in a threadpool from the route; results are cached per
(contract build, league, param set, snapshot, surplus mode) so repeat
requests are free until the board or the projections change.

READ-ONLY with respect to the live contract: BDVM never mutates
``latest_contract_data`` and never writes into ``rankDerivedValue``.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping

from src.api import league_registry as _league_registry
from src.bdvm.params import ParamSet, load_param_set
from src.bdvm.projections import latest_snapshot_path
from src.bdvm.service import run_valuation

_lock = threading.Lock()
_cache_key: tuple | None = None
_cache_value: dict[str, Any] | None = None


def _registry_settings_for(league_key: str) -> tuple[Mapping[str, Any] | None, bool, str]:
    try:
        cfg = _league_registry.get_league_by_key(league_key)
    except Exception:
        cfg = None
    if cfg is None:
        return None, True, ""
    return cfg.roster_settings, bool(cfg.idp_enabled), str(cfg.scoring_profile or "")


def get_bdvm_values(
    contract: Mapping[str, Any],
    league_key: str,
    *,
    surplus_mode: str = "option",
    params: ParamSet | None = None,
) -> dict[str, Any]:
    """Compute (or serve cached) BDVM values for one league."""
    global _cache_key, _cache_value
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
        if key == _cache_key and _cache_value is not None:
            return _cache_value

    roster_settings, idp_enabled, scoring_profile = _registry_settings_for(league_key)
    payload = run_valuation(
        contract,
        league_key=league_key,
        params=params,
        registry_roster_settings=roster_settings,
        idp_enabled=idp_enabled,
        scoring_profile=scoring_profile,
        surplus_mode=surplus_mode,
    )
    with _lock:
        _cache_key = key
        _cache_value = payload
    return payload


def reset_cache() -> None:
    """Test hook."""
    global _cache_key, _cache_value
    with _lock:
        _cache_key = None
        _cache_value = None
