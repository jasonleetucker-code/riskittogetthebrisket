#!/usr/bin/env python3
"""Fail when a decision path coerces missing data to a number.

WHY THIS EXISTS
---------------
The 2026-08-04 audit's largest cross-cutting pattern, present in
**every** subsystem it examined:

    "Missing data resolves to an optimistic, neutral or fabricated
     value instead of abstention."

Concretely — a team absent from a sim file becomes ``or 0.0`` playoff
odds and is labelled *Seller*, and the roster that happens to is ranked
#1 in the league.  An unknown FAAB budget becomes ``or 100``.  An
unresolvable asset is priced at ``1.0`` and publicly graded a fleecing
with the losing manager named.  An unpriced player is promoted into the
Value column via ``|| rawValues.full``.

Every one of those is the same three characters.  A review convention
does not catch them — the audit found them *after* they shipped, and
they had been reviewed.  So this is a gate.

HOW IT RATCHETS
---------------
Enforcing repo-wide on day one would block every PR on a pre-existing
backlog, which is how the ruff lint gate was (correctly) narrowed
before #708 cleared it.  So:

  * ``coercion_baseline.json`` records every KNOWN violation.
  * A violation not in the baseline fails the build.  That is the
    ratchet: new coercions cannot land.
  * A baseline entry that no longer matches also fails, with a message
    saying to remove it.  An allowance nobody can check is how the
    ``_LIVEDATA_MODULES`` exemption hid 33 core-blend tests from the
    gate for months; the same discipline applies here.

Each remediation batch deletes its findings' entries from the baseline.
When the file is empty the ``--strict`` default flips and the gate is
unconditional.

WHAT COUNTS AS A DECISION PATH
------------------------------
``_DECISION_ROOTS`` — the modules that produce a number or a label a
user acts on.  Deliberately not the whole repo: ``or 0`` in a log line
or a progress counter is not a decision, and a gate that cries about
those gets switched off.

Exit codes: 0 clean, 1 violations, 2 error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE = REPO_ROOT / "config" / "coercion_baseline.json"

# Roots whose output a user acts on.  server.py and data_contract.py are
# named explicitly because they are the two largest decision surfaces in
# the repo.
_DECISION_ROOTS = (
    "server.py",
    "src/api",
    "src/trade",
    "src/ros",
    "src/league_intel",
    "src/roster_intel",
    "src/sharp",
    "src/intel",
    "src/bdvm",
    "src/news",
    "src/public_league",
    "src/canonical",
    "src/scoring",
    "frontend/lib",
)

# Numeric-literal coercions only.  ``x or []`` and ``x || {}`` are
# structural defaults, not fabricated quantities — they cannot be
# mistaken for a measurement.  ``or 0``-style on a NUMBER can.
_PY_PATTERN = re.compile(r"\bor\s+(?:0\.0|0|1\.0|1|100|100\.0)\b(?!\s*[.\w])")
_JS_PATTERN = re.compile(r"(?:\|\||\?\?)\s*(?:0\.0|0|1\.0|1|100)\b(?!\s*[.\w])")

_SUFFIXES = {".py": _PY_PATTERN, ".js": _JS_PATTERN, ".jsx": _JS_PATTERN}


def _iter_files() -> list[Path]:
    out: list[Path] = []
    for root in _DECISION_ROOTS:
        p = REPO_ROOT / root
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for suffix in _SUFFIXES:
                out.extend(sorted(p.rglob(f"*{suffix}")))
    return sorted(set(out))


def _scan() -> list[dict]:
    found: list[dict] = []
    for path in _iter_files():
        pattern = _SUFFIXES.get(path.suffix)
        if pattern is None:
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            # Prose about a coercion is not a coercion.  The repo
            # documents these defects extensively in comments, and this
            # file's own docstring would otherwise trip it.
            if stripped.startswith(("#", "//", "*", '"""', "'''")):
                continue
            for m in pattern.finditer(line):
                found.append(
                    {
                        "file": rel,
                        "line": n,
                        "match": m.group(0).strip(),
                        "text": stripped[:120],
                    }
                )
    return found


def _key(v: dict) -> str:
    """Identify a violation by file + code, NOT by line number.

    Line-keyed baselines rot on the first unrelated edit above them and
    then have to be regenerated wholesale, which quietly re-blesses
    anything added in between.
    """
    return f"{v['file']}::{v['text']}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--write-baseline",
        action="store_true",
        help="record current violations as accepted debt (use once, at gate introduction)",
    )
    args = ap.parse_args()

    found = _scan()
    by_key: dict[str, dict] = {_key(v): v for v in found}

    if args.write_baseline:
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(
            json.dumps(
                {
                    "note": (
                        "Known missing-data coercions on decision paths, recorded so the "
                        "gate can block NEW ones while the remediation batches burn these "
                        "down. Each batch deletes its findings' entries. Do not add to "
                        "this file to make a build pass."
                    ),
                    "count": len(by_key),
                    "violations": sorted(by_key),
                },
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"baseline written: {len(by_key)} accepted violations -> {BASELINE.name}")
        return 0

    if not BASELINE.exists():
        print(f"error: {BASELINE} missing — run --write-baseline once", file=sys.stderr)
        return 2
    accepted = set(json.loads(BASELINE.read_text(encoding="utf-8")).get("violations") or [])

    new = sorted(set(by_key) - accepted)
    stale = sorted(accepted - set(by_key))

    print(f"decision-path coercions: {len(by_key)} present, {len(accepted)} accepted as debt")
    if new:
        print(f"\nNEW ({len(new)}) — a decision path may not fabricate a number:")
        for k in new[:40]:
            v = by_key[k]
            print(f"  {v['file']}:{v['line']}  {v['match']}")
            print(f"      {v['text']}")
    if stale:
        print(f"\nSTALE BASELINE ENTRIES ({len(stale)}) — fixed; delete them from the baseline:")
        for k in stale[:40]:
            print(f"  {k[:110]}")

    if new or stale:
        return 1
    print("\nclean: no new coercions, no stale allowances.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
