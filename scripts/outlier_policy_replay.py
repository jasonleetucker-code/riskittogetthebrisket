#!/usr/bin/env python3
"""Historical replay of ``outlier-corroborated-v1`` (owner directive 2026-10-19 §6).

``docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md`` fixes
the dataset, builds, metrics and verdict; this script only executes them.

``backfill`` replays every board of the frozen manifest
(``docs/valuation/evidence/idp-outlier-n3-2026-10-18/ARCHIVE_MANIFEST.json``,
hash-checked; a board pruned from the working tree is recovered byte-exact from the
commit that added it) through the inherited rebuild procedure
(``scripts/joint_filter_shadow.py``) and builds it three ways, all with the DLF IDP
vote hold OFF: incumbent filter, the policy, ``idp-hampel-n3-v1``. One gitignored
compact record per board goes to ``data/outlier_policy_replay/``.

``evaluate`` applies M1-M6 and the verdict table; ``adversarial`` runs the M7 suite
(function level on the newest frozen board, plus the two end-to-end checks).

Usage (full git history needed)::

    python scripts/outlier_policy_replay.py backfill [--shard 0/2]
    python scripts/outlier_policy_replay.py evaluate --out <json>
    python scripts/outlier_policy_replay.py adversarial --out <json>

Exit codes: 0 done; 1 inputs missing (shallow clone, manifest mismatch); 2 a build
failed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import statistics
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import joint_filter_shadow as J  # noqa: E402
from src.robust_filter_shadow import outlier_policy_eval as E  # noqa: E402

OUT_DIR = REPO_ROOT / "data" / "outlier_policy_replay"
RECOVERED = OUT_DIR / "_recovered_archives"
MANIFEST = (
    REPO_ROOT
    / "docs"
    / "valuation"
    / "evidence"
    / "idp-outlier-n3-2026-10-18"
    / "ARCHIVE_MANIFEST.json"
)
PREREG = "docs/valuation/evidence/outlier-disagreement-2026-10-19/PREREGISTRATION.md"
NEWEST_FROZEN = "dynasty_export_20261018_114711.zip"


def log(msg: str) -> None:
    print(f"[outlier-policy] {msg}", flush=True)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest() -> dict[str, dict]:
    data = json.loads(MANIFEST.read_text("utf-8"))
    return {b["board"]: b for b in data["boards"]}


def _code_pins() -> dict[str, Any]:
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import outlier_policy as op  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    return {
        "codeSha": (vr._git("rev-parse", "HEAD") or "").strip() or None,
        "workingTreeDirty": vr._dirty(),
        "hampel": {
            "K": dc._HAMPEL_K,
            "minN": dc._HAMPEL_MIN_N,
            "idpN3MinN": dc._IDP_HAMPEL_N3_MIN_N,
            "floor": dc._HAMPEL_MIN_THRESHOLD,
        },
        "policy": op.constants(),
        "builds": {k: dict(v) for k, v in E.BUILDS.items()},
        "preregistration": PREREG,
    }


def _plan(adds: dict) -> tuple[list, list]:
    manifest = _manifest()
    plan, missing = [], []
    for name, entry in sorted(manifest.items()):
        path = J.ARCHIVE_DIR / name
        commit, cut = adds.get(name, (None, None))
        if not path.is_file():
            blob = (
                J._git("show", f"{commit}:exports/archive/{name}", binary=True) if commit else None
            )
            if not blob:
                missing.append(name)
                continue
            RECOVERED.mkdir(parents=True, exist_ok=True)
            path = RECOVERED / name
            path.write_bytes(blob)
        zbytes = path.read_bytes()
        data, raw, site = J.load_archive(path)
        if _sha(zbytes) != entry["zipSha256"] or _sha(data) != entry["payloadSha256"]:
            missing.append(name)
            continue
        if commit is None:
            missing.append(name)
            continue
        plan.append((cut, path, raw, site, entry, commit))
    plan.sort(key=lambda item: item[0])
    return plan, missing


def _tree_root(path: Path, commit: str, site: dict, replayer, tmp: str) -> Path:
    root = Path(tmp)
    J.materialize_tree(root, commit, site)
    replayer.write(root / "data" / "scrape_state")
    return root


def cmd_backfill(args: argparse.Namespace) -> int:
    from src.api import value_replay as vr  # noqa: PLC0415

    try:
        if J._git("rev-parse", "--is-shallow-repository").strip() == "true":
            log("shallow clone: run `git fetch --unshallow` first")
            return 1
        adds = J.archive_add_commits()
    except Exception as exc:  # noqa: BLE001
        log(f"git history unavailable: {exc}")
        return 1
    plan, missing = _plan(adds)
    if missing:
        log(f"manifest boards missing or hash-mismatched: {missing}")
        return 1
    shard, shards = (int(x) for x in args.shard.split("/"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    code = _code_pins()
    replayer = J.StateReplayer()
    done = 0
    try:
        for i, (cut, path, raw, site, entry, commit) in enumerate(plan):
            replayer.advance(cut)
            if i % shards != shard:
                continue
            out = OUT_DIR / f"{path.stem}.json.gz"
            if out.exists():
                continue
            with tempfile.TemporaryDirectory(prefix="olp-") as tmp:
                root = _tree_root(path, commit, site, replayer, tmp)
                pins = {
                    **code,
                    "csvCommit": commit,
                    "csvTreeSha256": J.R.tree_sha256(root, ["CSVs/site_raw"], "*.csv"),
                    "stateTreeSha256": J.R.tree_sha256(
                        root, ["data/scrape_state"], "*_dataset.json"
                    ),
                    "stateReplayThrough": cut.isoformat(),
                }
                builds = {
                    name: vr.build(raw, {"csv_root": root, "flags": flags})
                    for name, flags in E.BUILDS.items()
                }
            if not all((builds[k] or {}).get("playersArray") for k in E.BUILDS):
                log(f"{path.name}: a build had no playersArray")
                return 2
            rec = {
                "schema": E.SCHEMA,
                "board": {
                    "archive": path.name,
                    "zipSha256": entry["zipSha256"],
                    "payloadSha256": entry["payloadSha256"],
                    "scrapeTimestamp": entry.get("scrapeTimestamp"),
                    "complete": bool(entry.get("complete")),
                },
                "pins": pins,
                **E.extract_record(builds),
            }
            with gzip.open(out, "wt", encoding="utf-8") as fh:
                json.dump(rec, fh, sort_keys=True)
            done += 1
            c = E.census(rec)
            log(
                f"{path.name} complete={rec['board']['complete']} "
                f"drops inc={c['incumbent']['drops']} pol={c['policy']['drops']} "
                f"n3={c['n3']['drops']} screen={c['boardScreenFlagged']} "
                f"votesIdentical={rec['checks']['votesIdentical']}"
            )
    finally:
        replayer.close()
    log(f"done: {done} boards written")
    return 0


def load_records(include_degraded: bool) -> list[dict]:
    manifest = _manifest()
    recs = []
    for name, entry in sorted(manifest.items()):
        if not include_degraded and not entry.get("complete"):
            continue
        p = OUT_DIR / f"{Path(name).stem}.json.gz"
        if not p.exists():
            continue
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            recs.append(json.load(fh))
    return recs


def _identity(recs: list[dict]) -> dict[str, Any]:
    return {
        "records": len(recs),
        "codeSha": dict(Counter(r["pins"].get("codeSha") for r in recs)),
        "workingTreeDirty": dict(Counter(str(r["pins"].get("workingTreeDirty")) for r in recs)),
        "votesIdentical": dict(Counter(str(r["checks"]["votesIdentical"]) for r in recs)),
        "payloadSha256": sorted(r["board"]["payloadSha256"] for r in recs),
    }


def _emulator_fidelity(days: dict) -> dict[str, Any]:
    """How closely the M1 emulator reproduces the incumbent's published blend."""
    rel = []
    for rec in days.values():
        for name, row in rec["rows"].items():
            if row.get("ac") == "pick" or not row.get("blend") or len(row["votes"]) < 2:
                continue
            drop = set((rec["variants"]["incumbent"].get(name) or [None, None, []])[2])
            v = E.blend({k: x for k, x in row["votes"].items() if k not in drop}, row["w"])
            if v:
                rel.append(abs(v - row["blend"]) / row["blend"])
    rel.sort()
    n = len(rel)
    return {
        "rows": n,
        "within0.5pct": round(sum(1 for x in rel if x <= 0.005) / n, 4) if n else None,
        "within2pct": round(sum(1 for x in rel if x <= 0.02) / n, 4) if n else None,
        "median": round(rel[n // 2], 5) if n else None,
        "p90": round(rel[int(0.9 * (n - 1))], 5) if n else None,
    }


def _segment(units: list[dict], pred) -> list[dict]:
    return [u for u in units if pred(u)]


def _s7_dedup(units: list[dict]) -> list[dict]:
    seen: dict[tuple, str] = {}
    out = []
    days = sorted({u["day"] for u in units})
    idx = {d: i for i, d in enumerate(days)}
    for u in sorted(units, key=lambda u: u["day"]):
        key = (
            u["row"],
            u["family"],
            tuple(u["dropped"]["policy"]),
            tuple(u["dropped"]["incumbent"]),
        )
        prev = seen.get(key)
        if prev is None or idx[prev] != idx[u["day"]] - 1:
            out.append(u)
        seen[key] = u["day"]
    return out


def _verdict(primary: dict, gate_ok: bool | None, fp: int, stab: dict) -> dict[str, Any]:
    p = primary["policy"]
    ratio = (stab.get("all") or {}).get("ratioPolicyOverIncumbent") or {}
    rci = ratio.get("ci95")
    if p["n"] < E.MIN_UNITS or p["days"] < E.MIN_DAYS or p["blocks"] < E.MIN_BLOCKS:
        verdict = "INSUFFICIENT"
    elif (
        (p["ci95"] and p["ci95"][0] > E.NONINFERIORITY)
        or gate_ok is False
        or fp > 0
        or (rci and rci[0] > E.STABILITY_LIMIT)
    ):
        verdict = "NOT_ELIGIBLE"
    elif (
        p["ci95"]
        and p["ci95"][1] <= E.NONINFERIORITY
        and gate_ok is True
        and fp == 0
        and rci
        and rci[1] <= E.STABILITY_LIMIT
    ):
        verdict = "PROMOTION_ELIGIBLE_PENDING_INDEPENDENT_VALIDATION"
    else:
        verdict = "INCONCLUSIVE"
    return {
        "verdict": verdict,
        "better": bool(p["ci95"] and p["ci95"][1] < 0),
        "minimumSample": {"units": p["n"], "days": p["days"], "blocks": p["blocks"]},
        "adversarialGatePasses": gate_ok,
        "boardScreenFalsePositives": fp,
        "stabilityRatio": ratio,
    }


def cmd_evaluate(args: argparse.Namespace) -> int:
    recs = load_records(include_degraded=False)
    expected = sum(1 for e in _manifest().values() if e.get("complete"))
    days = E.daily(recs)
    screens: dict = {}
    horizons: dict[str, Any] = {}
    units_by_h: dict[int, list] = {}
    for h in (E.PRIMARY_H, *E.SECONDARY_H, 0):
        units = E.m1_units(days, h, screens=screens)
        units_by_h[h] = units
        horizons[str(h)] = {
            "units": len(units),
            **{m: E.paired_stat(units, m) for m in ("policy", "n3", "none")},
            "allUnits": {
                m: E.paired_stat(units, m, disputed_only=False) for m in ("policy", "n3", "none")
            },
        }
    prim = units_by_h[E.PRIMARY_H]
    sens: dict[str, Any] = {}
    all_recs = load_records(include_degraded=True)
    sens["S1_all140"] = E.paired_stat(E.m1_units(E.daily(all_recs), E.PRIMARY_H), "policy")
    for seg in ("offense", "idp"):
        sens[f"S2_{seg}"] = {
            m: E.paired_stat(_segment(prim, lambda u, s=seg: u["ac"] == s), m)
            for m in ("policy", "n3", "none")
        }
    sens["S3_byHeldOutFamily"] = {
        f: E.paired_stat(_segment(prim, lambda u, f=f: u["family"] == f), "policy")
        for f in sorted({u["family"] for u in prim})
    }
    sens["S4_h0_persistence"] = horizons["0"]["policy"]
    sens["S5_noBoardScreen"] = E.paired_stat(
        E.m1_units(days, E.PRIMARY_H, with_screen=False), "policy"
    )
    sens["S6_dlfNotHeldOut"] = E.paired_stat(
        _segment(prim, lambda u: u["family"] != "dlf"), "policy"
    )
    sens["S7_episodeDedup"] = E.paired_stat(_s7_dedup(prim), "policy")
    stab = E.m4_stability(days)
    m3 = {str(h): E.m3_outcomes(days, h) for h in (E.PRIMARY_H, *E.SECONDARY_H)}
    per_board = []
    fired = []
    for rec in sorted(recs, key=lambda r: r["board"]["scrapeTimestamp"]):
        c = E.census(rec)
        per_board.append(
            {
                "archive": rec["board"]["archive"],
                "scrapeTimestamp": rec["board"]["scrapeTimestamp"],
                "drops": {m: c[m]["drops"] for m in ("incumbent", "policy", "n3")},
                "policyReasons": c["policyReasons"],
                "boardScreenFlagged": c["boardScreenFlagged"],
                "valueChangePolicyVsIncumbent": E.value_changes(rec, "incumbent", "policy").get(
                    "all"
                ),
            }
        )
        if c["boardScreenFlagged"]:
            fired.append({"archive": rec["board"]["archive"], "flagged": c["boardScreenFlagged"]})
    totals = Counter()
    by_source = {m: Counter() for m in ("incumbent", "policy", "n3")}
    for rec in recs:
        c = E.census(rec)
        for m in by_source:
            by_source[m].update(c[m]["bySource"])
            totals[m] += c[m]["drops"]
    newest = next((r for r in recs if r["board"]["archive"] == NEWEST_FROZEN), None)
    newest_block = None
    if newest is not None:
        newest_block = {
            "archive": NEWEST_FROZEN,
            "census": E.census(newest),
            "valueChanges": {
                "policyVsIncumbent": E.value_changes(newest, "incumbent", "policy"),
                "n3VsIncumbent": E.value_changes(newest, "incumbent", "n3"),
            },
            "moversOver30pct": {
                "policyVsIncumbent": E.movers(newest, "incumbent", "policy"),
                "n3VsIncumbent": E.movers(newest, "incumbent", "n3"),
            },
        }
    # The adversarial gate is read from its own evidence file when present.
    gate_ok = None
    adv_path = args.out.parent / "adversarial_suite.json"
    if adv_path.exists():
        gate_ok = bool(json.loads(adv_path.read_text("utf-8")).get("summary", {}).get("gatePasses"))
    decision = _verdict(horizons[str(E.PRIMARY_H)], gate_ok, len(fired), stab)
    result = {
        "schema": "outlier-policy-evaluation/v1",
        "preregistration": PREREG,
        "label": "archived inputs rebuilt through one replay code revision; NOT what production served",
        "identity": _identity(recs),
        "expectedCompleteBoards": expected,
        "originDays": len(days),
        "emulatorFidelity": _emulator_fidelity(days),
        "decision": decision,
        "M1": horizons,
        "sensitivities": sens,
        "M3": m3,
        "M4": stab,
        "M5": {
            "totals": dict(totals),
            "bySource": {m: dict(c.most_common()) for m, c in by_source.items()},
            "boardScreenFirings": fired,
            "perBoard": per_board,
        },
        "M6_newestFrozenBoard": newest_block,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    log(json.dumps({"decision": decision, "primary": horizons[str(E.PRIMARY_H)]["policy"]}))
    return 0


def _rewrite_csv(path: Path, transform) -> None:
    text = path.read_text("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    rows = transform(rows, reader.fieldnames or [])
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=reader.fieldnames or [])
    w.writeheader()
    w.writerows(rows)
    path.write_text(buf.getvalue(), "utf-8")


def cmd_adversarial(args: argparse.Namespace) -> int:
    from src.api import value_replay as vr  # noqa: PLC0415

    recs = [
        r for r in load_records(include_degraded=False) if r["board"]["archive"] == NEWEST_FROZEN
    ]
    if not recs:
        log("newest frozen board's record missing; run backfill first")
        return 1
    rec = recs[0]
    summary = E.adversarial(rec)
    # End-to-end checks (E1, E2) on the newest frozen board's own tree.
    adds = J.archive_add_commits()
    plan, missing = _plan(adds)
    if missing:
        log(f"manifest boards missing: {missing}")
        return 1
    replayer = J.StateReplayer()
    e2e: dict[str, Any] = {}
    try:
        for cut, path, raw, site, _entry, commit in plan:
            replayer.advance(cut)
            if path.name != NEWEST_FROZEN:
                continue
            flags = E.BUILDS["policy"]
            with tempfile.TemporaryDirectory(prefix="olp-adv-") as tmp:
                root = _tree_root(path, commit, site, replayer, tmp)
                dn = root / "CSVs" / "site_raw" / "dynastyNerdsSfTep.csv"
                original = dn.read_bytes()

                def reverse_ranks(rows, _f):
                    ranks = [float(r["Rank"]) for r in rows if r.get("Rank")]
                    top = max(ranks) if ranks else 0.0
                    for r in rows:
                        if r.get("Rank"):
                            r["Rank"] = str(int(top + 1 - float(r["Rank"])))
                    return rows

                def drop_first_page(rows, _f):
                    kept = sorted(rows, key=lambda r: float(r.get("Rank") or 1e9))[150:]
                    for i, r in enumerate(kept, start=1):
                        r["Rank"] = str(i)
                    return kept

                def double_ranks(rows, _f):
                    for r in rows:
                        if r.get("Rank"):
                            r["Rank"] = str(int(float(r["Rank"]) * 2))
                    return rows

                base_votes = {
                    r.get("displayName"): E._row_votes(r)[0].get("dynastyNerdsSfTep")
                    for r in vr.build(raw, {"csv_root": root, "flags": flags})["playersArray"]
                }
                for label, transform in (
                    ("E1_registered_doubledRanks", double_ranks),
                    ("E1_reversedRanks", reverse_ranks),
                    ("E1b_firstPageLost", drop_first_page),
                ):
                    dn.write_bytes(original)
                    _rewrite_csv(dn, transform)
                    c1 = vr.build(raw, {"csv_root": root, "flags": flags})
                    stamp = c1.get("outlierPolicy") or {}
                    screen = stamp.get("boardScreen") or {}
                    dn_rows = [
                        r
                        for r in c1["playersArray"]
                        if r.get("assetClass") == "offense"
                        and "dynastyNerdsSfTep" in E._row_votes(r)[0]
                    ]
                    dropped = sum(
                        1 for r in dn_rows if "dynastyNerdsSfTep" in (r.get("droppedSources") or [])
                    )
                    flagged = "dynastyNerdsSfTep" in (screen.get("flagged") or {}).get(
                        "offense", []
                    )
                    changed = sum(
                        1
                        for r in c1["playersArray"]
                        if E._row_votes(r)[0].get("dynastyNerdsSfTep")
                        != base_votes.get(r.get("displayName"))
                    )
                    e2e[label] = {
                        "votesChangedByCorruption": changed,
                        "flagged": screen.get("flagged"),
                        "rankingPasses": stamp.get("rankingPasses"),
                        "stats": (screen.get("stats") or {}).get("dynastyNerdsSfTep|offense"),
                        "rowsWithVote": len(dn_rows),
                        "rowsDropped": dropped,
                        "passes": flagged and dropped >= max(1, len(dn_rows) - 5),
                    }
                dn.write_bytes(original)
                # E2: swap two far-apart players' rows in one rank source.
                fc = root / "CSVs" / "site_raw" / "flockFantasySf.csv"
                fc_text = list(csv.DictReader(io.StringIO(fc.read_text("utf-8"))))
                names = [r["name"] for r in fc_text]
                pairs = [(names[i], names[i + 150]) for i in (5, 20, 40) if i + 150 < len(names)]

                def swap(rows, _f, pairs=pairs):
                    idx = {r["name"]: i for i, r in enumerate(rows)}
                    for a, b in pairs:
                        ia, ib = idx[a], idx[b]
                        rows[ia]["name"], rows[ib]["name"] = rows[ib]["name"], rows[ia]["name"]
                    return rows

                _rewrite_csv(fc, swap)
                c2 = vr.build(raw, {"csv_root": root, "flags": flags})
                c2_inc = vr.build(raw, {"csv_root": root, "flags": E.BUILDS["incumbent"]})
                rows2 = {r.get("displayName"): r for r in c2["playersArray"]}
                rows2i = {r.get("displayName"): r for r in c2_inc["playersArray"]}
                checks = []
                for a, b in pairs:
                    for name in (a, b):
                        r = rows2.get(name) or {}
                        votes = E._row_votes(r)[0]
                        others = [v for k, v in votes.items() if k != "flockFantasySf"]
                        checks.append(
                            {
                                "row": name,
                                "flockVote": votes.get("flockFantasySf"),
                                "othersMedian": statistics.median(others) if others else None,
                                "policyDropped": "flockFantasySf"
                                in (r.get("droppedSources") or []),
                                "incumbentDropped": "flockFantasySf"
                                in ((rows2i.get(name) or {}).get("droppedSources") or []),
                                "policyReason": (r.get("outlierPolicyReasons") or {}).get(
                                    "flockFantasySf"
                                ),
                            }
                        )
                e2e["E2_swappedRows"] = {"pairs": pairs, "rows": checks}
            break
    finally:
        replayer.close()
    out = {
        "schema": "outlier-policy-adversarial/v1",
        "preregistration": PREREG,
        "board": rec["board"],
        "codeSha": rec["pins"].get("codeSha"),
        "seed": E.SEED,
        "summary": summary,
        "endToEnd": e2e,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(out, indent=1, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    log(json.dumps({k: v.get("policyPasses") for k, v in summary.items() if isinstance(v, dict)}))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill")
    b.add_argument("--shard", default="0/1")
    e = sub.add_parser("evaluate")
    e.add_argument("--out", type=Path, required=True)
    a = sub.add_parser("adversarial")
    a.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    return {"backfill": cmd_backfill, "evaluate": cmd_evaluate, "adversarial": cmd_adversarial}[
        args.cmd
    ](args)


if __name__ == "__main__":
    raise SystemExit(main())
