#!/usr/bin/env python3
"""IDP source rehabilitation evaluation (owner master package 2026-10-17).

Read-only measurement instrument for the PENDING rows of the owner's IDP
rehabilitation package.  It answers, from committed data only:

1. **DLF IDP incremental evidence.**  The same pinned raw payload built twice
   through the canonical pipeline (``src/api/value_replay.build``): once with
   the owner's DLF offense-only vote hold in force (production) and once with
   it off (``dlf_offense_only_vote`` = False, the documented rollback flag).
   Reports coverage, Hampel rejections, value / rank movement by IDP family,
   families gained, confidence changes and top-N IDP membership churn.
2. **Source independence.**  Every IDP-covering source's own published
   ordering (the captured CSV, parsed with the 2026-10-01 lineage sweep's
   loader so "ordering" means the same thing), restricted to the board's IDP
   rows: raw Spearman plus a LEAVE-PAIR-OUT residual correlation (consensus
   excludes both members), overall and within DL / LB / DB, plus the same
   Spearman on the effective ranks the pipeline actually prices.
3. **IDP normalization.**  For each source that reaches IDP rows: the signed
   log ratio of its priced contribution against the leave-one-out mean of the
   other voters on the same row, by family — a persistent family-level skew is
   a normalization (coordinate) effect, not an opinion.  Also the share of
   votes priced past the fixed 500-rank percentile reference (curve tail).

Evidence only.  Nothing here changes a vote, a weight, a hold or a value; the
counterfactual flag is set only inside one in-process build and restored.
No network is required for the measurement (the build may attempt its usual
Sleeper league-context fetch; it is recorded, never required).

Usage::

    python scripts/idp_rehab_eval.py \\
        --payload exports/latest/dynasty_data_2026-10-18.json \\
        --out docs/sources/evidence/IDP_REHAB_2026-10-18/idp_rehab_eval.json

Exit codes: 0 written; 2 input missing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Mapping

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from src.api import value_replay as vr  # noqa: E402

_SWEEP_SPEC = importlib.util.spec_from_file_location(
    "lineage_integrity_sweep", REPO / "scripts" / "audit" / "lineage_integrity_sweep.py"
)
sweep = importlib.util.module_from_spec(_SWEEP_SPEC)
assert _SWEEP_SPEC.loader is not None
sys.modules["lineage_integrity_sweep"] = sweep
_SWEEP_SPEC.loader.exec_module(sweep)

CSV_DIR = REPO / "CSVs" / "site_raw"
#: Every IDP-covering source with a committed capture.  ``idpShow`` is the
#: unregistered IDP-only cut (evidence, never a vote).  The Signals IDP boards
#: are private and box-local (``data/sources/signals/board/``) and are
#: reported as not provisioned when absent — never guessed.
IDP_SOURCES = (
    "idpTradeCalc",
    "draftSharksIdp",
    "fantasyProsIdp",
    "dlfIdp",
    "dlfRookieIdp",
    "idpShowCombined",
    "idpShow",
)
PRIVATE_IDP_SOURCES = ("signalsIdpDl", "signalsIdpLb", "signalsIdpDb")
SIGNALS_BOARD_DIR = REPO / "data" / "sources" / "signals" / "board"
FAMILIES = ("DL", "LB", "DB")
DLF_IDP_KEYS = ("dlfIdp", "dlfRookieIdp")
#: Board-level sources that vote or could vote on IDP rows (one board per
#: provider; see ``independence``).
VOTER_POOL = ("idpTradeCalc", "draftSharksIdp", "fantasyProsIdp", "dlfIdp", "idpShowCombined")
#: Lead-lag window for the IDP Trade Calculator vs the IDP-only IDP Show cut.
LEAD_LAG_SINCE = "2026-09-15T00:00:00+00:00"
#: Agreement band, identical to the confidence gate's (15% relative).
AGREEMENT_BAND = 0.15


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _q(xs: list[float], p: float) -> float | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, int(p * (len(s) - 1) + 0.5))]


def _r(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(x, nd)


def _family(row: Mapping[str, Any]) -> str | None:
    pos = str(row.get("position") or "").upper()
    return pos if pos in FAMILIES else None


def _idp_rows(contract: Mapping[str, Any]) -> dict[str, dict]:
    return {
        r["displayName"]: r
        for r in contract.get("playersArray") or []
        if r.get("assetClass") == "idp" and r.get("displayName")
    }


def _voters(row: Mapping[str, Any]) -> dict[str, float]:
    """Sources whose priced vote reached this row's blend."""
    out = {}
    for key, meta in (row.get("sourceRankMeta") or {}).items():
        if meta.get("contributedToBlend") is False or meta.get("excludedReason"):
            continue
        if key in (row.get("droppedSources") or []):
            continue
        v = meta.get("valueContribution")
        w = meta.get("appliedWeight", meta.get("dynamicWeightFactor"))
        if isinstance(v, (int, float)) and v > 0 and (w is None or w > 0):
            out[key] = float(v)
    return out


