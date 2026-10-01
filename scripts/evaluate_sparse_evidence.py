"""Evaluate the sparse-evidence estimator against its preregistration (Batch 3 Unit E).

Builds the pinned archived board once per candidate through
``src/api/value_replay.py`` (only flags differ), measures the preregistered
metrics, evaluates the hard gates and writes a compact ``results.json``.

    python scripts/evaluate_sparse_evidence.py --base-tree <export of base commit>

Preregistration (method, gates, decision rule):
``docs/valuation/evidence/sparse-evidence-2026-10-01/PREREGISTRATION.md``.
Nothing here promotes or flips anything.

Exit codes: 0 written; 1 inputs missing; 2 the tree is dirty (evidence must
come from a clean committed tree).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.api import data_contract as dc  # noqa: E402
from src.api import value_replay as vr  # noqa: E402

EVIDENCE = REPO / "docs" / "valuation" / "evidence" / "sparse-evidence-2026-10-01"
PREREG = "docs/valuation/evidence/sparse-evidence-2026-10-01/PREREGISTRATION.md"
ARCHIVE = REPO / "exports" / "archive" / "dynasty_export_20260930_130404.zip"
PRIOR_EVIDENCE = REPO / "docs/valuation/evidence/joint-challenger-2026-10-01/diagnostics.json"
TOP_KS = (50, 100, 200, 400)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(REPO), *args], capture_output=True, text=True, check=True
    ).stdout


def _payload() -> tuple[dict, bytes]:
    with zipfile.ZipFile(ARCHIVE) as zf:
        name = next(
            n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
        )
        data = zf.read(name)
    return json.loads(data), data


def _rows(contract: dict) -> dict[str, dict]:
    return {r["displayName"]: r for r in contract["playersArray"] if r.get("displayName")}


def _players_hash(contract: dict) -> str:
    return _sha(json.dumps(contract["playersArray"], sort_keys=True, default=str).encode())


def _group(row: dict) -> str:
    if row.get("assetClass") == "pick":
        return "PICK"
    if row.get("assetClass") == "idp":
        return "IDP"
    return str(row.get("position") or "?")


def _rank(row: dict | None) -> int | None:
    return (row or {}).get("canonicalConsensusRank")


def _in_top(row: dict | None, k: int) -> bool:
    r = _rank(row)
    return r is not None and r <= k


def _dist(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"n": 0}
    v = sorted(values)
    q = lambda p: v[min(len(v) - 1, int(round(p * (len(v) - 1))))]  # noqa: E731
    return {
        "n": len(v),
        "min": round(v[0], 3),
        "p10": round(q(0.1), 3),
        "median": round(statistics.median(v), 3),
        "p90": round(q(0.9), 3),
        "max": round(v[-1], 3),
    }


def _churn(base: dict[str, dict], other: dict[str, dict]) -> dict[str, Any]:
    out = {}
    for k in TOP_KS:
        a = {n for n, r in base.items() if _in_top(r, k)}
        b = {n for n, r in other.items() if _in_top(r, k)}
        out[f"top{k}"] = {
            "entered": sorted(b - a),
            "left": sorted(a - b),
            "churn": len(b - a),
        }
    return out


def _ranks_without(rows: dict[str, dict], withheld: set[str]) -> dict[str, dict]:
    """Candidate D: C with the withheld rows removed and the board re-ranked."""
    ranked = sorted(
        (r for n, r in rows.items() if n not in withheld and _rank(r) is not None),
        key=lambda r: _rank(r),
    )
    return {r["displayName"]: {"canonicalConsensusRank": i + 1} for i, r in enumerate(ranked)}


def _trap() -> dict[str, Any]:
    """The 4600 -> 1380 failure through the real pipeline (same as the test)."""
    from tests.api import test_sparse_evidence_estimator as t  # noqa: PLC0415

    def naive(pairs, **_kw):
        pairs = list(pairs)
        if any(k == "ktcCrowdSfTep" and abs(v - 4600) < 1 for k, v in pairs):
            return [(k, v) for k, v in pairs if k == "ktcCrowdSfTep"], [
                k for k, _ in pairs if k != "ktcCrowdSfTep"
            ]
        return pairs, []

    def board():
        anchor = dict(ktcCrowdSfTep=9999, ktcTradesSfTep=9999, idpTradeCalc=9999)
        return [
            t._row("Anchor QB", "QB", dynastyDaddySf=9999, **anchor),
            t._row(
                "Trap WR",
                "WR",
                ktcCrowdSfTep=4600,
                ktcTradesSfTep=3000,
                idpTradeCalc=3100,
                dynastyDaddySf=3200,
            ),
        ]

    weak = {
        k: t._Weighting(k, freshness=0.03, state="SEVERELY_STALE")
        for k in ("ktcTradesSfTep", "idpTradeCalc", "dynastyDaddySf")
    }
    weighting = {"ktcCrowdSfTep": t._Weighting("ktcCrowdSfTep"), **weak}
    index = t._index(*[(k, ["Anchor QB", "Trap WR"]) for k in weighting])
    out: dict[str, Any] = {
        "inputs": "4600 @ 1.0 (ktcCrowd); 3000/3100/3200 @ 0.03 (ktcTrades, idpTradeCalc, "
        "dynastyDaddy); naive weighted filter drops the three weak observations",
    }
    with (
        mock.patch.object(
            dc, "_VALUE_BASED_SOURCES", frozenset(dc._VALUE_BASED_SOURCES | {"dynastyDaddySf"})
        ),
        mock.patch.object(dc, "_hampel_filter_per_player", naive),
    ):
        for label, on in (("incumbent", False), ("challengerC", True)):
            rows = board()
            with vr._flag("sparse_evidence_estimator", on):
                dc._compute_unified_rankings(rows, {}, csv_index=index, source_weighting=weighting)
            trap = next(r for r in rows if r["canonicalName"] == "Trap WR")
            out[label] = {
                "value": trap.get("rankDerivedValue"),
                "dropped": trap.get("droppedSources"),
                "state": (trap.get("sparseEvidence") or {}).get("state"),
            }
    return out


def _base_hash(base_tree: Path) -> dict[str, Any]:
    code = (
        "import json,sys,zipfile,hashlib;sys.path.insert(0,'.');"
        "from src.api import value_replay as vr;"
        f"zf=zipfile.ZipFile(r'{ARCHIVE}');"
        "n=[x for x in zf.namelist() if x.startswith('dynasty_data_') and x.endswith('.json')][0];"
        "c=vr.build(json.loads(zf.read(n)));"
        "print(json.dumps({'boardHash':vr.board_hash(c),'playersHash':hashlib.sha256("
        "json.dumps(c['playersArray'],sort_keys=True,default=str).encode()).hexdigest()}))"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], cwd=base_tree, capture_output=True, text=True, check=True
    )
    return json.loads(proc.stdout.strip().splitlines()[-1])


def _semantics_tests() -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         "tests/api/test_sparse_evidence_estimator.py"],
        cwd=REPO, capture_output=True, text=True,
    )  # fmt: skip
    tail = (proc.stdout.strip().splitlines() or [""])[-1]
    return {"exitCode": proc.returncode, "summary": tail}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base-tree", type=Path, help="export of the base commit (OFF identity)")
    ap.add_argument("--base-commit", default=None)
    ap.add_argument("--out", type=Path, default=EVIDENCE / "results.json")
    args = ap.parse_args()
    if not ARCHIVE.exists():
        print(f"missing {ARCHIVE}", file=sys.stderr)
        return 1
    if vr._dirty():
        print("working tree is dirty; evidence must come from a clean commit", file=sys.stderr)
        return 2

    prereg_blob = subprocess.run(
        ["git", "-C", str(REPO), "show", f"HEAD:{PREREG}"], capture_output=True, check=True
    ).stdout
    prereg_commit = _git("log", "--format=%H", "--diff-filter=A", "--", PREREG).split()[-1]
    raw, raw_bytes = _payload()
    with tempfile.TemporaryDirectory() as tmp:
        payload_path = Path(tmp) / "payload.json"
        payload_path.write_bytes(raw_bytes)
        pins = vr.pins(payload_path)
    pins["payload"] = {
        "archive": ARCHIVE.name,
        "archiveSha256": _sha(ARCHIVE.read_bytes()),
        "payloadSha256": _sha(raw_bytes),
        "scrapeTimestamp": raw.get("scrapeTimestamp") or raw.get("date"),
    }

    incumbent = vr.build(raw)
    again = vr.build(raw)
    with vr._flag("joint_sparse_limited_evidence", True):
        passthrough = vr.build(raw)
    with vr._flag("sparse_evidence_estimator", True):
        challenger = vr.build(raw)
    I, A, C = _rows(incumbent), _rows(passthrough), _rows(challenger)

    H = sorted(n for n, r in I.items() if r.get("singleSourceValuePenaltyApplied"))
    prior = json.loads(PRIOR_EVIDENCE.read_text(encoding="utf-8"))
    prior_names = {r["asset"] for r in prior.get("formerHaircutRows") or []}
    prior_value = {r["asset"]: r.get("valueOff") for r in prior.get("formerHaircutRows") or []}

    # ── rows changed, by asset class ──
    changed: dict[str, dict[str, list]] = {"C": defaultdict(list), "A": defaultdict(list)}
    for label, other in (("C", C), ("A", A)):
        for name, row in I.items():
            a, b = row.get("rankDerivedValue"), (other.get(name) or {}).get("rankDerivedValue")
            if a != b:
                changed[label][_group(row)].append(name)
    changed_summary = {
        label: {g: len(v) for g, v in sorted(groups.items())} for label, groups in changed.items()
    }

    # ── the former-haircut rows ──
    h_rows = []
    for name in H:
        i, a, c = I[name], A.get(name) or {}, C.get(name) or {}
        block = c.get("sparseEvidence") or {}
        iv, av, cv = i.get("rankDerivedValue"), a.get("rankDerivedValue"), c.get("rankDerivedValue")
        h_rows.append(
            {
                "asset": name,
                "group": _group(i),
                "rookie": bool(i.get("rookie")),
                "voting": sorted(
                    k
                    for k in (i.get("sourceRanks") or {})
                    if k not in set(i.get("droppedSources") or [])
                ),
                "I": [iv, _rank(i)],
                "A": [av, _rank(a)],
                "C": [cv, _rank(c)],
                "ratioCtoI": round(cv / iv, 3) if iv and cv else None,
                "ratioCtoA": round(cv / av, 3) if av and cv else None,
                "state": block.get("state"),
                "binding": [
                    [b["family"], b["bound"]] for b in block.get("censoredFamiliesUsed", [])
                ],
                "nonBinding": len(block.get("nonBindingFamilies") or []),
                "confidence": (block.get("confidence") or {}).get("bucket"),
                "prior1571ValueOff": prior_value.get(name),
            }
        )
    ratios_ci = [r["ratioCtoI"] for r in h_rows if r["ratioCtoI"] is not None]
    ratios_ai = [round(r["A"][0] / r["I"][0], 3) for r in h_rows if r["A"][0] and r["I"][0]]
    ratios_ca = [r["ratioCtoA"] for r in h_rows if r["ratioCtoA"] is not None]
    states = Counter(r["state"] for r in h_rows)

    def h_entries(other: dict[str, dict], k: int, ranks: dict[str, dict] | None = None) -> list:
        src = ranks if ranks is not None else other
        return sorted(n for n in H if _in_top(src.get(n), k) and not _in_top(I.get(n), k))

    withheld_d = {r["asset"] for r in h_rows if r["state"] == "uncorroborated"}
    d_ranks = _ranks_without(C, withheld_d)

    # ── picks ──
    pick_changes = []
    for name, row in I.items():
        if row.get("assetClass") != "pick":
            continue
        a, b = row.get("rankDerivedValue"), (C.get(name) or {}).get("rankDerivedValue")
        if a != b:
            prov = (C.get(name) or {}).get("pickValueProvenance") or {}
            pick_changes.append({"asset": name, "I": a, "C": b, "provenance": prov.get("class")})

    nonpick_outside = [
        n
        for n, r in I.items()
        if n not in set(H)
        and r.get("assetClass") != "pick"
        and r.get("rankDerivedValue") != (C.get(n) or {}).get("rankDerivedValue")
    ]
    moves = sorted(
        (
            (
                n,
                _group(I[n]),
                (C[n].get("rankDerivedValue") or 0) - (I[n].get("rankDerivedValue") or 0),
            )
            for n in I
            if n in C and I[n].get("rankDerivedValue") != C[n].get("rankDerivedValue")
        ),
        key=lambda t: -abs(t[2]),
    )[:10]

    # ── witness census (source-level) ──
    from src.api import sparse_evidence as se  # noqa: PLC0415

    weighting = dc._load_source_weighting(dc._payload_as_of(raw), None)
    census = {}
    for s in dc._RANKING_SOURCES:
        st = se.source_status(s, weighting.get(s["key"]), base_weight=1.0, freshness_applied=True)
        census[s["key"]] = "witness" if st.ok else st.reason

    trap = _trap()
    semantics = _semantics_tests()
    off_identity: dict[str, Any] = {
        "headFlagOffBoardHash": vr.board_hash(incumbent),
        "headFlagOffPlayersHash": _players_hash(incumbent),
        "deterministicRebuild": _players_hash(incumbent) == _players_hash(again),
    }
    if args.base_tree:
        base = _base_hash(args.base_tree)
        off_identity.update(
            {
                "baseCommit": args.base_commit,
                "baseBoardHash": base["boardHash"],
                "basePlayersHash": base["playersHash"],
                "identical": base["playersHash"] == off_identity["headFlagOffPlayersHash"],
            }
        )

    # ── gates ──
    g3_violations = []
    for r in h_rows:
        cv, av = r["C"][0], r["A"][0]
        block = (C.get(r["asset"]) or {}).get("sparseEvidence") or {}
        inputs = [block.get("observedValue")] + [
            b["bound"] for b in block.get("censoredFamiliesUsed", [])
        ]
        inputs = [v for v in inputs if v is not None]
        if cv is None or av is None or not inputs:
            g3_violations.append(r["asset"])
            continue
        if cv > av + 1 or cv < min(inputs) - 1:
            g3_violations.append(r["asset"])
    gates = {
        "G1_trap": {
            "pass": abs((trap["incumbent"]["value"] or 0) - 1380) <= 1
            and (trap["challengerC"]["value"] or 0) >= 4500,
            "incumbent": trap["incumbent"]["value"],
            "challenger": trap["challengerC"]["value"],
        },
        "G2a_no_H_entry_top200": {"pass": not h_entries(C, 200), "entries": h_entries(C, 200)},
        "G2b_no_H_entry_top400": {"pass": not h_entries(C, 400), "entries": h_entries(C, 400)},
        "G2c_median_C_over_I_le_2": {
            "pass": bool(ratios_ci) and statistics.median(ratios_ci) <= 2.0,
            "median": round(statistics.median(ratios_ci), 3) if ratios_ci else None,
        },
        "G3_bounded_influence": {"pass": not g3_violations, "violations": g3_violations},
        "G4_scope": {
            "pass": not nonpick_outside
            and all(p["provenance"] == "rookie_pool_tether" for p in pick_changes),
            "nonPickRowsOutsideHChanged": nonpick_outside,
            "pickChanges": len(pick_changes),
        },
        "G5_off_identical": {
            "pass": bool(off_identity.get("identical")) and off_identity["deterministicRebuild"],
        },
        "G6_semantics_tests": {"pass": semantics["exitCode"] == 0, **semantics},
    }
    all_pass = all(g["pass"] for g in gates.values())
    witnessed = sum(1 for r in h_rows if r["state"] != "uncorroborated")
    if not all_pass:
        verdict = "does not meet gate"
    elif witnessed * 2 < len(h_rows):
        verdict = "insufficient evidence"
    else:
        verdict = "meets gate (promotion-eligible pending independent review)"

    result = {
        "schema": "sparse-evidence-evaluation/v1",
        "preregistration": {
            "path": PREREG,
            "commit": prereg_commit,
            "sha256OfCommittedBlob": _sha(prereg_blob),
        },
        "pins": pins,
        "candidates": {
            "I": "incumbent (flags off)",
            "A": "passthrough (joint_sparse_limited_evidence)",
            "B": "not evaluable: no independent point-in-time prior exists",
            "C": "censor-aware family bounds (sparse_evidence_estimator)",
            "D": "C with uncorroborated rows withheld (diagnostic, from C's stamps)",
        },
        "boardRows": len(I),
        "rowsChangedByGroup": changed_summary,
        "topKChurnVsI": {"C": _churn(I, C), "A": _churn(I, A), "D": _churn(I, d_ranks)},
        "formerHaircut": {
            "count": len(H),
            "matches1571Names": len(set(H) & prior_names),
            "only1571": sorted(prior_names - set(H)),
            "onlyHere": sorted(set(H) - prior_names),
            "incumbentValuesMatch1571": sum(
                1 for r in h_rows if r["prior1571ValueOff"] == r["I"][0]
            ),
            "states": dict(states),
            "withAtLeastOneWitnessFamily": witnessed,
            "ratioCtoI": _dist(ratios_ci),
            "ratioAtoI": _dist(ratios_ai),
            "ratioCtoA": _dist(ratios_ca),
            "entriesTopK": {
                label: {f"top{k}": h_entries(o, k, ranks) for k in TOP_KS}
                for label, o, ranks in (("A", A, None), ("C", C, None), ("D", C, d_ranks))
            },
            "bestRankC": min((r["C"][1] for r in h_rows if r["C"][1]), default=None),
            "bestRankA": min((r["A"][1] for r in h_rows if r["A"][1]), default=None),
            "confidenceC": dict(Counter(r["confidence"] for r in h_rows)),
            "D_withheld": len(withheld_d),
            "rows": h_rows,
        },
        "subsets": {
            label: {
                "count": len(sub),
                "states": dict(Counter(r["state"] for r in sub)),
                "ratioCtoI": _dist([r["ratioCtoI"] for r in sub if r["ratioCtoI"]]),
            }
            for label, sub in (
                ("sparseIdp", [r for r in h_rows if r["group"] == "IDP"]),
                ("offense", [r for r in h_rows if r["group"] != "IDP"]),
                ("rookies", [r for r in h_rows if r["rookie"]]),
            )
        },
        "picks": {"changed": pick_changes},
        "largestMovesC": [{"asset": n, "group": g, "delta": d} for n, g, d in moves],
        "witnessCensus": census,
        "trap": trap,
        "offIdentity": off_identity,
        "gates": gates,
        "verdict": verdict,
    }
    args.out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: v["pass"] for k, v in gates.items()}), verdict)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
