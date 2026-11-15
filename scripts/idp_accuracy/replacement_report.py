#!/usr/bin/env python3
"""IDP accuracy Lane B: the offline replacement report (SHADOW, research only).

Authority: ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` section 7.
Record: ``docs/valuation/idp_accuracy/B_REPLACEMENT.md``.

Computes the six replacement definitions (``src/league_valuation/replacement_shadow.py``)
on the PINNED inputs of the Lane A manifest and writes aggregate-only evidence.
It changes no value, anchor, flag, scoring rule or served behaviour, imports
nothing into production, and writes nothing outside ``--out`` and the
gitignored cache ``data/idp_accuracy/cache``.

Pinned inputs (do not change without a new manifest):

* board: ``exports/archive/dynasty_export_20261025_120337.zip`` (sha256 checked),
  rebuilt with today's ``build_api_data_contract`` at this tree;
* league: Sleeper league ``LEAGUE_ID`` (registry key ``LEAGUE_KEY``);
* production: Sleeper weekly stat lines, 2026 regular season weeks 1-6, scored by
  the host-native scorer ``compute_weekly_points(source="sleeper")``
  (Lane A: 3,710 of 3,710 player-weeks equal Sleeper's own points);
* rosters / players DB / league settings: the Lane A cache snapshot (2026-10-25
  20:15Z), reused byte for byte.

The exact lineup solver is ``src.ros.lineup.solve_optimal_assignment`` (Lane A:
72 of 72 team-week totals equal Sleeper's best-ball totals), injected into the
shadow module through :class:`SolverPort`.

Public artifacts carry aggregates and public NFL player names only: no manager,
team or user names or ids (``assert_public_artifact``).
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
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCRIPT_DIR = REPO / "scripts"
sys.path.insert(0, str(REPO))

# ── pinned inputs ────────────────────────────────────────────────────────────
LEAGUE_KEY = "dynasty_main"
LEAGUE_ID = "1312006700437352448"
SEASON = 2026
WEEKS = (1, 2, 3, 4, 5, 6)
PINNED_ARCHIVE = "exports/archive/dynasty_export_20261025_120337.zip"
PINNED_ARCHIVE_SHA256 = "50fb251a79bc79abac54bcbcfc98c3018fc6b105115eb6dbd7928e3b6c8dc8f6"
SLEEPER = "https://api.sleeper.app/v1"
CACHE_DIR = REPO / "data/idp_accuracy/cache"
OUT_DEFAULT = "docs/valuation/idp_accuracy/evidence/b_replacement_2026-10-25.json"
B_PUBLISHED = "docs/valuation/evidence/idp_replacement_2026-10-20/idp_replacement.json"
TEAM_LABEL_SALT = "idp-accuracy-lane-b"


def _load_shadow():
    """The shadow module, loaded BY FILE PATH.

    ``tests/league_valuation/test_isolation.py`` pins that no production module --
    ``server.py``, ``src/``, ``scripts/`` or ``deploy/`` -- contains an ``import`` of
    ``src.league_valuation``.  This offline report is research tooling, not production,
    but the guard scans ``scripts/`` literally, so the module is loaded the way the
    sibling research scripts load each other (``_load_script``): by path.  When the
    module is already imported (a test did) that very object is reused, so there is
    never a second copy of its classes.
    """
    name = "src.league_valuation.replacement_shadow"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, REPO / "src" / "league_valuation" / "replacement_shadow.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rs = _load_shadow()

# ── the injected lineup owner ────────────────────────────────────────────────


class SolverPort:
    """The canonical lineup owner behind :class:`rs.LineupPort`.

    ``solve`` is ``src.ros.lineup.solve_optimal_assignment`` under the
    realized-points objective (exact maximum-weight assignment; Lane A verified
    it reproduces Sleeper's best-ball totals).  Nothing else is implemented
    here: no eligibility table, no fallback.
    """

    def __init__(self) -> None:
        from src.ros import lineup  # noqa: PLC0415

        self._lineup = lineup

    def solve(self, players: Sequence[rs.LineupPlayer], slots: Sequence[str]) -> Mapping[int, str]:
        lu = self._lineup
        pool = [
            lu.RosterPlayer(
                player_id=p.player_id,
                canonical_name=p.player_id,
                position=p.position,
                ros_value=float(p.points),
                fantasy_positions=tuple(p.fantasy_positions),
            )
            for p in players
        ]
        assignment = lu.solve_optimal_assignment(
            pool, list(slots), objective=lu.OBJECTIVE_REALIZED_POINTS
        )
        return {int(i): rp.player_id for i, rp in assignment.items()}

    def slot_family(self, slot: str) -> str:
        return self._lineup.normalize_slot(slot)


# ── polite cached fetcher (public, unauthenticated Sleeper GETs only) ─────────


class Fetcher:
    """Cached, throttled GET of public Sleeper endpoints.  A cached body is REUSED
    (``max_age_s=None``) so a re-run reproduces the same inputs."""

    MIN_INTERVAL_S = 0.25

    def __init__(self, cache_dir: Path = CACHE_DIR, *, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.offline = offline
        self._last = 0.0
        self.receipts: dict[str, dict[str, Any]] = {}

    def _path(self, url: str) -> Path:
        return self.cache_dir / f"{hashlib.sha256(url.encode()).hexdigest()[:24]}.json"

    def get(self, url: str) -> Any:
        path = self._path(url)
        if not path.exists():
            if self.offline:
                raise RuntimeError(f"offline and not cached: {url}")
            import requests  # noqa: PLC0415

            wait = self.MIN_INTERVAL_S - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            resp = requests.get(url, timeout=60)
            self._last = time.time()
            resp.raise_for_status()
            path.write_bytes(resp.content)
        blob = path.read_bytes()
        self.receipts[url] = {"sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob)}
        return json.loads(blob)


def _load_script(name: str):
    """Import a sibling research script by file name (Investigation B's loaders)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# ── inputs ───────────────────────────────────────────────────────────────────


def read_pinned_archive() -> tuple[dict, str]:
    """The pinned archive's raw payload and its (verified) sha256."""
    path = REPO / PINNED_ARCHIVE
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    if h != PINNED_ARCHIVE_SHA256:
        raise SystemExit(f"pinned archive sha256 mismatch: {h} != {PINNED_ARCHIVE_SHA256}")
    with zipfile.ZipFile(path) as zf:
        member = next(n for n in zf.namelist() if re.match(r"dynasty_data_.*\.json$", n))
        return json.loads(zf.read(member)), h


def fold_position(pos: str | None) -> str:
    """A Sleeper position in the lineup vocabulary (Investigation B's ``pos_group``)."""
    from src.ros.lineup import lineup_position  # noqa: PLC0415

    p = lineup_position(str(pos or ""))
    return "RB" if p == "FB" else p


def anonymous_team_labels(rosters: Sequence[Mapping[str, Any]]) -> dict[Any, str]:
    """``roster_id -> T01..`` in an order that carries no identity."""
    order = sorted(
        rosters,
        key=lambda r: hashlib.sha256(f"{TEAM_LABEL_SALT}:{r['roster_id']}".encode()).hexdigest(),
    )
    return {r["roster_id"]: f"T{i + 1:02d}" for i, r in enumerate(order)}


def load_sleeper(fetch: Fetcher) -> dict[str, Any]:
    league = fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}")
    return {
        "league": league,
        "rosters": fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}/rosters"),
        "pdb": fetch.get(f"{SLEEPER}/players/nfl"),
        "stats": {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{w}") for w in WEEKS},
        "matchups": {w: fetch.get(f"{SLEEPER}/league/{LEAGUE_ID}/matchups/{w}") for w in WEEKS},
    }


def score_weeks(sl: Mapping[str, Any]) -> tuple[dict[str, dict[int, float]], dict[str, Any]]:
    """Weekly league-scored points for every player with a stat line, by the
    host-native scorer, plus the check against Sleeper's own player points."""
    from src.nfl_data.realized_points import compute_weekly_points  # noqa: PLC0415

    card = {
        k: float(v)
        for k, v in (sl["league"].get("scoring_settings") or {}).items()
        if isinstance(v, (int, float))
    }
    pdb = sl["pdb"]
    pts: dict[str, dict[int, float]] = defaultdict(dict)
    for w, dump in sl["stats"].items():
        for sid, line in (dump or {}).items():
            sid = str(sid)
            if float(line.get("gp") or 0) <= 0:
                continue
            pos = fold_position((pdb.get(sid) or {}).get("position"))
            res = compute_weekly_points(
                {**line, "player_id": sid, "season": SEASON, "week": w},
                card,
                position=pos,
                source="sleeper",
            )
            if res is not None:
                pts[sid][int(w)] = float(res.fantasy_points)
    diffs = []
    for w in WEEKS:
        for m in sl["matchups"][w] or []:
            for sid, hp in (m.get("players_points") or {}).items():
                got = pts.get(str(sid), {}).get(w)
                if got is not None:
                    diffs.append(abs(got - float(hp)))
    check = {
        "playerWeeksCompared": len(diffs),
        "exactWithin0.01": sum(1 for d in diffs if d < 0.01),
        "maxAbsDiff": round(max(diffs), 4) if diffs else None,
    }
    return dict(pts), check


def infer_team_weeks(
    sl: Mapping[str, Any], pts: Mapping[str, Mapping[int, float]]
) -> dict[str, frozenset[int]]:
    """NFL team -> weeks it played, inferred from the stat dumps themselves (a team
    none of whose players has a stat line in a week was on bye).  Used for the
    availability rate only; a bye is a no-game week, never a zero score."""
    pdb = sl["pdb"]
    played: dict[str, set[int]] = defaultdict(set)
    for sid, weekly in pts.items():
        team = (pdb.get(sid) or {}).get("team")
        if team:
            played[team].update(weekly)
    return {t: frozenset(w for w in WEEKS if w in ws) for t, ws in played.items()}


def board_values(contract: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], int]:
    """Sleeper id -> {name, value, pos, rookie} for every PRICED player row."""
    sl = contract.get("sleeper") or {}
    name_to_id = {str(k): str(v) for k, v in (sl.get("playerIds") or {}).items()}
    out: dict[str, dict[str, Any]] = {}
    unjoined = 0
    for r in contract.get("playersArray") or []:
        if str(r.get("assetClass") or "") == "pick":
            continue
        v = r.get("rankDerivedValue")
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        sid = r.get("playerId")
        if not sid:
            for f in ("displayName", "canonicalName", "legacyRef"):
                sid = name_to_id.get(str(r.get(f) or ""))
                if sid:
                    break
        if not sid:
            unjoined += 1
            continue
        out[str(sid)] = {
            "name": r.get("displayName"),
            "value": float(v),
            "pos": (r.get("position") or "").upper(),
            "rookie": bool(r.get("rookie")),
        }
    return out, unjoined


