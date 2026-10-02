"""Daily Fantasy Fuel adapter (registry seed A-020): public projection pages → PIT observations.

Access (checked 2026-09-30): the per-sport, per-platform projections pages
(``/{sport}/projections/{platform}``) are public HTML; robots.txt disallows only
``/lineup/*``.  The owner has stated he is permitted to collect from this
source.  Redistribution rights are NOT established, so observations stay
owner-scoped, as every DFS record does.

Behaviour:

* **cached and paced** — fetched when the owner asks (``pull``) or by the
  automatic slate refresh (``src/dfs/auto``, DFS-AUTO-04: a 10-minute timer that
  refreshes by time to lock — 2 h / 30 min / 10 min), and never more than once
  per ``MIN_REFETCH_S`` per page (served from the on-disk cache otherwise), with a
  descriptive User-Agent and a timeout; no retries in a loop, no evasion of any
  access control;
* **provenance** — URL, fetch time, HTTP status and the SHA-256 of the raw page
  travel with every observation;
* **parse** — only the documented row attributes (name, team, opponent,
  position, salary, projection, recent averages, injury, spread, over/under,
  implied team total); a page with no rows is ``SOURCE_EMPTY``, never zero;
* **join** — to the slate by normalized name + team + position, CONFIRMED by an
  exact salary match (the page is platform-specific); a name that matches
  several athletes or whose salary disagrees is quarantined, never first-wins;
* **record** — ``projection`` (source ``dailyfantasyfuel``) and ``context``
  (spread / over-under / implied total) observations at FETCH time: the page
  states no publish time, and fetch time is the earliest we can prove we held it.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.dfs import pit, store
from src.utils.name_clean import normalize_player_name, normalize_team

SOURCE = "dailyfantasyfuel"
BASE = "https://www.dailyfantasyfuel.com"
SPORTS = {"nfl", "nba", "nhl"}
PLATFORMS = {"draftkings", "fanduel"}
MIN_REFETCH_S = 15 * 60
TIMEOUT_S = 20
MAX_BYTES = 8 * 1024 * 1024
USER_AGENT = "ChaseUpsideDFS/1.0 (owner research tool; contact via site)"
_ROW = re.compile(r"<tr[^>]*class=\"\s*projections-listing\s*\"[^>]*>", re.S)
_ATTR = re.compile(r"data-([a-z0-9_]+)\s*=\s*\"([^\"]*)\"")


class SourceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _cache_dir() -> Path:
    d = store._db_path().parent / "raw" / SOURCE
    d.mkdir(parents=True, exist_ok=True)
    return d


def fetch(sport: str, platform: str, *, now: float | None = None) -> dict[str, Any]:
    """The raw page (from cache when fresher than MIN_REFETCH_S) with provenance."""
    if sport not in SPORTS or platform not in PLATFORMS:
        raise SourceError(
            "UNSUPPORTED_SOURCE_SLATE", f"{SOURCE} has no {sport}/{platform} page adapter."
        )
    url = f"{BASE}/{sport}/projections/{platform}"
    now = time.time() if now is None else now
    cache = _cache_dir() / f"{sport}_{platform}.json"
    if cache.exists():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if now - cached["fetchedEpoch"] < MIN_REFETCH_S:
            return {**cached, "fromCache": True}
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed https URL
            status = resp.status
            body = resp.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise SourceError("PROVIDER_UNAVAILABLE", f"{SOURCE} answered HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise SourceError("PROVIDER_UNAVAILABLE", f"{SOURCE} could not be reached.") from exc
    if len(body) > MAX_BYTES:
        raise SourceError(
            "SOURCE_TOO_LARGE", f"{SOURCE} page exceeded {MAX_BYTES // 1024 // 1024} MB."
        )
    text = body.decode("utf-8", errors="replace")
    record = {
        "url": url,
        "status": status,
        "fetchedAt": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "fetchedEpoch": now,
        "sha256": hashlib.sha256(body).hexdigest(),
        "html": text,
    }
    cache.write_text(json.dumps(record), encoding="utf-8")
    return {**record, "fromCache": False}


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


_UPDATED = re.compile(r'<time[^>]*datetime="([^"]+)"[^>]*data-type="updated"', re.S)


def page_updated_at(page_html: str) -> str | None:
    """The page's own "Updated At" stamp (UTC ISO), or None when absent — the
    source's PUBLISH time, which beats our fetch time as point-in-time evidence."""
    m = _UPDATED.search(page_html)
    if not m:
        return None
    try:
        return (
            datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
            .astimezone(timezone.utc)
            .isoformat()
        )
    except ValueError:
        return None


