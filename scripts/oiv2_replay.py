#!/usr/bin/env python3
"""Outlier-integrity-v2 historical replay driver (prereg §5-§7, §10, §11).

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` fixes the
populations, builds, metrics and verdict; this script only executes them, on the
frozen manifests under ``docs/sources/outlier_integrity_v2/manifests/`` and with
#1847's rebuild procedure (``scripts/joint_filter_shadow.py``: the archive's
payload, ``CSVs/site_raw`` as committed with the archive overlaid with its own
copies, per-source dataset state replayed from git to the archive's add time).

Boards are processed in add-time order so the V2 history lane is rebuilt from
V2's OWN decisions on the earlier boards (never read from production).

Subcommands::

    collect-e   Stage 2 input pass over E_BASELINE + E_DEV at the PROVISIONAL
                thresholds: chained V2 + incumbent, Layer A age recorder,
                B3-selection injections on E_DEV (non-registered sources only).
    kc          Stage 2 k_c pass: three chained V2 runs over E at k_c 4 / 6 / 8.
    tauc        Stage 2 tau_C pass: cold-start x20 / x0.05 injections on E_DEV
                boards (selection seed 20261020), V2 at ln 4 / ln 5 / ln 6.
    run         The comparator replay at the COMMITTED thresholds over the named
                populations (E_DEV exploratory first; ``--populations V,I`` is the
                Stage 4 held-out run, refused before the freeze or on a dirty
                tree, and refused a second time unless ``--rerun-infra-failure``).

Records (one gz JSON per board) go to ``data/oiv2_replay/<stage>/`` (gitignored).

Exit codes: 0 done; 1 inputs missing / refused; 2 a build failed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import joint_filter_shadow as J  # noqa: E402
from src.robust_filter_shadow import oiv2_gates as G  # noqa: E402
from src.robust_filter_shadow import oiv2_replay as RP  # noqa: E402

MANIFESTS = REPO_ROOT / "docs" / "sources" / "outlier_integrity_v2" / "manifests"
OUT_ROOT = REPO_ROOT / "data" / "oiv2_replay"
RECOVERED = OUT_ROOT / "_recovered_archives"
POP_FILES = {
    "E_BASELINE": "E_BASELINE.json",
    "E_DEV": "E_DEV.json",
    "V": "V_HELDOUT.json",
    "I": "I_INDEPENDENT.json",
}
SELECTION_SEED = 20261020
#: Prereg §3.5: B3 selection injections use NON-registered sources only.
SELECTION_INJECT: tuple[tuple[str, str], ...] = (
    ("dlfSf", "offense"),
    ("draftSharks", "offense"),
    ("fantasyProsSf", "offense"),
    ("ktcCrowdSfTep", "offense"),
    ("idpTradeCalc", "offense"),
    ("draftSharksIdp", "idp"),
    ("idpTradeCalc", "idp"),
)
KC_GRID = (4.0, 6.0, 8.0)
TAUC_GRID = (("ln 4", math.log(4.0)), ("ln 5", math.log(5.0)), ("ln 6", math.log(6.0)))
ROOKIE_REFERENCES = ("ktcCrowdSfTep", "idpTradeCalc")


def log(msg: str) -> None:
    print(f"[oiv2-replay] {msg}", flush=True)


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_population(pop: str) -> list[dict]:
    data = json.loads((MANIFESTS / POP_FILES[pop]).read_text("utf-8"))
    return [dict(b, population=pop) for b in data["boards"]]


def plan(pops: list[str], adds: dict) -> tuple[list[tuple], list[str]]:
    """``[(cut, path, raw, site, entry)]`` in add-time order, hash-checked."""
    out, missing = [], []
    for pop in pops:
        for entry in load_population(pop):
            name = entry["board"]
            commit, cut = adds.get(name, (None, None))
            if commit is None or commit != entry["addCommit"]:
                missing.append(f"{name}:add-commit")
                continue
            path = J.ARCHIVE_DIR / name
            if not path.is_file():
                RECOVERED.mkdir(parents=True, exist_ok=True)
                path = RECOVERED / name
                if not path.is_file():
                    blob = J._git("show", f"{commit}:exports/archive/{name}", binary=True)
                    if not blob:
                        missing.append(f"{name}:unrecoverable")
                        continue
                    path.write_bytes(blob)
            zbytes = path.read_bytes()
            data, raw, site = J.load_archive(path)
            if _sha(zbytes) != entry["zipSha256"] or _sha(data) != entry["payloadSha256"]:
                missing.append(f"{name}:hash")
                continue
            out.append((cut, path, raw, site, entry))
    out.sort(key=lambda t: t[0])
    return out, missing


def code_pins() -> dict[str, Any]:
    from src.api import source_integrity as si  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    return {
        "codeSha": (vr._git("rev-parse", "HEAD") or "").strip() or None,
        "workingTreeDirty": vr._dirty(),
        "thresholds": si.load_thresholds().to_stamp(),
        "thresholdsFileSha256": _sha(si.THRESHOLDS_PATH.read_bytes())
        if si.THRESHOLDS_PATH.is_file()
        else None,
        "preregistration": RP.PREREG,
    }


def _write(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rec, fh, sort_keys=True, default=str)
    tmp.replace(path)


def board_meta(entry: dict, cut) -> dict:
    return {
        "archive": entry["board"],
        "population": entry["population"],
        "zipSha256": entry["zipSha256"],
        "payloadSha256": entry["payloadSha256"],
        "addCommit": entry["addCommit"],
        "addTime": cut.isoformat(),
        "scrapeTimestamp": entry.get("scrapeTimestamp"),
        "complete": bool(entry.get("complete")),
        "degraded": entry.get("degraded") or [],
        "labelledCases": entry.get("labelledCases") or [],
        "roles": entry.get("roles") or [],
    }


def iterate(pops: list[str]):
    """Yield ``(entry, cut, raw, root)`` per board with its tree materialized."""
    adds = J.archive_add_commits()
    boards, missing = plan(pops, adds)
    if missing:
        raise SystemExit(f"[oiv2-replay] manifest boards missing or mismatched: {missing}")
    replayer = J.StateReplayer()
    try:
        for cut, _path, raw, site, entry in boards:
            replayer.advance(cut)
            with tempfile.TemporaryDirectory(prefix="oiv2-replay-") as tmp:
                root = Path(tmp)
                J.materialize_tree(root, entry["addCommit"], site)
                replayer.write(root / "data" / "scrape_state")
                yield entry, cut, raw, root
    finally:
        replayer.close()


# ── collect-e ───────────────────────────────────────────────────────────


def cmd_collect_e(args: argparse.Namespace) -> int:
    from src.api import source_integrity as si  # noqa: PLC0415

    if si.load_thresholds().status != "provisional_stage1":
        log("collect-e is the pre-freeze Stage 2 input pass; thresholds are already frozen")
        return 1
    out_dir = OUT_ROOT / "collect_e"
    pins = code_pins()
    history = None
    t0 = time.time()
    for entry, cut, raw, root in iterate(["E_BASELINE", "E_DEV"]):
        drop = RP.degraded_filter(entry.get("degraded") or [])
        ages = RP.IdentityAgeRecorder()
        with ages.active():
            c_v2 = RP.build(raw, root, RP.CONFIGS["v2"], history=history)
        rec: dict[str, Any] = {
            "schema": RP.SCHEMA,
            "stage": "collect_e_provisional",
            "board": board_meta(entry, cut),
            "pins": pins,
            "historyIn": {"boards": 0 if history is None else history.boards},
            "builds": {"v2": RP.extract(c_v2, full=True)},
            "identityAges": ages.rows,
        }
        if entry["population"] == "E_DEV":
            c_inc = RP.build(raw, root, RP.CONFIGS["inc"])
            rec["builds"]["inc"] = RP.extract(c_inc, full=True)
            inj = []
            for source, ac in SELECTION_INJECT:
                for kind in G.AD3_KINDS:
                    ov = G.ad3_overrides(c_v2, source, ac, kind)
                    if not ov:
                        inj.append({"source": source, "assetClass": ac, "kind": kind, "rows": 0})
                        continue
                    ci = RP.build(
                        raw, root, RP.CONFIGS["v2"], history=history, transform=G.transform_for(ov)
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
                            "findings": [
                                f for f in integ.get("findings") or [] if f.get("source") == source
                            ],
                        }
                    )
            rec["injections"] = inj
        _write(out_dir / f"{Path(entry['board']).stem}.json.gz", rec)
        history = si.advance(history, RP.board_record_for_history(c_v2, drop))
        log(
            f"{entry['board']} {entry['population']} historyBoards={history.boards} "
            f"t={time.time() - t0:.0f}s"
        )
    _write(out_dir / "_history_final.json.gz", {"history": history.to_json()})
    return 0


# ── kc ──────────────────────────────────────────────────────────────────


def _selected_partial(path: Path) -> dict:
    return json.loads(path.read_text("utf-8"))


def _thresholds_from(sel: dict, **over: Any):
    from src.api import source_integrity as si  # noqa: PLC0415

    base = si.load_thresholds()
    import dataclasses  # noqa: PLC0415

    vals = {
        "tau_age": sel["tau_age"],
        "epsilon_b2": sel["epsilon_b2"],
        "n_min": sel["n_min"],
        "rho_min": sel["rho_min"],
        "tau_gross": math.log(float(sel["tau_gross"][3:])),
        "tau_board": sel["tau_board"],
    }
    vals.update(over)
    return dataclasses.replace(base, **vals)


def cmd_kc(args: argparse.Namespace) -> int:
    from src.api import source_integrity as si  # noqa: PLC0415

    sel = _selected_partial(args.selected)
    tables = sel["tau_c_mad"]  # {k_c: {source: {band: tau}}} computed by the selector
    chains: dict[str, Any] = {str(k): None for k in KC_GRID}
    th = {str(k): _thresholds_from(sel, k_c=k, tau_c=tables[str(int(k))]) for k in KC_GRID}
    out_dir = OUT_ROOT / "kc"
    pins = code_pins()
    t0 = time.time()
    for entry, cut, raw, root in iterate(["E_BASELINE", "E_DEV"]):
        drop = RP.degraded_filter(entry.get("degraded") or [])
        rec = {"schema": RP.SCHEMA, "stage": "kc", "board": board_meta(entry, cut), "pins": pins}
        res = {}
        for k in KC_GRID:
            key = str(k)
            c = RP.build(raw, root, RP.CONFIGS["v2"], history=chains[key], thresholds=th[key])
            holds = votes = 0
            held = []
            for r in c.get("playersArray") or []:
                if r.get("assetClass") == "pick":
                    continue
                for s, m in (r.get("sourceRankMeta") or {}).items():
                    st = RP.vote_state(m) if isinstance(m, dict) else None
                    if st is None or m.get("valueContribution") in (None, 0):
                        continue
                    if st in ("voting", "filter_dropped") or st.startswith("integrity:held"):
                        votes += 1
                    if st.startswith("integrity:held"):
                        holds += 1
                        held.append([r.get("displayName"), s])
            res[key] = {"votes": votes, "holds": holds, "held": held[:200]}
            chains[key] = si.advance(chains[key], RP.board_record_for_history(c, drop))
        rec["kc"] = res
        _write(out_dir / f"{Path(entry['board']).stem}.json.gz", rec)
        log(
            f"{entry['board']} "
            + " ".join(f"k{k}:{res[str(k)]['holds']}/{res[str(k)]['votes']}" for k in KC_GRID)
            + f" t={time.time() - t0:.0f}s"
        )
    return 0


# ── tauc ────────────────────────────────────────────────────────────────


def cmd_tauc(args: argparse.Namespace) -> int:
    sel = _selected_partial(args.selected)
    boards = set(args.boards.split(","))
    out_dir = OUT_ROOT / "tauc"
    pins = code_pins()
    th = {
        # Cold-start (NO-HISTORY) builds: B4 and persistence abstain without a
        # lane, so k_c / tau_c cannot affect them; the k_c = 8 table is used
        # until phase 2 has selected k_c.
        lab: _thresholds_from(
            sel,
            k_c=sel.get("k_c") or 8.0,
            tau_c=sel.get("tau_c") or sel["tau_c_mad"]["8"],
            tau_c_big=t,
        )
        for lab, t in TAUC_GRID
    }
    for entry, cut, raw, root in iterate(["E_BASELINE", "E_DEV"]):
        if entry["board"] not in boards:
            continue
        t0 = time.time()
        none_cfg = RP.CONFIGS["inc"]
        clean_none = _build_none(raw, root)
        clean = {lab: RP.build(raw, root, RP.CONFIGS["v2nh"], thresholds=th[lab]) for lab in th}
        gate_clean = {
            "none": clean_none,
            "incumbent": RP.build(raw, root, none_cfg),
            "v2": clean["ln 6"],
        }
        cases = [
            c for c in G.plan_cases(gate_clean, seed=SELECTION_SEED) if c.gate in ("AD1c", "AD1d")
        ]
        results = []
        for batch in G.batch_cases(cases):
            ov = {(c.row, c.source): c.bad for c in batch}
            tf = G.transform_for(ov)
            got_none = G.rows_by_name(_build_none(raw, root, tf))
            got = {
                lab: G.rows_by_name(
                    RP.build(raw, root, RP.CONFIGS["v2nh"], thresholds=th[lab], transform=tf)
                )
                for lab in th
            }
            base_none = G.rows_by_name(clean_none)
            base = {lab: G.rows_by_name(clean[lab]) for lab in th}
            for c in batch:
                harm_none = G._log_move(
                    G._value(base_none.get(c.row)), G._value(got_none.get(c.row))
                )
                item = {
                    "gate": c.gate,
                    "row": c.row,
                    "source": c.source,
                    "band": c.band,
                    "harmNone": harm_none,
                }
                for lab in th:
                    item[lab] = {
                        "excluded": G.exclusion_of(got[lab].get(c.row), c.source),
                        "harm": G._log_move(
                            G._value(base[lab].get(c.row)), G._value(got[lab].get(c.row))
                        ),
                    }
                results.append(item)
        rec = {
            "schema": RP.SCHEMA,
            "stage": "tauc",
            "board": board_meta(entry, cut),
            "pins": pins,
            "seed": SELECTION_SEED,
            "cases": results,
        }
        _write(out_dir / f"{Path(entry['board']).stem}.json.gz", rec)
        log(f"{entry['board']} cases={len(results)} t={time.time() - t0:.0f}s")
    return 0


def _build_none(raw, root, transform=None):
    """No per-row filter (the gate harness's ``none``): incumbent stood down."""
    from src.api import value_replay as vr  # noqa: PLC0415

    import contextlib  # noqa: PLC0415

    with contextlib.ExitStack() as stack:
        stack.enter_context(vr._patched("_hampel_filter_per_player", G._no_filter))
        return RP.build(raw, root, RP.CONFIGS["inc"], transform=transform)


# ── run ─────────────────────────────────────────────────────────────────


def _inj_seg_raw(raw: dict, seed: int) -> tuple[dict, dict]:
    """INJ-SEG (prereg §7.2): IDP Trade Calculator payload values (a value-
    direct source with a same-run CSV copy) shifted per position group by a
    random-sign |0.1-0.3| log on 70% of rows; the CSV keeps the true values."""
    rng = random.Random(seed)
    out = json.loads(json.dumps(raw))
    players = out.get("players") or {}
    positions = (out.get("sleeper") or {}).get("positions") or {}
    groups: dict[str, float] = {}
    touched = 0
    for name in sorted(players):
        p = players[name]
        if not isinstance(p, dict):
            continue
        site = p.get("_canonicalSiteValues")
        val = (site or {}).get("idpTradeCalc") if isinstance(site, dict) else None
        if not isinstance(val, (int, float)):
            val = p.get("idpTradeCalc")
        if not isinstance(val, (int, float)) or val <= 0:
            continue
        pos = str(positions.get(name) or "OTHER").upper()
        if pos not in groups:
            groups[pos] = rng.choice((-1.0, 1.0)) * rng.uniform(0.1, 0.3)
        if rng.random() < 0.7:
            new = int(round(float(val) * math.exp(groups[pos])))
            if isinstance(site, dict) and "idpTradeCalc" in site:
                site["idpTradeCalc"] = new
            if "idpTradeCalc" in p:
                p["idpTradeCalc"] = new
            touched += 1
    return out, {"rowsShifted": touched, "groupShifts": {k: round(v, 4) for k, v in groups.items()}}


def cmd_run(args: argparse.Namespace) -> int:
    from src.api import source_integrity as si  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    pops = [p.strip() for p in args.populations.split(",") if p.strip()]
    scored = set(pops)
    heldout = bool(scored & {"V", "I"})
    if si.load_thresholds().status == "provisional_stage1":
        log("run needs the Stage 2 freeze (FROZEN_THRESHOLDS.json); refused")
        return 1
    out_dir = OUT_ROOT / args.tag
    if heldout:
        if vr._dirty() or (vr._git("status", "--porcelain") or "").strip():
            log("the held-out run needs a clean tree at one committed SHA; refused")
            return 1
        marker = out_dir / "_STAGE4_STARTED.json"
        if marker.exists() and not args.rerun_infra_failure:
            log(f"Stage 4 already started ({marker}); held-out boards are evaluated once")
            return 1
        out_dir.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"started": time.time(), **code_pins()}, indent=1), "utf-8")
    chain_pops = ["E_BASELINE", "E_DEV", "V", "I"]
    last = max(chain_pops.index(p) for p in pops)
    chain_pops = chain_pops[: last + 1]
    pins = code_pins()
    history = None
    t0 = time.time()
    for entry, cut, raw, root in iterate(chain_pops):
        drop = RP.degraded_filter(entry.get("degraded") or [])
        pop = entry["population"]
        if pop not in scored:
            # History-only board: V2 builds it to advance the lane; a light
            # record (outcomes + non-voting observations + the integrity
            # stamp) is kept for the labelled controls (H3/H4/N5 live here).
            c_v2 = RP.build(raw, root, RP.CONFIGS["v2"], history=history)
            _write(
                out_dir / "_chain" / f"{Path(entry['board']).stem}.json.gz",
                {
                    "schema": RP.SCHEMA,
                    "stage": args.tag + ":chain",
                    "board": board_meta(entry, cut),
                    "pins": pins,
                    "builds": {"v2": RP.extract(c_v2, full=False)},
                },
            )
            history = si.advance(history, RP.board_record_for_history(c_v2, drop))
            continue
        builds: dict[str, Any] = {}
        timing: dict[str, float] = {}
        lc = RP.LayerCRecorder()
        for name, cfg in RP.CONFIGS.items():
            t1 = time.time()
            h = history if cfg.history == "chain" else None
            if name == "v2":
                with lc.active():
                    c = RP.build(raw, root, cfg, history=h)
                c_v2 = c
                builds[name] = RP.extract(c, full=True, layer_c=lc)
            else:
                c = RP.build(raw, root, cfg, history=h)
                builds[name] = RP.extract(c, full=name == "inc")
            timing[name] = round(time.time() - t1, 3)
            if not c.get("playersArray"):
                log(f"{entry['board']}: {name} had no playersArray")
                return 2
        rec: dict[str, Any] = {
            "schema": RP.SCHEMA,
            "stage": args.tag,
            "board": board_meta(entry, cut),
            "pins": pins,
            "historyIn": None
            if history is None
            else {
                "boards": history.boards,
                "asOf": history.as_of,
                "segments": {k: list(v) for k, v in history.segments.items()},
            },
            "builds": builds,
            "buildSeconds": timing,
        }
        if pop in ("V", "I"):
            # INJ-H1: the rookie-ladder references marked inactive.
            ch1 = RP.build(
                raw,
                root,
                RP.CONFIGS["v2"],
                history=history,
                source_overrides={k: {"include": False} for k in ROOKIE_REFERENCES},
            )
            rec["injH1"] = RP.extract(ch1, full=True)
            seg_raw, seg_meta = _inj_seg_raw(raw, 2033)
            cseg = RP.build(seg_raw, root, RP.CONFIGS["v2"], history=history)
            rec["injSeg"] = {
                **seg_meta,
                "provenance": ((cseg.get("sourceIntegrity") or {}).get("provenance") or {}).get(
                    "idpTradeCalc"
                ),
            }
        _write(out_dir / f"{Path(entry['board']).stem}.json.gz", rec)
        if pop in ("V", "I"):
            # The ARRIVING gate variant reads the lane exactly as it stood
            # before this board (prereg §7.1).
            _write(
                out_dir / "_history" / f"{Path(entry['board']).stem}.json.gz",
                {
                    "beforeBoard": entry["board"],
                    "history": None if history is None else history.to_json(),
                },
            )
        history = si.advance(history, RP.board_record_for_history(c_v2, drop))
        log(f"{entry['board']} {pop} t={time.time() - t0:.0f}s")
    return 0


