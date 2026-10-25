#!/usr/bin/env python3
"""Low-value-asset research — the IDP replacement-value anomaly.  RESEARCH ONLY.

Owner question (2026-10-20): in ``dynasty_main`` the best UNROSTERED player at
each IDP position is valued ABOVE the lowest rostered STARTER at that position
(``shadow_replay.json`` -> ``S1_replacementAnchors``: DB 2,156 vs 1,335, LB
2,149 vs 1,474, DL 1,918 vs 1,539).  Why?

Hypotheses, tested in order:

* **H1 data defect** — the "best unrostered" are not really available
  (identity-join miss between the board and ``sleeper.teams[].players``, a
  stale roster snapshot, a name collision, a retired / teamless player).
* **H2 lineup definition** — what objective solved the "12 optimal lineups".
* **H3 league-scoring mismatch** — is canonical IDP value a much weaker
  predictor of THIS league's IDP production than canonical offense value is of
  offense production?
* **H4 manager behaviour** — do managers roster IDP by production rather than
  by canonical value (or simply sit on stale rosters)?
* **H5 board movement** — did the high-value unrostered IDP rise on the board
  after rosters settled?

Inputs (all read-only):

* today's board — the newest tracked export archive built through
  ``build_api_data_contract`` with TODAY's code, exactly as
  ``scripts/low_value_asset_shadow_replay.py::build_context`` builds it (that
  function is imported, so the anomaly numbers are reproduced, not re-derived);
* the genuine SERVED pre-season board (2026-08-25 golden board) for H3/H5;
* sensitivity replays: TODAY's code over older archives (inputs move, the
  methodology is held constant) for H5;
* Sleeper's public API: live rosters, the player directory, weekly matchups,
  weekly stat dumps (scored under the league's own card by the canonical scorer
  ``compute_weekly_points(source="sleeper")``, validated here against the
  host's ``players_points``), and weekly transactions (aggregate counts only).

Output: ``docs/valuation/evidence/low_value_assets_2026-10-20/idp_anomaly.json``
— aggregates plus NFL player names / values / stats for the top unrostered
examples.  No Sleeper league / user / roster / transaction / player id, no team
or manager name (checked with ``assert_aggregate_only``).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import statistics
import sys
import time
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/valuation/evidence/low_value_assets_2026-10-20/idp_anomaly.json"
sys.path.insert(0, str(REPO))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SR = _load("low_value_asset_shadow_replay")  # build_context / newest_board / P2 guard
LU = _load("low_value_asset_lineup_utility")  # Fetcher, preseason board, scorer glue

from scipy import stats as sps  # noqa: E402

from src.api import league_registry  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.ros.lineup import RosterPlayer, resolve_starter_slots  # noqa: E402

LEAGUE = "dynasty_main"
SEASON = 2026
SLEEPER = "https://api.sleeper.app/v1"
IDP = ("DL", "LB", "DB")
OFFENSE = ("QB", "RB", "WR", "TE")
TOP_N = 10
MIN_GAMES = 3
#: Sensitivity-replay dates for H5 (nearest archive on or before each).
REPLAY_OFFSETS_DAYS = (60, 30, 14, 0)
#: Raw Sleeper stat keys that score as TACKLES on this card (the rest of an IDP
#: line is big-play scoring: sacks, TFL, QB hits, passes defended, takeaways).
TACKLE_KEYS = ("idp_tkl_solo", "idp_tkl_ast", "idp_tkl")
_NAME_NORM = re.compile(r"[^a-z]")
_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)


def _norm(name: str) -> str:
    return _NAME_NORM.sub("", _SUFFIX.sub("", str(name or "").lower()))


def _r(x, n=0):
    if x is None:
        return None
    return round(float(x), n) if n else round(float(x))


def _median(xs):
    xs = [x for x in xs if x is not None]
    return statistics.median(xs) if xs else None


def spearman(xs: list[float], ys: list[float]) -> dict:
    if len(xs) < 8:
        return {"n": len(xs), "rho": None}
    res = sps.spearmanr(xs, ys)
    return {"n": len(xs), "rho": _r(res.statistic, 3)}


def auc(pos_vals: list[float], neg_vals: list[float]) -> float | None:
    """P(a random member of ``pos_vals`` exceeds one of ``neg_vals``) — ties 1/2."""
    if len(pos_vals) < 5 or len(neg_vals) < 5:
        return None
    u = sps.mannwhitneyu(pos_vals, neg_vals, alternative="two-sided").statistic
    return _r(u / (len(pos_vals) * len(neg_vals)), 3)


# ── data ────────────────────────────────────────────────────────────────


def archive_for(day: date) -> Path | None:
    """Newest tracked export archive taken on or before ``day``."""
    best = None
    for p in sorted((REPO / "exports" / "archive").glob("dynasty_export_*.zip")):
        d = datetime.strptime(p.name.split("_")[2], "%Y%m%d").date()
        if d <= day:
            best = p
    return best


def read_archive(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        return json.loads(zf.read(member))


def values_by_sid(contract: dict) -> dict[str, dict]:
    """Sleeper id -> {value, pos, cls, name} for every priced player row."""
    sl = contract.get("sleeper") or {}
    name_to_id = {str(k): str(v) for k, v in (sl.get("playerIds") or {}).items()}
    out: dict[str, dict] = {}
    for row in contract.get("playersArray") or []:
        if str(row.get("assetClass") or "") == "pick":
            continue
        v = row.get("rankDerivedValue")
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        sid = row.get("playerId")
        if not sid:
            for f in ("displayName", "canonicalName", "legacyRef"):
                sid = name_to_id.get(str(row.get(f) or ""))
                if sid:
                    break
        if sid:
            out[str(sid)] = {
                "value": float(v),
                "pos": (row.get("position") or "").upper(),
                "cls": row.get("assetClass"),
                "name": row.get("displayName"),
            }
    return out


def rostered_ids(sleeper_block: dict) -> set[str]:
    return {str(x) for t in (sleeper_block.get("teams") or []) for x in (t.get("playerIds") or [])}


#: Sleeper ``injury_status`` values that mean "cannot start this week".
UNAVAILABLE_INJURY = {"IR", "Out", "PUP", "Doubtful", "Sus", "NA", "DNR", "COV"}


def is_healthy(meta: dict) -> bool:
    """On an NFL team, active, and not listed out / IR / PUP / suspended."""
    return (
        bool(meta.get("team"))
        and meta.get("status")
        not in ("Inactive", "Injured Reserve", "Physically Unable to Perform")
        and meta.get("injury_status") not in UNAVAILABLE_INJURY
    )


def row_sid(r: dict, name_to_id: dict[str, str]) -> str | None:
    return r.get("pid") or name_to_id.get(r["name"]) or None


def _readout(h1, census, healthy, lowest, h3, auc_, h5, tx) -> dict:
    """Key numbers per hypothesis, pulled from the computed sections (no new math)."""
    above = {p: census[p]["n"] for p in IDP}
    rho = h3["ppg"]

    def g(src, cls, which="all", band="allValues"):
        return rho[src][cls][which][band]["rho"]

    a = h5.get("idp:unrostered_atOrAboveLowestStarter", {})
    b = h5.get("idp:rostered_1000to2999", {})
    return {
        "H1": {
            "idpUnrosteredAtOrAboveLowestStarter": above,
            "ofThoseOnLiveRosters": sum(h1[p]["ofThoseOnLiveRosters"] for p in IDP),
            "ofThoseWithoutNflTeam": sum(h1[p]["ofThoseWithoutNflTeam"] for p in IDP),
            "ofThoseInjuredOrInactiveNow": sum(census[p]["injuredOrInactiveNow"] for p in IDP),
            "healthyWaiverBestVsLowestStarter": {
                p: [healthy.get(p, {}).get("value"), lowest.get(p, {}).get("value")] for p in IDP
            },
        },
        "H2": "lineups are solved on canonical value, so the anomaly is in value space; the "
        "lowest-valued IDP starters are productive veterans (see lowestValuedCanonicalStarter)",
        "H3": {
            "spearmanValueVsPpg_today": {
                "offense": g("today", "offense"),
                "idp": g("today", "idp"),
            },
            "spearmanValueVsPpg_preseasonServed": {
                "offense": g("preseasonServed", "offense"),
                "idp": g("preseasonServed", "idp"),
            },
            "spearmanValueVsPpg_1000to2999_today": {
                "offense": g("today", "offense", band="1000to2999"),
                "idp": g("today", "idp", band="1000to2999"),
            },
        },
        "H4": {
            "aucValue_offense_vs_idp": [
                auc_["offense"]["aucCanonicalValue"],
                auc_["idp"]["aucCanonicalValue"],
            ],  # fmt: skip
            "aucPpg_offense_vs_idp": [
                auc_["offense"]["aucLeagueScoredPpg"],
                auc_["idp"]["aucLeagueScoredPpg"],
            ],  # fmt: skip
            "waiverAndFreeAgentAdds_idp_vs_offense": [
                sum(tx.get("idp_adds", {}).get(k, 0) for k in ("waiver", "free_agent")),
                sum(tx.get("offense_adds", {}).get(k, 0) for k in ("waiver", "free_agent")),
            ],
        },
        "H5": {
            "anomalousIdpMedianRatio_Tminus60": (a.get("Tminus60") or {}).get(
                "medianTodayOverThen"
            ),
            "rosteredIdp1000to2999MedianRatio_Tminus60": (b.get("Tminus60") or {}).get(
                "medianTodayOverThen"
            ),
            "anomalousIdpRosteredAtTminus60": a.get("rosteredTminus60"),
        },
    }


# ── main ────────────────────────────────────────────────────────────────


def main() -> int:  # noqa: C901, PLR0912, PLR0915 — one linear research pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--weeks", type=int, default=6, help="2026 weeks 1..N (default 6)")
    ap.add_argument("--cache-dir", type=Path, default=Path("/tmp/low_value_idp_anomaly_cache"))
    args = ap.parse_args()
    t0 = time.time()

    # ── today's board, exactly as the shadow replay built it ─────────────
    zpath, member, blob, raw = SR.newest_board()
    ctx = SR.build_context(raw)
    contract, rows = ctx["contract"], ctx["rows"]
    anchors = ctx["anchors"]["byPosition"]
    sl = contract.get("sleeper") or {}
    name_to_id = {str(k): str(v) for k, v in (sl.get("playerIds") or {}).items()}
    archive_rostered_ids = rostered_ids(sl)

    # ── Sleeper (public; cached outside the repo) ─────────────────────────
    fetch = LU.Fetcher(args.cache_dir)
    league_id = league_registry.get_sleeper_league_id(LEAGUE)
    league = fetch.get(f"{SLEEPER}/league/{league_id}", max_age_s=86400)
    scoring = league.get("scoring_settings") or {}
    slots, _src = resolve_starter_slots(
        roster_positions=league.get("roster_positions"),
        roster_settings=league_registry.get_league_roster_settings(LEAGUE),
    )
    pdb = fetch.get(f"{SLEEPER}/players/nfl", max_age_s=7 * 86400)
    rosters = fetch.get(f"{SLEEPER}/league/{league_id}/rosters", max_age_s=0)  # fresh
    weeks = list(range(1, args.weeks + 1))
    matchups = {w: fetch.get(f"{SLEEPER}/league/{league_id}/matchups/{w}") for w in weeks}
    stats = {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{w}") for w in weeks}
    txns = {
        w: fetch.get(f"{SLEEPER}/league/{league_id}/transactions/{w}", max_age_s=6 * 3600)
        for w in range(1, args.weeks + 2)
    }
    live_ids = {str(p) for r in rosters for p in (r.get("players") or [])}
    live_taxi = {str(p) for r in rosters for p in (r.get("taxi") or [])}
    live_reserve = {str(p) for r in rosters for p in (r.get("reserve") or [])}
    roster_sizes = sorted(len(r.get("players") or []) for r in rosters)
    roster_cap = len(league.get("roster_positions") or [])

    def spos(sid: str) -> str:
        return LU.pos_group((pdb.get(sid) or {}).get("position"))

    # ── league-scored production, weeks 1..N ─────────────────────────────
    pts: dict[str, dict[int, float]] = defaultdict(dict)
    tackle_pts: dict[str, float] = defaultdict(float)
    #: players with ANY weekly line (``gms_active`` is set for inactive / IR
    #: players too, so it is presence on an NFL roster, not a game played).
    seen: set[str] = set()
    for w in weeks:
        for sid, line in (stats[w] or {}).items():
            sid = str(sid)
            seen.add(sid)
            if float(line.get("gp") or 0) <= 0:  # a game PLAYED
                continue
            row = dict(line)
            row.update({"player_id": sid, "season": SEASON, "week": w})
            res = compute_weekly_points(row, scoring, position=spos(sid), source="sleeper")
            if res is None:
                continue
            pts[sid][w] = float(res.fantasy_points)
            tackle_pts[sid] += sum(float(scoring.get(k) or 0) * float(line.get(k) or 0)
                                   for k in TACKLE_KEYS)  # fmt: skip
    scorer_diffs = []
    for w in weeks:
        for m in matchups[w]:
            for sid, hp in (m.get("players_points") or {}).items():
                if str(sid) in pts and w in pts[str(sid)]:
                    scorer_diffs.append(abs(pts[str(sid)][w] - float(hp)))

    def prod(sid: str) -> dict:
        wk = pts.get(sid) or {}
        g = len(wk)
        tot = sum(wk.values())
        return {
            "games": g,
            "points": round(tot, 1),
            "ppg": round(tot / g, 2) if g else None,
            "tackleShare": round(tackle_pts[sid] / tot, 2) if tot > 0 else None,
        }

    # ppg ranks per position: among everyone (>= MIN_GAMES) and among live free agents
    by_pos_ppg: dict[str, list[tuple[float, str]]] = defaultdict(list)
    for sid, wk in pts.items():
        if len(wk) >= MIN_GAMES:
            by_pos_ppg[spos(sid)].append((sum(wk.values()) / len(wk), sid))
    rank_all, rank_fa = {}, {}
    for pos, lst in by_pos_ppg.items():
        lst.sort(reverse=True)
        for i, (_, sid) in enumerate(lst):
            rank_all[sid] = i + 1
        for i, (_, sid) in enumerate(x for x in lst if x[1] not in live_ids):
            rank_fa[sid] = i + 1

    # ── H5 inputs: served pre-season + today's-code replays over archives ─
    pre_vals, pre_meta = LU.preseason_values()  # sid -> served 2026-08-25 value
    today = datetime.strptime(member.split("_")[2].split(".")[0], "%Y-%m-%d").date()
    replays: dict[int, dict] = {}
    for off in REPLAY_OFFSETS_DAYS:
        day = date.fromordinal(today.toordinal() - off)
        path = archive_for(day)
        if off == 0:
            c2, path = contract, zpath
        else:
            from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

            c2 = build_api_data_contract(read_archive(path))
        replays[off] = {
            "archive": str(path.relative_to(REPO)),
            "values": values_by_sid(c2),
            "rostered": rostered_ids(c2.get("sleeper") or {}),
        }
    today_vals = replays[0]["values"]

    # ── H1: are the "best unrostered" actually available? ────────────────
    h1_counts: dict[str, Any] = {}
    unrostered_rows: dict[str, list[dict]] = defaultdict(list)
    for r in rows.values():
        if r["cls"] == "pick" or r["name"] in ctx["rostered"] or not r["pos"]:
            continue
        unrostered_rows[r["pos"]].append(r)
    for pos in OFFENSE + IDP:
        lst = unrostered_rows.get(pos) or []
        low = ctx["lowest_starter"].get(pos)
        above = [r for r in lst if low is not None and r["value"] >= low]
        sids = [row_sid(r, name_to_id) for r in lst]
        h1_counts[pos] = {
            "unrosteredByName": len(lst),
            "noSleeperIdJoin": sum(1 for s in sids if not s),
            "rosteredByIdInSameSnapshot": sum(1 for s in sids if s and s in archive_rostered_ids),
            "rosteredOnLiveSleeperRosters": sum(1 for s in sids if s and s in live_ids),
            "unrosteredValuedAtOrAboveLowestStarter": len(above),
            "ofThoseOnLiveRosters": sum(
                1 for r in above if (row_sid(r, name_to_id) or "") in live_ids
            ),
            "ofThoseWithoutNflTeam": sum(
                1 for r in above if not (pdb.get(row_sid(r, name_to_id) or "") or {}).get("team")
            ),
        }  # fmt: skip

    name_count = Counter(_norm(p.get("full_name")) for p in pdb.values() if p.get("active"))
    board_name_count = Counter(_norm(r["name"]) for r in rows.values() if r["cls"] != "pick")

    def detail(r: dict) -> dict:
        sid = row_sid(r, name_to_id) or ""
        meta = pdb.get(sid) or {}
        pr = prod(sid)
        return {
            "name": r["name"],
            "boardPos": r["pos"],
            "value": _r(r["value"]),
            "sleeperPos": spos(sid) if sid else None,
            "fantasyPositions": meta.get("fantasy_positions"),
            "nflTeam": meta.get("team"),
            "status": meta.get("status"),
            "injuryStatus": meta.get("injury_status"),
            "yearsExp": meta.get("years_exp"),
            "age": meta.get("age"),
            "sleeperIdJoined": bool(sid),
            "onLiveSleeperRoster": sid in live_ids,
            "onLiveTaxiOrReserve": sid in live_taxi or sid in live_reserve,
            "activeSameNameSleeperPlayers": name_count.get(_norm(r["name"]), 0),
            "sameNameBoardRows": board_name_count.get(_norm(r["name"]), 0),
            **{f"wk1_{args.weeks}{k[0].upper()}{k[1:]}": v for k, v in pr.items()},
            "ppgRankAtPosAll": rank_all.get(sid),
            "ppgRankAtPosAmongFreeAgents": rank_fa.get(sid),
            "valueServedPreseason_2026_08_25": _r(pre_vals.get(sid)),
            **{
                f"valueReplayTminus{off}": _r((replays[off]["values"].get(sid) or {}).get("value"))
                for off in REPLAY_OFFSETS_DAYS
                if off
            },
            **{
                f"rosteredTminus{off}": sid in replays[off]["rostered"]
                for off in REPLAY_OFFSETS_DAYS
                if off
            },
        }

    top_unrostered = {
        pos: [detail(r) for r in sorted(unrostered_rows[pos], key=lambda r: -r["value"])[:TOP_N]]
        for pos in IDP
    }

    # Re-derive the waiver best per position after removing every H1 defect
    # (live roster by Sleeper id, no NFL team, inactive).
    clean_best: dict[str, dict] = {}
    for pos in OFFENSE + IDP:
        for r in sorted(unrostered_rows.get(pos) or [], key=lambda r: -r["value"]):
            sid = row_sid(r, name_to_id) or ""
            meta = pdb.get(sid) or {}
            if sid in live_ids or not meta.get("team") or meta.get("active") is False:
                continue
            clean_best[pos] = {"name": r["name"], "value": _r(r["value"])}
            break
    # ... and additionally healthy today (Sleeper injury/status), i.e. a player a
    # manager could actually start this week.
    healthy_best: dict[str, dict] = {}
    for pos in OFFENSE + IDP:
        for r in sorted(unrostered_rows.get(pos) or [], key=lambda r: -r["value"]):
            sid = row_sid(r, name_to_id) or ""
            if sid in live_ids or not is_healthy(pdb.get(sid) or {}):
                continue
            healthy_best[pos] = {"name": r["name"], "value": _r(r["value"])}
            break

    # Census of the anomalous end: unrostered and valued >= the lowest starter.
    census = {}
    for pos in OFFENSE + IDP:
        low = ctx["lowest_starter"].get(pos)
        above = [r for r in unrostered_rows.get(pos) or [] if low is not None and r["value"] >= low]
        sids = [row_sid(r, name_to_id) or "" for r in above]
        census[pos] = {
            "n": len(above),
            "injuredOrInactiveNow": sum(1 for s in sids if not is_healthy(pdb.get(s) or {})),
            "rookies": sum(1 for s in sids if (pdb.get(s) or {}).get("years_exp") == 0),
            "rosteredInArchiveTminus14": sum(1 for s in sids if s in replays[14]["rostered"]),
            "rosteredInArchiveTminus30": sum(1 for s in sids if s in replays[30]["rostered"]),
            "rosteredInArchiveTminus60": sum(1 for s in sids if s in replays[60]["rostered"]),
            "fewerThanMinGamesPlayed": sum(1 for s in sids if len(pts.get(s) or {}) < MIN_GAMES),
            "medianPpgWhenPlayed": _r(_median([prod(s)["ppg"] for s in sids]), 2),
        }  # fmt: skip
    # The one name-join miss class: rostered by Sleeper id, absent from the
    # name list the shadow replay used (names only — no ids).
    name_join_misses = [
        {"boardName": r["name"], "pos": r["pos"], "value": _r(r["value"]),
         "sleeperFullName": (pdb.get(row_sid(r, name_to_id) or "") or {}).get("full_name")}
        for pos in OFFENSE + IDP for r in unrostered_rows.get(pos) or []
        if (row_sid(r, name_to_id) or "") in archive_rostered_ids
    ]  # fmt: skip

    # ── H2: the lineup objective, and the lowest starters themselves ─────
    starter_rows = [rows[n] for n in ctx["starters"] if n in rows]
    lowest = {}
    for pos in OFFENSE + IDP:
        cand = sorted((r for r in starter_rows if r["pos"] == pos), key=lambda r: r["value"])
        if not cand:
            continue
        lo = cand[0]
        sid = row_sid(lo, name_to_id) or ""
        best = clean_best.get(pos, {}).get("value") or 0
        teams_below = 0
        for t in ctx["teams"]:
            ol = t.get("optimalLineup") or {}
            vals = [rows[n]["value"] for n in (ol.get("starters") or [])
                    if n in rows and rows[n]["pos"] == pos]  # fmt: skip
            teams_below += any(v < best for v in vals)
        lowest[pos] = {
            "name": lo["name"],
            "value": _r(lo["value"]),
            **{f"wk1_{args.weeks}{k[0].upper()}{k[1:]}": v for k, v in prod(sid).items()},
            "ppgRankAtPosAll": rank_all.get(sid),
            "startersAtPosValuedBelowCleanWaiverBest": sum(
                1 for r in cand if r["value"] < best
            ),
            "teamsStartingAtLeastOneBelowCleanWaiverBest": teams_below,
            "startersAtPos": len(cand),
            "startersAtPosValuedBelowHealthyWaiverBest": sum(
                1 for r in cand if r["value"] < (healthy_best.get(pos, {}).get("value") or 0)
            ),
        }  # fmt: skip

    # Lineups re-solved on PRODUCTION (season-to-date points, live rosters):
    # which canonical values do production-optimal lineups start?
    from src.ros.lineup import OBJECTIVE_REALIZED_POINTS, solve_optimal_assignment  # noqa: PLC0415

    prod_start_vals: dict[str, list[float]] = defaultdict(list)
    overlap = Counter()
    canon_starter_ids = {name_to_id.get(n) for n in ctx["starters"]}
    for r in rosters:
        pool = []
        for sid in (str(p) for p in (r.get("players") or [])):
            meta = pdb.get(sid) or {}
            fps = tuple(str(p).upper() for p in (meta.get("fantasy_positions") or ()) if p)
            pool.append(RosterPlayer(player_id=sid, canonical_name=sid,
                                     position=str(meta.get("position") or "").upper(),
                                     ros_value=float(sum((pts.get(sid) or {}).values())),
                                     fantasy_positions=fps))  # fmt: skip
        assign = solve_optimal_assignment(pool, slots, objective=OBJECTIVE_REALIZED_POINTS)
        for p in assign.values():
            pos = spos(p.player_id)
            v = (today_vals.get(p.player_id) or {}).get("value")
            if pos in IDP + OFFENSE:
                overlap[(pos, "prodStarters")] += 1
                overlap[(pos, "alsoCanonicalStarter")] += p.player_id in canon_starter_ids
                if v is not None:
                    prod_start_vals[pos].append(v)
                else:
                    overlap[(pos, "unvalued")] += 1
    h2_prod = {
        pos: {
            "productionOptimalStarters": overlap[(pos, "prodStarters")],
            "shareAlsoInCanonicalValueLineup": _r(
                overlap[(pos, "alsoCanonicalStarter")] / max(1, overlap[(pos, "prodStarters")]), 3
            ),
            "unvaluedProductionStarters": overlap[(pos, "unvalued")],
            "lowestValuedProductionStarter": _r(min(prod_start_vals[pos]))
            if prod_start_vals[pos]
            else None,
            "medianValueOfProductionStarters": _r(_median(prod_start_vals[pos])),
        }
        for pos in OFFENSE + IDP
    }

    # ── H3: does canonical value predict THIS league's production? ───────
    def pop(cls_positions, which, value_src, band=None, metric="ppg"):
        """``ppg``: points per game PLAYED, players with >= MIN_GAMES (rate when
        healthy).  ``perTeamWeek``: total points / N weeks over every player with
        a weekly line (availability included — what a best-ball roster gets)."""
        xs, ys = [], []
        for sid in pts.keys() if metric == "ppg" else seen:
            wk = pts.get(sid) or {}
            pos = spos(sid)
            if pos not in cls_positions or (metric == "ppg" and len(wk) < MIN_GAMES):
                continue
            if which == "rostered" and sid not in live_ids:
                continue
            if which == "unrostered" and sid in live_ids:
                continue
            v = (
                (today_vals.get(sid) or {}).get("value")
                if value_src == "today"
                else pre_vals.get(sid)
            )
            if v is None or (band and not band[0] <= v < band[1]):
                continue
            xs.append(v)
            ys.append(sum(wk.values()) / (len(wk) if metric == "ppg" else len(weeks)))
        return xs, ys

    h3: dict[str, Any] = {}
    for metric in ("ppg", "perTeamWeek"):
        for vsrc in ("today", "preseasonServed"):
            for label, group in (("offense", OFFENSE), ("idp", IDP),
                                 *((p, (p,)) for p in OFFENSE + IDP)):  # fmt: skip
                for which in ("all", "rostered", "unrostered"):
                    for bname, band in (("allValues", None), ("1000to2999", (1000, 3000))):
                        xs, ys = pop(group, which, "today" if vsrc == "today" else "pre", band,
                                     metric)  # fmt: skip
                        h3.setdefault(metric, {}).setdefault(vsrc, {}).setdefault(
                            label, {}
                        ).setdefault(which, {})[bname] = spearman(xs, ys)
    # tackle-vs-big-play profile of the anomaly's two ends
    tackle_profile = {}
    for pos in IDP:
        fa_ts = [d.get(f"wk1_{args.weeks}TackleShare") for d in top_unrostered[pos]]
        st = [rows[n] for n in ctx["starters"] if n in rows and rows[n]["pos"] == pos]
        st_ts = [prod(name_to_id.get(r["name"]) or "")["tackleShare"] for r in st]
        tackle_profile[pos] = {
            "medianTackleShareTop10UnrosteredByValue": _r(_median(fa_ts), 2),
            "medianTackleShareCanonicalStarters": _r(_median(st_ts), 2),
        }

    # ── H4: what do managers roster on? ──────────────────────────────────
    h4_auc = {}
    for label, group in (("offense", OFFENSE), ("idp", IDP), *((p, (p,)) for p in IDP)):
        vin, vout, pin, pout = [], [], [], []
        for sid, wk in pts.items():
            if spos(sid) not in group or len(wk) < MIN_GAMES:
                continue
            v = (today_vals.get(sid) or {}).get("value")
            if v is None:
                continue
            ppg = sum(wk.values()) / len(wk)
            (vin if sid in live_ids else vout).append(v)
            (pin if sid in live_ids else pout).append(ppg)
        h4_auc[label] = {
            "rostered": len(vin),
            "unrostered": len(vout),
            "aucCanonicalValue": auc(vin, vout),
            "aucLeagueScoredPpg": auc(pin, pout),
        }
    top_vs_lowest = {}
    for pos in IDP:
        lo_ppg = lowest[pos].get(f"wk1_{args.weeks}Ppg") if pos in lowest else None
        ppgs = [d.get(f"wk1_{args.weeks}Ppg") for d in top_unrostered[pos]]
        top_vs_lowest[pos] = {
            "lowestValuedStarterPpg": lo_ppg,
            "top10UnrosteredMedianPpg": _r(_median(ppgs), 2),
            "top10UnrosteredOutscoringLowestStarter": sum(
                1 for p in ppgs if p is not None and lo_ppg is not None and p > lo_ppg
            ),
            "top10UnrosteredWithFewerThanMinGames": sum(
                1 for d in top_unrostered[pos] if (d.get(f"wk1_{args.weeks}Games") or 0) < MIN_GAMES
            ),
        }  # fmt: skip
    tx_counts: Counter = Counter()
    for w, lst in txns.items():
        for t in lst or []:
            if t.get("status") != "complete":
                continue
            kind = t.get("type")
            for sid in (t.get("adds") or {}).keys():
                tx_counts[(f"{'idp' if spos(str(sid)) in IDP else 'offense'}", "adds", kind)] += 1
            for sid in (t.get("drops") or {}).keys():
                tx_counts[(f"{'idp' if spos(str(sid)) in IDP else 'offense'}", "drops", kind)] += 1
    tx_out: dict = defaultdict(dict)
    for (cls, act, kind), n in sorted(tx_counts.items()):
        tx_out[f"{cls}_{act}"][str(kind)] = n

    # ── H5: board movement of the anomaly's high end ─────────────────────
    def ratio_stats(sids: list[str], off: int) -> dict:
        rs = []
        for s in sids:
            a = (replays[off]["values"].get(s) or {}).get("value")
            b = (today_vals.get(s) or {}).get("value")
            if a and b:
                rs.append(b / a)
        return {"n": len(rs), "medianTodayOverThen": _r(_median(rs), 3)}

    def served_ratio(sids: list[str]) -> dict:
        rs = [
            (today_vals.get(s) or {}).get("value") / pre_vals[s]
            for s in sids
            if pre_vals.get(s) and (today_vals.get(s) or {}).get("value")
        ]
        return {"n": len(rs), "medianTodayReplayOverServedPreseason": _r(_median(rs), 3)}

    groups: dict[str, list[str]] = defaultdict(list)
    for sid, info in today_vals.items():
        pos = info["pos"]
        if pos not in OFFENSE + IDP:
            continue
        cls = "idp" if pos in IDP else "offense"
        low = ctx["lowest_starter"].get(pos)
        if sid in live_ids:
            if 1000 <= info["value"] < 3000:
                groups[f"{cls}:rostered_1000to2999"].append(sid)
        elif low is not None and info["value"] >= low:
            groups[f"{cls}:unrostered_atOrAboveLowestStarter"].append(sid)
    h5 = {
        g: {
            **{f"Tminus{off}": ratio_stats(s, off) for off in REPLAY_OFFSETS_DAYS if off},
            "servedPreseason": served_ratio(s),
            "rosteredTminus60": sum(1 for x in s if x in replays[60]["rostered"]),
        }
        for g, s in sorted(groups.items())
    }

    result = {
        "purpose": "RESEARCH ONLY, EXPLORATORY: why is the best unrostered IDP valued above "
        "the lowest rostered IDP starter in dynasty_main?  No production code, value or "
        "config changed.",
        "generatedBy": "scripts/low_value_asset_idp_anomaly.py",
        "board": {
            "archive": str(zpath.relative_to(REPO)),
            "member": member,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "methodology": "today's code via shadow_replay.build_context (reproduces "
            "S1_replacementAnchors)",
        },
        "reproducedAnomaly": {
            pos: {
                "waiverBestUnrostered": anchors[pos]["waiverBestUnrostered_PRIMARY"],
                "lowestStarterAcross12OptimalLineups": anchors[pos][
                    "lowestStarterAcross12OptimalLineups"
                ],
            }
            for pos in OFFENSE + IDP
        },
        "inputs": {
            "weeks": weeks,
            "minGamesForPpg": MIN_GAMES,
            "scorerVsHostPlayersPoints": {
                "playerWeeks": len(scorer_diffs),
                "exactWithin0.01": sum(1 for d in scorer_diffs if d < 0.01),
                "maxAbsDiff": _r(max(scorer_diffs), 3) if scorer_diffs else None,
            },
            "rosterSizes": roster_sizes,
            "rosterCap": roster_cap,
            "liveTaxiPlayers": len(live_taxi),
            "liveReservePlayers": len(live_reserve),
            "idpScoringCard": {
                k: round(float(v), 3)
                for k, v in sorted(scoring.items())
                if k.startswith("idp_") and float(v or 0)
            },
            "idpStarterSlotsPerTeam": {p: slots.count(p) for p in IDP},
            "servedPreseasonBoard": pre_meta["artifact"],
            "replayArchives": {f"Tminus{o}": replays[o]["archive"] for o in REPLAY_OFFSETS_DAYS},
            "temporalLedger": "data/temporal_ledger.sqlite is NOT present in this checkout; "
            "served history between 2026-08-25 and today is unavailable locally",
        },
        "H1_dataDefect": {
            "test": "every board player row the shadow replay counts as unrostered (name not in "
            "sleeper.teams[].players) checked by Sleeper id against the SAME snapshot's "
            "playerIds and against LIVE Sleeper rosters (players incl. taxi/reserve), plus "
            "Sleeper directory status",
            "countsByPosition": h1_counts,
            "cleanWaiverBestByPosition": clean_best,
            "healthyWaiverBestByPosition": healthy_best,
            "nameJoinMisses": name_join_misses,
            "censusUnrosteredAtOrAboveLowestStarter": census,
            "top10UnrosteredByValue": top_unrostered,
        },
        "H2_lineupDefinition": {
            "objective": "canonical rankDerivedValue — data_contract.contract_roster_pools "
            "feeds RosterPlayer.ros_value = rankDerivedValue to lineup.assign_lineup "
            "(stamp_optimal_lineups); NOT projections and NOT realized points",
            "lowestValuedCanonicalStarter": lowest,
            "lineupsResolvedOnSeasonToDatePoints": h2_prod,
        },
        "H3_scoringMismatch": {
            "test": "Spearman rank correlation between canonical value and weeks-1..N (ppg: per game played, >= minGames; perTeamWeek: total / N weeks, every player with a weekly line) "
            "league-scored points per game (players with >= minGames), today's board "
            "(hindsight-contaminated: it already knows the season) and the SERVED 2026-08-25 "
            "pre-season board",
            "spearman": h3,
            "tackleProfile": tackle_profile,
        },
        "H4_managerBehaviour": {
            "aucRosteredVsUnrostered": h4_auc,
            "top10UnrosteredVsLowestStarter": top_vs_lowest,
            "transactionsWeeks1toNplus1": dict(tx_out),
        },
        "H5_boardMovement": {
            "test": "median today/then value ratio, both values from TODAY's code (sensitivity "
            "replay: inputs move, methodology fixed), and today's replay over the SERVED "
            "pre-season value (mixes input moves AND pipeline changes)",
            "groups": h5,
        },
        "readout": _readout(h1_counts, census, healthy_best, lowest, h3, h4_auc, h5, tx_out),
        "timingsSec": round(time.time() - t0, 1),
    }
    SR.P2.assert_aggregate_only({k: v for k, v in result.items() if k != "board"})
    SR.P2.assert_aggregate_only({k: v for k, v in result["board"].items() if k != "sha256"})
    out = REPO / args.out
    out.write_text(json.dumps(result, indent=1, default=str) + "\n")
    print(json.dumps({"out": str(out), "timingsSec": result["timingsSec"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
