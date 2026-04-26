"""Wire the IDP scoring-fit pipeline into the live contract build.

Decoupled from ``data_contract.py`` so the pure compute (in
:mod:`src.scoring.idp_scoring_fit`) can be unit-tested with hand-built
fixtures, while this module handles the live I/O wiring:

* Sleeper league context (scoring + roster_positions + total_rosters)
* Sleeper /v1/players/nfl payload (sleeper_id ↔ gsis_id cross-walk)
* nflverse weekly defensive stats (trailing 3 seasons)
* nflverse players.csv (id_map for draft_round / rookie_season)

Every external fetch is best-effort — a network failure, an empty
cache, or a missing field collapses the pass to a no-op rather than
raising into the live contract build.

Feature-gated by ``feature_flags.is_enabled("idp_scoring_fit")``.
Phase 1 ships with the flag OFF until the production gate passes
(lens leans correct AND ≥20% precision floor on the prior-season
backtest).

Adjusted value (the "apply scoring fit" toggle)
─────────────────────────────────────────────────
When the pass runs, every IDP row also gets
``idpScoringFitAdjustedValue`` =
``clamp(rankDerivedValue + delta × _ADJUSTED_VALUE_WEIGHT, 0, 9999)``.

That field is what the value would be IF the user toggles "apply
scoring fit" on the frontend.  The toggle itself is purely a
display switch — the frontend re-sorts and re-displays using this
field instead of ``rankDerivedValue``.  Backend never mutates
``rankDerivedValue``.

The 0.30 weight was chosen as a middle ground between the original
plan's recommended 0.20 (Phase 3) and the proposal's 0.65
(too aggressive without proven calibration).  At 0.30 a +6000
delta moves a player ~1800 value points — meaningful but not
absurd; positive deltas of ~+2000 (the median of the live IDP
universe) shift values ~600 — a one-tier nudge.
"""
from __future__ import annotations

import json as _json
import logging
import threading
import time as _time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from src.api import feature_flags
from src.scoring.idp_scoring_fit import (
    IdpFitRow,
    compute_idp_scoring_fit,
    quantile_map_to_consensus_scale,
    stamp_delta,
)

_ADJUSTED_VALUE_WEIGHT: float = 0.30
_ADJUSTED_VALUE_MIN: float = 0.0
_ADJUSTED_VALUE_MAX: float = 9999.0

_LOGGER = logging.getLogger(__name__)

# ── Caches ────────────────────────────────────────────────────────
# Sleeper /v1/players/nfl is ~6MB — refresh once per day.
_SLEEPER_PLAYERS_CACHE: dict[str, Any] = {}
_SLEEPER_PLAYERS_TTL_SEC = 24 * 3600
_LOCK = threading.Lock()

# League context (scoring + roster_positions + total_rosters) — refresh
# every hour.  The existing _resolve_league_context only exposes
# bonus_rec_te + roster_count, so we keep our own cache for the full
# scoring/roster dicts.
_IDP_LEAGUE_CONTEXT_CACHE: dict[str, Any] = {}
_IDP_LEAGUE_CONTEXT_TTL_SEC = 3600


