#!/usr/bin/env python3
"""Outlier-integrity-v2 performance check (prereg §10 "Performance", §11 criterion 11).

Run from a throwaway tree whose ``CSVs/`` and ``data/`` are pinned to the input
commit (``outlier_integrity_v2/rootcause/pin_inputs.sh``), as the R checks are::

    python scripts/oiv2_perf.py PAYLOAD.json OUT.json

Each configuration is built in its OWN child process (so peak RSS is that
configuration's alone): one warm-up build, then ``--repeats`` timed builds;
wall time is the median of the timed builds, peak RSS the child's
``ru_maxrss``. ``incumbent`` = release defaults; ``v2`` = the V2 primary
configuration with the history lane empty (no lane exists for a pinned
production payload; NO-HISTORY is the variant Stage 4 gates on).
"""

from __future__ import annotations

import json
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))


def child(payload: str, config: str, repeats: int) -> None:
    from src.robust_filter_shadow import oiv2_replay as RP  # noqa: PLC0415

    raw = json.loads(Path(payload).read_text("utf-8"))
    cfg = RP.CONFIGS["inc" if config == "incumbent" else "v2nh"]
    RP.build(raw, None, cfg)  # warm-up
    times = []
    for _ in range(repeats):
        t = time.perf_counter()
        RP.build(raw, None, cfg)
        times.append(time.perf_counter() - t)
    print(
        json.dumps(
            {
                "config": config,
                "wallSecondsMedian": round(statistics.median(times), 4),
                "wallSeconds": [round(x, 4) for x in times],
                "peakRssMb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
            }
        )
    )


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3], int(sys.argv[4]))
        return 0
    payload, out = sys.argv[1], Path(sys.argv[2])
    repeats = 5
    res = {}
    for config in ("incumbent", "v2"):
        got = subprocess.run(
            [sys.executable, __file__, "--child", payload, config, str(repeats)],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        )
        res[config] = json.loads(got.stdout.strip().splitlines()[-1])
    inc, v2 = res["incumbent"], res["v2"]
    res["ratioWall"] = round(v2["wallSecondsMedian"] / inc["wallSecondsMedian"], 4)
    res["deltaRssMb"] = round(v2["peakRssMb"] - inc["peakRssMb"], 1)
    res["criterion11"] = {
        "wallLimit": 1.25,
        "rssLimitMb": 50,
        "passes": res["ratioWall"] <= 1.25 and res["deltaRssMb"] <= 50,
    }
    out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", "utf-8")
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
