#!/usr/bin/env python3
"""Render the owner-named D4 case (Theo Johnson, Draft Sharks 3182) from the
incumbent-only extraction of the newest I_INDEPENDENT board. No V2 board is
built on that held-out board; V2's reading of the same panel is the frozen
fixture test tests/api/test_oiv2_regression_set.py::test_theo_johnson_*.

    python oiv2_abcd_theo_iboard.py X_I.json.gz OUT.md
"""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from oiv2_abcd_analyze import focus_table  # noqa: E402

d = json.load(gzip.open(sys.argv[1], "rt"))
L = [
    "# Theo Johnson on the newest I_INDEPENDENT board (incumbent-only rebuild)",
    "",
    f"Archive `dynasty_export_20261020_052241` (I_INDEPENDENT), payload sha256 `{d['payloadSha256']}`, "
    "inputs pinned to its add commit `d9c3a70209`. Boards built: A (production), B′ (D4 on, incumbent), "
    "Anf / B′nf (no per-row filter). **No V2 build was run on this held-out board** (preregistration §16).",
    "",
]
L += focus_table(d["boards"], "Theo Johnson", ["A", "B'", "Anf", "B'nf"])
bp = d["boards"]["B'"]["rows"]["Theo Johnson"]
L += [
    "Pre-filter panel on B′ (votes reaching the filter): "
    + ", ".join(
        f"{k} {v.get('valueContribution')}"
        for k, v in sorted(bp["votes"].items())
        if v["status"] in (None, "filter_dropped")
    ),
    "",
]
Path(sys.argv[2]).write_text("\n".join(L) + "\n")
print("ok")
