#!/usr/bin/env python3
"""Host-golden check: which nflverse column is Sleeper's ``idp_fum_rec``?

The census (``../scoring-census-2026-10-01``) found the realized engine
reading ``fumble_recovery_own`` for the IDP fumble-recovery rule while 2025
defenders carry 16 own vs 235 opp recoveries.  This script decides it
against the HOST's own data, read-only, from public Sleeper endpoints
fetched into ``--sleeper-dir`` beforehand (no auth):

* ``league.json``           GET /v1/league/<id>                (2025 card)
* ``stats_wk<N>.json``      GET /v1/stats/nfl/regular/2025/<N> (N = 1..18)
* ``matchups_wk<N>.json``   GET /v1/league/<id>/matchups/<N>   (N = 1..17)

plus ``--players`` (GET /v1/players/nfl, positions + gsis ids), the nflverse
2025 weekly rows (``--weekly``, engine input) and, optionally, the
play-by-play supplement (``--pbp``, ``pbp_weekly.persist_pbp_weekly``).

Three different claims, each its own check:

1. **stat identity** — over every IDP-eligible joined player-week with any
   recovery on either side, which nflverse quantity equals the host's
   ``idp_fum_rec`` stat: ``own``, ``opp``, or ``opp − st_fum_rec`` (the
   host's own special-teams recovery stat, and separately the PBP-derived
   one).  Same for ``idp_fum_ret_yd`` against the yardage columns.
2. **host rule** — the host pays ``idp_fum_rec`` / ``idp_fum_ret_yd`` on its
   OWN stat line: ``players_points`` minus the line rescored WITHOUT those
   two rules equals the line scored with ONLY them (golden-validated exact
   scorer), on every rostered player-week.
3. **engine** — ``realized_points.compute_weekly_points`` on the nflverse
   row (with the PBP supplement attached when supplied), under a card
   carrying only those two rules, equals the host's awarded contribution
   (``players_points`` minus the no-FR rescoring).

Joins: gsis id, else a UNIQUE normalized (week, name) whose nflverse
position is in the same family as the host's (any IDP family counts as one:
edge rushers are DL to the host and LB to nflverse) — ambiguous or
offense/defense-crossing names are dropped, never guessed (the latter is a
measured trap: a WR ``DJ Turner`` joined by name alone to the CB ``DJ Turner``).

``--fixture`` writes the minimal NUMERIC fixture the regression test reads:
no names, no ids — only nflverse columns, the PBP count, the host stats and
the host-awarded contribution per player-week.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT))

from src.league_intel.scorer import score_stat_line  # noqa: E402
from src.nfl_data.pbp_weekly import PbpWeeklyStats, attach_supplement  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.utils.name_clean import POSITION_ALIASES, normalize_player_name  # noqa: E402

TOL = 0.011  # host publishes two decimals; W18 / the census used the same
FR_KEYS = ("idp_fum_rec", "idp_fum_ret_yd")
IDP_FAMILIES = {"DL", "LB", "DB"}


def _family(pos: str | None) -> str:
    p = str(pos or "").upper()
    return POSITION_ALIASES.get(p, p)


def _f(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sleeper-dir", required=True, type=Path)
    ap.add_argument("--players", required=True, type=Path)
    ap.add_argument("--weekly", required=True, type=Path)
    ap.add_argument("--pbp", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fixture", type=Path)
    a = ap.parse_args()
    d = a.sleeper_dir

    league = json.loads((d / "league.json").read_text(encoding="utf-8"))
    card = league["scoring_settings"]
    no_fr = {k: v for k, v in card.items() if k not in FR_KEYS}
    only_fr = {k: card[k] for k in FR_KEYS if k in card}
    players = json.loads(a.players.read_text(encoding="utf-8"))
    with gzip.open(a.weekly, "rt", encoding="utf-8") as fh:
        rows = [r for r in json.load(fh) if r.get("season_type") == "REG"]
    pbp = None
    if a.pbp:
        payload = json.loads(a.pbp.read_text(encoding="utf-8").splitlines()[0])
        pbp = PbpWeeklyStats.from_payload(payload)

    by_gsis = {(int(r["week"]), str(r["player_id"])): r for r in rows}
    by_name: dict = defaultdict(list)
    for r in rows:
        by_name[(int(r["week"]), normalize_player_name(r.get("player_display_name") or ""))].append(
            r
        )

    def join(pid: str, week: int):
        p = players.get(pid) or {}
        g = str(p.get("gsis_id") or "").strip()
        if g and (week, g) in by_gsis:
            return by_gsis[(week, g)]
        cand = by_name.get((week, normalize_player_name(p.get("full_name") or "")), [])
        fam = _family(p.get("position"))
        cand = [
            r
            for r in cand
            if _family(r.get("position")) == fam
            # Edge rushers are DL to the host and LB to nflverse; both IDP.
            or (_family(r.get("position")) in IDP_FAMILIES and fam in IDP_FAMILIES)
        ]
        return cand[0] if len(cand) == 1 else None

    identity: Counter = Counter()
    yards: Counter = Counter()
    host_rule: Counter = Counter()
    engine: Counter = Counter()
    worst = 0.0
    fixture: list[dict] = []
    weeks = sorted(
        int(p.stem.split("wk")[1]) for p in d.glob("stats_wk*.json") if p.stem[8:].isdigit()
    )
    for w in weeks:
        st = json.loads((d / f"stats_wk{w}.json").read_text(encoding="utf-8"))
        mp = d / f"matchups_wk{w}.json"
        points = {}
        if mp.exists():
            for m in json.loads(mp.read_text(encoding="utf-8")):
                points.update(m.get("players_points") or {})
        for pid, line in st.items():
            if not pid.isdigit():
                continue
            row = join(pid, w)
            h_fr, h_yd, h_st = (
                _f(line.get("idp_fum_rec")),
                _f(line.get("idp_fum_ret_yd")),
                _f(line.get("st_fum_rec")),
            )
            if row is None:
                if h_fr:
                    identity["hostRecoveriesUnjoined"] += 1
                continue
            idp = _family(row.get("position")) in IDP_FAMILIES
            own, opp = _f(row.get("fumble_recovery_own")), _f(row.get("fumble_recovery_opp"))
            yown, yopp = (
                _f(row.get("fumble_recovery_yards_own")),
                _f(row.get("fumble_recovery_yards_opp")),
            )
            sup = attach_supplement(row, pbp).get("pbp_derived") if pbp else None
            pbp_st = _f((sup or {}).get("st_fum_rec")) if sup is not None else None
            if idp and (h_fr or own or opp):
                identity["idpPlayerWeeks"] += 1
                identity["host"] += h_fr
                identity["own"] += own
                identity["opp"] += opp
                identity["hostStFumRec"] += h_st
                identity["eqOwn"] += h_fr == own
                identity["eqOpp"] += h_fr == opp
                identity["eqOppMinusHostSt"] += h_fr == max(0.0, opp - h_st)
                if pbp_st is not None:
                    identity["pbpConsulted"] += 1
                    identity["eqOppMinusPbpSt"] += h_fr == max(0.0, opp - pbp_st)
                    identity["pbpStEqualsHostSt"] += pbp_st == h_st
            if idp and (h_yd or yown or yopp):
                yards["idpPlayerWeeks"] += 1
                yards["eqOwn"] += h_yd == yown
                yards["eqOpp"] += h_yd == yopp

            if pid not in points:
                continue
            awarded = float(points[pid])
            host_contrib = awarded - score_stat_line(line, no_fr).total_points
            on_line = score_stat_line(line, only_fr).total_points
            host_rule["rosteredPlayerWeeks"] += 1
            host_rule["match"] += abs(host_contrib - on_line) <= TOL
            if not (idp and (h_fr or h_yd or own or opp or yown or yopp)):
                continue
            host_rule["rosteredIdpWithRecoveryActivity"] += 1
            host_rule["matchOnActivity"] += abs(host_contrib - on_line) <= TOL
            engine_row = attach_supplement(row, pbp) if pbp else dict(row)
            rp = compute_weekly_points(engine_row, only_fr, position=row.get("position"))
            got = rp.fantasy_points if rp else 0.0
            engine["joined"] += 1
            engine["match"] += abs(got - host_contrib) <= TOL
            worst = max(worst, abs(got - host_contrib))
            fixture.append(
                {
                    "week": w,
                    "position": row.get("position"),
                    "fumble_recovery_own": own,
                    "fumble_recovery_opp": opp,
                    "fumble_recovery_yards_own": yown,
                    "fumble_recovery_yards_opp": yopp,
                    "pbp_st_fum_rec": pbp_st,
                    "host_idp_fum_rec": h_fr,
                    "host_idp_fum_ret_yd": h_yd,
                    "host_st_fum_rec": h_st,
                    "host_awarded_fr_points": round(host_contrib, 4),
                }
            )

    doc = {
        "scope": "LOCAL read-only check against the PUBLIC Sleeper API",
        "league": {
            "leagueKey": "dynasty_main",
            "season": league.get("season"),
            "cardRates": {k: card.get(k) for k in (*FR_KEYS, "st_fum_rec")},
        },
        "weeks": weeks,
        "inputs": {
            **{
                p.name: _sha(p)
                for p in sorted(d.iterdir())
                if p.name == "league.json" or p.name.startswith(("matchups_wk", "stats_wk"))
            },
            "weekly": _sha(a.weekly),
            **({"pbp": _sha(a.pbp)} if a.pbp else {}),
        },
        "tolerance": TOL,
        "statIdentity": dict(identity),
        "yardIdentity": dict(yards),
        "hostRule": dict(host_rule),
        "engine": {**dict(engine), "maxAbsDelta": round(worst, 4), "pbpAttached": bool(pbp)},
    }
    a.out.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    if a.fixture:
        a.fixture.write_text(
            json.dumps(
                {
                    "_about": (
                        "Numeric host-golden fixture for idp_fum_rec / idp_fum_ret_yd. "
                        "Rostered IDP player-weeks with recovery activity, dynasty_main "
                        "2025 REG, public Sleeper API. Produced by "
                        "docs/research/bdvm-v1/fumble-recovery-host-golden-2026-10-01/"
                        "host_golden.py; evidence in host_golden.json there."
                    ),
                    "cardRates": only_fr,
                    "tolerance": TOL,
                    "rows": fixture,
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps({k: doc[k] for k in ("statIdentity", "yardIdentity", "hostRule", "engine")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
