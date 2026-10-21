#!/usr/bin/env python3
"""Outlier-integrity-v2 §6 comparison boards and R constraints on one pinned input.

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §6, §11
criterion 2; deviation T1/T2 (``outlier_integrity_v2/DEVIATIONS.md``): run before
the Stage 2 freeze at the provisional thresholds and under NO-HISTORY, so these
results are must-pass constraint checks, never evidence, and must be re-run at
Stage 3 proper on frozen thresholds.

Run with ``cwd`` = a throwaway tree whose ``CSVs/`` and ``data/`` are pinned to the
input commit (``rootcause/pin_inputs.sh``), exactly as the root-cause
reproduction does::

    python scripts/oiv2_regression_boards.py PAYLOAD.json PIN_TAG OUT_DIR

Boards (identical frozen data; only the two DLF flags and the filter differ):

====  =====================  ======================  ==========
board DLF IDP                D4 (DLF Values offense)  filter
====  =====================  ======================  ==========
A     held                   off                     incumbent
B     restored               off                     incumbent
C     restored               off                     V2
D     held                   off                     V2
B'    held                   on                      incumbent
C'    held                   on                      V2
B''   restored               on                      incumbent
C''   restored               on                      V2
Bnf   restored               off                     none (attribution)
B'nf  held                   on                      none (attribution)
====  =====================  ======================  ==========

Writes ``r_<PIN>.json`` (all comparisons) and ``panels_<PIN>.json`` (the frozen
pre-filter vote panels of every regression row, the test fixture).
"""

from __future__ import annotations

import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from src.api import data_contract as dc  # noqa: E402
from src.robust_filter_shadow import oiv2_gates as G  # noqa: E402

REGRESSION_SET = (
    ROOT / "docs" / "sources" / "outlier_integrity_v2" / "manifests" / "REGRESSION_SET.json"
)
FOCUS = (
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
)
DLF_VALUES = "dlfValuesSfTep"
BOARDS = {
    "A": ("incumbent", True, False),
    "B": ("incumbent", False, False),
    "C": ("v2", False, False),
    "D": ("v2", True, False),
    "B'": ("incumbent", True, True),
    "C'": ("v2", True, True),
    "B''": ("incumbent", False, True),
    "C''": ("v2", False, True),
    "Bnf": ("none", False, False),
    "B'nf": ("none", True, True),
}


def build(name: str, raw: dict) -> dict:
    config, held, d4 = BOARDS[name]
    return G.build(
        raw,
        None,
        config,
        extra_flags={"dlf_offense_only_vote": held, "dlf_values_rank_hill_vote": d4},
        history=None,
    )


def full_sha(contract: dict) -> str:
    return hashlib.sha256(
        json.dumps(contract.get("playersArray"), sort_keys=True, default=str).encode()
    ).hexdigest()


def panel(row: dict) -> dict:
    votes, weights, method, family = {}, {}, {}, {}
    for k, m in sorted((row.get("sourceRankMeta") or {}).items()):
        if not isinstance(m, dict) or m.get("excludedReason"):
            continue
        v = m.get("valueContribution")
        if not isinstance(v, (int, float)) or v <= 0:
            continue
        votes[k] = float(v)
        w = m.get("preFamilyWeight", m.get("appliedWeight"))
        weights[k] = float(w) if isinstance(w, (int, float)) else 1.0
        method[k] = {
            "method": m.get("method"),
            "sharedMarketTranslated": bool(m.get("sharedMarketTranslated")),
            "levelSource": m.get("levelSource"),
        }
        family[k] = dc.correlation_group_for(k) or k
    return {
        "row": row.get("displayName"),
        "assetClass": row.get("assetClass"),
        "position": row.get("position"),
        "votes": votes,
        "preCapWeights": weights,
        "families": family,
        "translation": method,
        "rankDerivedValue": row.get("rankDerivedValue"),
        "droppedSources": sorted(row.get("droppedSources") or []),
    }


