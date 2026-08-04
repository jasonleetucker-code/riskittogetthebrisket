"""Reproduce the blend from stamped per-source valueContribution and compare to rankDerivedValue."""

import json
import collections

CONTRACT = "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/data_full.json"
p = json.load(open(CONTRACT))
pa = p["playersArray"]

ALPHA = 0.10
HAMPEL_K = 2.75
HAMPEL_MIN_N = 4
HAMPEL_MIN_THRESHOLD = 1000.0
SINGLE_SOURCE_RETENTION = 0.30
IDP_POS = {"DL", "LB", "DB"}


def count_aware(values):
    if not values:
        return 0.0, None
    sv = sorted(values)
    k = len(sv)
    if k == 1:
        return sv[0], None
    if k == 2:
        return (sv[0] + sv[1]) / 2.0, abs(sv[0] - sv[1]) / 2.0
    used = sv[1:-1] if k >= 5 else sv
    m = len(used)
    u_mean = sum(used) / m
    u_med = float(used[m // 2]) if m % 2 == 1 else (used[m // 2 - 1] + used[m // 2]) / 2.0
    return (u_mean + u_med) / 2.0, sum(abs(v - u_mean) for v in used) / m


def hampel(pairs, k=HAMPEL_K, min_n=HAMPEL_MIN_N, min_threshold=HAMPEL_MIN_THRESHOLD):
    n = len(pairs)
    if n < min_n:
        return list(pairs), []
    sv = sorted(v for _, v in pairs)
    med = float(sv[n // 2]) if n % 2 == 1 else (sv[n // 2 - 1] + sv[n // 2]) / 2.0
    dev = sorted(abs(v - med) for _, v in pairs)
    mad = float(dev[n // 2]) if n % 2 == 1 else (dev[n // 2 - 1] + dev[n // 2]) / 2.0
    thr = max(k * mad, min_threshold)
    kept = []
    dropped = []
    for sk, v in pairs:
        (dropped if abs(v - med) > thr else kept).append(sk if abs(v - med) > thr else (sk, v))
    kept = [x for x in kept]
    if len(kept) < 2:
        return list(pairs), []
    return kept, dropped


results = []
mismatch = []
hampel_stats = collections.Counter()
per_source_total = collections.Counter()
per_source_dropped = collections.Counter()
single_source_rows = []
for r in pa:
    meta = r.get("sourceRankMeta") or {}
    if not meta:
        continue
    posn = str(r.get("position") or "").upper()
    is_pick = posn == "PICK" or r.get("assetClass") == "pick"
    pairs = []
    for sk, m in meta.items():
        vc = m.get("valueContribution")
        if vc is None:
            continue
        pairs.append((sk, float(vc), bool(m.get("isAnchor"))))
    if not pairs:
        continue
    # Hampel
    dropped = []
    if not is_pick and len(pairs) >= HAMPEL_MIN_N:
        kept, dropped = hampel([(k, v) for k, v, _ in pairs])
        keptset = {k for k, _ in kept}
    else:
        keptset = {k for k, _, _ in pairs}
    for sk, _v, _a in pairs:
        per_source_total[sk] += 1
    for sk in dropped:
        per_source_dropped[sk] += 1
    hampel_stats["rows"] += 1
    if dropped:
        hampel_stats["rows_with_drop"] += 1
    hampel_stats["pairs"] += len(pairs)
    hampel_stats["dropped_pairs"] += len(dropped)

    all_v = [v for k, v, _ in pairs if k in keptset]
    anchor_v = [v for k, v, a in pairs if k in keptset and a]
    sub_v = [v for k, v, a in pairs if k in keptset and not a]
    use_hier = is_pick or posn in IDP_POS
    anchor = count_aware(anchor_v)[0] if anchor_v else None
    subc = count_aware(sub_v)[0] if sub_v else None
    if use_hier:
        if anchor is not None and subc is not None:
            center = anchor + ALPHA * (subc - anchor)
            delta = subc - anchor
        elif anchor is not None:
            center = anchor
            delta = None
        elif subc is not None:
            center = subc
            delta = None
        else:
            center = 0.0
            delta = None
    else:
        center = count_aware(all_v)[0] if all_v else 0.0
        delta = (subc - anchor) if (anchor is not None and subc is not None) else None
    blended = max(0.0, center)
    haircut = False
    if (not is_pick) and len(all_v) <= 1:
        blended *= SINGLE_SOURCE_RETENTION
        haircut = True
        single_source_rows.append(
            (r.get("canonicalName"), posn, r.get("rankDerivedValue"), blended, all_v)
        )
    results.append(
        dict(
            name=r.get("canonicalName"),
            pos=posn,
            is_pick=is_pick,
            pred=blended,
            uncapped=r.get("_blendedValueUncapped"),
            rdv=r.get("rankDerivedValue"),
            anchor_pred=anchor,
            anchor_stamp=r.get("anchorValue"),
            sub_pred=subc,
            sub_stamp=r.get("subgroupBlendValue"),
            haircut=haircut,
            dropped=dropped,
            dropped_stamp=r.get("droppedSources"),
            rank=r.get("canonicalConsensusRank"),
            alpha=r.get("alphaShrinkage"),
        )
    )

json.dump(
    results,
    open(
        "/tmp/claude-0/-home-user-riskittogetthebrisket/0f0078ff-84f2-50d3-bce6-2bb1d1d8e920/scratchpad/repro.json",
        "w",
    ),
)
print("rows reproduced", len(results))
print(
    "HAMPEL: rows",
    hampel_stats["rows"],
    "rows_with_drop",
    hampel_stats["rows_with_drop"],
    "pair drop rate",
    round(hampel_stats["dropped_pairs"] / max(1, hampel_stats["pairs"]) * 100, 2),
    "%",
    "row drop rate",
    round(hampel_stats["rows_with_drop"] / max(1, hampel_stats["rows"]) * 100, 2),
    "%",
)
print()
print("per-source drop rates:")
for sk in sorted(
    per_source_total, key=lambda s: -per_source_dropped[s] / max(1, per_source_total[s])
):
    t = per_source_total[sk]
    d = per_source_dropped[sk]
    print(f"  {sk:28s} {d:5d}/{t:5d}  {d/max(1,t)*100:6.2f}%")
