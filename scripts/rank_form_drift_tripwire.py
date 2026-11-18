#!/usr/bin/env python3
"""Classify a rank-form drift verdict against the recorded accepted state.

``scripts/check_rank_form_drift.py`` answers "does the committed curve match
the board" and exits 2 on any drift.  The drift has been standing since
2026-08-18 (issue #898) awaiting an owner decision, so the weekly workflow was
permanently red and carried no information.  This module keeps the check
meaningful without pretending the drift is fixed:

* ``ok``       - the driver found no drift.
* ``accepted`` - drifted, but every drifted scope is recorded in
                 ``config/ci/rank_form_drift_accepted.json`` and no worse than
                 its accepted excess RMSE plus ``worseningMargin``.
* ``worse``    - a scope drifted that is not on the accepted list, or one got
                 worse than accepted + margin.  This FAILS the workflow.
* ``error``    - verdict or config unreadable.  This FAILS the workflow.

Exit codes: 0 ok / accepted, 1 error, 2 worse.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

DEFAULT_ACCEPTED = Path("config/ci/rank_form_drift_accepted.json")


def classify(verdict: dict[str, Any], accepted: dict[str, Any]) -> tuple[str, list[str]]:
    """Return ``(state, reasons)``."""
    drifted = list(verdict.get("drifted") or [])
    bad = [
        k
        for k, v in (verdict.get("scopes") or {}).items()
        if isinstance(v, dict)
        and isinstance(v.get("excessRmse"), (int, float))
        and not math.isfinite(v["excessRmse"])
    ]
    if bad:
        # A NaN/inf measurement is a broken verdict, whether or not it was flagged.
        return "error", [f"{k}: excessRmse is not finite" for k in bad]
    if not drifted:
        return "ok", []
    margin = float(accepted.get("worseningMargin", 0.0))
    known = accepted.get("scopes") or {}
    scopes = verdict.get("scopes") or {}
    reasons: list[str] = []
    errors: list[str] = []
    if not math.isfinite(margin):
        return "error", [f"worseningMargin is not finite ({margin!r})"]
    for scope in drifted:
        if scope not in known:
            reasons.append(f"{scope}: NEW drifted scope not in the accepted record")
            continue
        excess = (scopes.get(scope) or {}).get("excessRmse")
        base = float(known[scope]["acceptedExcessRmse"])
        if not math.isfinite(base):
            errors.append(f"{scope}: acceptedExcessRmse is not finite ({base!r})")
        elif excess is None:
            reasons.append(f"{scope}: drifted but excessRmse missing from verdict")
        elif not math.isfinite(float(excess)):
            # NaN compares False to everything: it must never read as "not worse".
            errors.append(f"{scope}: excessRmse is not finite ({excess!r})")
        elif float(excess) > base + margin:
            reasons.append(
                f"{scope}: excess RMSE {float(excess):.1f} > accepted {base:.1f} + margin {margin:.1f}"
            )
    if errors:
        return "error", errors + reasons
    return ("worse" if reasons else "accepted"), reasons


def _summary(
    state: str, reasons: list[str], verdict: dict[str, Any], accepted: dict[str, Any]
) -> str:
    lines = [f"### Rank-form drift tripwire: `{state}`", ""]
    if state == "accepted":
        lines += [
            "**Standing drift, NOT fixed.** The committed rank-form constants still "
            "do not match the board; this is the recorded accepted state, so the run is green.",
            "",
            f"- **Pending owner decision:** {accepted.get('pendingOwnerDecision')}",
            f"- Reference: {accepted.get('decisionReference')}",
            f"- Accepted state recorded {accepted.get('recordedAt')} "
            f"(margin {accepted.get('worseningMargin')} excess RMSE; going beyond it fails this check).",
        ]
    elif state == "worse":
        lines += ["**Drift is NEW or WORSE than the accepted state.**", ""]
        lines += [f"- {r}" for r in reasons]
    elif state == "ok":
        lines += ["Committed constants reproduce the board within budget."]
    else:
        lines += [f"Check errored: {'; '.join(reasons)}"]
    for scope, entry in (verdict.get("scopes") or {}).items():
        if "excessRmse" in entry:
            lines.append(
                f"- {scope}: excess RMSE {entry['excessRmse']} (drifted={entry['drifted']})"
            )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verdict", type=Path, required=True)
    parser.add_argument("--accepted", type=Path, default=DEFAULT_ACCEPTED)
    args = parser.parse_args(argv)
    try:
        verdict = json.loads(args.verdict.read_text(encoding="utf-8"))
        accepted = json.loads(args.accepted.read_text(encoding="utf-8"))
        state, reasons = classify(verdict, accepted)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        verdict, accepted, state, reasons = {}, {}, "error", [f"{type(exc).__name__}: {exc}"]
    text = _summary(state, reasons, verdict, accepted)
    print(text)
    for target, body in (("GITHUB_STEP_SUMMARY", text), ("GITHUB_OUTPUT", f"state={state}\n")):
        path = os.environ.get(target)
        if path:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(body)
    if state == "accepted":
        print(
            "::warning title=Rank-form drift is a STANDING accepted condition::"
            "constants still stale; owner decision pending (issue #898). Not fixed."
        )
    if state == "worse":
        print(f"::error title=Rank-form drift worsened::{'; '.join(reasons)}")
    return {"ok": 0, "accepted": 0, "worse": 2}.get(state, 1)


if __name__ == "__main__":
    sys.exit(main())
