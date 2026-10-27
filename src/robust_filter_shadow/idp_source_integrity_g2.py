"""Workstream G2: IDP source-integrity evaluation (SHADOW RESEARCH ONLY).

Preregistration: ``docs/valuation/idp_accuracy/g2_source_integrity/PREREGISTRATION.md``.

This module READS a built contract (``build_api_data_contract`` output), the
source CSV tables the build read, the lineage registry and per-source git
content clocks, and classifies every IDP (row, source) observation.  It never
changes a vote, a weight, a value, a flag or a served field; nothing in ``src/``
outside this module imports it (``tests/robust_filter_shadow/
test_idp_source_integrity_g2.py`` pins that).

Design principle (the lesson of Outlier Integrity V2): answer STRUCTURAL
questions first (identity, position family, normalization, staleness, lineage,
coverage) and treat disagreement last, as a CLASSIFICATION, never a drop.
Agreement between different providers is consensus; disagreement between them
is legitimate unless a structural defect corroborates it.  Missing is never
zero: an observation that did not vote is absent from every statistic that is
computed over votes, and a row with no other provider is ``not_evaluable``.

Every threshold below is FROZEN by the preregistration
(``THRESHOLDS`` == ``PREREGISTRATION.json::thresholds``, pinned by a test).
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.utils.name_clean import canonical_player_key, normalize_position_family

SCHEMA = "g2-idp-source-integrity/v1"
IDP_FAMILIES = ("DL", "LB", "DB")
LN = math.log

#: Frozen by the preregistration (section 4).  Changing any value after the
#: held-out read is a logged deviation, never a silent edit.
THRESHOLDS: dict[str, float | int] = {
    # disagreement classes over u = ln(provider vote / median of the other providers)
    "tauAgree": round(LN(2.0), 6),
    "tauExtreme": round(LN(3.0), 6),
    # minimum other providers for a leave-one-provider-out reference
    "minOtherProviders": 2,
    # segment (source x family) level shift
    "tauSegment": round(LN(2.5), 6),
    "segmentMinRows": 15,
    # rank-basis mixing (combined board): within-family ordinal k vs source rank
    "basisProbeK": 24,
    "basisMixedLowSlope": 1.25,
    "basisMixedHighSlope": 2.0,
    "basisMixedCollisionShare": 0.25,
    # stale-stamp consistency (hours)
    "stampAfterContentToleranceH": 1.0,
    "stampBeforeBroadChangeToleranceH": 36.0,
    # broad ranking change (mirrors config/sources/freshness_v1.json::broadChange)
    "broadChangeMinRows": 5,
    "broadChangeMinFraction": 0.02,
    # value-curve monotonicity slack (board points)
    "valueInversionSlack": 1.0,
    # deep tail
    "deepTailIdpRank": 216,
    "tailSaturationRank": 904,
    # evaluator-validity gates (E-gates)
    "e6RowCorruptionRecallMin": 0.90,
    "e6CleanExtremeRateMax": 0.05,
    "e7SwapRecallMin": 0.80,
    "e10RuntimeSecondsMax": 60.0,
}

#: Vendor-published position columns, by CSV header.  The first present wins.
VENDOR_POSITION_COLUMNS = ("family", "Fantasy Position", "position", "Position", "pos")
#: Vendor rank columns, by CSV header.  The first present wins.
VENDOR_RANK_COLUMNS = ("originalRank", "Rank", "rank")

DEFECT = "defect"
ADVISORY = "advisory"


# ── small helpers ──────────────────────────────────────────────────────


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return None
    f = float(x)
    return f if math.isfinite(f) else None


def _family(pos: Any) -> str:
    fam = normalize_position_family(str(pos)) if pos else ""
    return fam if fam in IDP_FAMILIES else (fam or "")


def _name_key(name: Any) -> str:
    return canonical_player_key(str(name or ""), None)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _hours(a: datetime, b: datetime) -> float:
    return (a - b).total_seconds() / 3600.0


def digest(obj: Any) -> str:
    blob = json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# ── inputs ─────────────────────────────────────────────────────────────


def read_csv_tables(site_raw: Path, sources: Iterable[str]) -> dict[str, list[dict[str, str]]]:
    """``{source: [row dict, ...]}`` for every ``<source>.csv`` present (absent = missing)."""
    out: dict[str, list[dict[str, str]]] = {}
    for src in sorted(set(sources)):
        path = site_raw / f"{src}.csv"
        if not path.is_file():
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            out[src] = [dict(r) for r in csv.DictReader(fh)]
    return out


def _vendor_index(table: Sequence[Mapping[str, str]]) -> dict[str, list[dict[str, Any]]]:
    """``{canonical name key: [entry, ...]}`` of a vendor CSV.

    Several entries under one key are either the SAME player listed twice (a
    dual-family listing) or DIFFERENT players whose names collide once
    suffixes are stripped (Byron Murphy II vs Byron Murphy Jr.).  Both are kept
    so the identity check can tell them apart."""
    if not table:
        return {}
    cols = table[0].keys()
    pcol = next((c for c in VENDOR_POSITION_COLUMNS if c in cols), None)
    rcol = next((c for c in VENDOR_RANK_COLUMNS if c in cols), None)
    vcol = next((c for c in ("value", "3D Value +", "normalizedValue") if c in cols), None)
    out: dict[str, list[dict[str, Any]]] = {}
    for r in table:
        raw = (r.get("name") or r.get("Player") or r.get("player") or "").strip()
        if not raw:
            continue
        pos = (r.get(pcol) or "").strip() if pcol else ""
        out.setdefault(_name_key(raw), []).append(
            {
                "rawName": raw,
                "position": pos,
                "family": _family(pos),
                "rank": _maybe_float(r.get(rcol)) if rcol else None,
                "value": _maybe_float(r.get(vcol)) if vcol else None,
            }
        )
    return out


def _vendor_entry(entries: Sequence[Mapping[str, Any]], matched: str) -> tuple[dict | None, str]:
    """The vendor entry an observation used, and how it was resolved.

    ``single`` | ``exact_among_collision`` (different raw names share the key,
    exactly one equals the matched name) | ``dual_listing`` (one player listed
    several times) | ``unresolvable`` | ``absent``."""
    if not entries:
        return None, "absent"
    if len(entries) == 1:
        return dict(entries[0]), "single"
    exact = [e for e in entries if e["rawName"] == matched]
    raw_names = {e["rawName"] for e in entries}
    if len(raw_names) > 1 and len(exact) == 1:
        return dict(exact[0]), "exact_among_collision"
    if len(raw_names) == 1 or len(exact) > 1:
        pool = exact or list(entries)
        fams = sorted({e["family"] for e in pool if e["family"]})
        ent = dict(pool[0])
        ent["family"] = fams[0] if len(fams) == 1 else None
        ent["families"] = fams
        return ent, "dual_listing"
    return None, "unresolvable"


def _maybe_float(x: Any) -> float | None:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def lineage_providers(lineage: Mapping[str, Any]) -> dict[str, str]:
    return {
        str(k): str(v.get("provider"))
        for k, v in (lineage.get("sources") or {}).items()
        if isinstance(v, Mapping) and v.get("provider")
    }


def lineage_relations_between(lineage: Mapping[str, Any], sources: Iterable[str]) -> list[dict]:
    """Recorded relations that touch at least two of ``sources``."""
    srcs = set(sources)
    out = []
    for rel in lineage.get("relations") or []:
        members = sorted(srcs.intersection(rel.get("sources") or []))
        if len(members) >= 2:
            out.append(
                {
                    "id": rel.get("id"),
                    "relation": rel.get("relation"),
                    "classification": rel.get("classification"),
                    "members": members,
                }
            )
    return sorted(out, key=lambda r: str(r["id"]))


# ── panel extraction ───────────────────────────────────────────────────


def extract_panel(
    contract: Mapping[str, Any],
    csv_tables: Mapping[str, Sequence[Mapping[str, str]]],
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    """The IDP observation panel of one built board.

    ``rows``: every IDP row.  ``observations``: every (row, source) pair the
    board MATCHED, voting or not, with the reason it did not vote.
    """
    providers = lineage_providers(lineage)
    sleeper = contract.get("sleeper") or {}
    id_to_name = sleeper.get("idToPlayer") or {}
    sl_pos = sleeper.get("positions") or {}
    sl_fpos = sleeper.get("fantasyPositions") or {}
    vendor = {src: _vendor_index(tab) for src, tab in csv_tables.items()}

    rows: list[dict[str, Any]] = []
    obs: list[dict[str, Any]] = []
    for r in contract.get("playersArray") or []:
        if not isinstance(r, Mapping) or r.get("assetClass") != "idp":
            continue
        name = str(r.get("displayName") or "")
        pid = r.get("playerId")
        pid = str(pid) if pid not in (None, "") else None
        fam = _family(r.get("position"))
        eligible = sorted({_family(p) for p in (sl_fpos.get(name) or [])} - {""})
        row = {
            "name": name,
            "key": _name_key(name),
            "playerId": pid,
            "family": fam,
            "sleeperName": id_to_name.get(pid) if pid else None,
            "sleeperFamily": _family(sl_pos.get(name)) if sl_pos.get(name) else None,
            "eligibleFamilies": eligible,
            "value": _num(r.get("rankDerivedValue")),
            "rank": r.get("canonicalConsensusRank"),
            "quarantined": bool(r.get("quarantined")),
            "anomalyFlags": sorted(r.get("anomalyFlags") or []),
            "droppedSources": sorted(r.get("droppedSources") or []),
            "confidence": r.get("confidenceBucket"),
        }
        rows.append(row)
        meta = r.get("sourceRankMeta") or {}
        details = ((r.get("sourceAudit") or {}).get("matchedDetails")) or {}
        site_vals = r.get("canonicalSiteValues") or {}
        orig_ranks = r.get("sourceOriginalRanks") or {}
        sources = (
            set(meta)
            | set(details)
            | {s for s, v in site_vals.items() if v is not None and s != "ktc"}
        )
        for src in sorted(sources):
            m = meta.get(src) or {}
            d = details.get(src) or {}
            value = _num(m.get("valueContribution"))
            excluded = m.get("excludedReason")
            if src in row["droppedSources"]:
                reason = "outlier_filter"
            elif excluded:
                reason = str(excluded)
            elif not m:
                reason = "not_voting_by_registry_or_hold"
            elif value is None or value <= 0:
                reason = "nonpositive_or_missing_vote"
            else:
                reason = None
            matched = d.get("matchedName") or name
            vend, vend_how = _vendor_entry(
                (vendor.get(src) or {}).get(_name_key(matched)) or [], matched
            )
            vend = vend or {}
            cands = sorted(set(d.get("candidates") or []))
            obs.append(
                {
                    "row": name,
                    "source": src,
                    "provider": providers.get(src, "UNREGISTERED"),
                    "voted": reason is None,
                    "exclusion": reason,
                    "rawRank": _num(m.get("rawRank", orig_ranks.get(src))),
                    "effectiveRank": _num(m.get("effectiveRank")),
                    "value": value,
                    "valuePath": m.get("valueContributionPath"),
                    "method": m.get("method"),
                    "scope": m.get("scope"),
                    "sharedMarketTranslated": bool(m.get("sharedMarketTranslated")),
                    "freshness": _num(m.get("freshness")),
                    "freshnessAgeHours": _num(m.get("freshnessAgeHours")),
                    "appliedWeight": _num(m.get("appliedWeight")),
                    "matchedName": matched,
                    "ambiguous": bool(d.get("ambiguous")),
                    "candidates": len(d.get("candidates") or []),
                    "candidateNames": cands,
                    "candidateKeys": sorted({_name_key(x) for x in cands}),
                    "vendorResolution": vend_how if src in vendor else "no_vendor_table",
                    "vendorPosition": vend.get("position") or None,
                    "vendorValue": vend.get("value"),
                    "vendorFamily": vend.get("family") or None,
                    "vendorFamilies": vend.get("families")
                    or ([vend["family"]] if vend.get("family") else []),
                }
            )
    rows.sort(key=lambda x: x["name"])
    obs.sort(key=lambda x: (x["row"], x["source"]))
    return {"rows": rows, "observations": obs}


# ── checks ─────────────────────────────────────────────────────────────


def identity_findings(panel: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Identity + position-family findings, one entry per (row, source, code)."""
    rows = {r["name"]: r for r in panel["rows"]}
    out: list[dict[str, Any]] = []

    def add(row, src, code, sev, detail):
        out.append({"row": row, "source": src, "code": code, "severity": sev, "detail": detail})

    for r in panel["rows"]:
        if not r["playerId"]:
            add(r["name"], None, "no_player_id", ADVISORY, "row carries no Sleeper id (name-only)")
        elif r["sleeperName"] is not None and _name_key(r["sleeperName"]) != r["key"]:
            add(
                r["name"], None, "sleeper_name_mismatch", DEFECT, f"id maps to {r['sleeperName']!r}"
            )
        if r["sleeperFamily"] and r["family"] and r["sleeperFamily"] != r["family"]:
            if r["family"] in r["eligibleFamilies"]:
                add(r["name"], None, "family_multi_eligible", ADVISORY, r["eligibleFamilies"])
            else:
                add(
                    r["name"],
                    None,
                    "sleeper_family_contradiction",
                    DEFECT,
                    f"row {r['family']} vs Sleeper {r['sleeperFamily']}",
                )
    shared: dict[tuple[str, str], list[str]] = defaultdict(list)
    for o in panel["observations"]:
        row = rows.get(o["row"]) or {}
        eligible = set(row.get("eligibleFamilies") or [])
        if row.get("family"):
            eligible.add(row["family"])
        how = o.get("vendorResolution")
        if how == "unresolvable":
            add(o["row"], o["source"], "unresolvable_vendor_collision", DEFECT, o["candidateNames"])
        elif how == "dual_listing":
            fams = set(o.get("vendorFamilies") or [])
            if fams and not fams <= eligible:
                add(o["row"], o["source"], "dual_listing_wrong_family", DEFECT, sorted(fams))
            else:
                add(o["row"], o["source"], "dual_family_listing", ADVISORY, sorted(fams))
        elif how == "exact_among_collision":
            add(o["row"], o["source"], "vendor_name_key_collision", ADVISORY, o["matchedName"])
        if o["vendorFamily"] and row.get("family") and o["vendorFamily"] != row["family"]:
            if o["vendorFamily"] in eligible:
                add(
                    o["row"],
                    o["source"],
                    "vendor_family_alt_eligible",
                    ADVISORY,
                    o["vendorPosition"],
                )
            else:
                add(
                    o["row"],
                    o["source"],
                    "vendor_family_mismatch",
                    DEFECT,
                    f"vendor {o['vendorPosition']} vs row {row['family']}",
                )
        if _name_key(o["matchedName"]) != row.get("key"):
            add(o["row"], o["source"], "fuzzy_join", ADVISORY, o["matchedName"])
        if len(o.get("candidateKeys") or []) > 1:
            # differently named vendor entries competed for this one row
            add(o["row"], o["source"], "ambiguous_alias_join", DEFECT, o["candidateNames"])
        shared[(o["source"], _name_key(o["matchedName"]))].append(o["row"])
    for (src, _k), names in sorted(shared.items()):
        if len(names) > 1:
            for n in sorted(names):
                add(n, src, "shared_vendor_entry", DEFECT, sorted(names))
    out.sort(key=lambda f: (f["row"], str(f["source"]), f["code"]))
    return out