def _fetch_sleeper_players_idmap() -> dict[str, str]:
    """Return Sleeper-id → GSIS-id cross-walk.

    Two-tier cache: in-memory hot path + on-disk warm path via the
    existing ``src.nfl_data.cache`` module.  A backend restart picks up
    the disk cache instantly (24-hour TTL) instead of refetching the
    ~6MB Sleeper /players/nfl payload every cold start.

    Empty dict on any failure.  Sleeper's /players/nfl endpoint
    returns ``{sleeper_id: {gsis_id, position, ...}, ...}``.  We pull
    the gsis_id field from each record where present.
    """
    now = _time.time()
    with _LOCK:
        cached = _SLEEPER_PLAYERS_CACHE.get("idmap")
        fetched_at = float(_SLEEPER_PLAYERS_CACHE.get("fetched_at") or 0.0)
        if isinstance(cached, dict) and (now - fetched_at) < _SLEEPER_PLAYERS_TTL_SEC:
            return cached

    # Disk cache check before the network round-trip.
    try:
        from src.nfl_data import cache as _disk_cache  # noqa: PLC0415
        disk_cached = _disk_cache.get(
            "idp_scoring_fit:sleeper_idmap:v1",
            ttl_seconds=_SLEEPER_PLAYERS_TTL_SEC,
        )
        if isinstance(disk_cached, dict) and disk_cached:
            with _LOCK:
                _SLEEPER_PLAYERS_CACHE["idmap"] = disk_cached
                _SLEEPER_PLAYERS_CACHE["fetched_at"] = now
            return disk_cached
    except Exception:  # noqa: BLE001
        pass  # disk cache miss / unwriteable → fall through to network

    url = "https://api.sleeper.app/v1/players/nfl"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "riskit-idp-fit/1.0"})
        with urllib.request.urlopen(req, timeout=30.0) as resp:
            data = _json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOGGER.warning("idp_scoring_fit=sleeper_players_fetch_failed err=%r", exc)
        return {}
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("idp_scoring_fit=sleeper_players_parse_failed err=%r", exc)
        return {}

    out: dict[str, str] = {}
    if isinstance(data, dict):
        for sid, meta in data.items():
            if not isinstance(meta, dict):
                continue
            gsis = meta.get("gsis_id")
            if isinstance(gsis, str) and gsis:
                out[str(sid)] = gsis.strip()

    with _LOCK:
        _SLEEPER_PLAYERS_CACHE["idmap"] = out
        _SLEEPER_PLAYERS_CACHE["fetched_at"] = now
    # Persist to disk cache so the next backend restart skips the
    # 6MB fetch (cache TTL is 24h, matching the in-memory TTL).
    try:
        from src.nfl_data import cache as _disk_cache  # noqa: PLC0415
        _disk_cache.put("idp_scoring_fit:sleeper_idmap:v1", out)
    except Exception:  # noqa: BLE001
        pass

    return out


def _fetch_idp_league_context() -> dict[str, Any]:
    """Return ``{scoring_settings, roster_positions, num_teams}``.

    Two-tier cache: in-memory + on-disk (24-hour TTL).  Empty dict
    on any failure.
    """
    now = _time.time()
    with _LOCK:
        cached = _IDP_LEAGUE_CONTEXT_CACHE.get("ctx")
        fetched_at = float(_IDP_LEAGUE_CONTEXT_CACHE.get("fetched_at") or 0.0)
        if isinstance(cached, dict) and (now - fetched_at) < _IDP_LEAGUE_CONTEXT_TTL_SEC:
            return cached

    # Disk cache check.
    try:
        from src.nfl_data import cache as _disk_cache  # noqa: PLC0415
        disk_cached = _disk_cache.get(
            "idp_scoring_fit:league_ctx:v1",
            ttl_seconds=_IDP_LEAGUE_CONTEXT_TTL_SEC,
        )
        if isinstance(disk_cached, dict) and disk_cached.get("scoring_settings"):
            with _LOCK:
                _IDP_LEAGUE_CONTEXT_CACHE["ctx"] = disk_cached
                _IDP_LEAGUE_CONTEXT_CACHE["fetched_at"] = now
            return disk_cached
    except Exception:  # noqa: BLE001
        pass

    # Resolve league id via the registry first; fall back to env var.
    league_id = ""
    try:
        from src.api import league_registry as _league_registry  # noqa: PLC0415
        league_id = (_league_registry.get_sleeper_league_id() or "").strip()
    except Exception:  # noqa: BLE001
        league_id = ""
    if not league_id:
        import os
        league_id = os.getenv("SLEEPER_LEAGUE_ID", "").strip()
    if not league_id:
        return {}

    url = f"https://api.sleeper.app/v1/league/{league_id}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "riskit-idp-fit/1.0"})
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = _json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOGGER.warning("idp_scoring_fit=league_fetch_failed err=%r", exc)
        return {}
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("idp_scoring_fit=league_parse_failed err=%r", exc)
        return {}

    if not isinstance(data, dict):
        return {}
    scoring_settings = data.get("scoring_settings") or {}
    roster_positions = data.get("roster_positions") or []
    total_rosters = int(data.get("total_rosters") or 0) or 12
    if not isinstance(scoring_settings, dict):
        scoring_settings = {}
    if not isinstance(roster_positions, list):
        roster_positions = []

    ctx = {
        "scoring_settings": scoring_settings,
        "roster_positions": [str(p) for p in roster_positions],
        "num_teams": total_rosters,
    }
    # Persist to disk so the next backend restart skips the network.
    try:
        from src.nfl_data import cache as _disk_cache  # noqa: PLC0415
        _disk_cache.put("idp_scoring_fit:league_ctx:v1", ctx)
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        _IDP_LEAGUE_CONTEXT_CACHE["ctx"] = ctx
        _IDP_LEAGUE_CONTEXT_CACHE["fetched_at"] = now
    return ctx


