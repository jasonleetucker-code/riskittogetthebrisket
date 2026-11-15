"""Re-measure the Package VA research Phases 1-3 under fairness_bands_v2 (2026-10-21).

RESEARCH ONLY.  Nothing here changes a value, a verdict, a config, a flag or the
active model: ``geom_q078_v1`` (q = 0.78) stays the package model and the
fairness-band owner (``src/valuation_math/fairness_bands.py``) is only CALLED.
Owner approval: ``docs/owner/LVA_OWNER_DECISIONS_2026-10-21.md`` (research only).

Phases 1-3 classified fairness levels on the retired fairness_bands_v1 denominator
(the larger ADJUSTED side).  This driver re-runs every band-dependent section of
each phase on its pinned board twice, through the phase scripts' own functions:

* ``v1_legacy`` -- the recorded basis; compared leaf by leaf with the committed
  evidence file to prove the reproduction;
* ``current`` -- fairness_bands_v2 from the owner, each model on its own package
  utilities (``package_model_hybrid_research.band_level``).

Only the band's DENOMINATOR differs between the two runs: same board, same code,
same seeds, same gaps.  Sections that never classify a band (properties,
residuals, market calibration, the box ledger) are band-independent and are not
re-run; the box-only inputs cannot be re-run here at all.

The Trade Finder / Best Offers / Package Builder engines read no band
denominator, so each model's replay is run ONCE and its trades are re-tagged on
both bases (``--finder``; roughly 20-40 minutes per phase).

Board pins (``scripts/research_pinned_board.py``): Phase 1 and 2 read the raw
payload ``exports/latest/dynasty_data_2026-10-19.json`` at their recorded code
SHAs (sha256 verified) and the CSV tree of the same revision; Phase 3 reads
``exports/archive/dynasty_export_20261019_235843.zip`` with the CSV tree at its
recorded code SHA.  Phase 1's own-league trade file is read at its revision too.

Output: ``docs/valuation/evidence/package_model_v2_remeasure_2026-10-21/phase{1,2,3}.json``.
The original evidence directories are never written.

Exact reproduction of Phases 1-2.  The canonical pipeline changed after they ran
(the pick horizon among others: today's build of the same payload prices 1,005
assets, the recorded one 1,029), so the board, Phase 1's trade rows and Phase 2's
Finder replay are rebuilt by ``scripts/package_model_v2_remeasure_extract.py``
inside a detached checkout of ``79c322828`` (the recorded Phase 2 commit; the same
pipeline inputs as Phase 1's ``9668165``) and passed in with ``--board-json`` /
``--finder-json``.  Phase 3's board reproduces with today's code once Travis
Hunter is held at his recorded value.

Usage (the evidence run)::

    python scripts/package_model_v2_remeasure.py --phase 1 --board-json <x>/board_p1p2.json
    python scripts/package_model_v2_remeasure.py --phase 2 --board-json <x>/board_p1p2.json         --finder-json <x>/finder2_GEOM_78.json <x>/finder2_HYBRID_50.json <x>/finder2_BLEND_G50_K50.json
    python scripts/package_model_v2_remeasure.py --phase 3 --finder --workers 3
"""

from __future__ import annotations

import argparse
import contextlib
import functools
import hashlib
import importlib.util
import json
import multiprocessing
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(SCRIPT_DIR))


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P3L = _load("package_model_phase3_local")  # loads Phase 3 -> Phase 2 -> Phase 1
P2 = P3L.P2
P1 = P2.P1
FR = P3L.FR
PB = _load("research_pinned_board")

from src.valuation_math import fairness_bands  # noqa: E402
from src.valuation_math import package_model as pm  # noqa: E402

OUT_DEFAULT = "docs/valuation/evidence/package_model_v2_remeasure_2026-10-21"
BASES = ("v1_legacy", "current")
EVIDENCE = REPO / "docs" / "valuation" / "evidence"
RAW_1019 = "exports/latest/dynasty_data_2026-10-19.json"
RAW_1019_SHA = "b639608f68176b9a395527e6e9ea992e324baa75d997b8ea289e587e61eae11c"

