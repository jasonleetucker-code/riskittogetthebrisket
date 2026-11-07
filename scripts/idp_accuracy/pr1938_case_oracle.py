"""Independent per-case check of PR #1938 against the HOST's own stat line.

Research/measurement only; writes only ``--out``.  The oracle is Sleeper's
published stat line (``/stats/nfl/regular/<season>/<week>``) -- the very line the
host scores, and which the host-native scorer reproduces exactly (CW-08:
4,833 / 4,833).  Nothing here reads the PR's evidence or its census code.

For each corrected case the check is in COUNT space, key by key: the stat line
``sleeper_stat_line_from_row`` emits for the nflverse row (with the
play-by-play supplement attached, exactly as ``weekly_points_from_rows`` does)
against the host's own count for the same key.  Both scorers are run -- the one
at ``--base-ref`` and the working tree -- so every case reports
``equal_before`` / ``equal_after`` / ``newly_wrong``.

Join: the identity owner (``src.identity.resolution.resolve_canonical_v2``) --
the GSIS rung, else its exact-name rungs (name + position + team); a guarded
fuzzy / initial rung or an ambiguity is refused, so no heuristic manufactures a
match.  Weeks: every finalized week (``--weeks``), which includes
weeks the PR's own evidence never saw (it measured 1-6).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.idp_accuracy.common import SEASON, Fetcher  # noqa: E402


def _num(v: Any) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _load_base(ref: str, scratch: Path):
    src = subprocess.run(
        ["git", "show", f"{ref}:src/nfl_data/realized_points.py"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    scratch.mkdir(parents=True, exist_ok=True)
    path = scratch / "_case_oracle_base_realized_points.py"
    path.write_text(src, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("_case_oracle_base_rp", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_case_oracle_base_rp"] = mod
    spec.loader.exec_module(mod)
    return mod


_FG_KEYS = ("fgmiss", "fgmiss_0_19", "fgmiss_20_29", "fgmiss_30_39", "fgmiss_40_49")
_FG_KEYS += ("fgmiss_50_59", "fgmiss_60p", "fgmiss_50p", "xpmiss")
_DEF_KEYS = (
    "idp_tkl_solo",
    "idp_tkl_ast",
    "idp_tkl_loss",
    "idp_sack",
    "idp_qb_hit",
    "idp_pass_def",
    "idp_int",
    "idp_ff",
    "idp_fum_rec",
    "idp_def_td",
    "idp_blk_kick",
    "idp_safe",
)
# The scorer's canonical spelling for two host aliases.
_ALIAS = {"idp_qb_hit": "idp_hit", "idp_pass_def": "idp_pd"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base-ref", default="origin/main")
    ap.add_argument("--season", type=int, default=SEASON)
    ap.add_argument("--weeks", type=int, nargs="+", default=list(range(1, 9)))
    ap.add_argument("--scratch", type=Path, default=REPO / "data" / "idp_accuracy" / "_pr1938")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    import src.nfl_data.realized_points as rp  # noqa: PLC0415
    from src.bdvm.baseline import normalize_weekly_row  # noqa: PLC0415
    from src.bdvm.context import TRUE_POSITION_MAP  # noqa: PLC0415
    from src.nfl_data import nflverse_direct  # noqa: PLC0415
    from src.nfl_data.pbp_weekly import attach_supplement, default_pbp_stats  # noqa: PLC0415

    base = _load_base(args.base_ref, args.scratch)
    f = Fetcher(offline=False)
    pdb = f.players()
    from src.identity.resolution import SleeperDirectoryIndex, resolve_canonical_v2  # noqa: PLC0415

    index = SleeperDirectoryIndex(dict(pdb))

    def resolve(r: dict) -> str | None:
        res = resolve_canonical_v2(index, gsis_id=str(r.get("player_id") or "").strip())
        if not res.resolved:
            res = resolve_canonical_v2(
                index,
                name=str(r.get("player_display_name") or r.get("player_name") or ""),
                position=str(r.get("position") or ""),
                team=str(r.get("team") or ""),
            )
            if res.resolved and res.method.startswith(("fuzzy_guarded", "initial_last_guarded")):
                return None
        return str(res.sleeper_id) if res.resolved and res.sleeper_id else None

    season = args.season
    host = {w: f.stats(w, season=season) or {} for w in args.weeks}
    pbp = default_pbp_stats(season)
    rows = [
        r
        for r in nflverse_direct.fetch_weekly_stats([season])
        if str(r.get("season_type") or "REG").upper() == "REG"
        and r.get("week") is not None
        and int(r["week"]) in args.weeks
    ]

    from src.ros.lineup import lineup_position  # noqa: PLC0415

    card = {
        k: float(v)
        for k, v in f.league()["scoring_settings"].items()
        if isinstance(v, (int, float))
    }
    # Points-level regression: the nflverse path (before / after) against the
    # host-native scorer over the host's own line, per Sleeper lineup group and
    # split into the weeks the PR's evidence measured (1-6) and the rest.
    points: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "withinTolBefore": 0, "withinTolAfter": 0, "newlyWrong": 0, "fixed": 0}
    )
    cases: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"n": 0, "equal_before": 0, "equal_after": 0, "newly_wrong": 0, "examples": []}
    )

    def tally(case: str, before: float, after: float, truth: float, ex: dict) -> None:
        c = cases[case]
        c["n"] += 1
        eb, ea = abs(before - truth) < 1e-9, abs(after - truth) < 1e-9
        c["equal_before"] += eb
        c["equal_after"] += ea
        c["newly_wrong"] += eb and not ea
        if not ea and len(c["examples"]) < 6:
            c["examples"].append({**ex, "before": before, "after": after, "host": truth})

    joined = 0
    for r in rows:
        sid = resolve(r)
        week = int(r["week"])
        line = host[week].get(sid) if sid else None
        if not line:
            continue
        joined += 1
        listing = str(r.get("position") or "").upper()
        pos = TRUE_POSITION_MAP.get(listing, listing)
        idp = rp._is_idp_position(pos)
        row = attach_supplement(normalize_weekly_row(r), pbp)
        lb = base.sleeper_stat_line_from_row(row, position=pos)
        la = rp.sleeper_stat_line_from_row(row, position=pos)
        sup = row.get(rp.PBP_SUPPLEMENT_ROW_KEY) or {}
        who = {
            "name": r.get("player_display_name"),
            "week": week,
            "nflversePos": listing,
            "sleeperPos": (pdb.get(sid) or {}).get("position"),
        }
        grp = "idp" if idp else "nonIdp"
        host_group = lineup_position(str((pdb.get(sid) or {}).get("position") or ""))
        host_rp = rp.compute_weekly_points(
            {**line, "player_id": sid, "season": season, "week": week},
            card,
            position=host_group,
            source="sleeper",
        )
        if host_rp is not None:
            pb = base.compute_weekly_points(row, card, position=pos).fantasy_points
            pa = rp.compute_weekly_points(row, card, position=pos).fantasy_points
            ok_b = abs(pb - host_rp.fantasy_points) <= 0.011
            ok_a = abs(pa - host_rp.fantasy_points) <= 0.011
            span = "weeks1to6" if week <= 6 else "weeks7plus"
            for bucket in (f"{span}/{host_group}", f"{span}/ALL", f"all/{host_group}", "all/ALL"):
                t = points[bucket]
                t["n"] += 1
                t["withinTolBefore"] += ok_b
                t["withinTolAfter"] += ok_a
                t["newlyWrong"] += ok_b and not ok_a
                t["fixed"] += ok_a and not ok_b

        def emitted(line_: dict, key: str) -> float:
            return _num(line_.get(_ALIAS.get(key, key)))

        # (1) special-teams solo tackles: rows where play-by-play saw one.
        if _num(sup.get("st_tkl_solo")) > 0:
            tally(
                f"st_subtraction_idp_tkl_solo/{grp}",
                emitted(lb, "idp_tkl_solo"),
                emitted(la, "idp_tkl_solo"),
                _num(line.get("idp_tkl_solo")),
                who,
            )
            cases[f"st_count_pbp_vs_host/{grp}"]["n"] += 1
            cases[f"st_count_pbp_vs_host/{grp}"]["equal_after"] += _num(
                sup.get("st_tkl_solo")
            ) == _num(line.get("st_tkl_solo"))
        # (2) tackle assists (the stated residual).
        if _num(r.get("def_tackle_assists")) > 0 or _num(line.get("idp_tkl_ast")) > 0:
            st = "stSnaps" if _num(line.get("st_snp")) > 0 else "noStSnaps"
            tally(
                f"assists_idp_tkl_ast/{grp}/{st}",
                emitted(lb, "idp_tkl_ast"),
                emitted(la, "idp_tkl_ast"),
                _num(line.get("idp_tkl_ast")),
                who,
            )
        # (3) blocked kicks: every miss key the host may charge.
        if _num(r.get("fg_blocked")) > 0 or _num(r.get("pat_blocked")) > 0:
            for key in _FG_KEYS:
                tally(
                    f"blocked_kick/{key}",
                    emitted(lb, key),
                    emitted(la, key),
                    _num(line.get(key)),
                    {**who, "fgBlockedList": r.get("fg_blocked_list")},
                )
        # (4) fumble-return TDs.
        if _num(r.get("fumble_recovery_tds")) > 0 or _num(line.get("idp_def_td")) > 0:
            tally(
                f"def_td/{grp}",
                emitted(lb, "idp_def_td"),
                emitted(la, "idp_def_td"),
                _num(line.get("idp_def_td")),
                {
                    **who,
                    "fumbleRecoveryTds": r.get("fumble_recovery_tds"),
                    "defTds": r.get("def_tds"),
                },
            )
        # (5) defensive stats on a NON-IDP-listed row, key by key.
        if not idp:
            for key in _DEF_KEYS:
                truth, a_, b_ = _num(line.get(key)), emitted(la, key), emitted(lb, key)
                if truth or a_ or b_:
                    tally(f"non_idp_defensive/{key}", b_, a_, truth, who)
        # (6) Sleeper FB vs nflverse RB/FB: first-down bonus keys.
        sleeper_pos = str((pdb.get(sid) or {}).get("position") or "").upper()
        if sleeper_pos == "FB" or listing == "FB":
            for key in ("bonus_fd_rb", "bonus_fd_wr", "bonus_fd_te", "bonus_fd_qb"):
                truth, a_, b_ = _num(line.get(key)), emitted(la, key), emitted(lb, key)
                if truth or a_ or b_:
                    tally(f"fb_position/{key}", b_, a_, truth, who)

    out = {
        "baseRef": args.base_ref,
        "season": season,
        "weeks": args.weeks,
        "scoringCard": "dynasty_main's CURRENT card for every season (a scorer-parity "
        "test: both paths score the same card; host awards are not read)",
        "joinedByIdentityOwner": joined,
        "nflverseRows": len(rows),
        "pointsVsHostNative": {k: dict(v) for k, v in sorted(points.items())},
        "cases": {k: dict(v) for k, v in sorted(cases.items())},
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, default=str) + "\n", encoding="utf-8")
    for k, v in sorted(points.items()):
        if k.endswith("/ALL") or k.startswith("all/"):
            print(f"points {k:24s} {v}")
    for k, v in sorted(cases.items()):
        print(
            f"{k:45s} n={v['n']:5d} eqBefore={v['equal_before']:5d} "
            f"eqAfter={v['equal_after']:5d} newlyWrong={v['newly_wrong']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
