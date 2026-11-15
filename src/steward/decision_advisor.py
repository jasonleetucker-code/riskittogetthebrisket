"""Offline, report-only typed decision shadow for Steward task profiles.

The deterministic router remains authoritative. This module reads a candidate
answer from a file; it never invokes a model, changes policy, or grants access.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re

from .routing import PROFILES, classify

SCHEMA_VERSION = "steward-decision/v1"
PROFILE_LABELS = (*PROFILES, "needs_system2")
MAX_INPUT_BYTES = 64 * 1024
OPAQUE_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")
ANSWER_FIELDS = frozenset(
    {
        "schema_version",
        "decision_id",
        "question_id",
        "question_type",
        "candidate_labels",
        "selected_label",
        "distribution",
        "abstained",
        "provider",
        "model",
        "model_version",
        "raw_confidence",
        "calibrated_probability",
        "latency_ms",
        "cost_usd",
        "evaluation_mode",
    }
)


def _measurement(value: object, *, maximum: float | None = None) -> bool:
    return value is None or (
        type(value) in {int, float}
        and math.isfinite(value)
        and value >= 0
        and (maximum is None or value <= maximum)
    )


def validate_profile_answer(answer: dict) -> None:
    """Validate one low-authority choice; never accept permission questions."""
    if not isinstance(answer, dict) or set(answer) != ANSWER_FIELDS:
        raise ValueError("typed answer fields differ from the shadow contract")
    if (
        answer["schema_version"] != SCHEMA_VERSION
        or answer["question_id"] != "task_profile"
        or answer["question_type"] != "CHOICE"
        or answer["evaluation_mode"] != "SHADOW"
        or answer["candidate_labels"] != list(PROFILE_LABELS)
    ):
        raise ValueError("shadow accepts only the task_profile choice question")
    if not isinstance(answer["decision_id"], str) or not OPAQUE_ID.fullmatch(answer["decision_id"]):
        raise ValueError("decision_id must be a bounded opaque identifier")
    if answer["selected_label"] not in PROFILE_LABELS or type(answer["abstained"]) is not bool:
        raise ValueError("selected label or abstention is invalid")
    if answer["abstained"] != (answer["selected_label"] == "needs_system2"):
        raise ValueError("needs_system2 must abstain; other labels must not")
    distribution = answer["distribution"]
    if not isinstance(distribution, dict) or set(distribution) != set(PROFILE_LABELS):
        raise ValueError("distribution must cover exactly the candidate labels")
    if not all(
        _measurement(value, maximum=1) and value is not None for value in distribution.values()
    ):
        raise ValueError("distribution has an invalid probability")
    if not math.isclose(sum(distribution.values()), 1.0, rel_tol=0, abs_tol=1e-6):
        raise ValueError("distribution probabilities must sum to one")
    if not answer["abstained"] and distribution[answer["selected_label"]] < max(
        distribution.values()
    ):
        raise ValueError("selected label must have maximal distribution mass")
    if answer["calibrated_probability"] is not None:
        raise ValueError("uncalibrated shadow answers cannot claim calibrated probability")
    for key, maximum in (("raw_confidence", 1), ("latency_ms", None), ("cost_usd", None)):
        if not _measurement(answer[key], maximum=maximum):
            raise ValueError(f"{key} must be a finite nonnegative measurement or null")
    for key in ("provider", "model", "model_version"):
        value = answer[key]
        if value is not None and (
            not isinstance(value, str) or not value or len(value) > 100 or not value.isprintable()
        ):
            raise ValueError(f"{key} must be bounded attribution or null")


def shadow_profile(task: dict, answer: dict | None = None) -> dict:
    """Compare a candidate to the current deterministic profile with no effect."""
    if not isinstance(task, dict):
        raise ValueError("task must be an object")
    for field in ("security_risk", "cross_system", "mechanical", "conflicting_evidence"):
        if field in task and type(task[field]) is not bool:
            raise ValueError(f"task.{field} must be a boolean")
    if "unresolved_failures" in task and (
        type(task["unresolved_failures"]) is not int or task["unresolved_failures"] < 0
    ):
        raise ValueError("task.unresolved_failures must be a nonnegative integer")
    for field in ("production_risk", "ambiguity"):
        if field in task and (
            not isinstance(task[field], str) or task[field] not in {"low", "normal", "high"}
        ):
            raise ValueError(f"task.{field} is not a known level")
    baseline = classify(task)
    if answer is not None:
        validate_profile_answer(answer)
    return {
        "schema_version": "steward-profile-shadow/v1",
        "task_id": task.get("id")
        if isinstance(task.get("id"), str) and OPAQUE_ID.fullmatch(task["id"])
        else None,
        "question_id": "task_profile",
        "baseline_profile": baseline,
        "advisor_label": answer["selected_label"] if answer is not None else None,
        "abstained": answer["abstained"] if answer is not None else None,
        "disagreed": answer["selected_label"] != baseline
        if answer is not None and not answer["abstained"]
        else None,
        "raw_confidence": answer["raw_confidence"] if answer is not None else None,
        "calibrated_probability": None,
        "cost_usd_declared": answer["cost_usd"] if answer is not None else None,
        "decision_id": answer["decision_id"] if answer is not None else None,
        "authority": "A_REPORT_ONLY",
        "effect": "NONE",
        "provider_called": False,
    }


def _read_json(path: Path) -> dict:
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("shadow input exceeds size limit")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("shadow input must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", type=Path, required=True)
    parser.add_argument("--advisor-answer", type=Path)
    args = parser.parse_args(argv)
    try:
        task = _read_json(args.task)
        answer = _read_json(args.advisor_answer) if args.advisor_answer else None
        result = shadow_profile(task, answer)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