PINS = {
    1: {
        "rev": "9668165298c9d50bf192931138e4c1cf13ad28d0",
        "raw": RAW_1019,
        "sha256": RAW_1019_SHA,
        "recorded": EVIDENCE / "package_model_hybrid_2026-10-19" / "research.json",
    },
    2: {
        "rev": "f2e0f614bcd2a47618426a05592efbd8a3942fb0",
        "raw": RAW_1019,
        "sha256": RAW_1019_SHA,
        "recorded": EVIDENCE / "package_model_phase2_2026-10-19" / "phase2.json",
    },
    3: {
        "rev": "6dbfc5aa9f7a9734f1d0cca6fed9e662b404218d",
        "archive": "exports/archive/dynasty_export_20261019_235843.zip",
        "sha256": "a8839a659d76e94366a7aa1dcf15168502b42a763845c08d0ada2bf8e3f0b1ae",
        "recorded": EVIDENCE / "package_model_phase3_2026-10-20" / "local.json",
    },
}


#: Travis Hunter's canonical value as RECORDED on each phase's board.  The value
#: pipeline changed it after the evidence ran (PR #1817), so a same-board
#: reproduction holds it (the #1898 precedent, ``LOW_VALUE_ASSET_V2_CORRECTION``
#: §3).  Applied to the phase's own board rows only, identically on both bases.
HUNTER = "Travis Hunter"
HUNTER_RECORDED = {1: 3746.0, 2: 3746.0, 3: 3738.0}


def hold_hunter(rows: dict, phase: int) -> dict:
    """Set Hunter's row value to the recorded one; returns what was changed."""
    r = rows.get(HUNTER)
    if r is None:
        return {"held": False, "reason": "not on the board"}
    built = r["value"]
    r["value"] = HUNTER_RECORDED[phase]
    return {"held": True, "builtValue": built, "heldAt": HUNTER_RECORDED[phase]}


# ── pinning ───────────────────────────────────────────────────────────────


def _git_bytes(rev: str, path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(REPO), "show", f"{rev}:{path}"], check=True, capture_output=True
    ).stdout


def raw_for(phase: int) -> tuple[bytes, dict]:
    pin = PINS[phase]
    if "archive" in pin:
        zpath, member, blob, _ = PB.load_archive(pin["archive"])
        src = {"archive": pin["archive"], "member": member}
    else:
        blob = _git_bytes(pin["rev"], pin["raw"])
        src = {"rawPayload": pin["raw"], "atRevision": pin["rev"]}
    sha = hashlib.sha256(blob).hexdigest()
    assert (
        sha == pin["sha256"]
    ), f"phase {phase}: raw payload sha256 {sha} != recorded {pin['sha256']}"
    return blob, {**src, "sha256": sha}


@contextlib.contextmanager
def pinned(phase: int):
    """The CSV tree at the phase's recorded revision, routed into every contract
    build (including Phase 1's module-level import of the builder)."""
    with PB.csv_tree(PINS[phase]["rev"]) as (root, tree_prov):
        with PB.pinned_contract_builds(root):
            original = P1.build_api_data_contract
            P1.build_api_data_contract = functools.partial(original, csv_root=root)
            try:
                yield tree_prov
            finally:
                P1.build_api_data_contract = original


# ── leaf-by-leaf reproduction check ───────────────────────────────────────


_BAND_LEAF = re.compile(r"level|starforpile|flag|fair|slight|lopsided|changed", re.IGNORECASE)


