#!/usr/bin/env python3
"""Apply ``outlier-corroborated-v1`` to ANOTHER checkout's board (read-only).

Used to answer "does the policy keep the votes the incumbent drops on PR #1817's
board?" without merging the two branches: the board is built by the other
checkout's own code (``value_replay.build``, DLF IDP hold off and on), and this
branch's pure policy module is applied offline to the stamped votes. That is exact
for the keep / drop decision, because every vote is computed before the filter.

Run it with the interpreter isolated from this checkout's ``src`` so the other
checkout's pipeline is the one imported::

    PYTHONDONTWRITEBYTECODE=1 python3 -I scripts/outlier_policy_check_branch_board.py \\
        --branch-root /path/to/other/checkout \\
        --payload exports/latest/dynasty_data_2026-10-19.json \\
        --out docs/valuation/evidence/outlier-disagreement-2026-10-19/pr1817_board_check.json
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

POLICY = Path(__file__).resolve().parents[1] / "src" / "api" / "outlier_policy.py"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--branch-root", type=Path, required=True)
    ap.add_argument("--payload", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    out_path = args.out.resolve()
    root = args.branch_root.resolve()
    sys.path.insert(0, str(root))
    os.chdir(root)
    spec = importlib.util.spec_from_file_location("outlier_policy_branch_check", POLICY)
    op = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = op
    spec.loader.exec_module(op)
    from src.api import data_contract as dc  # noqa: PLC0415
    from src.api import value_replay as vr  # noqa: PLC0415

    payload = args.payload if args.payload.is_absolute() else root / args.payload
    data = payload.read_bytes()
    raw = json.loads(data)
    hold = vr.build(raw, {"flags": [("dlf_offense_only_vote", True)]})
    cur = vr.build(raw, {"flags": [("dlf_offense_only_vote", False)]})
    rows = [r for r in cur["playersArray"] if r.get("assetClass") != "pick"]
    screen = op.board_screen(
        [
            op.BoardRow(
                str(r.get("assetClass")), op.scope_curve(r.get("assetClass")), op.stamped_votes(r)
            )
            for r in rows
        ],
        dc.correlation_group_for,
    )
    hold_rows = {r["displayName"]: r for r in hold["playersArray"]}
    inc: Counter[str] = Counter()
    kept: Counter[str] = Counter()
    policy_drops: list[list] = []
    newly: list[tuple] = []
    for r in rows:
        ac = str(r.get("assetClass"))
        votes = op.stamped_votes(r)
        meta = r.get("sourceRankMeta") or {}
        pre = {
            s: float(
                (meta.get(s) or {}).get("preFamilyWeight", (meta.get(s) or {}).get("appliedWeight"))
                or 0.0
            )
            for s in votes
        }
        capped, _f = dc.cap_family_weights(pre)
        verdict = op.assess_row(
            sorted(votes.items()),
            curve=op.scope_curve(ac),
            family_of=dc.correlation_group_for,
            weights=capped,
            board_excluded=(screen["flagged"] or {}).get(ac, []),
        )
        dropped = list(r.get("droppedSources") or [])
        for s in dropped:
            inc[ac] += 1
            kept[ac] += s not in verdict.dropped
        policy_drops += [[r["displayName"], ac, s, verdict.reasons.get(s)] for s in verdict.dropped]
        held = set((hold_rows.get(r["displayName"]) or {}).get("droppedSources") or [])
        for s in dropped:
            if s not in held and not s.startswith("dlf"):
                newly.append((r["displayName"], r.get("position"), s, s in verdict.dropped))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    result = {
        "branchHead": head or None,
        "payload": str(args.payload),
        "payloadSha256": hashlib.sha256(data).hexdigest(),
        "policy": op.constants(),
        "boardScreenFlagged": screen["flagged"],
        "incumbentDrops": dict(inc),
        "policyKeepsOfIncumbentDrops": dict(kept),
        "policyDrops": policy_drops,
        "newlyDroppedByDlfRestore": {
            "votes": len(newly),
            "rows": len({n for n, _p, _s, _d in newly}),
            "bySource": dict(Counter(s for _n, _p, s, _d in newly)),
            "byPosition": dict(Counter(p for _n, p, _s, _d in newly)),
            "policyStillDrops": sum(1 for *_x, d in newly if d),
            "detail": [
                {"row": n, "position": p, "source": s, "policyDrops": d}
                for n, p, s, d in sorted(newly)
            ],
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("incumbentDrops", "policyKeepsOfIncumbentDrops")}))
    print(
        json.dumps({k: v for k, v in result["newlyDroppedByDlfRestore"].items() if k != "detail"})
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
