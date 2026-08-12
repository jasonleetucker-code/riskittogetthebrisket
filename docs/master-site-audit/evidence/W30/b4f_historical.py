#!/usr/bin/env python3
"""B4-FINAL — historical source depth and candidate sensitivity.

Two questions the fresh single-day pin cannot answer:

**Step 4 — is the boundary evidence-backed, or is it one day's number?**
The 903 boundary was justified as "the deepest rank any source publishes",
corroborated at ``src/api/source_history.py:352-353``. That corroboration
is a *comment*: 903 has no executable definition anywhere in the tree, and
today's board reaches only 898. A boundary set from a single observation
of a quantity that moves is not evidence-backed — so this replays the 17
compatible days and reports the distribution of the deepest observed rank
rather than trusting either number.

**Step 13 — does the candidate behave on boards other than today's?**
Same replay, both tail policies, per-day impact.

Methodology is the one #799 established and is not re-litigated here:
CURRENT code, HISTORICAL inputs, never historical code. The leak guard
from ``cd_historical_replay`` fails the run if a build reads current-tree
market data or touches the network — the latter matters because a build
derives ``tep_multiplier`` from a live Sleeper call, which unpinned would
silently apply *today's* league scoring to every historical board.

Writes ``b4f_historical_*.json``. Touches no #799 evidence file.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
OUT = Path(__file__).resolve().parent
W02 = ROOT / "docs" / "master-site-audit" / "evidence" / "W02"

_spec = importlib.util.spec_from_file_location("cd_replay", W02 / "cd_historical_replay.py")
R = importlib.util.module_from_spec(_spec)
sys.modules["cd_replay"] = R
_spec.loader.exec_module(R)

POSITION_BUCKETS = (
    ("QB", {"QB"}),
    ("RB", {"RB"}),
    ("WR", {"WR"}),
    ("TE", {"TE"}),
    ("DL/EDGE", {"DL", "EDGE", "DE", "DT"}),
    ("LB", {"LB"}),
    ("DB", {"DB", "CB", "S"}),
)


def bucket_for(position: str, asset_class: str) -> str:
    if asset_class == "pick":
        return "picks"
    pos = (position or "").upper()
    for name, members in POSITION_BUCKETS:
        if pos in members:
            return name
    return "other"


def usable_days() -> list[dict]:
    mat = json.loads((W02 / "cd_historical_matrix.json").read_text())
    return sorted(
        [r for r in mat["representativeDays"] if r["usable"] == "usable"],
        key=lambda r: r["day"],
    )


def build_at(entry: dict, dest: Path, tail: int | None):
    import src.api.data_contract as dc
    from src.canonical import tail_policy

    raw = json.loads(R.board_at(entry["sha"])[1])
    rp = R.Replay(entry["sha"], entry["timestamp"], dest)
    saved_ctx, saved_snap = dc._resolve_league_context, dc._RANK_SNAPSHOT_PATH
    saved_tail = tail_policy.TAIL_SATURATION_RANK
    dc._resolve_league_context = lambda *a, **k: dict(R.PINNED_LEAGUE_CONTEXT)
    dc._RANK_SNAPSHOT_PATH = dest / "data" / "snapshots" / "ranks_last.json"
    tail_policy.TAIL_SATURATION_RANK = tail
    try:
        with rp.guard(), contextlib.redirect_stdout(io.StringIO()):
            return dc.build_api_data_contract(raw, csv_root=dest)
    finally:
        dc._resolve_league_context, dc._RANK_SNAPSHOT_PATH = saved_ctx, saved_snap
        tail_policy.TAIL_SATURATION_RANK = saved_tail


def depths(contract) -> dict:
    per_source: dict[str, float] = defaultdict(float)
    per_source_hill: dict[str, float] = defaultdict(float)
    deepest = 0.0
    deepest_hill = 0.0
    n_hill = 0
    for r in contract.get("playersArray") or []:
        for k, m in (r.get("sourceRankMeta") or {}).items():
            if not isinstance(m, dict):
                continue
            e = m.get("effectiveRank")
            if not isinstance(e, (int, float)):
                continue
            e = float(e)
            per_source[str(k)] = max(per_source[str(k)], e)
            deepest = max(deepest, e)
            if str(m.get("valueContributionPath")) == "rank_hill":
                n_hill += 1
                deepest_hill = max(deepest_hill, e)
                per_source_hill[str(k)] = max(per_source_hill[str(k)], e)
    return {
        "deepestEffectiveRank": deepest,
        "deepestRankHill": deepest_hill,
        "rankHillObservations": n_hill,
        "perSourceMax": dict(per_source),
        "perSourceMaxRankHill": dict(per_source_hill),
    }


def compare(base, cand) -> dict:
    a = {str(r.get("displayName")): r for r in (base.get("playersArray") or [])}
    b = {str(r.get("displayName")): r for r in (cand.get("playersArray") or [])}
    names = sorted(set(a) & set(b))

    deltas, rank_moves = {}, {}
    for nm in names:
        va, vb = a[nm].get("rankDerivedValue"), b[nm].get("rankDerivedValue")
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va != vb:
            deltas[nm] = vb - va
        ra, rb = a[nm].get("canonicalConsensusRank"), b[nm].get("canonicalConsensusRank")
        if isinstance(ra, int) and isinstance(rb, int) and ra != rb:
            rank_moves[nm] = rb - ra

    absd = sorted(abs(v) for v in deltas.values())
    moves = sorted(abs(v) for v in rank_moves.values())

    def served(idx):
        return {nm for nm, r in idx.items() if r.get("canonicalConsensusRank") is not None}

    def topn(idx, n):
        rk = [
            (r["canonicalConsensusRank"], nm)
            for nm, r in idx.items()
            if isinstance(r.get("canonicalConsensusRank"), int)
        ]
        return {nm for _, nm in sorted(rk)[:n]}

    by_bucket = Counter()
    for nm in deltas:
        by_bucket[
            bucket_for(str(a[nm].get("position") or ""), str(a[nm].get("assetClass") or ""))
        ] += 1

    viol = sum(
        1
        for r in (cand.get("playersArray") or [])
        if isinstance(r.get("blendIntegrityViolation"), dict)
    )
    viol_base = sum(
        1
        for r in (base.get("playersArray") or [])
        if isinstance(r.get("blendIntegrityViolation"), dict)
    )
    return {
        "rowsCompared": len(names),
        "valuesChanged": len(deltas),
        "medianAbsChange": absd[len(absd) // 2] if absd else 0,
        "p90AbsChange": absd[int(0.9 * (len(absd) - 1))] if absd else 0,
        "maxAbsChange": absd[-1] if absd else 0,
        "ranksChanged": len(rank_moves),
        "medianRankMove": moves[len(moves) // 2] if moves else 0,
        "maxRankMove": moves[-1] if moves else 0,
        "servedCutChurn": len(served(a) ^ served(b)),
        "top200Changed": len(topn(a, 200) ^ topn(b, 200)),
        "byBucket": dict(by_bucket),
        "integrityViolationsBase": viol_base,
        "integrityViolationsCandidate": viol,
    }


def resolve_candidate(explicit: int | None) -> tuple[int | None, str]:
    """The boundary to analyse — from the canonical owner, never a literal.

    This argument used to default to ``903``: the value B4 selected before
    the 17-day replay refuted it (``idpTradeCalc`` reaches 904). Running
    the tool without ``--candidate`` therefore analysed a **superseded**
    boundary while labelling its output "the candidate" — the tool would
    have quietly disagreed with production and said nothing.

    Reading ``tail_policy`` means the default is whatever production
    actually serves. ``None`` there is the pre-B4 state, which has no
    candidate to analyse, so the caller is required to name one rather
    than have a number invented for them.
    """
    if explicit is not None:
        return explicit, "--candidate"
    from src.canonical.tail_policy import TAIL_SATURATION_RANK

    return TAIL_SATURATION_RANK, "tail_policy.TAIL_SATURATION_RANK"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--depths", action="store_true", help="step 4: historical source depth")
    ap.add_argument("--sensitivity", action="store_true", help="step 13: per-day candidate impact")
    ap.add_argument(
        "--candidate",
        type=int,
        default=None,
        help=(
            "boundary to analyse; defaults to the live "
            "tail_policy.TAIL_SATURATION_RANK so this tool cannot silently "
            "analyse a superseded value"
        ),
    )
    args = ap.parse_args()
    if not (args.depths or args.sensitivity):
        ap.error("pass --depths and/or --sensitivity")

    candidate, candidate_source = resolve_candidate(args.candidate)
    if args.sensitivity and candidate is None:
        ap.error(
            "--sensitivity needs a boundary to compare against, and "
            "tail_policy.TAIL_SATURATION_RANK is None (pre-B4 saturation). "
            "Pass --candidate explicitly."
        )

    days = usable_days()
    print(f"== B4-FINAL historical pass over {len(days)} compatible days ==")
    print("   CURRENT code + HISTORICAL inputs, leak-guarded, league context pinned")
    print(f"   candidate boundary {candidate} (from {candidate_source})\n")

    rows_out = []
    agg_source_max: dict[str, float] = defaultdict(float)
    hdr = f"   {'day':<12}{'deepest':>9}{'hill':>7}" + (
        f"{'changed':>9}{'medΔ':>7}{'maxΔ':>7}{'rank Δ':>8}{'churn':>7}{'viol':>6}"
        if args.sensitivity
        else ""
    )
    print(hdr)
    for d in days:
        with tempfile.TemporaryDirectory(prefix="b4f_hist_") as td:
            dest = Path(td)
            R.materialise(d, dest)
            base = build_at(d, dest, None)
            dep = depths(base)
            rec = {"day": d["day"], "sha": d["sha"], **dep}
            line = f"   {d['day']:<12}{int(dep['deepestEffectiveRank']):>9}{int(dep['deepestRankHill']):>7}"
            if args.sensitivity:
                cand = build_at(d, dest, candidate)
                cmp_ = compare(base, cand)
                rec["impact"] = cmp_
                line += (
                    f"{cmp_['valuesChanged']:>9}{cmp_['medianAbsChange']:>7}"
                    f"{cmp_['maxAbsChange']:>7}{cmp_['ranksChanged']:>8}"
                    f"{cmp_['servedCutChurn']:>7}{cmp_['integrityViolationsCandidate']:>6}"
                )
        for k, v in dep["perSourceMax"].items():
            agg_source_max[k] = max(agg_source_max[k], v)
        rows_out.append(rec)
        print(line)

    hist_max = max(r["deepestEffectiveRank"] for r in rows_out)
    hist_max_hill = max(r["deepestRankHill"] for r in rows_out)
    hist_min = min(r["deepestEffectiveRank"] for r in rows_out)
    print(f"\n   deepest effective rank across all days   {int(hist_max)} (min {int(hist_min)})")
    print(f"   deepest rank-Hill rank across all days   {int(hist_max_hill)}")
    if candidate is None:
        # --depths against a pre-B4 tree: there is no boundary to score,
        # and printing "headroom None" would read as a measurement.
        print("   candidate boundary                       (none — TAIL_SATURATION_RANK is None)")
    else:
        print(f"   candidate boundary                       {candidate} (from {candidate_source})")
        print(f"   headroom over historical max             {candidate - int(hist_max)}")
        print(
            f"   any day exceeding the candidate          "
            f"{[r['day'] for r in rows_out if r['deepestEffectiveRank'] > candidate] or 'none'}"
        )

    print("\n   per-source deepest rank ever observed across these days:")
    for k in sorted(agg_source_max, key=lambda x: -agg_source_max[x])[:8]:
        print(f"     {k:<26}{int(agg_source_max[k]):>6}")

    if args.sensitivity:
        tot = sum(r["impact"]["valuesChanged"] for r in rows_out)
        churn = sum(r["impact"]["servedCutChurn"] for r in rows_out)
        viol = sum(r["impact"]["integrityViolationsCandidate"] for r in rows_out)
        print(f"\n   total values changed across days   {tot}")
        print(f"   total served-cut churn             {churn}")
        print(f"   total integrity violations         {viol}")
        worst = max(rows_out, key=lambda r: r["impact"]["maxAbsChange"])
        print(
            f"   largest single-day max change      {worst['impact']['maxAbsChange']} on {worst['day']}"
        )

    payload = {
        "days": rows_out,
        "candidate": candidate,
        # Recorded so a reader of the JSON can tell whether the run scored
        # the live boundary or one supplied on the command line.
        "candidateSource": candidate_source,
        "historicalDeepest": hist_max,
        "historicalDeepestRankHill": hist_max_hill,
        "perSourceDeepestEver": dict(agg_source_max),
    }
    name = "b4f_historical_sensitivity.json" if args.sensitivity else "b4f_historical_depths.json"
    (OUT / name).write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
