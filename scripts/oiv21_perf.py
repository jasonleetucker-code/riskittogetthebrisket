#!/usr/bin/env python3
"""Outlier-integrity V2.1 performance and contract-size measurement.

Preregistration ``docs/sources/OUTLIER_INTEGRITY_V21_PREREGISTRATION.md`` §10
("Performance", "Contract size") and §11 criteria 13-14:

* build wall time: sequential, same machine, each configuration in its OWN child
  process (so peak RSS is that configuration's alone), one warm-up build then
  ``--repeats`` timed builds (default 5); the median is reported;
* peak RSS: the child's ``ru_maxrss`` after the timed builds;
* contract size: the full contract serialized as the server writes it
  (``json.dumps(..., ensure_ascii=False, separators=(",", ":"))``), its gzip,
  and the rankings-overrides delta view (``build_rankings_delta_payload``).

``incumbent`` is release defaults (V2 replay pins); ``v21`` is the V2.1 primary
evaluated configuration (§3.8) with the history lane empty (no lane exists for
a pinned archive; V2.1-NOHIST).

Stage discipline (§5.4): by default only a DEV board may be measured.  An R pin
(pin2015 -- Stage 3, criteria 13-14 at frozen thresholds) needs
``--stage3-r-pin``; a SPENT board is refused outright; a board absent from the
population manifest (a fresh held-out board) is refused.

    python scripts/oiv21_perf.py dynasty_export_20260930_130404.zip OUT.json
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import gzip
import io
import json
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

POPULATIONS = REPO_ROOT / "docs/sources/outlier_integrity_v21/manifests/POPULATIONS.json"
V21_EXTRA = {"outlier_integrity_v21": True, "source_rank_history_record": True}
LIMITS = {"wallRatio": 1.25, "rssDeltaMb": 50.0, "sizeRatio": 1.02}


def _entry_for(board: str, allow_r_pin: bool) -> dict:
    pops = json.loads(POPULATIONS.read_text("utf-8"))
    for e in pops["DEV"]:
        if e["board"] == board:
            return e
    for e in pops["R_PIN"]:
        if e.get("board") == board:
            if not allow_r_pin:
                raise SystemExit(f"{board} is an R pin (Stage 3 only): pass --stage3-r-pin")
            return e
    for e in pops["SPENT"]:
        if e.get("board") == board:
            raise SystemExit(f"{board} is SPENT and may not be read by V2.1")
    raise SystemExit(f"{board} is not in the V2.1 population manifest (held-out boards are sealed)")


def materialize(board: str, out: Path, allow_r_pin: bool) -> Path:
    """The board's payload plus ``CSVs/site_raw`` as committed at its add-commit,
    overlaid with the archive's own copies (the replay harness's procedure)."""
    from scripts import joint_filter_shadow as J  # noqa: PLC0415

    entry = _entry_for(board, allow_r_pin)
    _data, raw, site = J.load_archive(J.ARCHIVE_DIR / board)
    J.materialize_tree(out, entry["addCommit"], site)
    (out / "payload.json").write_text(json.dumps(raw), "utf-8")
    return out


def _config(name: str):
    from src.robust_filter_shadow import oiv2_replay as RP  # noqa: PLC0415

    if name == "incumbent":
        return RP.CONFIGS["inc"]
    return RP.Config("v21nh", True, dict(V21_EXTRA), "none", "V2.1-NOHIST")


def child(tree: str, name: str, repeats: int) -> None:
    import logging  # noqa: PLC0415

    logging.disable(logging.WARNING)
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.robust_filter_shadow import oiv2_replay as RP  # noqa: PLC0415

    root = Path(tree)
    raw = json.loads((root / "payload.json").read_text("utf-8"))
    cfg = _config(name)
    t0 = time.perf_counter()
    RP.build(raw, root, cfg)  # warm-up (cold parse caches and memos; reported, not judged)
    first = time.perf_counter() - t0
    times = []
    contract = None
    for _ in range(repeats):
        t = time.perf_counter()
        contract = RP.build(raw, root, cfg)
        times.append(time.perf_counter() - t)
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    full = json.dumps(contract, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    # The delta view through its own builder, pointed at this board's CSV tree
    # (``build_rankings_delta_payload`` reads the repo tree by default).
    original = dc.build_api_data_contract
    dc.build_api_data_contract = functools.partial(original, csv_root=root)
    try:
        with _flags_for(cfg), contextlib.redirect_stdout(io.StringIO()):
            delta = dc.build_rankings_delta_payload(json.loads(json.dumps(raw)))
    finally:
        dc.build_api_data_contract = original
    delta_bytes = json.dumps(delta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    print(
        json.dumps(
            {
                "config": name,
                "wallSecondsMedian": round(statistics.median(times), 4),
                "wallSeconds": [round(x, 4) for x in times],
                "firstBuildSeconds": round(first, 4),
                "peakRssMb": round(rss, 1),
                "fullBytes": len(full),
                "fullGzipBytes": len(gzip.compress(full, 6)),
                "deltaBytes": len(delta_bytes),
                "rows": len(contract.get("playersArray") or []),
            }
        )
    )


def _flags_for(cfg):
    from src.api import source_integrity as si  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415
    from src.robust_filter_shadow import oiv2_replay as RP  # noqa: PLC0415

    stack = contextlib.ExitStack()
    for flag, enabled in sorted(RP.flags_for(cfg).items()):
        stack.enter_context(vr._flag(flag, enabled))
    if cfg.v2:
        stack.enter_context(si.history_override(None))
    return stack


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--child":
        child(argv[1], argv[2], int(argv[3]))
        return 0
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("board", help="archive name, e.g. dynasty_export_20260930_130404.zip")
    ap.add_argument("out", type=Path)
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--stage3-r-pin", action="store_true")
    args = ap.parse_args(argv)
    with tempfile.TemporaryDirectory(prefix="oiv21-perf-") as tmp:
        tree = materialize(args.board, Path(tmp), args.stage3_r_pin)
        res: dict = {"board": args.board, "repeats": args.repeats, "limits": LIMITS}
        for name in ("incumbent", "v21"):
            got = subprocess.run(
                [sys.executable, __file__, "--child", str(tree), name, str(args.repeats)],
                capture_output=True,
                text=True,
                check=True,
                cwd=REPO_ROOT,
            )
            res[name] = json.loads(got.stdout.strip().splitlines()[-1])
    inc, v21 = res["incumbent"], res["v21"]
    res["ratioWall"] = round(v21["wallSecondsMedian"] / inc["wallSecondsMedian"], 4)
    res["ratioFirstBuild"] = round(v21["firstBuildSeconds"] / inc["firstBuildSeconds"], 4)
    res["deltaRssMb"] = round(v21["peakRssMb"] - inc["peakRssMb"], 1)
    res["ratioFull"] = round(v21["fullBytes"] / inc["fullBytes"], 4)
    res["ratioGzip"] = round(v21["fullGzipBytes"] / inc["fullGzipBytes"], 4)
    res["ratioDelta"] = round(v21["deltaBytes"] / inc["deltaBytes"], 4)
    res["withinBudget"] = {
        "criterion13": res["ratioWall"] <= LIMITS["wallRatio"]
        and res["deltaRssMb"] <= LIMITS["rssDeltaMb"],
        "criterion14": max(res["ratioFull"], res["ratioGzip"], res["ratioDelta"])
        <= LIMITS["sizeRatio"],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(res, indent=1, sort_keys=True) + "\n", "utf-8")
    print(
        json.dumps(
            {
                k: res[k]
                for k in (
                    "ratioWall",
                    "ratioFirstBuild",
                    "deltaRssMb",
                    "ratioFull",
                    "ratioGzip",
                    "ratioDelta",
                    "withinBudget",
                )
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
