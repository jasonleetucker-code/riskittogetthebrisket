#!/usr/bin/env python3
"""Defect-signature tripwires for the 2026-08-05 unfalsifiable-number audit.

WHY THIS IS A SECOND SCRIPT AND NOT A CHANGE TO ``audit_status.py``
==================================================================
``scripts/audit_status.py`` is a status overlay on a **frozen** artifact.
``_registry_criticals()`` walks the 08-04 registry in order and mints
``C01…C43`` from positions; ``rebuild()`` raises if a curated entry is
missing for one.  There is no seam for a finding that registry does not
contain, and ``docs/audits/remediation-protocol.md`` states it is "never
regenerated".

It is also another session's live tooling, mid-batch.  So this reuses its
**probe mechanism** — ``_probe`` and ``_squash`` are imported, not
reimplemented, so there is one definition of "is the signature still
there" — while keeping its own registry, its own status file and its own
CLI.  If those helpers are ever renamed, this fails loudly at import,
which is the correct outcome rather than a silent divergence.

WHAT A SIGNATURE IS
===================
A fragment of source present exactly while the defect's mechanism is
present.  A probe is a **tripwire, not a proof**: signature absent does
not mean fixed (it may have moved), signature present does not mean live
(surrounding semantics may have changed).  ``status`` is set by someone
who read the code and ``verifiedBy`` records what they read.

Status has one authority: ``docs/audits/unfalsifiable-number-audit-2026-08-05.registry.json``,
which moves through review with the change that closes a finding.  The
generated ``.status.json`` is output — do not edit it.

Usage::

    python3 scripts/unfalsifiable_status.py             # check for drift
    python3 scripts/unfalsifiable_status.py --rebuild   # refresh probes

Exit codes: 0 no drift, 1 drift, 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

# One definition of the probe, borrowed rather than copied.  See the
# module docstring for why this is an import and not a fork.
from audit_status import _probe  # noqa: E402

REGISTRY = REPO_ROOT / "docs" / "audits" / "unfalsifiable-number-audit-2026-08-05.registry.json"
STATUS = REPO_ROOT / "docs" / "audits" / "unfalsifiable-number-audit-2026-08-05.status.json"

OPEN, CLOSED = "open", "closed"


def _findings() -> list[dict[str, Any]]:
    doc = json.loads(REGISTRY.read_text(encoding="utf-8"))
    findings = doc.get("findings") or []
    if not findings:
        raise SystemExit(f"{REGISTRY.name} lists no findings")
    return findings


def rebuild() -> int:
    entries = []
    for f in _findings():
        e = dict(f)
        e["probe"] = _probe(f.get("path"), f.get("signature"))
        entries.append(e)

    tally: dict[str, int] = {}
    for e in entries:
        tally[e.get("status", "?")] = tally.get(e.get("status", "?"), 0) + 1

    STATUS.write_text(
        json.dumps(
            {
                "source": REGISTRY.name,
                "note": "GENERATED. Status authority is the registry, not this file.",
                "total": len(entries),
                "tally": tally,
                "findings": entries,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {STATUS.relative_to(REPO_ROOT)} — {len(entries)} findings")
    for k in sorted(tally):
        print(f"  {k:>8}: {tally[k]}")
    return 0


def check() -> int:
    if not STATUS.exists():
        print(f"error: {STATUS.name} missing — run --rebuild first", file=sys.stderr)
        return 2
    recorded = {e["id"]: e for e in json.loads(STATUS.read_text(encoding="utf-8"))["findings"]}
    current = {f["id"]: f for f in _findings()}

    drift: list[str] = []

    gone = sorted(set(recorded) - set(current))
    added = sorted(set(current) - set(recorded))
    if gone or added:
        drift.append(f"registry and status disagree on membership: -{gone} +{added} — rebuild")

    for fid, f in current.items():
        was = (recorded.get(fid) or {}).get("probe") or {}
        now = _probe(f.get("path"), f.get("signature"))
        if was.get("result") in (None, "no_mechanical_probe"):
            continue
        if f["status"] == CLOSED and now["result"] == "signature_present":
            drift.append(f"{fid} recorded CLOSED but its defect signature is back")
        elif f["status"] == OPEN and now["result"] != was.get("result"):
            drift.append(
                f"{fid} probe changed: {was.get('result')} -> {now['result']}. "
                "If it was fixed, mark it closed with the measured effect; if it "
                "merely moved, re-anchor the signature by content."
            )

    print(f"unfalsifiable-number findings: {len(current)}")
    if drift:
        print(f"\nDRIFT ({len(drift)}):")
        for d in drift:
            print(f"  {d}")
        return 1
    print("no drift: every recorded status matches its probe.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rebuild", action="store_true", help="refresh probes")
    args = ap.parse_args()
    try:
        return rebuild() if args.rebuild else check()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — report, never traceback at the operator
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