def normalization_findings(panel: Mapping[str, Any]) -> dict[str, Any]:
    """Per-source monotonicity of the rank translation and of the vote curve,
    non-positive votes, and rank-basis mixing across families."""
    t = THRESHOLDS
    by_src: dict[str, list[dict]] = defaultdict(list)
    fam = {r["name"]: r["family"] for r in panel["rows"]}
    for o in panel["observations"]:
        by_src[o["source"]].append(o)
    per_source: dict[str, Any] = {}
    defects: list[dict[str, Any]] = []
    for src in sorted(by_src):
        obs = by_src[src]
        ranked = sorted(
            (o for o in obs if o["rawRank"] is not None and o["effectiveRank"] is not None),
            key=lambda o: (o["rawRank"], o["effectiveRank"], o["row"]),
        )
        inv = _translation_inversions(ranked)
        voted = sorted(
            (o for o in obs if o["value"] is not None and o["effectiveRank"] is not None),
            key=lambda o: (o["effectiveRank"], -o["value"], o["row"]),
        )
        vinv = [
            (a["row"], b["row"])
            for a, b in zip(voted, voted[1:])
            if b["effectiveRank"] > a["effectiveRank"]
            and b["value"] > a["value"] + t["valueInversionSlack"]
        ]
        nonpos = sorted(o["row"] for o in obs if o["exclusion"] == "nonpositive_or_missing_vote")
        basis = rank_basis_probe(
            [
                (fam.get(o["row"], ""), o["rawRank"], o.get("vendorValue"))
                for o in obs
                if o["rawRank"] is not None
            ]
        )
        per_source[src] = {
            "observations": len(obs),
            "voted": sum(1 for o in obs if o["voted"]),
            "translationInversions": len(inv),
            "valueInversions": len(vinv),
            "nonPositiveVotes": len(nonpos),
            "rankBasis": basis,
            "methods": dict(sorted(Counter(str(o["method"]) for o in obs).items())),
        }
        for a, b in inv:
            defects.append({"source": src, "code": "translation_inversion", "rows": [a, b]})
        for a, b in vinv:
            defects.append({"source": src, "code": "value_inversion", "rows": [a, b]})
        for n in nonpos:
            defects.append({"source": src, "code": "nonpositive_vote", "rows": [n]})
        if basis.get("mixed"):
            defects.append({"source": src, "code": "rank_basis_mixed", "rows": [], "detail": basis})
    return {"perSource": per_source, "defects": defects}


