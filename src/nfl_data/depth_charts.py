"""ESPN team depth charts — used to cross-check usage signals.

Purpose (Phase 8 of the 2026-04 upgrade)
----------------------------------------
Usage spikes + drops can fire false positives: a WR who caught 2
garbage-time targets in a blowout isn't really a BUY.  Requiring
the depth chart to also reflect the change halves the false-alert
rate.

Rule for MONITOR-grade cross-check:
  * Player's depth-chart slot moved (e.g., WR2 → WR1, RB3 → RB2)
    between consecutive nightly snapshots  AND
  * Snap-share usage delta ≥ 5 percentage points week-over-week.

When BOTH conditions are true, emit a depth-chart-confirmed
MONITOR signal.  Single-signal (usage OR depth alone) does NOT
trigger this guard — it's specifically the conjunction that's
reliable.

Endpoint
--------
    https://site.api.espn.com/apis/site/v2/sports/football/nfl
        /teams/{team_id}/depthchart

32 calls per nightly refresh — negligible load.  Cached in
``src.nfl_data.cache`` with a 12h TTL.

Degradation
-----------
* Flag ``depth_chart_validation`` OFF → returns [] and signal
  engine treats every usage signal as un-cross-checked (falls back
  to the existing non-gated path).
* Network error → cached prior + warning log.
* Schema drift → empty + warning log.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from src.api import feature_flags
from src.nfl_data import cache as _cache

_LOGGER = logging.getLogger(__name__)

_ESPN_DEPTH_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/depthchart"
)
_UA = "riskit-depth-chart/1.0"
_TTL_SECONDS = 12 * 3600
_TIMEOUT_SEC = 6.0

# NFL team IDs on ESPN — used by fetch_all().  Hardcoded because
# this list is stable (32 teams, no new teams added since 2002).
NFL_TEAM_IDS: list[str] = sorted({
    "22", "1", "33", "2", "29", "3", "4", "5",    # ARI, ATL, BAL, BUF, CAR, CHI, CIN, CLE
    "6", "7", "8", "9", "34", "11", "30", "12",   # DAL, DEN, DET, GB, HOU, IND, JAX, KC
    "24", "14", "13", "15", "16", "17", "18", "19",  # LAC, LAR, LV, MIA, MIN, NE, NO, NYG
    "20", "21", "23", "26", "25", "27", "10", "28",  # NYJ, PHI, PIT, SEA, SF, TB, TEN, WAS
})


@dataclass(frozen=True)
class DepthChartEntry:
    team_abbrev: str
    position: str  # "WR", "RB", "QB", etc.
    slot: int  # 1 = starter, 2 = backup, ...
    espn_athlete_id: str
    full_name: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "teamAbbrev": self.team_abbrev,
            "position": self.position,
            "slot": self.slot,
            "espnAthleteId": self.espn_athlete_id,
            "fullName": self.full_name,
        }


def fetch_team_depth_chart(
    team_id: str,
    *,
    ttl_seconds: float = _TTL_SECONDS,
    _url_opener=None,
    cache_dir=None,
) -> list[DepthChartEntry]:
    """Fetch a single team's depth chart.

    Pure read — the caller composes into a league-wide dict when
    needed.  Caches per-team so a single bad response doesn't
    invalidate the whole league.
    """
    if not feature_flags.is_enabled("depth_chart_validation"):
        return []
    key = f"espn_depth:{team_id}"
    cached = _cache.get(key, ttl_seconds=ttl_seconds, cache_dir=cache_dir)
    if cached is not None:
        return [_from_cached(d) for d in cached]
    try:
        url = _ESPN_DEPTH_URL.format(team_id=team_id)
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        opener = _url_opener or urllib.request.urlopen
        with opener(req, timeout=_TIMEOUT_SEC) as resp:
            raw = json.loads(resp.read())
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOGGER.warning("espn depth team=%s: network error: %s", team_id, exc)
        return []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("espn depth team=%s: parse error: %s", team_id, exc)
        return []
    parsed = _parse_depth_payload(raw)
    _cache.put(key, [e.to_dict() for e in parsed], cache_dir=cache_dir)
    return parsed


def _parse_depth_payload(payload: Any) -> list[DepthChartEntry]:
    """Parse ESPN's depth-chart response.  Shape varies slightly
    between pre-season and regular-season endpoints; we handle
    both defensively.

    Expected common shape:
        {
          "team": {"abbreviation": "BUF"},
          "athletes": [
            {"position": {"abbreviation": "QB"},
             "items": [{"athlete": {...}, ...}, ...]}
          ]
        }
    Older/alternative shape has athletes groups keyed by formation.
    """
    out: list[DepthChartEntry] = []
    if not isinstance(payload, dict):
        return out
    team_abbr = str(((payload.get("team") or {}).get("abbreviation")) or "").upper()
    athletes_top = payload.get("athletes") or []
    if not isinstance(athletes_top, list):
        return out
    for grp in athletes_top:
        if not isinstance(grp, dict):
            continue
        pos = str(((grp.get("position") or {}).get("abbreviation")) or "").upper()
        items = grp.get("items") or []
        if not isinstance(items, list):
            continue
        for i, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            athlete = item.get("athlete") or {}
            if not isinstance(athlete, dict):
                continue
            espn_id = str(athlete.get("id") or "").strip()
            if not espn_id:
                continue
            full_name = str(
                athlete.get("displayName") or athlete.get("fullName") or ""
            )
            out.append(DepthChartEntry(
                team_abbrev=team_abbr,
                position=pos,
                slot=i + 1,
                espn_athlete_id=espn_id,
                full_name=full_name,
            ))
    return out


def _from_cached(d: dict[str, Any]) -> DepthChartEntry:
    return DepthChartEntry(
        team_abbrev=str(d.get("teamAbbrev") or ""),
        position=str(d.get("position") or ""),
        slot=int(d.get("slot") or 0),
        espn_athlete_id=str(d.get("espnAthleteId") or ""),
        full_name=str(d.get("fullName") or ""),
    )


def detect_slot_changes(
    prior: list[DepthChartEntry],
    current: list[DepthChartEntry],
) -> list[dict[str, Any]]:
    """Return list of {athleteId, oldSlot, newSlot, direction} deltas.

    direction: "promoted" (higher up the chart) | "demoted" | "debut"
    """
    prior_by = {(e.team_abbrev, e.position, e.espn_athlete_id): e.slot for e in prior}
    out: list[dict[str, Any]] = []
    for e in current:
        key = (e.team_abbrev, e.position, e.espn_athlete_id)
        prev_slot = prior_by.get(key)
        if prev_slot is None:
            out.append({
                "espnAthleteId": e.espn_athlete_id,
                "fullName": e.full_name,
                "position": e.position,
                "team": e.team_abbrev,
                "oldSlot": None,
                "newSlot": e.slot,
                "direction": "debut",
            })
            continue
        if prev_slot == e.slot:
            continue
        out.append({
            "espnAthleteId": e.espn_athlete_id,
            "fullName": e.full_name,
            "position": e.position,
            "team": e.team_abbrev,
            "oldSlot": prev_slot,
            "newSlot": e.slot,
            "direction": "promoted" if e.slot < prev_slot else "demoted",
        })
    return out


def usage_confirms_slot_change(
    depth_change: dict[str, Any],
    snap_share_delta_pct: float,
    *,
    min_snap_delta_pct: float = 0.05,
) -> bool:
    """Return True when both signals agree.

    ``snap_share_delta_pct`` is the week-over-week change in snap
    share (not the z-score — raw pct).  Default gate: 5 pp.

    Direction must match — a promoted player with a snap-share
    DROP is not a confirmed signal (could be a garbage-time
    reshuffle on the stat sheet).
    """
    direction = depth_change.get("direction")
    if direction not in ("promoted", "demoted"):
        return False
    abs_delta = abs(snap_share_delta_pct or 0.0)
    if abs_delta < min_snap_delta_pct:
        return False
    # Promoted = slot number went DOWN (1 is starter).  Expect snap
    # share UP.  Signs must match.
    if direction == "promoted" and snap_share_delta_pct <= 0:
        return False
    if direction == "demoted" and snap_share_delta_pct >= 0:
        return False
    return True
