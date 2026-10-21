#!/usr/bin/env python3
"""DISCOVER-1 root cause: build one board and log every incumbent Hampel call.

usage: rc_build.py TREE PAYLOAD OUT.json [ENV=VAL ...]

Run with cwd=TREE.  Flags come from ENV=VAL pairs (e.g.
RISKIT_FEATURE_DLF_OFFENSE_ONLY_VOTE=0 for board B).  The incumbent filter
``data_contract._hampel_filter_per_player`` is wrapped (read-only: the wrapper
calls the original and returns its result unchanged) so every call records the
row, every vote (source, value, anchor flag, per-source pricing meta), the
median, MAD, k*MAD, threshold (with floor), n, min_n, the deviations, the
dropped keys and whether the "<2 survivors" guard stood the filter down.
Nothing in the pipeline is modified.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

tree, payload, out = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
for kv in sys.argv[4:]:
    k, _, v = kv.partition("=")
    os.environ[k] = v
sys.path.insert(0, tree)
from src.api import feature_flags  # noqa: E402

feature_flags.reload()
from src.api import data_contract as dc  # noqa: E402

_ORIG = dc._hampel_filter_per_player
CALLS: list[dict] = []
META_KEYS = (
    "valueContribution",
    "valueContributionPath",
    "percentile",
    "rawRank",
    "effectiveRank",
    "method",
    "rankCoordinatePool",
    "isAnchor",
    "appliedWeight",
    "tepMultiplier",
    "deepTailNative",
)


def _median(xs):
    s = sorted(xs)
    n = len(s)
    return float(s[n // 2]) if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def _wrapped(
    pairs, *, k=dc._HAMPEL_K, min_n=dc._HAMPEL_MIN_N, min_threshold=dc._HAMPEL_MIN_THRESHOLD
):
    kept, dropped = _ORIG(pairs, k=k, min_n=min_n, min_threshold=min_threshold)
    frame = sys._getframe(1)
    rec: dict = {"caller": frame.f_code.co_name, "n": len(pairs), "minN": min_n, "k": k}
    # The blend loop calls the filter directly (decision-bearing); the B11
    # lost-evidence replay (_lost_evidence_seats) calls it on the OBSERVED panel
    # (voting + withheld) to seat lost evidence -- it decides no vote.  Walk up to
    # the pipeline frame for the row identity either way.
    pipe = frame
    while pipe is not None and "players_array" not in pipe.f_locals:
        pipe = pipe.f_back
    loc = pipe.f_locals if pipe is not None else {}
    row = None
    try:
        pa, ri = loc.get("players_array"), loc.get("row_idx")
        if pa is not None and ri is not None:
            row = pa[ri]
            rec["row"] = row.get("displayName") or row.get("canonicalName")
            rec["position"] = row.get("position")
            rec["assetClass"] = row.get("assetClass")
            rec["rowIdx"] = ri
        anchors = {kk: a for kk, _v, a in (loc.get("all_value_pairs") or [])}
        rw = loc.get("row_weight") or {}
        rsm = loc.get("row_source_meta")
        meta_row = rsm[ri] if (rsm is not None and ri is not None) else {}
        if rec["caller"] != "_compute_unified_rankings":
            wp = dict(loc.get("withheld_pairs") or [])
            rec["withheldInPanel"] = sorted(s for s, _v in pairs if s in wp)
    except Exception as exc:  # pragma: no cover - diagnostics only
        rec["frameError"] = repr(exc)
        anchors, rw, meta_row = {}, {}, {}
    if len(pairs) >= min_n:
        vals = [float(v) for _, v in pairs]
        med = _median(vals)
        mad = _median([abs(v - med) for v in vals])
        thr = max(k * mad, min_threshold)
        rec.update(
            median=med,
            mad=mad,
            kMad=k * mad,
            threshold=thr,
            floorBound=k * mad < min_threshold,
            wouldDrop=[s for s, v in pairs if abs(float(v) - med) > thr],
        )
        rec["guardStoodDown"] = bool(rec["wouldDrop"]) and not dropped
    # Diagnostic counterfactual ONLY (never a proposal): RC_NO_IDP_FILTER=1 stands
    # the decision-bearing filter down on IDP rows so B-without-filter isolates
    # DLF's own vote from the filter's reaction to it.
    if (
        os.environ.get("RC_NO_IDP_FILTER") == "1"
        and rec["caller"] == "_compute_unified_rankings"
        and rec.get("assetClass") == "idp"
        and dropped
    ):
        rec["suppressedDrops"] = list(dropped)
        kept, dropped = list(pairs), []
    rec["dropped"] = list(dropped)
    votes = []
    for s, v in pairs:
        m = meta_row.get(s, {}) if isinstance(meta_row, dict) else {}
        votes.append(
            {
                "source": s,
                "value": float(v),
                "anchor": anchors.get(s),
                "weight": rw.get(s),
                "deviation": (abs(float(v) - rec["median"]) if "median" in rec else None),
                **{mk: m.get(mk) for mk in META_KEYS if mk in m},
            }
        )
    rec["votes"] = votes
    CALLS.append(rec)
    return kept, dropped


dc._hampel_filter_per_player = _wrapped

blob = payload.read_bytes()
if payload.suffix == ".gz":
    blob = gzip.decompress(blob)
raw = json.loads(blob)
contract = dc.build_api_data_contract(copy.deepcopy(raw))


def h(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


rows = []
for r in contract.get("playersArray") or []:
    if not isinstance(r, dict) or not r.get("displayName"):
        continue
    meta = {}
    for kk, m in (r.get("sourceRankMeta") or {}).items():
        if isinstance(m, dict):
            meta[kk] = {
                mk: m.get(mk)
                for mk in META_KEYS
                + (
                    "hampelDropped",
                    "contributedToBlend",
                    "excludedReason",
                    "preFamilyWeight",
                    "familyAdjustment",
                )
                if mk in m
            }
    rows.append(
        {
            "name": r.get("displayName"),
            "pos": r.get("position"),
            "cls": r.get("assetClass"),
            "v": r.get("rankDerivedValue"),
            "rank": r.get("canonicalConsensusRank"),
            "conf": r.get("confidenceBucket"),
            "isc": r.get("independentSourceCount"),
            "haircut": r.get("singleSourceValuePenaltyApplied"),
            "drop": r.get("droppedSources"),
            "fex": r.get("freshnessExcludedSources"),
            "anchor": r.get("anchorValue"),
            "sub": r.get("subgroupBlendValue"),
            "meta": meta,
        }
    )

out.write_text(
    json.dumps(
        {
            "env": sys.argv[4:],
            "payload": payload.name,
            "payloadSha256": hashlib.sha256(blob).hexdigest(),
            "scrapeTimestamp": raw.get("scrapeTimestamp"),
            "constants": {
                "K": dc._HAMPEL_K,
                "MIN_N": dc._HAMPEL_MIN_N,
                "MIN_THRESHOLD": dc._HAMPEL_MIN_THRESHOLD,
            },
            "policyHoldsInForce": sorted(dc._policy_source_vote_holds()),
            "hashPlayersArray": h(contract.get("playersArray")),
            "hampelCalls": CALLS,
            "rows": rows,
        },
        default=str,
    )
)
print("ok", out, "calls", len(CALLS))
