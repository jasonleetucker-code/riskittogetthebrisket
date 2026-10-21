#!/usr/bin/env python3
"""Compare the directive §6 boards extracted by ``oiv2_abcd_extract.py``.

    python oiv2_abcd_analyze.py X_PIN.json.gz REGRESSION_SET.json OUT_DIR

Writes ``abcd_<pin>.json`` (every comparison, machine-readable),
``MATERIAL_ROWS_<pin>.md`` (every |Δ| ≥ 5 % or |rank change| ≥ 25 row with
source-level attribution) and ``FOCUS_<pin>.md`` (full per-player source
tables). Pure reader: builds nothing, reads no repository state.
"""

from __future__ import annotations

import gzip
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path

PAIRS = [
    ("B", "A", "DLF IDP restored, incumbent filter (the documented defect)"),
    ("C", "A", "DLF IDP restored + V2 vs production"),
    ("C", "B", "V2 vs incumbent, both with DLF IDP restored"),
    ("D", "A", "V2 alone, DLF IDP still held (isolates the filter change)"),
    ("B'", "A", "D4 on, incumbent (the D4 defect)"),
    ("C'", "A", "D4 on + V2 vs production"),
    ("C'", "B'", "V2 vs incumbent, both with D4 on"),
    ("B''", "A", "DLF IDP restored + D4 on, incumbent"),
    ("C''", "A", "DLF IDP restored + D4 on + V2 vs production"),
    ("C''", "B''", "V2 vs incumbent, both with DLF IDP restored + D4 on"),
    ("C", "D", "DLF IDP activation impact with V2 already on"),
    ("C'", "D", "D4 activation impact with V2 already on"),
    ("C''", "D", "DLF IDP + D4 activation impact with V2 already on"),
    ("C", "Bnf", "V2 vs no per-row filter (same flags): every V2 refusal/drop"),
    ("D", "Anf", "V2 vs no per-row filter (DLF held)"),
    ("C'", "B'nf", "V2 vs no per-row filter (D4 on)"),
    ("C''", "B''nf", "V2 vs no per-row filter (DLF restored + D4 on)"),
]
NF = {
    "A": "Anf",
    "B": "Bnf",
    "C": "Bnf",
    "D": "Anf",
    "B'": "B'nf",
    "C'": "B'nf",
    "B''": "B''nf",
    "C''": "B''nf",
}
FOCUS = [
    "Trevin Wallace",
    "Myles Garrett",
    "Aidan Hutchinson",
    "CJ Allen",
    "T.J. Watt",
    "Josiah Trotter",
    "Will Anderson",
    "Danielle Hunter",
    "Jared Verse",
    "Theo Johnson",
    "Travis Hunter",
]
ORIGINAL_MOVERS = [
    "Trevin Wallace",
    "Myles Garrett",
    "CJ Allen",
    "T.J. Watt",
    "Josiah Trotter",
    "Will Anderson",
    "Aidan Hutchinson",
    "Danielle Hunter",
]
DLF_VALUES = "dlfValuesSfTep"
FLAG_SOURCES = ("dlfIdp", "dlfRookieIdp", DLF_VALUES)  # observations the two DLF flags add
MAT_PCT = 0.05
MAT_RANK = 25
VALUE_EPS = 0.005  # a vote value "changed" when it moved by more than 0.5 %


def val(r):
    v = (r or {}).get("rankDerivedValue")
    return float(v) if isinstance(v, (int, float)) and v > 0 else None


def obs_status(row, source):
    """'voting' | exclusion reason | 'v2_<status>:<reason>' (refused before
    pricing, stamped only in row.sourceIntegrity) | 'not_observed' | 'row_absent'."""
    if row is None:
        return "row_absent"
    m = row["votes"].get(source)
    if m is not None:
        return m["status"] or "voting"
    s = (row.get("sourceIntegrity") or {}).get(source) or {}
    if s.get("status") not in (None, "voting"):
        return f"v2_{s.get('status')}:{s.get('primaryReason')}"
    return "not_observed"


def vote_value(row, source):
    m = (row or {}).get("votes", {}).get(source) or {}
    v = m.get("valueContribution")
    return v if isinstance(v, (int, float)) else None


def integ(row, source):
    m = (row or {}).get("votes", {}).get(source) or {}
    i = m.get("integrity")
    if i:
        return i
    return ((row or {}).get("sourceIntegrity") or {}).get(source)


def q(xs, p):
    if not xs:
        return None
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p * len(s)))], 4)


def stats(xs):
    moved = [x for x in xs if x > 0]
    return {
        "rows": len(xs),
        "moved": len(moved),
        "median": round(statistics.median(xs), 4) if xs else None,
        "p90": q(xs, 0.9),
        "p99": q(xs, 0.99),
        "max": round(max(xs), 4) if xs else None,
        "medianMoved": round(statistics.median(moved), 4) if moved else None,
    }


def cls(r):
    return r.get("assetClass") or "?"


def voting_families(row):
    return sorted({m["family"] for m in row["votes"].values() if m["status"] is None})


