#!/usr/bin/env python3
"""Replay, verify and export pinned Hill training runs. Never promotes, never applies.

    # refit from every input as it stood at a commit (or the newest commit at or
    # before a cutoff) and print the challenger hash
    python scripts/hill_training_run.py replay --commit <sha> [--out run.json]
    python scripts/hill_training_run.py replay --cutoff 2026-09-30T13:00:00+00:00

    # re-derive a recorded challenger from its own pins and compare hashes AND
    # parameters (a composite: its source run, and its OFFENSE pair)
    python scripts/hill_training_run.py verify <version>
    python scripts/hill_training_run.py verify --latest-raw

    # write a recorded challenger's full training run (from its committed
    # artifact, integrity-checked) out as a file
    python scripts/hill_training_run.py show <version> --out run.json

    # delete run artifacts no registry entry still needs (retention)
    python scripts/hill_training_run.py prune [--max-age-days 30]

Exit codes: 0 ok / reproduced; 1 a replay did NOT reproduce the recorded
challenger; 2 error (missing pins, unreadable registry, refused run).

Nothing here writes ``player_valuation.py`` or the registry. A replay that reads
post-cutoff data is impossible by construction: the inputs are materialized from
a commit at or before the cutoff into a temporary directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.model_registry.hill_masters import load_or_seed_registry  # noqa: E402
from src.model_registry.training_run import (  # noqa: E402
    TrainingRunError,
    load_training_run,
    prune_training_runs,
    replay,
    verify_against_replay,
)
from src.model_registry.versioning import RegistryError  # noqa: E402

RAW_PRODUCER_PREFIX = "scripts/fit_hill_curve_percentile.py"


def _cutoff(text: str | None) -> datetime | None:
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _write(path: Path | None, blob: dict) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmd_replay(args: argparse.Namespace) -> int:
    run = replay(commit=args.commit, cutoff=_cutoff(args.cutoff))
    _write(args.out, run.record)
    print(f"challengerHash {run.challenger_hash}")
    print(f"pinsHash       {run.record['pinsHash']}")
    print(f"modelHash      {run.record['modelHash']}")
    print(f"cutoff         {run.record['trainingCutoff']}")
    print(f"origin         {run.record['inputsOrigin']}")
    for name, value in sorted(run.params.items()):
        print(f"  {name} = {value}")
    return 0


def _version(args: argparse.Namespace):
    reg = load_or_seed_registry()
    if getattr(args, "latest_raw", False):
        raw = [
            v
            for v in reg.versions
            if v.training_run and str(v.producer).startswith(RAW_PRODUCER_PREFIX)
        ]
        if not raw:
            raise RegistryError("no raw challenger with a training run is recorded")
        return raw[-1]
    return reg.get(args.version)


def cmd_verify(args: argparse.Namespace) -> int:
    version = _version(args)
    run = version.training_run or {}
    commit, cutoff = run.get("inputsCommit"), run.get("trainingCutoff")
    if not run or not commit or not cutoff or run.get("reproducible") is not True:
        print(
            f"ERROR: v{version.version} carries no reproducible training run "
            "(inputsCommit + trainingCutoff); it cannot be re-derived from its record",
            file=sys.stderr,
        )
        return 2
    snapshot_rel = (run.get("snapshot") or {}).get("path")
    again = replay(commit=commit, cutoff=_cutoff(cutoff), snapshot_rel=snapshot_rel)
    composed = run.get("composedFrom") is not None
    target = run.get("sourceChallengerHash") if composed else run.get("challengerHash")
    print(f"v{version.version} recorded  {target}" + (" (source run)" if composed else ""))
    print(f"v{version.version} replayed  {again.challenger_hash}")
    problems = verify_against_replay(version.params, run, again)
    if problems:
        try:
            full = load_training_run(run)
            pins = [
                k
                for k in ("manifestHash", "codeHash", "snapshot", "inputs", "trainingContent")
                if again.record.get(k) != full.get(k)
            ]
        except TrainingRunError as exc:
            pins = [f"(full record unavailable: {exc})"]
        for problem in problems:
            print(f"NOT REPRODUCED — {problem}", file=sys.stderr)
        print(f"differing pins: {pins}", file=sys.stderr)
        return 1
    if composed:
        print(
            f"REPRODUCED — composite of raw v{run['composedFrom']}: the source run replays "
            "to its recorded hash and the OFFENSE pair matches; GLOBAL/IDP/ROOKIE are the "
            "incumbent's and were not produced by this run"
        )
    else:
        print("REPRODUCED — identical challenger hash and parameters from the recorded pins")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    version = _version(args)
    if not version.training_run:
        print(f"ERROR: v{version.version} carries no training run", file=sys.stderr)
        return 2
    record = load_training_run(version.training_run)
    _write(args.out, record)
    if args.out is None:
        print(json.dumps(record, indent=2, sort_keys=True))
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    removed = prune_training_runs(load_or_seed_registry().versions, max_age_days=args.max_age_days)
    for rel in removed:
        print(f"pruned {rel}")
    print(f"{len(removed)} training-run artifact(s) pruned")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("replay", help="refit from git at a commit or cutoff")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--commit")
    g.add_argument("--cutoff", help="ISO 8601, timezone-aware")
    p.add_argument("--out", type=Path)
    p.set_defaults(fn=cmd_replay)

    for name, fn, helptext in (
        ("verify", cmd_verify, "replay a recorded challenger and compare hashes"),
        ("show", cmd_show, "export a recorded challenger's training run"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("version", type=int, nargs="?")
        p.add_argument("--latest-raw", action="store_true")
        if name == "show":
            p.add_argument("--out", type=Path)
        p.set_defaults(fn=fn)

    p = sub.add_parser("prune", help="delete run artifacts no registry entry still needs")
    p.add_argument("--max-age-days", type=float, default=30.0)
    p.set_defaults(fn=cmd_prune)

    args = ap.parse_args()
    if args.cmd in ("verify", "show") and args.version is None and not args.latest_raw:
        ap.error(f"{args.cmd} needs a version or --latest-raw")
    try:
        return int(args.fn(args))
    except (TrainingRunError, RegistryError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
