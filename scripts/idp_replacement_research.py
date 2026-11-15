#!/usr/bin/env python3
"""IDP replacement anchors and league-specific IDP scoring.  RESEARCH ONLY.

Owner authorization: ``docs/owner/LOW_VALUE_ASSET_OWNER_DECISIONS_2026-10-20.md``
§3 ("Investigation B").  This script changes NO value, weight, vote, curve,
anchor or served behaviour.  Every alternative anchor below is computed in
SHADOW and fed to the canonical consumers' own pure functions; nothing is
written back.

It extends ``scripts/low_value_asset_idp_anomaly.py`` (the prior lane, whose
helpers it imports rather than re-deriving) with the seven review items:

1. injured / non-producing free agents in replacement anchors, and
   alternative anchor definitions per position (offense and IDP);
2. availability and eligibility of waiver replacements;
3. this league's IDP scoring card versus a tackle-heavy reference card;
4. defensive positional scarcity and roster requirements;
5. robustness of the value-vs-production correlation (bootstrap CIs, 2025
   full season, split-half reliability, per-source predictors);
6. whether the canonical IDP consensus reflects this league's scoring
   (card-alignment test, BDVM league-scored fundamental in memory);
7. how replacement anchors move each consumer (cut ladder / forced drops,
   Trade Finder Team Context factor, Perfect Draft surplus, FAAB V_repl,
   LI-5 scarcity), in shadow.

Inputs (read-only): today's board (newest tracked export archive, built with
today's code through ``shadow_replay.build_context``), the SERVED 2026-08-25
pre-season board, a today's-code replay of the 2026-08-25 archive (per-source
ranks only), Sleeper's public API (league card and settings, live rosters,
player directory, weekly stat dumps for 2026 and 2025, matchups for scorer
validation, transactions as aggregate counts), and nflverse via the canonical
``src.bdvm.baseline.fetch_and_build_baseline`` (BDVM in memory; no snapshot is
written).

Output: ``docs/valuation/evidence/idp_replacement_2026-10-20/idp_replacement.json``
— aggregates plus NFL player names for illustrative rows.  No Sleeper league /
user / roster / transaction / player id and no team or manager name
(``assert_aggregate_only``).
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.util
import json
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
OUT_DEFAULT = "docs/valuation/evidence/idp_replacement_2026-10-20/idp_replacement.json"
sys.path.insert(0, str(REPO))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


SR = _load("low_value_asset_shadow_replay")  # newest_board / build_context / P2 guard
LU = _load("low_value_asset_lineup_utility")  # Fetcher, preseason board, pos_group
IA = _load("low_value_asset_idp_anomaly")  # values_by_sid, is_healthy, archive_for

from scipy import stats as sps  # noqa: E402

from src.api import league_registry  # noqa: E402
from src.nfl_data.realized_points import compute_weekly_points  # noqa: E402
from src.ros.lineup import (  # noqa: E402
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    resolve_league_slot_demand,
    resolve_starter_slots,
    slot_eligible_positions,
    solve_optimal_assignment,
)

LEAGUE = "dynasty_main"
SEASON = 2026
PRIOR = 2025
PRIOR_WEEKS = tuple(range(1, 19))
SLEEPER = "https://api.sleeper.app/v1"
IDP = ("DL", "LB", "DB")
OFFENSE = ("QB", "RB", "WR", "TE")
POSITIONS = OFFENSE + IDP
MIN_GAMES = 3  # 2026 season-to-date ppg
MIN_GAMES_PRIOR = 8  # 2025 full-season ppg
BOOT = 1000
SEED = 20261020
TOP_N = 10
#: the card-alignment family: 3 board/production pairings x 4 groups (IDP, DL, LB, DB)
ALIGN_FAMILY_M = 12
BANDS = (("lt2000", 0, 2000), ("2000to3999", 2000, 4000), ("4000plus", 4000, 1e9))

#: Sleeper raw stat keys that score as TACKLES; every other ``idp_*`` key on the
#: card is big-play scoring (sacks, TFL, QB hits, passes defended, takeaways,
#: return yards, safeties, blocked kicks, defensive TDs).
TACKLE_KEYS = ("idp_tkl_solo", "idp_tkl_ast", "idp_tkl")

#: A conventional tackle-heavy IDP card, authored for this research as a
#: REFERENCE ONLY (it is no provider's card and no recommendation).  Offense
#: keys are taken unchanged from the league card, so only IDP scoring differs.
#: Price ratios: one pass defended = 0.67 solo tackles here, 3.98 on the league
#: card; one sack = 2.0 solos here, 2.2 on the league card.
REFERENCE_TACKLE_HEAVY = {
    "idp_tkl_solo": 1.5,
    "idp_tkl_ast": 0.75,
    "idp_tkl": 0.0,
    "idp_sack": 3.0,
    "idp_sack_yd": 0.0,
    "idp_tkl_loss": 1.0,
    "idp_qb_hit": 0.5,
    "idp_int": 3.0,
    "idp_int_ret_yd": 0.0,
    "idp_pass_def": 1.0,
    "idp_ff": 3.0,
    "idp_fum_rec": 2.0,
    "idp_fum_ret_yd": 0.0,
    "idp_def_td": 6.0,
    "idp_safe": 2.0,
    "idp_blk_kick": 2.0,
}

_r = IA._r
_median = IA._median


def _q(xs, p):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return float(np.percentile(xs, p))


# ── statistics ──────────────────────────────────────────────────────────


def _rho(x: np.ndarray, y: np.ndarray) -> float:
    rx = sps.rankdata(x)
    ry = sps.rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def spearman_ci(xs, ys, *, boot: int = BOOT, seed: int = SEED, min_n: int = 12) -> dict:
    """Spearman rho with a percentile-bootstrap 95% CI (resampling players)."""
    n = len(xs)
    if n < min_n:
        return {"n": n, "rho": None, "ci95": None}
    x, y = np.asarray(xs, float), np.asarray(ys, float)
    rho = _rho(x, y)
    rng = np.random.default_rng(seed)
    bs = []
    for _ in range(boot):
        idx = rng.integers(0, n, n)
        v = _rho(x[idx], y[idx])
        if v == v:
            bs.append(v)
    lo, hi = np.percentile(bs, [2.5, 97.5])
    return {"n": n, "rho": round(rho, 3), "ci95": [round(float(lo), 3), round(float(hi), 3)]}


def diff_ci(a: tuple, b: tuple, *, boot: int = BOOT, seed: int = SEED) -> dict | None:
    """rho(a) - rho(b) for two INDEPENDENT samples, bootstrap 95% CI."""
    (ax, ay), (bx, by) = a, b
    if len(ax) < 12 or len(bx) < 12:
        return None
    ax, ay, bx, by = (np.asarray(v, float) for v in (ax, ay, bx, by))
    rng = np.random.default_rng(seed + 7)
    d = []
    for _ in range(boot):
        i = rng.integers(0, len(ax), len(ax))
        j = rng.integers(0, len(bx), len(bx))
        v = _rho(ax[i], ay[i]) - _rho(bx[j], by[j])
        if v == v:
            d.append(v)
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {"diff": round(_rho(ax, ay) - _rho(bx, by), 3), "ci95": [round(lo, 3), round(hi, 3)]}


def _boot_p(d: list[float]) -> float:
    """Two-sided percentile-bootstrap p-value for H0: difference = 0."""
    arr = np.asarray(d, float)
    tail = min(int((arr <= 0).sum()), int((arr >= 0).sum()))
    return round(min(1.0, (2 * tail + 1) / (len(arr) + 1)), 4)


def paired_diff_ci(
    x, y1, y2, *, boot: int = BOOT, seed: int = SEED, family_m: int | None = None
) -> dict | None:
    """rho(x, y1) - rho(x, y2) on the SAME players, paired bootstrap 95% CI.

    Also returns a two-sided bootstrap p-value; with ``family_m`` the
    Bonferroni-adjusted interval (level 1 - 0.05 / m) for a family of m tests.
    """
    if len(x) < 12:
        return None
    x, y1, y2 = (np.asarray(v, float) for v in (x, y1, y2))
    rng = np.random.default_rng(seed + 11)
    d = []
    for _ in range(boot):
        i = rng.integers(0, len(x), len(x))
        v = _rho(x[i], y1[i]) - _rho(x[i], y2[i])
        if v == v:
            d.append(v)
    lo, hi = np.percentile(d, [2.5, 97.5])
    out = {
        "n": len(x),
        "diff": round(_rho(x, y1) - _rho(x, y2), 3),
        "ci95": [round(lo, 3), round(hi, 3)],
        "pBoot": _boot_p(d),
    }
    if family_m:
        a = 100 * 0.05 / family_m / 2
        blo, bhi = np.percentile(d, [a, 100 - a])
        out[f"ciBonferroni_m{family_m}"] = [round(float(blo), 3), round(float(bhi), 3)]
    return out


def paired_rho_diff_ci(x1, y1, x2, y2, *, boot: int = BOOT, seed: int = SEED) -> dict | None:
    """rho(x1, y1) - rho(x2, y2) on the SAME players (paired bootstrap 95% CI)."""
    if len(x1) < 12:
        return None
    x1, y1, x2, y2 = (np.asarray(v, float) for v in (x1, y1, x2, y2))
    rng = np.random.default_rng(seed + 13)
    d = []
    for _ in range(boot):
        i = rng.integers(0, len(x1), len(x1))
        v = _rho(x1[i], y1[i]) - _rho(x2[i], y2[i])
        if v == v:
            d.append(v)
    lo, hi = np.percentile(d, [2.5, 97.5])
    return {
        "n": len(x1),
        "diff": round(_rho(x1, y1) - _rho(x2, y2), 3),
        "ci95": [round(float(lo), 3), round(float(hi), 3)],
        "pBoot": _boot_p(d),
    }


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm step-down adjusted p-values (family-wise error control)."""
    order = sorted(pvals, key=lambda k: pvals[k])
    m = len(order)
    out, running = {}, 0.0
    for i, k in enumerate(order):
        running = max(running, min(1.0, (m - i) * pvals[k]))
        out[k] = round(running, 4)
    return out


