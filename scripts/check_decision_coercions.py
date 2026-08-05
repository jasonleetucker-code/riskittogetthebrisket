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

...BUT ONLY FOR FILES THIS CHANGE TOUCHES
-----------------------------------------
Both rules are scoped to the files the PR actually changed, and that
scoping is not a convenience — without it the gate is unusable.

A ``pull_request`` build checks out ``refs/pull/N/merge``, so the tree
under test is *this branch merged into current main*.  Main moves
independently: on this gate's own first run, #707 landed a rewritten
FAAB engine while the PR was open, and the baseline — captured against
the branch point — reported new violations and stale allowances in
``faab_recommender.py`` and ``waiver.py`` that this PR had never
touched.  A whole-tree baseline makes every PR responsible for every
other PR's edits, which is the failure mode that got the ruff gate
narrowed in phase A3.

Scoping loses nothing that matters: a coercion can only be INTRODUCED
by a change, so a violation in an untouched file is by definition
pre-existing debt.  The full-tree count is still reported every run, so
the debt stays visible rather than becoming invisible.

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
import io
import json
import os
import re
import tokenize
import subprocess
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


def _masked_spans(source: str) -> dict[int, list[tuple[int, int]]]:
    """Column ranges per line that are comment or string literal.

    Prose about a coercion is not a coercion.  This began as a check on
    how a line STARTS (hash, slash-slash, a triple-quote), which cannot
    see a CONTINUATION line inside a multi-line docstring — and this
    codebase documents these defects at length, so a sentence
    explaining the pattern inside a docstring was reported as a live
    violation.  A false positive is not a harmless nuisance for a gate:
    it is the pressure that gets the gate weakened or switched off.

    Masking by SPAN and not by line, because the obvious version of this
    fix is wrong in the opposite and far more dangerous direction:
    marking any line containing a string token as prose silences
    ``x = data.get("k") or 0`` — a real coercion on a line that merely
    contains a string. That turns the gate off almost everywhere while
    still reporting success. Its own unit test caught it.
    """
    masked: dict[int, list[tuple[int, int]]] = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type not in (tokenize.COMMENT, tokenize.STRING):
                continue
            (srow, scol), (erow, ecol) = tok.start, tok.end
            for row in range(srow, erow + 1):
                start = scol if row == srow else 0
                end = ecol if row == erow else 10**9
                masked.setdefault(row, []).append((start, end))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Unparseable file: scan all of it rather than silently
        # exempting it. Over-reporting is recoverable; a gate that
        # quietly stops looking is the defect it exists to prevent.
        return {}
    return masked


def _is_masked(masked: dict[int, list[tuple[int, int]]], line_no: int, col: int) -> bool:
    return any(start <= col < end for start, end in masked.get(line_no, ()))


def _scan() -> list[dict]:
    found: list[dict] = []
    for path in _iter_files():
        pattern = _SUFFIXES.get(path.suffix)
        if pattern is None:
            continue
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        lines = source.splitlines()
        masked = _masked_spans(source) if path.suffix == ".py" else {}
        rel = path.relative_to(REPO_ROOT).as_posix()
        for n, line in enumerate(lines, 1):
            stripped = line.strip()
            # JS/JSX keeps the line-prefix heuristic — no tokenizer to
            # hand, and its block comments are rarer in these files.
            if stripped.startswith(("#", "//", "*", '"""', "'''")):
                continue
            for m in pattern.finditer(line):
                if _is_masked(masked, n, m.start()):
                    continue
                found.append(
                    {
                        "file": rel,
                        "line": n,
                        "match": m.group(0).strip(),
                        "text": stripped[:120],
                    }
                )
    return found


def _changed_files() -> set[str] | None:
    """Files this change touches, relative to its merge base.

    ``None`` means "could not determine" — the caller then falls back
    to whole-tree enforcement rather than to enforcing nothing.  A gate
    that silently downgrades to a no-op when git is unavailable is the
    same category of defect as the alert that reads a key its input
    never carries (O-1).
    """
    base_ref = os.environ.get("GITHUB_BASE_REF") or "main"
    for base in (f"origin/{base_ref}", base_ref):
        try:
            proc = subprocess.run(
                ["git", "diff", "--name-only", f"{base}...HEAD"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            return None
        if proc.returncode == 0:
            return {ln.strip() for ln in proc.stdout.splitlines() if ln.strip()}
    return None


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

    changed = _changed_files()
    scope = "changed files" if changed is not None else "whole tree (no merge base found)"
    print(
        f"decision-path coercions: {len(by_key)} present, "
        f"{len(accepted)} accepted as debt — enforcing on {scope}"
    )

    if changed is not None:
        blocking_new = [k for k in new if by_key[k]["file"] in changed]
        blocking_stale = [k for k in stale if k.split("::", 1)[0] in changed]
    else:
        blocking_new, blocking_stale = new, stale

    drifted = (len(new) - len(blocking_new)) + (len(stale) - len(blocking_stale))
    if drifted:
        print(
            f"  ({drifted} difference(s) in files this change does not touch — "
            "main moved; not this PR's to fix)"
        )

    if blocking_new:
        print(f"\nNEW ({len(blocking_new)}) — a decision path may not fabricate a number:")
        for k in blocking_new[:40]:
            v = by_key[k]
            print(f"  {v['file']}:{v['line']}  {v['match']}")
            print(f"      {v['text']}")
    if blocking_stale:
        print(
            f"\nSTALE BASELINE ENTRIES ({len(blocking_stale)}) — "
            "fixed by this change; delete them from the baseline:"
        )
        for k in blocking_stale[:40]:
            print(f"  {k[:110]}")

    if blocking_new or blocking_stale:
        return 1
    print("\nclean: no new coercions, no stale allowances in the files this change touches.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