def compare(boards, x, y):
    X, Y = boards[x]["rows"], boards[y]["rows"]
    names = sorted(set(X) | set(Y))
    # ── votes retained / rejected by source and class ──
    census = {}
    for b, R in ((y, Y), (x, X)):
        c = defaultdict(Counter)
        for n, r in R.items():
            for k in set(r["votes"]) | set((r.get("sourceIntegrity") or {})):
                c[f"{cls(r)}|{k}"][obs_status(r, k)] += 1
        census[b] = {k: dict(v) for k, v in sorted(c.items())}
    # ── every changed exclusion reason ──
    changes = []
    flag_added = defaultdict(list)
    trans = Counter()
    reason_trans = Counter()
    vote_value_changes = 0
    for n in names:
        ry, rx = Y.get(n), X.get(n)
        r0 = rx or ry
        srcs = set()
        for r in (ry, rx):
            if r:
                srcs |= set(r["votes"]) | set(r.get("sourceIntegrity") or {})
        for k in sorted(srcs):
            sy, sx = obs_status(ry, k), obs_status(rx, k)
            vy, vx = vote_value(ry, k), vote_value(rx, k)
            if sy != sx:
                trans[f"{cls(r0)}|{k}|{sy} -> {sx}"] += 1
                if (
                    k in FLAG_SOURCES
                    and sy in ("not_observed", "row_absent")
                    or k in FLAG_SOURCES
                    and sx in ("not_observed", "row_absent")
                ):
                    flag_added[k].append([n, vx if vx is not None else vy, sy, sx])
                    continue
                changes.append(
                    {
                        "row": n,
                        "assetClass": cls(r0),
                        "position": r0.get("position"),
                        "source": k,
                        "family": ((rx or ry)["votes"].get(k) or {}).get("family", k),
                        "from": sy,
                        "to": sx,
                        "voteFrom": vy,
                        "voteTo": vx,
                        "integrityTo": (integ(rx, k) or {}).get("primaryReason"),
                    }
                )
            elif sy == "voting" and vy and vx and abs(vx / vy - 1) > VALUE_EPS:
                vote_value_changes += 1
            iy = (integ(ry, k) or {}).get("primaryReason")
            ix = (integ(rx, k) or {}).get("primaryReason")
            if iy != ix:
                reason_trans[f"{k}|{iy} -> {ix}"] += 1
    # ── values, ranks, confidence, coverage, families ──
    by_class = defaultdict(list)
    by_pos = defaultdict(list)
    conf = Counter()
    axes = Counter()
    rank_moves = []
    gained, lost = [], []
    fam_count_changes = Counter()
    material = []
    for n in names:
        ry, rx = Y.get(n), X.get(n)
        if not ry or not rx:
            continue
        vy, vx = val(ry), val(rx)
        c = cls(rx)
        if vy and vx:
            d = abs(vx / vy - 1)
            by_class[c].append(d)
            by_pos[f"{c}:{rx.get('position')}"].append(d)
        elif vy and not vx:
            lost.append(n)
        elif vx and not vy:
            gained.append(n)
        by, bx = ry.get("confidenceBucket"), rx.get("confidenceBucket")
        if by != bx:
            conf[f"{c}:{by}->{bx}"] += 1
        ay, ax = ry.get("confidenceAxes") or {}, rx.get("confidenceAxes") or {}
        for a in sorted(set(ay) | set(ax)):
            if ay.get(a) != ax.get(a):
                axes[f"{c}:{a}:{ay.get(a)}->{ax.get(a)}"] += 1
        ky, kx = ry.get("canonicalConsensusRank"), rx.get("canonicalConsensusRank")
        dr = (kx - ky) if isinstance(ky, int) and isinstance(kx, int) else None
        if dr:
            rank_moves.append(abs(dr))
        fy, fx = len(voting_families(ry)), len(voting_families(rx))
        if fy != fx:
            fam_count_changes[f"{c}:{fy}->{fx}"] += 1
        pct = (vx / vy - 1) if (vy and vx) else None
        rank_mat = (dr is not None and abs(dr) >= MAT_RANK) or (
            (ky is None) != (kx is None) and (ky or kx)
        )
        if (pct is not None and abs(pct) >= MAT_PCT) or rank_mat or (bool(vy) != bool(vx)):
            material.append(attribute(boards, x, y, n, pct, dr))
    members = {}
    for N in (24, 50, 100, 200):
        sy = {
            n
            for n, r in Y.items()
            if isinstance(r.get("canonicalConsensusRank"), int) and r["canonicalConsensusRank"] <= N
        }
        sx = {
            n
            for n, r in X.items()
            if isinstance(r.get("canonicalConsensusRank"), int) and r["canonicalConsensusRank"] <= N
        }
        members[f"top{N}"] = {"entered": sorted(sx - sy), "left": sorted(sy - sx)}
    cov = {}
    for b, R in ((y, Y), (x, X)):
        cs, cf = Counter(), Counter()
        for r in R.values():
            for k, m in r["votes"].items():
                if m["status"] is None:
                    cs[f"{cls(r)}|{k}"] += 1
            for f in voting_families(r):
                cf[f"{cls(r)}|{f}"] += 1
        cov[b] = {
            "sourceRowsVoting": dict(sorted(cs.items())),
            "familyRowsRepresented": dict(sorted(cf.items())),
        }
    cov_delta = {
        "sourceRowsVoting": {
            k: cov[x]["sourceRowsVoting"].get(k, 0) - cov[y]["sourceRowsVoting"].get(k, 0)
            for k in sorted(set(cov[x]["sourceRowsVoting"]) | set(cov[y]["sourceRowsVoting"]))
            if cov[x]["sourceRowsVoting"].get(k, 0) != cov[y]["sourceRowsVoting"].get(k, 0)
        },
        "familyRowsRepresented": {
            k: cov[x]["familyRowsRepresented"].get(k, 0) - cov[y]["familyRowsRepresented"].get(k, 0)
            for k in sorted(
                set(cov[x]["familyRowsRepresented"]) | set(cov[y]["familyRowsRepresented"])
            )
            if cov[x]["familyRowsRepresented"].get(k, 0)
            != cov[y]["familyRowsRepresented"].get(k, 0)
        },
    }
    material.sort(key=lambda m: (-(abs(m["change"]) if m["change"] is not None else 9), m["row"]))
    return {
        "votesByClassSource": census,
        "statusTransitions": dict(sorted(trans.items())),
        "changedExclusions": changes,
        "changedExclusionCount": len(changes),
        "flagAddedObservations": {
            k: {"count": len(v), "byStatus": dict(Counter(e[3] for e in v)), "rows": v}
            for k, v in sorted(flag_added.items())
        },
        "integrityReasonTransitions": dict(sorted(reason_trans.items())),
        "votesValueChangedOver0p5pct": vote_value_changes,
        "valueChangesByClass": {c: stats(v) for c, v in sorted(by_class.items())},
        "valueChangesByPosition": {c: stats(v) for c, v in sorted(by_pos.items())},
        "rowsGainedValue": gained,
        "rowsLostValue": lost,
        "rankChanges": {
            "rowsRankChanged": len(rank_moves),
            "atLeast25": sum(1 for r in rank_moves if r >= MAT_RANK),
            "max": max(rank_moves) if rank_moves else 0,
        },
        "topMembership": members,
        "confidenceBucketTransitions": dict(sorted(conf.items())),
        "confidenceAxisTransitions": dict(sorted(axes.items())),
        "coverageDelta": cov_delta,
        "votingFamilyCountTransitions": dict(sorted(fam_count_changes.items())),
        "materialRows": material,
    }


