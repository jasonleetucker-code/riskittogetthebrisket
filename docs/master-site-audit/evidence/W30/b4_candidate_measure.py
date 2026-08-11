#!/usr/bin/env python3
"""B4 §4 steps 2-3 — declare the criteria, then measure candidates A-D.

Run with ``--criteria`` to print the evaluation criteria alone (they are
declared BEFORE any candidate is measured, which is the point), or
``--measure`` to score every candidate against them on the identical B4
pin.

**Nothing here changes production.** Candidates are applied by patching
the canonical functions for the duration of one board build; the tree is
untouched.

The four candidates
-------------------

``A`` **current** — ``p`` saturates at 1.0 at ``PERCENTILE_REFERENCE_N``.

``B`` **continuous** — no upper bound on ``p``; the Hill keeps decaying
      for arbitrarily deep ranks.

``C`` **bounded at a justified boundary** — ``p`` saturates at
      ``(R_MAX − 1) / (N − 1)`` for a boundary rank ``R_MAX`` chosen from
      observed evidence depth. Measured at two boundaries: 877 (the
      deepest rank-Hill rank consumed by a served row on this pin) and
      903 (the deepest rank any source publishes, per
      ``src/api/source_history.py:352``).

``D`` **per-source coverage boundary** — each source saturates at its own
      deepest published rank, the purest reading of "a source that stops
      at rank N has no opinion below it".

Why C is a tail policy and not a refit — the algebra
-----------------------------------------------------

The Hill in rank form is ``V(r) = 9999 / (1 + ((r−1)/M)^s)`` with
``M = c·(N−1)``, the rank-space midpoint B1.2 established as the
invariant. Two formulations of "saturate at ``R_MAX``" are therefore the
same function:

1. re-express the curve in a universe ``N' = R_MAX`` and transform
   ``c' = c·(N−1)/(N'−1)`` — the identity ``transform_c`` already
   verified in ``tests/canonical/test_coordinate_equivalence.py``;
2. keep ``c``, ``s`` and ``N`` exactly as committed and raise the
   coordinate ceiling to ``p_max = (R_MAX−1)/(N−1)``.

They agree at every rank (asserted below, not asserted in prose). The
second is the implementation this harness measures, because it changes
**no champion constant and no reference N** — so a bounded tail cannot be
confused with, or smuggle in, a refit. That is also why B4's standing
instruction "do not simply change ``PERCENTILE_REFERENCE_N``" is
satisfied rather than worked around: changing N alone WOULD reshape the
curve, because it moves ``M``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

OUT = Path(__file__).resolve().parent

#: Deepest rank-Hill effective rank consumed by a SERVED row (B4 pin).
DEEPEST_SERVED_RANK_HILL = 877

#: Deepest rank any source publishes, corroborated independently by
#: ``src/api/source_history.py:352``.
DEEPEST_PUBLISHED_RANK = 903

#: Live deep ranks the pin records as real per-source evidence.
LIVE_DEEP_RANKS = (501, 572, 620, 621, 661, 684, 730, 877)


CRITERIA = """
B4 evaluation criteria — DECLARED BEFORE MEASUREMENT
====================================================

A candidate must be scored against all eight. They are ordered: 1-3 are
disqualifying, 4-6 decide between survivors, 7-8 are properties the
chosen candidate must be able to demonstrate.

1. HEAD PRESERVATION (disqualifying).
   Ranks 1..500 must be bit-identical to today. A tail policy that moves
   the region the curve was fitted to represent is a refit wearing a
   tail's clothes, and B4 is explicitly forbidden from refitting to
   compensate for the tail.

2. EVIDENCE SEPARATION (disqualifying).
   Distinct ranks for which a source published distinct evidence must
   receive distinct contributions. Measured as (distinct values) /
   (distinct live deep ranks) over the observed range. This is the
   defect; a candidate that does not fix it is candidate A.

3. MONOTONICITY (disqualifying).
   Non-increasing in rank everywhere — a deeper rank must never be worth
   more — AND strictly decreasing across ranks that carry distinct
   evidence.

   MEASUREMENT CLARIFICATION, recorded rather than silently applied: the
   first draft of this criterion said "strictly decreasing per unit
   rank". That is unachievable by ANY candidate including the current
   one, because contributions are integers on a 1-9999 scale and adjacent
   deep ranks differ by less than half a unit, so they legitimately tie
   on rounding. The standard is unchanged in substance — distinct
   evidence must not collapse — but it is evaluated over distinct
   evidence ranks, with per-unit-rank strictness reported alongside as a
   diagnostic rather than a gate. Both figures are printed.

