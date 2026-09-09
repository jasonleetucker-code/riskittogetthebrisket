#!/usr/bin/env python3
"""Adjudicate the Hill candidate tournament and emit an auto-promotion plan.

The two-hour refit is allowed to create evidence.  This script is the
separate state-change gate: it re-scores every standing challenger and the
champion on the SAME current inputs, selects the best stable candidate, then
checks forward snapshots from git history that occurred after that candidate
was fitted.

If READY, the emitted params change OFFENSE only. GLOBAL/IDP/ROOKIE remain
the incumbent values until those scopes have their own promotable evidence.

Exit codes:
  0  not ready; champion stays
  10 ready; caller may run register -> validate -> board guard -> promote -> apply
  2  evaluation error
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.model_registry.autopilot import (  # noqa: E402
    AutopilotPolicy,
    CandidateScore,
    ForwardScore,
    compose_offense_only,
    decide,
)
from src.model_registry.hill_masters import load_or_seed_registry  # noqa: E402
from src.model_registry.holdout import (  # noqa: E402
    OFFENSE_HOLDOUT_SOURCES,
    HoldoutError,
    evaluate_offense_master,
)

POLICY_PATH = REPO / "config" / "model_registry" / "hill_autopilot_policy.json"
RUN_LOG = REPO / "config" / "model_registry" / "hill_autopilot_runs.jsonl"


def _policy() -> tuple[AutopilotPolicy, dict[str, Any]]:
    raw = json.loads(POLICY_PATH.read_text())
    return (
        AutopilotPolicy(
            min_current_improvement_points=float(raw["minCurrentImprovementPoints"]),
            min_current_improvement_fraction=float(raw["minCurrentImprovementFraction"]),
            min_improved_boards=int(raw["minImprovedBoards"]),
            max_board_worsening_fraction=float(raw["maxBoardWorseningFraction"]),
            min_rows_per_board=int(raw["minRowsPerBoard"]),
            stable_candidates_required=int(raw["stableCandidatesRequired"]),
            stable_span_days=float(raw["stableSpanDays"]),
            candidate_criterion_band_fraction=float(raw["candidateCriterionBandFraction"]),
            c_relative_tolerance=float(raw["cRelativeTolerance"]),
            s_relative_tolerance=float(raw["sRelativeTolerance"]),
            forward_days_required=int(raw["forwardDaysRequired"]),
            forward_win_rate_required=float(raw["forwardWinRateRequired"]),
            forward_median_improvement_points=float(raw["forwardMedianImprovementPoints"]),
        ),
        raw,
    )


def _dt(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime(1970, 1, 1, tzinfo=timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _score_version(version) -> CandidateScore:
    result = evaluate_offense_master(
        float(version.params["HILL_PERCENTILE_C"]),
        float(version.params["HILL_PERCENTILE_S"]),
    )
    return CandidateScore(
        version=version.version,
        c=float(version.params["HILL_PERCENTILE_C"]),
        s=float(version.params["HILL_PERCENTILE_S"]),
        criterion=float(result.criterion),
        per_source=dict(result.per_source),
        per_source_rows=dict(result.per_source_rows),
        fitted_at=version.fitted_at,
        status=version.status,
        training_inputs=dict(version.training_inputs),
    )


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc.stdout


def _historical_commits_after(fitted_at: str, *, max_days: int = 30) -> list[tuple[str, str, str]]:
    fitted = _dt(fitted_at)
    paths = [p for p, _ in OFFENSE_HOLDOUT_SOURCES.values()]
    text = _git(
        "log",
        f"--since={fitted.isoformat()}",
        "--format=%H%x09%cI",
        "--",
        *paths,
    )
    by_day: dict[str, tuple[str, str, str]] = {}
    for line in text.splitlines():
        if not line.strip() or "\t" not in line:
            continue
        sha, stamp = line.split("\t", 1)
        when = _dt(stamp)
        # A candidate is selected on the board available at fit time. Only
        # later UTC dates count as forward evidence; same-day rescrapes are
        # not independent future observations.
        if when.date() <= fitted.date():
            continue
        day = when.date().isoformat()
        if day not in by_day:
            by_day[day] = (sha, stamp, day)
    rows = sorted(by_day.values(), key=lambda x: x[2])
    return rows[-max_days:]


def _write_historical_root(root: Path, sha: str) -> None:
    for _label, (rel, _column) in OFFENSE_HOLDOUT_SOURCES.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_git("show", f"{sha}:{rel}"), encoding="utf-8")


def _forward_scores(
    champ, winner: CandidateScore
) -> tuple[list[ForwardScore], list[dict[str, Any]]]:
    out: list[ForwardScore] = []
    details: list[dict[str, Any]] = []
    commits = _historical_commits_after(winner.fitted_at)
    for sha, stamp, day in commits:
        try:
            with tempfile.TemporaryDirectory(prefix="hill-forward-") as td:
                root = Path(td)
                _write_historical_root(root, sha)
                ce = evaluate_offense_master(
                    float(champ.params["HILL_PERCENTILE_C"]),
                    float(champ.params["HILL_PERCENTILE_S"]),
                    repo_root=root,
                )
                we = evaluate_offense_master(winner.c, winner.s, repo_root=root)
        except (RuntimeError, HoldoutError, OSError, csv.Error):
            continue
        out.append(
            ForwardScore(
                label=day,
                champion_criterion=float(ce.criterion),
                candidate_criterion=float(we.criterion),
            )
        )
        details.append(
            {
                "date": day,
                "commit": sha,
                "commitTime": stamp,
                "championCriterion": round(ce.criterion, 4),
                "candidateCriterion": round(we.criterion, 4),
                "improvement": round(ce.criterion - we.criterion, 4),
                "rows": dict(we.per_source_rows),
            }
        )
    return out, details


def _recent_row_health(
    current: dict[str, int], max_drop_fraction: float
) -> tuple[bool, dict[str, Any]]:
    """Compare this run's holdout depth with recent successful observations."""
    if not RUN_LOG.exists():
        return True, {}
    history: list[dict[str, Any]] = []
    for line in RUN_LOG.read_text(encoding="utf-8").splitlines()[-24:]:
        try:
            blob = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows = blob.get("currentRows")
        if isinstance(rows, dict):
            history.append(rows)

    detail: dict[str, Any] = {}
    ok = True
    for src, now in current.items():
        prior = [
            int(rows[src])
            for rows in history
            if src in rows and isinstance(rows[src], (int, float))
        ]
        if len(prior) < 3:
            continue
        baseline = float(median(prior))
        floor = baseline * (1.0 - max_drop_fraction)
        source_ok = float(now) >= floor
        detail[src] = {
            "current": int(now),
            "recentMedian": baseline,
            "minimumAllowed": floor,
            "pass": source_ok,
        }
        ok = ok and source_ok
    return ok, detail