def _fetch_trailing_3yr_defensive_corpus() -> dict[int, list[dict[str, Any]]]:
    """Pull the trailing 3 seasons of nflverse weekly defensive stats,
    grouped by season.

    Years are determined relative to the current calendar year — for
    a build run in April 2026, the corpus is 2025 / 2024 / 2023.
    Empty dict on any failure.
    """
    try:
        from src.nfl_data import ingest as _ingest  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("idp_scoring_fit=ingest_import_failed err=%r", exc)
        return {}

    current_year = datetime.now(timezone.utc).year
    # If we're early in the year before the new season has played any
    # weeks, there's no current-year data — so the corpus is the
    # prior 3 completed seasons.  September onward starts pulling the
    # in-progress season too.
    if datetime.now(timezone.utc).month >= 9:
        years = [current_year, current_year - 1, current_year - 2]
    else:
        years = [current_year - 1, current_year - 2, current_year - 3]

    out: dict[int, list[dict[str, Any]]] = {}
    for year in years:
        try:
            rows = _ingest.fetch_weekly_defensive_stats([year])
        except Exception as exc:  # noqa: BLE001
            _LOGGER.warning(
                "idp_scoring_fit=defensive_fetch_failed year=%d err=%r",
                year, exc,
            )
            continue
        if rows:
            out[year] = rows
    return out


def _fetch_nflverse_id_map() -> list[dict[str, Any]]:
    """nflverse players.csv — gsis_id, position, rookie_season,
    draft_round, draft_pick.  Empty list on any failure."""
    try:
        from src.nfl_data import ingest as _ingest  # noqa: PLC0415
        return _ingest.fetch_id_map() or []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("idp_scoring_fit=id_map_fetch_failed err=%r", exc)
        return []


