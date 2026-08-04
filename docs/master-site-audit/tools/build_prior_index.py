"""Audit-only: give the prior 2026-08-04 audit's findings stable IDs.

``docs/audits/decision-intelligence-audit-2026-08-04.registry.json`` is a
26-element array of areas; each area carries ``systems``/``formulas``/
``findings`` arrays whose records have NO id field.  A cross-reference is
impossible without one, and every workstream inventing its own scheme would
make the crosswalk unmergeable.  So IDs are synthesized deterministically
from array position: ``PRIOR-A{areaIdx:02d}-F{findingIdx:02d}``.

Position-derived IDs are stable only against this exact file; the content
hash is recorded so a future reader can tell whether the source moved.

Writes docs/master-site-audit/evidence/prior-index.json.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "docs/audits/decision-intelligence-audit-2026-08-04.registry.json"
OUT = ROOT / "docs/master-site-audit/evidence/prior-index.json"


def main() -> None:
    raw = SRC.read_bytes()
    areas = json.loads(raw)
    findings = []
    systems_count = 0
    formulas_count = 0
    for ai, area in enumerate(areas):
        area_name = area.get("area") or area.get("subsystem") or f"area-{ai}"
        systems_count += len(area.get("systems") or [])
        formulas_count += len(area.get("formulas") or [])
        for fi, f in enumerate(area.get("findings") or []):
            findings.append(
                {
                    "id": f"PRIOR-A{ai:02d}-F{fi:02d}",
                    "areaIdx": ai,
                    "area": area_name[:160],
                    "title": f.get("title") or f.get("finding") or "",
                    "severity": f.get("severity"),
                    "rootCause": f.get("rootCause"),
                    "evidence": f.get("evidence"),
                    "userImpact": f.get("userImpact"),
                    "status": f.get("status"),
                }
            )
    out = {
        "source": str(SRC.relative_to(ROOT)),
        "sourceSha256": hashlib.sha256(raw).hexdigest(),
        "areas": [
            {
                "areaIdx": i,
                "area": (a.get("area") or "")[:200],
                "findings": len(a.get("findings") or []),
                "systems": len(a.get("systems") or []),
                "formulas": len(a.get("formulas") or []),
            }
            for i, a in enumerate(areas)
        ],
        "totals": {
            "areas": len(areas),
            "findings": len(findings),
            "systems": systems_count,
            "formulas": formulas_count,
        },
        "findings": findings,
    }
    OUT.write_text(json.dumps(out, indent=1))
    print(
        f"areas={len(areas)} findings={len(findings)} systems={systems_count} formulas={formulas_count}"
    )
    sev: dict[str, int] = {}
    for f in findings:
        sev[str(f["severity"])] = sev.get(str(f["severity"]), 0) + 1
    print("by severity:", sev)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