def _translation_inversions(ranked: Sequence[Mapping[str, Any]]) -> list[tuple[str, str]]:
    """Pairs (earlier, later) where a strictly worse source rank received a
    strictly better effective rank.  Ties in the source rank are never an
    inversion, whatever order the translation gives them."""
    out: list[tuple[str, str]] = []
    best_prev: tuple[float, str] | None = None
    i = 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j]["rawRank"] == ranked[i]["rawRank"]:
            j += 1
        group = ranked[i:j]
        if best_prev is not None:
            for o in group:
                if o["effectiveRank"] < best_prev[0]:
                    out.append((best_prev[1], o["row"]))
        top = max(group, key=lambda o: (o["effectiveRank"], o["row"]))
        if best_prev is None or top["effectiveRank"] > best_prev[0]:
            best_prev = (top["effectiveRank"], top["row"])
        i = j
    return out


def rank_basis_probe(fam_ranks: Sequence[tuple]) -> dict[str, Any]:
    """Within-family ordinal ``k`` vs the source's own rank at ``k``.

    On a COMBINED IDP list each family's ``rank / k`` sits well above 1 (three
    families share the list).  A family whose ranks restart at 1 (a
    per-position list mixed into a combined one; the ROS defect class of PR
    #1997) has slope ~1 while the others do not.  Families with fewer than
    ``basisProbeK`` ranks abstain.

    Entries are ``(family, source rank[, vendor value])``.  Two families at one
    rank are a COLLISION only when their vendor values differ (or are unknown):
    equal values are a vendor tie, which a combined list legitimately has."""
    t = THRESHOLDS
    k = int(t["basisProbeK"])
    entries = [(e[0], e[1], e[2] if len(e) > 2 else None) for e in fam_ranks]
    slopes: dict[str, float] = {}
    for f in IDP_FAMILIES:
        ranks = sorted(r for fa, r, _v in entries if fa == f)
        if len(ranks) >= k:
            slopes[f] = round(ranks[k - 1] / k, 4)
    if len(slopes) < 2:
        return {"slopesAtK": slopes, "mixed": False, "evaluable": False}
    lo, hi = min(slopes.values()), max(slopes.values())
    # A restarted family shares its small ranks with the other families; a
    # combined list that merely favours one family does not.
    at: dict[float, list[tuple[str, Any]]] = defaultdict(list)
    for fa, r, v in entries:
        if fa in IDP_FAMILIES and r <= k * max(lo, 1.0):
            at[r].append((fa, v))
    distinct = len(at)

    def collides(items: list[tuple[str, Any]]) -> bool:
        if len({fa for fa, _v in items}) < 2:
            return False
        vals = [v for _fa, v in items]
        return any(v is None for v in vals) or len(set(vals)) > 1

    share = sum(1 for items in at.values() if collides(items)) / distinct if distinct else 0.0
    slope_gap = lo <= t["basisMixedLowSlope"] and hi >= t["basisMixedHighSlope"]
    # Or the low-slope family's whole top k sits above every other family's
    # best rank (a restart onto a board whose IDP ranks start deep, such as a
    # cross-market list where offense holds the first ranks).
    low_fam = min(slopes, key=lambda f: (slopes[f], f))
    low_ranks = sorted(r for fa, r, _v in entries if fa == low_fam)
    other_best = min((r for fa, r, _v in entries if fa in slopes and fa != low_fam), default=None)
    segregated = bool(other_best is not None and low_ranks[k - 1] < other_best)
    mixed = bool(slope_gap and (share >= t["basisMixedCollisionShare"] or segregated))
    return {
        "slopesAtK": slopes,
        "evaluable": True,
        "lowSlopeFamily": low_fam,
        "probedRanks": distinct,
        "crossFamilyCollisionShare": round(share, 4),
        "lowFamilyTopKAboveAllOthers": segregated,
        "familyDominanceOnly": bool(slope_gap and not mixed),
        "mixed": mixed,
    }