# ── 1. DLF IDP counterfactual ──────────────────────────────────────────


def dlf_counterfactual(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    b_rows, a_rows = _idp_rows(base), _idp_rows(alt)
    obs = rejected = 0
    rejected_rows: list[dict] = []
    for name, row in a_rows.items():
        meta = row.get("sourceRankMeta") or {}
        for key in DLF_IDP_KEYS:
            if key in meta:
                obs += 1
                if key in (row.get("droppedSources") or []):
                    rejected += 1
                    rejected_rows.append({"player": name, "source": key})
    rel: list[float] = []
    rel_by_fam: dict[str, list[float]] = defaultdict(list)
    rank_moves: list[int] = []
    moved = 0
    fam_gain = 0
    fam_gain_thin = 0  # rows with <= 2 voting families today gaining one
    conf_changes = 0
    conf_transitions: dict[str, int] = defaultdict(int)
    agree = disagree = 0
    signed: dict[str, list[float]] = defaultdict(list)
    largest: list[tuple] = []
    for name, brow in b_rows.items():
        arow = a_rows.get(name)
        if not arow:
            continue
        bv, av = brow.get("rankDerivedValue"), arow.get("rankDerivedValue")
        fam = _family(brow) or "?"
        if isinstance(bv, (int, float)) and isinstance(av, (int, float)) and bv > 0:
            d = av / bv - 1.0
            rel.append(abs(d))
            rel_by_fam[fam].append(abs(d))
            if av != bv:
                moved += 1
                largest.append((abs(d), name, fam, bv, av))
        br, ar = brow.get("canonicalConsensusRank"), arow.get("canonicalConsensusRank")
        if isinstance(br, int) and isinstance(ar, int):
            rank_moves.append(abs(ar - br))
        bi, ai = brow.get("independentSourceCount") or 0, arow.get("independentSourceCount") or 0
        if ai > bi:
            fam_gain += 1
            if bi <= 2:
                fam_gain_thin += 1
        bc, ac = brow.get("confidenceBucket"), arow.get("confidenceBucket")
        if bc != ac:
            conf_changes += 1
            conf_transitions[f"{bc}->{ac}"] += 1
        voters = _voters(arow)
        if isinstance(av, (int, float)) and av > 0:
            for key in DLF_IDP_KEYS:
                if key in voters:
                    ratio = voters[key] / av
                    if abs(ratio - 1) <= AGREEMENT_BAND:
                        agree += 1
                    else:
                        disagree += 1
                    others = [v for k, v in voters.items() if k not in DLF_IDP_KEYS]
                    if others:
                        signed[fam].append(math.log(voters[key] / statistics.fmean(others)))

    def top_overlap(n: int) -> int:
        # ``idpRank`` is the IDP Trade Calculator's own rank, not the board's;
        # the board's IDP order is its published value order.
        def top(rows: dict) -> set[str]:
            ranked = sorted(
                (r for r in rows.values() if isinstance(r.get("rankDerivedValue"), (int, float))),
                key=lambda r: (-r["rankDerivedValue"], r["displayName"]),
            )
            return {r["displayName"] for r in ranked[:n]}

        return len(top(b_rows) ^ top(a_rows)) // 2

    offense_moved = pick_moved = 0
    b_all = {r["displayName"]: r for r in base.get("playersArray") or [] if r.get("displayName")}
    for r in alt.get("playersArray") or []:
        b = b_all.get(r.get("displayName"))
        if not b or b.get("rankDerivedValue") == r.get("rankDerivedValue"):
            continue
        if r.get("assetClass") == "offense":
            offense_moved += 1
        elif r.get("assetClass") == "pick":
            pick_moved += 1
    ranked_idp = [r for r in b_rows.values() if isinstance(r.get("canonicalConsensusRank"), int)]
    covered = [
        r
        for r in ranked_idp
        if any(
            k in (a_rows.get(r["displayName"], {}).get("sourceRankMeta") or {})
            for k in DLF_IDP_KEYS
        )
    ]
    fam_hist_before: dict[int, int] = defaultdict(int)
    for r in ranked_idp:
        fam_hist_before[int(r.get("independentSourceCount") or 0)] += 1
    fam_hist_after: dict[int, int] = defaultdict(int)
    for r in ranked_idp:
        a = a_rows.get(r["displayName"]) or {}
        fam_hist_after[int(a.get("independentSourceCount") or 0)] += 1
    return {
        "dlfIdpObservationsOnIdpRows": obs,
        "dlfIdpObservationsRejectedByHampel": rejected,
        "rejected": rejected_rows,
        "rankedIdpRows": len(ranked_idp),
        "rankedIdpRowsCoveredByDlf": len(covered),
        "idpRowsCompared": len(rel),
        "idpRowsValueMoved": moved,
        "relativeMove": {
            "median": _r(_q(rel, 0.5)),
            "p90": _r(_q(rel, 0.9)),
            "max": _r(max(rel) if rel else None),
        },
        "relativeMoveP90ByFamily": {f: _r(_q(v, 0.9)) for f, v in sorted(rel_by_fam.items())},
        "consensusRankMove": {"median": _q(rank_moves, 0.5), "p90": _q(rank_moves, 0.9)},
        "idpRowsGainingIndependentFamily": fam_gain,
        "idpRowsWithAtMostTwoFamiliesGainingOne": fam_gain_thin,
        "rankedIdpFamilyCountHistogram": {
            "holdInForce": dict(sorted(fam_hist_before.items())),
            "holdOff": dict(sorted(fam_hist_after.items())),
        },
        "confidenceBucketChanges": conf_changes,
        "confidenceTransitions": dict(sorted(conf_transitions.items())),
        "dlfVotesWithin15pctOfPublished": agree,
        "dlfVotesOutside15pctOfPublished": disagree,
        "dlfSignedLogRatioVsOtherVotersByFamily": {
            f: {
                "n": len(v),
                "median": _r(_q(v, 0.5)),
                "mean": _r(statistics.fmean(v) if v else None),
            }
            for f, v in sorted(signed.items())
        },
        "topIdpMembershipSwaps": {n: top_overlap(n) for n in (24, 50, 100)},
        "offenseRowsMoved": offense_moved,
        "pickRowsMoved": pick_moved,
        "largestIdpMoves": [
            {"player": n, "family": f, "before": b, "after": a, "relative": _r(d)}
            for d, n, f, b, a in sorted(largest, reverse=True)[:12]
        ],
        "boardDiff": vr.board_diff(base, alt, top=10),
    }


def filter_census(contract: Mapping[str, Any]) -> dict[str, Any]:
    """How many IDP rows reach the per-player outlier filter (at least
    ``_HAMPEL_MIN_N`` weighted voting observations) and what it drops there."""
    min_n = vr.dc._HAMPEL_MIN_N
    reach = 0
    drops: dict[str, int] = defaultdict(int)
    n_hist: dict[int, int] = defaultdict(int)
    for row in _idp_rows(contract).values():
        voting = [
            k
            for k, m in (row.get("sourceRankMeta") or {}).items()
            if not m.get("excludedReason") and (m.get("appliedWeight") or 0) > 0
        ]
        voting += [k for k in row.get("droppedSources") or [] if k not in voting]
        n_hist[len(voting)] += 1
        if len(voting) >= min_n:
            reach += 1
        for k in row.get("droppedSources") or []:
            drops[k] += 1
    return {
        "hampelMinN": min_n,
        "idpRowsReachingFilter": reach,
        "idpRowsByWeightedVoterCount": dict(sorted(n_hist.items())),
        "idpDropsBySource": dict(sorted(drops.items(), key=lambda kv: -kv[1])),
    }


def decomposition(
    base: Mapping[str, Any], alt: Mapping[str, Any], alt_nofilter: Mapping[str, Any]
) -> dict:
    """Split the reversal's IDP movement into DLF's own vote (hold off, filter
    off on both sides of the comparison — the hold-in-force board drops no IDP
    observation, so its filter-off board is identical on IDP rows) and the
    outlier filter it re-activates (hold off, filter on vs filter off)."""

    def rel(a: Mapping[str, Any], b: Mapping[str, Any]) -> dict[str, Any]:
        ar, br = _idp_rows(a), _idp_rows(b)
        xs, moved = [], 0
        for name, row in ar.items():
            x, y = row.get("rankDerivedValue"), (br.get(name) or {}).get("rankDerivedValue")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)) and x > 0:
                xs.append(abs(y / x - 1.0))
                moved += x != y
        return {
            "rowsMoved": moved,
            "median": _r(_q(xs, 0.5)),
            "p90": _r(_q(xs, 0.9)),
            "max": _r(max(xs) if xs else None),
        }

    return {
        "dlfVoteOnly_holdOn_vs_holdOffFilterOff": rel(base, alt_nofilter),
        "filterReactivation_holdOffFilterOff_vs_holdOff": rel(alt_nofilter, alt),
        "total_holdOn_vs_holdOff": rel(base, alt),
    }


