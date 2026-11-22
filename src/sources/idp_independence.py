"""IDP evidence independence -- read-only measurement (shadow).

Answers one question about the IDP rows of a BUILT contract: is the IDP
consensus several independent opinions, or one opinion counted several times?

This module MEASURES.  It changes no vote, weight, family, cap, registry or
flag, and it never imports the voting logic.  It reads only the per-row stamps
the canonical pipeline already wrote (``sourceRankMeta``, ``confidenceAxes`` ...)
and the lineage registry through its existing owner
(``src/sources/source_census.py``).  Methodology that binds how the numbers may
be used: ``docs/sources/SOURCE_VOTING_CONSENSUS_2026-10-19.md`` -- agreement
between different providers is consensus, and rank or value similarity alone
never merges, caps, excludes or haircuts a vote.  So the functions here keep
two kinds of number apart:

* SIMILARITY (rank / vote-value correlation, identical order): reported, never
  a basis for a cap;
* LINEAGE (a recorded ``PROVEN_COMMON_ANCESTRY`` relation, identical raw
  values, or a pipeline-structural fact such as the shared-market ladder):
  classified by :func:`pair_lineage` / :func:`ladder_coupling`.

Pure functions over plain dicts, so tests can feed synthetic rows.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from src.sources.source_census import (
    LINEAGE_PROVEN_COMMON_ANCESTRY,
    lineage_category,
    relation_dependence_category,
)

AXES: tuple[str, ...] = ("independence", "coverage", "freshness", "applicability", "agreement")
LEVEL_ORDER: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def idp_rows(contract: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Every IDP row of a built contract (priced or not)."""
    return [r for r in contract.get("playersArray") or [] if r.get("assetClass") == "idp"]


