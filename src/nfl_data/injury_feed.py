"""ESPN NFL injury feed integration.

Pulls from the undocumented public endpoint:

    https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries

Returns a league-wide list of active injuries with status (Out,
Questionable, IR, PUP), body part, return timeline, and ESPN
athleteId.  We resolve athleteId → Sleeper ID via the unified
ID mapper (Phase 1) so the signal engine downstream can filter
to roster-owned players.

Degradation
-----------
* Feature flag ``espn_injury_feed`` OFF → returns [].
* HTTP error / timeout → cached None, next retry after TTL.
* Schema drift (unknown response shape) → empty list + warning
  log.

The caller (signal engine) is responsible for fanning out
BUY/SELL transitions across rosters — this module only fetches +
normalizes.
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

_ESPN_INJURIES_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"
)
_UA = "riskit-injury-feed/1.0"
_TTL_IN_SEASON = 30 * 60  # 30 min
_TIMEOUT_SEC = 8.0


_ACTIVE_STATUSES = frozenset({
    "OUT", "INJURED_RESERVE", "IR", "PHYSICALLY_UNABLE",
    "PUP", "QUESTIONABLE", "DOUBTFUL", "DAY_TO_DAY",
})


@dataclass(frozen=True)
class InjuryEntry:
    espn_athlete_id: str
    full_name: str
    position: str
    team_abbrev: str
    status: str  # normalized: OUT | IR | QUESTIONABLE | DOUBTFUL | PUP
    body_part: str
    description: str
    date_reported: str  # ISO-8601 or empty
    returning: str  # best-effort "return timeline" free text

    def to_dict(self) -> dict[str, Any]:
        return {
            "espnAthleteId": self.espn_athlete_id,
            "fullName": self.full_name,
            "position": self.position,
            "teamAbbrev": self.team_abbrev,
            "status": self.status,
            "bodyPart": self.body_part,
            "description": self.description,
            "dateReported": self.date_reported,
            "returning": self.returning,
        }


def _normalize_status(raw: str) -> str:
    """Map ESPN's many status variants to our 5-bucket system.

    ESPN uses ``status``, ``type.description``, and ``shortComment``
    inconsistently.  Normalize to: OUT | IR | QUESTIONABLE | DOUBTFUL
    | PUP.  Unknown → verbatim uppercased.
    """
    s = str(raw or "").strip().upper().replace(" ", "_").replace("-", "_")
    if s in ("OUT", "SUSPENDED"):
        return "OUT"
    if s in ("IR", "INJURED_RESERVE", "RESERVE_INJURED"):
        return "IR"
    if s in ("QUESTIONABLE", "Q"):
        return "QUESTIONABLE"
    if s in ("DOUBTFUL", "D"):
        return "DOUBTFUL"
    if s in ("PUP", "PHYSICALLY_UNABLE", "PHYSICALLY_UNABLE_TO_PERFORM"):
        return "PUP"
    if s in ("DAY_TO_DAY", "PROBABLE", "P"):
        return "DAY_TO_DAY"
    return s


def fetch_injuries(
    *,
    ttl_seconds: float = _TTL_IN_SEASON,
    _url_opener=None,
    cache_dir=None,
) -> list[InjuryEntry]:
    """Return the current league-wide injury list.

    ``_url_opener`` is a test hook.  Production passes None.
    """
    if not feature_flags.is_enabled("espn_injury_feed"):
        return []
    key = "espn_injuries:v1"
    cached = _cache.get(key, ttl_seconds=ttl_seconds, cache_dir=cache_dir)
    if cached is not None:
        return [_from_cached_dict(d) for d in cached]

    try:
        req = urllib.request.Request(
            _ESPN_INJURIES_URL, headers={"User-Agent": _UA},
        )
        opener = _url_opener or urllib.request.urlopen
        with opener(req, timeout=_TIMEOUT_SEC) as resp:
            body = resp.read()
        raw = json.loads(body)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _LOGGER.warning("espn injuries: network error: %s", exc)
        return []
    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("espn injuries: parse error: %s", exc)
        return []

    parsed = _parse_espn_payload(raw)
    _cache.put(key, [e.to_dict() for e in parsed], cache_dir=cache_dir)
    return parsed


def _parse_espn_payload(payload: Any) -> list[InjuryEntry]:
    """Parse ESPN's injuries response.  Shape (as of 2026-04):

        {
          "injuries": [
            {
              "team": {"abbreviation": "BUF", ...},
              "injuries": [
                {
                  "athlete": {"id": "...", "displayName": "...",
                              "position": {"abbreviation": "QB"}},
                  "status": "...",
                  "type": {"description": "...", "abbreviation": "..."},
                  "details": {"type": "...", "location": "...",
                              "detail": "...", "side": "...",
                              "returnDate": "..."},
                  "date": "...",
                  "shortComment": "...",
                  "longComment": "..."
                }, ...
              ]
            }, ...
          ]
        }
    """
    out: list[InjuryEntry] = []
    if not isinstance(payload, dict):
        return out
    teams_list = payload.get("injuries") or []
    if not isinstance(teams_list, list):
        return out
    for team_block in teams_list:
        if not isinstance(team_block, dict):
            continue
        team_abbr = str(((team_block.get("team") or {}).get("abbreviation")) or "").upper()
        inj_list = team_block.get("injuries") or []
        if not isinstance(inj_list, list):
            continue
        for entry in inj_list:
            if not isinstance(entry, dict):
                continue
            athlete = entry.get("athlete") or {}
            if not isinstance(athlete, dict):
                continue
            espn_id = str(athlete.get("id") or "").strip()
            if not espn_id:
                continue
            name = str(athlete.get("displayName") or athlete.get("fullName") or "")
            pos_block = athlete.get("position") or {}
            pos = str(pos_block.get("abbreviation") or "").upper()
            status_norm = _normalize_status(entry.get("status") or "")
            if status_norm not in _ACTIVE_STATUSES:
                continue
            details = entry.get("details") or {}
            body_part = str(details.get("location") or details.get("type") or "")
            returning = str(details.get("returnDate") or "")
            description = str(entry.get("shortComment") or entry.get("longComment") or "")
            out.append(InjuryEntry(
                espn_athlete_id=espn_id,
                full_name=name,
                position=pos,
                team_abbrev=team_abbr,
                status=status_norm,
                body_part=body_part,
                description=description,
                date_reported=str(entry.get("date") or ""),
                returning=returning,
            ))
    return out


def _from_cached_dict(d: dict[str, Any]) -> InjuryEntry:
    return InjuryEntry(
        espn_athlete_id=str(d.get("espnAthleteId") or ""),
        full_name=str(d.get("fullName") or ""),
        position=str(d.get("position") or ""),
        team_abbrev=str(d.get("teamAbbrev") or ""),
        status=str(d.get("status") or ""),
        body_part=str(d.get("bodyPart") or ""),
        description=str(d.get("description") or ""),
        date_reported=str(d.get("dateReported") or ""),
        returning=str(d.get("returning") or ""),
    )


def diff_for_signals(
    prior: list[InjuryEntry],
    current: list[InjuryEntry],
) -> list[dict[str, Any]]:
    """Return new / changed injury transitions for the signal engine.

    Emits a signal dict when:
      * A player newly appears in the injury list (was healthy → injured).
      * A player's status worsens (Q → Out, DOUBTFUL → IR, etc.).

    Does NOT emit when:
      * Player recovers (Out → active / off-list) — buying a returning
        player is a different signal class (covered in a future idea).
      * Repeat report of same status.
    """
    prior_by_id = {e.espn_athlete_id: e for e in prior}
    severity = {"DAY_TO_DAY": 1, "QUESTIONABLE": 2, "DOUBTFUL": 3, "OUT": 4, "PUP": 4, "IR": 5}
    signals: list[dict[str, Any]] = []
    for curr in current:
        prev = prior_by_id.get(curr.espn_athlete_id)
        if prev is None:
            # New injury.
            signals.append({
                "espnAthleteId": curr.espn_athlete_id,
                "name": curr.full_name,
                "position": curr.position,
                "team": curr.team_abbrev,
                "transition": "healthy_to_injured",
                "newStatus": curr.status,
                "priorStatus": None,
                "reason": f"New injury — {curr.status}" + (
                    f" ({curr.body_part})" if curr.body_part else ""
                ),
            })
            continue
        prev_sev = severity.get(prev.status, 0)
        new_sev = severity.get(curr.status, 0)
        if new_sev > prev_sev:
            signals.append({
                "espnAthleteId": curr.espn_athlete_id,
                "name": curr.full_name,
                "position": curr.position,
                "team": curr.team_abbrev,
                "transition": "injury_worsened",
                "newStatus": curr.status,
                "priorStatus": prev.status,
                "reason": f"Status worsened: {prev.status} → {curr.status}",
            })
    return signals