# ── 2. independence ────────────────────────────────────────────────────


def _csv_boards() -> dict[str, Any]:
    boards = {}
    for key in IDP_SOURCES:
        path = CSV_DIR / f"{key}.csv"
        b = sweep.load_board(key, path)
        if b is not None:
            boards[key] = b
    return boards


def independence(base: Mapping[str, Any], alt: Mapping[str, Any]) -> dict[str, Any]:
    idp = _idp_rows(base)
    ident_family: dict[str, str] = {}
    for name, row in idp.items():
        ident = sweep.canonical(name)
        fam = _family(row)
        if ident and fam:
            ident_family[ident] = fam
    boards = _csv_boards()
    keys = [k for k in IDP_SOURCES if k in boards]

    def percentiles_for(idents: set[str]) -> dict[str, dict[str, float]]:
        out = {}
        for key in keys:
            mine = [i for i in boards[key].entries if i in idents]
            if len(mine) >= sweep.MIN_PAIR_OVERLAP:
                out[key] = sweep.to_percentiles(sweep.ordering(boards[key], mine))
        return out

    def matrix(idents: set[str], label: str, pool: tuple[str, ...]) -> list[dict]:
        pct = percentiles_for(idents)
        rows = []
        members = [k for k in keys if k in pool]
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if a not in pct or b not in pct:
                    continue
                rho, n = sweep.spearman(pct[a], pct[b])
                res, n_res = sweep.leave_pair_out_residuals(pct, a, b, members)
                rows.append(
                    {
                        "universe": label,
                        "a": a,
                        "b": b,
                        "spearman": _r(rho),
                        "n": n,
                        "leavePairOutResidual": _r(res),
                        "nResidual": n_res,
                    }
                )
        return rows

    all_idp = set(ident_family)
    out_rows = matrix(all_idp, "IDP", tuple(keys))
    for fam in FAMILIES:
        out_rows += matrix({i for i, f in ident_family.items() if f == fam}, fam, tuple(keys))
    # Second consensus pool without the IDP-only IDP Show cut (order-identical
    # to the IDP Trade Calculator, so it would sit in every consensus as a
    # clone of one pair member) and without the rookie-only DLF board.
    voter_rows = matrix(all_idp, "IDP", VOTER_POOL)
    for fam in FAMILIES:
        voter_rows += matrix({i for i, f in ident_family.items() if f == fam}, fam, VOTER_POOL)

    # Pipeline coordinates: effective ranks the build prices (held / quarantined
    # sources included where the build stamps them; DLF from the hold-off build).
    eff: dict[str, dict[str, float]] = defaultdict(dict)
    for name, row in _idp_rows(alt).items():
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            er = meta.get("effectiveRank")
            if isinstance(er, (int, float)):
                eff[key][name] = float(er)
    eff_keys = sorted(k for k in eff if len(eff[k]) >= sweep.MIN_PAIR_OVERLAP)
    eff_rows = []
    for i, a in enumerate(eff_keys):
        for b in eff_keys[i + 1 :]:
            rho, n = sweep.spearman(eff[a], eff[b])
            if rho is not None:
                eff_rows.append({"a": a, "b": b, "spearman": _r(rho), "n": n})

    registry = {s["key"]: s for s in vr.dc._RANKING_SOURCES}
    families = {
        k: (str(registry[k].get("correlation_group") or k) if k in registry else None)
        for k in (*IDP_SOURCES, *PRIVATE_IDP_SOURCES)
    }
    return {
        "csvBoards": {
            k: {
                "rows": boards[k].rows,
                "identities": len(boards[k].entries),
                "onBoardIdpIdentities": sum(1 for i in boards[k].entries if i in all_idp),
                "duplicateIdentities": len(boards[k].duplicates),
                "csvSha256": _sha256(CSV_DIR / f"{k}.csv"),
            }
            for k in keys
        },
        "b10Family": families,
        "registered": {k: k in registry for k in (*IDP_SOURCES, *PRIVATE_IDP_SOURCES)},
        "signalsIdpBoards": (
            "provisioned"
            if SIGNALS_BOARD_DIR.is_dir() and any(SIGNALS_BOARD_DIR.glob("*.csv"))
            else "not_provisioned (private, box-local data/sources/signals/board/ absent here)"
        ),
        "csvOrderingDependence": out_rows,
        "csvOrderingDependenceVoterPool": {"pool": list(VOTER_POOL), "rows": voter_rows},
        "idpTradeCalcVsIdpShowLeadLag": idptc_idpshow_lead_lag(all_idp),
        "pipelineEffectiveRankSpearman": eff_rows,
    }


