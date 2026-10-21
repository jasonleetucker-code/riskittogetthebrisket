"""Extract a recorded Package VA phase's inputs with the code AT the recorded revision.

RESEARCH HELPER for ``scripts/package_model_v2_remeasure.py`` (2026-10-21).  The
canonical pipeline changed after Phases 1-2 ran (the pick horizon and Travis
Hunter's value, among others), so a board rebuilt today from the same pinned
payload is not the recorded board.  This script is run with a DETACHED checkout of
the recorded revision as its first argument; it loads that checkout's own phase
scripts and pipeline (never this checkout's) and writes plain values to JSON:

* ``board``  -- the Phase 1/2 canonical board (``build_board``) and, with
  ``--trades``, Phase 1's own-league trade rows and census;
* ``finder`` -- the Phase 2 Trade Finder replay (``FR.run``) for ``--models``,
  tagged with that revision's v1 level (the re-measurement re-tags it on both bases).

It writes nothing inside either checkout and classifies no band itself.  Usage::

    git worktree add --detach <tmp>/old 79c322828
    cd <tmp>/old && python -I <this>/scripts/package_model_v2_remeasure_extract.py \\
        <tmp>/old board --trades --out <tmp>/board.json
    cd <tmp>/old && python -I <this>/scripts/package_model_v2_remeasure_extract.py \\
        <tmp>/old finder --models GEOM_78,KTC --out <tmp>/finder_a.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


def _load(old: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, old / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("old", type=Path, help="detached checkout of the recorded revision")
    ap.add_argument("mode", choices=["board", "finder"])
    ap.add_argument("--trades", action="store_true", help="board: also Phase 1's trade rows")
    ap.add_argument("--models", default="", help="finder: comma-separated model ids")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    old = args.old.resolve()
    assert not args.out.resolve().is_relative_to(old), "never write inside the old checkout"
    sys.path.insert(0, str(old))
    sys.path.insert(0, str(old / "scripts"))
    rev = subprocess.run(
        ["git", "-C", str(old), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(old), "status", "--porcelain", "--untracked-files=no"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    res: dict = {"revision": rev, "checkoutClean": not dirty, "mode": args.mode}
    if args.mode == "board":
        P1 = _load(old, "package_model_hybrid_research")
        board, prov = P1.latest_board()
        res.update({"prov": prov, "board": board})
        if args.trades:
            rows, census = P1.trade_rows(7.0)
            res.update({"tradeRows": rows, "tradeCensus": census})
    else:
        P2 = _load(old, "package_model_phase2_research")
        fr = _load(old, "package_model_finder_replay")
        raw = old / P2.P1.latest_board()[1]["rawPayload"]
        ids = [m for m in args.models.split(",") if m]
        res["replay"] = fr.run(board_raw_path=raw, models=P2.MODELS, model_ids=ids, level=P2.level)
    blob = json.dumps(res, default=str)
    args.out.write_text(blob, encoding="utf-8")
    print(json.dumps({"out": str(args.out), "sha256": hashlib.sha256(blob.encode()).hexdigest()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