def spearman_brown(r: float | None) -> float | None:
    if r is None or r <= -1:
        return None
    return round(2 * r / (1 + r), 3)


# ── source locations (traced at run time so the citations cannot drift) ─────


def is_healthy_strict(meta: dict) -> bool:
    """The RECOMMENDED health rule (doc §9, recommendation 1): an NFL team, an
    EXPLICIT ``status == "Active"``, and no unavailable injury designation.

    Differs from the shadow rule ``IA.is_healthy`` (prior lane) only in that a
    missing or unrecognised ``status`` is UNKNOWN and therefore excluded, never
    healthy.  Sleeper publishes no ``injury_status`` for an undesignated active
    player, so an absent injury designation on an explicitly Active player is
    not a missing status.
    """
    return (
        bool(meta.get("team"))
        and meta.get("status") == "Active"
        and meta.get("injury_status") not in IA.UNAVAILABLE_INJURY
    )


def locate(path: str, pattern: str) -> str:
    """``path:line`` of the first match of ``pattern`` in ``path``.

    The pattern is searched over the WHOLE file (``^`` still anchors a line
    start), so it can span lines: a call that a formatter wrapped after its
    opening parenthesis is found by a pattern that allows whitespace there
    (``\\(\\s*contract``).  The line reported is the one the match starts on.
    ``:?`` means no match, never "somewhere".
    """
    text = (REPO / path).read_text(encoding="utf-8")
    m = re.compile(pattern, re.MULTILINE).search(text)
    if m is None:
        return f"{path}:?"
    return f"{path}:{text.count(chr(10), 0, m.start()) + 1}"


CONSUMERS = (
    ("anchor owner — best unrostered rankDerivedValue per position",
     "src/draft/displacement.py", r"^def waiver_values_by_position"),
    ("ECC = max(0, base - waiver) x scarcity; unpriced base := waiver ('assumedWaiver')",
     "src/draft/displacement.py", r"^def effective_cut_cost"),
    ("cut ladder ordered by ECC (ties by name)", "src/draft/displacement.py",
     r"costed.sort\(key=lambda t: \(t\[0\], t\[1\]\)\)"),
    ("Trade Calculator / War Room / Finder / Angle capacity context builds the anchor",
     "src/trade/roster_capacity.py", r"waiver_values = waiver_values_by_position\(\s*contract"),
    ("forced drop release_cost = base x scarcity (unpriced: waiver x scarcity)",
     "src/trade/roster_capacity.py", r"release_cost=float\(rung.base_value\)"),
    ("forced_drop_cost (Team Context charge)", "src/trade/roster_capacity.py",
     r"^def forced_drop_cost"),
    ("Trade Finder Team Context factor -(cost/give) x _BOARD_EDGE_WEIGHT",
     "src/trade/finder.py", r"factor = -\(cost / max\(tc.give_model_total"),
    ("Analyze Trade objective value nets forced-drop release cost",
     "src/trade/analyze_trade.py", r"released = cap.get\(\"forcedDropReleaseCost\"\)"),
    ("Trade simulator (Trade Calculator Team Context) attaches capacity",
     "src/api/trade_simulator.py", r"capacity_context = build_capacity_context\("),
    ("War Room best-offers capacity charge", "server.py", r"cost, _basis = forced_drop_cost\(cap\)"),
    ("Perfect Draft roster context: positional anchor + position-agnostic FA ladder",
     "src/draft/context.py", r"waiver_values = waiver_values_by_position\(\s*contract"),
    ("Perfect Draft client surplus = max(0, v*tilt - waiver(pos))",
     "frontend/lib/perfect-draft.js", r"^export function surplusOverReplacement"),
    ("Perfect Draft client releaseCost = baseValue x scarcity", "frontend/lib/perfect-draft.js",
     r"^export function releaseCost"),
    ("Droppability (roster intelligence) cut ladder", "src/roster_intel/droppability.py",
     r"waiver_values = waiver_values_by_position\(\s*contract"),
    ("Perfect Waivers prices cuts with NO waiver anchor ({})", "src/trade/perfect_waivers.py",
     r"effective_cut_cost\(asset, \{\}, None\)"),
    ("FAAB V_repl (position-agnostic: format line blended with live pool's 12th best)",
     "src/trade/faab_engine.py", r"^def resolve_anchors"),
    ("FAAB route builds anchors", "server.py", r"faab_anchors = _faab_engine.resolve_anchors\("),
    ("LI-5 replacement tiers (waiver tier only when free_agents are passed)",
     "src/league_intel/replacement.py", r"^def compute_replacement_levels"),
    ("gameplan bundle calls LI-5 WITHOUT free_agents -> no waiver tier",
     "src/api/gameplan.py", r"replacement = compute_replacement_levels\(rep_teams, slots, endogenous"),
    ("scarcity multiplier reads waiver_scarcity only (inert 1.0 when None)",
     "src/draft/displacement.py", r"^def scarcity_multiplier"),
)  # fmt: skip


# ── main ────────────────────────────────────────────────────────────────