def idptc_idpshow_lead_lag(members: set[str]) -> dict[str, Any]:
    """Pairwise order discordance of every IDP Trade Calculator version in the
    window against each IDP-only IDP Show capture in it (and the capture
    current at the window start).  Our IDP Show captures lag the vendor when
    collection is down (2026-10-07 -> 10-17), so every capture is compared,
    not only the one current at the subject's time."""
    from datetime import datetime  # noqa: PLC0415

    since = datetime.fromisoformat(LEAD_LAG_SINCE)
    spath, tpath = sweep.csv_path("idpShow"), sweep.csv_path("idpTradeCalc")
    show_versions = list(reversed(sweep.git_versions(spath, since)))
    prior = sweep.git_versions(spath, None, since)[:1]
    captures = prior + show_versions
    show_orders = {}
    for sha, at in captures:
        b = sweep.board_at("idpShow", spath, sha)
        show_orders[sha] = (at, sweep.ordering(b, [i for i in b.entries if i in members]))
    rows = []
    for sha, at in reversed(sweep.git_versions(tpath, since)):
        b = sweep.board_at("idpTradeCalc", tpath, sha)
        o = sweep.ordering(b, [i for i in b.entries if i in members])
        cmp = {}
        for ssha, (sat, so) in show_orders.items():
            n, share = sweep.discordant_share(o, so)
            cmp[ssha] = {"idpShowCapturedAt": sat.isoformat(), "n": n, "discordantShare": share}
        rows.append({"idpTradeCalcVersion": sha, "at": at.isoformat(), "vsIdpShow": cmp})
    return {"since": LEAD_LAG_SINCE, "idpShowCaptures": len(captures), "versions": rows}


