"""Operating characteristics of the sim-calibration gates under a PERFECTLY calibrated model.

Backs preregistration §6.1 of ``docs/league-intelligence/SIM_CALIBRATION_V2_PREREGISTRATION_2026-10-26.md``
(the "a perfect challenger almost never passes" disclosure). Research only: no outcome, no data file and
no served artifact is read, and nothing is written outside ``--out``.

Under perfect calibration a player-week's PIT is iid Uniform(0, 1), so each gate's pass probability depends
only on the family sizes. For the known gated holdout families (QB 64, RB 122, WR 181, TE 90, DL 133,
LB 161, DB 170) and the 24 team-weeks, this draws ``--reps`` replications (default 20,000, seed 20261026)
and applies v1's own constants:

* SC-G1: PIT coverage 80 in [0.75, 0.85] and PIT coverage 95 in [0.90, 1.00], in every gated family;
* SC-G4: KS D <= 0.08 in every gated family (the relative pooled-vs-fallback half is not simulated);
* SC-G5 coverage halves: a team-week is covered with probability 0.80 / 0.95, n = 24.

Each player appears in up to two holdout weeks, so real sampling distributions are wider than these iid
ones: the numbers are lower bounds on how hard the gates are.

Run::

    python scripts/sim_calibration_gate_operating_characteristics.py
    python scripts/sim_calibration_gate_operating_characteristics.py --out \
        docs/league-intelligence/evidence/sim_calibration_v2/gate_operating_characteristics.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from scripts import sim_calibration_study as v1  # noqa: E402

#: The v2 study's committed evidence. It is the single source of the holdout
#: sample sizes, so they are read from there rather than restated.
EVIDENCE = REPO / "docs/league-intelligence/evidence/sim_calibration_v2/evaluation_v2.json"


def _holdout_sizes() -> tuple[dict[str, int], int]:
    """Holdout (2026 weeks 5-6) player-weeks per gated family, and team-weeks.

    Read from the committed evidence (``V2-D2_sizeAwareReading`` and
    ``teamWeek.n``). These are sample SIZES of the holdout, not a lineup
    demand. A missing or malformed evidence file is an error, never a guessed
    default.
    """
    doc = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    sizes = {fam: int(row["n"]) for fam, row in doc["V2-D2_sizeAwareReading"].items()}
    if not sizes:
        raise SystemExit(f"no gated-family sizes in {EVIDENCE}")
    return sizes, int(doc["teamWeek"]["n"])


FAMILY_N, TEAM_WEEKS = _holdout_sizes()
PIT80, PIT95 = (0.10, 0.90), (0.025, 0.975)
EPS = 1e-9  # v1's band tolerance (``_within``)


def _share(u: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return ((u >= lo) & (u <= hi)).mean(axis=1)


def operating_characteristics(
    family_n: Mapping[str, int] = FAMILY_N, reps: int = 20_000, seed: int = v1.SEED
) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    g1: dict[str, np.ndarray] = {}
    g4: dict[str, np.ndarray] = {}
    for fam, n in family_n.items():
        u = np.sort(rng.random((reps, n)), axis=1)
        i = np.arange(1, n + 1)
        d = np.maximum((i / n - u).max(axis=1), (u - (i - 1) / n).max(axis=1)).round(5)
        c80, c95 = _share(u, *PIT80), _share(u, *PIT95)
        g1[fam] = (
            (c80 >= v1.G1_COV80[0] - EPS)
            & (c80 <= v1.G1_COV80[1] + EPS)
            & (c95 >= v1.G1_COV95[0] - EPS)
            & (c95 <= v1.G1_COV95[1] + EPS)
        )
        g4[fam] = d <= v1.G4_MAX_KS_D
    t80 = rng.binomial(TEAM_WEEKS, 0.80, reps) / TEAM_WEEKS
    t95 = rng.binomial(TEAM_WEEKS, 0.95, reps) / TEAM_WEEKS
    g5 = (
        (t80 >= v1.G5_COV80[0] - EPS)
        & (t80 <= v1.G5_COV80[1] + EPS)
        & (t95 >= v1.G5_MIN_COV95 - EPS)
    )
    all_g1 = np.logical_and.reduce(list(g1.values()))
    all_g4 = np.logical_and.reduce(list(g4.values()))
    return {
        "reps": reps,
        "seed": seed,
        "familyN": dict(family_n),
        "SC-G1": {"everyGatedFamily": float(all_g1.mean()), "byFamily": _means(g1)},
        "SC-G4": {"everyGatedFamily": float(all_g4.mean()), "byFamily": _means(g4)},
        "SC-G1_and_SC-G4": float((all_g1 & all_g4).mean()),
        "SC-G5_coverageHalves": float(g5.mean()),
    }


def _means(by_family: Mapping[str, np.ndarray]) -> dict[str, float]:
    return {fam: round(float(m.mean()), 4) for fam, m in by_family.items()}


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--reps", type=int, default=20_000)
    p.add_argument("--seed", type=int, default=v1.SEED)
    p.add_argument("--out", default=None, help="write the result as JSON here (guarded path)")
    args = p.parse_args(argv)
    result = {"promotes": False, **operating_characteristics(reps=args.reps, seed=args.seed)}
    if args.out:
        v1.write_json(Path(args.out), result)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
