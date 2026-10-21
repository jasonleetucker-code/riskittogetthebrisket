#!/usr/bin/env python3
"""Outlier-integrity V2.1 EXPLORATORY / DEV evaluation driver.

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md``;
library ``src/robust_filter_shadow/oiv21_dev.py``; dev-stage execution choices
logged in ``docs/sources/outlier_integrity_v21/DEVIATIONS.md`` (V21-D*) before
any result that depends on them was read.

**DEV boards only.**  Every board is checked against the V2.1 populations
manifest (``outlier_integrity_v21/manifests/POPULATIONS.json``): a board that is
not in DEV is refused -- R pins (Stage 3), SPENT boards (never) and every
archive added after T0 (the sealed held-out set, Stage 4).  Nothing here writes
``config/sources/outlier_integrity_v21.json`` (the Stage 2 freeze); the
exploratory selection is written under ``docs/.../dev/`` only.

Records (gz JSON) go to ``data/oiv21_dev/<stage>/`` (gitignored).

Subcommands are listed by ``--help``.  Exit codes: 0 done; 1 refused / inputs
missing; 2 a build failed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import oiv2_replay as R2  # noqa: E402
from src.robust_filter_shadow import oiv2_gates as G  # noqa: E402
from src.robust_filter_shadow import oiv2_replay as RP  # noqa: E402
from src.robust_filter_shadow import oiv21_dev as D  # noqa: E402

OUT_ROOT = REPO_ROOT / "data" / "oiv21_dev"
DEV_OUT = REPO_ROOT / "docs" / "sources" / "outlier_integrity_v21" / "dev"
POPULATIONS = (
    REPO_ROOT / "docs" / "sources" / "outlier_integrity_v21" / "manifests" / "POPULATIONS.json"
)
SELECTION_INJECT = R2.SELECTION_INJECT  # prereg §3.6: V2's non-registered sources


def log(msg: str) -> None:
    print(f"[oiv21-dev] {msg}", flush=True)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dev_boards() -> dict[str, dict]:
    pops = json.loads(POPULATIONS.read_text("utf-8"))
    return {e["board"]: e for e in pops["DEV"]}


def assert_dev_only(names) -> None:
    dev = dev_boards()
    bad = [n for n in names if n not in dev]
    if bad:
        raise SystemExit(f"[oiv21-dev] not DEV boards (refused): {bad}")


def write_gz(path: Path, rec: Any) -> None:
    R2._write(path, rec)


def read_gz(path: Path) -> Any:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return json.load(fh)


def code_pins() -> dict[str, Any]:
    from src.api import source_integrity as si  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    return {
        "codeSha": (vr._git("rev-parse", "HEAD") or "").strip() or None,
        "workingTreeDirty": vr._dirty(),
        "v2ThresholdsFileSha256": _sha(si.THRESHOLDS_PATH.read_bytes()),
        "v21ThresholdsFileExists": si.V21_THRESHOLDS_PATH.exists(),
        "preregistration": D.PREREG,
        "directory": DIRECTORY_STAMP,
    }


DIRECTORY_STAMP: dict[str, Any] = {}


def set_directory(path: str | None) -> None:
    global DIRECTORY_STAMP
    if path:
        p = Path(path)
        DIRECTORY_STAMP = {
            "path": str(p),
            "sha256": _sha(p.read_bytes()),
            "mtime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(p.stat().st_mtime)),
        }
        D.set_directory(p)
    else:
        DIRECTORY_STAMP = {"path": None}
        D.set_directory(None)


def iterate(pops=("E_BASELINE", "E_DEV")):
    """``(entry, cut, raw, root)`` per DEV board, add-time order, hash-checked
    against V2's frozen manifests AND the V2.1 DEV list."""
    dev = dev_boards()
    for entry, cut, raw, root in R2.iterate(list(pops)):
        if entry["board"] not in dev:
            raise SystemExit(f"[oiv21-dev] {entry['board']} is not DEV; refused")
        e21 = dev[entry["board"]]
        if e21["zipSha256"] != entry["zipSha256"] or e21["payloadSha256"] != entry["payloadSha256"]:
            raise SystemExit(f"[oiv21-dev] {entry['board']} hash differs from POPULATIONS.json")
        yield entry, cut, raw, root


def extract21(contract: dict, *, full: bool = True) -> dict[str, Any]:
    from src.api import source_integrity as si  # noqa: PLC0415

    out = RP.extract(contract, full=full)
    integ = contract.get("sourceIntegrity") or {}
    out["proofSources"] = integ.get("proofSources")
    out["hashes"] = si.board_record(contract).get("hashes")
    out["counts"] = D.board_counts(contract)
    return out


# ── collect: the Stage-2-shaped input pass at the provisional thresholds ──


def cmd_collect(args: argparse.Namespace) -> int:
    out_dir = OUT_ROOT / "collect"
    pins = code_pins()
    history = None
    t0 = time.time()
    for entry, cut, raw, root in iterate():
        name = Path(entry["board"]).stem
        write_gz(
            out_dir / "_history_before" / f"{name}.json.gz",
            {"beforeBoard": entry["board"], "history": D.history_json(history)},
        )
        prov = D.ProvenanceRecorder()
        with prov.active():
            c21 = D.build(raw, root, "v21", history=history)
        rec: dict[str, Any] = {
            "schema": D.SCHEMA,
            "stage": "collect_provisional",
            "board": R2.board_meta(entry, cut),
            "pins": pins,
            "historyIn": {"boards": 0 if history is None else history.boards},
            "thresholds": (c21.get("sourceIntegrity") or {}).get("thresholds"),
            "builds": {"v21": extract21(c21)},
            "provenancePairs": prov.calls,
        }
        if entry["population"] == "E_DEV":
            cinc = D.build(raw, root, "inc")
            rec["builds"]["inc"] = RP.extract(cinc, full=True)
            inj = []
            for source, ac in SELECTION_INJECT:
                for kind in G.AD3_KINDS:
                    ov = G.ad3_overrides(c21, source, ac, kind)
                    if not ov:
                        inj.append({"source": source, "assetClass": ac, "kind": kind, "rows": 0})
                        continue
                    ci = D.build(raw, root, "v21", history=history, transform=G.transform_for(ov))
                    integ = ci.get("sourceIntegrity") or {}
                    pref = f"{source}|{ac}|"
                    inj.append(
                        {
                            "source": source,
                            "assetClass": ac,
                            "kind": kind,
                            "rows": len(ov),
                            "segmentStats": {
                                k: v
                                for k, v in (integ.get("segmentStats") or {}).items()
                                if k.startswith(pref)
                            },
                            "proofSources": integ.get("proofSources"),
                            "sourceQuarantine": (integ.get("sourceQuarantines") or {}).get(source),
                            "findings": [
                                f for f in integ.get("findings") or [] if f.get("source") == source
                            ],
                        }
                    )
            rec["injections"] = inj
        write_gz(out_dir / f"{name}.json.gz", rec)
        history = D.advance(history, c21, entry.get("degraded") or [])
        log(
            f"{entry['board']} {entry['population']} lane={history.boards} t={time.time() - t0:.0f}s"
        )
    write_gz(out_dir / "_history_final.json.gz", {"history": D.history_json(history)})
    return 0


# ── collect-b3off: the B3 selection inputs with B4 abstaining (V21-D16) ─


def cmd_collect_b3off(args: argparse.Namespace) -> int:
    """E_DEV only: the clean V2.1 build and the B3-selection injections
    rebuilt with an EMPTY tau_c table (B4 abstains, as in V2's phase 1,
    where B3 is selected before k_c and its tau_c table exist), on the
    same DEV lane as ``collect``."""
    import dataclasses  # noqa: PLC0415

    from src.api import source_integrity as si  # noqa: PLC0415

    th = dataclasses.replace(D.thresholds_from({}), tau_c={})
    out_dir = OUT_ROOT / "collect_b3off"
    t0 = time.time()
    for entry, cut, raw, root in iterate():
        if entry["population"] != "E_DEV":
            continue
        name = Path(entry["board"]).stem
        hist = D.history_from(
            read_gz(OUT_ROOT / "collect" / "_history_before" / f"{name}.json.gz")["history"]
        )
        c21 = D.build(raw, root, "v21", history=hist, thresholds=th)
        b = extract21(c21)
        rec = {
            "schema": D.SCHEMA,
            "stage": "collect_b3off",
            "board": R2.board_meta(entry, cut),
            "builds": {
                "v21": {"sourceIntegrity": b["sourceIntegrity"], "proofSources": b["proofSources"]}
            },
        }
        inj = []
        for source, ac in SELECTION_INJECT:
            for kind in G.AD3_KINDS:
                ov = G.ad3_overrides(c21, source, ac, kind)
                if not ov:
                    inj.append({"source": source, "assetClass": ac, "kind": kind, "rows": 0})
                    continue
                ci = D.build(
                    raw, root, "v21", history=hist, thresholds=th, transform=G.transform_for(ov)
                )
                integ = ci.get("sourceIntegrity") or {}
                pref = f"{source}|{ac}|"
                inj.append(
                    {
                        "source": source,
                        "assetClass": ac,
                        "kind": kind,
                        "rows": len(ov),
                        "segmentStats": {
                            k: v
                            for k, v in (integ.get("segmentStats") or {}).items()
                            if k.startswith(pref)
                        },
                        "proofSources": integ.get("proofSources"),
                        "sourceQuarantine": (integ.get("sourceQuarantines") or {}).get(source),
                    }
                )
        rec["injections"] = inj
        write_gz(out_dir / f"{name}.json.gz", rec)
        log(f"b3off {entry['board']} t={time.time() - t0:.0f}s")
    del si
    return 0