# ── 3. normalization ───────────────────────────────────────────────────


def normalization(alt: Mapping[str, Any]) -> dict[str, Any]:
    skew: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    tail: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    coord: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in _idp_rows(alt).values():
        fam = _family(row)
        voters = _voters(row)
        for key, meta in (row.get("sourceRankMeta") or {}).items():
            p = meta.get("percentile")
            if isinstance(p, (int, float)):
                tail[key][1] += 1
                if p > 1.0:
                    tail[key][0] += 1
            coord[key][str(meta.get("rankCoordinatePool"))] += 1
        if not fam:
            continue
        for key, v in voters.items():
            others = [x for k, x in voters.items() if k != key]
            if len(others) >= 2:
                skew[key][fam].append(math.log(v / statistics.fmean(others)))
    from src.canonical import player_valuation as pv  # noqa: PLC0415
    from src.canonical import rank_coordinates as rc  # noqa: PLC0415

    ref_n = vr.dc._PERCENTILE_REFERENCE_N
    nat: dict[str, list[float]] = defaultdict(list)
    for row in _idp_rows(alt).values():
        meta = (row.get("sourceRankMeta") or {}).get("idpTradeCalc") or {}
        er, v = meta.get("effectiveRank"), meta.get("valueContribution")
        if meta.get("valueContributionPath") != "value_direct":
            continue
        if not isinstance(er, (int, float)) or not isinstance(v, (int, float)) or v <= 0:
            continue
        c, sl = rc.curve_for_pool(str(meta.get("rankCoordinatePool") or "shared_market"))
        h = pv.percentile_to_value((float(er) - 1.0) / (ref_n - 1), midpoint=c, slope=sl)
        band = (
            "1-100" if er <= 100 else "101-250" if er <= 250 else "251-500" if er <= 500 else "501+"
        )
        lr = math.log(v / h)
        nat[f"band:{band}"].append(lr)
        nat[f"family:{_family(row) or '?'}"].append(lr)
    native_vs_hill = {
        k: {
            "n": len(v),
            "medianLogRatio": _r(_q(v, 0.5)),
            "p10": _r(_q(v, 0.1)),
            "p90": _r(_q(v, 0.9)),
        }
        for k, v in sorted(nat.items())
    }
    return {
        "idpTradeCalcNativeValueVsHillAtOwnEffectiveRank": native_vs_hill,
        "signedLogRatioVsLeaveOneOutMean": {
            key: {
                fam: {
                    "n": len(v),
                    "median": _r(_q(v, 0.5)),
                    "p10": _r(_q(v, 0.1)),
                    "p90": _r(_q(v, 0.9)),
                }
                for fam, v in sorted(by.items())
            }
            for key, by in sorted(skew.items())
        },
        "votesPastPercentileReference": {
            k: {"pastReference": v[0], "stamped": v[1]} for k, v in sorted(tail.items())
        },
        "rankCoordinatePool": {k: dict(v) for k, v in sorted(coord.items())},
    }