def main() -> int:  # noqa: C901, PLR0912, PLR0915 — one linear research pass
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--weeks", type=int, default=None, help="2026 weeks 1..N (default: scored)")
    ap.add_argument("--cache-dir", type=Path, default=Path("/tmp/idp_replacement_cache"))
    ap.add_argument("--no-bdvm", action="store_true", help="skip the in-memory BDVM run")
    ap.add_argument(
        "--roster-max-age-s",
        type=float,
        default=0,
        help="reuse cached live rosters younger than this (default 0: always refetch); "
        "set it to reproduce a run against the same roster snapshot",
    )
    args = ap.parse_args()
    t0 = time.time()

    # ── board (today's code, exactly as the prior lanes built it) ─────────
    zpath, member, blob, raw = SR.newest_board()
    ctx = SR.build_context(raw)
    contract, rows = ctx["contract"], ctx["rows"]
    sl = contract.get("sleeper") or {}
    name_to_id = {str(k): str(v) for k, v in (sl.get("playerIds") or {}).items()}

    def sid_of_row(r: dict) -> str | None:
        sid = r.get("playerId")
        if sid:
            return str(sid)
        for f in ("displayName", "canonicalName", "legacyRef"):
            s = name_to_id.get(str(r.get(f) or ""))
            if s:
                return s
        return None

    board: dict[str, dict] = {}
    for r in contract.get("playersArray") or []:
        if str(r.get("assetClass") or "") == "pick":
            continue
        v = r.get("rankDerivedValue")
        sid = sid_of_row(r)
        if not sid or not isinstance(v, (int, float)) or v <= 0:
            continue
        board[sid] = {
            "name": r.get("displayName"),
            "value": float(v),
            "pos": (r.get("position") or "").upper(),
            "sourceRanks": dict(r.get("sourceRanks") or {}),
            "rookie": bool(r.get("rookie")),
        }
    name_rows = {b["name"]: b for b in board.values()}

    # ── Sleeper (public; cached outside the repo) ─────────────────────────
    fetch = LU.Fetcher(args.cache_dir)
    league_id = league_registry.get_sleeper_league_id(LEAGUE)
    league = fetch.get(f"{SLEEPER}/league/{league_id}", max_age_s=6 * 3600)
    settings = league.get("settings") or {}
    card = {k: float(v) for k, v in (league.get("scoring_settings") or {}).items()
            if isinstance(v, (int, float))}  # fmt: skip
    ref_card = {**card, **REFERENCE_TACKLE_HEAVY}
    cards = {"league": card, "tackleHeavyRef": ref_card}
    roster_settings = league_registry.get_league_roster_settings(LEAGUE)
    slots, slot_src = resolve_starter_slots(
        roster_positions=league.get("roster_positions"), roster_settings=roster_settings
    )
    weeks_n = args.weeks or int(settings.get("last_scored_leg") or 6)
    weeks = list(range(1, weeks_n + 1))
    pdb = fetch.get(f"{SLEEPER}/players/nfl", max_age_s=7 * 86400)
    rosters = fetch.get(f"{SLEEPER}/league/{league_id}/rosters", max_age_s=args.roster_max_age_s)
    matchups = {w: fetch.get(f"{SLEEPER}/league/{league_id}/matchups/{w}") for w in weeks}
    stats = {
        SEASON: {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{SEASON}/{w}") for w in weeks},
        PRIOR: {w: fetch.get(f"{SLEEPER}/stats/nfl/regular/{PRIOR}/{w}") for w in PRIOR_WEEKS},
    }
    txns = {
        w: fetch.get(f"{SLEEPER}/league/{league_id}/transactions/{w}", max_age_s=6 * 3600)
        for w in range(1, weeks_n + 2)
    }
    live_ids = {str(p) for r in rosters for p in (r.get("players") or [])}
    teams_n = len(rosters)
    roster_cap = len(league.get("roster_positions") or [])

    def spos(sid: str) -> str:
        return LU.pos_group((pdb.get(sid) or {}).get("position"))

    def meta(sid: str) -> dict:
        return pdb.get(sid) or {}

    healthy = {sid: IA.is_healthy(meta(sid)) for sid in set(board) | live_ids}
    healthy_strict = {sid: is_healthy_strict(meta(sid)) for sid in set(board) | live_ids}

    # ── league-scored production under both cards, 2026 YTD and 2025 ──────
    pts: dict[tuple[int, str], dict[str, dict[int, float]]] = defaultdict(lambda: defaultdict(dict))
    comp: dict[int, dict[str, Counter]] = {
        SEASON: defaultdict(Counter),
        PRIOR: defaultdict(Counter),
    }
    raw_idp: dict[int, dict[str, Counter]] = {
        SEASON: defaultdict(Counter),
        PRIOR: defaultdict(Counter),
    }
    for season, by_week in stats.items():
        for w, dump in by_week.items():
            for sid, line in (dump or {}).items():
                sid = str(sid)
                if float(line.get("gp") or 0) <= 0:
                    continue
                pos = spos(sid)
                row = {**line, "player_id": sid, "season": season, "week": w}
                for cname, cdict in cards.items():
                    res = compute_weekly_points(row, cdict, position=pos, source="sleeper")
                    if res is not None:
                        pts[(season, cname)][sid][w] = float(res.fantasy_points)
                if pos in IDP:
                    for k, v in line.items():
                        if k.startswith("idp_") and isinstance(v, (int, float)):
                            raw_idp[season][sid][k] += float(v)
                            pv = card.get(k, 0.0) * float(v)
                            comp[season][sid]["tackle" if k in TACKLE_KEYS else "bigPlay"] += pv
    scorer_diffs = []
    for w in weeks:
        for m in matchups[w] or []:
            for sid, hp in (m.get("players_points") or {}).items():
                got = pts[(SEASON, "league")].get(str(sid), {}).get(w)
                if got is not None:
                    scorer_diffs.append(abs(got - float(hp)))

    def ppg(season: int, sid: str, cname: str = "league", min_g: int | None = None):
        wk = pts[(season, cname)].get(sid) or {}
        mg = min_g if min_g is not None else (MIN_GAMES if season == SEASON else MIN_GAMES_PRIOR)
        if len(wk) < mg:
            return None
        return sum(wk.values()) / len(wk)

    def games(season: int, sid: str) -> int:
        return len(pts[(season, "league")].get(sid) or {})

    def tackle_share(season: int, sid: str):
        c = comp[season].get(sid)
        tot = (c or {}).get("tackle", 0) + (c or {}).get("bigPlay", 0)
        return c["tackle"] / tot if c and tot > 0 else None

    # ── production-optimal lineups on live rosters (season-to-date points) ─
    prod_starters: dict[str, list[str]] = defaultdict(list)
    for r in rosters:
        pool = []
        for sid in (str(p) for p in (r.get("players") or [])):
            m = meta(sid)
            fps = tuple(str(p).upper() for p in (m.get("fantasy_positions") or ()) if p)
            pool.append(RosterPlayer(player_id=sid, canonical_name=sid,
                                     position=str(m.get("position") or "").upper(),
                                     ros_value=float(sum((pts[(SEASON, "league")].get(sid) or {}).values())),
                                     fantasy_positions=fps))  # fmt: skip
        for p in solve_optimal_assignment(
            pool, slots, objective=OBJECTIVE_REALIZED_POINTS
        ).values():
            if spos(p.player_id) in POSITIONS:
                prod_starters[spos(p.player_id)].append(p.player_id)
    prod_line = {  # P25 of production-optimal starters' ppg: "a solid starter"
        pos: _q([ppg(SEASON, s) for s in prod_starters[pos]], 25) for pos in POSITIONS
    }
    prod_floor = {  # P10 of production-optimal starters' ppg: "startable at all" (A4 bar)
        pos: _q([ppg(SEASON, s) for s in prod_starters[pos]], 10) for pos in POSITIONS
    }
    prod_median = {pos: _q([ppg(SEASON, s) for s in prod_starters[pos]], 50) for pos in POSITIONS}

    # dropped this season (any completed transaction), aggregate use only
    dropped_season: Counter = Counter()
    last_ts = 0
    drop_ts: dict[str, int] = {}
    for _w, lst in txns.items():
        for t in lst or []:
            if t.get("status") != "complete":
                continue
            ts = int(t.get("status_updated") or t.get("created") or 0)
            last_ts = max(last_ts, ts)
            for sid in (t.get("drops") or {}).keys():
                dropped_season[str(sid)] += 1
                drop_ts[str(sid)] = max(drop_ts.get(str(sid), 0), ts)

    # ════════════════════════════════════════════════════════════════════
    # Q1 — anchors: who sets them, and alternative definitions in shadow
    # ════════════════════════════════════════════════════════════════════
    fa_pool: dict[str, list[dict]] = defaultdict(list)
    for sid, b in board.items():
        if sid in live_ids or b["pos"] not in POSITIONS:
            continue
        fa_pool[b["pos"]].append(
            {
                "sid": sid,
                "name": b["name"],
                "value": b["value"],
                "healthy": healthy.get(sid, False),
                "healthyStrict": healthy_strict.get(sid, False),
                "games": games(SEASON, sid),
                "ppg": ppg(SEASON, sid),
                "rookie": meta(sid).get("years_exp") == 0,
                "nflTeam": bool(meta(sid).get("team")),
                "droppedThisSeason": dropped_season.get(sid, 0) > 0,
            }
        )
    for lst in fa_pool.values():
        lst.sort(key=lambda d: -d["value"])

    def producing(d: dict, pos: str, bar: dict | None = None) -> bool:
        line = (bar if bar is not None else prod_floor).get(pos)
        return bool(d["healthy"] and d["ppg"] is not None and line is not None and d["ppg"] >= line)

    rostered_by_pos: dict[str, list[str]] = defaultdict(list)
    for sid in live_ids:
        b = board.get(sid)
        if b and b["pos"] in POSITIONS:
            rostered_by_pos[b["pos"]].append(sid)

    served = ctx["anchors"]["byPosition"]

    def pick(lst, k=1):
        return lst[k - 1] if len(lst) >= k else None

    anchor_defs: dict[str, dict[str, Any]] = {}
    for pos in POSITIONS:
        pool = fa_pool.get(pos) or []
        hp = [d for d in pool if d["healthy"]]
        hps = [d for d in pool if d["healthyStrict"]]
        prodq = [d for d in pool if producing(d, pos)]
        prodq25 = [d for d in pool if producing(d, pos, prod_line)]
        top3 = pool[:3]
        top3h = hp[:3]
        top3hs = hps[:3]
        # production-equivalent (diagnostic): the board's median value for
        # rostered players producing at the wire's 3rd-best healthy rate
        wire_ppgs = sorted((d["ppg"] for d in hp if d["ppg"] is not None), reverse=True)
        ref_ppg = wire_ppgs[2] if len(wire_ppgs) >= 3 else None
        eq_vals = []
        if ref_ppg:
            for sid in rostered_by_pos[pos]:
                p = ppg(SEASON, sid)
                if p is not None and 0.85 * ref_ppg <= p <= 1.15 * ref_ppg:
                    eq_vals.append(board[sid]["value"])
        defs = {
            "A0_current_served": (served[pos]["waiverBestUnrostered_PRIMARY"], None),
            "A0_current_liveRosters": (pick(pool)["value"] if pool else None, pick(pool)),
            "A1_bestHealthy": (pick(hp)["value"] if hp else None, pick(hp)),
            "A1s_bestHealthy_strictRule": (pick(hps)["value"] if hps else None, pick(hps)),
            "A2_3rdBestHealthy": (pick(hp, 3)["value"] if len(hp) >= 3 else None, pick(hp, 3)),
            "A2b_6thBestHealthy": (pick(hp, 6)["value"] if len(hp) >= 6 else None, pick(hp, 6)),
            "A3_li5BandedTop3_all": (statistics.fmean(d["value"] for d in top3) if top3 else None, None),
            "A3h_li5BandedTop3_healthy": (
                statistics.fmean(d["value"] for d in top3h) if top3h else None, None),
            "A3hs_li5BandedTop3_healthyStrictRule": (
                statistics.fmean(d["value"] for d in top3hs) if top3hs else None, None),
            "A4_bestProductionQualified": (pick(prodq)["value"] if prodq else None, pick(prodq)),
            "A4b_bestProductionQualified_P25bar": (
                pick(prodq25)["value"] if prodq25 else None, pick(prodq25)),
            "A5_li5_bestBallStarter_rosters": (served[pos]["li5_bestBallStarter"], None),
            "A5b_li5_starterMedianMarginal_rosters": (served[pos]["li5_starterMedianMarginal"], None),
            "D_productionEquivalentValue_diagnostic": (
                statistics.median(eq_vals) if len(eq_vals) >= 5 else None, None),
        }  # fmt: skip
        anchor_defs[pos] = {k: v for k, v in defs.items()}

    lowest_canon = ctx["lowest_starter"]

    def anchor_effects(pos: str, a: float | None) -> dict | None:
        if a is None:
            return None
        canon = [name_rows[n]["value"] for n in ctx["starters"]
                 if n in name_rows and name_rows[n]["pos"] == pos]  # fmt: skip
        prodv = [board[s]["value"] for s in prod_starters[pos] if s in board]
        ros = [board[s]["value"] for s in rostered_by_pos[pos]]
        return {
            "canonicalStartersValuedBelowAnchor": f"{sum(v < a for v in canon)}/{len(canon)}",
            "productionStartersValuedBelowAnchor": f"{sum(v < a for v in prodv)}/{len(prodv)}",
            "rosteredValuedAboveAnchor": f"{sum(v > a for v in ros)}/{len(ros)}",
            "rosteredSurplusOverAnchorSum": _r(sum(max(0.0, v - a) for v in ros)),
            "anchorAboveLowestCanonicalStarter": (
                a > lowest_canon[pos] if lowest_canon.get(pos) is not None else None),
        }  # fmt: skip

    def who(d: dict | None) -> dict | None:
        if not d:
            return None
        m = meta(d["sid"])
        return {
            "name": d["name"],
            "value": _r(d["value"]),
            "injuryStatus": m.get("injury_status"),
            "status": m.get("status"),
            "rookie": d["rookie"],
            f"wk1_{weeks_n}Games": d["games"],
            f"wk1_{weeks_n}Ppg": _r(d["ppg"], 2),
        }

    q1_anchors = {
        pos: {
            name: {"value": _r(v), "setBy": who(d), **(anchor_effects(pos, v) or {})}
            for name, (v, d) in anchor_defs[pos].items()
        }
        for pos in POSITIONS
    }

    def _top_ppg_fa(pool: list[dict]) -> dict:
        """Value rank (among all board-priced unrostered at the position) of the
        healthy free agent with the HIGHEST season-to-date ppg."""
        cand = [(d["ppg"], -i) for i, d in enumerate(pool) if d["healthy"] and d["ppg"] is not None]
        if not cand:
            return {"valueRankOfTopPpgHealthyFA": None}
        p, neg_i = max(cand)
        return {
            "valueRankOfTopPpgHealthyFA": -neg_i + 1,
            "topPpgHealthyFA_ppg": _r(p, 2),
            "unrosteredBoardPricedAtPosition": len(pool),
        }

    q1_census = {}
    for pos in POSITIONS:
        top = (fa_pool.get(pos) or [])[:TOP_N]
        q1_census[pos] = {
            "top10UnrosteredByValue": len(top),
            "injuredOrInactiveNow": sum(not d["healthy"] for d in top),
            "fewerThanMinGamesPlayed": sum(d["games"] < MIN_GAMES for d in top),
            "rookies": sum(d["rookie"] for d in top),
            "droppedByAManagerThisSeason": sum(d["droppedThisSeason"] for d in top),
            "healthyAndProductionQualified": sum(producing(d, pos) for d in top),
            "medianPpgWhenPlayed": _r(_median([d["ppg"] for d in top]), 2),
            "productionFloorPpg_P10ofProductionStarters": _r(prod_floor.get(pos), 2),
            "valueRankOfBestProducingHealthyFA": next(
                (i + 1 for i, d in enumerate(fa_pool.get(pos) or []) if producing(d, pos)), None),
            **_top_ppg_fa(fa_pool.get(pos) or []),
            "healthyLooseButNotStrict": sum(
                1 for d in fa_pool.get(pos) or [] if d["healthy"] and not d["healthyStrict"]),
            "healthyLooseButNotStrict_statuses": dict(Counter(
                str(meta(d["sid"]).get("status")) for d in fa_pool.get(pos) or []
                if d["healthy"] and not d["healthyStrict"])),
        }  # fmt: skip
    # spearman(value, ppg) among unrostered (does value order the wire?)
    q1_wire_order = {}
    for pos in POSITIONS:
        pr = [(d["value"], d["ppg"]) for d in fa_pool.get(pos) or [] if d["ppg"] is not None]
        q1_wire_order[pos] = spearman_ci([a for a, _ in pr], [b for _, b in pr])

    # ════════════════════════════════════════════════════════════════════
    # Q2 — availability and eligibility of waiver replacements
    # ════════════════════════════════════════════════════════════════════
    rule_keys = ("best_ball", "waiver_type", "waiver_budget", "daily_waivers", "waiver_clear_days",
                 "reserve_slots", "taxi_slots", "reserve_allow_out", "reserve_allow_doubtful",
                 "reserve_allow_sus", "reserve_allow_na", "trade_deadline", "bench_lock",
                 "playoff_week_start", "last_scored_leg")  # fmt: skip
    sizes = sorted(len(r.get("players") or []) for r in rosters)
    q2_pool = {}
    for pos in POSITIONS:
        pool = fa_pool.get(pos) or []
        status_mix = Counter(
            (meta(d["sid"]).get("injury_status") or ("healthy" if d["healthy"] else
             meta(d["sid"]).get("status") or "unknown")) for d in pool
        )  # fmt: skip
        multi = Counter(
            "/".join(
                sorted(str(p).upper() for p in (meta(d["sid"]).get("fantasy_positions") or []))
            )
            for d in pool
            if len(meta(d["sid"]).get("fantasy_positions") or []) > 1
        )
        q2_pool[pos] = {
            "unrosteredBoardPriced": len(pool),
            "withNflTeam": sum(d["nflTeam"] for d in pool),
            "healthyNow": sum(d["healthy"] for d in pool),
            "statusMix": dict(status_mix.most_common()),
            "multiPositionEligible": dict(multi),
            "boardPositionDiffersFromSleeper": sum(spos(d["sid"]) != pos for d in pool),
            "droppedWithinWaiverClearWindow": sum(
                1
                for d in pool
                if drop_ts.get(d["sid"], 0)
                >= last_ts - int(settings.get("waiver_clear_days") or 0) * 86400000
            ),  # fmt: skip
            "producingHealthyFreeAgents": sum(producing(d, pos) for d in pool),
        }
    q2 = {
        "leagueRules": {k: settings.get(k) for k in rule_keys},
        "rosterSlotsTotal": roster_cap,
        "liveRosterSizes": sizes,
        "teamsAtOrOverCap": sum(s >= roster_cap for s in sizes),
        "liveTaxiPlayers": sum(len(r.get("taxi") or []) for r in rosters),
        "liveReservePlayers": sum(len(r.get("reserve") or []) for r in rosters),
        "slotEligibility": {s: sorted(slot_eligible_positions(s)) for s in sorted(set(slots))},
        "freeAgentPoolByPosition": q2_pool,
        "reading": "best ball with no IR and no taxi: an injured player occupies one of 58 "
        "spots and scores 0 for as long as he is out; with daily waivers and a "
        f"{settings.get('waiver_clear_days')}-day clear window almost every unrostered player is "
        "a free agent at any moment",
    }

    # ════════════════════════════════════════════════════════════════════
    # Q3 — the league's IDP scoring card vs a tackle-heavy reference
    # ════════════════════════════════════════════════════════════════════
    idp_card = {k: v for k, v in sorted(card.items()) if k.startswith("idp_") and v}
    # The league's demand comes from the one resolver (C2-U1 single-owner gate).
    league_demand = resolve_league_slot_demand(
        roster_positions=league.get("roster_positions"), roster_settings=roster_settings
    )
    assert tuple(league_demand.slots) == tuple(slots), "demand resolved different slots"
    sd = league_demand.demand
    even = {p: float(v) for p, v in (sd.even_split or {}).items()}
    n_start = {p: max(1, round(teams_n * even.get(p, 0))) for p in POSITIONS}

    def top_by(season, pos, cname, n):
        xs = []
        for sid in pts[(season, cname)]:
            if spos(sid) != pos:
                continue
            p = ppg(season, sid, cname)
            if p is not None:
                xs.append((p, sid))
        xs.sort(reverse=True)
        return xs[:n]

    q3_pos = {}
    for season in (SEASON, PRIOR):
        for pos in POSITIONS:
            n = n_start[pos]
            out = {"startingPoolN": n}
            for cname in cards:
                top = top_by(season, pos, cname, n)
                nxt = top_by(season, pos, cname, 2 * n)[n:]
                out[cname] = {
                    "meanPpgStartingPool": _r(statistics.fmean(p for p, _ in top), 2) if top else None,
                    "ppgAtStarterLine": _r(top[-1][0], 2) if top else None,
                    "ppgAt2xStarterLine": _r(nxt[-1][0], 2) if nxt else None,
                    "replacementDropRatio_2xOver1x": _r(nxt[-1][0] / top[-1][0], 3)
                    if top and nxt and top[-1][0] > 0 else None,
                }  # fmt: skip
            if pos in IDP:
                top = top_by(season, pos, "league", n)
                ts = [tackle_share(season, s) for _, s in top]
                out["medianTackleShareOfPointsStartingPool_league"] = _r(_median(ts), 3)
                sids = [s for s in pts[(season, "league")] if spos(s) == pos
                        and ppg(season, s) is not None]  # fmt: skip
                out["spearmanLeagueVsReferenceCardPpg"] = spearman_ci(
                    [ppg(season, s) for s in sids], [ppg(season, s, "tackleHeavyRef") for s in sids]
                )
                topn = {s for _, s in top_by(season, pos, "league", 2 * n)}
                topn |= {s for _, s in top_by(season, pos, "tackleHeavyRef", 2 * n)}
                topn = sorted(topn)  # deterministic bootstrap order
                out["spearmanLeagueVsReferenceCardPpg_top2xStartersEitherCard"] = spearman_ci(
                    [ppg(season, s) for s in topn], [ppg(season, s, "tackleHeavyRef") for s in topn]
                )
                # who gains under THIS card relative to the reference
                lr = {s: i for i, (_, s) in enumerate(top_by(season, pos, "league", 10**6))}
                rr = {s: i for i, (_, s) in enumerate(top_by(season, pos, "tackleHeavyRef", 10**6))}
                common = [s for s in lr if s in rr and min(lr[s], rr[s]) < 2 * n]
                gain = sorted(common, key=lambda s: lr[s] - rr[s])

                def prof(s):
                    c = raw_idp[season][s]
                    g = games(season, s) or 1
                    return {
                        "name": meta(s).get("full_name"),
                        "leagueRank": lr[s] + 1,
                        "refRank": rr[s] + 1,
                        "tackleShare": _r(tackle_share(season, s), 2),
                        "perGame": {
                            k.replace("idp_", ""): _r(c.get(k, 0) / g, 2)
                            for k in (
                                "idp_tkl_solo",
                                "idp_tkl_ast",
                                "idp_sack",
                                "idp_tkl_loss",
                                "idp_pass_def",
                                "idp_int",
                            )
                        },
                    }

                out["topGainersUnderLeagueCard"] = [prof(s) for s in gain[:5]]
                out["topLosersUnderLeagueCard"] = [prof(s) for s in gain[::-1][:5]]
            q3_pos[f"{season}:{pos}"] = out
    # tackle-share tertile profiles: do high-tackle players score worse here?
    q3_profiles = {}
    for pos in IDP:
        sids = [s for s in pts[(PRIOR, "league")] if spos(s) == pos and ppg(PRIOR, s) is not None]
        sids = sorted(sids, key=lambda s: -ppg(PRIOR, s))[: 2 * n_start[pos]]
        ts = sorted((tackle_share(PRIOR, s), s) for s in sids if tackle_share(PRIOR, s) is not None)
        k = len(ts) // 3
        groups = {
            "lowTackleShare": ts[:k],
            "midTackleShare": ts[k : 2 * k],
            "highTackleShare": ts[2 * k :],
        }
        q3_profiles[pos] = {
            g: {"n": len(v), "tackleShareRange": [_r(v[0][0], 2), _r(v[-1][0], 2)] if v else None,
                "medianPpgLeague": _r(_median([ppg(PRIOR, s) for _, s in v]), 2),
                "medianPpgReference": _r(_median([ppg(PRIOR, s, "tackleHeavyRef") for _, s in v]), 2)}
            for g, v in groups.items()
        }  # fmt: skip

    # ════════════════════════════════════════════════════════════════════
    # Q4 — positional scarcity and roster requirements
    # ════════════════════════════════════════════════════════════════════
    q4_depth = {}
    for pos in POSITIONS:
        hp = [d for d in fa_pool.get(pos) or [] if d["healthy"] and d["ppg"] is not None]
        hp_ppg = sorted((d["ppg"] for d in hp), reverse=True)
        med = prod_median.get(pos)
        q4_depth[pos] = {
            "productionOptimalStarters": len(prod_starters[pos]),
            "canonicalValueStarters": sum(1 for n in ctx["starters"]
                                          if n in name_rows and name_rows[n]["pos"] == pos),
            "productionStarterPpgMedian": _r(med, 2),
            "productionStarterPpgP25": _r(prod_line.get(pos), 2),
            "healthyFreeAgentsAtOrAboveP25StarterPpg": sum(p >= (prod_line.get(pos) or 1e9) for p in hp_ppg),
            "healthyFreeAgentsAtOrAboveMedianStarterPpg": sum(p >= (med or 1e9) for p in hp_ppg),
            "bestHealthyFreeAgentPpg": _r(hp_ppg[0], 2) if hp_ppg else None,
            "thirdBestHealthyFreeAgentPpg": _r(hp_ppg[2], 2) if len(hp_ppg) >= 3 else None,
            "thirdBestFaOverMedianStarter": _r(hp_ppg[2] / med, 3) if len(hp_ppg) >= 3 and med else None,
        }  # fmt: skip
    q4_wire_all = {}
    for pos in POSITIONS:
        fa = []
        for sid in pts[(SEASON, "league")]:
            if sid in live_ids or spos(sid) != pos or not IA.is_healthy(meta(sid)):
                continue
            p = ppg(SEASON, sid)
            if p is not None:
                fa.append((p, sid in board))
        fa.sort(reverse=True)
        med, p25, p10 = prod_median.get(pos), prod_line.get(pos), prod_floor.get(pos)
        q4_wire_all[pos] = {
            "healthyUnrosteredWithMinGames": len(fa),
            "atOrAboveP10StarterPpg": sum(p >= (p10 or 1e9) for p, _ in fa),
            "atOrAboveP25StarterPpg": sum(p >= (p25 or 1e9) for p, _ in fa),
            "atOrAboveMedianStarterPpg": sum(p >= (med or 1e9) for p, _ in fa),
            "ofP10QualifiedNotPricedByBoard": sum(1 for p, b in fa if p >= (p10 or 1e9) and not b),
            "bestPpg": _r(fa[0][0], 2) if fa else None,
            "thirdBestPpg": _r(fa[2][0], 2) if len(fa) >= 3 else None,
            "thirdBestOverMedianStarter": _r(fa[2][0] / med, 3) if len(fa) >= 3 and med else None,
        }
    q4 = {
        "starterSlots": slots,
        "slotSource": slot_src,
        "slotDemand": {
            "dedicated": dict(sd.dedicated),
            "flexCapacity": dict(sd.flex_capacity),
            "evenSplit": even,
            "evenSplitIsApproximation": sd.even_split_is_approximation,
        },
        "idpFlexSlots": sum(1 for s in slots if str(s).upper() == "IDP_FLEX"),
        "leagueStartersByPosition_teamsTimesEvenSplit": n_start,
        "rosterCap": roster_cap,
        "startersPerTeam": len(slots),
        "benchSpotsPerTeam": roster_cap - len(slots),
        "wireDepthSeasonToDate_hindsight_boardPricedOnly": q4_depth,
        "wireDepthSeasonToDate_hindsight_allUnrostered": q4_wire_all,
        "formatScarcity_byCardAndSeason": {
            k: {c: v[c]["replacementDropRatio_2xOver1x"] for c in cards} for k, v in q3_pos.items()
        },
    }

    # ════════════════════════════════════════════════════════════════════
    # Q5 — robustness of value vs league-scored production
    # ════════════════════════════════════════════════════════════════════
    pre_vals, pre_meta = LU.preseason_values()
    today_vals = {s: b["value"] for s, b in board.items()}
    deep_k = {p: 2 * n_start[p] for p in POSITIONS}  # comparable depth per position

    def pairs(
        vals: dict, season: int, positions, *, cname="league", which="all", band=None, deep=False
    ):
        xs, ys, ids = [], [], []
        for sid, v in vals.items():
            if v is None or spos(sid) not in positions:
                continue
            if which == "rostered" and sid not in live_ids:
                continue
            if band and not band[0] <= v < band[1]:
                continue
            p = ppg(season, sid, cname)
            if p is None:
                continue
            xs.append(v)
            ys.append(p)
            ids.append(sid)
        if deep:  # top deep_k[pos] by value within each position
            keep = set()
            for pos in positions:
                cand = sorted((v, s) for v, s in zip(xs, ids) if spos(s) == pos)[::-1]
                keep |= {s for _, s in cand[: deep_k[pos]]}
            sel = [i for i, s in enumerate(ids) if s in keep]
            xs, ys, ids = [xs[i] for i in sel], [ys[i] for i in sel], [ids[i] for i in sel]
        return xs, ys, ids

    groups = {"offense": OFFENSE, "idp": IDP, **{p: (p,) for p in POSITIONS}}
    q5: dict[str, Any] = {}
    for label, vals, season in (
        ("valueToday_vs_ppg2026ytd", today_vals, SEASON),
        ("valuePreseasonServed_vs_ppg2026ytd", pre_vals, SEASON),
        ("valuePreseasonServed_vs_ppg2025", pre_vals, PRIOR),
    ):
        block = {}
        for g, ps in groups.items():
            block[g] = {
                "all": spearman_ci(*pairs(vals, season, ps)[:2]),
                "rostered": spearman_ci(*pairs(vals, season, ps, which="rostered")[:2]),
                "deepPool_top2xStarters": spearman_ci(*pairs(vals, season, ps, deep=True)[:2]),
                **{f"band_{b}": spearman_ci(*pairs(vals, season, ps, band=(lo, hi))[:2])
                   for b, lo, hi in BANDS},
            }  # fmt: skip
        block["offenseMinusIdp_all"] = diff_ci(
            pairs(vals, season, OFFENSE)[:2], pairs(vals, season, IDP)[:2]
        )
        block["offenseMinusIdp_deepPool"] = diff_ci(
            pairs(vals, season, OFFENSE, deep=True)[:2], pairs(vals, season, IDP, deep=True)[:2]
        )
        q5[label] = block

    # production stability and reliability (the ceiling any value can reach)
    stab = {}
    for g, ps in groups.items():
        xs, ys = [], []
        for sid in pts[(SEASON, "league")]:
            if spos(sid) not in ps:
                continue
            a, b = ppg(PRIOR, sid), ppg(SEASON, sid)
            if a is not None and b is not None:
                xs.append(a)
                ys.append(b)
        half = {}
        for season, wk_all, min_half in ((SEASON, weeks, 2), (PRIOR, list(PRIOR_WEEKS), 4)):
            h1x, h2x = [], []
            for sid, wk in pts[(season, "league")].items():
                if spos(sid) not in ps:
                    continue
                o = [v for w, v in wk.items() if w % 2 == 1]
                e = [v for w, v in wk.items() if w % 2 == 0]
                if len(o) >= min_half and len(e) >= min_half:
                    h1x.append(statistics.fmean(o))
                    h2x.append(statistics.fmean(e))
            r = spearman_ci(h1x, h2x)
            half[str(season)] = {**r, "spearmanBrownFullPeriod": spearman_brown(r["rho"])}
        rel26 = half[str(SEASON)]["spearmanBrownFullPeriod"]
        obs = q5["valuePreseasonServed_vs_ppg2026ytd"][g]["all"]["rho"]
        stab[g] = {
            "ppg2025_vs_ppg2026ytd": spearman_ci(xs, ys),
            "splitHalfOddEvenWeeks": half,
            "valuePreseason_vs_ppg2026_disattenuated": _r(obs / rel26**0.5, 3)
            if obs is not None and rel26 and rel26 > 0 else None,
        }  # fmt: skip
    q5["productionStabilityAndReliability"] = stab
    same_set = {}
    for g, ps in groups.items():
        v, a, y = [], [], []
        for sid, pv in pre_vals.items():
            if pv is None or spos(sid) not in ps:
                continue
            p25, p26 = ppg(PRIOR, sid), ppg(SEASON, sid)
            if p25 is not None and p26 is not None:
                v.append(pv)
                a.append(p25)
                y.append(p26)
        same_set[g] = {
            "valuePreseason_vs_ppg2026": spearman_ci(v, y),
            "ppg2025_vs_ppg2026": spearman_ci(a, y),
            "ppg2025MinusValue_paired": paired_diff_ci(y, a, v),
            "note": "same players: priced pre-season, >= 8 games in 2025 and >= 3 in 2026",
        }
    q5["predictorsOfPpg2026_sameSet"] = same_set

    # value vs league card vs reference card (Q6's alignment test)
    align = {}
    for label, vals, season in (("today_2026ytd", today_vals, SEASON),
                                ("preseason_2025", pre_vals, PRIOR),
                                ("preseason_2026ytd", pre_vals, SEASON)):  # fmt: skip
        for g in ("idp", *IDP):
            xs, y1, y2 = [], [], []
            for sid, v in vals.items():
                if v is None or spos(sid) not in groups[g]:
                    continue
                a, b = ppg(season, sid), ppg(season, sid, "tackleHeavyRef")
                if a is not None and b is not None:
                    xs.append(v)
                    y1.append(a)
                    y2.append(b)
            align[f"{label}:{g}"] = {
                "rhoVsLeagueCard": spearman_ci(xs, y1),
                "rhoVsTackleHeavyRef": spearman_ci(xs, y2),
                "leagueMinusRef_paired": paired_diff_ci(xs, y1, y2, family_m=ALIGN_FAMILY_M),
            }
    pv = {k: v["leagueMinusRef_paired"]["pBoot"] for k, v in align.items()
          if v["leagueMinusRef_paired"]}  # fmt: skip
    holm_p = holm(pv)
    bkey = f"ciBonferroni_m{ALIGN_FAMILY_M}"
    align_mult = {
        "familySize": len(align),
        "method": "two-sided percentile-bootstrap p per cell (1,000 resamples, so p >= 0.001); "
        f"Holm step-down across the family; Bonferroni interval at level 1 - 0.05/{ALIGN_FAMILY_M}",
        "nominallySignificant_ci95ExcludesZero": {
            k: v["leagueMinusRef_paired"]["diff"] for k, v in align.items()
            if v["leagueMinusRef_paired"] and (v["leagueMinusRef_paired"]["ci95"][0] > 0
                                                or v["leagueMinusRef_paired"]["ci95"][1] < 0)},
        "holmAdjustedP": holm_p,
        "significantAfterHolm_p_lt_0.05": sorted(k for k, p in holm_p.items() if p < 0.05),
        "bonferroniIntervalExcludesZero": sorted(
            k for k, v in align.items() if v["leagueMinusRef_paired"]
            and (v["leagueMinusRef_paired"][bkey][0] > 0 or v["leagueMinusRef_paired"][bkey][1] < 0)),
        "outOfSampleCells": "today_2026ytd and preseason_2026ytd; preseason_2025 is IN-sample "
        "(the 2026-08-25 board was built after the 2025 season it is compared with)",
    }  # fmt: skip

    # per-card year-to-year stability control.  How stable is each card's ordering
    # of the SAME players from 2025 to 2026?  If this card's (big-play-heavy)
    # ordering is less stable than the tackle-heavy card's, a board that
    # rationally discounts noisy big-play stats would show the same signature in
    # the alignment test and the tackle-share residual with no mis-valuation.
    def per_game(season: int, sid: str, part: str):
        c = comp[season].get(sid)
        g_ = games(season, sid)
        return (c or {}).get(part, 0.0) / g_ if c is not None and g_ else None

    card_stab = {}
    for g in ("idp", *IDP):
        rows_s = []
        for sid, v in pre_vals.items():
            if v is None or spos(sid) not in groups[g]:
                continue
            l25, l26 = ppg(PRIOR, sid), ppg(SEASON, sid)
            r25, r26 = ppg(PRIOR, sid, "tackleHeavyRef"), ppg(SEASON, sid, "tackleHeavyRef")
            parts = [
                per_game(se, sid, pt) for pt in ("tackle", "bigPlay") for se in (PRIOR, SEASON)
            ]
            if None in (l25, l26, r25, r26, *parts):
                continue
            rows_s.append((v, l25, l26, r25, r26, *parts))
        if len(rows_s) < 12:
            continue
        v_, l25, l26, r25, r26, t25, t26, b25, b26 = (list(c) for c in zip(*rows_s))
        card_stab[g] = {
            "n": len(rows_s),
            "leagueCard_ppg2025_vs_ppg2026": spearman_ci(l25, l26),
            "tackleHeavyRef_ppg2025_vs_ppg2026": spearman_ci(r25, r26),
            "leagueMinusRefStability_paired": paired_rho_diff_ci(l25, l26, r25, r26),
            "predictLeagueCard2026_from_leagueCard2025": spearman_ci(l25, l26),
            "predictLeagueCard2026_from_refCard2025": spearman_ci(r25, l26),
            "refCardMinusLeagueCard2025_asPredictorOfLeague2026_paired": paired_diff_ci(
                l26, r25, l25),
            "valuePreseason_vs_leagueCard2026": spearman_ci(v_, l26),
            "tacklePtsPerGame_2025_vs_2026": spearman_ci(t25, t26),
            "bigPlayPtsPerGame_2025_vs_2026": spearman_ci(b25, b26),
            "note": "same players: priced pre-season, >= 8 games in 2025 and >= 3 in 2026; "
            "points per game under THIS card split into tackle and big-play components",
        }  # fmt: skip
    # residual (ppg rank - value rank) against tackle share, 2025, preseason values
    resid = {}
    for pos in IDP:
        xs, ys, ts = [], [], []
        for sid, v in pre_vals.items():
            if v is None or spos(sid) != pos:
                continue
            p, t = ppg(PRIOR, sid), tackle_share(PRIOR, sid)
            if p is not None and t is not None:
                xs.append(v)
                ys.append(p)
                ts.append(t)
        if len(xs) >= 12:
            r = sps.rankdata(ys) / len(ys) - sps.rankdata(xs) / len(xs)
            resid[pos] = spearman_ci(list(r), ts)
            resid[pos]["meaning"] = (
                "rho < 0: the higher a player's tackle share, the more the "
                "board values him relative to his league-card production"
            )

    # per-source predictors (today's board, and the 08-25 archive replayed)
    pre_archive = IA.archive_for(__import__("datetime").date(2026, 8, 25))
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415

    c_pre = build_api_data_contract(IA.read_archive(pre_archive))
    sl_pre = c_pre.get("sleeper") or {}
    n2i_pre = {str(k): str(v) for k, v in (sl_pre.get("playerIds") or {}).items()}
    pre_src: dict[str, dict] = {}
    pre_cons: dict[str, float] = {}
    for r in c_pre.get("playersArray") or []:
        if str(r.get("assetClass") or "") == "pick":
            continue
        sid = r.get("playerId") or next((n2i_pre.get(str(r.get(f) or "")) for f in
                                         ("displayName", "canonicalName", "legacyRef")
                                         if n2i_pre.get(str(r.get(f) or ""))), None)  # fmt: skip
        v = r.get("rankDerivedValue")
        if sid and isinstance(v, (int, float)) and v > 0:
            pre_src[str(sid)] = dict(r.get("sourceRanks") or {})
            pre_cons[str(sid)] = float(v)

    def per_source(src_map: dict, cons: dict, season: int) -> dict:
        out = {}
        for g in ("offense", "idp", *POSITIONS):
            ps = groups[g]
            keys = Counter(k for s, m in src_map.items() if spos(s) in ps for k in m)
            res = {}
            for k, cnt in keys.most_common():
                if cnt < 30:
                    continue
                xs, xc, ys = [], [], []
                for s, m in src_map.items():
                    if spos(s) not in ps or k not in m or cons.get(s) is None:
                        continue
                    p = ppg(season, s)
                    if p is None:
                        continue
                    xs.append(-float(m[k]))
                    xc.append(cons[s])
                    ys.append(p)
                if len(xs) >= 12:
                    res[k] = {
                        "source": spearman_ci(xs, ys),
                        "consensusSameSet": spearman_ci(xc, ys),
                        "sourceMinusConsensus_paired": paired_diff_ci(ys, xs, xc),
                    }
            out[g] = res
        return out

    q5["perSource_today_vs_ppg2026ytd"] = per_source(
        {s: b["sourceRanks"] for s, b in board.items()}, today_vals, SEASON
    )
    q5["perSource_preseasonInputs_vs_ppg2026ytd"] = per_source(pre_src, pre_cons, SEASON)
    q5["perSource_preseasonInputs_vs_ppg2025"] = per_source(pre_src, pre_cons, PRIOR)

    # ════════════════════════════════════════════════════════════════════
    # Q6 — BDVM (league-scored fundamental), in memory, vs canonical
    # ════════════════════════════════════════════════════════════════════
    q6_bdvm: dict[str, Any] = {"status": "skipped"}
    if not args.no_bdvm:
        try:
            from src.bdvm.baseline import fetch_and_build_baseline  # noqa: PLC0415
            from src.bdvm.service import run_valuation  # noqa: PLC0415

            records, summary = fetch_and_build_baseline(
                season=SEASON, as_of="2026-08-25", scoring_settings=card, seasons_back=3,
                pbp_for_season=None)  # fmt: skip
            cfg = league_registry.get_league_by_key(LEAGUE)
            bd = run_valuation(contract, league_key=LEAGUE,
                               registry_roster_settings=dict(cfg.roster_settings or {}),
                               scoring_profile=league_registry.get_scoring_profile(LEAGUE) or "",
                               projection_records=records, snapshot_as_of="2026-08-25",
                               season=SEASON, write_snapshot_files=False)  # fmt: skip
            bvals = {
                str(p.get("playerId")): p for p in bd.get("players") or [] if p.get("playerId")
            }
            out = {"status": bd.get("status"), "pricedPlayers": len(bvals),
                   "baseline": {k: summary.get(k) for k in ("seasonsSeen", "pbpSupplementJoined",
                                                            "rookiePriorRecords", "recordsBuilt")},
                   "note": "proxy baseline (2023-2025 realized PPG under this card + rookie "
                   "draft-slot priors), no in-season actuals: a league-scored PRE-SEASON "
                   "fundamental, so 2026 ppg is out of sample for it"}  # fmt: skip
            for g in ("offense", "idp", *POSITIONS):
                ps = groups[g]
                xs_b, xs_f, xs_c, ys = [], [], [], []
                for sid, p in bvals.items():
                    if spos(sid) not in ps or pre_vals.get(sid) is None:
                        continue
                    y = ppg(SEASON, sid)
                    tv = (p.get("tradeValue") or {}).get("balanced")
                    fpg = (p.get("raw") or {}).get("fpg")
                    if y is None or tv is None or fpg is None:
                        continue
                    xs_b.append(tv)
                    xs_f.append(fpg)
                    xs_c.append(pre_vals[sid])
                    ys.append(y)
                out[g] = {
                    "bdvmBalancedTradeValue": spearman_ci(xs_b, ys),
                    "bdvmProjectedFpg": spearman_ci(xs_f, ys),
                    "canonicalPreseasonSameSet": spearman_ci(xs_c, ys),
                    "bdvmFpgMinusCanonical_paired": paired_diff_ci(ys, xs_f, xs_c),
                    "bdvmVsCanonicalAgreement": spearman_ci(xs_b, xs_c),
                }
            q6_bdvm = out
        except Exception as exc:  # noqa: BLE001 — optional lane; reported, never silent
            q6_bdvm = {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"[:300]}

    # ════════════════════════════════════════════════════════════════════
    # Q7 — consumers, and how each alternative anchor moves them (shadow)
    # ════════════════════════════════════════════════════════════════════
    from src.trade import faab_engine  # noqa: PLC0415
    from src.trade.finder import _BOARD_EDGE_WEIGHT  # noqa: PLC0415
    from src.trade.roster_capacity import (  # noqa: PLC0415
        assess_roster_capacity,
        build_capacity_context,
        forced_drop_cost,
    )

    shadow_names = ("A0_current_served", "A1_bestHealthy", "A2_3rdBestHealthy",
                    "A3h_li5BandedTop3_healthy", "A3hs_li5BandedTop3_healthyStrictRule",
                    "A5_li5_bestBallStarter_rosters")  # fmt: skip
    teams = sl.get("teams") or []
    base_ctx0 = build_capacity_context(contract, LEAGUE, teams[0] if teams else None,
                                       roster_settings=roster_settings)  # fmt: skip
    served_wv = dict(base_ctx0.waiver_values)

    def anchor_dict(name: str) -> dict[str, float]:
        d = dict(served_wv)
        for pos in POSITIONS:
            v = anchor_defs[pos][name][0]
            if v is not None:
                d[pos] = float(v)
        return d

    alt_wv = {n: anchor_dict(n) for n in shadow_names}

    # neutral trade per team: give the own offense player nearest 3,500, receive
    # the two offense players nearest 3,500 on the next team (net +1), and a
    # 1-for-3 variant (net +2).  Incoming players sit far above any anchor, so the
    # forced drop is the team's own cheapest legal cut.
    def nearest(team, k):
        cand = [(abs(name_rows[n]["value"] - 3500), n) for n in team.get("players") or []
                if n in name_rows and name_rows[n]["pos"] in OFFENSE]  # fmt: skip
        return [n for _, n in sorted(cand)[:k]]

    cap_rows = []
    for i, team in enumerate(teams):
        other = teams[(i + 1) % len(teams)]
        give = nearest(team, 1)
        for net, k_in in (("net+1", 2), ("net+2", 3)):
            recv = nearest(other, k_in)
            ctx_t = build_capacity_context(contract, LEAGUE, team, roster_settings=roster_settings)
            row = {"scenario": net}
            for name in shadow_names:
                c2 = dataclasses.replace(ctx_t, waiver_values=alt_wv[name])
                cap = assess_roster_capacity(c2, incoming_players=recv, outgoing_players=give)
                cost, basis = forced_drop_cost(cap)
                give_v = sum(name_rows[n]["value"] for n in give)
                row[name] = {
                    "drops": [(d.name, d.position, d.value_basis) for d in cap.forced_drops],
                    "cost": cost,
                    "eccSum": cap.forced_drop_cut_cost,
                    "finderFactor": (-(cost / max(give_v, 1)) * _BOARD_EDGE_WEIGHT
                                     if cost is not None else None),
                }  # fmt: skip
            cap_rows.append(row)

    def cap_summary(scn: str) -> dict:
        rows_s = [r for r in cap_rows if r["scenario"] == scn]
        base = "A0_current_served"
        out = {"teams": len(rows_s)}
        for name in shadow_names:
            changed = sum(1 for r in rows_s if r[name]["drops"] != r[base]["drops"])
            dc = [r[name]["cost"] - r[base]["cost"] for r in rows_s
                  if r[name]["cost"] is not None and r[base]["cost"] is not None]  # fmt: skip
            dfac = [
                r[name]["finderFactor"] - r[base]["finderFactor"]
                for r in rows_s
                if r[name]["finderFactor"] is not None and r[base]["finderFactor"] is not None
            ]
            drops = [d for r in rows_s for d in r[name]["drops"]]
            out[name] = {
                "teamsWhoseForcedDropChanged": changed,
                "forcedDropCostMean": _r(statistics.fmean(r[name]["cost"] for r in rows_s
                                                          if r[name]["cost"] is not None)),
                "deltaCostVsCurrent_mean": _r(statistics.fmean(dc)) if dc else None,
                "deltaCostVsCurrent_maxAbs": _r(max((abs(x) for x in dc), default=0)),
                "deltaFinderFactor_meanAbs": _r(statistics.fmean(abs(x) for x in dfac), 2)
                if dfac else None,
                "dropsByPosition": dict(Counter(p for _, p, _ in drops)),
                "dropsAssumedWaiver": sum(1 for *_, b in drops if b == "assumedWaiver"),
                "eccSumMean": _r(statistics.fmean(r[name]["eccSum"] for r in rows_s)),
            }  # fmt: skip
        return out

    q7_capacity = {s: cap_summary(s) for s in ("net+1", "net+2")}
    # one illustrative team (names only, no team identity)
    q7_capacity["illustrativeNet+1_firstTeamWhoseDropChanges"] = next(
        (
            {n: r[n]["drops"] for n in shadow_names}
            for r in cap_rows
            if r["scenario"] == "net+1"
            and any(r[n]["drops"] != r["A0_current_served"]["drops"] for n in shadow_names)
        ),
        None,
    )

    # Perfect Draft: surplus over replacement for every board rookie, by anchor
    rookies = [b for s, b in board.items() if b["rookie"] and b["pos"] in POSITIONS]
    q7_pd = {}
    for name in shadow_names:
        wv = alt_wv[name]
        by = defaultdict(lambda: [0, 0.0, 0])
        for b in rookies:
            s = max(0.0, b["value"] - wv.get(b["pos"], min(wv.values())))
            by[b["pos"]][0] += s > 0
            by[b["pos"]][1] += s
            by[b["pos"]][2] += 1
        q7_pd[name] = {p: {"rookies": v[2], "positiveSurplus": v[0], "surplusSum": _r(v[1])}
                       for p, v in sorted(by.items())}  # fmt: skip
    # position-agnostic FA ladder W(k): all vs healthy
    all_fa = sorted((b["value"] for s, b in board.items() if s not in live_ids
                     and b["pos"] in POSITIONS), reverse=True)  # fmt: skip
    healthy_fa = sorted((b["value"] for s, b in board.items() if s not in live_ids
                         and b["pos"] in POSITIONS and healthy.get(s)), reverse=True)  # fmt: skip
    healthy_fa_s = sorted((b["value"] for s, b in board.items() if s not in live_ids
                           and b["pos"] in POSITIONS and healthy_strict.get(s)), reverse=True)  # fmt: skip
    q7_pd["waiverLadderTop5"] = {"all": [_r(v) for v in all_fa[:5]],
                                 "healthyOnly": [_r(v) for v in healthy_fa[:5]],
                                 "healthyOnlyStrictRule": [_r(v) for v in healthy_fa_s[:5]]}  # fmt: skip

    # FAAB V_repl: available pool all / healthy / healthy-producing
    excluded = set(faab_engine.FaabConfig().get("anchors", "excludedPositions", []) or [])
    starters_map = roster_settings.get("starters") or {}
    spt = sum(int(v or 0) for k, v in starters_map.items() if str(k).upper() != "K") or 20
    bvals_all = [
        r["value"] for r in rows.values() if r["cls"] != "pick" and (r["pos"] or "") not in excluded
    ]
    pools = {
        "all_unrostered_served": [r["value"] for n, r in rows.items() if r["cls"] != "pick"
                                  and (r["pos"] or "") not in excluded and n not in ctx["rostered"]],
        "healthy_unrostered": [d["value"] for p in POSITIONS for d in fa_pool.get(p) or [] if d["healthy"]],
        "healthyStrict_unrostered": [d["value"] for p in POSITIONS for d in fa_pool.get(p) or []
                                     if d["healthyStrict"]],
        "healthy_productionQualified": [d["value"] for p in POSITIONS for d in fa_pool.get(p) or []
                                        if producing(d, p)],
    }  # fmt: skip
    q7_faab = {}
    faab_w = faab_engine.FaabConfig().num("anchors", "replacementLivePoolWeight", 0.5)
    faab_w = max(0.0, min(1.0, faab_w))
    for pname, av in pools.items():
        a = faab_engine.resolve_anchors(
            bvals_all,
            faab_engine.LeagueContext(team_count=teams_n or 12, starters_per_team=spt),
            available_values=av or None,
        )
        q7_faab[pname] = {
            "vRepl": _r(a.v_repl),
            "vReplRawBlendBeforeGuardrail": _r(
                faab_w * a.live_pool_repl + (1 - faab_w) * a.format_repl
                if a.live_pool_repl is not None and a.format_repl is not None
                else None
            ),
            "guardrailWidened_vReplCappedAt_vAllinMinusMinBand": a.widened,
            "livePoolRepl_12th": _r(a.live_pool_repl),
            "formatRepl": _r(a.format_repl),
            "vAllin": _r(a.v_allin),
            "objectiveCeilingPctOfBudget": {
                str(v): _r(100 * faab_engine.objective_ceiling(v, a)[0], 1)
                for v in (1800, 2200, 2600, 3000, 4000)
            },
        }

    # LI-5 / scarcity: served multiplier, and the value-scale waiver tier in shadow
    try:
        from src.draft.context import _league_scarcity  # noqa: PLC0415
        from src.draft.displacement import scarcity_multiplier  # noqa: PLC0415

        sc, note = _league_scarcity(LEAGUE, contract)
        q7_scarcity = {
            "servedNote": note,
            "servedWaiverScarcityByPosition": {p: (getattr(sc.get(p), "waiver_scarcity", None)
                                                   if sc else None) for p in POSITIONS},
            "servedMultiplierByPosition": {p: _r(scarcity_multiplier(sc.get(p) if sc else None), 3)
                                           for p in POSITIONS},
        }  # fmt: skip
    except Exception as exc:  # noqa: BLE001
        q7_scarcity = {"servedNote": f"{type(exc).__name__}: {exc}"[:200]}

    result = {
        "purpose": "RESEARCH ONLY (owner decision 2026-10-20 §3, investigation B): IDP "
        "replacement anchors and league-specific IDP scoring.  No production code, value, "
        "weight, vote, curve, anchor or config changed; every alternative is shadow.",
        "generatedBy": "scripts/idp_replacement_research.py",
        "board": {
            "archive": str(zpath.relative_to(REPO)),
            "member": member,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "methodology": "today's code via shadow_replay.build_context",
            "servedPreseasonBoard": pre_meta["artifact"],
            "preseasonPerSourceReplay": str(pre_archive.relative_to(REPO)),
        },
        "inputs": {
            "weeks2026": weeks,
            "weeks2025": list(PRIOR_WEEKS),
            "minGames2026": MIN_GAMES,
            "minGames2025": MIN_GAMES_PRIOR,
            "bootstrapResamples": BOOT,
            "scorerVsHostPlayersPoints2026": {
                "playerWeeks": len(scorer_diffs),
                "exactWithin0.01": sum(1 for d in scorer_diffs if d < 0.01),
                "maxAbsDiff": _r(max(scorer_diffs), 3) if scorer_diffs else None,
            },
            "cardNote": "both seasons are scored under the CURRENT (2026) card; 2025 was "
            "played under a different format, so 2025 here is 'this card applied to last "
            "season's stat lines', not what the league scored in 2025",
        },
        "consumers": [{"what": w, "where": locate(p, rx)} for w, p, rx in CONSUMERS],
        "Q1_anchors": {
            "definitions": {
                "A0": "served rule: best unrostered rankDerivedValue (snapshot rosters / live)",
                "A1": "best unrostered that is HEALTHY now under the shadow rule IA.is_healthy "
                "(NFL team, status not Inactive/IR/PUP, injury status not IR/Out/PUP/Doubtful/Sus/"
                "NA/DNR/COV; a missing status passes)",
                "A1s/A3hs": "A1 / A3h under the RECOMMENDED strict rule is_healthy_strict: NFL "
                "team AND explicit status 'Active' AND no unavailable injury designation; a "
                "missing or unrecognised status is unknown and excluded",
                "A2": "k-th best healthy unrostered (k = 3, 6)",
                "A3": "LI-5 banded waiver tier: mean of the top 3 unrostered (all / healthy)",
                "A4": "best-valued healthy unrostered whose season-to-date ppg >= P10 of the "
                "league's production-optimal starters at the position (A4b: P25 bar).  It uses "
                "weeks 1..N, the same data as the 'production starters below' metric, so that "
                "metric is circular for A4",
                "A5": "LI-5 roster tiers from shadow_replay (bestBallStarter = mean of the two "
                "lowest teams' marginal starters; starter = median marginal starter)",
                "D": "diagnostic: median value of rostered players producing within +-15% of "
                "the 3rd-best healthy free agent's ppg (the board's price of wire production)",
            },
            "byPosition": q1_anchors,
            "top10UnrosteredCensus": q1_census,
            "spearmanValueVsPpgAmongUnrostered": q1_wire_order,
        },
        "Q2_availabilityEligibility": q2,
        "Q3_scoringCard": {
            "idpScoringCardThisLeague": idp_card,
            "tackleHeavyReference": REFERENCE_TACKLE_HEAVY,
            "priceRatios_leagueCard": {
                "passDefendedInSoloTackles": _r(
                    card.get("idp_pass_def", 0) / max(card.get("idp_tkl_solo", 1e-9), 1e-9), 2
                ),
                "tflInSoloTackles": _r(
                    card.get("idp_tkl_loss", 0) / max(card.get("idp_tkl_solo", 1e-9), 1e-9), 2
                ),
                "sackInSoloTackles": _r(
                    card.get("idp_sack", 0) / max(card.get("idp_tkl_solo", 1e-9), 1e-9), 2
                ),
            },  # fmt: skip
            "byPositionAndSeason": q3_pos,
            "tackleShareTertiles_2025_top2xStarters": q3_profiles,
        },
        "Q4_scarcity": q4,
        "Q5_correlation": q5,
        "Q6_leagueScoringAlignment": {
            "valueVsCard": align,
            "valueVsCard_multiplicity": align_mult,
            "perCardYearToYearStability_control": card_stab,
            "residualVsTackleShare_preseason_2025": resid,
            "bdvm": q6_bdvm,
        },
        "Q7_consumerShadow": {
            "anchorDictsUsed": {
                n: {p: _r(v) for p, v in sorted(d.items())} for n, d in alt_wv.items()
            },
            "rosterCapacityForcedDrops": q7_capacity,
            "perfectDraftRookieSurplus": q7_pd,
            "faabVRepl": q7_faab,
            "scarcity": q7_scarcity,
        },
        "timingsSec": round(time.time() - t0, 1),
    }
    SR.P2.assert_aggregate_only({k: v for k, v in result.items() if k != "board"})
    SR.P2.assert_aggregate_only({k: v for k, v in result["board"].items() if k != "sha256"})
    out = REPO / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(out), "timingsSec": result["timingsSec"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