def drops_by_source(rows: dict, asset_class: str | None = None) -> dict:
    c: Counter = Counter()
    for r in rows.values():
        if asset_class and r.get("assetClass") != asset_class:
            continue
        for k in r.get("sourceRankMeta") or {}:
            reason = G.exclusion_of(r, k)
            if reason == "filter_dropped" or reason == "extreme_uncorroborated_tail":
                c[k] += 1
    return dict(sorted(c.items()))


def value_changes(a: dict, b: dict) -> dict:
    moves = []
    for n, ra in a.items():
        rb = b.get(n)
        va, vb = G._value(ra), G._value(rb)
        if va and vb and va != vb and ra.get("assetClass") != "pick":
            moves.append((abs(vb / va - 1.0), n, ra.get("assetClass"), va, vb))
    moves.sort(reverse=True)
    pct = [m[0] for m in moves]

    def q(p):
        if not pct:
            return None
        s = sorted(pct)
        return round(s[min(len(s) - 1, int(p * len(s)))], 4)

    return {
        "rowsChanged": len(moves),
        "median": round(statistics.median(pct), 4) if pct else None,
        "p90": q(0.9),
        "max": round(max(pct), 4) if pct else None,
        "rowsAtLeast10pct": [
            {"row": n, "assetClass": ac, "from": va, "to": vb, "change": round(vb / va - 1, 4)}
            for p, n, ac, va, vb in moves
            if p >= 0.10
        ],
    }


