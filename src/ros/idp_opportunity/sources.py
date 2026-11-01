"""Inputs for the IDP opportunity study: public, freely licensed or already wired.

* Sleeper weekly stat dumps through the single HTTP owner
  :func:`src.league_comparison.sleeper_stats.fetch_week_stats_response`;
* Sleeper's player dump through :func:`src.public_league.sleeper_client.fetch_nfl_players`;
* nflverse release CSVs (CC-BY 4.0; FTN charting CC-BY-SA 4.0), downloaded once into a
  local cache directory and hashed (SHA-256) so a run can be reproduced.

No paid source, no The IDP Show content, no gated page.  Every file is read and
written with ``encoding="utf-8"``.  Parsing is pure over a file path.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import urllib.request
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.playerctx.normalize import normalize_team_code as _team
from src.ros.idp_opportunity.leakage import SeasonData
from src.ros.idp_opportunity.positions import family_of, subgroup_of

__all__ = [
    "NFLVERSE_RELEASE_BASE",
    "build_season",
    "cached_download",
    "count_prekickoff_snapshots",
    "ftn_publication_lag_days",
    "load_sleeper_players",
    "load_sleeper_team_weeks",
    "load_sleeper_weeks",
    "parse_games",
    "parse_injuries",
    "parse_players_csv",
    "parse_roster_crosswalk",
    "parse_stats_player_week",
]

NFLVERSE_RELEASE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"
_UA = {"User-Agent": "riskit-research-idp-opportunity/1.0"}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cached_download(
    url: str, cache_dir: Path, name: str, *, refresh: bool = False
) -> tuple[Path | None, str | None]:
    """Download ``url`` to ``cache_dir/name`` once (atomic); return ``(path, sha256)``.
    ``(None, error)`` on failure — a missing input is reported, never an empty file."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / name
    if dest.exists() and not refresh:
        return dest, _sha256_file(dest)
    try:
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=180) as resp:  # noqa: S310
            fd, tmp = tempfile.mkstemp(dir=str(cache_dir), prefix=".dl_")
            with os.fdopen(fd, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
        os.replace(tmp, dest)
    except Exception as exc:  # noqa: BLE001
        return None, f"download_failed:{type(exc).__name__}:{exc}"
    return dest, _sha256_file(dest)


def _read_csv(path: Path, columns: Sequence[str] | None = None) -> Iterable[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if columns is None:
                yield row
            else:
                yield {c: row.get(c, "") for c in columns}


def _num(v: Any) -> float:
    try:
        return float(v) if v not in (None, "", "NA") else 0.0
    except (TypeError, ValueError):
        return 0.0


# ── Sleeper ──────────────────────────────────────────────────────────────────


def load_sleeper_weeks(
    season: int, weeks: Iterable[int], cache_dir: Path, *, refresh: bool = False
) -> tuple[dict[int, dict[str, dict[str, Any]]], dict[str, Any]]:
    """Weekly stat dumps, cached as JSON.  A week that cannot be fetched is ABSENT
    from the result and named in the report — never a week of zeros."""
    from src.league_comparison.sleeper_stats import fetch_week_stats_response

    out: dict[int, dict[str, dict[str, Any]]] = {}
    report: dict[str, Any] = {"hashes": {}, "missing": {}}
    cache_dir.mkdir(parents=True, exist_ok=True)
    for w in sorted(set(int(x) for x in weeks)):
        path = cache_dir / f"sleeper_stats_{season}_w{w:02d}.json"
        payload: Any = None
        if path.exists() and not refresh:
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            resp = fetch_week_stats_response(season, w)
            if resp.error is None and isinstance(resp.payload, dict) and resp.payload:
                payload = resp.payload
                path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            else:
                report["missing"][str(w)] = resp.error or "empty_payload"
        if isinstance(payload, dict) and payload:
            out[w] = payload
            report["hashes"][str(w)] = _sha256_file(path)
    return out, report


SLEEPER_TEAM_STATS_URL = (
    "https://api.sleeper.app/stats/nfl/{season}/{week}"
    "?season_type=regular&position[]=DL&position[]=LB&position[]=DB"
)


def load_sleeper_team_weeks(
    season: int, weeks: Iterable[int], cache_dir: Path, *, refresh: bool = False
) -> tuple[dict[int, dict[str, tuple[str, str]]], dict[str, Any]]:
    """``{week: {sleeper_id: (team, opponent)}}`` for IDP-eligible rows, from the
    team-bearing Sleeper stats endpoint (the same provider family as the wired weekly
    projections endpoint).  A week that cannot be fetched is ABSENT and named."""
    out: dict[int, dict[str, tuple[str, str]]] = {}
    report: dict[str, Any] = {"hashes": {}, "missing": {}}
    cache_dir.mkdir(parents=True, exist_ok=True)
    for w in sorted(set(int(x) for x in weeks)):
        name = f"sleeper_team_stats_{season}_w{w:02d}.json"
        path, h = cached_download(
            SLEEPER_TEAM_STATS_URL.format(season=season, week=w), cache_dir, name, refresh=refresh
        )
        if path is None:
            report["missing"][str(w)] = h
            continue
        try:
            rows = json.loads(path.read_text(encoding="utf-8"))
        except ValueError as exc:
            report["missing"][str(w)] = f"invalid_json:{exc}"
            continue
        week: dict[str, tuple[str, str]] = {}
        for r in rows if isinstance(rows, list) else []:
            pid, team, opp = r.get("player_id"), r.get("team"), r.get("opponent")
            if pid and team and opp:
                week[str(pid)] = (_team(str(team)), _team(str(opp)))
        out[w] = week
        report["hashes"][str(w)] = h
    return out, report


def parse_roster_crosswalk(path: Path) -> dict[str, dict[str, str]]:
    """nflverse season roster: ``{sleeper_id: {gsis, position, depth}}`` — an exact
    published ID crosswalk (no name matching)."""
    out: dict[str, dict[str, str]] = {}
    for row in _read_csv(path, ("sleeper_id", "gsis_id", "position", "depth_chart_position")):
        sid = (row["sleeper_id"] or "").strip()
        if not sid or sid == "NA":
            continue
        out[sid] = {
            "gsis": (row["gsis_id"] or "").strip(),
            "position": (row["position"] or "").strip(),
            "depth": (row["depth_chart_position"] or "").strip(),
        }
    return out


def load_sleeper_players(
    cache_dir: Path, *, refresh: bool = False
) -> tuple[dict[str, Any], str | None]:
    path = cache_dir / "sleeper_players_nfl.json"
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8")), _sha256_file(path)
    from src.public_league.sleeper_client import fetch_nfl_players

    data = fetch_nfl_players()
    if not data:
        return {}, None
    slim = {
        str(pid): {
            "position": p.get("position"),
            "fantasy_positions": p.get("fantasy_positions"),
            "gsis_id": (p.get("gsis_id") or "").strip() or None,
            "espn_id": str(p.get("espn_id") or "").strip() or None,
            "full_name": p.get("full_name"),
        }
        for pid, p in data.items()
        if isinstance(p, dict)
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(slim, sort_keys=True), encoding="utf-8")
    return slim, _sha256_file(path)


# ── nflverse parsers ─────────────────────────────────────────────────────────


def parse_players_csv(path: Path) -> dict[str, tuple[str, str]]:
    """``{gsis_id: (pff_position, position)}``."""
    out: dict[str, tuple[str, str]] = {}
    for row in _read_csv(path, ("gsis_id", "pff_position", "position")):
        gid = (row["gsis_id"] or "").strip()
        if gid:
            out[gid] = ((row["pff_position"] or "").strip(), (row["position"] or "").strip())
    return out


def parse_stats_player_week(
    path: Path, season: int
) -> tuple[dict[int, dict[str, tuple[str, str]]], dict[int, dict[str, dict[str, float]]]]:
    """``(team_of_by_gsis, offense_volume)`` for REG weeks of ``season``."""
    team_of: dict[int, dict[str, tuple[str, str]]] = defaultdict(dict)
    offense: dict[int, dict[str, dict[str, float]]] = defaultdict(
        lambda: defaultdict(lambda: {"dropbacks": 0.0, "wr_targets": 0.0})
    )
    cols = (
        "player_id",
        "season",
        "week",
        "season_type",
        "team",
        "opponent_team",
        "position",
        "attempts",
        "sacks_suffered",
        "targets",
    )
    for row in _read_csv(path, cols):
        if str(row["season"]) != str(season) or row["season_type"] != "REG":
            continue
        try:
            w = int(row["week"])
        except ValueError:
            continue
        team, opp = _team(row["team"]), _team(row["opponent_team"])
        if not team or not opp:
            continue
        team_of[w][row["player_id"]] = (team, opp)
        vol = offense[w][team]
        vol["dropbacks"] += _num(row["attempts"]) + _num(row["sacks_suffered"])
        if (row["position"] or "").upper() == "WR":
            vol["wr_targets"] += _num(row["targets"])
    return (
        {w: dict(v) for w, v in team_of.items()},
        {w: {t: dict(x) for t, x in v.items()} for w, v in offense.items()},
    )


def parse_games(path: Path, season: int) -> dict[str, Any]:
    """Schedule, first kickoff (UTC) and finality per REG week."""
    from zoneinfo import ZoneInfo

    et = ZoneInfo("America/New_York")
    schedule: dict[int, dict[str, str]] = defaultdict(dict)
    first: dict[int, datetime] = {}
    last_day: dict[int, str] = {}
    games: dict[int, int] = defaultdict(int)
    finals: dict[int, int] = defaultdict(int)
    for row in _read_csv(path):
        if str(row.get("season")) != str(season) or row.get("game_type") != "REG":
            continue
        w = int(row["week"])
        home, away = _team(row["home_team"]), _team(row["away_team"])
        schedule[w][home] = away
        schedule[w][away] = home
        games[w] += 1
        if (row.get("result") or "").strip() not in ("", "NA"):
            finals[w] += 1
        day = row.get("gameday") or ""
        try:
            local = datetime.fromisoformat(f"{day}T{row.get('gametime') or '00:00'}:00").replace(
                tzinfo=et
            )
            utc = local.astimezone(timezone.utc)
            if w not in first or utc < first[w]:
                first[w] = utc
        except ValueError:
            pass
        if day > last_day.get(w, ""):
            last_day[w] = day
    final_weeks = sorted(w for w in games if games[w] and finals[w] == games[w])
    return {
        "schedule": {w: dict(v) for w, v in schedule.items()},
        "firstKickoffUtc": first,
        "lastGameday": last_day,
        "finalWeeks": final_weeks,
    }


def parse_injuries(path: Path, season: int) -> dict[int, dict[str, dict[str, str]]]:
    """``{week: {team: {gsis_id: report_status}}}`` (REG, non-empty status only)."""
    out: dict[int, dict[str, dict[str, str]]] = defaultdict(lambda: defaultdict(dict))
    for row in _read_csv(path, ("season", "game_type", "team", "week", "gsis_id", "report_status")):
        if str(row["season"]) != str(season) or row["game_type"] != "REG":
            continue
        status = (row["report_status"] or "").strip()
        if not status or status == "NA" or not row["gsis_id"]:
            continue
        out[int(row["week"])][_team(row["team"])][row["gsis_id"]] = status
    return {w: {t: dict(x) for t, x in v.items()} for w, v in out.items()}


def ftn_publication_lag_days(path: Path, last_gameday: Mapping[int, str]) -> dict[int, float]:
    """Per week: days from the week's last gameday to the EARLIEST FTN ``date_pulled``."""
    earliest: dict[int, str] = {}
    for row in _read_csv(path, ("week", "date_pulled")):
        try:
            w = int(row["week"])
        except ValueError:
            continue
        dp = row["date_pulled"] or ""
        if dp and (w not in earliest or dp < earliest[w]):
            earliest[w] = dp
    out: dict[int, float] = {}
    for w, dp in sorted(earliest.items()):
        day = last_gameday.get(w)
        if not day:
            continue
        pulled = datetime.fromisoformat(dp.replace("Z", "+00:00"))
        end = datetime.fromisoformat(f"{day}T23:59:59").replace(tzinfo=timezone.utc)
        out[w] = round((pulled - end).total_seconds() / 86400.0, 2)
    return out


# ── pre-kickoff archive census ───────────────────────────────────────────────


def _stamp_utc(value: Any) -> datetime | None:
    """A provider stamp (ISO string or epoch milliseconds) as UTC, else ``None``."""
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            return datetime.fromtimestamp(float(value) / 1000.0, tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def count_prekickoff_snapshots(
    season: int, weeks: Iterable[int], first_kickoff: Mapping[int, datetime], roots: Sequence[Path]
) -> dict[str, Any]:
    """Genuine pre-kickoff captures: ``fetchedAt`` AND every provider ``updated_at``
    strictly before the week's first kickoff."""
    from src.ros.weekly_projection_archive import list_captures, load_capture

    out: dict[str, Any] = {"roots": [], "captures": 0, "genuinePreKickoff": 0, "byWeek": {}}
    for root in roots:
        # the last three path parts only: no machine-local prefix in evidence
        out["roots"].append({"path": "/".join(root.parts[-3:]), "exists": root.is_dir()})
        if not root.is_dir():
            continue
        for w in sorted(set(weeks)):
            ko = first_kickoff.get(w)
            for cap in list_captures(season, w, base_dir=root):
                out["captures"] += 1
                if ko is None or not cap.readable or not cap.fetched_at:
                    continue
                fetched = datetime.fromisoformat(cap.fetched_at.replace("Z", "+00:00"))
                if fetched >= ko:
                    continue
                data = load_capture(cap.path)
                latest = _stamp_utc(data.get("providerUpdatedAtMax"))
                if latest is None or latest >= ko:
                    # an unprovable provider stamp is not "before kickoff"
                    continue
                out["genuinePreKickoff"] += 1
                out["byWeek"][str(w)] = out["byWeek"].get(str(w), 0) + 1
    return out


# ── assembly ─────────────────────────────────────────────────────────────────


def build_season(
    season: int,
    sleeper_weeks: Mapping[int, Mapping[str, Mapping[str, Any]]],
    sleeper_players: Mapping[str, Mapping[str, Any]],
    nfl_players: Mapping[str, tuple[str, str]],
    roster_xwalk: Mapping[str, Mapping[str, str]],
    team_of: Mapping[int, Mapping[str, tuple[str, str]]],
    offense: Mapping[int, Mapping[str, Mapping[str, float]]],
    schedule: Mapping[int, Mapping[str, str]],
    injuries_gsis: Mapping[int, Mapping[str, Mapping[str, str]]],
) -> tuple[SeasonData, dict[str, Any]]:
    """Join everything onto Sleeper ids through exact published ID links (the nflverse
    roster crosswalk, else Sleeper's own ``gsis_id``).  Unjoinable rows are counted,
    never guessed."""
    positions: dict[str, tuple[str, str]] = {}
    gsis_to_sleeper: dict[str, str] = {}
    census: dict[str, Any] = {
        "idpPlayers": 0,
        "subgroupUnknown": 0,
        "noGsis": 0,
        "gsisCollisions": 0,
        "subgroupFromPff": 0,
        "pffVsOtherDisagree": 0,
    }
    for pid in sorted(sleeper_players):
        p = sleeper_players[pid]
        fam = family_of(p.get("position"), p.get("fantasy_positions"))
        xw = roster_xwalk.get(pid, {})
        gid = xw.get("gsis") or p.get("gsis_id")
        if gid:
            if gid in gsis_to_sleeper and gsis_to_sleeper[gid] != pid:
                census["gsisCollisions"] += 1
            else:
                gsis_to_sleeper[gid] = pid
        if fam is None:
            continue
        census["idpPlayers"] += 1
        pff, pos = nfl_players.get(gid or "", ("", ""))
        if not gid:
            census["noGsis"] += 1
        sg = subgroup_of(fam, pff, pos, xw.get("depth"), xw.get("position"), p.get("position"))
        if sg == "UNKNOWN":
            census["subgroupUnknown"] += 1
        # where the PFF-derived label and our other position owners disagree
        pff_sg = subgroup_of(fam, pff)
        other_sg = subgroup_of(fam, "", pos, xw.get("depth"), xw.get("position"), p.get("position"))
        if pff_sg != "UNKNOWN":
            census["subgroupFromPff"] += 1
            if other_sg != "UNKNOWN" and other_sg != pff_sg:
                census["pffVsOtherDisagree"] += 1
                key = f"{pff_sg}->{other_sg}"
                census.setdefault("disagreeByPair", {})[key] = (
                    census.get("disagreeByPair", {}).get(key, 0) + 1
                )
        positions[pid] = (fam, sg)
    injury = {
        w: {
            t: {gsis_to_sleeper[g]: s for g, s in m.items() if g in gsis_to_sleeper}
            for t, m in teams.items()
        }
        for w, teams in injuries_gsis.items()
    }
    data = SeasonData(
        season=season,
        stats={int(w): dict(v) for w, v in sleeper_weeks.items()},
        team_of={int(w): dict(v) for w, v in team_of.items()},
        offense={int(w): dict(v) for w, v in offense.items()},
        schedule={int(w): dict(v) for w, v in schedule.items()},
        injury_report=injury,
        positions=positions,
    )
    return data, census
