#!/usr/bin/env python3
"""Build the outlier-integrity-v2.1 population manifest (DEV / R pins / SPENT).

usage (from the repository root):
    python docs/sources/outlier_integrity_v21/manifests/build_populations.py [--check] [--at COMMIT]

Read-only over git objects and the committed V2 manifests.  It writes
``POPULATIONS.json`` beside this file:

* ``DEV`` -- V2's E_BASELINE (35) + E_DEV (44) boards, copied from the V2 manifests
  after their sha256 is checked against V2's ``INDEX.json``.  The ONLY boards on
  which V2.1 may develop or select thresholds (V2.1 preregistration section 5).
* ``R_PIN`` -- must-pass constraints, never evidence: pin2015, pin0527 (V2's R pins)
  and pinOB, the board behind the owner's Option-B freshness fixture.
* ``SPENT`` -- every board V2 registered as held-out or independent (V_HELDOUT 61,
  I_INDEPENDENT 7), V2's EXCLUDED board, and every archive added to ``main`` after
  the V2 preregistration anchor and up to ``--at`` (V2's prospective I window),
  except pinOB.  A SPENT board is never built, scored or read by V2.1.

The fresh held-out set is NOT listed here: it does not exist yet.  It is selected
at Stage 4 by the rule in ``HELDOUT_RULE.json`` (boards added after the V2.1
preregistration commit).  Any archive added at or before that commit and absent
from this file is SPENT by rule.

``--check`` rebuilds in memory and exits 1 if the committed file differs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
V2 = REPO / "docs/sources/outlier_integrity_v2/manifests"
SCHEMA = "oiv21-population-manifest/v1"
V2_ANCHOR = "3c69945723631c2d14023e3bd064fd669b116ef1"  # V2 preregistration commit
PIN_OB = "dynasty_export_20261020_121619.zip"
OUT = HERE / "POPULATIONS.json"


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True).stdout


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def v2_boards(name: str) -> list[dict]:
    index = json.loads((V2 / "INDEX.json").read_text())
    want = index["files"][f"{name}.json"]["sha256"]
    got = sha256_file(V2 / f"{name}.json")
    if got != want:
        raise SystemExit(f"V2 manifest {name}.json sha256 {got} != INDEX {want}")
    return json.loads((V2 / f"{name}.json").read_text())["boards"]


def board_entry(name: str, at: str) -> dict:
    out = git(
        "log", "--diff-filter=A", "--format=%H %cI", "-1", at, "--", f"exports/archive/{name}"
    )
    commit, when = out.decode().split()
    raw = git("show", f"{commit}:exports/archive/{name}")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    members = [m for m in zf.namelist() if m.endswith(".json") and "dynasty_data_" in m]
    payload_blob = zf.read(members[0])
    payload = json.loads(payload_blob)
    sys.path.insert(0, str(REPO))
    from tests.archive_fixtures import _degraded_critical_sources

    degraded = sorted(_degraded_critical_sources(payload))
    return {
        "board": name,
        "addCommit": commit,
        "addCommitTime": when,
        "zipSha256": hashlib.sha256(raw).hexdigest(),
        "payloadSha256": hashlib.sha256(payload_blob).hexdigest(),
        "scrapeTimestamp": payload.get("scrapeTimestamp"),
        "complete": not degraded,
        "degraded": degraded,
    }


def post_v2_anchor_boards(at: str) -> list[str]:
    anchor_time = git("log", "-1", "--format=%cI", V2_ANCHOR).decode().strip()
    out = git(
        "log",
        "--diff-filter=A",
        "--name-only",
        "--format=",
        f"--since={anchor_time}",
        at,
        "--",
        "exports/archive/",
    )
    names = sorted({Path(n).name for n in out.decode().split() if n.endswith(".zip")})
    return names


def build(at: str) -> dict:
    dev = []
    for pop in ("E_BASELINE", "E_DEV"):
        for b in v2_boards(pop):
            dev.append({**b, "v2Population": pop})
    spent = []
    for pop in ("V_HELDOUT", "I_INDEPENDENT", "EXCLUDED"):
        for b in v2_boards(pop):
            spent.append({**b, "v2Population": pop, "spentReason": f"V2 {pop}"})
    v2_names = {b["board"] for b in dev + spent}
    for b in v2_boards("R_REGRESSION_PIN"):
        v2_names.add(b["board"])
    prospective = [n for n in post_v2_anchor_boards(at) if n not in v2_names]
    pins = [
        {
            "pin": "pin2015",
            "board": "dynasty_export_20261019_201546.zip",
            "source": "V2 R_REGRESSION_PIN",
        },
        {
            "pin": "pin0527",
            "board": None,
            "refreshCommit": "eb10d3e12d",
            "payloadSha256Prefix": "b639608f",
            "source": "V2 R_REGRESSION_PIN",
        },
    ]
    for name in prospective:
        entry = board_entry(name, at)
        if name == PIN_OB:
            pins.append(
                {
                    "pin": "pinOB",
                    **entry,
                    "source": "owner decision 2026-10-20 (#1831 Option B) item 6: the board behind "
                    "tests/fixtures/outlier_integrity_v2/freshness_v2_affected_rows_2026-10-20.json",
                    "note": "V2-prospective-I board used only as an owner-mandated must-pass constraint; never evidence",
                }
            )
        else:
            spent.append(
                {
                    **entry,
                    "v2Population": "I_INDEPENDENT (prospective, section 5.4)",
                    "spentReason": "added after the V2 preregistration anchor; V2's prospective independent window",
                }
            )
    for p in (dev, spent):
        p.sort(key=lambda b: b["board"])
    return {
        "schema": SCHEMA,
        "builtAt": at,
        "v2Anchor": V2_ANCHOR,
        "counts": {"DEV": len(dev), "R_PIN": len(pins), "SPENT": len(spent)},
        "rule": "any archive added to main at or before the V2.1 preregistration commit and absent from this file is SPENT",
        "DEV": dev,
        "R_PIN": pins,
        "SPENT": spent,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--at",
        default=None,
        help="commit to read archives from (default: builtAt of the committed file, else origin/main)",
    )
    args = ap.parse_args()
    at = args.at
    if at is None and OUT.exists():
        at = json.loads(OUT.read_text())["builtAt"]
    if at is None:
        at = git("rev-parse", "origin/main").decode().strip()
    text = json.dumps(build(at), indent=1, sort_keys=False) + "\n"
    if args.check:
        same = OUT.exists() and OUT.read_text() == text
        print("POPULATIONS.json up to date" if same else "POPULATIONS.json differs")
        return 0 if same else 1
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
