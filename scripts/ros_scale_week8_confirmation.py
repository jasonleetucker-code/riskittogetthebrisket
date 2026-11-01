#!/usr/bin/env python3
"""Frozen week-8 ROS calibration confirmation (read-only, research-only).

This is NOT an extension of the original weeks 5-7 preregistered gate and
does not promote a model. The exact fits committed by PR #2010 are loaded,
not refitted. All point outcomes are read only after the week is final.

Run from the repository root::

    python scripts/ros_scale_week8_confirmation.py
    python scripts/ros_scale_week8_confirmation.py --offline

Output: docs/league-intelligence/evidence/ros_scale_calibration/week8_confirmation.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import ros_scale_calibration_study as study_mod  # noqa: E402
from src.ros_calibration import conversion as cv  # noqa: E402

# The Git blob SHA of #2010's frozen fits, not an outcome-derived estimate.
# Changing the content intentionally requires independent review of this pin.
PINNED_FROZEN_BLOB = "cbed086e21deca852f8db9abf3ef1de26656158d"
FROZEN_PATH = (
    REPO
    / "docs"
    / "league-intelligence"
    / "evidence"
    / "ros_scale_calibration"
    / "fits_week8_frozen.json"
)
OUTPUT_PATH = study_mod.OUT_DIR / "week8_confirmation.json"


def git_blob_sha(contents: bytes) -> str:
    """Git's content-addressed blob checksum (sha1, distinct from file sha256)."""
    header = f"blob {len(contents)}\0".encode("ascii")
    return hashlib.sha1(header + contents).hexdigest()  # noqa: S324 — Git blob identity


def _refuse(message: str) -> None:
    raise study_mod.v1.StudyRefusal(message)


def load_frozen_models(
    path: Path = FROZEN_PATH, *, expected_blob: str = PINNED_FROZEN_BLOB
) -> tuple[dict[str, cv.ConversionModel], dict[str, str]]:
    """Load and validate preregistered model parameters without fitting anything."""
    raw_bytes = path.read_bytes()
    observed_blob = git_blob_sha(raw_bytes)
    if observed_blob != expected_blob:
        _refuse(f"frozen-fit Git blob changed: {observed_blob} != {expected_blob}")
    raw = json.loads(raw_bytes)
    if (
        raw.get("promotes") is not False
        or raw.get("preregistration") != study_mod.PREREGISTRATION
        or raw.get("fitWeeks") != list(study_mod.FINAL_FIT_WEEKS)
        or raw.get("confirmWeek") != study_mod.CONFIRM_WEEK
    ):
        _refuse("frozen-fit provenance, study weeks or research-only state changed")
    blocks = raw.get("models")
    if not isinstance(blocks, dict) or set(blocks) != set(study_mod.EVAL_MODELS):
        _refuse("frozen models differ from the preregistered model set")

    models: dict[str, cv.ConversionModel] = {}
    for model_id in study_mod.EVAL_MODELS:
        block = blocks[model_id]
        if not isinstance(block, dict) or set(block) != {"modelId", "fits"}:
            _refuse(f"invalid frozen model contract: {model_id}")
        if block["modelId"] != model_id or not isinstance(block["fits"], dict):
            _refuse(f"frozen model ID or fits invalid: {model_id}")
        if (model_id == "F") != (not block["fits"]):
            _refuse(f"unexpected empty/nonempty fits for {model_id}")
        fits: dict[str, cv.LinearFit] = {}
        for family, params in block["fits"].items():
            if family != "*" and family not in cv.FAMILIES:
                _refuse(f"unknown frozen family: {family}")
            if not isinstance(params, dict) or set(params) != {"a", "b", "n", "source"}:
                _refuse(f"invalid frozen fit fields: {model_id}/{family}")
            a, b, n, source = (params[k] for k in ("a", "b", "n", "source"))
            if (
                isinstance(a, bool)
                or isinstance(b, bool)
                or not isinstance(a, (int, float))
                or not isinstance(b, (int, float))
                or not math.isfinite(float(a))
                or not math.isfinite(float(b))
                or type(n) is not int
                or n < 1
                or not isinstance(source, str)
                or not source
            ):
                _refuse(f"invalid frozen fit coefficient: {model_id}/{family}")
            fits[family] = cv.LinearFit(
                a=float(a), b=float(b), n=n, source=source
            )
        model = cv.ConversionModel(model_id=model_id, fits=fits)
        if model.to_dict() != block:
            _refuse(f"frozen model failed lossless roundtrip: {model_id}")
        models[model_id] = model
    return models, {
        "gitBlobSha1": observed_blob,
        "fileSha256": hashlib.sha256(raw_bytes).hexdigest(),
    }