def provider_votes(panel: Mapping[str, Any]) -> dict[str, dict[str, float]]:
    """``{row: {provider: vote}}`` -- one vote per PROVIDER (median of its voting
    sources), so a provider's several boards are never counted as several
    opinions.  Different providers stay separate (consensus, not duplication)."""
    acc: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for o in panel["observations"]:
        if o["voted"] and o["value"] is not None and o["value"] > 0:
            acc[o["row"]][o["provider"]].append(o["value"])
    return {
        row: {p: float(statistics.median(v)) for p, v in sorted(pv.items())}
        for row, pv in sorted(acc.items())
    }


def disagreement(
    panel: Mapping[str, Any], votes: Mapping[str, Mapping[str, float]] | None = None
) -> list[dict]:
    """Leave-one-provider-out log ratio and class for every provider vote."""
    t = THRESHOLDS
    votes = provider_votes(panel) if votes is None else votes
    out = []
    for row in sorted(votes):
        pv = votes[row]
        for p in sorted(pv):
            others = [v for q, v in pv.items() if q != p]
            if len(others) < t["minOtherProviders"]:
                out.append(
                    {"row": row, "provider": p, "u": None, "class": "not_evaluable", "n": len(pv)}
                )
                continue
            u = LN(pv[p] / statistics.median(others))
            au = abs(u)
            cls = (
                "agree"
                if au <= t["tauAgree"]
                else "dissent"
                if au <= t["tauExtreme"]
                else "extreme"
            )
            out.append({"row": row, "provider": p, "u": round(u, 6), "class": cls, "n": len(pv)})
    return out


