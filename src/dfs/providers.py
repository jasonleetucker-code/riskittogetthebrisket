"""Licensed DFS slate feeds → the canonical slate.

Today: SportsDataIO ``DfsSlatesByDate`` (NFL / NBA / NHL), mapped from the field
names in SportsDataIO's published OpenAPI description
(``https://api.apis.guru/v2/specs/sportsdata.io/{sport}-v3-projections/1.0/openapi.json``,
schemas ``DfsSlate`` / ``DfsSlateGame`` / ``DfsSlatePlayer``, read 2026-09-30).

What is DOCUMENTED is not what is VERIFIED.  The schema names the fields; it does
not say which operators a subscription returns, what values ``Operator`` and
``OperatorGameType`` take, how fresh the salaries are, or what the licence
permits.  So:

* acquisition needs the ``dfs_sportsdataio_slates`` flag (default OFF) AND the
  shared ``SPORTSDATAIO_API_KEY`` credential (the same env var and header the
  repo's other SportsDataIO modules use), and neither is provisioned;
* unrecognised ``Operator`` / ``OperatorGameType`` values are reported, never
  mapped by guess;
* ``OperatorSalary`` missing means the athlete is refused, never priced at 0;
* a player the operator removed is excluded and counted.

Failure states: ``SOURCE_PERMISSION_REQUIRED`` (no credential),
``PROVIDER_UNAVAILABLE`` (flag off / network / 5xx), ``QUOTA_EXCEEDED`` (429),
``PROVIDER_ERROR`` (anything else).  The official platform CSV is the always-
available fallback; this module never falls back to an unofficial endpoint.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from src.dfs.imports import SlateAthlete
from src.dfs.slate import CanonicalSlate, SlateEvent

FLAG = "dfs_sportsdataio_slates"
CREDENTIAL_ENV_VAR = "SPORTSDATAIO_API_KEY"
CREDENTIAL_HEADER = "Ocp-Apim-Subscription-Key"
API = "https://api.sportsdata.io/v3/{sport}/projections/json/DfsSlatesByDate/{date}"
SPORTS = ("nfl", "nba", "nhl")
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
TIMEOUT_S = 12.0
#: Operator / game-type labels as they are expected to appear.  Unverified: a
#: value outside these maps is REPORTED, not mapped.
OPERATORS = {"draftkings": "draftkings", "fanduel": "fanduel"}
GAME_TYPES = {"classic": "classic", "showdown": "showdown_captain"}
#: SportsDataIO publishes naive local times; the repo's existing SportsDataIO
#: owner (src/nfl_data/sportsdataio_live_game_state.py) reads them as US Eastern.
NAIVE_ZONE = ZoneInfo("America/New_York")
_SAFE_ID = re.compile(r"^[0-9A-Za-z][0-9A-Za-z\-]{0,39}$")


class ProviderError(Exception):
    def __init__(self, code: str, message: str, status: int = 503):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _flag_on() -> bool:
    try:
        from src.api import feature_flags

        return feature_flags.is_enabled("dfs_sportsdataio_slates")
    except Exception:  # noqa: BLE001
        return False


def provider_status() -> dict[str, Any]:
    """What the provider can do right now.  Never reveals the credential."""
    has_key = bool(os.getenv(CREDENTIAL_ENV_VAR, "").strip())
    if not _flag_on():
        state, note = "disabled", f"Feature flag {FLAG} is off."
    elif not has_key:
        state, note = (
            "no_credential",
            f"{CREDENTIAL_ENV_VAR} is not set (paid subscription; owner approval).",
        )
    else:
        state, note = (
            "configured_unverified",
            "Credential present; coverage not yet verified against live data.",
        )
    return {"provider": "sportsdataio", "state": state, "note": note, "sports": list(SPORTS)}


HttpGet = Callable[[str, Mapping[str, str], float], tuple[int, bytes]]


def _default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> tuple[int, bytes]:
    req = urllib.request.Request(url, headers=dict(headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed https host
            return resp.status, resp.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


def fetch_slates(sport: str, date: str, http_get: HttpGet | None = None) -> list[dict[str, Any]]:
    if sport not in SPORTS:
        raise ProviderError(
            "UNSUPPORTED_SLATE",
            f"SportsDataIO DFS slates are not documented for {sport.upper()}.",
            400,
        )
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date or ""):
        raise ProviderError("INVALID_DATE", "Date must be YYYY-MM-DD.", 400)
    status = provider_status()
    if status["state"] == "disabled":
        raise ProviderError("PROVIDER_UNAVAILABLE", status["note"])
    key = os.getenv(CREDENTIAL_ENV_VAR, "").strip()
    if not key:
        raise ProviderError("SOURCE_PERMISSION_REQUIRED", status["note"])
    code, body = (http_get or _default_http_get)(
        API.format(sport=sport, date=date),
        {CREDENTIAL_HEADER: key, "Accept": "application/json"},
        TIMEOUT_S,
    )
    if code == 429:
        raise ProviderError(
            "QUOTA_EXCEEDED", "SportsDataIO quota exceeded; use the platform CSV meanwhile."
        )
    if code in (401, 403):
        raise ProviderError(
            "SOURCE_PERMISSION_REQUIRED", "SportsDataIO refused the credential for this feed."
        )
    if code >= 500 or code == 0:
        raise ProviderError("PROVIDER_UNAVAILABLE", f"SportsDataIO answered {code}.")
    if code != 200:
        raise ProviderError("PROVIDER_ERROR", f"SportsDataIO answered {code}.")
    if len(body) > MAX_RESPONSE_BYTES:
        raise ProviderError("PROVIDER_ERROR", "SportsDataIO response exceeded the size limit.")
    try:
        data = json.loads(body)
    except ValueError as exc:
        raise ProviderError("PROVIDER_ERROR", "SportsDataIO returned invalid JSON.") from exc
    if not isinstance(data, list):
        raise ProviderError("PROVIDER_ERROR", "SportsDataIO returned an unexpected shape.")
    return data


def _utc(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=NAIVE_ZONE)
    return dt.astimezone(timezone.utc).isoformat()


def slate_summary(raw: dict[str, Any]) -> dict[str, Any]:
    op = str(raw.get("Operator") or "")
    gt = str(raw.get("OperatorGameType") or "")
    return {
        "providerSlateId": raw.get("SlateID"),
        "operatorSlateId": raw.get("OperatorSlateID"),
        "name": raw.get("OperatorName"),
        "operator": op,
        "platform": OPERATORS.get(op.lower()),
        "gameType": gt,
        "format": GAME_TYPES.get(gt.lower()),
        "startTimeUtc": _utc(raw.get("OperatorStartTime")),
        "games": raw.get("NumberOfGames"),
        "players": len(raw.get("DfsSlatePlayers") or []),
        "removedByOperator": bool(raw.get("RemovedByOperator")),
    }


def canonical_from_sportsdataio(
    raw: dict[str, Any], sport: str
) -> tuple[CanonicalSlate, dict[str, Any]]:
    """One ``DfsSlate`` object → canonical slate + a report of everything not mapped."""
    summary = slate_summary(raw)
    if summary["platform"] is None:
        raise ProviderError(
            "UNSUPPORTED_SLATE", f"Unrecognised operator {summary['operator']!r}.", 422
        )
    if summary["format"] is None:
        raise ProviderError(
            "UNSUPPORTED_FORMAT", f"Unrecognised game type {summary['gameType']!r}.", 422
        )
    events: dict[int, SlateEvent] = {}
    for g in raw.get("DfsSlateGames") or []:
        sgid = g.get("SlateGameID")
        game = g.get("Game") or {}
        away, home = game.get("AwayTeam"), game.get("HomeTeam")
        eid = f"{away}@{home}" if away and home else f"sdio-game-{sgid}"
        events[sgid] = SlateEvent(
            event_id=eid,
            participants=[away, home] if away and home else [],
            start_time_utc=_utc(game.get("DateTime")),
            status="removed"
            if g.get("RemovedByOperator")
            else ("scheduled" if game else "unknown"),
            source_ids={
                "sportsdataioGameID": str(g.get("GameID")),
                "operatorGameID": str(g.get("OperatorGameID")),
            },
        )
    athletes: list[SlateAthlete] = []
    refused: list[dict[str, Any]] = []
    removed = 0
    seen: set[str] = set()
    for p in raw.get("DfsSlatePlayers") or []:
        if p.get("RemovedByOperator"):
            removed += 1
            continue
        pid = str(p.get("OperatorPlayerID") or "")
        salary = p.get("OperatorSalary")
        name = str(p.get("OperatorPlayerName") or "").strip()
        why = None
        if not _SAFE_ID.match(pid):
            why = "invalid_or_missing_operator_player_id"
        elif pid in seen:
            why = "duplicate_operator_player_id"
        elif not isinstance(salary, int) or isinstance(salary, bool) or salary < 0:
            why = "missing_salary"  # missing is never priced at zero
        elif not name or not p.get("OperatorPosition"):
            why = "missing_name_or_position"
        if why:
            if len(refused) < 200:
                refused.append({"operatorPlayerId": pid, "name": name[:80], "reason": why})
            continue
        seen.add(pid)
        ev = events.get(p.get("SlateGameID"))
        team = str(p.get("Team") or "").upper()
        opponent = None
        if ev and len(ev.participants) == 2 and team in ev.participants:
            opponent = ev.participants[1] if ev.participants[0] == team else ev.participants[0]
        athletes.append(
            SlateAthlete(
                player_id=pid,
                name=name,
                positions=[
                    x.strip().upper() for x in str(p["OperatorPosition"]).split("/") if x.strip()
                ],
                team=team,
                opponent=opponent,
                game=ev.event_id if ev else None,
                salary=salary,
                start_time_utc=ev.start_time_utc if ev else None,
                eligible_slots=[str(s).upper() for s in (p.get("OperatorRosterSlots") or [])],
                extra={
                    k: str(p.get(k))
                    for k in ("PlayerID", "SlatePlayerID", "OperatorSlatePlayerID", "TeamID")
                    if p.get(k) is not None
                },
            )
        )
    slate = CanonicalSlate(
        sport=sport,
        platform=summary["platform"],
        format=summary["format"],
        athletes=athletes,
        events=sorted(events.values(), key=lambda e: (e.start_time_utc or "", e.event_id)),
        name=summary["name"],
        start_time_utc=summary["startTimeUtc"],
        slate_date=(summary["startTimeUtc"] or "")[:10] or None,
        external_ids={
            k: str(v)
            for k, v in (
                ("sportsdataioSlateID", raw.get("SlateID")),
                ("operatorSlateID", raw.get("OperatorSlateID")),
            )
            if v is not None
        },
        source_salary_cap=raw.get("SalaryCap") if isinstance(raw.get("SalaryCap"), int) else None,
        source_roster_slots=[str(s).upper() for s in raw.get("SlateRosterSlots") or []] or None,
        provenance={
            "sourceKind": "licensed_feed",
            "adapter": "sportsdataio_dfs_slates_v1",
            "layoutVerification": "documented_unverified",
            "importedAt": datetime.now(timezone.utc).isoformat(),
            "timezoneAssumption": "naive provider times read as America/New_York",
        },
    )
    return slate, {"refused": refused, "removedByOperator": removed, "summary": summary}