def run_confirmation(*, offline: bool = False) -> dict[str, Any]:
    """Confirm once against finalized week 8 without refitting or changing gates."""
    models, frozen_receipt = load_frozen_models()
    source = study_mod.Study(offline=offline)
    if not source.is_final(study_mod.CONFIRM_WEEK):
        _refuse(f"week {study_mod.CONFIRM_WEEK} is not final; no partial-week evaluation")
    wd = source.week(study_mod.CONFIRM_WEEK)

    reconciled_rows = [
        r for r in wd.rows if r.points is not None and r.host_points is not None
    ]
    if not reconciled_rows:
        _refuse("no comparable host-scored roster rows in confirmation week")
    mismatched = sum(
        abs(float(r.points) - float(r.host_points)) > 0.02
        for r in reconciled_rows
    )
    if mismatched:
        _refuse(f"host scoring does not reconcile: {mismatched} player-weeks")

    ev = study_mod.evaluate_week(source, study_mod.CONFIRM_WEEK, models)
    records = ev["records"]
    if not records:
        _refuse("no eligible as-of player-weeks in confirmation week")
    accuracy = study_mod.accuracy_block(records, study_mod.EVAL_MODELS)
    if accuracy["nScoredByEveryModel"] == 0:
        _refuse("no player-weeks were forecast by all frozen models")
    concordance = study_mod.concordance_block([ev], study_mod.EVAL_MODELS)
    teams = study_mod.team_block([ev], study_mod.EVAL_MODELS)
    payload: dict[str, Any] = {
        "status": "RESEARCH_EVIDENCE_NOT_FOR_PROMOTION",
        "promotes": False,
        "confirmationOnly": True,
        "retrainedOnConfirmationWeek": False,
        "week": study_mod.CONFIRM_WEEK,
        "trainingWeeks": list(study_mod.FINAL_FIT_WEEKS),
        "preregistration": study_mod.PREREGISTRATION,
        "frozenFits": frozen_receipt,
        "code": study_mod.v1.code_identity(),
        "cardFingerprint": source.fingerprint,
        "snapshot": wd.snapshot.relative_to(REPO).as_posix(),
        "snapshotSha256": study_mod.v1.sha256_file(wd.snapshot),
        "hostPointsReconciled": {
            "match": len(reconciled_rows),
            "of": len(reconciled_rows),
            "tolerance": 0.02,
        },
        "accuracy": accuracy,
        "crossGroupConcordance": concordance,
        "teamOrderingAndLineups": teams,
        "gates": {
            "status": "NOT_RERUN",
            "reason": (
                "A single confirmation week is independent evidence, not a replacement "
                "for the preregistered pooled gates. Team-week sample is insufficient "
                "for the original 36-team-week gate."
            ),
        },
        "networkCalls": source.f.network_calls,
    }
    study_mod.write_json(OUTPUT_PATH, payload)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="use cached external bodies")
    args = parser.parse_args(argv)
    try:
        result = run_confirmation(offline=args.offline)
    except (study_mod.v1.StudyRefusal, FileNotFoundError, ValueError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    accuracy = result["accuracy"]["byModel"]
    print(
        json.dumps(
            {
                "status": result["status"],
                "week": result["week"],
                "scored": result["accuracy"]["nScoredByEveryModel"],
                "mae": {key: row["mae"] for key, row in accuracy.items()},
                "gates": result["gates"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
