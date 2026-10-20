"""Outlier-integrity-v2 Stage 2 threshold selection (prereg §3.5) on E only.

Every rule here is the registered selection rule as executed under
``outlier_integrity_v2/DEVIATIONS.md`` S3-S9. Inputs are the records written by
``scripts/oiv2_replay.py collect-e`` / ``kc`` / ``tauc`` over E_BASELINE and
E_DEV; nothing here reads a V_HELDOUT, I_INDEPENDENT or R board.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from src.api import source_integrity as si

TAU_AGE_GRID = (1.0, 1.5, 2.0)
EPS_GRID = (0.01, 0.02, 0.05)
N_MIN_GRID = (10, 20)
RHO_GRID = (0.0, 0.3)
TAU_GROSS_GRID = (("ln 3", math.log(3.0)), ("ln 4", math.log(4.0)))
KC_GRID = (4.0, 6.0, 8.0)
H3_H4_BOARDS = ("dynasty_export_20260803_235610.zip", "dynasty_export_20260806_150742.zip")
MIN_TAU_C_PAIRS = 20
FALSE_HOLD_LIMIT = 0.005


def _is_ktc(source: str) -> bool:
    return str(source).lower().startswith("ktc")


def _excluded(rec: Mapping[str, Any], source: str) -> bool:
    """S1: a degraded source's observations never enter history baselines."""
    return bool(rec["board"].get("degraded")) and _is_ktc(source)


def is_clean_dev(rec: Mapping[str, Any]) -> bool:
    b = rec["board"]
    return b["population"] == "E_DEV" and "H1" not in (b.get("labelledCases") or [])


# ── τ_age (S3) ──────────────────────────────────────────────────────────