def cmd_select1b(args: argparse.Namespace) -> int:
    """B3 re-selected on the B4-abstaining inputs (V21-D16); E_BASELINE
    boards carry no injections and enter only the window, from ``collect``."""
    from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

    sel = json.loads(SEL_PATH.read_text("utf-8"))
    base = {r["board"]["archive"]: r for r in _load("collect")}
    off = {r["board"]["archive"]: r for r in _load("collect_b3off")}
    recs = []
    for name, r in sorted(base.items(), key=lambda kv: kv[1]["board"]["addTime"]):
        if name in off:
            recs.append(
                {
                    "board": r["board"],
                    "builds": {"v21": off[name]["builds"]["v21"]},
                    "injections": off[name]["injections"],
                }
            )
        else:
            recs.append(
                {"board": r["board"], "builds": {"v21": r["builds"]["v21"]}, "injections": []}
            )
    b3 = D.select_b3(recs, sel["tau_board"])
    sel["evidence"]["b3_b4Active"] = sel["evidence"]["b3"]
    sel["evidence"]["b3_b4Abstaining"] = b3
    sel["b3_b4Abstaining"] = b3["selected"]
    sel["b3Status_b4Abstaining"] = b3["status"]
    SEL_PATH.write_text(json.dumps(sel, indent=1, sort_keys=True) + "\n", "utf-8")
    log(
        json.dumps(
            {
                "b3": b3["selected"],
                "status": b3["status"],
                "settings": [
                    (
                        s["n_min"],
                        s["rho_min"],
                        s["tau_gross"],
                        s["cleanHardFlags"],
                        s["injectionsCaught"],
                        s["injections"],
                    )
                    for s in b3["settings"]
                ],
            }
        )
    )
    del S
    return 0


# ── selection (prereg §3.6), exploratory: never frozen here ─────────────


def _load(stage: str) -> list[dict]:
    recs = [read_gz(f) for f in sorted((OUT_ROOT / stage).glob("dynasty_export_*.json.gz"))]
    recs.sort(key=lambda r: r["board"]["addTime"])
    return recs


SEL_PATH = OUT_ROOT / "selection.json"


def cmd_select1(args: argparse.Namespace) -> int:
    from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

    recs = _load("collect")
    if len(recs) != 79 or {r["board"]["population"] for r in recs} - {"E_BASELINE", "E_DEV"}:
        log(f"collect incomplete or not DEV-only: {len(recs)} boards")
        return 1
    eps = D.select_epsilon(recs)
    tb = S.select_tau_board([{**r, "builds": {"v2": r["builds"]["v21"]}} for r in recs])
    b3 = D.select_b3(recs, tb["selected"])
    mads = D.tau_c_mad(recs)
    # V2-RPC error cells: E_BASELINE pre-Layer-C panels (V21-D6).
    panels = []
    for r in recs:
        if r["board"]["population"] != "E_BASELINE":
            continue
        for row in r["builds"]["v21"]["rows"].values():
            if row.get("ac") in (None, "pick"):
                continue
            pan = RP.voting_panel(row.get("obs") or {})
            if len(pan) >= 2:
                panels.append((row["ac"], pan))
    rpc = D.fit_rpc_model(panels)
    out = {
        "schema": "oiv21-dev-selection/v1",
        "status": "EXPLORATORY_DEV_NOT_FROZEN",
        "seed": D.SELECTION_SEED,
        "boardsRead": [r["board"]["archive"] for r in recs],
        "evidence": {"epsilon_b2": eps, "tau_board": tb, "b3": b3, "tau_c_mad": mads},
        "epsilon_b2": eps["selected"],
        "tau_board": tb["selected"],
        "b3": b3["selected"],
        "b3Status": b3["status"],
        "tau_c_tables": {str(int(k)): D.tau_c_table(mads, k) for k in D.KC_GRID},
        "rpcModel": rpc,
        "failedSelection": [
            k
            for k, ok in (("epsilon_b2", eps["feasible"]), ("b3", b3["status"] == "SELECTED"))
            if not ok
        ],
    }
    SEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEL_PATH.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", "utf-8")
    log(json.dumps({k: out[k] for k in ("epsilon_b2", "b3", "b3Status", "failedSelection")}))
    return 0


def _partial_thresholds(sel: dict, **over):
    base = dict(sel)
    if base.get("b3") is None and base.get("b3_b4Abstaining"):
        base["b3"] = base["b3_b4Abstaining"]  # V21-D16
    if base.get("b3") is None:
        # FAILED_SELECTION: the run cannot reach READY; development continues
        # at V2's registered conservative point so later stages still run.
        base["b3"] = {"n_min": 20, "rho_min": 0.0, "tau_gross": "ln 4"}
    if base.get("epsilon_b2") is None:
        base["epsilon_b2"] = max(D.EPS_GRID)
    return D.thresholds_from(base, **over)


def cmd_kc(args: argparse.Namespace) -> int:
    sel = json.loads(SEL_PATH.read_text("utf-8"))
    out_dir = OUT_ROOT / "kc"
    chains: dict[str, Any] = {str(k): None for k in D.KC_GRID}
    th = {
        str(k): _partial_thresholds(sel, k_c=k, tau_c=sel["tau_c_tables"][str(int(k))])
        for k in D.KC_GRID
    }
    t0 = time.time()
    for entry, cut, raw, root in iterate():
        name = Path(entry["board"]).stem
        rec = {"schema": D.SCHEMA, "stage": "kc", "board": R2.board_meta(entry, cut)}
        res = {}
        for k in D.KC_GRID:
            key = str(k)
            write_gz(
                out_dir / f"_history_k{int(k)}" / f"{name}.json.gz",
                {"beforeBoard": entry["board"], "history": D.history_json(chains[key])},
            )
            c = D.build(raw, root, "v21", history=chains[key], thresholds=th[key])
            holds = votes = 0
            held = []
            for r in c.get("playersArray") or []:
                if r.get("assetClass") == "pick":
                    continue
                for s, m in (r.get("sourceRankMeta") or {}).items():
                    if not isinstance(m, dict) or (m.get("valueContribution") in (None, 0)):
                        continue
                    st = RP.vote_state(m)
                    if st in ("voting", "filter_dropped") or st.startswith("integrity:held"):
                        votes += 1
                    if st.startswith("integrity:held"):
                        holds += 1
                        held.append([r.get("displayName"), s])
            res[key] = {"votes": votes, "holds": holds, "held": held[:200]}
            chains[key] = D.advance(chains[key], c, entry.get("degraded") or [])
        rec["kc"] = res
        write_gz(out_dir / f"{name}.json.gz", rec)
        log(
            f"kc {entry['board']} "
            + " ".join(f"k{k}:{res[str(k)]['holds']}/{res[str(k)]['votes']}" for k in D.KC_GRID)
            + f" t={time.time() - t0:.0f}s"
        )
    return 0


def cmd_select2(args: argparse.Namespace) -> int:
    from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

    sel = json.loads(SEL_PATH.read_text("utf-8"))
    kc = S.select_kc(_load("kc"))
    feasible = bool(kc["feasible"])
    kc["selected"] = (
        min(k for k in D.KC_GRID if kc["byKc"][str(k)]["feasible"]) if feasible else None
    )
    sel["evidence"]["k_c"] = kc
    sel["k_c"] = kc["selected"]
    sel["tau_c"] = sel["tau_c_tables"][str(int(kc["selected"]))] if feasible else None
    if not feasible:
        sel["failedSelection"] = sorted(set(sel["failedSelection"]) | {"k_c"})
    SEL_PATH.write_text(json.dumps(sel, indent=1, sort_keys=True) + "\n", "utf-8")
    log(
        json.dumps(
            {
                "k_c": sel["k_c"],
                "byKc": {
                    k: {kk: v[kk] for kk in ("maxRate", "totalHolds", "feasible")}
                    for k, v in kc["byKc"].items()
                },
            }
        )
    )
    return 0


# ── the labelled legitimate set L4 on DEV (prereg §7.4) ─────────────────

