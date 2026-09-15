"""API adapter for the BDVM fundamental valuation engine.

Thin, cached bridge between ``server.py`` and ``src/bdvm``.  The heavy
lifting (projection consensus, replacement solve, per-player paths)
runs in a threadpool from the route; results are cached per (contract
build, league, param set, snapshot, surplus mode) so repeat requests
are free until the board or the projections change.

Player context (nflverse id map + career loads) and the season schedule
are loaded from local artifacts and cached by their file generations.
Missing inputs preserve the existing neutral-prior degradation. Scored
actuals also key on scoring rules and the local weekly/PBP generations.

READ-ONLY with respect to the live contract: BDVM never mutates
``latest_contract_data`` and never writes into ``rankDerivedValue``.
"""

from __future__ import annotations

import json
import logging
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Mapping

from src.api import league_registry as _league_registry
from src.bdvm.actuals import nfl_projection_season
from src.bdvm.params import ParamSet, load_param_set
from src.bdvm.projections import latest_snapshot_path
from src.bdvm.roster import analyze_rosters, scan_double_positive_trades
from src.bdvm.service import run_valuation
from src.utils.singleflight import SingleFlight

_LOGGER = logging.getLogger(__name__)

_lock = threading.Lock()
# Small LRU, not a single slot: the roster/trades path always computes
# with the default surplus mode while /api/bdvm/values may carry a
# non-default one — a single-entry cache would make those two keys
# evict each other on every alternation, turning each request into a
# cold multi-second engine run.
_VALUES_CACHE_MAX = 4
_values_cache: OrderedDict[tuple, dict[str, Any]] = OrderedDict()

_values_flights = SingleFlight()
_aux_flights = SingleFlight()
_aux_lock = threading.Lock()
_AUX_CACHE_MAX = 16
_context_cache: OrderedDict[tuple, Mapping[str, Any]] = OrderedDict()
_schedule_cache: OrderedDict[tuple, Mapping[str, Any] | None] = OrderedDict()
_actuals_cache: OrderedDict[tuple, tuple[int | None, Mapping[str, Any]]] = OrderedDict()


def _file_generation(path: Path | None) -> tuple:
    """Cheap local identity, including atomic replacement at the same path."""
    if path is None:
        return (None,)
    try:
        stat = path.stat()
        return (str(path), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino)
    except OSError:
        return (str(path), None)


def _nfl_generation(feed: str, season: int) -> tuple:
    # Acquisition owns key/path naming. Include both files: the reader requires
    # the metadata sidecar, and a refresh can replace it independently.
    from src.nfl_data import cache, ingest  # noqa: PLC0415

    paths = cache._entry_paths(cache._default_cache_dir(), ingest.cache_key(feed, [season]))
    return tuple(_file_generation(path) for path in paths)


def _context_generation(season: int) -> tuple:
    from src.bdvm.context_store import snapshot_path  # noqa: PLC0415

    return _file_generation(snapshot_path(season))


def _scoring_key(contract: Mapping[str, Any]) -> tuple:
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415

    scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
    # Keep the exact card too: compatibility normalization intentionally ignores
    # nonnumeric values, while the scoring engine may accept numeric strings.
    # Sharing must never introduce an equivalence the scorer did not promise.
    return scoring_fingerprint(scoring), json.dumps(scoring, sort_keys=True, default=str)


def _actuals_key(contract: Mapping[str, Any]) -> tuple | None:
    from src.bdvm.actuals import current_nfl_season  # noqa: PLC0415
    from src.nfl_data.pbp_weekly import pbp_weekly_path  # noqa: PLC0415

    season = current_nfl_season()
    if season is None:
        return None
    return (
        season,
        _today(),
        _scoring_key(contract),
        _nfl_generation("weekly_stats", season),
        _file_generation(pbp_weekly_path(season)),
    )


def _cached_aux(cache: OrderedDict, key: tuple, build):
    with _aux_lock:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]

    def compute():
        with _aux_lock:
            if key in cache:
                cache.move_to_end(key)
                return cache[key]
        result = build()
        with _aux_lock:
            cache[key] = result
            cache.move_to_end(key)
            while len(cache) > _AUX_CACHE_MAX:
                cache.popitem(last=False)
        return result

    return _aux_flights.run((id(cache), key), compute)[0]


