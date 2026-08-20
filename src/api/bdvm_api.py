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
from src.bdvm.actuals import nfl_projection_season
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
# In-season actuals change WEEKLY, so unlike context/schedule this
# cache keys on (season, UTC day) — a failed or preseason-empty fetch
# is retried the next day, and the day rides the ingest layer's 24h
# disk TTL underneath.
_actuals_cache: dict[tuple[int, str], tuple[int | None, Mapping[str, Any]]] = {}


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

        # REQUEST PATH: cache-only, never a fetch.  A cold call here is
        # six seasons of weekly stats plus six of snap counts (~270,000
        # rows); parsing that in the serving process is what starved
        # /api/data past the Next bridge's 4s idle timeout.
        ctx = fetch_and_build_context(season, cache_only=True)
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

        sched = fetch_team_weeks(season, cache_only=True) or None
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm: schedule unavailable: %s", exc)
        sched = None
    with _aux_lock:
        _schedule_cache[season] = sched
    return sched


def _events_fingerprint(season: int) -> tuple[int, int] | None:
    """(mtime_ns, size) of the season's events file, or None.

    Joins the values cache key so writing/editing
    ``data/bdvm/events/<season>.json`` (the daily news→events ingest,
    or a hand edit) invalidates cached valuations — without this, a
    new event would sit unseen until the next contract rebuild.
    """
    try:
        from src.bdvm.events import EVENTS_DIR  # noqa: PLC0415

        stat = (EVENTS_DIR / f"{season}.json").stat()
        return (stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None
    except Exception:  # noqa: BLE001
        return None


def _today() -> str:
    from datetime import datetime, timezone  # noqa: PLC0415

    return datetime.now(timezone.utc).date().isoformat()


def _actuals_for(contract: Mapping[str, Any]) -> tuple[int | None, Mapping[str, Any]]:
    """In-progress-season weekly actuals, cached per (season, UTC day).

    The season is the CALENDAR NFL season (``current_nfl_season``),
    never the contract's ``currentDraftYear`` — the draft year points
    one season ahead for the entire Sept–Jan window, which would make
    the posterior structurally unreachable in production.

    A fetch that RAISES is returned but NOT memoized: a transient
    nflverse/network blip on the day's first request must not pin the
    board to preseason values until midnight.  (An empty SUCCESS is
    cached for the day — that's the honest preseason/early-window
    signal.)
    """
    from src.bdvm.actuals import current_nfl_season  # noqa: PLC0415

    nfl_season = current_nfl_season()
    if nfl_season is None:
        return (None, {})
    cache_key = (nfl_season, _today())
    with _aux_lock:
        if cache_key in _actuals_cache:
            return _actuals_cache[cache_key]
    try:
        from src.bdvm.actuals import fetch_current_season_actuals  # noqa: PLC0415
        from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

        scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
        result = fetch_current_season_actuals(
            scoring,
            name_normalizer=normalize_player_name,
            season=nfl_season,
            cache_only=True,
        )
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm: in-season actuals unavailable (not cached, will retry): %s", exc)
        return (None, {})
    with _aux_lock:
        # Drop stale day entries so the cache never grows unbounded.
        for old_key in [k for k in _actuals_cache if k[1] != cache_key[1]]:
            _actuals_cache.pop(old_key, None)
        _actuals_cache[cache_key] = result
    return result


# Operational states for the cache-only auxiliary inputs.  Deliberately
# the plain words the rest of this repo already uses for evidence, not a
# new vocabulary: an artifact is there and current, there and old, or not
# there.  NONE of them means zero — a missing input degrades the engine to
# the neutral priors it has always used when a fetch failed.
AUX_AVAILABLE = "available"
AUX_STALE = "stale"
AUX_MISSING = "missing"


def _aux_state(key: str, ttl_seconds: float) -> dict[str, Any]:
    """Report one cache-only input's presence and age — never its value.

    The request path may serve a TTL-EXPIRED artifact (the TTL governs
    when the refresh owner should re-fetch, not whether an older artifact
    is readable), so "stale" must be visible rather than silently
    presented as current.  ``fetched_at`` has always been written by
    ``nfl_data.cache.put``; this only reads it back.
    """
    from src.nfl_data import cache as nfl_cache  # noqa: PLC0415

    age = nfl_cache.entry_age_seconds(key)
    if age is None:
        return {"state": AUX_MISSING, "ageSeconds": None}
    return {
        "state": AUX_STALE if age > ttl_seconds else AUX_AVAILABLE,
        "ageSeconds": round(age, 1),
    }


def _auxiliary_input_report(season: int, actuals_season: int | None) -> dict[str, Any]:
    """Freshness/provenance for every input the request path reads locally.

    Published so a consumer can tell "BDVM is running on a week-old
    player context" from "BDVM is current" — and both from "the artifact
    is absent and the engine is on neutral priors".
    """
    from src.nfl_data import ingest  # noqa: PLC0415

    years = list(range(season - 6, season))
    year_key = ",".join(str(y) for y in years)
    report: dict[str, Any] = {
        "policy": "cache_only_request_path",
        "refreshOwner": "scripts/refresh_bdvm_inputs.py (scheduled, out of band)",
        "idMap": _aux_state("id_map", ingest._ROSTERS_TTL),
        "weeklyStats": _aux_state(f"weekly_stats:{year_key}", ingest._WEEKLY_STATS_TTL),
        "snapCounts": _aux_state(f"snap_counts:{year_key}", ingest._SNAP_COUNTS_TTL),
        "schedules": _aux_state(f"schedules:{season}", ingest._SCHEDULES_TTL),
    }
    if actuals_season is not None:
        report["currentSeasonActuals"] = _aux_state(
            f"weekly_stats:{actuals_season}", ingest._WEEKLY_STATS_TTL
        )
    return report


def get_bdvm_values(
    contract: Mapping[str, Any],
    league_key: str,
    *,
    surplus_mode: str = "option",
    params: ParamSet | None = None,
) -> dict[str, Any]:
    """Compute (or serve cached) BDVM values for one league."""
    params = params or load_param_set()
    # The NFL season, resolved the SAME way ``run_valuation`` resolves it
    # (never the contract's rookie-draft year) — this season keys the
    # snapshot lookup, the player context, the schedule and the events
    # fingerprint, so a different answer here than in the service would
    # cache and enrich one season while valuing another.
    season = nfl_projection_season()
    snapshot = latest_snapshot_path(season)
    # Without a projection snapshot ``run_valuation`` can price nothing and
    # returns its "no snapshot" status, so the nflverse actuals fetch below
    # — the better part of a minute on a cold cache — buys nothing at all.
    # Ask whether the answer is reachable before paying for an input to it.
    actuals = _actuals_for(contract) if snapshot else (None, {})
    key = (
        id(contract),
        contract.get("generatedAt"),
        league_key,
        params.param_set_id,
        str(snapshot) if snapshot else None,
        surplus_mode,
        # In-season freshness: a new observed week (or day rollover
        # after one) must recompute; events-file edits are covered by
        # the fingerprint.
        actuals[0],
        _today() if actuals[0] is not None else None,
        _events_fingerprint(season),
    )
    with _lock:
        cached = _values_cache.get(key)
        if cached is not None:
            _values_cache.move_to_end(key)
            return cached

    roster_settings, idp_enabled, scoring_profile = _registry_settings_for(league_key)
    context = _context_for(season)
    schedule_weeks = _schedule_for(season)
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
        actuals=actuals,
    )
    # Operational metadata only — never a methodology input.  Stamped
    # here rather than inside ``run_valuation`` so the engine's inputs and
    # its arithmetic are untouched by this repair: for identical
    # materialised inputs the payload is byte-equivalent apart from this
    # block.
    if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
        payload["meta"]["auxiliaryInputs"] = _auxiliary_input_report(season, actuals[0])
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


