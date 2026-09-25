"""Rebuild the Game Day replay fixtures from raw captures (provenance record).

Run once, by hand, against the raw capture directory (not committed — the
raw files are ~30 MB):

    python tests/fixtures/game_day/replay/build_replay_fixtures.py <capture_dir>

Every trim is lossless for what the replay exercises and is listed in
``README.md``.  Synthetic mutations are built from a REAL base scenario and
say exactly what they changed in their own ``meta.mutation``.
"""

from __future__ import annotations

import copy
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
EVIDENCE = REPO / "docs" / "master-site-audit" / "evidence" / "W18"

LEAGUES = {
    "dynasty_main": ("1312006700437352448", "sleeper_league_1312006700437352448.json"),
    "dynasty_new": ("1320092771247222784", "sleeper_league_dynasty_new.json"),
}
PROJECTION_CAPTURE = "20260925T005824Z"
LATER_PROJECTION_CAPTURE = "20260925T012854Z"
REAL_SCENARIOS = {
    # scenario name -> (capture stamp, league keys)
    "real_end_q1": ("20260925T005824Z", ("dynasty_main",)),
    "real_q2_in_progress": ("20260925T011334Z", ("dynasty_main",)),
    "real_halftime": ("20260925T015008Z", ("dynasty_main", "dynasty_new")),
    "real_q3_in_progress": ("20260925T020524Z", ("dynasty_main",)),
}
YARD_KEYS = ("pass_yd", "rush_yd", "rec_yd")
TNF_TEAMS = ("GB", "ATL")


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _dump(path: Path, obj, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = (
        json.dumps(obj, sort_keys=True, separators=(",", ":"))
        if compact
        else json.dumps(obj, indent=1, sort_keys=True)
    )
    path.write_text(text + "\n", encoding="utf-8")


def _trim_scoreboard(payload: dict) -> dict:
    events = []
    for e in payload.get("events") or []:
        comp = (e.get("competitions") or [{}])[0]
        status = comp.get("status") or {}
        stype = status.get("type") or {}
        events.append(
            {
                "id": e.get("id"),
                "date": e.get("date"),
                "competitions": [
                    {
                        "date": comp.get("date"),
                        "competitors": [
                            {
                                "homeAway": c.get("homeAway"),
                                "score": c.get("score"),
                                "team": {"abbreviation": (c.get("team") or {}).get("abbreviation")},
                            }
                            for c in comp.get("competitors") or []
                        ],
                        "status": {
                            "clock": status.get("clock"),
                            "displayClock": status.get("displayClock"),
                            "period": status.get("period"),
                            "type": {
                                k: stype.get(k)
                                for k in ("name", "state", "completed", "shortDetail")
                            },
                        },
                    }
                ],
            }
        )
    return {
        "season": {"year": payload["season"]["year"], "type": payload["season"]["type"]},
        "week": {"number": payload["week"]["number"]},
        "events": events,
    }


def _trim_matchups(rows: list) -> list:
    keep = ("roster_id", "matchup_id", "points", "players", "starters", "players_points")
    return [{k: r.get(k) for k in keep} for r in rows]


def _stamp_iso(stamp: str) -> str:
    return datetime.strptime(stamp, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).isoformat()


def main(capture_dir: Path) -> None:
    leagues = {}
    for key, (_lid, fname) in LEAGUES.items():
        raw = _load(EVIDENCE / fname)
        leagues[key] = {
            "league_id": raw.get("league_id"),
            "season": raw.get("season"),
            "settings": {
                k: raw["settings"].get(k)
                for k in ("best_ball", "league_average_match", "num_teams")
            },
            "roster_positions": raw.get("roster_positions"),
            "scoring_settings": raw.get("scoring_settings"),
        }
        _dump(HERE / "shared" / f"{key}_league.json", leagues[key])

    rostered: set[str] = set()
    for stamp, keys in REAL_SCENARIOS.values():
        for key in keys:
            lid = LEAGUES[key][0]
            for m in _load(capture_dir / f"{stamp}_matchups_{lid}_w3.json"):
                rostered.update(str(p) for p in m.get("players") or [])

    rows = _load(capture_dir / f"{PROJECTION_CAPTURE}_sleeper_projections_w3.json")
    paid: set[str] = set(YARD_KEYS)
    for lg in leagues.values():
        paid |= {k for k, v in (lg["scoring_settings"] or {}).items() if float(v or 0) != 0.0}

    players: dict[str, dict] = {}
    proj_rows = []
    for r in rows:
        pid = str(r.get("player_id"))
        if pid not in rostered:
            continue
        p = r.get("player") or {}
        players[pid] = {
            "full_name": f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip(),
            "position": p.get("position"),
            "fantasy_positions": p.get("fantasy_positions"),
            "team": p.get("team"),
            "injury_status": p.get("injury_status"),
        }
        if not r.get("game_id"):
            continue  # Sleeper's no-projection placeholder: nothing to keep
        stats = {k: v for k, v in (r.get("stats") or {}).items() if k in paid and v}
        proj_rows.append(
            {
                "player_id": pid,
                "game_id": r.get("game_id"),
                "team": r.get("team"),
                "opponent": r.get("opponent"),
                "company": r.get("company"),
                "season": r.get("season"),
                "week": r.get("week"),
                "season_type": r.get("season_type"),
                "updated_at": r.get("updated_at"),
                "player": {
                    "position": p.get("position"),
                    "fantasy_positions": p.get("fantasy_positions"),
                },
                "stats": stats,
            }
        )
    proj_rows.sort(key=lambda r: r["player_id"])

    # A LATER real fetch (01:28:54Z), trimmed to the rostered rows whose stat
    # line CHANGED versus 00:58:24Z: the provider updates lines mid-game (TNF
    # included), which the kickoff lock must ignore for TNF players while
    # Sunday players (still pre-kickoff) legitimately take the newer line.
    first_stats = {str(r.get("player_id")): r.get("stats") for r in rows}
    later = []
    for r in _load(capture_dir / f"{LATER_PROJECTION_CAPTURE}_sleeper_projections_w3.json"):
        pid = str(r.get("player_id"))
        if pid not in rostered or not r.get("game_id"):
            continue
        if r.get("stats") == first_stats.get(pid):
            continue
        p = r.get("player") or {}
        later.append(
            {
                "player_id": pid,
                "game_id": r.get("game_id"),
                "team": r.get("team"),
                "opponent": r.get("opponent"),
                "company": r.get("company"),
                "season": r.get("season"),
                "week": r.get("week"),
                "season_type": r.get("season_type"),
                "updated_at": r.get("updated_at"),
                "player": {
                    "position": p.get("position"),
                    "fantasy_positions": p.get("fantasy_positions"),
                },
                "stats": {k: v for k, v in (r.get("stats") or {}).items() if k in paid and v},
            }
        )
    later.sort(key=lambda r: r["player_id"])
    _dump(
        HERE / "shared" / "projections_real_later_changed_only.json",
        {"observedAt": _stamp_iso(LATER_PROJECTION_CAPTURE), "rows": later},
        compact=True,
    )
    _dump(HERE / "shared" / "players.json", dict(sorted(players.items())), compact=True)
    _dump(
        HERE / "shared" / "projections_real.json",
        {"observedAt": _stamp_iso(PROJECTION_CAPTURE), "rows": proj_rows},
        compact=True,
    )

    # SYNTHETIC pre-kickoff fetch.  No capture predates the 00:15Z TNF
    # kickoff, and the provider's per-row updated_at cannot date a line: every
    # stamped row carries the same 00:50:12Z batch-refresh stamp.  So the TNF
    # rows are re-stamped as if fetched at 00:10Z, with the provider stamp
    # removed (unknown), under a stated, UNVERIFIABLE assumption (the lines
    # did not change between 00:10Z and 00:58Z).
    tnf_kickoff = datetime(2026, 9, 25, 0, 15, tzinfo=timezone.utc)
    pre = [dict(r, updated_at=None) for r in proj_rows if r["team"] in TNF_TEAMS]
    _dump(
        HERE / "shared" / "projections_synthetic_pre_kickoff.json",
        {
            "observedAt": (tnf_kickoff - timedelta(minutes=5)).isoformat(),
            "synthetic": (
                "NOT a provider capture: the REAL 20260925T005824Z rows for GB/ATL players "
                "re-stamped as if fetched at 00:10Z (5 min before the 00:15Z kickoff), "
                "provider updated_at removed. UNVERIFIABLE ASSUMPTION: the lines did not "
                "change between 00:10Z and 00:58Z. The provider DOES change lines mid-game "
                "(the 01:28:54Z fetch changed 254 players' stat lines, GB/ATL included), and "
                "its row stamps are one batch-refresh stamp that cannot date a line. Used "
                "only to exercise the in-progress path; not evidence of a real baseline."
            ),
            "rows": pre,
        },
    )

    scenarios: dict[str, dict] = {}
    for name, (stamp, keys) in REAL_SCENARIOS.items():
        scenario = {
            "meta": {
                "kind": "real",
                "capturedAt": _stamp_iso(stamp),
                "description": f"Real capture {stamp} (Thursday GB@ATL in play, Sunday games scheduled)",
                "mutation": None,
            },
            "espn": _trim_scoreboard(_load(capture_dir / f"{stamp}_espn_scoreboard.json")),
            "matchups": {
                key: _trim_matchups(
                    _load(capture_dir / f"{stamp}_matchups_{LEAGUES[key][0]}_w3.json")
                )
                for key in keys
            },
        }
        scenarios[name] = scenario

    base = scenarios["real_halftime"]

    def _mutate(name: str, description: str, mutation: str, fn) -> None:
        sc = copy.deepcopy(base)
        sc["matchups"] = {"dynasty_main": sc["matchups"]["dynasty_main"]}
        sc["meta"] = {
            "kind": "synthetic",
            "capturedAt": base["meta"]["capturedAt"],
            "description": description,
            "mutation": mutation,
        }
        fn(sc)
        scenarios[name] = sc

    def _tnf(sc):
        for e in sc["espn"]["events"]:
            teams = {c["team"]["abbreviation"] for c in e["competitions"][0]["competitors"]}
            if teams == set(TNF_TEAMS):
                return e["competitions"][0]
        raise SystemExit("TNF game missing")

    def _status(comp, name, state, period, clock, completed=False, detail=None):
        comp["status"] = {
            "clock": clock,
            "displayClock": f"{int(clock) // 60}:{int(clock) % 60:02d}",
            "period": period,
            "type": {
                "name": name,
                "state": state,
                "completed": completed,
                "shortDetail": detail or name,
            },
        }

    def _scores(comp, home, away):
        for c in comp["competitors"]:
            c["score"] = str(home if c["homeAway"] == "home" else away)

    def overtime(sc):
        comp = _tnf(sc)
        _status(comp, "STATUS_IN_PROGRESS", "in", 5, 480.0)
        _scores(comp, 20, 20)

    def end_regulation_tied(sc):
        comp = _tnf(sc)
        _status(comp, "STATUS_END_PERIOD", "in", 4, 0.0)
        _scores(comp, 20, 20)

    def delayed(sc):
        _status(_tnf(sc), "STATUS_DELAYED", "in", 3, 600.0, detail="Weather delay")

    def postponed_sunday(sc):
        for e in sc["espn"]["events"]:
            comp = e["competitions"][0]
            if comp["status"]["type"]["name"] == "STATUS_SCHEDULED":
                _status(comp, "STATUS_POSTPONED", "pre", 0, 0.0, detail="Postponed")
                sc["meta"]["postponedEventId"] = e["id"]
                return

    def final(sc):
        comp = _tnf(sc)
        _status(comp, "STATUS_FINAL", "post", 4, 0.0, completed=True, detail="Final")
        _scores(comp, 17, 24)

    _mutate(
        "synthetic_overtime",
        "Halftime base; GB@ATL rewritten to overtime (period 5, tied 20-20)",
        "espn: TNF status -> STATUS_IN_PROGRESS period 5 clock 8:00, scores 20-20",
        overtime,
    )
    _mutate(
        "synthetic_end_regulation_tied",
        "Halftime base; GB@ATL rewritten to end of Q4 tied (overtime possible)",
        "espn: TNF status -> STATUS_END_PERIOD period 4 clock 0:00, scores 20-20",
        end_regulation_tied,
    )
    _mutate(
        "synthetic_delayed",
        "Halftime base; GB@ATL rewritten to an in-game weather delay",
        "espn: TNF status -> STATUS_DELAYED state in, period 3",
        delayed,
    )
    _mutate(
        "synthetic_postponed",
        "Halftime base; the first scheduled Sunday game rewritten to postponed",
        "espn: first STATUS_SCHEDULED event -> STATUS_POSTPONED state pre",
        postponed_sunday,
    )
    _mutate(
        "synthetic_final",
        "Halftime base; GB@ATL rewritten FINAL (17-24), halftime player points kept as final",
        "espn: TNF status -> STATUS_FINAL completed; matchups unchanged",
        final,
    )
    for name, sc in scenarios.items():
        _dump(HERE / name / "scenario.json", sc)
    print(
        f"wrote {len(scenarios)} scenarios, {len(proj_rows)} projection rows, {len(pre)} pre-kickoff"
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
