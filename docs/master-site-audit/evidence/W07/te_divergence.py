"""W07 evidence: quantify /rankings (tep-override board) vs /api/data (engine board).

Re-run with:
    .venv/bin/python docs/master-site-audit/evidence/W07/te_divergence.py

Reads ``payload-extracts.json`` — per-player extracts of the seven live payloads
captured for this workstream (raw multi-MB bodies were pruned; the reproduction
commands in ``registry/W07.jsonl`` regenerate them verbatim).
"""

from __future__ import annotations

import collections
import json
import pathlib

HERE = pathlib.Path(__file__).parent
ENGINE_BOARD = "apiData_GET_/api/data"
PAGE_BOARD = "page_POST_overrides_tep1.15"


def main() -> None:
    ex = json.loads((HERE / "payload-extracts.json").read_text())
    engine = ex[ENGINE_BOARD]["players"]
    board = ex[PAGE_BOARD]["players"]

    diffs = []
    by_pos: collections.Counter[str] = collections.Counter()
    positions = {n: v.get("position") for n, v in engine.items()}
    rank_diff = tier_diff = 0
    for name, row in board.items():
        eng = engine.get(name)
        if eng is None:
            continue
        ev = eng.get("rankDerivedValue")
        pv = row.get("rankDerivedValue")
        if ev != pv:
            by_pos[str(positions.get(name))] += 1
            if ev:
                diffs.append(
                    {
                        "player": name,
                        "apiDataValue": ev,
                        "renderedValue": pv,
                        "ratio": round((pv or 0) / ev, 6),
                        "pctUnderstated": round(100 * (1 - (pv or 0) / ev), 3),
                    }
                )
        if eng.get("canonicalConsensusRank") != row.get("canonicalConsensusRank"):
            rank_diff += 1
        if eng.get("canonicalTierId") != row.get("canonicalTierId"):
            tier_diff += 1

    diffs.sort(key=lambda d: d["ratio"])
    out = {
        "rowsCompared": len(board),
        "valueDiffRows": sum(by_pos.values()),
        "rankDiffRows": rank_diff,
        "tierDiffRows": tier_diff,
        "worst10": diffs[:10],
        "payloadBytes": {k: v["bytes"] for k, v in ex.items()},
        "note": (
            "renderedValue is what /rankings shows (POST /api/rankings/overrides "
            "with the frontend's forced tep_multiplier=1.15); apiDataValue is what "
            "GET /api/data serves and what every server-side engine prices from."
        ),
    }
    (HERE / "te-divergence.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "worst10"}, indent=1))
    for d in diffs[:10]:
        print(d)


if __name__ == "__main__":
    main()