def attribute(boards, x, y, n, pct, dr):
    X, Y = boards[x]["rows"], boards[y]["rows"]
    ry, rx = Y.get(n), X.get(n)
    srcs = sorted(
        set(ry["votes"])
        | set(rx["votes"])
        | set(ry.get("sourceIntegrity") or {})
        | set(rx.get("sourceIntegrity") or {})
    )
    status_changes, value_changes = [], []
    for k in srcs:
        sy, sx = obs_status(ry, k), obs_status(rx, k)
        vy, vx = vote_value(ry, k), vote_value(rx, k)
        if sy != sx:
            status_changes.append({"source": k, "from": sy, "to": sx, "voteFrom": vy, "voteTo": vx})
        elif sy == "voting" and vy and vx and abs(vx / vy - 1) > VALUE_EPS:
            value_changes.append(
                {"source": k, "from": vy, "to": vx, "change": round(vx / vy - 1, 4)}
            )
    value_changes.sort(key=lambda e: -abs(e["change"]))
    steps = None
    if y == "A" and x in NF:
        a, anf, nf = val(ry), val(boards["Anf"]["rows"].get(n)), val(boards[NF[x]]["rows"].get(n))
        xx = val(rx)

        def lg(p, q_):
            return round(math.log(q_ / p), 4) if p and q_ else None

        steps = {"A->Anf (stand the incumbent filter down)": lg(a, anf)}
        if NF[x] != "Anf":
            steps[f"Anf->{NF[x]} (the DLF flag change, no filter)"] = lg(anf, nf)
        steps[f"{NF[x]}->{x} (the filter under test)"] = lg(nf, xx)
    notes = []
    tw = rx.get("twoWayPlayerBoost")
    if tw:
        notes.append(
            f"two-way boost: alt {tw.get('altFamily')} {tw.get('altFamilyValue')} vs primary {tw.get('primaryFamilyValue')}"
        )
    if rx.get("pickValueProvenance") or ry.get("pickValueProvenance"):
        notes.append(
            f"pick provenance {((ry.get('pickValueProvenance') or {}).get('class'))} -> {((rx.get('pickValueProvenance') or {}).get('class'))}"
        )
    if not status_changes and not value_changes:
        notes.append(
            "no vote on this row changed status or value: the move comes from a post-blend stage or ranking renumbering"
        )
    return {
        "row": n,
        "assetClass": cls(rx),
        "position": rx.get("position"),
        "from": val(ry),
        "to": val(rx),
        "change": round(pct, 4) if pct is not None else None,
        "rankFrom": ry.get("canonicalConsensusRank"),
        "rankTo": rx.get("canonicalConsensusRank"),
        "rankChange": dr,
        "confidence": f"{ry.get('confidenceBucket')}->{rx.get('confidenceBucket')}",
        "voteStatusChanges": status_changes,
        "voteValueChanges": value_changes[:6],
        "voteValueChangesCount": len(value_changes),
        "logSteps": steps,
        "notes": notes,
    }


def v2_refusals(boards, b):
    out = []
    for n, r in boards[b]["rows"].items():
        for k, s in sorted((r.get("sourceIntegrity") or {}).items()):
            if (s or {}).get("status") in (None, "voting"):
                continue
            nfrow = boards[NF[b]]["rows"].get(n)
            ident = s.get("identity") or {}
            out.append(
                {
                    "row": n,
                    "assetClass": cls(r),
                    "position": r.get("position"),
                    "rowTeam": r.get("team"),
                    "source": k,
                    "status": s.get("status"),
                    "primaryReason": s.get("primaryReason"),
                    "category": s.get("category"),
                    "identityVerdict": ident.get("verdict"),
                    "entryTeam": ident.get("entryTeam"),
                    "evidence": ident.get("evidence"),
                    "statusWithoutV2": obs_status(nfrow, k),
                    "voteWithoutV2": vote_value(nfrow, k),
                    "rowValueWithoutV2": val(nfrow),
                    "rowValueV2": val(r),
                }
            )
        for k, m in sorted(r["votes"].items()):
            i = m.get("integrity") or {}
            if i.get("status") not in (None, "voting"):
                out.append(
                    {
                        "row": n,
                        "assetClass": cls(r),
                        "position": r.get("position"),
                        "source": k,
                        "status": i.get("status"),
                        "primaryReason": i.get("primaryReason"),
                        "category": i.get("category"),
                        "vote": m.get("valueContribution"),
                    }
                )
    return sorted(out, key=lambda e: (e["row"], e["source"]))


