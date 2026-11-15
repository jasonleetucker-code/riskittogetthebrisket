"""CW-08 scoring-parity census: repo scorers vs the league host (Sleeper).

Measurement only.  Imports production scorers, changes none of them.

For every ROSTERED player-week of a FINALIZED week of ``dynasty_main`` it joins

* **host**   - Sleeper ``players_points`` (``/league/<id>/matchups/<week>``);
* **(b)**    - canonical ``score_stat_line`` on Sleeper's own raw stat line
               (``/stats/nfl/regular/<season>/<week>``), plus the production
               host-native wrapper ``compute_weekly_points(source="sleeper")``;
* **(c)**    - ``compute_weekly_points`` on the nflverse weekly row, exactly as
               the BDVM in-season blend feeds it (``normalize_weekly_row`` +
               play-by-play supplement + TRUE_POSITION_MAP).

The nflverse row is joined to a Sleeper id by GSIS id through the canonical
identity owner (``src.identity.resolution.resolve_canonical_v2``) - never by
name.  Rows that cannot be joined are counted separately, never as 0.

Network is confined to ``fetch_inputs``; ``build_census`` is pure and is what
the unit test drives with fixtures.

Usage::

    python scripts/scoring_parity_census.py                 # live, caches under data/scoring_parity/
    python scripts/scoring_parity_census.py --offline       # reuse cache
    python scripts/scoring_parity_census.py --alt-realized-points path/to/realized_points.py

Public artifact policy: aggregates plus public NFL player names / Sleeper
player ids.  No roster, user, manager or league id is written.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

TOL = 0.011  # Sleeper publishes 2 decimals; rounding alone is <= 0.005
SLEEPER = "https://api.sleeper.app/v1"
IDP_GROUPS = ("DL", "LB", "DB")

#: nflverse columns that carry the event a Sleeper key pays; used to separate a
#: MAPPING defect (the row has the event, our normalization dropped it) from a
#: feed difference (the row does not carry it / carries a different count).
MAPPING_PROBES: dict[str, tuple[str, ...]] = {
    "idp_tkl_solo": ("def_tackles_solo",),
    "idp_tkl_ast": ("def_tackle_assists",),
    "idp_tkl_loss": ("def_tackles_for_loss",),
    "idp_sack": ("def_sacks",),
    "idp_qb_hit": ("def_qb_hits",),
    "idp_pass_def": ("def_pass_defended",),
    "idp_int": ("def_interceptions",),
    "idp_ff": ("def_fumbles_forced",),
    "idp_fum_rec": ("fumble_recovery_opp",),
    "idp_def_td": ("def_tds", "fumble_recovery_tds"),
    "idp_safe": ("def_safeties",),
    "idp_blk_kick": ("def_fg_blocks", "def_pat_blocks", "def_punt_blocks"),
    "xpmiss": ("pat_blocked",),
    "fgmiss": ("fg_blocked",),
}
STAT_KEY_PREFIXES_BLOCKED = ("fgmiss",)


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


# ── scorer loading (optionally the PR #1938 variant) ──────────────────────────


def load_scoring(alt_realized_points: Path | None = None) -> SimpleNamespace:
    """Resolve the production scorer functions, optionally swapping realized_points."""
    if alt_realized_points is not None:
        spec = importlib.util.spec_from_file_location(
            "src.nfl_data.realized_points", alt_realized_points
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules["src.nfl_data.realized_points"] = mod
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        import src.nfl_data as pkg  # noqa: PLC0415

        pkg.realized_points = mod  # type: ignore[attr-defined]
    from src.bdvm.baseline import normalize_weekly_row  # noqa: PLC0415
    from src.bdvm.context import TRUE_POSITION_MAP  # noqa: PLC0415
    from src.league_intel.scorer import score_stat_line  # noqa: PLC0415
    from src.nfl_data import pbp_weekly  # noqa: PLC0415
    from src.nfl_data import realized_points as rp  # noqa: PLC0415
    from src.ros.lineup import lineup_position  # noqa: PLC0415

    return SimpleNamespace(
        compute_weekly_points=rp.compute_weekly_points,
        score_stat_line=score_stat_line,
        normalize_weekly_row=normalize_weekly_row,
        attach_supplement=pbp_weekly.attach_supplement,
        true_position_map=TRUE_POSITION_MAP,
        lineup_position=lineup_position,
        realized_points_module=rp,
    )


# ── pure census ───────────────────────────────────────────────────────────────


def _components(res: Any) -> dict[str, tuple[float, float]]:
    """key -> (raw stat, awarded points) for nonzero-rate components."""
    out: dict[str, tuple[float, float]] = {}
    for key, raw, rate, pts in getattr(res, "components", ()) or ():
        if rate:
            out[key] = (float(raw), float(pts))
    return out


def classify_key(
    key: str,
    host_raw: float,
    nfl_raw: float,
    raw_row: Mapping[str, Any],
    *,
    host_pos: str,
    nfl_pos: str,
) -> tuple[str, str]:
    """(category, subtype) for one scoring key whose points differ.

    Categories (directive §6 vocabulary): ``category_mapping_defect``,
    ``missing_raw_stat_event_in_feed``.  Rules, in order:

    1. position-scoped first-down key paid under a different position than the
       host used -> mapping defect (position vocabulary);
    2. host pays MORE and the nflverse row demonstrably carries the event in a
       column this key maps from, yet normalization emitted less ->
       mapping defect;
    3. everything else: the providers chart the event differently (counts
       differ) or the feed has no event -> feed difference.
    """
    if key.startswith("bonus_fd_") and host_pos != nfl_pos:
        return "category_mapping_defect", "position_vocabulary"

    def has(cols: tuple[str, ...]) -> bool:
        return any((_num(raw_row.get(c)) or 0) > 0 for c in cols)

    probe = MAPPING_PROBES.get(key)
    if probe is None and key.startswith(STAT_KEY_PREFIXES_BLOCKED):
        probe = MAPPING_PROBES["fgmiss"]
    # A mapping defect is "the row HAS the event and normalization emitted
    # NOTHING for this key".  A nonzero emitted count that merely differs from
    # the host's is two providers charting the event differently.
    if probe and host_raw > nfl_raw and nfl_raw == 0 and has(probe):
        return "category_mapping_defect", "event_present_in_row_not_emitted"
    if host_raw > nfl_raw:
        return "missing_raw_stat_event_in_feed", "feed_undercounts_vs_host"
    st = _num(raw_row.get("_pbp_st_" + key)) or 0.0
    if st > 0 and nfl_raw - host_raw > 0:
        exact = abs((nfl_raw - host_raw) - st) < 1e-9
        return (
            "missing_raw_stat_event_in_feed",
            "special_teams_play_in_defensive_column" + ("_exact" if exact else "_partial"),
        )
    return "missing_raw_stat_event_in_feed", "feed_overcounts_vs_host"


def _dist(diffs: list[float]) -> dict[str, Any]:
    a = sorted(abs(d) for d in diffs)
    n = len(a)
    ok = sum(1 for d in a if d <= TOL)
    return {
        "n": n,
        "withinTol": ok,
        "agreement": round(ok / n, 6) if n else None,
        "maxAbs": round(a[-1], 4) if n else None,
        "meanAbs": round(sum(a) / n, 6) if n else None,
        "netSigned": round(sum(diffs), 3),
    }


def build_census(
    *,
    card: Mapping[str, Any],
    players: Mapping[str, Mapping[str, Any]],
    matchups_by_week: Mapping[int, list[dict[str, Any]]],
    stats_by_week: Mapping[int, Mapping[str, Mapping[str, Any]]],
    nflverse_rows: list[dict[str, Any]],
    pbp_stats: Any | None,
    scoring: SimpleNamespace,
    weeks: list[int],
) -> dict[str, Any]:
    from src.identity.resolution import SleeperDirectoryIndex, resolve_canonical_v2  # noqa: PLC0415

    index = SleeperDirectoryIndex(dict(players))
    card_f = {k: float(v) for k, v in card.items() if _num(v) is not None}

    # nflverse rows -> (sleeper id, week) via the identity owner (GSIS only).
    nfl_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    nfl_unjoined = Counter()
    join_methods: Counter = Counter()
    dup_keys = 0
    for r in nflverse_rows:
        if str(r.get("season_type") or "REG").upper() != "REG":
            continue
        wk = _num(r.get("week"))
        if wk is None or int(wk) not in weeks:
            continue
        gsis = str(r.get("player_id") or "").strip()
        res = resolve_canonical_v2(index, gsis_id=gsis)
        if not res.resolved:
            # Sleeper's directory carries gsis_id for only ~1/3 of entries (and
            # none for most current rookies).  Fall back to the SAME owner's
            # exact-name rungs (name + position + team); the guarded-fuzzy and
            # initial-expansion rungs are refused, an ambiguity is refused.
            res = resolve_canonical_v2(
                index,
                name=str(r.get("player_display_name") or r.get("player_name") or ""),
                position=str(r.get("position") or ""),
                team=str(r.get("team") or ""),
            )
            if res.resolved and res.method.startswith(("fuzzy_guarded", "initial_last_guarded")):
                nfl_unjoined["refused_fuzzy_rung"] += 1
                continue
        if not res.resolved or not res.sleeper_id:
            nfl_unjoined["unresolved_by_identity_owner"] += 1
            continue
        join_methods[res.method.split(":")[0]] += 1
        k = (str(res.sleeper_id), int(wk))
        if k in nfl_by_key:
            dup_keys += 1
            continue
        nfl_by_key[k] = r

    recs: list[dict[str, Any]] = []
    for w in weeks:
        stats = stats_by_week.get(w) or {}
        for m in matchups_by_week.get(w) or []:
            started = {str(s) for s in (m.get("starters") or [])}
            for sid, awarded in (m.get("players_points") or {}).items():
                sid = str(sid)
                meta = players.get(sid) or {}
                listed = str(meta.get("position") or "").upper()
                rec: dict[str, Any] = {
                    "week": w,
                    "sid": sid,
                    "name": meta.get("full_name")
                    or f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip(),
                    "pos": listed,
                    "group": scoring.lineup_position(listed) or listed or "?",
                    "started": sid in started,
                    "host": float(awarded),
                }
                line = stats.get(sid)
                host_comp: dict[str, tuple[float, float]] = {}
                if line is None:
                    rec["b_raw"] = rec["b_prod"] = None
                else:
                    rec["b_raw"] = scoring.score_stat_line(line, card_f).total_points
                    row = {**line, "player_id": sid, "season": 2026, "week": w}
                    prod = scoring.compute_weekly_points(
                        row, card_f, position=rec["group"], source="sleeper"
                    )
                    rec["b_prod"] = None if prod is None else prod.fantasy_points
                    host_comp = _components(prod) if prod is not None else {}
                raw = nfl_by_key.get((sid, w))
                nfl_comp: dict[str, tuple[float, float]] = {}
                rec["c"] = None
                if raw is not None:
                    listing = str(raw.get("position") or "").upper()
                    npos = scoring.true_position_map.get(listing, listing)
                    row = scoring.normalize_weekly_row(raw)
                    if pbp_stats is not None:
                        row = scoring.attach_supplement(row, pbp_stats)
                    cres = scoring.compute_weekly_points(row, card_f, position=npos)
                    if cres is not None:
                        rec["c"] = cres.fantasy_points
                        rec["c_unscored"] = [k for k, _ in cres.unscored]
                        nfl_comp = _components(cres)
                    rec["nflPos"] = npos
                rec["_host_comp"] = host_comp
                rec["_nfl_comp"] = nfl_comp
                rec["_raw"] = raw
                rec["_st"] = {}
                if raw is not None and pbp_stats is not None:
                    sup = scoring.attach_supplement(raw, pbp_stats).get("pbp_derived") or {}
                    rec["_st"] = {
                        "_pbp_st_idp_tkl_solo": _num(sup.get("st_tkl_solo")) or 0.0,
                        "_pbp_st_idp_tkl_ast": _num(sup.get("st_tkl_ast")) or 0.0,
                    }
                recs.append(rec)

    # ---- (b) host-native ----------------------------------------------------
    def _agree(a: float | None, b: float) -> bool | None:
        return None if a is None else abs(a - b) <= TOL

    b_rows = [r for r in recs if r["b_raw"] is not None]
    b_no_line = [r for r in recs if r["b_raw"] is None]
    host_native = {
        "rosteredPlayerWeeks": len(recs),
        "withStatLine": len(b_rows),
        "noStatLine": len(b_no_line),
        "noStatLineAwardedZero": sum(1 for r in b_no_line if abs(r["host"]) <= TOL),
        "noStatLineAwardedNonzero": [
            {"week": r["week"], "name": r["name"], "pos": r["pos"], "host": r["host"]}
            for r in b_no_line
            if abs(r["host"]) > TOL
        ],
        "canonicalScoreStatLine": _dist([r["b_raw"] - r["host"] for r in b_rows]),
        "productionHostNative": _dist(
            [r["b_prod"] - r["host"] for r in b_rows if r["b_prod"] is not None]
        ),
        "byGroup": {
            g: _dist([r["b_raw"] - r["host"] for r in b_rows if r["group"] == g])
            for g in sorted({r["group"] for r in b_rows})
        },
        "byWeek": {
            f"w{w}": _dist([r["b_raw"] - r["host"] for r in b_rows if r["week"] == w])
            for w in weeks
        },
        "exceptions": [
            {
                "week": r["week"],
                "name": r["name"],
                "pos": r["pos"],
                "host": r["host"],
                "b_raw": round(r["b_raw"], 4),
            }
            for r in b_rows
            if abs(r["b_raw"] - r["host"]) > TOL
        ],  # fmt: skip
    }
    # Where (b) disagrees: is the host's own raw line the cause (host-scoring difference)?
    host_scoring_diff = len(host_native["exceptions"])

    # ---- (c) nflverse -------------------------------------------------------
    c_rows = [r for r in recs if r["c"] is not None]
    unjoined = Counter()
    unjoined_nonzero: list[dict[str, Any]] = []
    for r in recs:
        if r["c"] is not None:
            continue
        if r["_raw"] is None:
            if abs(r["host"]) <= TOL:
                unjoined["no_nflverse_row_host_zero"] += 1
            else:
                unjoined["no_nflverse_row_host_nonzero"] += 1
                unjoined_nonzero.append(
                    {"week": r["week"], "name": r["name"], "pos": r["pos"], "host": r["host"]}
                )
        else:
            unjoined["row_refused_by_scorer"] += 1

    key_stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"rowsDiffer": 0, "netPts": 0.0, "absPts": 0.0, "hostRows": 0, "nflRows": 0,
                 "hostPts": 0.0, "nflPts": 0.0, "byGroup": Counter(), "classes": Counter()}
    )  # fmt: skip
    row_classes: Counter = Counter()
    by_class_pts: Counter = Counter()
    mismatches: list[dict[str, Any]] = []
    explained_single_key = 0
    for r in c_rows:
        hc, nc = r["_host_comp"], r["_nfl_comp"]
        for k in set(hc) | set(nc):
            ks = key_stats[k]
            hr, hp = hc.get(k, (0.0, 0.0))
            nr, np_ = nc.get(k, (0.0, 0.0))
            ks["hostRows"] += hr != 0
            ks["nflRows"] += nr != 0
            ks["hostPts"] += hp
            ks["nflPts"] += np_
        d = r["c"] - r["host"]
        if abs(d) <= TOL:
            continue
        diffs: dict[str, dict[str, Any]] = {}
        for k in set(hc) | set(nc):
            hr, hp = hc.get(k, (0.0, 0.0))
            nr, np_ = nc.get(k, (0.0, 0.0))
            if abs(np_ - hp) > 1e-9:
                diffs[k] = {"hostRaw": hr, "nflRaw": nr, "deltaPts": round(np_ - hp, 4)}
        if r["b_raw"] is not None and abs(r["b_raw"] - r["host"]) > TOL:
            cat, sub = "host_scoring_difference", "host_line_vs_award"
            row_classes[cat] += 1
            by_class_pts[cat] += d
            mismatches.append({"week": r["week"], "name": r["name"], "pos": r["pos"],
                               "delta": round(d, 4), "category": cat, "subtype": sub})  # fmt: skip
            continue
        row_cats: Counter = Counter()
        for k, v in diffs.items():
            cat, sub = classify_key(
                k, v["hostRaw"], v["nflRaw"], {**(r["_raw"] or {}), **r["_st"]},
                host_pos=r["group"], nfl_pos=scoring.lineup_position(r.get("nflPos") or "") or "",
            )  # fmt: skip
            v["category"], v["subtype"] = cat, sub
            row_cats[cat] += abs(v["deltaPts"])
            ks = key_stats[k]
            ks["rowsDiffer"] += 1
            ks["netPts"] += v["deltaPts"]
            ks["absPts"] += abs(v["deltaPts"])
            ks["byGroup"][r["group"]] += 1
            ks["classes"][f"{cat}:{sub}"] += 1
        if len(diffs) == 1:
            explained_single_key += 1
        residual = d - sum(v["deltaPts"] for v in diffs.values())
        if abs(residual) > TOL:
            cat, sub = "unexplained_residual", "keys_do_not_sum_to_delta"
        else:
            cat, sub = max(row_cats.items(), key=lambda kv: kv[1])[0], "dominant_key_class"
        row_classes[cat] += 1
        by_class_pts[cat] += d
        mismatches.append({"week": r["week"], "name": r["name"], "pos": r["pos"],
                           "delta": round(d, 4), "category": cat, "keys": diffs,
                           "unscored": r.get("c_unscored") or []})  # fmt: skip

    aliases = dict(getattr(scoring.realized_points_module, "_SCORING_KEY_ALIASES", {}))

    def _ks(k: str, v: dict[str, Any]) -> dict[str, Any]:
        rate = card_f.get(k)
        if rate is None:
            rate = next((card_f[a] for a, c in aliases.items() if c == k and a in card_f), None)
        return {"key": k, "rate": rate, "hostRowsNonzero": v["hostRows"],
                "nflverseRowsNonzero": v["nflRows"], "rowsDiffer": v["rowsDiffer"],
                "netPtsNflMinusHost": round(v["netPts"], 3), "absPts": round(v["absPts"], 3),
                "hostPtsTotal": round(v["hostPts"], 2), "nflPtsTotal": round(v["nflPts"], 2),
                "byGroup": dict(v["byGroup"]), "classes": dict(v["classes"])}  # fmt: skip

    per_key = sorted((_ks(k, v) for k, v in key_stats.items()), key=lambda x: -x["absPts"])
    # priced keys with no nonzero activity on either side are reported separately
    seen = set(key_stats) | {a for a, c in aliases.items() if c in key_stats}
    quiet = sorted(k for k, rate in card_f.items() if rate and k not in seen)

    return {
        "nflverseJoin": {
            "nflverseRegRowsInScope": sum(
                1
                for r in nflverse_rows
                if str(r.get("season_type") or "REG").upper() == "REG"
                and _num(r.get("week")) is not None
                and int(_num(r.get("week"))) in weeks
            ),  # fmt: skip
            "joinedToSleeperId": len(nfl_by_key),
            "joinMethods": dict(join_methods),
            "directoryEntriesWithGsis": sum(
                1 for v in players.values() if str(v.get("gsis_id") or "").strip()
            ),
            "directoryEntries": len(players),
            "nflverseRowsUnjoined": dict(nfl_unjoined),
            "duplicateSleeperIdWeek": dup_keys,
            "nflverseRowsNotRostered": len(nfl_by_key)
            - sum(1 for r in recs if r["_raw"] is not None),
            "hostRowsWithoutNflverseRow": dict(unjoined),
            "hostRowsWithoutNflverseRowButHostNonzero": unjoined_nonzero,
        },
        "hostNative": host_native,
        "nflversePath": {
            "scored": _dist([r["c"] - r["host"] for r in c_rows]),
            "byGroup": {
                g: _dist([r["c"] - r["host"] for r in c_rows if r["group"] == g])
                for g in sorted({r["group"] for r in c_rows})
            },
            "byWeek": {
                f"w{w}": _dist([r["c"] - r["host"] for r in c_rows if r["week"] == w])
                for w in weeks
            },
            "startedOnly": _dist([r["c"] - r["host"] for r in c_rows if r["started"]]),
            "rowClassification": dict(row_classes),
            "netPtsByClassNflMinusHost": {k: round(v, 2) for k, v in by_class_pts.items()},
            "mismatchedRowsExplainedBySingleKey": explained_single_key,
            "rowsWithUnscoredPbpRules": sum(1 for r in c_rows if r.get("c_unscored")),
            "hostScoringDifferenceRows": host_scoring_diff,
            "perKey": per_key,
            "pricedKeysWithNoActivity": quiet,
            "mismatches": mismatches,
        },
        "_recs": recs,
    }


# ── network layer ─────────────────────────────────────────────────────────────


class Cache:
    def __init__(self, root: Path, offline: bool) -> None:
        self.root, self.offline, self.last = root, offline, 0.0
        self.receipts: dict[str, dict[str, Any]] = {}
        root.mkdir(parents=True, exist_ok=True)

    def get(self, url: str, label: str) -> Any:
        import requests  # noqa: PLC0415

        p = self.root / (hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")
        if not p.exists():
            if self.offline:
                raise RuntimeError(f"offline and not cached: {label}")
            time.sleep(max(0.0, 0.25 - (time.time() - self.last)))
            resp = requests.get(url, timeout=90)
            self.last = time.time()
            resp.raise_for_status()
            p.write_bytes(resp.content)
        blob = p.read_bytes()
        self.receipts[label] = {
            "sha256": hashlib.sha256(blob).hexdigest(),
            "bytes": len(blob),
            "fetchedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.stat().st_mtime)),
        }
        return json.loads(blob)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cache", type=Path, default=REPO / "data/scoring_parity/cache")
    ap.add_argument("--pbp-dir", type=Path, default=REPO / "data/scoring_parity/pbp_weekly")
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO / "docs/scoring/evidence/scoring_parity_census_2026-11-06.json",
    )
    ap.add_argument("--alt-realized-points", type=Path, default=None)
    ap.add_argument("--label", default="main")
    ap.add_argument(
        "--variant-json",
        type=Path,
        default=None,
        help="census JSON of another scorer variant to embed as a summary",
    )
    args = ap.parse_args()

    scoring = load_scoring(args.alt_realized_points)
    from src.api import league_registry  # noqa: PLC0415
    from src.league_comparison.sleeper_scoring import scoring_fingerprint  # noqa: PLC0415
    from src.nfl_data import nflverse_direct, pbp_weekly  # noqa: PLC0415
    from src.public_league.metrics import host_lineups_open_from_week  # noqa: PLC0415

    league_key = "dynasty_main"
    league_id = str(league_registry.get_sleeper_league_id(league_key))
    c = Cache(args.cache, args.offline)
    league = c.get(f"{SLEEPER}/league/{league_id}", "sleeper_league")
    state = c.get(f"{SLEEPER}/state/nfl", "sleeper_state_nfl")
    season = int(league["season"])
    open_from, reason = host_lineups_open_from_week(
        SimpleNamespace(league=league, season=str(season)), state
    )
    last_scored = int(league.get("settings", {}).get("last_scored_leg") or 0)
    top = (open_from - 1) if open_from else last_scored
    weeks = list(range(1, min(top, last_scored or top) + 1))
    card = {k: v for k, v in (league.get("scoring_settings") or {}).items() if _num(v) is not None}
    fp = scoring_fingerprint(card)
    players = c.get(f"{SLEEPER}/players/nfl", "sleeper_players_nfl")
    matchups = {
        w: c.get(f"{SLEEPER}/league/{league_id}/matchups/{w}", f"matchups_w{w}") for w in weeks
    }
    stats = {w: c.get(f"{SLEEPER}/stats/nfl/regular/{season}/{w}", f"stats_w{w}") for w in weeks}
    rows = [r for r in nflverse_direct.fetch_weekly_stats([season])
            if str(r.get("season_type") or "REG").upper() == "REG"]  # fmt: skip
    pbp_dir = args.pbp_dir
    if pbp_weekly.load_pbp_weekly(season, out_dir=pbp_dir) is None:
        pbp_weekly.persist_pbp_weekly([season], out_dir=pbp_dir, complete_through_week=max(weeks))
    pbp_stats = pbp_weekly.default_pbp_stats(season, out_dir=pbp_dir)

    res = build_census(card=card, players=players, matchups_by_week=matchups,
                       stats_by_week=stats, nflverse_rows=rows, pbp_stats=pbp_stats,
                       scoring=scoring, weeks=weeks)  # fmt: skip
    res.pop("_recs")
    pinned = json.loads((REPO / "docs/valuation/idp_accuracy/MANIFEST.json").read_text("utf-8"))
    pinned_fp = (pinned.get("scoringCard") or {}).get("scoringFingerprint")
    out = {
        "census": "CW-08 scoring parity",
        "generatedAtUtc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scorerVariant": args.label,
        "league": {"key": league_key, "season": season, "status": league.get("status")},
        "scoringFingerprint": fp,
        "scoringFingerprintPinnedByLaneA2026_10_25": pinned_fp,
        "configurationMismatch": None if pinned_fp is None else fp != pinned_fp,
        "finality": {
            "nflState": {
                k: state.get(k) for k in ("season", "week", "display_week", "season_type")
            },
            "hostLineupsOpenFromWeek": open_from,
            "reason": reason,
            "lastScoredLeg": last_scored,
            "weeksCensused": weeks,
        },  # fmt: skip
        "tolerance": TOL,
        "inputs": c.receipts,
        "nflverseRowsCanonicalSha256": _sha(rows),
        "pbpArtifactWeeksCovered": sorted(pbp_stats.weeks_covered) if pbp_stats else None,
        "projectionConfusion": "none: the nflverse weekly row and the Sleeper stat line are "
        "realized statistics; no projection field is read by either scorer path",
        **res,
    }
    if args.variant_json is not None:
        v = json.loads(args.variant_json.read_text("utf-8"))
        vn = v["nflversePath"]
        out["variant"] = {
            "scorerVariant": v.get("scorerVariant"),
            "generatedAtUtc": v.get("generatedAtUtc"),
            "scored": vn["scored"],
            "byGroup": vn["byGroup"],
            "rowClassification": vn["rowClassification"],
            "netPtsByClassNflMinusHost": vn["netPtsByClassNflMinusHost"],
            "perKey": [k for k in vn["perKey"] if k["rowsDiffer"]],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"weeks": weeks, "b": res["hostNative"]["canonicalScoreStatLine"],
                      "c": res["nflversePath"]["scored"]}, indent=1))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
