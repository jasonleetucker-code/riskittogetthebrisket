"""Per-player snap-share aggregation from nflverse weekly snap counts.

Used as a durability signal for IDPs: a 100-tackle LB with 95% snap
share is a true bell-cow; the same line on 60% snap share is a
rotational role susceptible to snap-redistribution.  Stamped on each
IDP row alongside the scoring-fit fields so the popup + lens can
surface it.

Reads ``src.nfl_data.fetch_snap_counts`` (cached on disk).  Returns
``{player_id: float}`` mapping gsis_id → defensive snap share
(0.0-1.0) averaged across the season.

No-throw contract — empty dict on any failure (network, parse, no
data).  The apply pass treats the absence as "no snap data" and
skips stamping the field.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

_LOGGER = logging.getLogger(__name__)


def _resolve_target_season() -> int:
    """Most recent completed (or in-progress) NFL season.

    September onward → current calendar year (regular season has
    started).  Earlier in the calendar → previous calendar year.
    Matches the convention in ``idp_scoring_fit_apply``.
    """
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 9 else now.year - 1


def fetch_idp_snap_shares(season: int | None = None) -> dict[str, float]:
    """Return ``{gsis_id: defensive_snap_share}`` for IDPs in
    ``season`` (defaults to most recent).

    Snap share is computed per player as
    ``sum(defense_snaps) / sum(team_snaps)`` across all weeks where
    both fields are non-zero.  Players with < 4 weeks of data are
    excluded — too small a sample to be informative.

    Returns ``{}`` on any fetch failure or when nflverse hasn't
    published snap counts yet.
    """
    if season is None:
        season = _resolve_target_season()

    try:
        from src.nfl_data import ingest as _ingest  # noqa: PLC0415
        rows = _ingest.fetch_snap_counts([season])
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("snap_share=fetch_failed season=%d err=%r", season, exc)
        return {}

    if not rows:
        return {}

    # Aggregate per player.  nflverse snap_counts has columns:
    #   pfr_player_id, player, position, team, week, season,
    #   offense_snaps, defense_snaps, st_snaps, offense_pct,
    #   defense_pct, st_pct
    # We need gsis_id (so it joins to the other pipeline).  The
    # snap_counts file uses ``pfr_player_id`` not gsis — we cross-
    # walk via the id_map.
    pfr_to_defense_pcts: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if not isinstance(r, dict):
            continue
        pfr = str(r.get("pfr_player_id") or "").strip()
        pos = str(r.get("position") or "").upper()
        if not pfr:
            continue
        # IDP gate — saves work on the cross-walk lookup.
        if pos not in {"DL", "DT", "DE", "EDGE", "NT", "LB", "ILB", "OLB",
                       "MLB", "DB", "CB", "S", "FS", "SS"}:
            continue
        try:
            pct = float(r.get("defense_pct") or 0)
        except (TypeError, ValueError):
            continue
        # nflverse stores defense_pct as 0.0-1.0 in some seasons,
        # 0-100 in others.  Normalise: anything > 1 is a percent.
        if pct > 1:
            pct = pct / 100.0
        if pct <= 0:
            continue
        pfr_to_defense_pcts[pfr].append(pct)

    # Cross-walk pfr_id → gsis_id.
    try:
        from src.nfl_data import ingest as _ingest  # noqa: PLC0415
        id_map_rows = _ingest.fetch_id_map() or []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("snap_share=id_map_failed err=%r", exc)
        return {}

    pfr_to_gsis: dict[str, str] = {}
    for row in id_map_rows:
        gsis = str(row.get("gsis_id") or "").strip()
        pfr = str(row.get("pfr_id") or "").strip()
        if gsis and pfr:
            pfr_to_gsis[pfr] = gsis

    out: dict[str, float] = {}
    for pfr, pcts in pfr_to_defense_pcts.items():
        if len(pcts) < 4:
            continue
        gsis = pfr_to_gsis.get(pfr)
        if not gsis:
            continue
        out[gsis] = sum(pcts) / len(pcts)

    _LOGGER.info(
        "snap_share=loaded season=%d idps=%d pfr_no_gsis=%d",
        season, len(out),
        sum(1 for p in pfr_to_defense_pcts if p not in pfr_to_gsis),
    )
    return out