def _registry_settings_for(league_key: str) -> tuple[Mapping[str, Any] | None, bool, str]:
    try:
        cfg = _league_registry.get_league_by_key(league_key)
    except Exception:
        cfg = None
    if cfg is None:
        return None, True, ""
    return cfg.roster_settings, bool(cfg.idp_enabled), str(cfg.scoring_profile or "")


def _context_for(season: int) -> Mapping[str, Any]:
    key = (season, _context_generation(season))

    def load():
        try:
            from src.bdvm.context_store import load_snapshot  # noqa: PLC0415

            # Never reconstruct the multi-season context in the request process.
            ctx = load_snapshot(season)
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("bdvm: context unavailable: %s", exc)
            ctx = None
        if ctx is None:
            _LOGGER.warning(
                "bdvm: no materialised player context for %s — running on neutral "
                "priors; run scripts/refresh_bdvm_inputs.py",
                season,
            )
        return ctx if ctx is not None else {}

    return _cached_aux(_context_cache, key, load)


def _schedule_for(season: int) -> Mapping[str, Any] | None:
    key = (season, _nfl_generation("schedules", season))

    def load():
        try:
            from src.bdvm.schedule import fetch_team_weeks  # noqa: PLC0415

            return fetch_team_weeks(season, cache_only=True) or None
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning("bdvm: schedule unavailable: %s", exc)
            return None

    return _cached_aux(_schedule_cache, key, load)


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
    """Score local actuals once per scoring card, day and weekly/PBP generation.

    Calendar NFL season, never rookie draft year. Empty successful reads stay
    cached until the artifact or day changes; failed reads are retried. No
    request-path acquisition is allowed.
    """
    key = _actuals_key(contract)
    if key is None:
        return (None, {})

    def load():
        from src.bdvm.actuals import fetch_current_season_actuals  # noqa: PLC0415
        from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

        scoring = (contract.get("sleeper") or {}).get("scoringSettings") or {}
        return fetch_current_season_actuals(
            scoring, name_normalizer=normalize_player_name, season=key[0], cache_only=True
        )

    try:
        return _cached_aux(_actuals_cache, key, load)
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("bdvm: in-season actuals unavailable (not cached, will retry): %s", exc)
        return (None, {})


# Operational states for the cache-only auxiliary inputs.  Deliberately
# the plain words the rest of this repo already uses for evidence, not a
# new vocabulary: an artifact is there and current, there and old, or not
# there.  NONE of them means zero — a missing input degrades the engine to
# the neutral priors it has always used when a fetch failed.
AUX_AVAILABLE = "available"
AUX_STALE = "stale"
AUX_MISSING = "missing"

#: The cadence the context snapshot is PRODUCED on — the weekly
#: ``dynasty-bdvm-refresh`` timer (``OnCalendar=Tue *-*-* 06:10:00 UTC``).
#:
#: It is NOT a freshness ceiling and it withholds nothing: an older snapshot
#: is still loaded and still served, exactly like a TTL-expired cache entry.
#: It only decides the LABEL, so that "a scheduled refresh was missed" — the
#: one thing an operator can act on — is distinguishable from "current".
#: Reported, never enforced.
_CONTEXT_REFRESH_CADENCE_SECONDS = 7 * 24 * 3600


def _aux_state(feed: str, years: list[int] | None = None) -> dict[str, Any]:
    """Report one cache-only input's presence and age — never its value.

    The request path may serve a TTL-EXPIRED artifact (the TTL governs
    when the refresh owner should re-fetch, not whether an older artifact
    is readable), so ``stale`` must be VISIBLE rather than silently
    presented as current.  ``fetched_at`` has always been written by
    ``nfl_data.cache.put``; this only reads it back.

    The key and the TTL both come from ``ingest`` rather than being
    rebuilt here: a second copy of the key format reports MISSING for an
    artifact that is present the moment the two drift.
    """
    from src.nfl_data import cache as nfl_cache  # noqa: PLC0415
    from src.nfl_data import ingest  # noqa: PLC0415

    age = nfl_cache.entry_age_seconds(ingest.cache_key(feed, years))
    if age is None:
        return {"state": AUX_MISSING, "ageSeconds": None}
    return {
        "state": AUX_STALE if age > ingest.CACHE_TTLS[feed] else AUX_AVAILABLE,
        "ageSeconds": round(age, 1),
    }


