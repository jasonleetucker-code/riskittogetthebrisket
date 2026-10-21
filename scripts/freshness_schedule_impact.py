#!/usr/bin/env python3
"""Whole-board impact of the owner's freshness schedule (v2) against the v1 curve.

Owner directive 2026-10-19 §9.  Builds the SAME input twice through the real
entry point (``build_api_data_contract``) in one process — once with
``source_freshness_schedule_v2`` off (the v1 cadence curve, byte-identical to
the pre-change board) and once on — so the two boards share every input
(export, ``CSVs/site_raw``, ``data/scrape_state``) and every difference is
the schedule.  Reports what the directive asks to measure:

* players changed by class (offense / IDP / rookie / picks), median / p90 /
  p99 / max change, largest movers with the voters that moved them;
* position-level changes; top-50 / top-200 membership and movement;
* voting sources per player, per-source rows voted and mean applied weight,
  family weight totals, outlier-filter drops, single-source rows;
* confidence transitions; the two-way player (Travis Hunter);
* the two verifications: no vote rests on evidence older than 30 days, and a
  fresh, healthy source carries its full approved base weight (before any
  provider-family cap).

Usage::

    python scripts/freshness_schedule_impact.py --input exports/latest/dynasty_data_2026-10-19.json \\
        --json-out impact.json --md-out impact.md

Exit codes: 0 success (both verifications hold), 1 a verification failed,
2 usage / input error.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

FLAG_ENV = "RISKIT_FEATURE_SOURCE_FRESHNESS_SCHEDULE_V2"
TWO_WAY = ("Travis Hunter",)
STEPS = (1.0, 0.75, 0.5, 0.25)


def _read(path: Path) -> tuple[dict[str, Any], str]:
    blob = path.read_bytes()
    if path.suffix == ".gz":
        blob = gzip.decompress(blob)
    return json.loads(blob.decode("utf-8")), hashlib.sha256(blob).hexdigest()


def build(raw: dict[str, Any], *, v2: bool) -> dict[str, Any]:
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import feature_flags  # noqa: PLC0415

    os.environ[FLAG_ENV] = "1" if v2 else "0"
    feature_flags.reload()
    dc._SOURCE_WEIGHTING_CACHE.clear()
    try:
        return dc.build_api_data_contract(json.loads(json.dumps(raw)))
    finally:
        os.environ.pop(FLAG_ENV, None)
        feature_flags.reload()


def _klass(row: dict[str, Any]) -> str:
    if row.get("assetClass") == "pick":
        return "pick"
    if row.get("assetClass") == "idp":
        return "idp"
    return "rookie" if row.get("rookie") else "offense"


def _voters(row: dict[str, Any]) -> dict[str, float]:
    out = {}
    for k, m in (row.get("sourceRankMeta") or {}).items():
        w = m.get("appliedWeight") if isinstance(m, dict) else None
        if (
            isinstance(w, (int, float))
            and w > 0
            and m.get("contributedToBlend") is not False
            and not m.get("hampelDropped")
        ):
            out[k] = float(w)
    return out


def _pct(a: float, b: float) -> float:
    return abs(b - a) / a * 100.0 if a else 0.0


def _stats(xs: list[float]) -> dict[str, Any]:
    if not xs:
        return {"n": 0}
    s = sorted(xs)

    def q(p: float) -> float:
        return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]

    return {
        "n": len(s),
        "medianPct": round(statistics.median(s), 2),
        "p90Pct": round(q(0.90), 2),
        "p99Pct": round(q(0.99), 2),
        "maxPct": round(s[-1], 2),
    }


def _rank_map(rows: dict[str, dict[str, Any]], limit: int) -> dict[str, int]:
    return {
        n: int(r["canonicalConsensusRank"])
        for n, r in rows.items()
        if isinstance(r.get("canonicalConsensusRank"), int) and r["canonicalConsensusRank"] <= limit
    }


def _explain(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    vb, va = _voters(before), _voters(after)
    meta_b = before.get("sourceRankMeta") or {}
    meta_a = after.get("sourceRankMeta") or {}
    changed = {}
    for k in sorted(set(vb) | set(va)):
        if round(vb.get(k, 0.0), 4) != round(va.get(k, 0.0), 4):
            changed[k] = {
                "before": round(vb.get(k, 0.0), 4),
                "after": round(va.get(k, 0.0), 4),
                "value": (meta_a.get(k) or meta_b.get(k) or {}).get("valueContribution"),
            }
    return {
        "added": sorted(set(va) - set(vb)),
        "removed": sorted(set(vb) - set(va)),
        "weightChanges": changed,
        "outlierDroppedBefore": sorted(k for k, m in meta_b.items() if m.get("hampelDropped")),
        "outlierDroppedAfter": sorted(k for k, m in meta_a.items() if m.get("hampelDropped")),
    }


def verify(contract: dict[str, Any]) -> dict[str, Any]:
    """The two §9 verifications, from the board's own per-row stamps.

    * every vote's freshness factor is a schedule step (1, .75, .5, .25) and
      any reduced vote's stamped age is within 30 whole days;
    * a vote with no reduced freshness from a healthy, full-coverage source
      carries its base weight times its family adjustment (the family cap is
      the only further scaling).
    """
    status = {e["key"]: e for e in (contract.get("sourceVotingStatus") or {}).get("sources") or []}
    off_schedule, too_old, not_full = [], [], []
    votes = 0
    for row in contract.get("playersArray") or []:
        for k, m in (row.get("sourceRankMeta") or {}).items():
            if k not in _voters(row):
                continue
            votes += 1
            fresh = m.get("freshness", 1.0)
            if not any(abs(fresh - s) < 1e-9 for s in STEPS):
                off_schedule.append((row.get("displayName"), k, fresh))
            age = m.get("freshnessAgeHours")
            if age is not None and int(age // 24) > 30:
                too_old.append((row.get("displayName"), k, age))
            st = status.get(k) or {}
            factors = st.get("weightFactors") or {}
            if fresh == 1.0 and factors.get("health") == 1.0 and factors.get("coverage") == 1.0:
                base = float(m.get("baseWeight", m.get("weight", 1.0)) or 1.0)
                fam = float(m.get("familyAdjustment", 1.0) or 1.0)
                if abs(float(m["appliedWeight"]) - base * fam) > 1e-3:
                    not_full.append((row.get("displayName"), k, m["appliedWeight"], base, fam))
    stale_voting = [
        k for k, e in status.items() if e.get("voting") and (e.get("daysSinceUpdate") or 0) > 30
    ]
    return {
        "votesChecked": votes,
        "votesOffSchedule": off_schedule[:20],
        "votesOlderThan30Days": too_old[:20],
        "freshVotesBelowBaseTimesFamily": not_full[:20],
        "votingSourcesOlderThan30Days": stale_voting,
        "ok": not (off_schedule or too_old or not_full or stale_voting),
    }


def compare(before: dict[str, Any], after: dict[str, Any], *, top: int) -> dict[str, Any]:
    rb = {str(r.get("displayName")): r for r in before["playersArray"]}
    ra = {str(r.get("displayName")): r for r in after["playersArray"]}
    names = sorted(set(rb) & set(ra))
    by_class: dict[str, list[float]] = {}
    by_pos: dict[str, list[float]] = {}
    movers = []
    newly_unpriced, newly_priced = [], []
    for n in names:
        a, b = rb[n].get("rankDerivedValue"), ra[n].get("rankDerivedValue")
        if a and not b:
            newly_unpriced.append(n)
            continue
        if b and not a:
            newly_priced.append(n)
            continue
        if not a or not b or a == b:
            continue
        pct = _pct(a, b)
        by_class.setdefault(_klass(ra[n]), []).append(pct)
        by_pos.setdefault(str(ra[n].get("position") or "?"), []).append(pct)
        movers.append((pct, n, a, b))
    movers.sort(reverse=True)
    priced = {k: 0 for k in ("offense", "idp", "rookie", "pick")}
    for n in names:
        if rb[n].get("rankDerivedValue"):
            priced[_klass(rb[n])] += 1

    def top_block(limit: int) -> dict[str, Any]:
        mb, ma = _rank_map(rb, limit), _rank_map(ra, limit)
        common = set(mb) & set(ma)
        moves = [abs(mb[n] - ma[n]) for n in common]
        val = [_pct(rb[n]["rankDerivedValue"], ra[n]["rankDerivedValue"]) for n in common]
        return {
            "entered": sorted(set(ma) - set(mb)),
            "left": sorted(set(mb) - set(ma)),
            "rankMoved": sum(1 for m in moves if m),
            "maxRankMove": max(moves) if moves else 0,
            "maxValueChangePct": round(max(val), 2) if val else 0.0,
            "medianValueChangePct": round(statistics.median(val), 2) if val else 0.0,
        }

    def voters_hist(rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
        counts = [len(_voters(r)) for r in rows.values() if r.get("rankDerivedValue")]
        return {
            "mean": round(statistics.mean(counts), 3) if counts else None,
            "histogram": dict(sorted(Counter(counts).items())),
        }

    def per_source(c: dict[str, Any]) -> dict[str, Any]:
        out = {}
        for e in (c.get("sourceVotingStatus") or {}).get("sources") or []:
            out[e["key"]] = {
                "rows": e["playersContributing"] + e["picksContributing"],
                "effectiveWeight": e["effectiveWeight"],
                "meanAppliedWeight": e["meanAppliedWeight"],
                "status": e["status"],
                "outlierDropped": (e.get("notVotingRows") or {}).get("outlier_filter", 0),
            }
        return out

    def family_totals(rows: dict[str, dict[str, Any]], c: dict[str, Any]) -> dict[str, float]:
        fam = {
            e["key"]: e["family"] for e in (c.get("sourceVotingStatus") or {}).get("sources") or []
        }
        tot: dict[str, float] = {}
        for r in rows.values():
            for k, w in _voters(r).items():
                tot[fam.get(k, k)] = tot.get(fam.get(k, k), 0.0) + w
        return {k: round(v, 2) for k, v in sorted(tot.items())}

    conf = Counter(
        (str(rb[n].get("confidenceBucket")), str(ra[n].get("confidenceBucket")))
        for n in names
        if rb[n].get("confidenceBucket") != ra[n].get("confidenceBucket")
    )
    single = (
        sum(1 for r in rb.values() if r.get("isSingleSource")),
        sum(1 for r in ra.values() if r.get("isSingleSource")),
    )
    two_way = {}
    for n in TWO_WAY:
        if n in rb and n in ra:
            two_way[n] = {
                "before": rb[n].get("rankDerivedValue"),
                "after": ra[n].get("rankDerivedValue"),
                **_explain(rb[n], ra[n]),
            }
    return {
        "rowsCompared": len(names),
        "pricedBefore": priced,
        "changedByClass": {k: _stats(v) for k, v in sorted(by_class.items())},
        "changedAll": _stats([m[0] for m in movers]),
        "byPosition": {k: _stats(v) for k, v in sorted(by_pos.items())},
        "newlyUnpriced": newly_unpriced,
        "newlyPriced": newly_priced,
        "topMovers": [
            {
                "player": n,
                "before": a,
                "after": b,
                "changePct": round((b - a) / a * 100.0, 2),
                **_explain(rb[n], ra[n]),
            }
            for _pct_, n, a, b in movers[:top]
        ],
        "top50": top_block(50),
        "top200": top_block(200),
        "votersPerPlayer": {"before": voters_hist(rb), "after": voters_hist(ra)},
        "perSource": {"before": per_source(before), "after": per_source(after)},
        "familyAppliedWeightTotals": {
            "before": family_totals(rb, before),
            "after": family_totals(ra, after),
        },
        "singleSourceRows": {"before": single[0], "after": single[1]},
        "confidenceBucketTransitions": {f"{a}->{b}": n for (a, b), n in sorted(conf.items())},
        "twoWayPlayers": two_way,
    }


def render_md(report: dict[str, Any]) -> str:
    c = report["comparison"]
    lines = [
        f"Input `{report['input']}` (sha256 `{report['inputSha256'][:16]}`), board as of "
        f"`{report['scrapeTimestamp']}`. Before = v1 cadence curve (flag off, byte-identical to "
        "main); after = owner step schedule (flag on).",
        "",
        "| class | rows priced before | rows changed | median | p90 | p99 | max |",
        "|---|---|---|---|---|---|---|",
    ]
    for k in ("offense", "rookie", "idp", "pick"):
        s = c["changedByClass"].get(k, {"n": 0})
        lines.append(
            f"| {k} | {c['pricedBefore'].get(k, 0)} | {s.get('n', 0)} | {s.get('medianPct', 0)}% | "
            f"{s.get('p90Pct', 0)}% | {s.get('p99Pct', 0)}% | {s.get('maxPct', 0)}% |"
        )
    s = c["changedAll"]
    lines.append(
        f"| **all** | {sum(c['pricedBefore'].values())} | {s.get('n', 0)} | "
        f"{s.get('medianPct', 0)}% | {s.get('p90Pct', 0)}% | {s.get('p99Pct', 0)}% | "
        f"{s.get('maxPct', 0)}% |"
    )
    lines += [
        "",
        f"Newly unpriced: {', '.join(c['newlyUnpriced']) or 'none'}. "
        f"Newly priced: {', '.join(c['newlyPriced']) or 'none'}.",
        "",
        "| | entered | left | rank moved | max rank move | median value change | max value change |",
        "|---|---|---|---|---|---|---|",
    ]
    for k in ("top50", "top200"):
        t = c[k]
        lines.append(
            f"| {k} | {len(t['entered'])} | {len(t['left'])} | {t['rankMoved']} | "
            f"{t['maxRankMove']} | {t['medianValueChangePct']}% | {t['maxValueChangePct']}% |"
        )
    lines += [
        "",
        "| largest movers | before | after | change | what moved it |",
        "|---|---|---|---|---|",
    ]
    for m in c["topMovers"]:
        why = []
        if m["added"]:
            why.append("now voting: " + ", ".join(m["added"]))
        if m["removed"]:
            why.append("no longer voting: " + ", ".join(m["removed"]))
        ob, oa = set(m["outlierDroppedBefore"]), set(m["outlierDroppedAfter"])
        if ob - oa:
            why.append("outlier filter no longer drops: " + ", ".join(sorted(ob - oa)))
        if oa - ob:
            why.append("outlier filter now drops: " + ", ".join(sorted(oa - ob)))
        rew = [
            f"{k} {v['before']}->{v['after']}"
            for k, v in m["weightChanges"].items()
            if k not in m["added"] and k not in m["removed"]
        ]
        if rew:
            why.append("weights: " + ", ".join(rew))
        lines.append(
            f"| {m['player']} | {m['before']} | {m['after']} | {m['changePct']:+.1f}% | "
            f"{'; '.join(why)} |"
        )
    vb, va = c["votersPerPlayer"]["before"], c["votersPerPlayer"]["after"]
    lines += [
        "",
        f"Voting sources per priced player: mean {vb['mean']} -> {va['mean']}. "
        f"Single-source rows: {c['singleSourceRows']['before']} -> {c['singleSourceRows']['after']}.",
        "",
        "| source | rows voted (before -> after) | effective weight | mean applied weight | outlier drops |",
        "|---|---|---|---|---|",
    ]
    for k, a in c["perSource"]["after"].items():
        b = c["perSource"]["before"].get(k, {})
        lines.append(
            f"| `{k}` | {b.get('rows')} -> {a['rows']} | {b.get('effectiveWeight')} -> "
            f"{a['effectiveWeight']} | {b.get('meanAppliedWeight')} -> {a['meanAppliedWeight']} | "
            f"{b.get('outlierDropped')} -> {a['outlierDropped']} |"
        )
    fb, fa = c["familyAppliedWeightTotals"]["before"], c["familyAppliedWeightTotals"]["after"]
    lines += ["", "| family | total applied weight before | after |", "|---|---|---|"]
    for k in sorted(set(fb) | set(fa)):
        lines.append(f"| {k} | {fb.get(k, 0)} | {fa.get(k, 0)} |")
    lines += [
        "",
        "Confidence bucket transitions: "
        + (", ".join(f"{k} {v}" for k, v in c["confidenceBucketTransitions"].items()) or "none")
        + ".",
    ]
    for n, t in c["twoWayPlayers"].items():
        lines.append(
            f"Two-way player {n}: {t['before']} -> {t['after']}; weight changes "
            + ", ".join(f"{k} {v['before']}->{v['after']}" for k, v in t["weightChanges"].items())
            + "."
        )
    v = report["verification"]
    lines += [
        "",
        f"Verification ({v['votesChecked']} votes): off-schedule factors "
        f"{len(v['votesOffSchedule'])}; votes older than 30 days {len(v['votesOlderThan30Days'])}; "
        f"fresh healthy votes below base x family cap {len(v['freshVotesBelowBaseTimesFamily'])}; "
        f"voting sources older than 30 days {v['votingSourcesOlderThan30Days'] or 'none'}. "
        f"**{'PASS' if v['ok'] else 'FAIL'}**.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--input", required=True, help="raw export (JSON or .gz)")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--json-out")
    ap.add_argument("--md-out")
    args = ap.parse_args(argv)
    try:
        raw, sha = _read(Path(args.input))
    except (OSError, ValueError) as exc:
        print(f"freshness_schedule_impact: {exc}", file=sys.stderr)
        return 2
    before = build(raw, v2=False)
    after = build(raw, v2=True)
    report = {
        "input": args.input,
        "inputSha256": sha,
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "comparison": compare(before, after, top=args.top),
        "verification": verify(after),
    }
    text = json.dumps(report, indent=1, sort_keys=True, default=str) + "\n"
    if args.json_out:
        Path(args.json_out).write_text(text, encoding="utf-8")
    md = render_md(report)
    if args.md_out:
        Path(args.md_out).write_text(md, encoding="utf-8")
    if not args.json_out and not args.md_out:
        sys.stdout.write(md)
    return 0 if report["verification"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