# ── select ──────────────────────────────────────────────────────────────


def _load_stage(stage: str) -> list[dict]:
    recs = []
    for f in sorted((OUT_ROOT / stage).glob("dynasty_export_*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            recs.append(json.load(fh))
    recs.sort(key=lambda r: r["board"]["addTime"])
    return recs


def cmd_select(args: argparse.Namespace) -> int:
    from src.robust_filter_shadow import oiv2_select as S  # noqa: PLC0415

    sel_path = OUT_ROOT / "selection.json"
    recs = _load_stage("collect_e")
    pops = {r["board"]["population"] for r in recs}
    if pops - {"E_BASELINE", "E_DEV"}:
        log(f"selection may read E only; found {sorted(pops)}")
        return 1
    if len(recs) != 79:
        log(f"collect-e incomplete: {len(recs)} / 79 boards")
        return 1
    if args.phase == 1:
        tau_age = S.select_tau_age(recs)
        eps = S.select_epsilon(recs)
        tb = S.select_tau_board(recs)
        b3 = S.select_b3(recs, tb["selected"])
        mads = S.tau_c_mad(recs)
        out = {
            "schema": "oiv2-selection/v1",
            "boardsRead": [r["board"]["archive"] for r in recs],
            "evidence": {"tau_age": tau_age, "epsilon_b2": eps, "tau_board": tb, "b3": b3},
            "tau_age": tau_age["selected"],
            "epsilon_b2": eps["selected"],
            "tau_board": tb["selected"],
            "n_min": b3["selected"]["n_min"],
            "rho_min": b3["selected"]["rho_min"],
            "tau_gross": b3["selected"]["tau_gross"],
            "b3SelectionStatus": b3["status"],
            "tau_c_madSource": mads,
            "tau_c_mad": {str(int(k)): S.tau_c_table(mads, k) for k in S.KC_GRID},
        }
    else:
        out = json.loads(sel_path.read_text("utf-8"))
        if args.phase == 2:
            kc = S.select_kc(_load_stage("kc"))
            out["evidence"]["k_c"] = kc
            out["k_c"] = kc["selected"]
            out["tau_c"] = out["tau_c_mad"][str(int(kc["selected"]))]
        elif args.phase == 3:
            tc = S.select_tau_c_big(_load_stage("tauc"), TAUC_GRID)
            out["evidence"]["tau_C"] = tc
            out["tau_C"] = tc["selected"]
    sel_path.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", "utf-8")
    log(
        json.dumps(
            {
                k: out.get(k)
                for k in (
                    "tau_age",
                    "epsilon_b2",
                    "n_min",
                    "rho_min",
                    "tau_gross",
                    "b3SelectionStatus",
                    "k_c",
                    "tau_C",
                )
            }
        )
    )
    return 0


# ── evaluate ────────────────────────────────────────────────────────────

PAIRS = (
    ("policy", "incumbent", "D vs A (V2 alone, release defaults)"),
    ("v1", "incumbent", "V1 vs A"),
    ("v2nh", "incumbent", "V2-NOHIST vs A"),
    ("v2d1", "incumbent", "V2+D1 vs A"),
    ("B", "incumbent", "B vs A (DLF IDP restored, incumbent)"),
    ("C", "incumbent", "C vs A (DLF IDP restored + V2)"),
    ("C", "B", "C vs B"),
    ("Bp", "incumbent", "B' vs A' (D4 on, incumbent)"),
    ("Cp", "incumbent", "C' vs A' (D4 on + V2)"),
    ("Cp", "Bp", "C' vs B'"),
    ("Cpp", "incumbent", "C'' vs A (DLF IDP + D4 + V2)"),
    ("Cpp", "Bpp", "C'' vs B''"),
)
N_SOURCES = {
    "N1": ("draftSharks",),
    "N2": ("dynastyDaddySf",),
    "N3": ("dlfSf", "dlfRookieSf", "dlfIdp", "dlfRookieIdp", "dlfValuesSfTep"),
    "N4": ("yahooBoone",),
    "N5": ("draftSharks", "draftSharksIdp"),
    "N6": (
        "flockFantasySfRookies",
        "fantasyProsSf",
        "ktcCrowdSfTep",
        "ktcTradesSfTep",
        "idpTradeCalc",
    ),
}


def _load_tag(tag: str, sub: str | None = None) -> list[dict]:
    d = OUT_ROOT / tag / sub if sub else OUT_ROOT / tag
    recs = []
    for f in sorted(d.glob("dynasty_export_*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rec = json.load(fh)
        rec["_file"] = f.name
        rec["_sha256"] = _sha(f.read_bytes())
        recs.append(rec)
    recs.sort(key=lambda r: r["board"]["addTime"])
    return recs


def cmd_evaluate(args: argparse.Namespace) -> int:
    from src.robust_filter_shadow import oiv2_eval as V  # noqa: PLC0415
    from src.robust_filter_shadow import outlier_policy_eval as E  # noqa: PLC0415

    pops = {p.strip() for p in args.populations.split(",") if p.strip()}
    recs = [r for r in _load_tag(args.tag) if r["board"]["population"] in pops]
    chain = _load_tag(args.tag, "_chain")
    expected = sum(len(load_population(p)) for p in pops)
    adapted = [V.adapt(r) for r in recs]
    days = E.daily(adapted)
    per_board = []
    for a in adapted:
        r = a["_rec"]
        b = r["board"]
        entry = {
            "archive": b["archive"],
            "population": b["population"],
            "labelledCases": b["labelledCases"],
            "roles": b["roles"],
            "recordSha256": r["_sha256"],
            "historyBoardsIn": (r.get("historyIn") or {}).get("boards"),
            "census": V.exclusion_census(r),
            "falseExclusions": V.false_exclusions(r),
            "boardLevelHardFindings": V.board_level_findings(r),
            "boardLevelHardFindingsNoHist": V.board_level_findings(r, "v2nh"),
            "untranslatedFires": V.untranslated_fires(r),
            "valueChanges": {lab: E.value_changes(a, x, y).get("all") for x, y, lab in PAIRS[:5]},
            "moversOver10pctDvsA": len(V.movers_attributed(a, "incumbent", "policy")),
            "layerC": ((r["builds"]["v2"].get("sourceIntegrity") or {}).get("layerC")),
            "buildSeconds": r.get("buildSeconds"),
        }
        if "injH1" in r:
            entry["INJ_H1"] = V.rookie_status(r, key="injH1")
        if "injSeg" in r:
            prov = (r["injSeg"] or {}).get("provenance") or {}
            entry["INJ_SEG"] = {
                "rowsShifted": r["injSeg"].get("rowsShifted"),
                "boardProof": bool(prov.get("boardProof")),
                "provenGroups": prov.get("provenGroups"),
            }
        per_board.append(entry)
    clean = [e for e in per_board if not set(e["labelledCases"]) & {"H2", "H3"}]
    fe_upper = [e["falseExclusions"]["rateUpperBound"] for e in clean]
    fe_nondet = [e["falseExclusions"]["rateNonDeterministicOnly"] for e in clean]
    m1 = {}
    for h in (E.PRIMARY_H, *E.SECONDARY_H, 0):
        units = V.m1_units(days, h)
        m1[str(h)] = {
            "units": len(units),
            "v2": E.paired_stat(units, "v2"),
            "none": E.paired_stat(units, "none"),
            "v2AllUnits": E.paired_stat(units, "v2", disputed_only=False),
            "byClass": {
                seg: E.paired_stat([u for u in units if u["ac"] == seg], "v2")
                for seg in ("offense", "idp")
            },
        }
    prim = m1[str(E.PRIMARY_H)]["v2"]
    m1_sufficient = (
        prim["n"] >= E.MIN_UNITS and prim["days"] >= E.MIN_DAYS and prim["blocks"] >= E.MIN_BLOCKS
    )
    stab = V.stability_ratio(days)
    m3 = {str(h): E.m3_outcomes(days, h) for h in (E.PRIMARY_H,)}
    # Labelled cases.
    by_name = {r["board"]["archive"]: r for r in recs}
    by_name_chain = {r["board"]["archive"]: r for r in chain}
    h_cases: dict[str, Any] = {}
    h1 = [r for r in recs if "H1" in r["board"]["labelledCases"]]
    if h1:
        rows = []
        for r in h1:
            st = V.rookie_status(r)
            ok = all(v["stillVoting"] == 0 for k, v in st.items() if k != "dlfRookieIdp") and any(
                v["withheld"] > 0 for k, v in st.items() if k != "dlfRookieIdp"
            )
            rows.append({"archive": r["board"]["archive"], "withheldAll": ok, "status": st})
        h_cases["H1"] = {
            "boards": len(rows),
            "withheldOnAllBoards": sum(1 for x in rows if x["withheldAll"]),
            "perBoard": rows,
        }
    h2 = []
    for name in V.H2_BOARDS:
        r = by_name.get(name)
        if r is None:
            continue
        h2.append(
            {
                "archive": name,
                "v2": V.provenance_of(r, "v2"),
                "v2BoardProof": bool((V.provenance_of(r, "v2") or {}).get("boardProof")),
                "idptcDrops": {
                    cfg: sum(
                        1
                        for e in r["builds"][cfg]["rows"].values()
                        if "idpTradeCalc" in (e.get("dr") or [])
                    )
                    for cfg in ("inc", "v1", "v2", "v2nh")
                },
            }
        )
    if h2:
        h_cases["H2"] = {
            "boards": len(h2),
            "boardProofs": sum(1 for x in h2 if x["v2BoardProof"]),
            "perBoard": h2,
        }
    h3 = []
    for name in V.H3_BOARDS:
        r = by_name.get(name) or by_name_chain.get(name)
        if r is None:
            continue
        cfgs = [c for c in ("inc", "v1", "v2", "v2nh") if c in r["builds"]]
        h3.append({"archive": name, **{c: V.h3_status(r, c) for c in cfgs}})
    if h3:
        h_cases["H3"] = h3
    h4 = []
    for name in V.H4_BOARDS:
        r = by_name.get(name) or by_name_chain.get(name)
        if r is None:
            continue
        excl = {
            n: st
            for n, e in r["builds"]["v2"]["rows"].items()
            for k, st in V._nonvoting(e).items()
            if k == "idpTradeCalc" and st.startswith("integrity:")
        }
        h4.append(
            {
                "archive": name,
                "idptcIntegrityExclusions": excl,
                "provenance": V.provenance_of(r, "v2"),
            }
        )
    if h4:
        h_cases["H4"] = h4
    # H5 / H6 / N controls over every record (scored + chain).
    advis, a4, n_hits = Counter(), Counter(), defaultdict(list)
    for r in [*recs, *chain]:
        integ = r["builds"]["v2"].get("sourceIntegrity") or {}
        for f in integ.get("findings") or []:
            if f.get("source") == "fantasyProsIdp" and not f.get("hard"):
                advis[f.get("reason")] += 1
            for nid, srcs in N_SOURCES.items():
                if f.get("hard") and f.get("source") in srcs:
                    n_hits[nid].append(
                        {
                            "archive": r["board"]["archive"],
                            **{k: f.get(k) for k in ("source", "reason", "scope")},
                        }
                    )
        for e in r["builds"]["v2"]["rows"].values():
            st = V._nonvoting(e).get("fantasyProsIdp")
            if st and "ambiguous" in st:
                a4[r["board"]["archive"]] += 1
    h_cases["H5"] = {
        "fantasyProsIdpAdvisories": dict(advis),
        "note": "soft label: reported, never in hard metrics",
    }
    h_cases["H6"] = {"fantasyProsIdpA4Refusals": dict(a4), "boardsWithRefusals": len(a4)}
    n_controls = {
        nid: {"hardFindings": len(v), "sample": v[:20]} for nid, v in sorted(n_hits.items())
    }
    for nid in N_SOURCES:
        n_controls.setdefault(nid, {"hardFindings": 0, "sample": []})
    newest = recs[-1] if recs else None
    newest_block = None
    if newest is not None:
        a = V.adapt(newest)
        newest_block = {
            "archive": newest["board"]["archive"],
            "census": V.exclusion_census(newest),
            "valueChanges": {lab: E.value_changes(a, x, y) for x, y, lab in PAIRS},
            "moversOver10pct": {lab: V.movers_attributed(a, y, x)[:80] for x, y, lab in PAIRS},
            "focusRows": V.focus_rows(newest, [c for c in newest["builds"] if c != "inc"]),
        }
    out = {
        "schema": "oiv2-replay-evaluation/v1",
        "preregistration": RP.PREREG,
        "label": "archived inputs rebuilt through one replay code revision; NOT what production served",
        "tag": args.tag,
        "populations": sorted(pops),
        "identity": {
            "records": len(recs),
            "expected": expected,
            "codeSha": dict(Counter(r["pins"]["codeSha"] for r in recs)),
            "workingTreeDirty": dict(Counter(str(r["pins"]["workingTreeDirty"]) for r in recs)),
            "thresholdsFileSha256": dict(
                Counter(r["pins"].get("thresholdsFileSha256") for r in recs)
            ),
            "chainRecords": len(chain),
        },
        "M1": m1,
        "M1MinimumSampleMet": m1_sufficient,
        "M3": m3,
        "M4": stab,
        "labelledCases": h_cases,
        "nControls": n_controls,
        "cleanBoardFalseExclusions": {
            "boards": len(clean),
            "maxRateUpperBound": max(fe_upper) if fe_upper else None,
            "maxRateNonDeterministic": max(fe_nondet) if fe_nondet else None,
            "boardsOver0.5pctUpperBound": sum(1 for x in fe_upper if x is not None and x > 0.005),
            "boardsOver0.5pctNonDeterministic": sum(
                1 for x in fe_nondet if x is not None and x > 0.005
            ),
        },
        "boardLevelFindings": [
            {
                "archive": e["archive"],
                "labelledCases": e["labelledCases"],
                "findings": e["boardLevelHardFindings"],
            }
            for e in per_board
            if e["boardLevelHardFindings"]
        ],
        "perBoard": per_board,
        "newestBoard": newest_block,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    log(
        json.dumps(
            {
                "records": len(recs),
                "expected": expected,
                "M1": m1[str(E.PRIMARY_H)]["v2"],
                "M4": (stab.get("all") or {}).get("ratioPolicyOverIncumbent"),
            }
        )
    )
    return 0


# ── freeze ──────────────────────────────────────────────────────────────


def cmd_freeze(args: argparse.Namespace) -> int:
    """Stage 2: commit the E-selected thresholds (prereg §3.5, §5.3)."""
    from src.api import source_integrity as si  # noqa: PLC0415

    sel = json.loads((OUT_ROOT / "selection.json").read_text("utf-8"))
    for k in ("tau_age", "epsilon_b2", "n_min", "rho_min", "tau_gross", "k_c", "tau_c", "tau_C"):
        if sel.get(k) is None:
            log(f"selection incomplete: {k}")
            return 1
    cfg_path = si.THRESHOLDS_PATH
    cfg = json.loads(cfg_path.read_text("utf-8"))
    status = "frozen_stage2"
    failed = [
        name
        for name, ok in (
            ("b3 (n_min, rho_min, tau_gross)", sel["b3SelectionStatus"] == "SELECTED"),
            ("tau_C", sel["evidence"]["tau_C"]["feasible"]),
            ("k_c", sel["evidence"]["k_c"]["feasible"]),
            ("epsilon_b2", sel["evidence"]["epsilon_b2"]["feasible"]),
        )
        if not ok
    ]
    selected = {
        "tau_age": sel["tau_age"],
        "epsilon_b2": sel["epsilon_b2"],
        "n_min": sel["n_min"],
        "rho_min": sel["rho_min"],
        "tau_gross": sel["tau_gross"],
        "k_c": sel["k_c"],
        "tau_C": sel["tau_C"],
        "tau_board": sel["tau_board"],
        "tau_c": sel["tau_c"],
    }
    cfg["status"] = status
    cfg["note"] = (
        "Outlier-integrity-v2 thresholds FROZEN at Stage 2 "
        "(docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md section 3.5): every value "
        "selected on E_BASELINE / E_DEV only by the registered rules as executed under "
        "DEVIATIONS.md S3-S9 and S15; evidence in "
        "docs/sources/outlier_integrity_v2/FROZEN_THRESHOLDS.json. No value here was "
        "chosen by looking at V, I or R boards. Read only while outlier_integrity_v2 is on; "
        "no production default changes."
    )
    cfg["selected"] = selected
    cfg_path.write_text(json.dumps(cfg, indent=2) + "\n", "utf-8")
    ev = sel["evidence"]
    frozen = {
        "schema": "oiv2-frozen-thresholds/v1",
        "status": status,
        "selectionFailures": failed,
        "verdictConsequence": (
            "FAILED_SELECTION recorded for the B3b triple: the run cannot reach READY FOR "
            "APPROVAL (prereg section 3.5); the most conservative registered setting is used"
            if sel["b3SelectionStatus"] != "SELECTED"
            else None
        ),
        "selected": selected,
        "populationRead": "E_BASELINE + E_DEV only",
        "boardsRead": sel["boardsRead"],
        "selectionSeed": SELECTION_SEED,
        "evidence": {
            "tau_age": ev["tau_age"],
            "epsilon_b2": {k: v for k, v in ev["epsilon_b2"].items() if k != "boardProofsByGrid"},
            "tau_board": ev["tau_board"],
            "b3": {
                "status": ev["b3"]["status"],
                "selected": ev["b3"]["selected"],
                "settings": [
                    {k: v for k, v in st.items() if k != "cleanHardFlagSample"}
                    for st in ev["b3"]["settings"]
                ],
            },
            "tau_c_mad": {
                src: {"pooledMad": v["pooledMad"], "pooledN": v["pooledN"], "bands": v["bands"]}
                for src, v in sel["tau_c_madSource"].items()
            },
            "k_c": ev["k_c"],
            "tau_C": ev["tau_C"],
        },
        "thresholdsFile": "config/sources/outlier_integrity_v2.json",
        "thresholdsFileSha256": _sha(cfg_path.read_bytes()),
    }
    out = REPO_ROOT / "docs" / "sources" / "outlier_integrity_v2" / "FROZEN_THRESHOLDS.json"
    out.write_text(json.dumps(frozen, indent=1, sort_keys=True) + "\n", "utf-8")
    log(
        json.dumps(
            {
                "status": status,
                "failures": failed,
                "selected": {k: v for k, v in selected.items() if k not in ("tau_board", "tau_c")},
            }
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect-e")
    k = sub.add_parser("kc")
    k.add_argument("--selected", type=Path, required=True)
    t = sub.add_parser("tauc")
    t.add_argument("--selected", type=Path, required=True)
    t.add_argument("--boards", required=True)
    se = sub.add_parser("select")
    se.add_argument("--phase", type=int, choices=(1, 2, 3), required=True)
    ev = sub.add_parser("evaluate")
    ev.add_argument("--tag", required=True)
    ev.add_argument("--populations", required=True)
    ev.add_argument("--out", type=Path, required=True)
    sub.add_parser("freeze")
    r = sub.add_parser("run")
    r.add_argument("--populations", required=True)
    r.add_argument("--tag", required=True)
    r.add_argument("--rerun-infra-failure", action="store_true")
    args = ap.parse_args(argv)
    return {
        "collect-e": cmd_collect_e,
        "kc": cmd_kc,
        "tauc": cmd_tauc,
        "run": cmd_run,
        "select": cmd_select,
        "evaluate": cmd_evaluate,
        "freeze": cmd_freeze,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
