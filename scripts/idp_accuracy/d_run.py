"""Lane D driver: run every scenario in parallel and write the evidence JSON.

    python scripts/idp_accuracy/d_run.py --draws 1500 --boots 60 --workers 18
    python scripts/idp_accuracy/d_run.py --report-only          # re-aggregate cached scenario rows

Research only.  Writes ``docs/valuation/idp_accuracy/evidence/bestball_archetypes.json`` and a
gitignored scenario cache under ``data/idp_accuracy/work/``.  Reads public Sleeper / nflverse data
through the cached fetcher (``--offline`` forbids any network call).

This script must not import ``src.bestball`` (``tests/bestball/test_import_graph.py``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.idp_accuracy import d_data as D  # noqa: E402
from scripts.idp_accuracy import d_engine as E  # noqa: E402
from scripts.idp_accuracy import d_study as S  # noqa: E402

WORK = ROOT / "data/idp_accuracy/work"
EVIDENCE = ROOT / "docs/valuation/idp_accuracy/evidence/bestball_archetypes.json"

_G: dict = {}


def _init(universes, shape):
    _G["universes"] = universes
    _G["shape"] = shape


def _task(sc: E.Scenario):
    t0 = time.time()
    rows = S.run_scenario(_G["universes"], _G["shape"], sc)
    return sc, rows, time.time() - t0


def scenario_plan(draws: int, boots: int, seed: int) -> list[E.Scenario]:
    base = dict(draws=draws, seed=seed)
    plan = [
        E.Scenario(model="E", **base),  # the pre-specified primary
        E.Scenario(model="Ec", **base),
        E.Scenario(model="S", **base),
        E.Scenario(model="Su", **base),
        E.Scenario(model="P", **base),
        E.Scenario(model="Q", **base),
        E.Scenario(model="E", avail="always", **base),
        E.Scenario(model="E", byes="none", **base),
        E.Scenario(model="E", cand_ranks=(1, 2), repl_mode="best", **base),
        E.Scenario(model="E", cand_ranks=(1,), repl_mode="best", **base),
        E.Scenario(model="E", cand_ranks=(3,), repl_mode="best", **base),
        E.Scenario(model="E", cand_ranks=(5,), repl_mode="best", **base),
        E.Scenario(model="E", window="early", **base),
        E.Scenario(model="E", window="late", **base),
        E.Scenario(model="E", window="all_inj", **base),
    ]
    plan += [E.Scenario(model="E", boot=b, **base) for b in range(1, boots + 1)]
    return plan


def scenario_key(sc: E.Scenario) -> str:
    parts = [
        sc.model,
        sc.avail,
        sc.byes,
        sc.window,
        sc.repl_mode + ":" + "-".join(map(str, sc.cand_ranks)),
    ]
    if sc.boot is not None:
        parts.append(f"boot{sc.boot}")
    return "|".join(parts)


def build_all(offline: bool):
    inp = D.load_inputs(offline=offline)
    cls = S.classify(inp)
    cls_inj = S.classify(inp, include_injured=True)
    universes = {
        "all": S.build_universe(inp, cls, "all"),
        "early": S.build_universe(inp, cls, "early"),
        "late": S.build_universe(inp, cls, "late"),
        "all_inj": S.build_universe(inp, cls_inj, "all_inj"),
    }
    shape = S.build_shape(inp)
    return inp, cls, universes, shape


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--draws", type=int, default=1500)
    ap.add_argument("--boots", type=int, default=60)
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--seed", type=int, default=20261026)
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--report-only", action="store_true")
    args = ap.parse_args(argv)
    store = WORK / f"d{args.draws}_s{args.seed}"
    store.mkdir(parents=True, exist_ok=True)
    inp, cls, universes, shape = build_all(args.offline)
    plan = scenario_plan(args.draws, args.boots, args.seed)

    def path_for(sc: E.Scenario) -> Path:
        return store / (hashlib.sha1(scenario_key(sc).encode()).hexdigest()[:16] + ".pkl")

    # Every finished scenario is written the moment it completes, so a killed run resumes where it
    # stopped instead of starting over (a 75-scenario run is ~40 minutes on a shared machine).
    results: dict = {}
    pending = []
    for sc in plan:
        f = path_for(sc)
        if f.exists():
            results[scenario_key(sc)] = pickle.loads(f.read_bytes())
        else:
            pending.append(sc)
    print(f"{len(results)} scenarios cached, {len(pending)} to run", flush=True)
    if pending and not args.report_only:
        t0 = time.time()
        with ProcessPoolExecutor(
            max_workers=args.workers, initializer=_init, initargs=(universes, shape)
        ) as pool:
            futures = [pool.submit(_task, sc) for sc in pending]
            for fut in as_completed(futures):
                try:
                    sc, rows, dt = fut.result()
                except Exception as exc:  # noqa: BLE001 - a failed scenario is rerun, not fatal
                    print(
                        f"scenario failed ({type(exc).__name__}: {exc}); rerun to resume",
                        flush=True,
                    )
                    continue
                rec = {"scenario": sc, "rows": rows}
                tmp = path_for(sc).with_suffix(".tmp")
                tmp.write_bytes(pickle.dumps(rec))
                tmp.replace(path_for(sc))
                results[scenario_key(sc)] = rec
                print(
                    f"[{time.time() - t0:7.0f}s] {scenario_key(sc)}  ({dt:.0f}s, {len(rows)} players)",
                    flush=True,
                )
    missing = [scenario_key(sc) for sc in plan if scenario_key(sc) not in results]
    if missing:
        print(f"{len(missing)} scenarios missing; not writing evidence", file=sys.stderr)
        return 3
    from scripts.idp_accuracy import d_report as R

    evidence = R.build_evidence(inp, cls, universes, shape, results, args)
    EVIDENCE.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE.write_text(json.dumps(evidence, indent=1, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {EVIDENCE.relative_to(ROOT)} ({EVIDENCE.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
