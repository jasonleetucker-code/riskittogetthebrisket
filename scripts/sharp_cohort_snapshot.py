#!/usr/bin/env python3
"""Snapshot the sharp cohort, and diff two snapshots.

Exists because a claim was shipped that could not be checked where it
was written.  ``sharp-v2.1`` renormalizes the scoring sum over the
components that have evidence, which RAISES every score — and the
argument that this is safe is that the absent component set is identical
for every manager, so all scores scale by the same factor, and
qualification is ``minScorePercentile`` (a percentile of the evaluable
population, not an absolute bar).  Ordering is preserved, therefore the
cohort is unchanged.

That argument is asserted on synthetic records in
``tests/sharp/test_score.py``.  It was NOT measured against the live
population, because the dev environment's ledger yields zero cohort
members — so the honest status was "owed, not done".  This makes paying
that debt one command on the box that has the data::

    # before deploying a scoring change
    python scripts/sharp_cohort_snapshot.py --out /tmp/cohort-before.json

    # after
    python scripts/sharp_cohort_snapshot.py --out /tmp/cohort-after.json
    python scripts/sharp_cohort_snapshot.py --compare /tmp/cohort-before.json \\
        --against /tmp/cohort-after.json

It computes nothing itself.  Records, scores and membership all come
from the canonical path — ``platform_records.build_manager_records`` →
``score.score_managers`` → ``cohort.cohort_members`` — because a second
implementation of "who is a sharp" is the thing ``cohort.py`` exists to
prevent.

Exit codes:
  0  snapshot written, or comparison ran and found no reordering
  1  comparison found the cohort or the ORDER changed (read the output)
  2  nothing to measure — no evaluable managers.  Deliberately NOT 0:
     "no data" must never read as "verified unchanged".
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.sharp import cohort as sharp_cohort  # noqa: E402
from src.sharp import platform_records  # noqa: E402
from src.sharp import score as sharp_score  # noqa: E402


def build_snapshot(ledger_path: Path | None = None) -> dict[str, Any]:
    records, evidence = platform_records.build_manager_records(ledger_path=ledger_path)
    scored = sharp_score.score_managers(records)
    members, coverage = sharp_cohort.cohort_members(ledger_path=ledger_path)

    evaluable = [s for s in scored if s.evaluable]
    # Rank by score descending.  user_id breaks ties so the ordering is
    # total and a diff cannot report a spurious reorder for two managers
    # who genuinely tie.
    ranked = sorted(evaluable, key=lambda s: (-(s.score or 0.0), s.user_id))

    return {
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "methodologyVersion": sharp_score.methodology_version(),
        "population": {
            "records": len(records),
            "evaluable": len(evaluable),
            "qualified": sum(1 for s in evaluable if s.qualified),
            "cohortMembers": len(members),
        },
        "evidence": evidence if isinstance(evidence, dict) else {},
        "coverage": coverage,
        # The ORDER is the artifact under test, so it is stored as a list.
        "ranking": [s.user_id for s in ranked],
        "scores": {
            s.user_id: {
                "score": s.score,
                "scorePercentile": s.score_percentile,
                "qualified": s.qualified,
                "weightsApplied": s.components.get("weightsApplied"),
            }
            for s in ranked
        },
        "cohort": sorted(m.manager_key for m in members),
    }


def compare(before: dict[str, Any], after: dict[str, Any]) -> tuple[int, list[str]]:
    """Return ``(exit_code, lines)``. Non-zero when membership or order moved."""
    lines: list[str] = []
    changed = False

    lines.append(
        f"methodologyVersion: {before.get('methodologyVersion')} -> "
        f"{after.get('methodologyVersion')}"
    )
    for key in ("records", "evaluable", "qualified", "cohortMembers"):
        b = before.get("population", {}).get(key)
        a = after.get("population", {}).get(key)
        flag = "" if b == a else "   <-- CHANGED"
        lines.append(f"  {key:>14}: {b} -> {a}{flag}")

    b_cohort, a_cohort = set(before.get("cohort", [])), set(after.get("cohort", []))
    entered, left = sorted(a_cohort - b_cohort), sorted(b_cohort - a_cohort)
    if entered or left:
        changed = True
        lines.append(f"\nCOHORT MEMBERSHIP CHANGED — {len(entered)} in, {len(left)} out")
        for m in entered:
            lines.append(f"  + {m}")
        for m in left:
            lines.append(f"  - {m}")
    else:
        lines.append(f"\ncohort membership unchanged ({len(a_cohort)} members)")

    # Ordering is compared over the managers present in BOTH snapshots.
    # Comparing raw lists would report a reorder whenever the population
    # merely grew, which is a different fact and is already reported above.
    common = [u for u in before.get("ranking", []) if u in set(after.get("ranking", []))]
    after_common = [u for u in after.get("ranking", []) if u in set(common)]
    if common != after_common:
        changed = True
        lines.append("\nORDER CHANGED among managers present in both snapshots:")
        for i, (b, a) in enumerate(zip(common, after_common)):
            if b != a:
                lines.append(f"  rank {i + 1}: {b} -> {a}")
    else:
        lines.append(f"order unchanged across {len(common)} shared managers")

    # Score movement is EXPECTED under a renormalization; it is reported
    # rather than judged.  A uniform ratio is the signature of the safety
    # argument holding; a spread means it does not.
    ratios = []
    for user_id, a_entry in after.get("scores", {}).items():
        b_entry = before.get("scores", {}).get(user_id)
        if not b_entry:
            continue
        b_score, a_score = b_entry.get("score"), a_entry.get("score")
        if b_score and a_score:
            ratios.append(a_score / b_score)
    if ratios:
        lo, hi = min(ratios), max(ratios)
        lines.append(
            f"\nscore ratio after/before over {len(ratios)} managers: "
            f"min {lo:.4f}, max {hi:.4f}, spread {hi - lo:.4f}"
        )
        lines.append(
            "  a spread near zero is the uniform-scaling the safety argument predicts; "
            "a wide spread means the absent component set was NOT uniform"
        )

    return (1 if changed else 0), lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="write a snapshot to this path")
    ap.add_argument("--ledger", type=Path, default=None, help="override ledger path")
    ap.add_argument("--compare", type=Path, help="baseline snapshot to compare FROM")
    ap.add_argument("--against", type=Path, help="snapshot to compare TO (default: live)")
    args = ap.parse_args()

    if args.compare:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        after = (
            json.loads(args.against.read_text(encoding="utf-8"))
            if args.against
            else build_snapshot(args.ledger)
        )
        code, lines = compare(before, after)
        print("\n".join(lines))
        return code

    snap = build_snapshot(args.ledger)
    if snap["population"]["evaluable"] == 0:
        print(
            "no evaluable managers — nothing to measure.\n"
            "  This is exit 2, not 0: an empty population cannot verify that a "
            "scoring change left the cohort alone.\n"
            f"  records seen: {snap['population']['records']}",
            file=sys.stderr,
        )
        return 2

    payload = json.dumps(snap, indent=1) + "\n"
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(payload)
    pop = snap["population"]
    print(
        f"  methodology {snap['methodologyVersion']}: "
        f"{pop['evaluable']} evaluable, {pop['qualified']} qualified, "
        f"{pop['cohortMembers']} cohort members",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