def _context_snapshot_state(season: int) -> dict[str, Any]:
    """Presence + age of the materialised player context.

    The raw nflverse feeds are no longer reported here: the request path
    does not read them, and naming an input it does not consume would
    misdirect whoever is diagnosing a degraded board.  Their freshness
    reaches this number through the snapshot that was built from them,
    which is the thing the request actually depends on.
    """
    from src.bdvm import context_store  # noqa: PLC0415

    age = context_store.snapshot_age_seconds(season)
    if age is None:
        return {"state": AUX_MISSING, "ageSeconds": None, "playerCount": None}
    return {
        "state": AUX_STALE if age > _CONTEXT_REFRESH_CADENCE_SECONDS else AUX_AVAILABLE,
        "ageSeconds": round(age, 1),
        "playerCount": context_store.snapshot_player_count(season),
    }


def _auxiliary_input_report(season: int, actuals_season: int | None) -> dict[str, Any]:
    """Freshness/provenance for every input the request path reads locally.

    Published so a consumer can tell "BDVM is running on a week-old
    context" from "BDVM is current" — and both from "the artifact is
    absent and the engine is on the neutral priors it has always used
    when a fetch failed".  None of the three states is zero.
    """
    report: dict[str, Any] = {
        "policy": "cache_only_request_path",
        "refreshOwner": "scripts/refresh_bdvm_inputs.py (scheduled, out of band)",
        "playerContext": _context_snapshot_state(season),
        "schedules": _aux_state("schedules", [season]),
    }
    if actuals_season is not None:
        # Its OWN entry: ``bdvm/actuals.py`` fetches ``[season]`` alone so
        # the in-progress season refreshes without dragging six years of
        # history with it.
        report["currentSeasonActuals"] = _aux_state("weekly_stats", [actuals_season])
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
    # Fingerprint only the small source/config identities, once per request,
    # before entering any per-player work. Missing→present is a generation change.
    actuals_key = _actuals_key(contract) if snapshot else None
    roster_settings, idp_enabled, scoring_profile = _registry_settings_for(league_key)
    key = (
        id(contract),
        contract.get("generatedAt"),
        league_key,
        params.param_set_id,
        _file_generation(snapshot),
        surplus_mode,
        _scoring_key(contract),
        json.dumps(roster_settings, sort_keys=True, default=str),
        idp_enabled,
        scoring_profile,
        actuals_key,
        _context_generation(season),
        _nfl_generation("schedules", season),
        _events_fingerprint(season),
    )
    with _lock:
        cached = _values_cache.get(key)
        if cached is not None:
            _values_cache.move_to_end(key)
            return cached

    def compute():
        with _lock:
            cached = _values_cache.get(key)
            if cached is not None:
                _values_cache.move_to_end(key)
                return cached
        # No snapshot means no reachable answer; do not parse/score actuals.
        actuals = _actuals_for(contract) if snapshot else (None, {})
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
        if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
            payload["meta"]["auxiliaryInputs"] = _auxiliary_input_report(
                season, actuals_key[0] if actuals_key is not None else None
            )
        with _lock:
            # A failed actuals read was deliberately not memoized. Do not pin
            # its degraded valuation either; the next request must retry it.
            actuals_ready = actuals_key is None or actuals[0] is not None
            if not actuals_ready:
                with _aux_lock:
                    actuals_ready = actuals_key in _actuals_cache
            if actuals_ready:
                _values_cache[key] = payload
                _values_cache.move_to_end(key)
                while len(_values_cache) > _VALUES_CACHE_MAX:
                    _values_cache.popitem(last=False)
        return payload

    return _values_flights.run(key, compute)[0]


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