def _leaves(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _leaves(v, f"{path}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _leaves(v, f"{path}[{i}]")
    else:
        yield path, obj


def reproduction(recorded, rerun, *, label: str) -> dict:
    """Compare ``rerun`` (the v1_legacy run, JSON-normalised) with ``recorded``."""
    a = dict(_leaves(json.loads(json.dumps(recorded, default=str))))
    b = dict(_leaves(json.loads(json.dumps(rerun, default=str))))
    common = sorted(set(a) & set(b))
    diff = [p for p in common if a[p] != b[p]]
    # a leaf a fairness LEVEL can move (levels, level counts / transitions / changes, flags)
    lvl = [p for p in diff if _BAND_LEAF.search(p)]
    return {
        "section": label,
        "leavesRecorded": len(a),
        "leavesRerun": len(b),
        "leavesCompared": len(common),
        "leavesEqual": len(common) - len(diff),
        "onlyInRecorded": len(set(a) - set(b)),
        "onlyInRerun": len(set(b) - set(a)),
        "bandDependentLeavesDifferent": len(lvl),
        "differences": [{"path": p, "recorded": a[p], "rerun": b[p]} for p in diff[:60]],
    }


def _both(fn):
    """``{basis: fn()}`` for each basis, the band basis scoped around each call."""
    out = {}
    for basis in BASES:
        with P1.band_basis(basis):
            out[basis] = fn()
    return out


# ── Trade Finder: run once per model, re-tag on both bases ────────────────


def _replay_gap(models: dict, mid: str):
    """The gap ``FR.run`` tags with (closed-form geometric for the incumbent and
    the blends, exactly as ``FR.run`` builds its ``safe`` table)."""
    geom = FR._geom_exact_gap()
    if mid == "GEOM_78":
        return geom
    if mid.startswith("BLEND_G"):
        w = int(mid.split("_")[1][1:]) / 100.0
        ktc = models["KTC"]["gap"]
        return lambda a, b: w * geom(a, b) + (1 - w) * ktc(a, b)
    return models[mid]["gap"]


def _vals(side) -> list[float]:
    return [float(v) for _, v in side if isinstance(v, (int, float)) and v > 0]


def retag(replay: dict, models: dict, basis: str) -> tuple[dict, int]:
    """A copy of ``replay`` whose ``level`` / ``starForPile`` tags are on ``basis``
    (the preregistered rule of ``FR.classify``); the other tags are band-free and
    kept.  Returns ``(replay, tags_changed_vs_recorded_run)``."""
    out = json.loads(json.dumps(replay, default=str))
    changed = 0
    for mid, surfaces in out["raw"].items():
        gap = _replay_gap(models, mid)
        for teams in surfaces.values():
            for d in teams.values():
                for tr in d["trades"]:
                    tg = tr["tags"]
                    if not tg.get("priced"):
                        continue
                    give, recv = _vals(tr["give"]), _vals(tr["receive"])
                    star, pile = (give, recv) if max(give) >= max(recv) else (recv, give)
                    lvl = P1.band_level(mid, gap(recv, give), recv, give, basis=basis)
                    sfp = (
                        len(pile) >= 3
                        and all(v < 0.5 * max(star) for v in pile)
                        and lvl in ("fair", "slight")
                    )
                    changed += (lvl, sfp) != (tg["level"], tg["starForPile"])
                    tg["level"], tg["starForPile"] = lvl, sfp
    return out, changed


def _star_for_pile_examples(replay: dict, base: str = "GEOM_78") -> dict:
    out = {}
    for mid in replay["models"]:
        rows = []
        for s in replay["surfaces"]:
            for team in replay["teams"]:
                b = {t["key"] for t in replay["raw"][base][s][team]["trades"]}
                for t in replay["raw"][mid][s][team]["trades"]:
                    if t["tags"].get("starForPile"):
                        rows.append(
                            {
                                "surface": s,
                                "trade": t["key"],
                                "level": t["tags"]["level"],
                                "newVsIncumbent": t["key"] not in b,
                            }  # fmt: skip
                        )
        out[mid] = rows[:20]
    return out


def _replay_job(job):
    """One model's replay in a spawned worker, on the phase's pinned board."""
    phase, raw_path, mid = job
    models = P2.MODELS if phase == 2 else P3L.build_models()
    with pinned(phase):
        return FR.run(board_raw_path=Path(raw_path), models=models, model_ids=[mid], level=P2.level)


def finder_replay(phase: int, blob: bytes, model_ids: list[str], workers: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="pkg_v2_remeasure_") as tmp:
        raw_path = Path(tmp) / "dynasty_data_2026-10-19.json"
        raw_path.write_bytes(blob)
        jobs = [(phase, str(raw_path), m) for m in model_ids]
        ctx = multiprocessing.get_context("spawn")
        with ctx.Pool(max(1, min(workers, len(jobs)))) as pool:
            parts = pool.map(_replay_job, jobs)
    return P3L._merge(parts, model_ids)


def extracted_replay(paths: list[Path], model_ids: list[str]) -> tuple[dict, list[dict]]:
    """Merge Finder replays written by ``package_model_v2_remeasure_extract.py finder``."""
    parts, prov = [], []
    for p in paths:
        blob = Path(p).read_bytes()
        d = json.loads(blob)
        parts.append(d["replay"])
        prov.append({"file": Path(p).name, "sha256": hashlib.sha256(blob).hexdigest(),
                     "revision": d["revision"], "checkoutClean": d["checkoutClean"],
                     "models": d["replay"]["models"]})  # fmt: skip
    merged = P3L._merge(parts, model_ids)
    assert set(merged["raw"]) == set(model_ids), "the extracted replays must cover every model"
    return merged, prov


def finder_section(phase: int, blob: bytes, models: dict, model_ids, workers: int, recorded,
                   replay_json: list[Path] | None = None):  # fmt: skip
    if replay_json:
        replay, source = extracted_replay(replay_json, model_ids)
        source = {"engine": "recorded revision (extracted)", "files": source}
    else:
        replay = finder_replay(phase, blob, model_ids, workers)
        source = {"engine": "current checkout (pinned board inputs)"}
    per_basis, selfcheck = {}, None
    for basis in BASES:
        tagged, changed = retag(replay, models, basis)
        if basis == "v1_legacy":
            selfcheck = changed  # must be 0: the replay itself tagged on v1
        per_basis[basis] = {
            "comparison": FR.compare(tagged),
            "starForPile": _star_for_pile_examples(tagged),
        }
    return {
        "method": "each model replayed once (the engines read no band denominator); its trades "
        "re-tagged on each basis with FR.classify's preregistered rule",
        "models": model_ids,
        "replaySource": source,
        "timingsSec": replay["timingsSec"],
        "retagV1SelfCheckChangedTags": selfcheck,
        "reproduction": reproduction(
            recorded, per_basis["v1_legacy"]["comparison"], label="finder"
        ),
        **per_basis,
    }


# ── phases ────────────────────────────────────────────────────────────────


def extracted_board(path: Path | None) -> dict | None:
    """A board written by ``package_model_v2_remeasure_extract.py board``."""
    if path is None:
        return None
    blob = Path(path).read_bytes()
    d = json.loads(blob)
    d["provenance"] = {"source": "built by the recorded revision's own pipeline (extracted)",
                       "file": Path(path).name, "extractSha256": hashlib.sha256(blob).hexdigest(),
                       "revision": d["revision"], "checkoutClean": d["checkoutClean"],
                       "recordedRunProvenance": d["prov"]}  # fmt: skip
    return d


def phase1(args) -> dict:
    blob, src = raw_for(1)
    recorded = json.loads(PINS[1]["recorded"].read_text(encoding="utf-8"))
    ext = extracted_board(args.board_json)
    if ext is not None:
        return _phase1_run(args, recorded, ext["board"], ext["tradeRows"], ext["tradeCensus"],
                           {**src, **ext["provenance"], "pricedAssets": len(ext["board"]["rows"]),
                            "builtBoardSha256": PB.built_board_sha256(ext["board"]["rows"])},
                           {"held": False, "reason": "recorded-revision board carries the recorded value"})  # fmt: skip
    trades_file = Path(tempfile.mkdtemp(prefix="pkg_v2_trades_")) / "sleeper_last_good.json"
    trades_file.write_bytes(_git_bytes(PINS[1]["rev"], "data/sleeper_last_good.json"))
    saved_trades = P1.TRADES
    P1.TRADES = trades_file
    try:
        with pinned(1) as tree:
            board = P1.build_board(json.loads(blob))
            held = hold_hunter(board["rows"], 1)
            rows, census = P1.trade_rows(7.0)
            prov = {**src, "csvTree": tree, "source": "built by the current pipeline",
                    "pricedAssets": len(board["rows"]),
                    "builtBoardSha256": PB.built_board_sha256(board["rows"])}  # fmt: skip
            return _phase1_run(args, recorded, board, rows, census, prov, held)
    finally:
        P1.TRADES = saved_trades


def _phase1_run(args, recorded, board, rows, census, prov, held) -> dict:
    p = P1.pools(board)
    per_cell = 60 if args.quick else 400
    t = time.time()
    worked = _both(lambda: P1.worked_examples(board))
    history = _both(
        lambda: P1.trade_evidence(rows, seed=7, detail=False)["tradeHistoryLevelChangesVsIncumbent"]
    )
    matrix = _both(lambda: P1.aggregate_matrix(P1.run_matrix(p, per_cell, seed=20261019)))
    elapsed = round(time.time() - t, 1)
    rec_m = recorded["matrix"]["aggregates"]
    return {
        "phase": 1,
        "memo": "docs/valuation/PACKAGE_MODEL_HYBRID_RESEARCH_2026-10-19.md",
        "board": prov,
        "hunter": held,
        "ownLeagueTradeCensus": census,
        "perCell": per_cell,
        "elapsedSec": elapsed,
        "reproduction": [
            reproduction(recorded["workedExamples"], worked["v1_legacy"], label="workedExamples"),
            reproduction(
                recorded["trades"]["tradeHistoryLevelChangesVsIncumbent"],
                history["v1_legacy"],
                label="tradeHistoryLevelChangesVsIncumbent",
            ),
            reproduction(rec_m, matrix["v1_legacy"], label="matrix.aggregates"),
        ],
        "workedExamples": worked,
        "tradeHistoryLevelChangesVsIncumbent": history,
        "matrixAggregates": matrix,
    }


def phase2(args) -> dict:
    blob, src = raw_for(2)
    recorded = json.loads(PINS[2]["recorded"].read_text(encoding="utf-8"))
    ext = extracted_board(args.board_json)
    if ext is not None:
        board = ext["board"]
        prov = {**src, **ext["provenance"]}
        held = {"held": False, "reason": "recorded-revision board carries the recorded value"}
    else:
        with pinned(2) as tree:
            board = P1.build_board(json.loads(blob))
        prov = {**src, "csvTree": tree, "source": "built by the current pipeline"}
        held = hold_hunter(board["rows"], 2)
    prov.update(
        pricedAssets=len(board["rows"]), builtBoardSha256=PB.built_board_sha256(board["rows"])
    )
    out = {
        "depthVsFiller": _both(P2.depth_vs_filler),
        "asymmetric": _both(P2.asymmetric),
        "realExamples": _both(lambda: P2.real_examples(board)),
    }
    lp = recorded["largePackage"]
    rep = [
        reproduction(
            lp.get("depthVsFiller"), out["depthVsFiller"]["v1_legacy"], label="depthVsFiller"
        ),
        reproduction(lp.get("asymmetric"), out["asymmetric"]["v1_legacy"], label="asymmetric"),
        reproduction(
            recorded["realExamples"], out["realExamples"]["v1_legacy"], label="realExamples"
        ),
    ]
    res = {
        "phase": 2,
        "hunter": held,
        "memo": "docs/valuation/PACKAGE_MODEL_PHASE2_RESEARCH_2026-10-19.md",
        "board": prov,
        "reproduction": rep,
        **out,
    }
    if args.finder or args.finder_json:
        res["finder"] = finder_section(
            2,
            blob,
            P2.MODELS,
            FR.DEFAULT_MODELS,
            args.workers,
            recorded["finder"]["comparison"],
            replay_json=args.finder_json,
        )
    return res


def phase3(args) -> dict:
    blob, src = raw_for(3)
    recorded = json.loads(PINS[3]["recorded"].read_text(encoding="utf-8"))
    models = P3L.build_models()
    with pinned(3) as tree:
        rows = P3L.load_board(json.loads(blob))
        held = hold_hunter(rows, 3)
        out = {
            "realExamples": _both(lambda: P3L.real_examples(models, rows)),
            "fairnessSample": _both(lambda: P3L.fairness_sample(models, rows, n=2000)),
        }
    rep = [
        reproduction(
            recorded["C_realExamples"], out["realExamples"]["v1_legacy"], label="C_realExamples"
        ),
        reproduction(
            recorded["D_decisions"]["fairnessSample"],
            out["fairnessSample"]["v1_legacy"],
            label="D_decisions.fairnessSample",
        ),
    ]
    res = {
        "phase": 3,
        "hunter": held,
        "memo": "docs/valuation/PACKAGE_MODEL_PHASE3_RESEARCH_2026-10-20.md",
        "board": {**src, "csvTree": tree, "pricedAssets": len(rows)},
        "boxOnly": "production_phase3_run_2026-10-20.json / production_ledger_run_2026-10-20.json "
        "(the 18,690-trade box ledger) classify no fairness band: residuals, calibration, "
        "selections and confirmation are band-independent.  Not re-run (box-only); see the memo.",
        "reproduction": rep,
        **out,
    }
    if args.finder:
        order = [P3L.INCUMBENT] + [m for m in P3L.ALL_MODELS if m != P3L.INCUMBENT]
        res["finder"] = finder_section(
            3,
            blob,
            models,
            order,
            args.workers,
            recorded["D_decisions"]["finderReplay"]["comparisonVsIncumbent"],
        )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--phase", choices=["1", "2", "3", "all"], default="all")
    ap.add_argument("--finder", action="store_true", help="also replay the Trade Finder surfaces")
    ap.add_argument("--workers", type=int, default=3, help="parallel finder-replay processes")
    ap.add_argument("--quick", action="store_true", help="Phase 1 matrix at 60 cases per cell")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument(
        "--board-json",
        type=Path,
        default=None,
        help="phase 1/2: board (and Phase 1 trade rows) from package_model_v2_remeasure_extract.py",
    )
    ap.add_argument(
        "--finder-json",
        type=Path,
        nargs="*",
        default=None,
        help="phase 2: Finder replays from package_model_v2_remeasure_extract.py (re-tagged here)",
    )
    args = ap.parse_args()
    assert pm.active_model_id() == pm.GEOM_Q078_V1, "the incumbent must be the active model"
    out = REPO / args.out
    assert "package_model_v2_remeasure" in out.name, "never write into an original evidence dir"
    out.mkdir(parents=True, exist_ok=True)
    phases = [1, 2, 3] if args.phase == "all" else [int(args.phase)]
    for ph in phases:
        t0 = time.time()
        res = {1: phase1, 2: phase2, 3: phase3}[ph](args)
        res.update(
            {
                "purpose": "RESEARCH ONLY. v1_legacy reproduces the recorded evidence; current is "
                "fairness_bands_v2. geom_q078_v1 stays active; nothing is promoted.",
                "generatedBy": "scripts/package_model_v2_remeasure.py",
                "codeSha": P1._git_sha(),
                "fairnessBands": fairness_bands.receipt(),
                "activeModelAtRun": pm.active_model_id(),
                "totalSec": round(time.time() - t0, 1),
            }
        )
        P2.assert_aggregate_only(
            {k: v for k, v in res.items() if k not in ("board", "codeSha", "fairnessBands")}
        )
        suffix = "_quick" if args.quick and ph == 1 else ""
        (out / f"phase{ph}{suffix}.json").write_text(
            json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8"
        )
        print(json.dumps({"phase": ph, "sec": res["totalSec"],
                          "reproduction": [(r["section"], r["leavesEqual"], r["leavesCompared"])
                                           for r in res["reproduction"]]}))  # fmt: skip
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