def get_bdvm_trade_eval(
    contract: Mapping[str, Any],
    league_key: str,
    *,
    side_a: list[Any],
    side_b: list[Any],
    params: ParamSet | None = None,
) -> dict[str, Any]:
    """CES evaluation of ONE specific trade in every strategy currency.

    ``side_a`` / ``side_b`` are asset refs: dicts with ``playerId`` or
    ``name``, or plain strings (player names or pick names like
    "2027 1.05").  Resolution is playerId-first, then normalized name,
    then the pick table.  Unresolvable refs are REPORTED, never
    silently priced at zero — a trade grade that quietly dropped an
    asset would be worse than no grade.

    Package math is the display-layer CES (never a plain sum — §3.13);
    when both sides' rosters are known to the BDVM roster analysis,
    the own-currency double-positive verdict is included.
    """
    params = params or load_param_set()
    values = get_bdvm_values(contract, league_key, params=params)
    if values.get("status") != "ok":
        return {
            "status": values.get("status"),
            "message": values.get("message"),
            "byStrategy": {},
        }

    from src.bdvm.trade_math import package_value  # noqa: PLC0415
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    strategies = [s for s in ("contender", "balanced", "rebuilder", "risk_neutral")]
    by_id: dict[str, dict] = {}
    by_name: dict[str, dict] = {}
    for p in values.get("players") or []:
        pid = str(p.get("playerId") or "")
        if pid:
            by_id[pid] = p
        name = str(p.get("name") or "")
        if name:
            by_name[normalize_player_name(name)] = p
    picks_by_name = {
        str(p.get("name") or "").lower(): p
        for p in values.get("picks") or []
        if p.get("distribution")
    }

    def _resolve(ref: Any) -> tuple[dict | None, str, str]:
        """(strategy→value source dict, kind, label) or (None, 'unresolved', label)."""
        if isinstance(ref, Mapping):
            pid = str(ref.get("playerId") or "").strip()
            label = str(ref.get("name") or pid)
            if pid and pid in by_id:
                return by_id[pid], "player", label
            name = str(ref.get("name") or "").strip()
        else:
            name = str(ref or "").strip()
            label = name
        if not name:
            return None, "unresolved", label
        player = by_name.get(normalize_player_name(name))
        if player is not None:
            return player, "player", name
        pick = picks_by_name.get(name.lower())
        if pick is not None:
            return pick, "pick", name
        return None, "unresolved", name

    def _side_values(refs: list[Any]) -> tuple[dict[str, list[float]], list[str], list[dict]]:
        per_strategy: dict[str, list[float]] = {s: [] for s in strategies}
        unresolved: list[str] = []
        resolved: list[dict] = []
        for ref in refs or []:
            asset, kind, label = _resolve(ref)
            if asset is None:
                unresolved.append(label)
                continue
            entry: dict[str, Any] = {"name": label, "kind": kind, "values": {}}
            for s in strategies:
                if kind == "player":
                    v = float((asset.get("tradeValue") or {}).get(s) or 0.0)
                else:
                    v = float(((asset.get("distribution") or {}).get(s) or {}).get("ev") or 0.0)
                per_strategy[s].append(v)
                entry["values"][s] = round(v, 1)
            resolved.append(entry)
        return per_strategy, unresolved, resolved

    a_vals, a_unresolved, a_assets = _side_values(side_a)
    b_vals, b_unresolved, b_assets = _side_values(side_b)

    by_strategy: dict[str, dict[str, float]] = {}
    for s in strategies:
        pkg_a = package_value(a_vals[s], params)
        pkg_b = package_value(b_vals[s], params)
        total = max(1.0, pkg_a + pkg_b)
        by_strategy[s] = {
            "sideA": round(pkg_a, 1),
            "sideB": round(pkg_b, 1),
            "edge": round(pkg_a - pkg_b, 1),
            "edgePct": round(100.0 * (pkg_a - pkg_b) / total, 1),
        }

    return {
        "status": "ok",
        "byStrategy": by_strategy,
        "sideAAssets": a_assets,
        "sideBAssets": b_assets,
        "unresolved": {"sideA": a_unresolved, "sideB": b_unresolved},
        "meta": {
            "packageMath": "ces",
            "valuationAsOf": (values.get("meta") or {}).get("asOf"),
            "paramSetId": (values.get("meta") or {}).get("paramSetId"),
        },
    }


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
        _actuals_cache.clear()
