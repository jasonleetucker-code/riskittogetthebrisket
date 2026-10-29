"""Measure the nflverse-path scorer fixes (IDPA-DEFECT-01/02/03) on pinned inputs.

Follow-up to ``scorer_reconcile.py`` (Deliverable A).  Research/measurement only:
imports production code, changes none of it, writes only
``docs/valuation/idp_accuracy/evidence/scorer_fix_measure.json``.

Four questions, each answered by running the SAME inputs through the scorer as it
stood at ``--base-ref`` (default: the Lane A branch this fix is stacked on) and as
it stands in the working tree:

0. **Lane A reconciliation, re-run.**  ``scorer_reconcile.reconcile_nflverse`` --
   the exact function that found the defects, on its cached inputs -- against the
   committed "before" in ``evidence/scorer_reconciliation.json``.
1. **Wide-sample regression.**  ``scorer_reconcile.py`` joins only players on a
   roster (3,095 player-weeks).  Special-teams specialists and backups are rarely
   rostered, so this joins EVERY player with a Sleeper stat line to his nflverse
   row (GSIS id, else a name unique on both sides that week) and scores the
   nflverse row with the production path against the host-native scorer over
   Sleeper's own stat line (verified exact against Sleeper's awarded points,
   3,710 / 3,710).  ``newlyWrongVsBase`` must be 0.
2. **Tackle census.**  Count-space evidence for the special-teams rule in
   ``realized_points._defensive_tackle_view`` -- code-independent.
3. **Served impact.**  ``src.bdvm.actuals.weekly_points_from_rows`` (the in-season
   blend's feed) before vs after, and the implied shift of BDVM's posterior mean,
   ``mu_post = w * mu_prior + (1 - w) * mu_recent`` (``src/bdvm/ros.py``), i.e.
   ``d(mu_post) = (1 - w) * d(mu_recent)`` whatever the projection is.

``stage1`` is the same fix with the special-teams subtraction withheld from
IDP-listed players (so IDP-listed tackle scoring is exactly the base behaviour);
it exists only to separate what IDPA-DEFECT-01/02/03 move from what the
IDP-listed special-teams rule moves.

Inputs are the cached Sleeper responses (``data/idp_accuracy/cache``), the pbp
artifact (``data/idp_accuracy/pbp_weekly``) and the live nflverse weekly file;
the canonical row hash is compared with the one pinned in
``evidence/scorer_reconciliation.json``.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.idp_accuracy.common import (  # noqa: E402
    OUT_DIR,
    PINNED_ARCHIVE,
    REPO,
    SEASON,
    WEEKS,
    Fetcher,
    sha256_bytes,
    sha256_file,
)

TOL = 0.01
OUT = OUT_DIR / "evidence" / "scorer_fix_measure.json"
BASE_EVIDENCE = OUT_DIR / "evidence" / "scorer_reconciliation.json"
PBP_DIR = REPO / "data/idp_accuracy/pbp_weekly"


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def load_base_scorer(ref: str):
    """``src/nfl_data/realized_points.py`` as of ``ref``, as an importable module."""
    src = subprocess.run(
        ["git", "show", f"{ref}:src/nfl_data/realized_points.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    path = REPO / "data/idp_accuracy/_base_realized_points.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_base_realized_points", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_base_realized_points"] = mod  # @dataclass resolves cls.__module__ here
    spec.loader.exec_module(mod)
    return mod, sha256_bytes(src.encode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-ref", default="origin/claude/idp-a-scoring-manifest")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    import src.bdvm.actuals as actuals  # noqa: PLC0415
    import src.nfl_data.realized_points as rp  # noqa: PLC0415
    from src.api.data_contract import build_api_data_contract  # noqa: PLC0415
    from src.bdvm.baseline import normalize_weekly_row  # noqa: PLC0415
    from src.bdvm.context import TRUE_POSITION_MAP  # noqa: PLC0415
    from src.bdvm.params import load_param_set  # noqa: PLC0415
    from src.bdvm.ros import ros_projection_weight  # noqa: PLC0415
    from src.nfl_data import nflverse_direct, pbp_weekly  # noqa: PLC0415
    from src.ros.lineup import lineup_position  # noqa: PLC0415
    from src.utils.name_clean import normalize_player_name  # noqa: PLC0415

    from scripts.idp_accuracy import scorer_reconcile as sr  # noqa: PLC0415

    base, base_sha = load_base_scorer(args.base_ref)
    final_fn = rp.compute_weekly_points
    final_view = rp._defensive_tackle_view

    f = Fetcher(offline=True)
    card = {
        k: float(v)
        for k, v in f.league()["scoring_settings"].items()
        if isinstance(v, (int, float))
    }
    pdb = f.players()
    stats = {w: f.stats(w) or {} for w in WEEKS}
    rows = [
        r
        for r in nflverse_direct.fetch_weekly_stats([SEASON])
        if str(r.get("season_type") or "REG").upper() == "REG"
        and r.get("week") is not None
        and int(r["week"]) in WEEKS
    ]
    rows_sha = sha256_bytes(json.dumps(rows, sort_keys=True, default=str).encode())
    pinned = json.loads(BASE_EVIDENCE.read_text())["nflverse"]["nflverseRowsCanonicalSha256"]
    pbp = pbp_weekly.default_pbp_stats(SEASON, out_dir=PBP_DIR)

    # ── join every Sleeper stat line to its nflverse row ─────────────────────
    gsis_to_sid = {str(m["gsis_id"]).strip(): s for s, m in pdb.items() if m.get("gsis_id")}
    sl_by_name: dict = defaultdict(list)
    for w in WEEKS:
        for sid in stats[w]:
            m = pdb.get(sid) or {}
            nm = m.get("full_name") or f"{m.get('first_name', '')} {m.get('last_name', '')}".strip()
            if nm:
                sl_by_name[(w, normalize_player_name(nm))].append(sid)
    nfl_by_name: dict = defaultdict(list)
    for r in rows:
        nm = str(r.get("player_display_name") or r.get("player_name") or "")
        nfl_by_name[(int(r["week"]), normalize_player_name(nm))].append(r)
    joined: list[tuple[dict, str]] = []
    no_join = 0
    for r in rows:
        sid = gsis_to_sid.get(str(r.get("player_id")).strip())
        if not sid:
            nm = str(r.get("player_display_name") or r.get("player_name") or "")
            k = (int(r["week"]), normalize_player_name(nm))
            if len(sl_by_name.get(k, [])) == 1 and len(nfl_by_name[k]) == 1:
                sid = sl_by_name[k][0]
        if sid and stats[int(r["week"])].get(sid) is not None:
            joined.append((r, sid))
        else:
            no_join += 1

    def host_points(r: dict, sid: str):
        group = lineup_position(str((pdb.get(sid) or {}).get("position") or ""))
        line = stats[int(r["week"])][sid]
        row = {**line, "player_id": sid, "season": SEASON, "week": int(r["week"])}
        return group, rp.compute_weekly_points(row, card, position=group, source="sleeper")

    def nflverse_points(fn: Callable, r: dict):
        listing = str(r.get("position") or "").upper()
        row = pbp_weekly.attach_supplement(normalize_weekly_row(r), pbp)
        return fn(row, card, position=TRUE_POSITION_MAP.get(listing, listing))

    host = {}
    for r, sid in joined:
        group, h = host_points(r, sid)
        if h is not None:
            host[(int(r["week"]), sid)] = (group, h.fantasy_points)

    def regression(fn: Callable) -> tuple[dict, set]:
        wrong: set = set()
        by_group: dict = defaultdict(lambda: [0, 0])
        for r, sid in joined:
            key = (int(r["week"]), sid)
            if key not in host:
                continue
            res = nflverse_points(fn, r)
            if res is None:
                continue
            group, hp = host[key]
            ok = abs(res.fantasy_points - hp) <= TOL
            by_group[group][0] += ok
            by_group[group][1] += 1
            if not ok:
                wrong.add(key)
        n = sum(v[1] for v in by_group.values())
        m = sum(v[0] for v in by_group.values())
        return (
            {
                "playerWeeks": n,
                "withinTol": m,
                "exactMatchRate": round(m / n, 6) if n else None,
                "byGroup": {g: {"withinTol": v[0], "n": v[1]} for g, v in sorted(by_group.items())},
            },
            wrong,
        )

    # ── 0. the Lane A reconciliation itself, re-run ──────────────────────────
    host_res = sr.reconcile_host(f, card, pdb)
    recs = host_res.pop("records")
    committed = json.loads(BASE_EVIDENCE.read_text())["nflverse"]

    def rostered(n: dict, *, with_exceptions: bool = False) -> dict:
        blk = {
            "census": n["census"],
            "withinTol": n["distribution"]["withinTol"],
            "n": n["distribution"]["n"],
            "exactMatchRate": n["distribution"]["exactMatchRate"],
            "maxAbs": n["distribution"]["maxAbs"],
            "byGroup": {
                g: {"withinTol": v["withinTol"], "n": v["n"], "exactMatchRate": v["exactMatchRate"]}
                for g, v in n["distributionByGroup"].items()
            },
            "defects": {k: {kk: vv for kk, vv in v.items() if kk != "description"}
                        for k, v in n["defects"].items()},
            "mismatchKeyCounts": n["mismatchKeyCounts"],
        }  # fmt: skip
        if with_exceptions:
            blk["exceptions"] = n["exceptions"]
        return blk

    def stage1_view(stat_row, *, idp_listed):
        if idp_listed:  # base behaviour for IDP-listed players
            return rp._tackle_view(stat_row)
        return final_view(stat_row, idp_listed=idp_listed)

    rp._defensive_tackle_view = stage1_view
    try:
        rostered_stage1 = rostered(sr.reconcile_nflverse(card, pdb, recs, f))
    finally:
        rp._defensive_tackle_view = final_view
    rostered_final = rostered(sr.reconcile_nflverse(card, pdb, recs, f), with_exceptions=True)

    reg_base, wrong_base = regression(base.compute_weekly_points)
    rp._defensive_tackle_view = stage1_view
    try:
        reg_stage1, wrong_stage1 = regression(final_fn)
    finally:
        rp._defensive_tackle_view = final_view
    reg_final, wrong_final = regression(final_fn)

    # ── tackle census (count space; independent of either scorer) ────────────
    cen: dict = {"idpListed": Counter(), "otherListed": Counter()}
    ast: dict = defaultdict(Counter)
    for r, sid in joined:
        listing = str(r.get("position") or "").upper()
        idp = rp._is_idp_position(TRUE_POSITION_MAP.get(listing, listing))
        line = stats[int(r["week"])][sid]
        solo, assists, _c = rp._tackle_view(r)
        sup = pbp.stats_for(r["player_id"], r["week"]) or {}
        pst = _num(sup.get("st_tkl_solo"))
        hs, hst, ha = (_num(line.get(k)) for k in ("idp_tkl_solo", "st_tkl_solo", "idp_tkl_ast"))
        c = cen["idpListed" if idp else "otherListed"]
        if solo or hs or hst or pst:
            c["playerWeeksWithSoloData"] += 1
            c["nflverseSoloEqualsHostIdpSolo"] += solo == hs
            c["equalOnlyAfterRemovingPbpSpecialTeams"] += solo != hs and solo - pst == hs
            c["pbpSpecialTeamsEqualsHostSt"] += pst == hst
        if assists:
            key = (
                "idp" if idp else "other",
                "stSnaps" if _num(line.get("st_snp")) > 0 else "noStSnaps",
            )
            ast[key]["playerWeeksWithNflverseAssists"] += 1
            ast[key]["nflverseEqualsHost"] += assists == ha
            ast[key]["nflverseExceedsHost"] += assists > ha
            ast[key]["nflverseBelowHost"] += assists < ha

    # ── served impact ─────────────────────────────────────────────────────────
    params = load_param_set()
    run_rows = rows

    def feed(fn: Callable):
        actuals.compute_weekly_points = fn
        try:
            return actuals.weekly_points_from_rows(
                run_rows, card, season=SEASON, name_normalizer=normalize_player_name, pbp_stats=pbp
            )
        finally:
            actuals.compute_weekly_points = final_fn

    cw0, before = feed(base.compute_weekly_points)
    rp._defensive_tackle_view = stage1_view
    try:
        _cw, stage1 = feed(final_fn)
    finally:
        rp._defensive_tackle_view = final_view
    cw1, after = feed(final_fn)
    pos_of: dict = {}
    disp_of: dict = {}
    for r in rows:
        nm = str(r.get("player_display_name") or r.get("player_name") or "").strip()
        k = normalize_player_name(nm)
        listing = str(r.get("position") or "").upper()
        pos_of[k], disp_of[k] = TRUE_POSITION_MAP.get(listing, listing), nm
    raw = json.loads(zipfile.ZipFile(PINNED_ARCHIVE).read("dynasty_data_2026-10-25.json"))
    board = {
        normalize_player_name(str(r.get("displayName") or "")): r
        for r in build_api_data_contract(raw).get("playersArray") or []
        if r.get("assetClass") != "pick"
    }

    def impact(new: dict) -> dict:
        changed = []
        summary: dict = defaultdict(
            lambda: {"playersWithSamples": 0, "changed": 0, "up": 0, "down": 0}
        )
        for k in new:
            summary[pos_of.get(k, "?")]["playersWithSamples"] += 1
        for k in sorted(set(before) | set(new)):
            b, a = dict(before.get(k, [])), dict(new.get(k, []))
            weeks = sorted(set(b) | set(a))
            if all(abs(b.get(w, 0.0) - a.get(w, 0.0)) < 1e-9 for w in weeks):
                continue
            n = len(a)
            is_idp = rp._is_idp_position(pos_of.get(k, ""))
            w_proj = ros_projection_weight(float(n), is_idp=is_idp, params=params)
            d_mean = sum(a.get(w, 0.0) - b.get(w, 0.0) for w in weeks) / n
            brow = board.get(k) or {}
            changed.append(
                {
                    "name": disp_of.get(k, k),
                    "pos": pos_of.get(k),
                    "weeksPlayed": n,
                    "dMeanPpg": round(d_mean, 4),
                    "dMuPost": round((1 - w_proj) * d_mean, 4),
                    "onBoard": bool(brow),
                    "boardRank": brow.get("canonicalConsensusRank"),
                }
            )
            s = summary[pos_of.get(k) or "?"]
            s["changed"] += 1
            s["up" if d_mean > 0 else "down"] += 1
        for s in summary.values():
            vals = [abs(c["dMuPost"]) for c in changed if summary[c["pos"] or "?"] is s]
            s["meanAbsDMuPost"] = round(sum(vals) / len(vals), 4) if vals else None
        ranked = [c for c in changed if c["boardRank"]]
        return {
            "playersWithSamples": len(new),
            "playersChanged": len(changed),
            "playersChangedOnBoard": sum(c["onBoard"] for c in changed),
            "playersChangedRankedOnBoard": len(ranked),
            "byPosition": {k: dict(v) for k, v in sorted(summary.items())},
            "top20RankedByAbsDMuPost": sorted(ranked, key=lambda c: -abs(c["dMuPost"]))[:20],
        }

    out = {
        "baseRef": args.base_ref,
        "baseScorerSha256": base_sha,
        "workingTreeScorerSha256": sha256_file(REPO / "src/nfl_data/realized_points.py"),
        "inputs": {
            "nflverseRegRowsWeeks1to6": len(rows),
            "nflverseRowsCanonicalSha256": rows_sha,
            "matchesPinnedLaneAHash": rows_sha == pinned,
            "pbpArtifactSha256": sha256_file(pbp_weekly.pbp_weekly_path(SEASON, out_dir=PBP_DIR)),
            "scoringCard": "dynasty_main 2026 (Sleeper scoring_settings, cached)",
        },
        "rostered": {
            "scope": "scorer_reconcile.reconcile_nflverse: the 3,095 rostered, name-joined "
            "player-weeks scored against Sleeper's awarded players_points",
            "before": rostered(committed),
            "stage1_defects_01_02_03_only": rostered_stage1,
            "final": rostered_final,
        },
        "wideSample": {
            "joinedPlayerWeeks": len(joined),
            "noJoin": no_join,
            "truth": "host-native scorer over Sleeper's own stat line",
            "base": reg_base,
            "stage1_defects_01_02_03_only": reg_stage1,
            "final": reg_final,
            "newlyWrongVsBase_stage1": len(wrong_stage1 - wrong_base),
            "newlyWrongVsBase_final": len(wrong_final - wrong_base),
            "fixedVsBase_final": len(wrong_base - wrong_final),
        },
        "tackleCensus": {k: dict(v) for k, v in cen.items()},
        "assistCensus": {"/".join(k): dict(v) for k, v in sorted(ast.items())},
        "servedImpact": {
            "currentWeek": cw1,
            "currentWeekBase": cw0,
            "paramsNPrior": {
                "offense": params["ros"]["n_prior_offense"],
                "idp": params["ros"]["n_prior_idp"],
            },
            "stage1_defects_01_02_03_only": impact(stage1),
            "final": impact(after),
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("inputs",)}, indent=1))
    ws = out["wideSample"]
    print("wide:", ws["joinedPlayerWeeks"], "base", ws["base"]["withinTol"], "stage1",
          ws["stage1_defects_01_02_03_only"]["withinTol"], "final", ws["final"]["withinTol"],
          "newlyWrong", ws["newlyWrongVsBase_final"])  # fmt: skip
    for tag in ("stage1_defects_01_02_03_only", "final"):
        si = out["servedImpact"][tag]
        print(
            tag,
            si["playersChanged"],
            "changed;",
            si["playersChangedRankedOnBoard"],
            "ranked on board",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
