#!/usr/bin/env python3
"""LOCAL reproducibility demonstration for the Hill training substrate repair.

Never records a challenger, never promotes, never touches a live constant.

1. Two replays of the same pins (every input materialized from git at one
   commit, cutoff = that commit's time) -> identical challenger hashes.
2. The CI path (a working-tree refit at HEAD, ``--require-reproducible``) and a
   replay of THAT run's own recorded pins -> identical challenger hashes.
3. Two point-in-time replays at a past cutoff -> identical hashes, and the
   resolved commit, snapshot scrape time and dataset clocks are all at or before
   the cutoff (the run refuses anything later).

    python docs/valuation/evidence/hill-trainer-repair-2026-10-01/reproduce_demo.py \
        --out docs/valuation/evidence/hill-trainer-repair-2026-10-01/demo.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))

from scripts.auto_refit_hill_curves import run_training  # noqa: E402
from src.model_registry.training_run import replay  # noqa: E402

PIT_CUTOFF = "2026-09-29T00:00:00+00:00"


def _summary(run) -> dict:
    r = run.record
    return {
        "challengerHash": run.challenger_hash,
        "pinsHash": r["pinsHash"],
        "modelHash": r["modelHash"],
        "codeHash": r["codeHash"],
        "manifestHash": r["manifestHash"],
        "inputsOrigin": r["inputsOrigin"],
        "trainingCutoff": r["trainingCutoff"],
        "reproducible": r["reproducible"],
        "snapshot": r["snapshot"],
        "params": run.params,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    work = run_training(require_reproducible=True)
    rec = work.record
    head_a = replay(commit=rec["inputsCommit"])
    head_b = replay(commit=rec["inputsCommit"])
    of_work = replay(
        commit=rec["inputsCommit"],
        cutoff=datetime.fromisoformat(rec["trainingCutoff"]),
        snapshot_rel=rec["snapshot"]["path"],
    )
    pit_a = replay(cutoff=datetime.fromisoformat(PIT_CUTOFF))
    pit_b = replay(cutoff=datetime.fromisoformat(PIT_CUTOFF))

    cut = datetime.fromisoformat(PIT_CUTOFF)
    clocks = [
        pin["datasetState"].get("lastAnyMeaningfulChangeAt")
        for pin in pit_a.record["inputs"].values()
        if pin["datasetState"].get("measured")
    ]
    latest_clock = max(
        (datetime.fromisoformat(c.replace("Z", "+00:00")) for c in clocks if c), default=None
    )
    blob = {
        "label": "LOCAL",
        "headCommit": rec["inputsCommit"],
        "1_twoReplaysOfOnePinSet": {
            "a": _summary(head_a),
            "b": _summary(head_b),
            "identical": head_a.challenger_hash == head_b.challenger_hash,
        },
        "2_ciPathEqualsReplayOfItsOwnPins": {
            "worktree": _summary(work),
            "replay": _summary(of_work),
            "identical": work.challenger_hash == of_work.challenger_hash,
        },
        "3_pointInTime": {
            "cutoff": PIT_CUTOFF,
            "resolvedCommit": pit_a.record["inputsCommit"],
            "a": _summary(pit_a),
            "b": _summary(pit_b),
            "identical": pit_a.challenger_hash == pit_b.challenger_hash,
            "snapshotScrapedAtOrBeforeCutoff": datetime.fromisoformat(
                pit_a.record["snapshot"]["scrapeTimestamp"]
            )
            <= cut,
            "latestDatasetClock": None if latest_clock is None else latest_clock.isoformat(),
            "datasetClocksAtOrBeforeCutoff": latest_clock is None or latest_clock <= cut,
        },
        "offenseKtcInputAtHead": rec["inputs"]["CSVs/site_raw/ktc.csv"],
        "offenseScopeAtHead": rec["scopes"]["OFFENSE"],
        "perSourceFitsAtHead": rec["perSourceFits"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(blob, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                k: v.get("identical")
                for k, v in blob.items()
                if isinstance(v, dict) and "identical" in v
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
