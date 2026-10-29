"""Deliverable A — reconcile the production scorer against Sleeper's awarded points.

Owner directive ``docs/owner/IDP_VALUATION_ACCURACY_DIRECTIVE_2026-10-25.md`` §6B.
Research-only: imports production code, changes none of it, writes only
``docs/valuation/idp_accuracy/evidence/scorer_reconciliation.json``.

Two production scorer paths are reconciled, because both are live:

* **host-native** — ``compute_weekly_points(row, card, source="sleeper")`` over
  Sleeper's own weekly stat line.  This is the path Investigation B used for its
  "3,299 / 3,299 within 0.01" claim (``scripts/idp_replacement_research.py``
  lines ~446-469); ``reproduceInvestigationB`` re-runs its exact filter.
* **nflverse** (``--nflverse``) — the champion path the in-season BDVM blend uses
  (``src/bdvm/actuals.py``): nflverse ``stats_player_week`` row →
  ``normalize_weekly_row`` → play-by-play supplement → ``compute_weekly_points``
  (default ``source="nflverse"``), joined to Sleeper ids by GSIS id.

Truth is Sleeper's ``players_points`` from ``/league/<id>/matchups/<week>``, which
covers every player on every roster that week (starters AND bench in best ball).

A third, independent number is computed for every player-week: a naive
``Σ card[k] × line[k]`` written here from scratch (``oracle``).  It is NOT the
production scorer; it exists so a disagreement can be attributed (production
scorer vs data) rather than merely counted.

Public artifact rules: aggregates plus public NFL player names / Sleeper player
ids only.  No roster id, team, manager or user id is written.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.idp_accuracy.common import (  # noqa: E402
    LEAGUE_ID,
    IDP_GROUPS,
    LEAGUE_KEY,
    OUT_DIR,
    SEASON,
    WEEKS,
    Fetcher,
    sha256_bytes,
    sha256_file,
)
from src.nfl_data.realized_points import (  # noqa: E402
    HOST_DERIVED_TOTALS,
    compute_weekly_points,
)
from src.ros.lineup import (  # noqa: E402
    OBJECTIVE_REALIZED_POINTS,
    RosterPlayer,
    lineup_position,
    player_eligible_for_slot,
    resolve_starter_slots,
    solve_optimal_assignment,
)

TOL = 0.01  # Sleeper publishes 2 decimals; rounding alone is <= 0.005
OUT = OUT_DIR / "evidence" / "scorer_reconciliation.json"
_META = {"season", "week", "season_type", "player_id", "gp", "gs", "gms_active"}


def _num(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and math.isfinite(float(v)):
        return float(v)
    return None


def oracle_points(line: dict[str, Any], card: dict[str, float]) -> float:
    """Independent naive dot product, deliberately NOT the production code.

    Skips only precomputed fantasy totals and rank/rate fields, so any key the
    host publishes AND the card prices is paid exactly once at its listed rate.
    """
    tot = 0.0
    for k, v in line.items():
        if k in _META or k in HOST_DERIVED_TOTALS or k.startswith(("pos_rank_", "tm_")):
            continue
        x = _num(v)
        r = card.get(k)
        if x is None or not r:
            continue
        tot += r * x
    return tot


def _q(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    i = (len(s) - 1) * p / 100.0
    lo, hi = math.floor(i), math.ceil(i)
    return s[lo] + (s[hi] - s[lo]) * (i - lo)


def _dist(diffs: list[float]) -> dict[str, Any]:
    a = [abs(d) for d in diffs]
    return {
        "n": len(a),
        "withinTol": sum(1 for d in a if d <= TOL),
        "exactMatchRate": round(sum(1 for d in a if d <= TOL) / len(a), 6) if a else None,
        "maxAbs": round(max(a), 4) if a else None,
        "meanAbs": round(sum(a) / len(a), 6) if a else None,
        "p50Abs": round(_q(a, 50), 4) if a else None,
        "p99Abs": round(_q(a, 99), 4) if a else None,
        "p999Abs": round(_q(a, 99.9), 4) if a else None,
    }


# ── host-native path ──────────────────────────────────────────────────────────


def reconcile_host(f: Fetcher, card: dict[str, float], pdb: dict) -> dict[str, Any]:
    recs: list[dict[str, Any]] = []
    b_diffs: list[float] = []  # Investigation B's exact filter
    roster_entries_without_points = 0
    for w in WEEKS:
        stats = f.stats(w) or {}
        for m in f.matchups(w) or []:
            pp = m.get("players_points") or {}
            roster_entries_without_points += sum(
                1 for s in (m.get("players") or []) if str(s) not in pp
            )
            for sid, awarded in pp.items():
                sid = str(sid)
                meta = pdb.get(sid) or {}
                line = stats.get(sid)
                rec: dict[str, Any] = {
                    "week": w,
                    "sid": sid,
                    "name": meta.get("full_name")
                    or f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip(),
                    "pos": meta.get("position"),
                    "group": lineup_position(str(meta.get("position") or "")),
                    "awarded": float(awarded),
                    "hasStatLine": line is not None,
                    "gp": _num((line or {}).get("gp")),
                }
                if line is None:
                    rec["computed"] = None
                    rec["oracle"] = None
                else:
                    row = {**line, "player_id": sid, "season": SEASON, "week": w}
                    res = compute_weekly_points(row, card, position=rec["group"], source="sleeper")
                    rec["computed"] = None if res is None else round(res.fantasy_points, 6)
                    rec["oracle"] = round(oracle_points(line, card), 6)
                    if res is not None and float(line.get("gp") or 0) > 0:
                        b_diffs.append(abs(res.fantasy_points - float(awarded)))
                recs.append(rec)

    census: Counter = Counter()
    exceptions: list[dict[str, Any]] = []
    diffs: list[float] = []
    for r in recs:
        if r["computed"] is None:
            if not r["hasStatLine"] and abs(r["awarded"]) <= TOL:
                r["category"] = "no_stat_line_awarded_zero"
            elif not r["hasStatLine"]:
                r["category"] = "stat_source_gap"
            else:
                r["category"] = "scorer_refused_row"
        else:
            d = r["computed"] - r["awarded"]
            diffs.append(d)
            if abs(d) <= TOL:
                r["category"] = "match"
            elif abs(r["oracle"] - r["awarded"]) <= TOL:
                r["category"] = "scorer_bug"  # data agrees with host; our code does not
            elif abs(r["oracle"] - r["computed"]) <= TOL:
                r["category"] = "stat_line_disagrees_with_award"  # correction / timing
            else:
                r["category"] = "unexplained"
        census[r["category"]] += 1
        if r["category"] not in ("match", "no_stat_line_awarded_zero"):
            exceptions.append(r)

    # no-stat-line rows that ALSO carry gp/played elsewhere are impossible to
    # score; report how many of them had a stat line on another week.
    no_line_by_group = Counter(
        r["group"] for r in recs if r["category"] == "no_stat_line_awarded_zero"
    )
    by_group: dict[str, list[float]] = defaultdict(list)
    for r in recs:
        if r["computed"] is not None:
            by_group[r["group"]].append(r["computed"] - r["awarded"])
    return {
        "records": recs,
        "census": dict(census),
        "exceptions": exceptions,
        "distribution": _dist(diffs),
        "distributionByGroup": {g: _dist(v) for g, v in sorted(by_group.items())},
        "noStatLineAwardedZeroByGroup": dict(no_line_by_group),
        "rosterEntriesWithoutPlayersPoints": roster_entries_without_points,
        "independentOracleDisagreesWithProduction": sum(
            1 for r in recs if r["computed"] is not None and abs(r["oracle"] - r["computed"]) > TOL
        ),
        "reproduceInvestigationB": {
            "filter": "stat line present, gp > 0, scorer returned a result "
            "(scripts/idp_replacement_research.py L446-469)",
            "claimed": {"playerWeeks": 3299, "exactWithin0.01": 3299, "maxAbsDiff": 0.004},
            "reproduced": {
                "playerWeeks": len(b_diffs),
                "exactWithin0.01": sum(1 for d in b_diffs if d < 0.01),
                "maxAbsDiff": round(max(b_diffs), 4) if b_diffs else None,
            },
        },
    }


# ── stacking / event-structure evidence from awarded data ─────────────────────


def stacking_evidence(recs: list[dict], f: Fetcher, card: dict[str, float]) -> dict[str, Any]:
    """Does Sleeper pay TFL / QB hit ON TOP of a sack?  Test both hypotheses."""
    stats = {w: f.stats(w) or {} for w in WEEKS}
    stack_ok = nostack_ok = n = 0
    examples = []
    for r in recs:
        line = stats[r["week"]].get(r["sid"]) or {}
        sack = float(line.get("idp_sack") or 0)
        tfl = float(line.get("idp_tkl_loss") or 0)
        hit = float(line.get("idp_qb_hit") or 0)
        if sack <= 0 or (tfl <= 0 and hit <= 0):
            continue
        n += 1
        stacked = oracle_points(line, card)
        overlap = min(sack, tfl) * card.get("idp_tkl_loss", 0) + min(sack, hit) * card.get(
            "idp_qb_hit", 0
        )
        unstacked = stacked - overlap
        stack_ok += abs(stacked - r["awarded"]) <= TOL
        nostack_ok += abs(unstacked - r["awarded"]) <= TOL
        if len(examples) < 5:
            examples.append(
                {
                    "name": r["name"],
                    "week": r["week"],
                    "sack": sack,
                    "tkl_loss": tfl,
                    "qb_hit": hit,
                    "awarded": r["awarded"],
                    "stackedPrediction": round(stacked, 3),
                    "unstackedPrediction": round(unstacked, 3),
                }
            )
    # Sleeper's own lines: is a sack always also a TFL / a QB hit in the STAT feed?
    sack_rows = tfl_ge = hit_ge = 0
    for w in WEEKS:
        for sid, line in stats[w].items():
            s = float((line or {}).get("idp_sack") or 0)
            if s >= 1:
                sack_rows += 1
                tfl_ge += float(line.get("idp_tkl_loss") or 0) >= s
                hit_ge += float(line.get("idp_qb_hit") or 0) >= s
    return {
        "playerWeeksWithSackAndTflOrHit": n,
        "matchUnderStackingHypothesis": stack_ok,
        "matchUnderNoStackingHypothesis": nostack_ok,
        "examples": examples,
        "statFeed": {
            "playerWeeksWithSackGe1": sack_rows,
            "tklLossGeSack": tfl_ge,
            "qbHitGeSack": hit_ge,
            "note": "Sleeper's feed records a sack's TFL and QB hit as separate stats; "
            "the card then pays each key independently (stacking is a property of "
            "the STAT line, not of a scoring rule).",
        },
    }


# ── lineup / eligibility reconciliation ───────────────────────────────────────


def reconcile_lineups(f: Fetcher, league: dict, pdb: dict, recs: list[dict]) -> dict[str, Any]:
    slots, slot_src = resolve_starter_slots(
        roster_positions=league.get("roster_positions"), roster_settings=None
    )
    computed = {(r["week"], r["sid"]): r["computed"] for r in recs}
    team_weeks = 0
    awarded_total_match = 0
    computed_total_match = 0
    total_diffs_awarded: list[float] = []
    total_diffs_computed: list[float] = []
    starter_slots_checked = 0
    ineligible_by_our_rule: list[dict] = []
    off_primary_starts: Counter = Counter()
    for w in WEEKS:
        for m in f.matchups(w) or []:
            team_weeks += 1
            pp = {str(k): float(v) for k, v in (m.get("players_points") or {}).items()}
            sleeper_total = float(m.get("points") or 0)

            def pool(vals: dict[str, float | None]) -> list[RosterPlayer]:
                out = []
                for sid in (str(p) for p in (m.get("players") or [])):
                    meta = pdb.get(sid) or {}
                    out.append(
                        RosterPlayer(
                            player_id=sid,
                            canonical_name=sid,
                            position=str(meta.get("position") or "").upper(),
                            ros_value=vals.get(sid),
                            fantasy_positions=tuple(
                                str(p).upper() for p in (meta.get("fantasy_positions") or ()) if p
                            ),
                        )
                    )
                return out

            sol_a = solve_optimal_assignment(pool(pp), slots, objective=OBJECTIVE_REALIZED_POINTS)
            ours_a = sum(p.ros_value or 0 for p in sol_a.values())
            total_diffs_awarded.append(ours_a - sleeper_total)
            awarded_total_match += abs(ours_a - sleeper_total) <= 0.015
            cvals = {sid: computed.get((w, sid)) for sid in pp}
            # a rostered player with no stat line scored 0 at the host; keep it
            # UNKNOWN here (not 0) - it is simply not a candidate
            sol_c = solve_optimal_assignment(
                pool(cvals), slots, objective=OBJECTIVE_REALIZED_POINTS
            )
            ours_c = sum(p.ros_value or 0 for p in sol_c.values())
            total_diffs_computed.append(ours_c - sleeper_total)
            computed_total_match += abs(ours_c - sleeper_total) <= 0.015
            # Sleeper's own starters vs our eligibility predicate
            for i, sid in enumerate(m.get("starters") or []):
                sid = str(sid)
                if i >= len(slots) or sid in ("0", "", "None"):
                    continue
                meta = pdb.get(sid) or {}
                rp = RosterPlayer(
                    player_id=sid,
                    canonical_name=sid,
                    position=str(meta.get("position") or "").upper(),
                    ros_value=pp.get(sid),
                    fantasy_positions=tuple(
                        str(p).upper() for p in (meta.get("fantasy_positions") or ()) if p
                    ),
                )
                starter_slots_checked += 1
                if not player_eligible_for_slot(slots[i], rp):
                    ineligible_by_our_rule.append(
                        {
                            "week": w,
                            "slot": slots[i],
                            "name": meta.get("full_name"),
                            "position": meta.get("position"),
                            "fantasy_positions": meta.get("fantasy_positions"),
                        }
                    )
                prim = lineup_position(str(meta.get("position") or ""))
                if slots[i] in ("DL", "LB", "DB", "QB", "RB", "WR", "TE", "K") and prim != slots[i]:
                    off_primary_starts[f"{prim}->{slots[i]}"] += 1
    return {
        "slots": slots,
        "slotSource": slot_src,
        "teamWeeks": team_weeks,
        "optimalTotalFromAwardedPlayerPoints": {
            "matchWithin0.015": awarded_total_match,
            "dist": _dist(total_diffs_awarded),
            "meaning": "exact solver + our eligibility over Sleeper's own per-player points "
            "vs Sleeper's team total — isolates lineup solver/eligibility from scoring",
        },
        "optimalTotalFromComputedPlayerPoints": {
            "matchWithin0.015": computed_total_match,
            "dist": _dist(total_diffs_computed),
            "meaning": "the full production chain: our scorer + our solver vs Sleeper's total",
        },
        "sleeperStarterSlotsChecked": starter_slots_checked,
        "sleeperStartersIneligibleUnderOurRule": ineligible_by_our_rule,
        "startsOutsidePrimaryPosition": dict(off_primary_starts),
    }


def eligibility_census(f: Fetcher, pdb: dict) -> dict[str, Any]:
    rostered = {str(p) for r in f.rosters() for p in (r.get("players") or [])}
    combos: Counter = Counter()
    mismatched_primary = []
    for sid in rostered:
        meta = pdb.get(sid) or {}
        fps = tuple(meta.get("fantasy_positions") or ())
        if len(fps) > 1:
            combos["/".join(fps)] += 1
        fam = lineup_position(str(meta.get("position") or ""))
        if fps and fam not in {lineup_position(str(x)) for x in fps}:
            mismatched_primary.append(
                {"name": meta.get("full_name"), "position": meta.get("position"), "fp": fps}
            )
    return {
        "rosteredPlayersNow": len(rostered),
        "multiPositionCombos": dict(combos),
        "primaryPositionNotInFantasyPositions": mismatched_primary,
        "caveat": "fantasy_positions read from the CURRENT /players/nfl directory; Sleeper "
        "does not publish a dated eligibility history, so a mid-season eligibility change "
        "is invisible to this check.",
    }


# ── nflverse champion path (optional) ─────────────────────────────────────────


NFLVERSE_DEFECTS = {
    "IDPA-DEFECT-01": "nflverse normalization (sleeper_stat_line_from_row) drops def_* stats "
    "for a player whose listed position is not IDP; Sleeper pays idp_* rules to ANY player "
    "(e.g. a WR's solo tackle / forced fumble after a turnover)",
    "IDPA-DEFECT-02": "a BLOCKED field goal / PAT (nflverse fg_blocked / pat_blocked) is not "
    "scored as a miss; Sleeper counts it in fgmiss_<band> / xpmiss",
    "IDPA-DEFECT-03": "a defensive fumble-return TD (nflverse fumble_recovery_tds on an IDP "
    "row) is not mapped to idp_def_td",
    "IDPA-DEFECT-04": "a player Sleeper lists as FB but nflverse lists as RB has first downs "
    "scored under bonus_fd_rb (position taken from the provider listing); Sleeper derives "
    "bonus_fd_<pos> from ITS position, and the card prices no FB first down",
}


def _attribute_nflverse_defects(dk: dict, raw: dict, group: str) -> list[str]:
    """Name the scorer defect behind a host-vs-nflverse key difference, if any.

    A difference is a SCORER defect only when the nflverse row demonstrably
    carries the event and our normalization did not emit it; every other
    difference is the two stat providers disagreeing (gamebook solo/assist
    splits, QB-hit / PD charting, first downs, special-teams tackles).
    """

    def has(*cols: str) -> bool:
        return any((_num(raw.get(c)) or 0) > 0 for c in cols)

    out = set()
    for k, (host_v, nfl_v) in dk.items():
        if k.startswith("bonus_fd_") and host_v < nfl_v and group == "FB":
            out.add("IDPA-DEFECT-04")
            continue
        if host_v <= nfl_v:
            continue
        if k.startswith("idp_") and group not in IDP_GROUPS and has(
            "def_tackles_solo", "def_tackle_assists", "def_fumbles_forced", "def_interceptions",
            "def_pass_defended", "def_sacks", "def_qb_hits", "def_tackles_for_loss",
        ):  # fmt: skip
            out.add("IDPA-DEFECT-01")
        elif k.startswith("fgmiss") and has("fg_blocked"):
            out.add("IDPA-DEFECT-02")
        elif k == "xpmiss" and has("pat_blocked"):
            out.add("IDPA-DEFECT-02")
        elif k == "idp_def_td" and has("fumble_recovery_tds", "def_tds"):
            out.add("IDPA-DEFECT-03")
    return sorted(out)


def reconcile_nflverse(
    card: dict[str, float], pdb: dict, recs: list[dict], f: Fetcher
) -> dict[str, Any]:
    """The champion in-season path EXACTLY as ``bdvm_api`` runs it.

    ``weekly_points_from_rows`` (production) keyed by ``normalize_player_name``
    (production), with the play-by-play supplement built by
    ``persist_pbp_weekly`` (production).  The join back to Sleeper ids is the
    same name key applied to Sleeper's ``full_name``.
    """
    from src.bdvm.actuals import weekly_points_from_rows  # noqa: PLC0415
    from src.bdvm.baseline import normalize_weekly_row  # noqa: PLC0415
    from src.nfl_data import nflverse_direct, pbp_weekly  # noqa: PLC0415
    from src.bdvm.context import TRUE_POSITION_MAP  # noqa: PLC0415
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    rows = [
        r
        for r in nflverse_direct.fetch_weekly_stats([SEASON])
        if str(r.get("season_type") or "REG").upper() == "REG"
        and _num(r.get("week")) is not None
        and int(r["week"]) in WEEKS
    ]
    if not rows:
        return {"status": "UNAVAILABLE", "reason": "nflverse stats_player_week_2026 empty/404"}
    pbp_dir = Path(__file__).resolve().parents[2] / "data/idp_accuracy/pbp_weekly"
    pbp_dir.mkdir(parents=True, exist_ok=True)
    pbp_note = "loaded"
    if pbp_weekly.load_pbp_weekly(SEASON, out_dir=pbp_dir) is None:
        pbp_weekly.persist_pbp_weekly([SEASON], out_dir=pbp_dir, complete_through_week=max(WEEKS))
        pbp_note = "built"
    stats_obj = pbp_weekly.default_pbp_stats(SEASON, out_dir=pbp_dir)
    _cw, by_key = weekly_points_from_rows(
        rows, card, season=SEASON, name_normalizer=normalize_player_name, pbp_stats=stats_obj
    )
    weekly = {k: dict(v) for k, v in by_key.items()}
    raw_by: dict[tuple[str, int], dict] = {}
    for r in rows:
        nm = str(r.get("player_display_name") or r.get("player_name") or "").strip()
        raw_by[(normalize_player_name(nm), int(r["week"]))] = r
    host_stats = {w: f.stats(w) or {} for w in WEEKS}
    names_all = {k for k, _w in raw_by}

    census: Counter = Counter()
    diffs: list[float] = []
    all_by_group: dict[str, list[float]] = defaultdict(list)
    exceptions: list[dict] = []
    key_diff_counter: Counter = Counter()
    defect_points: Counter = Counter()
    defect_rows: Counter = Counter()
    for r in recs:
        key = normalize_player_name(str(r["name"] or ""))
        e = {"week": r["week"], "sid": r["sid"], "name": r["name"], "group": r["group"],
             "awarded": r["awarded"]}  # fmt: skip
        pts = (weekly.get(key) or {}).get(r["week"])
        if pts is None:
            if abs(r["awarded"]) <= TOL:
                cat = "no_nflverse_points_awarded_zero"
            elif key in names_all and key not in weekly:
                cat = "identity_name_collision_dropped"
            elif key not in names_all:
                cat = "identity_join_miss"
            else:
                cat = "stat_source_gap_week_missing"
        else:
            d = pts - r["awarded"]
            diffs.append(d)
            all_by_group[r["group"]].append(d)
            e["computed"] = round(pts, 4)
            e["diff"] = round(d, 4)
            if abs(d) <= TOL:
                cat = "match"
            elif r.get("category") == "match":
                cat = "nflverse_stat_disagrees_with_host"
                raw = raw_by.get((key, r["week"]))
                hrow = {**(host_stats[r["week"]].get(r["sid"]) or {}), "player_id": r["sid"],
                        "season": SEASON, "week": r["week"]}  # fmt: skip
                hres = compute_weekly_points(hrow, card, position=r["group"], source="sleeper")
                hl = {c[0]: c[1] for c in (hres.components if hres else ()) if c[2]}
                if raw is not None:
                    listing = str(raw.get("position") or "").upper()
                    nrow = pbp_weekly.attach_supplement(normalize_weekly_row(raw), stats_obj)
                    nres = compute_weekly_points(
                        nrow, card, position=TRUE_POSITION_MAP.get(listing, listing)
                    )
                    nl = {c[0]: c[1] for c in (nres.components if nres else ()) if c[2]}
                    e["nflversePositionListing"] = listing
                    dk = {
                        k: [hl.get(k, 0.0), nl.get(k, 0.0)]
                        for k in sorted(set(hl) | set(nl))
                        if abs(hl.get(k, 0.0) - nl.get(k, 0.0)) > 1e-9
                    }
                    e["keysDifferHostVsNflverse"] = dk
                    for k in dk:
                        key_diff_counter[k] += 1
                    defects = _attribute_nflverse_defects(dk, raw, r["group"])
                    e["attribution"] = defects or ["stat_source_disagreement"]
                    cat = "scorer_defect" if defects else "stat_source_disagreement"
                    for dd in defects:
                        defect_points[dd] += d
                        defect_rows[dd] += 1
            else:
                cat = "unexplained"
        e["category"] = cat
        census[cat] += 1
        if cat not in ("match", "no_nflverse_points_awarded_zero"):
            exceptions.append(e)
    by_group: dict[str, list[float]] = defaultdict(list)
    for e in exceptions:
        if "diff" in e:
            by_group[e["group"]].append(e["diff"])
    return {
        "status": "OK",
        "path": "src.bdvm.actuals.weekly_points_from_rows (the bdvm_api in-season blend) + "
        "pbp_weekly supplement; joined by src.utils.name_clean.normalize_player_name",
        "nflverseRegRowsWeeks1to6": len(rows),
        "nflverseRowsCanonicalSha256": sha256_bytes(
            json.dumps(rows, sort_keys=True, default=str).encode()
        ),
        "nflverseSource": "https://github.com/nflverse/nflverse-data/releases/download/"
        "stats_player/stats_player_week_2026.csv (fetched live; not cached by "
        "nflverse_direct — the canonical-JSON sha256 above pins the rows actually scored)",
        "pbpArtifactSha256": sha256_file(pbp_weekly.pbp_weekly_path(SEASON, out_dir=pbp_dir)),
        "pbpSupplement": pbp_note if stats_obj is not None else "UNAVAILABLE",
        "pbpWeeksCovered": sorted(stats_obj.weeks_covered) if stats_obj is not None else None,
        "census": dict(census),
        "distribution": _dist(diffs),
        "distributionByGroup": {g: _dist(v) for g, v in sorted(all_by_group.items())},
        "mismatchKeyCounts": dict(key_diff_counter.most_common()),
        "defects": {
            k: {
                "playerWeeks": defect_rows[k],
                "netPointsComputedMinusAwarded": round(v, 3),
                "description": NFLVERSE_DEFECTS[k],
            }  # fmt: skip
            for k, v in sorted(defect_points.items())
        },
        "mismatchDiffsByGroup": {g: _dist(v) for g, v in sorted(by_group.items())},
        "exceptions": exceptions,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--offline", action="store_true", help="use only the cached responses")
    ap.add_argument("--nflverse", action="store_true", help="also reconcile the nflverse path")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()
    f = Fetcher(offline=args.offline)
    league = f.league()
    assert str(league.get("league_id")) == LEAGUE_ID, "wrong league"
    card = {
        k: float(v)
        for k, v in (league.get("scoring_settings") or {}).items()
        if _num(v) is not None
    }
    pdb = f.players()
    host = reconcile_host(f, card, pdb)
    recs = host.pop("records")
    out: dict[str, Any] = {
        "league": {"key": LEAGUE_KEY, "sleeperId": LEAGUE_ID, "season": SEASON},
        "weeks": list(WEEKS),
        "tolerance": TOL,
        "truth": "Sleeper players_points from /league/<id>/matchups/<week> (every rostered "
        "player, starters and bench)",
        "hostNative": host,
        "stacking": stacking_evidence(recs, f, card),
        "lineups": reconcile_lineups(f, league, pdb, recs),
        "eligibility": eligibility_census(f, pdb),
        "inputs": f.receipts,
    }
    if args.nflverse:
        try:
            out["nflverse"] = reconcile_nflverse(card, pdb, recs, f)
        except Exception as exc:  # noqa: BLE001 — research: report, don't crash
            out["nflverse"] = {"status": "UNAVAILABLE", "reason": f"{type(exc).__name__}: {exc}"}
    # the per-record table is large; keep only exceptions + compact per-week counts
    per_week = Counter((r["week"], r["category"]) for r in recs)
    out["hostNative"]["perWeekCategory"] = {
        f"w{w}": {c: n for (ww, c), n in sorted(per_week.items()) if ww == w} for w in WEEKS
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(out, indent=1, sort_keys=False, default=str) + "\n", encoding="utf-8"
    )
    h = out["hostNative"]
    print(json.dumps({"census": h["census"], "dist": h["distribution"],
                      "B": h["reproduceInvestigationB"]["reproduced"]}, indent=1))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
