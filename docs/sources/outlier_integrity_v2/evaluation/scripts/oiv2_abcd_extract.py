#!/usr/bin/env python3
"""Build the directive §6 comparison boards on one pinned input and extract a
compact, complete per-row / per-vote record of each.

Run with cwd = a throwaway tree of the V2 code commit whose CSVs/ and data/ are
pinned to the input commit (rootcause/pin_inputs.sh)::

    python oiv2_abcd_extract.py PAYLOAD.json TAG OUT.json.gz [--boards A,B,...]

Every board is the same frozen payload + CSVs + data + weights + config; only
the two DLF flags and the per-row filter differ (BOARDS below). Build engine:
``src.robust_filter_shadow.oiv2_gates.build`` (the harness the R constraint
checks use; flags pinned there, NO-HISTORY for V2, provisional thresholds).
"""

from __future__ import annotations

import gzip
import hashlib
import json
import resource
import sys
import time
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from src.api import data_contract as dc  # noqa: E402
from src.robust_filter_shadow import oiv2_gates as G  # noqa: E402

# name: (filter config, DLF IDP held (dlf_offense_only_vote), D4 on (dlf_values_rank_hill_vote))
BOARDS = {
    "A": ("incumbent", True, False),
    "B": ("incumbent", False, False),
    "C": ("v2", False, False),
    "D": ("v2", True, False),
    "B'": ("incumbent", True, True),
    "C'": ("v2", True, True),
    "B''": ("incumbent", False, True),
    "C''": ("v2", False, True),
    # attribution boards: per-row filter stood down entirely
    "Anf": ("none", True, False),
    "Bnf": ("none", False, False),
    "B'nf": ("none", True, True),
    "B''nf": ("none", False, True),
}

ROW_KEYS = (
    "displayName",
    "assetClass",
    "position",
    "team",
    "playerId",
    "rankDerivedValue",
    "canonicalConsensusRank",
    "confidenceBucket",
    "confidenceAxes",
    "confidenceReasons",
    "quarantined",
    "anomalyFlags",
    "droppedSources",
    "outlierIntegrityReasons",
    "outlierPolicyReasons",
    "freshnessExcludedSources",
    "effectiveSourceCount",
    "independentSourceCount",
    "sourceCount",
    "isSingleSource",
    "retainedAuthority",
    "pickValueProvenance",
    "twoWayPlayerBoost",
    "alphaShrinkage",
    "anchorValue",
    "subgroupBlendValue",
    "_blendedValueUncapped",
    "rookie",
    "offCapPlayerValue",
    "offCapPickValue",
    "sourceIntegrity",
)
META_KEYS = (
    "valueContribution",
    "valueContributionPath",
    "excludedReason",
    "hampelDropped",
    "method",
    "rawRank",
    "effectiveRank",
    "rankCoordinatePool",
    "sharedMarketTranslated",
    "levelSource",
    "appliedWeight",
    "effectiveWeight",
    "baseWeight",
    "familyAdjustment",
    "freshness",
    "contributedToBlend",
    "isAnchor",
    "integrity",
)


def row_key(r: dict, seen: dict) -> str:
    n = str(r.get("displayName") or "")
    k = n
    if k in seen:
        k = f"{n}|{r.get('position')}|{r.get('assetClass')}"
        i = 2
        while k in seen:
            k = f"{n}|{r.get('position')}|{r.get('assetClass')}#{i}"
            i += 1
    seen[k] = True
    return k


def extract_row(r: dict) -> dict:
    out = {k: r.get(k) for k in ROW_KEYS if r.get(k) is not None}
    votes = {}
    for k, m in sorted((r.get("sourceRankMeta") or {}).items()):
        if not isinstance(m, dict):
            continue
        e = {mk: m.get(mk) for mk in META_KEYS if m.get(mk) is not None}
        e["status"] = G.exclusion_of(r, k)  # None = voting
        e["family"] = dc.correlation_group_for(k) or k
        votes[k] = e
    out["votes"] = votes
    return out


def build(name: str, raw: dict) -> dict:
    config, held, d4 = BOARDS[name]
    return G.build(
        raw,
        None,
        config,
        extra_flags={"dlf_offense_only_vote": held, "dlf_values_rank_hill_vote": d4},
        history=None,
    )


def main() -> int:
    payload, tag, out = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
    names = list(BOARDS)
    if len(sys.argv) > 5 and sys.argv[4] == "--boards":
        names = sys.argv[5].split(",")
    raw_bytes = payload.read_bytes()
    raw = json.loads(raw_bytes)
    result = {
        "schema": "oiv2-abcd-extract/v1",
        "pin": tag,
        "payloadSha256": hashlib.sha256(raw_bytes).hexdigest(),
        "boardsSpec": {
            b: {"filter": BOARDS[b][0], "dlfIdpHeld": BOARDS[b][1], "d4On": BOARDS[b][2]}
            for b in names
        },
        "boards": {},
    }
    for b in names:
        t = time.time()
        c = build(b, raw)
        secs = time.time() - t
        seen: dict = {}
        rows = {}
        for r in c.get("playersArray") or []:
            rows[row_key(r, seen)] = extract_row(r)
        si = c.get("sourceIntegrity") or {}
        result["boards"][b] = {
            "buildSeconds": round(secs, 2),
            "digest": G.board_digest(c),
            "playersArraySha256": hashlib.sha256(
                json.dumps(c.get("playersArray"), sort_keys=True, default=str).encode()
            ).hexdigest(),
            "sourceIntegrity": si,
            "sourceVotingEligibility": c.get("sourceVotingEligibility"),
            "validationSummary": c.get("validationSummary"),
            "rows": rows,
        }
        print(f"{tag} {b}: {len(rows)} rows, {secs:.1f}s", file=sys.stderr, flush=True)
        del c
    # determinism: rebuild C
    if "C" in names:
        c2 = build("C", raw)
        result["determinismC"] = {
            "digestRun1": result["boards"]["C"]["digest"],
            "digestRun2": G.board_digest(c2),
            "shaRun1": result["boards"]["C"]["playersArraySha256"],
            "shaRun2": hashlib.sha256(
                json.dumps(c2.get("playersArray"), sort_keys=True, default=str).encode()
            ).hexdigest(),
        }
        d = result["determinismC"]
        d["identical"] = d["digestRun1"] == d["digestRun2"] and d["shaRun1"] == d["shaRun2"]
        del c2
    result["peakRssMb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(out, "wt", encoding="utf-8") as fh:
        json.dump(result, fh, sort_keys=True, default=str)
    print(
        json.dumps(
            {
                "pin": tag,
                "peakRssMb": result["peakRssMb"],
                "determinism": result.get("determinismC", {}).get("identical"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
