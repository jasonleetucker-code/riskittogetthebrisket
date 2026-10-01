#!/usr/bin/env python3
"""Replay, verify and export pinned Hill training runs. Never promotes, never applies.

    # refit from every input as it stood at a commit (or the newest commit at or
    # before a cutoff) and print the challenger hash
    python scripts/hill_training_run.py replay --commit <sha> [--out run.json]
    python scripts/hill_training_run.py replay --cutoff 2026-09-30T13:00:00+00:00

    # re-derive a recorded challenger from its own pins and compare hashes
    python scripts/hill_training_run.py verify <version>
    python scripts/hill_training_run.py verify --latest-raw

    # write a recorded challenger's training run out as a run artifact
    python scripts/hill_training_run.py show <version> --out run.json

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
from src.model_registry.training_run import TrainingRunError, replay  # noqa: E402
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
    same = again.challenger_hash == run.get("challengerHash")
    print(f"v{version.version} recorded  {run.get('challengerHash')}")
    print(f"v{version.version} replayed  {again.challenger_hash}")
    if not same:
        diffs = [
            k
            for k in ("manifestHash", "codeHash", "snapshot", "inputs", "params")
            if (again.record.get(k) if k != "params" else again.params)
            != (run.get(k) if k != "params" else version.params)
        ]
        print(f"NOT REPRODUCED — differing pins: {diffs}", file=sys.stderr)
        return 1
    print("REPRODUCED — identical challenger hash from the recorded pins")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    version = _version(args)
    if not version.training_run:
        print(f"ERROR: v{version.version} carries no training run", file=sys.stderr)
        return 2
    _write(args.out, version.training_run)
    if args.out is None:
        print(json.dumps(version.training_run, indent=2, sort_keys=True))
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