def kept_dissent(boards, b):
    out = []
    for n, r in boards[b]["rows"].items():
        for k, m in sorted(r["votes"].items()):
            i = m.get("integrity") or {}
            if i.get("primaryReason") == "kept_dissent":
                out.append(
                    {
                        "row": n,
                        "assetClass": cls(r),
                        "position": r.get("position"),
                        "source": k,
                        "vote": m.get("valueContribution"),
                        "rowValue": val(r),
                        "layerC": i.get("layerC"),
                    }
                )
    return sorted(out, key=lambda e: (e["assetClass"], e["row"], e["source"]))


def regression31(boards, pairs):
    out = []
    for p in pairs:
        n, k = p["row"], p["source"]
        e = {"row": n, "source": k}
        for b in ("A", "Anf", "B", "Bnf", "C", "D", "C''", "B''"):
            r = boards[b]["rows"].get(n)
            e[b] = {"status": obs_status(r, k), "vote": vote_value(r, k), "rowValue": val(r)}
        r = boards["C"]["rows"].get(n) or {}
        e["v2Integrity"] = integ(r, k)
        m = r.get("votes", {}).get(k) or {}
        e["provenance"] = {
            f: m.get(f)
            for f in (
                "method",
                "rawRank",
                "effectiveRank",
                "rankCoordinatePool",
                "valueContributionPath",
                "appliedWeight",
                "family",
            )
        }
        others = {
            s: v.get("valueContribution")
            for s, v in r.get("votes", {}).items()
            if s != k and v["status"] is None
        }
        e["otherVotingSourcesInC"] = others
        if others and e["C"]["vote"]:
            u = lambda v: math.log(v)  # noqa: E731
            e["nearestOtherLogDistanceInC"] = round(
                min(abs(u(e["C"]["vote"]) - u(v)) for v in others.values() if v), 4
            )
        e["droppedInB"] = e["B"]["status"] == "filter_dropped"
        e["retainedInC"] = e["C"]["status"] == "voting"
        e["retainedInCpp"] = e["C''"]["status"] == "voting"
        e["retainedInD"] = e["D"]["status"] == "voting"
        out.append(e)
    return out


def d4_set(boards, base, d4board, v2boards):
    out = []
    for n, rb in sorted(boards[d4board]["rows"].items()):
        if cls(rb) != "offense":
            continue
        ra = boards[base]["rows"].get(n)
        for k in sorted(rb["votes"]):
            if k == DLF_VALUES:
                continue
            if obs_status(rb, k) == "filter_dropped" and obs_status(ra, k) != "filter_dropped":
                e = {
                    "row": n,
                    "source": k,
                    base: {
                        "status": obs_status(ra, k),
                        "vote": vote_value(ra, k),
                        "rowValue": val(ra),
                    },
                    d4board: {
                        "status": obs_status(rb, k),
                        "vote": vote_value(rb, k),
                        "rowValue": val(rb),
                    },
                    "dlfValuesVote": vote_value(rb, DLF_VALUES),
                }
                for b in v2boards:
                    r = boards[b]["rows"].get(n)
                    e[b] = {
                        "status": obs_status(r, k),
                        "vote": vote_value(r, k),
                        "rowValue": val(r),
                        "integrity": (integ(r, k) or {}).get("primaryReason"),
                    }
                out.append(e)
    return out


def focus_table(boards, n, board_list):
    lines = []
    present = [b for b in board_list if n in boards[b]["rows"]]
    if not present:
        return [f"_{n}: no row on this pin_", ""]
    r0 = boards[present[0]]["rows"][n]
    lines.append(f"#### {n} ({r0.get('position')}, {r0.get('team')}, {cls(r0)})")
    lines.append("")
    hdr = "| board | value | rank | confidence | axes (ind/cov/fresh/appl/agr) | voting families | dropped (incumbent / V2) |"
    lines += [hdr, "|---|---|---|---|---|---|---|"]
    for b in present:
        r = boards[b]["rows"][n]
        ax = r.get("confidenceAxes") or {}
        axs = "/".join(
            str(ax.get(a, "-"))
            for a in ("independence", "coverage", "freshness", "applicability", "agreement")
        )
        lines.append(
            f"| {b} | {r.get('rankDerivedValue')} | {r.get('canonicalConsensusRank')} | {r.get('confidenceBucket')} | {axs} | {len(voting_families(r))} | {', '.join(r.get('droppedSources') or []) or '-'} |"
        )
    lines.append("")
    srcs = sorted(
        {
            k
            for b in present
            for k in set(boards[b]["rows"][n]["votes"])
            | set(boards[b]["rows"][n].get("sourceIntegrity") or {})
        }
    )
    lines.append(
        "| source | family | method | raw→eff rank | applied weight | " + " | ".join(present) + " |"
    )
    lines.append("|---|---|---|---|---|" + "---|" * len(present))
    for k in srcs:
        ref = next(
            (
                boards[b]["rows"][n]["votes"][k]
                for b in present
                if k in boards[b]["rows"][n]["votes"]
            ),
            {},
        )
        cells = []
        for b in present:
            r = boards[b]["rows"][n]
            st = obs_status(r, k)
            v = vote_value(r, k)
            if st == "not_observed":
                cells.append("—")
                continue
            tag = {
                "voting": "✓",
                "filter_dropped": "**DROPPED**",
                "freshness_or_health_zero_weight": "stale(w=0)",
            }.get(st, st)
            ir = (integ(r, k) or {}).get("primaryReason")
            if ir and ir not in ("voting",) and st == "voting":
                tag += f" [{ir}]"
            cells.append(f"{v if v is not None else ''} {tag}".strip())
        if all(c == "—" for c in cells):
            continue
        rr = (
            f"{ref.get('rawRank')}→{ref.get('effectiveRank')}"
            if ref.get("rawRank") is not None
            else "-"
        )
        aw = ref.get("appliedWeight")
        lines.append(
            f"| {k} | {ref.get('family', '-')} | {ref.get('method', '-')} | {rr} | {aw if aw is not None else '-'} | "
            + " | ".join(cells)
            + " |"
        )
    lines.append("")
    return lines