# ── 4. DLF Values publication stability ────────────────────────────────


def dlf_values_publication_history() -> dict[str, Any]:
    """Distinct content versions of the DLF Trade Analyzer Values capture.

    The 2026-09-25 gate left "capture stability" untested on one content
    version.  A re-stamp of unchanged content is not a release: versions are
    deduplicated on the parsed (name, value) set."""
    path = CSV_DIR / "dlfValuesSfTep.csv"
    versions = list(reversed(sweep.git_versions(path)))
    distinct: list[dict] = []
    prev_key = None
    prev_vals: dict[str, float] | None = None
    for sha, at in versions:
        board = sweep.board_at("dlfValuesSfTep", path, sha)
        vals = {i: e["value"] for i, e in board.entries.items() if e["value"] is not None}
        key = hashlib.sha256(json.dumps(sorted(vals.items())).encode()).hexdigest()
        if key == prev_key or not vals:
            continue
        rec: dict[str, Any] = {"commit": sha, "at": at.isoformat(), "rows": len(vals)}
        if prev_vals:
            common = set(vals) & set(prev_vals)
            rho, n = sweep.spearman(
                {i: -vals[i] for i in common}, {i: -prev_vals[i] for i in common}
            )
            changed = sum(1 for i in common if vals[i] != prev_vals[i])
            top = lambda d: set(sorted(d, key=lambda i: -d[i])[:24])  # noqa: E731
            rec.update(
                {
                    "spearmanVsPrevious": _r(rho),
                    "nCommon": n,
                    "valuesChangedShare": _r(changed / len(common)) if common else None,
                    "added": len(set(vals) - set(prev_vals)),
                    "removed": len(set(prev_vals) - set(vals)),
                    "top24OverlapVsPrevious": len(top(vals) & top(prev_vals)),
                }
            )
        distinct.append(rec)
        prev_key, prev_vals = key, vals
    return {"commitsTouchingCsv": len(versions), "distinctContentVersions": distinct}


