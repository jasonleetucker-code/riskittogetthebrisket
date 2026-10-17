"""Structured injury RETURN evidence per player — the input "out for the rest
of the season" needs and nothing else in the repo carried.

Owner master package 2026-10-17, Workstream A (P0): "Jaxson Dart enters the
optimal lineup in 82% of simulated weeks" while he is out for the remainder of
the regular season.  Sleeper says only ``injury_status: "IR"`` (no return
date), and IR is not season-ending by itself.  ESPN publishes the evidence that
decides it — an expected ``returnDate`` per current injury (Dart: IR,
``returnDate`` 2027-01-17, after the regular season) — but
:mod:`src.nfl_data.injury_feed` reads ESPN's league-wide endpoint, which caps
each team at its 25 most recently UPDATED entries.  A long-term IR player
whose report has not changed for weeks falls off that list (measured
2026-10-17: Dart is absent from it), so exactly the season-ending cases were
the ones the repo could not see.

This module reads the uncapped shape in two cheap passes:

1. ``teams/{id}/roster`` per NFL team (32 requests) — every athlete's ESPN id,
   name, position and current injury STATUS + report date (no return date).
2. ``athletes/{id}`` (common v3) for each athlete who is out-type injured —
   the current injury's ``details.returnDate``.  INCREMENTAL: refetched only
   when the roster's report date changed or the stored record is older than
   :data:`REFETCH_AFTER_SECONDS`, so a steady state costs a handful of calls.

ESPN athlete -> Sleeper id goes through the identity owner
(``resolve_canonical_v2``): exact ESPN id when Sleeper carries it (Dart's
Sleeper record does NOT), else name + team + position.  An ambiguous or
unresolved athlete is dropped and counted — never guessed.

Output: ``data/nfl_data/injury_return_evidence.json`` (gitignored, box-local,
like ``injuries_prior.json``), written atomically.  Consumers read it through
:func:`load_evidence`; the availability owner (``src.ros.availability``) is the
one that turns it into per-week states.  Evidence is reported with its own
``observedAt`` so a stale file is visible, never silently current.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
EVIDENCE_PATH = REPO_ROOT / "data" / "nfl_data" / "injury_return_evidence.json"
SCHEMA = "injury-return-evidence/v1"

ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/teams/{team_id}/roster"
ATHLETE_URL = (
    "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl/athletes/{athlete_id}"
)
_UA = "riskit-injury-return/1.0"
_TIMEOUT_SEC = 12.0
#: ESPN NFL team ids are 1..34 with 31/32 unused.
ESPN_TEAM_IDS: tuple[int, ...] = tuple(i for i in range(1, 35) if i not in (31, 32))
#: A stored return date is re-read at least this often even when the roster's
#: report date has not moved (ESPN revises returnDate without a new report).
REFETCH_AFTER_SECONDS = 24 * 3600
#: Out-type statuses whose return date matters beyond the current week.
#: Questionable / Doubtful are weekly designations: their "return date" is the
#: next game and is handled from the weekly status, not from here.
OUT_TYPE_STATUSES = frozenset(
    {"injured reserve", "out", "physically unable to perform", "suspension", "suspended", "pup"}
)

Fetcher = Callable[[str], Any]


def _http_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_SEC) as resp:  # noqa: S310 — fixed https host
        return json.loads(resp.read().decode("utf-8"))


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


# ── pass 1: rosters ──────────────────────────────────────────────────────


def roster_athletes(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every athlete on one ESPN team roster with his current injury status.

    The roster groups players (offense / defense / specialTeam /
    injuredReserveOrOut / suspended / practiceSquad); the group named
    ``injuredReserveOrOut`` is itself evidence of an out-type status even when
    the athlete's ``injuries`` list is empty.
    """
    team = (payload.get("team") or {}).get("abbreviation")
    out: list[dict[str, Any]] = []
    for group in payload.get("athletes") or []:
        gname = str(group.get("position") or "")
        for a in group.get("items") or []:
            injuries = a.get("injuries") or []
            current = injuries[0] if injuries and isinstance(injuries[0], dict) else {}
            out.append(
                {
                    "espnId": str(a.get("id") or ""),
                    "name": str(a.get("displayName") or a.get("fullName") or ""),
                    "position": str(((a.get("position") or {}).get("abbreviation")) or ""),
                    "team": str(team or ""),
                    "group": gname,
                    "injuryStatus": str(current.get("status") or "") or None,
                    "injuryDate": str(current.get("date") or "") or None,
                }
            )
    return out


def is_out_type(athlete: Mapping[str, Any]) -> bool:
    status = str(athlete.get("injuryStatus") or "").strip().lower()
    return status in OUT_TYPE_STATUSES or athlete.get("group") in (
        "injuredReserveOrOut",
        "suspended",
    )


# ── pass 2: current injury with return date ─────────────────────────────