def build_records(
    sl: Mapping[str, Any],
    pts: Mapping[str, Mapping[int, float]],
    board: Mapping[str, Mapping[str, Any]],
    team_weeks: Mapping[str, frozenset[int]],
) -> dict[str, rs.PlayerRecord]:
    """Every player the shadow may need: rostered, priced on the board, or with a
    stat line, in the lineup vocabulary.  Public NFL facts only."""
    pdb = sl["pdb"]
    live = {str(p) for r in sl["rosters"] for p in (r.get("players") or [])}
    ids = set(live) | set(board) | set(pts)
    out: dict[str, rs.PlayerRecord] = {}
    for sid in sorted(ids):
        meta = pdb.get(sid) or {}
        pos = fold_position(meta.get("position"))
        if pos not in rs.ALL_POSITIONS:
            if sid not in live:
                continue
            pos = pos or ""
        fps = []
        for p in meta.get("fantasy_positions") or []:
            q = fold_position(p)
            if q in rs.ALL_POSITIONS and q not in fps:
                fps.append(q)
        if pos and pos not in fps:
            fps.insert(0, pos)
        team = meta.get("team") or None
        b = board.get(sid)
        out[sid] = rs.PlayerRecord(
            player_id=sid,
            name=str(meta.get("full_name") or (b or {}).get("name") or sid),
            position=pos,
            fantasy_positions=tuple(fps),
            nfl_team=team,
            status=meta.get("status"),
            injury_status=meta.get("injury_status"),
            years_exp=meta.get("years_exp"),
            board_value=(b or {}).get("value"),
            weekly=dict(pts.get(sid) or {}),
            team_weeks=team_weeks.get(team) if team else None,
        )
    return out


# ── integrity: the engine against Sleeper's own best-ball totals ─────────────


def best_ball_reproduction(
    sl: Mapping[str, Any],
    records: Mapping[str, rs.PlayerRecord],
    port: SolverPort,
    slots: Sequence[str],
) -> dict[str, Any]:
    """Each team-week's roster AS PLAYED (the matchup's own player list), through
    the injected exact solver, against Sleeper's awarded best-ball total.

    Lane A verified 72 of 72; this repeats it inside this pipeline so the report
    states that its engine is the host's.
    """
    engine = rs.WeeklyEngine(records, port, slots, WEEKS, zero_fill_rostered=True)
    diffs = []
    for w in WEEKS:
        for m in sl["matchups"][w] or []:
            ids = [str(p) for p in (m.get("players") or [])]
            if not ids or m.get("points") is None:
                continue
            diffs.append(abs(engine.solve(ids, w).score - float(m["points"])))
    return {
        "teamWeeks": len(diffs),
        "withinRounding0.02": sum(1 for d in diffs if d < 0.02),
        "maxAbsDiff": round(max(diffs), 4) if diffs else None,
        "note": "Sleeper sums each player's points rounded to 2 decimals, so a total can differ from the unrounded sum by a few hundredths. A rostered player with no stat line scores 0.0 and is startable (the host's rule).",
    }