L4_BOARDS: dict[str, list[str]] = {
    "H4": ["dynasty_export_20260803_235610.zip", "dynasty_export_20260806_150742.zip"],
    "N1": ["dynasty_export_20260819_230341.zip", "dynasty_export_20260820_230504.zip"],
    "N2": [
        "dynasty_export_20260825_230528.zip",
        "dynasty_export_20260826_211658.zip",
        "dynasty_export_20260827_153424.zip",
        "dynasty_export_20260829_211720.zip",
        "dynasty_export_20260830_213746.zip",
    ],
    "N3": [
        "dynasty_export_20260924_232149.zip",
        "dynasty_export_20260925_233646.zip",
        "dynasty_export_20260926_164906.zip",
        "dynasty_export_20260927_214140.zip",
        "dynasty_export_20260928_233322.zip",
        "dynasty_export_20260929_194208.zip",
        "dynasty_export_20260930_130404.zip",
    ],
    "N5": ["dynasty_export_20260804_234442.zip", "dynasty_export_20260805_234032.zip"],
}
H1_SOURCES = ("dlfRookieSf", "flockFantasySfRookies")
N6_SOURCES = R2.N_SOURCES["N6"]
H3_ROW = ("dynasty_export_20260803_235610.zip", "Justin Jefferson", "idpTradeCalc")


def l4_exclude_for(entry: dict):
    h1 = "H1" in (entry.get("labelledCases") or [])

    def _ex(row: str, source: str) -> bool:
        if h1 and source in H1_SOURCES:
            return True
        return (entry["board"], row, source) == H3_ROW

    return _ex


def l4_board_set() -> set[str]:
    return {b for v in L4_BOARDS.values() for b in v}


TAUC_BOARDS = (
    "dynasty_export_20260818_230211.zip",
    "dynasty_export_20260901_212308.zip",
    "dynasty_export_20260916_214700.zip",
    "dynasty_export_20260930_130404.zip",
)


def cmd_tauc(args: argparse.Namespace) -> int:
    sel = json.loads(SEL_PATH.read_text("utf-8"))
    kc = sel.get("k_c") or 8.0
    tau_c = sel.get("tau_c") or sel["tau_c_tables"][str(int(kc))]
    th = {lab: _partial_thresholds(sel, k_c=kc, tau_c=tau_c, tau_c_big=t) for lab, t in D.TAUC_GRID}
    out_dir = OUT_ROOT / "tauc"
    l4 = l4_board_set()
    l4_only = bool(getattr(args, "l4_only", False))
    want = l4 if l4_only else set(TAUC_BOARDS) | l4
    for entry, cut, raw, root in iterate():
        b = entry["board"]
        if b not in want:
            continue
        t0 = time.time()
        rec: dict[str, Any] = {
            "schema": D.SCHEMA,
            "stage": "tauc",
            "board": R2.board_meta(entry, cut),
        }
        prior = out_dir / f"{Path(b).stem}.json.gz"
        if l4_only and prior.exists():
            # V21-D17: recompute only the L4 measurement; keep the value cases.
            rec = read_gz(prior)
            rec["l4MeasurementRevision"] = "V21-D17"
        if b in l4:
            ex = l4_exclude_for(entry)
            rec["l4"] = {}
            for lab in th:
                c = D.build(raw, root, "v21", history=None, thresholds=th[lab])
                got = D.l4_drops(c, exclude=ex)
                rec["l4"][lab] = {
                    "votes": got["votes"],
                    "dropped": got["dropped"],
                    "drops": got["drops"][:200],
                }
        if b in TAUC_BOARDS and not l4_only:
            hist = D.history_from(
                read_gz(OUT_ROOT / "kc" / f"_history_k{int(kc)}" / f"{Path(b).stem}.json.gz")[
                    "history"
                ]
            )
            clean = {
                "none": D.build(raw, root, "none"),
                "inc": D.build(raw, root, "inc"),
                "cand": D.build(raw, root, "v21", history=hist, thresholds=th["ln 6"]),
            }
            cases = D.plan_cases(
                clean,
                seed=D.SELECTION_SEED,
                allowed_sources=[s for s, _ac in SELECTION_INJECT],
                gates=("AD1a", "AD1b", "AD1c", "AD1d", "AD4"),
            )
            specs = [D.Spec("none", "none")] + [D.Spec(lab, "v21", hist, th[lab]) for lab in th]
            cl = {"none": clean["none"]}
            for lab in th:
                cl[lab] = (
                    clean["cand"]
                    if lab == "ln 6"
                    else D.build(raw, root, "v21", history=hist, thresholds=th[lab])
                )
            results, census = D.run_value_cases(raw, root, specs, cl, cases, progress=log)
            rec["cases"] = results
            rec["contamination"] = census
        write_gz(out_dir / f"{Path(b).stem}.json.gz", rec)
        log(f"tauc {b} t={time.time() - t0:.0f}s")
    return 0


CAND_PATH = OUT_ROOT / "candidate_thresholds.json"


def cmd_select3(args: argparse.Namespace) -> int:
    sel = json.loads(SEL_PATH.read_text("utf-8"))
    recs = _load("tauc")
    by_grid: dict[str, Any] = {}
    for lab, _t in D.TAUC_GRID:
        entry: dict[str, Any] = {}
        items = [c for r in recs for c in r.get("cases") or []]
        for gate, bar in (
            ("AD1a", 0.90),
            ("AD1b", 0.90),
            ("AD1c", 0.95),
            ("AD1d", 0.95),
            ("AD4", 0.95),
        ):
            mat = [c for c in items if c["gate"] == gate and D.case_material(c)]
            ok = [c for c in mat if D.case_passed(c, lab)]
            entry[gate] = {
                "material": len(mat),
                "passed": len(ok),
                "rate": round(len(ok) / len(mat), 4) if mat else None,
                "bar": bar,
            }
        l4 = [r["l4"][lab] for r in recs if r.get("l4")]
        entry["l4Boards"] = len(l4)
        entry["l4Votes"] = sum(x["votes"] for x in l4)
        entry["l4Dropped"] = sum(x["dropped"] for x in l4)
        entry["l4DropsByLayer"] = dict(
            sorted(
                __import__("collections")
                .Counter(d["layer"] for x in l4 for d in x["drops"])
                .items()
            )
        )
        entry["feasible"] = (
            all(
                (entry[g]["rate"] or 0) >= entry[g]["bar"]
                for g in ("AD1a", "AD1b", "AD1c", "AD1d", "AD4")
            )
            and entry["l4Dropped"] == 0
        )
        by_grid[lab] = entry
    feasible = [(lab, t) for lab, t in D.TAUC_GRID if by_grid[lab]["feasible"]]
    chosen = max(feasible, key=lambda x: x[1])[0] if feasible else None
    sel["evidence"]["tau_C"] = {
        "boards": [r["board"]["archive"] for r in recs if r.get("cases") is not None],
        "l4Boards": [r["board"]["archive"] for r in recs if r.get("l4")],
        "byGrid": by_grid,
        "feasible": bool(feasible),
        "selected": chosen,
    }
    sel["tau_C"] = chosen
    if chosen is None:
        sel["failedSelection"] = sorted(set(sel["failedSelection"]) | {"tau_C"})
        # Development continues at the grid point with the fewest cold-start
        # drops (ties: the largest); it is NOT a selection (V21-D5).
        cont = sorted(D.TAUC_GRID, key=lambda x: (by_grid[x[0]]["l4Dropped"], -x[1]))[0][0]
        sel["devContinuation"] = {"tau_C": cont, "note": "not a selection: FAILED_SELECTION"}
    SEL_PATH.write_text(json.dumps(sel, indent=1, sort_keys=True) + "\n", "utf-8")
    cand = {
        "epsilon_b2": sel["epsilon_b2"] if sel["epsilon_b2"] is not None else max(D.EPS_GRID),
        "tau_board": sel["tau_board"],
        "b3": sel["b3"] or {"n_min": 20, "rho_min": 0.0, "tau_gross": "ln 4"},
        "k_c": sel.get("k_c") or 8.0,
        "tau_c": sel.get("tau_c") or sel["tau_c_tables"]["8"],
        "tau_C": chosen or sel["devContinuation"]["tau_C"],
        "failedSelection": sel["failedSelection"],
    }
    CAND_PATH.write_text(json.dumps(cand, indent=1, sort_keys=True) + "\n", "utf-8")
    DEV_OUT.mkdir(parents=True, exist_ok=True)
    (DEV_OUT / "SELECTION_EXPLORATORY.json").write_text(
        json.dumps(sel, indent=1, sort_keys=True) + "\n", "utf-8"
    )
    log(
        json.dumps(
            {
                "tau_C": chosen,
                "byGrid": {
                    k: {kk: v[kk] for kk in ("feasible", "l4Dropped")}
                    | {g: v[g]["rate"] for g in ("AD1a", "AD1b", "AD1c", "AD1d", "AD4")}
                    for k, v in by_grid.items()
                },
                "failedSelection": sel["failedSelection"],
            }
        )
    )
    return 0


def candidate_thresholds():
    return D.thresholds_from(json.loads(CAND_PATH.read_text("utf-8")))


def rpc_model() -> dict:
    return json.loads(SEL_PATH.read_text("utf-8"))["rpcModel"]


# ── chain: the DEV history lanes at the candidate thresholds, plus every
#    per-board record (clean false exclusions, labelled cases, DLF pairs) ──