def why_line(boards, n):
    """One-line V2 retention explanation per focus row on board C."""
    r = boards["C"]["rows"].get(n)
    rb = boards["B"]["rows"].get(n)
    if not r or not rb:
        return None
    dropped = [k for k in rb["votes"] if rb["votes"][k]["status"] == "filter_dropped"]
    parts = []
    for k in dropped:
        i = integ(r, k) or {}
        parts.append(
            f"{k} {vote_value(rb, k)}: incumbent drop in B; in C status={obs_status(r, k)}, "
            f"identity={i.get('identity')}, V2 reason={i.get('primaryReason')}"
        )
    return parts


def restored_incumbent_drops(boards, base, v2b):
    """Every vote the incumbent drops on ``base`` and its fate on ``v2b``, with
    its distance (natural log, value space) to the nearest other voting vote of
    a DIFFERENT source on the V2 board, and V2's own Layer C reading."""
    out = []
    for n, ra in boards[base]["rows"].items():
        for k, m in sorted(ra["votes"].items()):
            if m["status"] != "filter_dropped":
                continue
            rv = boards[v2b]["rows"].get(n)
            mv = (rv or {}).get("votes", {}).get(k) or {}
            v = mv.get("valueContribution") or m.get("valueContribution")
            others = [
                (t, o.get("valueContribution"))
                for t, o in (rv or {}).get("votes", {}).items()
                if t != k and o["status"] is None and o.get("valueContribution")
            ]
            near = (
                min(((abs(math.log(v / ov)), t, ov) for t, ov in others), default=None)
                if v
                else None
            )
            i = mv.get("integrity") or {}
            out.append(
                {
                    "row": n,
                    "assetClass": cls(ra),
                    "position": ra.get("position"),
                    "source": k,
                    "vote": v,
                    "statusV2": obs_status(rv, k),
                    "v2Reason": i.get("primaryReason"),
                    "identity": i.get("identity"),
                    "layerCNearestOtherProvider": (i.get("layerC") or {}).get(
                        "nearestOtherProvider"
                    ),
                    "nearestOtherVote": {
                        "source": near[1],
                        "vote": near[2],
                        "lnDistance": round(near[0], 4),
                    }
                    if near
                    else None,
                    "rowValueBase": val(ra),
                    "rowValueV2": val(rv),
                }
            )
    out.sort(key=lambda e: -((e["nearestOtherVote"] or {}).get("lnDistance") or 0))
    return out


def _pct(x):
    return f"{(x or 0) * 100:.1f}%"


