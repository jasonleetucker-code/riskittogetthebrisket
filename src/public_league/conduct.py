"""Source-backed current-roster conduct board for the public League page.

This section deliberately does *not* scrape names or infer misconduct.  It
joins current Sleeper roster IDs against a small, reviewed registry whose
entries require public evidence links and an explicit legal/disposition
status.  The registry is data, not a verdict: allegations, arrests/charges,
pleas/convictions, cleared matters, and league discipline remain separate in
the emitted contract.

The section is registered as lazy in :mod:`src.public_league.public_contract`
so opening the default League page does not load this registry or enlarge the
aggregate response.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .snapshot import PublicLeagueSnapshot

log = logging.getLogger(__name__)

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "public_league" / "conduct_registry.json"
)
_SCHEMA_VERSION = 1

_DATE_RE = re.compile(r"^\d{4}(?:-\d{2}(?:-\d{2})?)?$")

_CATEGORY_LABELS: dict[str, str] = {
    "domesticViolence": "Domestic violence",
    "sexualMisconduct": "Sexual assault / misconduct",
    "seriousCrime": "Other serious crime",
    "weapons": "Weapons-related serious crime",
    "violentConduct": "Other violent conduct",
}

_ALLOWED_STATUSES = frozenset(
    {
        "allegedNoCharge",
        "arrestedInvestigationOpen",
        "chargedPending",
        "pretrialDiversion",
        "prosecutionDeclined",
        "noBilled",
        "dismissed",
        "acquitted",
        "pleaded",
        "convicted",
        "resolvedMixed",
        "leagueFinding",
        "leagueNoFinding",
    }
)

_ALLOWED_BASES = frozenset(
    {
        "credibleAllegation",
        "formalLegalAction",
        "convictionOrPlea",
        "violenceRelatedDiscipline",
    }
)

_BREAKDOWN_KEYS = (
    "credibleAllegation",
    "formalLegalAction",
    "convictionOrPlea",
    "violenceRelatedDiscipline",
)

# Deliberately simple, public, and auditable.  Category points express the
# seriousness of the alleged/documented conduct; the status multiplier is the
# evidentiary/outcome control that prevents an allegation from scoring like a
# conviction.  Do not infer either value from prose in a summary.
_CATEGORY_POINTS: dict[str, float] = {
    "domesticViolence": 50.0,
    "sexualMisconduct": 50.0,
    "violentConduct": 40.0,
    "weapons": 40.0,
    "seriousCrime": 30.0,
}

_OUTCOME_MULTIPLIERS: dict[str, float] = {
    "convicted": 1.0,
    "pleaded": 1.0,
    "leagueFinding": 0.85,
    "pretrialDiversion": 0.65,
    "chargedPending": 0.55,
    "arrestedInvestigationOpen": 0.45,
    "resolvedMixed": 0.30,
    "allegedNoCharge": 0.20,
    "prosecutionDeclined": 0.10,
    "noBilled": 0.10,
    "dismissed": 0.10,
    "leagueNoFinding": 0.05,
    "acquitted": 0.0,
}

_OUTCOME_LABELS: dict[str, str] = {
    "convicted": "Convicted",
    "pleaded": "Guilty / no-contest plea",
    "leagueFinding": "League or organization finding",
    "pretrialDiversion": "Pretrial diversion",
    "chargedPending": "Charge pending",
    "arrestedInvestigationOpen": "Arrest / investigation open",
    "resolvedMixed": "Mixed or partially resolved record",
    "allegedNoCharge": "Documented allegation; no charge",
    "prosecutionDeclined": "Prosecution declined",
    "noBilled": "Grand jury no-bill",
    "dismissed": "Charge or case dismissed",
    "leagueNoFinding": "League found insufficient evidence / no violation",
    "acquitted": "Acquitted",
}

_DISCIPLINE_BONUS = 10.0
_REPEAT_INCIDENT_BONUS = 10.0

_SCORING = {
    "version": "1.0",
    "formula": (
        "Team score = sum(category severity points × current-status multiplier "
        "+ qualifying discipline bonus) + outcome-scaled repeat-incident bonuses"
    ),
    "severityWeights": [
        {
            "category": category,
            "label": _CATEGORY_LABELS[category],
            "points": points,
        }
        for category, points in _CATEGORY_POINTS.items()
    ],
    "outcomeMultipliers": [
        {
            "status": status,
            "label": _OUTCOME_LABELS[status],
            "multiplier": multiplier,
        }
        for status, multiplier in _OUTCOME_MULTIPLIERS.items()
    ],
    "disciplineBonus": _DISCIPLINE_BONUS,
    "repeatIncidentBonus": _REPEAT_INCIDENT_BONUS,
    "repeatDefinition": (
        "The highest-status-multiplier incident is the player's base incident. Every other "
        "distinct reviewed incident adds up to the repeat bonus, scaled by that incident's "
        "current-status multiplier; an acquittal therefore adds zero. Multiple allegations "
        "grouped in one registry incident do not create extra bonuses."
    ),
    "caveat": (
        "The score ranks current fantasy rosters from this reviewed registry. It is not a "
        "finding of guilt, a complete background check, or an objective measure of a person's "
        "character. Status updates can change the score."
    ),
}

_METHODOLOGY = {
    "mainTally": (
        "Teams are ranked by the published score formula, not by a raw player count. The "
        "unique-player and incident totals remain visible as context."
    ),
    "breakdownCounts": (
        "Each breakdown also counts unique players. Categories can overlap, so they do not "
        "sum to the unique flagged-player total."
    ),
    "rosterScope": (
        "Current Sleeper player IDs across active, bench, reserve/IR, taxi, and starter slots; "
        "draft picks are never included. A roster move moves the flag on the next snapshot."
    ),
    "sourceRule": (
        "Every published incident must carry at least one HTTPS source with a label. "
        "Malformed or unsourced incidents are rejected before the response is built."
    ),
    "included": [
        "Publicly documented adult domestic-violence or sexual-assault/misconduct allegations",
        "Arrests or charges for a felony or equivalent serious crime",
        "Convictions or pleas for qualifying conduct",
        "Non-drug discipline tied to violence, abuse, threats, or serious weapons conduct",
    ],
    "excluded": [
        "Rumors or social posts without reliable reporting",
        "Drug/PED and gambling matters",
        "Ordinary on-field penalties or discipline",
        "Traffic offenses and unrelated misdemeanors",
    ],
    "caveat": (
        "This is a curated public-record index, not a complete background check. A listing is "
        "not a finding of guilt; read each status and disposition."
    ),
}


def _base_payload(
    snapshot: PublicLeagueSnapshot,
    *,
    available: bool,
    unavailable_reason: str | None,
    registry_last_reviewed: str = "",
) -> dict[str, Any]:
    return {
        "available": available,
        "unavailableReason": unavailable_reason,
        "asOf": snapshot.generated_at,
        "registryLastReviewed": registry_last_reviewed,
        "methodology": _METHODOLOGY,
        "scoring": _SCORING,
        "totals": {
            "teams": 0,
            "rosteredPlayers": 0,
            "flaggedPlayers": 0,
            "incidents": 0,
            "score": 0.0,
            "breakdown": {key: 0 for key in _BREAKDOWN_KEYS},
        },
        "dataQuality": {
            "acceptedPlayerCount": 0,
            "acceptedIncidentCount": 0,
            "rejectedPlayerCount": 0,
            "rejectedIncidentCount": 0,
            "matchedRegistryPlayerCount": 0,
            "unrosteredRegistryPlayerCount": 0,
        },
        "teams": [],
    }


def _load_registry(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        log.warning("conduct registry is missing")
        return None, "registryUnavailable"
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("conduct registry could not be read: %s", exc)
        return None, "registryUnavailable"

    if not isinstance(raw, dict):
        return None, "registryInvalid"
    if raw.get("schemaVersion") != _SCHEMA_VERSION:
        return None, "registryInvalid"
    if not isinstance(raw.get("players"), list):
        return None, "registryInvalid"
    last_reviewed = raw.get("lastReviewed")
    if not isinstance(last_reviewed, str) or not _DATE_RE.fullmatch(last_reviewed):
        return None, "registryInvalid"
    return raw, None


def _valid_source(source: Any) -> dict[str, str] | None:
    if not isinstance(source, dict):
        return None
    label = str(source.get("label") or "").strip()
    url = str(source.get("url") or "").strip()
    parsed = urlparse(url)
    if not label or parsed.scheme != "https" or not parsed.netloc:
        return None
    return {"label": label, "url": url}


def _incident_score(
    *,
    category: str,
    status: str,
    has_discipline: bool,
) -> tuple[float, dict[str, float]]:
    severity_points = _CATEGORY_POINTS[category]
    outcome_multiplier = _OUTCOME_MULTIPLIERS[status]
    discipline_bonus = _DISCIPLINE_BONUS if has_discipline else 0.0
    points = round((severity_points * outcome_multiplier) + discipline_bonus, 1)
    return points, {
        "severityPoints": severity_points,
        "outcomeMultiplier": outcome_multiplier,
        "disciplineBonus": discipline_bonus,
    }


def _normalize_incident(
    raw: Any,
    *,
    seen_incident_ids: set[str],
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None

    incident_id = str(raw.get("incidentId") or "").strip()
    category = str(raw.get("category") or "").strip()
    status = str(raw.get("status") or "").strip()
    summary = str(raw.get("summary") or "").strip()
    status_label = str(raw.get("statusLabel") or "").strip()
    disposition = str(raw.get("disposition") or "").strip()
    date_label = str(raw.get("dateLabel") or "").strip()
    last_verified = str(raw.get("lastVerified") or "").strip()
    date = raw.get("date")

    if (
        not incident_id
        or incident_id in seen_incident_ids
        or category not in _CATEGORY_LABELS
        or status not in _ALLOWED_STATUSES
        or not summary
        or not status_label
        or not disposition
        or not date_label
        or not _DATE_RE.fullmatch(last_verified)
    ):
        return None
    if date is not None and (not isinstance(date, str) or not _DATE_RE.fullmatch(date)):
        return None

    raw_bases = raw.get("qualifyingBasis")
    if not isinstance(raw_bases, list):
        return None
    bases: list[str] = []
    for basis in raw_bases:
        value = str(basis or "").strip()
        if value not in _ALLOWED_BASES:
            return None
        if value not in bases:
            bases.append(value)
    if not bases:
        return None

    raw_sources = raw.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        return None
    sources: list[dict[str, str]] = []
    for source in raw_sources:
        normalized = _valid_source(source)
        if normalized is None:
            return None
        sources.append(normalized)

    discipline: dict[str, str] | None = None
    raw_discipline = raw.get("discipline")
    if raw_discipline is not None:
        if not isinstance(raw_discipline, dict):
            return None
        organization = str(raw_discipline.get("organization") or "").strip()
        description = str(raw_discipline.get("description") or "").strip()
        discipline_date = str(raw_discipline.get("date") or "").strip()
        if (
            not organization
            or not description
            or not discipline_date
            or not _DATE_RE.fullmatch(discipline_date)
        ):
            return None
        discipline = {
            "organization": organization,
            "description": description,
            "date": discipline_date,
        }
    if "violenceRelatedDiscipline" in bases and discipline is None:
        return None

    if (status in {"pleaded", "convicted"}) != ("convictionOrPlea" in bases):
        return None

    denial = str(raw.get("denial") or "").strip()
    score, score_breakdown = _incident_score(
        category=category,
        status=status,
        has_discipline=discipline is not None,
    )
    seen_incident_ids.add(incident_id)
    return {
        "incidentId": incident_id,
        "date": date,
        "dateLabel": date_label,
        "lastVerified": last_verified,
        "category": category,
        "categoryLabel": _CATEGORY_LABELS[category],
        "summary": summary,
        "status": status,
        "statusLabel": status_label,
        "disposition": disposition,
        "qualifyingBasis": bases,
        "discipline": discipline,
        "denial": denial,
        "sources": sources,
        "score": score,
        "scoreBreakdown": score_breakdown,
    }


def _normalize_registry(
    raw: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    players_by_id: dict[str, dict[str, Any]] = {}
    seen_incident_ids: set[str] = set()
    rejected_players = 0
    rejected_incidents = 0
    accepted_incidents = 0

    for raw_player in raw.get("players", []):
        if not isinstance(raw_player, dict):
            rejected_players += 1
            continue
        player_id = str(raw_player.get("sleeperPlayerId") or "").strip()
        player_name = str(raw_player.get("playerName") or "").strip()
        raw_incidents = raw_player.get("incidents")
        if (
            not player_id
            or not player_name
            or player_id in players_by_id
            or not isinstance(raw_incidents, list)
        ):
            rejected_players += 1
            if isinstance(raw_incidents, list):
                rejected_incidents += len(raw_incidents)
            continue

        incidents: list[dict[str, Any]] = []
        for raw_incident in raw_incidents:
            incident = _normalize_incident(
                raw_incident,
                seen_incident_ids=seen_incident_ids,
            )
            if incident is None:
                rejected_incidents += 1
                continue
            incidents.append(incident)
            accepted_incidents += 1

        # A name without any publishable evidence must never create a flag.
        if not incidents:
            rejected_players += 1
            continue
        incidents.sort(key=lambda row: str(row.get("date") or ""), reverse=True)
        players_by_id[player_id] = {
            "playerId": player_id,
            "playerName": player_name,
            "incidents": incidents,
        }

    quality = {
        "acceptedPlayerCount": len(players_by_id),
        "acceptedIncidentCount": accepted_incidents,
        "rejectedPlayerCount": rejected_players,
        "rejectedIncidentCount": rejected_incidents,
    }
    return players_by_id, quality


def _roster_player_ids(roster: dict[str, Any]) -> set[str]:
    """Return every player slot represented by a Sleeper roster.

    Sleeper's ``players`` list normally includes bench/reserve/taxi already,
    but the explicit union keeps the contract correct for partial fixtures and
    future payload variants.  Draft-pick fields are intentionally absent.
    """

    player_ids: set[str] = set()
    for key in ("players", "reserve", "taxi", "starters"):
        values = roster.get(key)
        if not isinstance(values, list):
            continue
        for value in values:
            player_id = str(value or "").strip()
            if player_id:
                player_ids.add(player_id)
    return player_ids


def _player_row(
    snapshot: PublicLeagueSnapshot,
    registry_player: dict[str, Any],
) -> dict[str, Any]:
    player_id = registry_player["playerId"]
    incidents = registry_player["incidents"]
    bases = sorted(
        {basis for incident in incidents for basis in incident.get("qualifyingBasis", [])}
    )
    metadata = snapshot.nfl_players.get(player_id)
    nfl_team = ""
    if isinstance(metadata, dict):
        nfl_team = str(metadata.get("team") or "")
    incident_points = round(sum(float(incident["score"]) for incident in incidents), 1)
    outcome_multipliers = sorted(
        (float(incident["scoreBreakdown"]["outcomeMultiplier"]) for incident in incidents),
        reverse=True,
    )
    repeat_incident_bonus = round(
        sum(outcome_multipliers[1:]) * _REPEAT_INCIDENT_BONUS,
        1,
    )
    score = round(incident_points + repeat_incident_bonus, 1)
    return {
        "playerId": player_id,
        "playerName": snapshot.player_display(player_id) or registry_player["playerName"],
        "position": snapshot.player_position(player_id),
        "nflTeam": nfl_team,
        "incidentCount": len(incidents),
        "qualifyingBasis": bases,
        "score": score,
        "incidentPoints": incident_points,
        "repeatIncidentBonus": repeat_incident_bonus,
        "isRepeatIncidentPlayer": len(incidents) > 1,
        "incidents": incidents,
    }


def _team_breakdown(players: list[dict[str, Any]]) -> dict[str, int]:
    return {
        key: sum(1 for player in players if key in player["qualifyingBasis"])
        for key in _BREAKDOWN_KEYS
    }


def build_section(
    snapshot: PublicLeagueSnapshot,
    *,
    registry: dict[str, Any] | None = None,
    registry_path: Path | None = None,
) -> dict[str, Any]:
    """Build the lazy ``conduct`` section for current fantasy rosters.

    ``registry`` and ``registry_path`` are injection seams for deterministic
    tests and maintenance tooling. Production calls use the reviewed JSON at
    :data:`_REGISTRY_PATH`.
    """

    current = snapshot.current_season
    if current is None:
        return _base_payload(
            snapshot,
            available=False,
            unavailable_reason="noCurrentSeason",
        )
    if not current.rosters:
        return _base_payload(
            snapshot,
            available=False,
            unavailable_reason="noRosters",
        )

    if registry is None:
        registry, registry_error = _load_registry(registry_path or _REGISTRY_PATH)
        if registry is None:
            return _base_payload(
                snapshot,
                available=False,
                unavailable_reason=registry_error,
            )
    elif (
        not isinstance(registry, dict)
        or registry.get("schemaVersion") != _SCHEMA_VERSION
        or not isinstance(registry.get("players"), list)
        or not isinstance(registry.get("lastReviewed"), str)
        or not _DATE_RE.fullmatch(registry["lastReviewed"])
    ):
        return _base_payload(
            snapshot,
            available=False,
            unavailable_reason="registryInvalid",
        )

    last_reviewed = str(registry.get("lastReviewed") or "")
    registry_players, quality = _normalize_registry(registry)

    teams: list[dict[str, Any]] = []
    matched_registry_ids: set[str] = set()
    rostered_total = 0

    for roster in current.rosters:
        roster_player_ids = _roster_player_ids(roster)
        rostered_total += len(roster_player_ids)
        flagged_players = [
            _player_row(snapshot, registry_players[player_id])
            for player_id in roster_player_ids
            if player_id in registry_players
        ]
        matched_registry_ids.update(player["playerId"] for player in flagged_players)
        flagged_players.sort(
            key=lambda player: (
                -player["score"],
                -player["incidentCount"],
                player["playerName"].casefold(),
            )
        )

        owner_id = str(roster.get("owner_id") or "")
        manager = snapshot.managers.by_owner_id.get(owner_id)
        try:
            roster_id: int | str = int(roster.get("roster_id"))
        except (TypeError, ValueError):
            roster_id = str(roster.get("roster_id") or "")
        display_name = manager.display_name if manager else owner_id
        team_name = manager.current_team_name if manager else ""

        teams.append(
            {
                "ownerId": owner_id,
                "rosterId": roster_id,
                "displayName": display_name or f"Team {roster_id}",
                "teamName": team_name,
                "rosteredPlayerCount": len(roster_player_ids),
                "flaggedPlayerCount": len(flagged_players),
                "incidentCount": sum(player["incidentCount"] for player in flagged_players),
                "score": round(sum(player["score"] for player in flagged_players), 1),
                "breakdown": _team_breakdown(flagged_players),
                "players": flagged_players,
            }
        )

    teams.sort(
        key=lambda team: (
            -team["score"],
            -team["flaggedPlayerCount"],
            -team["incidentCount"],
            team["displayName"].casefold(),
        )
    )
    previous_score: float | None = None
    previous_rank = 0
    for position, team in enumerate(teams, start=1):
        if previous_score is None or team["score"] != previous_score:
            previous_rank = position
            previous_score = team["score"]
        team["rank"] = previous_rank

    all_players = [player for team in teams for player in team["players"]]
    payload = _base_payload(
        snapshot,
        available=True,
        unavailable_reason=None,
        registry_last_reviewed=last_reviewed,
    )
    payload["teams"] = teams
    payload["totals"] = {
        "teams": len(teams),
        "rosteredPlayers": rostered_total,
        "flaggedPlayers": len(all_players),
        "incidents": sum(player["incidentCount"] for player in all_players),
        "score": round(sum(player["score"] for player in all_players), 1),
        "breakdown": _team_breakdown(all_players),
    }
    payload["dataQuality"] = {
        **quality,
        "matchedRegistryPlayerCount": len(matched_registry_ids),
        "unrosteredRegistryPlayerCount": max(
            0, quality["acceptedPlayerCount"] - len(matched_registry_ids)
        ),
    }
    return payload