def archive_manifest() -> dict[str, Any]:
    """Frozen dataset identity for a preregistration: every archived scrape,
    its zip and payload sha256, and its completeness under the contract's own
    source-health rule (``tests.archive_fixtures._degraded_critical_sources``)."""
    import zipfile  # noqa: PLC0415

    from tests.archive_fixtures import _degraded_critical_sources  # noqa: PLC0415

    boards = []
    for path in sorted((REPO / "exports" / "archive").glob("dynasty_export_*.zip")):
        with zipfile.ZipFile(path) as zf:
            names = sorted(
                n for n in zf.namelist() if n.startswith("dynasty_data_") and n.endswith(".json")
            )
            if not names:
                continue
            blob = zf.read(names[0])
        payload = json.loads(blob)
        degraded = _degraded_critical_sources(payload)
        boards.append(
            {
                "board": path.name,
                "zipSha256": _sha256(path),
                "payloadSha256": hashlib.sha256(blob).hexdigest(),
                "scrapeTimestamp": payload.get("scrapeTimestamp"),
                "complete": not degraded,
                "degraded": degraded,
            }
        )
    return {
        "schema": "archive-manifest/v1",
        "boards": boards,
        "count": len(boards),
        "complete": sum(1 for b in boards if b["complete"]),
    }


