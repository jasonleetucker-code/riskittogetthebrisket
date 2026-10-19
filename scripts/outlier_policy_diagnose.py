#!/usr/bin/env python3
"""Diagnose every outlier-filter rejection on one board (owner directive 2026-10-19 §6).

Read-only. Builds the board through the canonical pipeline (``value_replay.build``)
with the DLF IDP vote hold OFF -- the state the directive restores -- and, for
every vote the incumbent filter (``data_contract._hampel_filter_per_player``)
rejects, records the evidence needed to call it a DATA ERROR or a LEGITIMATE
DISAGREEMENT:

* the incumbent's own statistics (median, MAD, threshold) and whether the
  threshold collapsed to the 1,000-point floor, plus the size of the
  identical-vote cluster that collapsed it;
* identity: the matched source name and its ambiguity, the source's own position
  label and (where the board carries one) its Sleeper id, against the row;
* normalization: the vote's pricing path and translation stamps, and the
  source's whole-board scale statistics on that asset class;
* staleness: the source's freshness factor and age;
* opinion: the vote's distance from the other families in the policy's
  smoothed implied-rank coordinate, the source's own systematic bias at that
  position on this board, and whether another family corroborates it;
* optionally, persistence: the same (player, source) on earlier boards of a
  replay directory (``--history``).

It also applies the preregistered challenger (``src/api/outlier_policy.py``) to
the same stamped votes, so the two filters' decisions are listed side by side.

Usage::

    python scripts/outlier_policy_diagnose.py --out <json> [--payload <raw json>]
        [--hold on|off] [--history <dir of replay records>]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.api import outlier_policy as op  # noqa: E402

CLASS_IDENTITY = "data_error_identity"
CLASS_NORMALIZATION = "data_error_normalization"
CLASS_STALE = "data_error_stale_or_corrupt"
CLASS_DISAGREEMENT = "legitimate_disagreement"

_POS_COLUMNS = ("position", "pos", "fantasy position")
_NAME_COLUMNS = ("name", "player")
_SLEEPER_COLUMNS = ("sleeperid", "sleeper_id")
_IDP_FAMILY = {
    "DL": "DL",
    "DE": "DL",
    "DT": "DL",
    "EDGE": "DL",
    "NT": "DL",
    "LB": "LB",
    "ILB": "LB",
    "OLB": "LB",
    "MLB": "LB",
    "DB": "DB",
    "CB": "DB",
    "S": "DB",
    "FS": "DB",
    "SS": "DB",
}
_OFFENSE = {"QB", "RB", "WR", "TE", "FB", "HB"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pos_group(pos: Any) -> str | None:
    p = str(pos or "").strip().upper()
    if not p:
        return None
    if p in _OFFENSE:
        return "RB" if p in ("FB", "HB") else p
    return _IDP_FAMILY.get(p)


def source_csv_index(csv_root: Path | None = None) -> dict[str, dict[str, dict[str, str]]]:
    """``{source: {csv name: {"position", "sleeperId"}}}`` for boards that carry them."""
    from src.api import data_contract as dc  # noqa: PLC0415

    root = csv_root or REPO_ROOT
    out: dict[str, dict[str, dict[str, str]]] = {}
    for key, spec in dc._SOURCE_CSV_PATHS.items():
        rel = spec.get("path") if isinstance(spec, dict) else spec
        if not isinstance(rel, str):
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            with path.open(encoding="utf-8", errors="replace", newline="") as fh:
                reader = csv.DictReader(fh)
                cols = {c.strip().lower(): c for c in (reader.fieldnames or [])}
                name_col = next((cols[c] for c in _NAME_COLUMNS if c in cols), None)
                pos_col = next((cols[c] for c in _POS_COLUMNS if c in cols), None)
                sid_col = next((cols[c] for c in _SLEEPER_COLUMNS if c in cols), None)
                if name_col is None or (pos_col is None and sid_col is None):
                    continue
                entries: dict[str, dict[str, str]] = {}
                for row in reader:
                    name = str(row.get(name_col) or "").strip()
                    if not name:
                        continue
                    entries.setdefault(
                        name,
                        {
                            "position": str(row.get(pos_col) or "").strip() if pos_col else "",
                            "sleeperId": str(row.get(sid_col) or "").strip() if sid_col else "",
                        },
                    )
                out[key] = entries
        except OSError:
            continue
    return out


def row_curve(row: dict) -> tuple[float, float]:
    from src.canonical import player_valuation as pv  # noqa: PLC0415

    if row.get("assetClass") == "idp":
        return (pv.IDP_HILL_PERCENTILE_C, pv.IDP_HILL_PERCENTILE_S)
    return (pv.HILL_PERCENTILE_C, pv.HILL_PERCENTILE_S)


def voting(row: dict) -> dict[str, float]:
    out = {}
    for s, m in (row.get("sourceRankMeta") or {}).items():
        if not isinstance(m, dict) or m.get("excludedReason"):
            continue
        v = m.get("valueContribution")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out[str(s)] = float(v)
    return out


def incumbent_stats(values: list[float]) -> dict[str, float]:
    from src.api import data_contract as dc  # noqa: PLC0415

    med = statistics.median(values)
    mad = statistics.median(abs(v - med) for v in values)
    thr = max(dc._HAMPEL_K * mad, dc._HAMPEL_MIN_THRESHOLD)
    return {
        "median": round(med, 1),
        "mad": round(mad, 1),
        "threshold": round(thr, 1),
        "floorBound": dc._HAMPEL_K * mad <= dc._HAMPEL_MIN_THRESHOLD,
        "clusterAtMedian": sum(1 for v in values if abs(v - med) <= 1.0),
    }


def position_bias(rows: list[dict], family_of) -> dict[tuple[str, str], dict[str, float]]:
    """Median signed policy-coordinate deviation of each source at each position."""
    devs: dict[tuple[str, str], list[float]] = defaultdict(list)
    for row in rows:
        if row.get("assetClass") == "pick":
            continue
        values = voting(row)
        curve = row_curve(row)
        coords = {k: op.rank_coordinate(v, curve) for k, v in values.items()}
        coords = {k: u for k, u in coords.items() if u is not None}
        for k in coords:
            ref = op.leave_family_out(k, coords, values, family_of)
            if ref is not None:
                devs[(k, str(row.get("position") or ""))].append(coords[k] - ref.coordinate)
    return {
        key: {"rows": len(d), "median": round(statistics.median(d), 4)}
        for key, d in devs.items()
        if d
    }


def load_history(path: Path | None) -> list[dict]:
    """Replay records (``scripts/outlier_policy_replay.py``), oldest first."""
    if path is None or not path.is_dir():
        return []
    recs = []
    for f in sorted(path.glob("*.json.gz")):
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            rec = json.load(fh)
        if (rec.get("board") or {}).get("complete"):
            recs.append(rec)
    recs.sort(key=lambda r: (r.get("board") or {}).get("scrapeTimestamp") or "")
    return recs


def persistence(history: list[dict], name: str, source: str) -> dict[str, Any] | None:
    """The (player, source) policy distance on every earlier replayed board.

    Read from the replay records' incumbent votes (DLF IDP hold off). A view the
    source has held on most earlier boards is a held opinion; one that appeared
    only recently, while it sat with the field before, is a candidate transient
    error.
    """
    from src.api import data_contract as dc  # noqa: PLC0415

    series = []
    for rec in history:
        row = (rec.get("rows") or {}).get(name)
        if not row or source not in (row.get("votes") or {}):
            continue
        votes = {k: float(v) for k, v in row["votes"].items()}
        curve = op.scope_curve(row.get("ac"))
        coords = {k: op.rank_coordinate(v, curve) for k, v in votes.items()}
        coords = {k: u for k, u in coords.items() if u is not None}
        if source not in coords:
            continue
        ref = op.leave_family_out(source, coords, votes, dc.correlation_group_for)
        if ref is None:
            continue
        series.append(
            ((rec.get("board") or {}).get("scrapeTimestamp"), coords[source] - ref.coordinate)
        )
    if not series:
        return None
    last = series[-1][1]
    ds = [d for _t, d in series]
    recent = ds[-7:]
    return {
        "boards": len(series),
        "first": series[0][0],
        "last": series[-1][0],
        "medianDistance": round(statistics.median(ds), 4),
        "sameSideShare": round(sum(1 for d in ds if d * last > 0) / len(ds), 4),
        "beyondHalfOfLatestShare": round(
            sum(1 for d in ds if d * last > 0 and abs(d) >= abs(last) / 2) / len(ds), 4
        ),
        "recentMedian": round(statistics.median(recent), 4),
    }


def classify(ev: dict[str, Any]) -> tuple[str, list[str]]:
    """Evidence -> class; the reasons list says which evidence decided it."""
    why: list[str] = []
    ident = ev["identity"]
    if ident.get("ambiguous") or (ident.get("candidates") or 1) > 1:
        why.append("identity_ambiguous_match")
    if ident.get("sleeperIdMismatch"):
        why.append("identity_sleeper_id_mismatch")
    if ident.get("positionMismatch") == "cross_class":
        why.append("identity_position_cross_class")
    if why:
        return CLASS_IDENTITY, why
    norm = ev["normalization"]
    if norm.get("valueDirectFallbackReason"):
        why.append(f"normalization_fallback:{norm['valueDirectFallbackReason']}")
    if norm.get("idpBackboneFallback"):
        why.append("normalization_idp_backbone_fallback")
    if norm.get("boardScreenFlagged"):
        why.append("normalization_board_scale_mismatch")
    if why:
        return CLASS_NORMALIZATION, why
    fresh = ev["freshness"]
    if fresh.get("weight") is not None and fresh["weight"] <= 0:
        why.append("stale_zero_weight")
    pers = ev.get("persistence")
    if why:
        return CLASS_STALE, why
    op_ = ev["opinion"]
    why.append("identity_verified_unambiguous")
    why.append("standard_normalization_path")
    if op_.get("corroborated"):
        why.append("corroborated_by_another_family")
    if (
        op_.get("residualAfterPositionBias") is not None
        and abs(op_["residualAfterPositionBias"]) <= op.CORROBORATION_DISTANCE
    ):
        why.append("consistent_with_source_position_methodology")
    else:
        why.append("player_specific_view")
    # History before this board cannot prove an error (a source may revise its
    # view on news); it says whether the view is long-held or recent.
    if pers and pers["boards"] >= 7:
        why.append(
            "held_view_over_replayed_history"
            if pers["beyondHalfOfLatestShare"] >= 0.25
            else "recent_view_in_replayed_history"
        )
    return CLASS_DISAGREEMENT, why


def diagnose(contract: dict, csv_index: dict, history: list[dict]) -> dict[str, Any]:
    from src.api import data_contract as dc  # noqa: PLC0415

    family_of = dc.correlation_group_for
    rows = [r for r in contract.get("playersArray") or [] if isinstance(r, dict)]
    screen = op.board_screen(
        (
            op.BoardRow(str(r.get("assetClass")), row_curve(r), voting(r))
            for r in rows
            if r.get("assetClass") != "pick"
        ),
        family_of,
    )
    bias = position_bias(rows, family_of)
    drops: list[dict[str, Any]] = []
    policy_drops: list[dict[str, Any]] = []
    census = Counter()
    for row in rows:
        if row.get("assetClass") == "pick":
            continue
        values = voting(row)
        ac = str(row.get("assetClass"))
        if len(values) >= dc._HAMPEL_MIN_N:
            census[f"incumbentFilterRows:{ac}"] += 1
        curve = row_curve(row)
        flagged = set((screen["flagged"] or {}).get(ac, []))
        meta = row.get("sourceRankMeta") or {}
        weights = {s: float((meta.get(s) or {}).get("appliedWeight") or 0.0) for s in values}
        verdict = op.assess_row(
            sorted(values.items()),
            curve=curve,
            family_of=family_of,
            weights=weights,
            board_excluded=flagged,
        )
        if len({family_of(k) for k in values}) >= 1 + op.MIN_OTHER_FAMILIES:
            census[f"policyAssessableRows:{ac}"] += 1
        for k in verdict.dropped:
            policy_drops.append(
                {
                    "row": row.get("displayName"),
                    "assetClass": ac,
                    "position": row.get("position"),
                    "source": k,
                    "value": values[k],
                    "reason": verdict.reasons.get(k),
                    **(verdict.details.get(k) or {}),
                    "incumbentDrops": k in (row.get("droppedSources") or []),
                }
            )
        dropped = list(row.get("droppedSources") or [])
        if not dropped:
            continue
        stats = incumbent_stats(list(values.values()))
        coords = {k: op.rank_coordinate(v, curve) for k, v in values.items()}
        coords = {k: u for k, u in coords.items() if u is not None}
        audit = ((row.get("sourceAudit") or {}).get("matchedDetails")) or {}
        for k in dropped:
            m = meta.get(k) or {}
            ref = op.leave_family_out(k, coords, values, family_of) if k in coords else None
            md = audit.get(k) or {}
            matched = str(md.get("matchedName") or "")
            src_entry = (csv_index.get(k) or {}).get(matched) or {}
            src_pos = pos_group(src_entry.get("position"))
            row_pos = pos_group(row.get("position"))
            if src_pos and row_pos and src_pos != row_pos:
                cross = (src_pos in _OFFENSE) != (row_pos in _OFFENSE)
                pos_mismatch = "cross_class" if cross else "within_class"
            else:
                pos_mismatch = None
            sid = src_entry.get("sleeperId") or ""
            pb = bias.get((k, str(row.get("position") or ""))) or {}
            dist = (coords[k] - ref.coordinate) if ref else None
            ev = {
                "row": row.get("displayName"),
                "assetClass": ac,
                "position": row.get("position"),
                "canonicalRank": row.get("canonicalConsensusRank"),
                "source": k,
                "family": family_of(k),
                "value": values.get(k),
                "votes": {s: int(v) for s, v in sorted(values.items())},
                "families": len({family_of(s) for s in values}),
                "incumbent": {**stats, "deviation": round(abs(values[k] - stats["median"]), 1)},
                "identity": {
                    "rowIdentityMethod": row.get("identityMethod"),
                    "matchedName": matched or None,
                    "nameMatchesCanonical": matched.strip().lower()
                    == str(row.get("canonicalName") or "").strip().lower(),
                    "ambiguous": bool(md.get("ambiguous")),
                    "candidates": len(md.get("candidates") or []) or None,
                    "via": md.get("via"),
                    "sourcePosition": src_entry.get("position") or None,
                    "positionMismatch": pos_mismatch,
                    "sleeperIdMismatch": bool(sid)
                    and bool(row.get("playerId"))
                    and sid != str(row.get("playerId")),
                },
                "normalization": {
                    "path": m.get("valueContributionPath"),
                    "method": m.get("method"),
                    "pool": m.get("rankCoordinatePool"),
                    "rawRank": m.get("rawRank"),
                    "effectiveRank": m.get("effectiveRank"),
                    "sharedMarketTranslated": m.get("sharedMarketTranslated"),
                    "valueDirectFallbackReason": m.get("valueDirectFallbackReason"),
                    "idpBackboneFallback": bool(row.get("idpBackboneFallback")),
                    "tepMultiplier": m.get("tepMultiplier"),
                    "boardScreen": screen["stats"].get(f"{k}|{ac}"),
                    "boardScreenFlagged": k in flagged,
                },
                "freshness": {
                    "weight": m.get("appliedWeight"),
                    "factor": m.get("dynamicWeightFactor", m.get("freshness")),
                    "ageHours": m.get("freshnessAgeHours"),
                },
                "opinion": {
                    "distance": round(dist, 4) if dist is not None else None,
                    "rankFactor": round(math.exp(abs(dist)), 2) if dist is not None else None,
                    "referenceValue": round(ref.value, 1) if ref else None,
                    "nearestOtherFamily": round(ref.nearest_family_distance, 4) if ref else None,
                    "corroborated": bool(ref)
                    and ref.nearest_family_distance <= op.CORROBORATION_DISTANCE,
                    "sourcePositionBias": pb.get("median"),
                    "residualAfterPositionBias": (
                        round(dist - pb["median"], 4)
                        if dist is not None and pb.get("median") is not None
                        else None
                    ),
                },
                "persistence": persistence(history, str(row.get("displayName")), k),
                "policyDrops": k in verdict.dropped,
            }
            cls, why = classify(ev)
            ev["class"] = cls
            ev["classReasons"] = why
            drops.append(ev)
            census[f"incumbentDrops:{ac}"] += 1
            census[f"class:{cls}"] += 1
            census[f"class:{cls}:{ac}"] += 1
            census[f"floorBound:{stats['floorBound']}"] += 1
    drops.sort(key=lambda d: (d["assetClass"], d["row"], d["source"]))
    return {
        "census": dict(sorted(census.items())),
        "incumbentDropsBySource": dict(
            Counter(f"{d['assetClass']}|{d['source']}" for d in drops).most_common()
        ),
        "boardScreen": screen,
        "drops": drops,
        "policyDrops": policy_drops,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--payload", type=Path, default=None)
    ap.add_argument("--hold", choices=("on", "off"), default="off")
    ap.add_argument("--history", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    from src.api import value_replay as vr  # noqa: PLC0415

    payload = args.payload
    if payload is None:
        latest = sorted((REPO_ROOT / "exports" / "latest").glob("dynasty_data_*.json"))
        if not latest:
            print("no payload under exports/latest", file=sys.stderr)
            return 1
        payload = latest[-1]
    data = payload.read_bytes()
    raw = json.loads(data)
    flags = [("dlf_offense_only_vote", args.hold == "on")]
    contract = vr.build(raw, {"flags": flags})
    result = diagnose(contract, source_csv_index(), load_history(args.history))
    result["pins"] = {
        "payload": str(payload.relative_to(REPO_ROOT))
        if payload.is_relative_to(REPO_ROOT)
        else str(payload),
        "payloadSha256": _sha(data),
        "scrapeTimestamp": raw.get("scrapeTimestamp"),
        "codeSha": (vr._git("rev-parse", "HEAD") or "").strip() or None,
        "workingTreeDirty": vr._dirty(),
        "flags": dict(flags),
        "policy": op.constants(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result["census"], indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