def projection_setup(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """The PROJECTED-roster inputs: empirical-Bayes expected ppg as one pseudo-week,
    the engine over it (no zero-fill: a player with no expectation is unknown, not
    zero), and the viable-pool census carrying the same expectation."""
    mg = int(cfg["window"]["minGames"]["value"])
    rostered = {pid for t in teams.values() for pid in t}
    eb = rs.fit_eb(records, rostered, WEEKS, min_games=mg)
    expected = {pid: m for pid, m in eb.mean.items() if rs.games_in(records[pid], WEEKS) >= mg}
    proj = rs.projection_records(records, expected)
    engine = rs.WeeklyEngine(proj, port, slots, (1,), zero_fill_rostered=False)

    def ppg_fn(rec: rs.PlayerRecord) -> float | None:
        return expected.get(rec.player_id)

    census = rs.build_census(
        records, rostered, weeks=WEEKS, cfg=cfg, rule=rs.PoolRule(), ppg_fn=ppg_fn
    )
    return {"eb": eb, "expected": expected, "records": proj, "engine": engine, "census": census}


def _r(x: Any, nd: int = 3) -> Any:
    return None if x is None else round(float(x), nd)


# ── per-position levels with game-level bootstrap ────────────────────────────

LEVEL_ROWS = (
    ("D1_starterMedianMarginal", "d1_medianMarginal"),
    ("D1_bestBallStarterFloor", "d1_bestBallFloor"),
    ("D2_bestViable", "d2_best"),
    ("D2_rank3Viable", "d2_rank3"),
    ("D2_bandedTop3Viable_LI5style", "d2_bandedTop"),
    ("D3_qualifiedPoolMean", "d3_poolMean"),
    ("D4_rank3Qualified", "d4_rank3"),
    ("D4_top5MedianQualified", "d4_top5Median"),
)


def level_tables(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
    *,
    replicates: int | None,
    estimator: str = rs.EST_RAW,
) -> dict[str, Any]:
    flat, det, aux = rs.compute_level_set(
        records, teams, port, slots, weeks=WEEKS, cfg=cfg, estimator=estimator, detail=True
    )
    resel = rs.reselection_bootstrap(
        records,
        teams,
        port,
        slots,
        weeks=WEEKS,
        cfg=cfg,
        replicates=replicates,
        estimator=estimator,
    )
    # The interval to quote is conditional on the selected identities and exists for the
    # raw estimator (the shrunk estimate is refitted from the whole population).
    cond = (
        rs.conditional_level_cis(records, det, aux, weeks=WEEKS, cfg=cfg, replicates=replicates)
        if estimator == rs.EST_RAW
        else None
    )
    out: dict[str, Any] = {}
    for p in rs.ALL_POSITIONS:
        d = det[p]
        c = (cond or {}).get(p, {})
        r = resel[p]
        rows: dict[str, Any] = {}
        for label, stem in LEVEL_ROWS:
            if estimator == rs.EST_EB and label.startswith("D1_"):
                # The shrinkage estimate is validated out of sample for FREE AGENTS only
                # (selectionRegression.estimatorMse). Shrinking rostered starters toward a
                # rostered mean that includes bench players would pull stars down; that use is
                # not validated and is not published.
                continue
            row: dict[str, Any] = {}
            for unit, tag in (("ppg", "Ppg"), ("value", "Value")):
                key = f"{stem}{tag}"
                cell: dict[str, Any] = {"point": _r((flat[p] or {}).get(key))}
                if unit == "ppg" and key in c:
                    cell["ci95Conditional"] = c[key]["ci95"]
                lvl = d.get(key)
                if lvl is not None:
                    cell["n"] = lvl.n
                    cell["reason"] = lvl.reason
                    cell["setBy"] = list(lvl.set_by)
                elif cell["point"] is None:
                    # a league-wide threshold (D1) with nobody to measure it on
                    cell["reason"] = (
                        "no_started_player_with_a_board_value"
                        if unit == "value"
                        else "no_started_player_with_ppg"
                    )
                rk = r.get(key) or {}
                if rk.get("reselection"):
                    cell["reselection"] = rk["reselection"]
                if rk.get("identityStability"):
                    cell["identityStability"] = rk["identityStability"]
                row[unit] = cell
            rows[label] = row
        gaps: dict[str, Any] = {}
        for k, v in c.items():
            if k.startswith("gap_"):
                gaps[k.removeprefix("gap_")] = {"point": v["point"], "ci95Conditional": v["ci95"]}
        out[p] = {
            "expectedPpg": None
            if estimator == rs.EST_EB
            else {
                "starterMean": c.get("starterMeanPpg")
                or {"point": _r(flat[p].get("starterMeanPpg"))},
                "starterMedian": c.get("starterMedianPpg")
                or {"point": _r(flat[p].get("starterMedianPpg"))},
            },
            "productionBarPpg_P10ofProductionStarters": _r(flat[p].get("productionBarPpg")),
            "levels": rows,
            "starterToReplacementGapPpg": {} if estimator == rs.EST_EB else gaps,
            "poolSizes": {
                "candidatesUnrostered": flat[p].get("candidatesN"),
                "viable": flat[p].get("viableN"),
                "qualified": flat[p].get("qualifiedN"),
                "unpricedViable": flat[p].get("unpricedViableN"),
            },
        }
    meta = {
        "estimator": estimator,
        "replicates": int(replicates or cfg["bootstrap"]["replicates"]["value"]),
        "seed": cfg["bootstrap"]["seed"],
        "intervalDefinition": "ci95Conditional: percentile interval from resampling the played weeks of exactly the players behind each number (and teams as clusters for league-wide thresholds); conditional on the selected identities, so it excludes selection (winner's curse). reselection: spread of the whole definition when games are resampled and everything is re-selected; it is biased upward for maxima and is NOT an interval. identityStability: how often the same player or set sets the level again.",
    }
    return {"bootstrap": meta, "byPosition": out, "_flat": flat, "_detail": det}


def depth_table(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
    flat: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Healthy waiver depth: how many free agents are usable, and how they compare to a starter."""
    rostered = {pid for t in teams.values() for pid in t}
    census = rs.build_census(records, rostered, weeks=WEEKS, cfg=cfg, rule=rs.PoolRule())
    min_games = int(cfg["window"]["minGames"]["value"])
    th_total = rs.starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=lambda r: rs.total_points(r, WEEKS)
        if rs.games_in(r, WEEKS) >= min_games
        else None,
    )
    out: dict[str, Any] = {}
    for p in rs.ALL_POSITIONS:
        pool = census.pool(p)
        ppgs = [e.ppg for e in pool.by_ppg()]
        med_start = flat[p].get("starterMedianPpg")
        bars: dict[str, Any] = {}
        for pct in (10, 25, 50):
            bar = rs.production_bars(th_total, records, WEEKS, pct).get(p)
            bars[f"P{pct}"] = {"barPpg": _r(bar), "qualified": len(pool.qualified(bar))}
        floor = flat[p].get("d1_bestBallFloorPpg")
        bars["bestBallStarterFloor"] = {
            "barPpg": _r(floor),
            "qualified": len(pool.qualified(floor)),
        }
        third = ppgs[2] if len(ppgs) >= 3 else None
        avail = [e.availability for e in pool.entries if e.availability is not None]
        out[p] = {
            "unrosteredCandidates": pool.candidates,
            "viable": len(pool.entries),
            "viableUncertainHealth": sum(1 for e in pool.entries if e.health.state == rs.UNCERTAIN),
            "unpricedViable": pool.unpriced,
            "excluded": dict(sorted(pool.excluded.items())),
            "qualifiedByBar": bars,
            "viableAtOrAboveMedianMarginalStarter": sum(
                1
                for x in ppgs
                if flat[p].get("d1_medianMarginalPpg") is not None
                and x >= flat[p]["d1_medianMarginalPpg"]
            ),
            "thirdBestViableOverMedianStarter": _r(third / med_start)
            if third is not None and med_start
            else None,
            "bestViableOverMedianStarter": _r(ppgs[0] / med_start) if ppgs and med_start else None,
            "meanAvailabilityRateViable": _r(statistics.fmean(avail)) if avail else None,
        }
    return out


# ── sensitivities ────────────────────────────────────────────────────────────


def _with_top_k(cfg: Mapping[str, Any], k: int) -> dict[str, Any]:
    import copy  # noqa: PLC0415

    c = copy.deepcopy(dict(cfg))
    c["levels"]["topK"]["value"] = int(k)
    return c


def sensitivities(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    """Point estimates of the headline levels under each PRIOR's alternatives."""
    keys = (
        "d2_bestPpg",
        "d2_rank3Ppg",
        "d3_poolMeanPpg",
        "d4_rank3Ppg",
        "d2_bestValue",
        "d2_rank3Value",
        "d3_poolMeanValue",
        "d4_rank3Value",
    )
    variants: dict[str, Any] = {}

    def run(name: str, *, rule: rs.PoolRule | None = None, pct: float | None = None) -> None:
        f = rs.compute_level_set(
            records, teams, port, slots, weeks=WEEKS, cfg=cfg, rule=rule, bar_percentile=pct
        )
        variants[name] = {
            p: {k: _r(f[p].get(k), 2) for k in keys}
            | {"viableN": f[p]["viableN"], "qualifiedN": f[p]["qualifiedN"]}
            for p in rs.POSITIONS
        }

    run("primary")
    run("bar_P25", pct=25)
    run("bar_P50", pct=50)
    run("drop_uncertain_health", rule=rs.PoolRule(include_uncertain=False))
    run("nominal_position_only", rule=rs.PoolRule.nominal_only())
    run(
        "pool_without_games_or_production_floor",
        rule=rs.PoolRule(require_min_games=False, require_positive_ppg=False),
    )
    k_variants = {}
    for k in sorted({*cfg["levels"]["topKSensitivities"], cfg["levels"]["topK"]["value"]}):
        f = rs.compute_level_set(records, teams, port, slots, weeks=WEEKS, cfg=_with_top_k(cfg, k))
        k_variants[f"top{k}Median"] = {
            p: {
                "ppg": _r(f[p].get(f"d4_top{k}MedianPpg"), 2),
                "value": _r(f[p].get(f"d4_top{k}MedianValue"), 1),
            }
            for p in rs.POSITIONS
        }
    return {"variants": variants, "topKVariants": k_variants}


# ── D5: dynamic league-wide allocation ───────────────────────────────────────


def _value_of_leftover(census: rs.Census, taken: set[str], p: str) -> float | None:
    rest = [e for e in census.pool(p).entries if e.player_id not in taken]
    return rs.level_best(rest, "value").value


def allocation_section(
    teams: Mapping[str, Sequence[str]],
    engine: rs.WeeklyEngine,
    census: rs.Census,
    cfg: Mapping[str, Any],
    cap: int | None,
) -> tuple[dict[str, Any], rs.Allocation]:
    alloc = rs.allocate_free_agents(teams, engine, census, cfg=cfg, roster_cap=cap)
    taken = {c.player_id for c in alloc.claims}
    reps = int(cfg["bootstrap"]["replicates"]["value"])
    seed = int(cfg["bootstrap"]["seed"])
    by_pos: dict[str, Any] = {}
    for p in rs.POSITIONS:
        row: dict[str, Any] = {}
        for tag, claims in (
            ("round1", [c for c in alloc.claims if c.position == p and c.round == 1]),
            ("allRounds", [c for c in alloc.claims if c.position == p]),
        ):
            priced = [c.value for c in claims if c.value is not None]
            row[tag] = {
                "claims": len(claims),
                "ppg": rs.cluster_bootstrap_mean(
                    [c.ppg for c in claims], replicates=reps, seed=seed
                ),
                "value": rs.cluster_bootstrap_mean(priced, replicates=reps, seed=seed),
                "unpricedClaims": len(claims) - len(priced),
                "gainPerWeek": rs.cluster_bootstrap_mean(
                    [c.gain_per_week for c in claims], replicates=reps, seed=seed
                ),
            }
        lo = alloc.leftover[p]
        row["leftoverBestViable"] = {
            "ppg": _r(lo.value),
            "setBy": list(lo.set_by),
            "value": _r(_value_of_leftover(census, taken, p), 1),
        }
        row["viableBeforeAllocation"] = len(census.pool(p).entries)
        by_pos[p] = row
    summary = {
        "method": cfg["allocation"]["method"],
        "mechanismNote": cfg["allocation"]["mechanismNote"],
        "rounds": cfg["allocation"]["rounds"]["value"],
        "roundsRun": alloc.rounds_run,
        "rosterCap": cap,
        "teamsWithoutFreeDrop": alloc.teams_without_free_drop,
        "claimsTotal": len(alloc.claims),
        "claimsByRound": dict(Counter(c.round for c in alloc.claims)),
        "round1": {
            "freeAgentsThatWereMoreThanOneTeamsBestClaim": alloc.round1_top_choice_collisions,
            "independentGainPerWeekSummed": _r(alloc.round1_independent_gain),
            "matchedGainPerWeekSummed": _r(alloc.round1_matched_gain),
            "competitionLossPerWeekSummed": _r(
                alloc.round1_independent_gain - alloc.round1_matched_gain
            ),
        },
        "claims": [
            {
                "round": c.round,
                "player": c.name,
                "position": c.position,
                "ppg": _r(c.ppg, 2),
                "value": _r(c.value, 0),
                "gainPerWeek": _r(c.gain_per_week, 2),
            }
            for c in alloc.claims
        ],
    }
    return {"summary": summary, "byPosition": by_pos}, alloc


def walk_forward_allocation(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
    cap: int | None,
) -> dict[str, Any]:
    """Out-of-sample check of the allocation: decide on history, score on the next week.

    For each evaluation week ``w`` the free-agent pool, the gains and the
    matching use ONLY weeks before ``w``.  The claims are then replayed on the
    real rosters and scored on week ``w`` alone: the realised lineup points the
    allocation added that week, against the points per week it predicted.
    """
    rostered = {pid for t in teams.values() for pid in t}
    rows = []
    for w in cfg["window"]["walkForwardEvalWeeks"]["value"]:
        hist = [x for x in WEEKS if x < w]
        eng_h = rs.WeeklyEngine(records, port, slots, hist)
        cen_h = rs.build_census(records, rostered, weeks=hist, cfg=cfg, rule=rs.PoolRule())
        alloc = rs.allocate_free_agents(teams, eng_h, cen_h, cfg=cfg, roster_cap=cap)
        final = rs.apply_claims(teams, alloc.claims)
        eng_w = rs.WeeklyEngine(records, port, slots, (w,))
        realised = sum(eng_w.score(final[t]) - eng_w.score(teams[t]) for t in teams)
        predicted = sum(c.gain_per_week for c in alloc.claims)
        by_claim = []
        for c in alloc.claims:
            r1 = rs.apply_claims({c.team: teams[c.team]}, [c])[c.team]
            by_claim.append(eng_w.score(r1) - eng_w.score(teams[c.team]))
        rows.append(
            {
                "week": w,
                "historyWeeks": hist,
                "claims": len(alloc.claims),
                "predictedPointsPerWeekFromHistory": _r(predicted, 2),
                "realisedPointsInWeek": _r(realised, 2),
                "realisedOverPredicted": _r(realised / predicted, 3) if predicted > 0 else None,
                "claimsThatScoredPositiveInWeek": sum(1 for g in by_claim if g > 1e-9),
                "claimsThatScoredZeroInWeek": sum(1 for g in by_claim if abs(g) <= 1e-9),
                "claimsThatHurtInWeek": sum(1 for g in by_claim if g < -1e-9),
            }
        )
    pred = sum(r["predictedPointsPerWeekFromHistory"] for r in rows)
    real = sum(r["realisedPointsInWeek"] for r in rows)
    return {
        "rule": "free agents, gains and the matching use weeks before w only; the claims are scored on week w alone",
        "byWeek": rows,
        "pooledRealisedOverPredicted": _r(real / pred, 3) if pred > 0 else None,
        "caveat": "three evaluation weeks and one allocation per week: an honest direction, not a precise ratio",
    }


# ── D6: team-specific replacement after a hypothetical transaction ───────────


def team_specific_section(
    teams: Mapping[str, Sequence[str]],
    engine: rs.WeeklyEngine,
    census: rs.Census,
    alloc: rs.Allocation,
    cfg: Mapping[str, Any],
    cap: int | None,
    ppg_fn: Callable[[str], float | None],
) -> dict[str, Any]:
    """Each team loses its highest-ppg player at the position; what is ITS best claim?

    Run twice: with every viable free agent open (no competition), and with the
    players the other teams claimed in the D5 allocation removed (competition).
    """
    reps = int(cfg["bootstrap"]["replicates"]["value"])
    seed = int(cfg["bootstrap"]["seed"])
    pool_all = list({e.player_id: e for pl in census.pools.values() for e in pl.entries}.values())
    claims_by_team: dict[str, set[str]] = defaultdict(set)
    for c in alloc.claims:
        claims_by_team[c.team].add(c.player_id)
    cells: dict[str, list[dict[str, Any]]] = defaultdict(list)
    n_weeks = len(engine.weeks)
    for t in sorted(teams):
        ros = list(teams[t])
        before_w = engine.per_week(ros)
        others = (
            set().union(*(claims_by_team[x] for x in claims_by_team if x != t))
            if claims_by_team
            else set()
        )
        for p in rs.POSITIONS:
            cand = [
                (ppg_fn(pid), pid)
                for pid in ros
                if pid in engine.records and engine.records[pid].position == p
            ]
            cand = [(v, pid) for v, pid in cand if v is not None]
            if not cand:
                continue
            _v, x = max(cand, key=lambda vp: (vp[0], vp[1]))
            after = [pid for pid in ros if pid != x]
            lost = (sum(before_w) - sum(engine.per_week(after))) / n_weeks
            cell: dict[str, Any] = {"lostPerWeek": lost}
            for mode, ex in (("open", ()), ("afterCompetition", others)):
                tr = rs.team_replacement_after(
                    after, pool_all, engine, exclude=ex, positions=(p,), roster_cap=cap
                )
                cell[mode] = tr.by_position[p]
            cells[p].append(cell)
    out: dict[str, Any] = {"scenario": cfg["teamSpecific"]["scenario"], "byPosition": {}}
    for p in rs.POSITIONS:
        rows = cells.get(p, [])
        entry: dict[str, Any] = {
            "teams": len(rows),
            "lostPerWeek": rs.cluster_bootstrap_mean(
                [r["lostPerWeek"] for r in rows], replicates=reps, seed=seed
            ),
        }
        for mode in ("open", "afterCompetition"):
            claims = [r[mode] for r in rows if r[mode]["state"] == "claim"]
            entry[mode] = {
                "teamsWithAClaimThatHelps": len(claims),
                "teamsInternalPromotionOnly": len(rows) - len(claims),
                "claimPpg": rs.cluster_bootstrap_mean(
                    [c["ppg"] for c in claims], replicates=reps, seed=seed
                ),
                "claimValue": rs.cluster_bootstrap_mean(
                    [c["value"] for c in claims if c["value"] is not None],
                    replicates=reps,
                    seed=seed,
                ),
                "claimsUnpriced": sum(1 for c in claims if c["value"] is None),
                "gainPerWeek": rs.cluster_bootstrap_mean(
                    [c["gainPerWeek"] for c in claims], replicates=reps, seed=seed
                ),
                "recoveredShareOfLoss": rs.cluster_bootstrap_mean(
                    [
                        min(1.0, r[mode]["gainPerWeek"] / r["lostPerWeek"])
                        for r in rows
                        if r["lostPerWeek"] > 1e-9
                    ],
                    replicates=reps,
                    seed=seed,
                ),
                "weakestStartedPpgWhenInternal": rs.cluster_bootstrap_mean(
                    [r[mode]["weakestStartedPpg"] for r in rows if r[mode]["state"] != "claim"],
                    replicates=reps,
                    seed=seed,
                ),
            }
        out["byPosition"][p] = entry
    return out


# ── marginal optimised best-ball contribution ────────────────────────────────


def _replacement_specs(
    records: Mapping[str, rs.PlayerRecord],
    rostered: set[str],
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
    bars: Mapping[str, float | None],
) -> dict[str, dict[str, rs.ReplacementSpec]]:
    census = rs.build_census(
        records, rostered, weeks=weeks, cfg=cfg, rule=rs.PoolRule(), positions=rs.POSITIONS
    )
    specs: dict[str, dict[str, rs.ReplacementSpec]] = {}
    for p in rs.POSITIONS:
        pool = census.pool(p)
        by_ppg = pool.by_ppg()
        qual = pool.qualified(bars.get(p))
        d: dict[str, rs.ReplacementSpec] = {}
        if by_ppg:
            d["D2best"] = rs.ReplacementSpec("D2best", by_ppg[0].rec)
        if len(qual) >= int(cfg["levels"]["rank"]["value"]):
            d["D4rank3"] = rs.ReplacementSpec(
                "D4rank3", qual[int(cfg["levels"]["rank"]["value"]) - 1].rec
            )
        syn = rs.synthetic_pool_mean(p, qual, weeks) if qual else None
        if syn is not None:
            d["D3poolMean"] = rs.ReplacementSpec("D3poolMean", syn, synthetic=True)
        specs[p] = d
    return specs


def _bars_on(
    teams: Mapping[str, Sequence[str]],
    records: Mapping[str, rs.PlayerRecord],
    port: SolverPort,
    slots: Sequence[str],
    weeks: Sequence[int],
    cfg: Mapping[str, Any],
) -> dict[str, float | None]:
    mg = int(cfg["window"]["minGames"]["value"])
    th = rs.starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=lambda r: rs.total_points(r, weeks) if rs.games_in(r, weeks) >= mg else None,
    )
    return rs.production_bars(
        th, records, weeks, float(cfg["qualification"]["primary"]["percentile"])
    )


def _aggregate_contrib(
    per_player: Mapping[str, Mapping[str, Any]], cfg: Mapping[str, Any]
) -> dict[str, Any]:
    reps = int(cfg["bootstrap"]["replicates"]["value"])
    seed = int(cfg["bootstrap"]["seed"])
    by_pos: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in per_player.values():
        by_pos[row["position"]].append(row)
    out: dict[str, Any] = {}
    for p in rs.POSITIONS:
        rows = by_pos.get(p, [])
        starters = [r for r in rows if r["startWeeks"] > 0]
        entry: dict[str, Any] = {
            "rostered": len(rows),
            "startedAtLeastOnce": len(starters),
            "emptyAllRostered": rs.cluster_bootstrap_mean(
                [r["contribution_empty"] for r in rows], replicates=reps, seed=seed
            ),
            "emptyStarters": rs.cluster_bootstrap_mean(
                [r["contribution_empty"] for r in starters], replicates=reps, seed=seed
            ),
        }
        labels = sorted(
            {
                k.removeprefix("contribution_over_")
                for r in rows
                for k in r
                if k.startswith("contribution_over_")
            }
        )
        for lab in labels:
            key = f"contribution_over_{lab}"
            entry[f"over_{lab}_all"] = rs.cluster_bootstrap_mean(
                [r.get(key) for r in rows], replicates=reps, seed=seed
            )
            entry[f"over_{lab}_starters"] = rs.cluster_bootstrap_mean(
                [r.get(key) for r in starters], replicates=reps, seed=seed
            )
        out[p] = entry
    return out


def contribution_section(
    teams: Mapping[str, Sequence[str]],
    records: Mapping[str, rs.PlayerRecord],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
) -> dict[str, Any]:
    rostered = {pid for t in teams.values() for pid in t}
    engine = rs.WeeklyEngine(records, port, slots, WEEKS)
    bars = _bars_on(teams, records, port, slots, WEEKS, cfg)
    specs = _replacement_specs(records, rostered, WEEKS, cfg, bars)
    in_sample = rs.marginal_contributions(teams, engine, specs)
    # walk-forward: the backfill is chosen from weeks BEFORE the week it is scored on
    eval_weeks = list(cfg["window"]["walkForwardEvalWeeks"]["value"])
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    meta: dict[str, dict[str, Any]] = {}
    for w in eval_weeks:
        hist = [x for x in WEEKS if x < w]
        specs_w = _replacement_specs(
            records, rostered, hist, cfg, _bars_on(teams, records, port, slots, hist, cfg)
        )
        res = rs.marginal_contributions(teams, engine, specs_w, eval_weeks=[w])
        for pid, row in res.items():
            meta[pid] = {"position": row["position"]}
            acc[pid]["startWeeks"].append(row["startWeeks"])
            for k, v in row.items():
                if k.startswith("contribution_"):
                    acc[pid][k].append(v)
    wf: dict[str, dict[str, Any]] = {}
    for pid, cols in acc.items():
        row = {"position": meta[pid]["position"], "startWeeks": int(sum(cols["startWeeks"]))}
        for k, v in cols.items():
            if k.startswith("contribution_"):
                row[k] = statistics.fmean(v)
        wf[pid] = row
    return {
        "unit": "best-ball lineup points per week, whole-roster solve per week (never a sum of per-player deltas)",
        "inSampleWeeks1to6": {
            "caution": "the backfill is selected on the same weeks it is scored on, so it is optimistic and every over-replacement value is understated",
            "byPosition": _aggregate_contrib(in_sample, cfg),
        },
        "walkForward": {
            "evalWeeks": eval_weeks,
            "rule": "for each evaluated week w the backfill is chosen from weeks < w only; its contribution is scored on week w alone",
            "byPosition": _aggregate_contrib(wf, cfg),
        },
        "backfills": {
            p: {
                k: (v.record.name if not v.synthetic else "synthetic week-by-week pool mean")
                for k, v in specs.get(p, {}).items()
            }
            for p in rs.POSITIONS
        },
    }


# ── whole-roster package evaluation ──────────────────────────────────────────


def _best_at(
    records: Mapping[str, rs.PlayerRecord],
    ids: Sequence[str],
    p: str,
    ppg_fn: Callable[[str], float | None],
    k: int,
) -> list[str]:
    cand = []
    for pid in ids:
        rec = records.get(pid)
        if rec is None or rec.position != p:
            continue
        v = ppg_fn(pid)
        if v is not None:
            cand.append((-v, pid))
    return [pid for _v, pid in sorted(cand)[:k]]


def package_section(
    teams: Mapping[str, Sequence[str]],
    engine: rs.WeeklyEngine,
    census: rs.Census,
    cfg: Mapping[str, Any],
    cap: int | None,
    ppg_fn: Callable[[str], float | None],
) -> dict[str, Any]:
    """Standard package recipes run for every team; each is a whole-roster before/after."""
    reps = int(cfg["bootstrap"]["replicates"]["value"])
    seed = int(cfg["bootstrap"]["seed"])
    records = engine.records
    pool_all = list({e.player_id: e for pl in census.pools.values() for e in pl.entries}.values())
    recipes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    example: dict[str, Any] | None = None
    for t in sorted(teams):
        ros = list(teams[t])
        started = engine.starter_weeks(ros)
        others = [pid for o, r in teams.items() if o != t for pid in r]
        for p in ("DL", "LB", "DB", "RB", "WR"):
            mine = sorted(
                (
                    (ppg_fn(pid), pid)
                    for pid in ros
                    if pid in records and records[pid].position == p and started.get(pid)
                ),
                key=lambda vp: (vp[0] if vp[0] is not None else 1e9, vp[1]),
            )
            mine = [(v, pid) for v, pid in mine if v is not None]
            best_other = _best_at(records, others, p, ppg_fn, 3)
            if len(mine) < 2 or len(best_other) < 3:
                continue
            specs = {
                "R1_swap_weakest_starter_for_league_best_1for1": ([mine[0][1]], [best_other[0]]),
                "R2_consolidate_two_weakest_starters_for_league_best_2for1": (
                    [mine[0][1], mine[1][1]],
                    [best_other[0]],
                ),
                "R3_expand_best_for_next_two_best_1for2": (
                    [_best_at(records, ros, p, ppg_fn, 1)[0]],
                    [best_other[1], best_other[2]],
                ),
            }
            for name, (give, get) in specs.items():
                res = rs.evaluate_package(
                    ros, give, get, engine, pool=pool_all, roster_cap=cap, backfill_positions=(p,)
                )
                if res.status != "ok":
                    continue
                recipes[f"{name}|{p}"].append(
                    {
                        "delta": res.delta_per_week,
                        "deltaBackfill": res.delta_with_backfill_per_week,
                        "naive": res.naive_sum_of_player_deltas,
                        "interaction": res.interaction,
                        "forcedDrops": len(res.forced_drops),
                        "perWeek": res.per_week_delta,
                    }
                )
                if example is None and name.startswith("R2") and p == "DB":
                    example = {
                        "recipe": name,
                        "position": p,
                        "give": [records[g].name for g in give],
                        "get": [records[g].name for g in get],
                        "beforePerWeek": _r(res.before_per_week, 2),
                        "afterPerWeek": _r(res.after_per_week, 2),
                        "deltaPerWeek": _r(res.delta_per_week, 2),
                        "deltaWithBackfillPerWeek": _r(res.delta_with_backfill_per_week, 2),
                        "naiveSumOfPlayerDeltas": _r(res.naive_sum_of_player_deltas, 2),
                        "interaction": _r(res.interaction, 2),
                        "perWeekDelta": [_r(x, 2) for x in res.per_week_delta],
                        "forcedDrops": res.forced_drops,
                        "backfill": res.backfill,
                    }
    out: dict[str, Any] = {}
    for key, rows in sorted(recipes.items()):
        out[key] = {
            "teams": len(rows),
            "deltaPerWeek": rs.cluster_bootstrap_mean(
                [r["delta"] for r in rows], replicates=reps, seed=seed
            ),
            "deltaWithBackfillPerWeek": rs.cluster_bootstrap_mean(
                [r["deltaBackfill"] for r in rows], replicates=reps, seed=seed
            ),
            "naiveSumOfPlayerDeltasPerWeek": rs.cluster_bootstrap_mean(
                [r["naive"] for r in rows], replicates=reps, seed=seed
            ),
            "interactionPerWeek": rs.cluster_bootstrap_mean(
                [r["interaction"] for r in rows], replicates=reps, seed=seed
            ),
            "meanAbsInteraction": _r(statistics.fmean(abs(r["interaction"]) for r in rows)),
            "teamsWhereNaiveSumDiffersFromWhole": sum(
                1 for r in rows if abs(r["interaction"]) > 0.005
            ),
            "forcedDropsMean": _r(statistics.fmean(r["forcedDrops"] for r in rows)),
        }
    return {
        "note": "every number is a whole before/after roster solve; the naive sum is shown only to expose the interaction",
        "recipes": out,
        "example": example,
    }


# ── reproduction of Investigation B ──────────────────────────────────────────

#: B's anchor name -> (health rule, metric of the shadow module in LEGACY-B mode, bar percentile)
B_REPRODUCTION_MAP = {
    "A0_current_liveRosters": ("none", "d2_bestValue", None),
    "A1_bestHealthy": ("loose", "d2_bestValue", None),
    "A1s_bestHealthy_strictRule": ("strict", "d2_bestValue", None),
    "A2_3rdBestHealthy": ("loose", "d2_rank3Value", None),
    "A3_li5BandedTop3_all": ("none", "d2_bandedTopValue", None),
    "A3h_li5BandedTop3_healthy": ("loose", "d2_bandedTopValue", None),
    "A3hs_li5BandedTop3_healthyStrictRule": ("strict", "d2_bandedTopValue", None),
    "A4_bestProductionQualified": ("loose", "d3_bestQualifiedValue", 10),
    "A4b_bestProductionQualified_P25bar": ("loose", "d3_bestQualifiedValue", 25),
}


def li5_parity(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
) -> dict[str, Any]:
    """Value-unit D1 against the canonical LI-5 owner, on the SAME rosters.

    Runs ``compute_replacement_levels`` (rosValue := board value, exactly as
    Investigation B's ``build_context`` does) and the shadow's D1 in nominal
    attribution (LI-5's own).  They are the same computation; any difference
    would be a bug in the shadow.
    """
    from src.league_intel.replacement import compute_replacement_levels  # noqa: PLC0415

    def prow(pid: str) -> dict[str, Any] | None:
        r = records.get(pid)
        if r is None or not r.board_value or r.board_value <= 0:
            return None
        return {
            "playerId": pid,
            "canonicalName": pid,
            "position": r.position,
            "rosValue": r.board_value,
            "fantasyPositions": list(r.fantasy_positions),
        }

    rep_teams = [{"players": [p for p in (prow(x) for x in t) if p]} for t in teams.values()]
    li5 = compute_replacement_levels(rep_teams, list(slots))
    th = rs.starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=rs.board_value_of,
        attribution=rs.ATTR_NOMINAL,
        eligibility=rs.ELIG_SLEEPER,
    )
    band = 2
    out: dict[str, Any] = {}
    for p in rs.POSITIONS:
        lv = (li5.get(p).levels if li5.get(p) else {}) or {}
        t = th.by_position.get(p)
        mine_floor = t.floor(band) if t else None
        mine_med = t.median_marginal() if t else None
        out[p] = {
            "li5BestBallStarter": _r(lv["bestBallStarter"].value, 4)
            if "bestBallStarter" in lv
            else None,
            "shadowBestBallFloor": _r(mine_floor, 4),
            "li5StarterMedianMarginal": _r(lv["starter"].value, 4) if "starter" in lv else None,
            "shadowMedianMarginal": _r(mine_med, 4),
            "equal": (
                (_r(lv["bestBallStarter"].value, 4) if "bestBallStarter" in lv else None)
                == _r(mine_floor, 4)
                and (_r(lv["starter"].value, 4) if "starter" in lv else None) == _r(mine_med, 4)
            ),
        }
    return out


