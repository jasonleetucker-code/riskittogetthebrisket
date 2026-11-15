#!/usr/bin/env python3
"""Build the frozen outlier-integrity-v2 test-population manifests.

usage (from the repository root, at the preregistration commit's parent):
    python docs/sources/outlier_integrity_v2/manifests/build_manifests.py [--check] [--at COMMIT]

``--at`` defaults to ``1511ca1d08dfffad4b48d113b2ac9a20d7a5de4b`` (origin/main when
the populations were frozen; the preregistration commit's parent).  Later archives
are NOT added here: they join I_INDEPENDENT through the prospective shadow window
described in the preregistration (§5.4), with their own add-commit and hashes.

Read-only over git objects.  Every board's zip is read from the commit that
ADDED it (so boards pruned from the working tree are recovered byte-exact), its
zip sha256 and payload sha256 (the ``dynasty_data_*.json`` member, the
convention of ``docs/valuation/evidence/idp-outlier-n3-2026-10-18/
ARCHIVE_MANIFEST.json``) are computed, and the 140 frozen boards are checked
against that manifest.  Completeness of the boards added after the frozen
manifest uses the same rule the frozen manifest used
(``tests.archive_fixtures._degraded_critical_sources``).

``--check`` rebuilds in memory and exits 1 if any committed manifest differs.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import zipfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
FROZEN = "docs/valuation/evidence/idp-outlier-n3-2026-10-18/ARCHIVE_MANIFEST.json"
SCHEMA = "oiv2-population-manifest/v1"

GATE_BOARD = "dynasty_export_20261018_114711.zip"
GATE_PRIOR = "dynasty_export_20261018_051224.zip"
H2_STRESS = ("20261007_092552", "20261008_141213", "20261016_134010")
EXCLUDED = {
    "dynasty_export_20261019_052349.zip": "V1 diagnosis board (design contact; contaminated)"
}
PIN2015 = "dynasty_export_20261019_201546.zip"

ANCHOR = "1511ca1d08dfffad4b48d113b2ac9a20d7a5de4b"
AT = ANCHOR
POPULATIONS = ("E_BASELINE", "E_DEV", "V_HELDOUT", "I_INDEPENDENT", "R_REGRESSION_PIN", "EXCLUDED")


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True).stdout


def add_commit(name: str) -> str:
    out = git("log", "--diff-filter=A", "--format=%H", "-1", AT, "--", f"exports/archive/{name}")
    sha = out.decode().strip()
    if not sha:
        raise SystemExit(f"no add commit for {name}")
    return sha


def read_board(name: str) -> tuple[str, bytes, bytes, dict]:
    commit = add_commit(name)
    raw = git("show", f"{commit}:exports/archive/{name}")
    zf = zipfile.ZipFile(io.BytesIO(raw))
    members = sorted(
        n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
    )
    if not members:
        raise SystemExit(f"{name}: no dynasty_data_*.json member")
    payload = zf.read(members[0])
    return commit, raw, payload, json.loads(payload)


def labelled_cases(stamp: str) -> list[str]:
    """Case ids from HISTORY_CASES.json (labels fixed before any V2 evaluation)."""
    out: list[str] = []
    day = stamp[:8]
    if "20260818" <= day <= "20260908":
        out.append("H1")
    if stamp in H2_STRESS:
        out += ["H2", "H3"]
    if stamp.startswith("20260803_2356"):
        out += ["H3", "H4"]
    if stamp.startswith("20260806"):
        out.append("H4")
    if "20260917_2149" <= stamp <= "20260922_2143":
        out.append("H5")
    if day == "20260820":
        out.append("N1")
    if day in ("20260826", "20260827", "20260830"):
        out.append("N2")
    if stamp >= "20260924_232149":
        out.append("N3")
    return out


def build() -> dict[str, dict]:
    sys.path.insert(0, str(REPO))
    from tests.archive_fixtures import _degraded_critical_sources  # noqa: PLC0415

    frozen = json.loads(git("show", f"{AT}:{FROZEN}"))
    frozen_by_name = {b["board"]: b for b in frozen["boards"]}
    names = sorted(
        {
            n.decode().rsplit("/", 1)[-1]
            for n in git("ls-tree", "--name-only", AT, "exports/archive/").split()
        }
        | set(frozen_by_name)
    )
    names = [n for n in names if n.startswith("dynasty_export_") and n.endswith(".zip")]
    boards: list[dict] = []
    for name in names:
        commit, raw, payload_blob, payload = read_board(name)
        stamp = name[len("dynasty_export_") : -len(".zip")]
        ent: dict = {
            "board": name,
            "addCommit": commit,
            "zipSha256": hashlib.sha256(raw).hexdigest(),
            "payloadSha256": hashlib.sha256(payload_blob).hexdigest(),
            "scrapeTimestamp": payload.get("scrapeTimestamp"),
        }
        fz = frozen_by_name.get(name)
        if fz is not None:
            for k in ("zipSha256", "payloadSha256"):
                if fz[k] != ent[k]:
                    raise SystemExit(f"{name}: {k} differs from the frozen V1 manifest")
            ent["complete"] = bool(fz["complete"])
            ent["degraded"] = list(fz.get("degraded") or [])
            ent["inFrozenV1Manifest"] = True
            ent["inWorkingTree"] = bool(git("ls-tree", AT, f"exports/archive/{name}").strip())
            if not ent["complete"]:
                pop = "E_BASELINE"
            elif stamp[:8] <= "20260930":
                pop = "E_DEV"
            else:
                pop = "V_HELDOUT"
        else:
            degraded = _degraded_critical_sources(payload)
            ent["complete"] = not degraded
            ent["degraded"] = degraded
            ent["inFrozenV1Manifest"] = False
            ent["inWorkingTree"] = True
            if name in EXCLUDED:
                pop = "EXCLUDED"
                ent["reason"] = EXCLUDED[name]
            elif name == PIN2015:
                pop = "R_REGRESSION_PIN"
                ent["reason"] = (
                    "pin2015: section-6 primary acceptance input; every V2 candidate's feasibility "
                    "numbers were computed on it, so it is a must-pass constraint, never evidence"
                )
            else:
                pop = "I_INDEPENDENT"
                ent["reason"] = "added after the frozen V1 manifest; no V2 design contact"
        roles: list[str] = []
        if name == GATE_BOARD:
            roles.append("REGISTERED_GATE_BOARD(seed 2033)")
        if name == GATE_PRIOR:
            roles.append("REGISTERED_GATE_PRIOR_HISTORY")
        if stamp in H2_STRESS:
            roles.append("STRESS_LABELLED_BEFORE_DESIGN(not independent evidence)")
        ent["population"] = pop
        ent["roles"] = roles
        ent["labelledCases"] = labelled_cases(stamp)
        boards.append(ent)

    out: dict[str, dict] = {}
    for pop in POPULATIONS:
        sel = [b for b in boards if b["population"] == pop]
        out[pop] = {"schema": SCHEMA, "population": pop, "count": len(sel), "boards": sel}
    regression = {
        "schema": SCHEMA,
        "population": "R_REGRESSION_PIN",
        "count": 3,
        "pins": [
            {
                "pin": "pin2015",
                "archive": PIN2015,
                "refreshCommit": "d9680440a5",
                "payloadPath": "exports/latest/dynasty_data_2026-10-19.json",
                "payloadSha256": "3ef54acda8c1062f96d02692fc22ea8ebc7e8f9bc38168359efac60675119199",
                "use": "boards A/B/C/D and A'/B'/C'/D'; the 31 IDP votes; the D4 newly-dropped offense votes",
            },
            {
                "pin": "pin0527",
                "archive": None,
                "refreshCommit": "eb10d3e12d",
                "payloadPath": "exports/latest/dynasty_data_2026-10-19.json",
                "payloadSha256Prefix": "b639608f",
                "use": "reproduction input of the documented 31/18/10/3 and the seven 34-54% movers",
            },
            {
                "pin": "d4_newest_I",
                "archive": "the newest I_INDEPENDENT board at evaluation time",
                "use": "D4 newly-dropped offense votes recomputed on an independent board (reported)",
            },
        ],
        "boards": out["R_REGRESSION_PIN"]["boards"],
    }
    out["R_REGRESSION_PIN"] = regression
    return out


def write(out: dict[str, dict], check: bool) -> int:
    index = {"schema": SCHEMA, "builtFrom": AT, "files": {}}
    bad = 0
    for pop, body in out.items():
        path = HERE / f"{pop}.json"
        text = json.dumps(body, indent=1, sort_keys=True) + "\n"
        index["files"][path.name] = {
            "count": body["count"],
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        if check:
            if not path.exists() or path.read_text() != text:
                print(f"DIFFERS: {path.name}")
                bad += 1
        else:
            path.write_text(text)
    index["countsByPopulation"] = {p: b["count"] for p, b in out.items()}
    index["completeCounts"] = dict(
        Counter(
            f"{b['population']}:{b['complete']}" for body in out.values() for b in body["boards"]
        )
    )
    itext = json.dumps(index, indent=1, sort_keys=True) + "\n"
    ipath = HERE / "INDEX.json"
    if check:
        if not ipath.exists() or ipath.read_text() != itext:
            print("DIFFERS: INDEX.json")
            bad += 1
    else:
        ipath.write_text(itext)
    print(json.dumps(index["countsByPopulation"]))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--at", default=ANCHOR, help="commit the populations are frozen at")
    args = ap.parse_args()
    global AT
    AT = args.at
    return write(build(), args.check)


if __name__ == "__main__":
    sys.exit(main())