def _meta(row: Mapping[str, Any], key: str) -> Mapping[str, Any] | None:
    m = (row.get("sourceRankMeta") or {}).get(key)
    return m if isinstance(m, Mapping) else None


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def voting_keys(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Source keys that carried a positive applied weight on at least one row."""
    out: set[str] = set()
    for row in rows:
        for key, m in (row.get("sourceRankMeta") or {}).items():
            w = _num((m or {}).get("appliedWeight"))
            if w is not None and w > 0:
                out.add(str(key))
    return sorted(out)


def average_ranks(values: Sequence[float]) -> list[float]:
    """1-based ranks, ties share their average rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """Spearman rank correlation (Pearson on average ranks); ``None`` when
    undefined (fewer than 2 points or a constant side) -- never 0."""
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = average_ranks(xs), average_ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    return sxy / math.sqrt(sxx * syy)


def weight_shares(rows: Sequence[Mapping[str, Any]], keys: Sequence[str]) -> dict[str, dict]:
    """Applied voting weight per source over ``rows``.

    ``pooledShare`` = sum of the source's ``appliedWeight`` / sum over all
    ``keys``.  ``meanRowShare`` = the mean over rows of the source's share of
    THAT row's applied weight (rows with no applied weight are skipped).
    """
    totals = dict.fromkeys(keys, 0.0)
    counts = dict.fromkeys(keys, 0)
    row_shares: dict[str, list[float]] = {k: [] for k in keys}
    for row in rows:
        w = {}
        for k in keys:
            m = _meta(row, k)
            v = _num((m or {}).get("appliedWeight")) if m else None
            w[k] = v if v is not None and v > 0 else 0.0
        s = sum(w.values())
        if s <= 0:
            continue
        for k in keys:
            totals[k] += w[k]
            if w[k] > 0:
                counts[k] += 1
            row_shares[k].append(w[k] / s)
    grand = sum(totals.values())
    return {
        k: {
            "votingRows": counts[k],
            "appliedWeightSum": round(totals[k], 4),
            "pooledShare": round(totals[k] / grand, 4) if grand else None,
            "meanRowShare": round(sum(row_shares[k]) / len(row_shares[k]), 4)
            if row_shares[k]
            else None,
        }
        for k in keys
    }


def _stat_getter(stat: str) -> Callable[[Mapping[str, Any], str], float | None]:
    if stat == "rawRank":
        return lambda row, k: _num((_meta(row, k) or {}).get("rawRank"))
    if stat == "effectiveRank":
        return lambda row, k: _num((_meta(row, k) or {}).get("effectiveRank"))
    if stat == "voteValue":
        return lambda row, k: _num((_meta(row, k) or {}).get("valueContribution"))
    raise ValueError(f"unknown statistic {stat!r}")


def pairwise_spearman(
    rows: Sequence[Mapping[str, Any]], keys: Sequence[str], stat: str
) -> dict[str, dict]:
    """Spearman between every voter pair on the rows both stamped.

    ``stat`` is ``rawRank`` (the source's own coordinate: order only),
    ``effectiveRank`` (after any shared-market translation) or ``voteValue``
    (the pre-blend vote, ``valueContribution``).  Keyed ``"a|b"``.
    """
    get = _stat_getter(stat)
    out: dict[str, dict] = {}
    for i, a in enumerate(keys):
        for b in keys[i + 1 :]:
            xs: list[float] = []
            ys: list[float] = []
            for row in rows:
                x, y = get(row, a), get(row, b)
                if x is not None and y is not None:
                    xs.append(x)
                    ys.append(y)
            rho = spearman(xs, ys)
            out[f"{a}|{b}"] = {"n": len(xs), "spearman": None if rho is None else round(rho, 4)}
    return out


def identical_value_share(
    rows: Sequence[Mapping[str, Any]], a: str, b: str, field: str = "canonicalSiteValues"
) -> dict[str, Any]:
    """Share of co-covered rows whose RAW value for ``a`` equals ``b``'s.

    Meaningful as lineage evidence only when both sources publish the SAME kind
    of number (``comparableEncoding``): two native 0-9999 values, not a native
    value against a rank encoding.  ``canonicalSiteValues`` of a rank-signal
    source is an encoding of its rank, so there equality is rank equality --
    similarity, which is never lineage.
    """
    both = equal = 0
    for row in rows:
        vals = row.get(field) or {}
        x, y = _num(vals.get(a)), _num(vals.get(b))
        if x is None or y is None:
            continue
        both += 1
        equal += x == y
    paths = {
        p
        for row in rows
        for p in (
            (_meta(row, a) or {}).get("valueContributionPath"),
            (_meta(row, b) or {}).get("valueContributionPath"),
        )
        if p
    }
    comparable = paths == {"value_direct"}
    return {
        "n": both,
        "identical": equal,
        "share": round(equal / both, 4) if both else None,
        "comparableEncoding": comparable,
    }


def translation_profile(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, Any]:
    """How a source's vote reaches the shared-market coordinate.

    ``orderOnly`` is True when ``effectiveRank`` is a monotone non-decreasing
    function of the source's own ``rawRank`` on every row it stamped: the
    source then contributes only its ORDER and the LEVEL comes from the ladder.
    """
    paths: Counter = Counter()
    methods: Counter = Counter()
    translated = 0
    pairs: list[tuple[float, float]] = []
    ladder_depths: set[int] = set()
    backbone_depths: set[int] = set()
    n = 0
    for row in rows:
        m = _meta(row, key)
        if not m or not (_num(m.get("appliedWeight")) or 0) > 0:
            continue
        n += 1
        paths[str(m.get("valueContributionPath"))] += 1
        methods[str(m.get("method"))] += 1
        if m.get("sharedMarketTranslated"):
            translated += 1
            for fld, sink in (("ladderDepth", ladder_depths), ("backboneDepth", backbone_depths)):
                d = _num(m.get(fld))
                if d is not None:
                    sink.add(int(d))
        rr, er = _num(m.get("rawRank")), _num(m.get("effectiveRank"))
        if rr is not None and er is not None:
            pairs.append((rr, er))
    pairs.sort()
    descents = sum(1 for (_, e1), (_, e2) in zip(pairs, pairs[1:]) if e2 < e1)
    return {
        "votingRows": n,
        "translatedRows": translated,
        "translatedShare": round(translated / n, 4) if n else None,
        "valuePaths": dict(paths),
        "methods": dict(methods),
        "ladderDepths": sorted(ladder_depths),
        "backboneDepths": sorted(backbone_depths),
        "orderOnly": (not descents) if pairs else None,
        "rankDescents": descents,
    }


def ladder_coupling(
    rows: Sequence[Mapping[str, Any]], translated_key: str, anchor_key: str
) -> dict[str, Any]:
    """How much of ``translated_key``'s LEVEL is the anchor board's own positions.

    Under a single-contributor ladder, entry ``i`` is the combined rank at which
    the anchor's ``i``-th IDP sits, so every translated ``effectiveRank`` is
    one of the anchor board's own ``rawRank`` values.  ``ladderSetShare`` is the
    share of translated votes landing exactly on such a position.  This is a
    pipeline-STRUCTURAL fact (our translation), not provider data lineage.
    """
    anchor_positions = {
        r
        for row in rows
        for r in [_num((_meta(row, anchor_key) or {}).get("rawRank"))]
        if r is not None
    }
    n = hit = 0
    for row in rows:
        m = _meta(row, translated_key)
        if not m or not m.get("sharedMarketTranslated"):
            continue
        er = _num(m.get("effectiveRank"))
        if er is None:
            continue
        n += 1
        hit += er in anchor_positions
    return {
        "translatedVotes": n,
        "onAnchorPositions": hit,
        "ladderSetShare": round(hit / n, 4) if n else None,
        "anchorPositions": len(anchor_positions),
    }


def pair_lineage(
    lineage: Mapping[str, Any], provider_of: Callable[[str], str | None], a: str, b: str
) -> dict[str, Any]:
    """What the lineage registry records about a source pair, classified for the
    2026-10-19 rule.  ``countsAsLineageEvidence`` is True only for a
    ``PROVEN_COMMON_ANCESTRY`` relation or a shared recorded provider; a
    MEASURED or SUSPECTED relation is similarity and never qualifies."""
    rels = []
    for rel in lineage.get("relations") or []:
        members = {str(s) for s in rel.get("sources") or []}
        if a in members and b in members:
            rels.append(
                {
                    "id": rel.get("id"),
                    "classification": rel.get("classification"),
                    "category": lineage_category(rel),
                    "dependenceCategory": relation_dependence_category(rel),
                }
            )
    pa, pb = provider_of(a), provider_of(b)
    same_provider = bool(pa and pa == pb)
    proven = any(r["category"] == LINEAGE_PROVEN_COMMON_ANCESTRY for r in rels)
    return {
        "providers": [pa, pb],
        "sameProvider": same_provider,
        "relations": rels,
        "countsAsLineageEvidence": proven or same_provider,
    }


def confidence_profile(
    rows: Sequence[Mapping[str, Any]],
    *,
    independence_high_families: int,
) -> dict[str, Any]:
    """What the B11 gate stamped on the priced IDP rows and which axis binds.

    ``bottleneckAxes`` counts, per axis, the rows on which that axis equals the
    row's weakest level, when that level is below high (an overall bucket is the weakest axis).
    ``soleBlockerAxes`` counts rows where exactly ONE axis is below high, i.e.
    where that axis alone keeps the row from "high".  The gate is read, never
    re-decided.
    """
    buckets: Counter = Counter()
    axis_levels: dict[str, Counter] = {a: Counter() for a in AXES}
    bottleneck: Counter = Counter()
    sole_blocker: Counter = Counter()
    families: Counter = Counter()
    n = 0
    for row in rows:
        axes = row.get("confidenceAxes")
        if not isinstance(axes, Mapping):
            continue
        n += 1
        buckets[str(row.get("confidenceBucket"))] += 1
        levels = {a: axes.get(a) for a in AXES if axes.get(a) in LEVEL_ORDER}
        for a, lv in levels.items():
            axis_levels[a][lv] += 1
        if levels:
            floor = min(LEVEL_ORDER[v] for v in levels.values())
            for a, lv in levels.items():
                if LEVEL_ORDER[lv] == floor and lv != "high":
                    bottleneck[a] += 1
            below = [a for a, lv in levels.items() if lv != "high"]
            if len(below) == 1:
                sole_blocker[below[0]] += 1
        fam = row.get("independentSourceCount")
        if isinstance(fam, int) and not isinstance(fam, bool):
            families[fam] += 1
    return {
        "rowsWithAxes": n,
        "buckets": dict(buckets),
        "axisLevels": {a: dict(c) for a, c in axis_levels.items()},
        "bottleneckAxes": dict(bottleneck),
        "soleBlockerAxes": dict(sole_blocker),
        "independentFamiliesPerRow": {str(k): v for k, v in sorted(families.items())},
        "maxFamiliesOnAnyRow": max(families) if families else None,
        "independenceHighFamilies": independence_high_families,
        "rowsAtOrAboveHighFamilies": sum(
            v for k, v in families.items() if k >= independence_high_families
        ),
    }


def withheld_reasons(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    """Per source, how often ``sourceAuthorityReasons`` names it and under which
    reason class (``held`` / ``stale`` / other), over ``rows``."""
    out: dict[str, Counter] = {}
    for row in rows:
        for key, reason in (row.get("sourceAuthorityReasons") or {}).items():
            cls = str(reason).split(":", 1)[0].split("=", 1)[0]
            out.setdefault(str(key), Counter())[cls] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def board_diff(
    base_rows: Iterable[Mapping[str, Any]],
    alt_rows: Iterable[Mapping[str, Any]],
    key: Callable[[Mapping[str, Any]], Any] = lambda r: r.get("displayName"),
) -> dict[str, Any]:
    """Read-only value / bucket diff between two builds over matched rows."""
    alt = {key(r): r for r in alt_rows}
    deltas: list[float] = []
    flips = 0
    rank_moves = 0
    matched = 0
    for r in base_rows:
        o = alt.get(key(r))
        if o is None:
            continue
        v0, v1 = _num(r.get("rankDerivedValue")), _num(o.get("rankDerivedValue"))
        if v0 is None or v1 is None or v0 <= 0:
            continue
        matched += 1
        deltas.append(abs(v1 - v0) / v0)
        flips += r.get("confidenceBucket") != o.get("confidenceBucket")
        rank_moves += r.get("canonicalConsensusRank") != o.get("canonicalConsensusRank")
    deltas.sort()

    def pct(p: float) -> float | None:
        if not deltas:
            return None
        return round(deltas[min(len(deltas) - 1, int(p * len(deltas)))] * 100, 3)

    return {
        "matchedRows": matched,
        "valuesMoved": sum(1 for d in deltas if d > 0),
        "medianAbsPct": pct(0.5),
        "p90AbsPct": pct(0.9),
        "maxAbsPct": round(deltas[-1] * 100, 3) if deltas else None,
        "confidenceBucketFlips": flips,
        "consensusRankChanges": rank_moves,
    }
