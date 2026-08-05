"""W08 evidence: the trade calculator's board is not the canonical board.

Reproduces the divergence between ``GET /api/dynasty-data`` (the base
contract, no override posted) and ``POST /api/rankings/overrides?view=delta``
with the body the /trade page actually sends by default
(``{"tep_multiplier": 1.15}`` — ``frontend/components/useSettings.js:35``).

Run:
    .venv/bin/python docs/master-site-audit/evidence/W08/tep_override_divergence.py
"""

from __future__ import annotations

import json
import subprocess
import statistics
import sys
import tempfile
from pathlib import Path

BACKEND = "http://127.0.0.1:8000"
COOKIES = "/tmp/audit-cookies-w08.txt"


def _curl(args: list[str], out: Path) -> None:
    subprocess.run(
        ["curl", "-s", "-b", COOKIES, *args, "-o", str(out)],
        check=True,
    )


def main() -> int:
    tmp = Path(tempfile.mkdtemp())
    base_path = tmp / "base.json"
    ovr_path = tmp / "ovr.json"
    _curl([f"{BACKEND}/api/dynasty-data"], base_path)
    _curl(
        [
            "-X",
            "POST",
            f"{BACKEND}/api/rankings/overrides?view=delta",
            "-H",
            "Content-Type: application/json",
            "-d",
            '{"tep_multiplier":1.15}',
        ],
        ovr_path,
    )
    base = json.loads(base_path.read_text())
    base = base.get("data", base)
    ovr = json.loads(ovr_path.read_text())

    base_vals = {r["displayName"]: r.get("rankDerivedValue") for r in base["playersArray"]}
    ovr_vals = {p["id"]: p.get("rankDerivedValue") for p in ovr["rankingsDelta"]["players"]}

    rows = []
    for name, bv in base_vals.items():
        ov = ovr_vals.get(name)
        if not bv or not ov:
            continue
        rows.append((name, bv, ov, abs(ov - bv) / bv))

    diffs = sorted(r[3] for r in rows)
    rows.sort(key=lambda r: -r[3])
    print(f"compared            : {len(rows)}")
    print(f"differing           : {sum(1 for r in rows if r[1] != r[2])}")
    print(f"median abs % diff   : {100 * statistics.median(diffs):.3f}%")
    print(f"p90 abs % diff      : {100 * diffs[int(0.9 * len(diffs))]:.3f}%")
    print(f"max abs % diff      : {100 * diffs[-1]:.3f}%")
    print(f">5% diff            : {sum(1 for d in diffs if d > 0.05)}")
    print(f">10% diff           : {sum(1 for d in diffs if d > 0.10)}")
    print("\ntop 10 (base -> what /trade sums):")
    for name, bv, ov, _ in rows[:10]:
        print(f"  {name:<26} {bv:>6} -> {ov:>6}  ({100 * (ov - bv) / bv:+.1f}%)")
    print("\nrankingsOverride declared parameters:")
    for key in (
        "tepMultiplier",
        "tepMultiplierDefault",
        "tepMultiplierDerived",
        "tepMultiplierSource",
    ):
        print(f"  base  {key:<24} = {base['rankingsOverride'].get(key)}")
        print(f"  ovr   {key:<24} = {ovr['rankingsOverride'].get(key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