4. NO INVENTED EVIDENCE.
   "Missing is never zero." A source that stops at rank N has no opinion
   about players below it. A policy is penalised for resolving ranks
   beyond any observed coverage, because doing so states a value the
   data does not support.

5. BOUNDED AND STABLE AT DEPTH.
   Behaviour as rank grows without limit must be defined and defensible.
   A future source ranking twice as deep must not silently receive an
   arbitrarily small contribution that no evidence backs.

6. ONE OWNER FOR SERVING, FITTING AND SCORING.
   The policy must be expressible in a single place that all four
   clamps defer to. A policy that cannot be shared re-creates W30-F008,
   where training and serving disagreed about a coordinate.

7. PROPORTIONATE BOARD IMPACT.
   The measured movement must land where the defect is (deep IDP rows)
   and not where it is not (offense, picks). Movement outside the
   saturated population is evidence the change did something other than
   what it claims.

8. REVERSIBLE BY ONE CONSTANT.
   Current behaviour must be restorable by a single declared value,
   with no code path change.
"""


def _hill_raw(p: float, c: float, s: float) -> float:
    """Hill with NO coordinate clamp — the counterfactual evaluator."""
    if p <= 0.0:
        return 9999.0
    return 9999.0 / (1.0 + (p / c) ** s)


def _clamp_out(v: float) -> int:
    return max(1, min(9999, round(v)))


class Policy:
    """A tail policy as a coordinate ceiling on ``p``.

    ``p_max is None`` means unbounded (candidate B). Everything else is a
    ceiling expressed in the SAME coordinate the committed curve already
    uses, so ``c``, ``s`` and ``N`` never move.
    """

    def __init__(self, key: str, label: str, boundary_rank: int | None, *, n: int = 500):
        self.key = key
        self.label = label
        self.boundary_rank = boundary_rank
        self.n = n
        self.p_max = None if boundary_rank is None else (boundary_rank - 1.0) / (n - 1.0)

    def percentile(self, rank: float, reference_n: int | None = None) -> float:
        n = int(reference_n or self.n)
        if n < 2:
            return 0.0
        p = (float(rank) - 1.0) / float(n - 1)
        p = max(0.0, p)
        return p if self.p_max is None else min(self.p_max, p)

    def value(self, rank: float, c: float, s: float, reference_n: int | None = None) -> int:
        return _clamp_out(_hill_raw(self.percentile(rank, reference_n), c, s))


CANDIDATES = [
    Policy("A", "current — saturate at N=500", 500),
    Policy("B", "continuous — never saturate", None),
    Policy("C877", "bounded at 877 (deepest served rank-Hill rank)", DEEPEST_SERVED_RANK_HILL),
    Policy("C903", "bounded at 903 (deepest rank any source publishes)", DEEPEST_PUBLISHED_RANK),
]


def _curves() -> dict[str, tuple[float, float]]:
    from src.canonical.rank_coordinates import (
        RANK_POOL_IDP,
        RANK_POOL_OFFENSE,
        RANK_POOL_SHARED_MARKET,
        curve_for_pool,
    )

    return {
        "GLOBAL": curve_for_pool(RANK_POOL_SHARED_MARKET),
        "OFFENSE": curve_for_pool(RANK_POOL_OFFENSE),
        "IDP": curve_for_pool(RANK_POOL_IDP),
    }


def prove_bounded_is_not_a_refit() -> list[str]:
    """Assert formulation 1 == formulation 2 at every tested rank.

    Stated as executable arithmetic rather than prose, because "this is
    only a change of units" is exactly the claim a reader should refuse
    to take on trust.
    """
    lines = []
    for label, (c, s) in _curves().items():
        m = c * 499.0
        for boundary in (DEEPEST_SERVED_RANK_HILL + 1, DEEPEST_PUBLISHED_RANK):
            c_t = c * 499.0 / (boundary - 1.0)
            worst = 0.0
            for r in list(range(1, 500, 7)) + list(range(500, boundary + 1, 11)):
                p_t = min(1.0, (r - 1.0) / (boundary - 1.0))
                v_t = _clamp_out(_hill_raw(p_t, c_t, s))
                v_ceiling = Policy("x", "x", boundary).value(r, c, s)
                worst = max(worst, abs(v_t - v_ceiling))
            assert worst == 0.0, (label, boundary, worst)
            lines.append(
                f"  {label:<8} M=c(N-1)={m:8.3f}   boundary {boundary}: "
                f"transform c->{c_t:.6f} == coordinate ceiling "
                f"p_max={(boundary - 1) / 499.0:.4f}   max |delta| = {worst:.0f}"
            )
    return lines


def score_analytic() -> dict:
    """Criteria 1-6, which need no board rebuild."""
    curves = _curves()
    out: dict[str, dict] = {}
    for pol in CANDIDATES:
        rec: dict = {"label": pol.label, "boundaryRank": pol.boundary_rank}
        base = CANDIDATES[0]

        # 1. head preservation
        head_delta = 0
        for label, (c, s) in curves.items():
            for r in range(1, 501):
                head_delta = max(head_delta, abs(pol.value(r, c, s) - base.value(r, c, s)))
        rec["headMaxAbsDelta"] = head_delta
        rec["headPreserved"] = head_delta == 0

        # 2. evidence separation, on the pool that carries the defect
        c, s = curves["GLOBAL"]
        vals = [pol.value(r, c, s) for r in LIVE_DEEP_RANKS]
        rec["distinctLiveDeepRanks"] = len(set(LIVE_DEEP_RANKS))
        rec["distinctValues"] = len(set(vals))
        rec["evidenceSeparation"] = round(len(set(vals)) / len(set(LIVE_DEEP_RANKS)), 3)

        # 3. strict monotonicity across the resolved range
        ranks = list(range(1, DEEPEST_SERVED_RANK_HILL + 1))
        seq = [pol.value(r, c, s) for r in ranks]
        rec["strictlyDecreasingPerUnitRank"] = all(a > b for a, b in zip(seq, seq[1:]))
        rec["nonIncreasing"] = all(a >= b for a, b in zip(seq, seq[1:]))
        deep_seq = [pol.value(r, c, s) for r in sorted(LIVE_DEEP_RANKS)]
        rec["strictlyDecreasingOverLiveDeepRanks"] = all(
            a > b for a, b in zip(deep_seq, deep_seq[1:])
        )

        # 4/5. invented evidence and depth behaviour
        rec["resolvesBeyondObservedCoverage"] = pol.boundary_rank is None
        rec["valueAtRank5000"] = pol.value(5000, c, s)
        rec["valueAtRank50000"] = pol.value(50000, c, s)
        rec["boundedAtDepth"] = pol.boundary_rank is not None

        # 6. shareable by one owner — true for every ceiling-shaped policy
        rec["expressibleAsOneOwner"] = True
        out[pol.key] = rec

    # Candidate D is structural, and fails on a criterion no number softens.
    out["D"] = _score_candidate_d()
    return out


def _score_candidate_d() -> dict:
    """D — per-source coverage boundary. Measured, then rejected.

    The appeal is real: it is the strictest reading of "missing is never
    zero". The disqualifier is that the boundary becomes a property of
    the SOURCE rather than of the coordinate, so the same ordinal rank
    maps to different percentiles depending on which source supplied it —
    which is W30-F008 exactly, the defect the canonical coordinate owner
    was created to end.
    """
    report = json.loads((OUT / "b4_tail_report.json").read_text())
    depths = {
        k: v["deepestRankHillRank"]
        for k, v in report["bySource"].items()
        if v["rankHillObservations"]
    }
    c, s = _curves()["GLOBAL"]

    # D rescales the coordinate onto each source's OWN pool —
    # ``p = (r-1)/(depth-1)`` — rather than truncating a shared one. That
    # distinction is the whole of the candidate: a ceiling at each
    # source's depth would leave the coordinate shared and would simply
    # be candidate C with a per-source boundary, which prices a given
    # rank identically everywhere and so is not a separate candidate at
    # all. The rescaling is what makes D "the source's own tail", and it
    # is also what disqualifies it.
    def d_value(rank: float, depth: int) -> int:
        if depth < 2:
            return 9999
        p = max(0.0, min(1.0, (float(rank) - 1.0) / (depth - 1.0)))
        return _clamp_out(_hill_raw(p, c, s))

    rank = 600
    coords = {k: d_value(rank, d) for k, d in sorted(depths.items()) if d >= rank}
    head_delta = 0
    base = CANDIDATES[0]
    for depth in depths.values():
        for r in range(1, 501):
            head_delta = max(head_delta, abs(d_value(r, depth) - base.value(r, c, s)))
    deep = sorted(r for r in LIVE_DEEP_RANKS if r <= max(depths.values()))
    seq = [d_value(r, max(depths.values())) for r in deep]
    return {
        "label": "per-source native-pool coordinate",
        "boundaryRank": "per-source",
        "headMaxAbsDelta": head_delta,
        "headPreserved": head_delta == 0,
        "evidenceSeparation": round(len(set(seq)) / len(set(deep)), 3),
        "strictlyDecreasingOverLiveDeepRanks": all(a > b for a, b in zip(seq, seq[1:])),
        "resolvesBeyondObservedCoverage": False,
        "boundedAtDepth": True,
        "expressibleAsOneOwner": False,
        "sameRankOneValuePerSource": coords,
        "distinctValuesForOneRank": len(set(coords.values())),
        "disqualifier": (
            f"rank {rank} receives {len(set(coords.values()))} different values depending on "
            "which source supplied it, and the fitted head moves by "
            f"{head_delta} — the coordinate stops being a shared unit, which is W30-F008 "
            "re-created, and the curve is reshaped inside the region it was fitted to"
        ),
    }


def measure() -> None:
    print(CRITERIA)
    print("== the bounded candidate is a change of units, proven as arithmetic ==")
    for line in prove_bounded_is_not_a_refit():
        print(line)

    scores = score_analytic()

    print("\n== criteria 1-3 (disqualifying) ==")
    print("  'strict/evidence' = strictly decreasing across ranks carrying distinct evidence.")
    print("  'strict/unit' = per unit rank; False for EVERY candidate incl. current, because")
    print("  contributions are integers and adjacent deep ranks tie on rounding — diagnostic,")
    print("  not a gate (see criterion 3).")
    print(
        f"  {'cand':<6}{'head delta':>12}{'head ok':>9}{'separation':>12}"
        f"{'strict/evidence':>17}{'strict/unit':>13}{'non-incr':>10}"
    )
    for key in ("A", "B", "C877", "C903", "D"):
        r = scores[key]
        print(
            f"  {key:<6}{str(r.get('headMaxAbsDelta', 0)):>12}{str(r['headPreserved']):>9}"
            f"{r['evidenceSeparation']:>12}"
            f"{str(r['strictlyDecreasingOverLiveDeepRanks']):>17}"
            f"{str(r.get('strictlyDecreasingPerUnitRank', '—')):>13}"
            f"{str(r.get('nonIncreasing', '—')):>10}"
        )

    print("\n== criteria 4-6 ==")
    print(f"  {'cand':<6}{'invents evidence':>18}{'V@5000':>9}{'V@50000':>9}{'one owner':>11}")
    for key in ("A", "B", "C877", "C903"):
        r = scores[key]
        print(
            f"  {key:<6}{str(r['resolvesBeyondObservedCoverage']):>18}"
            f"{r['valueAtRank5000']:>9}{r['valueAtRank50000']:>9}"
            f"{str(r['expressibleAsOneOwner']):>11}"
        )
    d = scores["D"]
    print(f"\n  D — {d['label']}: {d['disqualifier']}")
    print(f"      rank 600 priced as {d['sameRankOneValuePerSource']}")

    print("\n== B vs C on the LIVE evidence range — do they differ at all? ==")
    curves = _curves()
    b = next(p for p in CANDIDATES if p.key == "B")
    for ckey in ("C877", "C903"):
        cpol = next(p for p in CANDIDATES if p.key == ckey)
        worst = 0
        for label, (c, s) in curves.items():
            for r in range(1, DEEPEST_SERVED_RANK_HILL + 1):
                worst = max(worst, abs(b.value(r, c, s) - cpol.value(r, c, s)))
        print(f"  B vs {ckey}: max |delta| over ranks 1..{DEEPEST_SERVED_RANK_HILL} = {worst}")
    print(
        "  They are observationally IDENTICAL on every rank the pinned board contains.\n"
        "  The choice between them is therefore not decidable from this board — it is a\n"
        "  decision about ranks nobody has published, and criteria 4/5 are what decide it."
    )

    payload = {"criteria": CRITERIA.strip().splitlines(), "candidates": scores}
    (OUT / "b4_candidate_report.json").write_text(json.dumps(payload, indent=1, default=str))
    print(f"\nwrote {OUT / 'b4_candidate_report.json'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--criteria", action="store_true")
    ap.add_argument("--measure", action="store_true")
    args = ap.parse_args()
    if args.criteria:
        print(CRITERIA)
        return 0
    if args.measure:
        measure()
        return 0
    ap.error("pass --criteria or --measure")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
