#!/usr/bin/env python3
"""Low-value asset research — LINEUP UTILITY and REPLACEMENT lane.

Owner research program 2026-10-20.  RESEARCH ONLY: this script reads the
canonical owners and public Sleeper data, writes ONE aggregate evidence
file, and changes no production value, model, config or route.

Question: how much do low-value assets (canonical ``rankDerivedValue`` below
roughly 3,000) actually contribute to a ``dynasty_main`` best-ball lineup,
and which of them are usable roster depth versus expendable filler?

Inputs
------
* **Pre-season value** — the genuine served board captured before deploy on
  2026-08-25 (``data/ops/v1-27/pre-deploy-golden-board-LIVE-2026-08-25.json``,
  the manifest's PRIMARY artifact).  It is keyed by display name, so names
  join to Sleeper ids through the same day's tracked export archive
  (``players[name]._sleeperId`` then ``sleeper.playerIds``).  A player the
  board did not price is ``unvalued`` — a separate band, never 0.
* **Today's value** — a board built NOW, under TODAY's methodology, from the
  newest tracked export archive via ``build_api_data_contract`` (labelled).
* **Weekly outcomes** — Sleeper's public ``/matchups/{week}`` for 2026 weeks
  1..N (per roster: ``players``, ``starters``, ``players_points``).  In a
  best-ball league ``starters`` is the host's own after-the-fact optimal 21.
* **Free agents** — Sleeper's public weekly stat dump, scored under the
  league's own scoring card by the canonical scorer
  (``src.nfl_data.realized_points.compute_weekly_points(source="sleeper")``),
  validated here against the host's ``players_points`` for rostered players.

Method
------
* Lineup re-solves use THE canonical solver
  (``src.ros.lineup.solve_optimal_assignment`` with the
  ``realized_points`` objective) against the host's ``roster_positions``.
  It is checked against the host's own awarded starters first.
* Marginal lineup contribution of a rostered player-week = optimal score
  with him minus optimal score without him (the best bench alternative fills
  in).  A non-starter's marginal is exactly 0 by construction.
* Marginal vs FREE replacement = the same, but with a free agent added to the
  pool when he is removed (hindsight-selected: the best/3rd-best unrostered
  player at the position by weeks-1..N total).  This is the "is he worth more
  than what the wire hands you" measure.
* Replacement machinery is CONSUMED, not rebuilt:
  ``src.league_intel.replacement.compute_replacement_levels``,
  ``src.draft.context.build_roster_context`` (waiver values + cut ladder via
  ``src.draft.displacement``), ``src.trade.faab_engine.resolve_anchors``.

Privacy: the output carries NO Sleeper league / user / roster id and no team
name; teams are anonymous.  Network responses are cached outside the repo
(``--cache-dir``, default under /tmp).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
import time
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402

from src.api import league_registry  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.ros.lineup import (  # noqa: E402
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    lineup_position,
    resolve_starter_slots,
    solve_optimal_assignment,
)

LEAGUE_KEY = "dynasty_main"
SEASON = 2026
SLEEPER = "https://api.sleeper.app/v1"
GOLDEN_LIVE = REPO_ROOT / "data/ops/v1-27/pre-deploy-golden-board-LIVE-2026-08-25.json"
GOLDEN_MANIFEST = REPO_ROOT / "data/ops/v1-27/pre-deploy-manifest-2026-08-25.json"
ARCHIVE_DIR = REPO_ROOT / "exports/archive"
PRESEASON_ARCHIVE = "dynasty_export_20260825_230528.zip"
DEFAULT_OUT = REPO_ROOT / "docs/valuation/evidence/low_value_assets_2026-10-20/lineup_utility.json"

#: Value bands requested by the owner.  ``unvalued`` is separate: a player
#: the board did not price is UNKNOWN, never a value of 0.
BANDS: tuple[tuple[str, float, float], ...] = (
    ("<500", 0, 500),
    ("500-1000", 500, 1000),
    ("1000-1500", 1000, 1500),
    ("1500-2000", 1500, 2000),
    ("2000-3000", 2000, 3000),
    ("3000-4500", 3000, 4500),
    ("4500+", 4500, float("inf")),
)
UNVALUED = "unvalued"
BAND_ORDER = [b[0] for b in BANDS] + [UNVALUED]
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DL", "LB", "DB")
OFFENSE = ("QB", "RB", "WR", "TE")
IDP = ("DL", "LB", "DB")
#: Cells below either floor are flagged ``smallSample``.
MIN_PLAYER_WEEKS = 30
MIN_PLAYERS = 8


def band_of(value: float | None) -> str:
    if value is None:
        return UNVALUED
    for name, lo, hi in BANDS:
        if lo <= value < hi:
            return name
    return UNVALUED


#: Sleeper spellings outside the lineup vocabulary that this report folds.
_REPORT_POSITION_FOLD = {"FB": "RB"}


def pos_group(position: str | None) -> str:
    p = lineup_position(str(position or ""))
    p = _REPORT_POSITION_FOLD.get(p, p)
    return p if p in POSITIONS else (p or "UNKNOWN")


def class_of(pos: str) -> str:
    if pos in OFFENSE:
        return "offense"
    if pos in IDP:
        return "idp"
    if pos == "K":
        return "kicker"
    return "other"


# ── network (cached outside the repo) ─────────────────────────────────


class Fetcher:
    def __init__(self, cache_dir: Path, *, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self.session = requests.Session()
        self.calls = 0

    def get(self, url: str, *, max_age_s: float | None = None) -> Any:
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        path = self.cache_dir / f"{key}.json"
        if path.exists() and (max_age_s is None or time.time() - path.stat().st_mtime < max_age_s):
            return json.loads(path.read_text())
        if self.offline:
            raise RuntimeError(f"offline and not cached: {url.split('/v1/')[-1][:40]}")
        resp = self.session.get(url, timeout=60)
        resp.raise_for_status()
        self.calls += 1
        data = resp.json()
        path.write_text(json.dumps(data))
        return data


# ── values ────────────────────────────────────────────────────────────


def _read_zip_json(zip_path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        name = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        return json.loads(zf.read(name))


def preseason_values() -> tuple[dict[str, float | None], dict[str, Any]]:
    """Sleeper id → 2026-08-25 served ``rankDerivedValue`` (None = unpriced row)."""
    board = json.loads(GOLDEN_LIVE.read_text())
    manifest = json.loads(GOLDEN_MANIFEST.read_text())
    raw = _read_zip_json(ARCHIVE_DIR / PRESEASON_ARCHIVE)
    name_to_id: dict[str, str] = {}
    for name, row in (raw.get("players") or {}).items():
        sid = row.get("_sleeperId") if isinstance(row, dict) else None
        if sid:
            name_to_id[name] = str(sid)
    for name, sid in ((raw.get("sleeper") or {}).get("playerIds") or {}).items():
        name_to_id.setdefault(name, str(sid))
    out: dict[str, float | None] = {}
    joined = unjoined = 0
    for name, row in board["rows"].items():
        if str(row.get("assetClass") or "") == "pick":
            continue
        sid = name_to_id.get(name)
        if not sid:
            unjoined += 1
            continue
        joined += 1
        v = row.get("rankDerivedValue")
        out[sid] = float(v) if isinstance(v, (int, float)) and v > 0 else None
    priced = sorted(
        float(r["rankDerivedValue"])
        for r in board["rows"].values()
        if str(r.get("assetClass") or "") != "pick"
        and isinstance(r.get("rankDerivedValue"), (int, float))
        and r["rankDerivedValue"] > 0
    )
    meta = {
        "pricedPlayerRows": len(priced),
        "lowestPricedPlayerValue": priced[0] if priced else None,
        "floorNote": "the 2026-08-25 board priced no player below this value, so the "
        "<500 and 500-1000 pre-season bands are EMPTY by construction (players past the "
        "rank cap were unpriced then -> 'unvalued'); today's board prices off-cap players",
        "artifact": str(GOLDEN_LIVE.relative_to(REPO_ROOT)),
        "basis": manifest["primaryArtifact"]["basis"],
        "boardSha256": manifest["primaryArtifact"]["boardSha256"],
        "capturedAt": manifest["capturedAt"],
        "nameToSleeperIdJoin": {
            "via": f"exports/archive/{PRESEASON_ARCHIVE}",
            "playerRowsJoined": joined,
            "playerRowsUnjoined": unjoined,
        },
    }
    return out, meta


def build_today_contract() -> tuple[dict[str, Any], dict[str, Any]]:
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    newest = sorted(ARCHIVE_DIR.glob("dynasty_export_*.zip"))[-1]
    raw = _read_zip_json(newest)
    contract = build_api_data_contract(raw)
    meta = {
        "archive": f"exports/archive/{newest.name}",
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "methodology": "TODAY's code at this commit (build_api_data_contract), "
        "not the methodology that served on the archive date",
    }
    return contract, meta


def today_values(contract: Mapping[str, Any]) -> dict[str, float | None]:
    sl = contract.get("sleeper") or {}
    name_to_id = {str(k): str(v) for k, v in (sl.get("playerIds") or {}).items()}
    out: dict[str, float | None] = {}
    for row in contract.get("playersArray") or []:
        if str(row.get("assetClass") or "") == "pick":
            continue
        sid = row.get("playerId")
        if not sid:
            for f in ("displayName", "canonicalName", "legacyRef"):
                sid = name_to_id.get(str(row.get(f) or ""))
                if sid:
                    break
        if not sid:
            continue
        v = row.get("rankDerivedValue")
        out[str(sid)] = float(v) if isinstance(v, (int, float)) and v > 0 else None
    return out


# ── lineup ────────────────────────────────────────────────────────────


def make_player(pid: str, pts: float, pdb: Mapping[str, Any]) -> RosterPlayer:
    meta = pdb.get(pid) or {}
    fps = tuple(str(p).upper() for p in (meta.get("fantasy_positions") or ()) if p)
    return RosterPlayer(
        player_id=pid,
        canonical_name=str(meta.get("full_name") or pid),
        position=str(meta.get("position") or (fps[0] if fps else "")).upper(),
        ros_value=float(pts),
        fantasy_positions=fps,
    )


def solve(pool: list[RosterPlayer], slots: list[str]) -> tuple[float, set[str]]:
    assignment = solve_optimal_assignment(pool, slots, objective=OBJECTIVE_REALIZED_POINTS)
    return (
        float(sum(p.ros_value or 0.0 for p in assignment.values())),
        {p.player_id for p in assignment.values()},
    )


# ── aggregation helpers ───────────────────────────────────────────────


def _r(x: float | None, nd: int = 2) -> float | None:
    return None if x is None else round(float(x), nd)


def summarize(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0, "mean": None, "median": None, "p75": None, "p90": None}
    s = sorted(values)
    q = statistics.quantiles(s, n=20, method="inclusive") if len(s) > 1 else [s[0]] * 19
    return {
        "n": len(s),
        "mean": _r(statistics.fmean(s)),
        "median": _r(statistics.median(s)),
        "p75": _r(q[14]),
        "p90": _r(q[17]),
    }


def cell_stats(rows: list[dict[str, Any]], total_start_pts: float) -> dict[str, Any]:
    n = len(rows)
    players = {r["pid"] for r in rows}
    started = [r for r in rows if r["started"]]
    marg = [r["marginal"] for r in rows]
    marg_started = [r["marginal"] for r in started]
    fa1 = [r["marginalVsFa1"] for r in rows if r["marginalVsFa1"] is not None]
    fa3 = [r["marginalVsFa3"] for r in rows if r["marginalVsFa3"] is not None]
    start_pts = sum(r["points"] for r in started)
    out = {
        "playerWeeks": n,
        "distinctPlayers": len(players),
        "startRate": _r(len(started) / n, 4) if n else None,
        "meanPointsPerWeek": _r(statistics.fmean(r["points"] for r in rows)) if n else None,
        "meanPointsWhenStarted": _r(statistics.fmean(r["points"] for r in started))
        if started
        else None,
        "shareOfLeagueStartingPoints": _r(start_pts / total_start_pts, 4)
        if total_start_pts
        else None,
        "marginalPointsPerRosteredWeek": summarize(marg),
        "marginalPointsPerStartedWeek": summarize(marg_started),
        "shareOfWeeksWithPositiveMarginal": _r(sum(1 for m in marg if m > 1e-9) / n, 4)
        if n
        else None,
        "marginalVsBestFreeAgentPerRosteredWeek": summarize(fa1),
        "marginalVs3rdBestFreeAgentPerRosteredWeek": summarize(fa3),
        "smallSample": n < MIN_PLAYER_WEEKS or len(players) < MIN_PLAYERS,
    }
    return out


# ── main ──────────────────────────────────────────────────────────────


def main(argv: Iterable[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--weeks", type=int, default=6, help="2026 weeks 1..N (default 6)")
    ap.add_argument("--cache-dir", type=Path, default=Path("/tmp/low_value_lineup_utility_cache"))
    ap.add_argument("--offline", action="store_true", help="use cached responses only")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(list(argv) if argv is not None else None)

    t0 = time.time()
    fetch = Fetcher(args.cache_dir, offline=args.offline)
    league_id = league_registry.get_sleeper_league_id(LEAGUE_KEY)
    if not league_id:
        print("dynasty_main has no Sleeper league id in the registry", file=sys.stderr)
        return 2
    league = fetch.get(f"{SLEEPER}/league/{league_id}", max_age_s=86400)
    if str(league.get("season")) != str(SEASON):
        print(f"registry league is season {league.get('season')}, expected {SEASON}")
        return 2
    scoring = league.get("scoring_settings") or {}
    slots, slot_source = resolve_starter_slots(
        roster_positions=league.get("roster_positions"),
        roster_settings=league_registry.get_league_roster_settings(LEAGUE_KEY),
    )
    if not slots:
        print("no starter slots resolved", file=sys.stderr)
        return 2
    weeks = list(range(1, args.weeks + 1))
    pdb = fetch.get(f"{SLEEPER}/players/nfl", max_age_s=7 * 86400)
    rosters_now = fetch.get(f"{SLEEPER}/league/{league_id}/rosters", max_age_s=6 * 3600)
    matchups = {w: fetch.get(f"{SLEEPER}/league/{league_id}/matchups/{w}") for w in weeks}
    stats = {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{w}") for w in weeks}

    pre_vals, pre_meta = preseason_values()
    contract, today_meta = build_today_contract()
    contract_league_ok = str((contract.get("sleeper") or {}).get("leagueId") or "") == str(
        league_id
    )
    now_vals = today_values(contract)

    # Anonymous team labels — no roster/user id or team name reaches the output.
    roster_ids = sorted({int(m["roster_id"]) for w in weeks for m in matchups[w]})
    team_label = {rid: f"team_{i + 1:02d}" for i, rid in enumerate(roster_ids)}

    # ── 1. host-vs-canonical validation + per player-week rows ──────────
    scorer_checks: list[float] = []
    solver_week_matches = solver_week_total = 0
    solver_score_diffs: list[float] = []
    starter_set_matches = 0
    rows: list[dict[str, Any]] = []
    rostered_by_week: dict[int, set[str]] = {}
    total_start_pts = 0.0

    # Free-agent weekly points, scored by the canonical scorer.
    def fa_points(w: int, pid: str) -> float | None:
        line = (stats[w] or {}).get(pid)
        if not line:
            return None
        meta = pdb.get(pid) or {}
        row = dict(line)
        row.update({"player_id": pid, "season": SEASON, "week": w})
        res = compute_weekly_points(
            row, scoring, position=str(meta.get("position") or ""), source="sleeper"
        )
        return None if res is None else float(res.fantasy_points)

    for w in weeks:
        rostered_by_week[w] = set()
        for m in matchups[w]:
            for pid in m.get("players") or []:
                rostered_by_week[w].add(str(pid))
                hp = (m.get("players_points") or {}).get(pid)
                if hp is None:
                    continue
                cp = fa_points(w, str(pid))
                scorer_checks.append(abs((cp or 0.0) - float(hp)))

    # Free-agent pool per position: players on NO roster at the current
    # snapshot.  Their weekly points count every week (what he would have
    # given a team that held him); ranked by weeks-1..N total — HINDSIGHT.
    rostered_now = {str(p) for r in rosters_now for p in (r.get("players") or [])}
    fa_totals: dict[str, dict[str, float]] = defaultdict(dict)
    fa_weekly: dict[str, dict[int, float]] = defaultdict(dict)
    for w in weeks:
        for pid in stats[w] or {}:
            pid = str(pid)
            if pid in rostered_now:
                continue
            meta = pdb.get(pid) or {}
            pos = pos_group(meta.get("position"))
            if pos not in POSITIONS:
                continue
            pts = fa_points(w, pid)
            if pts is None:
                continue
            fa_weekly[pid][w] = pts
            fa_totals[pos][pid] = fa_totals[pos].get(pid, 0.0) + pts
    fa_ranked = {
        pos: sorted(d.items(), key=lambda kv: (-kv[1], kv[0])) for pos, d in fa_totals.items()
    }

    def fa_player(pos: str, rank: int, w: int) -> RosterPlayer | None:
        ranked = fa_ranked.get(pos) or []
        if len(ranked) < rank:
            return None
        pid = ranked[rank - 1][0]
        return make_player("FA:" + pid, fa_weekly[pid].get(w, 0.0), {"FA:" + pid: pdb.get(pid)})

    for w in weeks:
        for m in matchups[w]:
            pids = [str(p) for p in (m.get("players") or [])]
            pp = m.get("players_points") or {}
            pool = [make_player(pid, float(pp.get(pid) or 0.0), pdb) for pid in pids]
            base, starters = solve(pool, slots)
            host_starters = {str(p) for p in (m.get("starters") or []) if p and str(p) != "0"}
            host_score = sum(float(pp.get(p) or 0.0) for p in host_starters)
            solver_week_total += 1
            solver_score_diffs.append(abs(base - host_score))
            if abs(base - host_score) < 0.011:
                solver_week_matches += 1
            if starters == host_starters:
                starter_set_matches += 1
            total_start_pts += host_score
            by_id = {p.player_id: p for p in pool}
            for pid in pids:
                p = by_id[pid]
                started = pid in host_starters
                # Bench player: removing him cannot lower the optimum, so his
                # marginal is exactly 0 — but swapping his roster SPOT for a
                # free agent can raise it, so the vs-FA measure runs for all.
                rest = [q for q in pool if q.player_id != pid]
                marginal = base - solve(rest, slots)[0] if pid in starters else 0.0
                pos = pos_group(p.position)
                f1 = fa_player(pos, 1, w)
                f3 = fa_player(pos, 3, w)
                mfa1 = base - solve(rest + [f1], slots)[0] if f1 else None
                mfa3 = base - solve(rest + [f3], slots)[0] if f3 else None
                rows.append(
                    {
                        "week": w,
                        "team": team_label[int(m["roster_id"])],
                        "pid": pid,
                        "pos": pos_group(p.position),
                        "points": float(p.ros_value or 0.0),
                        "started": started,
                        "marginal": marginal,
                        "marginalVsFa1": mfa1,
                        "marginalVsFa3": mfa3,
                        "preValue": pre_vals.get(pid),
                        "preBand": band_of(pre_vals.get(pid)),
                        "nowValue": now_vals.get(pid),
                        "nowBand": band_of(now_vals.get(pid)),
                    }
                )

    # ── 2. band x position tables ────────────────────────────────────
    def table(band_key: str) -> dict[str, Any]:
        grid: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
        for r in rows:
            grid[r[band_key]][r["pos"]].append(r)
            grid[r[band_key]]["ALL"].append(r)
            grid[r[band_key]][class_of(r["pos"])].append(r)
        out: dict[str, Any] = {}
        for band in BAND_ORDER:
            if band not in grid:
                continue
            out[band] = {
                k: cell_stats(v, total_start_pts)
                for k, v in sorted(grid[band].items())
                if v and k in (*POSITIONS, "ALL", "offense", "idp", "kicker")
            }
        return out

    by_band_pre = table("preBand")
    by_band_now = table("nowBand")

    # ── 3. per-player aggregates (usable depth vs filler) ──────────────
    per_player: dict[str, dict[str, Any]] = {}
    for r in rows:
        a = per_player.setdefault(
            r["pid"],
            {
                "name": (pdb.get(r["pid"]) or {}).get("full_name") or r["pid"],
                "pos": r["pos"],
                "preValue": r["preValue"],
                "preBand": r["preBand"],
                "nowValue": r["nowValue"],
                "weeksRostered": 0,
                "starts": 0,
                "points": 0.0,
                "marginal": 0.0,
                "marginalVsFa1": 0.0,
                "marginalVsFa3": 0.0,
            },
        )
        a["weeksRostered"] += 1
        a["starts"] += int(r["started"])
        a["points"] += r["points"]
        a["marginal"] += r["marginal"]
        a["marginalVsFa1"] += r["marginalVsFa1"] or 0.0
        a["marginalVsFa3"] += r["marginalVsFa3"] or 0.0

    def fmt(a: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": a["name"],
            "pos": a["pos"],
            "preValue": _r(a["preValue"], 0),
            "nowValue": _r(a["nowValue"], 0),
            "weeksRostered": a["weeksRostered"],
            "starts": a["starts"],
            "points": _r(a["points"], 1),
            "marginalPts": _r(a["marginal"], 1),
            "marginalVsBestFaPts": _r(a["marginalVsFa1"], 1),
            "marginalVs3rdFaPts": _r(a["marginalVsFa3"], 1),
        }

    def is_low(a: dict[str, Any]) -> bool:
        return a["preBand"] in ("<500", "500-1000", "1000-1500", "1500-2000", UNVALUED)

    low = [a for a in per_player.values() if is_low(a)]
    usable = [a for a in low if a["marginal"] > 1e-9]
    usable_vs_fa = [a for a in low if a["marginalVsFa3"] > 1e-9]
    never_started = [a for a in low if a["starts"] == 0]

    def depth_tier(a: dict[str, Any]) -> str:
        if a["starts"] == 0:
            return "filler_neverStarted"
        if a["marginal"] <= 1e-9:
            return "startedButRedundant_zeroMarginal"
        if a["marginalVsFa3"] > 1e-9:
            return "usableDepth_beatsFreeReplacement"
        return "lineupContributor_butReplaceableFromWaivers"

    tiers: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for a in low:
        tiers[depth_tier(a)].append(a)

    def count_by(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        c: dict[str, int] = defaultdict(int)
        for a in items:
            c[a[key]] += 1
        return dict(sorted(c.items()))

    depth_classes: dict[str, Any] = {}
    for band in BAND_ORDER:
        members = [a for a in per_player.values() if a["preBand"] == band]
        if not members:
            continue
        depth_classes[band] = {
            "distinctPlayersRostered": len(members),
            "neverStarted": sum(1 for a in members if a["starts"] == 0),
            "positiveMarginalVsBench": sum(1 for a in members if a["marginal"] > 1e-9),
            "positiveMarginalVs3rdBestFa": sum(1 for a in members if a["marginalVsFa3"] > 1e-9),
            "marginalPtsPerPlayerSeason": summarize([a["marginal"] for a in members]),
            "byPosition": {
                pos: {
                    "players": len(ps),
                    "neverStarted": sum(1 for a in ps if a["starts"] == 0),
                    "positiveMarginal": sum(1 for a in ps if a["marginal"] > 1e-9),
                    "positiveMarginalVs3rdBestFa": sum(1 for a in ps if a["marginalVsFa3"] > 1e-9),
                    "meanMarginalPtsPerPlayer": _r(statistics.fmean(a["marginal"] for a in ps)),
                }
                for pos in POSITIONS
                if (ps := [a for a in members if a["pos"] == pos])
            },
        }

    # ── 4. roster structure (current rosters) ───────────────────────────
    per_team_band: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    per_team_band_pos: dict[str, dict[str, dict[str, int]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(int))
    )
    for r in rosters_now:
        lab = team_label.get(int(r["roster_id"]), "team_unknown")
        for pid in r.get("players") or []:
            pid = str(pid)
            b = band_of(pre_vals.get(pid))
            per_team_band[lab][b] += 1
            per_team_band_pos[b][pos_group((pdb.get(pid) or {}).get("position"))][lab] += 1
    roster_structure = {
        "basis": "CURRENT Sleeper rosters (week-7 snapshot), banded by PRE-SEASON value",
        "rosterPlayersPerTeamByBand": {
            b: {
                "mean": _r(statistics.fmean(per_team_band[t].get(b, 0) for t in per_team_band), 1),
                "min": min(per_team_band[t].get(b, 0) for t in per_team_band),
                "max": max(per_team_band[t].get(b, 0) for t in per_team_band),
            }
            for b in BAND_ORDER
        },
        "rosterPlayersPerTeamByBandAndPosition_mean": {
            b: {
                pos: _r(sum(per_team_band_pos[b][pos].values()) / max(1, len(per_team_band)), 2)
                for pos in POSITIONS
                if per_team_band_pos[b].get(pos)
            }
            for b in BAND_ORDER
            if b in per_team_band_pos
        },
        "everStartedWeeks1toN_byBand": {
            b: {
                "distinctPlayersRosteredAnyWeek": d["distinctPlayersRostered"],
                "everStarted": d["distinctPlayersRostered"] - d["neverStarted"],
                "neverStarted": d["neverStarted"],
            }
            for b, d in depth_classes.items()
        },
    }

    # ── 5. replacement machinery on TODAY's board ───────────────────────
    replacement = replacement_block(contract, contract_league_ok, slots, rows, fa_ranked, weeks)

    # ── 6. free-agent scoring vs rostered low-value players ────────────
    fa_block: dict[str, Any] = {}
    for pos in POSITIONS:
        ranked = fa_ranked.get(pos) or []
        weekly_best = []
        weekly_third = []
        weekly_twelfth = []
        for w in weeks:
            wk = sorted(
                (
                    fa_weekly[pid][w]
                    for pid, _t in ranked
                    if w in fa_weekly[pid] and pid not in rostered_by_week[w]
                ),
                reverse=True,
            )
            if wk:
                weekly_best.append(wk[0])
            if len(wk) >= 3:
                weekly_third.append(wk[2])
            if len(wk) >= 12:
                weekly_twelfth.append(wk[11])
        low_rows = [r for r in rows if r["pos"] == pos and is_low({"preBand": r["preBand"]})]
        low_started = [r for r in low_rows if r["started"]]
        fa_block[pos] = {
            "freeAgentsWithStats": len(ranked),
            "top3FreeAgentsByTotal": [
                {
                    "name": (pdb.get(pid) or {}).get("full_name") or pid,
                    "totalPts": _r(t, 1),
                    "ppg": _r(t / len(weeks), 2),
                    "preValue": _r(pre_vals.get(pid), 0),
                }
                for pid, t in ranked[:3]
            ],
            "hindsightWeeklyBestFaPts_mean": _r(statistics.fmean(weekly_best))
            if weekly_best
            else None,
            "hindsightWeekly3rdBestFaPts_mean": _r(statistics.fmean(weekly_third))
            if weekly_third
            else None,
            "hindsightWeekly12thBestFaPts_mean": _r(statistics.fmean(weekly_twelfth))
            if weekly_twelfth
            else None,
            "rosteredLowValue_lt2000_or_unvalued": {
                "playerWeeks": len(low_rows),
                "meanPtsPerWeek": _r(statistics.fmean(r["points"] for r in low_rows))
                if low_rows
                else None,
                "meanPtsWhenStarted": _r(statistics.fmean(r["points"] for r in low_started))
                if low_started
                else None,
                "startRate": _r(len(low_started) / len(low_rows), 4) if low_rows else None,
            },
        }

    scorer_match = sum(1 for d in scorer_checks if d <= 0.011)
    out = {
        "schema": "low_value_assets.lineup_utility.v1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "researchOnly": True,
        "productionChanged": False,
        "league": {
            "leagueKey": LEAGUE_KEY,
            "season": SEASON,
            "teams": len(roster_ids),
            "rosterSize": league_registry.get_league_roster_settings(LEAGUE_KEY).get("rosterSize"),
            "bestBall": bool((league.get("settings") or {}).get("best_ball")),
            "starterSlots": slots,
            "starterSlotSource": slot_source,
            "weeks": weeks,
            "idsSanitized": "no Sleeper league/user/roster ids or team names are written",
        },
        "values": {
            "preseason": pre_meta,
            "today": {**today_meta, "contractSleeperBlockIsThisLeague": contract_league_ok},
            "bands": BAND_ORDER,
            "unvaluedMeans": "the board did not price this player (unpriced row or not on "
            "the board) - UNKNOWN, never a value of 0",
        },
        "validation": {
            "scorer": {
                "what": "canonical scorer (source='sleeper') vs host players_points, "
                "rostered player-weeks",
                "playerWeeks": len(scorer_checks),
                "withinOneHundredth": scorer_match,
                "maxAbsDiff": _r(max(scorer_checks) if scorer_checks else None, 3),
            },
            "solver": {
                "what": "canonical exact solver (realized_points) vs host best-ball starters",
                "rosterWeeks": solver_week_total,
                "scoreMatches": solver_week_matches,
                "identicalStarterSets": starter_set_matches,
                "maxAbsScoreDiff": _r(max(solver_score_diffs) if solver_score_diffs else None, 3),
                "note": "identical starter sets can differ only by equal-point ties",
            },
        },
        "method": {
            "marginal": "optimal(roster) - optimal(roster without player), canonical solver on "
            "that week's actual points; 0 for a non-starter by construction",
            "marginalVsFreeAgent": "optimal(roster) - optimal(roster without player + a "
            "free agent at his position): the value of his roster SPOT over the wire. The "
            "free agent is the best / 3rd-best player on NO roster at the current snapshot, "
            "ranked by weeks-1..N total (HINDSIGHT selection), with his actual points that "
            "week. Negative = a free agent in that spot would have scored more. Computed for "
            "every rostered player-week (bench players are <= 0 by construction)",
            "shareOfLeagueStartingPoints": "points this cell supplied while started / all "
            "starting points league-wide",
            "smallSample": f"flagged when < {MIN_PLAYER_WEEKS} player-weeks or "
            f"< {MIN_PLAYERS} distinct players",
            "byeWeeks": "kept (a rostered bye week is a real 0-utility roster week)",
        },
        "q1_q2_byPreseasonBand": by_band_pre,
        "q1_q2_byTodayBand": {
            "note": "same rows banded by TODAY's board - partly circular (today's values "
            "already absorbed weeks 1-6), shown for comparison only",
            "table": by_band_now,
        },
        "q3_rosterStructure": roster_structure,
        "q3_replacementLevels": replacement,
        "q4_usableDepthVsFiller": {
            "lowValueDefinition": "PRE-SEASON value < 2000 or unvalued",
            "lowValuePlayersRostered": len(low),
            "usableDepth_positiveMarginalVsBench": len(usable),
            "usableDepth_positiveMarginalVs3rdBestFa": len(usable_vs_fa),
            "neverStarted": len(never_started),
            "usableByPosition": count_by(usable, "pos"),
            "usableVsFaByPosition": count_by(usable_vs_fa, "pos"),
            "neverStartedByPosition": count_by(never_started, "pos"),
            "tiers": {
                "definitions": {
                    "filler_neverStarted": "0 best-ball starts in weeks 1..N",
                    "startedButRedundant_zeroMarginal": "started, but an equal bench "
                    "alternative existed every time (marginal 0)",
                    "lineupContributor_butReplaceableFromWaivers": "positive marginal over "
                    "the bench, but the 3rd-best free agent in his spot would have done as "
                    "well or better over weeks 1..N",
                    "usableDepth_beatsFreeReplacement": "positive marginal over the bench "
                    "AND over the 3rd-best free agent",
                },
                "counts": {k: len(v) for k, v in sorted(tiers.items())},
                "countsByPosition": {k: count_by(v, "pos") for k, v in sorted(tiers.items())},
            },
            "byBand": depth_classes,
            "topUsableExamples": [
                fmt(a) for a in sorted(usable, key=lambda a: -a["marginal"])[:30]
            ],
            "topUsableBeatsFreeReplacementExamples": [
                fmt(a)
                for a in sorted(
                    tiers.get("usableDepth_beatsFreeReplacement", []),
                    key=lambda a: -a["marginalVsFa3"],
                )[:30]
            ],
            "neverStartedExamples_highestPreValue": [
                fmt(a)
                for a in sorted(
                    never_started,
                    key=lambda a: -(a["preValue"] or 0),
                )[:20]
            ],
        },
        "q5_freeAgentReplacement": fa_block,
        "caveats": [
            f"{len(weeks)} weeks only: per-player season marginals are noisy; cell means "
            "with smallSample=true should not be quoted alone",
            "free agents are those on no roster NOW; the "
            "hindsight-best FA is an upper envelope a manager could not pick in advance, "
            "and best ball requires rostering before the week",
            "marginal vs bench measures realized lineup utility in THIS league's 58-man "
            "best-ball format; deep benches dilute any single depth player's marginal",
            "pre-season value of in-season breakouts and undrafted players is low or "
            "unvalued by construction; that is the question being asked, not a defect",
            "2025 (10 teams, different format) was not used: no pre-season board on this "
            "scale exists before 2026-07-14",
        ],
        "runtimeSeconds": _r(time.time() - t0, 1),
        "networkCalls": fetch.calls,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=False) + "\n")
    print(f"wrote {args.out.relative_to(REPO_ROOT)} in {out['runtimeSeconds']}s")
    return 0


def replacement_block(
    contract: Mapping[str, Any],
    contract_league_ok: bool,
    slots: list[str],
    rows: list[dict[str, Any]],
    fa_ranked: Mapping[str, list[tuple[str, float]]],
    weeks: list[int],
) -> dict[str, Any]:
    """Consume the canonical replacement owners on TODAY's board."""
    from src.draft.context import build_roster_context, contract_teams  # noqa: PLC0415
    from src.league_intel.replacement import compute_replacement_levels  # noqa: PLC0415
    from src.trade import faab_engine  # noqa: PLC0415

    out: dict[str, Any] = {"board": "TODAY (see values.today)"}
    if not contract_league_ok:
        out["refused"] = "contract sleeper block is not this league; not computed"
        return out

    arr = [r for r in contract.get("playersArray") or [] if isinstance(r, dict)]
    by_name = {}
    for r in arr:
        for f in ("displayName", "canonicalName", "legacyRef"):
            if r.get(f):
                by_name[str(r[f]).strip().lower()] = r
    teams = contract_teams(contract)

    # (a) waiver values + cut ladder per team (src.draft.displacement via context)
    waiver_values: dict[str, float] = {}
    ladders: list[list[dict[str, Any]]] = []
    notes: set[str] = set()
    for t in teams:
        try:
            ctx = build_roster_context(contract, LEAGUE_KEY, roster_id=t.get("roster_id"))
        except Exception as exc:  # noqa: BLE001
            notes.add(f"roster context failed: {type(exc).__name__}")
            continue
        waiver_values = ctx.get("waiverValues") or waiver_values
        ladders.append(ctx["cutLadder"]["rungs"])
    rung_base = [r["baseValue"] for lad in ladders for r in lad[:5]]
    rung_basis = defaultdict(int)
    for lad in ladders:
        for r in lad[:5]:
            rung_basis[r["valueBasis"]] += 1
    first5_pos = defaultdict(int)
    for lad in ladders:
        for r in lad[:5]:
            first5_pos[pos_group(r["position"])] += 1
    out["waiverValuesByPosition_bestUnrosteredBoardValue"] = waiver_values
    out["cutLadder"] = {
        "teams": len(ladders),
        "first5RungsBaseValue": summarize(rung_base),
        "first5RungsValueBasis": dict(rung_basis),
        "first5RungsByPosition": dict(sorted(first5_pos.items())),
        "rung1BaseValuePerTeam": sorted(_r(lad[0]["baseValue"], 0) for lad in ladders if lad),
        "notes": sorted(notes),
    }

    # (b) replacement levels in BOARD-VALUE space (rosValue := rankDerivedValue)
    def team_rows(value_of) -> list[dict[str, Any]]:
        out_t = []
        for t in teams:
            players = []
            for name in t.get("players") or []:
                r = by_name.get(str(name).strip().lower())
                if r is None:
                    continue
                players.append(
                    {
                        "playerId": r.get("playerId") or name,
                        "canonicalName": name,
                        "position": r.get("position"),
                        "rosValue": value_of(r),
                    }
                )
            out_t.append({"players": players})
        return out_t

    rostered = {str(n).strip().lower() for t in teams for n in (t.get("players") or [])}
    fas = [
        {"position": r.get("position"), "rosValue": r.get("rankDerivedValue")}
        for r in arr
        if str(r.get("assetClass") or "") != "pick"
        and not (
            {str(r.get(f) or "").strip().lower() for f in ("displayName", "canonicalName")}
            & rostered
        )
    ]
    levels = compute_replacement_levels(
        team_rows(lambda r: r.get("rankDerivedValue")), slots, free_agents=fas
    )
    out["replacementLevels_boardValue"] = {
        pos: {
            "startersPerTeam": round(pr.starters_per_team, 2),
            **{tier: _r(lv.value, 0) for tier, lv in pr.levels.items()},
        }
        for pos, pr in sorted(levels.items())
    }

    # (c) replacement levels in REALIZED-PPG space (weeks 1..N, the same
    # canonical function fed realized points per game instead of value).
    ppg: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        ppg[r["pid"]].append(r["points"])
    ppg_teams: dict[str, list[dict[str, Any]]] = defaultdict(list)
    last_week = max(weeks)
    for r in rows:
        if r["week"] != last_week:
            continue
        ppg_teams[r["team"]].append(
            {
                "playerId": r["pid"],
                "position": r["pos"],
                "rosValue": statistics.fmean(ppg[r["pid"]]),
            }
        )
    fa_ppg = [
        {"position": pos, "rosValue": tot / len(weeks)}
        for pos, ranked in fa_ranked.items()
        for _pid, tot in ranked
    ]
    lv_ppg = compute_replacement_levels(
        [{"players": v} for v in ppg_teams.values()], slots, free_agents=fa_ppg
    )
    out["replacementLevels_realizedPpgWeeks1toN"] = {
        "note": "rosValue := mean weekly points while rostered (weeks 1..N), rosters as of "
        "the last week; point estimates erase best-ball spikes (see the module docstring)",
        "levels": {
            pos: {
                "startersPerTeam": round(pr.starters_per_team, 2),
                **{tier: _r(lv.value, 2) for tier, lv in pr.levels.items()},
            }
            for pos, pr in sorted(lv_ppg.items())
        },
    }

    # (d) FAAB anchors (V_allin / V_repl) on today's board
    cfg = faab_engine.FaabConfig()
    excluded = set(cfg.get("anchors", "excludedPositions", []) or [])
    board_values = [
        r.get("rankDerivedValue")
        for r in arr
        if isinstance(r.get("rankDerivedValue"), (int, float))
        and str(r.get("position") or "").upper() not in excluded
        and str(r.get("assetClass") or "") != "pick"
    ]
    avail = [
        f["rosValue"]
        for f in fas
        if isinstance(f["rosValue"], (int, float))
        and str(f["position"] or "").upper() not in excluded
    ]
    anchors = faab_engine.resolve_anchors(
        board_values,
        faab_engine.LeagueContext(team_count=12, starters_per_team=20),
        available_values=avail or None,
    )
    out["faabAnchors"] = {
        "vAllIn": _r(anchors.v_allin, 0),
        "vRepl": _r(anchors.v_repl, 0),
        "formatRepl": _r(anchors.format_repl, 0),
        "livePoolRepl": _r(anchors.live_pool_repl, 0),
        "starterSlots": anchors.starter_slots,
        "note": "starters_per_team=20 excludes K (anchors.excludedPositions), as the "
        "waiver route passes it",
    }
    out["marketLevelForComparison"] = 2000
    return out


if __name__ == "__main__":
    raise SystemExit(main())