RESTORE = {
    "dlfIdp": ("B", "C", "idp", ("dlfIdp", "dlfRookieIdp")),
    "d4": ("Bp", "Cp", "offense", ("dlfValuesSfTep",)),
    "both": ("Bpp", "Cpp", None, ("dlfIdp", "dlfRookieIdp", "dlfValuesSfTep")),
}


def restore_pairs(builds: dict[str, dict]) -> dict[str, Any]:
    """Directive §6 generalised: (row, source) pairs the incumbent newly drops
    when a DLF restoration votes (DLF's own votes excluded), and V2.1's fate
    for each, ARRIVING (C) and NO-HISTORY (Cnh)."""
    a = D.rows_by_name(builds["inc"])
    out = {}
    for tag, (bc, cc, ac, own) in RESTORE.items():
        b = D.rows_by_name(builds[bc])
        cs = {k: D.rows_by_name(builds[k]) for k in (cc, cc + "nh") if k in builds}
        pairs = []
        for name, e in b.items():
            ra = a.get(name)
            if ra is None or ra.get("assetClass") == "pick" or (ac and ra.get("assetClass") != ac):
                continue
            newly = (
                set(e.get("droppedSources") or []) - set(ra.get("droppedSources") or []) - set(own)
            )
            for src in sorted(newly):
                item = {
                    "row": name,
                    "source": src,
                    "position": ra.get("position"),
                    "valueA": D.value_of(ra),
                    "valueB": D.value_of(e),
                }
                for k, rows in cs.items():
                    item["fate_" + k] = D.exclusion_of(rows.get(name), src)
                    item["value_" + k] = D.value_of(rows.get(name))
                pairs.append(item)
        out[tag] = {
            "newlyDroppedByIncumbent": len(pairs),
            "retained": {k: sum(1 for p in pairs if p.get("fate_" + k) is None) for k in cs},
            "pairs": pairs,
        }
    return out


def labelled_checks(entry: dict, c21: dict, c21nh: dict) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lab = entry.get("labelledCases") or []
    for variant, c in (("arriving", c21), ("nohist", c21nh)):
        rows = D.rows_by_name(c)
        integ = c.get("sourceIntegrity") or {}
        chk: dict[str, Any] = {}
        # H1: every rookie-ladder vote withheld on H1 boards, 0 fires elsewhere.
        rk = {"withheld": 0, "voting": 0, "other": 0}
        for r in rows.values():
            for s in H1_SOURCES:
                ex = D.exclusion_of(r, s)
                if ex == "observation_absent":
                    continue
                if ex in ("normalization_untranslated", "normalization_dependency_unavailable"):
                    rk["withheld"] += 1
                elif ex is None:
                    rk["voting"] += 1
                else:
                    rk["other"] += 1
        chk["H1"] = {"labelled": "H1" in lab, **rk}
        # N6: no hard quarantine of an N6-listed source's votes.
        chk["N6hard"] = sorted(
            [s for s in (integ.get("sourceQuarantines") or {}) if s in N6_SOURCES]
            + [
                k
                for k in (integ.get("segmentQuarantines") or {})
                if str(k).split("/")[0] in N6_SOURCES
            ]
        )
        # N4: yahooBoone never read as a value of zero; no V2.1 exclusion of it.
        yb = [D.v21_layer_drop(r, "yahooBoone") for r in rows.values()]
        zero = sum(
            1
            for r in rows.values()
            if ((r.get("sourceRankMeta") or {}).get("yahooBoone") or {}).get("valueContribution")
            == 0
        )
        chk["N4"] = {"v21Excluded": sum(1 for x in yb if x), "zeroValueVotes": zero}
        if entry["board"] in H3_H4:
            jj = rows.get("Justin Jefferson") or {}
            chk["H3"] = {
                "exclusion": D.exclusion_of(jj, "idpTradeCalc"),
                "vote": ((jj.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}).get(
                    "valueContribution"
                ),
                "provenance": jj.get("sourceProvenance"),
            }
            chk["H4"] = {
                "idptcV21Excluded": sorted(
                    n for n, r in rows.items() if D.v21_layer_drop(r, "idpTradeCalc")
                ),
                "hardFindings": [f for f in integ.get("findings") or [] if f.get("hard")],
            }
        out[variant] = chk
    return out


H3_H4 = set(L4_BOARDS["H4"])


def cmd_chain(args: argparse.Namespace) -> int:
    th = candidate_thresholds()
    rpc = rpc_model()
    out_dir = OUT_ROOT / "chain"
    lanes: dict[str, Any] = {"v21": None, "v2": None, "rpc": None}
    t0 = time.time()
    for entry, cut, raw, root in iterate():
        name = Path(entry["board"]).stem
        write_gz(
            out_dir / "_history_before" / f"{name}.json.gz",
            {"beforeBoard": entry["board"], **{k: D.history_json(v) for k, v in lanes.items()}},
        )
        builds = {
            "v21": D.build(raw, root, "v21", history=lanes["v21"], thresholds=th),
            "v21nh": D.build(raw, root, "v21", history=None, thresholds=th),
            "v2": D.build(raw, root, "v2", history=lanes["v2"]),
            "rpc": D.build(raw, root, "rpc", history=lanes["rpc"], thresholds=th, rpc_model=rpc),
            "inc": D.build(raw, root, "inc"),
        }
        rec: dict[str, Any] = {
            "schema": D.SCHEMA,
            "stage": "chain_candidate",
            "board": R2.board_meta(entry, cut),
            "pins": code_pins(),
            "counts": {k: D.board_counts(v) for k, v in builds.items()},
            "labelled": labelled_checks(entry, builds["v21"], builds["v21nh"]),
            "invalidCategoryLabels": {
                k: D.invalid_category_labels(builds[k]) for k in ("v21", "v21nh")
            },
            "v21": extract21(builds["v21"]),
            "inc": RP.extract(builds["inc"], full=True),
        }
        if entry["population"] == "E_DEV":
            for k in ("B", "Bp", "Bpp"):
                builds[k] = D.build(raw, root, k)
            for k in ("C", "Cp", "Cpp"):
                builds[k] = D.build(raw, root, k, history=lanes["v21"], thresholds=th)
                builds[k + "nh"] = D.build(raw, root, k, history=None, thresholds=th)
            rec["restore"] = restore_pairs(builds)
        write_gz(out_dir / f"{name}.json.gz", rec)
        for k in lanes:
            lanes[k] = D.advance(lanes[k], builds[k], entry.get("degraded") or [])
        r = rec.get("restore") or {}
        log(
            f"chain {entry['board']} v21 excl {rec['counts']['v21']['v21Excluded']}/"
            f"{rec['counts']['v21']['observations']} nh {rec['counts']['v21nh']['v21Excluded']} "
            + " ".join(f"{t}:{v['newlyDroppedByIncumbent']}->{v['retained']}" for t, v in r.items())
            + f" t={time.time() - t0:.0f}s"
        )
    write_gz(out_dir / "_history_final.json.gz", {k: D.history_json(v) for k, v in lanes.items()})
    return 0


# ── the dev gates (prereg §7.2 / §7.3 on DEV boards; V21-D1) ────────────

G1_DEV = "dynasty_export_20260909_211525.zip"
G2_DEV = "dynasty_export_20260930_130404.zip"
ROOKIE_REFERENCES = R2.ROOKIE_REFERENCES


def _board_tree(board: str):
    for entry, cut, raw, root in iterate():
        if entry["board"] == board:
            yield entry, cut, raw, root
            return
    raise SystemExit(f"[oiv21-dev] {board} not found")


def lanes_before(board: str) -> dict[str, Any]:
    blob = read_gz(OUT_ROOT / "chain" / "_history_before" / f"{Path(board).stem}.json.gz")
    if blob.get("beforeBoard") != board:
        raise SystemExit("history snapshot is not the state before this board")
    return {k: D.history_from(blob.get(k)) for k in ("v21", "v2", "rpc")}


def specs_for(variant: str, board: str, th, rpc) -> list:
    lanes = lanes_before(board) if variant == "ARRIVING" else {"v21": None, "v2": None, "rpc": None}
    return [
        D.Spec("none", "none"),
        D.Spec("inc", "inc"),
        D.Spec("v1", "v1"),
        D.Spec("v2", "v2", lanes["v2"]),
        D.Spec("v21", "v21", lanes["v21"], th),
        D.Spec("rpc", "rpc", lanes["rpc"], th, rpc),
    ]


def sur_cases(clean_rows: dict, rank_of: dict, seed: int) -> list[dict]:
    import random  # noqa: PLC0415

    rng = random.Random(seed)
    pool = sorted(
        n
        for n, r in clean_rows.items()
        if r.get("assetClass") != "pick"
        and D.exclusion_of(r, "idpTradeCalc") is None
        and "idpTradeCalc" in G.voting_votes(r)
        and len({G.family_of(k) for k in G.voting_votes(r)}) >= 3
    )
    out = []
    for n in pool:
        rk = rank_of.get(n)
        others = [
            o
            for o in pool
            if o != n and rk is not None and o in rank_of and abs(rank_of[o] - rk) >= 100
        ]
        if not others:
            continue
        out.append({"row": n, "source": "idpTradeCalc", "other": rng.choice(others)})
    return out