def select_tau_age(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    diffs = [
        row["absDiff"]
        for rec in records
        if rec["board"]["population"] == "E_DEV"
        for row in rec.get("identityAges") or []
        if row.get("idAgrees") and row.get("preAgeVerdict") != "CONTRADICTED"
    ]
    per = {str(t): sum(1 for d in diffs if d > t) for t in TAU_AGE_GRID}
    feasible = [t for t in TAU_AGE_GRID if per[str(t)] == 0]
    chosen = min(feasible) if feasible else max(TAU_AGE_GRID)
    return {
        "selected": chosen,
        "feasible": bool(feasible),
        "idVerifiedJoinsWithAge": len(diffs),
        "maxAbsDiff": max(diffs) if diffs else None,
        "contradictionsByGrid": per,
    }


# ── ε (S4) ──────────────────────────────────────────────────────────────


def _b2_proof(groups: Mapping[str, Mapping[str, Any]], eps: float) -> list[str]:
    hit = []
    for g, st in sorted(groups.items()):
        m = float(st.get("medianLogRatio") or 0.0)
        if (
            abs(m) > eps
            and int(st.get("rows") or 0) >= si.B2_MIN_GROUP_ROWS
            and float(st.get("signShare") or 0.0) >= si.B2_SIGN_SHARE
        ):
            hit.append(g)
    return hit


def select_epsilon(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    proofs: dict[str, list] = {str(e): [] for e in EPS_GRID}
    boards = 0
    for rec in records:
        if rec["board"]["archive"] in H3_H4_BOARDS:
            continue
        boards += 1
        prov = (rec["builds"]["v2"].get("sourceIntegrity") or {}).get("provenance") or {}
        for source, blk in sorted(prov.items()):
            for e in EPS_GRID:
                hit = _b2_proof(blk.get("groups") or {}, e)
                if len(hit) >= si.B2_MIN_GROUPS:
                    proofs[str(e)].append(
                        {"board": rec["board"]["archive"], "source": source, "groups": hit}
                    )
    feasible = [e for e in EPS_GRID if not proofs[str(e)]]
    return {
        "selected": min(feasible) if feasible else max(EPS_GRID),
        "feasible": bool(feasible),
        "boards": boards,
        "boardProofsByGrid": {k: v[:50] for k, v in proofs.items()},
        "boardProofCountsByGrid": {k: len(v) for k, v in proofs.items()},
    }


# ── τ_board (S5) ────────────────────────────────────────────────────────


def select_tau_board(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    series: dict[str, list[float]] = defaultdict(list)
    for rec in records:
        if rec["board"]["population"] != "E_DEV":
            continue
        med = (rec["builds"]["v2"].get("sourceIntegrity") or {}).get("segmentMedians") or {}
        for key, m in med.items():
            source, ac, pos = (key.split("|") + ["", "", ""])[:3]
            if pos == "*":
                series[f"{source}|{ac}"].append(float(m))
    table = {k: round(statistics.stdev(v), 6) for k, v in sorted(series.items()) if len(v) >= 3}
    return {
        "selected": table,
        "boardsPerCell": {k: len(v) for k, v in sorted(series.items())},
    }


# ── B3b (S6) ────────────────────────────────────────────────────────────


def _hard_findings(
    stats: Mapping[str, Mapping[str, Any]],
    window: Mapping[str, Sequence[float]],
    *,
    n_min: int,
    rho_min: float,
    tau_gross: float,
    tau_board: Mapping[str, float],
    proof: set[str],
) -> dict[str, str]:
    """``{segment key: reason}`` for every hard B3 finding of one board under
    one setting, mirroring ``source_integrity.segment_screen``."""
    out: dict[str, str] = {}
    for key, st in stats.items():
        source, ac, pos = (key.split("|") + ["", "", ""])[:3]
        hist = window.get(key)
        base = statistics.median(hist) if hist else None
        if pos == "*":
            tb = tau_board.get(f"{source}|{ac}")
            m = st.get("medianResidual")
            if base is not None and tb is not None and m is not None:
                if abs(float(m) - base) >= max(si.B3A_MULTIPLIER * tb, si.B3A_FLOOR):
                    out[key] = "B3a_scale"
            continue
        m = st.get("medianSignedDeviation")
        rho = st.get("spearman")
        rows = int(st.get("rows") or 0)
        if rows >= n_min and rho is not None and float(rho) <= rho_min:
            out[key] = "B3b_direction"
        elif base is not None and m is not None and abs(float(m) - base) >= tau_gross:
            out[key] = "B3b_scale"
        elif (
            base is not None
            and m is not None
            and abs(float(m) - base) >= si.B3_SHIFT_FLOOR
            and source in proof
        ):
            out[key] = "B3b_shift_with_proof"
    return out


def _proof_sources(rec: Mapping[str, Any]) -> set[str]:
    integ = rec["builds"]["v2"].get("sourceIntegrity") or {}
    out = {s for s, blk in (integ.get("provenance") or {}).items() if blk.get("boardProof")}
    for f in integ.get("findings") or []:
        if f.get("hard") and str(f.get("scope")) == "source":
            out.add(str(f.get("source")))
    return out


def _advance(window: dict, rec: Mapping[str, Any], quarantined: Mapping[str, str]) -> None:
    med = (rec["builds"]["v2"].get("sourceIntegrity") or {}).get("segmentMedians") or {}
    for key, m in med.items():
        source = key.split("|", 1)[0]
        if _excluded(rec, source) or key in quarantined:
            continue
        window[key] = (list(window.get(key, ())) + [float(m)])[-si.HISTORY_WINDOW :]


def select_b3(records: Sequence[Mapping[str, Any]], tau_board: Mapping[str, float]) -> dict:
    settings = []
    for n_min in N_MIN_GRID:
        for rho in RHO_GRID:
            for lab, tg in TAU_GROSS_GRID:
                window: dict[str, list[float]] = {}
                clean_flags: list[dict] = []
                inj_total = inj_caught = 0
                missed: list[dict] = []
                for rec in records:
                    stats = (rec["builds"]["v2"].get("sourceIntegrity") or {}).get(
                        "segmentStats"
                    ) or {}
                    proof = _proof_sources(rec)
                    kw = dict(
                        n_min=n_min, rho_min=rho, tau_gross=tg, tau_board=tau_board, proof=proof
                    )
                    hard = _hard_findings(stats, window, **kw)
                    if is_clean_dev(rec):
                        for k, why in sorted(hard.items()):
                            clean_flags.append(
                                {"board": rec["board"]["archive"], "segment": k, "rule": why}
                            )
                    for inj in rec.get("injections") or []:
                        if not inj.get("rows"):
                            continue
                        inj_total += 1
                        ih = _hard_findings(inj.get("segmentStats") or {}, window, **kw)
                        if ih:
                            inj_caught += 1
                        else:
                            missed.append(
                                {
                                    "board": rec["board"]["archive"],
                                    "source": inj["source"],
                                    "assetClass": inj["assetClass"],
                                    "kind": inj["kind"],
                                }
                            )
                    _advance(window, rec, hard)
                by_kind: dict[str, list[int]] = defaultdict(lambda: [0, 0])
                for m in missed:
                    by_kind[m["kind"]][0] += 1
                settings.append(
                    {
                        "n_min": n_min,
                        "rho_min": rho,
                        "tau_gross": lab,
                        "cleanHardFlags": len(clean_flags),
                        "cleanHardFlagSample": clean_flags[:30],
                        "injections": inj_total,
                        "injectionsCaught": inj_caught,
                        "injectionCatchRate": round(inj_caught / inj_total, 4)
                        if inj_total
                        else None,
                        "missedByKind": {k: v[0] for k, v in sorted(by_kind.items())},
                        "missedSample": missed[:30],
                        "feasible": not clean_flags and inj_total > 0 and inj_caught == inj_total,
                    }
                )
    feasible = [s for s in settings if s["feasible"]]
    if feasible:
        best = sorted(
            feasible,
            key=lambda s: (-s["n_min"], s["rho_min"], -dict(TAU_GROSS_GRID)[s["tau_gross"]]),
        )[0]
        status = "SELECTED"
    else:
        best = next(
            s
            for s in settings
            if s["n_min"] == 20 and s["rho_min"] == 0.0 and s["tau_gross"] == "ln 4"
        )
        status = "FAILED_SELECTION"
    return {
        "status": status,
        "selected": {
            "n_min": best["n_min"],
            "rho_min": best["rho_min"],
            "tau_gross": best["tau_gross"],
        },
        "settings": settings,
    }


# ── τ_c table (S7) ──────────────────────────────────────────────────────


def tau_c_mad(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """``{source: {band: MAD}}`` of consecutive accepted same-player Δu."""
    prev: dict[str, tuple[int, float]] = {}
    deltas: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for i, rec in enumerate(records):
        rows = rec["builds"]["v2"]["rows"]
        for row in rows.values():
            pk, ac = row.get("pk"), row.get("ac")
            if not pk or ac == "pick":
                continue
            for source, (val, _w, state) in (row.get("obs") or {}).items():
                if val is None or val <= 0 or state not in ("voting", "filter_dropped"):
                    continue
                if _excluded(rec, source):
                    continue
                u = si.vote_coordinate(val, ac)
                if u is None:
                    continue
                key = f"{source}|{pk}"
                got = prev.get(key)
                if got is not None and got[0] == i - 1:
                    deltas[source][si.depth_band(got[1])].append(u - got[1])
                prev[key] = (i, u)
    out: dict[str, dict[str, Any]] = {}
    for source, bands in sorted(deltas.items()):
        pooled = [d for v in bands.values() for d in v]
        if len(pooled) < MIN_TAU_C_PAIRS:
            continue
        med = statistics.median(pooled)
        pooled_mad = statistics.median(abs(d - med) for d in pooled)
        cells = {}
        for band in sorted(bands):
            v = bands[band]
            if len(v) >= MIN_TAU_C_PAIRS:
                m = statistics.median(v)
                cells[band] = {"mad": statistics.median(abs(d - m) for d in v), "n": len(v)}
            else:
                cells[band] = {"mad": pooled_mad, "n": len(v), "pooled": True}
        for _edge, band in si.B4_BANDS:
            cells.setdefault(band, {"mad": pooled_mad, "n": 0, "pooled": True})
        out[source] = {"pooledMad": pooled_mad, "pooledN": len(pooled), "bands": cells}
    return out


def tau_c_table(mads: Mapping[str, Any], k_c: float) -> dict[str, dict[str, float]]:
    return {
        source: {
            band: round(max(si.B4_MIN_TAU_C, k_c * 1.4826 * float(c["mad"])), 6)
            for band, c in blk["bands"].items()
        }
        for source, blk in mads.items()
    }


def select_kc(kc_records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    per: dict[str, list[dict]] = {str(k): [] for k in KC_GRID}
    for rec in kc_records:
        if not is_clean_dev(rec):
            continue
        for k in KC_GRID:
            r = rec["kc"][str(k)]
            rate = r["holds"] / r["votes"] if r["votes"] else 0.0
            per[str(k)].append(
                {
                    "board": rec["board"]["archive"],
                    "rate": round(rate, 6),
                    "holds": r["holds"],
                    "votes": r["votes"],
                }
            )
    summary = {
        k: {
            "boards": len(v),
            "maxRate": max((x["rate"] for x in v), default=None),
            "totalHolds": sum(x["holds"] for x in v),
            "feasible": bool(v) and all(x["rate"] <= FALSE_HOLD_LIMIT for x in v),
            "worst": sorted(v, key=lambda x: -x["rate"])[:5],
        }
        for k, v in per.items()
    }
    feasible = [k for k in KC_GRID if summary[str(k)]["feasible"]]
    return {
        "selected": min(feasible) if feasible else 8.0,
        "feasible": bool(feasible),
        "byKc": summary,
    }


def select_tau_c_big(
    tauc_records: Sequence[Mapping[str, Any]], grid: Sequence[tuple[str, float]]
) -> dict:
    rates: dict[str, dict[str, Any]] = {}
    for lab, _t in grid:
        rates[lab] = {}
        for gate in ("AD1c", "AD1d"):
            mat = [
                c
                for rec in tauc_records
                for c in rec["cases"]
                if c["gate"] == gate and c["harmNone"] is not None and c["harmNone"] >= 0.10
            ]
            passed = [
                c
                for c in mat
                if c[lab]["excluded"] or (c[lab]["harm"] is not None and c[lab]["harm"] < 0.10)
            ]
            rates[lab][gate] = {
                "material": len(mat),
                "passed": len(passed),
                "rate": round(len(passed) / len(mat), 4) if mat else None,
            }
        rates[lab]["feasible"] = all((rates[lab][g]["rate"] or 0) >= 0.95 for g in ("AD1c", "AD1d"))
    feasible = [(lab, t) for lab, t in grid if rates[lab]["feasible"]]
    chosen = max(feasible, key=lambda x: x[1])[0] if feasible else "ln 4"
    return {
        "selected": chosen,
        "feasible": bool(feasible),
        "byGrid": rates,
        "boards": [r["board"]["archive"] for r in tauc_records],
    }