def main() -> int:
    payload, tag, out_dir = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    raw = json.loads(payload.read_text("utf-8"))
    reg = json.loads(REGRESSION_SET.read_text("utf-8"))
    pairs = [(p["row"], p["source"]) for p in reg["idpRestore"]["pin2015"]["pairs"]]

    contracts = {name: build(name, raw) for name in BOARDS}
    rows = {name: G.rows_by_name(c) for name, c in contracts.items()}
    repeat = build("C", raw)

    def status(board, n, k):
        r = rows[board].get(n)
        m = ((r or {}).get("sourceRankMeta") or {}).get(k) or {}
        return {
            "vote": m.get("valueContribution"),
            "excluded": G.exclusion_of(r, k),
            "integrity": (m.get("integrity") or {}).get("primaryReason"),
            "rowValue": (r or {}).get("rankDerivedValue"),
        }

    idp = []
    for n, k in pairs:
        entry = {"row": n, "source": k}
        for b in ("A", "B", "C", "C''", "Bnf"):
            entry[b] = status(b, n, k)
        entry["retainedC"] = entry["C"]["excluded"] is None and entry["C"]["vote"] is not None
        entry["retainedCpp"] = entry["C''"]["excluded"] is None and entry["C''"]["vote"] is not None
        entry["droppedB"] = entry["B"]["excluded"] == "filter_dropped"
        idp.append(entry)

    d4 = []
    for n, rb in sorted(rows["B'"].items()):
        if rb.get("assetClass") != "offense":
            continue
        ra = rows["A"].get(n) or {}
        for k in sorted(rb.get("sourceRankMeta") or {}):
            if k == DLF_VALUES:
                continue
            if (
                G.exclusion_of(rb, k) == "filter_dropped"
                and G.exclusion_of(ra, k) != "filter_dropped"
            ):
                e = {"row": n, "source": k}
                for b in ("A", "B'", "C'", "C''", "B'nf"):
                    e[b] = status(b, n, k)
                e["retainedCp"] = e["C'"]["excluded"] is None and e["C'"]["vote"] is not None
                e["retainedCpp"] = e["C''"]["excluded"] is None and e["C''"]["vote"] is not None
                d4.append(e)

    focus = {}
    for n in FOCUS:
        focus[n] = {}
        for b in BOARDS:
            r = rows[b].get(n)
            if not r:
                continue
            focus[n][b] = {
                "value": r.get("rankDerivedValue"),
                "confidence": r.get("confidenceBucket"),
                "votes": {
                    k: [
                        (m or {}).get("valueContribution"),
                        G.exclusion_of(r, k),
                    ]
                    for k, m in sorted((r.get("sourceRankMeta") or {}).items())
                },
            }

    regression_rows = sorted({n for n, _k in pairs} | {e["row"] for e in d4} | set(FOCUS))
    panels = {
        "schema": "oiv2-frozen-panels/v1",
        "pin": tag,
        "payloadSha256": hashlib.sha256(payload.read_bytes()).hexdigest(),
        "note": "Pre-filter vote panels (votes that reached the per-row filter, their "
        "pre-cap weights and B10 families) read from board B (IDP restore) and B' (D4) "
        "of this pin. Frozen inputs for tests/api/test_oiv2_regression_set.py; never "
        "used to fit or select a threshold.",
        "B": {n: panel(rows["B"][n]) for n in regression_rows if n in rows["B"]},
        "B'": {n: panel(rows["B'"][n]) for n in regression_rows if n in rows["B'"]},
    }

    result = {
        "schema": "oiv2-r-constraints/v1",
        "pin": tag,
        "payloadSha256": panels["payloadSha256"],
        "status": "pre_freeze_constraint_check_provisional_thresholds_no_history",
        "thresholds": contracts["C"].get("sourceIntegrity", {}).get("thresholds"),
        "boards": {
            b: {"config": v[0], "dlfIdpHeld": v[1], "d4On": v[2]} for b, v in BOARDS.items()
        },
        "idpRestore": {
            "pairs": idp,
            "droppedInB": sum(1 for e in idp if e["droppedB"]),
            "retainedInC": sum(1 for e in idp if e["retainedC"]),
            "retainedInCpp": sum(1 for e in idp if e["retainedCpp"]),
            "total": len(idp),
        },
        "d4": {
            "rule": reg["d4"]["definition"],
            "pairs": d4,
            "count": len(d4),
            "rows": len({e["row"] for e in d4}),
            "retainedInCp": sum(1 for e in d4 if e["retainedCp"]),
            "retainedInCpp": sum(1 for e in d4 if e["retainedCpp"]),
            "theoJohnsonDraftSharksInSet": any(
                e["row"] == "Theo Johnson" and e["source"] == "draftSharks" for e in d4
            ),
        },
        "focus": focus,
        "drops": {
            b: {
                "offense": drops_by_source(rows[b], "offense"),
                "idp": drops_by_source(rows[b], "idp"),
            }
            for b in BOARDS
        },
        "valueChanges": {
            "B_vs_A": value_changes(rows["A"], rows["B"]),
            "C_vs_A": value_changes(rows["A"], rows["C"]),
            "C_vs_B": value_changes(rows["B"], rows["C"]),
            "D_vs_A": value_changes(rows["A"], rows["D"]),
            "Bp_vs_A": value_changes(rows["A"], rows["B'"]),
            "Cp_vs_A": value_changes(rows["A"], rows["C'"]),
            "Cpp_vs_A": value_changes(rows["A"], rows["C''"]),
        },
        "integrity": {
            b: {
                k: (contracts[b].get("sourceIntegrity") or {}).get(k)
                for k in (
                    "voteExclusions",
                    "sourceQuarantines",
                    "segmentQuarantines",
                    "rankingPasses",
                )
            }
            for b in BOARDS
            if BOARDS[b][0] == "v2"
        },
        "determinism": {
            "C_digest_run1": G.board_digest(contracts["C"]),
            "C_digest_run2": G.board_digest(repeat),
            "C_playersArray_sha_run1": full_sha(contracts["C"]),
            "C_playersArray_sha_run2": full_sha(repeat),
        },
        "digests": {b: G.board_digest(c) for b, c in contracts.items()},
    }
    d = result["determinism"]
    d["identical"] = (
        d["C_digest_run1"] == d["C_digest_run2"]
        and d["C_playersArray_sha_run1"] == d["C_playersArray_sha_run2"]
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"r_{tag}.json").write_text(
        json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", "utf-8"
    )
    (out_dir / f"panels_{tag}.json").write_text(
        json.dumps(panels, indent=1, sort_keys=True, default=str) + "\n", "utf-8"
    )
    print(
        json.dumps(
            {
                "pin": tag,
                "idp": {k: v for k, v in result["idpRestore"].items() if k != "pairs"},
                "d4": {k: v for k, v in result["d4"].items() if k not in ("pairs", "rule")},
                "deterministic": d["identical"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