def parse(page_html: str) -> list[dict[str, Any]]:
    rows = []
    for tag in _ROW.findall(page_html):
        a = {k: html.unescape(v).strip() for k, v in _ATTR.findall(tag)}
        if not a.get("name") or not a.get("team"):
            continue
        rows.append(
            {
                "name": a["name"],
                "team": a["team"],
                "opponent": a.get("opp") or None,
                "position": (a.get("pos") or "").upper(),
                "salary": int(_num(a.get("salary")) or 0) or None,
                "projection": _num(a.get("ppg_proj")),
                "seasonAvg": _num(a.get("szn_avg")),
                "last5Avg": _num(a.get("l5_avg")),
                "injury": a.get("inj") or None,
                "spread": _num(a.get("spread")),
                "overUnder": _num(a.get("ou")),
                "impliedTeamTotal": _num(a.get("proj_score")),
                "startDate": a.get("start_date") or None,
                "sourcePlayerId": a.get("player_id") or None,
            }
        )
    return rows


def join(rows: list[dict[str, Any]], athletes: list[Any]) -> dict[str, Any]:
    """Source rows → slate athletes: name + team + position, confirmed by exact salary."""
    idx: dict[tuple[str, str], list[Any]] = {}
    for a in athletes:
        idx.setdefault((normalize_player_name(a.name), normalize_team(a.team)), []).append(a)
    matched: dict[str, dict[str, Any]] = {}
    quarantined = []
    for r in rows:
        cands = [
            a
            for a in idx.get((normalize_player_name(r["name"]), normalize_team(r["team"])), [])
            if not r["position"]
            or r["position"] in a.positions
            or r["position"] in (a.eligible_slots or [])
        ]
        if r["salary"] is not None:
            cands = [a for a in cands if a.salary == r["salary"]]
        idents = {getattr(a, "identity", a.player_id) for a in cands}
        if len(idents) != 1:
            quarantined.append(
                {
                    "name": r["name"][:60],
                    "team": r["team"],
                    "reason": "ambiguous_identity"
                    if idents
                    else "no_slate_athlete_or_salary_mismatch",
                }
            )
            continue
        for a in cands:  # every platform row of the one athlete (Showdown CPT/FLEX)
            matched[a.player_id] = r
    return {"matched": matched, "quarantined": quarantined}


def pull(
    owner: str, snapshot: dict[str, Any], sport: str, platform: str, athletes: list[Any]
) -> dict[str, Any]:
    """Fetch (or reuse the cache), parse, join, and record observations for one slate."""
    page = fetch(sport, platform)
    rows = parse(page["html"])
    if not rows:
        raise SourceError(
            "SOURCE_EMPTY", f"{SOURCE} returned no projection rows for {sport}/{platform}."
        )
    joined = join(rows, athletes)
    if pit.get_slate(owner, snapshot["id"]) is None:
        pit.capture_snapshot(owner, snapshot)
    prov = {
        "url": page["url"],
        "sha256": page["sha256"],
        "status": page["status"],
        "via": "adapter",
    }
    obs = []
    for pid, r in joined["matched"].items():
        if r["projection"] is not None:
            obs.append(
                {
                    "playerId": pid,
                    "kind": "projection",
                    "source": SOURCE,
                    "observedAt": page["fetchedAt"],
                    "value": r["projection"],
                    "provenance": prov,
                }
            )
        ctx = {
            k: r[k]
            for k in ("spread", "overUnder", "impliedTeamTotal", "injury")
            if r[k] is not None
        }
        if ctx:
            obs.append(
                {
                    "playerId": pid,
                    "kind": "context",
                    "source": SOURCE,
                    "observedAt": page["fetchedAt"],
                    "value": ctx,
                    "provenance": prov,
                }
            )
    counts = (
        pit.record(owner, snapshot["id"], obs, recorded_at=page["fetchedAt"])
        if obs
        else {"added": 0}
    )
    return {
        "source": SOURCE,
        "url": page["url"],
        "fetchedAt": page["fetchedAt"],
        "fromCache": page["fromCache"],
        "rows": len(rows),
        "matched": len(joined["matched"]),
        "slateAthletes": len(athletes),
        "quarantined": joined["quarantined"][:100],
        "observations": counts,
        "note": "Owner-authorized collection; redistribution rights not established — kept private to you.",
    }