def current_injury(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """The athlete endpoint's CURRENT injury: status, report date, returnDate.

    ``None`` when ESPN lists no current injury.  ``returnDate`` is ESPN's
    stated expectation, kept verbatim (date part) — never inferred.
    """
    athlete = payload.get("athlete") if isinstance(payload.get("athlete"), dict) else payload
    injuries = athlete.get("injuries") or []
    if not injuries or not isinstance(injuries[0], dict):
        return None
    inj = injuries[0]
    details = inj.get("details") or {}
    ret = str(details.get("returnDate") or "")[:10] or None
    return {
        "status": str(inj.get("status") or "") or None,
        "statusCode": str(((inj.get("type") or {}).get("abbreviation")) or "") or None,
        "fantasyStatus": str(((details.get("fantasyStatus") or {}).get("abbreviation")) or "")
        or None,
        "reportedAt": str(inj.get("date") or "") or None,
        "returnDate": ret,
        "bodyPart": str(details.get("type") or "") or None,
        "detail": str(details.get("detail") or "") or None,
    }


# ── identity ─────────────────────────────────────────────────────────────


def _resolve_sleeper(index: Any, athlete: Mapping[str, Any]) -> tuple[str | None, str]:
    from src.identity.resolution import resolve_canonical_v2  # noqa: PLC0415
    from src.playerctx.normalize import normalize_team_code  # noqa: PLC0415

    if index is None:
        return None, "no_sleeper_directory"
    by_id = resolve_canonical_v2(index, espn_id=athlete.get("espnId") or None)
    if by_id.resolved and by_id.method == "espn_id":
        return by_id.sleeper_id, "espn_id"
    res = resolve_canonical_v2(
        index,
        name=athlete.get("name") or None,
        position=athlete.get("position") or None,
        team=normalize_team_code(str(athlete.get("team") or "")) or None,
    )
    if res.resolved:
        return res.sleeper_id, f"name:{res.method}"
    return None, f"unresolved:{res.status}"


# ── collection ───────────────────────────────────────────────────────────


def collect(
    *,
    previous: Mapping[str, Any] | None = None,
    sleeper_index: Any = None,
    fetch: Fetcher = _http_json,
    now: float | None = None,
    workers: int = 4,
) -> dict[str, Any]:
    """One collection.  Raises nothing for a single failed request: failures
    are counted, and a team whose roster could not be read keeps its previous
    records (marked ``carriedForward``) rather than reading as "healthy"."""
    now = time.time() if now is None else now
    prev_players: dict[str, Any] = dict((previous or {}).get("players") or {})
    prev_by_espn = {v.get("espnId"): (k, v) for k, v in prev_players.items() if v.get("espnId")}

    def _roster(team_id: int) -> tuple[int, list[dict[str, Any]] | None]:
        try:
            return team_id, roster_athletes(fetch(ROSTER_URL.format(team_id=team_id)))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            _LOGGER.warning("injury_return_evidence: roster %s failed: %s", team_id, exc)
            return team_id, None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        rosters = list(ex.map(_roster, ESPN_TEAM_IDS))
    failed_teams = sorted(t for t, r in rosters if r is None)
    athletes = [a for _, r in rosters if r for a in r if a["espnId"]]
    seen_teams = {a["team"] for a in athletes}
    out_type = [a for a in athletes if is_out_type(a)]

    players: dict[str, Any] = {}
    census = {"rosterAthletes": len(athletes), "outType": len(out_type), "unresolved": 0}
    to_fetch: list[tuple[dict[str, Any], str, str]] = []
    for a in out_type:
        sid, method = _resolve_sleeper(sleeper_index, a)
        if sid is None:
            census["unresolved"] += 1
            continue
        prior = prev_by_espn.get(a["espnId"], (None, None))[1]
        observed = (prior or {}).get("observedAtEpoch")
        fresh = (
            prior
            and prior.get("rosterInjuryDate") == a["injuryDate"]
            and isinstance(observed, (int, float))  # unknown age is never fresh
            and now - observed < REFETCH_AFTER_SECONDS
        )
        if fresh:
            players[sid] = dict(prior)
            continue
        to_fetch.append((a, sid, method))

    def _athlete(item: tuple[dict[str, Any], str, str]):
        a, sid, method = item
        try:
            return item, current_injury(fetch(ATHLETE_URL.format(athlete_id=a["espnId"]))), None
        except (urllib.error.URLError, OSError, ValueError, TimeoutError) as exc:
            return item, None, type(exc).__name__

    fetched = failed = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for (a, sid, method), inj, err in ex.map(_athlete, to_fetch):
            if err is not None:
                failed += 1
                prior = prev_by_espn.get(a["espnId"], (None, None))[1]
                if prior:
                    players[sid] = {**prior, "carriedForward": True}
                continue
            fetched += 1
            players[sid] = {
                "espnId": a["espnId"],
                "name": a["name"],
                "team": a["team"],
                "identity": method,
                "rosterStatus": a["injuryStatus"],
                "rosterInjuryDate": a["injuryDate"],
                "current": inj,
                "observedAt": _iso(now),
                "observedAtEpoch": now,
            }
    # A team whose roster failed this run keeps its previous records, labelled.
    for sid, rec in prev_players.items():
        if sid not in players and rec.get("team") and rec["team"] not in seen_teams:
            players[sid] = {**rec, "carriedForward": True}
    census.update(
        {
            "athleteFetches": fetched,
            "athleteFetchFailures": failed,
            "rosterFailures": failed_teams,
            "players": len(players),
        }
    )
    return {
        "schema": SCHEMA,
        "asOf": _iso(now),
        "asOfEpoch": now,
        "census": census,
        "players": players,
    }


def write_evidence(payload: Mapping[str, Any], path: Path = EVIDENCE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


_load_lock = threading.Lock()
_load_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


def load_evidence(path: Path | None = None) -> dict[str, Any] | None:
    """The persisted evidence, re-read when the file changes; ``None`` when
    absent or unreadable (UNKNOWN — never "no injuries")."""
    target = Path(path) if path is not None else EVIDENCE_PATH
    try:
        st = target.stat()
    except OSError:
        return None
    key = (st.st_mtime_ns, st.st_size)
    with _load_lock:
        hit = _load_cache.get(str(target))
        if hit and hit[0] == key:
            return hit[1]
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        return None
    with _load_lock:
        _load_cache[str(target)] = (key, data)
    return data


def players_needing(evidence: Mapping[str, Any] | None, ids: Iterable[str]) -> dict[str, Any]:
    """The evidence records for ``ids`` (absent ids are simply not returned)."""
    recs = (evidence or {}).get("players") or {}
    return {i: recs[i] for i in ids if i in recs}
