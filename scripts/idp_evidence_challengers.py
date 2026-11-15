#!/usr/bin/env python3
"""Historical replay of the two IDP evidence challengers (owner closeout 2026-10-18).

* ``idp-hampel-n3-v1`` (Decision 1) --
  ``docs/valuation/evidence/idp-outlier-n3-2026-10-18/PREREGISTRATION.md``
* ``idp-deep-tail-native-v1`` (Decision 6) --
  ``docs/valuation/evidence/idp-deep-tail-native-2026-10-18/PREREGISTRATION.md``

Both are evaluation only: every flag is set inside one in-process build and
restored, nothing is promoted, and the served board is untouched.

``backfill`` replays every board of the frozen manifest (hash-checked) through the
inherited rebuild procedure (``scripts/joint_filter_shadow.py``: archive payload,
``CSVs/site_raw`` committed with the archive + the archive's own copies, dataset
state replayed from git history) and builds it four ways (incumbent; n = 3
challenger; DLF IDP hold off, read for DLF's own vote; deep-tail challenger). It
writes one gitignored record per board and experiment:
``data/robust_filter_shadow_idp_n3/`` and ``data/idp_evidence_challengers/``.

``evaluate-n3`` / ``evaluate-deep-tail`` apply each preregistration's metrics and
verdict table and write the evidence JSON.

Usage (full git history needed)::

    python scripts/idp_evidence_challengers.py backfill [--shard 0/2]
    python scripts/idp_evidence_challengers.py evaluate-n3 --out <json>
    python scripts/idp_evidence_challengers.py evaluate-deep-tail --out <json>

Exit codes: 0 done; 1 inputs missing (shallow clone, manifest mismatch); 2 a
build failed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import joint_filter_shadow as J  # noqa: E402
from src.robust_filter_shadow import idp_challengers as C  # noqa: E402

N3_DIR = REPO_ROOT / "data" / "robust_filter_shadow_idp_n3"
DTN_DIR = REPO_ROOT / "data" / "idp_evidence_challengers"
MANIFEST = (
    REPO_ROOT
    / "docs"
    / "valuation"
    / "evidence"
    / "idp-outlier-n3-2026-10-18"
    / "ARCHIVE_MANIFEST.json"
)
N3_PREREG = "docs/valuation/evidence/idp-outlier-n3-2026-10-18/PREREGISTRATION.md"
DTN_PREREG = "docs/valuation/evidence/idp-deep-tail-native-2026-10-18/PREREGISTRATION.md"
POLICY = REPO_ROOT / "config" / "model_registry" / "hill_autopilot_policy.json"


def log(msg: str) -> None:
    print(f"[idp-evidence] {msg}", flush=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _code_pins() -> dict[str, Any]:
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415
    from src.canonical import player_valuation as pv  # noqa: PLC0415
    from src.canonical import tail_policy  # noqa: PLC0415

    return {
        "codeSha": (vr._git("rev-parse", "HEAD") or "").strip() or None,
        "workingTreeDirty": vr._dirty(),
        "hampel": {
            "K": dc._HAMPEL_K,
            "minN": dc._HAMPEL_MIN_N,
            "idpN3MinN": dc._IDP_HAMPEL_N3_MIN_N,
            "floor": dc._HAMPEL_MIN_THRESHOLD,
        },
        "hill": {
            "offense": [pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S],
            "idp": [pv.IDP_HILL_PERCENTILE_C, pv.IDP_HILL_PERCENTILE_S],
            "global": [pv.HILL_GLOBAL_PERCENTILE_C, pv.HILL_GLOBAL_PERCENTILE_S],
            "referenceN": pv.PERCENTILE_REFERENCE_N,
            "tailSaturationRank": tail_policy.TAIL_SATURATION_RANK,
        },
        "builds": {k: dict(v) for k, v in C.BUILDS.items()},
    }


def _manifest() -> dict[str, dict]:
    data = json.loads(MANIFEST.read_text("utf-8"))
    return {b["board"]: b for b in data["boards"]}


def _build_board(raw: dict, root: Path) -> dict[str, Any]:
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    out: dict[str, Any] = {}
    captured: list = []
    real = dc._idp_trade_calc_native_points

    def spy(*args, **kwargs):
        pts = real(*args, **kwargs)
        captured.append(list(pts))
        return pts

    for name, flags in C.BUILDS.items():
        if name == "deepTail":
            dc._idp_trade_calc_native_points = spy
        try:
            out[name] = vr.build(raw, {"csv_root": root, "flags": flags})
        finally:
            dc._idp_trade_calc_native_points = real
    out["ladderPoints"] = captured[-1] if captured else []
    return out


def cmd_backfill(args: argparse.Namespace) -> int:
    try:
        if J._git("rev-parse", "--is-shallow-repository").strip() == "true":
            log("shallow clone: run `git fetch --unshallow` first")
            return 1
        adds = J.archive_add_commits()
    except Exception as exc:  # noqa: BLE001
        log(f"git history unavailable: {exc}")
        return 1
    manifest = _manifest()
    plan = []
    missing = []
    for name, entry in sorted(manifest.items()):
        path = J.ARCHIVE_DIR / name
        if not path.is_file():
            # Pruned from the working tree by archive retention after the
            # manifest froze it: recover the exact bytes from the commit that
            # added it (hash-checked below), never a substitute board.
            commit, _cut = adds.get(name, (None, None))
            blob = (
                J._git("show", f"{commit}:exports/archive/{name}", binary=True) if commit else None
            )
            if not blob:
                missing.append(name)
                continue
            cache = DTN_DIR / "_recovered_archives"
            cache.mkdir(parents=True, exist_ok=True)
            path = cache / name
            path.write_bytes(blob)
        zbytes = path.read_bytes()
        data, raw, site = J.load_archive(path)
        if _sha(zbytes) != entry["zipSha256"] or _sha(data) != entry["payloadSha256"]:
            missing.append(name)
            continue
        commit, cut = adds.get(name, (None, None))
        if commit is None:
            missing.append(name)
            continue
        plan.append((cut, path, data, raw, site, entry, commit))
    if missing:
        log(f"manifest boards missing or hash-mismatched: {missing}")
        return 1
    plan.sort(key=lambda item: item[0])
    shard, shards = (int(x) for x in args.shard.split("/"))
    N3_DIR.mkdir(parents=True, exist_ok=True)
    DTN_DIR.mkdir(parents=True, exist_ok=True)
    code = _code_pins()
    replayer = J.StateReplayer()
    done = 0
    try:
        for i, (cut, path, data, raw, site, entry, commit) in enumerate(plan):
            replayer.advance(cut)
            if i % shards != shard:
                continue
            stem = path.stem
            if (N3_DIR / f"{stem}.json").exists() and (DTN_DIR / f"{stem}.json").exists():
                continue
            with tempfile.TemporaryDirectory(prefix="idpe-") as tmp:
                root = Path(tmp)
                J.materialize_tree(root, commit, site)
                replayer.write(root / "data" / "scrape_state")
                pins = {
                    **code,
                    "csvCommit": commit,
                    "csvTreeSha256": J.R.tree_sha256(root, ["CSVs/site_raw"], "*.csv"),
                    "stateTreeSha256": J.R.tree_sha256(
                        root, ["data/scrape_state"], "*_dataset.json"
                    ),
                    "stateReplayThrough": cut.isoformat(),
                }
                builds = _build_board(raw, root)
            board = {
                "archive": path.name,
                "zipSha256": entry["zipSha256"],
                "payloadSha256": entry["payloadSha256"],
                "scrapeTimestamp": entry.get("scrapeTimestamp"),
                "complete": bool(entry.get("complete")),
            }
            if not all((builds[k] or {}).get("playersArray") for k in C.BUILDS):
                log(f"{path.name}: a build had no playersArray")
                return 2
            n3 = C.n3_record(builds["incumbent"], builds["n3"], builds["holdOff"])
            deep = C.deep_tail_record(
                builds["incumbent"], builds["deepTail"], builds["holdOff"], builds["ladderPoints"]
            )
            (N3_DIR / f"{stem}.json").write_text(
                json.dumps(
                    {
                        "schema": "idp-n3/v1",
                        "challenger": C.N3_VERSION,
                        "board": board,
                        "pins": pins,
                        **n3,
                    },
                    sort_keys=True,
                ),
                "utf-8",
            )
            (DTN_DIR / f"{stem}.json").write_text(
                json.dumps(
                    {
                        "schema": "idp-deep-tail/v1",
                        "challenger": "idp-deep-tail-native-v1",
                        "board": board,
                        "pins": pins,
                        **deep,
                    },
                    sort_keys=True,
                ),
                "utf-8",
            )
            done += 1
            log(
                f"{path.name} complete={board['complete']} "
                f"n3Guard={n3['guard']['violationCount']} dtnGuard={deep['guard']['violationCount']} "
                f"ladder={len(builds['ladderPoints'])}"
            )
    finally:
        replayer.close()
    log(f"done: {done} boards written")
    return 0


# ── evaluation ──────────────────────────────────────────────────────────


def _load(include_degraded: bool) -> list[dict]:
    manifest = _manifest()
    recs = []
    for name, entry in sorted(manifest.items()):
        if not include_degraded and not entry.get("complete"):
            continue
        stem = Path(name).stem
        n3p, dtp = N3_DIR / f"{stem}.json", DTN_DIR / f"{stem}.json"
        if not (n3p.exists() and dtp.exists()):
            continue
        n3 = json.loads(n3p.read_text("utf-8"))
        dt = json.loads(dtp.read_text("utf-8"))
        recs.append({"board": n3["board"], "pins": n3["pins"], "n3": n3, "deepTail": dt})
    return recs


def _identity(recs: list[dict]) -> dict[str, Any]:
    shas = Counter(r["pins"].get("codeSha") for r in recs)
    dirty = Counter(str(r["pins"].get("workingTreeDirty")) for r in recs)
    return {
        "records": len(recs),
        "codeSha": dict(shas),
        "workingTreeDirty": dict(dirty),
        "payloadSha256": sorted(r["board"]["payloadSha256"] for r in recs),
    }


def _r(x: Any, nd: int = 4) -> Any:
    return round(x, nd) if isinstance(x, float) else x


def _q(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    s = sorted(vals)
    return s[min(len(s) - 1, int(round(p * (len(s) - 1))))]


def cmd_evaluate_n3(args: argparse.Namespace) -> int:
    recs = _load(include_degraded=False)
    expected = sum(1 for e in _manifest().values() if e.get("complete"))
    days = C.daily(recs)
    primary = C.n3_horizon(days, C.PRIMARY_H)
    secondary = [C.n3_horizon(days, h) for h in C.SECONDARY_H]
    decision = C.n3_verdict(primary, secondary)

    def by_pos(pos):
        return lambda _n, row: row.get("pos") == pos

    sens: dict[str, Any] = {}
    all_recs = _load(include_degraded=True)
    sens["S1_all140"] = C.n3_horizon(C.daily(all_recs), C.PRIMARY_H)
    # S2: first origin of each run of the same (player, dropped source).
    units, _c = C.n3_units(days, C.PRIMARY_H)
    seen_prev: dict[tuple, str] = {}
    s2 = []
    ordered_days = sorted(d.isoformat() for d in days)
    for u in sorted(units, key=lambda u: u["day"]):
        key = (u["row"], tuple(u["dropped"]))
        prev = seen_prev.get(key)
        idx = ordered_days.index(u["day"])
        if prev is None or ordered_days.index(prev) != idx - 1:
            s2.append(u)
        seen_prev[key] = u["day"]
    sens["S2_episodeDedup"] = {
        "P1": C._ci(s2, C._mean_key("d"), C.N3_SEED),
        "n": len(s2),
    }
    sens["S3"] = {
        pos: C.n3_horizon(days, C.PRIMARY_H, row_filter=by_pos(pos)) for pos in C.FAMILIES
    }
    sens["S5_persistence"] = C.n3_horizon(days, C.PRIMARY_H, persistence=True)
    sens["S7_noRookies"] = C.n3_horizon(
        days, C.PRIMARY_H, row_filter=lambda _n, row: not row.get("rookie")
    )
    # S8: before vs after the first board where idpShowCombined carries zero weight.
    first_zero = None
    for day in sorted(days):
        rows = days[day]["deepTail"]["rows"]
        ws = [
            (row["votes"].get("idpShowCombined") or {})
            for row in rows.values()
            if "idpShowCombined" in row["votes"]
        ]
        if ws and all((w.get("ex") or (w.get("w") or 0) <= 0) for w in ws):
            first_zero = day
            break
    if first_zero:
        before = {d: r for d, r in days.items() if d < first_zero}
        after = {d: r for d, r in days.items() if d >= first_zero}
        sens["S8"] = {
            "firstZeroWeightBoardDay": first_zero.isoformat(),
            "before": C.n3_horizon(before, C.PRIMARY_H) if len(before) > 7 else None,
            "after": C.n3_horizon(after, C.PRIMARY_H) if len(after) > 7 else None,
        }
    # S6: T2 equal-family median over the other families (circular at n = 3, reported).
    s6 = []
    from src.api.data_contract import correlation_group_for  # noqa: PLC0415

    ordered = sorted(days)
    first = ordered[0]
    for origin in ordered:
        tday = C.target_day(origin, C.PRIMARY_H, ordered)
        if tday is None:
            continue
        orows, trows = days[origin]["n3"]["rows"], days[tday]["n3"]["rows"]
        for name, row in orows.items():
            vi, vc = row["inc"]["v"], row["ch"]["v"]
            if vi is None or vc is None or vi == vc:
                continue
            dropped = set(row["ch"]["drop"]) - set(row["inc"]["drop"])
            fam_drop = {
                "idpShow"
                if correlation_group_for(s) in ("idpTradeCalc", "idpShow")
                else correlation_group_for(s)
                for s in dropped
            }
            tv = (trows.get(name) or {}).get("votes") or {}
            fams: dict[str, list[float]] = defaultdict(list)
            for s, v in tv.items():
                g = correlation_group_for(s)
                g = "idpShow" if g in ("idpTradeCalc", "idpShow") else g
                if g not in fam_drop:
                    fams[g].append(v)
            if len(fams) < 2:
                continue
            t2 = statistics.median(statistics.median(v) for v in fams.values())
            s6.append(
                {
                    "block": (origin - first).days // 7,
                    "d": abs(math.log(vc / t2)) - abs(math.log(vi / t2)),
                }
            )
    sens["S6_T2_circular"] = {"P1": C._ci(s6, C._mean_key("d"), C.N3_SEED), "n": len(s6)}

    # D1 drop census + D4 largest moves on the newest board.
    drop_src = Counter()
    drop_fam = Counter()
    drop_band = Counter()
    for rec in recs:
        for name, row in rec["n3"]["rows"].items():
            new = set(row["ch"]["drop"]) - set(row["inc"]["drop"])
            for s in new:
                drop_src[s] += 1
                drop_fam[row.get("pos")] += 1
                rk = row["inc"].get("rank")
                band = (
                    "unranked"
                    if not isinstance(rk, int)
                    else "1-200"
                    if rk <= 200
                    else "201-400"
                    if rk <= 400
                    else "401-800"
                )
                drop_band[band] += 1
    newest = max(recs, key=lambda r: C.parse_time(r["board"]["scrapeTimestamp"]))
    moves = []
    for name, row in newest["n3"]["rows"].items():
        vi, vc = row["inc"]["v"], row["ch"]["v"]
        if vi and vc and vi != vc:
            moves.append(
                {
                    "row": name,
                    "pos": row.get("pos"),
                    "vInc": vi,
                    "vCh": vc,
                    "move": _r(vc / vi - 1.0),
                    "dropped": sorted(set(row["ch"]["drop"]) - set(row["inc"]["drop"])),
                    "votes": row["votes"],
                    "dlf": row.get("dlf"),
                }
            )
    moves.sort(key=lambda m: -abs(m["move"]))
    guards = {
        "boardsWithViolations": sum(1 for r in recs if r["n3"]["guard"]["violationCount"]),
        "violations": sum(r["n3"]["guard"]["violationCount"] for r in recs),
        "tetherPickRows": sum(r["n3"]["guard"]["tetherPick"] for r in recs),
        "twoWayRows": sum(r["n3"]["guard"]["twoWay"] for r in recs),
        "ordinalOnlyRows": sum(r["n3"]["guard"]["ordinalOnly"] for r in recs),
    }
    per_board = []
    for rec in sorted(recs, key=lambda r: r["board"]["archive"]):
        rows = rec["n3"]["rows"].values()
        per_board.append(
            {
                "archive": rec["board"]["archive"],
                "idpRows": len(rec["n3"]["rows"]),
                "n3Rows": sum(1 for r in rows if r["inc"]["n"] == 3),
                "nGe4Rows": sum(1 for r in rows if r["inc"]["n"] >= 4),
                "challengerOnlyDrops": sum(
                    len(set(r["ch"]["drop"]) - set(r["inc"]["drop"])) for r in rows
                ),
                "rowsMoved": sum(
                    1
                    for r in rows
                    if r["inc"]["v"] and r["ch"]["v"] and r["inc"]["v"] != r["ch"]["v"]
                ),
            }
        )
    out = {
        "experiment": C.N3_VERSION,
        "preregistration": N3_PREREG,
        "label": "archived inputs rebuilt through one replay code revision -- NOT what production served",
        "dataset": {"completeExpected": expected, "completeRecorded": len(recs), **_identity(recs)},
        "seed": C.N3_SEED,
        "primary": primary,
        "secondary": secondary,
        "decision": decision,
        "sensitivities": sens,
        "diagnostics": {
            "D1_dropCensus": {
                "bySource": dict(drop_src),
                "byFamily": dict(drop_fam),
                "byConsensusRankBand": dict(drop_band),
            },
            "D4_largestMovesNewestBoard": {
                "board": newest["board"]["archive"],
                "moves": moves[:20],
            },
            "perBoard": per_board,
        },
        "structuralGuard": guards,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    log(f"verdict {decision['verdict']}; P1 h=7 {primary['P1']} n={primary['n']}")
    return 0


def cmd_evaluate_deep_tail(args: argparse.Namespace) -> int:
    recs = _load(include_degraded=False)
    expected = sum(1 for e in _manifest().values() if e.get("complete"))
    days = C.daily(recs)
    seed = C.DTN_SEED
    primary = C.c1_horizon(days, C.PRIMARY_H)
    secondary = [C.c1_horizon(days, h) for h in C.SECONDARY_H]

    def by_pos(pos):
        return lambda _n, row: row.get("pos") == pos

    families = {pos: C.c1_horizon(days, C.PRIMARY_H, row_filter=by_pos(pos)) for pos in C.FAMILIES}
    r1u = C.r1_units(days, C.PRIMARY_H)
    r1u_ok = [u for u in r1u if u["rows"] >= 30]
    r1 = {
        "R1": C._ci(r1u_ok, C._mean_key("d"), seed),
        "originDays": len(r1u_ok),
        "blocks": len({u["block"] for u in r1u_ok}),
        "meanRows": _r(statistics.fmean([u["rows"] for u in r1u_ok])) if r1u_ok else None,
        "meanRhoInc": _r(statistics.fmean([u["rhoInc"] for u in r1u_ok])) if r1u_ok else None,
        "meanRhoCh": _r(statistics.fmean([u["rhoCh"] for u in r1u_ok])) if r1u_ok else None,
        "daysWithRowsBelow30": len(r1u) - len(r1u_ok),
    }
    r1_disputed = C.r1_units(days, C.PRIMARY_H, disputed_only=True)
    h1u = C.h1_units(days)
    h1 = {
        "H1": C._ci(h1u, C.h1_ratio, seed),
        "pairs": len(h1u),
        "meanIncDailyAbsLogMove": _r(statistics.fmean([u["inc"] for u in h1u])) if h1u else None,
        "meanChDailyAbsLogMove": _r(statistics.fmean([u["ch"] for u in h1u])) if h1u else None,
    }
    limits = json.loads(POLICY.read_text("utf-8"))["boardImpact"]
    rails = []
    for rec in sorted(recs, key=lambda r: r["board"]["archive"]):
        res = C.board_rails(rec["deepTail"]["allRows"], limits)
        rails.append({"archive": rec["board"]["archive"], **res})
    rails_fail = [r["archive"] for r in rails if not r["pass"]]

    # Structural guards: scope guard + S (votes / weights / families / monotone).
    s_viol = []
    boundary_inversions = Counter()
    repriced = Counter()
    skipped_cov = Counter()
    decision_changed_rows = 0
    for rec in recs:
        dt = rec["deepTail"]
        for name, row in dt["rows"].items():
            same_drop = row["inc"]["drop"] == row["ch"]["drop"]
            if not same_drop:
                decision_changed_rows += 1
            for s, v in row["votes"].items():
                if v.get("ex") != v.get("exch") or (same_drop and v.get("w") != v.get("wch")):
                    s_viol.append((rec["board"]["archive"], name, s, "weight"))
                if v.get("dtn"):
                    repriced[s] += 1
                    if not C.repriceable(v, s):
                        s_viol.append((rec["board"]["archive"], name, s, "repriced_out_of_scope"))
                elif v.get("v") != v.get("vch"):
                    s_viol.append((rec["board"]["archive"], name, s, "unrepriced_vote_changed"))
                elif C.repriceable(v, s) and not v.get("ex"):
                    skipped_cov[s] += 1
            if same_drop and (
                row["inc"]["n"] != row["ch"]["n"]
                or row["inc"].get("eff") != row["ch"].get("eff")
                or row["inc"].get("ind") != row["ch"].get("ind")
            ):
                s_viol.append((rec["board"]["archive"], name, "*", "counts"))
        # Monotone within source (repriced votes), and the 500 boundary (diagnostic).
        per_src: dict[str, list] = defaultdict(list)
        for name, row in dt["rows"].items():
            for s, v in row["votes"].items():
                if v.get("r") is not None and v.get("pool") == "shared_market" and v.get("vch"):
                    per_src[s].append((v["r"], v["vch"], bool(v.get("dtn"))))
        for s, items in per_src.items():
            items.sort()
            rep = [x for x in items if x[2]]
            for a, b in zip(rep, rep[1:]):
                if b[0] > a[0] and b[1] > a[1] + 1e-6:
                    s_viol.append((rec["board"]["archive"], "*", s, "inversion_within_repriced"))
            for a, b in zip(items, items[1:]):
                if b[0] > a[0] and b[1] > a[1] + 0.5 and (a[2] != b[2]):
                    boundary_inversions[s] += 1
    guards = {
        "scopeGuardViolations": sum(r["deepTail"]["guard"]["violationCount"] for r in recs),
        "scopeGuardBoardsWithViolations": sum(
            1 for r in recs if r["deepTail"]["guard"]["violationCount"]
        ),
        "tetherPickRows": sum(r["deepTail"]["guard"]["tetherPick"] for r in recs),
        "twoWayRows": sum(r["deepTail"]["guard"]["twoWay"] for r in recs),
        "sViolations": len(s_viol),
        "sViolationSample": s_viol[:30],
        "idpRowsWhoseOutlierDecisionChanged": decision_changed_rows,
        "repricedVotesBySource": dict(repriced),
        "deepBandVotesNotCoveredByLadder": dict(skipped_cov),
        "boundaryInversionsDiagnostic": dict(boundary_inversions),
    }
    guards_ok = guards["scopeGuardViolations"] == 0 and guards["sViolations"] == 0

    # Verdict (PREREGISTRATION §3).
    c = primary["C1"]
    sample_ok = (
        primary["n"] >= 200
        and primary["originDays"] >= 10
        and primary["blocks"] >= 4
        and r1["originDays"] >= 10
    )
    fam_ok = all(
        f["C1"]["point"] is None or f["C1"]["point"] <= 0 for f in families.values() if f["n"] >= 30
    )
    fam_harm = any(
        f["C1"]["lo"] is not None and f["C1"]["lo"] > 0 for f in families.values() if f["n"] >= 30
    )
    sec_neg = sum(1 for s in secondary if s["C1"]["point"] is not None and s["C1"]["point"] < 0)
    r = r1["R1"]
    h = h1["H1"]
    checks = {
        "C1_upper95_lt_0": c["hi"] is not None and c["hi"] < 0,
        "C1_negative_secondary_ge_2": sec_neg >= 2,
        "C1_le_0_every_family_ge30": fam_ok,
        "R1_lower95_ge_-0.005": r["lo"] is not None and r["lo"] >= -0.005,
        "H1_upper95_le_1.10": h["hi"] is not None and h["hi"] <= 1.10,
        "guards_hold": guards_ok,
        "rails_every_board": not rails_fail,
    }
    not_better = {
        "C1_lower95_gt_0": c["lo"] is not None and c["lo"] > 0,
        "family_C1_lower95_gt_0": fam_harm,
        "R1_upper95_lt_0": r["hi"] is not None and r["hi"] < 0,
        "H1_lower95_gt_1.10": h["lo"] is not None and h["lo"] > 1.10,
        "rail_failed": bool(rails_fail),
    }
    if not sample_ok:
        verdict = "INSUFFICIENT"
    elif any(not_better.values()):
        verdict = "NOT BETTER"
    elif all(checks.values()):
        verdict = "PROMOTION-ELIGIBLE"
    else:
        verdict = "INCONCLUSIVE"

    sens: dict[str, Any] = {}
    all_days = C.daily(_load(include_degraded=True))
    sens["S1_all140"] = {
        "C1": C.c1_horizon(all_days, C.PRIMARY_H),
        "R1": C._ci(
            [u for u in C.r1_units(all_days, C.PRIMARY_H) if u["rows"] >= 30],
            C._mean_key("d"),
            seed,
        ),
        "H1": C._ci(C.h1_units(all_days), C.h1_ratio, seed),
    }
    sens["S3"] = {
        pos: {
            "C1": families[pos],
            "R1": C._ci(
                C.r1_units(days, C.PRIMARY_H, row_filter=by_pos(pos)), C._mean_key("d"), seed
            ),
            "H1": C._ci(C.h1_units(days, row_filter=by_pos(pos)), C.h1_ratio, seed),
        }
        for pos in C.FAMILIES
    }
    sens["S4_inSampleLadder"] = C.c1_horizon(days, C.PRIMARY_H, in_sample=True)
    sens["S5_persistence"] = C.c1_horizon(days, C.PRIMARY_H, persistence=True)
    sens["S6_playerNotOnIdptcAtOrigin"] = C.c1_horizon(days, C.PRIMARY_H, out_of_sample_player=True)
    sens["S7_noRookies"] = C.c1_horizon(
        days, C.PRIMARY_H, row_filter=lambda _n, row: not row.get("rookie")
    )
    srcs = sorted({u["source"] for u in C.c1_units(days, C.PRIMARY_H)[0]})
    sens["S8_bySource"] = {s: C.c1_horizon(days, C.PRIMARY_H, source_filter=s) for s in srcs}
    sens["S9_bands"] = {
        "501-700": C.c1_horizon(days, C.PRIMARY_H, band=(500, 700)),
        "701-904": C.c1_horizon(days, C.PRIMARY_H, band=(700, 904)),
    }
    sens["R1_disputedRowsOnly"] = {
        "R1": C._ci([u for u in r1_disputed if u["rows"] >= 3], C._mean_key("d"), seed),
        "originDays": len(r1_disputed),
    }

    # Diagnostics D1-D5.
    def band_of(r: float) -> str:
        if r <= 600:
            return "501-600"
        if r <= 700:
            return "601-700"
        return "701-800" if r <= 800 else "801-904"

    d1 = defaultdict(Counter)
    d2 = defaultdict(list)
    conf = Counter()
    moved_rows = []
    pull = Counter()
    for rec in recs:
        for name, row in rec["deepTail"]["rows"].items():
            for s, v in row["votes"].items():
                if v.get("dtn") and v.get("r"):
                    b = band_of(v["r"])
                    d1["bySource"][s] += 1
                    d1["byFamily"][row.get("pos")] += 1
                    d1["byBand"][b] += 1
                    hv, nv = v["dtn"].get("hillValue"), v["dtn"].get("nativeValue")
                    if hv and nv:
                        d2[b].append(math.log(nv / hv))
            vi, vc = row["inc"]["v"], row["ch"]["v"]
            if row["inc"].get("conf") != row["ch"].get("conf"):
                conf[f"{row['inc'].get('conf')}->{row['ch'].get('conf')}"] += 1
            if vi and vc and vi != vc:
                moved_rows.append(abs(vc / vi - 1.0))
                it = (row["votes"].get(C.IDPTC) or {}).get("v")
                if it:
                    pull[
                        "towardOwnIdptcVote" if abs(vc - it) < abs(vi - it) else "awayOrEqual"
                    ] += 1
                else:
                    pull["noIdptcVote"] += 1
    newest = max(recs, key=lambda r: C.parse_time(r["board"]["scrapeTimestamp"]))
    d5 = []
    for name, row in newest["deepTail"]["rows"].items():
        vi, vc = row["inc"]["v"], row["ch"]["v"]
        if vi and vc and vi != vc:
            d5.append(
                {
                    "row": name,
                    "pos": row.get("pos"),
                    "vInc": vi,
                    "vCh": vc,
                    "move": _r(vc / vi - 1.0),
                    "repriced": {
                        s: v["dtn"] | {"r": v["r"]} for s, v in row["votes"].items() if v.get("dtn")
                    },
                    "idptc": (row["votes"].get(C.IDPTC) or {}).get("v"),
                }
            )
    d5.sort(key=lambda m: -abs(m["move"]))

    def churn(rec, n):
        rows = rec["deepTail"]["rows"]
        a = sorted((r["inc"]["v"] or 0, k) for k, r in rows.items())[::-1][:n]
        b = sorted((r["ch"]["v"] or 0, k) for k, r in rows.items())[::-1][:n]
        return len({k for _v, k in a} - {k for _v, k in b})

    out = {
        "experiment": "idp-deep-tail-native-v1",
        "preregistration": DTN_PREREG,
        "label": "archived inputs rebuilt through one replay code revision -- NOT what production served",
        "dataset": {"completeExpected": expected, "completeRecorded": len(recs), **_identity(recs)},
        "seed": seed,
        "primary": {"C1": primary, "R1": r1, "H1": h1, "families": families},
        "secondary": secondary,
        "decision": {
            "verdict": verdict,
            "promotionChecks": checks,
            "notBetterTriggers": not_better,
            "secondaryNegative": sec_neg,
            "minimumSample": {
                "C1": [primary["n"], 200],
                "C1originDays": [primary["originDays"], 10],
                "C1blocks": [primary["blocks"], 4],
                "R1originDays": [r1["originDays"], 10],
                "met": sample_ok,
            },
            "governanceOverlay": "AUTO_PROMOTION_BLOCKED: no_independent_validation_target",
        },
        "boardRails": {"failedBoards": rails_fail, "perBoard": rails},
        "structuralGuard": guards,
        "sensitivities": sens,
        "diagnostics": {
            "D1_repriceCensus": {k: dict(v) for k, v in d1.items()},
            "D2_logNativeOverHillByBand": {
                b: {
                    "n": len(v),
                    "median": _r(_q(v, 0.5)),
                    "p10": _r(_q(v, 0.1)),
                    "p90": _r(_q(v, 0.9)),
                }
                for b, v in sorted(d2.items())
            },
            "D3_publishedMoves": {
                "rowsMoved": len(moved_rows),
                "median": _r(_q(moved_rows, 0.5)),
                "p90": _r(_q(moved_rows, 0.9)),
                "max": _r(max(moved_rows)) if moved_rows else None,
                "idpTopChurnNewestBoard": {n: churn(newest, n) for n in (24, 50, 100)},
                "movedTowardOwnIdptcVote": dict(pull),
            },
            "D4_confidenceTransitions": dict(conf),
            "D5_largestMovesNewestBoard": {"board": newest["board"]["archive"], "moves": d5[:20]},
        },
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    log(f"verdict {verdict}; C1 {c} n={primary['n']}; R1 {r}; H1 {h}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("backfill")
    p.add_argument("--shard", default="0/1", help="i/k: build only boards with index %% k == i")
    p = sub.add_parser("evaluate-n3")
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("evaluate-deep-tail")
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.cmd == "backfill":
        return cmd_backfill(args)
    if args.cmd == "evaluate-n3":
        return cmd_evaluate_n3(args)
    return cmd_evaluate_deep_tail(args)


if __name__ == "__main__":
    raise SystemExit(main())
