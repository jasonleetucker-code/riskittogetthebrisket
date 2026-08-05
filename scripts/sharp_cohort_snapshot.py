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

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO))

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


def verify_invariant(snapshot: dict[str, Any]) -> tuple[int, list[str]]:
    """Check the claim `sharp-v2.1` shipped on, from ONE snapshot.

    The before/after this was meant to be measured with is
    **unrecoverable**: v2.1 is already live, and nobody captured the
    pre-v2.1 cohort.  Carrying it as an owed measurement is carrying a
    debt that cannot be paid in the form stated.

    But the safety argument does not actually need a baseline.  It is:

        the absent component set is identical for every manager,
        so every score scales by the same factor,
        so the ORDER cannot move,
        and qualification is a percentile of the population,
        so the cohort cannot change.

    Every clause after the first follows from it, and the first is a
    property of a SINGLE population at a SINGLE instant: if every
    evaluable manager's ``weightsApplied`` map is identical, the
    renormalization multiplied every score by the same constant.  That
    is checkable right now, on prod, with no baseline at all.

    Returns ``(exit_code, lines)``.  Non-zero means the absent set is NOT
    uniform — the case where v2.1 could have reordered managers and the
    shipped claim would be false.
    """
    lines: list[str] = []
    scores = snapshot.get("scores", {})

    groups: dict[str, list[str]] = {}
    missing: list[str] = []
    for user_id, entry in scores.items():
        applied = entry.get("weightsApplied")
        if not isinstance(applied, dict) or not applied:
            missing.append(user_id)
            continue
        key = json.dumps({k: round(float(v), 9) for k, v in sorted(applied.items())})
        groups.setdefault(key, []).append(user_id)

    if missing:
        lines.append(
            f"{len(missing)} manager(s) carry no weightsApplied stamp — "
            "the renormalization is unauditable for them"
        )
        lines.append(f"  e.g. {', '.join(missing[:5])}")

    if not groups:
        lines.append("no manager carries a weightsApplied stamp; nothing to verify")
        return 1, lines

    lines.append(f"distinct weightsApplied maps across {len(scores)} managers: {len(groups)}")
    for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        weights = json.loads(key)
        total = sum(weights.values())
        lines.append(f"  {len(members):>5} manager(s), sum {total:.6f}: {weights}")

    if len(groups) == 1 and not missing:
        lines.append(
            "\nINVARIANT HOLDS: one absent-component set across the whole population, "
            "so every score scaled by the same factor and the ordering — hence the "
            "percentile-selected cohort — could not have moved."
        )
        return 0, lines

    lines.append(
        "\nINVARIANT VIOLATED: managers do NOT share one absent-component set, so "
        "renormalization scaled them by DIFFERENT factors and could have reordered "
        "them. The sharp-v2.1 safety claim does not hold on this population."
    )
    return 1, lines


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, help="write a snapshot to this path")
    ap.add_argument("--ledger", type=Path, default=None, help="override ledger path")
    ap.add_argument("--compare", type=Path, help="baseline snapshot to compare FROM")
    ap.add_argument("--against", type=Path, help="snapshot to compare TO (default: live)")
    ap.add_argument(
        "--daily",
        action="store_true",
        help="write data/sharp/cohort/snapshot_<utc-date>.json (used by the prod timer)",
    )
    ap.add_argument(
        "--verify-invariant",
        action="store_true",
        help="check the sharp-v2.1 uniform-scaling claim on ONE snapshot (no baseline needed)",
    )
    args = ap.parse_args()

    # The script owns its own filename, deliberately.  Putting
    # `snapshot_$(date -u +%Y-%m-%d).json` in the unit's ExecStart needs a
    # `/bin/sh -c` wrapper and systemd `%` escaping, and it breaks the
    # repo's rule — pinned by tests/deploy/test_all_timers_are_wired.py —
    # that every path in an ExecStart resolves to a file that exists.
    # Same reasoning as store.history_path owning the playerctx naming.
    if args.daily and not args.out:
        args.out = (
            _REPO
            / "data"
            / "sharp"
            / "cohort"
            / f"snapshot_{datetime.now(timezone.utc).date().isoformat()}.json"
        )

    if args.verify_invariant:
        snap = (
            json.loads(args.compare.read_text(encoding="utf-8"))
            if args.compare
            else build_snapshot(args.ledger)
        )
        if snap.get("population", {}).get("evaluable", 0) == 0:
            print(
                "no evaluable managers — the invariant is VACUOUS here, not verified.\n"
                "  Exit 2, because 'every manager in an empty set shares one weight map' "
                "is trivially true and proves nothing about production.",
                file=sys.stderr,
            )
            return 2
        code, lines = verify_invariant(snap)
        print("\n".join(lines))
        return code

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
        # The prod timer writes into data/sharp/cohort/, which does not
        # exist on a fresh box — a dated baseline lost to a missing
        # parent directory is a baseline that cannot be recovered later.
        args.out.parent.mkdir(parents=True, exist_ok=True)
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
