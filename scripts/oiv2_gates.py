#!/usr/bin/env python3
"""Outlier-integrity-v2 directive §5 gates, FULL PIPELINE, on one archived board.

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V2_PREREGISTRATION.md`` §7;
harness ``src/robust_filter_shadow/oiv2_gates.py`` (which says exactly which
pipeline component each gate measures).

Held-out discipline is enforced here, not left to the operator: a board in
V_HELDOUT, I_INDEPENDENT or R_REGRESSION_PIN is REFUSED unless
``--stage4-gate-of-record`` is passed, and that flag additionally requires the
Stage 2 freeze (``status`` of ``config/sources/outlier_integrity_v2.json`` not
``provisional_stage1``) and a clean tree. Before the freeze the only legitimate
use is a DEVELOPMENT run on an E board (prereg §5.3 Stage 1).

Exit codes: 0 every gate passes; 1 at least one gate fails (a failing gate is a
result, never relabelled); 2 inputs missing / refused / a build failed.

Usage::

    python scripts/oiv2_gates.py --board dynasty_export_20260930_130404.zip --out <json>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts import joint_filter_shadow as J  # noqa: E402
from src.robust_filter_shadow import oiv2_gates as G  # noqa: E402

MANIFESTS = REPO_ROOT / "docs" / "sources" / "outlier_integrity_v2" / "manifests"
HELD_OUT = ("V_HELDOUT", "I_INDEPENDENT", "R_REGRESSION_PIN")
DEVELOPMENT = ("E_DEV", "E_BASELINE")


def log(msg: str) -> None:
    print(f"[oiv2-gates] {msg}", flush=True)


def population_of(board: str) -> tuple[str | None, dict | None]:
    for path in sorted(MANIFESTS.glob("*.json")):
        try:
            data = json.loads(path.read_text("utf-8"))
        except ValueError:
            continue
        for entry in data.get("boards") or []:
            if isinstance(entry, dict) and entry.get("board") == board:
                return str(data.get("population")), entry
    return None, None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--board", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=G.SEED)
    ap.add_argument("--max-rows", type=int, default=None)
    ap.add_argument("--gates", default=",".join(G.GATES))
    ap.add_argument("--stage4-gate-of-record", action="store_true")
    ap.add_argument("--report-v1", action="store_true", help="also report V1's rates")
    ap.add_argument(
        "--history-file",
        type=Path,
        default=None,
        help="ARRIVING variant: the V2 history lane before this board (oiv2_replay run)",
    )
    args = ap.parse_args(argv)

    population, entry = population_of(args.board)
    if population is None or entry is None:
        log(f"{args.board} is in no frozen manifest; refused")
        return 2
    if population in HELD_OUT:
        from src.api import source_integrity as si  # noqa: PLC0415
        from src.api import value_replay as vr  # noqa: PLC0415

        if not args.stage4_gate_of_record:
            log(
                f"{args.board} is {population}: held-out boards are evaluated once (Stage 4); refused"
            )
            return 2
        if si.load_thresholds().status == "provisional_stage1" or vr._dirty():
            log("Stage 4 needs frozen thresholds and a clean tree; refused")
            return 2
    elif population not in DEVELOPMENT:
        log(f"{args.board}: population {population} is not a development population; refused")
        return 2

    adds = J.archive_add_commits()
    commit, cut = adds.get(args.board, (None, None))
    path = J.ARCHIVE_DIR / args.board
    if not path.is_file() and commit:
        blob = J._git("show", f"{commit}:exports/archive/{args.board}", binary=True)
        if blob:
            tmpzip = Path(tempfile.mkdtemp(prefix="oiv2-zip-")) / args.board
            tmpzip.write_bytes(blob)
            path = tmpzip
    if commit is None or not path.is_file():
        log("archive or its add commit unavailable")
        return 2
    zbytes = path.read_bytes()
    data, raw, site = J.load_archive(path)
    if (
        hashlib.sha256(zbytes).hexdigest() != entry["zipSha256"]
        or hashlib.sha256(data).hexdigest() != entry["payloadSha256"]
    ):
        log("hash mismatch against the frozen manifest; refused")
        return 2

    from src.api import value_replay as vr  # noqa: PLC0415

    t0 = time.time()
    replayer = J.StateReplayer()
    try:
        replayer.advance(cut)
        with tempfile.TemporaryDirectory(prefix="oiv2-gates-") as tmp:
            root = Path(tmp)
            J.materialize_tree(root, commit, site)
            replayer.write(root / "data" / "scrape_state")
            history = None
            variant = "NO-HISTORY"
            if args.history_file is not None:
                import gzip  # noqa: PLC0415

                from src.api import source_integrity as si  # noqa: PLC0415

                with gzip.open(args.history_file, "rt", encoding="utf-8") as fh:
                    blob = json.load(fh)
                if blob.get("beforeBoard") != args.board:
                    log("history file is not the state before this board; refused")
                    return 2
                history = si.IntegrityHistory.from_json(blob.get("history"))
                variant = "ARRIVING"
            result = G.run_all(
                raw,
                root,
                seed=args.seed,
                max_rows=args.max_rows,
                gates=[g for g in args.gates.split(",") if g],
                progress=log,
                report_v1=args.report_v1,
                history=history,
                variant=variant,
            )
    except Exception as exc:  # noqa: BLE001
        log(f"build failed: {exc!r}")
        return 2
    finally:
        replayer.close()
    result.update(
        {
            "board": {
                "archive": args.board,
                "population": population,
                "zipSha256": entry["zipSha256"],
                "payloadSha256": entry["payloadSha256"],
                "addCommit": commit,
            },
            "status": "gate_of_record_stage4"
            if args.stage4_gate_of_record
            else "development_run_not_gate_of_record",
            "codeSha": (vr._git("rev-parse", "HEAD") or "").strip() or None,
            "workingTreeDirty": vr._dirty(),
            "wallSeconds": round(time.time() - t0, 1),
        }
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True, default=str) + "\n", "utf-8")
    log(json.dumps(result["gates"]))
    ran = [v for v in result["gates"].values() if v is not None]
    return 0 if ran and all(ran) else 1


if __name__ == "__main__":
    raise SystemExit(main())