def run_sur(raw, root, specs, clean, cases, *, variant_fields: str, control: bool) -> list[dict]:
    """AD2-SUR (V21-D9): an autocomplete (surname-rung) U2 capture.  The
    payload AND the CSV copy of IDPTC for the target carry the swapped
    player's value (``control``: the target's own true value), and a bound
    synthetic sidecar stamps it as the real scraper does: vendorName = the
    typed (target) name, acquisition ``autocomplete_fallback``, rung [] ->
    via ``scraper_surname``.  ``variant_fields``: ``faithful`` (no published
    fields, as the scraper records today) or ``position`` (the page's
    "- POS" of the captured asset)."""
    from src.identity import capture_evidence as cev  # noqa: PLC0415

    base = D.rows_by_name(clean["none"])
    clean_rows = {s.label: D.rows_by_name(clean[s.label]) for s in specs}
    out = []
    batch_size = 40
    for i in range(0, len(cases), batch_size):
        batch = cases[i : i + batch_size]
        raw2 = json.loads(json.dumps(raw))
        stamps = {}
        metas = []
        for c in batch:
            tkey = D.payload_key_of(base, c["row"])
            okey = D.payload_key_of(base, c["other"])
            val = D.payload_value(raw2, tkey if control else okey, "idpTradeCalc")
            if val is None:
                metas.append({"constructed": False})
                continue
            D.set_payload_value(raw2, tkey, "idpTradeCalc", val)
            st = {
                "vendorName": tkey,
                "value": val,
                "rung": [],
                "via": cev.VIA_SCRAPER_SURNAME,
                "acquisition": cev.ACQ_AUTOCOMPLETE,
                "queriedName": tkey,
            }
            if variant_fields == "position":
                st["position"] = str(
                    (base.get(c["other"] if not control else c["row"]) or {}).get("position") or ""
                )
            stamps[tkey] = st
            metas.append({"constructed": True, "value": val})
        with D.tree_copy(root) as r2:
            # the CSV copy agrees with the payload (both copies corrupted)
            path = D.csv_path_for("idpTradeCalc", r2)
            if path and path.is_file():
                header, rows, idx = D.csv_index(path)
                for c, m in zip(batch, metas):
                    if not m.get("constructed"):
                        continue
                    hit = idx.get(D.name_key(c["row"])) or []
                    if len(hit) == 1:
                        rows[hit[0]]["value"] = str(int(round(m["value"])))
                D.write_csv(path, header, rows)
            D.write_sur_sidecar(r2, raw2, stamps)
            got = {s.label: D.rows_by_name(s.build(raw2, r2)) for s in specs}
        for c, m in zip(batch, metas):
            item = {
                **c,
                **m,
                "identityFields": ["position"] if variant_fields == "position" else [],
                "harm": {},
                "excluded": {},
                "identity": {},
            }
            for s in specs:
                row = got[s.label].get(c["row"])
                mv = D.log_move(D.value_of(clean_rows[s.label].get(c["row"])), D.value_of(row))
                item["harm"][s.label] = None if mv is None else round(mv, 6)
                item["excluded"][s.label] = (
                    None if s.cfg == "none" else D.exclusion_of(row, "idpTradeCalc")
                )
            out.append(item)
    return out


def homonym_cases(clean_none: dict, dir_path: Path | None) -> list[dict]:
    if dir_path is None:
        return []
    from src.utils.name_clean import canonical_position_group  # noqa: PLC0415

    hom = D.directory_homonyms(dir_path)
    rows = D.rows_by_name(clean_none)
    out = []
    for n, r in sorted(rows.items()):
        if r.get("assetClass") == "pick":
            continue
        grp = canonical_position_group(str(r.get("position") or ""))
        players = hom.get((D.name_key(n), grp))
        if not players:
            continue
        sid = str((r.get("sleeperId") or r.get("playerId") or ""))
        others = [p for p in players if p["sleeperId"] != sid]
        votes = G.voting_votes(r)
        for src in sorted(votes):
            out.append(
                {
                    "row": n,
                    "source": src,
                    "mode": "strip",
                    "homonymOf": [p["sleeperId"] for p in players],
                }
            )
            if others:
                o = others[0]
                out.append(
                    {
                        "row": n,
                        "source": src,
                        "mode": "homonym",
                        "homonymFields": {"position": o["position"], "team": o["team"]},
                        "homonymOf": [o["sleeperId"]],
                    }
                )
    return out


def cmd_gates(args: argparse.Namespace) -> int:
    board = args.board
    assert_dev_only([board])
    th = candidate_thresholds()
    rpc = rpc_model()
    variant = args.variant
    out_path = OUT_ROOT / "gates" / f"{Path(board).stem}_{variant}.json.gz"
    t0 = time.time()
    for entry, cut, raw, root in _board_tree(board):
        specs = specs_for(variant, board, th, rpc)
        by = {s.label: s for s in specs}
        clean = {s.label: s.build(raw, root) for s in specs}
        res: dict[str, Any] = {
            "schema": D.SCHEMA,
            "stage": "dev_gates",
            "status": "EXPLORATORY_DEV_NOT_GATE_OF_RECORD",
            "variant": variant,
            "board": R2.board_meta(entry, cut),
            "pins": code_pins(),
            "thresholds": th.to_stamp(),
            "seed": D.GATE_SEED,
        }
        parts = set(args.parts.split(","))
        cases = D.plan_cases(
            {"none": clean["none"], "inc": clean["inc"], "cand": clean["v21"]}, seed=D.GATE_SEED
        )
        if "value" in parts:
            results, census = D.run_value_cases(raw, root, specs, clean, cases, progress=log)
            res["valueGates"] = D.summarize(results, [s.label for s in specs])
            res["contamination"] = census
            res["valueCaseRecords"] = results
            log(f"value gates done t={time.time() - t0:.0f}s")
        if "ad3" in parts:
            res["AD3"] = D.run_ad3(raw, root, [by["v21"], by["v2"]], clean["none"], progress=log)
            log(f"AD3 done t={time.time() - t0:.0f}s")
        idspecs = [by[k] for k in ("none", "inc", "v2", "v21", "rpc")]
        if "ad2id" in parts:
            ad2 = [
                {"row": c.row, "source": c.source, "other": c.swapped_from, "mode": "swap_id"}
                for c in cases
                if c.gate == "AD2"
            ]
            items = D.run_input_cases(raw, root, idspecs, clean, ad2, progress=log)
            res["AD2_ID"] = D.summarize_input(items, [s.label for s in idspecs], rule="material")
            res["AD2_ID"]["records"] = items
            log(f"AD2-ID done t={time.time() - t0:.0f}s")
        if "ad2sur" in parts:
            rank_of = {
                n: r.get("canonicalConsensusRank")
                for n, r in D.rows_by_name(clean["inc"]).items()
                if isinstance(r.get("canonicalConsensusRank"), int)
            }
            sc = sur_cases(D.rows_by_name(clean["none"]), rank_of, D.GATE_SEED)
            sur = {}
            for vf in ("faithful", "position"):
                items = run_sur(raw, root, idspecs, clean, sc, variant_fields=vf, control=False)
                sur[vf] = D.summarize_input(items, [s.label for s in idspecs], rule="material")
            ctrl = run_sur(raw, root, idspecs, clean, sc, variant_fields="faithful", control=True)
            sur["control_true_value_faithful"] = {
                lab: {
                    "refused": sum(1 for i in ctrl if D.identity_refused(i, lab)),
                    "of": len(ctrl),
                }
                for lab in ("v21", "rpc")
            }
            res["AD2_SUR"] = sur
            log(f"AD2-SUR done t={time.time() - t0:.0f}s")
        if "ad2n" in parts:
            hc = homonym_cases(clean["none"], D._DIRECTORY[0])
            items = D.run_input_cases(raw, root, idspecs, clean, hc, progress=log) if hc else []
            res["AD2_N"] = D.summarize_input(items, [s.label for s in idspecs], rule="refused")
            res["AD2_N"]["records"] = items[:200]
            log(f"AD2-N done ({len(hc)} cases) t={time.time() - t0:.0f}s")
        if "dup" in parts:
            res["INJ_DUP"] = D.run_inj_dup(
                raw, root, by["v21"], clean["v21"], seed=D.GATE_SEED, progress=log
            )
            log(f"INJ-DUP done t={time.time() - t0:.0f}s")
        if "structural" in parts:
            ch1 = by["v21"].build(
                raw, root, source_overrides={k: {"include": False} for k in ROOKIE_REFERENCES}
            )

            def _rook(c):
                cnt = {"withheld": 0, "voting": 0, "other": 0}
                for r in D.rows_by_name(c).values():
                    for s in ("dlfRookieSf", "flockFantasySfRookies", "dlfRookieIdp"):
                        ex = D.exclusion_of(r, s)
                        if ex == "observation_absent":
                            continue
                        key = (
                            "withheld"
                            if ex
                            in (
                                "normalization_untranslated",
                                "normalization_dependency_unavailable",
                            )
                            else ("voting" if ex is None else "other")
                        )
                        cnt[key] += 1
                return cnt

            res["INJ_H1"] = {"injected": _rook(ch1), "unmodified": _rook(clean["v21"])}
            seg_raw, seg_meta = D.shift_payload_source(
                raw, "idpTradeCalc", {}, share=0.7, seed=D.GATE_SEED, sign_random=True
            )
            cseg = by["v21"].build(seg_raw, root)
            res["INJ_SEG"] = {
                **seg_meta,
                "provenance": ((cseg.get("sourceIntegrity") or {}).get("provenance") or {}).get(
                    "idpTradeCalc"
                ),
            }
            h2 = {
                "QB": -0.15,
                "RB": 0.17,
                "WR": 0.19,
                "TE": 0.21,
                "DL": 0.18,
                "LB": 0.18,
                "DB": 0.18,
            }
            h2_raw, h2_meta = D.shift_payload_source(
                raw, "idpTradeCalc", h2, share=0.95, seed=D.GATE_SEED
            )
            ch2 = by["v21"].build(h2_raw, root)
            twin = clean["v21"]
            res["H2_SYN"] = {
                **h2_meta,
                "proof": ((ch2.get("sourceIntegrity") or {}).get("provenance") or {}).get(
                    "idpTradeCalc"
                ),
                "healthyTwinProof": (
                    (twin.get("sourceIntegrity") or {}).get("provenance") or {}
                ).get("idpTradeCalc"),
            }
            log(f"structural done t={time.time() - t0:.0f}s")
        res["wallSeconds"] = round(time.time() - t0, 1)
        write_gz(out_path, res)
    return 0