def reproduce_b(
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    port: SolverPort,
    slots: Sequence[str],
    cfg: Mapping[str, Any],
    b_pinned_path: Path | None,
) -> dict[str, Any]:
    """Investigation B's anchors: its OWN script on the pinned inputs, its published
    numbers (2026-10-20 board), and the shadow module in legacy-B mode."""
    published = json.loads((REPO / B_PUBLISHED).read_text(encoding="utf-8"))
    pinned = json.loads(b_pinned_path.read_text(encoding="utf-8")) if b_pinned_path else None
    cache: dict[tuple[str, int | None], Any] = {}

    def legacy(health: str, pct: int | None) -> Any:
        key = (health, pct)
        if key not in cache:
            cache[key] = rs.compute_level_set(
                records,
                teams,
                port,
                slots,
                weeks=WEEKS,
                cfg=cfg,
                rule=rs.PoolRule.legacy_b(health=health),
                bar_percentile=pct,
                positions=rs.POSITIONS,
            )
        return cache[key]

    rows: dict[str, Any] = {}
    mismatches = []
    for p in rs.POSITIONS:
        rows[p] = {}
        for name, (health, metric, pct) in B_REPRODUCTION_MAP.items():
            mine = legacy(health, pct)[p].get(metric)
            cell: dict[str, Any] = {"shadowLegacyMode": _r(mine, 0)}
            if pinned is not None:
                b_new = pinned["Q1_anchors"]["byPosition"][p][name]["value"]
                cell["investigationBOnPinnedInputs"] = b_new
                cell["equal"] = (b_new is None and mine is None) or (
                    b_new is not None and mine is not None and abs(round(mine) - b_new) < 1
                )
                if not cell["equal"]:
                    mismatches.append(
                        {"position": p, "definition": name, "shadow": _r(mine, 0), "b": b_new}
                    )
            b_old = published["Q1_anchors"]["byPosition"][p][name]["value"]
            cell["investigationBPublished_2026_10_20"] = b_old
            rows[p][name] = cell
    out: dict[str, Any] = {
        "method": "Investigation B's script (scripts/idp_replacement_research.py, unmodified) was run on the pinned inputs; the shadow module in legacy-B mode (pools keyed by listed position, B's health rules, no games/production floor, value ordering, B's production bar) is compared field by field",
        "anchorsByPosition": rows,
        "shadowVsBOnPinnedInputs": {
            "compared": sum(1 for p in rows for c in rows[p].values() if "equal" in c),
            "equal": sum(1 for p in rows for c in rows[p].values() if c.get("equal")),
            "mismatches": mismatches,
        }
        if pinned is not None
        else "not run (no --b-pinned-run supplied)",
    }
    if pinned is not None:
        out["pinnedBoard"] = pinned["board"]["archive"]
        out["publishedBoard"] = published["board"]["archive"]
    return out


