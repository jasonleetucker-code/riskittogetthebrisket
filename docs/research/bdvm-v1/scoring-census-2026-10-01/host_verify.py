#!/usr/bin/env python3
"""Host verification of the ``bonus_rec_<pos>`` mapping against Sleeper.

Every committed Sleeper golden fixture carries ``bonus_rec_wr/_rb = 0.0``, so
"the host pays this per reception, by position" was an assumption until it
was checked against host-AWARDED points.  This script checks it on real
dynasty_main weeks, read-only, from public Sleeper endpoints fetched into
``--dir`` beforehand (no auth):

* ``league.json``           GET /v1/league/<id>            (the live card)
* ``matchups_wk<N>.json``   GET /v1/league/<id>/matchups/<N>  (players_points)
* ``stats_wk<N>.json``      GET /v1/stats/nfl/regular/<season>/<N>
* ``players.json``          GET /v1/players/nfl            (positions)
* ``weekly.json.gz``        nflverse weekly rows for those weeks (engine input)

Three checks, each a different claim:

1. **host rule** — the host's own stat line scored by the golden-validated
   exact scorer (``src.league_intel.scorer``) reproduces ``players_points``
   WITH the card's ``bonus_rec_wr`` and misses it WITHOUT.
2. **stat identity** — Sleeper's ``bonus_rec_<pos>`` stat equals its ``rec``
   for every receiver, i.e. the bonus is a per-reception rate keyed by the
   listed position.  FB lines are inspected separately.
3. **engine** — ``realized_points.compute_weekly_points`` on the nflverse row,
   under a card carrying only ``bonus_rec_wr``, equals the host's bonus
   contribution (host points minus the no-bonus rescoring).  WR rows are
   joined by gsis_id, else by a UNIQUE normalized (week, name); ambiguous
   names are dropped, never guessed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from src.league_intel.scorer import score_stat_line  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.utils.name_clean import normalize_player_name  # noqa: E402

TOL = 0.011  # the host publishes two decimals; R4 (W18) used the same tolerance


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dir", required=True, type=Path)
    ap.add_argument("--weeks", default="1,2,3")
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    d = a.dir
    weeks = [int(w) for w in a.weeks.split(",")]
    league = json.loads((d / "league.json").read_text(encoding="utf-8"))
    card = league["scoring_settings"]
    nob = {**card, "bonus_rec_wr": 0.0}
    players = json.loads((d / "players.json").read_text(encoding="utf-8"))
    with gzip.open(d / "weekly.json.gz", "rt", encoding="utf-8") as fh:
        rows = json.load(fh)

    host: dict[str, Counter] = {}
    stat_identity: Counter = Counter()
    fb_lines: list[dict] = []
    examples: list[dict] = []
    stats_by_week = {}
    for w in weeks:
        m = json.loads((d / f"matchups_wk{w}.json").read_text(encoding="utf-8"))
        st = json.loads((d / f"stats_wk{w}.json").read_text(encoding="utf-8"))
        stats_by_week[w] = (m, st)
        for pid, line in st.items():
            pos = (players.get(pid) or {}).get("position")
            for k in ("bonus_rec_wr", "bonus_rec_rb", "bonus_rec_te"):
                if k in line:
                    stat_identity[
                        f"{pos}:{k}:{'eq_rec' if line[k] == line.get('rec') else 'NE_rec'}"
                    ] += 1
            if pos == "FB" and line.get("rec"):
                fb_lines.append(
                    {
                        "week": w,
                        "sleeperId": pid,
                        "fantasyPositions": (players.get(pid) or {}).get("fantasy_positions"),
                        "rec": line.get("rec"),
                        "rec_fd": line.get("rec_fd"),
                        "bonus_rec_rb": line.get("bonus_rec_rb"),
                        "bonus_fd_rb": line.get("bonus_fd_rb"),
                    }
                )
        for mm in m:
            for pid, pts in (mm.get("players_points") or {}).items():
                line = st.get(pid)
                if line is None:
                    continue
                pos = (players.get(pid) or {}).get("position")
                grp = pos if pos in ("QB", "RB", "WR", "TE", "FB") else "other"
                c = host.setdefault(grp, Counter())
                with_b = score_stat_line(line, card).total_points
                without = score_stat_line(line, nob).total_points
                c["playerWeeks"] += 1
                c["matchWithBonus"] += abs(with_b - float(pts)) <= TOL
                c["matchWithoutBonus"] += abs(without - float(pts)) <= TOL
                if pos == "WR" and float(line.get("rec") or 0) > 0:
                    c["withReceptions"] += 1
                if pos == "WR" and float(line.get("rec") or 0) >= 5 and len(examples) < 5:
                    examples.append(
                        {
                            "week": w,
                            "sleeperId": pid,
                            "rec": line["rec"],
                            "hostPoints": float(pts),
                            "rescoredWithBonus": round(with_b, 4),
                            "rescoredWithoutBonus": round(without, 4),
                        }
                    )

    # Engine check.
    g2s = {str(v.get("gsis_id") or "").strip(): k for k, v in players.items() if v.get("gsis_id")}
    by = {(int(r.get("week") or 0), g2s.get(str(r.get("player_id") or ""))): r for r in rows}
    names: dict = {}
    for r in rows:
        if str(r.get("position") or "").upper() == "WR":
            k = (int(r.get("week") or 0), normalize_player_name(r.get("player_display_name") or ""))
            names.setdefault(k, []).append(r)
    for pid, p in players.items():
        if p.get("position") != "WR" or (p.get("gsis_id") or "").strip():
            continue
        for w in weeks:
            cand = names.get((w, normalize_player_name(p.get("full_name") or "")), [])
            if len(cand) == 1:
                by.setdefault((w, pid), cand[0])
    only = {"bonus_rec_wr": card["bonus_rec_wr"]}
    eng: Counter = Counter()
    worst = 0.0
    for w in weeks:
        m, st = stats_by_week[w]
        for mm in m:
            for pid, pts in (mm.get("players_points") or {}).items():
                if (players.get(pid) or {}).get("position") != "WR" or pid not in st:
                    continue
                line = st[pid]
                if not float(line.get("rec") or 0):
                    continue
                eng["wrWeeksWithReceptions"] += 1
                row = by.get((w, pid))
                if row is None:
                    eng["unjoined"] += 1
                    continue
                eng["joined"] += 1
                eng["receptionsEqual"] += float(row.get("receptions") or 0) == float(line["rec"])
                host_bonus = float(pts) - score_stat_line(line, nob).total_points
                rp = compute_weekly_points(row, only, position="WR")
                got = rp.fantasy_points if rp else 0.0
                worst = max(worst, abs(got - host_bonus))
                eng["engineMatchesHostBonus"] += abs(got - host_bonus) <= TOL

    doc = {
        "scope": "LOCAL read-only check against the PUBLIC Sleeper API",
        "league": {
            "leagueKey": "dynasty_main",
            "season": league.get("season"),
            "cardRates": {
                k: card.get(k) for k in ("rec", "bonus_rec_wr", "bonus_rec_rb", "bonus_rec_te")
            },
        },
        "weeks": weeks,
        "inputs": {
            p.name: _sha(p)
            for p in sorted(d.iterdir())
            if p.name == "league.json"
            or p.name == "weekly.json.gz"
            or p.name.startswith(("matchups_wk", "stats_wk"))
        },
        "tolerance": TOL,
        "hostRule": {g: dict(c) for g, c in sorted(host.items())},
        "statIdentity": dict(sorted(stat_identity.items())),
        "fbReceptionLines": fb_lines,
        "engine": {**dict(eng), "maxAbsDelta": round(worst, 4)},
        "examples": examples,
    }
    a.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: doc[k] for k in ("hostRule", "statIdentity", "engine")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