def tables_md(res):
    pin = res["pin"]
    L = [
        f"# Board tables, {pin}",
        "",
        f"Payload sha256 `{res['payloadSha256']}`. Status: {res['status']} (V2 thresholds "
        f"`{res['v2Thresholds'].get('status')}`, history lane `{res['v2HistoryLane'].get('state')}`).",
        "",
    ]
    L += [
        "## Comparison summary",
        "",
        "Exclusion changes count other sources' observations only; the DLF boards' own added votes are listed in the next section.",
        "",
        "| pair | what it isolates | exclusion changes | offense moves: rows / p90 / max | IDP moves: rows / p90 / max | pick moves: rows / max | confidence bucket changes | rank change ≥ 25 | material rows |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for key, c in res["comparisons"].items():
        tr = Counter()
        for t, v in c["statusTransitions"].items():
            _a, src, st = t.split("|", 2)
            if src in FLAG_SOURCES and "not_observed" in st:
                continue
            tr[st] += v
        trs = "; ".join(f"{k}: {v}" for k, v in sorted(tr.items())) or "none"
        vc = c["valueChangesByClass"]

        def f(cl):
            sx = vc.get(cl) or {}
            return f"{sx.get('moved', 0)} / {_pct(sx.get('p90'))} / {_pct(sx.get('max'))}"

        pk = vc.get("pick") or {}
        conf = sum(c["confidenceBucketTransitions"].values())
        L.append(
            f"| {key} | {c['label']} | {trs} | {f('offense')} | {f('idp')} | {pk.get('moved', 0)} / {_pct(pk.get('max'))} | {conf} | {c['rankChanges']['atLeast25']} | {len(c['materialRows'])} |"
        )
    L.append("")
    L += ["## Flag-added observations (the DLF boards' own votes)", ""]
    for key in ("B vs A", "C vs A", "D vs A", "B' vs A", "C' vs A", "B'' vs A", "C'' vs A"):
        c = res["comparisons"].get(key)
        if c:
            parts = []
            for k, v in c["flagAddedObservations"].items():
                bs = ", ".join(f"{s2}: {n}" for s2, n in sorted(v["byStatus"].items()))
                parts.append(f"{k} {v['count']} ({bs})")
            L.append(f"* {key}: " + ("; ".join(parts) or "none"))
    L.append("")
    r = res["regression31"]
    L += [
        f"## The 31 regression votes: dropped in B {r['droppedInB']}/{r['total']}; retained in C {r['retainedInC']}/{r['total']}, C″ {r['retainedInCpp']}/{r['total']}, D {r['retainedInD']}/{r['total']}",
        "",
        "Layer C distance `u` is V2's own coordinate (ln(10 + 500·p)); a vote is a Layer C drop candidate only beyond τ_C (provisional ln 6 = 1.792; grid floor ln 4 = 1.386). `< ln 2` = another provider within 2x, so not even dissent.",
        "",
        "| row | source | vote | A row | B row (vote) | C row (vote) | C″ | identity (Layer A) | V2 reason | Layer C nearest-provider distance (u) | nearest other vote, ln value |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in r["pairs"]:
        i = e["v2Integrity"] or {}
        cpp = e["C''"]["status"]
        lc = (i.get("layerC") or {}).get("nearestOtherProvider", "< ln 2")
        L.append(
            f"| {e['row']} | {e['source']} | {e['C']['vote']} | {e['A']['rowValue']} | {e['B']['rowValue']} ({fmt_status(e['B']['status'])}) | {e['C']['rowValue']} ({e['C']['status']}) | {cpp} | {i.get('identity') or 'none (value-direct source)'} | {i.get('primaryReason')} | {lc} | {e.get('nearestOtherLogDistanceInC')} |"
        )
    L.append("")
    d4 = res["d4Set"]
    L += [
        f"## D4 regression set by rule (B′ vs A): {d4['count']} votes on {d4['rows']} rows; retained in C′ {d4['retainedInCp']}/{d4['count']}, C″ {d4['retainedInCpp']}/{d4['count']}",
        "",
        "| row | source | vote | A row | B′ row | DLF Values vote | C′ row (status, V2 reason) | C″ status |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for e in d4["pairs"]:
        bp, cp, cpp = e["B'"], e["C'"], e["C''"]
        L.append(
            f"| {e['row']} | {e['source']} | {bp['vote']} | {e['A']['rowValue']} | {bp['rowValue']} | {e['dlfValuesVote']} | {cp['rowValue']} ({cp['status']}, {cp['integrity']}) | {cpp['status']} |"
        )
    L.append("")
    L += [
        "## Original 30 %+ movers",
        "",
        "| row | A | B | B vs A | C | C vs A | C″ | D | dropped in B | dropped in C |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in res["originalMovers"]:
        L.append(
            f"| {m['row']} | {m['A']} | {m['B']} | {m['B_vs_A']*100:+.1f}% | {m['C']} | {m['C_vs_A']*100:+.1f}% | {m["C''"]} | {m['D']} | {', '.join(m['droppedInB'] or [])} | {', '.join(m['droppedInC'] or []) or '-'} |"
        )
    L.append("")
    L += [
        "## Every V2 refusal / hold (any layer) on the V2 boards",
        "",
        "| board | row | row team | source | V2 status / reason | category | vendor team | without V2 (status, vote) | row value no-filter → V2 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for b, lst in res["v2Refusals"].items():
        for e in lst:
            L.append(
                f"| {b} | {e['row']} | {e.get('rowTeam')} | {e['source']} | {e['status']} / {e['primaryReason']} | {e['category']} | {e.get('entryTeam') or '-'} | {e.get('statusWithoutV2')}, {e.get('voteWithoutV2')} | {e.get('rowValueWithoutV2')} → {e.get('rowValueV2')} |"
            )
    L.append("")
    rd = res["incumbentDropsRestoredByV2"]
    within = sum(
        1
        for e in rd
        if e["nearestOtherVote"] and e["nearestOtherVote"]["lnDistance"] <= math.log(2)
    )
    L += [
        f"## The incumbent's own drops on A ({len(rd)}) and their fate under V2 (board D)",
        "",
        f"{within} of {len(rd)} have another voting source within 2x (ln 2) on board D. Largest distances first (top 15; full list in the JSON):",
        "",
        "| row | source | vote | V2 status / reason | nearest other vote (source, value, ln distance) | row A → D |",
        "|---|---|---|---|---|---|",
    ]
    for e in rd[:15]:
        nv = e["nearestOtherVote"] or {}
        L.append(
            f"| {e['row']} | {e['source']} | {e['vote']} | {e['statusV2']} / {e['v2Reason']} | {nv.get('source')} {nv.get('vote')} ({nv.get('lnDistance')}) | {e['rowValueBase']} → {e['rowValueV2']} |"
        )
    L.append("")
    L += [
        "## Two-way (Travis Hunter)",
        "",
        "| board | published | alt (DB) family value | primary (offense) value | alt sources considered | alt-panel drops | row drops |",
        "|---|---|---|---|---|---|---|",
    ]
    for b, t in res["twoWay"].items():
        tw = t["twoWayPlayerBoost"] or {}
        L.append(
            f"| {b} | {t['value']} | {tw.get('altFamilyValue')} | {tw.get('primaryFamilyValue')} | {', '.join(tw.get('sourcesConsidered') or [])} | {', '.join(tw.get('droppedSources') or []) or '-'} | {', '.join(t['dropped'] or []) or '-'} |"
        )
    L.append("")
    L += ["## Picks", ""]
    for key, pk in res["picks"].items():
        top = ", ".join(f"{e['row']} {e['from']}→{e['to']}" for e in pk["rows"][:4])
        L.append(
            f"* {key}: {pk['moved']} pick rows move, by provenance {pk['byProvenance']}, max |Δ| {_pct(pk['maxAbs'])} (largest: {top})"
        )
    L.append("")
    return L


def fmt_status(s):
    return {"voting": "voting", "filter_dropped": "DROPPED (incumbent)"}.get(s, s)


def material_md(pin, comps):
    L = [
        f"# Material rows, {pin}",
        "",
        f"Every row with |value change| ≥ {int(MAT_PCT*100)} % or |rank change| ≥ {MAT_RANK} (or gaining / losing a value or a rank), "
        "per comparison, with the source-level attribution: every vote whose status changed "
        "(with its value), and the largest vote VALUE changes (> 0.5 %) on votes that kept voting. "
        "For comparisons against A, `logSteps` decomposes the move into (1) standing the incumbent filter "
        "down, (2) the DLF flag change with no filter, (3) the filter under test; the three log-steps sum "
        "to the total log change.",
        "",
    ]
    for key, c in comps.items():
        mats = c["materialRows"]
        L.append(f"## {key}: {len(mats)} material rows")
        L.append("")
        if not mats:
            L.append("None.")
            L.append("")
            continue
        L.append(
            "| row | class/pos | value | Δ | rank | conf | vote status changes | vote value changes (top) | steps / notes |"
        )
        L.append("|---|---|---|---|---|---|---|---|---|")
        for m in mats:
            sc = (
                "; ".join(
                    f"{e['source']} {e['voteFrom'] if e['voteFrom'] is not None else e['voteTo']}: {fmt_status(e['from'])} → {fmt_status(e['to'])}"
                    for e in m["voteStatusChanges"]
                )
                or "-"
            )
            vc = (
                "; ".join(f"{e['source']} {e['from']}→{e['to']}" for e in m["voteValueChanges"][:3])
                or "-"
            )
            if m["voteValueChangesCount"] > 3:
                vc += f" (+{m['voteValueChangesCount'] - 3} more)"
            st = ""
            if m["logSteps"]:
                st = ", ".join(
                    f"{k.split(' ')[0]} {v:+.3f}" for k, v in m["logSteps"].items() if v is not None
                )
            if m["notes"]:
                st = (st + "; " if st else "") + "; ".join(m["notes"])
            ch = f"{m['change']*100:+.1f}%" if m["change"] is not None else "n/a"
            L.append(
                f"| {m['row']} | {m['assetClass']}/{m['position']} | {m['from']}→{m['to']} | {ch} | {m['rankFrom']}→{m['rankTo']} | {m['confidence']} | {sc} | {vc} | {st} |"
            )
        L.append("")
    return L


def main() -> int:
    src, regp, out_dir = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    d = json.load(gzip.open(src, "rt"))
    reg = json.loads(regp.read_text())
    pin = d["pin"]
    boards = d["boards"]
    pairs31 = reg["idpRestore"][pin]["pairs"]
    comps = {}
    for x, y, label in PAIRS:
        if x in boards and y in boards:
            c = compare(boards, x, y)
            c["label"] = label
            comps[f"{x} vs {y}"] = c
    r31 = regression31(boards, pairs31)
    d4 = d4_set(boards, "A", "B'", ["C'", "C''", "B''"])
    d4_restored = d4_set(boards, "B", "B''", ["C''"])
    two_way = {
        b: {
            "value": val(boards[b]["rows"].get("Travis Hunter")),
            "twoWayPlayerBoost": (boards[b]["rows"].get("Travis Hunter") or {}).get(
                "twoWayPlayerBoost"
            ),
            "dropped": (boards[b]["rows"].get("Travis Hunter") or {}).get("droppedSources"),
        }
        for b in boards
    }
    picks = {}
    for key in ("B vs A", "C vs A", "C vs B", "D vs A", "C' vs A", "C'' vs A"):
        x, y = key.split(" vs ")
        rows = []
        for n, rx in boards[x]["rows"].items():
            if cls(rx) != "pick":
                continue
            ry = boards[y]["rows"].get(n)
            vy, vx = val(ry), val(rx)
            if vy != vx:
                rows.append(
                    {
                        "row": n,
                        "from": vy,
                        "to": vx,
                        "change": round(vx / vy - 1, 4) if vy and vx else None,
                        "provenance": (rx.get("pickValueProvenance") or {}).get("class"),
                    }
                )
        rows.sort(key=lambda e: -abs(e["change"] or 0))
        by = Counter(e["provenance"] for e in rows)
        picks[key] = {
            "moved": len(rows),
            "byProvenance": dict(by),
            "maxAbs": max((abs(e["change"] or 0) for e in rows), default=0.0),
            "rows": rows,
        }
    refusals = {b: v2_refusals(boards, b) for b in ("C", "D", "C'", "C''") if b in boards}
    dissent = {b: kept_dissent(boards, b) for b in ("C", "D", "C'", "C''") if b in boards}
    focus = {}
    for n in FOCUS:
        focus[n] = {
            b: {
                "value": val(boards[b]["rows"].get(n)),
                "rank": (boards[b]["rows"].get(n) or {}).get("canonicalConsensusRank"),
                "confidence": (boards[b]["rows"].get(n) or {}).get("confidenceBucket"),
                "axes": (boards[b]["rows"].get(n) or {}).get("confidenceAxes"),
                "dropped": (boards[b]["rows"].get(n) or {}).get("droppedSources"),
                "votes": {
                    k: {
                        "vote": vote_value(boards[b]["rows"].get(n), k),
                        "status": obs_status(boards[b]["rows"].get(n), k),
                        "integrity": (integ(boards[b]["rows"].get(n), k) or {}).get(
                            "primaryReason"
                        ),
                    }
                    for k in sorted(
                        set((boards[b]["rows"].get(n) or {}).get("votes", {}))
                        | set((boards[b]["rows"].get(n) or {}).get("sourceIntegrity") or {})
                    )
                },
            }
            for b in boards
            if n in boards[b]["rows"]
        }
        focus[n]["whyV2"] = why_line(boards, n)
    movers = []
    for n in ORIGINAL_MOVERS:
        a, b_, c_ = (val(boards[k]["rows"].get(n)) for k in ("A", "B", "C"))
        cpp, dd, bnf = (val(boards[k]["rows"].get(n)) for k in ("C''", "D", "Bnf"))
        movers.append(
            {
                "row": n,
                "A": a,
                "B": b_,
                "C": c_,
                "C''": cpp,
                "D": dd,
                "Bnf": bnf,
                "B_vs_A": round(b_ / a - 1, 4),
                "C_vs_A": round(c_ / a - 1, 4),
                "C_vs_Bnf": round(c_ / bnf - 1, 4),
                "droppedInB": boards["B"]["rows"][n].get("droppedSources"),
                "droppedInC": boards["C"]["rows"][n].get("droppedSources"),
            }
        )
    board_census = {}
    for b, bd in boards.items():
        c = Counter()
        for r in bd["rows"].values():
            for k in set(r["votes"]) | set(r.get("sourceIntegrity") or {}):
                c[f"{cls(r)}|{obs_status(r, k)}"] += 1
        board_census[b] = dict(sorted(c.items()))
    result = {
        "schema": "oiv2-abcd-evaluation/v1",
        "pin": pin,
        "payloadSha256": d["payloadSha256"],
        "status": "pre_freeze_provisional_thresholds_no_history",
        "boardsSpec": d["boardsSpec"],
        "digests": {b: bd["digest"] for b, bd in boards.items()},
        "playersArraySha256": {b: bd["playersArraySha256"] for b, bd in boards.items()},
        "determinismC": d.get("determinismC"),
        "peakRssMb": d.get("peakRssMb"),
        "buildSeconds": {b: bd["buildSeconds"] for b, bd in boards.items()},
        "v2Thresholds": boards["C"]["sourceIntegrity"].get("thresholds"),
        "v2HistoryLane": boards["C"]["sourceIntegrity"].get("historyLane"),
        "v2Summary": {
            b: {
                k: boards[b]["sourceIntegrity"].get(k)
                for k in (
                    "findings",
                    "sourceQuarantines",
                    "segmentQuarantines",
                    "voteExclusions",
                    "rankingPasses",
                    "identity",
                    "dependency",
                    "alerts",
                )
            }
            | {
                "votingCategoryTotals": (
                    boards[b]["sourceIntegrity"].get("votingCategories") or {}
                ).get("totals"),
                "layerC": boards[b]["sourceIntegrity"].get("layerC"),
            }
            for b in ("C", "D", "C'", "C''")
        },
        "boardVoteCensus": board_census,
        "comparisons": comps,
        "regression31": {
            "pairs": r31,
            "droppedInB": sum(e["droppedInB"] for e in r31),
            "retainedInC": sum(e["retainedInC"] for e in r31),
            "retainedInCpp": sum(e["retainedInCpp"] for e in r31),
            "retainedInD": sum(e["retainedInD"] for e in r31),
            "total": len(r31),
        },
        "d4Set": {
            "rule": "offense (row, source) dropped by the incumbent in B' and not in A, DLF Values' own vote excluded",
            "pairs": d4,
            "count": len(d4),
            "rows": len({e["row"] for e in d4}),
            "retainedInCp": sum(e["C'"]["status"] == "voting" for e in d4),
            "retainedInCpp": sum(e["C''"]["status"] == "voting" for e in d4),
        },
        "d4SetWithDlfIdpRestored": {
            "rule": "same rule, B'' vs B",
            "pairs": d4_restored,
            "count": len(d4_restored),
            "retainedInCpp": sum(e["C''"]["status"] == "voting" for e in d4_restored),
        },
        "originalMovers": movers,
        "twoWay": two_way,
        "picks": picks,
        "v2Refusals": refusals,
        "v2KeptDissent": dissent,
        "focus": focus,
        "incumbentDropsRestoredByV2": restored_incumbent_drops(boards, "A", "D"),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"abcd_{pin}.json").write_text(
        json.dumps(result, sort_keys=True, default=str, separators=(",", ":")) + "\n"
    )
    (out_dir / f"TABLES_{pin}.md").write_text("\n".join(tables_md(result)) + "\n")
    (out_dir / f"MATERIAL_ROWS_{pin}.md").write_text("\n".join(material_md(pin, comps)) + "\n")
    F = [
        f"# Focus rows, {pin}: full per-player source tables",
        "",
        "Cell = the source's priced vote on that board and its state: ✓ voting; **DROPPED** = removed by the "
        "incumbent per-row filter; stale(w=0) = freshness/health zero weight (never a vote); `v2_refused:<reason>` = "
        "refused by V2 Layer A before pricing; a bracketed reason is V2's stamp on a vote that still votes "
        "(`kept_dissent` = Layer C assessed it as legitimate disagreement and kept it; `voting_name_only_identity` "
        "= Layer A could confirm the name only and let it vote). — = no observation. "
        "Boards: A production; B DLF IDP restored + incumbent; C DLF IDP restored + V2; D V2 with DLF held; "
        "B′/C′ D4 on (incumbent / V2); B″/C″ DLF IDP restored + D4 on (incumbent / V2); Anf/Bnf no per-row filter.",
        "",
    ]
    for n in FOCUS:
        F += focus_table(boards, n, ["A", "B", "C", "D", "B'", "C'", "B''", "C''", "Anf", "Bnf"])
        w = focus[n].get("whyV2")
        if w:
            F.append("Why V2 keeps the votes the incumbent removed in B: " + " | ".join(w))
            F.append("")
    (out_dir / f"FOCUS_{pin}.md").write_text("\n".join(F) + "\n")
    print(
        json.dumps(
            {
                "pin": pin,
                "regression31": {k: v for k, v in result["regression31"].items() if k != "pairs"},
                "d4": {k: v for k, v in result["d4Set"].items() if k not in ("pairs", "rule")},
                "material": {k: len(c["materialRows"]) for k, c in comps.items()},
                "refusals": {b: len(v) for b, v in refusals.items()},
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