# ── PERSISTENT (prereg §7.1, P-5; V21-D7) ───────────────────────────────


def dataset_windows(board: str, sources: set[str], k: int = 3) -> dict[str, dict]:
    """For each source: the boards (DEV order, before ``board``) holding its
    ``k`` prior content-distinct datasets, from the chain records' content
    hashes.  ``start`` = the first board of the k-th prior dataset."""
    recs = _load("chain")
    names = [r["board"]["archive"] for r in recs]
    gi = names.index(board)
    out = {}
    for src in sorted(sources):
        hg = (recs[gi]["v21"].get("hashes") or {}).get(src)
        seen: list[str] = []
        start = None
        for j in range(gi - 1, -1, -1):
            h = (recs[j]["v21"].get("hashes") or {}).get(src)
            if h is None:
                continue
            if h != hg and h not in seen:
                if len(seen) == k:
                    break
                seen.append(h)
            start = j
        out[src] = {
            "datasets": len(seen),
            "start": start,
            "startBoard": names[start] if start is not None else None,
        }
    return out


def cmd_persistent(args: argparse.Namespace) -> int:
    board = args.board
    assert_dev_only([board])
    th = candidate_thresholds()
    rec_g = read_gz(OUT_ROOT / "gates" / f"{Path(board).stem}_ARRIVING.json.gz")
    arriving = {(c["gate"], c["row"], c["source"]): c for c in rec_g["valueCaseRecords"]}
    cases = [
        G.Case(
            c["gate"],
            c["row"],
            c["source"],
            c["clean"],
            c["bad"],
            (c["source"], "", ""),
            c["band"],
            c.get("swappedFrom"),
        )
        for c in rec_g["valueCaseRecords"]
        if D.case_material(c)
    ]
    if args.max_cases:
        cases = cases[: args.max_cases]
    sources = {c.source for c in cases}
    win = dataset_windows(board, sources)
    names = [r["board"]["archive"] for r in _load("chain")]
    gi = names.index(board)
    lo = min((w["start"] for w in win.values() if w["start"] is not None), default=gi)
    # materialize the window once (raw + tree copies)
    import shutil  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    cache = Path(tempfile.mkdtemp(prefix="oiv21-persist-"))
    trees: dict[int, tuple[dict, Path, list]] = {}
    for entry, cut, raw, root in iterate():
        j = names.index(entry["board"])
        if lo <= j <= gi:
            dst = cache / str(j)
            shutil.copytree(root, dst, symlinks=True)
            trees[j] = (raw, dst, entry.get("degraded") or [])
        if j >= gi:
            break
    snap = {
        j: read_gz(OUT_ROOT / "chain" / "_history_before" / f"{Path(names[j]).stem}.json.gz")
        for j in trees
    }
    # group cases by source window start so each batch rebuilds one span
    by_start: dict[int, list] = {}
    for c in cases:
        st = win[c.source]["start"]
        by_start.setdefault(gi if st is None else st, []).append(c)
    results = []
    t0 = time.time()
    raw_g, root_g, _deg = trees[gi]
    clean_none = D.build(raw_g, root_g, "none")
    clean_none_rows = D.rows_by_name(clean_none)
    lane_g = D.history_from(snap[gi]["v21"])
    clean_v21_rows = D.rows_by_name(D.build(raw_g, root_g, "v21", history=lane_g, thresholds=th))
    nb = 0
    for start in sorted(by_start):
        for batch in G.batch_cases(by_start[start]):
            nb += 1
            tf_all = G.transform_for({(c.row, c.source): c.bad for c in batch})
            lane = D.history_from(snap[start]["v21"])
            for j in range(start, gi):
                raw_j, root_j, deg_j = trees[j]
                c_j = D.build(raw_j, root_j, "v21", history=lane, thresholds=th, transform=tf_all)
                lane = D.advance(lane, c_j, deg_j)
            got = D.rows_by_name(
                D.build(raw_g, root_g, "v21", history=lane, thresholds=th, transform=tf_all)
            )
            got_none = D.rows_by_name(D.build(raw_g, root_g, "none", transform=tf_all))
            for c in batch:
                row = got.get(c.row)
                m = ((row or {}).get("sourceRankMeta") or {}).get(c.source) or {}
                integ = m.get("integrity") if isinstance(m, dict) else None
                item = {
                    "gate": c.gate,
                    "row": c.row,
                    "source": c.source,
                    "band": c.band,
                    "windowStart": names[start],
                    "datasets": win[c.source]["datasets"],
                    "harm": {
                        "none": D.log_move(
                            D.value_of(clean_none_rows.get(c.row)), D.value_of(got_none.get(c.row))
                        ),
                        "v21": D.log_move(D.value_of(clean_v21_rows.get(c.row)), D.value_of(row)),
                    },
                    "excluded": {"v21": D.exclusion_of(row, c.source)},
                    "integrity": {
                        k: (integ or {}).get(k) for k in ("status", "primaryReason", "keptBecause")
                    }
                    if integ
                    else None,
                    "arrivingPassed": D.case_passed(arriving[(c.gate, c.row, c.source)], "v21"),
                }
                results.append(item)
            log(
                f"persistent batch {nb} start={names[start]} span={gi - start} t={time.time() - t0:.0f}s"
            )
    shutil.rmtree(cache, ignore_errors=True)
    summary: dict[str, Any] = {}
    for gate in ("AD1a", "AD1b", "AD1c", "AD1d", "AD2", "AD4"):
        mat = [r for r in results if r["gate"] == gate and (r["harm"]["none"] or 0) >= G.MATERIAL]
        ok = [r for r in mat if D.case_passed(r, "v21")]
        lost = [r for r in mat if r["arrivingPassed"] and not D.case_passed(r, "v21")]
        mech = __import__("collections").Counter(
            ((r["integrity"] or {}).get("status") or "voting")
            + ":"
            + str((r["integrity"] or {}).get("primaryReason") or "accepted_baseline")
            for r in lost
        )
        summary[gate] = {
            "material": len(mat),
            "passRate": round(len(ok) / len(mat), 4) if mat else None,
            "bar": G.GATES[gate]["bar"],
            "caughtArrivingNotPersistent": len(lost),
            "mechanism": dict(sorted(mech.items())),
        }
    write_gz(
        OUT_ROOT / "gates" / f"{Path(board).stem}_PERSISTENT.json.gz",
        {
            "schema": D.SCHEMA,
            "stage": "dev_persistent",
            "board": board,
            "pins": code_pins(),
            "windows": win,
            "summary": summary,
            "records": results,
            "wallSeconds": round(time.time() - t0, 1),
        },
    )
    log(json.dumps(summary))
    return 0


# ── cold-start safety gate on L4 (prereg §7.4) ──────────────────────────


