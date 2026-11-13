"""Build ``pinned_cache.zip``: a trimmed, public-data-only copy of the pinned IDP-accuracy
research cache (``data/idp_accuracy/cache``, gitignored, ~33 MB).

Three tests read that cache (``tests/league_valuation/test_replacement_shadow.py`` x2,
``tests/idp_accuracy/test_scoring_sensitivity.py`` x1) and skipped wherever it was absent
(CI).  This keeps only what they read:

* league / rosters / matchups bodies: whitelisted fields only.  No owner ids, co-owners,
  league name, avatars, chat fields, metadata or per-roster settings.
* Sleeper ``players/nfl`` directory: public NFL facts (position, team, status, name, ids)
  for players that are rostered, in a matchup, or at a fantasy position.
* weekly stat lines for those players (public NFL box-score stats).
* nflverse schedules (columns read) and rosters (columns read).

Usage: ``python tests/fixtures/idp_accuracy/build_pinned_cache.py <source cache dir>``.
Deterministic: sorted members, fixed timestamps, compact sorted JSON.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))

import scripts.idp_accuracy.scoring_sensitivity as S  # noqa: E402

OUT = HERE / "pinned_cache.zip"
FANTASY_POS = {
    "QB", "RB", "FB", "WR", "TE", "K", "DL", "DE", "DT", "NT", "EDGE",
    "LB", "OLB", "ILB", "MLB", "DB", "CB", "S", "FS", "SS",
}  # fmt: skip
LEAGUE_KEEP = ("league_id", "previous_league_id", "season", "season_type", "sport", "status",
               "scoring_settings", "roster_positions", "total_rosters")  # fmt: skip
SETTINGS_KEEP = ("num_teams", "taxi_slots", "reserve_slots", "best_ball")
ROSTER_KEEP = ("roster_id", "players", "starters", "reserve", "taxi")
MATCHUP_KEEP = ("matchup_id", "roster_id", "players", "starters", "points", "players_points")
PLAYER_KEEP = ("player_id", "position", "fantasy_positions", "team", "status", "injury_status",
               "full_name", "first_name", "last_name", "depth_chart_position", "gsis_id")  # fmt: skip
GAMES_KEEP = ("game_id", "season", "game_type", "week", "away_team", "home_team")
ROSTER_CSV_KEEP = ("season", "team", "position", "depth_chart_position", "full_name",
                   "gsis_id", "sleeper_id")  # fmt: skip


def _name(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24] + ".json"


def _dump(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()


def _pick(d: dict, keys) -> dict:
    return {k: d[k] for k in keys if k in d}


def _trim_csv(raw: bytes, keep, row_ok=lambda r: True) -> bytes:
    rows = [r for r in csv.DictReader(io.StringIO(raw.decode("utf-8"))) if row_ok(r)]
    buf = io.StringIO()
    w = csv.DictWriter(
        buf, fieldnames=[k for k in keep if rows and k in rows[0]], lineterminator="\n"
    )
    w.writeheader()
    for r in rows:
        w.writerow({k: r[k] for k in w.fieldnames})
    return buf.getvalue().encode()


def main(src: Path) -> None:
    sl = S.SLEEPER
    league_id = S.load_config()["league"]["sleeperLeagueId"]

    def read(url: str):
        return json.loads((src / _name(url)).read_bytes())

    league = read(f"{sl}/league/{league_id}")
    rosters = read(f"{sl}/league/{league_id}/rosters")
    members: dict[str, bytes] = {}

    def put_league(lg: dict) -> dict:
        out = _pick(lg, LEAGUE_KEEP)
        out["settings"] = _pick(lg.get("settings") or {}, SETTINGS_KEEP)
        return out

    members[_name(f"{sl}/league/{league_id}")] = _dump(put_league(league))
    members[_name(f"{sl}/league/{league_id}/rosters")] = _dump(
        [_pick(r, ROSTER_KEEP) for r in rosters]
    )
    prev = league.get("previous_league_id")
    for _ in S.SEASONS_PRIOR:
        if not prev or str(prev) == "0":
            break
        pl = read(f"{sl}/league/{prev}")
        members[_name(f"{sl}/league/{prev}")] = _dump(put_league(pl))
        prev = pl.get("previous_league_id")

    keep_ids = {
        str(p) for r in rosters for k in ("players", "reserve", "taxi") for p in r.get(k) or []
    }
    for w in S.STUDY_WEEKS:
        url = f"{sl}/league/{league_id}/matchups/{w}"
        mu = read(url)
        members[_name(url)] = _dump([_pick(m, MATCHUP_KEEP) for m in mu])
        for m in mu:
            keep_ids |= {str(p) for p in m.get("players") or []}
            keep_ids |= {str(p) for p in (m.get("players_points") or {})}

    pdb = read(f"{sl}/players/nfl")
    keep_ids |= {
        pid for pid, meta in pdb.items() if str(meta.get("position") or "").upper() in FANTASY_POS
    }
    members[_name(f"{sl}/players/nfl")] = _dump(
        {pid: _pick(meta, PLAYER_KEEP) for pid, meta in pdb.items() if pid in keep_ids}
    )

    for season, weeks in S.ALL_WEEKS.items():
        for w in weeks:
            url = f"{sl}/stats/nfl/regular/{season}/{w}"
            dump = read(url)
            members[_name(url)] = _dump(
                {
                    pid: line
                    for pid, line in dump.items()
                    if str(pid) in keep_ids or not str(pid).isdigit()
                }
            )

    nv = src / "nflverse"
    members["nflverse/schedules__games.csv"] = _trim_csv(
        (nv / "schedules__games.csv").read_bytes(), GAMES_KEEP,
        lambda r: r.get("season") in {"2024", "2025", "2026"},
    )  # fmt: skip
    for key in ("roster_2025", "roster_2026"):
        members[f"nflverse/rosters__{key}.csv"] = _trim_csv(
            (nv / f"rosters__{key}.csv").read_bytes(), ROSTER_CSV_KEEP
        )

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(members):
            zi = zipfile.ZipInfo(name, date_time=(2026, 11, 8, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zi, members[name])
    raw = sum(len(v) for v in members.values())
    print(f"{len(members)} members, {raw / 1e6:.1f} MB raw, {OUT.stat().st_size / 1e6:.2f} MB zip")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
