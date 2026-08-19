#!/usr/bin/env python3
"""Champion/challenger pass on the Meaningful Roster Core multiplier M.

``docs/MATH_MODEL_CALIBRATION_POLICY_2026-08-15.md`` §4.3 keeps
``ceil(1.5 x starter demand)`` as the approved V1 champion and requires
a challenger pass before it may be frozen as canonical long-term
methodology:

    - 1.25x starter demand;
    - 1.50x starter demand;
    - 1.75x starter demand;
    - a data-derived marginal-value / replacement-impact cutoff.

    Evaluate stability across league formats and whether the selected
    core matches the assets that meaningfully drive roster strength.
    Do not tune merely until a few hand-picked rosters "look right."

EVALUATION IS NOT ACTIVATION.  This script promotes nothing, writes no
config and changes no published number.  ``config/roster_intel/
meaningful_core.json`` keeps ``reserveMultiplier: 1.5`` whatever it
prints, per the repo's champion/challenger rule that nothing
self-promotes.  Promoting M is a human decision on this evidence.

What "meaningfully drive roster strength" is measured AS
========================================================

The vague half of the requirement is the important half, so it is made
explicit rather than left to judgement.

Reserve demand exists for **resilience**, not for this week's lineup: a
bench player contributes nothing to the optimal lineup while everyone is
healthy, which is precisely why "marginal contribution to the starting
lineup" is the wrong statistic and would return M = 1.0 for every league.

So a core is scored by how much of the FULL roster's resilience it
retains:

    resilience(S, k) = mean over k-subsets A of starters
                       of optimal_score(S \\ A, slots)

i.e. the average lineup you can still field when *k* starters are
unavailable at once, computed with the canonical exact solver over the
real slot list.  ``retention = resilience(core, k) / resilience(full, k)``.

**k > 1 is load-bearing, and the first version of this script got it
wrong.**  At k = 1 the statistic is degenerate: one absence needs at
most one replacement, so retention reads exactly 100.00% for every
candidate *including M = 1.01*, and a constant cannot discriminate
between them.  That is the same failure mode
``tests/roster_intel/test_real_rosters.py`` records for
``_positional_coverage`` — "a constant masquerading as a score" — and it
is reported here rather than quietly dropped, because a metric that
cannot separate the candidates is evidence about the metric.  Reserve
depth exists for injury AND bye AND bust in the same week, so k = 2 and
k = 3 are the loads it is actually for.

k = 1 and k = 2 are exhaustive over all subsets; k = 3 is a deterministic
seeded sample (the exhaustive count is 1,330 per team per candidate),
seeded so the number does not drift between runs.

The **data-derived cutoff** is then the smallest M on a fine grid whose
core retains at least ``--target`` of full-roster resilience on EVERY
team at the deepest k measured — a threshold on the outcome, not a tuned
parameter.

Stability across formats is measured by re-running every candidate
against slot-list variants of the same real rosters (IDP removed,
Superflex removed, both), because a multiplier that is only right for
one league's shape is not canonical methodology.

Exit codes:  0 evidence produced * 1 a candidate could not be evaluated
* 2 no board.  ``2`` is deliberately distinct: "no data" must never read
as "the champion held", the same rule
``scripts/backtest_perfect_draft.py`` sets for a blocked backtest.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import statistics
import sys
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from src.api.data_contract import contract_roster_pools  # noqa: E402
from src.roster_intel.core import build_meaningful_core, reserve_demand  # noqa: E402
from src.roster_intel.marginal import optimal_score  # noqa: E402
from src.roster_intel.strength import build_team_strength, rank_team_strengths  # noqa: E402
from src.ros.lineup import assign_lineup  # noqa: E402

#: Slot-list variants of the same real rosters.  Named for what they
#: remove, and each is a shape a real dynasty league actually uses.
_IDP_SLOTS = {"DL", "LB", "DB", "IDP_FLEX"}


def _format_variants(slots: Sequence[str]) -> dict[str, list[str]]:
    base = [str(s) for s in slots]
    return {
        "live": base,
        "no_idp": [s for s in base if s.upper() not in _IDP_SLOTS],
        "no_superflex": [s for s in base if s.upper() != "SUPER_FLEX"],
        "offense_1qb": [
            s for s in base if s.upper() not in _IDP_SLOTS and s.upper() != "SUPER_FLEX"
        ],
    }


#: How many simultaneous starter absences to sample at k = 3, where the
#: exhaustive count (1,330 per team per candidate) is impractical.
_K3_SAMPLES = 120


def _absence_sets(starter_ids: Sequence[str], k: int) -> list[tuple[str, ...]]:
    """All k-subsets, or a DETERMINISTIC sample when there are too many.

    Seeded, because a resilience number that drifts between runs cannot
    be compared across candidates — which is the entire point of the
    exercise.
    """
    if k <= 2:
        return list(itertools.combinations(starter_ids, k))
    rng = random.Random(20260818)
    everything = list(itertools.combinations(starter_ids, k))
    if len(everything) <= _K3_SAMPLES:
        return everything
    return rng.sample(everything, _K3_SAMPLES)


def _resilience(pool: Sequence[Any], slots: Sequence[str], k: int) -> float | None:
    """Mean optimal score with *k* starters removed at once.

    ``None`` when no starter can be seated at all — an unmeasured
    resilience, never a resilience of zero.
    """
    if not slots:
        return None
    lineup = assign_lineup(list(pool), list(slots))
    starter_ids = sorted(p.player_id for p in lineup.assignments.values())
    if len(starter_ids) < k:
        return None
    scores = []
    for absent in _absence_sets(starter_ids, k):
        gone = set(absent)
        survivors = [p for p in pool if p.player_id not in gone]
        scores.append(optimal_score(survivors, list(slots)))
    return statistics.fmean(scores) if scores else None


def _core_ids(pool, slots, multiplier: float) -> set[str]:
    core = build_meaningful_core(pool, slots, config={"reserveMultiplier": multiplier})
    return set(core.core_ids)


def _evaluate(pools, slots, multiplier: float, ks: Sequence[int]) -> dict[str, Any]:
    sizes: list[int] = []
    retentions: dict[int, list[float]] = {k: [] for k in ks}
    for pool in pools.values():
        ids = _core_ids(pool, slots, multiplier)
        core_pool = [p for p in pool if p.player_id in ids]
        sizes.append(len(ids))
        for k in ks:
            full = _resilience(pool, slots, k)
            got = _resilience(core_pool, slots, k)
            if full and full > 0 and got is not None:
                retentions[k].append(got / full)
    demand = reserve_demand(slots, config={"reserveMultiplier": multiplier})
    return {
        "multiplier": multiplier,
        "ceiling": len(slots) + demand.total(),
        "meanCoreSize": statistics.fmean(sizes) if sizes else None,
        "byK": {
            k: {
                "meanRetention": statistics.fmean(v) if v else None,
                "minRetention": min(v) if v else None,
                "teamsBelowTarget": None,
            }
            for k, v in retentions.items()
        },
    }


def _strength_order(pools, slots, multiplier: float) -> list[str]:
    ranked = rank_team_strengths(
        {
            oid: build_team_strength(
                build_meaningful_core(pool, slots, config={"reserveMultiplier": multiplier})
            )
            for oid, pool in pools.items()
        }
    )
    return [oid for oid, _ in sorted(ranked.items(), key=lambda kv: kv[1].league_rank or 999)]


def _load_contract(path: str | None):
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8")), path
    from tests.archive_fixtures import newest_complete_raw_payload

    raw, name = newest_complete_raw_payload()
    if raw is None:
        return None, "none"
    from src.api.data_contract import build_api_data_contract

    return build_api_data_contract(raw), name or "archive"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--contract", help="path to a built contract JSON")
    ap.add_argument(
        "--targets",
        type=float,
        nargs="+",
        default=[0.99, 0.999, 0.9999, 1.0],
        help=(
            "resilience-retention targets the data-derived cutoff must reach on EVERY "
            "team. Several, because a single line hides how sensitive the answer is"
        ),
    )
    ap.add_argument(
        "--absences",
        default="1,2,3",
        help=(
            "simultaneous starter absences to measure. k=1 is DEGENERATE and kept "
            "only so the degeneracy stays visible in the output"
        ),
    )
    ap.add_argument("--json", help="write the full evidence table here")
    args = ap.parse_args()

    contract, source = _load_contract(args.contract)
    if contract is None:
        print("[core-M] NO BOARD AVAILABLE — cannot evaluate. Exit 2.")
        print("[core-M] 'no data' is not 'the champion held'.")
        return 2

    pools, slots, slot_source = contract_roster_pools(dict(contract))
    if not pools or not slots:
        print("[core-M] contract carries no rosters or no slots. Exit 2.")
        return 2

    print(f"[core-M] source={source} teams={len(pools)} slots={len(slots)} ({slot_source})")
    print("[core-M] EVALUATION ONLY — this script promotes nothing and writes no config.\n")

    candidates = [1.25, 1.50, 1.75]
    ks = [int(k) for k in args.absences.split(",") if k.strip()]
    variants = _format_variants(slots)
    evidence: dict[str, Any] = {"source": source, "targets": args.targets, "formats": {}}
    failures: list[str] = []

    for fmt, fmt_slots in variants.items():
        if not fmt_slots:
            failures.append(f"{fmt}: variant has no slots")
            continue
        print(f"── format {fmt} ({len(fmt_slots)} slots) " + "─" * (34 - len(fmt)))
        header = "".join(f"{'k=' + str(k):>18}" for k in ks)
        print(f"{'M':>6}{'ceiling':>9}{'coreSize':>10}{header}")
        rows = []
        for m in candidates:
            row = _evaluate(pools, fmt_slots, m, ks)
            rows.append(row)
            cells = ""
            for k in ks:
                stats = row["byK"][k]
                if stats["meanRetention"] is None:
                    cells += f"{'unmeasured':>18}"
                    failures.append(f"{fmt}: M={m} k={k} produced no measurable retention")
                else:
                    cells += (
                        f"{stats['meanRetention'] * 100:>11.2f}%"
                        f"{stats['minRetention'] * 100:>6.1f}"
                    )
            print(f"{m:>6.2f}{row['ceiling']:>9}{row['meanCoreSize']:>10.1f}{cells}")
        print("   (each cell: mean retention %, worst team)")

        # Data-derived cutoff: smallest M on a fine grid clearing a target
        # on EVERY team at the DEEPEST k measured.  A threshold on the
        # OUTCOME, not a tuned knob.
        #
        # Reported at SEVERAL targets rather than one, because a single
        # line hides how sensitive the answer is to where it is drawn —
        # and on this board it is very sensitive, which is the finding.
        deepest = max(ks)
        derived_by_target: dict[str, Any] = {}
        for target in args.targets:
            found = None
            for step in range(100, 301, 5):
                m = step / 100.0
                probe = _evaluate(pools, fmt_slots, m, [deepest])
                worst = probe["byK"][deepest]["minRetention"]
                if worst is not None and worst >= target:
                    found = probe
                    break
            derived_by_target[f"{target:.4f}"] = found
            if found is None:
                print(f"  cutoff @ {target:.2%} (k={deepest}): none up to M=3.00")
            else:
                print(
                    f"  cutoff @ {target:.2%} (k={deepest}): M={found['multiplier']:.2f}"
                    f"  ceiling {found['ceiling']}, core {found['meanCoreSize']:.1f}"
                )

        # Does the champion's ranking survive a different M?
        champion_order = _strength_order(pools, fmt_slots, 1.50)
        for m in candidates:
            if m == 1.50:
                continue
            order = _strength_order(pools, fmt_slots, m)
            moved = sum(1 for a, b in zip(champion_order, order) if a != b)
            print(f"  strength order vs M=1.50 at M={m:.2f}: {moved} of {len(order)} seats differ")
        evidence["formats"][fmt] = {
            "slots": len(fmt_slots),
            "candidates": rows,
            "derivedByTarget": derived_by_target,
        }
        print()

    print("── reading ──────────────────────────────────────────────")
    print("  Retention is resilience-of-core / resilience-of-full-roster,")
    print("  where resilience is the mean optimal lineup with k starters")
    print("  removed at once.  A core at 100% loses nothing a full roster")
    print("  could have covered; below that, the core omits players the")
    print("  roster would actually have leaned on.")
    print("  k=1 is DEGENERATE — one absence needs one replacement, so it")
    print("  reads 100% for every candidate including M=1.01.  Read k>=2.")
    print("  M is NOT changed by this script.  config keeps 1.5.")

    if args.json:
        Path(args.json).write_text(json.dumps(evidence, indent=2), encoding="utf-8")
        print(f"  evidence written to {args.json}")

    if failures:
        for f in failures:
            print(f"  FAIL  {f}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(math.floor(main()))