def cmd_coldstart(args: argparse.Namespace) -> int:
    th = candidate_thresholds()
    l4 = l4_board_set()
    out: dict[str, Any] = {
        "schema": D.SCHEMA,
        "stage": "dev_coldstart",
        "pins": code_pins(),
        "boards": {},
    }
    t0 = time.time()
    for entry, cut, raw, root in iterate():
        b = entry["board"]
        if b not in l4:
            continue
        ex = l4_exclude_for(entry)
        res = {}
        for lab, dirp in (("withDirectory", D._DIRECTORY[0]), ("boardRowsOnly", None)):
            saved = D._DIRECTORY[0]
            D.set_directory(dirp)
            try:
                c = D.build(raw, root, "v21", history=None, thresholds=th)
            finally:
                D.set_directory(saved)
            got = D.l4_drops(c, exclude=ex)
            res[lab] = {
                "votes": got["votes"],
                "dropped": got["dropped"],
                "drops": got["drops"],
                "invalidCategoryLabels": D.invalid_category_labels(c),
                "sleeperDirectory": (c.get("sourceIntegrity") or {}).get("sleeperDirectory"),
            }
        out["boards"][b] = {"parts": [k for k, v in L4_BOARDS.items() if b in v], **res}
        log(
            f"coldstart {b} dir:{res['withDirectory']['dropped']} rows-only:{res['boardRowsOnly']['dropped']} t={time.time() - t0:.0f}s"
        )
    # N4 / N6 rules on every DEV board, from the chain records (NO-HISTORY).
    n4 = n6 = 0
    n_boards = 0
    for r in _load("chain"):
        n_boards += 1
        lab = r["labelled"]["nohist"]
        n4 += lab["N4"]["v21Excluded"] + lab["N4"]["zeroValueVotes"]
        n6 += len(lab["N6hard"])
    out["N4N6"] = {"boards": n_boards, "N4violations": n4, "N6hardQuarantines": n6}
    write_gz(OUT_ROOT / "coldstart.json.gz", out)
    tot = {
        lab: sum(v[lab]["dropped"] for v in out["boards"].values())
        for lab in ("withDirectory", "boardRowsOnly")
    }
    log(json.dumps({"L4dropped": tot, **out["N4N6"]}))
    return 0


# ── the §6 comparison boards on a DEV board (A-D, A'-D', B'', C'') ──────

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
    "LaJohntay Wester",
    "Dee Alford",
    "James Pierre",
    "Kyle Dugger",
    "Josh Cameron",
)
PAIRS6 = (
    ("B", "A", "B vs A: DLF IDP restored, incumbent"),
    ("C", "A", "C vs A: DLF IDP restored + V2.1"),
    ("C", "B", "C vs B"),
    ("D", "A", "D vs A: V2.1, DLF held (filter change alone) = D' vs A'"),
    ("Bp", "A", "B' vs A': D4 on, incumbent"),
    ("Cp", "A", "C' vs A': D4 on + V2.1"),
    ("Cp", "Bp", "C' vs B'"),
    ("Bpp", "A", "B'' vs A: DLF IDP + D4, incumbent"),
    ("Cpp", "A", "C'' vs A: DLF IDP + D4 + V2.1"),
    ("Cpp", "Bpp", "C'' vs B''"),
)


def _compare(x: dict, y: dict) -> dict[str, Any]:
    rx, ry = D.rows_by_name(x), D.rows_by_name(y)
    moves = {"ge1pct": 0, "ge10pct": 0, "byClass": __import__("collections").Counter()}
    big = []
    exch = __import__("collections").Counter()
    conf = __import__("collections").Counter()
    priced_switch = []
    for n in sorted(set(rx) | set(ry)):
        a, b = ry.get(n), rx.get(n)
        va, vb = D.value_of(a), D.value_of(b)
        if (va is None) != (vb is None):
            priced_switch.append({"row": n, "from": va, "to": vb})
        if va and vb:
            rel = vb / va - 1
            if abs(rel) >= 0.01:
                moves["ge1pct"] += 1
                moves["byClass"][str((b or a).get("assetClass"))] += 1
            if abs(rel) >= 0.10:
                moves["ge10pct"] += 1
                big.append(
                    {
                        "row": n,
                        "class": (b or a).get("assetClass"),
                        "pos": (b or a).get("position"),
                        "from": va,
                        "to": vb,
                        "pct": round(100 * rel, 1),
                    }
                )
        if a and b:
            if a.get("confidenceBucket") != b.get("confidenceBucket"):
                conf[f"{a.get('confidenceBucket')}->{b.get('confidenceBucket')}"] += 1
            for src in set(a.get("sourceRankMeta") or {}) | set(b.get("sourceRankMeta") or {}):
                ea, eb = D.exclusion_of(a, src), D.exclusion_of(b, src)
                if ea != eb:
                    exch[f"{ea or 'voting'} -> {eb or 'voting'}"] += 1
    moves["byClass"] = dict(moves["byClass"])
    return {
        "valueMoves": moves,
        "moversGe10pct": sorted(big, key=lambda d: -abs(d["pct"]))[:80],
        "pricedUnpricedSwitches": priced_switch[:80],
        "exclusionChanges": dict(sorted(exch.items(), key=lambda kv: -kv[1])),
        "confidenceChanges": dict(conf),
    }


def _focus(builds: dict, names=FOCUS) -> dict[str, Any]:
    out = {}
    rows = {k: D.rows_by_name(v) for k, v in builds.items()}
    for n in names:
        per = {}
        for k, rr in rows.items():
            r = rr.get(n)
            if not r:
                continue
            per[k] = {
                "value": D.value_of(r),
                "confidence": r.get("confidenceBucket"),
                "votes": {
                    s: o["v"] for s, o in D.observations(r).items() if o["ex"] is None and o["v"]
                },
                "excluded": {
                    s: o["ex"]
                    for s, o in D.observations(r).items()
                    if o["ex"] not in (None, "observation_absent")
                },
            }
        if per:
            out[n] = per
    return out


def cmd_boards(args: argparse.Namespace) -> int:
    board = args.board
    assert_dev_only([board])
    th = candidate_thresholds()
    lanes = lanes_before(board)
    for entry, cut, raw, root in _board_tree(board):
        builds = {"A": D.build(raw, root, "inc")}
        for k in ("B", "Bp", "Bpp"):
            builds[k] = D.build(raw, root, k)
        for variant, lane in (("ARRIVING", lanes["v21"]), ("NOHIST", None)):
            vb = dict(builds)
            vb["D"] = D.build(raw, root, "v21", history=lane, thresholds=th)
            for k in ("C", "Cp", "Cpp"):
                vb[k] = D.build(raw, root, k, history=lane, thresholds=th)
            res = {
                "schema": D.SCHEMA,
                "stage": "dev_boards",
                "variant": variant,
                "board": R2.board_meta(entry, cut),
                "pins": code_pins(),
                "comparisons": {
                    lab: {"pair": f"{x} vs {y}", **_compare(vb[x], vb[y])} for x, y, lab in PAIRS6
                },
                "restorePairs": restore_pairs(
                    {"inc": vb["A"], **{k: vb[k] for k in ("B", "Bp", "Bpp", "C", "Cp", "Cpp")}}
                ),
                "focus": _focus(vb),
                "counts": {k: D.board_counts(v) for k, v in vb.items()},
            }
            write_gz(OUT_ROOT / "boards" / f"{Path(board).stem}_{variant}.json.gz", res)
            log(
                f"boards {board} {variant}: "
                + " ".join(
                    f"{t}:{v['newlyDroppedByIncumbent']}->{v['retained']}"
                    for t, v in res["restorePairs"].items()
                )
            )
    return 0


# ── evaluate: aggregate every dev record into the committed results ─────


def _attribution(rec: dict) -> dict[str, Any]:
    """Prereg §10 attribution, DEV analogue: every row moving >= 10% (V2.1
    ARRIVING vs incumbent) attributed to a named vote change (a source whose
    state differs between the two builds), picks and priced/unpriced switches
    included."""
    inc, v21 = rec["inc"]["rows"], rec["v21"]["rows"]
    movers = []
    unattributed = []
    for n in sorted(set(inc) | set(v21)):
        a, b = inc.get(n) or {}, v21.get(n) or {}
        va, vb = a.get("v"), b.get("v")
        switched = (va is None) != (vb is None)
        if not switched and not (va and vb and abs(vb / va - 1) >= 0.10):
            continue
        oa, ob = a.get("obs") or {}, b.get("obs") or {}
        changes = []
        for src in sorted(set(oa) | set(ob)):
            sa = (oa.get(src) or [None, 0, "absent"])[2]
            sb = (ob.get(src) or [None, 0, "absent"])[2]
            if sa != sb:
                changes.append({"source": src, "incumbent": sa, "v21": sb})
        item = {
            "row": n,
            "class": b.get("ac") or a.get("ac"),
            "from": va,
            "to": vb,
            "changes": changes,
        }
        movers.append(item)
        if not changes:
            unattributed.append(item)
    return {
        "movers": len(movers),
        "unattributed": len(unattributed),
        "unattributedRows": unattributed[:30],
        "sample": movers[:30],
    }