def _append_log(blob: dict[str, Any]) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(blob, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True, help="write the full plan JSON")
    ap.add_argument("--params-out", type=Path, required=True, help="write safe composed params")
    ap.add_argument("--record", action="store_true", help="append this adjudication to the run log")
    ap.add_argument("--trigger-sha", default="", help="data-refresh SHA that caused this run")
    args = ap.parse_args()

    policy, raw_policy = _policy()
    reg = load_or_seed_registry()
    champ = reg.champion

    try:
        champ_eval = evaluate_offense_master(
            float(champ.params["HILL_PERCENTILE_C"]),
            float(champ.params["HILL_PERCENTILE_S"]),
        )
        scores = [_score_version(v) for v in reg.versions if v.status == "challenger"]
    except (HoldoutError, KeyError, ValueError) as exc:
        print(
            f"ERROR: current tournament could not be evaluated: {exc}",
            file=sys.stderr,
        )
        return 2

    fitted_days = {c.version: _dt(c.fitted_at).timestamp() / 86400.0 for c in scores}
    provisional = min(
        (
            c
            for c in scores
            if c.status == "challenger"
            and c.training_inputs
            and all(v != "missing" for v in c.training_inputs.values())
        ),
        key=lambda c: (c.criterion, -c.version),
        default=None,
    )

    forward: list[ForwardScore] = []
    forward_details: list[dict[str, Any]] = []
    if provisional is not None:
        forward, forward_details = _forward_scores(champ, provisional)

    row_health_ok, row_health_detail = _recent_row_health(
        dict(champ_eval.per_source_rows),
        float(raw_policy.get("maxRowDropFromRecentMedianFraction", 0.15)),
    )

    decision = decide(
        champion_criterion=float(champ_eval.criterion),
        champion_per_source=dict(champ_eval.per_source),
        candidates=scores,
        fitted_span_days=fitted_days,
        forward_scores=forward,
        policy=policy,
        recent_row_health_ok=row_health_ok,
    )

    winner = next((c for c in scores if c.version == decision.winner_version), None)
    params = compose_offense_only(champ.params, winner) if winner else dict(champ.params)
    args.params_out.parent.mkdir(parents=True, exist_ok=True)
    args.params_out.write_text(json.dumps(params, indent=2, sort_keys=True) + "\n")

    now = datetime.now(timezone.utc).isoformat()
    plan = {
        "schemaVersion": 1,
        "evaluatedAt": now,
        "triggerSha": args.trigger_sha or None,
        "championVersion": champ.version,
        "championCriterion": round(champ_eval.criterion, 4),
        "championPerSource": {k: round(v, 4) for k, v in sorted(champ_eval.per_source.items())},
        "currentRows": dict(champ_eval.per_source_rows),
        "rowHealthDetail": row_health_detail,
        "winnerVersion": decision.winner_version,
        "ready": decision.ready,
        "reason": decision.reason,
        "gates": dict(decision.gates),
        "requiredImprovement": round(decision.required_improvement, 4),
        "currentImprovement": (
            round(decision.current_improvement, 4)
            if decision.current_improvement is not None
            else None
        ),
        "stableVersions": list(decision.stable_versions),
        "forwardDays": decision.forward_days,
        "forwardWinRate": decision.forward_win_rate,
        "forwardMedianImprovement": decision.forward_median_improvement,
        "forwardEvidence": forward_details,
        "safePromotionScope": ["OFFENSE"] if winner else [],
        "composedParams": params,
        "tournament": [
            {
                "version": c.version,
                "criterion": round(c.criterion, 4),
                "c": c.c,
                "s": c.s,
                "fittedAt": c.fitted_at,
                "rows": dict(c.per_source_rows),
                "perSource": {k: round(v, 4) for k, v in sorted(c.per_source.items())},
            }
            for c in sorted(scores, key=lambda x: (x.criterion, -x.version))
        ],
        "policy": raw_policy,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    if args.record:
        _append_log(plan)

    print(
        f"Hill autopilot: {'READY' if decision.ready else 'HOLD'} "
        f"winner=v{decision.winner_version} — {decision.reason}"
    )
    if decision.current_improvement is not None:
        print(
            f"current improvement {decision.current_improvement:.1f}; "
            f"required {decision.required_improvement:.1f}"
        )
    print(
        f"stable={list(decision.stable_versions)} "
        f"forwardDays={decision.forward_days} "
        f"forwardWinRate={decision.forward_win_rate}"
    )
    return 10 if decision.ready else 0


if __name__ == "__main__":
    raise SystemExit(main())