def signals_dependence(base: Mapping[str, Any]) -> dict[str, Any]:
    """Signals IDP pairwise dependence, ON THE PRODUCTION BOX (owner Decision 7).

    The Signals IDP boards are private and box-local, so this measurement can
    run only where ``data/sources/signals/board/`` exists.  Each family board
    (``signalsIdpDl`` / ``Lb`` / ``Db``) is compared WITHIN its own family's
    on-board identities against every voting-capable IDP board, with the same
    Spearman and leave-pair-out residual the public matrix uses (consensus
    pool: ``VOTER_POOL`` plus the Signals board).  The output is AGGREGATE ONLY
    (correlations and counts): no player name, rank or value leaves the box.
    Read-only; nothing here changes a vote, a hold or a threshold.
    """
    if not (SIGNALS_BOARD_DIR.is_dir() and any(SIGNALS_BOARD_DIR.glob("*.csv"))):
        return {"state": "not_provisioned", "boardDir": str(SIGNALS_BOARD_DIR)}
    ident_family: dict[str, str] = {}
    for name, row in _idp_rows(base).items():
        ident, fam = sweep.canonical(name), _family(row)
        if ident and fam:
            ident_family[ident] = fam
    boards = _csv_boards()
    family_of = {"signalsIdpDl": "DL", "signalsIdpLb": "LB", "signalsIdpDb": "DB"}
    out: dict[str, Any] = {"state": "provisioned", "families": {}}
    for key, fam in family_of.items():
        board = sweep.load_board(key, SIGNALS_BOARD_DIR / f"{key}.csv")
        if board is None:
            out["families"][fam] = {"source": key, "state": "board_missing"}
            continue
        idents = {i for i, f in ident_family.items() if f == fam}
        pool = {k: boards[k] for k in VOTER_POOL if k in boards}
        pool[key] = board
        pct = {}
        for k, b in pool.items():
            mine = [i for i in b.entries if i in idents]
            if len(mine) >= sweep.MIN_PAIR_OVERLAP:
                pct[k] = sweep.to_percentiles(sweep.ordering(b, mine))
        rows = []
        members = list(pct)
        for other in members:
            if other == key or key not in pct:
                continue
            rho, n = sweep.spearman(pct[key], pct[other])
            res, n_res = sweep.leave_pair_out_residuals(pct, key, other, members)
            rows.append(
                {
                    "a": key,
                    "b": other,
                    "spearman": _r(rho),
                    "n": n,
                    "leavePairOutResidual": _r(res),
                    "nResidual": n_res,
                }
            )
        out["families"][fam] = {
            "source": key,
            "boardRows": board.rows,
            "onBoardFamilyIdentities": sum(1 for i in board.entries if i in idents),
            "duplicateIdentities": len(board.duplicates),
            "pairs": rows,
        }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--payload", type=Path, default=REPO / "exports/latest/dynasty_data_2026-10-18.json"
    )
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument(
        "--archive-manifest",
        type=Path,
        default=None,
        help="write only the frozen archive manifest to this path and exit",
    )
    ap.add_argument(
        "--signals-dependence-only",
        action="store_true",
        help=(
            "ON THE PRODUCTION BOX: print only the aggregate Signals IDP pairwise "
            "dependence (owner Decision 7) and exit"
        ),
    )
    args = ap.parse_args(argv)
    if args.signals_dependence_only:
        if not args.payload.is_file():
            print(f"payload missing: {args.payload}", file=sys.stderr)
            return 2
        raw = json.loads(args.payload.read_text(encoding="utf-8"))
        result = {
            "schema": "idp-rehab-eval/signals-dependence/v1",
            "payload": args.payload.name,
            "codeRevision": vr.pins(args.payload.resolve())["codeRevision"],
            "signalsIdpDependence": signals_dependence(vr.build(raw)),
        }
        text = json.dumps(result, indent=1, default=str)
        if args.out:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            args.out.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0
    if args.archive_manifest:
        args.archive_manifest.parent.mkdir(parents=True, exist_ok=True)
        args.archive_manifest.write_text(
            json.dumps(archive_manifest(), indent=1) + "\n", encoding="utf-8"
        )
        return 0
    if not args.payload.is_file():
        print(f"payload missing: {args.payload}", file=sys.stderr)
        return 2
    raw = json.loads(args.payload.read_text(encoding="utf-8"))
    pins = vr.pins(args.payload.resolve())
    base = vr.build(raw)
    alt = vr.build(raw, {"kind": "feature_flag", "flag": ("dlf_offense_only_vote", False)})
    alt_nofilter = vr.build(
        raw,
        {
            "kind": "diagnostic_patch",
            "flag": ("dlf_offense_only_vote", False),
            "patch": ("_hampel_filter_per_player", vr._no_hampel),
        },
    )
    base_nofilter = vr.build(
        raw, {"kind": "diagnostic_patch", "patch": ("_hampel_filter_per_player", vr._no_hampel)}
    )
    report = {
        "schema": "idp-rehab-eval/v1",
        "pins": {
            "codeRevision": pins["codeRevision"],
            "workingTreeDirty": pins["workingTreeDirty"],
            "payload": pins["payload"],
            "idpSourceCsvs": {
                k: pins["sourceCsvs"].get(f"{k}.csv") for k in (*IDP_SOURCES, "dlfSf")
            },
            "flags": {
                k: pins["flags"].get(k)
                for k in (
                    "dlf_offense_only_vote",
                    "source_freshness_weighting",
                    "source_family_cap",
                )
            },
            "hampel": pins["hampel"],
            "contractVersion": pins["contractVersion"],
            "boardHashHoldInForce": vr.board_hash(base),
            "boardHashHoldOff": vr.board_hash(alt),
        },
        "dlfIdpCounterfactual": dlf_counterfactual(base, alt),
        "outlierFilterOnIdpRows": {
            "holdInForce": filter_census(base),
            "holdOff": filter_census(alt),
            "holdInForceFilterOffIdpIdentical": all(
                (_idp_rows(base_nofilter).get(n) or {}).get("rankDerivedValue")
                == r.get("rankDerivedValue")
                for n, r in _idp_rows(base).items()
            ),
        },
        "dlfReversalDecomposition": decomposition(base, alt, alt_nofilter),
        "independence": independence(base, alt),
        "normalization": normalization(alt),
        "dlfValuesPublicationHistory": dlf_values_publication_history(),
    }
    text = json.dumps(report, indent=1, sort_keys=False, default=str)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