def cmd_evaluate(args: argparse.Namespace) -> int:
    DEV_OUT.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "schema": "oiv21-dev-evaluation/v1",
        "status": "EXPLORATORY_DEV_NOT_GATE_OF_RECORD",
        "pins": code_pins(),
    }
    sel = json.loads(SEL_PATH.read_text("utf-8")) if SEL_PATH.exists() else None
    if sel:
        out["selection"] = {
            k: sel.get(k)
            for k in (
                "epsilon_b2",
                "b3",
                "b3Status",
                "k_c",
                "tau_C",
                "failedSelection",
                "devContinuation",
            )
        }
    chain = _load("chain")
    if chain:
        from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

        clean = [r for r in chain if S.is_clean_dev({"board": r["board"]})]
        fe = {}
        for k in ("v21", "v21nh", "v2", "rpc"):
            rates = [
                (
                    r["board"]["archive"],
                    r["counts"][k]["rate"] or 0.0,
                    r["counts"][k]["v21Excluded"],
                    r["counts"][k]["observations"],
                )
                for r in clean
            ]
            hard = [
                (r["board"]["archive"], r["counts"][k]["hardFindings"])
                for r in clean
                if r["counts"][k]["hardFindings"]
            ]
            layers = __import__("collections").Counter()
            for r in clean:
                layers.update(r["counts"][k]["byLayer"])
            fe[k] = {
                "boards": len(rates),
                "maxRate": max((x[1] for x in rates), default=None),
                "boardsAbove0.5pct": [x for x in rates if x[1] > 0.005],
                "totalExcluded": sum(x[2] for x in rates),
                "totalObservations": sum(x[3] for x in rates),
                "byLayer": dict(layers.most_common()),
                "boardLevelFalsePositives": hard,
            }
        out["cleanBoardFalseExclusions"] = fe
        lab = {}
        for variant in ("arriving", "nohist"):
            h1 = [(r["board"]["archive"], r["labelled"][variant]["H1"]) for r in chain]
            lab[variant] = {
                "H1_labelledBoards": sum(1 for _b, x in h1 if x["labelled"]),
                "H1_boardsAllWithheld": sum(
                    1
                    for _b, x in h1
                    if x["labelled"] and x["voting"] == 0 and x["other"] == 0 and x["withheld"] > 0
                ),
                "H1_firesOnUnlabelled": sum(x["withheld"] for _b, x in h1 if not x["labelled"]),
                "H3H4": {
                    r["board"]["archive"]: {k: r["labelled"][variant].get(k) for k in ("H3", "H4")}
                    for r in chain
                    if "H3" in r["labelled"][variant]
                },
                "N6hard": sum(len(r["labelled"][variant]["N6hard"]) for r in chain),
                "N4": sum(
                    r["labelled"][variant]["N4"]["v21Excluded"]
                    + r["labelled"][variant]["N4"]["zeroValueVotes"]
                    for r in chain
                ),
            }
        out["labelled"] = lab
        out["invalidCategoryLabels"] = {
            k: sum(len(r["invalidCategoryLabels"][k]) for r in chain) for k in ("v21", "v21nh")
        }
        tot = __import__("collections").Counter()
        lost = []
        for r in chain:
            for tag, v in (r.get("restore") or {}).items():
                tot[tag + ":pairs"] += v["newlyDroppedByIncumbent"]
                for k, n in v["retained"].items():
                    tot[f"{tag}:{k}_retained"] += n
                for p_ in v["pairs"]:
                    for k in ("C", "Cnh", "Cp", "Cpnh", "Cpp", "Cppnh"):
                        f = p_.get("fate_" + k, "absent_key")
                        if f not in (None, "absent_key"):
                            lost.append(
                                {
                                    "board": r["board"]["archive"],
                                    "tag": tag,
                                    "build": k,
                                    **{kk: p_[kk] for kk in ("row", "source")},
                                    "fate": f,
                                }
                            )
        out["dlfRestorePairs"] = {
            "totals": dict(tot),
            "notRetained": lost[:200],
            "notRetainedCount": len(lost),
        }
        attr = [
            (r["board"]["archive"], _attribution(r))
            for r in chain
            if r["board"]["population"] == "E_DEV"
        ]
        out["attribution"] = {
            "boards": len(attr),
            "movers": sum(a["movers"] for _b, a in attr),
            "unattributed": sum(a["unattributed"] for _b, a in attr),
            "unattributedRows": [
                dict(board=b, **x) for b, a in attr for x in a["unattributedRows"]
            ][:40],
        }
    gates = {}
    for f in sorted((OUT_ROOT / "gates").glob("*.json.gz")):
        rec = read_gz(f)
        key = f.name[:-8]
        if rec.get("stage") == "dev_persistent":
            gates[key] = {
                "summary": rec["summary"],
                "windows": rec["windows"],
                "wallSeconds": rec["wallSeconds"],
            }
            continue
        g = {
            k: rec.get(k) for k in ("variant", "thresholds", "seed", "wallSeconds", "contamination")
        }
        if rec.get("valueGates"):
            g["valueGates"] = {
                gate: {kk: vv for kk, vv in v.items() if kk not in ("label",)}
                for gate, v in rec["valueGates"].items()
            }
        if rec.get("AD3"):
            g["AD3"] = {
                seam: {
                    lab: {k: v[k] for k in ("flagged", "boards", "passes16of16")}
                    | {
                        "cases": [
                            {
                                kk: c.get(kk)
                                for kk in (
                                    "source",
                                    "kind",
                                    "flagged",
                                    "flags",
                                    "votesExcluded",
                                    "noneBoardMaxLogMove",
                                    "applied",
                                )
                            }
                            for c in v["cases"]
                        ]
                    }
                    for lab, v in per.items()
                }
                for seam, per in rec["AD3"].items()
            }
        for k in ("AD2_ID", "AD2_N"):
            if rec.get(k):
                g[k] = {kk: vv for kk, vv in rec[k].items() if kk != "records"}
        for k in ("AD2_SUR", "INJ_DUP", "INJ_H1", "INJ_SEG", "H2_SYN"):
            if rec.get(k) is not None:
                g[k] = rec[k]
        gates[key] = g
    out["gates"] = gates
    cs = OUT_ROOT / "coldstart.json.gz"
    if cs.exists():
        c = read_gz(cs)
        out["coldStart"] = {
            "L4": {
                lab: {
                    "boards": len(c["boards"]),
                    "votes": sum(v[lab]["votes"] for v in c["boards"].values()),
                    "dropped": sum(v[lab]["dropped"] for v in c["boards"].values()),
                    "invalidCategoryLabels": sum(
                        len(v[lab]["invalidCategoryLabels"]) for v in c["boards"].values()
                    ),
                    "byLayer": dict(
                        __import__("collections")
                        .Counter(d["layer"] for v in c["boards"].values() for d in v[lab]["drops"])
                        .most_common()
                    ),
                    "bySource": dict(
                        __import__("collections")
                        .Counter(d["source"] for v in c["boards"].values() for d in v[lab]["drops"])
                        .most_common()
                    ),
                    "drops": [
                        dict(board=b, **d) for b, v in c["boards"].items() for d in v[lab]["drops"]
                    ][:120],
                }
                for lab in ("withDirectory", "boardRowsOnly")
            },
            "N4N6": c["N4N6"],
        }
    bd = {}
    for f in sorted((OUT_ROOT / "boards").glob("*.json.gz")):
        rec = read_gz(f)
        bd[f.name[:-8]] = {
            "comparisons": {
                k: {kk: (vv if kk != "moversGe10pct" else vv[:25]) for kk, vv in v.items()}
                for k, v in rec["comparisons"].items()
            },
            "restorePairs": {
                t: {k: v[k] for k in ("newlyDroppedByIncumbent", "retained")}
                | {"pairs": v["pairs"]}
                for t, v in rec["restorePairs"].items()
            },
            "focus": rec["focus"],
        }
    out["boards"] = bd
    path = DEV_OUT / "evaluation.json"
    path.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    log(f"wrote {path} ({path.stat().st_size} bytes)")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--directory",
        default=None,
        help="the identity owner's Sleeper directory snapshot V2.1 builds read",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in (
        "collect",
        "collect_b3off",
        "select1",
        "select1b",
        "kc",
        "select2",
        "select3",
        "chain",
    ):
        sub.add_parser(name)
    tc = sub.add_parser("tauc")
    tc.add_argument("--l4-only", action="store_true")
    g = sub.add_parser("gates")
    g.add_argument("--board", required=True)
    g.add_argument("--variant", choices=("ARRIVING", "NOHIST"), required=True)
    g.add_argument("--parts", default="value,ad3,ad2id,ad2sur,ad2n,dup,structural")
    sub.add_parser("coldstart")
    sub.add_parser("evaluate")
    bb = sub.add_parser("boards")
    bb.add_argument("--board", required=True)
    pp = sub.add_parser("persistent")
    pp.add_argument("--board", required=True)
    pp.add_argument("--max-cases", type=int, default=None)
    args = ap.parse_args(argv)
    set_directory(args.directory)
    cmds = {
        "collect": cmd_collect,
        "select1": cmd_select1,
        "kc": cmd_kc,
        "select2": cmd_select2,
        "tauc": cmd_tauc,
        "select3": cmd_select3,
        "chain": cmd_chain,
        "gates": cmd_gates,
        "persistent": cmd_persistent,
        "coldstart": cmd_coldstart,
        "boards": cmd_boards,
        "evaluate": cmd_evaluate,
        "collect_b3off": cmd_collect_b3off,
        "select1b": cmd_select1b,
    }
    return cmds[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