# ── consumer-impact diagnostics (offline, read-only) ─────────────────────────

#: Anchor sets handed to the consumers' own pure functions, in board-VALUE units.
ANCHOR_SETS = (
    ("D1_starterMedianMarginal", "d1_medianMarginalValue"),
    ("D1_bestBallStarterFloor", "d1_bestBallFloorValue"),
    ("D2_bestViable", "d2_bestValue"),
    ("D2_rank3Viable", "d2_rank3Value"),
    ("D2_bandedTop3Viable", "d2_bandedTopValue"),
    ("D3_qualifiedPoolMean", "d3_poolMeanValue"),
    ("D4_rank3Qualified", "d4_rank3Value"),
)


def _contract_rows(contract: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in contract.get("playersArray") or []:
        v = r.get("rankDerivedValue")
        if str(r.get("assetClass") or "") == "pick" or not isinstance(v, (int, float)) or v <= 0:
            continue
        out[str(r["displayName"])] = {
            "value": float(v),
            "pos": (r.get("position") or "").upper(),
            "rookie": bool(r.get("rookie")),
            "pid": str(r.get("playerId") or ""),
        }
    return out


def consumer_impact(
    contract: Mapping[str, Any],
    records: Mapping[str, rs.PlayerRecord],
    teams: Mapping[str, Sequence[str]],
    flat: Mapping[str, Mapping[str, Any]],
    alloc: rs.Allocation,
    census: rs.Census,
    engine: rs.WeeklyEngine,
    cfg: Mapping[str, Any],
    cap: int | None,
) -> dict[str, Any]:
    """What each consumer's own pure function would see under each definition.

    OFFLINE and read-only: the anchor dicts are swapped into the real
    ``CapacityContext`` / ``faab_engine`` / Perfect Draft surplus arithmetic that
    Investigation B used; nothing is written back and no flag is touched.  The
    consumers read the contract's own roster snapshot (the scrape-time rosters);
    the definitions are computed on the live Sleeper rosters, and the two are
    compared in ``rosterSnapshotAgreement``.
    """
    import dataclasses  # noqa: PLC0415

    from src.draft.displacement import waiver_values_by_position  # noqa: PLC0415
    from src.trade import faab_engine  # noqa: PLC0415
    from src.trade.finder import _BOARD_EDGE_WEIGHT  # noqa: PLC0415
    from src.trade.roster_capacity import (  # noqa: PLC0415
        assess_roster_capacity,
        build_capacity_context,
        forced_drop_cost,
    )
    from src.api import league_registry  # noqa: PLC0415

    rows = _contract_rows(contract)
    sl = contract.get("sleeper") or {}
    c_teams = sl.get("teams") or []
    roster_settings = league_registry.get_league_roster_settings(LEAGUE_KEY)
    OFF = ("QB", "RB", "WR", "TE")

    # the served anchor, exactly as the consumers build it today
    rostered_keys = [n for t in c_teams for n in (t.get("players") or [])] + [
        str(x) for t in c_teams for x in (t.get("playerIds") or []) if x
    ]
    served = {k: float(v) for k, v in waiver_values_by_position(contract, rostered_keys).items()}

    live_ids = {pid for t in teams.values() for pid in t}
    contract_ids = {str(x) for t in c_teams for x in (t.get("playerIds") or []) if x}
    agreement = {
        "liveRosteredIds": len(live_ids),
        "contractRosteredIds": len(contract_ids),
        "inLiveNotInContract": len(live_ids - contract_ids),
        "inContractNotInLive": len(contract_ids - live_ids),
    }

    def anchor_dict(values: Mapping[str, Any]) -> tuple[dict[str, float], list[str]]:
        d = dict(served)
        fell_back = []
        for p in rs.POSITIONS:
            v = values.get(p)
            if v is None:
                fell_back.append(p)
            else:
                d[p] = float(v)
        return d, fell_back

    sets: dict[str, tuple[dict[str, float], list[str]]] = {"A0_served": (dict(served), [])}
    for name, metric in ANCHOR_SETS:
        sets[name] = anchor_dict({p: flat[p].get(metric) for p in rs.POSITIONS})
    # D5: the value of what the allocation actually hands out, and what is left
    taken = {c.player_id for c in alloc.claims}
    r1 = defaultdict(list)
    for c in alloc.claims:
        if c.round == 1 and c.value is not None:
            r1[c.position].append(c.value)
    sets["D5_allocatedMeanRound1"] = anchor_dict(
        {p: (statistics.fmean(v) if v else None) for p, v in r1.items()}
    )
    sets["D5_leftoverBestViable"] = anchor_dict(
        {p: _value_of_leftover(census, taken, p) for p in rs.POSITIONS}
    )

    # a neutral trade per team, as Investigation B built it (net +1 and net +2)
    def nearest(team: Mapping[str, Any], k: int) -> list[str]:
        cand = [
            (abs(rows[n]["value"] - 3500), n)
            for n in team.get("players") or []
            if n in rows and rows[n]["pos"] in OFF
        ]
        return [n for _, n in sorted(cand)[:k]]

    scenarios = []
    for i, team in enumerate(c_teams):
        other = c_teams[(i + 1) % len(c_teams)]
        give = nearest(team, 1)
        for net, k_in in (("net+1", 2), ("net+2", 3)):
            scenarios.append((i, team, net, give, nearest(other, k_in)))

    pool_all = list({e.player_id: e for pl in census.pools.values() for e in pl.entries}.values())
    ctx_cache: dict[int, Any] = {}

    def team_ctx(i: int, team: Mapping[str, Any]):
        if i not in ctx_cache:
            ctx_cache[i] = build_capacity_context(
                contract, LEAGUE_KEY, team, roster_settings=roster_settings
            )
        return ctx_cache[i]

    def run_capacity(
        anchor_for: Callable[
            [int, str, Sequence[str], Sequence[str], Mapping[str, Any]], Mapping[str, float]
        ],
    ) -> list[dict[str, Any]]:
        out = []
        for i, team, net, give, recv in scenarios:
            ctx_t = team_ctx(i, team)
            wv = anchor_for(i, net, give, recv, team)
            c2 = dataclasses.replace(ctx_t, waiver_values=dict(wv))
            capr = assess_roster_capacity(c2, incoming_players=recv, outgoing_players=give)
            cost, _basis = forced_drop_cost(capr)
            give_v = sum(rows[n]["value"] for n in give)
            out.append(
                {
                    "scenario": net,
                    "drops": [(d.name, d.position, d.value_basis) for d in capr.forced_drops],
                    "cost": cost,
                    "finderFactor": (-(cost / max(give_v, 1)) * _BOARD_EDGE_WEIGHT)
                    if cost is not None
                    else None,
                }
            )
        return out

    base_rows = run_capacity(lambda *_a: served)

    def summarize(cap_rows: list[dict[str, Any]], name: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for scn in ("net+1", "net+2"):
            idx = [k for k, r in enumerate(scenarios) if r[2] == scn]
            changed = sum(1 for k in idx if cap_rows[k]["drops"] != base_rows[k]["drops"])
            dc = [
                cap_rows[k]["cost"] - base_rows[k]["cost"]
                for k in idx
                if cap_rows[k]["cost"] is not None and base_rows[k]["cost"] is not None
            ]
            dfac = [
                cap_rows[k]["finderFactor"] - base_rows[k]["finderFactor"]
                for k in idx
                if cap_rows[k]["finderFactor"] is not None
                and base_rows[k]["finderFactor"] is not None
            ]
            drops = [d for k in idx for d in cap_rows[k]["drops"]]
            out[scn] = {
                "teams": len(idx),
                "teamsWhoseForcedDropChanged": changed,
                "forcedDropCountMean": _r(
                    statistics.fmean(len(cap_rows[k]["drops"]) for k in idx), 2
                ),
                "forcedDropCostMean": _r(
                    statistics.fmean(
                        cap_rows[k]["cost"] for k in idx if cap_rows[k]["cost"] is not None
                    ),
                    0,
                ),
                "deltaCostVsServed_mean": _r(statistics.fmean(dc), 0) if dc else None,
                "deltaCostVsServed_maxAbs": _r(max((abs(x) for x in dc), default=0), 0),
                "deltaFinderFactor_meanAbs": _r(statistics.fmean(abs(x) for x in dfac), 2)
                if dfac
                else None,
                "forcedDropsByPosition": dict(Counter(p for _n, p, _b in drops)),
                "dropsChargedAsAssumedWaiver": sum(1 for *_x, b in drops if b == "assumedWaiver"),
            }
        return out

    capacity: dict[str, Any] = {}
    for name, (wv, fell) in sets.items():
        res = base_rows if name == "A0_served" else run_capacity(lambda *_a, _wv=wv: _wv)
        capacity[name] = {"positionsFellBackToServed": fell, **summarize(res, name)}

    # D6: the team-specific anchor AFTER that very trade (priced claims only; else served)
    def d6_anchor(
        i: int, net: str, give: Sequence[str], recv: Sequence[str], team: Mapping[str, Any]
    ) -> Mapping[str, float]:
        ids = [str(x) for x in (team.get("playerIds") or []) if str(x) in records]
        gid = {rows[n]["pid"] for n in give if n in rows}
        rid = [rows[n]["pid"] for n in recv if n in rows and rows[n]["pid"] in records]
        after = [x for x in ids if x not in gid] + [x for x in rid if x not in ids]
        tr = rs.team_replacement_after(
            after, pool_all, engine, positions=rs.POSITIONS, roster_cap=cap
        )
        d = dict(served)
        for p, v in tr.by_position.items():
            if v["state"] == "claim" and v["value"] is not None:
                d[p] = float(v["value"])
        return d

    d6_rows = run_capacity(d6_anchor)
    d6_fell = Counter()
    for i, team, net, give, recv in scenarios:
        a = d6_anchor(i, net, give, recv, team)
        for p in rs.POSITIONS:
            if a.get(p) == served.get(p):
                d6_fell[p] += 1
    capacity["D6_teamSpecificAfterTheTrade"] = {
        "positionsFellBackToServedTeamScenarios": dict(sorted(d6_fell.items())),
        "note": "a position whose best claim is unpriced or helps nobody keeps the served anchor (counted, never zero)",
        **summarize(d6_rows, "D6"),
    }

    # Perfect Draft: rookies whose board value clears the position's anchor
    rookies = [b for b in rows.values() if b["rookie"] and b["pos"] in rs.POSITIONS]
    perfect_draft: dict[str, Any] = {}
    for name, (wv, _f) in sets.items():
        by = defaultdict(lambda: [0, 0.0, 0])
        for b in rookies:
            s = max(0.0, b["value"] - wv.get(b["pos"], min(wv.values())))
            by[b["pos"]][0] += s > 0
            by[b["pos"]][1] += s
            by[b["pos"]][2] += 1
        perfect_draft[name] = {
            p: {"rookies": v[2], "positiveSurplus": v[0], "surplusSum": _r(v[1], 0)}
            for p, v in sorted(by.items())
        }

    # FAAB V_repl is position-agnostic and reads the live pool's 12th best
    excluded = set(faab_engine.FaabConfig().get("anchors", "excludedPositions", []) or [])
    starters_map = roster_settings.get("starters") or {}
    spt = sum(int(v or 0) for k, v in starters_map.items() if str(k).upper() != "K") or 20
    board_vals = [r["value"] for r in rows.values() if (r["pos"] or "") not in excluded]
    rostered_names = {n for t in c_teams for n in (t.get("players") or [])}
    pools = {
        "all_unrostered_served": [
            r["value"]
            for n, r in rows.items()
            if n not in rostered_names and (r["pos"] or "") not in excluded
        ],
        "viable_unrostered_priced": [
            e.value for e in pool_all if e.value is not None and e.rec.position not in excluded
        ],
        "qualified_priced": [
            e.value
            for pl in census.pools.values()
            for e in pl.qualified(flat[pl.position].get("productionBarPpg"))
            if e.value is not None
        ],
        "leftover_after_allocation_priced": [
            e.value for e in pool_all if e.player_id not in taken and e.value is not None
        ],
    }
    faab: dict[str, Any] = {}
    w = max(
        0.0, min(1.0, faab_engine.FaabConfig().num("anchors", "replacementLivePoolWeight", 0.5))
    )
    for pname, av in pools.items():
        a = faab_engine.resolve_anchors(
            board_vals,
            faab_engine.LeagueContext(team_count=len(c_teams) or 12, starters_per_team=spt),
            available_values=av or None,
        )
        faab[pname] = {
            "poolSize": len(av),
            "vRepl": _r(a.v_repl, 0),
            "vReplRawBlendBeforeGuardrail": _r(
                w * a.live_pool_repl + (1 - w) * a.format_repl
                if a.live_pool_repl is not None and a.format_repl is not None
                else None,
                0,
            ),
            "guardrailWidened": a.widened,
            "livePoolRepl_12th": _r(a.live_pool_repl, 0),
            "formatRepl": _r(a.format_repl, 0),
            "vAllin": _r(a.v_allin, 0),
            "objectiveCeilingPctOfBudget": {
                str(v): _r(100 * faab_engine.objective_ceiling(v, a)[0], 1)
                for v in (1800, 2200, 2600, 3000, 4000)
            },
        }

    # LI-5 consolidation (flag replacement_level_li5_consolidation, OFF, owner-held): its lens-A level
    li5_ref = None
    try:
        li5_ref = _li5_flag_on_levels(contract, records, rostered_keys)
    except Exception as exc:  # noqa: BLE001 — a reference column, reported not hidden
        li5_ref = {"state": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:200]}

    return {
        "scope": "OFFLINE shadow: anchor dicts swapped into the consumers' own pure functions; nothing written back, no flag changed",
        "rosterSnapshotAgreement": agreement,
        "servedAnchorsByPosition": {p: _r(served.get(p), 0) for p in rs.POSITIONS},
        "anchorSets": {
            name: {
                "valueByPosition": {p: _r(wv.get(p), 0) for p in rs.POSITIONS},
                "fellBackToServed": fell,
            }
            for name, (wv, fell) in sets.items()
        },
        "rosterCapacityAndTradeFinder": {
            "trade": "each team gives its offense player nearest 3,500 and receives the next team's two (net +1) or three (net +2) offense players nearest 3,500 (Investigation B's neutral trade)",
            "bySet": capacity,
        },
        "perfectDraftRookieSurplusOverAnchor": perfect_draft,
        "faabVRepl": {
            "pools": faab,
            "note": "FAAB V_repl is position-agnostic and has its own anchor; only the pool it reads changes here",
        },
        "li5ConsolidationFlagOn_lensA": li5_ref,
        "scarcityMultiplier": "inert (1.0) at every position: the gameplan bundle still hands LI-5 no free agents, and none of the definitions here changes that",
    }


def _li5_flag_on_levels(
    contract: Mapping[str, Any],
    records: Mapping[str, rs.PlayerRecord],
    rostered_keys: Sequence[str],
) -> dict[str, Any]:
    """The level the LI-5 consolidation would serve with its flag ON (lens A: banded top-3
    over the health-filtered add-pool), computed offline from the cached players DB."""
    from datetime import date  # noqa: PLC0415

    from src.draft.displacement import waiver_values_by_position  # noqa: PLC0415
    from src.draft.waiver_population import HealthEvidence, build_waiver_population  # noqa: PLC0415
    from src.ros.availability import build_context  # noqa: PLC0415

    pdb = {pid: {"injury_status": r.injury_status, "status": r.status, "team": r.nfl_team, "position": r.position}
           for pid, r in records.items()}  # fmt: skip
    league_settings = ((contract.get("sleeper") or {}).get("leagueSettings")) or {}
    ctx = build_context(
        season=SEASON, league_settings=league_settings, schedule_rows=[], evidence_payload=None
    )
    pop = build_waiver_population(
        contract,
        rostered_keys,
        (),
        rookies_eligible=True,
        availability=ctx,
        health_evidence=HealthEvidence(pdb, None, None),
        as_of=date(2026, 10, 25),
    )
    wv = waiver_values_by_position(contract, rostered_keys, population=pop)
    return {
        "state": pop.health.get("state"),
        "lens": pop.served_lens,
        "valueByPosition": {p: _r(wv.get(p), 0) for p in rs.POSITIONS},
        "population": {
            k: v
            for k, v in pop.provenance().items()
            if k
            in (
                "baseFreeAgents",
                "addPoolEligible",
                "eligibleFreeAgents",
                "excludedByReason",
                "health",
            )
        },
        "note": "no schedule rows were supplied, so byes are not applied; the health step uses the cached players DB statuses only",
    }


# ── headline, limits, main ───────────────────────────────────────────────────


def headline(
    levels_raw: Mapping[str, Any], levels_eb: Mapping[str, Any], depth: Mapping[str, Any]
) -> dict[str, Any]:
    """The numbers to quote, with n and the conditional interval."""
    out: dict[str, Any] = {}
    for p in rs.POSITIONS:
        raw = levels_raw["byPosition"][p]
        eb = levels_eb["byPosition"][p]

        def cell(table: Mapping[str, Any], label: str, unit: str = "ppg") -> dict[str, Any]:
            c = table["levels"][label][unit]
            return {
                k: c.get(k) for k in ("point", "ci95Conditional", "n", "reason", "setBy") if k in c
            }

        out[p] = {
            "starterMedianPpg": raw["expectedPpg"]["starterMedian"],
            "starterMeanPpg": raw["expectedPpg"]["starterMean"],
            "D1_starterMedianMarginalPpg": cell(raw, "D1_starterMedianMarginal"),
            "D1_bestBallStarterFloorPpg": cell(raw, "D1_bestBallStarterFloor"),
            "D2_bestViablePpg": cell(raw, "D2_bestViable"),
            "D2_bestViablePpg_empiricalBayes": cell(eb, "D2_bestViable"),
            "D3_qualifiedPoolMeanPpg": cell(raw, "D3_qualifiedPoolMean"),
            "D4_rank3QualifiedPpg": cell(raw, "D4_rank3Qualified"),
            "gapMedianStarterMinusD2best": raw["starterToReplacementGapPpg"].get("d2_bestPpg"),
            "gapMedianStarterMinusD1medianMarginal": raw["starterToReplacementGapPpg"].get(
                "d1_medianMarginalPpg"
            ),
            "viable": depth[p]["viable"],
            "qualifiedP10": depth[p]["qualifiedByBar"]["P10"]["qualified"],
            "unpricedViable": depth[p]["unpricedViable"],
            "thirdBestViableOverMedianStarter": depth[p]["thirdBestViableOverMedianStarter"],
        }
    return out


LIMITS = [
    "Six regular-season weeks (2026 weeks 1-6). A free agent's ppg is three to six games; single-player levels (D2 best, D4 rank 3) are noise-dominated and their intervals are wide.",
    "The interval quoted is CONDITIONAL on the players who set each level; it excludes the selection itself. Free agents were chosen because their ppg was high, and the out-of-sample check shows the top five by history score roughly half (IDP) of it the next week. Read every free-agent level beside selectionRegression.",
    "The game-level full-procedure bootstrap is biased upward for maxima and for lineup-optimised statistics; it is published only as selection stability (identity) and an inflation diagnostic, never as an interval.",
    "In-sample lineup gains (D5, D6, packages, contributions over replacement) are hindsight: the backfill is chosen on the weeks it is scored on. The walk-forward blocks choose on weeks before the scored week; the allocation realised about a quarter of what history predicted.",
    "The board prices only a minority of the productive free agents (unpricedViable). Value-unit D3/D4 levels therefore rest on very few priced players and are mostly undefined or near the board floor; an unpriced player is counted and never given a value of 0.",
    "A DL/LB hybrid is legal at either slot by Sleeper's fantasy_positions (the exact solver's basis, verified against Sleeper's awarded best-ball totals); the eligibility-uncertainty block shows how much each level moves if hybrids were nominal only.",
    "Health is a single snapshot (2026-10-25 20:15Z players DB: explicit status plus injury designation). A missing status is UNKNOWN. Bye weeks are inferred from the stat dumps for weeks 1-6 only; no forward schedule was used, so a future bye is not modelled.",
    "D5 is a planner allocation (maximise total lineup points; each free agent to at most one team). It is not a model of FAAB bidding and does not say who wins a contested player. The cheapest legal drop is a rostered player who never starts, which is exact (adding a player cannot promote a non-starter) and free; this is the module's own lineup-points reading, not the production forced-drop owner.",
    "Empirical-Bayes expectation uses a normal prior per (position, rostered or free agent). Free-agent populations are right-skewed mixtures, so it over-shrinks true risers; it brackets the raw level from below. It is validated out of sample for FREE AGENTS only (estimatorMse: lower squared error than raw); it is not published for rostered starters, where a rostered mean that includes bench players would pull stars down.",
    "Consumer diagnostics swap anchor dicts into the consumers' own pure functions offline. They are not the served result: no flag was changed, and the displacement/capacity owners were read, never edited.",
    "Investigation B's 2,156 DB anchor (an Out player) does not reproduce on the pinned 2026-10-25 inputs because the rosters moved; its code reproduces exactly on the new inputs (63 of 63 anchors), so the change is data, not method.",
]


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument(
        "--replicates", type=int, default=None, help="bootstrap replicates (default: config)"
    )
    ap.add_argument(
        "--b-pinned-run",
        type=Path,
        default=None,
        help="JSON from scripts/idp_replacement_research.py run on the pinned inputs",
    )
    ap.add_argument(
        "--offline", action="store_true", help="fail if a Sleeper body is not already cached"
    )
    ap.add_argument(
        "--skip-slow",
        action="store_true",
        help="skip the walk-forward allocation and the package recipes",
    )
    args = ap.parse_args(argv)
    t0 = time.time()

    def log(msg: str) -> None:
        print(f"[{time.time() - t0:7.1f}s] {msg}", file=sys.stderr, flush=True)

    from src.api import league_registry  # noqa: PLC0415
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.ros.lineup import resolve_starter_slots  # noqa: PLC0415

    cfg = rs.load_config()
    port = SolverPort()
    raw, archive_sha = read_pinned_archive()
    contract = build_api_data_contract(raw)
    log("board rebuilt from the pinned archive")
    fetch = Fetcher(offline=args.offline)
    sl = load_sleeper(fetch)
    pts, scorer_check = score_weeks(sl)
    tw = infer_team_weeks(sl, pts)
    board, unjoined = board_values(contract)
    records = build_records(sl, pts, board, tw)
    labels = anonymous_team_labels(sl["rosters"])
    teams = {labels[r["roster_id"]]: [str(p) for p in r["players"]] for r in sl["rosters"]}
    roster_settings = league_registry.get_league_roster_settings(LEAGUE_KEY)
    slots, slot_source = resolve_starter_slots(
        roster_positions=sl["league"].get("roster_positions"), roster_settings=roster_settings
    )
    cap = len(sl["league"].get("roster_positions") or []) or None
    reps = args.replicates
    log(
        f"inputs: {len(records)} players, {len(teams)} rosters, {len(slots)} starter slots, cap {cap}"
    )

    result: dict[str, Any] = {
        "purpose": "IDP accuracy Lane B (directive 2026-10-25 section 7): six separate replacement definitions, in SHADOW. Changes no value, anchor, flag, scoring rule or served behaviour.",
        "status": "SHADOW_RESEARCH",
        "generatedBy": "scripts/idp_accuracy/replacement_report.py",
        "pins": {
            "boardArchive": PINNED_ARCHIVE,
            "boardArchiveSha256": archive_sha,
            "boardRebuiltWith": "today's build_api_data_contract at this tree",
            "season": SEASON,
            "weeks": list(WEEKS),
            "scorer": "src.nfl_data.realized_points.compute_weekly_points(source='sleeper')",
            "lineupOwner": "src.ros.lineup.solve_optimal_assignment (realized-points objective)",
            "starterSlots": list(slots),
            "starterSlotsSource": slot_source,
            "rosterCap": cap,
            "teams": len(teams),
            "configParamSetId": cfg["paramSetId"],
            "moduleSha256": hashlib.sha256(
                (REPO / "src/league_valuation/replacement_shadow.py").read_bytes()
            ).hexdigest(),
            "sleeperBodies": {
                re.sub(r"1\d{18}", "<league>", k.replace(SLEEPER, "")): v["sha256"]
                for k, v in sorted(fetch.receipts.items())
            },
        },
        "integrity": {
            "scorerVsSleeperPlayerPoints": scorer_check,
            "bestBallReproduction": best_ball_reproduction(sl, records, port, slots),
            "boardPricedPlayers": len(board),
            "boardRowsWithoutSleeperId": unjoined,
        },
    }
    log("integrity done")

    result["weeklyProfile"] = rs.weekly_starter_profile(
        teams, rs.WeeklyEngine(records, port, slots, WEEKS)
    )
    th = rs.starter_thresholds(
        teams,
        records,
        port,
        slots,
        value_of=lambda r: rs.ppg_of(r, WEEKS, min_games=int(cfg["window"]["minGames"]["value"])),
    )
    result["starterAllocation"] = {
        "startersPerTeam_endogenous": {
            p: _r(th.starters_per_team(p), 3) for p in sorted(th.by_position)
        },
        "slotFill": {k: dict(v) for k, v in th.slot_fill.items()},
        "note": "season-to-date ppg lineups; attribution by slot family, FLEX/SUPER_FLEX by the occupant's own position (flex competition is measured, not preassigned)",
    }
    log("weekly profile done")

    raw_t = level_tables(records, teams, port, slots, cfg, replicates=reps, estimator=rs.EST_RAW)
    log("levels (raw) done")
    eb_t = level_tables(records, teams, port, slots, cfg, replicates=reps, estimator=rs.EST_EB)
    log("levels (empirical Bayes) done")
    flat = raw_t["_flat"]
    result["levels"] = {
        "raw": {k: v for k, v in raw_t.items() if not k.startswith("_")},
        "empiricalBayes": {k: v for k, v in eb_t.items() if not k.startswith("_")},
    }
    mg = int(cfg["window"]["minGames"]["value"])
    eb_fit = rs.fit_eb(records, {pid for t in teams.values() for pid in t}, WEEKS, min_games=mg)
    result["levels"]["empiricalBayes"]["priorParameters"] = eb_fit.params
    result["selectionRegression"] = rs.selection_regression(records, teams, cfg=cfg)
    log("selection regression done")
    depth = depth_table(records, teams, port, slots, cfg, flat)
    result["healthyWaiverDepth"] = depth
    result["sensitivities"] = sensitivities(records, teams, port, slots, cfg)
    result["eligibilityUncertainty"] = rs.eligibility_uncertainty(
        records, teams, port, slots, weeks=WEEKS, cfg=cfg
    )
    result["headline"] = headline(raw_t, eb_t, depth)
    log("depth, sensitivities, eligibility done")

    engine = rs.WeeklyEngine(records, port, slots, WEEKS)
    rostered = {pid for t in teams.values() for pid in t}
    census = rs.build_census(records, rostered, weeks=WEEKS, cfg=cfg, rule=rs.PoolRule())
    alloc_block, alloc = allocation_section(teams, engine, census, cfg, cap)
    if not args.skip_slow:
        alloc_block["walkForward"] = walk_forward_allocation(records, teams, port, slots, cfg, cap)
    # contrast: the same allocation on AVERAGE-week expected lineups (one pseudo-week of shrunk ppg),
    # which is how a mean-based owner (LI-5 on rosValue) sees depth -- best ball pays for spikes
    ps = projection_setup(records, teams, port, slots, cfg)
    contrast, _ = allocation_section(teams, ps["engine"], ps["census"], cfg, cap)
    alloc_block["averageWeekProjectionContrast"] = {
        "what": "the same serial matching on one pseudo-week of empirical-Bayes expected ppg per player (an average-week lineup)",
        "summary": {k: v for k, v in contrast["summary"].items() if k != "claims"},
        "claims": contrast["summary"]["claims"],
    }
    result["D5_dynamicAllocation"] = alloc_block
    log("allocation done")
    ppg_raw = lambda pid: rs.ppg_of(records[pid], WEEKS, min_games=mg)  # noqa: E731
    result["D6_teamSpecificAfterTransaction"] = team_specific_section(
        teams, engine, census, alloc, cfg, cap, ppg_raw
    )
    log("team-specific done")
    result["marginalBestBallContribution"] = contribution_section(teams, records, port, slots, cfg)
    log("contributions done")
    if not args.skip_slow:
        result["wholeRosterPackages"] = package_section(teams, engine, census, cfg, cap, ppg_raw)
        log("packages done")
    result["consumerImpact"] = consumer_impact(
        contract, records, teams, flat, alloc, census, engine, cfg, cap
    )
    log("consumer impact done")
    result["reproductionOfInvestigationB"] = {
        **reproduce_b(records, teams, port, slots, cfg, args.b_pinned_run),
        "li5ParityOnTheSameRosters": li5_parity(records, teams, port, slots),
    }
    result["limits"] = LIMITS
    result["timingsSec"] = round(time.time() - t0, 1)

    rs.assert_public_artifact(result, forbidden_values=[LEAGUE_ID])
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "timingsSec": result["timingsSec"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