def segment_shifts(panel: Mapping[str, Any], dis: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Median ``u`` per (provider, family) over evaluable votes."""
    t = THRESHOLDS
    fam = {r["name"]: r["family"] for r in panel["rows"]}
    g: dict[tuple[str, str], list[float]] = defaultdict(list)
    for d in dis:
        if d["u"] is not None:
            g[(d["provider"], fam.get(d["row"], ""))].append(d["u"])
    out = []
    for (p, f), us in sorted(g.items()):
        evaluable = len(us) >= t["segmentMinRows"]
        med = statistics.median(us) if us else None
        out.append(
            {
                "provider": p,
                "family": f,
                "n": len(us),
                "medianU": round(med, 6) if med is not None else None,
                "evaluable": evaluable,
                "shift": bool(evaluable and abs(med) > t["tauSegment"]),
            }
        )
    return out


def stale_findings(
    voting_status: Mapping[str, Any],
    content_clocks: Mapping[str, Mapping[str, str | None]],
    idp_sources: Iterable[str],
) -> list[dict[str, Any]]:
    """Pipeline ``lastGenuineUpdate`` vs the git-observed content clocks.

    ``content_clocks[src]`` = ``{"lastByteChange", "lastBroadChange"}``: commit
    times (UTC ISO) of the last commit at or before the board that changed the
    CSV bytes / that changed at least ``broadChangeMinRows`` rows AND
    ``broadChangeMinFraction`` of them, renames at an unchanged rank excluded
    (the broad-change rule of ``src/sources/dataset_state.py``).  A stamp LATER
    than any byte change is impossible; a stamp much EARLIER than the last broad
    change means the pipeline believes the source is older than its rankings."""
    t = THRESHOLDS
    stamps = {
        s.get("key"): s for s in (voting_status.get("sources") or []) if isinstance(s, Mapping)
    }
    out = []
    for src in sorted(set(idp_sources)):
        st = stamps.get(src) or {}
        clocks = content_clocks.get(src) or {}
        stamp = _parse_time(st.get("lastGenuineUpdate"))
        byte = _parse_time(clocks.get("lastByteChange"))
        order = _parse_time(clocks.get("lastBroadChange"))
        rec = {
            "source": src,
            "status": st.get("status"),
            "freshnessPct": st.get("freshnessPct"),
            "lastGenuineUpdate": st.get("lastGenuineUpdate"),
            "lastGenuineUpdateBasis": st.get("lastGenuineUpdateBasis"),
            "gitLastByteChange": clocks.get("lastByteChange"),
            "gitLastBroadChange": clocks.get("lastBroadChange"),
        }
        if stamp is None or byte is None:
            rec["verdict"] = "not_evaluable"
        elif _hours(stamp, byte) > t["stampAfterContentToleranceH"]:
            rec["verdict"] = "stamp_after_content"
        elif order is not None and _hours(order, stamp) > t["stampBeforeBroadChangeToleranceH"]:
            rec["verdict"] = (
                "vendor_stamp_older_than_broad_change"
                if st.get("lastGenuineUpdateBasis") == "publisher_timestamp"
                else "stamp_older_than_broad_change"
            )
            rec["lagHours"] = round(_hours(order, stamp), 2)
        else:
            rec["verdict"] = "consistent"
        out.append(rec)
    return out


def coverage(panel: Mapping[str, Any], votes: Mapping[str, Mapping[str, float]]) -> dict[str, Any]:
    """Independent provider coverage per row, by family and IDP rank band.

    ``levelOwn`` counts providers whose vote carries their OWN level (a direct
    value, or their own cross-position placement) rather than a level borrowed
    through the shared-market translation backbone.  Reported, never capped:
    borrowing a scale is not shared data lineage."""
    t = THRESHOLDS
    own_level: dict[str, set[str]] = defaultdict(set)
    for o in panel["observations"]:
        if o["voted"] and not o["sharedMarketTranslated"]:
            own_level[o["row"]].add(o["provider"])
    ranked = sorted(
        (r for r in panel["rows"] if r["value"]), key=lambda r: (-r["value"], r["name"])
    )
    idp_rank = {r["name"]: i + 1 for i, r in enumerate(ranked)}
    bands = (
        (1, 36),
        (37, 108),
        (109, int(t["deepTailIdpRank"])),
        (int(t["deepTailIdpRank"]) + 1, 10**6),
    )
    table: dict[str, dict[str, Any]] = {}
    for r in panel["rows"]:
        if r["name"] not in idp_rank:
            continue
        k = idp_rank[r["name"]]
        band = next(f"{a}-{b if b < 10**6 else 'end'}" for a, b in bands if a <= k <= b)
        n = len(votes.get(r["name"]) or {})
        cell = table.setdefault(
            f"{r['family']}|{band}", {"rows": 0, "providers": [], "single": 0, "ownLevel": []}
        )
        cell["rows"] += 1
        cell["providers"].append(n)
        cell["ownLevel"].append(len(own_level.get(r["name"]) or ()))
        cell["single"] += int(n == 1)
    for cell in table.values():
        cell["medianProviders"] = statistics.median(cell.pop("providers"))
        cell["medianOwnLevelProviders"] = statistics.median(cell.pop("ownLevel"))
    priced_no_vote = sorted(
        r["name"] for r in panel["rows"] if r["value"] and not votes.get(r["name"])
    )
    return {
        "byFamilyBand": dict(sorted(table.items())),
        "pricedRowsWithoutVote": priced_no_vote,
        "idpRank": idp_rank,
    }


def deep_tail(panel: Mapping[str, Any], idp_rank: Mapping[str, int], votes) -> dict[str, Any]:
    t = THRESHOLDS
    tail = [r for r in panel["rows"] if idp_rank.get(r["name"], 0) > t["deepTailIdpRank"]]
    nonpos = sorted(r["name"] for r in panel["rows"] if r["value"] is not None and r["value"] <= 0)
    sat = Counter()
    plateau: dict[str, int] = {}
    by_src: dict[str, Counter] = defaultdict(Counter)
    for o in panel["observations"]:
        if o["voted"] and o["effectiveRank"] is not None:
            if o["effectiveRank"] > t["tailSaturationRank"]:
                sat[o["source"]] += 1
            if idp_rank.get(o["row"], 0) > t["deepTailIdpRank"] and o["rawRank"] is not None:
                by_src[o["source"]][o["rawRank"]] += 1
    for src, c in sorted(by_src.items()):
        plateau[src] = max(c.values()) if c else 0
    return {
        "tailRows": len(tail),
        "tailSingleProvider": sum(1 for r in tail if len(votes.get(r["name"]) or {}) == 1),
        "tailNoVote": sum(1 for r in tail if not votes.get(r["name"])),
        "votesPastSaturation": dict(sorted(sat.items())),
        "largestTiePlateauInTail": plateau,
        "nonPositivePublishedValues": nonpos,
    }


def exclusions(panel: Mapping[str, Any], id_findings, norm) -> dict[str, Any]:
    """Every observation that did not vote, by cause, and whether a G2 structural
    defect explains it.  A filter drop or quarantine with no structural defect
    is a FALSE-EXCLUSION CANDIDATE.  Policy causes (stale weight, a registry
    hold) are reported, never called false."""
    defect_obs = {
        (f["row"], f["source"]) for f in id_findings if f["severity"] == DEFECT and f["source"]
    }
    defect_rows = {f["row"] for f in id_findings if f["severity"] == DEFECT and not f["source"]}
    for d in norm["defects"]:
        for row in d["rows"]:
            defect_obs.add((row, d["source"]))
    by_reason: Counter = Counter()
    candidates = []
    for o in panel["observations"]:
        if o["voted"]:
            continue
        by_reason[f"{o['source']}|{o['exclusion']}"] += 1
        if o["exclusion"] == "outlier_filter":
            explained = (o["row"], o["source"]) in defect_obs or o["row"] in defect_rows
            if not explained:
                candidates.append({"row": o["row"], "source": o["source"], "value": o["value"]})
    quarantined = []
    for r in panel["rows"]:
        if r["quarantined"]:
            quarantined.append(
                {
                    "row": r["name"],
                    "flags": r["anomalyFlags"],
                    "structuralDefect": r["name"] in defect_rows
                    or any(row == r["name"] for row, _ in defect_obs),
                }
            )
    return {
        "byReason": dict(sorted(by_reason.items())),
        "falseExclusionCandidates": sorted(candidates, key=lambda c: (c["row"], c["source"])),
        "quarantinedRows": quarantined,
    }


def attribute(dis, id_findings, norm, panel) -> dict[str, Any]:
    """Legitimate disagreement vs data error, for every extreme provider vote."""
    prov = {(o["row"], o["source"]): o["provider"] for o in panel["observations"]}
    defect_obs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for f in id_findings:
        if f["severity"] == DEFECT:
            if f["source"]:
                defect_obs[(f["row"], prov.get((f["row"], f["source"]), ""))].append(f["code"])
            else:
                defect_obs[(f["row"], "*")].append(f["code"])
    for d in norm["defects"]:
        for row in d["rows"]:
            defect_obs[(row, prov.get((row, d["source"]), ""))].append(d["code"])
    counts = Counter(d["class"] for d in dis)
    extreme = []
    for d in dis:
        if d["class"] != "extreme":
            continue
        codes = sorted(
            set(defect_obs.get((d["row"], d["provider"]), []) + defect_obs.get((d["row"], "*"), []))
        )
        extreme.append(
            {
                **d,
                "attribution": "data_error_corroborated"
                if codes
                else "unexplained_extreme_dissent",
                "structuralCodes": codes,
            }
        )
    return {
        "classCounts": dict(sorted(counts.items())),
        "extreme": extreme,
        "legitimateDisagreement": counts.get("dissent", 0),
    }


def evaluate_panel(
    panel: Mapping[str, Any],
    *,
    voting_status: Mapping[str, Any] | None = None,
    content_clocks: Mapping[str, Mapping[str, str | None]] | None = None,
    lineage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Every G2 check over one panel.  Pure and deterministic."""
    idf = identity_findings(panel)
    norm = normalization_findings(panel)
    votes = provider_votes(panel)
    dis = disagreement(panel, votes)
    seg = segment_shifts(panel, dis)
    cov = coverage(panel, votes)
    tail = deep_tail(panel, cov["idpRank"], votes)
    exc = exclusions(panel, idf, norm)
    att = attribute(dis, idf, norm, panel)
    sources = sorted({o["source"] for o in panel["observations"]})
    voting_sources = sorted({o["source"] for o in panel["observations"] if o["voted"]})
    lin = lineage or {}
    providers = lineage_providers(lin)
    result = {
        "schema": SCHEMA,
        "thresholds": THRESHOLDS,
        "counts": {
            "rows": len(panel["rows"]),
            "pricedRows": sum(1 for r in panel["rows"] if r["value"]),
            "observations": len(panel["observations"]),
            "votes": sum(1 for o in panel["observations"] if o["voted"]),
        },
        "identity": {
            "byCode": dict(sorted(Counter(f"{f['severity']}|{f['code']}" for f in idf).items())),
            "defects": [f for f in idf if f["severity"] == DEFECT],
        },
        "normalization": norm,
        "disagreement": att,
        "segments": seg,
        "stale": stale_findings(voting_status or {}, content_clocks or {}, sources),
        "coverage": {k: v for k, v in cov.items() if k != "idpRank"},
        "deepTail": tail,
        "exclusions": exc,
        "lineage": {
            "unregisteredSources": [s for s in sources if s not in providers],
            "votingProviders": sorted({providers.get(s, "UNREGISTERED") for s in voting_sources}),
            "relations": lineage_relations_between(lin, sources),
        },
    }
    result["digest"] = digest(result)
    return result


# ── injections (evaluator-validity E-gates) ────────────────────────────


def _clone(panel):
    return json.loads(json.dumps(panel))


def _row_index(panel):
    return {r["name"]: r for r in panel["rows"]}


def inject_vendor_family(panel, n: int, seed: int) -> tuple[dict, list[tuple[str, str]]]:
    p = _clone(panel)
    rows = _row_index(p)
    rng = random.Random(seed)
    pool = [
        o
        for o in p["observations"]
        if o["vendorFamily"] and o["vendorFamily"] == rows[o["row"]]["family"]
    ]
    picked = rng.sample(pool, min(n, len(pool)))
    labels = []
    for o in picked:
        row = rows[o["row"]]
        wrong = next(
            f for f in IDP_FAMILIES if f != row["family"] and f not in row["eligibleFamilies"]
        )
        o["vendorFamily"], o["vendorPosition"] = wrong, wrong
        labels.append((o["row"], o["source"]))
    return p, labels


def inject_sleeper_id(panel, n: int, seed: int) -> tuple[dict, list[str]]:
    p = _clone(panel)
    rng = random.Random(seed)
    pool = [r for r in p["rows"] if r["playerId"] and r["sleeperName"]]
    picked = rng.sample(pool, min(n, len(pool)))
    others = [r["name"] for r in p["rows"]]
    labels = []
    for r in picked:
        r["sleeperName"] = next(
            x for x in rng.sample(others, len(others)) if _name_key(x) != r["key"]
        )
        labels.append(r["name"])
    return p, labels


def inject_shared_entry(panel, n: int, seed: int) -> tuple[dict, list[tuple[str, str]]]:
    p = _clone(panel)
    rng = random.Random(seed)
    by_src = defaultdict(list)
    for o in p["observations"]:
        by_src[o["source"]].append(o)
    labels = []
    srcs = sorted(s for s, v in by_src.items() if len(v) >= 2)
    for _ in range(n):
        src = rng.choice(srcs)
        a, b = rng.sample(by_src[src], 2)
        b["matchedName"] = a["matchedName"]
        labels.append((b["row"], src))
    return p, labels


def inject_rank_inversion(panel, n: int, seed: int) -> tuple[dict, list[tuple[str, str, str]]]:
    p = _clone(panel)
    rng = random.Random(seed)
    by_src = defaultdict(list)
    for o in p["observations"]:
        if o["rawRank"] is not None and o["effectiveRank"] is not None:
            by_src[o["source"]].append(o)
    labels = []
    srcs = sorted(s for s, v in by_src.items() if len(v) >= 10)
    for _ in range(n):
        src = rng.choice(srcs)
        obs = sorted(by_src[src], key=lambda o: (o["rawRank"], o["effectiveRank"], o["row"]))
        i = rng.randrange(0, len(obs) - 5)
        a = obs[i]
        b = next(
            (
                x
                for x in obs[i + 1 :]
                if x["rawRank"] > a["rawRank"] and x["effectiveRank"] > a["effectiveRank"]
            ),
            None,
        )
        if b is None:
            continue
        a["effectiveRank"], b["effectiveRank"] = b["effectiveRank"], a["effectiveRank"]
        labels.append((src, a["row"], b["row"]))
    return p, labels


def inject_family_restart(panel, source: str, family: str) -> dict:
    """Replace one family's ranks on one source with a within-family 1..n list:
    a per-position board mixed into a combined one (the PR #1997 defect class)."""
    p = _clone(panel)
    fam = {r["name"]: r["family"] for r in p["rows"]}
    obs = sorted(
        (
            o
            for o in p["observations"]
            if o["source"] == source and fam.get(o["row"]) == family and o["rawRank"] is not None
        ),
        key=lambda o: (o["rawRank"], o["row"]),
    )
    for i, o in enumerate(obs):
        o["rawRank"] = float(i + 1)
        o["vendorValue"] = None
    return p


def _evaluable_votes(panel) -> list[dict]:
    votes = provider_votes(panel)
    ok_rows = {r for r, pv in votes.items() if len(pv) >= THRESHOLDS["minOtherProviders"] + 1}
    return [o for o in panel["observations"] if o["voted"] and o["row"] in ok_rows]


def inject_row_corruption(
    panel, n: int, seed: int, factor: float
) -> tuple[dict, list[tuple[str, str]]]:
    """Multiply single votes by ``factor`` (or its inverse) on rows with enough providers.

    Only a provider with exactly one voting source on the row is corrupted, so
    the corrupted number IS that provider's vote."""
    p = _clone(panel)
    rng = random.Random(seed)
    per = Counter((o["row"], o["provider"]) for o in p["observations"] if o["voted"])
    pool = [o for o in _evaluable_votes(p) if per[(o["row"], o["provider"])] == 1]
    rng.shuffle(pool)
    picked, seen = [], set()
    for o in pool:  # at most ONE corrupted vote per row: a single gross error
        if o["row"] not in seen:
            picked.append(o)
            seen.add(o["row"])
        if len(picked) >= n:
            break
    labels = []
    for i, o in enumerate(picked):
        o["value"] = o["value"] * (factor if i % 2 == 0 else 1.0 / factor)
        labels.append((o["row"], o["provider"]))
    return p, labels


def inject_segment_scale(panel, provider: str, family: str, factor: float) -> dict:
    p = _clone(panel)
    fam = {r["name"]: r["family"] for r in p["rows"]}
    for o in p["observations"]:
        if o["voted"] and o["provider"] == provider and fam.get(o["row"]) == family:
            o["value"] *= factor
    return p


def inject_swaps(
    panel, n: int, seed: int, min_ratio: float = 4.0
) -> tuple[dict, list[tuple[str, str, str]]]:
    """Swap one provider's votes between two rows of one family (a wrong-player join)."""
    p = _clone(panel)
    rng = random.Random(seed)
    fam = {r["name"]: r["family"] for r in p["rows"]}
    per = Counter((o["row"], o["provider"]) for o in p["observations"] if o["voted"])
    pool = defaultdict(list)
    for o in _evaluable_votes(p):
        if per[(o["row"], o["provider"])] == 1:
            pool[(o["provider"], fam.get(o["row"]))].append(o)
    keys = sorted(k for k, v in pool.items() if len(v) >= 2)
    labels = []
    used: set[str] = set()
    tries = 0
    while keys and len(labels) < n and tries < n * 200:
        tries += 1
        k = rng.choice(keys)
        a, b = rng.sample(pool[k], 2)
        if a["row"] in used or b["row"] in used:  # one injected error per row
            continue
        hi, lo = max(a["value"], b["value"]), min(a["value"], b["value"])
        if lo <= 0 or hi / lo < min_ratio:
            continue
        a["value"], b["value"] = b["value"], a["value"]
        used.update({a["row"], b["row"]})
        labels.append((a["row"], b["row"], k[0]))
    return p, labels


def run_e_gates(panel, *, seed: int, voting_status=None, content_clocks=None) -> dict[str, Any]:
    """The preregistered evaluator-validity gates over one (clean) panel."""
    import time  # noqa: PLC0415

    t = THRESHOLDS
    gates: dict[str, Any] = {}

    t0 = time.perf_counter()
    a = evaluate_panel(panel, voting_status=voting_status, content_clocks=content_clocks)
    runtime = time.perf_counter() - t0
    b = evaluate_panel(panel, voting_status=voting_status, content_clocks=content_clocks)
    gates["E1_determinism"] = {"pass": a["digest"] == b["digest"], "digest": a["digest"]}

    inj, lab = inject_vendor_family(panel, 30, seed + 1)
    hits = {
        (f["row"], f["source"])
        for f in identity_findings(inj)
        if f["code"] == "vendor_family_mismatch"
    }
    rec = sum(1 for x in lab if tuple(x) in hits)
    gates["E2_vendor_family"] = {
        "injected": len(lab),
        "detected": rec,
        "pass": bool(lab) and rec == len(lab),
    }

    inj, lab = inject_sleeper_id(panel, 20, seed + 2)
    hits = {f["row"] for f in identity_findings(inj) if f["code"] == "sleeper_name_mismatch"}
    rec = sum(1 for x in lab if x in hits)
    gates["E3_sleeper_id"] = {
        "injected": len(lab),
        "detected": rec,
        "pass": bool(lab) and rec == len(lab),
    }

    inj, lab = inject_shared_entry(panel, 20, seed + 3)
    hits = {
        (f["row"], f["source"])
        for f in identity_findings(inj)
        if f["code"] == "shared_vendor_entry"
    }
    rec = sum(1 for x in lab if tuple(x) in hits)
    gates["E4_shared_entry"] = {
        "injected": len(lab),
        "detected": rec,
        "pass": bool(lab) and rec == len(lab),
    }

    seg_res = []
    clean_seg = {
        (s["provider"], s["family"]): s for s in segment_shifts(panel, disagreement(panel))
    }
    for (prov, fam), s in sorted(clean_seg.items()):
        if not s["evaluable"] or s["shift"]:
            continue
        for factor in (5.0, 0.2):
            inj = inject_segment_scale(panel, prov, fam, factor)
            got = {(x["provider"], x["family"]): x for x in segment_shifts(inj, disagreement(inj))}
            seg_res.append(
                {
                    "provider": prov,
                    "family": fam,
                    "factor": factor,
                    "detected": got[(prov, fam)]["shift"],
                }
            )
    det = sum(1 for x in seg_res if x["detected"])
    gates["E5_segment_scale"] = {
        "injected": len(seg_res),
        "detected": det,
        "pass": bool(seg_res) and det == len(seg_res),
        "cleanShiftedSegments": [k for k, s in sorted(clean_seg.items()) if s["shift"]],
    }

    inj, lab = inject_row_corruption(panel, 200, seed + 5, 8.0)
    ext = {(d["row"], d["provider"]) for d in disagreement(inj) if d["class"] == "extreme"}
    rec = sum(1 for x in lab if tuple(x) in ext) / len(lab) if lab else 0.0
    clean = disagreement(panel)
    ev = [d for d in clean if d["u"] is not None]
    clean_rate = sum(1 for d in ev if d["class"] == "extreme") / len(ev) if ev else 0.0
    gates["E6_row_corruption"] = {
        "injected": len(lab),
        "recall": round(rec, 4),
        "cleanExtremeRate": round(clean_rate, 4),
        "pass": bool(lab)
        and rec >= t["e6RowCorruptionRecallMin"]
        and clean_rate <= t["e6CleanExtremeRateMax"],
    }

    inj, lab = inject_swaps(panel, 100, seed + 7)
    ext = {(d["row"], d["provider"]) for d in disagreement(inj) if d["class"] == "extreme"}
    rec = (
        sum(1 for a_, b_, pv in lab if (a_, pv) in ext or (b_, pv) in ext) / len(lab)
        if lab
        else 0.0
    )
    gates["E7_wrong_player_swap"] = {
        "injected": len(lab),
        "recall": round(rec, 4),
        "pass": bool(lab) and rec >= t["e7SwapRecallMin"],
    }

    detected, lab_all = 0, []
    for k in range(20):  # one inversion per panel, so injections cannot mask each other
        inj, lab = inject_rank_inversion(panel, 1, seed + 800 + k)
        if not lab:
            continue
        lab_all.extend(lab)
        src, a_, b_ = lab[0]
        flagged = {
            r
            for d in normalization_findings(inj)["defects"]
            if d["code"] == "translation_inversion" and d["source"] == src
            for r in d["rows"]
        }
        detected += int(a_ in flagged or b_ in flagged)
    gates["E8_rank_inversion"] = {
        "injected": len(lab_all),
        "detected": detected,
        "pass": bool(lab_all) and detected == len(lab_all),
    }

    basis_res = []
    base_norm = normalization_findings(panel)["perSource"]
    for src, info in sorted(base_norm.items()):
        if not info["rankBasis"].get("evaluable") or info["rankBasis"].get("mixed"):
            continue
        slopes = info["rankBasis"]["slopesAtK"]
        # restart the family that sits deepest on the combined list
        fam = max(slopes, key=lambda f: (slopes[f], f))
        inj = inject_family_restart(panel, src, fam)
        got = normalization_findings(inj)["perSource"][src]["rankBasis"]
        basis_res.append({"source": src, "family": fam, "detected": bool(got.get("mixed"))})
    det = sum(1 for x in basis_res if x["detected"])
    gates["E11_rank_basis_restart"] = {
        "injected": len(basis_res),
        "detected": det,
        "cases": basis_res,
        "pass": bool(basis_res) and det == len(basis_res),
    }

    gates["E9_stale_stamp"] = _stale_gate()
    gates["E10_runtime"] = {
        "seconds": round(runtime, 3),
        "pass": runtime <= t["e10RuntimeSecondsMax"],
    }
    return gates


def _stale_gate() -> dict[str, Any]:
    vs = {
        "sources": [
            {"key": "a", "lastGenuineUpdate": "2026-01-10T12:00:00Z"},
            {"key": "b", "lastGenuineUpdate": "2026-01-01T00:00:00Z"},
            {"key": "c", "lastGenuineUpdate": "2026-01-10T00:00:00Z"},
        ]
    }
    clocks = {
        "a": {"lastByteChange": "2026-01-10T00:00:00Z", "lastBroadChange": "2026-01-10T00:00:00Z"},
        "b": {"lastByteChange": "2026-01-12T00:00:00Z", "lastBroadChange": "2026-01-11T00:00:00Z"},
        "c": {"lastByteChange": "2026-01-10T03:00:00Z", "lastBroadChange": "2026-01-10T03:00:00Z"},
    }
    got = {r["source"]: r["verdict"] for r in stale_findings(vs, clocks, ["a", "b", "c"])}
    want = {"a": "stamp_after_content", "b": "stamp_older_than_broad_change", "c": "consistent"}
    return {"verdicts": got, "pass": got == want}