# ── Public pass ───────────────────────────────────────────────────
def apply_idp_scoring_fit_pass(
    players_array: list[dict[str, Any]],
    *,
    league_idp_enabled: bool = True,
) -> None:
    """Stamp ``idpScoringFit*`` fields on each IDP row in
    ``players_array`` (in-place).

    Called from ``_compute_unified_rankings`` after the corridor
    clamp + two-way boost.  Fully gated:

    * ``feature_flags.is_enabled("idp_scoring_fit")`` must be True
    * ``league_idp_enabled`` must be True (the league actually has
      IDP slots in its roster)
    * Sleeper league context must be fetchable
    * The trailing 3-yr defensive corpus must be non-empty

    Any fail collapses to a no-op — no fields are stamped.  Safe to
    leave the call site enabled even when the pipeline can't produce
    output.
    """
    if not feature_flags.is_enabled("idp_scoring_fit"):
        return
    if not league_idp_enabled:
        return
    if not players_array:
        return

    ctx = _fetch_idp_league_context()
    scoring_settings = ctx.get("scoring_settings") if isinstance(ctx, dict) else None
    roster_positions = ctx.get("roster_positions") if isinstance(ctx, dict) else None
    num_teams = int((ctx or {}).get("num_teams") or 0)
    if not scoring_settings or not roster_positions or num_teams <= 0:
        _LOGGER.info("idp_scoring_fit=skip reason=missing_league_context")
        return

    weekly_rows_by_season = _fetch_trailing_3yr_defensive_corpus()
    if not weekly_rows_by_season:
        _LOGGER.info("idp_scoring_fit=skip reason=missing_defensive_corpus")
        return

    id_map_rows = _fetch_nflverse_id_map()
    sleeper_to_gsis = _fetch_sleeper_players_idmap()

    fit_by_name = compute_idp_scoring_fit(
        players_array,
        scoring_settings,
        roster_positions,
        num_teams,
        weekly_rows_by_season=weekly_rows_by_season,
        id_map_rows=id_map_rows,
        sleeper_to_gsis=sleeper_to_gsis,
    )
    if not fit_by_name:
        _LOGGER.info("idp_scoring_fit=empty fit_count=0")
        return

    # Build the league-wide PAR-per-game distribution from realized
    # rows.  Used for quantile-mapping each fit-row to a value-scale
    # delta.  Synthetic rows do NOT contribute to the distribution
    # (they're already cohort-derived; including them would be
    # circular) but are mapped against it.
    par_distribution = [
        (row.vorp / max(1, row.games_used)) for row in fit_by_name.values()
        if row.vorp is not None and row.games_used > 0
    ]

    stamped = 0
    for player in players_array:
        name = str(player.get("displayName") or "")
        if not name:
            continue
        fit = fit_by_name.get(name)
        if fit is None:
            continue
        consensus_value = float(player.get("rankDerivedValue") or 0)
        fit_with_delta = stamp_delta(fit, consensus_value, par_distribution)
        player["idpScoringFitVorp"] = fit_with_delta.vorp
        player["idpScoringFitTier"] = fit_with_delta.tier
        player["idpScoringFitDelta"] = fit_with_delta.delta
        player["idpScoringFitConfidence"] = fit_with_delta.confidence
        # Diagnostic-only fields stamped for the lens UI.  Frontend
        # treats them as informational; not part of the delta payload
        # whitelist (they don't change per-source toggle).
        if fit_with_delta.synthetic:
            player["idpScoringFitSynthetic"] = True
            if fit_with_delta.draft_round is not None:
                player["idpScoringFitDraftRound"] = fit_with_delta.draft_round
        if fit_with_delta.weighted_ppg is not None:
            player["idpScoringFitWeightedPpg"] = fit_with_delta.weighted_ppg
        if fit_with_delta.games_used:
            player["idpScoringFitGamesUsed"] = fit_with_delta.games_used
        # Adjusted value: what rankDerivedValue would BE if the user
        # toggles "apply scoring fit" on the frontend.  Always stamped
        # when the pass produces a delta — frontend toggle decides
        # whether to display this or the raw consensus.  Backend never
        # mutates ``rankDerivedValue`` itself.
        if fit_with_delta.delta is not None and consensus_value > 0:
            adjusted = consensus_value + fit_with_delta.delta * _ADJUSTED_VALUE_WEIGHT
            adjusted = max(_ADJUSTED_VALUE_MIN, min(_ADJUSTED_VALUE_MAX, adjusted))
            player["idpScoringFitAdjustedValue"] = round(adjusted, 2)
        stamped += 1

    _LOGGER.info(
        "idp_scoring_fit=applied stamped=%d total_fit_rows=%d weight=%.2f",
        stamped, len(fit_by_name), _ADJUSTED_VALUE_WEIGHT,
    )
